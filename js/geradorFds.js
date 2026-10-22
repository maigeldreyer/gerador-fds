/**
 * Gerador de FDS completa (16 seções, ABNT NBR 14725:2023) — geração de PDF
 * ===========================================================================
 *
 * Porte 1:1 de gerador_fds.py / GeradorFds.php para rodar 100% no navegador.
 *
 * Este módulo NÃO reimplementa nenhuma regra de classificação (isso já é
 * feito por motorToxicidadeAguda.js / motorCorrosaoIrritacao.js). Ele:
 *   1. Deriva pictogramas, palavra de advertência e frases H/P a partir das
 *      categorias JÁ CALCULADAS por esses motores (`derivarRotuloGhs`).
 *   2. Preenche as seções que não vêm de cálculo com FRASES PADRÃO,
 *      parametrizadas pela severidade calculada e por campos opcionais que
 *      o usuário pode preencher para sobrescrever o texto genérico.
 *   3. Monta a estrutura completa das 16 seções e gera o PDF final no
 *      layout de duas colunas (rótulo | valor), estilo Fosfeed/Safeeds —
 *      agora com jsPDF + jspdf-autotable em vez de reportlab, para rodar
 *      inteiramente no navegador do usuário (sem servidor).
 *
 * IMPORTANTE (mesma limitação assumida do original, não escondida): classes
 * de perigo que dependem de ENSAIO em vez de cálculo por composição NÃO são
 * calculadas por este sistema. Elas só aparecem na FDS se o usuário
 * informar manualmente via os campos extras.
 */

// ---------------------------------------------------------------------------
// Carregamento dos dados tabulares (h_codes, p_codes, mapas) — mesmo
// arquivo dados_fds.json do projeto original, servido como asset estático.
// ---------------------------------------------------------------------------

let _dadosFdsCache = null;

/** Carrega (e cacheia) o conteúdo de data/dados_fds.json. */
export async function carregarDadosFds(url = "./data/dados_fds.json") {
  if (_dadosFdsCache) return _dadosFdsCache;
  const resp = await fetch(url);
  if (!resp.ok) throw new Error(`Não foi possível carregar ${url} (HTTP ${resp.status})`);
  _dadosFdsCache = await resp.json();
  return _dadosFdsCache;
}

// Categorias que disparam o pictograma de caveira (toxicidade aguda 1-3)
const _CATEGORIAS_CAVEIRA = new Set([1, 2, 3]);
const _CATEGORIAS_EXCLAMACAO_TOX = new Set([4]);
const _SUBCATEGORIAS_PELE_CORROSIVAS = new Set(["1A", "1B", "1C", "1"]);
const _SUBCATEGORIAS_PELE_IRRITANTES = new Set(["2", "3"]);
const _SUBCATEGORIAS_OLHOS_GRAVES = new Set(["1"]);
const _SUBCATEGORIAS_OLHOS_IRRITANTES = new Set(["2A", "2B", "2"]);

function _viaParaChaveH(via) {
  if (via === "oral") return "toxicidade_oral";
  if (via === "dermica") return "toxicidade_dermica";
  return "toxicidade_inalatoria";
}

/**
 * A partir dos resultados JÁ CALCULADOS pelos motores, deriva códigos H/P,
 * pictogramas, palavra de advertência e flags de severidade.
 * @param {Object<string,object>} resultadoToxicidadeAguda
 * @param {?object} resultadoPele
 * @param {?object} resultadoOlhos
 * @param {object} dadosFds  retorno de carregarDadosFds()
 */
export function derivarRotuloGhs(resultadoToxicidadeAguda, resultadoPele, resultadoOlhos, dadosFds) {
  const { h_codes: H_CODES, p_codes: P_CODES, mapa_categoria_h: MAPA_CATEGORIA_H, mapa_h_para_p: MAPA_H_PARA_P } = dadosFds;

  const codigosH = [];
  const categoriasAgudas = {};

  for (const [via, resultado] of Object.entries(resultadoToxicidadeAguda || {})) {
    const categoria = resultado.categoria;
    if (categoria === null || categoria === undefined) continue;
    const chave = _viaParaChaveH(via);
    const h = MAPA_CATEGORIA_H[chave][String(categoria)];
    if (h && !codigosH.includes(h)) codigosH.push(h);
    categoriasAgudas[via] = categoria;
  }

  const categoriaPele = (resultadoPele || {}).categoria;
  if (categoriaPele) {
    const h = MAPA_CATEGORIA_H.pele[categoriaPele];
    if (h && !codigosH.includes(h)) codigosH.push(h);
  }

  const categoriaOlhos = (resultadoOlhos || {}).categoria;
  if (categoriaOlhos) {
    const h = MAPA_CATEGORIA_H.olhos[categoriaOlhos];
    if (h && !codigosH.includes(h)) codigosH.push(h);
  }

  const valoresAgudas = Object.values(categoriasAgudas);
  const temCaveira = valoresAgudas.some((c) => _CATEGORIAS_CAVEIRA.has(c));
  const temExclamacaoTox = !temCaveira && valoresAgudas.some((c) => _CATEGORIAS_EXCLAMACAO_TOX.has(c));
  const temCorrosao = _SUBCATEGORIAS_PELE_CORROSIVAS.has(categoriaPele) || _SUBCATEGORIAS_OLHOS_GRAVES.has(categoriaOlhos);
  const temExclamacaoPeleOlhos = _SUBCATEGORIAS_PELE_IRRITANTES.has(categoriaPele) || _SUBCATEGORIAS_OLHOS_IRRITANTES.has(categoriaOlhos);

  const pictogramas = [];
  if (temCorrosao) pictogramas.push("corrosao");
  if (temExclamacaoTox || temExclamacaoPeleOlhos) pictogramas.push("exclamacao");
  if (temCaveira) pictogramas.push("caveira");

  let palavraAdvertencia;
  if (temCaveira || temCorrosao) palavraAdvertencia = "PERIGO";
  else if (temExclamacaoTox || temExclamacaoPeleOlhos) palavraAdvertencia = "ATENÇÃO";
  else palavraAdvertencia = null;

  let codigosP = [];
  for (const h of codigosH) {
    for (const p of MAPA_H_PARA_P[h] || []) {
      if (!codigosP.includes(p)) codigosP.push(p);
    }
  }
  if (codigosH.length) {
    codigosP = ["P101", "P102", "P103"].concat(codigosP.filter((p) => !["P101", "P102", "P103"].includes(p)));
  }

  function grupo(pCode) {
    const primeiro = pCode.split("+")[0];
    const numero = parseInt(primeiro.slice(1, 4), 10);
    if (numero < 200) return "Geral";
    if (numero < 300) return "Prevenção";
    if (numero < 400) return "Resposta";
    if (numero < 500) return "Armazenamento";
    return "Disposição";
  }

  const pPorGrupo = { Geral: [], "Prevenção": [], Resposta: [], Armazenamento: [], "Disposição": [] };
  for (const p of codigosP) {
    pPorGrupo[grupo(p)].push({ codigo: p, descricao: P_CODES[p] || "" });
  }

  return {
    codigos_h: codigosH.map((h) => ({ codigo: h, descricao: H_CODES[h] || "" })),
    codigos_p_por_grupo: pPorGrupo,
    pictogramas,
    palavra_advertencia: palavraAdvertencia,
    flags: {
      corrosivo: temCorrosao,
      irritante: !temCorrosao && temExclamacaoPeleOlhos,
      toxico_agudo: Object.keys(categoriasAgudas).length > 0,
      caveira: temCaveira,
    },
  };
}

