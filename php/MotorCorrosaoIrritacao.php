<?php
/**
 * Motor de classificação — Corrosão/Irritação à Pele e Lesões Oculares
 * ======================================================================
 *
 * Implementa a classificação de misturas por:
 *   - Corrosão/irritação à pele  (NBR 14725:2023, Seção 5.3.2 — Tabelas 20 e 21)
 *   - Lesões oculares graves/irritação ocular (Seção 5.3.3 — Tabelas 24 e 25)
 *
 * Fonte normativa: ABNT NBR 14725:2023, adquirida legitimamente pelo
 * usuário. Os valores numéricos abaixo (limiares de concentração e
 * fatores de peso) são dados técnicos/tabulares da norma, reproduzidos
 * aqui apenas como constantes de cálculo — não como texto da norma.
 *
 * Escopo e limitações assumidas de propósito (não escondidas):
 *   - A abordagem por aditividade (Tabelas 20 e 24) é o caminho
 *     principal implementado aqui.
 *   - A abordagem não-aditiva por pH (Tabelas 21 e 25) é implementada
 *     como verificação adicional/override para ácidos e bases fortes,
 *     e para ingredientes marcados explicitamente como não aptos à
 *     aditividade (5.3.2.3.3.4 / 5.3.3.3.3.4).
 *   - A exceção por "peso da evidência" (5.1.3.2) é um julgamento de
 *     especialista, não automatizável — NÃO está implementada aqui de
 *     propósito.
 *
 * Porte 1:1 de motor_corrosao_irritacao.py, incluindo o fix da Tabela 21
 * (via não-aditiva resulta em Categoria 1 SEM subcategoria, mesmo que o
 * ingrediente em si seja 1A/1B/1C — 5.3.2.3.3.4).
 */

declare(strict_types=1);

const CATEGORIAS_PELE_CORROSIVAS = ["1A", "1B", "1C", "1"]; // "1" = Categoria 1 sem subcategoria
const CATEGORIAS_PELE_IRRITANTES = ["2", "3"];
const CATEGORIAS_OLHOS_GRAVES = ["1"];
const CATEGORIAS_OLHOS_IRRITANTES = ["2A", "2B", "2"]; // "2" = Categoria 2 sem subcategoria informada

const LIMITE_RELEVANCIA_PADRAO = 1.0; // % — abaixo disso, ingrediente é ignorado, salvo override

/**
 * Ingrediente para as classes de pele/olhos.
 *
 * Campos: nome, cas, concentracao, categoria_pele, categoria_olhos, ph,
 * acido_ou_base_forte, nao_apto_aditividade, relevante_abaixo_1pct,
 * sem_perigo_pele_olhos.
 */
function novo_ingrediente_pele_olhos(
    string $nome,
    ?string $cas,
    float $concentracao,
    ?string $categoria_pele = null,
    ?string $categoria_olhos = null,
    ?float $ph = null,
    bool $acido_ou_base_forte = false,
    bool $nao_apto_aditividade = false,
    bool $relevante_abaixo_1pct = false,
    bool $sem_perigo_pele_olhos = false
): array {
    return [
        "nome" => $nome,
        "cas" => $cas,
        "concentracao" => $concentracao,
        "categoria_pele" => $categoria_pele,
        "categoria_olhos" => $categoria_olhos,
        "ph" => $ph,
        "acido_ou_base_forte" => $acido_ou_base_forte,
        "nao_apto_aditividade" => $nao_apto_aditividade,
        "relevante_abaixo_1pct" => $relevante_abaixo_1pct,
        "sem_perigo_pele_olhos" => $sem_perigo_pele_olhos,
    ];
}

function _relevante(array $ing, float $limite = LIMITE_RELEVANCIA_PADRAO): bool
{
    if ($ing["sem_perigo_pele_olhos"]) {
        return false;
    }
    return $ing["concentracao"] >= $limite || $ing["relevante_abaixo_1pct"];
}

// ---------------------------------------------------------------------------
// PELE — Corrosão/Irritação (Tabelas 20 e 21)
// ---------------------------------------------------------------------------

