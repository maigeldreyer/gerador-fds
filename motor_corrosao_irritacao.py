"""
Motor de classificação — Corrosão/Irritação à Pele e Lesões Oculares
======================================================================

Implementa a classificação de misturas por:
  - Corrosão/irritação à pele  (NBR 14725:2023, Seção 5.3.2 — Tabelas 20 e 21)
  - Lesões oculares graves/irritação ocular (Seção 5.3.3 — Tabelas 24 e 25)

Fonte normativa: ABNT NBR 14725:2023, adquirida legitimamente pelo
usuário. Os valores numéricos abaixo (limiares de concentração e
fatores de peso) são dados técnicos/tabulares da norma, reproduzidos
aqui apenas como constantes de cálculo — não como texto da norma.

Escopo e limitações assumidas de propósito (não escondidas):
  - A abordagem por aditividade (Tabelas 20 e 24) é o caminho
    principal implementado aqui.
  - A abordagem não-aditiva por pH (Tabelas 21 e 25) é implementada
    como verificação adicional/override para ácidos e bases fortes,
    e para ingredientes marcados explicitamente como não aptos à
    aditividade (5.3.2.3.3.4 / 5.3.3.3.3.4).
  - A exceção por "peso da evidência" (5.1.3.2), em que dados
    confiáveis mostram que o efeito de um ingrediente não é evidente
    acima do limite genérico, é um julgamento de especialista, não
    automatizável — NÃO está implementada aqui de propósito. Se for
    necessária, é uma decisão humana que sobrepõe o resultado deste
    motor, não um cálculo.
"""

from dataclasses import dataclass, field
from enum import Enum
from typing import Optional


# ---------------------------------------------------------------------------
# Categorias possíveis (como strings, para acomodar as subcategorias 1A/1B/1C
# da pele e 2A/2B dos olhos, que não são só números)
# ---------------------------------------------------------------------------

CATEGORIAS_PELE_CORROSIVAS = ("1A", "1B", "1C", "1")   # "1" = Categoria 1 sem subcategoria
CATEGORIAS_PELE_IRRITANTES = ("2", "3")
CATEGORIAS_OLHOS_GRAVES = ("1",)
CATEGORIAS_OLHOS_IRRITANTES = ("2A", "2B", "2")          # "2" = Categoria 2 sem subcategoria informada

LIMITE_RELEVANCIA_PADRAO = 1.0  # % — abaixo disso, ingrediente é ignorado, salvo override


@dataclass
class IngredientePeleOlhos:
    nome: str
    cas: Optional[str]
    concentracao: float  # % no produto final

    # Classificação de perigo à PELE do ingrediente, se houver:
    categoria_pele: Optional[str] = None   # um de CATEGORIAS_PELE_CORROSIVAS/IRRITANTES, ou None

    # Classificação de perigo aos OLHOS do ingrediente, se houver:
    categoria_olhos: Optional[str] = None  # um de CATEGORIAS_OLHOS_GRAVES/IRRITANTES, ou None

    # Dados para a abordagem não-aditiva (Tabelas 21/25):
    ph: Optional[float] = None
    acido_ou_base_forte: bool = False   # marca explícita de que o pH deve decidir (5.3.2.3.1.2)
    nao_apto_aditividade: bool = False  # ingrediente que a própria aditividade não capta corretamente
                                         # (sais inorgânicos, aldeídos, fenóis, surfactantes — 5.3.2.3.3.4)

    # Override para ingredientes conhecidos como relevantes mesmo abaixo de
    # 1% (ex.: corrosivos muito potentes) — 5.3.2.3.3.6 / 5.3.3.3.3.6.
    relevante_abaixo_1pct: bool = False

    sem_perigo_pele_olhos: bool = False  # presumidamente sem perigo relevante (ex.: água)


def _relevante(ing: IngredientePeleOlhos, limite: float = LIMITE_RELEVANCIA_PADRAO) -> bool:
    if ing.sem_perigo_pele_olhos:
        return False
    return ing.concentracao >= limite or ing.relevante_abaixo_1pct


