"""
Gerador de FDS completa (16 seções, ABNT NBR 14725:2023) — geração de PDF
===========================================================================

Este módulo NÃO reimplementa nenhuma regra de classificação (isso já é
feito por motor_toxicidade_aguda.py / motor_corrosao_irritacao.py). Ele:

  1. Deriva pictogramas, palavra de advertência e frases H/P a partir das
     categorias JÁ CALCULADAS por esses motores (função `derivar_rotulo_ghs`).
  2. Preenche as seções que não vêm de cálculo (primeiros-socorros, combate
     a incêndio, manuseio/armazenamento, EPI, estabilidade/reatividade,
     informações ecológicas, destinação final, regulamentações) com FRASES
     PADRÃO, parametrizadas pela severidade calculada (corrosivo vs.
     irritante vs. sem perigo) e por campos opcionais que o usuário pode
     preencher para sobrescrever o texto genérico.
  3. Monta a estrutura completa das 16 seções e gera o PDF final no layout
     de duas colunas (rótulo à esquerda, valor à direita) — o mesmo estilo
     do modelo "Fosfeed/Safeeds" escolhido pelo usuário.

IMPORTANTE (limitação assumida de propósito, não escondida): classes de
perigo que dependem de ENSAIO em vez de cálculo por composição
(inflamabilidade, propriedades explosivas, corrosivo a metais, perigo
ambiental agudo/crônico formal, STOT, etc.) NÃO são calculadas por este
sistema. Elas só aparecem na FDS se o usuário informar manualmente via os
campos extras — do contrário, a seção correspondente traz "Não
disponível" / "Não classificado", nunca um valor inventado.

Os textos de frases padrão são redigidos de forma genérica e conservadora
(a favor da segurança) — servem como ponto de partida, não como
substituto da revisão de um responsável técnico antes de publicar a FDS.
"""

import json
import os
from datetime import date
from typing import Optional

_CAMINHO_DADOS = os.path.join(os.path.dirname(os.path.abspath(__file__)), "dados_fds.json")
with open(_CAMINHO_DADOS, encoding="utf-8") as _f:
    _DADOS = json.load(_f)

H_CODES = _DADOS["h_codes"]
P_CODES = _DADOS["p_codes"]
MAPA_CATEGORIA_H = _DADOS["mapa_categoria_h"]
MAPA_H_PARA_P = _DADOS["mapa_h_para_p"]

# Categorias que disparam o pictograma de caveira (toxicidade aguda 1-3)
_CATEGORIAS_CAVEIRA = {1, 2, 3}
_CATEGORIAS_EXCLAMACAO_TOX = {4}
_SUBCATEGORIAS_PELE_CORROSIVAS = {"1A", "1B", "1C", "1"}
_SUBCATEGORIAS_PELE_IRRITANTES = {"2", "3"}
_SUBCATEGORIAS_OLHOS_GRAVES = {"1"}
_SUBCATEGORIAS_OLHOS_IRRITANTES = {"2A", "2B", "2"}


def _via_para_chave_h(via: str) -> str:
    """Mapeia o nome da via (como usado pelo motor de toxicidade aguda)
    para a chave do mapa_categoria_h, já que H330/H331/H332 (inalatória)
    são os mesmos independentemente de a via ser vapor, poeira/névoa ou
    gás — a distinção vapor/poeira só importa para o CÁLCULO (Tabela 17),
    não para o código H final."""
    if via == "oral":
        return "toxicidade_oral"
    if via == "dermica":
        return "toxicidade_dermica"
    return "toxicidade_inalatoria"  # inalatoria_vapores / inalatoria_poeiras_nevoas / inalatoria_gases


def derivar_rotulo_ghs(resultado_toxicidade_aguda: dict, resultado_pele: dict, resultado_olhos: dict) -> dict:
    """A partir dos resultados JÁ CALCULADOS pelos motores, deriva:
      - lista de códigos H aplicáveis (com descrição)
      - lista de códigos P aplicáveis (com descrição), agrupados por
        Geral/Prevenção/Resposta/Armazenamento/Disposição (o agrupamento é
        só o primeiro dígito do código P: P1xx=Geral, P2xx=Prevenção,
        P3xx=Resposta, P4xx=Armazenamento, P5xx=Disposição — mesma
        convenção do GHS/Purple Book)
      - pictogramas aplicáveis ('corrosao', 'exclamacao', 'caveira')
      - palavra de advertência ('PERIGO', 'ATENÇÃO' ou None)
      - flags de severidade (usados para escolher as frases padrão das
        seções 4-16): corrosivo, irritante, toxico_agudo

    Regra de precedência de pictogramas (GHS, seção de alocação de
    elementos de rótulo): quando o pictograma de caveira se aplica para
    toxicidade aguda, o de exclamação NÃO é exigido para essa mesma
    classe de perigo (mesmo que outra via tenha categoria 4) — a
    exclamação por irritação de pele/olhos é uma classe de perigo
    diferente e não é afetada por essa regra.
    """
    codigos_h = []

    categorias_agudas = {}
    for via, resultado in (resultado_toxicidade_aguda or {}).items():
        categoria = resultado.get("categoria")
        if categoria is None:
            continue
        chave = _via_para_chave_h(via)
        mapa_via = MAPA_CATEGORIA_H[chave]
        h = mapa_via.get(str(categoria))
        if h and h not in codigos_h:
            codigos_h.append(h)
        categorias_agudas[via] = categoria

    categoria_pele = (resultado_pele or {}).get("categoria")
    if categoria_pele:
        h = MAPA_CATEGORIA_H["pele"].get(categoria_pele)
        if h and h not in codigos_h:
            codigos_h.append(h)

    categoria_olhos = (resultado_olhos or {}).get("categoria")
    if categoria_olhos:
        h = MAPA_CATEGORIA_H["olhos"].get(categoria_olhos)
        if h and h not in codigos_h:
            codigos_h.append(h)

    # --- Pictogramas ---
    tem_caveira = any(c in _CATEGORIAS_CAVEIRA for c in categorias_agudas.values())
    tem_exclamacao_tox = (not tem_caveira) and any(
        c in _CATEGORIAS_EXCLAMACAO_TOX for c in categorias_agudas.values()
    )
    tem_corrosao = (categoria_pele in _SUBCATEGORIAS_PELE_CORROSIVAS) or (categoria_olhos in _SUBCATEGORIAS_OLHOS_GRAVES)
    tem_exclamacao_pele_olhos = (categoria_pele in _SUBCATEGORIAS_PELE_IRRITANTES) or (
        categoria_olhos in _SUBCATEGORIAS_OLHOS_IRRITANTES
    )

    pictogramas = []
    if tem_corrosao:
        pictogramas.append("corrosao")
    if tem_exclamacao_tox or tem_exclamacao_pele_olhos:
        pictogramas.append("exclamacao")
    if tem_caveira:
        pictogramas.append("caveira")

    # --- Palavra de advertência ---
    if tem_caveira or tem_corrosao:
        palavra_advertencia = "PERIGO"
    elif tem_exclamacao_tox or tem_exclamacao_pele_olhos:
        palavra_advertencia = "ATENÇÃO"
    else:
        palavra_advertencia = None

    # --- Códigos P (derivados dos H aplicáveis) ---
    codigos_p = []
    for h in codigos_h:
        for p in MAPA_H_PARA_P.get(h, []):
            if p not in codigos_p:
                codigos_p.append(p)
    # Sempre incluir as gerais (P101-P103) quando há qualquer classificação
    if codigos_h:
        for p in ("P101", "P102", "P103"):
            if p not in codigos_p:
                codigos_p.insert(0, p)
        codigos_p = ["P101", "P102", "P103"] + [p for p in codigos_p if p not in ("P101", "P102", "P103")]

    def _grupo(p_code: str) -> str:
        primeiro = p_code.split("+")[0]
        numero = int(primeiro[1:4])
        if numero < 200:
            return "Geral"
        if numero < 300:
            return "Prevenção"
        if numero < 400:
            return "Resposta"
        if numero < 500:
            return "Armazenamento"
        return "Disposição"

    p_por_grupo = {"Geral": [], "Prevenção": [], "Resposta": [], "Armazenamento": [], "Disposição": []}
    for p in codigos_p:
        p_por_grupo[_grupo(p)].append({"codigo": p, "descricao": P_CODES.get(p, "")})

    return {
        "codigos_h": [{"codigo": h, "descricao": H_CODES.get(h, "")} for h in codigos_h],
        "codigos_p_por_grupo": p_por_grupo,
        "pictogramas": pictogramas,
        "palavra_advertencia": palavra_advertencia,
        "flags": {
            "corrosivo": tem_corrosao,
            "irritante": (not tem_corrosao) and tem_exclamacao_pele_olhos,
            "toxico_agudo": bool(categorias_agudas),
            "caveira": tem_caveira,
        },
    }


