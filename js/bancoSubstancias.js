/**
 * Banco de substâncias — schema, importador do Anexo VI (ECHA) e ponte com
 * o motor de cálculo de classificação.
 *
 * Porte 1:1 de banco_substancias.py / BancoSubstancias.php para rodar 100%
 * no navegador: SQLite -> IndexedDB, pandas -> SheetJS (biblioteca `xlsx`,
 * carregada via CDN na página), leitura de arquivo -> File API (o usuário
 * seleciona o .xlsx do Anexo VI direto no navegador; o arquivo NUNCA é
 * enviado a lugar nenhum, fica só na memória/IndexedDB local).
 *
 * Mesma observação de direitos autorais do projeto original: o .xlsx do
 * Anexo VI e o conteúdo da NBR não são distribuídos com este código — cada
 * usuário importa sua própria cópia, uma vez, localmente.
 */

import { ViaExposicao, criarIngrediente } from "./motorToxicidadeAguda.js";
import { criarIngredientePeleOlhos } from "./motorCorrosaoIrritacao.js";
import { buscarClassificacaoGhs, PubChemIndisponivel } from "./pubchemEnriquecimento.js";

const NOME_DB = "gerador_fds_substancias";
const VERSAO_DB = 1;

// ---------------------------------------------------------------------------
// Faixas de concentração da própria substância (não da mistura) — mesma
// lógica/regex do original.
// ---------------------------------------------------------------------------

const _PADRAO_FAIXA_UNICA = /\bC\s*(>=|<=|≥|≤|>|<)\s*([\d.,]+)\s*%/i;
const _PADRAO_FAIXA_DUPLA = /([\d.,]+)\s*%\s*(<=|≤|<)\s*C\s*(<=|≤|<)\s*([\d.,]+)\s*%/i;

function _num(texto) {
  return parseFloat(texto.replace(",", "."));
}

/**
 * Procura notação de faixa de concentração no nome/rótulo da linha do
 * Anexo VI. Devolve [faixa_min, faixa_min_incl, faixa_max, faixa_max_incl];
 * todos null se a linha não tiver faixa (aplica-se em qualquer concentração).
 */
export function extrairFaixaConcentracao(nomeQuimico) {
  if (typeof nomeQuimico !== "string") return [null, null, null, null];

  const m2 = _PADRAO_FAIXA_DUPLA.exec(nomeQuimico);
  if (m2) {
    return [_num(m2[1]), ["<=", "≤"].includes(m2[2]), _num(m2[4]), ["<=", "≤"].includes(m2[3])];
  }

  const m1 = _PADRAO_FAIXA_UNICA.exec(nomeQuimico);
  if (m1) {
    const op = m1[1];
    const val = _num(m1[2]);
    if (op === ">=" || op === "≥") return [val, true, null, null];
    if (op === ">") return [val, false, null, null];
    if (op === "<=" || op === "≤") return [null, null, val, true];
    if (op === "<") return [null, null, val, false];
  }

  return [null, null, null, null];
}

/**
 * True se `concentracao` satisfaz a faixa (null em min/max = sem limite
 * naquele lado — logo, uma linha sem faixa alguma sempre retorna true).
 */
export function faixaContem(concentracao, faixaMin, faixaMinIncl, faixaMax, faixaMaxIncl) {
  if (faixaMin !== null && faixaMin !== undefined) {
    const ok = faixaMinIncl ? concentracao >= faixaMin : concentracao > faixaMin;
    if (!ok) return false;
  }
  if (faixaMax !== null && faixaMax !== undefined) {
    const ok = faixaMaxIncl ? concentracao <= faixaMax : concentracao < faixaMax;
    if (!ok) return false;
  }
  return true;
}

// ---------------------------------------------------------------------------
// Helpers de IndexedDB (promisificação mínima, sem dependências externas)
// ---------------------------------------------------------------------------

function _reqToPromise(req) {
  return new Promise((resolve, reject) => {
    req.onsuccess = () => resolve(req.result);
    req.onerror = () => reject(req.error);
  });
}

function _txDone(tx) {
  return new Promise((resolve, reject) => {
    tx.oncomplete = () => resolve();
    tx.onerror = () => reject(tx.error);
    tx.onabort = () => reject(tx.error);
  });
}

function _abrirBanco(nomeDb) {
  return new Promise((resolve, reject) => {
    const req = indexedDB.open(nomeDb, VERSAO_DB);
    req.onupgradeneeded = () => {
      const db = req.result;
      if (!db.objectStoreNames.contains("substancias")) {
        db.createObjectStore("substancias", { keyPath: "cas" });
      }
      if (!db.objectStoreNames.contains("toxicidade_aguda")) {
        const s = db.createObjectStore("toxicidade_aguda", { keyPath: "id", autoIncrement: true });
        s.createIndex("cas", "cas", { unique: false });
      }
      if (!db.objectStoreNames.contains("pele_olhos")) {
        const s = db.createObjectStore("pele_olhos", { keyPath: "id", autoIncrement: true });
        s.createIndex("cas", "cas", { unique: false });
      }
      if (!db.objectStoreNames.contains("presumidos_sem_toxicidade_aguda")) {
        db.createObjectStore("presumidos_sem_toxicidade_aguda", { keyPath: "cas" });
      }
      if (!db.objectStoreNames.contains("presumidos_sem_perigo_pele_olhos")) {
        db.createObjectStore("presumidos_sem_perigo_pele_olhos", { keyPath: "cas" });
      }
    };
    req.onsuccess = () => resolve(req.result);
    req.onerror = () => reject(req.error);
  });
}