# ---------------------------------------------------------------------------
# PELE — Corrosão/Irritação (Tabelas 20 e 21)
# ---------------------------------------------------------------------------

def _somar_por_categoria_pele(ingredientes: list[IngredientePeleOlhos]) -> dict:
    somas = {"1A": 0.0, "1B": 0.0, "1C": 0.0, "1": 0.0, "2": 0.0, "3": 0.0}
    tem_categoria_1_sem_subcategoria = False
    detalhes = []

    for ing in ingredientes:
        if not _relevante(ing) or ing.categoria_pele is None:
            continue
        cat = ing.categoria_pele
        if cat not in somas:
            continue
        somas[cat] += ing.concentracao
        if cat == "1":
            tem_categoria_1_sem_subcategoria = True
        detalhes.append({"nome": ing.nome, "categoria_pele": cat, "concentracao": ing.concentracao})

    return somas, tem_categoria_1_sem_subcategoria, detalhes


def _classificar_corrosao_pele_tabela21(ingredientes: list[IngredientePeleOlhos]) -> Optional[dict]:
    """Tabela 21 — abordagem não-aditiva, para ácidos/bases fortes e
    ingredientes marcados como não aptos à aditividade. Retorna None se
    nenhum ingrediente disparar essa via; senão, retorna o resultado mais
    severo encontrado por essa via (a ser comparado com o da Tabela 20)."""
    achados = []
    for ing in ingredientes:
        if not _relevante(ing, limite=1.0) and not ing.relevante_abaixo_1pct:
            continue

        if ing.acido_ou_base_forte and ing.ph is not None:
            if ing.ph <= 2 and ing.concentracao >= 1.0:
                achados.append(("1", ing, "ácido pH ≤ 2, ≥1%"))
            elif ing.ph >= 11.5 and ing.concentracao >= 1.0:
                achados.append(("1", ing, "base pH ≥ 11,5, ≥1%"))

        if ing.nao_apto_aditividade:
            if ing.categoria_pele in ("1A", "1B", "1C", "1") and ing.concentracao >= 1.0:
                # 5.3.2.3.3.4 (texto): "deve ser classificada como Categoria 1
                # de corrosão à pele" — SEM subcategoria, mesmo que o
                # ingrediente em si seja 1A/1B/1C. Corrigido: antes este
                # código propagava a subcategoria do ingrediente para a
                # mistura, o que não corresponde ao texto da norma para
                # esta via não-aditiva (diferente da Tabela 20, onde a
                # subcategorização É prevista explicitamente).
                achados.append(("1", ing, "corrosivo não apto à aditividade, ≥1%"))
            elif ing.categoria_pele in ("2", "3") and ing.concentracao >= 3.0:
                # a norma diz "Categoria 2 ou 3" sem regra de desempate explícita
                # nesta tabela; usamos a própria categoria do ingrediente.
                achados.append((ing.categoria_pele, ing, "irritante não apto à aditividade, ≥3%"))

    if not achados:
        return None

    ordem_severidade = ["1A", "1B", "1C", "1", "2", "3"]
    achados.sort(key=lambda a: ordem_severidade.index(a[0]))
    categoria_mais_severa = achados[0][0]
    return {
        "categoria": categoria_mais_severa,
        "via": "Tabela 21 (não-aditiva / pH)",
        "gatilhos": [{"nome": a[1].nome, "motivo": a[2]} for a in achados],
    }


