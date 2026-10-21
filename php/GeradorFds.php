<?php
/**
 * Gerador de FDS completa (16 seções, ABNT NBR 14725:2023) — geração de PDF
 * ===========================================================================
 *
 * Porte 1:1 de gerador_fds.py — ver o docstring daquele arquivo para o
 * raciocínio completo (escopo, limitações assumidas, frases padrão nunca
 * inventando dado de ensaio). Este arquivo espelha exatamente a mesma
 * lógica de derivação de rótulo GHS e montagem das 16 seções; a única
 * diferença real é a camada de renderização do PDF, que aqui usa
 * dompdf/dompdf (HTML -> PDF) em vez do reportlab/Platypus do lado Python
 * — a saída visual é a mesma (duas colunas rótulo/valor, barra cinza de
 * título de seção, estilo Fosfeed/Safeeds), só o motor de renderização
 * muda.
 */

declare(strict_types=1);

$_CAMINHO_DADOS = dirname(__DIR__) . "/dados_fds.json";
$_DADOS_FDS = json_decode(file_get_contents($_CAMINHO_DADOS), true);

const _CATEGORIAS_CAVEIRA = [1, 2, 3];
const _CATEGORIAS_EXCLAMACAO_TOX = [4];
const _SUBCATEGORIAS_PELE_CORROSIVAS = ["1A", "1B", "1C", "1"];
const _SUBCATEGORIAS_PELE_IRRITANTES = ["2", "3"];
const _SUBCATEGORIAS_OLHOS_GRAVES = ["1"];
const _SUBCATEGORIAS_OLHOS_IRRITANTES = ["2A", "2B", "2"];

const _NOMES_PICTOGRAMA = [
    "corrosao" => "Corrosão (GHS05)",
    "exclamacao" => "Ponto de exclamação (GHS07)",
    "caveira" => "Caveira e ossos cruzados (GHS06)",
];

const _NOMES_VIA_TOXICIDADE = [
    "oral" => "Via oral",
    "dermica" => "Via dérmica",
    "inalatoria_gases" => "Via inalatória (gases)",
    "inalatoria_vapores" => "Via inalatória (vapores)",
    "inalatoria_poeiras_nevoas" => "Via inalatória (poeiras/névoas)",
];

const LEGENDA_PADRAO = [
    "ABNT" => "Associação Brasileira de Normas Técnicas",
    "CAS" => "Chemical Abstracts Service",
    "DL50" => "Dose Letal 50%",
    "CL50" => "Concentração Letal 50%",
    "EPI" => "Equipamento de Proteção Individual",
    "ETA" => "Estimativa de Toxicidade Aguda",
    "FDS" => "Ficha de Dados de Segurança",
    "GHS" => "Sistema Globalmente Harmonizado de Classificação e Rotulagem de Produtos Químicos",
    "NBR" => "Norma Brasileira",
    "NR" => "Norma Regulamentadora",
    "ONU" => "Organização das Nações Unidas",
    "STOT" => "Toxicidade para Órgãos-alvo Específicos",
];

function _viaParaChaveH(string $via): string
{
    if ($via === "oral") return "toxicidade_oral";
    if ($via === "dermica") return "toxicidade_dermica";
    return "toxicidade_inalatoria";
}

/**
 * Deriva pictogramas, palavra de advertência e frases H/P a partir dos
 * resultados JÁ CALCULADOS pelos motores — mesma regra de precedência de
 * pictogramas e mesmo agrupamento de códigos P do lado Python (ver
 * derivar_rotulo_ghs em gerador_fds.py).
 */
function derivarRotuloGhs(array $resultadoToxicidadeAguda, ?array $resultadoPele, ?array $resultadoOlhos): array
{
    global $_DADOS_FDS;
    $hCodes = $_DADOS_FDS["h_codes"];
    $pCodes = $_DADOS_FDS["p_codes"];
    $mapaCategoriaH = $_DADOS_FDS["mapa_categoria_h"];
    $mapaHParaP = $_DADOS_FDS["mapa_h_para_p"];

    $codigosH = [];
    $categoriasAgudas = [];

    foreach ($resultadoToxicidadeAguda as $via => $resultado) {
        $categoria = $resultado["categoria"] ?? null;
        if ($categoria === null) continue;
        $chave = _viaParaChaveH($via);
        $h = $mapaCategoriaH[$chave][(string) $categoria] ?? null;
        if ($h && !in_array($h, $codigosH, true)) $codigosH[] = $h;
        $categoriasAgudas[$via] = $categoria;
    }

    $categoriaPele = $resultadoPele["categoria"] ?? null;
    if ($categoriaPele) {
        $h = $mapaCategoriaH["pele"][$categoriaPele] ?? null;
        if ($h && !in_array($h, $codigosH, true)) $codigosH[] = $h;
    }

    $categoriaOlhos = $resultadoOlhos["categoria"] ?? null;
    if ($categoriaOlhos) {
        $h = $mapaCategoriaH["olhos"][$categoriaOlhos] ?? null;
        if ($h && !in_array($h, $codigosH, true)) $codigosH[] = $h;
    }

    $temCaveira = false;
    foreach ($categoriasAgudas as $c) {
        if (in_array($c, _CATEGORIAS_CAVEIRA, true)) { $temCaveira = true; break; }
    }
    $temExclamacaoTox = false;
    if (!$temCaveira) {
        foreach ($categoriasAgudas as $c) {
            if (in_array($c, _CATEGORIAS_EXCLAMACAO_TOX, true)) { $temExclamacaoTox = true; break; }
        }
    }
    $temCorrosao = in_array($categoriaPele, _SUBCATEGORIAS_PELE_CORROSIVAS, true)
        || in_array($categoriaOlhos, _SUBCATEGORIAS_OLHOS_GRAVES, true);
    $temExclamacaoPeleOlhos = in_array($categoriaPele, _SUBCATEGORIAS_PELE_IRRITANTES, true)
        || in_array($categoriaOlhos, _SUBCATEGORIAS_OLHOS_IRRITANTES, true);

    $pictogramas = [];
    if ($temCorrosao) $pictogramas[] = "corrosao";
    if ($temExclamacaoTox || $temExclamacaoPeleOlhos) $pictogramas[] = "exclamacao";
    if ($temCaveira) $pictogramas[] = "caveira";

    if ($temCaveira || $temCorrosao) {
        $palavraAdvertencia = "PERIGO";
    } elseif ($temExclamacaoTox || $temExclamacaoPeleOlhos) {
        $palavraAdvertencia = "ATENÇÃO";
    } else {
        $palavraAdvertencia = null;
    }

    $codigosP = [];
    foreach ($codigosH as $h) {
        foreach (($mapaHParaP[$h] ?? []) as $p) {
            if (!in_array($p, $codigosP, true)) $codigosP[] = $p;
        }
    }
    if (!empty($codigosH)) {
        $gerais = ["P101", "P102", "P103"];
        $resto = array_values(array_filter($codigosP, fn($p) => !in_array($p, $gerais, true)));
        $codigosP = array_merge($gerais, $resto);
    }

    $grupo = function (string $pCode): string {
        $primeiro = explode("+", $pCode)[0];
        $numero = (int) substr($primeiro, 1, 3);
        if ($numero < 200) return "Geral";
        if ($numero < 300) return "Prevenção";
        if ($numero < 400) return "Resposta";
        if ($numero < 500) return "Armazenamento";
        return "Disposição";
    };

    $pPorGrupo = ["Geral" => [], "Prevenção" => [], "Resposta" => [], "Armazenamento" => [], "Disposição" => []];
    foreach ($codigosP as $p) {
        $pPorGrupo[$grupo($p)][] = ["codigo" => $p, "descricao" => $pCodes[$p] ?? ""];
    }

    return [
        "codigos_h" => array_map(fn($h) => ["codigo" => $h, "descricao" => $hCodes[$h] ?? ""], $codigosH),
        "codigos_p_por_grupo" => $pPorGrupo,
        "pictogramas" => $pictogramas,
        "palavra_advertencia" => $palavraAdvertencia,
        "flags" => [
            "corrosivo" => $temCorrosao,
            "irritante" => (!$temCorrosao) && $temExclamacaoPeleOlhos,
            "toxico_agudo" => !empty($categoriasAgudas),
            "caveira" => $temCaveira,
        ],
    ];
}