def obter_h_codes_substancia(banco, cas: str) -> list:
    """Classificação INTRÍNSECA de uma matéria-prima (não da mistura), para
    exibir na tabela da Seção 3 — mesmo espírito das FDS de referência, que
    listam o(s) código(s) H de cada ingrediente conforme sua própria ficha/
    classificação harmonizada. Quando há mais de uma linha no Anexo VI para
    o mesmo CAS (faixas de concentração/formas físicas), usa a mais severa
    de cada via/classe — aqui é só informativo, a resolução por banda já
    acontece corretamente no cálculo da mistura em outro lugar."""
    codigos = []

    linhas_tox = banco.conn.execute(
        "SELECT via, categoria FROM toxicidade_aguda WHERE cas = ? AND categoria IS NOT NULL",
        (cas,),
    ).fetchall()
    melhor_por_via = {}
    for via_str, categoria in linhas_tox:
        if via_str not in melhor_por_via or categoria < melhor_por_via[via_str]:
            melhor_por_via[via_str] = categoria
    for via_str, categoria in melhor_por_via.items():
        chave = _via_para_chave_h(via_str)
        h = MAPA_CATEGORIA_H[chave].get(str(categoria))
        if h and h not in codigos:
            codigos.append(h)

    linha_pele_olhos = banco.conn.execute(
        "SELECT categoria_pele, categoria_olhos FROM pele_olhos WHERE cas = ?", (cas,)
    ).fetchall()
    ordem_pele = ["1A", "1B", "1C", "1", "2", "3"]
    ordem_olhos = ["1", "2A", "2B", "2"]
    cats_pele = [r[0] for r in linha_pele_olhos if r[0]]
    cats_olhos = [r[1] for r in linha_pele_olhos if r[1]]
    if cats_pele:
        cats_pele.sort(key=lambda c: ordem_pele.index(c) if c in ordem_pele else len(ordem_pele))
        h = MAPA_CATEGORIA_H["pele"].get(cats_pele[0])
        if h and h not in codigos:
            codigos.append(h)
    if cats_olhos:
        cats_olhos.sort(key=lambda c: ordem_olhos.index(c) if c in ordem_olhos else len(ordem_olhos))
        h = MAPA_CATEGORIA_H["olhos"].get(cats_olhos[0])
        if h and h not in codigos:
            codigos.append(h)

    return codigos


# ---------------------------------------------------------------------------
# Frases padrão — parametrizadas por severidade (flags) e por overrides
# opcionais informados pelo usuário (campos_extras). Nunca inventam um dado
# de ensaio; quando não há informação (calculada ou informada), o texto diz
# explicitamente "Não disponível" / "Não determinado".
# ---------------------------------------------------------------------------

def frases_primeiros_socorros(flags: dict) -> dict:
    if flags["corrosivo"]:
        return {
            "inalacao": "Remova a pessoa para um local ventilado. Se a respiração estiver irregular ou parar, procure atendimento médico imediatamente.",
            "contato_pele": "Retire imediatamente a roupa contaminada. Lave a pele com água em abundância por no mínimo 15 minutos. Procure atendimento médico IMEDIATAMENTE.",
            "contato_olhos": "Enxágue imediatamente os olhos com água corrente durante pelo menos 15 minutos, mantendo as pálpebras bem abertas. Remova lentes de contato, se presentes e fácil de fazer. Consulte um oftalmologista IMEDIATAMENTE.",
            "ingestao": "NÃO provoque vômito. Enxágue a boca com água. Nunca administre nada por via oral a uma pessoa inconsciente. Consulte um médico IMEDIATAMENTE.",
            "sintomas": "O contato com a pele e os olhos pode provocar queimaduras/lesões graves. A inalação ou ingestão pode causar irritação e danos ao trato respiratório/gastrointestinal.",
            "notas_medico": "Tratamento sintomático. Considerar o caráter corrosivo do produto antes de procedimentos como lavagem gástrica. Não há antídoto específico conhecido.",
        }
    if flags["irritante"]:
        return {
            "inalacao": "Remova a pessoa para um local ventilado. Em caso de desconforto persistente, procure atendimento médico.",
            "contato_pele": "Lave a pele com água e sabão em abundância. Em caso de irritação persistente, procure atendimento médico.",
            "contato_olhos": "Enxágue cuidadosamente com água durante vários minutos. Remova lentes de contato, se presentes e fácil de fazer. Se a irritação ocular persistir, consulte um médico.",
            "ingestao": "Enxágue a boca com água. Procure atendimento médico se sentir indisposição.",
            "sintomas": "Pode provocar irritação da pele, dos olhos e das vias respiratórias.",
            "notas_medico": "Tratamento sintomático. Não há antídoto específico conhecido.",
        }
    return {
        "inalacao": "Remova a pessoa para um local ventilado. Procure atendimento médico se os sintomas persistirem.",
        "contato_pele": "Lave a pele com água em abundância.",
        "contato_olhos": "Enxágue os olhos com água em abundância. Procure atendimento médico se a irritação persistir.",
        "ingestao": "Enxágue a boca com água. Procure atendimento médico se sentir indisposição.",
        "sintomas": "Não são esperados efeitos adversos significativos nas condições normais de uso.",
        "notas_medico": "Tratamento sintomático, conforme quadro clínico apresentado.",
    }