function _somar_por_categoria_pele(array $ingredientes): array
{
    $somas = ["1A" => 0.0, "1B" => 0.0, "1C" => 0.0, "1" => 0.0, "2" => 0.0, "3" => 0.0];
    $tem_categoria_1_sem_subcategoria = false;
    $detalhes = [];

    foreach ($ingredientes as $ing) {
        if (!_relevante($ing) || $ing["categoria_pele"] === null) {
            continue;
        }
        $cat = $ing["categoria_pele"];
        if (!array_key_exists($cat, $somas)) {
            continue;
        }
        $somas[$cat] += $ing["concentracao"];
        if ($cat === "1") {
            $tem_categoria_1_sem_subcategoria = true;
        }
        $detalhes[] = ["nome" => $ing["nome"], "categoria_pele" => $cat, "concentracao" => $ing["concentracao"]];
    }

    return [$somas, $tem_categoria_1_sem_subcategoria, $detalhes];
}

/**
 * Tabela 21 — abordagem não-aditiva, para ácidos/bases fortes e
 * ingredientes marcados como não aptos à aditividade. Retorna null se
 * nenhum ingrediente disparar essa via; senão, retorna o resultado mais
 * severo encontrado por essa via (a ser comparado com o da Tabela 20).
 */
function _classificar_corrosao_pele_tabela21(array $ingredientes): ?array
{
    $achados = [];
    foreach ($ingredientes as $ing) {
        if (!_relevante($ing, 1.0) && !$ing["relevante_abaixo_1pct"]) {
            continue;
        }

        if ($ing["acido_ou_base_forte"] && $ing["ph"] !== null) {
            if ($ing["ph"] <= 2 && $ing["concentracao"] >= 1.0) {
                $achados[] = ["1", $ing, "ácido pH ≤ 2, ≥1%"];
            } elseif ($ing["ph"] >= 11.5 && $ing["concentracao"] >= 1.0) {
                $achados[] = ["1", $ing, "base pH ≥ 11,5, ≥1%"];
            }
        }

        if ($ing["nao_apto_aditividade"]) {
            if (in_array($ing["categoria_pele"], ["1A", "1B", "1C", "1"], true) && $ing["concentracao"] >= 1.0) {
                // 5.3.2.3.3.4 (texto): "deve ser classificada como Categoria 1
                // de corrosão à pele" — SEM subcategoria, mesmo que o
                // ingrediente em si seja 1A/1B/1C. Diferente da Tabela 20,
                // onde a subcategorização É prevista explicitamente.
                $achados[] = ["1", $ing, "corrosivo não apto à aditividade, ≥1%"];
            } elseif (in_array($ing["categoria_pele"], ["2", "3"], true) && $ing["concentracao"] >= 3.0) {
                // a norma diz "Categoria 2 ou 3" sem regra de desempate explícita
                // nesta tabela; usamos a própria categoria do ingrediente.
                $achados[] = [$ing["categoria_pele"], $ing, "irritante não apto à aditividade, ≥3%"];
            }
        }
    }

    if (empty($achados)) {
        return null;
    }

    $ordem_severidade = ["1A", "1B", "1C", "1", "2", "3"];
    usort($achados, fn($a, $b) => array_search($a[0], $ordem_severidade) <=> array_search($b[0], $ordem_severidade));
    $categoria_mais_severa = $achados[0][0];

    $gatilhos = array_map(fn($a) => ["nome" => $a[1]["nome"], "motivo" => $a[2]], $achados);
    return [
        "categoria" => $categoria_mais_severa,
        "via" => "Tabela 21 (não-aditiva / pH)",
        "gatilhos" => $gatilhos,
    ];
}

/**
 * Classifica a mistura quanto à corrosão/irritação à pele, combinando a
 * abordagem aditiva (Tabela 20, caminho principal) com a abordagem por
 * pH/não-aditividade (Tabela 21, para os casos especiais que a própria
 * norma alerta não funcionarem bem com aditividade pura).
 */
