<?php
/**
 * API local do Gerador de FDS (versão PHP)
 * ==========================================
 *
 * Porte 1:1 de api_local.py. Roda com o servidor embutido do PHP:
 *
 *     php -S localhost:5000 index.php
 *
 * -> abre em http://localhost:5000 (a própria tela é servida daqui, em
 *    "/", para evitar problemas de CORS/arquivo local).
 *
 * Este arquivo é só a camada de integração (HTTP + validação de
 * entrada). Toda a lógica de classificação já está implementada e
 * testada separadamente em MotorToxicidadeAguda.php,
 * MotorCorrosaoIrritacao.php e BancoSubstancias.php — este arquivo não
 * reimplementa nenhuma regra da norma, só orquestra chamadas a esses
 * módulos.
 */

declare(strict_types=1);

require_once __DIR__ . "/MotorToxicidadeAguda.php";
require_once __DIR__ . "/MotorCorrosaoIrritacao.php";
require_once __DIR__ . "/BancoSubstancias.php";
require_once __DIR__ . "/GeradorFds.php";
require_once __DIR__ . "/PerfisEmpresa.php";

$caminhoDb = getenv("FDS_DB_PATH") ?: (__DIR__ . "/substancias.db");
$repoPerfis = new RepositorioPerfisEmpresa();

// CORS amplo: a tela pode estar publicada em outra origem (ex.: claude.ai)
// e rodar no navegador do usuário, que então chama este servidor local —
// isso é seguro porque o servidor só escuta em localhost, então só o
// próprio computador do usuário consegue alcançá-lo.
header("Access-Control-Allow-Origin: *");
header("Access-Control-Allow-Headers: Content-Type");
header("Access-Control-Allow-Methods: GET, POST, OPTIONS");

$metodo = $_SERVER["REQUEST_METHOD"];
$caminho = parse_url($_SERVER["REQUEST_URI"], PHP_URL_PATH) ?? "/";

if ($caminho === "/" && $metodo === "GET") {
    $arquivoHtml = __DIR__ . "/gerador-fds.html";
    if (!file_exists($arquivoHtml)) {
        http_response_code(404);
        echo "gerador-fds.html não encontrado em " . __DIR__;
        exit;
    }
    header("Content-Type: text/html; charset=utf-8");
    readfile($arquivoHtml);
    exit;
}

/**
 * Validação de entrada compartilhada por /api/classificar e
 * /api/gerar_fds (mesmo papel de _validar_entrada em api_local.py).
 * Retorna [nomeProduto, estadoFisico, formula, somaConcentracoes, erros].
 */
function validarEntrada(array $dados): array
{
    $nomeProduto = trim((string) ($dados["nome_produto"] ?? ""));
    $estadoFisico = $dados["estado_fisico"] ?? null;
    $composicao = $dados["composicao"] ?? [];

    $errosValidacao = [];
    if ($nomeProduto === "") {
        $errosValidacao[] = "Nome do produto é obrigatório.";
    }
    if (!in_array($estadoFisico, ["liquido", "solido_pulverulento"], true)) {
        $errosValidacao[] = 'estado_fisico deve ser "liquido" ou "solido_pulverulento".';
    }
    if (empty($composicao)) {
        $errosValidacao[] = "A composição da mistura não pode estar vazia.";
    }

    $formula = [];
    $somaConcentracoes = 0.0;
    foreach ($composicao as $i => $item) {
        $nome = trim((string) ($item["nome"] ?? ""));
        $cas = trim((string) ($item["cas"] ?? ""));
        $concentracaoRaw = $item["concentracao"] ?? null;

        if (!is_numeric($concentracaoRaw)) {
            $errosValidacao[] = "Linha " . ($i + 1) . ": concentração inválida.";
            continue;
        }
        $concentracao = (float) $concentracaoRaw;

        if ($nome === "") {
            $errosValidacao[] = "Linha " . ($i + 1) . ": nome da substância é obrigatório.";
            continue;
        }
        if ($cas === "") {
            $errosValidacao[] = "Linha " . ($i + 1) . " ('$nome'): Nº CAS é obrigatório — o motor busca a " .
                "classificação de perigo pelo CAS, sem ele a substância não pode ser avaliada.";
            continue;
        }

        $formula[] = [
            "nome" => $nome,
            "cas" => $cas,
            "concentracao" => $concentracao,
            "segredo_industrial" => (bool) ($item["segredo_industrial"] ?? false),
        ];
        $somaConcentracoes += $concentracao;
    }

    if (empty($errosValidacao) && abs($somaConcentracoes - 100.0) > 0.5) {
        $errosValidacao[] = sprintf(
            "A soma das concentrações é %.2f%%, não 100%%. Corrija a fórmula antes de calcular a classificação.",
            $somaConcentracoes
        );
    }

    return [$nomeProduto, $estadoFisico, $formula, $somaConcentracoes, $errosValidacao];
}

/**
 * Roda os dois motores de cálculo sobre a fórmula já validada — mesmo
 * papel de _calcular_classificacao em api_local.py.
 */