def frases_combate_incendio(flags: dict, extras: dict) -> dict:
    return {
        "meios_apropriados": extras.get("meios_extincao_apropriados")
        or "Água pulverizada/nebulizada, pó químico seco, espuma resistente ao álcool ou dióxido de carbono (CO2). Selecionar o meio de extinção conforme o material envolvido no entorno do incêndio.",
        "meios_nao_apropriados": extras.get("meios_extincao_inadequados")
        or "Não utilizar jato de água direto e pressurizado, que pode espalhar o produto.",
        "perigos_especificos": extras.get("perigos_incendio")
        or ("A decomposição térmica pode liberar gases/vapores irritantes ou tóxicos." if (flags["corrosivo"] or flags["irritante"]) else "Não são esperados perigos específicos de combustão além dos comuns a incêndios."),
        "medidas_bombeiros": "Utilizar equipamento de respiração autônoma com pressão positiva e vestuário de proteção química completo. Resfriar os recipientes expostos ao fogo, se seguro fazê-lo.",
    }


def frases_vazamento(flags: dict) -> dict:
    protecao = "roupa de proteção individual completa, conforme indicado na Seção 8" if (flags["corrosivo"] or flags["irritante"]) else "equipamento de proteção individual básico"
    return {
        "precaucoes_pessoais_nao_emergencial": f"Evitar contato com o produto derramado. Usar {protecao}. Garantir ventilação adequada do local.",
        "precaucoes_pessoais_emergencia": "Isolar a área do vazamento. Utilizar equipamento de proteção individual completo, conforme descrito na Seção 8.",
        "precaucoes_ambientais": "Não permitir que o produto atinja canalizações, esgotos, águas subterrâneas ou cursos d'água. Em caso de contaminação significativa, notificar as autoridades competentes locais.",
        "metodos_contencao": "Conter o derramamento com materiais absorventes inertes (areia, terra, diatomito, ou outro material inerte compatível) ou diques, conforme o volume.",
        "metodos_limpeza": "Recolher o material derramado com auxílio de utensílios adequados e transferir para recipientes apropriados para descarte conforme a Seção 13. Lavar a área com água em abundância após a remoção do produto.",
    }


def frases_manuseio_armazenamento(flags: dict, extras: dict, estado_fisico: str) -> dict:
    forma = "vapores/névoas" if estado_fisico == "liquido" else "poeiras"
    return {
        "manuseio_seguro": extras.get("manuseio_seguro")
        or f"Manusear em área com ventilação adequada. Evitar contato com a pele, os olhos e a roupa. Não inalar {forma} do produto. Utilizar o equipamento de proteção individual indicado na Seção 8.",
        "medidas_higiene": "Proibido comer, beber ou fumar na área de trabalho. Remover imediatamente o vestuário contaminado. Lavar as mãos e o rosto cuidadosamente após o manuseio.",
        "condicoes_armazenamento": extras.get("condicoes_armazenamento")
        or "Conservar em local fresco, seco e bem ventilado, em recipientes bem fechados, ao abrigo de luz solar direta.",
        "materiais_incompativeis": extras.get("materiais_incompativeis")
        or ("Agentes oxidantes fortes e bases fortes." if flags["corrosivo"] else "Nenhum conhecido nas condições normais de uso."),
    }


def frases_epi(flags: dict, extras: dict) -> dict:
    if flags["corrosivo"]:
        return {
            "protecao_olhos": extras.get("epi_olhos") or "Óculos de segurança de ampla visão contra respingos químicos e/ou protetor facial completo.",
            "protecao_pele": extras.get("epi_pele") or "Vestuário de proteção química resistente ao produto (avental ou macacão).",
            "protecao_maos": extras.get("epi_maos") or "Luvas de proteção impermeáveis e resistentes ao produto.",
            "protecao_respiratoria": extras.get("epi_respiratoria") or "Em ambientes com ventilação insuficiente, utilizar respirador com filtro adequado ao produto.",
            "controles_engenharia": "Assegurar ventilação adequada. Disponibilizar chuveiro de emergência e lava-olhos no local de trabalho.",
        }
    return {
        "protecao_olhos": extras.get("epi_olhos") or "Óculos de segurança.",
        "protecao_pele": extras.get("epi_pele") or "Vestuário de proteção conforme a atividade.",
        "protecao_maos": extras.get("epi_maos") or "Luvas de proteção adequadas ao manuseio.",
        "protecao_respiratoria": extras.get("epi_respiratoria") or "Não são necessárias medidas especiais nas condições normais de uso; avaliar conforme ventilação do local.",
        "controles_engenharia": "Assegurar ventilação adequada do local de trabalho.",
    }


def frases_estabilidade_reatividade(flags: dict, extras: dict) -> dict:
    return {
        "reatividade": extras.get("reatividade") or ("Produto de caráter corrosivo. Pode reagir com agentes oxidantes fortes e bases fortes." if flags["corrosivo"] else "Não são esperadas reações perigosas nas condições normais de uso."),
        "estabilidade_quimica": "Estável sob condições normais de uso, manuseio e armazenamento recomendadas.",
        "reacoes_perigosas": extras.get("reacoes_perigosas") or ("Pode reagir com materiais incompatíveis listados na Seção 10, com liberação de calor e/ou gases." if flags["corrosivo"] else "Não são conhecidas reações perigosas nas condições normais de uso."),
        "condicoes_evitar": "Temperaturas elevadas, fontes de ignição e contato com materiais incompatíveis.",
        "materiais_incompativeis": extras.get("materiais_incompativeis") or ("Agentes oxidantes fortes, bases fortes." if flags["corrosivo"] else "Nenhum conhecido nas condições normais de uso."),
        "produtos_decomposicao": extras.get("produtos_decomposicao") or "Não disponível.",
    }


def frases_ecologicas(extras: dict) -> dict:
    return {
        "ecotoxicidade": extras.get("ecotoxicidade") or "Não disponível.",
        "persistencia_degradabilidade": extras.get("persistencia") or "Não disponível.",
        "potencial_bioacumulacao": extras.get("bioacumulacao") or "Não disponível.",
        "mobilidade_solo": extras.get("mobilidade_solo") or "Não disponível.",
        "outros_efeitos": extras.get("outros_efeitos_ecologicos") or "Não disponível.",
    }