function classificar_corrosao_irritacao_pele(array $ingredientes): array
{
    [$somas, $tem_cat1_sem_sub, $detalhes] = _somar_por_categoria_pele($ingredientes);
    $s1a = $somas["1A"]; $s1b = $somas["1B"]; $s1c = $somas["1C"]; $s1_sem_sub = $somas["1"];
    $s2 = $somas["2"]; $s3 = $somas["3"];

    $soma_cat1_total = $s1a + $s1b + $s1c + $s1_sem_sub;
    $ponderado_1_2 = 10 * $soma_cat1_total + $s2;
    $ponderado_1_2_3 = $ponderado_1_2 + $s3;

    $resultado_tabela20 = null;

    // --- Corrosão Categoria 1, com subcategorização (footnote a, Tabela 20) ---
    if ($s1a >= 5) {
        $resultado_tabela20 = ["categoria" => "1A", "criterio" => "soma Subcategoria 1A ≥ 5%"];
    } elseif ($s1a + $s1b >= 5) {
        $resultado_tabela20 = ["categoria" => "1B", "criterio" => "soma 1A+1B ≥ 5%"];
    } elseif ($s1a + $s1b + $s1c >= 5) {
        $resultado_tabela20 = ["categoria" => "1C", "criterio" => "soma 1A+1B+1C ≥ 5%"];
    } elseif ($tem_cat1_sem_sub && $soma_cat1_total >= 5) {
        $resultado_tabela20 = ["categoria" => "1", "criterio" => "soma de todos os Cat.1 (sem subcategoria) ≥ 5%"];
    }

    // --- Se não for corrosiva, avalia irritação (Categoria 2, depois 3) ---
    if ($resultado_tabela20 === null) {
        if ($s2 >= 10) {
            $resultado_tabela20 = ["categoria" => "2", "criterio" => "soma Categoria 2 ≥ 10%"];
        } elseif ($soma_cat1_total >= 1 && $soma_cat1_total < 5) {
            $resultado_tabela20 = ["categoria" => "2", "criterio" => "soma Categoria 1 entre 1% e <5%"];
        } elseif ($ponderado_1_2 >= 10) {
            $resultado_tabela20 = ["categoria" => "2", "criterio" => "10×Cat.1 + Cat.2 ≥ 10%"];
        }
    }

    if ($resultado_tabela20 === null) {
        if ($s3 >= 10) {
            $resultado_tabela20 = ["categoria" => "3", "criterio" => "soma Categoria 3 ≥ 10%"];
        } elseif ($s2 >= 1 && $s2 < 10) {
            $resultado_tabela20 = ["categoria" => "3", "criterio" => "soma Categoria 2 entre 1% e <10%"];
        } elseif ($ponderado_1_2 >= 1 && $ponderado_1_2 < 10) {
            $resultado_tabela20 = ["categoria" => "3", "criterio" => "10×Cat.1 + Cat.2 entre 1% e <10%"];
        } elseif ($ponderado_1_2_3 >= 10) {
            $resultado_tabela20 = ["categoria" => "3", "criterio" => "10×Cat.1 + Cat.2 + Cat.3 ≥ 10%"];
        }
    }

    $resultado_tabela21 = _classificar_corrosao_pele_tabela21($ingredientes);

    // Combina os dois caminhos: usa o mais severo entre os dois, quando ambos existem.
    $ordem_severidade = ["1A", "1B", "1C", "1", "2", "3"];
    $candidatos = [];
    if ($resultado_tabela20) {
        $candidatos[] = ["Tabela 20 (aditiva)", $resultado_tabela20["categoria"], $resultado_tabela20["criterio"]];
    }
    if ($resultado_tabela21) {
        $motivos = implode("; ", array_map(fn($g) => $g["motivo"], $resultado_tabela21["gatilhos"]));
        $candidatos[] = ["Tabela 21 (pH / não-aditiva)", $resultado_tabela21["categoria"], $motivos];
    }

    if (empty($candidatos)) {
        $categoria_final = null;
        $via_final = null;
        $criterio_final = null;
    } else {
        usort($candidatos, fn($a, $b) => array_search($a[1], $ordem_severidade) <=> array_search($b[1], $ordem_severidade));
        [$via_final, $categoria_final, $criterio_final] = $candidatos[0];
    }

    return [
        "classe_perigo" => "corrosao_irritacao_pele",
        "categoria" => $categoria_final,
        "via_decisao" => $via_final,
        "criterio" => $criterio_final,
        "somas_por_categoria" => $somas,
        "somatorio_ponderado_cat1_cat2" => round($ponderado_1_2, 4),
        "somatorio_ponderado_cat1_cat2_cat3" => round($ponderado_1_2_3, 4),
        "detalhes_tabela20" => $detalhes,
        "resultado_tabela21" => $resultado_tabela21,
    ];
}

