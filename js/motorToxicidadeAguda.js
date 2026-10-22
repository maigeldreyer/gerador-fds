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
 * Este módulo NÃO decide a classificação final de nenhuma classe de
 * perigo além de toxicidade aguda. É uma peça do motor de cálculo maior
 * (um módulo por classe de perigo).
 *
 * Porte 1:1 de motor_toxicidade_aguda.py — mesma lógica, mesmos nomes de
 * campo (em português, como no original) para manter rastreabilidade.
 */

export const ViaExposicao = Object.freeze({
  ORAL: "oral",
  DERMICA: "dermica",
  INALATORIA_GASES: "inalatoria_gases", // ppmV
  INALATORIA_VAPORES: "inalatoria_vapores", // mg/L
  INALATORIA_POEIRAS_NEVOAS: "inalatoria_poeiras_nevoas", // mg/L
});

// ---------------------------------------------------------------------------
// Tabela 16 — limites de categoria por via de exposição (NBR 14725:2023)
// Cada array é [limite_superior_categoria_1, ..., limite_superior_categoria_4, cat5_ou_null]
// Categoria 5 vai até o teto indicado; acima disso, não classificado (NC).
// ---------------------------------------------------------------------------

const _LIMITES_CATEGORIA = {
  [ViaExposicao.ORAL]: [5, 50, 300, 2000, 5000],
  [ViaExposicao.DERMICA]: [50, 200, 1000, 2000, 5000],
  [ViaExposicao.INALATORIA_GASES]: [100, 500, 2500, 20000, null], // cat.5 sem valor numérico p/ gases
  [ViaExposicao.INALATORIA_VAPORES]: [0.5, 2.0, 10.0, 20.0, null],
  [ViaExposicao.INALATORIA_POEIRAS_NEVOAS]: [0.05, 0.5, 1.0, 5.0, null],
};

// ---------------------------------------------------------------------------
// Tabela 17 — valores de conversão de categoria/faixa para ETA estimada,
// usados quando não há DL50/CL50 exato do ingrediente (só a categoria).
// ---------------------------------------------------------------------------

const _CONVERSAO_ETA = {
  [ViaExposicao.ORAL]: [0.5, 5, 100, 500, 2500],
  [ViaExposicao.DERMICA]: [5, 50, 300, 1100, 2500],
  [ViaExposicao.INALATORIA_GASES]: [10, 100, 700, 4500, null],
  [ViaExposicao.INALATORIA_VAPORES]: [0.05, 0.5, 3, 11, null],
  [ViaExposicao.INALATORIA_POEIRAS_NEVOAS]: [0.005, 0.05, 0.5, 1.5, null],
};

// Concentração mínima acima da qual um ingrediente sem nenhum dado de
// toxicidade aguda invalida uma ETA definitiva para a mistura (5.3.1.7.2).
export const LIMITE_INGREDIENTE_DESCONHECIDO = 1.0; // % m/m ou v/v

/**
 * @typedef {Object} Ingrediente
 * @property {string} nome
 * @property {?string} cas
 * @property {number} concentracao   // % no produto final (m/m ou v/v conforme via)
 * @property {?number} [eta]         // DL50/CL50 ou ETA já conhecida do ingrediente
 * @property {?number} [categoria]   // usada só se eta for null (via Tabela 17)
 * @property {boolean} [sem_toxicidade_aguda] // ex.: água, açúcar — ignorado no somatório
 */

/** Cria um ingrediente com os valores-padrão do dataclass original. */
export function criarIngrediente({
  nome,
  cas = null,
  concentracao,
  eta = null,
  categoria = null,
  sem_toxicidade_aguda = false,
}) {
  return { nome, cas, concentracao, eta, categoria, sem_toxicidade_aguda };
}

/**
 * Classifica um valor de ETA numa categoria de 1 a 5, conforme a Tabela 16.
 * Retorna null se o valor estiver acima do teto de Categoria 5 (não classificado).
 * @param {number} eta
 * @param {string} via
 * @returns {?number}
 */
export function categoriaPorEta(eta, via) {
  const limites = _LIMITES_CATEGORIA[via];
  for (let i = 0; i < limites.length; i++) {
    const limite = limites[i];
    if (limite === null) continue;
    if (eta <= limite) return i + 1;
  }
  return null; // acima do maior limite definido -> não classificado (NC)
}