// ---------------------------------------------------------------------------
// Mapeamento de colunas / H-codes (idêntico ao original)
// ---------------------------------------------------------------------------

const MAPA_COLUNAS = {
  cas: ["cas no", "cas number", "cas"],
  ec: ["ec no", "ec number"],
  nome: ["international chemical identification", "chemical name", "substance name"],
  classificacao: ["hazard class and category code"],
  h_codes: ["classification hazard statement code", "hazard statement code"],
  scl: ["specific conc", "conc. limits", "m-factor", "m, scl, ate"],
};

const _H_PARA_VIA = {
  H300: ["oral", 1], H301: ["oral", 3], H302: ["oral", 4],
  H310: ["dermica", 1], H311: ["dermica", 3], H312: ["dermica", 4],
  H330: ["inalatoria_generica", 1], H331: ["inalatoria_generica", 3], H332: ["inalatoria_generica", 4],
};

const _H_ACUTE_PARA_VIA = {
  H300: "oral", H301: "oral", H302: "oral",
  H310: "dermica", H311: "dermica", H312: "dermica",
  H330: "inalatoria_generica", H331: "inalatoria_generica", H332: "inalatoria_generica",
};

function _acharColuna(colunas, chaves) {
  const colunasLower = colunas.map((c) => [c, String(c).toLowerCase()]);
  for (const chave of chaves) {
    for (const [original, lower] of colunasLower) {
      if (lower.includes(chave)) return original;
    }
  }
  return null;
}

function _extrairCategoriaAcuteTox(linhaClassificacao) {
  const m = /acute\s+tox\.?\s*(\d)/i.exec(linhaClassificacao || "");
  return m ? parseInt(m[1], 10) : null;
}

function _extrairSubcategoriaPeleCorr(linha) {
  const m = /skin\s+corr\.?\s*(1[abc]?)/i.exec(linha);
  return m ? m[1].toUpperCase() : "1";
}

function _extrairCategoriaPeleIrrit(linha) {
  const m = /skin\s+irrit\.?\s*(\d)/i.exec(linha);
  return m ? m[1] : "2";
}

function _extrairSubcategoriaOlhosIrrit(linha) {
  const m = /eye\s+irrit\.?\s*(2[ab]?)/i.exec(linha);
  return m ? m[1].toUpperCase() : "2";
}

/**
 * Retorna {resultados, avisos}, onde resultados é uma lista de
 * [via, categoria] extraída de uma célula de classificação + sua célula de
 * H-codes. Mesma estratégia de filtro-e-pareamento posicional do original.
 */
function _parseToxicidadeAguda(textoClassificacao, textoHCodes) {
  if (typeof textoClassificacao !== "string" || typeof textoHCodes !== "string") {
    return { resultados: [], avisos: [] };
  }

  const linhasAcuteTox = textoClassificacao
    .split(/\r?\n/)
    .map((l) => l.trim())
    .filter((l) => /acute\s+tox\.?\s*\d/i.test(l));

  const hCodesAcuteTox = textoHCodes.match(/H3(?:00|01|02|10|11|12|30|31|32)/g) || [];

  const avisos = [];
  const resultados = [];

  if (linhasAcuteTox.length !== hCodesAcuteTox.length) {
    if (linhasAcuteTox.length || hCodesAcuteTox.length) {
      avisos.push(
        `Contagem de 'Acute Tox.' (${linhasAcuteTox.length}) não bate com a ` +
          `contagem de H-codes de toxicidade aguda (${hCodesAcuteTox.length}) ` +
          `para classificação=${JSON.stringify(textoClassificacao)} / H=${JSON.stringify(textoHCodes)}. ` +
          `Pulado — requer conferência manual.`
      );
    }
    return { resultados: [], avisos };
  }

  for (let i = 0; i < linhasAcuteTox.length; i++) {
    const hCode = hCodesAcuteTox[i];
    if (!(hCode in _H_PARA_VIA)) continue;
    const [viaStr, categoriaBase] = _H_PARA_VIA[hCode];
    const categoria = _extrairCategoriaAcuteTox(linhasAcuteTox[i]) || categoriaBase;
    resultados.push([viaStr, categoria]);
  }

  return { resultados, avisos };
}

/**
 * Retorna {categoriaPele, categoriaOlhos, avisos}, extraídos da mesma
 * célula de classificação e de H-codes usada para toxicidade aguda.
 */