// ---------------------------------------------------------------------------
// OLHOS — Lesões oculares graves/irritação ocular (Tabelas 24 e 25)
// ---------------------------------------------------------------------------
//
// Particularidade importante (footnote a da Tabela 24): um ingrediente
// classificado como Categoria 1 PELE *e* Categoria 1 OLHOS entra apenas
// uma vez na soma "Categoria 1 pele + Categoria 1 ocular" — por isso a
// soma é feita por INGREDIENTE (evitando dupla contagem), não pela soma
// independente das duas colunas.

function _somar_para_olhos(array $ingredientes): array
{
    $soma_cat1_combinada = 0.0; // Categoria 1 pele OU Categoria 1 olhos (sem dupla contagem)
    $soma_cat2 = 0.0;
    $todos_cat2_sao_2b = true;
    $tem_algum_cat2 = false;
    $detalhes = [];

    foreach ($ingredientes as $ing) {
        if (!_relevante($ing) || $ing["sem_perigo_pele_olhos"]) {
            continue;
        }

        $eh_cat1_pele = in_array($ing["categoria_pele"], ["1A", "1B", "1C", "1"], true);
        $eh_cat1_olhos = $ing["categoria_olhos"] === "1";

        if ($eh_cat1_pele || $eh_cat1_olhos) {
            $soma_cat1_combinada += $ing["concentracao"]; // contado uma única vez, por ingrediente
            $detalhes[] = ["nome" => $ing["nome"], "grupo" => "Cat.1 pele e/ou olhos", "concentracao" => $ing["concentracao"]];
        } elseif (in_array($ing["categoria_olhos"], ["2", "2A", "2B"], true)) {
            $soma_cat2 += $ing["concentracao"];
            $tem_algum_cat2 = true;
            if ($ing["categoria_olhos"] !== "2B") {
                $todos_cat2_sao_2b = false;
            }
            $detalhes[] = ["nome" => $ing["nome"], "grupo" => "Olhos " . $ing["categoria_olhos"], "concentracao" => $ing["concentracao"]];
        }
    }

    return [
        "soma_cat1_combinada" => $soma_cat1_combinada,
        "soma_cat2" => $soma_cat2,
        "todos_cat2_sao_2b" => $todos_cat2_sao_2b && $tem_algum_cat2,
        "detalhes" => $detalhes,
    ];
}

function _classificar_olhos_tabela25(array $ingredientes): ?array
{
    $achados = [];
    foreach ($ingredientes as $ing) {
        if (!_relevante($ing, 1.0) && !$ing["relevante_abaixo_1pct"]) {
            continue;
        }

        if ($ing["acido_ou_base_forte"] && $ing["ph"] !== null) {
            if ($ing["ph"] <= 2 && $ing["concentracao"] >= 1.0) {
                $achados[] = ["1", $ing, "ácido pH ≤ 2, ≥1%"];
            } elseif ($ing["ph"] >= 11.5 && $ing["concentracao"] >= 1.0) {
                $achados[] = ["1", $ing, "base pH ≥ 11,5, ≥1%"];
            }
        }

        if ($ing["nao_apto_aditividade"]) {
            if ($ing["categoria_olhos"] === "1" && $ing["concentracao"] >= 1.0) {
                $achados[] = ["1", $ing, "corrosivo ocular não apto à aditividade, ≥1%"];
            } elseif (in_array($ing["categoria_olhos"], ["2", "2A", "2B"], true) && $ing["concentracao"] >= 3.0) {
                $achados[] = ["2", $ing, "irritante ocular não apto à aditividade, ≥3%"];
            }
        }
    }

    if (empty($achados)) {
        return null;
    }

    $ordem = ["1", "2"];
    usort($achados, fn($a, $b) => array_search($a[0], $ordem) <=> array_search($b[0], $ordem));
    $categoria_mais_severa = $achados[0][0];

    $gatilhos = array_map(fn($a) => ["nome" => $a[1]["nome"], "motivo" => $a[2]], $achados);
    return [
        "categoria" => $categoria_mais_severa,
        "via" => "Tabela 25 (não-aditiva / pH)",
        "gatilhos" => $gatilhos,
    ];
}

/**
 * Classifica a mistura quanto a lesões oculares graves/irritação ocular,
 * combinando a abordagem aditiva (Tabela 24) com a abordagem por
 * pH/não-aditividade (Tabela 25).
 */