/**
 * Classificação INTRÍNSECA de uma matéria-prima (Seção 3), buscando
 * direto no banco (mesma lógica de obter_h_codes_substancia em Python).
 */
function obterHCodesSubstancia(BancoSubstancias $banco, string $cas): array
{
    global $_DADOS_FDS;
    $mapaCategoriaH = $_DADOS_FDS["mapa_categoria_h"];
    $codigos = [];

    $stmt = $banco->conn->prepare("SELECT via, categoria FROM toxicidade_aguda WHERE cas = ? AND categoria IS NOT NULL");
    $stmt->execute([$cas]);
    $melhorPorVia = [];
    foreach ($stmt->fetchAll(PDO::FETCH_NUM) as [$viaStr, $categoria]) {
        $categoria = (int) $categoria;
        if (!isset($melhorPorVia[$viaStr]) || $categoria < $melhorPorVia[$viaStr]) {
            $melhorPorVia[$viaStr] = $categoria;
        }
    }
    foreach ($melhorPorVia as $viaStr => $categoria) {
        $chave = _viaParaChaveH($viaStr);
        $h = $mapaCategoriaH[$chave][(string) $categoria] ?? null;
        if ($h && !in_array($h, $codigos, true)) $codigos[] = $h;
    }

    $stmt = $banco->conn->prepare("SELECT categoria_pele, categoria_olhos FROM pele_olhos WHERE cas = ?");
    $stmt->execute([$cas]);
    $linhas = $stmt->fetchAll(PDO::FETCH_NUM);
    $ordemPele = ["1A", "1B", "1C", "1", "2", "3"];
    $ordemOlhos = ["1", "2A", "2B", "2"];
    $catsPele = array_values(array_filter(array_column($linhas, 0)));
    $catsOlhos = array_values(array_filter(array_column($linhas, 1)));

    if (!empty($catsPele)) {
        usort($catsPele, fn($a, $b) => (array_search($a, $ordemPele) ?: 99) <=> (array_search($b, $ordemPele) ?: 99));
        $h = $mapaCategoriaH["pele"][$catsPele[0]] ?? null;
        if ($h && !in_array($h, $codigos, true)) $codigos[] = $h;
    }
    if (!empty($catsOlhos)) {
        usort($catsOlhos, fn($a, $b) => (array_search($a, $ordemOlhos) ?: 99) <=> (array_search($b, $ordemOlhos) ?: 99));
        $h = $mapaCategoriaH["olhos"][$catsOlhos[0]] ?? null;
        if ($h && !in_array($h, $codigos, true)) $codigos[] = $h;
    }

    return $codigos;
}

// ---------------------------------------------------------------------------
// Frases padrão — mesmos textos/regras de gerador_fds.py, parametrizadas
// por $flags (severidade calculada) e $extras (overrides opcionais do
// usuário). Nunca inventam dado de ensaio: usam "Não disponível" quando
// não há informação calculada nem informada.
// ---------------------------------------------------------------------------

function frasesPrimeirosSocorros(array $flags): array
{
    if ($flags["corrosivo"]) {
        return [
            "inalacao" => "Remova a pessoa para um local ventilado. Se a respiração estiver irregular ou parar, procure atendimento médico imediatamente.",
            "contato_pele" => "Retire imediatamente a roupa contaminada. Lave a pele com água em abundância por no mínimo 15 minutos. Procure atendimento médico IMEDIATAMENTE.",
            "contato_olhos" => "Enxágue imediatamente os olhos com água corrente durante pelo menos 15 minutos, mantendo as pálpebras bem abertas. Remova lentes de contato, se presentes e fácil de fazer. Consulte um oftalmologista IMEDIATAMENTE.",
            "ingestao" => "NÃO provoque vômito. Enxágue a boca com água. Nunca administre nada por via oral a uma pessoa inconsciente. Consulte um médico IMEDIATAMENTE.",
            "sintomas" => "O contato com a pele e os olhos pode provocar queimaduras/lesões graves. A inalação ou ingestão pode causar irritação e danos ao trato respiratório/gastrointestinal.",
            "notas_medico" => "Tratamento sintomático. Considerar o caráter corrosivo do produto antes de procedimentos como lavagem gástrica. Não há antídoto específico conhecido.",
        ];
    }
    if ($flags["irritante"]) {
        return [
            "inalacao" => "Remova a pessoa para um local ventilado. Em caso de desconforto persistente, procure atendimento médico.",
            "contato_pele" => "Lave a pele com água e sabão em abundância. Em caso de irritação persistente, procure atendimento médico.",
            "contato_olhos" => "Enxágue cuidadosamente com água durante vários minutos. Remova lentes de contato, se presentes e fácil de fazer. Se a irritação ocular persistir, consulte um médico.",
            "ingestao" => "Enxágue a boca com água. Procure atendimento médico se sentir indisposição.",
            "sintomas" => "Pode provocar irritação da pele, dos olhos e das vias respiratórias.",
            "notas_medico" => "Tratamento sintomático. Não há antídoto específico conhecido.",
        ];
    }
    return [
        "inalacao" => "Remova a pessoa para um local ventilado. Procure atendimento médico se os sintomas persistirem.",
        "contato_pele" => "Lave a pele com água em abundância.",
        "contato_olhos" => "Enxágue os olhos com água em abundância. Procure atendimento médico se a irritação persistir.",
        "ingestao" => "Enxágue a boca com água. Procure atendimento médico se sentir indisposição.",
        "sintomas" => "Não são esperados efeitos adversos significativos nas condições normais de uso.",
        "notas_medico" => "Tratamento sintomático, conforme quadro clínico apresentado.",
    ];
}