function _parsePeleOlhos(textoClassificacao, textoHCodes) {
  if (typeof textoClassificacao !== "string" || typeof textoHCodes !== "string") {
    return { categoriaPele: null, categoriaOlhos: null, avisos: [] };
  }

  const avisos = [];

  const linhasPele = textoClassificacao
    .split(/\r?\n/)
    .map((l) => l.trim())
    .filter((l) => /skin\s+(corr|irrit)\.?/i.test(l));
  const hPele = textoHCodes.match(/H31[45]/g) || [];

  let categoriaPele = null;
  if (linhasPele.length === hPele.length && linhasPele.length > 0) {
    const candidatosPele = [];
    for (let i = 0; i < linhasPele.length; i++) {
      const linha = linhasPele[i], h = hPele[i];
      if (h === "H314") candidatosPele.push(_extrairSubcategoriaPeleCorr(linha));
      else if (h === "H315") candidatosPele.push(_extrairCategoriaPeleIrrit(linha));
    }
    if (candidatosPele.length) {
      const ordem = ["1A", "1B", "1C", "1", "2", "3"];
      candidatosPele.sort((a, b) => {
        const ia = ordem.includes(a) ? ordem.indexOf(a) : ordem.length;
        const ib = ordem.includes(b) ? ordem.indexOf(b) : ordem.length;
        return ia - ib;
      });
      categoriaPele = candidatosPele[0];
    }
  } else if (linhasPele.length || hPele.length) {
    avisos.push(
      `Contagem de linhas 'Skin Corr./Irrit.' (${linhasPele.length}) não bate com ` +
        `H314/H315 (${hPele.length}) para classificação=${JSON.stringify(textoClassificacao)} / ` +
        `H=${JSON.stringify(textoHCodes)}. Pulado — requer conferência manual.`
    );
  }

  const linhasOlhos = textoClassificacao
    .split(/\r?\n/)
    .map((l) => l.trim())
    .filter((l) => /eye\s+(dam|irrit)\.?/i.test(l));
  const hOlhos = textoHCodes.match(/H31[89]/g) || [];

  let categoriaOlhos = null;
  if (linhasOlhos.length === hOlhos.length && linhasOlhos.length > 0) {
    const candidatosOlhos = [];
    for (let i = 0; i < linhasOlhos.length; i++) {
      const linha = linhasOlhos[i], h = hOlhos[i];
      if (h === "H318") candidatosOlhos.push("1");
      else if (h === "H319") candidatosOlhos.push(_extrairSubcategoriaOlhosIrrit(linha));
    }
    if (candidatosOlhos.length) {
      const ordem = ["1", "2A", "2", "2B"];
      candidatosOlhos.sort((a, b) => {
        const ia = ordem.includes(a) ? ordem.indexOf(a) : ordem.length;
        const ib = ordem.includes(b) ? ordem.indexOf(b) : ordem.length;
        return ia - ib;
      });
      categoriaOlhos = candidatosOlhos[0];
    }
  } else if (linhasOlhos.length || hOlhos.length) {
    avisos.push(
      `Contagem de linhas 'Eye Dam./Irrit.' (${linhasOlhos.length}) não bate com ` +
        `H318/H319 (${hOlhos.length}) para classificação=${JSON.stringify(textoClassificacao)} / ` +
        `H=${JSON.stringify(textoHCodes)}. Pulado — requer conferência manual.`
    );
  }

  return { categoriaPele, categoriaOlhos, avisos };
}

function _celulaParaTexto(v) {
  if (v === null || v === undefined) return null;
  const s = String(v).trim();
  return s === "" ? null : s;
}

function _hoje() {
  return new Date().toISOString().slice(0, 10);
}

export class BancoSubstancias {
  constructor(nomeDb = NOME_DB) {
    this.nomeDb = nomeDb;
    this.db = null;
  }

  /** Precisa ser chamado (e aguardado) antes de qualquer outro método. */
  async abrir() {
    this.db = await _abrirBanco(this.nomeDb);
    return this;
  }

  fechar() {
    if (this.db) this.db.close();
  }

  /** Apaga completamente o banco local (equivalente a remover o substancias.db). */
  static async apagar(nomeDb = NOME_DB) {
    return new Promise((resolve, reject) => {
      const req = indexedDB.deleteDatabase(nomeDb);
      req.onsuccess = () => resolve();
      req.onerror = () => reject(req.error);
    });
  }

  _tx(lojas, modo = "readonly") {
    return this.db.transaction(lojas, modo);
  }

  // -----------------------------------------------------------------
  // Inserção manual
  // -----------------------------------------------------------------

  async upsertSubstancia(cas, nome, fonte, ecNumber = null, fonteVersao = null) {
    const tx = this._tx(["substancias"], "readwrite");
    tx.objectStore("substancias").put({
      cas, ec_number: ecNumber, nome, fonte, fonte_versao: fonteVersao, data_importacao: _hoje(),
    });
    await _txDone(tx);
  }

  async marcarSemToxicidadeAguda(cas, nome, fonte = "MANUAL") {
    const tx = this._tx(["presumidos_sem_toxicidade_aguda"], "readwrite");
    tx.objectStore("presumidos_sem_toxicidade_aguda").put({ cas, nome, fonte });
    await _txDone(tx);
  }

