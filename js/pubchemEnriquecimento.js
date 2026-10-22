/**
 * Enriquecimento via PubChem — complemento para substâncias sem entrada
 * no Anexo VI da ECHA.
 * ============================================================================
 *
 * Porte 1:1 de pubchem_enriquecimento.py.
 *
 * AVISO DE VALIDAÇÃO (igual ao do módulo original): a extração do PUG View
 * foi validada contra uma resposta mockada que reproduz o schema
 * documentado (ver `_testeOfflineComMock` no fim do arquivo); a chamada
 * HTTP real a pubchem.ncbi.nlm.nih.gov não pôde ser exercitada ao vivo no
 * ambiente de desenvolvimento. Diferente da versão Python — que era
 * bloqueada por política de rede do sandbox — esta versão roda DENTRO do
 * navegador do usuário final, então a chamada real (`fetch`) é feita pelo
 * próprio navegador dele; se a PubChem não enviar os cabeçalhos CORS
 * necessários, o navegador vai bloquear a resposta e cada chamada vira um
 * erro de rede tratado abaixo (nunca interrompe o restante do
 * enriquecimento). Teste em produção antes de confiar neste módulo; se o
 * schema da resposta tiver mudado, os pontos de ajuste são só
 * `_extrairSecaoGhs` e `_parseLinhasGhs`.
 *
 * Por que isso é "enriquecimento" e não fonte primária: a classificação
 * GHS que a PubChem expõe é um AGREGADO de notificações de terceiros.
 * Por isso este módulo NUNCA sobrescreve uma classificação já vinda do
 * Anexo VI, e quando há divergência registra o conflito para revisão
 * humana em vez de escolher silenciosamente.
 */

const PUG_REST_BASE = "https://pubchem.ncbi.nlm.nih.gov/rest/pug";
const PUG_VIEW_BASE = "https://pubchem.ncbi.nlm.nih.gov/rest/pug_view";

// PubChem pede no máximo 5 requisições/segundo — intervalo mínimo
// conservador entre chamadas.
const INTERVALO_MINIMO_ENTRE_CHAMADAS_MS = 250;

export class PubChemIndisponivel extends Error {}

function _sleep(ms) {
  return new Promise((resolve) => setTimeout(resolve, ms));
}

async function _get(url) {
  let resp;
  try {
    resp = await fetch(url);
  } catch (e) {
    throw new PubChemIndisponivel(`Falha ao consultar PubChem (${url}): ${e.message}`);
  }
  if (resp.status === 404) return {};
  if (!resp.ok) {
    throw new PubChemIndisponivel(`PubChem respondeu ${resp.status} para ${url}`);
  }
  try {
    return await resp.json();
  } catch (e) {
    throw new PubChemIndisponivel(`Resposta inválida da PubChem (${url}): ${e.message}`);
  }
}

function _extrairCid(respostaCid) {
  try {
    return respostaCid.IdentifierList.CID[0];
  } catch {
    return null;
  }
}

/** Resolve um número CAS para o CID (Compound ID) da PubChem. */
export async function casParaCid(cas) {
  const url = `${PUG_REST_BASE}/compound/name/${encodeURIComponent(cas)}/cids/JSON`;
  const dados = await _get(url);
  return _extrairCid(dados);
}

// ---------------------------------------------------------------------------
// Extração da seção "GHS Classification" do PUG View — mesmos marcadores
// textuais usados no parser do Anexo VI ("Skin Corr./Irrit.", "Eye
// Dam./Irrit.", "Acute Tox."), já que a convenção CLP/GHS é a mesma em
// ambas as fontes.
// ---------------------------------------------------------------------------

const _PADRAO_LINHA_GHS = /(H\d{3}\w{0,2})\s*\(([\d.]+)%\):.*?\[([^\]]+)\]/i;

function _extrairSecaoGhs(respostaPugView) {
  const linhas = [];

  function percorrer(no) {
    if (no && typeof no === "object" && !Array.isArray(no)) {
      if (no.TOCHeading === "GHS Classification") {
        for (const info of no.Information || []) {
          const valor = info.Value || {};
          for (const swm of valor.StringWithMarkup || []) {
            if (swm.String) linhas.push(swm.String);
          }
        }
      }
      for (const v of Object.values(no)) percorrer(v);
    } else if (Array.isArray(no)) {
      for (const item of no) percorrer(item);
    }
  }

  percorrer(respostaPugView);
  return linhas;
}

const _PADROES_CATEGORIA = [
  /acute\s+tox\.?\s*\d/i,
  /skin\s+corr\.?\s*1[abc]?/i,
  /skin\s+irrit\.?\s*\d/i,
  /eye\s+dam\.?\s*1/i,
  /eye\s+irrit\.?\s*2[ab]?/i,
];

function _parseLinhasGhs(linhas) {
  const resultados = [];
  for (const linha of linhas) {
    const m = _PADRAO_LINHA_GHS.exec(linha);
    if (!m) continue;
    const hCode = m[1].toUpperCase();
    const pct = parseFloat(m[2]);
    const colchete = m[3];

    let categoriaTexto = null;
    for (const padrao of _PADROES_CATEGORIA) {
      const m2 = padrao.exec(colchete);
      if (m2) {
        categoriaTexto = m2[0];
        break;
      }
    }

    if (categoriaTexto) {
      resultados.push({ h_code: hCode, categoria_texto: categoriaTexto, percentual_notificadores: pct });
    }
  }
  return resultados;
}

function _grupoDeCategoria(categoriaTexto) {
  const m = /^[a-z]+\.?\s*[a-z]*\.?/i.exec(categoriaTexto);
  return (m ? m[0] : categoriaTexto).trim().split(/\s+/)[0].toLowerCase();
}