/**
 * Classificação INTRÍNSECA de uma matéria-prima (não da mistura), para
 * exibir na tabela da Seção 3. Quando há mais de uma linha no Anexo VI
 * para o mesmo CAS, usa a mais severa de cada via/classe — aqui é só
 * informativo, a resolução por banda já acontece corretamente no cálculo
 * da mistura em `BancoSubstancias.montarIngredientesPorVia/PeleOlhos`.
 * @param {import("./bancoSubstancias.js").BancoSubstancias} banco
 */
export async function obterHCodesSubstancia(banco, cas, dadosFds) {
  const { mapa_categoria_h: MAPA_CATEGORIA_H } = dadosFds;
  const codigos = [];

  const linhasTox = (await banco.obterToxicidadeAgudaPorCas(cas)).filter(
    (r) => r.categoria !== null && r.categoria !== undefined
  );
  const melhorPorVia = new Map();
  for (const r of linhasTox) {
    const atual = melhorPorVia.get(r.via);
    if (atual === undefined || r.categoria < atual) melhorPorVia.set(r.via, r.categoria);
  }
  for (const [viaStr, categoria] of melhorPorVia.entries()) {
    const chave = _viaParaChaveH(viaStr);
    const h = MAPA_CATEGORIA_H[chave][String(categoria)];
    if (h && !codigos.includes(h)) codigos.push(h);
  }

  const linhasPeleOlhos = await banco.obterPeleOlhosPorCas(cas);
  const ordemPele = ["1A", "1B", "1C", "1", "2", "3"];
  const ordemOlhos = ["1", "2A", "2B", "2"];
  const catsPele = linhasPeleOlhos.map((r) => r.categoria_pele).filter(Boolean);
  const catsOlhos = linhasPeleOlhos.map((r) => r.categoria_olhos).filter(Boolean);

  if (catsPele.length) {
    catsPele.sort((a, b) => (ordemPele.includes(a) ? ordemPele.indexOf(a) : ordemPele.length) -
      (ordemPele.includes(b) ? ordemPele.indexOf(b) : ordemPele.length));
    const h = MAPA_CATEGORIA_H.pele[catsPele[0]];
    if (h && !codigos.includes(h)) codigos.push(h);
  }
  if (catsOlhos.length) {
    catsOlhos.sort((a, b) => (ordemOlhos.includes(a) ? ordemOlhos.indexOf(a) : ordemOlhos.length) -
      (ordemOlhos.includes(b) ? ordemOlhos.indexOf(b) : ordemOlhos.length));
    const h = MAPA_CATEGORIA_H.olhos[catsOlhos[0]];
    if (h && !codigos.includes(h)) codigos.push(h);
  }

  return codigos;
}

// ---------------------------------------------------------------------------
// Frases padrão — parametrizadas por severidade (flags) e por overrides
// opcionais informados pelo usuário (extras). Nunca inventam um dado de
// ensaio; quando não há informação, o texto diz explicitamente "Não
// disponível" / "Não determinado".
// ---------------------------------------------------------------------------

export function frasesPrimeirosSocorros(flags) {
  if (flags.corrosivo) {
    return {
      inalacao: "Remova a pessoa para um local ventilado. Se a respiração estiver irregular ou parar, procure atendimento médico imediatamente.",
      contato_pele: "Retire imediatamente a roupa contaminada. Lave a pele com água em abundância por no mínimo 15 minutos. Procure atendimento médico IMEDIATAMENTE.",
      contato_olhos: "Enxágue imediatamente os olhos com água corrente durante pelo menos 15 minutos, mantendo as pálpebras bem abertas. Remova lentes de contato, se presentes e fácil de fazer. Consulte um oftalmologista IMEDIATAMENTE.",
      ingestao: "NÃO provoque vômito. Enxágue a boca com água. Nunca administre nada por via oral a uma pessoa inconsciente. Consulte um médico IMEDIATAMENTE.",
      sintomas: "O contato com a pele e os olhos pode provocar queimaduras/lesões graves. A inalação ou ingestão pode causar irritação e danos ao trato respiratório/gastrointestinal.",
      notas_medico: "Tratamento sintomático. Considerar o caráter corrosivo do produto antes de procedimentos como lavagem gástrica. Não há antídoto específico conhecido.",
    };
  }
  if (flags.irritante) {
    return {
      inalacao: "Remova a pessoa para um local ventilado. Em caso de desconforto persistente, procure atendimento médico.",
      contato_pele: "Lave a pele com água e sabão em abundância. Em caso de irritação persistente, procure atendimento médico.",
      contato_olhos: "Enxágue cuidadosamente com água durante vários minutos. Remova lentes de contato, se presentes e fácil de fazer. Se a irritação ocular persistir, consulte um médico.",
      ingestao: "Enxágue a boca com água. Procure atendimento médico se sentir indisposição.",
      sintomas: "Pode provocar irritação da pele, dos olhos e das vias respiratórias.",
      notas_medico: "Tratamento sintomático. Não há antídoto específico conhecido.",
    };
  }
  return {
    inalacao: "Remova a pessoa para um local ventilado. Procure atendimento médico se os sintomas persistirem.",
    contato_pele: "Lave a pele com água em abundância.",
    contato_olhos: "Enxágue os olhos com água em abundância. Procure atendimento médico se a irritação persistir.",
    ingestao: "Enxágue a boca com água. Procure atendimento médico se sentir indisposição.",
    sintomas: "Não são esperados efeitos adversos significativos nas condições normais de uso.",
    notas_medico: "Tratamento sintomático, conforme quadro clínico apresentado.",
  };
}