function calcularClassificacao(BancoSubstancias $banco, array $formula, string $estadoFisico): array
{
    [$ingredientesToxicidade, $avisosToxicidade] = $banco->montarIngredientesPorVia($formula, $estadoFisico);
    $resultadoToxicidadeAguda = classificar_todas_as_vias($ingredientesToxicidade);

    [$ingredientesPeleOlhos, $avisosPeleOlhos] = $banco->montarIngredientesPeleOlhos($formula);
    $resultadoPele = classificar_corrosao_irritacao_pele($ingredientesPeleOlhos);
    $resultadoOlhos = classificar_lesao_ocular($ingredientesPeleOlhos);

    return [$resultadoToxicidadeAguda, $resultadoPele, $resultadoOlhos, array_merge($avisosToxicidade, $avisosPeleOlhos)];
}

function algumErroMenciona100(array $erros): bool
{
    foreach ($erros as $e) {
        if (str_contains($e, "100%")) return true;
    }
    return false;
}

if ($caminho === "/api/classificar") {
    if ($metodo === "OPTIONS") {
        http_response_code(204);
        exit;
    }
    if ($metodo !== "POST") {
        http_response_code(405);
        header("Content-Type: application/json; charset=utf-8");
        echo json_encode(["erro" => "Método não permitido."]);
        exit;
    }

    header("Content-Type: application/json; charset=utf-8");

    $corpo = file_get_contents("php://input");
    $dados = json_decode($corpo, true);
    if (!is_array($dados)) {
        http_response_code(400);
        echo json_encode(["erro" => "Corpo da requisição ausente ou não é JSON válido."], JSON_UNESCAPED_UNICODE);
        exit;
    }

    [$nomeProduto, $estadoFisico, $formula, $somaConcentracoes, $errosValidacao] = validarEntrada($dados);
    if (!empty($errosValidacao)) {
        http_response_code(400);
        $erroPrincipal = algumErroMenciona100($errosValidacao) ? "Fórmula não fecha em 100%." : "Dados de entrada inválidos.";
        echo json_encode(["erro" => $erroPrincipal, "detalhes" => $errosValidacao], JSON_UNESCAPED_UNICODE);
        exit;
    }

    $banco = new BancoSubstancias($caminhoDb);
    [$resultadoToxicidadeAguda, $resultadoPele, $resultadoOlhos, $avisos] = calcularClassificacao($banco, $formula, $estadoFisico);
    $banco->close();

    echo json_encode([
        "produto" => $nomeProduto,
        "soma_concentracoes" => round($somaConcentracoes, 2),
        "toxicidade_aguda" => $resultadoToxicidadeAguda,
        "corrosao_irritacao_pele" => $resultadoPele,
        "lesao_ocular" => $resultadoOlhos,
        "avisos" => $avisos,
    ], JSON_UNESCAPED_UNICODE | JSON_UNESCAPED_SLASHES);
    exit;
}

if ($caminho === "/api/gerar_fds") {
    if ($metodo === "OPTIONS") {
        http_response_code(204);
        exit;
    }
    if ($metodo !== "POST") {
        http_response_code(405);
        header("Content-Type: application/json; charset=utf-8");
        echo json_encode(["erro" => "Método não permitido."]);
        exit;
    }

    $corpo = file_get_contents("php://input");
    $dados = json_decode($corpo, true);
    if (!is_array($dados)) {
        header("Content-Type: application/json; charset=utf-8");
        http_response_code(400);
        echo json_encode(["erro" => "Corpo da requisição ausente ou não é JSON válido."], JSON_UNESCAPED_UNICODE);
        exit;
    }

    [$nomeProduto, $estadoFisico, $formula, $somaConcentracoes, $errosValidacao] = validarEntrada($dados);
    if (!empty($errosValidacao)) {
        header("Content-Type: application/json; charset=utf-8");
        http_response_code(400);
        $erroPrincipal = algumErroMenciona100($errosValidacao) ? "Fórmula não fecha em 100%." : "Dados de entrada inválidos.";
        echo json_encode(["erro" => $erroPrincipal, "detalhes" => $errosValidacao], JSON_UNESCAPED_UNICODE);
        exit;
    }

    $perfilEmpresa = $dados["perfil_empresa"] ?? [];
    $perfilEmpresaId = $dados["perfil_empresa_id"] ?? null;
    if ($perfilEmpresaId) {
        $perfilSalvo = $repoPerfis->obter($perfilEmpresaId);
        if ($perfilSalvo === null) {
            header("Content-Type: application/json; charset=utf-8");
            http_response_code(400);
            echo json_encode(["erro" => "Dados de entrada inválidos.", "detalhes" => ["Perfil de empresa '$perfilEmpresaId' não encontrado."]], JSON_UNESCAPED_UNICODE);
            exit;
        }
        $perfilEmpresa = $perfilSalvo;
    }

    $produtoInfo = (array) ($dados["produto_info"] ?? []);
    $produtoInfo["nome_produto"] = $nomeProduto;
    $camposExtras = (array) ($dados["campos_extras"] ?? []);
    $numeroRevisao = (string) ($dados["numero_revisao"] ?? "01");

    $banco = new BancoSubstancias($caminhoDb);
    [$resultadoToxicidadeAguda, $resultadoPele, $resultadoOlhos, $avisos] = calcularClassificacao($banco, $formula, $estadoFisico);

    $dadosFds = montarDadosFds(
        perfilEmpresa: $perfilEmpresa,
        produtoInfo: $produtoInfo,
        composicao: $formula,
        estadoFisico: $estadoFisico,
        resultadoToxicidadeAguda: $resultadoToxicidadeAguda,
        resultadoPele: $resultadoPele,
        resultadoOlhos: $resultadoOlhos,
        banco: $banco,
        camposExtras: $camposExtras,
        numeroRevisao: $numeroRevisao,
    );
    $banco->close();

    $caminhoTemp = tempnam(sys_get_temp_dir(), "fds_") . ".pdf";
    try {
        gerarPdfFds($dadosFds, $caminhoTemp);
    } catch (\Throwable $e) {
        header("Content-Type: application/json; charset=utf-8");
        http_response_code(500);
        echo json_encode([
            "erro" => "Não foi possível gerar o PDF.",
            "detalhes" => [$e->getMessage() . " — verifique se rodou 'composer install' na pasta php/ (dependência dompdf/dompdf)."],
        ], JSON_UNESCAPED_UNICODE);
        @unlink($caminhoTemp);
        exit;
    }

    $nomeArquivo = "FDS_" . preg_replace('/[^\w-]+/u', '_', trim($nomeProduto)) . ".pdf";
    header("Content-Type: application/pdf");
    header("Content-Disposition: attachment; filename=\"" . addslashes($nomeArquivo) . "\"");
    header("Content-Length: " . filesize($caminhoTemp));
    readfile($caminhoTemp);
    @unlink($caminhoTemp);
    exit;
}

