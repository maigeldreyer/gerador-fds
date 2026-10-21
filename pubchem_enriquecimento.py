"""
Enriquecimento via PubChem — complemento para substâncias sem entrada
no Anexo VI da ECHA.
==============================================================================

AVISO DE VALIDAÇÃO (leia antes de usar em produção):
Este módulo foi escrito e testado neste ambiente contra uma resposta
MOCKADA que reproduz fielmente o schema documentado do PUG View da
PubChem (a estrutura de "GHS Classification" com H-codes, percentuais
de notificadores e categoria entre colchetes). O ambiente de
desenvolvimento usado para construir este projeto bloqueia por
política de rede o acesso a pubchem.ncbi.nlm.nih.gov, então a chamada
HTTP real (função `_get`) não pôde ser exercitada ao vivo aqui.
RECOMENDA-SE rodar `testar_conexao_real()` no seu próprio computador
antes de confiar neste módulo em produção — se a estrutura da resposta
tiver mudado, os pontos de ajuste são só as funções `_extrair_cid` e
`_extrair_secao_ghs`.

Por que isso é "enriquecimento" e não fonte primária:
A classificação GHS que a PubChem expõe é um AGREGADO de notificações
de terceiros (frequentemente originadas do próprio C&L Inventory da
ECHA, replicadas). Ela pode trazer classificações divergentes para a
mesma substância, cada uma com um percentual de "quantos notificadores
reportaram aquilo". Por isso este módulo:
  - NUNCA sobrescreve uma classificação já vinda do Anexo VI
    (ECHA_ANEXO_VI é sempre a fonte de maior prioridade);
  - Quando há mais de uma categoria distinta reportada para a mesma
    classe de perigo, grava a mais frequente (maior percentual) mas
    registra o conflito explicitamente para revisão humana, em vez de
    escolher silenciosamente.
"""

import re
import time
from dataclasses import dataclass, field
from typing import Optional

import requests

PUG_REST_BASE = "https://pubchem.ncbi.nlm.nih.gov/rest/pug"
PUG_VIEW_BASE = "https://pubchem.ncbi.nlm.nih.gov/rest/pug_view"

# PubChem pede no máximo 5 requisições/segundo (ver conversa anterior) —
# aplicamos um intervalo mínimo conservador entre chamadas.
INTERVALO_MINIMO_ENTRE_CHAMADAS = 0.25  # segundos


@dataclass
class ClassificacaoEncontrada:
    h_code: str
    categoria_texto: str      # ex.: "Acute Tox. 4", "Skin Corr. 1A"
    percentual_notificadores: Optional[float]


@dataclass
class ResultadoEnriquecimento:
    cas: str
    cid: Optional[int]
    encontrado: bool
    classificacoes: list[ClassificacaoEncontrada] = field(default_factory=list)
    conflitos: list[str] = field(default_factory=list)
    erro: Optional[str] = None


class PubChemIndisponivel(Exception):
    """Levantada quando a API não responde — para o chamador decidir
    entre abortar, tentar mais tarde, ou seguir sem esse dado."""


def _get(url: str, timeout: int = 20) -> dict:
    resp = requests.get(url, timeout=timeout)
    if resp.status_code == 404:
        return {}
    resp.raise_for_status()
    return resp.json()


def _extrair_cid(resposta_cid: dict) -> Optional[int]:
    try:
        return resposta_cid["IdentifierList"]["CID"][0]
    except (KeyError, IndexError, TypeError):
        return None


def cas_para_cid(cas: str) -> Optional[int]:
    """Resolve um número CAS para o CID (Compound ID) da PubChem."""
    url = f"{PUG_REST_BASE}/compound/name/{cas}/cids/JSON"
    try:
        dados = _get(url)
    except requests.exceptions.RequestException as e:
        raise PubChemIndisponivel(f"Falha ao consultar PubChem para CAS {cas}: {e}") from e
    return _extrair_cid(dados)


# ---------------------------------------------------------------------------
# Extração da seção "GHS Classification" do PUG View
# ---------------------------------------------------------------------------
#
# Formato real documentado (uma StringWithMarkup por classificação):
#   "H315 (35.29%): Causes skin irritation
#    [Warning Skin Irrit. 2 - GHS Classification from ECHA C&L Notifications]"
#
# Reaproveitamos os MESMOS marcadores textuais ("Skin Corr./Irrit.",
# "Eye Dam./Irrit.", "Acute Tox.") que usamos no parser do Anexo VI —
# a nomenclatura de categoria é a mesma convenção CLP/GHS em ambas as
# fontes.