def classificar_corrosao_irritacao_pele(ingredientes: list[IngredientePeleOlhos]) -> dict:
    """Classifica a mistura quanto à corrosão/irritação à pele, combinando
    a abordagem aditiva (Tabela 20, caminho principal) com a abordagem por
    pH/não-aditividade (Tabela 21, para os casos especiais que a própria
    norma alerta não funcionarem bem com aditividade pura)."""

    somas, tem_cat1_sem_sub, detalhes = _somar_por_categoria_pele(ingredientes)
    s1a, s1b, s1c, s1_sem_sub = somas["1A"], somas["1B"], somas["1C"], somas["1"]
    s2, s3 = somas["2"], somas["3"]

    soma_cat1_total = s1a + s1b + s1c + s1_sem_sub
    ponderado_1_2 = 10 * soma_cat1_total + s2
    ponderado_1_2_3 = ponderado_1_2 + s3

    resultado_tabela20 = None

    # --- Corrosão Categoria 1, com subcategorização (footnote a, Tabela 20) ---
    if s1a >= 5:
        resultado_tabela20 = {"categoria": "1A", "criterio": "soma Subcategoria 1A ≥ 5%"}
    elif s1a + s1b >= 5:
        resultado_tabela20 = {"categoria": "1B", "criterio": "soma 1A+1B ≥ 5%"}
    elif s1a + s1b + s1c >= 5:
        resultado_tabela20 = {"categoria": "1C", "criterio": "soma 1A+1B+1C ≥ 5%"}
    elif tem_cat1_sem_sub and soma_cat1_total >= 5:
        resultado_tabela20 = {"categoria": "1", "criterio": "soma de todos os Cat.1 (sem subcategoria) ≥ 5%"}

    # --- Se não for corrosiva, avalia irritação (Categoria 2, depois 3) ---
    if resultado_tabela20 is None:
        if s2 >= 10:
            resultado_tabela20 = {"categoria": "2", "criterio": "soma Categoria 2 ≥ 10%"}
        elif 1 <= soma_cat1_total < 5:
            resultado_tabela20 = {"categoria": "2", "criterio": "soma Categoria 1 entre 1% e <5%"}
        elif ponderado_1_2 >= 10:
            resultado_tabela20 = {"categoria": "2", "criterio": "10×Cat.1 + Cat.2 ≥ 10%"}

    if resultado_tabela20 is None:
        if s3 >= 10:
            resultado_tabela20 = {"categoria": "3", "criterio": "soma Categoria 3 ≥ 10%"}
        elif 1 <= s2 < 10:
            resultado_tabela20 = {"categoria": "3", "criterio": "soma Categoria 2 entre 1% e <10%"}
        elif 1 <= ponderado_1_2 < 10:
            resultado_tabela20 = {"categoria": "3", "criterio": "10×Cat.1 + Cat.2 entre 1% e <10%"}
        elif ponderado_1_2_3 >= 10:
            resultado_tabela20 = {"categoria": "3", "criterio": "10×Cat.1 + Cat.2 + Cat.3 ≥ 10%"}

    resultado_tabela21 = _classificar_corrosao_pele_tabela21(ingredientes)

    # Combina os dois caminhos: usa o mais severo entre os dois, quando ambos existem.
    ordem_severidade = ["1A", "1B", "1C", "1", "2", "3"]
    candidatos = []
    if resultado_tabela20:
        candidatos.append(("Tabela 20 (aditiva)", resultado_tabela20["categoria"], resultado_tabela20["criterio"]))
    if resultado_tabela21:
        candidatos.append(("Tabela 21 (pH / não-aditiva)", resultado_tabela21["categoria"],
                            "; ".join(g["motivo"] for g in resultado_tabela21["gatilhos"])))

    if not candidatos:
        categoria_final = None
        via_final = None
        criterio_final = None
    else:
        candidatos.sort(key=lambda c: ordem_severidade.index(c[1]))
        via_final, categoria_final, criterio_final = candidatos[0]

    return {
        "classe_perigo": "corrosao_irritacao_pele",
        "categoria": categoria_final,
        "via_decisao": via_final,
        "criterio": criterio_final,
        "somas_por_categoria": somas,
        "somatorio_ponderado_cat1_cat2": round(ponderado_1_2, 4),
        "somatorio_ponderado_cat1_cat2_cat3": round(ponderado_1_2_3, 4),
        "detalhes_tabela20": detalhes,
        "resultado_tabela21": resultado_tabela21,
    }