function frasesCombateIncendio(array $flags, array $extras): array
{
    return [
        "meios_apropriados" => $extras["meios_extincao_apropriados"]
            ?? "Água pulverizada/nebulizada, pó químico seco, espuma resistente ao álcool ou dióxido de carbono (CO2). Selecionar o meio de extinção conforme o material envolvido no entorno do incêndio.",
        "meios_nao_apropriados" => $extras["meios_extincao_inadequados"]
            ?? "Não utilizar jato de água direto e pressurizado, que pode espalhar o produto.",
        "perigos_especificos" => $extras["perigos_incendio"]
            ?? (($flags["corrosivo"] || $flags["irritante"])
                ? "A decomposição térmica pode liberar gases/vapores irritantes ou tóxicos."
                : "Não são esperados perigos específicos de combustão além dos comuns a incêndios."),
        "medidas_bombeiros" => "Utilizar equipamento de respiração autônoma com pressão positiva e vestuário de proteção química completo. Resfriar os recipientes expostos ao fogo, se seguro fazê-lo.",
    ];
}

function frasesVazamento(array $flags): array
{
    $protecao = ($flags["corrosivo"] || $flags["irritante"])
        ? "roupa de proteção individual completa, conforme indicado na Seção 8"
        : "equipamento de proteção individual básico";
    return [
        "precaucoes_pessoais_nao_emergencial" => "Evitar contato com o produto derramado. Usar {$protecao}. Garantir ventilação adequada do local.",
        "precaucoes_pessoais_emergencia" => "Isolar a área do vazamento. Utilizar equipamento de proteção individual completo, conforme descrito na Seção 8.",
        "precaucoes_ambientais" => "Não permitir que o produto atinja canalizações, esgotos, águas subterrâneas ou cursos d'água. Em caso de contaminação significativa, notificar as autoridades competentes locais.",
        "metodos_contencao" => "Conter o derramamento com materiais absorventes inertes (areia, terra, diatomito, ou outro material inerte compatível) ou diques, conforme o volume.",
        "metodos_limpeza" => "Recolher o material derramado com auxílio de utensílios adequados e transferir para recipientes apropriados para descarte conforme a Seção 13. Lavar a área com água em abundância após a remoção do produto.",
    ];
}

function frasesManuseioArmazenamento(array $flags, array $extras, string $estadoFisico): array
{
    $forma = $estadoFisico === "liquido" ? "vapores/névoas" : "poeiras";
    return [
        "manuseio_seguro" => $extras["manuseio_seguro"]
            ?? "Manusear em área com ventilação adequada. Evitar contato com a pele, os olhos e a roupa. Não inalar {$forma} do produto. Utilizar o equipamento de proteção individual indicado na Seção 8.",
        "medidas_higiene" => "Proibido comer, beber ou fumar na área de trabalho. Remover imediatamente o vestuário contaminado. Lavar as mãos e o rosto cuidadosamente após o manuseio.",
        "condicoes_armazenamento" => $extras["condicoes_armazenamento"]
            ?? "Conservar em local fresco, seco e bem ventilado, em recipientes bem fechados, ao abrigo de luz solar direta.",
        "materiais_incompativeis" => $extras["materiais_incompativeis"]
            ?? ($flags["corrosivo"] ? "Agentes oxidantes fortes e bases fortes." : "Nenhum conhecido nas condições normais de uso."),
    ];
}

function frasesEpi(array $flags, array $extras): array
{
    if ($flags["corrosivo"]) {
        return [
            "protecao_olhos" => $extras["epi_olhos"] ?? "Óculos de segurança de ampla visão contra respingos químicos e/ou protetor facial completo.",
            "protecao_pele" => $extras["epi_pele"] ?? "Vestuário de proteção química resistente ao produto (avental ou macacão).",
            "protecao_maos" => $extras["epi_maos"] ?? "Luvas de proteção impermeáveis e resistentes ao produto.",
            "protecao_respiratoria" => $extras["epi_respiratoria"] ?? "Em ambientes com ventilação insuficiente, utilizar respirador com filtro adequado ao produto.",
            "controles_engenharia" => "Assegurar ventilação adequada. Disponibilizar chuveiro de emergência e lava-olhos no local de trabalho.",
        ];
    }
    return [
        "protecao_olhos" => $extras["epi_olhos"] ?? "Óculos de segurança.",
        "protecao_pele" => $extras["epi_pele"] ?? "Vestuário de proteção conforme a atividade.",
        "protecao_maos" => $extras["epi_maos"] ?? "Luvas de proteção adequadas ao manuseio.",
        "protecao_respiratoria" => $extras["epi_respiratoria"] ?? "Não são necessárias medidas especiais nas condições normais de uso; avaliar conforme ventilação do local.",
        "controles_engenharia" => "Assegurar ventilação adequada do local de trabalho.",
    ];
}

function frasesEstabilidadeReatividade(array $flags, array $extras): array
{
    return [
        "reatividade" => $extras["reatividade"] ?? ($flags["corrosivo"] ? "Produto de caráter corrosivo. Pode reagir com agentes oxidantes fortes e bases fortes." : "Não são esperadas reações perigosas nas condições normais de uso."),
        "estabilidade_quimica" => "Estável sob condições normais de uso, manuseio e armazenamento recomendadas.",
        "reacoes_perigosas" => $extras["reacoes_perigosas"] ?? ($flags["corrosivo"] ? "Pode reagir com materiais incompatíveis listados na Seção 10, com liberação de calor e/ou gases." : "Não são conhecidas reações perigosas nas condições normais de uso."),
        "condicoes_evitar" => "Temperaturas elevadas, fontes de ignição e contato com materiais incompatíveis.",
        "materiais_incompativeis" => $extras["materiais_incompativeis"] ?? ($flags["corrosivo"] ? "Agentes oxidantes fortes, bases fortes." : "Nenhum conhecido nas condições normais de uso."),
        "produtos_decomposicao" => $extras["produtos_decomposicao"] ?? "Não disponível.",
    ];
}