def frases_destinacao_final(extras: dict) -> dict:
    return {
        "residuos_produto": extras.get("destinacao_residuos")
        or "Descartar conforme a regulamentação local, estadual e federal aplicável (incluindo a Lei nº 12.305/2010 - Política Nacional de Resíduos Sólidos). Não descartar em esgotos, cursos d'água ou solo.",
        "embalagens": extras.get("destinacao_embalagens")
        or "Não reutilizar embalagens vazias para outros fins. Descartar conforme a regulamentação aplicável a resíduos perigosos, ou encaminhar a empresas especializadas em descontaminação.",
    }


def frases_regulamentacoes(extras: dict) -> list:
    base = [
        "ABNT NBR 14725:2023 - Produtos químicos — Informações sobre segurança, saúde e meio ambiente — Sistema Globalmente Harmonizado (GHS), classificação, FDS e rotulagem de produtos químicos.",
        "Norma Regulamentadora nº 26 (NR-26) - Sinalização de Segurança.",
        "Lei nº 12.305/2010 - Política Nacional de Resíduos Sólidos.",
    ]
    extra_texto = extras.get("regulamentacoes_adicionais")
    if extra_texto:
        base.extend([linha.strip() for linha in extra_texto.splitlines() if linha.strip()])
    return base


LEGENDA_PADRAO = {
    "ABNT": "Associação Brasileira de Normas Técnicas",
    "CAS": "Chemical Abstracts Service",
    "DL50": "Dose Letal 50%",
    "CL50": "Concentração Letal 50%",
    "EPI": "Equipamento de Proteção Individual",
    "ETA": "Estimativa de Toxicidade Aguda",
    "FDS": "Ficha de Dados de Segurança",
    "GHS": "Sistema Globalmente Harmonizado de Classificação e Rotulagem de Produtos Químicos",
    "NBR": "Norma Brasileira",
    "NR": "Norma Regulamentadora",
    "ONU": "Organização das Nações Unidas",
    "STOT": "Toxicidade para Órgãos-alvo Específicos",
}

_NOMES_PICTOGRAMA = {
    "corrosao": "Corrosão (GHS05)",
    "exclamacao": "Ponto de exclamação (GHS07)",
    "caveira": "Caveira e ossos cruzados (GHS06)",
}

_NOMES_VIA_TOXICIDADE = {
    "oral": "Via oral",
    "dermica": "Via dérmica",
    "inalatoria_gases": "Via inalatória (gases)",
    "inalatoria_vapores": "Via inalatória (vapores)",
    "inalatoria_poeiras_nevoas": "Via inalatória (poeiras/névoas)",
}


# ---------------------------------------------------------------------------
# Blocos de conteúdo de uma seção — cada seção da FDS é uma lista de blocos.
# Um bloco é sempre um dict com "tipo" e os dados daquele tipo, para que o
# renderizador de PDF (gerar_pdf_fds) saiba como desenhá-lo sem precisar
# inspecionar a seção inteira.
# ---------------------------------------------------------------------------

def _bloco_campos(pares: list[tuple[str, str]]) -> dict:
    """Bloco tabela de 2 colunas (rótulo | valor) — o padrão Fosfeed/Safeeds."""
    return {"tipo": "campos", "pares": pares}


def _bloco_tabela(cabecalhos: list[str], linhas: list[list[str]]) -> dict:
    """Bloco tabela de N colunas com cabeçalho (ex.: composição, seção 3)."""
    return {"tipo": "tabela", "cabecalhos": cabecalhos, "linhas": linhas}


def _bloco_lista(titulo: str, itens: list[str]) -> dict:
    """Bloco de lista simples de linhas de texto, com um rótulo à esquerda
    (ex.: 'Frases H', 'Frases P — Prevenção') e os itens empilhados numa
    única célula à direita — mesmo estilo do modelo Fosfeed."""
    return {"tipo": "lista", "titulo": titulo, "itens": itens}


def _bloco_texto(texto: str) -> dict:
    """Bloco de texto corrido, ocupando a largura toda (ex.: aviso legal)."""
    return {"tipo": "texto", "texto": texto}