  /** Uso manual/pontual (sem faixa): no máximo uma linha por (cas, via) para essa origem. */
  async upsertToxicidadeAguda(cas, via, { categoria = null, eta = null, estadoFisico = null, fonte = "MANUAL" } = {}) {
    const viaStr = typeof via === "string" ? via : via;
    const tx = this._tx(["toxicidade_aguda"], "readwrite");
    const store = tx.objectStore("toxicidade_aguda");
    const idx = store.index("cas");
    const existentes = await _reqToPromise(idx.getAll(cas));
    for (const row of existentes) {
      if (row.via === viaStr && row.faixa_min == null && row.faixa_max == null) {
        store.delete(row.id);
      }
    }
    store.add({
      cas, via: viaStr, categoria, eta, estado_fisico: estadoFisico,
      faixa_min: null, faixa_min_incl: null, faixa_max: null, faixa_max_incl: null,
      nome_variante: null, fonte,
    });
    await _txDone(tx);
  }

  /** Usado pela importação do Anexo VI: sempre insere uma nova linha, nunca substitui. */
  _inserirToxicidadeAgudaVariante(store, cas, viaStr, categoria, faixaMin, faixaMinIncl, faixaMax, faixaMaxIncl, nomeVariante, fonte) {
    store.add({
      cas, via: viaStr, categoria, eta: null, estado_fisico: null,
      faixa_min: faixaMin, faixa_min_incl: faixaMinIncl, faixa_max: faixaMax, faixa_max_incl: faixaMaxIncl,
      nome_variante: nomeVariante, fonte,
    });
  }

  async marcarSemPerigoPeleOlhos(cas, nome, fonte = "MANUAL") {
    const tx = this._tx(["presumidos_sem_perigo_pele_olhos"], "readwrite");
    tx.objectStore("presumidos_sem_perigo_pele_olhos").put({ cas, nome, fonte });
    await _txDone(tx);
  }

  async upsertPeleOlhos(cas, { categoriaPele = null, categoriaOlhos = null, ph = null, fonte = "MANUAL" } = {}) {
    const tx = this._tx(["pele_olhos"], "readwrite");
    const store = tx.objectStore("pele_olhos");
    const idx = store.index("cas");
    const existentes = await _reqToPromise(idx.getAll(cas));
    for (const row of existentes) {
      if (row.faixa_min == null && row.faixa_max == null) store.delete(row.id);
    }
    store.add({
      cas, categoria_pele: categoriaPele, categoria_olhos: categoriaOlhos, ph,
      faixa_min: null, faixa_min_incl: null, faixa_max: null, faixa_max_incl: null,
      nome_variante: null, fonte,
    });
    await _txDone(tx);
  }

  _inserirPeleOlhosVariante(store, cas, categoriaPele, categoriaOlhos, faixaMin, faixaMinIncl, faixaMax, faixaMaxIncl, nomeVariante, fonte) {
    store.add({
      cas, categoria_pele: categoriaPele, categoria_olhos: categoriaOlhos, ph: null,
      faixa_min: faixaMin, faixa_min_incl: faixaMinIncl, faixa_max: faixaMax, faixa_max_incl: faixaMaxIncl,
      nome_variante: nomeVariante, fonte,
    });
  }

  // -----------------------------------------------------------------
  // Importador do Anexo VI (ECHA) — a partir de um File (<input type=file>)
  // Requer a biblioteca SheetJS (global `XLSX`) carregada na página.
  // -----------------------------------------------------------------

