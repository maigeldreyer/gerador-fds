<?php
/**
 * Banco de substâncias — schema, importador do Anexo VI (ECHA) e ponte com
 * o motor de cálculo de classificação.
 *
 * Porte 1:1 de banco_substancias.py, incluindo a correção de integridade
 * de dados: o Anexo VI pode ter MAIS DE UMA linha para o mesmo CAS
 * (faixas de concentração da própria substância, ex. ácido nítrico >70%
 * vs ≤70%; ou variantes de forma física). A resolução usa banda de
 * concentração quando possível e cai para "mais severo + aviso" quando
 * ambíguo — nunca sobrescreve silenciosamente por ordem de importação.
 *
 * Requer PhpSpreadsheet só para importar_anexo_vi() (leitura do .xlsx):
 *   composer require phpoffice/phpspreadsheet
 */

declare(strict_types=1);

require_once __DIR__ . "/MotorToxicidadeAguda.php";
require_once __DIR__ . "/MotorCorrosaoIrritacao.php";

// ---------------------------------------------------------------------------
// Schema
// ---------------------------------------------------------------------------

const SCHEMA_SQL = <<<SQL
CREATE TABLE IF NOT EXISTS substancias (
    cas             TEXT PRIMARY KEY,
    ec_number       TEXT,
    nome            TEXT NOT NULL,
    fonte           TEXT NOT NULL,
    fonte_versao    TEXT,
    data_importacao TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS toxicidade_aguda (
    id              INTEGER PRIMARY KEY AUTOINCREMENT,
    cas             TEXT NOT NULL,
    via             TEXT NOT NULL,
    categoria       INTEGER,
    eta             REAL,
    estado_fisico   TEXT,
    faixa_min       REAL,
    faixa_min_incl  INTEGER,
    faixa_max       REAL,
    faixa_max_incl  INTEGER,
    nome_variante   TEXT,
    fonte           TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_toxicidade_aguda_cas_via ON toxicidade_aguda (cas, via);

CREATE TABLE IF NOT EXISTS presumidos_sem_toxicidade_aguda (
    cas    TEXT PRIMARY KEY,
    nome   TEXT,
    fonte  TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS pele_olhos (
    id              INTEGER PRIMARY KEY AUTOINCREMENT,
    cas             TEXT NOT NULL,
    categoria_pele  TEXT,
    categoria_olhos TEXT,
    ph              REAL,
    faixa_min       REAL,
    faixa_min_incl  INTEGER,
    faixa_max       REAL,
    faixa_max_incl  INTEGER,
    nome_variante   TEXT,
    fonte           TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_pele_olhos_cas ON pele_olhos (cas);

CREATE TABLE IF NOT EXISTS presumidos_sem_perigo_pele_olhos (
    cas    TEXT PRIMARY KEY,
    nome   TEXT,
    fonte  TEXT NOT NULL
);
SQL;

// ---------------------------------------------------------------------------
// Faixas de concentração da própria substância (não da mistura) — ver
// banco_substancias.py para a explicação completa. Ex.: "nitric acid …%
// [C > 70 %]" vs "nitric acid …% [C ≤ 70 %]" (mesmo CAS, duas linhas).
// ---------------------------------------------------------------------------

const PADRAO_FAIXA_UNICA = '/\bC\s*(?P<op>>=|<=|≥|≤|>|<)\s*(?P<val>[\d.,]+)\s*%/iu';
const PADRAO_FAIXA_DUPLA = '/(?P<val1>[\d.,]+)\s*%\s*(?P<op1><=|≤|<)\s*C\s*(?P<op2><=|≤|<)\s*(?P<val2>[\d.,]+)\s*%/iu';

function _num(string $texto): float
{
    return (float) str_replace(",", ".", $texto);
}

/**
 * Procura notação de faixa de concentração no nome/rótulo da linha do
 * Anexo VI. Devolve [faixa_min, faixa_min_incl, faixa_max, faixa_max_incl];
 * todos null se a linha não tiver faixa (aplica-se em qualquer concentração).
 */
function extrair_faixa_concentracao(?string $nome_quimico): array
{
    if ($nome_quimico === null) {
        return [null, null, null, null];
    }

    if (preg_match(PADRAO_FAIXA_DUPLA, $nome_quimico, $m2)) {
        return [
            _num($m2["val1"]), in_array($m2["op1"], ["<=", "≤"], true),
            _num($m2["val2"]), in_array($m2["op2"], ["<=", "≤"], true),
        ];
    }

    if (preg_match(PADRAO_FAIXA_UNICA, $nome_quimico, $m1)) {
        $op = $m1["op"];
        $val = _num($m1["val"]);
        if (in_array($op, [">=", "≥"], true)) {
            return [$val, true, null, null];
        }
        if ($op === ">") {
            return [$val, false, null, null];
        }
        if (in_array($op, ["<=", "≤"], true)) {
            return [null, null, $val, true];
        }
        if ($op === "<") {
            return [null, null, $val, false];
        }
    }

    return [null, null, null, null];
}

/**
 * True se `concentracao` satisfaz a faixa (null em min/max = sem limite
 * naquele lado — logo, uma linha sem faixa alguma sempre retorna true).
 */
function faixa_contem(float $concentracao, ?float $faixa_min, ?bool $faixa_min_incl,
                       ?float $faixa_max, ?bool $faixa_max_incl): bool
{
    if ($faixa_min !== null) {
        $ok = $faixa_min_incl ? $concentracao >= $faixa_min : $concentracao > $faixa_min;
        if (!$ok) {
            return false;
        }
    }
    if ($faixa_max !== null) {
        $ok = $faixa_max_incl ? $concentracao <= $faixa_max : $concentracao < $faixa_max;
        if (!$ok) {
            return false;
        }
    }
    return true;
}

final class BancoSubstancias
{
    public PDO $conn;
    private string $caminhoDb;

    public const MAPA_COLUNAS = [
        "cas" => ["cas no", "cas number", "cas"],
        "ec" => ["ec no", "ec number"],
        "nome" => ["international chemical identification", "chemical name", "substance name"],
        "classificacao" => ["hazard class and category code"],
        "h_codes" => ["classification hazard statement code", "hazard statement code"],
        "scl" => ["specific conc", "conc. limits", "m-factor", "m, scl, ate"],
    ];

    private const H_PARA_VIA = [
        "H300" => ["oral", 1], "H301" => ["oral", 3], "H302" => ["oral", 4],
        "H310" => ["dermica", 1], "H311" => ["dermica", 3], "H312" => ["dermica", 4],
        "H330" => ["inalatoria_generica", 1], "H331" => ["inalatoria_generica", 3], "H332" => ["inalatoria_generica", 4],
    ];

    public function __construct(string $caminhoDb = "substancias.db")
    {
        $this->caminhoDb = $caminhoDb;
        $this->conn = new PDO("sqlite:" . $caminhoDb);
        $this->conn->setAttribute(PDO::ATTR_ERRMODE, PDO::ERRMODE_EXCEPTION);
        $this->conn->exec("PRAGMA foreign_keys = ON;");
        $this->migrarSchemaAntigoSeNecessario();
        $this->conn->exec(SCHEMA_SQL);
    }

    /**
     * Bancos criados antes da correção de faixas de concentração tinham
     * PRIMARY KEY (cas, via)/(cas) em toxicidade_aguda/pele_olhos, o que
     * colapsava silenciosamente múltiplas linhas do Anexo VI para o
     * mesmo CAS. Se detectar o schema antigo, derruba essas duas tabelas
     * para serem recriadas com o schema novo.
     */
    private function migrarSchemaAntigoSeNecessario(): void
    {
        foreach (["toxicidade_aguda", "pele_olhos"] as $tabela) {
            $stmt = $this->conn->query("PRAGMA table_info($tabela)");
            $colunas = array_map(fn($row) => $row["name"], $stmt->fetchAll(PDO::FETCH_ASSOC));
            if (!empty($colunas) && !in_array("faixa_min", $colunas, true)) {
                $this->conn->exec("DROP TABLE $tabela");
            }
        }
    }

    public function close(): void
    {
        // PDO fecha a conexão quando o objeto é destruído; método mantido
        // por simetria com a versão Python.
    }

    // -----------------------------------------------------------------
    // Inserção manual
    // -----------------------------------------------------------------

    public function upsertSubstancia(string $cas, string $nome, string $fonte,
                                      ?string $ecNumber = null, ?string $fonteVersao = null): void
    {
        $stmt = $this->conn->prepare(
            "INSERT INTO substancias (cas, ec_number, nome, fonte, fonte_versao, data_importacao)
             VALUES (:cas, :ec, :nome, :fonte, :versao, :data)
             ON CONFLICT(cas) DO UPDATE SET
                nome=excluded.nome, fonte=excluded.fonte,
                fonte_versao=excluded.fonte_versao, data_importacao=excluded.data_importacao"
        );
        $stmt->execute([
            ":cas" => $cas, ":ec" => $ecNumber, ":nome" => $nome,
            ":fonte" => $fonte, ":versao" => $fonteVersao, ":data" => date("Y-m-d"),
        ]);
    }

    public function marcarSemToxicidadeAguda(string $cas, string $nome, string $fonte = "MANUAL"): void
    {
        $stmt = $this->conn->prepare(
            "INSERT INTO presumidos_sem_toxicidade_aguda (cas, nome, fonte) VALUES (:cas, :nome, :fonte)
             ON CONFLICT(cas) DO UPDATE SET nome=excluded.nome, fonte=excluded.fonte"
        );
        $stmt->execute([":cas" => $cas, ":nome" => $nome, ":fonte" => $fonte]);
    }

    public function upsertToxicidadeAguda(string $cas, string $via, ?int $categoria = null,
                                           ?float $eta = null, ?string $estadoFisico = null,
                                           string $fonte = "MANUAL"): void
    {
        $del = $this->conn->prepare(
            "DELETE FROM toxicidade_aguda WHERE cas = :cas AND via = :via AND faixa_min IS NULL AND faixa_max IS NULL"
        );
        $del->execute([":cas" => $cas, ":via" => $via]);

        $ins = $this->conn->prepare(
            "INSERT INTO toxicidade_aguda (cas, via, categoria, eta, estado_fisico, fonte)
             VALUES (:cas, :via, :categoria, :eta, :estado_fisico, :fonte)"
        );
        $ins->execute([
            ":cas" => $cas, ":via" => $via, ":categoria" => $categoria,
            ":eta" => $eta, ":estado_fisico" => $estadoFisico, ":fonte" => $fonte,
        ]);
    }

    /**
     * Usado pela importação do Anexo VI: sempre INSERE uma nova linha,
     * nunca substitui — porque o mesmo (cas, via) pode legitimamente ter
     * mais de uma linha de origem (faixas de concentração, formas
     * físicas). A resolução de qual linha usar acontece depois, em
     * montarIngredientesPorVia(), com base na concentração real do
     * ingrediente na fórmula.
     */
    private function inserirToxicidadeAgudaVariante(string $cas, string $viaStr, ?int $categoria,
                                                     ?float $faixaMin, ?bool $faixaMinIncl,
                                                     ?float $faixaMax, ?bool $faixaMaxIncl,
                                                     string $nomeVariante, string $fonte): void
    {
        $stmt = $this->conn->prepare(
            "INSERT INTO toxicidade_aguda
             (cas, via, categoria, faixa_min, faixa_min_incl, faixa_max, faixa_max_incl, nome_variante, fonte)
             VALUES (:cas, :via, :categoria, :fmin, :fmin_i, :fmax, :fmax_i, :variante, :fonte)"
        );
        $stmt->execute([
            ":cas" => $cas, ":via" => $viaStr, ":categoria" => $categoria,
            ":fmin" => $faixaMin, ":fmin_i" => $faixaMinIncl === null ? null : (int) $faixaMinIncl,
            ":fmax" => $faixaMax, ":fmax_i" => $faixaMaxIncl === null ? null : (int) $faixaMaxIncl,
            ":variante" => $nomeVariante, ":fonte" => $fonte,
        ]);
    }

    public function marcarSemPerigoPeleOlhos(string $cas, string $nome, string $fonte = "MANUAL"): void
    {
        $stmt = $this->conn->prepare(
            "INSERT INTO presumidos_sem_perigo_pele_olhos (cas, nome, fonte) VALUES (:cas, :nome, :fonte)
             ON CONFLICT(cas) DO UPDATE SET nome=excluded.nome, fonte=excluded.fonte"
        );
        $stmt->execute([":cas" => $cas, ":nome" => $nome, ":fonte" => $fonte]);
    }

    public function upsertPeleOlhos(string $cas, ?string $categoriaPele = null,
                                     ?string $categoriaOlhos = null, ?float $ph = null,
                                     string $fonte = "MANUAL"): void
    {
        $del = $this->conn->prepare(
            "DELETE FROM pele_olhos WHERE cas = :cas AND faixa_min IS NULL AND faixa_max IS NULL"
        );
        $del->execute([":cas" => $cas]);

        $ins = $this->conn->prepare(
            "INSERT INTO pele_olhos (cas, categoria_pele, categoria_olhos, ph, fonte)
             VALUES (:cas, :cp, :co, :ph, :fonte)"
        );
        $ins->execute([
            ":cas" => $cas, ":cp" => $categoriaPele, ":co" => $categoriaOlhos,
            ":ph" => $ph, ":fonte" => $fonte,
        ]);
    }

    private function inserirPeleOlhosVariante(string $cas, ?string $categoriaPele, ?string $categoriaOlhos,
                                               ?float $faixaMin, ?bool $faixaMinIncl,
                                               ?float $faixaMax, ?bool $faixaMaxIncl,
                                               string $nomeVariante, string $fonte): void
    {
        $stmt = $this->conn->prepare(
            "INSERT INTO pele_olhos
             (cas, categoria_pele, categoria_olhos, faixa_min, faixa_min_incl, faixa_max, faixa_max_incl,
              nome_variante, fonte)
             VALUES (:cas, :cp, :co, :fmin, :fmin_i, :fmax, :fmax_i, :variante, :fonte)"
        );
        $stmt->execute([
            ":cas" => $cas, ":cp" => $categoriaPele, ":co" => $categoriaOlhos,
            ":fmin" => $faixaMin, ":fmin_i" => $faixaMinIncl === null ? null : (int) $faixaMinIncl,
            ":fmax" => $faixaMax, ":fmax_i" => $faixaMaxIncl === null ? null : (int) $faixaMaxIncl,
            ":variante" => $nomeVariante, ":fonte" => $fonte,
        ]);
    }

    // -----------------------------------------------------------------
    // Parsers de célula (classificação + H-codes) — mesma estratégia de
    // filtro-e-pareamento posicional do banco_substancias.py
    // -----------------------------------------------------------------

    private static function achaColuna(array $colunas, array $chaves): ?string
    {
        foreach ($chaves as $chave) {
            foreach ($colunas as $original) {
                if (str_contains(strtolower((string) $original), $chave)) {
                    return $original;
                }
            }
        }
        return null;
    }

    public static function extrairCategoriaAcuteTox(string $linhaClassificacao): ?int
    {
        if (preg_match('/acute\s+tox\.?\s*(\d)/i', $linhaClassificacao, $m)) {
            return (int) $m[1];
        }
        return null;
    }

    /**
     * Retorna [resultados, avisos], onde resultados é uma lista de
     * [via, categoria] extraída de uma célula de classificação + sua
     * célula de H-codes.
     */
    public function parseToxicidadeAguda(?string $textoClassificacao, ?string $textoHCodes): array
    {
        if ($textoClassificacao === null || $textoHCodes === null) {
            return [[], []];
        }

        $linhasAcuteTox = array_values(array_filter(
            array_map("trim", preg_split('/\R/u', $textoClassificacao)),
            fn($l) => preg_match('/acute\s+tox\.?\s*\d/i', $l) === 1
        ));

        // A regex já inclui o "H" no padrão, então preg_match_all devolve
        // o código completo (ex.: "H330") — NÃO reprefixar com "H" de novo
        // (bug do porte original em Python gerava "HH330").
        preg_match_all('/H3(?:00|01|02|10|11|12|30|31|32)/u', $textoHCodes, $mh);
        $hCodesAcuteTox = $mh[0];

        $avisos = [];
        $resultados = [];

        if (count($linhasAcuteTox) !== count($hCodesAcuteTox)) {
            if (!empty($linhasAcuteTox) || !empty($hCodesAcuteTox)) {
                $avisos[] = sprintf(
                    "Contagem de 'Acute Tox.' (%d) não bate com a contagem de H-codes de " .
                    "toxicidade aguda (%d) para classificação=%s / H=%s. Pulado — requer conferência manual.",
                    count($linhasAcuteTox), count($hCodesAcuteTox),
                    var_export($textoClassificacao, true), var_export($textoHCodes, true)
                );
            }
            return [[], $avisos];
        }

        foreach ($linhasAcuteTox as $i => $classeLinha) {
            $hCode = $hCodesAcuteTox[$i];
            if (!array_key_exists($hCode, self::H_PARA_VIA)) {
                continue;
            }
            [$viaStr, $categoriaBase] = self::H_PARA_VIA[$hCode];
            $categoria = self::extrairCategoriaAcuteTox($classeLinha) ?? $categoriaBase;
            $resultados[] = [$viaStr, $categoria];
        }

        return [$resultados, $avisos];
    }

    public static function extrairSubcategoriaPeleCorr(string $linha): string
    {
        if (preg_match('/skin\s+corr\.?\s*(1[abc]?)/i', $linha, $m)) {
            return strtoupper($m[1]);
        }
        return "1";
    }

    public static function extrairCategoriaPeleIrrit(string $linha): string
    {
        if (preg_match('/skin\s+irrit\.?\s*(\d)/i', $linha, $m)) {
            return $m[1];
        }
        return "2";
    }

    public static function extrairSubcategoriaOlhosIrrit(string $linha): string
    {
        if (preg_match('/eye\s+irrit\.?\s*(2[ab]?)/i', $linha, $m)) {
            return strtoupper($m[1]);
        }
        return "2";
    }

    /**
     * Retorna [categoria_pele, categoria_olhos, avisos].
     */
    public function parsePeleOlhos(?string $textoClassificacao, ?string $textoHCodes): array
    {
        if ($textoClassificacao === null || $textoHCodes === null) {
            return [null, null, []];
        }

        $avisos = [];
        $linhas = array_map("trim", preg_split('/\R/u', $textoClassificacao));

        $linhasPele = array_values(array_filter($linhas, fn($l) => preg_match('/skin\s+(corr|irrit)\.?/i', $l) === 1));
        preg_match_all('/H31[45]/u', $textoHCodes, $mp);
        $hPele = $mp[0];

        $categoriaPele = null;
        if (count($linhasPele) === count($hPele) && !empty($linhasPele)) {
            $candidatosPele = [];
            foreach ($linhasPele as $i => $linha) {
                $h = $hPele[$i];
                if ($h === "H314") {
                    $candidatosPele[] = self::extrairSubcategoriaPeleCorr($linha);
                } elseif ($h === "H315") {
                    $candidatosPele[] = self::extrairCategoriaPeleIrrit($linha);
                }
            }
            if (!empty($candidatosPele)) {
                $ordem = ["1A", "1B", "1C", "1", "2", "3"];
                usort($candidatosPele, function ($a, $b) use ($ordem) {
                    $ia = array_search($a, $ordem, true); $ia = $ia === false ? count($ordem) : $ia;
                    $ib = array_search($b, $ordem, true); $ib = $ib === false ? count($ordem) : $ib;
                    return $ia <=> $ib;
                });
                $categoriaPele = $candidatosPele[0];
            }
        } elseif (!empty($linhasPele) || !empty($hPele)) {
            $avisos[] = sprintf(
                "Contagem de linhas 'Skin Corr./Irrit.' (%d) não bate com H314/H315 (%d) " .
                "para classificação=%s / H=%s. Pulado — requer conferência manual.",
                count($linhasPele), count($hPele),
                var_export($textoClassificacao, true), var_export($textoHCodes, true)
            );
        }

        $linhasOlhos = array_values(array_filter($linhas, fn($l) => preg_match('/eye\s+(dam|irrit)\.?/i', $l) === 1));
        preg_match_all('/H31[89]/u', $textoHCodes, $mo);
        $hOlhos = $mo[0];

        $categoriaOlhos = null;
        if (count($linhasOlhos) === count($hOlhos) && !empty($linhasOlhos)) {
            $candidatosOlhos = [];
            foreach ($linhasOlhos as $i => $linha) {
                $h = $hOlhos[$i];
                if ($h === "H318") {
                    $candidatosOlhos[] = "1";
                } elseif ($h === "H319") {
                    $candidatosOlhos[] = self::extrairSubcategoriaOlhosIrrit($linha);
                }
            }
            if (!empty($candidatosOlhos)) {
                $ordem = ["1", "2A", "2", "2B"];
                usort($candidatosOlhos, function ($a, $b) use ($ordem) {
                    $ia = array_search($a, $ordem, true); $ia = $ia === false ? count($ordem) : $ia;
                    $ib = array_search($b, $ordem, true); $ib = $ib === false ? count($ordem) : $ib;
                    return $ia <=> $ib;
                });
                $categoriaOlhos = $candidatosOlhos[0];
            }
        } elseif (!empty($linhasOlhos) || !empty($hOlhos)) {
            $avisos[] = sprintf(
                "Contagem de linhas 'Eye Dam./Irrit.' (%d) não bate com H318/H319 (%d) " .
                "para classificação=%s / H=%s. Pulado — requer conferência manual.",
                count($linhasOlhos), count($hOlhos),
                var_export($textoClassificacao, true), var_export($textoHCodes, true)
            );
        }

        return [$categoriaPele, $categoriaOlhos, $avisos];
    }

    // -----------------------------------------------------------------
    // Importador da planilha do Anexo VI (ECHA) — usa PhpSpreadsheet só
    // para ler as células; toda a lógica de parsing/gravação é a mesma
    // função `processarLinhasAnexoVi()`, testável sem o Excel real.
    // -----------------------------------------------------------------

    /**
     * Importa a planilha do Anexo VI (arquivo .xlsx). $headerRow é o
     * índice (0-based) da linha real de cabeçalhos — na planilha
     * "unofficial" da ECHA, a primeira linha costuma ser um aviso, então
     * o cabeçalho real fica algumas linhas abaixo (ex.: headerRow=2 no
     * arquivo ATP23). Devolve um resumo da importação.
     */
    public function importarAnexoVi(string $caminhoExcel, ?string $fonteVersao = null,
                                     ?string $sheetName = null, int $headerRow = 0): array
    {
        if (!class_exists('\PhpOffice\PhpSpreadsheet\IOFactory')) {
            require __DIR__ . "/vendor/autoload.php";
        }

        $spreadsheet = \PhpOffice\PhpSpreadsheet\IOFactory::load($caminhoExcel);
        $sheet = $sheetName !== null ? $spreadsheet->getSheetByName($sheetName) : $spreadsheet->getActiveSheet();
        if ($sheet === null) {
            throw new \InvalidArgumentException("Aba '$sheetName' não encontrada na planilha.");
        }

        $linhasBrutas = $sheet->toArray(null, true, true, false);
        $cabecalho = $linhasBrutas[$headerRow] ?? null;
        if ($cabecalho === null) {
            throw new \InvalidArgumentException("Linha de cabeçalho $headerRow não existe na planilha.");
        }

        $linhas = [];
        for ($i = $headerRow + 1; $i < count($linhasBrutas); $i++) {
            $linha = [];
            foreach ($cabecalho as $col => $nomeColuna) {
                $linha[$nomeColuna] = $linhasBrutas[$i][$col] ?? null;
            }
            $linhas[] = $linha;
        }

        return $this->processarLinhasAnexoVi($linhas, $fonteVersao);
    }

    /**
     * Processa linhas já extraídas do Excel (uma associativa por linha,
     * chave = nome da coluna). Separado de importarAnexoVi() para poder
     * ser testado sem depender do PhpSpreadsheet/arquivo real.
     */
    public function processarLinhasAnexoVi(array $linhas, ?string $fonteVersao = null): array
    {
        if (empty($linhas)) {
            throw new \InvalidArgumentException("Nenhuma linha de dados para importar.");
        }

        $colunas = array_keys($linhas[0]);
        $colCas = self::achaColuna($colunas, self::MAPA_COLUNAS["cas"]);
        $colNome = self::achaColuna($colunas, self::MAPA_COLUNAS["nome"]);
        $colEc = self::achaColuna($colunas, self::MAPA_COLUNAS["ec"]);
        $colClasse = self::achaColuna($colunas, self::MAPA_COLUNAS["classificacao"]);
        $colH = self::achaColuna($colunas, self::MAPA_COLUNAS["h_codes"]);

        $faltantes = [];
        foreach (["CAS" => $colCas, "Nome" => $colNome, "Classificação" => $colClasse, "H-codes" => $colH] as $nome => $c) {
            if ($c === null) {
                $faltantes[] = $nome;
            }
        }
        if (!empty($faltantes)) {
            throw new \InvalidArgumentException(
                "Não consegui localizar as colunas: " . implode(", ", $faltantes) . ". " .
                "Colunas encontradas na planilha: " . implode(", ", $colunas) . ". " .
                "Ajuste BancoSubstancias::MAPA_COLUNAS conforme o layout real do seu arquivo."
            );
        }

        $versao = $fonteVersao ?? ("importado em " . date("Y-m-d"));

        // Idempotência: apaga TODAS as linhas de origem ECHA_ANEXO_VI antes
        // de reimportar (qualquer versão anterior).
        $this->conn->exec("DELETE FROM toxicidade_aguda WHERE fonte LIKE 'ECHA_ANEXO_VI%'");
        $this->conn->exec("DELETE FROM pele_olhos WHERE fonte LIKE 'ECHA_ANEXO_VI%'");

        $resumo = [
            "linhas_lidas" => count($linhas), "substancias_gravadas" => 0,
            "linhas_sem_cas" => 0, "linhas_sem_toxicidade_aguda" => 0,
            "linhas_com_pele_ou_olhos" => 0, "cas_com_multiplas_linhas" => 0,
            "avisos_parser" => [],
        ];

        $this->conn->beginTransaction();
        try {
            foreach ($linhas as $linha) {
                $casRaw = $linha[$colCas] ?? null;
                $cas = $casRaw !== null ? trim((string) $casRaw) : null;
                if (!$cas || strtolower($cas) === "nan" || $cas === "-") {
                    $resumo["linhas_sem_cas"]++;
                    continue;
                }

                $nomeRaw = $linha[$colNome] ?? null;
                $nome = ($nomeRaw !== null && $nomeRaw !== "") ? trim((string) $nomeRaw) : $cas;
                $ecRaw = $colEc ? ($linha[$colEc] ?? null) : null;
                $ec = ($ecRaw !== null && $ecRaw !== "") ? trim((string) $ecRaw) : null;

                $this->upsertSubstancia($cas, $nome, "ECHA_ANEXO_VI", $ec, $versao);
                $resumo["substancias_gravadas"]++;

                [$faixaMin, $faixaMinIncl, $faixaMax, $faixaMaxIncl] = extrair_faixa_concentracao($nome);

                $textoClasse = (string) ($linha[$colClasse] ?? "");
                $textoH = (string) ($linha[$colH] ?? "");

                [$pares, $avisosLinha] = $this->parseToxicidadeAguda($textoClasse, $textoH);
                foreach ($avisosLinha as $a) {
                    $resumo["avisos_parser"][] = "CAS $cas: $a";
                }
                if (empty($pares)) {
                    $resumo["linhas_sem_toxicidade_aguda"]++;
                }
                foreach ($pares as [$viaStr, $categoria]) {
                    $this->inserirToxicidadeAgudaVariante(
                        $cas, $viaStr, $categoria, $faixaMin, $faixaMinIncl, $faixaMax, $faixaMaxIncl,
                        $nome, "ECHA_ANEXO_VI ($versao)"
                    );
                }

                [$catPele, $catOlhos, $avisosPeleOlhos] = $this->parsePeleOlhos($textoClasse, $textoH);
                foreach ($avisosPeleOlhos as $a) {
                    $resumo["avisos_parser"][] = "CAS $cas: $a";
                }
                if ($catPele !== null || $catOlhos !== null) {
                    $resumo["linhas_com_pele_ou_olhos"]++;
                    $this->inserirPeleOlhosVariante(
                        $cas, $catPele, $catOlhos, $faixaMin, $faixaMinIncl, $faixaMax, $faixaMaxIncl,
                        $nome, "ECHA_ANEXO_VI ($versao)"
                    );
                }
            }
            $this->conn->commit();
        } catch (\Throwable $e) {
            $this->conn->rollBack();
            throw $e;
        }

        $stmt = $this->conn->query("
            SELECT COUNT(*) FROM (
                SELECT cas FROM toxicidade_aguda WHERE fonte LIKE 'ECHA_ANEXO_VI%'
                GROUP BY cas, via HAVING COUNT(*) > 1
            )
        ");
        $resumo["cas_com_multiplas_linhas"] = (int) $stmt->fetchColumn();

        return $resumo;
    }

    // -----------------------------------------------------------------
    // Ponte com o motor: monta os ingredientes por via, a partir da
    // fórmula informada na tela (CAS + concentração).
    // -----------------------------------------------------------------

    /**
     * $formula: lista de ["cas" => string, "nome" => string, "concentracao" => float]
     * $estadoFisicoProduto: "liquido" ou "solido_pulverulento"
     *
     * Retorna [ingredientes_por_via, avisos].
     */
    public function montarIngredientesPorVia(array $formula, string $estadoFisicoProduto): array
    {
        if (!in_array($estadoFisicoProduto, ["liquido", "solido_pulverulento"], true)) {
            throw new \InvalidArgumentException('estadoFisicoProduto deve ser "liquido" ou "solido_pulverulento"');
        }

        $viaInalatoriaRelevante = $estadoFisicoProduto === "liquido"
            ? ViaExposicao::INALATORIA_VAPORES
            : ViaExposicao::INALATORIA_POEIRAS_NEVOAS;

        $viasACalcular = [ViaExposicao::ORAL, ViaExposicao::DERMICA, $viaInalatoriaRelevante];

        $avisos = [];
        $ingredientesPorVia = [];
        foreach ($viasACalcular as $via) {
            $ingredientesPorVia[$via] = [];
        }

        foreach ($formula as $item) {
            $cas = $item["cas"];
            $nome = $item["nome"] ?? $cas;
            $concentracao = (float) $item["concentracao"];

            $stmt = $this->conn->prepare("SELECT 1 FROM presumidos_sem_toxicidade_aguda WHERE cas = :cas");
            $stmt->execute([":cas" => $cas]);
            if ($stmt->fetchColumn()) {
                foreach ($viasACalcular as $via) {
                    $ingredientesPorVia[$via][] = novo_ingrediente($nome, $cas, $concentracao, null, null, true);
                }
                continue;
            }

            $stmt = $this->conn->prepare(
                "SELECT via, categoria, eta, faixa_min, faixa_min_incl, faixa_max, faixa_max_incl, nome_variante
                 FROM toxicidade_aguda WHERE cas = :cas"
            );
            $stmt->execute([":cas" => $cas]);
            $linhasDb = $stmt->fetchAll(PDO::FETCH_ASSOC);

            if (empty($linhasDb)) {
                $avisos[] = "'$nome' (CAS $cas) não tem entrada de toxicidade aguda no banco " .
                    "(nem no Anexo VI, nem cadastro manual). Ele entrará no cálculo como " .
                    "ETA desconhecida em todas as vias — se a concentração for ≥ 1%, " .
                    "nenhuma via terá ETA definitiva até você complementar o dado.";
                foreach ($viasACalcular as $via) {
                    $ingredientesPorVia[$via][] = novo_ingrediente($nome, $cas, $concentracao);
                }
                continue;
            }

            // Agrupa por via (remapeando 'inalatoria_generica' para a via
            // real do produto), pois a mesma substância pode ter mais de
            // uma linha na MESMA via (faixas de concentração / variantes
            // de forma física).
            $linhasPorVia = [];
            foreach ($linhasDb as $row) {
                $viaStr = $row["via"] === "inalatoria_generica" ? $viaInalatoriaRelevante : $row["via"];
                if (!in_array($viaStr, $viasACalcular, true)) {
                    continue;
                }
                $linhasPorVia[$viaStr][] = [
                    "categoria" => $row["categoria"] !== null ? (int) $row["categoria"] : null,
                    "eta" => $row["eta"] !== null ? (float) $row["eta"] : null,
                    "faixa_min" => $row["faixa_min"] !== null ? (float) $row["faixa_min"] : null,
                    "faixa_min_incl" => $row["faixa_min_incl"] !== null ? (bool) $row["faixa_min_incl"] : null,
                    "faixa_max" => $row["faixa_max"] !== null ? (float) $row["faixa_max"] : null,
                    "faixa_max_incl" => $row["faixa_max_incl"] !== null ? (bool) $row["faixa_max_incl"] : null,
                    "nome_variante" => $row["nome_variante"],
                ];
            }

            $viasPresentes = [];
            foreach ($linhasPorVia as $via => $candidatas) {
                if (count($candidatas) === 1) {
                    $categoria = $candidatas[0]["categoria"];
                    $eta = $candidatas[0]["eta"];
                } else {
                    $aplicaveis = array_values(array_filter($candidatas, fn($c) => faixa_contem(
                        $concentracao, $c["faixa_min"], $c["faixa_min_incl"], $c["faixa_max"], $c["faixa_max_incl"]
                    )));
                    if (count($aplicaveis) === 1) {
                        $categoria = $aplicaveis[0]["categoria"];
                        $eta = $aplicaveis[0]["eta"];
                    } else {
                        // Ambíguo: nenhuma faixa bateu com exatidão, ou mais
                        // de uma bateu. Escolha segura: usa a classificação
                        // MAIS SEVERA entre todas as candidatas e avisa
                        // explicitamente para revisão humana.
                        $comCategoria = array_values(array_filter($candidatas, fn($c) => $c["categoria"] !== null));
                        if (!empty($comCategoria)) {
                            usort($comCategoria, fn($a, $b) => $a["categoria"] <=> $b["categoria"]);
                            $escolhida = $comCategoria[0];
                        } else {
                            $escolhida = $candidatas[0];
                        }
                        $categoria = $escolhida["categoria"];
                        $eta = $escolhida["eta"];

                        $variantes = implode("; ", array_map(
                            fn($c) => ($c["nome_variante"] ?: "(sem nome de variante)") . " → Categoria " . $c["categoria"],
                            $candidatas
                        ));
                        $avisos[] = "'$nome' (CAS $cas) tem " . count($candidatas) . " entradas diferentes no Anexo VI " .
                            "para toxicidade aguda ($via), e a concentração informada " .
                            "({$concentracao}%) não identificou uma única faixa aplicável com " .
                            "segurança: $variantes. Usada a mais severa (Categoria $categoria) " .
                            "por precaução — confirme manualmente qual variante corresponde à " .
                            "matéria-prima real antes de finalizar a FDS.";
                    }
                }

                $viasPresentes[$via] = true;
                $ingredientesPorVia[$via][] = novo_ingrediente($nome, $cas, $concentracao, $eta, $categoria);
            }

            // Para vias sem entrada no banco, o ingrediente entra como ETA
            // desconhecida nessa via específica (diferente de "sem
            // toxicidade aguda", que é uma afirmação positiva de ausência
            // de perigo).
            foreach ($viasACalcular as $via) {
                if (!isset($viasPresentes[$via])) {
                    $ingredientesPorVia[$via][] = novo_ingrediente($nome, $cas, $concentracao);
                }
            }
        }

        return [$ingredientesPorVia, $avisos];
    }

    /**
     * $formula: lista de ["cas" => string, "nome" => string, "concentracao" => float]
     *
     * Retorna [ingredientes, avisos], prontos para
     * classificar_corrosao_irritacao_pele() e classificar_lesao_ocular().
     */
    public function montarIngredientesPeleOlhos(array $formula): array
    {
        // Ordem de severidade (menor = mais severo), mesmo critério do
        // desempate em montarIngredientesPorVia().
        $ordemPele = ["1A" => 0, "1B" => 1, "1C" => 2, "1" => 3, "2" => 4, "3" => 5];
        $ordemOlhos = ["1" => 0, "2A" => 1, "2B" => 2, "2" => 3];

        $avisos = [];
        $ingredientes = [];

        foreach ($formula as $item) {
            $cas = $item["cas"];
            $nome = $item["nome"] ?? $cas;
            $concentracao = (float) $item["concentracao"];

            $stmt = $this->conn->prepare("SELECT 1 FROM presumidos_sem_perigo_pele_olhos WHERE cas = :cas");
            $stmt->execute([":cas" => $cas]);
            if ($stmt->fetchColumn()) {
                $ingredientes[] = novo_ingrediente_pele_olhos(
                    $nome, $cas, $concentracao, null, null, null, false, false, false, true
                );
                continue;
            }

            $stmt = $this->conn->prepare(
                "SELECT categoria_pele, categoria_olhos, ph,
                        faixa_min, faixa_min_incl, faixa_max, faixa_max_incl, nome_variante
                 FROM pele_olhos WHERE cas = :cas"
            );
            $stmt->execute([":cas" => $cas]);
            $rows = $stmt->fetchAll(PDO::FETCH_ASSOC);

            $candidatas = [];
            foreach ($rows as $row) {
                if ($row["categoria_pele"] === null && $row["categoria_olhos"] === null) {
                    continue;
                }
                $candidatas[] = [
                    "categoria_pele" => $row["categoria_pele"],
                    "categoria_olhos" => $row["categoria_olhos"],
                    "ph" => $row["ph"] !== null ? (float) $row["ph"] : null,
                    "faixa_min" => $row["faixa_min"] !== null ? (float) $row["faixa_min"] : null,
                    "faixa_min_incl" => $row["faixa_min_incl"] !== null ? (bool) $row["faixa_min_incl"] : null,
                    "faixa_max" => $row["faixa_max"] !== null ? (float) $row["faixa_max"] : null,
                    "faixa_max_incl" => $row["faixa_max_incl"] !== null ? (bool) $row["faixa_max_incl"] : null,
                    "nome_variante" => $row["nome_variante"],
                ];
            }

            if (empty($candidatas)) {
                $avisos[] = "'$nome' (CAS $cas) não tem classificação de pele/olhos no banco " .
                    "(nem no Anexo VI, nem cadastro manual). Ele NÃO contribuirá para o " .
                    "cálculo de corrosão/irritação — se for um componente relevante " .
                    "(ex.: ≥1%), complemente o dado antes de considerar o resultado final.";
                $ingredientes[] = novo_ingrediente_pele_olhos($nome, $cas, $concentracao);
                continue;
            }

            if (count($candidatas) === 1) {
                $categoriaPele = $candidatas[0]["categoria_pele"];
                $categoriaOlhos = $candidatas[0]["categoria_olhos"];
                $ph = $candidatas[0]["ph"];
            } else {
                $aplicaveis = array_values(array_filter($candidatas, fn($c) => faixa_contem(
                    $concentracao, $c["faixa_min"], $c["faixa_min_incl"], $c["faixa_max"], $c["faixa_max_incl"]
                )));
                if (count($aplicaveis) === 1) {
                    $categoriaPele = $aplicaveis[0]["categoria_pele"];
                    $categoriaOlhos = $aplicaveis[0]["categoria_olhos"];
                    $ph = $aplicaveis[0]["ph"];
                } else {
                    // Ambíguo: usa a combinação mais severa (pele e olhos
                    // avaliados separadamente) e avisa para revisão humana.
                    $comPele = array_values(array_filter($candidatas,
                        fn($c) => $c["categoria_pele"] !== null && array_key_exists($c["categoria_pele"], $ordemPele)));
                    $comOlhos = array_values(array_filter($candidatas,
                        fn($c) => $c["categoria_olhos"] !== null && array_key_exists($c["categoria_olhos"], $ordemOlhos)));

                    $escolhidaPele = null;
                    if (!empty($comPele)) {
                        usort($comPele, fn($a, $b) => $ordemPele[$a["categoria_pele"]] <=> $ordemPele[$b["categoria_pele"]]);
                        $escolhidaPele = $comPele[0];
                    }
                    $escolhidaOlhos = null;
                    if (!empty($comOlhos)) {
                        usort($comOlhos, fn($a, $b) => $ordemOlhos[$a["categoria_olhos"]] <=> $ordemOlhos[$b["categoria_olhos"]]);
                        $escolhidaOlhos = $comOlhos[0];
                    }

                    $categoriaPele = $escolhidaPele["categoria_pele"] ?? null;
                    $categoriaOlhos = $escolhidaOlhos["categoria_olhos"] ?? null;
                    $ph = $escolhidaPele["ph"] ?? null;
                    if ($ph === null && $escolhidaOlhos !== null) {
                        $ph = $escolhidaOlhos["ph"];
                    }

                    $variantes = implode("; ", array_map(
                        fn($c) => ($c["nome_variante"] ?: "(sem nome de variante)") .
                            " → pele " . ($c["categoria_pele"] ?? "—") . " / olhos " . ($c["categoria_olhos"] ?? "—"),
                        $candidatas
                    ));
                    $avisos[] = "'$nome' (CAS $cas) tem " . count($candidatas) . " entradas diferentes no Anexo VI " .
                        "para pele/olhos, e a concentração informada ({$concentracao}%) não " .
                        "identificou uma única faixa aplicável com segurança: $variantes. " .
                        "Usada a combinação mais severa (pele " . ($categoriaPele ?? "—") . " / " .
                        "olhos " . ($categoriaOlhos ?? "—") . ") por precaução — confirme manualmente " .
                        "qual variante corresponde à matéria-prima real antes de finalizar a FDS.";
                }
            }

            $ingredientes[] = novo_ingrediente_pele_olhos($nome, $cas, $concentracao, $categoriaPele, $categoriaOlhos, $ph);
        }

        return [$ingredientes, $avisos];
    }
}