function frasesEcologicas(array $extras): array
{
    return [
        "ecotoxicidade" => $extras["ecotoxicidade"] ?? "Não disponível.",
        "persistencia_degradabilidade" => $extras["persistencia"] ?? "Não disponível.",
        "potencial_bioacumulacao" => $extras["bioacumulacao"] ?? "Não disponível.",
        "mobilidade_solo" => $extras["mobilidade_solo"] ?? "Não disponível.",
        "outros_efeitos" => $extras["outros_efeitos_ecologicos"] ?? "Não disponível.",
    ];
}

function frasesDestinacaoFinal(array $extras): array
{
    return [
        "residuos_produto" => $extras["destinacao_residuos"]
            ?? "Descartar conforme a regulamentação local, estadual e federal aplicável (incluindo a Lei nº 12.305/2010 - Política Nacional de Resíduos Sólidos). Não descartar em esgotos, cursos d'água ou solo.",
        "embalagens" => $extras["destinacao_embalagens"]
            ?? "Não reutilizar embalagens vazias para outros fins. Descartar conforme a regulamentação aplicável a resíduos perigosos, ou encaminhar a empresas especializadas em descontaminação.",
    ];
}

function frasesRegulamentacoes(array $extras): array
{
    $base = [
        "ABNT NBR 14725:2023 - Produtos químicos — Informações sobre segurança, saúde e meio ambiente — Sistema Globalmente Harmonizado (GHS), classificação, FDS e rotulagem de produtos químicos.",
        "Norma Regulamentadora nº 26 (NR-26) - Sinalização de Segurança.",
        "Lei nº 12.305/2010 - Política Nacional de Resíduos Sólidos.",
    ];
    if (!empty($extras["regulamentacoes_adicionais"])) {
        foreach (preg_split('/\r\n|\r|\n/', $extras["regulamentacoes_adicionais"]) as $linha) {
            $linha = trim($linha);
            if ($linha !== "") $base[] = $linha;
        }
    }
    return $base;
}

// ---------------------------------------------------------------------------
// Blocos de conteúdo de uma seção (mesmo formato de gerador_fds.py) — cada
// bloco é um array associativo com "tipo" e os dados daquele tipo.
// ---------------------------------------------------------------------------

function blocoCampos(array $pares): array { return ["tipo" => "campos", "pares" => $pares]; }
function blocoTabela(array $cabecalhos, array $linhas): array { return ["tipo" => "tabela", "cabecalhos" => $cabecalhos, "linhas" => $linhas]; }
function blocoLista(string $titulo, array $itens): array { return ["tipo" => "lista", "titulo" => $titulo, "itens" => $itens]; }
function blocoTexto(string $texto): array { return ["tipo" => "texto", "texto" => $texto]; }

/**
 * Monta a estrutura completa das 16 seções da FDS — porte 1:1 de
 * montar_dados_fds() em gerador_fds.py. Ver aquele arquivo para os
 * comentários linha a linha; aqui só a sintaxe muda para PHP.
 */