def montar_dados_fds(
    perfil_empresa: dict,
    produto_info: dict,
    composicao: list,
    estado_fisico: str,
    resultado_toxicidade_aguda: dict,
    resultado_pele: dict,
    resultado_olhos: dict,
    banco=None,
    campos_extras: Optional[dict] = None,
    data_emissao: Optional[date] = None,
    numero_revisao: str = "01",
) -> dict:
    """Monta a estrutura completa das 16 seções da FDS, combinando:
      - o perfil da empresa (identificação, seção 1);
      - os dados do produto informados na tela (nome, uso recomendado etc.);
      - a composição (para a tabela da seção 3 — usa `banco`, se fornecido,
        para buscar a classificação intrínseca de cada matéria-prima);
      - os resultados JÁ CALCULADOS pelos motores de toxicidade aguda e de
        corrosão/irritação (seções 2 e 11);
      - `campos_extras`: dicionário achatado e totalmente opcional com
        campos manuais que o usuário pode preencher para sobrescrever as
        frases padrão ou preencher dados de ensaio que o sistema não
        calcula (propriedades físico-químicas, transporte etc.). Qualquer
        campo não informado aparece como "Não disponível" — nunca é
        inventado um valor.

    Não decide nem recalcula nenhuma classificação: só formata o que os
    motores já decidiram e o que o usuário informou.
    """
    extras = campos_extras or {}
    data_emissao = data_emissao or date.today()
    data_str = data_emissao.strftime("%d/%m/%Y")

    rotulo = derivar_rotulo_ghs(resultado_toxicidade_aguda, resultado_pele, resultado_olhos)
    flags = rotulo["flags"]

    nome_produto = produto_info.get("nome_produto", "")

    secoes = {}

    # --- Seção 1 — Identificação --------------------------------------
    secoes["1"] = {
        "titulo": "IDENTIFICAÇÃO",
        "blocos": [
            _bloco_campos([
                ("Nome do produto", nome_produto or "Não informado"),
                ("Código interno do produto", produto_info.get("codigo_produto") or "Não disponível"),
                ("Uso recomendado", produto_info.get("uso_recomendado") or "Não informado"),
                ("Restrições de uso", produto_info.get("restricoes_uso") or "Não disponível"),
            ]),
            _bloco_campos([
                ("Razão social do fornecedor", perfil_empresa.get("razao_social") or "Não informado"),
                ("CNPJ", perfil_empresa.get("cnpj") or "Não disponível"),
                ("Endereço", perfil_empresa.get("endereco") or "Não disponível"),
                ("Telefone", perfil_empresa.get("telefone") or "Não disponível"),
                ("E-mail", perfil_empresa.get("email") or "Não disponível"),
                ("Telefone de emergência", perfil_empresa.get("telefone_emergencia") or "Não disponível"),
            ]),
        ],
    }

    # --- Seção 2 — Identificação de perigos -----------------------------
    linhas_classificacao = []
    for via, resultado in (resultado_toxicidade_aguda or {}).items():
        nome_via = _NOMES_VIA_TOXICIDADE.get(via, via)
        categoria = resultado.get("categoria")
        if categoria is not None:
            linhas_classificacao.append(f"Toxicidade aguda — {nome_via}: Categoria {categoria}")
        elif resultado.get("declaracao_obrigatoria"):
            linhas_classificacao.append(f"Toxicidade aguda — {nome_via}: não classificada ({resultado['declaracao_obrigatoria']})")
    if (resultado_pele or {}).get("categoria"):
        linhas_classificacao.append(f"Corrosão/irritação à pele: Categoria {resultado_pele['categoria']}")
    if (resultado_olhos or {}).get("categoria"):
        linhas_classificacao.append(f"Lesão ocular grave/irritação ocular: Categoria {resultado_olhos['categoria']}")
    if not linhas_classificacao:
        linhas_classificacao.append("Não classificado como perigoso para as classes calculadas por este sistema (toxicidade aguda e corrosão/irritação à pele e olhos).")

    blocos_secao2 = [
        _bloco_lista("Classificação da mistura (calculada)", linhas_classificacao),
        _bloco_campos([
            ("Palavra de advertência", rotulo["palavra_advertencia"] or "Nenhuma"),
            ("Pictogramas", ", ".join(_NOMES_PICTOGRAMA[p] for p in rotulo["pictogramas"]) or "Nenhum"),
        ]),
        _bloco_lista("Frases de perigo (H)", [f"{c['codigo']} - {c['descricao']}" for c in rotulo["codigos_h"]] or ["Não aplicável."]),
    ]
    for grupo, itens in rotulo["codigos_p_por_grupo"].items():
        if itens:
            blocos_secao2.append(_bloco_lista(f"Frases de precaução (P) — {grupo}", [f"{c['codigo']} - {c['descricao']}" for c in itens]))
    blocos_secao2.append(_bloco_campos([
        ("Outros perigos", extras.get("outros_perigos") or "Não classificado para outras classes de perigo com base nos dados calculados por este sistema (ver limitações na Seção 16)."),
    ]))
    secoes["2"] = {"titulo": "IDENTIFICAÇÃO DE PERIGOS", "blocos": blocos_secao2}

    # --- Seção 3 — Composição e informações sobre os ingredientes --------
    linhas_composicao = []
    for item in composicao:
        segredo = item.get("segredo_industrial", False)
        nome_i = "Segredo Industrial" if segredo else item.get("nome", "")
        cas_i = "Segredo Industrial" if segredo else (item.get("cas") or "Não disponível")
        conc_i = f"{item.get('concentracao', 0):.2f}%"
        if segredo:
            classif_i = "Não divulgada (segredo industrial)"
        elif banco is not None and item.get("cas"):
            codigos = obter_h_codes_substancia(banco, item["cas"])
            classif_i = ", ".join(codigos) if codigos else "Não classificado / não disponível no Anexo VI"
        else:
            classif_i = "Não disponível"
        linhas_composicao.append([nome_i, cas_i, conc_i, classif_i])

    secoes["3"] = {
        "titulo": "COMPOSIÇÃO E INFORMAÇÕES SOBRE OS INGREDIENTES",
        "blocos": [
            _bloco_campos([("Natureza química", extras.get("natureza_quimica") or "Mistura")]),
            _bloco_tabela(["Nome / Identificação", "Nº CAS", "Concentração", "Classificação de perigo"], linhas_composicao),
        ],
    }

    # --- Seção 4 — Primeiros socorros ------------------------------------
    fp = frases_primeiros_socorros(flags)
    secoes["4"] = {
        "titulo": "MEDIDAS DE PRIMEIROS SOCORROS",
        "blocos": [_bloco_campos([
            ("Inalação", fp["inalacao"]),
            ("Contato com a pele", fp["contato_pele"]),
            ("Contato com os olhos", fp["contato_olhos"]),
            ("Ingestão", fp["ingestao"]),
            ("Principais sintomas e efeitos", fp["sintomas"]),
            ("Notas para o médico", fp["notas_medico"]),
        ])],
    }

    # --- Seção 5 — Combate a incêndio -------------------------------------
    fi = frases_combate_incendio(flags, extras)
    secoes["5"] = {
        "titulo": "MEDIDAS DE COMBATE A INCÊNDIO",
        "blocos": [_bloco_campos([
            ("Meios de extinção apropriados", fi["meios_apropriados"]),
            ("Meios de extinção não apropriados", fi["meios_nao_apropriados"]),
            ("Perigos específicos do produto", fi["perigos_especificos"]),
            ("Medidas de proteção da equipe de combate a incêndio", fi["medidas_bombeiros"]),
        ])],
    }

    # --- Seção 6 — Medidas de controle para derramamento ou vazamento ----
    fv = frases_vazamento(flags)
    secoes["6"] = {
        "titulo": "MEDIDAS DE CONTROLE PARA DERRAMAMENTO OU VAZAMENTO",
        "blocos": [_bloco_campos([
            ("Precauções pessoais (pessoal não emergencial)", fv["precaucoes_pessoais_nao_emergencial"]),
            ("Precauções pessoais (equipe de emergência)", fv["precaucoes_pessoais_emergencia"]),
            ("Precauções ao meio ambiente", fv["precaucoes_ambientais"]),
            ("Métodos de contenção", fv["metodos_contencao"]),
            ("Métodos de limpeza", fv["metodos_limpeza"]),
        ])],
    }

    # --- Seção 7 — Manuseio e armazenamento -------------------------------
    fm = frases_manuseio_armazenamento(flags, extras, estado_fisico)
    secoes["7"] = {
        "titulo": "MANUSEIO E ARMAZENAMENTO",
        "blocos": [_bloco_campos([
            ("Manuseio seguro", fm["manuseio_seguro"]),
            ("Medidas de higiene", fm["medidas_higiene"]),
            ("Condições de armazenamento", fm["condicoes_armazenamento"]),
            ("Produtos e materiais incompatíveis", fm["materiais_incompativeis"]),
        ])],
    }

    # --- Seção 8 — Controle de exposição / EPI ----------------------------
    fe = frases_epi(flags, extras)
    secoes["8"] = {
        "titulo": "CONTROLE DE EXPOSIÇÃO E PROTEÇÃO INDIVIDUAL",
        "blocos": [_bloco_campos([
            ("Limites de exposição ocupacional", extras.get("limites_exposicao") or "Não estabelecidos para os componentes desta mistura."),
            ("Controles de engenharia apropriados", fe["controles_engenharia"]),
            ("Proteção dos olhos/face", fe["protecao_olhos"]),
            ("Proteção da pele/corpo", fe["protecao_pele"]),
            ("Proteção das mãos", fe["protecao_maos"]),
            ("Proteção respiratória", fe["protecao_respiratoria"]),
        ])],
    }

    # --- Seção 9 — Propriedades físicas e químicas ------------------------
    nome_estado = "Líquido" if estado_fisico == "liquido" else "Sólido pulverulento"
    secoes["9"] = {
        "titulo": "PROPRIEDADES FÍSICAS E QUÍMICAS",
        "blocos": [_bloco_campos([
            ("Estado físico", nome_estado),
            ("Cor", extras.get("cor") or "Não disponível"),
            ("Odor", extras.get("odor") or "Não disponível"),
            ("pH", extras.get("ph") or "Não disponível"),
            ("Ponto de fusão/congelamento", extras.get("ponto_fusao") or "Não disponível"),
            ("Ponto de ebulição inicial e faixa", extras.get("ponto_ebulicao") or "Não disponível"),
            ("Ponto de fulgor", extras.get("ponto_fulgor") or "Não disponível"),
            ("Taxa de evaporação", extras.get("taxa_evaporacao") or "Não disponível"),
            ("Inflamabilidade", extras.get("inflamabilidade") or "Não determinada"),
            ("Limites inferior/superior de inflamabilidade ou explosividade", extras.get("limites_explosividade") or "Não disponível"),
            ("Pressão de vapor", extras.get("pressao_vapor") or "Não disponível"),
            ("Densidade de vapor", extras.get("densidade_vapor") or "Não disponível"),
            ("Densidade relativa", extras.get("densidade_relativa") or "Não disponível"),
            ("Solubilidade em água", extras.get("solubilidade_agua") or "Não disponível"),
            ("Coeficiente de partição n-octanol/água", extras.get("coeficiente_particao") or "Não disponível"),
            ("Temperatura de auto-ignição", extras.get("temperatura_autoignicao") or "Não disponível"),
            ("Temperatura de decomposição", extras.get("temperatura_decomposicao") or "Não disponível"),
            ("Viscosidade", extras.get("viscosidade") or "Não disponível"),
        ])],
    }

    # --- Seção 10 — Estabilidade e reatividade -----------------------------
    fr = frases_estabilidade_reatividade(flags, extras)
    secoes["10"] = {
        "titulo": "ESTABILIDADE E REATIVIDADE",
        "blocos": [_bloco_campos([
            ("Reatividade", fr["reatividade"]),
            ("Estabilidade química", fr["estabilidade_quimica"]),
            ("Possibilidade de reações perigosas", fr["reacoes_perigosas"]),
            ("Condições a evitar", fr["condicoes_evitar"]),
            ("Materiais incompatíveis", fr["materiais_incompativeis"]),
            ("Produtos perigosos da decomposição", fr["produtos_decomposicao"]),
        ])],
    }

    # --- Seção 11 — Informações toxicológicas ------------------------------
    linhas_tox = []
    for via, resultado in (resultado_toxicidade_aguda or {}).items():
        nome_via = _NOMES_VIA_TOXICIDADE.get(via, via)
        categoria = resultado.get("categoria")
        eta = resultado.get("eta_mistura")
        if categoria is not None and eta is not None:
            linhas_tox.append(f"{nome_via}: ETA (estimativa de toxicidade aguda) da mistura ≈ {eta} — Categoria {categoria}.")
        elif resultado.get("declaracao_obrigatoria"):
            linhas_tox.append(f"{nome_via}: {resultado['declaracao_obrigatoria']}")
        else:
            linhas_tox.append(f"{nome_via}: não classificado com os dados informados.")
    if (resultado_pele or {}).get("categoria"):
        linhas_tox.append(f"Corrosão/irritação à pele: Categoria {resultado_pele['categoria']} (critério: {resultado_pele.get('criterio') or 'não disponível'}).")
    else:
        linhas_tox.append("Corrosão/irritação à pele: não classificada com os dados informados.")
    if (resultado_olhos or {}).get("categoria"):
        linhas_tox.append(f"Lesão ocular grave/irritação ocular: Categoria {resultado_olhos['categoria']} (critério: {resultado_olhos.get('criterio') or 'não disponível'}).")
    else:
        linhas_tox.append("Lesão ocular grave/irritação ocular: não classificada com os dados informados.")

    secoes["11"] = {
        "titulo": "INFORMAÇÕES TOXICOLÓGICAS",
        "blocos": [
            _bloco_lista("Toxicidade aguda e corrosão/irritação (calculadas)", linhas_tox),
            _bloco_campos([
                ("Sensibilização", extras.get("sensibilizacao") or "Não disponível"),
                ("Mutagenicidade em células germinativas", extras.get("mutagenicidade") or "Não disponível"),
                ("Carcinogenicidade", extras.get("carcinogenicidade") or "Não disponível"),
                ("Toxicidade à reprodução", extras.get("toxicidade_reproducao") or "Não disponível"),
                ("Toxicidade para órgãos-alvo específicos (STOT) — exposição única", extras.get("stot_unica") or "Não disponível"),
                ("Toxicidade para órgãos-alvo específicos (STOT) — exposição repetida", extras.get("stot_repetida") or "Não disponível"),
                ("Perigo de aspiração", extras.get("perigo_aspiracao") or "Não disponível"),
            ]),
        ],
    }

    # --- Seção 12 — Informações ecológicas ---------------------------------
    fec = frases_ecologicas(extras)
    secoes["12"] = {
        "titulo": "INFORMAÇÕES ECOLÓGICAS",
        "blocos": [_bloco_campos([
            ("Ecotoxicidade", fec["ecotoxicidade"]),
            ("Persistência e degradabilidade", fec["persistencia_degradabilidade"]),
            ("Potencial bioacumulativo", fec["potencial_bioacumulacao"]),
            ("Mobilidade no solo", fec["mobilidade_solo"]),
            ("Outros efeitos adversos", fec["outros_efeitos"]),
        ])],
    }

    # --- Seção 13 — Considerações sobre destinação final --------------------
    fd = frases_destinacao_final(extras)
    secoes["13"] = {
        "titulo": "CONSIDERAÇÕES SOBRE DESTINAÇÃO FINAL",
        "blocos": [_bloco_campos([
            ("Métodos e materiais para destinação final do produto", fd["residuos_produto"]),
            ("Métodos e materiais para destinação final de embalagens", fd["embalagens"]),
        ])],
    }

    # --- Seção 14 — Informações sobre transporte ------------------------------
    secoes["14"] = {
        "titulo": "INFORMAÇÕES SOBRE TRANSPORTE",
        "blocos": [_bloco_campos([
            ("Número ONU", extras.get("numero_onu") or "Não classificado"),
            ("Nome apropriado para embarque", extras.get("nome_embarque") or "Não disponível"),
            ("Classe de risco", extras.get("classe_risco") or "Não classificado"),
            ("Número de risco", extras.get("numero_risco") or "Não disponível"),
            ("Grupo de embalagem", extras.get("grupo_embalagem") or "Não disponível"),
            ("Perigos ambientais para o transporte", extras.get("perigo_ambiental_transporte") or "Não disponível"),
            ("Precauções especiais para o usuário", extras.get("precaucoes_transporte") or "Não disponível"),
        ])],
    }

    # --- Seção 15 — Regulamentações ----------------------------------------
    secoes["15"] = {
        "titulo": "REGULAMENTAÇÕES",
        "blocos": [_bloco_lista("Regulamentações aplicáveis", frases_regulamentacoes(extras))],
    }

    # --- Seção 16 — Outras informações --------------------------------------
    linhas_legenda = [f"{sigla} - {significado}" for sigla, significado in LEGENDA_PADRAO.items()]
    secoes["16"] = {
        "titulo": "OUTRAS INFORMAÇÕES",
        "blocos": [
            _bloco_campos([
                ("Data de emissão desta FDS", data_str),
                ("Número da revisão", numero_revisao),
            ]),
            _bloco_lista("Legenda / abreviaturas", linhas_legenda),
            _bloco_texto(
                extras.get("aviso_legal")
                or "As informações contidas nesta Ficha de Dados de Segurança foram elaboradas com base nos dados "
                "disponíveis até a data de emissão indicada acima e correspondem ao melhor conhecimento atual sobre o "
                "produto. A classificação de perigo apresentada nas Seções 2 e 11 foi obtida por cálculo determinístico "
                "a partir da composição informada, conforme a ABNT NBR 14725:2023, e cobre apenas as classes de perigo "
                "calculadas por este sistema (toxicidade aguda e corrosão/irritação à pele e olhos) — outras classes de "
                "perigo (inflamabilidade, propriedades explosivas, corrosivo a metais, toxicidade para órgãos-alvo "
                "específicos, perigo ao ambiente aquático agudo/crônico, entre outras) não foram avaliadas por cálculo e "
                "só constam nesta ficha quando informadas manualmente. Esta ficha não substitui a avaliação técnica de "
                "um responsável qualificado para o uso específico pretendido pelo destinatário."
            ),
        ],
    }

    return {
        "cabecalho": {
            "produto": nome_produto,
            "data_emissao": data_str,
            "numero_revisao": numero_revisao,
            "empresa_nome": perfil_empresa.get("razao_social") or "",
        },
        "secoes": secoes,
    }