  /**
   * @param {File} arquivo  arquivo .xlsx escolhido pelo usuário (nunca enviado a um servidor)
   * @param {Object} opcoes
   * @param {string|number} [opcoes.sheetName=0]
   * @param {number} [opcoes.headerRow=0]  linha (0-based) do cabeçalho real
   * @param {string} [opcoes.fonteVersao]
   */
  async importarAnexoVi(arquivo, { sheetName = 0, headerRow = 0, fonteVersao = null } = {}) {
    if (typeof XLSX === "undefined") {
      throw new Error("Biblioteca SheetJS (XLSX) não carregada. Inclua o script da CDN na página.");
    }

    const buffer = await arquivo.arrayBuffer();
    const wb = XLSX.read(buffer, { type: "array" });
    const nomeAba = typeof sheetName === "number" ? wb.SheetNames[sheetName] : sheetName;
    const planilha = wb.Sheets[nomeAba];
    if (!planilha) {
      throw new Error(`Aba '${sheetName}' não encontrada. Abas disponíveis: ${wb.SheetNames.join(", ")}`);
    }

    // range: headerRow faz o SheetJS usar essa linha como cabeçalho e
    // devolver um objeto por linha subsequente — equivalente a
    // pd.read_excel(header=header_row).
    const linhas = XLSX.utils.sheet_to_json(planilha, { range: headerRow, defval: null, raw: true });
    if (linhas.length === 0) {
      throw new Error("Nenhuma linha de dados encontrada após o cabeçalho informado.");
    }
    const colunas = Object.keys(linhas[0]);

    const colCas = _acharColuna(colunas, MAPA_COLUNAS.cas);
    const colNome = _acharColuna(colunas, MAPA_COLUNAS.nome);
    const colEc = _acharColuna(colunas, MAPA_COLUNAS.ec);
    const colClasse = _acharColuna(colunas, MAPA_COLUNAS.classificacao);
    const colH = _acharColuna(colunas, MAPA_COLUNAS.h_codes);

    const faltantes = [
      ["CAS", colCas], ["Nome", colNome], ["Classificação", colClasse], ["H-codes", colH],
    ].filter(([, c]) => c === null).map(([n]) => n);
    if (faltantes.length) {
      throw new Error(
        `Não consegui localizar as colunas: ${faltantes.join(", ")}. ` +
          `Colunas encontradas na planilha: ${colunas.join(", ")}. ` +
          `Ajuste MAPA_COLUNAS conforme o layout real do seu arquivo.`
      );
    }

    const versao = fonteVersao || `importado em ${_hoje()}`;

    // Idempotência: apaga TODAS as linhas de origem ECHA_ANEXO_VI antes de
    // reimportar. Cadastros MANUAIS (outra fonte) não são afetados.
    {
      const tx = this._tx(["toxicidade_aguda", "pele_olhos"], "readwrite");
      for (const nomeLoja of ["toxicidade_aguda", "pele_olhos"]) {
        const store = tx.objectStore(nomeLoja);
        const todos = await _reqToPromise(store.getAll());
        for (const row of todos) {
          if (typeof row.fonte === "string" && row.fonte.startsWith("ECHA_ANEXO_VI")) {
            store.delete(row.id);
          }
        }
      }
      await _txDone(tx);
    }

    const resumo = {
      linhas_lidas: linhas.length, substancias_gravadas: 0,
      linhas_sem_cas: 0, linhas_sem_toxicidade_aguda: 0,
      linhas_com_pele_ou_olhos: 0, cas_com_multiplas_linhas: 0,
      avisos_parser: [],
    };

    const tx = this._tx(["substancias", "toxicidade_aguda", "pele_olhos"], "readwrite");
    const storeSubstancias = tx.objectStore("substancias");
    const storeToxAguda = tx.objectStore("toxicidade_aguda");
    const storePeleOlhos = tx.objectStore("pele_olhos");

    const casContagemPorVia = new Map(); // "cas|via" -> contagem, para cas_com_multiplas_linhas

    for (const linha of linhas) {
      const casRaw = _celulaParaTexto(linha[colCas]);
      if (!casRaw || casRaw.toLowerCase() === "nan" || casRaw === "-") {
        resumo.linhas_sem_cas += 1;
        continue;
      }
      const cas = casRaw;
      const nome = _celulaParaTexto(linha[colNome]) || cas;
      const ec = colEc ? _celulaParaTexto(linha[colEc]) : null;

      storeSubstancias.put({
        cas, ec_number: ec, nome, fonte: "ECHA_ANEXO_VI", fonte_versao: versao, data_importacao: _hoje(),
      });
      resumo.substancias_gravadas += 1;

      const [faixaMin, faixaMinIncl, faixaMax, faixaMaxIncl] = extrairFaixaConcentracao(nome);

      const textoClasse = _celulaParaTexto(linha[colClasse]) || "";
      const textoH = _celulaParaTexto(linha[colH]) || "";

      const { resultados: pares, avisos: avisosLinha } = _parseToxicidadeAguda(textoClasse, textoH);
      if (avisosLinha.length) resumo.avisos_parser.push(...avisosLinha.map((a) => `CAS ${cas}: ${a}`));
      if (!pares.length) resumo.linhas_sem_toxicidade_aguda += 1;
      for (const [viaStr, categoria] of pares) {
        this._inserirToxicidadeAgudaVariante(
          storeToxAguda, cas, viaStr, categoria, faixaMin, faixaMinIncl, faixaMax, faixaMaxIncl,
          nome, `ECHA_ANEXO_VI (${versao})`
        );
        const chave = `${cas}|${viaStr}`;
        casContagemPorVia.set(chave, (casContagemPorVia.get(chave) || 0) + 1);
      }

      const { categoriaPele: catPele, categoriaOlhos: catOlhos, avisos: avisosPeleOlhos } =
        _parsePeleOlhos(textoClasse, textoH);
      if (avisosPeleOlhos.length) resumo.avisos_parser.push(...avisosPeleOlhos.map((a) => `CAS ${cas}: ${a}`));
      if (catPele !== null || catOlhos !== null) {
        resumo.linhas_com_pele_ou_olhos += 1;
        this._inserirPeleOlhosVariante(
          storePeleOlhos, cas, catPele, catOlhos, faixaMin, faixaMinIncl, faixaMax, faixaMaxIncl,
          nome, `ECHA_ANEXO_VI (${versao})`
        );
      }
    }

    await _txDone(tx);

    resumo.cas_com_multiplas_linhas = [...casContagemPorVia.values()].filter((n) => n > 1).length;

    return resumo;
  }

  // -----------------------------------------------------------------
  // Ponte com o motor: monta os Ingrediente(...) por via, a partir da
  // fórmula informada pelo usuário na tela (CAS + concentração).
  // -----------------------------------------------------------------