function montarDadosFds(
    array $perfilEmpresa,
    array $produtoInfo,
    array $composicao,
    string $estadoFisico,
    array $resultadoToxicidadeAguda,
    ?array $resultadoPele,
    ?array $resultadoOlhos,
    ?BancoSubstancias $banco = null,
    array $camposExtras = [],
    ?string $dataEmissao = null,
    string $numeroRevisao = "01"
): array {
    $extras = $camposExtras;
    $dataStr = $dataEmissao ?? date("d/m/Y");

    $rotulo = derivarRotuloGhs($resultadoToxicidadeAguda, $resultadoPele, $resultadoOlhos);
    $flags = $rotulo["flags"];
    $nomeProduto = $produtoInfo["nome_produto"] ?? "";

    $secoes = [];

    // --- Seção 1 ---
    $secoes["1"] = [
        "titulo" => "IDENTIFICAÇÃO",
        "blocos" => [
            blocoCampos([
                ["Nome do produto", $nomeProduto ?: "Não informado"],
                ["Código interno do produto", $produtoInfo["codigo_produto"] ?? "Não disponível"],
                ["Uso recomendado", $produtoInfo["uso_recomendado"] ?? "Não informado"],
                ["Restrições de uso", $produtoInfo["restricoes_uso"] ?? "Não disponível"],
            ]),
            blocoCampos([
                ["Razão social do fornecedor", $perfilEmpresa["razao_social"] ?? "Não informado"],
                ["CNPJ", $perfilEmpresa["cnpj"] ?? "Não disponível"],
                ["Endereço", $perfilEmpresa["endereco"] ?? "Não disponível"],
                ["Telefone", $perfilEmpresa["telefone"] ?? "Não disponível"],
                ["E-mail", $perfilEmpresa["email"] ?? "Não disponível"],
                ["Telefone de emergência", $perfilEmpresa["telefone_emergencia"] ?? "Não disponível"],
            ]),
        ],
    ];

    // --- Seção 2 ---
    $linhasClassificacao = [];
    foreach ($resultadoToxicidadeAguda as $via => $resultado) {
        $nomeVia = _NOMES_VIA_TOXICIDADE[$via] ?? $via;
        $categoria = $resultado["categoria"] ?? null;
        if ($categoria !== null) {
            $linhasClassificacao[] = "Toxicidade aguda — {$nomeVia}: Categoria {$categoria}";
        } elseif (!empty($resultado["declaracao_obrigatoria"])) {
            $linhasClassificacao[] = "Toxicidade aguda — {$nomeVia}: não classificada ({$resultado['declaracao_obrigatoria']})";
        }
    }
    if (!empty($resultadoPele["categoria"])) {
        $linhasClassificacao[] = "Corrosão/irritação à pele: Categoria {$resultadoPele['categoria']}";
    }
    if (!empty($resultadoOlhos["categoria"])) {
        $linhasClassificacao[] = "Lesão ocular grave/irritação ocular: Categoria {$resultadoOlhos['categoria']}";
    }
    if (empty($linhasClassificacao)) {
        $linhasClassificacao[] = "Não classificado como perigoso para as classes calculadas por este sistema (toxicidade aguda e corrosão/irritação à pele e olhos).";
    }

    $blocosSecao2 = [
        blocoLista("Classificação da mistura (calculada)", $linhasClassificacao),
        blocoCampos([
            ["Palavra de advertência", $rotulo["palavra_advertencia"] ?? "Nenhuma"],
            ["Pictogramas", !empty($rotulo["pictogramas"]) ? implode(", ", array_map(fn($p) => _NOMES_PICTOGRAMA[$p], $rotulo["pictogramas"])) : "Nenhum"],
        ]),
        blocoLista("Frases de perigo (H)", !empty($rotulo["codigos_h"]) ? array_map(fn($c) => "{$c['codigo']} - {$c['descricao']}", $rotulo["codigos_h"]) : ["Não aplicável."]),
    ];
    foreach ($rotulo["codigos_p_por_grupo"] as $grupoNome => $itens) {
        if (!empty($itens)) {
            $blocosSecao2[] = blocoLista("Frases de precaução (P) — {$grupoNome}", array_map(fn($c) => "{$c['codigo']} - {$c['descricao']}", $itens));
        }
    }
    $blocosSecao2[] = blocoCampos([
        ["Outros perigos", $extras["outros_perigos"] ?? "Não classificado para outras classes de perigo com base nos dados calculados por este sistema (ver limitações na Seção 16)."],
    ]);
    $secoes["2"] = ["titulo" => "IDENTIFICAÇÃO DE PERIGOS", "blocos" => $blocosSecao2];

    // --- Seção 3 ---
    $linhasComposicao = [];
    foreach ($composicao as $item) {
        $segredo = !empty($item["segredo_industrial"]);
        $nomeI = $segredo ? "Segredo Industrial" : ($item["nome"] ?? "");
        $casI = $segredo ? "Segredo Industrial" : ($item["cas"] ?: "Não disponível");
        $concI = number_format((float) ($item["concentracao"] ?? 0), 2) . "%";
        if ($segredo) {
            $classifI = "Não divulgada (segredo industrial)";
        } elseif ($banco !== null && !empty($item["cas"])) {
            $codigos = obterHCodesSubstancia($banco, $item["cas"]);
            $classifI = !empty($codigos) ? implode(", ", $codigos) : "Não classificado / não disponível no Anexo VI";
        } else {
            $classifI = "Não disponível";
        }
        $linhasComposicao[] = [$nomeI, $casI, $concI, $classifI];
    }
    $secoes["3"] = [
        "titulo" => "COMPOSIÇÃO E INFORMAÇÕES SOBRE OS INGREDIENTES",
        "blocos" => [
            blocoCampos([["Natureza química", $extras["natureza_quimica"] ?? "Mistura"]]),
            blocoTabela(["Nome / Identificação", "Nº CAS", "Concentração", "Classificação de perigo"], $linhasComposicao),
        ],
    ];

    // --- Seção 4 ---
    $fp = frasesPrimeirosSocorros($flags);
    $secoes["4"] = ["titulo" => "MEDIDAS DE PRIMEIROS SOCORROS", "blocos" => [blocoCampos([
        ["Inalação", $fp["inalacao"]],
        ["Contato com a pele", $fp["contato_pele"]],
        ["Contato com os olhos", $fp["contato_olhos"]],
        ["Ingestão", $fp["ingestao"]],
        ["Principais sintomas e efeitos", $fp["sintomas"]],
        ["Notas para o médico", $fp["notas_medico"]],
    ])]];

    // --- Seção 5 ---
    $fi = frasesCombateIncendio($flags, $extras);
    $secoes["5"] = ["titulo" => "MEDIDAS DE COMBATE A INCÊNDIO", "blocos" => [blocoCampos([
        ["Meios de extinção apropriados", $fi["meios_apropriados"]],
        ["Meios de extinção não apropriados", $fi["meios_nao_apropriados"]],
        ["Perigos específicos do produto", $fi["perigos_especificos"]],
        ["Medidas de proteção da equipe de combate a incêndio", $fi["medidas_bombeiros"]],
    ])]];

    // --- Seção 6 ---
    $fv = frasesVazamento($flags);
    $secoes["6"] = ["titulo" => "MEDIDAS DE CONTROLE PARA DERRAMAMENTO OU VAZAMENTO", "blocos" => [blocoCampos([
        ["Precauções pessoais (pessoal não emergencial)", $fv["precaucoes_pessoais_nao_emergencial"]],
        ["Precauções pessoais (equipe de emergência)", $fv["precaucoes_pessoais_emergencia"]],
        ["Precauções ao meio ambiente", $fv["precaucoes_ambientais"]],
        ["Métodos de contenção", $fv["metodos_contencao"]],
        ["Métodos de limpeza", $fv["metodos_limpeza"]],
    ])]];

    // --- Seção 7 ---
    $fm = frasesManuseioArmazenamento($flags, $extras, $estadoFisico);
    $secoes["7"] = ["titulo" => "MANUSEIO E ARMAZENAMENTO", "blocos" => [blocoCampos([
        ["Manuseio seguro", $fm["manuseio_seguro"]],
        ["Medidas de higiene", $fm["medidas_higiene"]],
        ["Condições de armazenamento", $fm["condicoes_armazenamento"]],
        ["Produtos e materiais incompatíveis", $fm["materiais_incompativeis"]],
    ])]];

    // --- Seção 8 ---
    $fe = frasesEpi($flags, $extras);
    $secoes["8"] = ["titulo" => "CONTROLE DE EXPOSIÇÃO E PROTEÇÃO INDIVIDUAL", "blocos" => [blocoCampos([
        ["Limites de exposição ocupacional", $extras["limites_exposicao"] ?? "Não estabelecidos para os componentes desta mistura."],
        ["Controles de engenharia apropriados", $fe["controles_engenharia"]],
        ["Proteção dos olhos/face", $fe["protecao_olhos"]],
        ["Proteção da pele/corpo", $fe["protecao_pele"]],
        ["Proteção das mãos", $fe["protecao_maos"]],
        ["Proteção respiratória", $fe["protecao_respiratoria"]],
    ])]];

    // --- Seção 9 ---
    $nomeEstado = $estadoFisico === "liquido" ? "Líquido" : "Sólido pulverulento";
    $secoes["9"] = ["titulo" => "PROPRIEDADES FÍSICAS E QUÍMICAS", "blocos" => [blocoCampos([
        ["Estado físico", $nomeEstado],
        ["Cor", $extras["cor"] ?? "Não disponível"],
        ["Odor", $extras["odor"] ?? "Não disponível"],
        ["pH", $extras["ph"] ?? "Não disponível"],
        ["Ponto de fusão/congelamento", $extras["ponto_fusao"] ?? "Não disponível"],
        ["Ponto de ebulição inicial e faixa", $extras["ponto_ebulicao"] ?? "Não disponível"],
        ["Ponto de fulgor", $extras["ponto_fulgor"] ?? "Não disponível"],
        ["Taxa de evaporação", $extras["taxa_evaporacao"] ?? "Não disponível"],
        ["Inflamabilidade", $extras["inflamabilidade"] ?? "Não determinada"],
        ["Limites inferior/superior de inflamabilidade ou explosividade", $extras["limites_explosividade"] ?? "Não disponível"],
        ["Pressão de vapor", $extras["pressao_vapor"] ?? "Não disponível"],
        ["Densidade de vapor", $extras["densidade_vapor"] ?? "Não disponível"],
        ["Densidade relativa", $extras["densidade_relativa"] ?? "Não disponível"],
        ["Solubilidade em água", $extras["solubilidade_agua"] ?? "Não disponível"],
        ["Coeficiente de partição n-octanol/água", $extras["coeficiente_particao"] ?? "Não disponível"],
        ["Temperatura de auto-ignição", $extras["temperatura_autoignicao"] ?? "Não disponível"],
        ["Temperatura de decomposição", $extras["temperatura_decomposicao"] ?? "Não disponível"],
        ["Viscosidade", $extras["viscosidade"] ?? "Não disponível"],
    ])]];

    // --- Seção 10 ---
    $fr = frasesEstabilidadeReatividade($flags, $extras);
    $secoes["10"] = ["titulo" => "ESTABILIDADE E REATIVIDADE", "blocos" => [blocoCampos([
        ["Reatividade", $fr["reatividade"]],
        ["Estabilidade química", $fr["estabilidade_quimica"]],
        ["Possibilidade de reações perigosas", $fr["reacoes_perigosas"]],
        ["Condições a evitar", $fr["condicoes_evitar"]],
        ["Materiais incompatíveis", $fr["materiais_incompativeis"]],
        ["Produtos perigosos da decomposição", $fr["produtos_decomposicao"]],
    ])]];

    // --- Seção 11 ---
    $linhasTox = [];
    foreach ($resultadoToxicidadeAguda as $via => $resultado) {
        $nomeVia = _NOMES_VIA_TOXICIDADE[$via] ?? $via;
        $categoria = $resultado["categoria"] ?? null;
        $eta = $resultado["eta_mistura"] ?? null;
        if ($categoria !== null && $eta !== null) {
            $linhasTox[] = "{$nomeVia}: ETA (estimativa de toxicidade aguda) da mistura ≈ {$eta} — Categoria {$categoria}.";
        } elseif (!empty($resultado["declaracao_obrigatoria"])) {
            $linhasTox[] = "{$nomeVia}: {$resultado['declaracao_obrigatoria']}";
        } else {
            $linhasTox[] = "{$nomeVia}: não classificado com os dados informados.";
        }
    }
    if (!empty($resultadoPele["categoria"])) {
        $linhasTox[] = "Corrosão/irritação à pele: Categoria {$resultadoPele['categoria']} (critério: " . ($resultadoPele["criterio"] ?? "não disponível") . ").";
    } else {
        $linhasTox[] = "Corrosão/irritação à pele: não classificada com os dados informados.";
    }
    if (!empty($resultadoOlhos["categoria"])) {
        $linhasTox[] = "Lesão ocular grave/irritação ocular: Categoria {$resultadoOlhos['categoria']} (critério: " . ($resultadoOlhos["criterio"] ?? "não disponível") . ").";
    } else {
        $linhasTox[] = "Lesão ocular grave/irritação ocular: não classificada com os dados informados.";
    }

    $secoes["11"] = [
        "titulo" => "INFORMAÇÕES TOXICOLÓGICAS",
        "blocos" => [
            blocoLista("Toxicidade aguda e corrosão/irritação (calculadas)", $linhasTox),
            blocoCampos([
                ["Sensibilização", $extras["sensibilizacao"] ?? "Não disponível"],
                ["Mutagenicidade em células germinativas", $extras["mutagenicidade"] ?? "Não disponível"],
                ["Carcinogenicidade", $extras["carcinogenicidade"] ?? "Não disponível"],
                ["Toxicidade à reprodução", $extras["toxicidade_reproducao"] ?? "Não disponível"],
                ["Toxicidade para órgãos-alvo específicos (STOT) — exposição única", $extras["stot_unica"] ?? "Não disponível"],
                ["Toxicidade para órgãos-alvo específicos (STOT) — exposição repetida", $extras["stot_repetida"] ?? "Não disponível"],
                ["Perigo de aspiração", $extras["perigo_aspiracao"] ?? "Não disponível"],
            ]),
        ],
    ];

    // --- Seção 12 ---
    $fec = frasesEcologicas($extras);
    $secoes["12"] = ["titulo" => "INFORMAÇÕES ECOLÓGICAS", "blocos" => [blocoCampos([
        ["Ecotoxicidade", $fec["ecotoxicidade"]],
        ["Persistência e degradabilidade", $fec["persistencia_degradabilidade"]],
        ["Potencial bioacumulativo", $fec["potencial_bioacumulacao"]],
        ["Mobilidade no solo", $fec["mobilidade_solo"]],
        ["Outros efeitos adversos", $fec["outros_efeitos"]],
    ])]];

    // --- Seção 13 ---
    $fd = frasesDestinacaoFinal($extras);
    $secoes["13"] = ["titulo" => "CONSIDERAÇÕES SOBRE DESTINAÇÃO FINAL", "blocos" => [blocoCampos([
        ["Métodos e materiais para destinação final do produto", $fd["residuos_produto"]],
        ["Métodos e materiais para destinação final de embalagens", $fd["embalagens"]],
    ])]];

    // --- Seção 14 ---
    $secoes["14"] = ["titulo" => "INFORMAÇÕES SOBRE TRANSPORTE", "blocos" => [blocoCampos([
        ["Número ONU", $extras["numero_onu"] ?? "Não classificado"],
        ["Nome apropriado para embarque", $extras["nome_embarque"] ?? "Não disponível"],
        ["Classe de risco", $extras["classe_risco"] ?? "Não classificado"],
        ["Número de risco", $extras["numero_risco"] ?? "Não disponível"],
        ["Grupo de embalagem", $extras["grupo_embalagem"] ?? "Não disponível"],
        ["Perigos ambientais para o transporte", $extras["perigo_ambiental_transporte"] ?? "Não disponível"],
        ["Precauções especiais para o usuário", $extras["precaucoes_transporte"] ?? "Não disponível"],
    ])]];

    // --- Seção 15 ---
    $secoes["15"] = ["titulo" => "REGULAMENTAÇÕES", "blocos" => [blocoLista("Regulamentações aplicáveis", frasesRegulamentacoes($extras))]];

    // --- Seção 16 ---
    $linhasLegenda = [];
    foreach (LEGENDA_PADRAO as $sigla => $significado) {
        $linhasLegenda[] = "{$sigla} - {$significado}";
    }
    $secoes["16"] = [
        "titulo" => "OUTRAS INFORMAÇÕES",
        "blocos" => [
            blocoCampos([
                ["Data de emissão desta FDS", $dataStr],
                ["Número da revisão", $numeroRevisao],
            ]),
            blocoLista("Legenda / abreviaturas", $linhasLegenda),
            blocoTexto($extras["aviso_legal"]
                ?? "As informações contidas nesta Ficha de Dados de Segurança foram elaboradas com base nos dados "
                . "disponíveis até a data de emissão indicada acima e correspondem ao melhor conhecimento atual sobre o "
                . "produto. A classificação de perigo apresentada nas Seções 2 e 11 foi obtida por cálculo determinístico "
                . "a partir da composição informada, conforme a ABNT NBR 14725:2023, e cobre apenas as classes de perigo "
                . "calculadas por este sistema (toxicidade aguda e corrosão/irritação à pele e olhos) — outras classes de "
                . "perigo (inflamabilidade, propriedades explosivas, corrosivo a metais, toxicidade para órgãos-alvo "
                . "específicos, perigo ao ambiente aquático agudo/crônico, entre outras) não foram avaliadas por cálculo e "
                . "só constam nesta ficha quando informadas manualmente. Esta ficha não substitui a avaliação técnica de "
                . "um responsável qualificado para o uso específico pretendido pelo destinatário."),
        ],
    ];

    return [
        "cabecalho" => [
            "produto" => $nomeProduto,
            "data_emissao" => $dataStr,
            "numero_revisao" => $numeroRevisao,
            "empresa_nome" => $perfilEmpresa["razao_social"] ?? "",
        ],
        "secoes" => $secoes,
    ];
}