export function frasesCombateIncendio(flags, extras) {
  return {
    meios_apropriados: extras.meios_extincao_apropriados ||
      "Água pulverizada/nebulizada, pó químico seco, espuma resistente ao álcool ou dióxido de carbono (CO2). Selecionar o meio de extinção conforme o material envolvido no entorno do incêndio.",
    meios_nao_apropriados: extras.meios_extincao_inadequados ||
      "Não utilizar jato de água direto e pressurizado, que pode espalhar o produto.",
    perigos_especificos: extras.perigos_incendio ||
      (flags.corrosivo || flags.irritante
        ? "A decomposição térmica pode liberar gases/vapores irritantes ou tóxicos."
        : "Não são esperados perigos específicos de combustão além dos comuns a incêndios."),
    medidas_bombeiros: "Utilizar equipamento de respiração autônoma com pressão positiva e vestuário de proteção química completo. Resfriar os recipientes expostos ao fogo, se seguro fazê-lo.",
  };
}

export function frasesVazamento(flags) {
  const protecao = flags.corrosivo || flags.irritante
    ? "roupa de proteção individual completa, conforme indicado na Seção 8"
    : "equipamento de proteção individual básico";
  return {
    precaucoes_pessoais_nao_emergencial: `Evitar contato com o produto derramado. Usar ${protecao}. Garantir ventilação adequada do local.`,
    precaucoes_pessoais_emergencia: "Isolar a área do vazamento. Utilizar equipamento de proteção individual completo, conforme descrito na Seção 8.",
    precaucoes_ambientais: "Não permitir que o produto atinja canalizações, esgotos, águas subterrâneas ou cursos d'água. Em caso de contaminação significativa, notificar as autoridades competentes locais.",
    metodos_contencao: "Conter o derramamento com materiais absorventes inertes (areia, terra, diatomito, ou outro material inerte compatível) ou diques, conforme o volume.",
    metodos_limpeza: "Recolher o material derramado com auxílio de utensílios adequados e transferir para recipientes apropriados para descarte conforme a Seção 13. Lavar a área com água em abundância após a remoção do produto.",
  };
}

export function frasesManuseioArmazenamento(flags, extras, estadoFisico) {
  const forma = estadoFisico === "liquido" ? "vapores/névoas" : "poeiras";
  return {
    manuseio_seguro: extras.manuseio_seguro ||
      `Manusear em área com ventilação adequada. Evitar contato com a pele, os olhos e a roupa. Não inalar ${forma} do produto. Utilizar o equipamento de proteção individual indicado na Seção 8.`,
    medidas_higiene: "Proibido comer, beber ou fumar na área de trabalho. Remover imediatamente o vestuário contaminado. Lavar as mãos e o rosto cuidadosamente após o manuseio.",
    condicoes_armazenamento: extras.condicoes_armazenamento ||
      "Conservar em local fresco, seco e bem ventilado, em recipientes bem fechados, ao abrigo de luz solar direta.",
    materiais_incompativeis: extras.materiais_incompativeis ||
      (flags.corrosivo ? "Agentes oxidantes fortes e bases fortes." : "Nenhum conhecido nas condições normais de uso."),
  };
}

export function frasesEpi(flags, extras) {
  if (flags.corrosivo) {
    return {
      protecao_olhos: extras.epi_olhos || "Óculos de segurança de ampla visão contra respingos químicos e/ou protetor facial completo.",
      protecao_pele: extras.epi_pele || "Vestuário de proteção química resistente ao produto (avental ou macacão).",
      protecao_maos: extras.epi_maos || "Luvas de proteção impermeáveis e resistentes ao produto.",
      protecao_respiratoria: extras.epi_respiratoria || "Em ambientes com ventilação insuficiente, utilizar respirador com filtro adequado ao produto.",
      controles_engenharia: "Assegurar ventilação adequada. Disponibilizar chuveiro de emergência e lava-olhos no local de trabalho.",
    };
  }
  return {
    protecao_olhos: extras.epi_olhos || "Óculos de segurança.",
    protecao_pele: extras.epi_pele || "Vestuário de proteção conforme a atividade.",
    protecao_maos: extras.epi_maos || "Luvas de proteção adequadas ao manuseio.",
    protecao_respiratoria: extras.epi_respiratoria || "Não são necessárias medidas especiais nas condições normais de uso; avaliar conforme ventilação do local.",
    controles_engenharia: "Assegurar ventilação adequada do local de trabalho.",
  };
}

export function frasesEstabilidadeReatividade(flags, extras) {
  return {
    reatividade: extras.reatividade ||
      (flags.corrosivo ? "Produto de caráter corrosivo. Pode reagir com agentes oxidantes fortes e bases fortes." : "Não são esperadas reações perigosas nas condições normais de uso."),
    estabilidade_quimica: "Estável sob condições normais de uso, manuseio e armazenamento recomendadas.",
    reacoes_perigosas: extras.reacoes_perigosas ||
      (flags.corrosivo ? "Pode reagir com materiais incompatíveis listados na Seção 10, com liberação de calor e/ou gases." : "Não são conhecidas reações perigosas nas condições normais de uso."),
    condicoes_evitar: "Temperaturas elevadas, fontes de ignição e contato com materiais incompatíveis.",
    materiais_incompativeis: extras.materiais_incompativeis ||
      (flags.corrosivo ? "Agentes oxidantes fortes, bases fortes." : "Nenhum conhecido nas condições normais de uso."),
    produtos_decomposicao: extras.produtos_decomposicao || "Não disponível.",
  };
}

export function frasesEcologicas(extras) {
  return {
    ecotoxicidade: extras.ecotoxicidade || "Não disponível.",
    persistencia_degradabilidade: extras.persistencia || "Não disponível.",
    potencial_bioacumulacao: extras.bioacumulacao || "Não disponível.",
    mobilidade_solo: extras.mobilidade_solo || "Não disponível.",
    outros_efeitos: extras.outros_efeitos_ecologicos || "Não disponível.",
  };
}

export function frasesDestinacaoFinal(extras) {
  return {
    residuos_produto: extras.destinacao_residuos ||
      "Descartar conforme a regulamentação local, estadual e federal aplicável (incluindo a Lei nº 12.305/2010 - Política Nacional de Resíduos Sólidos). Não descartar em esgotos, cursos d'água ou solo.",
    embalagens: extras.destinacao_embalagens ||
      "Não reutilizar embalagens vazias para outros fins. Descartar conforme a regulamentação aplicável a resíduos perigosos, ou encaminhar a empresas especializadas em descontaminação.",
  };
}