  /**
   * @param {{cas:string, nome?:string, concentracao:number}[]} formula
   * @param {"liquido"|"solido_pulverulento"} estadoFisicoProduto
   * @returns {Promise<{ingredientesPorVia: Object<string, object[]>, avisos: string[]}>}
   */
  async montarIngredientesPorVia(formula, estadoFisicoProduto) {
    if (!["liquido", "solido_pulverulento"].includes(estadoFisicoProduto)) {
      throw new Error('estadoFisicoProduto deve ser "liquido" ou "solido_pulverulento"');
    }

    const viaInalatoriaRelevante =
      estadoFisicoProduto === "liquido" ? ViaExposicao.INALATORIA_VAPORES : ViaExposicao.INALATORIA_POEIRAS_NEVOAS;
    const viasACalcular = [ViaExposicao.ORAL, ViaExposicao.DERMICA, viaInalatoriaRelevante];

    const avisos = [];
    const ingredientesPorVia = {};
    for (const via of viasACalcular) ingredientesPorVia[via] = [];

    const txLeitura = this._tx(["presumidos_sem_toxicidade_aguda", "toxicidade_aguda"], "readonly");
    const storePresumidos = txLeitura.objectStore("presumidos_sem_toxicidade_aguda");
    const storeTox = txLeitura.objectStore("toxicidade_aguda");
    const idxTox = storeTox.index("cas");

    for (const item of formula) {
      const cas = item.cas;
      const nome = item.nome || cas;
      const concentracao = item.concentracao;

      const presumidoSeguro = await _reqToPromise(storePresumidos.get(cas));
      if (presumidoSeguro) {
        for (const via of viasACalcular) {
          ingredientesPorVia[via].push(
            criarIngrediente({ nome, cas, concentracao, sem_toxicidade_aguda: true })
          );
        }
        continue;
      }

      const linhas = await _reqToPromise(idxTox.getAll(cas));

      if (!linhas.length) {
        avisos.push(
          `'${nome}' (CAS ${cas}) não tem entrada de toxicidade aguda no banco ` +
            `(nem no Anexo VI, nem cadastro manual). Ele entrará no cálculo como ` +
            `ETA desconhecida em todas as vias — se a concentração for ≥ 1%, ` +
            `nenhuma via terá ETA definitiva até você complementar o dado.`
        );
        for (const via of viasACalcular) {
          ingredientesPorVia[via].push(criarIngrediente({ nome, cas, concentracao }));
        }
        continue;
      }

      const linhasPorVia = new Map();
      for (const l of linhas) {
        const via = l.via === "inalatoria_generica" ? viaInalatoriaRelevante : l.via;
        if (!viasACalcular.includes(via)) continue;
        if (!linhasPorVia.has(via)) linhasPorVia.set(via, []);
        linhasPorVia.get(via).push(l);
      }

      const viasPresentes = new Set();
      for (const [via, candidatas] of linhasPorVia.entries()) {
        let categoria, eta;
        if (candidatas.length === 1) {
          categoria = candidatas[0].categoria;
          eta = candidatas[0].eta;
        } else {
          const aplicaveis = candidatas.filter((c) =>
            faixaContem(concentracao, c.faixa_min, c.faixa_min_incl, c.faixa_max, c.faixa_max_incl)
          );
          if (aplicaveis.length === 1) {
            categoria = aplicaveis[0].categoria;
            eta = aplicaveis[0].eta;
          } else {
            const comCategoria = candidatas.filter((c) => c.categoria !== null && c.categoria !== undefined);
            const escolhida = comCategoria.length
              ? comCategoria.reduce((min, c) => (c.categoria < min.categoria ? c : min))
              : candidatas[0];
            categoria = escolhida.categoria;
            eta = escolhida.eta;
            const variantes = candidatas
              .map((c) => `${c.nome_variante || "(sem nome de variante)"} → Categoria ${c.categoria}`)
              .join("; ");
            avisos.push(
              `'${nome}' (CAS ${cas}) tem ${candidatas.length} entradas diferentes no Anexo VI ` +
                `para toxicidade aguda (${via}), e a concentração informada ` +
                `(${concentracao}%) não identificou uma única faixa aplicável com ` +
                `segurança: ${variantes}. Usada a mais severa (Categoria ${categoria}) ` +
                `por precaução — confirme manualmente qual variante corresponde à ` +
                `matéria-prima real antes de finalizar a FDS.`
            );
          }
        }

        viasPresentes.add(via);
        ingredientesPorVia[via].push(criarIngrediente({ nome, cas, concentracao, eta, categoria }));
      }

      for (const via of viasACalcular) {
        if (!viasPresentes.has(via)) {
          ingredientesPorVia[via].push(criarIngrediente({ nome, cas, concentracao }));
        }
      }
    }

    return { ingredientesPorVia, avisos };
  }

