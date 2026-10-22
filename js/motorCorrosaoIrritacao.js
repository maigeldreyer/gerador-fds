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
 *   - A exceção por "peso da evidência" (5.1.3.2), em que dados
 *     confiáveis mostram que o efeito de um ingrediente não é evidente
 *     acima do limite genérico, é um julgamento de especialista, não
 *     automatizável — NÃO está implementada aqui de propósito. Se for
 *     necessária, é uma decisão humana que sobrepõe o resultado deste
 *     motor, não um cálculo.
 *
 * Porte 1:1 de motor_corrosao_irritacao.py.
 */

export const CATEGORIAS_PELE_CORROSIVAS = ["1A", "1B", "1C", "1"];
export const CATEGORIAS_PELE_IRRITANTES = ["2", "3"];
export const CATEGORIAS_OLHOS_GRAVES = ["1"];
export const CATEGORIAS_OLHOS_IRRITANTES = ["2A", "2B", "2"];

export const LIMITE_RELEVANCIA_PADRAO = 1.0; // % — abaixo disso, ingrediente é ignorado, salvo override

/**
 * @typedef {Object} IngredientePeleOlhos
 * @property {string} nome
 * @property {?string} cas
 * @property {number} concentracao
 * @property {?string} [categoria_pele]
 * @property {?string} [categoria_olhos]
 * @property {?number} [ph]
 * @property {boolean} [acido_ou_base_forte]
 * @property {boolean} [nao_apto_aditividade]
 * @property {boolean} [relevante_abaixo_1pct]
 * @property {boolean} [sem_perigo_pele_olhos]
 */

/** Cria um ingrediente com os valores-padrão do dataclass original. */
export function criarIngredientePeleOlhos({
  nome,
  cas = null,
  concentracao,
  categoria_pele = null,
  categoria_olhos = null,
  ph = null,
  acido_ou_base_forte = false,
  nao_apto_aditividade = false,
  relevante_abaixo_1pct = false,
  sem_perigo_pele_olhos = false,
}) {
  return {
    nome,
    cas,
    concentracao,
    categoria_pele,
    categoria_olhos,
    ph,
    acido_ou_base_forte,
    nao_apto_aditividade,
    relevante_abaixo_1pct,
    sem_perigo_pele_olhos,
  };
}

function _round(valor, casas) {
  const fator = 10 ** casas;
  return Math.round((valor + Number.EPSILON) * fator) / fator;
}

function _relevante(ing, limite = LIMITE_RELEVANCIA_PADRAO) {
  if (ing.sem_perigo_pele_olhos) return false;
  return ing.concentracao >= limite || ing.relevante_abaixo_1pct;
}

// ---------------------------------------------------------------------------
// PELE — Corrosão/Irritação (Tabelas 20 e 21)
// ---------------------------------------------------------------------------

function _somarPorCategoriaPele(ingredientes) {
  const somas = { "1A": 0.0, "1B": 0.0, "1C": 0.0, "1": 0.0, "2": 0.0, "3": 0.0 };
  let temCategoria1SemSubcategoria = false;
  const detalhes = [];

  for (const ing of ingredientes) {
    if (!_relevante(ing) || ing.categoria_pele === null || ing.categoria_pele === undefined) continue;
    const cat = ing.categoria_pele;
    if (!(cat in somas)) continue;
    somas[cat] += ing.concentracao;
    if (cat === "1") temCategoria1SemSubcategoria = true;
    detalhes.push({ nome: ing.nome, categoria_pele: cat, concentracao: ing.concentracao });
  }

  return { somas, temCategoria1SemSubcategoria, detalhes };
}

/**
 * Tabela 21 — abordagem não-aditiva, para ácidos/bases fortes e
 * ingredientes marcados como não aptos à aditividade. Retorna null se
 * nenhum ingrediente disparar essa via; senão, retorna o resultado mais
 * severo encontrado por essa via (a ser comparado com o da Tabela 20).
 */