export function frasesRegulamentacoes(extras) {
  const base = [
    "ABNT NBR 14725:2023 - Produtos químicos — Informações sobre segurança, saúde e meio ambiente — Sistema Globalmente Harmonizado (GHS), classificação, FDS e rotulagem de produtos químicos.",
    "Norma Regulamentadora nº 26 (NR-26) - Sinalização de Segurança.",
    "Lei nº 12.305/2010 - Política Nacional de Resíduos Sólidos.",
  ];
  const extraTexto = extras.regulamentacoes_adicionais;
  if (extraTexto) {
    base.push(...extraTexto.split(/\r?\n/).map((l) => l.trim()).filter(Boolean));
  }
  return base;
}

export const LEGENDA_PADRAO = {
  ABNT: "Associação Brasileira de Normas Técnicas",
  CAS: "Chemical Abstracts Service",
  DL50: "Dose Letal 50%",
  CL50: "Concentração Letal 50%",
  EPI: "Equipamento de Proteção Individual",
  ETA: "Estimativa de Toxicidade Aguda",
  FDS: "Ficha de Dados de Segurança",
  GHS: "Sistema Globalmente Harmonizado de Classificação e Rotulagem de Produtos Químicos",
  NBR: "Norma Brasileira",
  NR: "Norma Regulamentadora",
  ONU: "Organização das Nações Unidas",
  STOT: "Toxicidade para Órgãos-alvo Específicos",
};

const _NOMES_PICTOGRAMA = {
  corrosao: "Corrosão (GHS05)",
  exclamacao: "Ponto de exclamação (GHS07)",
  caveira: "Caveira e ossos cruzados (GHS06)",
};

const _NOMES_VIA_TOXICIDADE = {
  oral: "Via oral",
  dermica: "Via dérmica",
  inalatoria_gases: "Via inalatória (gases)",
  inalatoria_vapores: "Via inalatória (vapores)",
  inalatoria_poeiras_nevoas: "Via inalatória (poeiras/névoas)",
};

// ---------------------------------------------------------------------------
// Blocos de conteúdo de uma seção — cada seção da FDS é uma lista de
// blocos, um dict com "tipo" e os dados daquele tipo, para que o
// renderizador de PDF saiba como desenhá-lo sem inspecionar a seção inteira.
// ---------------------------------------------------------------------------

function _blocoCampos(pares) {
  return { tipo: "campos", pares };
}
function _blocoTabela(cabecalhos, linhas) {
  return { tipo: "tabela", cabecalhos, linhas };
}
function _blocoLista(titulo, itens) {
  return { tipo: "lista", titulo, itens };
}
function _blocoTexto(texto) {
  return { tipo: "texto", texto };
}

/**
 * Monta a estrutura completa das 16 seções da FDS. Não decide nem
 * recalcula nenhuma classificação: só formata o que os motores já
 * decidiram e o que o usuário informou.
 *
 * @param {object} opts
 * @param {object} opts.perfilEmpresa
 * @param {object} opts.produtoInfo
 * @param {Array<{nome?:string, cas?:string, concentracao:number, segredo_industrial?:boolean}>} opts.composicao
 * @param {"liquido"|"solido_pulverulento"} opts.estadoFisico
 * @param {Object<string,object>} opts.resultadoToxicidadeAguda
 * @param {?object} opts.resultadoPele
 * @param {?object} opts.resultadoOlhos
 * @param {?import("./bancoSubstancias.js").BancoSubstancias} [opts.banco]
 * @param {object} [opts.camposExtras]
 * @param {?Date} [opts.dataEmissao]
 * @param {string} [opts.numeroRevisao]
 * @param {?object} [opts.dadosFds]  se omitido, chama carregarDadosFds()
 */