// ---------------------------------------------------------------------------
// Geração do PDF via dompdf/dompdf (HTML -> PDF). O HTML monta exatamente
// o mesmo layout visual do lado Python (reportlab): barra cinza de título
// de seção em largura total, tabelas rótulo/valor de duas colunas, sem
// logotipo/pictogramas gráficos (só texto), rodapé com identificador do
// documento e numeração de página — estilo Fosfeed/Safeeds.
//
// dompdf não pôde ser testado neste ambiente de desenvolvimento (mesmo
// bloqueio de rede do Packagist já documentado para phpoffice/
// phpspreadsheet) — a função está escrita para a API pública estável do
// dompdf (Dompdf::loadHtml / setPaper / render / output), mas precisa ser
// validada na máquina do usuário, que tem acesso ao Packagist.
// ---------------------------------------------------------------------------

function _htmlEscape(?string $texto): string
{
    return htmlspecialchars($texto ?? "", ENT_QUOTES, "UTF-8");
}

function _renderBlocoHtml(array $bloco): string
{
    switch ($bloco["tipo"]) {
        case "campos":
            $linhas = "";
            foreach ($bloco["pares"] as [$rotulo, $valor]) {
                $linhas .= "<tr><td class=\"rotulo\">" . _htmlEscape($rotulo) . "</td><td class=\"valor\">" . nl2br(_htmlEscape((string) $valor)) . "</td></tr>";
            }
            return "<table class=\"campos\">{$linhas}</table>";

        case "lista":
            $itens = implode("<br>", array_map(fn($i) => _htmlEscape($i), $bloco["itens"]));
            return "<table class=\"campos\"><tr><td class=\"rotulo\">" . _htmlEscape($bloco["titulo"]) . "</td><td class=\"valor\">{$itens}</td></tr></table>";

        case "tabela":
            $cabecalho = "<tr>" . implode("", array_map(fn($c) => "<th>" . _htmlEscape($c) . "</th>", $bloco["cabecalhos"])) . "</tr>";
            $linhas = "";
            foreach ($bloco["linhas"] as $linha) {
                $linhas .= "<tr>" . implode("", array_map(fn($v) => "<td>" . _htmlEscape((string) $v) . "</td>", $linha)) . "</tr>";
            }
            return "<table class=\"tabela-multi\">{$cabecalho}{$linhas}</table>";

        case "texto":
            return "<p class=\"texto-corrido\">" . nl2br(_htmlEscape($bloco["texto"])) . "</p>";

        default:
            return "";
    }
}