function _classificarCorrosaoPeleTabela21(ingredientes) {
  const achados = [];
  for (const ing of ingredientes) {
    if (!_relevante(ing, 1.0) && !ing.relevante_abaixo_1pct) continue;

    if (ing.acido_ou_base_forte && ing.ph !== null && ing.ph !== undefined) {
      if (ing.ph <= 2 && ing.concentracao >= 1.0) {
        achados.push(["1", ing, "ácido pH ≤ 2, ≥1%"]);
      } else if (ing.ph >= 11.5 && ing.concentracao >= 1.0) {
        achados.push(["1", ing, "base pH ≥ 11,5, ≥1%"]);
      }
    }

    if (ing.nao_apto_aditividade) {
      if (["1A", "1B", "1C", "1"].includes(ing.categoria_pele) && ing.concentracao >= 1.0) {
        // 5.3.2.3.3.4 (texto): "deve ser classificada como Categoria 1
        // de corrosão à pele" — SEM subcategoria, mesmo que o
        // ingrediente em si seja 1A/1B/1C.
        achados.push(["1", ing, "corrosivo não apto à aditividade, ≥1%"]);
      } else if (["2", "3"].includes(ing.categoria_pele) && ing.concentracao >= 3.0) {
        // a norma diz "Categoria 2 ou 3" sem regra de desempate explícita
        // nesta tabela; usamos a própria categoria do ingrediente.
        achados.push([ing.categoria_pele, ing, "irritante não apto à aditividade, ≥3%"]);
      }
    }
  }

  if (achados.length === 0) return null;

  const ordemSeveridade = ["1A", "1B", "1C", "1", "2", "3"];
  achados.sort((a, b) => ordemSeveridade.indexOf(a[0]) - ordemSeveridade.indexOf(b[0]));
  const categoriaMaisSevera = achados[0][0];
  return {
    categoria: categoriaMaisSevera,
    via: "Tabela 21 (não-aditiva / pH)",
    gatilhos: achados.map((a) => ({ nome: a[1].nome, motivo: a[2] })),
  };
}

/**
 * Classifica a mistura quanto à corrosão/irritação à pele, combinando
 * a abordagem aditiva (Tabela 20, caminho principal) com a abordagem por
 * pH/não-aditividade (Tabela 21, para os casos especiais que a própria
 * norma alerta não funcionarem bem com aditividade pura).
 * @param {IngredientePeleOlhos[]} ingredientes
 */