export async function montarDadosFds({
  perfilEmpresa,
  produtoInfo,
  composicao,
  estadoFisico,
  resultadoToxicidadeAguda,
  resultadoPele,
  resultadoOlhos,
  banco = null,
  camposExtras = null,
  dataEmissao = null,
  numeroRevisao = "01",
  dadosFds = null,
}) {
  const dados = dadosFds || (await carregarDadosFds());
  const extras = camposExtras || {};
  const emissao = dataEmissao || new Date();
  const dataStr = `${String(emissao.getDate()).padStart(2, "0")}/${String(emissao.getMonth() + 1).padStart(2, "0")}/${emissao.getFullYear()}`;

  const rotulo = derivarRotuloGhs(resultadoToxicidadeAguda, resultadoPele, resultadoOlhos, dados);
  const flags = rotulo.flags;

  const nomeProduto = produtoInfo.nome_produto || "";
  const secoes = {};

  // --- Seção 1 — Identificação --------------------------------------
  secoes["1"] = {
    titulo: "IDENTIFICAÇÃO",
    blocos: [
      _blocoCampos([
        ["Nome do produto", nomeProduto || "Não informado"],
        ["Código interno do produto", produtoInfo.codigo_produto || "Não disponível"],
        ["Uso recomendado", produtoInfo.uso_recomendado || "Não informado"],
        ["Restrições de uso", produtoInfo.restricoes_uso || "Não disponível"],
      ]),
      _blocoCampos([
        ["Razão social do fornecedor", perfilEmpresa.razao_social || "Não informado"],
        ["CNPJ", perfilEmpresa.cnpj || "Não disponível"],
        ["Endereço", perfilEmpresa.endereco || "Não disponível"],
        ["Telefone", perfilEmpresa.telefone || "Não disponível"],
        ["E-mail", perfilEmpresa.email || "Não disponível"],
        ["Telefone de emergência", perfilEmpresa.telefone_emergencia || "Não disponível"],
      ]),
    ],
  };

  // --- Seção 2 — Identificação de perigos -----------------------------
  const linhasClassificacao = [];
  for (const [via, resultado] of Object.entries(resultadoToxicidadeAguda || {})) {
    const nomeVia = _NOMES_VIA_TOXICIDADE[via] || via;
    const categoria = resultado.categoria;
    if (categoria !== null && categoria !== undefined) {
      linhasClassificacao.push(`Toxicidade aguda — ${nomeVia}: Categoria ${categoria}`);
    } else if (resultado.declaracao_obrigatoria) {
      linhasClassificacao.push(`Toxicidade aguda — ${nomeVia}: não classificada (${resultado.declaracao_obrigatoria})`);
    }
  }
  if ((resultadoPele || {}).categoria) {
    linhasClassificacao.push(`Corrosão/irritação à pele: Categoria ${resultadoPele.categoria}`);
  }
  if ((resultadoOlhos || {}).categoria) {
    linhasClassificacao.push(`Lesão ocular grave/irritação ocular: Categoria ${resultadoOlhos.categoria}`);
  }
  if (!linhasClassificacao.length) {
    linhasClassificacao.push(
      "Não classificado como perigoso para as classes calculadas por este sistema (toxicidade aguda e corrosão/irritação à pele e olhos)."
    );
  }

  const blocosSecao2 = [
    _blocoLista("Classificação da mistura (calculada)", linhasClassificacao),
    _blocoCampos([
      ["Palavra de advertência", rotulo.palavra_advertencia || "Nenhuma"],
      ["Pictogramas", rotulo.pictogramas.map((p) => _NOMES_PICTOGRAMA[p]).join(", ") || "Nenhum"],
    ]),
    _blocoLista(
      "Frases de perigo (H)",
      rotulo.codigos_h.length ? rotulo.codigos_h.map((c) => `${c.codigo} - ${c.descricao}`) : ["Não aplicável."]
    ),
  ];
  for (const [grupoNome, itens] of Object.entries(rotulo.codigos_p_por_grupo)) {
    if (itens.length) {
      blocosSecao2.push(_blocoLista(`Frases de precaução (P) — ${grupoNome}`, itens.map((c) => `${c.codigo} - ${c.descricao}`)));
    }
  }
  blocosSecao2.push(
    _blocoCampos([
      [
        "Outros perigos",
        extras.outros_perigos ||
          "Não classificado para outras classes de perigo com base nos dados calculados por este sistema (ver limitações na Seção 16).",
      ],
    ])
  );
  secoes["2"] = { titulo: "IDENTIFICAÇÃO DE PERIGOS", blocos: blocosSecao2 };

  // --- Seção 3 — Composição e informações sobre os ingredientes --------
  const linhasComposicao = [];
  for (const item of composicao) {
    const segredo = !!item.segredo_industrial;
    const nomeI = segredo ? "Segredo Industrial" : item.nome || "";
    const casI = segredo ? "Segredo Industrial" : item.cas || "Não disponível";
    const concI = `${Number(item.concentracao || 0).toFixed(2)}%`;
    let classifI;
    if (segredo) {
      classifI = "Não divulgada (segredo industrial)";
    } else if (banco !== null && item.cas) {
      const codigos = await obterHCodesSubstancia(banco, item.cas, dados);
      classifI = codigos.length ? codigos.join(", ") : "Não classificado / não disponível no Anexo VI";
    } else {
      classifI = "Não disponível";
    }
    linhasComposicao.push([nomeI, casI, concI, classifI]);
  }

  secoes["3"] = {
    titulo: "COMPOSIÇÃO E INFORMAÇÕES SOBRE OS INGREDIENTES",
    blocos: [
      _blocoCampos([["Natureza química", extras.natureza_quimica || "Mistura"]]),
      _blocoTabela(["Nome / Identificação", "Nº CAS", "Concentração", "Classificação de perigo"], linhasComposicao),
    ],
  };

  // --- Seção 4 — Primeiros socorros ------------------------------------
  const fp = frasesPrimeirosSocorros(flags);
  secoes["4"] = {
    titulo: "MEDIDAS DE PRIMEIROS SOCORROS",
    blocos: [
      _blocoCampos([
        ["Inalação", fp.inalacao],
        ["Contato com a pele", fp.contato_pele],
        ["Contato com os olhos", fp.contato_olhos],
        ["Ingestão", fp.ingestao],
        ["Principais sintomas e efeitos", fp.sintomas],
        ["Notas para o médico", fp.notas_medico],
      ]),
    ],
  };

  // --- Seção 5 — Combate a incêndio -------------------------------------
  const fi = frasesCombateIncendio(flags, extras);
  secoes["5"] = {
    titulo: "MEDIDAS DE COMBATE A INCÊNDIO",
    blocos: [
      _blocoCampos([
        ["Meios de extinção apropriados", fi.meios_apropriados],
        ["Meios de extinção não apropriados", fi.meios_nao_apropriados],
        ["Perigos específicos do produto", fi.perigos_especificos],
        ["Medidas de proteção da equipe de combate a incêndio", fi.medidas_bombeiros],
      ]),
    ],
  };

  // --- Seção 6 — Medidas de controle para derramamento ou vazamento ----
  const fv = frasesVazamento(flags);
  secoes["6"] = {
    titulo: "MEDIDAS DE CONTROLE PARA DERRAMAMENTO OU VAZAMENTO",
    blocos: [
      _blocoCampos([
        ["Precauções pessoais (pessoal não emergencial)", fv.precaucoes_pessoais_nao_emergencial],
        ["Precauções pessoais (equipe de emergência)", fv.precaucoes_pessoais_emergencia],
        ["Precauções ao meio ambiente", fv.precaucoes_ambientais],
        ["Métodos de contenção", fv.metodos_contencao],
        ["Métodos de limpeza", fv.metodos_limpeza],
      ]),
    ],
  };

  // --- Seção 7 — Manuseio e armazenamento -------------------------------
  const fm = frasesManuseioArmazenamento(flags, extras, estadoFisico);
  secoes["7"] = {
    titulo: "MANUSEIO E ARMAZENAMENTO",
    blocos: [
      _blocoCampos([
        ["Manuseio seguro", fm.manuseio_seguro],
        ["Medidas de higiene", fm.medidas_higiene],
        ["Condições de armazenamento", fm.condicoes_armazenamento],
        ["Produtos e materiais incompatíveis", fm.materiais_incompativeis],
      ]),
    ],
  };

  // --- Seção 8 — Controle de exposição / EPI ----------------------------
  const fe = frasesEpi(flags, extras);
  secoes["8"] = {
    titulo: "CONTROLE DE EXPOSIÇÃO E PROTEÇÃO INDIVIDUAL",
    blocos: [
      _blocoCampos([
        ["Limites de exposição ocupacional", extras.limites_exposicao || "Não estabelecidos para os componentes desta mistura."],
        ["Controles de engenharia apropriados", fe.controles_engenharia],
        ["Proteção dos olhos/face", fe.protecao_olhos],
        ["Proteção da pele/corpo", fe.protecao_pele],
        ["Proteção das mãos", fe.protecao_maos],
        ["Proteção respiratória", fe.protecao_respiratoria],
      ]),
    ],
  };

  // --- Seção 9 — Propriedades físicas e químicas ------------------------
  const nomeEstado = estadoFisico === "liquido" ? "Líquido" : "Sólido pulverulento";
  secoes["9"] = {
    titulo: "PROPRIEDADES FÍSICAS E QUÍMICAS",
    blocos: [
      _blocoCampos([
        ["Estado físico", nomeEstado],
        ["Cor", extras.cor || "Não disponível"],
        ["Odor", extras.odor || "Não disponível"],
        ["pH", extras.ph || "Não disponível"],
        ["Ponto de fusão/congelamento", extras.ponto_fusao || "Não disponível"],
        ["Ponto de ebulição inicial e faixa", extras.ponto_ebulicao || "Não disponível"],
        ["Ponto de fulgor", extras.ponto_fulgor || "Não disponível"],
        ["Taxa de evaporação", extras.taxa_evaporacao || "Não disponível"],
        ["Inflamabilidade", extras.inflamabilidade || "Não determinada"],
        ["Limites inferior/superior de inflamabilidade ou explosividade", extras.limites_explosividade || "Não disponível"],
        ["Pressão de vapor", extras.pressao_vapor || "Não disponível"],
        ["Densidade de vapor", extras.densidade_vapor || "Não disponível"],
        ["Densidade relativa", extras.densidade_relativa || "Não disponível"],
        ["Solubilidade em água", extras.solubilidade_agua || "Não disponível"],
        ["Coeficiente de partição n-octanol/água", extras.coeficiente_particao || "Não disponível"],
        ["Temperatura de auto-ignição", extras.temperatura_autoignicao || "Não disponível"],
        ["Temperatura de decomposição", extras.temperatura_decomposicao || "Não disponível"],
        ["Viscosidade", extras.viscosidade || "Não disponível"],
      ]),
    ],
  };

  // --- Seção 10 — Estabilidade e reatividade -----------------------------
  const fr = frasesEstabilidadeReatividade(flags, extras);
  secoes["10"] = {
    titulo: "ESTABILIDADE E REATIVIDADE",
    blocos: [
      _blocoCampos([
        ["Reatividade", fr.reatividade],
        ["Estabilidade química", fr.estabilidade_quimica],
        ["Possibilidade de reações perigosas", fr.reacoes_perigosas],
        ["Condições a evitar", fr.condicoes_evitar],
        ["Materiais incompatíveis", fr.materiais_incompativeis],
        ["Produtos perigosos da decomposição", fr.produtos_decomposicao],
      ]),
    ],
  };

  // --- Seção 11 — Informações toxicológicas ------------------------------
  const linhasTox = [];
  for (const [via, resultado] of Object.entries(resultadoToxicidadeAguda || {})) {
    const nomeVia = _NOMES_VIA_TOXICIDADE[via] || via;
    const categoria = resultado.categoria;
    const eta = resultado.eta_mistura;
    if (categoria !== null && categoria !== undefined && eta !== null && eta !== undefined) {
      linhasTox.push(`${nomeVia}: ETA (estimativa de toxicidade aguda) da mistura ≈ ${eta} — Categoria ${categoria}.`);
    } else if (resultado.declaracao_obrigatoria) {
      linhasTox.push(`${nomeVia}: ${resultado.declaracao_obrigatoria}`);
    } else {
      linhasTox.push(`${nomeVia}: não classificado com os dados informados.`);
    }
  }
  if ((resultadoPele || {}).categoria) {
    linhasTox.push(`Corrosão/irritação à pele: Categoria ${resultadoPele.categoria} (critério: ${resultadoPele.criterio || "não disponível"}).`);
  } else {
    linhasTox.push("Corrosão/irritação à pele: não classificada com os dados informados.");
  }
  if ((resultadoOlhos || {}).categoria) {
    linhasTox.push(`Lesão ocular grave/irritação ocular: Categoria ${resultadoOlhos.categoria} (critério: ${resultadoOlhos.criterio || "não disponível"}).`);
  } else {
    linhasTox.push("Lesão ocular grave/irritação ocular: não classificada com os dados informados.");
  }

  secoes["11"] = {
    titulo: "INFORMAÇÕES TOXICOLÓGICAS",
    blocos: [
      _blocoLista("Toxicidade aguda e corrosão/irritação (calculadas)", linhasTox),
      _blocoCampos([
        ["Sensibilização", extras.sensibilizacao || "Não disponível"],
        ["Mutagenicidade em células germinativas", extras.mutagenicidade || "Não disponível"],
        ["Carcinogenicidade", extras.carcinogenicidade || "Não disponível"],
        ["Toxicidade à reprodução", extras.toxicidade_reproducao || "Não disponível"],
        ["Toxicidade para órgãos-alvo específicos (STOT) — exposição única", extras.stot_unica || "Não disponível"],
        ["Toxicidade para órgãos-alvo específicos (STOT) — exposição repetida", extras.stot_repetida || "Não disponível"],
        ["Perigo de aspiração", extras.perigo_aspiracao || "Não disponível"],
      ]),
    ],
  };

  // --- Seção 12 — Informações ecológicas ---------------------------------
  const fec = frasesEcologicas(extras);
  secoes["12"] = {
    titulo: "INFORMAÇÕES ECOLÓGICAS",
    blocos: [
      _blocoCampos([
        ["Ecotoxicidade", fec.ecotoxicidade],
        ["Persistência e degradabilidade", fec.persistencia_degradabilidade],
        ["Potencial bioacumulativo", fec.potencial_bioacumulacao],
        ["Mobilidade no solo", fec.mobilidade_solo],
        ["Outros efeitos adversos", fec.outros_efeitos],
      ]),
    ],
  };

  // --- Seção 13 — Considerações sobre destinação final --------------------
  const fd = frasesDestinacaoFinal(extras);
  secoes["13"] = {
    titulo: "CONSIDERAÇÕES SOBRE DESTINAÇÃO FINAL",
    blocos: [
      _blocoCampos([
        ["Métodos e materiais para destinação final do produto", fd.residuos_produto],
        ["Métodos e materiais para destinação final de embalagens", fd.embalagens],
      ]),
    ],
  };

  // --- Seção 14 — Informações sobre transporte ------------------------------
  secoes["14"] = {
    titulo: "INFORMAÇÕES SOBRE TRANSPORTE",
    blocos: [
      _blocoCampos([
        ["Número ONU", extras.numero_onu || "Não classificado"],
        ["Nome apropriado para embarque", extras.nome_embarque || "Não disponível"],
        ["Classe de risco", extras.classe_risco || "Não classificado"],
        ["Número de risco", extras.numero_risco || "Não disponível"],
        ["Grupo de embalagem", extras.grupo_embalagem || "Não disponível"],
        ["Perigos ambientais para o transporte", extras.perigo_ambiental_transporte || "Não disponível"],
        ["Precauções especiais para o usuário", extras.precaucoes_transporte || "Não disponível"],
      ]),
    ],
  };

  // --- Seção 15 — Regulamentações ----------------------------------------
  secoes["15"] = {
    titulo: "REGULAMENTAÇÕES",
    blocos: [_blocoLista("Regulamentações aplicáveis", frasesRegulamentacoes(extras))],
  };

  // --- Seção 16 — Outras informações --------------------------------------
  const linhasLegenda = Object.entries(LEGENDA_PADRAO).map(([sigla, significado]) => `${sigla} - ${significado}`);
  secoes["16"] = {
    titulo: "OUTRAS INFORMAÇÕES",
    blocos: [
      _blocoCampos([
        ["Data de emissão desta FDS", dataStr],
        ["Número da revisão", numeroRevisao],
      ]),
      _blocoLista("Legenda / abreviaturas", linhasLegenda),
      _blocoTexto(
        extras.aviso_legal ||
          "As informações contidas nesta Ficha de Dados de Segurança foram elaboradas com base nos dados " +
            "disponíveis até a data de emissão indicada acima e correspondem ao melhor conhecimento atual sobre o " +
            "produto. A classificação de perigo apresentada nas Seções 2 e 11 foi obtida por cálculo determinístico " +
            "a partir da composição informada, conforme a ABNT NBR 14725:2023, e cobre apenas as classes de perigo " +
            "calculadas por este sistema (toxicidade aguda e corrosão/irritação à pele e olhos) — outras classes de " +
            "perigo (inflamabilidade, propriedades explosivas, corrosivo a metais, toxicidade para órgãos-alvo " +
            "específicos, perigo ao ambiente aquático agudo/crônico, entre outras) não foram avaliadas por cálculo e " +
            "só constam nesta ficha quando informadas manualmente. Esta ficha não substitui a avaliação técnica de " +
            "um responsável qualificado para o uso específico pretendido pelo destinatário."
      ),
    ],
  };

  return {
    cabecalho: {
      produto: nomeProduto,
      data_emissao: dataStr,
      numero_revisao: numeroRevisao,
      empresa_nome: perfilEmpresa.razao_social || "",
    },
    secoes,
  };
}