_PADRAO_LINHA_GHS = re.compile(
    r"(?P<h_code>H\d{3}\w{0,2})\s*\((?P<pct>[\d.]+)%\):.*?\[(?P<colchete>[^\]]+)\]",
    re.IGNORECASE,
)


def _extrair_secao_ghs(resposta_pug_view: dict) -> list[str]:
    """Percorre a árvore de seções do PUG View e devolve todas as strings
    de "GHS Classification" encontradas (uma por linha de classificação)."""
    linhas = []

    def _percorrer(no):
        if isinstance(no, dict):
            if no.get("TOCHeading") == "GHS Classification":
                for info in no.get("Information", []):
                    valor = info.get("Value", {})
                    for swm in valor.get("StringWithMarkup", []):
                        s = swm.get("String")
                        if s:
                            linhas.append(s)
            for v in no.values():
                _percorrer(v)
        elif isinstance(no, list):
            for item in no:
                _percorrer(item)

    _percorrer(resposta_pug_view)
    return linhas


def _parse_linhas_ghs(linhas: list[str]) -> list[ClassificacaoEncontrada]:
    resultados = []
    for linha in linhas:
        m = _PADRAO_LINHA_GHS.search(linha)
        if not m:
            continue
        h_code = m.group("h_code").upper()
        pct = float(m.group("pct"))
        colchete = m.group("colchete")

        categoria_texto = None
        for padrao in (r"acute\s+tox\.?\s*\d", r"skin\s+corr\.?\s*1[abc]?",
                       r"skin\s+irrit\.?\s*\d", r"eye\s+dam\.?\s*1",
                       r"eye\s+irrit\.?\s*2[ab]?"):
            m2 = re.search(padrao, colchete, re.IGNORECASE)
            if m2:
                categoria_texto = m2.group(0)
                break

        if categoria_texto:
            resultados.append(ClassificacaoEncontrada(
                h_code=h_code, categoria_texto=categoria_texto, percentual_notificadores=pct
            ))
    return resultados


def buscar_classificacao_ghs(cas: str) -> ResultadoEnriquecimento:
    """Busca a classificação GHS agregada da PubChem para um CAS.
    Não lança exceção em caso de substância não encontrada — só quando a
    própria API está inacessível (PubChemIndisponivel)."""
    try:
        cid = cas_para_cid(cas)
        if cid is None:
            return ResultadoEnriquecimento(cas=cas, cid=None, encontrado=False)

        time.sleep(INTERVALO_MINIMO_ENTRE_CHAMADAS)
        url = f"{PUG_VIEW_BASE}/data/compound/{cid}/JSON/?heading=GHS+Classification"
        dados = _get(url)
    except requests.exceptions.RequestException as e:
        raise PubChemIndisponivel(f"Falha ao consultar PubChem para CAS {cas}: {e}") from e

    if not dados:
        return ResultadoEnriquecimento(cas=cas, cid=cid, encontrado=False)

    linhas = _extrair_secao_ghs(dados)
    classificacoes = _parse_linhas_ghs(linhas)

    # Detecta conflito: mais de uma categoria distinta para o MESMO
    # "grupo" de perigo (ex.: duas categorias diferentes de Acute Tox.)
    conflitos = []
    por_grupo: dict[str, set] = {}
    for c in classificacoes:
        grupo = re.match(r"[a-z]+\.?\s*[a-z]*\.?", c.categoria_texto, re.IGNORECASE).group(0).split()[0].lower()
        por_grupo.setdefault(grupo, set()).add(c.categoria_texto)
    for grupo, categorias in por_grupo.items():
        if len(categorias) > 1:
            conflitos.append(
                f"Classificações divergentes reportadas para '{grupo}': {sorted(categorias)} — "
                f"usar a de maior percentual de notificadores e sinalizar para revisão."
            )

    return ResultadoEnriquecimento(
        cas=cas, cid=cid, encontrado=True,
        classificacoes=classificacoes, conflitos=conflitos,
    )