export function classificarCorrosaoIrritacaoPele(ingredientes) {
  const { somas, temCategoria1SemSubcategoria: temCat1SemSub, detalhes } = _somarPorCategoriaPele(ingredientes);
  const s1a = somas["1A"], s1b = somas["1B"], s1c = somas["1C"], s1SemSub = somas["1"];
  const s2 = somas["2"], s3 = somas["3"];

  const somaCat1Total = s1a + s1b + s1c + s1SemSub;
  const ponderado12 = 10 * somaCat1Total + s2;
  const ponderado123 = ponderado12 + s3;

  let resultadoTabela20 = null;

  // --- Corrosão Categoria 1, com subcategorização (footnote a, Tabela 20) ---
  if (s1a >= 5) {
    resultadoTabela20 = { categoria: "1A", criterio: "soma Subcategoria 1A ≥ 5%" };
  } else if (s1a + s1b >= 5) {
    resultadoTabela20 = { categoria: "1B", criterio: "soma 1A+1B ≥ 5%" };
  } else if (s1a + s1b + s1c >= 5) {
    resultadoTabela20 = { categoria: "1C", criterio: "soma 1A+1B+1C ≥ 5%" };
  } else if (temCat1SemSub && somaCat1Total >= 5) {
    resultadoTabela20 = { categoria: "1", criterio: "soma de todos os Cat.1 (sem subcategoria) ≥ 5%" };
  }

  // --- Se não for corrosiva, avalia irritação (Categoria 2, depois 3) ---
  if (resultadoTabela20 === null) {
    if (s2 >= 10) {
      resultadoTabela20 = { categoria: "2", criterio: "soma Categoria 2 ≥ 10%" };
    } else if (somaCat1Total >= 1 && somaCat1Total < 5) {
      resultadoTabela20 = { categoria: "2", criterio: "soma Categoria 1 entre 1% e <5%" };
    } else if (ponderado12 >= 10) {
      resultadoTabela20 = { categoria: "2", criterio: "10×Cat.1 + Cat.2 ≥ 10%" };
    }
  }

  if (resultadoTabela20 === null) {
    if (s3 >= 10) {
      resultadoTabela20 = { categoria: "3", criterio: "soma Categoria 3 ≥ 10%" };
    } else if (s2 >= 1 && s2 < 10) {
      resultadoTabela20 = { categoria: "3", criterio: "soma Categoria 2 entre 1% e <10%" };
    } else if (ponderado12 >= 1 && ponderado12 < 10) {
      resultadoTabela20 = { categoria: "3", criterio: "10×Cat.1 + Cat.2 entre 1% e <10%" };
    } else if (ponderado123 >= 10) {
      resultadoTabela20 = { categoria: "3", criterio: "10×Cat.1 + Cat.2 + Cat.3 ≥ 10%" };
    }
  }

  const resultadoTabela21 = _classificarCorrosaoPeleTabela21(ingredientes);

  // Combina os dois caminhos: usa o mais severo entre os dois, quando ambos existem.
  const ordemSeveridade = ["1A", "1B", "1C", "1", "2", "3"];
  const candidatos = [];
  if (resultadoTabela20) {
    candidatos.push(["Tabela 20 (aditiva)", resultadoTabela20.categoria, resultadoTabela20.criterio]);
  }
  if (resultadoTabela21) {
    candidatos.push([
      "Tabela 21 (pH / não-aditiva)",
      resultadoTabela21.categoria,
      resultadoTabela21.gatilhos.map((g) => g.motivo).join("; "),
    ]);
  }

  let categoriaFinal = null, viaFinal = null, criterioFinal = null;
  if (candidatos.length > 0) {
    candidatos.sort((a, b) => ordemSeveridade.indexOf(a[1]) - ordemSeveridade.indexOf(b[1]));
    [viaFinal, categoriaFinal, criterioFinal] = candidatos[0];
  }

  return {
    classe_perigo: "corrosao_irritacao_pele",
    categoria: categoriaFinal,
    via_decisao: viaFinal,
    criterio: criterioFinal,
    somas_por_categoria: somas,
    somatorio_ponderado_cat1_cat2: _round(ponderado12, 4),
    somatorio_ponderado_cat1_cat2_cat3: _round(ponderado123, 4),
    detalhes_tabela20: detalhes,
    resultado_tabela21: resultadoTabela21,
  };
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

function _somarParaOlhos(ingredientes) {
  let somaCat1Combinada = 0.0;
  let somaCat2 = 0.0;
  let todosCat2Sao2b = true;
  let temAlgumCat2 = false;
  const detalhes = [];

  for (const ing of ingredientes) {
    if (!_relevante(ing) || ing.sem_perigo_pele_olhos) continue;

    const ehCat1Pele = ["1A", "1B", "1C", "1"].includes(ing.categoria_pele);
    const ehCat1Olhos = ing.categoria_olhos === "1";

    if (ehCat1Pele || ehCat1Olhos) {
      somaCat1Combinada += ing.concentracao; // contado uma única vez, por ingrediente
      detalhes.push({ nome: ing.nome, grupo: "Cat.1 pele e/ou olhos", concentracao: ing.concentracao });
    } else if (["2", "2A", "2B"].includes(ing.categoria_olhos)) {
      somaCat2 += ing.concentracao;
      temAlgumCat2 = true;
      if (ing.categoria_olhos !== "2B") todosCat2Sao2b = false;
      detalhes.push({ nome: ing.nome, grupo: `Olhos ${ing.categoria_olhos}`, concentracao: ing.concentracao });
    }
  }

  return {
    soma_cat1_combinada: somaCat1Combinada,
    soma_cat2: somaCat2,
    todos_cat2_sao_2b: todosCat2Sao2b && temAlgumCat2,
    detalhes,
  };
}

function _classificarOlhosTabela25(ingredientes) {
  const achados = [];
  for (const ing of ingredientes) {
    if (!_relevante(ing, 1.0) && !ing.relevante_abaixo_1pct) continue;

    if (ing.acido_ou_base_forte && ing.ph !== null && ing.ph !== undefined) {
      if (ing.ph <= 2 && ing.concentracao >= 1.0) {
        achados.push(["1", ing, "ácido pH ≤ 2, ≥1%"]);
      } else if (ing.ph >= 11.5 && ing.concentracao >= 1.0) {
        achados.push(["1", ing, "base pH ≥ 11,5, ≥1%"]);
      }
    }

    if (ing.nao_apto_aditividade) {
      if (ing.categoria_olhos === "1" && ing.concentracao >= 1.0) {
        achados.push(["1", ing, "corrosivo ocular não apto à aditividade, ≥1%"]);
      } else if (["2", "2A", "2B"].includes(ing.categoria_olhos) && ing.concentracao >= 3.0) {
        achados.push(["2", ing, "irritante ocular não apto à aditividade, ≥3%"]);
      }
    }
  }

  if (achados.length === 0) return null;

  const ordem = ["1", "2"];
  achados.sort((a, b) => ordem.indexOf(a[0]) - ordem.indexOf(b[0]));
  const categoriaMaisSevera = achados[0][0];
  return {
    categoria: categoriaMaisSevera,
    via: "Tabela 25 (não-aditiva / pH)",
    gatilhos: achados.map((a) => ({ nome: a[1].nome, motivo: a[2] })),
  };
}

/**
 * Classifica a mistura quanto a lesões oculares graves/irritação
 * ocular, combinando a abordagem aditiva (Tabela 24) com a abordagem
 * por pH/não-aditividade (Tabela 25).
 * @param {IngredientePeleOlhos[]} ingredientes
 */
export function classificarLesaoOcular(ingredientes) {
  const somas = _somarParaOlhos(ingredientes);
  const s1 = somas.soma_cat1_combinada;
  const s2 = somas.soma_cat2;
  const ponderado = 10 * s1 + s2;

  let resultadoTabela24 = null;

  if (s1 >= 3) {
    resultadoTabela24 = { categoria: "1", criterio: "soma (Cat.1 pele + Cat.1 olhos) ≥ 3%" };
  } else if (s1 >= 1) {
    // 1% <= s1 < 3%
    const cat2Default = somas.todos_cat2_sao_2b ? "2B" : "2A";
    resultadoTabela24 = { categoria: cat2Default, criterio: "soma (Cat.1 pele + Cat.1 olhos) entre 1% e <3%" };
  } else if (s2 >= 10) {
    const cat2Default = somas.todos_cat2_sao_2b ? "2B" : "2A";
    resultadoTabela24 = { categoria: cat2Default, criterio: "soma Categoria 2 ocular ≥ 10%" };
  } else if (ponderado >= 10) {
    const cat2Default = somas.todos_cat2_sao_2b ? "2B" : "2A";
    resultadoTabela24 = { categoria: cat2Default, criterio: "10×(Cat.1 pele+olhos) + Cat.2 ≥ 10%" };
  }

  const resultadoTabela25 = _classificarOlhosTabela25(ingredientes);

  const ordemSeveridade = ["1", "2A", "2", "2B"]; // 2A tratado como mais severo que 2B para desempate conservador
  const candidatos = [];
  if (resultadoTabela24) {
    candidatos.push(["Tabela 24 (aditiva)", resultadoTabela24.categoria, resultadoTabela24.criterio]);
  }
  if (resultadoTabela25) {
    candidatos.push([
      "Tabela 25 (pH / não-aditiva)",
      resultadoTabela25.categoria,
      resultadoTabela25.gatilhos.map((g) => g.motivo).join("; "),
    ]);
  }

  let categoriaFinal = null, viaFinal = null, criterioFinal = null;
  if (candidatos.length > 0) {
    const chaveSeveridade = (c) => {
      const idx = ordemSeveridade.indexOf(c[1]);
      return idx === -1 ? ordemSeveridade.length : idx;
    };
    candidatos.sort((a, b) => chaveSeveridade(a) - chaveSeveridade(b));
    [viaFinal, categoriaFinal, criterioFinal] = candidatos[0];
  }

  return {
    classe_perigo: "lesao_ocular",
    categoria: categoriaFinal,
    via_decisao: viaFinal,
    criterio: criterioFinal,
    soma_cat1_combinada: _round(s1, 4),
    soma_cat2: _round(s2, 4),
    somatorio_ponderado: _round(ponderado, 4),
    detalhes_tabela24: somas.detalhes,
    resultado_tabela25: resultadoTabela25,
  };
}