if (str_starts_with($caminho, "/api/perfis")) {
    header("Content-Type: application/json; charset=utf-8");

    if ($metodo === "OPTIONS") {
        http_response_code(204);
        exit;
    }

    $partes = array_values(array_filter(explode("/", $caminho)));
    // $partes = ["api", "perfis"] ou ["api", "perfis", "<id>"]
    $perfilId = $partes[2] ?? null;

    if ($perfilId === null) {
        if ($metodo === "GET") {
            echo json_encode($repoPerfis->listar(), JSON_UNESCAPED_UNICODE);
            exit;
        }
        if ($metodo === "POST") {
            $dados = json_decode(file_get_contents("php://input"), true) ?: [];
            try {
                $perfil = $repoPerfis->salvar($dados);
            } catch (\InvalidArgumentException $e) {
                http_response_code(400);
                echo json_encode(["erro" => "Dados de entrada inválidos.", "detalhes" => [$e->getMessage()]], JSON_UNESCAPED_UNICODE);
                exit;
            }
            http_response_code(201);
            echo json_encode($perfil, JSON_UNESCAPED_UNICODE);
            exit;
        }
        http_response_code(405);
        echo json_encode(["erro" => "Método não permitido."]);
        exit;
    }

    if ($metodo === "GET") {
        $perfil = $repoPerfis->obter($perfilId);
        if ($perfil === null) {
            http_response_code(404);
            echo json_encode(["erro" => "Perfil não encontrado."], JSON_UNESCAPED_UNICODE);
            exit;
        }
        echo json_encode($perfil, JSON_UNESCAPED_UNICODE);
        exit;
    }

    if ($metodo === "PUT") {
        if ($repoPerfis->obter($perfilId) === null) {
            http_response_code(404);
            echo json_encode(["erro" => "Perfil não encontrado."], JSON_UNESCAPED_UNICODE);
            exit;
        }
        $dados = json_decode(file_get_contents("php://input"), true) ?: [];
        try {
            $perfil = $repoPerfis->salvar($dados, $perfilId);
        } catch (\InvalidArgumentException $e) {
            http_response_code(400);
            echo json_encode(["erro" => "Dados de entrada inválidos.", "detalhes" => [$e->getMessage()]], JSON_UNESCAPED_UNICODE);
            exit;
        }
        echo json_encode($perfil, JSON_UNESCAPED_UNICODE);
        exit;
    }

    if ($metodo === "DELETE") {
        if ($repoPerfis->excluir($perfilId)) {
            http_response_code(204);
            exit;
        }
        http_response_code(404);
        echo json_encode(["erro" => "Perfil não encontrado."], JSON_UNESCAPED_UNICODE);
        exit;
    }

    http_response_code(405);
    echo json_encode(["erro" => "Método não permitido."]);
    exit;
}

http_response_code(404);
header("Content-Type: application/json; charset=utf-8");
echo json_encode(["erro" => "Rota não encontrada: $caminho"], JSON_UNESCAPED_UNICODE);