# ---------------------------------------------------------------------------
# Geração do PDF — layout de duas colunas (rótulo | valor), estilo
# Fosfeed/Safeeds: barra cinza de título de seção em largura total, tabelas
# label/valor logo abaixo, sem logotipo/pictogramas gráficos (só texto),
# rodapé com identificador do documento e numeração de página.
# ---------------------------------------------------------------------------

def gerar_pdf_fds(dados: dict, caminho_saida: str) -> str:
    """Renderiza `dados` (saída de `montar_dados_fds`) num PDF no layout
    escolhido pelo usuário. Usa reportlab (Platypus), já disponível no
    ambiente — sem dependência de bibliotecas externas de HTML-para-PDF."""
    from reportlab.lib.pagesizes import A4
    from reportlab.lib.units import cm
    from reportlab.lib import colors
    from reportlab.lib.styles import getSampleStyleSheet, ParagraphStyle
    from reportlab.lib.enums import TA_LEFT, TA_RIGHT, TA_CENTER
    from reportlab.platypus import (
        SimpleDocTemplate, Table, TableStyle, Paragraph, Spacer, KeepTogether,
    )
    from reportlab.pdfgen import canvas as pdfcanvas

    estilos = getSampleStyleSheet()
    estilo_rotulo = ParagraphStyle(
        "Rotulo", parent=estilos["Normal"], fontName="Helvetica-Bold", fontSize=8.5, leading=11,
    )
    estilo_valor = ParagraphStyle(
        "Valor", parent=estilos["Normal"], fontName="Helvetica", fontSize=8.5, leading=11,
    )
    estilo_secao = ParagraphStyle(
        "Secao", parent=estilos["Normal"], fontName="Helvetica-Bold", fontSize=10.5, leading=13,
        textColor=colors.white,
    )
    estilo_titulo_produto = ParagraphStyle(
        "TituloProduto", parent=estilos["Normal"], fontName="Helvetica-Bold", fontSize=16, leading=19,
    )
    estilo_fds_wordmark = ParagraphStyle(
        "FdsWordmark", parent=estilos["Normal"], fontName="Helvetica-Bold", fontSize=20, leading=22,
        alignment=TA_RIGHT,
    )
    estilo_cabecalho_info = ParagraphStyle(
        "CabecalhoInfo", parent=estilos["Normal"], fontName="Helvetica", fontSize=8.5, leading=11,
    )
    estilo_tabela_cabecalho = ParagraphStyle(
        "TabCabecalho", parent=estilos["Normal"], fontName="Helvetica-Bold", fontSize=8.5, leading=11,
        textColor=colors.white,
    )
    estilo_texto_corrido = ParagraphStyle(
        "TextoCorrido", parent=estilos["Normal"], fontName="Helvetica", fontSize=8, leading=10.5,
    )

    LARGURA_UTIL = A4[0] - 2 * 1.5 * cm
    COR_BARRA_SECAO = colors.HexColor("#4d4d4d")
    COR_LINHA = colors.HexColor("#999999")
    COR_FUNDO_ROTULO = colors.HexColor("#f2f2f2")

    elementos = []

    cab = dados["cabecalho"]

    # --- Cabeçalho do documento (texto, sem logotipo) ---
    tabela_cabecalho = Table(
        [[
            Paragraph(cab["empresa_nome"] or "", estilo_cabecalho_info),
            Paragraph("FDS", estilo_fds_wordmark),
        ]],
        colWidths=[LARGURA_UTIL * 0.7, LARGURA_UTIL * 0.3],
    )
    tabela_cabecalho.setStyle(TableStyle([
        ("VALIGN", (0, 0), (-1, -1), "MIDDLE"),
        ("LEFTPADDING", (0, 0), (-1, -1), 0),
        ("RIGHTPADDING", (0, 0), (-1, -1), 0),
    ]))
    elementos.append(tabela_cabecalho)
    elementos.append(Spacer(1, 0.2 * cm))
    elementos.append(Paragraph(f"FICHA DE DADOS DE SEGURANÇA — {cab['produto'] or 'PRODUTO'}", estilo_titulo_produto))
    elementos.append(Spacer(1, 0.1 * cm))

    tabela_meta = Table(
        [[
            Paragraph(f"<b>Data de emissão:</b> {cab['data_emissao']}", estilo_cabecalho_info),
            Paragraph(f"<b>Revisão:</b> {cab['numero_revisao']}", estilo_cabecalho_info),
        ]],
        colWidths=[LARGURA_UTIL * 0.5, LARGURA_UTIL * 0.5],
    )
    tabela_meta.setStyle(TableStyle([
        ("LEFTPADDING", (0, 0), (-1, -1), 0),
        ("BOTTOMPADDING", (0, 0), (-1, -1), 2),
        ("LINEBELOW", (0, 0), (-1, -1), 0.75, COR_LINHA),
    ]))
    elementos.append(tabela_meta)
    elementos.append(Spacer(1, 0.3 * cm))

    def _barra_secao(numero: str, titulo: str):
        t = Table(
            [[Paragraph(f"{numero} - {titulo}", estilo_secao)]],
            colWidths=[LARGURA_UTIL],
        )
        t.setStyle(TableStyle([
            ("BACKGROUND", (0, 0), (-1, -1), COR_BARRA_SECAO),
            ("LEFTPADDING", (0, 0), (-1, -1), 6),
            ("TOPPADDING", (0, 0), (-1, -1), 4),
            ("BOTTOMPADDING", (0, 0), (-1, -1), 4),
        ]))
        return t

    def _tabela_campos(pares):
        linhas = [[Paragraph(rotulo, estilo_rotulo), Paragraph(str(valor), estilo_valor)] for rotulo, valor in pares]
        t = Table(linhas, colWidths=[LARGURA_UTIL * 0.32, LARGURA_UTIL * 0.68])
        t.setStyle(TableStyle([
            ("BACKGROUND", (0, 0), (0, -1), COR_FUNDO_ROTULO),
            ("VALIGN", (0, 0), (-1, -1), "TOP"),
            ("GRID", (0, 0), (-1, -1), 0.5, COR_LINHA),
            ("LEFTPADDING", (0, 0), (-1, -1), 5),
            ("RIGHTPADDING", (0, 0), (-1, -1), 5),
            ("TOPPADDING", (0, 0), (-1, -1), 3),
            ("BOTTOMPADDING", (0, 0), (-1, -1), 3),
        ]))
        return t

    def _tabela_lista(titulo, itens):
        texto_html = "<br/>".join(itens) if itens else "Não aplicável."
        t = Table(
            [[Paragraph(titulo, estilo_rotulo), Paragraph(texto_html, estilo_valor)]],
            colWidths=[LARGURA_UTIL * 0.32, LARGURA_UTIL * 0.68],
        )
        t.setStyle(TableStyle([
            ("BACKGROUND", (0, 0), (0, -1), COR_FUNDO_ROTULO),
            ("VALIGN", (0, 0), (-1, -1), "TOP"),
            ("GRID", (0, 0), (-1, -1), 0.5, COR_LINHA),
            ("LEFTPADDING", (0, 0), (-1, -1), 5),
            ("RIGHTPADDING", (0, 0), (-1, -1), 5),
            ("TOPPADDING", (0, 0), (-1, -1), 3),
            ("BOTTOMPADDING", (0, 0), (-1, -1), 3),
        ]))
        return t

    def _tabela_multicolunas(cabecalhos, linhas_dados):
        largura_col = LARGURA_UTIL / len(cabecalhos)
        linha_cabecalho = [Paragraph(c, estilo_tabela_cabecalho) for c in cabecalhos]
        linhas_render = [linha_cabecalho] + [
            [Paragraph(str(v), estilo_valor) for v in linha] for linha in linhas_dados
        ]
        t = Table(linhas_render, colWidths=[largura_col] * len(cabecalhos), repeatRows=1)
        t.setStyle(TableStyle([
            ("BACKGROUND", (0, 0), (-1, 0), COR_BARRA_SECAO),
            ("VALIGN", (0, 0), (-1, -1), "TOP"),
            ("GRID", (0, 0), (-1, -1), 0.5, COR_LINHA),
            ("LEFTPADDING", (0, 0), (-1, -1), 5),
            ("RIGHTPADDING", (0, 0), (-1, -1), 5),
            ("TOPPADDING", (0, 0), (-1, -1), 3),
            ("BOTTOMPADDING", (0, 0), (-1, -1), 3),
        ]))
        return t

    for numero in [str(n) for n in range(1, 17)]:
        secao = dados["secoes"][numero]
        bloco_secao = [_barra_secao(numero, secao["titulo"])]
        for bloco in secao["blocos"]:
            if bloco["tipo"] == "campos":
                bloco_secao.append(_tabela_campos(bloco["pares"]))
            elif bloco["tipo"] == "lista":
                bloco_secao.append(_tabela_lista(bloco["titulo"], bloco["itens"]))
            elif bloco["tipo"] == "tabela":
                bloco_secao.append(_tabela_multicolunas(bloco["cabecalhos"], bloco["linhas"]))
            elif bloco["tipo"] == "texto":
                bloco_secao.append(Spacer(1, 0.15 * cm))
                bloco_secao.append(Paragraph(bloco["texto"], estilo_texto_corrido))
        elementos.append(KeepTogether(bloco_secao[:1] + bloco_secao[1:2]))
        elementos.extend(bloco_secao[2:] if len(bloco_secao) > 2 else [])
        elementos.append(Spacer(1, 0.25 * cm))

    id_documento = f"FDS-{(cab['produto'] or 'PRODUTO').strip().upper().replace(' ', '-')[:24]}-{cab['numero_revisao']}"

    class _CanvasNumerado(pdfcanvas.Canvas):
        """Canvas que sabe o total de páginas no momento de desenhar o
        rodapé de cada uma (técnica padrão do reportlab: guarda o estado
        de cada página e só desenha o rodapé no save() final, quando o
        total já é conhecido) — necessário para poder escrever
        "Esta é a última página." somente na página final."""

        def __init__(self, *args, **kwargs):
            super().__init__(*args, **kwargs)
            self._paginas_salvas = []

        def showPage(self):
            self._paginas_salvas.append(dict(self.__dict__))
            self._startPage()

        def save(self):
            total = len(self._paginas_salvas)
            for i, estado in enumerate(self._paginas_salvas, start=1):
                self.__dict__.update(estado)
                self._desenhar_rodape(i, total)
                super().showPage()
            super().save()

        def _desenhar_rodape(self, pagina_atual, total_paginas):
            self.setFont("Helvetica", 7)
            self.setFillColor(colors.HexColor("#666666"))
            self.drawString(1.5 * cm, 1.0 * cm, id_documento)
            self.drawRightString(A4[0] - 1.5 * cm, 1.0 * cm, f"Página {pagina_atual} de {total_paginas}")
            if pagina_atual == total_paginas:
                self.drawCentredString(A4[0] / 2, 1.0 * cm, "Esta é a última página.")

    doc = SimpleDocTemplate(
        caminho_saida,
        pagesize=A4,
        leftMargin=1.5 * cm, rightMargin=1.5 * cm,
        topMargin=1.5 * cm, bottomMargin=1.8 * cm,
        title=f"FDS - {cab['produto']}",
    )
    doc.build(elementos, canvasmaker=_CanvasNumerado)
    return caminho_saida
