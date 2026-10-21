<?php
/**
 * Motor de classificação — Toxicidade Aguda
 * ==========================================
 *
 * Implementa a classificação de misturas por toxicidade aguda segundo a
 * ABNT NBR 14725:2023, Seção 5.3.1 (Tabela 16, Tabela 17 e equação de
 * aditividade de 5.3.1.7.1).
 *
 * Fonte normativa: ABNT NBR 14725:2023, adquirida legitimamente pelo
 * usuário. Os valores numéricos abaixo (limiares de categoria e fatores
 * de conversão) são dados técnicos/tabulares da norma, reproduzidos aqui
 * apenas como constantes de cálculo — não como texto da norma.
 *
 * Porte 1:1 de motor_toxicidade_aguda.py — mesma lógica, mesmos nomes de
 * campo (para manter os dois lados comparáveis).
 */

declare(strict_types=1);

final class ViaExposicao
{
    public const ORAL = "oral";
    public const DERMICA = "dermica";
    public const INALATORIA_GASES = "inalatoria_gases";           // ppmV
    public const INALATORIA_VAPORES = "inalatoria_vapores";       // mg/L
    public const INALATORIA_POEIRAS_NEVOAS = "inalatoria_poeiras_nevoas"; // mg/L

    public static function todas(): array
    {
        return [self::ORAL, self::DERMICA, self::INALATORIA_GASES,
                 self::INALATORIA_VAPORES, self::INALATORIA_POEIRAS_NEVOAS];
    }
}

// ---------------------------------------------------------------------------
// Tabela 16 — limites de categoria por via de exposição (NBR 14725:2023)
// Cada lista é [limite_cat1, limite_cat2, limite_cat3, limite_cat4, limite_cat5]
// Categoria 5 vai até o teto indicado (null = sem valor numérico definido,
// como nas vias que não têm Categoria 5 tabelada); acima do maior limite
// definido, a substância/mistura fica não classificada (NC).
// ---------------------------------------------------------------------------

const LIMITES_CATEGORIA = [
    ViaExposicao::ORAL                     => [5, 50, 300, 2000, 5000],
    ViaExposicao::DERMICA                  => [50, 200, 1000, 2000, 5000],
    ViaExposicao::INALATORIA_GASES         => [100, 500, 2500, 20000, null],
    ViaExposicao::INALATORIA_VAPORES       => [0.5, 2.0, 10.0, 20.0, null],
    ViaExposicao::INALATORIA_POEIRAS_NEVOAS => [0.05, 0.5, 1.0, 5.0, null],
];

// ---------------------------------------------------------------------------
// Tabela 17 — valores de conversão de categoria/faixa para ETA estimada,
// usados quando não há DL50/CL50 exato do ingrediente (só a categoria).
// ---------------------------------------------------------------------------

const CONVERSAO_ETA = [
    ViaExposicao::ORAL                     => [0.5, 5, 100, 500, 2500],
    ViaExposicao::DERMICA                  => [5, 50, 300, 1100, 2500],
    ViaExposicao::INALATORIA_GASES         => [10, 100, 700, 4500, null],
    ViaExposicao::INALATORIA_VAPORES       => [0.05, 0.5, 3, 11, null],
    ViaExposicao::INALATORIA_POEIRAS_NEVOAS => [0.005, 0.05, 0.5, 1.5, null],
];

// Concentração mínima acima da qual um ingrediente sem nenhum dado de
// toxicidade aguda invalida uma ETA definitiva para a mistura (5.3.1.7.2).
const LIMITE_INGREDIENTE_DESCONHECIDO = 1.0; // % m/m ou v/v

/**
 * Ingrediente de uma via de exposição.
 *
 * Campos:
 *   nome (string), cas (?string), concentracao (float),
 *   eta (?float), categoria (?int), sem_toxicidade_aguda (bool)
 */
function novo_ingrediente(
    string $nome,
    ?string $cas,
    float $concentracao,
    ?float $eta = null,
    ?int $categoria = null,
    bool $sem_toxicidade_aguda = false
): array {
    return [
        "nome" => $nome,
        "cas" => $cas,
        "concentracao" => $concentracao,
        "eta" => $eta,
        "categoria" => $categoria,
        "sem_toxicidade_aguda" => $sem_toxicidade_aguda,
    ];
}

/**
 * Classifica um valor de ETA numa categoria de 1 a 5, conforme a Tabela 16.
 * Retorna null se o valor estiver acima do teto de Categoria 5 (não classificado).
 */
function categoria_por_eta(float $eta, string $via): ?int
{
    $limites = LIMITES_CATEGORIA[$via];
    foreach ($limites as $i => $limite) {
        if ($limite === null) {
            continue;
        }
        if ($eta <= $limite) {
            return $i + 1;
        }
    }
    return null; // acima do maior limite definido -> não classificado (NC)
}

/**
 * Resolve a ETA de um ingrediente individual:
 * 1) usa o DL50/CL50 (ou ETA) direto, se fornecido;
 * 2) senão, converte a partir da categoria conhecida, via Tabela 17;
 * 3) senão, retorna null (dado ausente).
 */