/**
 * Resolve a ETA de um ingrediente individual:
 * 1) usa o DL50/CL50 (ou ETA) direto, se fornecido;
 * 2) senão, converte a partir da categoria conhecida, via Tabela 17;
 * 3) senão, retorna null (dado ausente).
 * @param {Ingrediente} ing
 * @param {string} via
 * @returns {?number}
 */
export function etaDoIngrediente(ing, via) {
  if (ing.sem_toxicidade_aguda) return null; // ignorado no somatório por definição (5.3.1.7.1-b)
  if (ing.eta !== null && ing.eta !== undefined) return ing.eta;
  if (ing.categoria !== null && ing.categoria !== undefined) {
    const tabela = _CONVERSAO_ETA[via];
    const idx = ing.categoria - 1;
    if (idx >= 0 && idx < tabela.length && tabela[idx] !== null) {
      return tabela[idx];
    }
  }
  return null;
}

function _round(valor, casas) {
  const fator = 10 ** casas;
  return Math.round((valor + Number.EPSILON) * fator) / fator;
}

/**
 * Classifica a mistura para UMA via de exposição, aplicando a equação de
 * aditividade de 5.3.1.7.1:
 *
 *     100 / ETA_mistura = soma( Ci / ETAi )   para todo ingrediente i
 *                                               com ETA conhecida
 *
 * Retorna um objeto com o resultado e a rastreabilidade do cálculo,
 * em vez de só a categoria — importante para auditoria posterior.
 * @param {Ingrediente[]} ingredientes
 * @param {string} via
 */
export function classificarToxicidadeAguda(ingredientes, via) {
  let somaCiSobreEtai = 0.0;
  let concentracaoDesconhecida = 0.0;
  let concentracaoConsiderada = 0.0;
  const detalhes = [];

  for (const ing of ingredientes) {
    const etaI = etaDoIngrediente(ing, via);

    if (ing.sem_toxicidade_aguda) {
      detalhes.push({ nome: ing.nome, status: "ignorado (sem toxicidade aguda conhecida)" });
      continue;
    }

    if (etaI === null) {
      concentracaoDesconhecida += ing.concentracao;
      detalhes.push({ nome: ing.nome, status: "ETA desconhecida" });
      continue;
    }

    somaCiSobreEtai += ing.concentracao / etaI;
    concentracaoConsiderada += ing.concentracao;
    detalhes.push({
      nome: ing.nome,
      concentracao: ing.concentracao,
      eta_usada: etaI,
      contribuicao: ing.concentracao / etaI,
    });
  }

  const resultado = {
    via,
    detalhes,
    concentracao_com_eta_conhecida: _round(concentracaoConsiderada, 4),
    concentracao_eta_desconhecida: _round(concentracaoDesconhecida, 4),
  };

  // Regra 5.3.1.7.2: ingrediente sem qualquer dado, em concentração >= 1%,
  // impede ETA definitiva da mistura para essa via.
  if (concentracaoDesconhecida >= LIMITE_INGREDIENTE_DESCONHECIDO) {
    return {
      ...resultado,
      eta_mistura: null,
      categoria: null,
      eta_definitiva: false,
      declaracao_obrigatoria:
        `${concentracaoDesconhecida.toFixed(2)}% da mistura consiste em ` +
        `ingrediente(s) com toxicidade aguda (${via}) desconhecida.`,
    };
  }

  if (somaCiSobreEtai <= 0) {
    // Nenhum ingrediente com toxicidade aguda relevante
    return {
      ...resultado,
      eta_mistura: null,
      categoria: null,
      eta_definitiva: true,
      declaracao_obrigatoria: null,
    };
  }

  const etaMistura = 100.0 / somaCiSobreEtai;
  const categoria = categoriaPorEta(etaMistura, via);

  return {
    ...resultado,
    eta_mistura: _round(etaMistura, 4),
    categoria,
    eta_definitiva: true,
    declaracao_obrigatoria: null,
  };
}

/**
 * Conveniência: roda o cálculo para cada via de exposição informada e
 * devolve o detalhamento por via. A lista de ingredientes pode (e
 * normalmente deve) ser diferente por via, já que nem todo ingrediente
 * tem DL50 oral E dérmico E inalatório.
 * @param {Object<string, Ingrediente[]>} ingredientesPorVia  mapa via -> lista
 */
export function classificarTodasAsVias(ingredientesPorVia) {
  const resultados = {};
  for (const [via, ingredientes] of Object.entries(ingredientesPorVia)) {
    resultados[via] = classificarToxicidadeAguda(ingredientes, via);
  }
  return resultados;
}