// ---------------------------------------------------------------------------
// Geração do PDF — layout de duas colunas (rótulo | valor), estilo
// Fosfeed/Safeeds: barra cinza de título de seção em largura total, tabelas
// label/valor logo abaixo, sem logotipo/pictogramas gráficos (só texto),
// rodapé com identificador do documento e numeração de página.
//
// Usa jsPDF + jspdf-autotable (globais `window.jspdf.jsPDF` / `doc.autoTable`,
// carregados via <script> na página — ver gerador-fds.html) em vez de
// reportlab, para rodar inteiramente no navegador, sem servidor.
// ---------------------------------------------------------------------------

const PT_POR_CM = 28.3465;
const MARGEM_ESQ = 1.5 * PT_POR_CM;
const MARGEM_DIR = 1.5 * PT_POR_CM;
const MARGEM_TOPO = 1.5 * PT_POR_CM;
const MARGEM_BASE = 1.8 * PT_POR_CM;

const COR_BARRA_SECAO = [77, 77, 77]; // #4d4d4d
const COR_LINHA = [153, 153, 153]; // #999999
const COR_FUNDO_ROTULO = [242, 242, 242]; // #f2f2f2
const COR_RODAPE = [102, 102, 102]; // #666666

function _estiloBaseTabela(larguraUtil) {
  return {
    theme: "grid",
    styles: {
      font: "helvetica",
      fontSize: 8.5,
      textColor: [0, 0, 0],
      lineColor: COR_LINHA,
      lineWidth: 0.5,
      cellPadding: { top: 3, bottom: 3, left: 5, right: 5 },
      valign: "top",
    },
    tableWidth: larguraUtil,
    margin: { left: MARGEM_ESQ, right: MARGEM_DIR },
  };
}