# ---------------------------------------------------------------------------
# OLHOS — Lesões oculares graves/irritação ocular (Tabelas 24 e 25)
# ---------------------------------------------------------------------------
#
# Particularidade importante (footnote a da Tabela 24): um ingrediente
# classificado como Categoria 1 PELE *e* Categoria 1 OLHOS entra apenas
# uma vez na soma "Categoria 1 pele + Categoria 1 ocular" — por isso a
# soma é feita por INGREDIENTE (evitando dupla contagem), não pela soma
# independente das duas colunas.

def _somar_para_olhos(ingredientes: list[IngredientePeleOlhos]) -> dict:
    soma_cat1_combinada = 0.0   # Categoria 1 pele OU Categoria 1 olhos (sem dupla contagem)
    soma_cat2 = 0.0
    todos_cat2_sao_2b = True
    tem_algum_cat2 = False
    detalhes = []

    for ing in ingredientes:
        if not _relevante(ing) or ing.sem_perigo_pele_olhos:
            continue

        eh_cat1_pele = ing.categoria_pele in ("1A", "1B", "1C", "1")
        eh_cat1_olhos = ing.categoria_olhos == "1"

        if eh_cat1_pele or eh_cat1_olhos:
            soma_cat1_combinada += ing.concentracao  # contado uma única vez, por ingrediente
            detalhes.append({"nome": ing.nome, "grupo": "Cat.1 pele e/ou olhos", "concentracao": ing.concentracao})
        elif ing.categoria_olhos in ("2", "2A", "2B"):
            soma_cat2 += ing.concentracao
            tem_algum_cat2 = True
            if ing.categoria_olhos != "2B":
                todos_cat2_sao_2b = False
            detalhes.append({"nome": ing.nome, "grupo": f"Olhos {ing.categoria_olhos}", "concentracao": ing.concentracao})

    return {
        "soma_cat1_combinada": soma_cat1_combinada,
        "soma_cat2": soma_cat2,
        "todos_cat2_sao_2b": todos_cat2_sao_2b and tem_algum_cat2,
        "detalhes": detalhes,
    }


def _classificar_olhos_tabela25(ingredientes: list[IngredientePeleOlhos]) -> Optional[dict]:
    achados = []
    for ing in ingredientes:
        if not _relevante(ing, limite=1.0) and not ing.relevante_abaixo_1pct:
            continue

        if ing.acido_ou_base_forte and ing.ph is not None:
            if ing.ph <= 2 and ing.concentracao >= 1.0:
                achados.append(("1", ing, "ácido pH ≤ 2, ≥1%"))
            elif ing.ph >= 11.5 and ing.concentracao >= 1.0:
                achados.append(("1", ing, "base pH ≥ 11,5, ≥1%"))

        if ing.nao_apto_aditividade:
            if ing.categoria_olhos == "1" and ing.concentracao >= 1.0:
                achados.append(("1", ing, "corrosivo ocular não apto à aditividade, ≥1%"))
            elif ing.categoria_olhos in ("2", "2A", "2B") and ing.concentracao >= 3.0:
                achados.append(("2", ing, "irritante ocular não apto à aditividade, ≥3%"))

    if not achados:
        return None

    ordem = ["1", "2"]
    achados.sort(key=lambda a: ordem.index(a[0]))
    categoria_mais_severa = achados[0][0]
    return {
        "categoria": categoria_mais_severa,
        "via": "Tabela 25 (não-aditiva / pH)",
        "gatilhos": [{"nome": a[1].nome, "motivo": a[2]} for a in achados],
    }