function classificar_lesao_ocular(array $ingredientes): array
{
    $somas = _somar_para_olhos($ingredientes);
    $s1 = $somas["soma_cat1_combinada"];
    $s2 = $somas["soma_cat2"];
    $ponderado = 10 * $s1 + $s2;

    $resultado_tabela24 = null;

    if ($s1 >= 3) {
        $resultado_tabela24 = ["categoria" => "1", "criterio" => "soma (Cat.1 pele + Cat.1 olhos) ≥ 3%"];
    } elseif ($s1 >= 1) { // 1% <= s1 < 3%
        $cat2_default = $somas["todos_cat2_sao_2b"] ? "2B" : "2A";
        $resultado_tabela24 = ["categoria" => $cat2_default, "criterio" => "soma (Cat.1 pele + Cat.1 olhos) entre 1% e <3%"];
    } elseif ($s2 >= 10) {
        $cat2_default = $somas["todos_cat2_sao_2b"] ? "2B" : "2A";
        $resultado_tabela24 = ["categoria" => $cat2_default, "criterio" => "soma Categoria 2 ocular ≥ 10%"];
    } elseif ($ponderado >= 10) {
        $cat2_default = $somas["todos_cat2_sao_2b"] ? "2B" : "2A";
        $resultado_tabela24 = ["categoria" => $cat2_default, "criterio" => "10×(Cat.1 pele+olhos) + Cat.2 ≥ 10%"];
    }

    $resultado_tabela25 = _classificar_olhos_tabela25($ingredientes);

    $ordem_severidade = ["1", "2A", "2", "2B"]; // 2A tratado como mais severo que 2B para desempate conservador
    $candidatos = [];
    if ($resultado_tabela24) {
        $candidatos[] = ["Tabela 24 (aditiva)", $resultado_tabela24["categoria"], $resultado_tabela24["criterio"]];
    }
    if ($resultado_tabela25) {
        $motivos = implode("; ", array_map(fn($g) => $g["motivo"], $resultado_tabela25["gatilhos"]));
        $candidatos[] = ["Tabela 25 (pH / não-aditiva)", $resultado_tabela25["categoria"], $motivos];
    }

    if (empty($candidatos)) {
        $categoria_final = null; $via_final = null; $criterio_final = null;
    } else {
        $chave_severidade = function ($c) use ($ordem_severidade) {
            $idx = array_search($c[1], $ordem_severidade, true);
            return $idx === false ? count($ordem_severidade) : $idx;
        };
        usort($candidatos, fn($a, $b) => $chave_severidade($a) <=> $chave_severidade($b));
        [$via_final, $categoria_final, $criterio_final] = $candidatos[0];
    }

    return [
        "classe_perigo" => "lesao_ocular",
        "categoria" => $categoria_final,
        "via_decisao" => $via_final,
        "criterio" => $criterio_final,
        "soma_cat1_combinada" => round($s1, 4),
        "soma_cat2" => round($s2, 4),
        "somatorio_ponderado" => round($ponderado, 4),
        "detalhes_tabela24" => $somas["detalhes"],
        "resultado_tabela25" => $resultado_tabela25,
    ];
}

// ---------------------------------------------------------------------------
// Exemplo de uso / caso de teste (rode com: php MotorCorrosaoIrritacao.php)
// ---------------------------------------------------------------------------
if (php_sapi_name() === "cli" && realpath($argv[0] ?? "") === __FILE__) {
    $ingredientes = [
        novo_ingrediente_pele_olhos("Tensoativo X", "0001-01-1", 8.0, "2", "2A"),
        novo_ingrediente_pele_olhos("Conservante corrosivo Y", "0002-02-2", 0.5, "1B", "1"),
        novo_ingrediente_pele_olhos("Água", "7732-18-5", 91.5, null, null, null, false, false, false, true),
    ];

    echo "=== Pele ===\n";
    echo json_encode(classificar_corrosao_irritacao_pele($ingredientes), JSON_PRETTY_PRINT | JSON_UNESCAPED_UNICODE | JSON_UNESCAPED_SLASHES) . "\n";

    echo "\n=== Olhos ===\n";
    echo json_encode(classificar_lesao_ocular($ingredientes), JSON_PRETTY_PRINT | JSON_UNESCAPED_UNICODE | JSON_UNESCAPED_SLASHES) . "\n";
}