function _montarHtmlFds(array $dados): string
{
    $cab = $dados["cabecalho"];

    $secoesHtml = "";
    foreach (range(1, 16) as $numero) {
        $secao = $dados["secoes"][(string) $numero];
        $secoesHtml .= "<div class=\"barra-secao\">{$numero} - " . _htmlEscape($secao["titulo"]) . "</div>";
        foreach ($secao["blocos"] as $bloco) {
            $secoesHtml .= _renderBlocoHtml($bloco);
        }
    }

    $css = <<<CSS
        @page { margin: 40px 40px 50px 40px; }
        body { font-family: "DejaVu Sans", sans-serif; font-size: 8.5pt; color: #1a1a1a; }
        .cabecalho-topo { width: 100%; margin-bottom: 4px; }
        .cabecalho-topo td { vertical-align: middle; }
        .empresa-nome { font-size: 8.5pt; }
        .fds-wordmark { font-size: 20pt; font-weight: bold; text-align: right; }
        .titulo-produto { font-size: 16pt; font-weight: bold; margin: 4px 0; }
        .meta { width: 100%; border-bottom: 0.75pt solid #999999; padding-bottom: 4px; margin-bottom: 10px; font-size: 8.5pt; }
        .barra-secao { background: #4d4d4d; color: #ffffff; font-weight: bold; font-size: 10.5pt; padding: 5px 6px; margin-top: 10px; }
        table.campos { width: 100%; border-collapse: collapse; margin-bottom: 0; }
        table.campos td { border: 0.5pt solid #999999; padding: 4px 5px; vertical-align: top; }
        table.campos td.rotulo { width: 32%; font-weight: bold; background: #f2f2f2; }
        table.campos td.valor { width: 68%; }
        table.tabela-multi { width: 100%; border-collapse: collapse; }
        table.tabela-multi th { background: #4d4d4d; color: #fff; font-size: 8.5pt; padding: 4px 5px; border: 0.5pt solid #999999; text-align: left; }
        table.tabela-multi td { border: 0.5pt solid #999999; padding: 4px 5px; font-size: 8.5pt; }
        p.texto-corrido { font-size: 8pt; line-height: 1.35; margin: 6px 0 0; }
    CSS;

    $empresaNome = _htmlEscape($cab["empresa_nome"]);
    $tituloProduto = _htmlEscape("FICHA DE DADOS DE SEGURANÇA — " . ($cab["produto"] ?: "PRODUTO"));
    $dataEmissao = _htmlEscape($cab["data_emissao"]);
    $revisao = _htmlEscape($cab["numero_revisao"]);

    return <<<HTML
    <!DOCTYPE html>
    <html>
    <head>
    <meta charset="UTF-8">
    <style>{$css}</style>
    </head>
    <body>
      <table class="cabecalho-topo">
        <tr>
          <td class="empresa-nome">{$empresaNome}</td>
          <td class="fds-wordmark">FDS</td>
        </tr>
      </table>
      <div class="titulo-produto">{$tituloProduto}</div>
      <table class="meta">
        <tr>
          <td><b>Data de emissão:</b> {$dataEmissao}</td>
          <td><b>Revisão:</b> {$revisao}</td>
        </tr>
      </table>
      {$secoesHtml}
    </body>
    </html>
    HTML;
}

/**
 * Renderiza `dados` (saída de `montarDadosFds`) num PDF no layout
 * Fosfeed/Safeeds, via dompdf/dompdf (HTML -> PDF).
 *
 * NÃO PÔDE SER TESTADA neste ambiente de desenvolvimento (o Packagist
 * ficou bloqueado aqui, mesmo bloqueio já documentado para
 * phpoffice/phpspreadsheet — ver BancoSubstancias.php). Escrita contra a
 * API pública estável do dompdf; execute o teste funcional no final deste
 * arquivo (`php GeradorFds.php`, seção de PDF) na sua máquina, que tem
 * acesso ao Packagist, para confirmar antes de usar em produção.
 *
 * Numeração de página: usa `Canvas::page_text()`, o mecanismo oficial e
 * seguro do dompdf (substitui os marcadores {PAGE_NUM}/{PAGE_COUNT} depois
 * de renderizar todas as páginas, sem precisar habilitar execução de PHP
 * embutido no HTML). Limitação assumida: esse mecanismo não permite
 * escrever um texto SÓ na última página (ele aplica o mesmo texto,
 * com os marcadores substituídos, em todas as páginas) — por isso a
 * versão PHP não reproduz a linha "Esta é a última página." que a
 * versão Python (reportlab, com controle manual de canvas) inclui.
 *
 * $caminhoSaida: caminho de arquivo ou "php://output"/um stream aberto
 * (fwrite do conteúdo retornado por $dompdf->output()).
 */
function gerarPdfFds(array $dados, string $caminhoSaida): string
{
    if (!class_exists('\Dompdf\Dompdf')) {
        require __DIR__ . "/vendor/autoload.php";
    }

    $cab = $dados["cabecalho"];
    $idDocumento = strtoupper(preg_replace('/[^A-Za-z0-9]+/', '-', trim($cab["produto"] ?: "PRODUTO")));
    $idDocumento = "FDS-" . substr($idDocumento, 0, 24) . "-" . $cab["numero_revisao"];

    $options = new \Dompdf\Options();
    $options->set('defaultFont', 'DejaVu Sans');
    $options->set('isRemoteEnabled', false);

    $dompdf = new \Dompdf\Dompdf($options);
    $dompdf->loadHtml(_montarHtmlFds($dados), 'UTF-8');
    $dompdf->setPaper('A4', 'portrait');
    $dompdf->render();

    $canvas = $dompdf->getCanvas();
    $fontMetrics = $dompdf->getFontMetrics();
    $fonte = $fontMetrics->getFont("DejaVu Sans", "normal");
    $canvas->page_text(40, $canvas->get_height() - 30, $idDocumento, $fonte, 7, [0.4, 0.4, 0.4]);
    $canvas->page_text($canvas->get_width() - 140, $canvas->get_height() - 30, "Página {PAGE_NUM} de {PAGE_COUNT}", $fonte, 7, [0.4, 0.4, 0.4]);

    $conteudoPdf = $dompdf->output();
    file_put_contents($caminhoSaida, $conteudoPdf);
    return $caminhoSaida;
}

// ---------------------------------------------------------------------------
// Teste funcional — mesmo cenário de teste_pdf.py (ácido fosfórico ~40%,
// corrosivo à pele/olhos, toxicidade aguda oral moderada). Requer
// `composer install` (dompdf) para a parte de geração de PDF; a parte de
// montagem dos dados (montarDadosFds/derivarRotuloGhs) não depende do
// dompdf e pode ser conferida sempre.
// ---------------------------------------------------------------------------
if (php_sapi_name() === "cli" && realpath($argv[0]) === __FILE__) {
    require_once __DIR__ . "/MotorToxicidadeAguda.php";
    require_once __DIR__ . "/MotorCorrosaoIrritacao.php";
    require_once __DIR__ . "/BancoSubstancias.php";

    $resultadoTox = classificar_todas_as_vias([
        ViaExposicao::ORAL => [
            novo_ingrediente("Ácido fosfórico", "7664-38-2", 40.0, null, 4, false),
            novo_ingrediente("Água", "7732-18-5", 60.0, null, null, true),
        ],
    ]);

    $ingredientesPeleOlhos = [
        novo_ingrediente_pele_olhos("Ácido fosfórico", "7664-38-2", 40.0, "1", "1", 1.0, true, false, false, false),
        novo_ingrediente_pele_olhos("Água", "7732-18-5", 60.0, null, null, null, false, false, false, true),
    ];
    $resultadoPele = classificar_corrosao_irritacao_pele($ingredientesPeleOlhos);
    $resultadoOlhos = classificar_lesao_ocular($ingredientesPeleOlhos);

    $rotulo = derivarRotuloGhs($resultadoTox, $resultadoPele, $resultadoOlhos);
    echo "=== Rótulo GHS derivado ===\n";
    echo json_encode($rotulo, JSON_PRETTY_PRINT | JSON_UNESCAPED_UNICODE) . "\n";

    $dados = montarDadosFds(
        perfilEmpresa: ["razao_social" => "Minha Empresa Química Ltda.", "cnpj" => "00.000.000/0001-00"],
        produtoInfo: ["nome_produto" => "Fosfeed Teste PHP", "uso_recomendado" => "Fertilizante foliar."],
        composicao: [
            ["nome" => "Ácido fosfórico", "cas" => "7664-38-2", "concentracao" => 40.0],
            ["nome" => "Água", "cas" => "7732-18-5", "concentracao" => 60.0],
        ],
        estadoFisico: "liquido",
        resultadoToxicidadeAguda: $resultadoTox,
        resultadoPele: $resultadoPele,
        resultadoOlhos: $resultadoOlhos,
        camposExtras: ["ph" => "~1,0 (produto puro)", "cor" => "Incolor"],
    );

    echo "\n=== montarDadosFds() OK — seções geradas: " . count($dados["secoes"]) . " ===\n";

    if (class_exists('\Dompdf\Dompdf') || file_exists(__DIR__ . "/vendor/autoload.php")) {
        $caminho = sys_get_temp_dir() . "/teste_fds_php.pdf";
        gerarPdfFds($dados, $caminho);
        echo "PDF gerado em: $caminho (" . filesize($caminho) . " bytes)\n";
    } else {
        echo "\nAVISO: vendor/autoload.php não encontrado — rode 'composer install' nesta pasta para testar gerarPdfFds().\n";
    }
}