function eta_do_ingrediente(array $ing, string $via): ?float
{
    if ($ing["sem_toxicidade_aguda"]) {
        return null; // ignorado no somatório por definição (5.3.1.7.1-b)
    }
    if ($ing["eta"] !== null) {
        return $ing["eta"];
    }
    if ($ing["categoria"] !== null) {
        $tabela = CONVERSAO_ETA[$via];
        $idx = $ing["categoria"] - 1;
        if ($idx >= 0 && $idx < count($tabela) && $tabela[$idx] !== null) {
            return $tabela[$idx];
        }
    }
    return null;
}

/**
 * Classifica a mistura para UMA via de exposição, aplicando a equação de
 * aditividade de 5.3.1.7.1:
 *
 *     100 / ETA_mistura = soma( Ci / ETAi )   para todo ingrediente i
 *                                               com ETA conhecida
 *
 * Retorna um array associativo com o resultado e a rastreabilidade do
 * cálculo, em vez de só a categoria — importante para auditoria posterior.
 */
function classificar_toxicidade_aguda(array $ingredientes, string $via): array
{
    $soma_ci_sobre_etai = 0.0;
    $concentracao_desconhecida = 0.0;
    $concentracao_considerada = 0.0;
    $detalhes = [];

    foreach ($ingredientes as $ing) {
        $eta_i = eta_do_ingrediente($ing, $via);

        if ($ing["sem_toxicidade_aguda"]) {
            $detalhes[] = ["nome" => $ing["nome"], "status" => "ignorado (sem toxicidade aguda conhecida)"];
            continue;
        }

        if ($eta_i === null) {
            $concentracao_desconhecida += $ing["concentracao"];
            $detalhes[] = ["nome" => $ing["nome"], "status" => "ETA desconhecida"];
            continue;
        }

        $soma_ci_sobre_etai += $ing["concentracao"] / $eta_i;
        $concentracao_considerada += $ing["concentracao"];
        $detalhes[] = [
            "nome" => $ing["nome"],
            "concentracao" => $ing["concentracao"],
            "eta_usada" => $eta_i,
            "contribuicao" => $ing["concentracao"] / $eta_i,
        ];
    }

    $resultado = [
        "via" => $via,
        "detalhes" => $detalhes,
        "concentracao_com_eta_conhecida" => round($concentracao_considerada, 4),
        "concentracao_eta_desconhecida" => round($concentracao_desconhecida, 4),
    ];

    // Regra 5.3.1.7.2: ingrediente sem qualquer dado, em concentração >= 1%,
    // impede ETA definitiva da mistura para essa via.
    if ($concentracao_desconhecida >= LIMITE_INGREDIENTE_DESCONHECIDO) {
        $resultado["eta_mistura"] = null;
        $resultado["categoria"] = null;
        $resultado["eta_definitiva"] = false;
        $resultado["declaracao_obrigatoria"] = sprintf(
            "%.2f%% da mistura consiste em ingrediente(s) com toxicidade aguda (%s) desconhecida.",
            $concentracao_desconhecida, $via
        );
        return $resultado;
    }

    if ($soma_ci_sobre_etai <= 0) {
        // Nenhum ingrediente com toxicidade aguda relevante
        $resultado["eta_mistura"] = null;
        $resultado["categoria"] = null;
        $resultado["eta_definitiva"] = true;
        $resultado["declaracao_obrigatoria"] = null;
        return $resultado;
    }

    $eta_mistura = 100.0 / $soma_ci_sobre_etai;
    $categoria = categoria_por_eta($eta_mistura, $via);

    $resultado["eta_mistura"] = round($eta_mistura, 4);
    $resultado["categoria"] = $categoria;
    $resultado["eta_definitiva"] = true;
    $resultado["declaracao_obrigatoria"] = null;
    return $resultado;
}

/**
 * Conveniência: roda o cálculo para cada via de exposição informada e
 * devolve o detalhamento por via.
 *
 * $ingredientes_por_via: array [via_string => array de ingredientes]
 */
function classificar_todas_as_vias(array $ingredientes_por_via): array
{
    $resultados = [];
    foreach ($ingredientes_por_via as $via => $ingredientes) {
        $resultados[$via] = classificar_toxicidade_aguda($ingredientes, $via);
    }
    return $resultados;
}

// ---------------------------------------------------------------------------
// Exemplo de uso / caso de teste (rode com: php MotorToxicidadeAguda.php)
// ---------------------------------------------------------------------------
if (php_sapi_name() === "cli" && realpath($argv[0] ?? "") === __FILE__) {
    $ingredientes_oral = [
        novo_ingrediente("Lauril éter sulfato de sódio", "68891-38-3", 5.4, 1288.0),
        novo_ingrediente("Cloreto de sódio", "7647-14-5", 1.0, null, null, true),
        novo_ingrediente("Conservante X", "0000-00-0", 0.3, null, 4),
        novo_ingrediente("Água", "7732-18-5", 93.3, null, null, true),
    ];

    $resultado = classificar_toxicidade_aguda($ingredientes_oral, ViaExposicao::ORAL);
    echo json_encode($resultado, JSON_PRETTY_PRINT | JSON_UNESCAPED_UNICODE | JSON_UNESCAPED_SLASHES) . "\n";
}