function _desenharBarraSecao(doc, y, larguraUtil, numero, titulo) {
  const altura = 22;
  doc.setFillColor(...COR_BARRA_SECAO);
  doc.rect(MARGEM_ESQ, y, larguraUtil, altura, "F");
  doc.setFont("helvetica", "bold");
  doc.setFontSize(10.5);
  doc.setTextColor(255, 255, 255);
  doc.text(`${numero} - ${titulo}`, MARGEM_ESQ + 6, y + altura / 2, { baseline: "middle" });
  doc.setTextColor(0, 0, 0);
  return y + altura;
}

function _desenharTabelaCampos(doc, y, larguraUtil, pares) {
  doc.autoTable({
    ..._estiloBaseTabela(larguraUtil),
    startY: y,
    body: pares.map(([rotulo, valor]) => [rotulo, String(valor)]),
    columnStyles: {
      0: { cellWidth: larguraUtil * 0.32, fontStyle: "bold", fillColor: COR_FUNDO_ROTULO },
      1: { cellWidth: larguraUtil * 0.68 },
    },
  });
  return doc.lastAutoTable.finalY;
}

function _desenharTabelaLista(doc, y, larguraUtil, titulo, itens) {
  const texto = itens.length ? itens.join("\n") : "Não aplicável.";
  doc.autoTable({
    ..._estiloBaseTabela(larguraUtil),
    startY: y,
    body: [[titulo, texto]],
    columnStyles: {
      0: { cellWidth: larguraUtil * 0.32, fontStyle: "bold", fillColor: COR_FUNDO_ROTULO },
      1: { cellWidth: larguraUtil * 0.68 },
    },
  });
  return doc.lastAutoTable.finalY;
}

function _desenharTabelaMulticolunas(doc, y, larguraUtil, cabecalhos, linhas) {
  doc.autoTable({
    ..._estiloBaseTabela(larguraUtil),
    startY: y,
    head: [cabecalhos],
    body: linhas,
    headStyles: { fillColor: COR_BARRA_SECAO, textColor: [255, 255, 255], fontStyle: "bold" },
  });
  return doc.lastAutoTable.finalY;
}