/**
 * Busca a classificação GHS agregada da PubChem para um CAS. Não lança
 * exceção em caso de substância não encontrada — só quando a própria API
 * está inacessível (PubChemIndisponivel).
 * @returns {Promise<{cas:string, cid:?number, encontrado:boolean, classificacoes:object[], conflitos:string[], erro:?string}>}
 */
export async function buscarClassificacaoGhs(cas) {
  const cid = await casParaCid(cas);
  if (cid === null) {
    return { cas, cid: null, encontrado: false, classificacoes: [], conflitos: [], erro: null };
  }

  await _sleep(INTERVALO_MINIMO_ENTRE_CHAMADAS_MS);
  const url = `${PUG_VIEW_BASE}/data/compound/${cid}/JSON/?heading=GHS+Classification`;
  const dados = await _get(url);

  if (!dados || Object.keys(dados).length === 0) {
    return { cas, cid, encontrado: false, classificacoes: [], conflitos: [], erro: null };
  }

  const linhas = _extrairSecaoGhs(dados);
  const classificacoes = _parseLinhasGhs(linhas);

  const conflitos = [];
  const porGrupo = new Map();
  for (const c of classificacoes) {
    const grupo = _grupoDeCategoria(c.categoria_texto);
    if (!porGrupo.has(grupo)) porGrupo.set(grupo, new Set());
    porGrupo.get(grupo).add(c.categoria_texto);
  }
  for (const [grupo, categorias] of porGrupo.entries()) {
    if (categorias.size > 1) {
      conflitos.push(
        `Classificações divergentes reportadas para '${grupo}': ${JSON.stringify([...categorias].sort())} — ` +
          `usar a de maior percentual de notificadores e sinalizar para revisão.`
      );
    }
  }

  return { cas, cid, encontrado: true, classificacoes, conflitos, erro: null };
}

/**
 * Dentre as classificações de um determinado grupo (ex.: só as de "Acute
 * Tox."), devolve o texto da categoria com maior percentual de
 * notificadores.
 * @param {object[]} classificacoes
 * @param {RegExp} padraoPrefixo
 */
export function categoriaMaisFrequente(classificacoes, padraoPrefixo) {
  const candidatas = classificacoes.filter((c) => padraoPrefixo.test(c.categoria_texto));
  if (!candidatas.length) return null;
  candidatas.sort((a, b) => (b.percentual_notificadores || 0) - (a.percentual_notificadores || 0));
  return candidatas[0].categoria_texto;
}

// ---------------------------------------------------------------------------
// Teste offline com resposta mockada (schema real do PUG View) — mesmo
// mock do módulo Python, para validar a lógica de extração sem rede.
// Chame `_testeOfflineComMock()` manualmente (ex.: no console do
// navegador ou num script Node de teste) para conferir.
// ---------------------------------------------------------------------------

const _MOCK_PUG_VIEW_RESPONSE = {
  Record: {
    RecordType: "CID",
    RecordNumber: 3423265,
    Section: [
      {
        TOCHeading: "Safety and Hazards",
        Section: [
          {
            TOCHeading: "Hazards Identification",
            Section: [
              {
                TOCHeading: "GHS Classification",
                Information: [
                  {
                    Value: {
                      StringWithMarkup: [
                        { String: "H302 (60%): Harmful if swallowed [Warning Acute Tox. 4 - GHS Classification from ECHA C&L Notifications]" },
                        { String: "H302 (40%): Harmful if swallowed [Warning Acute Tox. 3 - GHS Classification from ECHA C&L Notifications]" },
                        { String: "H315 (100%): Causes skin irritation [Warning Skin Irrit. 2 - GHS Classification from ECHA C&L Notifications]" },
                        { String: "H319 (100%): Causes serious eye irritation [Warning Eye Irrit. 2A - GHS Classification from ECHA C&L Notifications]" },
                      ],
                    },
                  },
                ],
              },
            ],
          },
        ],
      },
    ],
  },
};

export function _testeOfflineComMock() {
  const linhas = _extrairSecaoGhs(_MOCK_PUG_VIEW_RESPONSE);
  if (linhas.length !== 4) throw new Error(`esperava 4 linhas, veio ${linhas.length}`);

  const classificacoes = _parseLinhasGhs(linhas);
  if (classificacoes.length !== 4) throw new Error(`esperava 4 classificações, veio ${classificacoes.length}`);

  const conflitos = [];
  const porGrupo = new Map();
  for (const c of classificacoes) {
    const grupo = _grupoDeCategoria(c.categoria_texto);
    if (!porGrupo.has(grupo)) porGrupo.set(grupo, new Set());
    porGrupo.get(grupo).add(c.categoria_texto);
  }
  for (const [grupo, categorias] of porGrupo.entries()) {
    if (categorias.size > 1) conflitos.push(grupo);
  }
  if (!conflitos.includes("acute")) throw new Error("deveria detectar conflito em Acute Tox. 3 vs 4");

  const maisFrequente = categoriaMaisFrequente(classificacoes, /acute\s+tox/i);
  if (maisFrequente !== "Acute Tox. 4") throw new Error(`esperava 'Acute Tox. 4' (60%), veio ${maisFrequente}`);

  console.log("Teste offline (mock do schema real do PUG View): OK");
  console.log(`  ${classificacoes.length} classificações extraídas, conflito detectado em: ${conflitos}`);
  console.log(`  Categoria de toxicidade aguda mais frequente: ${maisFrequente} (60% dos notificadores)`);
}