  /**
   * @param {{cas:string, nome?:string, concentracao:number}[]} formula
   * @returns {Promise<{ingredientes: object[], avisos: string[]}>}
   */
  async montarIngredientesPeleOlhos(formula) {
    const ordemPele = { "1A": 0, "1B": 1, "1C": 2, "1": 3, "2": 4, "3": 5 };
    const ordemOlhos = { "1": 0, "2A": 1, "2B": 2, "2": 3 };

    const avisos = [];
    const ingredientes = [];

    const tx = this._tx(["presumidos_sem_perigo_pele_olhos", "pele_olhos"], "readonly");
    const storePresumidos = tx.objectStore("presumidos_sem_perigo_pele_olhos");
    const storePeleOlhos = tx.objectStore("pele_olhos");
    const idxPeleOlhos = storePeleOlhos.index("cas");

    for (const item of formula) {
      const cas = item.cas;
      const nome = item.nome || cas;
      const concentracao = item.concentracao;

      const presumidoSeguro = await _reqToPromise(storePresumidos.get(cas));
      if (presumidoSeguro) {
        ingredientes.push(criarIngredientePeleOlhos({ nome, cas, concentracao, sem_perigo_pele_olhos: true }));
        continue;
      }

      const todas = await _reqToPromise(idxPeleOlhos.getAll(cas));
      const candidatas = todas.filter((c) => !(c.categoria_pele == null && c.categoria_olhos == null));

      if (!candidatas.length) {
        avisos.push(
          `'${nome}' (CAS ${cas}) não tem classificação de pele/olhos no banco ` +
            `(nem no Anexo VI, nem cadastro manual). Ele NÃO contribuirá para o ` +
            `cálculo de corrosão/irritação — se for um componente relevante ` +
            `(ex.: ≥1%), complemente o dado antes de considerar o resultado final.`
        );
        ingredientes.push(criarIngredientePeleOlhos({ nome, cas, concentracao }));
        continue;
      }

      let categoriaPele, categoriaOlhos, ph;
      if (candidatas.length === 1) {
        categoriaPele = candidatas[0].categoria_pele;
        categoriaOlhos = candidatas[0].categoria_olhos;
        ph = candidatas[0].ph;
      } else {
        const aplicaveis = candidatas.filter((c) =>
          faixaContem(concentracao, c.faixa_min, c.faixa_min_incl, c.faixa_max, c.faixa_max_incl)
        );
        if (aplicaveis.length === 1) {
          categoriaPele = aplicaveis[0].categoria_pele;
          categoriaOlhos = aplicaveis[0].categoria_olhos;
          ph = aplicaveis[0].ph;
        } else {
          const comPele = candidatas.filter((c) => c.categoria_pele !== null && c.categoria_pele in ordemPele);
          const comOlhos = candidatas.filter((c) => c.categoria_olhos !== null && c.categoria_olhos in ordemOlhos);
          const escolhidaPele = comPele.length
            ? comPele.reduce((min, c) => (ordemPele[c.categoria_pele] < ordemPele[min.categoria_pele] ? c : min))
            : null;
          const escolhidaOlhos = comOlhos.length
            ? comOlhos.reduce((min, c) => (ordemOlhos[c.categoria_olhos] < ordemOlhos[min.categoria_olhos] ? c : min))
            : null;

          categoriaPele = escolhidaPele ? escolhidaPele.categoria_pele : null;
          categoriaOlhos = escolhidaOlhos ? escolhidaOlhos.categoria_olhos : null;
          ph = escolhidaPele ? escolhidaPele.ph : null;
          if (ph === null && escolhidaOlhos !== null) ph = escolhidaOlhos.ph;

          const variantes = candidatas
            .map((c) => `${c.nome_variante || "(sem nome de variante)"} → pele ${c.categoria_pele || "—"} / olhos ${c.categoria_olhos || "—"}`)
            .join("; ");
          avisos.push(
            `'${nome}' (CAS ${cas}) tem ${candidatas.length} entradas diferentes no Anexo VI ` +
              `para pele/olhos, e a concentração informada (${concentracao}%) não ` +
              `identificou uma única faixa aplicável com segurança: ${variantes}. ` +
              `Usada a combinação mais severa (pele ${categoriaPele || "—"} / ` +
              `olhos ${categoriaOlhos || "—"}) por precaução — confirme manualmente ` +
              `qual variante corresponde à matéria-prima real antes de finalizar a FDS.`
          );
        }
      }

      ingredientes.push(
        criarIngredientePeleOlhos({ nome, cas, concentracao, categoria_pele: categoriaPele, categoria_olhos: categoriaOlhos, ph })
      );
    }

    return { ingredientes, avisos };
  }

  // -----------------------------------------------------------------
  // Enriquecimento via PubChem — só preenche LACUNAS, nunca sobrescreve
  // dados já vindos do Anexo VI (ver pubchemEnriquecimento.js para o
  // aviso de validação sobre CORS/disponibilidade real da API a partir
  // do navegador do usuário final).
  // -----------------------------------------------------------------