function _desenharTexto(doc, y, larguraUtil, pageHeight, texto) {
  doc.setFont("helvetica", "normal");
  doc.setFontSize(8);
  doc.setTextColor(0, 0, 0);
  const linhas = doc.splitTextToSize(texto, larguraUtil);
  const alturaLinha = 10.5;
  let yy = y + 4.25; // ~0.15cm de espaçamento antes do parágrafo, como no original
  for (const linha of linhas) {
    if (yy + alturaLinha > pageHeight - MARGEM_BASE) {
      doc.addPage();
      yy = MARGEM_TOPO;
    }
    doc.text(linha, MARGEM_ESQ, yy);
    yy += alturaLinha;
  }
  return yy;
}

function _garantirEspaco(doc, y, alturaNecessaria, pageHeight) {
  if (y + alturaNecessaria > pageHeight - MARGEM_BASE) {
    doc.addPage();
    return MARGEM_TOPO;
  }
  return y;
}

/**
 * Renderiza `dados` (saída de `montarDadosFds`) num PDF, no navegador.
 * @param {object} dados
 * @param {object} [opcoes]
 * @param {?string} [opcoes.nomeArquivo]  se omitido, usa o id do documento
 * @param {boolean} [opcoes.autoSalvar=true]  chama doc.save() (dispara o download no navegador)
 * @returns {object} a instância jsPDF (`doc`), para quem quiser `doc.output('blob')` etc.
 */
export function gerarPdfFds(dados, { nomeArquivo = null, autoSalvar = true } = {}) {
  if (typeof window === "undefined" || !window.jspdf || !window.jspdf.jsPDF) {
    throw new Error(
      "jsPDF não está carregado. Inclua os scripts jspdf.umd.min.js e jspdf.plugin.autotable.min.js na página antes de gerar o PDF."
    );
  }
  const { jsPDF } = window.jspdf;
  const doc = new jsPDF({ unit: "pt", format: "a4" });
  if (typeof doc.autoTable !== "function") {
    throw new Error("jspdf-autotable não está carregado. Inclua jspdf.plugin.autotable.min.js na página, depois de jspdf.umd.min.js.");
  }

  const pageWidth = doc.internal.pageSize.getWidth();
  const pageHeight = doc.internal.pageSize.getHeight();
  const larguraUtil = pageWidth - MARGEM_ESQ - MARGEM_DIR;

  const estilos = {
    cabecalhoInfo: { fontSize: 8.5 },
    tituloProduto: { fontSize: 16 },
    fdsWordmark: { fontSize: 20 },
  };

  const cab = dados.cabecalho;
  let y = MARGEM_TOPO;

  // --- Cabeçalho do documento (texto, sem logotipo) ---
  doc.setFont("helvetica", "normal");
  doc.setFontSize(estilos.cabecalhoInfo.fontSize);
  doc.setTextColor(0, 0, 0);
  const linhasEmpresa = doc.splitTextToSize(cab.empresa_nome || "", larguraUtil * 0.68);
  linhasEmpresa.forEach((linha, i) => doc.text(linha, MARGEM_ESQ, y + 10 + i * 11));

  doc.setFont("helvetica", "bold");
  doc.setFontSize(estilos.fdsWordmark.fontSize);
  doc.text("FDS", pageWidth - MARGEM_DIR, y + 16, { align: "right" });

  y += Math.max(linhasEmpresa.length * 11, 22) + 6;

  doc.setFont("helvetica", "bold");
  doc.setFontSize(estilos.tituloProduto.fontSize);
  const tituloLinhas = doc.splitTextToSize(`FICHA DE DADOS DE SEGURANÇA — ${cab.produto || "PRODUTO"}`, larguraUtil);
  tituloLinhas.forEach((linha, i) => doc.text(linha, MARGEM_ESQ, y + 14 + i * 18));
  y += tituloLinhas.length * 18 + 8;

  doc.setFont("helvetica", "normal");
  doc.setFontSize(8.5);
  doc.text(`Data de emissão: ${cab.data_emissao}`, MARGEM_ESQ, y);
  doc.text(`Revisão: ${cab.numero_revisao}`, MARGEM_ESQ + larguraUtil * 0.5, y);
  doc.setDrawColor(...COR_LINHA);
  doc.setLineWidth(0.75);
  doc.line(MARGEM_ESQ, y + 4, MARGEM_ESQ + larguraUtil, y + 4);
  y += 4 + 10;

  for (let numero = 1; numero <= 16; numero++) {
    const secao = dados.secoes[String(numero)];

    // Aproximação do KeepTogether(barra + primeiro bloco) do original:
    // garante espaço para a barra + uma margem mínima antes de desenhá-la,
    // para não deixar o título de seção "órfão" no fim da página.
    y = _garantirEspaco(doc, y, 50, pageHeight);
    y = _desenharBarraSecao(doc, y, larguraUtil, String(numero), secao.titulo);

    for (const bloco of secao.blocos) {
      if (bloco.tipo === "campos") {
        y = _desenharTabelaCampos(doc, y, larguraUtil, bloco.pares);
      } else if (bloco.tipo === "lista") {
        y = _desenharTabelaLista(doc, y, larguraUtil, bloco.titulo, bloco.itens);
      } else if (bloco.tipo === "tabela") {
        y = _desenharTabelaMulticolunas(doc, y, larguraUtil, bloco.cabecalhos, bloco.linhas);
      } else if (bloco.tipo === "texto") {
        y = _desenharTexto(doc, y, larguraUtil, pageHeight, bloco.texto);
      }
    }

    y += 7.09; // Spacer(1, 0.25cm) do original
    y = _garantirEspaco(doc, y, 0, pageHeight);
  }

  const idDocumento = `FDS-${(cab.produto || "PRODUTO").trim().toUpperCase().replace(/\s+/g, "-").slice(0, 24)}-${cab.numero_revisao}`;

  const totalPaginas = doc.internal.getNumberOfPages();
  for (let p = 1; p <= totalPaginas; p++) {
    doc.setPage(p);
    doc.setFont("helvetica", "normal");
    doc.setFontSize(7);
    doc.setTextColor(...COR_RODAPE);
    const footerY = pageHeight - PT_POR_CM; // 1.0cm a partir da base
    doc.text(idDocumento, MARGEM_ESQ, footerY);
    doc.text(`Página ${p} de ${totalPaginas}`, pageWidth - MARGEM_DIR, footerY, { align: "right" });
    if (p === totalPaginas) {
      doc.text("Esta é a última página.", pageWidth / 2, footerY, { align: "center" });
    }
  }
  doc.setTextColor(0, 0, 0);

  doc.setProperties({ title: `FDS - ${cab.produto || ""}` });

  if (autoSalvar) {
    doc.save(nomeArquivo || `${idDocumento}.pdf`);
  }

  return doc;
}