def categoria_mais_frequente(classificacoes: list[ClassificacaoEncontrada], prefixo_regex: str) -> Optional[str]:
    """Dentre as classificações de um determinado grupo (ex.: só as de
    'Acute Tox.'), devolve o texto da categoria com maior percentual de
    notificadores — usado para resolver o dado a gravar quando há
    divergência."""
    candidatas = [c for c in classificacoes if re.match(prefixo_regex, c.categoria_texto, re.IGNORECASE)]
    if not candidatas:
        return None
    candidatas.sort(key=lambda c: c.percentual_notificadores or 0, reverse=True)
    return candidatas[0].categoria_texto


# ---------------------------------------------------------------------------
# Teste de conectividade real (rodar no SEU computador, não neste sandbox)
# ---------------------------------------------------------------------------

def testar_conexao_real(cas_teste: str = "7732-18-5"):
    """Faz uma chamada real à PubChem (água, por padrão) e imprime o
    resultado bruto. Rode isto no seu ambiente antes de confiar no
    restante do módulo — este sandbox de desenvolvimento não conseguiu
    validar a chamada ao vivo (bloqueio de rede por política)."""
    resultado = buscar_classificacao_ghs(cas_teste)
    print(f"CAS {cas_teste} -> CID {resultado.cid}, encontrado={resultado.encontrado}")
    for c in resultado.classificacoes:
        print(f"  {c.h_code} ({c.percentual_notificadores}%): {c.categoria_texto}")
    for conflito in resultado.conflitos:
        print(f"  [CONFLITO] {conflito}")


# ---------------------------------------------------------------------------
# Teste offline com resposta mockada (schema real do PUG View),
# usado neste ambiente de desenvolvimento por falta de acesso à rede.
# ---------------------------------------------------------------------------

_MOCK_PUG_VIEW_RESPONSE = {
    "Record": {
        "RecordType": "CID",
        "RecordNumber": 3423265,
        "Section": [
            {
                "TOCHeading": "Safety and Hazards",
                "Section": [
                    {
                        "TOCHeading": "Hazards Identification",
                        "Section": [
                            {
                                "TOCHeading": "GHS Classification",
                                "Information": [
                                    {
                                        "Value": {
                                            "StringWithMarkup": [
                                                {"String": "H302 (60%): Harmful if swallowed "
                                                           "[Warning Acute Tox. 4 - GHS Classification "
                                                           "from ECHA C&L Notifications]"},
                                                {"String": "H302 (40%): Harmful if swallowed "
                                                           "[Warning Acute Tox. 3 - GHS Classification "
                                                           "from ECHA C&L Notifications]"},
                                                {"String": "H315 (100%): Causes skin irritation "
                                                           "[Warning Skin Irrit. 2 - GHS Classification "
                                                           "from ECHA C&L Notifications]"},
                                                {"String": "H319 (100%): Causes serious eye irritation "
                                                           "[Warning Eye Irrit. 2A - GHS Classification "
                                                           "from ECHA C&L Notifications]"},
                                            ]
                                        }
                                    }
                                ],
                            }
                        ],
                    }
                ],
            }
        ],
    }
}


def _teste_offline_com_mock():
    """Valida a lógica de extração/parsing sem depender de rede —
    usa uma resposta que reproduz fielmente o schema real do PUG View."""
    linhas = _extrair_secao_ghs(_MOCK_PUG_VIEW_RESPONSE)
    assert len(linhas) == 4, f"esperava 4 linhas, veio {len(linhas)}"

    classificacoes = _parse_linhas_ghs(linhas)
    assert len(classificacoes) == 4

    conflitos = []
    por_grupo: dict[str, set] = {}
    for c in classificacoes:
        grupo = re.match(r"[a-z]+\.?\s*[a-z]*\.?", c.categoria_texto, re.IGNORECASE).group(0).split()[0].lower()
        por_grupo.setdefault(grupo, set()).add(c.categoria_texto)
    for grupo, categorias in por_grupo.items():
        if len(categorias) > 1:
            conflitos.append(grupo)

    assert "acute" in conflitos, "deveria detectar conflito em Acute Tox. 3 vs 4"

    mais_frequente = categoria_mais_frequente(classificacoes, r"acute\s+tox")
    assert mais_frequente == "Acute Tox. 4", f"esperava 'Acute Tox. 4' (60%), veio {mais_frequente!r}"

    print("Teste offline (mock do schema real do PUG View): OK")
    print(f"  {len(classificacoes)} classificações extraídas, conflito detectado em: {conflitos}")
    print(f"  Categoria de toxicidade aguda mais frequente: {mais_frequente} (60% dos notificadores)")


if __name__ == "__main__":
    _teste_offline_com_mock()