def classificar_lesao_ocular(ingredientes: list[IngredientePeleOlhos]) -> dict:
    """Classifica a mistura quanto a lesões oculares graves/irritação
    ocular, combinando a abordagem aditiva (Tabela 24) com a abordagem
    por pH/não-aditividade (Tabela 25)."""

    somas = _somar_para_olhos(ingredientes)
    s1 = somas["soma_cat1_combinada"]
    s2 = somas["soma_cat2"]
    ponderado = 10 * s1 + s2

    resultado_tabela24 = None

    if s1 >= 3:
        resultado_tabela24 = {"categoria": "1", "criterio": "soma (Cat.1 pele + Cat.1 olhos) ≥ 3%"}
    elif s1 >= 1:  # 1% <= s1 < 3%
        cat2_default = "2B" if somas["todos_cat2_sao_2b"] else "2A"
        resultado_tabela24 = {"categoria": cat2_default, "criterio": "soma (Cat.1 pele + Cat.1 olhos) entre 1% e <3%"}
    elif s2 >= 10:
        cat2_default = "2B" if somas["todos_cat2_sao_2b"] else "2A"
        resultado_tabela24 = {"categoria": cat2_default, "criterio": "soma Categoria 2 ocular ≥ 10%"}
    elif ponderado >= 10:
        cat2_default = "2B" if somas["todos_cat2_sao_2b"] else "2A"
        resultado_tabela24 = {"categoria": cat2_default, "criterio": "10×(Cat.1 pele+olhos) + Cat.2 ≥ 10%"}

    resultado_tabela25 = _classificar_olhos_tabela25(ingredientes)

    ordem_severidade = ["1", "2A", "2", "2B"]  # 2A tratado como mais severo que 2B para desempate conservador
    candidatos = []
    if resultado_tabela24:
        candidatos.append(("Tabela 24 (aditiva)", resultado_tabela24["categoria"], resultado_tabela24["criterio"]))
    if resultado_tabela25:
        candidatos.append(("Tabela 25 (pH / não-aditiva)", resultado_tabela25["categoria"],
                            "; ".join(g["motivo"] for g in resultado_tabela25["gatilhos"])))

    if not candidatos:
        categoria_final, via_final, criterio_final = None, None, None
    else:
        def chave_severidade(c):
            cat = c[1]
            return ordem_severidade.index(cat) if cat in ordem_severidade else len(ordem_severidade)
        candidatos.sort(key=chave_severidade)
        via_final, categoria_final, criterio_final = candidatos[0]

    return {
        "classe_perigo": "lesao_ocular",
        "categoria": categoria_final,
        "via_decisao": via_final,
        "criterio": criterio_final,
        "soma_cat1_combinada": round(s1, 4),
        "soma_cat2": round(s2, 4),
        "somatorio_ponderado": round(ponderado, 4),
        "detalhes_tabela24": somas["detalhes"],
        "resultado_tabela25": resultado_tabela25,
    }


# ---------------------------------------------------------------------------
# Exemplo de uso / caso de teste
# ---------------------------------------------------------------------------
if __name__ == "__main__":
    import json

    # Exemplo: mistura com um tensoativo levemente irritante (Categoria 2
    # pele e olhos) a 8%, e um conservante corrosivo à pele (Categoria 1B)
    # a 0,5% — abaixo do corte de 1% para relevância, então NÃO deve
    # contribuir para a classificação por padrão.
    ingredientes = [
        IngredientePeleOlhos(nome="Tensoativo X", cas="0001-01-1", concentracao=8.0,
                              categoria_pele="2", categoria_olhos="2A"),
        IngredientePeleOlhos(nome="Conservante corrosivo Y", cas="0002-02-2", concentracao=0.5,
                              categoria_pele="1B", categoria_olhos="1"),
        IngredientePeleOlhos(nome="Água", cas="7732-18-5", concentracao=91.5,
                              sem_perigo_pele_olhos=True),
    ]

    print("=== Pele ===")
    print(json.dumps(classificar_corrosao_irritacao_pele(ingredientes), indent=2, ensure_ascii=False))

    print("\n=== Olhos ===")
    print(json.dumps(classificar_lesao_ocular(ingredientes), indent=2, ensure_ascii=False))