  /**
   * @param {string[]} casLista
   * @returns {Promise<{consultadas:number, enriquecidas_toxicidade_aguda:number, enriquecidas_pele_olhos:number, sem_dado_na_pubchem:string[], conflitos:string[], erros_api:string[]}>}
   */
  async enriquecerFaltantesComPubchem(casLista) {
    const resumo = {
      consultadas: 0, enriquecidas_toxicidade_aguda: 0,
      enriquecidas_pele_olhos: 0, sem_dado_na_pubchem: [],
      conflitos: [], erros_api: [],
    };

    for (const cas of casLista) {
      const txCheck = this._tx(["toxicidade_aguda", "pele_olhos"], "readonly");
      const idxTox = txCheck.objectStore("toxicidade_aguda").index("cas");
      const idxPele = txCheck.objectStore("pele_olhos").index("cas");
      const linhasTox = await _reqToPromise(idxTox.getAll(cas));
      const linhasPele = await _reqToPromise(idxPele.getAll(cas));
      const jaTemToxicidade = linhasTox.some((r) => typeof r.fonte === "string" && r.fonte.startsWith("ECHA_ANEXO_VI"));
      const jaTemPeleOlhos = linhasPele.some((r) => typeof r.fonte === "string" && r.fonte.startsWith("ECHA_ANEXO_VI"));

      if (jaTemToxicidade && jaTemPeleOlhos) continue; // já coberto pelo Anexo VI

      resumo.consultadas += 1;
      let resultado;
      try {
        resultado = await buscarClassificacaoGhs(cas);
      } catch (e) {
        if (e instanceof PubChemIndisponivel) {
          resumo.erros_api.push(`CAS ${cas}: ${e.message}`);
          continue;
        }
        throw e;
      }

      if (!resultado.encontrado || !resultado.classificacoes.length) {
        resumo.sem_dado_na_pubchem.push(cas);
        continue;
      }

      if (resultado.conflitos.length) {
        resumo.conflitos.push(...resultado.conflitos.map((c) => `CAS ${cas}: ${c}`));
      }

      if (!jaTemToxicidade) {
        for (const [hCode, viaStr] of Object.entries(_H_ACUTE_PARA_VIA)) {
          const candidatas = resultado.classificacoes.filter((c) => c.h_code.toUpperCase() === hCode);
          if (!candidatas.length) continue;
          candidatas.sort((a, b) => (b.percentual_notificadores || 0) - (a.percentual_notificadores || 0));
          const melhor = candidatas[0];
          const categoria = _extrairCategoriaAcuteTox(melhor.categoria_texto);
          if (categoria === null) continue;
          await this.upsertToxicidadeAguda(cas, viaStr, {
            categoria, fonte: `PUBCHEM (${(melhor.percentual_notificadores || 0).toFixed(0)}% dos notificadores)`,
          });
          resumo.enriquecidas_toxicidade_aguda += 1;
        }
      }

      if (!jaTemPeleOlhos) {
        let catPele = null, catOlhos = null, pctRef = 0;

        const candidatasPele = resultado.classificacoes.filter((c) => /^skin\s+(corr|irrit)/i.test(c.categoria_texto));
        if (candidatasPele.length) {
          candidatasPele.sort((a, b) => (b.percentual_notificadores || 0) - (a.percentual_notificadores || 0));
          const melhor = candidatasPele[0];
          catPele = melhor.h_code.toUpperCase() === "H314"
            ? _extrairSubcategoriaPeleCorr(melhor.categoria_texto)
            : _extrairCategoriaPeleIrrit(melhor.categoria_texto);
          pctRef = melhor.percentual_notificadores || 0;
        }

        const candidatasOlhos = resultado.classificacoes.filter((c) => /^eye\s+(dam|irrit)/i.test(c.categoria_texto));
        if (candidatasOlhos.length) {
          candidatasOlhos.sort((a, b) => (b.percentual_notificadores || 0) - (a.percentual_notificadores || 0));
          const melhor = candidatasOlhos[0];
          catOlhos = melhor.h_code.toUpperCase() === "H318" ? "1" : _extrairSubcategoriaOlhosIrrit(melhor.categoria_texto);
          if (!candidatasPele.length) pctRef = melhor.percentual_notificadores || 0;
        }

        if (catPele || catOlhos) {
          await this.upsertPeleOlhos(cas, {
            categoriaPele: catPele, categoriaOlhos: catOlhos,
            fonte: `PUBCHEM (${pctRef.toFixed(0)}% dos notificadores)`,
          });
          resumo.enriquecidas_pele_olhos += 1;
        }
      }
    }

    return resumo;
  }

  // -----------------------------------------------------------------
  // Consultas auxiliares (para a tela: listar substâncias cadastradas etc.)
  // -----------------------------------------------------------------

  async listarSubstancias() {
    const tx = this._tx(["substancias"], "readonly");
    return _reqToPromise(tx.objectStore("substancias").getAll());
  }

  async contarSubstancias() {
    const tx = this._tx(["substancias"], "readonly");
    return _reqToPromise(tx.objectStore("substancias").count());
  }

  /** Todas as linhas de toxicidade_aguda para um CAS (classificação intrínseca da matéria-prima, uso informativo — ex.: gerador de FDS, Seção 3). */
  async obterToxicidadeAgudaPorCas(cas) {
    const tx = this._tx(["toxicidade_aguda"], "readonly");
    return _reqToPromise(tx.objectStore("toxicidade_aguda").index("cas").getAll(cas));
  }

  /** Todas as linhas de pele_olhos para um CAS (classificação intrínseca da matéria-prima, uso informativo). */
  async obterPeleOlhosPorCas(cas) {
    const tx = this._tx(["pele_olhos"], "readonly");
    return _reqToPromise(tx.objectStore("pele_olhos").index("cas").getAll(cas));
  }
}
