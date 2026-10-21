<?php
/**
 * Perfis de empresa — armazenamento local (JSON) e CRUD
 * ========================================================
 *
 * Porte 1:1 de perfis_empresa.py. Ver o docstring daquele arquivo para o
 * raciocínio (arquivo JSON simples, sem SQLite, id estável por perfil).
 */

declare(strict_types=1);

const CAMPOS_PERFIL = ["razao_social", "cnpj", "endereco", "telefone", "email", "telefone_emergencia"];

class RepositorioPerfisEmpresa
{
    private string $caminho;

    public function __construct(?string $caminho = null)
    {
        $this->caminho = $caminho ?? (getenv("FDS_PERFIS_PATH") ?: (__DIR__ . "/perfis_empresa.json"));
        if (!file_exists($this->caminho)) {
            $this->salvarTudo([]);
        }
    }

    private function carregarTudo(): array
    {
        $conteudo = file_get_contents($this->caminho);
        $dados = json_decode($conteudo, true);
        return is_array($dados) ? $dados : [];
    }

    private function salvarTudo(array $perfis): void
    {
        $tmp = $this->caminho . ".tmp";
        file_put_contents($tmp, json_encode($perfis, JSON_PRETTY_PRINT | JSON_UNESCAPED_UNICODE));
        rename($tmp, $this->caminho);
    }

    /** Lista de perfis (id + campos), ordenada por razão social. */
    public function listar(): array
    {
        $perfis = $this->carregarTudo();
        $lista = [];
        foreach ($perfis as $id => $dados) {
            $lista[] = array_merge(["id" => $id], $dados);
        }
        usort($lista, fn($a, $b) => strcasecmp($a["razao_social"] ?? "", $b["razao_social"] ?? ""));
        return $lista;
    }

    public function obter(string $perfilId): ?array
    {
        $perfis = $this->carregarTudo();
        if (!isset($perfis[$perfilId])) {
            return null;
        }
        return array_merge(["id" => $perfilId], $perfis[$perfilId]);
    }

    /**
     * Cria (perfilId=null) ou atualiza um perfil existente. Só persiste os
     * campos conhecidos (CAMPOS_PERFIL); qualquer outra chave é ignorada.
     * Lança InvalidArgumentException se razão social estiver vazia.
     */
    public function salvar(array $dados, ?string $perfilId = null): array
    {
        $perfis = $this->carregarTudo();
        $registro = [];
        foreach (CAMPOS_PERFIL as $campo) {
            $registro[$campo] = trim((string) ($dados[$campo] ?? ""));
        }

        if ($registro["razao_social"] === "") {
            throw new InvalidArgumentException("Razão social é obrigatória para salvar um perfil de empresa.");
        }

        if ($perfilId === null || !isset($perfis[$perfilId])) {
            $perfilId = $perfilId ?: $this->gerarUuid();
        }
        $perfis[$perfilId] = $registro;
        $this->salvarTudo($perfis);
        return array_merge(["id" => $perfilId], $registro);
    }

    public function excluir(string $perfilId): bool
    {
        $perfis = $this->carregarTudo();
        if (!isset($perfis[$perfilId])) {
            return false;
        }
        unset($perfis[$perfilId]);
        $this->salvarTudo($perfis);
        return true;
    }

    private function gerarUuid(): string
    {
        $dados = random_bytes(16);
        $dados[6] = chr((ord($dados[6]) & 0x0f) | 0x40);
        $dados[8] = chr((ord($dados[8]) & 0x3f) | 0x80);
        return vsprintf('%s%s-%s-%s-%s-%s%s%s', str_split(bin2hex($dados), 4));
    }
}

// ---------------------------------------------------------------------------
// Teste funcional rápido — mesmo roteiro de perfis_empresa.py
// ---------------------------------------------------------------------------
if (php_sapi_name() === "cli" && realpath($argv[0]) === __FILE__) {
    $tmp = tempnam(sys_get_temp_dir(), "perfis_teste_");
    unlink($tmp);
    $repo = new RepositorioPerfisEmpresa($tmp);

    assert($repo->listar() === []);

    $p1 = $repo->salvar([
        "razao_social" => "Minha Empresa Química Ltda.",
        "cnpj" => "00.000.000/0001-00",
        "endereco" => "Rua Exemplo, 123",
        "telefone" => "(11) 0000-0000",
        "email" => "contato@minhaempresa.com.br",
        "telefone_emergencia" => "0800-000-0000",
    ]);
    assert(!empty($p1["id"]));

    $p2 = $repo->salvar(["razao_social" => "Outra Empresa S.A."]);

    $lista = $repo->listar();
    assert(count($lista) === 2);
    assert($lista[0]["razao_social"] === "Minha Empresa Química Ltda.");

    $obtido = $repo->obter($p1["id"]);
    assert($obtido["cnpj"] === "00.000.000/0001-00");

    $atualizado = $repo->salvar(["razao_social" => "Minha Empresa Química Ltda. (atualizada)", "cnpj" => "11.111.111/0001-11"], $p1["id"]);
    assert($atualizado["id"] === $p1["id"]);
    assert(str_ends_with($repo->obter($p1["id"])["razao_social"], "(atualizada)"));
    assert(count($repo->listar()) === 2);

    assert($repo->excluir($p2["id"]) === true);
    assert(count($repo->listar()) === 1);
    assert($repo->excluir("id-inexistente") === false);

    $capturou = false;
    try {
        $repo->salvar(["razao_social" => ""]);
    } catch (InvalidArgumentException $e) {
        $capturou = true;
    }
    assert($capturou);

    unlink($tmp);
    echo "OK — todos os testes de RepositorioPerfisEmpresa (PHP) passaram." . PHP_EOL;
}
