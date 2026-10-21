"""
Motor de classificação — Toxicidade Aguda
==========================================

Implementa a classificação de misturas por toxicidade aguda segundo a
ABNT NBR 14725:2023, Seção 5.3.1 (Tabela 16, Tabela 17 e equação de
aditividade de 5.3.1.7.1).

Fonte normativa: ABNT NBR 14725:2023, adquirida legitimamente pelo
usuário. Os valores numéricos abaixo (limiares de categoria e fatores
de conversão) são dados técnicos/tabulares da norma, reproduzidos aqui
apenas como constantes de cálculo — não como texto da norma.

Este módulo NÃO decide a classificação final de nenhuma classe de
perigo além de toxicidade aguda. É uma peça do motor de cálculo maior
(um módulo por classe de perigo).
"""

from dataclasses import dataclass
from enum import Enum
from typing import Optional


class ViaExposicao(str, Enum):
    ORAL = "oral"
    DERMICA = "dermica"
    INALATORIA_GASES = "inalatoria_gases"          # ppmV
    INALATORIA_VAPORES = "inalatoria_vapores"       # mg/L
    INALATORIA_POEIRAS_NEVOAS = "inalatoria_poeiras_nevoas"  # mg/L


# ---------------------------------------------------------------------------
# Tabela 16 — limites de categoria por via de exposição (NBR 14725:2023)
# Cada tupla é (limite_superior_categoria_1, ..., limite_superior_categoria_4)
# Categoria 5 vai até o teto indicado; acima disso, não classificado (NC).
# ---------------------------------------------------------------------------

_LIMITES_CATEGORIA = {
    ViaExposicao.ORAL:                      [5, 50, 300, 2000, 5000],
    ViaExposicao.DERMICA:                    [50, 200, 1000, 2000, 5000],
    ViaExposicao.INALATORIA_GASES:           [100, 500, 2500, 20000, None],  # cat.5 sem valor numérico p/ gases
    ViaExposicao.INALATORIA_VAPORES:         [0.5, 2.0, 10.0, 20.0, None],
    ViaExposicao.INALATORIA_POEIRAS_NEVOAS:  [0.05, 0.5, 1.0, 5.0, None],
}

# ---------------------------------------------------------------------------
# Tabela 17 — valores de conversão de categoria/faixa para ETA estimada,
# usados quando não há DL50/CL50 exato do ingrediente (só a categoria).
# ---------------------------------------------------------------------------

_CONVERSAO_ETA = {
    ViaExposicao.ORAL:                     [0.5, 5, 100, 500, 2500],
    ViaExposicao.DERMICA:                   [5, 50, 300, 1100, 2500],
    ViaExposicao.INALATORIA_GASES:          [10, 100, 700, 4500, None],
    ViaExposicao.INALATORIA_VAPORES:        [0.05, 0.5, 3, 11, None],
    ViaExposicao.INALATORIA_POEIRAS_NEVOAS: [0.005, 0.05, 0.5, 1.5, None],
}

# Concentração mínima acima da qual um ingrediente sem nenhum dado de
# toxicidade aguda invalida uma ETA definitiva para a mistura (5.3.1.7.2).
LIMITE_INGREDIENTE_DESCONHECIDO = 1.0  # % m/m ou v/v


@dataclass
class Ingrediente:
    nome: str
    cas: Optional[str]
    concentracao: float  # % no produto final (m/m ou v/v conforme via)
    eta: Optional[float] = None       # DL50/CL50 ou ETA já conhecida do ingrediente
    categoria: Optional[int] = None   # usada só se eta for None (via Tabela 17)
    sem_toxicidade_aguda: bool = False  # ex.: água, açúcar — ignorado no somatório


class ClassificacaoInvalida(Exception):
    """Levantada quando não é possível calcular uma ETA definitiva."""


def categoria_por_eta(eta: float, via: ViaExposicao) -> Optional[int]:
    """Classifica um valor de ETA numa categoria de 1 a 5, conforme a Tabela 16.
    Retorna None se o valor estiver acima do teto de Categoria 5 (não classificado)."""
    limites = _LIMITES_CATEGORIA[via]
    for categoria, limite in enumerate(limites, start=1):
        if limite is None:
            continue
        if eta <= limite:
            return categoria
    return None  # acima do maior limite definido -> não classificado (NC)


def eta_do_ingrediente(ing: Ingrediente, via: ViaExposicao) -> Optional[float]:
    """Resolve a ETA de um ingrediente individual:
    1) usa o DL50/CL50 (ou ETA) direto, se fornecido;
    2) senão, converte a partir da categoria conhecida, via Tabela 17;
    3) senão, retorna None (dado ausente)."""
    if ing.sem_toxicidade_aguda:
        return None  # ignorado no somatório por definição (5.3.1.7.1-b)
    if ing.eta is not None:
        return ing.eta
    if ing.categoria is not None:
        tabela = _CONVERSAO_ETA[via]
        idx = ing.categoria - 1
        if 0 <= idx < len(tabela) and tabela[idx] is not None:
            return tabela[idx]
    return None


def classificar_toxicidade_aguda(
    ingredientes: list[Ingrediente],
    via: ViaExposicao,
) -> dict:
    """
    Classifica a mistura para UMA via de exposição, aplicando a equação de
    aditividade de 5.3.1.7.1:

        100 / ETA_mistura = soma( Ci / ETAi )   para todo ingrediente i
                                                  com ETA conhecida

    Retorna um dicionário com o resultado e a rastreabilidade do cálculo,
    em vez de só a categoria — importante para auditoria posterior.
    """
    soma_ci_sobre_etai = 0.0
    concentracao_desconhecida = 0.0
    concentracao_considerada = 0.0
    detalhes = []

    for ing in ingredientes:
        eta_i = eta_do_ingrediente(ing, via)

        if ing.sem_toxicidade_aguda:
            detalhes.append({"nome": ing.nome, "status": "ignorado (sem toxicidade aguda conhecida)"})
            continue

        if eta_i is None:
            concentracao_desconhecida += ing.concentracao
            detalhes.append({"nome": ing.nome, "status": "ETA desconhecida"})
            continue

        soma_ci_sobre_etai += ing.concentracao / eta_i
        concentracao_considerada += ing.concentracao
        detalhes.append({
            "nome": ing.nome,
            "concentracao": ing.concentracao,
            "eta_usada": eta_i,
            "contribuicao": ing.concentracao / eta_i,
        })

    resultado = {
        "via": via.value,
        "detalhes": detalhes,
        "concentracao_com_eta_conhecida": round(concentracao_considerada, 4),
        "concentracao_eta_desconhecida": round(concentracao_desconhecida, 4),
    }

    # Regra 5.3.1.7.2: ingrediente sem qualquer dado, em concentração >= 1%,
    # impede ETA definitiva da mistura para essa via.
    if concentracao_desconhecida >= LIMITE_INGREDIENTE_DESCONHECIDO:
        resultado.update({
            "eta_mistura": None,
            "categoria": None,
            "eta_definitiva": False,
            "declaracao_obrigatoria": (
                f"{concentracao_desconhecida:.2f}% da mistura consiste em "
                f"ingrediente(s) com toxicidade aguda ({via.value}) desconhecida."
            ),
        })
        return resultado

    if soma_ci_sobre_etai <= 0:
        # Nenhum ingrediente com toxicidade aguda relevante
        resultado.update({
            "eta_mistura": None,
            "categoria": None,
            "eta_definitiva": True,
            "declaracao_obrigatoria": None,
        })
        return resultado

    eta_mistura = 100.0 / soma_ci_sobre_etai
    categoria = categoria_por_eta(eta_mistura, via)

    resultado.update({
        "eta_mistura": round(eta_mistura, 4),
        "categoria": categoria,
        "eta_definitiva": True,
        "declaracao_obrigatoria": None,
    })
    return resultado


def classificar_todas_as_vias(ingredientes_por_via: dict[ViaExposicao, list[Ingrediente]]) -> dict:
    """Conveniência: roda o cálculo para cada via de exposição informada e
    devolve a categoria mais severa junto com o detalhamento por via.
    A lista de ingredientes pode (e normalmente deve) ser diferente por via,
    já que nem todo ingrediente tem DL50 oral E dérmico E inalatório."""
    resultados = {}
    for via, ingredientes in ingredientes_por_via.items():
        resultados[via.value] = classificar_toxicidade_aguda(ingredientes, via)
    return resultados


# ---------------------------------------------------------------------------
# Exemplo de uso / caso de teste
# ---------------------------------------------------------------------------
if __name__ == "__main__":
    # Exemplo: formulação com 3 ingredientes, via oral.
    # Lauril éter sulfato de sódio: DL50 oral rato ~ 1288 mg/kg (dado hipotético de exemplo)
    # Cloreto de sódio: sem toxicidade aguda relevante -> ignorado
    # Um conservante com apenas a categoria conhecida (Categoria 4)
    ingredientes_oral = [
        Ingrediente(nome="Lauril éter sulfato de sódio", cas="68891-38-3",
                    concentracao=5.4, eta=1288),
        Ingrediente(nome="Cloreto de sódio", cas="7647-14-5",
                    concentracao=1.0, sem_toxicidade_aguda=True),
        Ingrediente(nome="Conservante X", cas="0000-00-0",
                    concentracao=0.3, categoria=4),
        Ingrediente(nome="Água", cas="7732-18-5",
                    concentracao=93.3, sem_toxicidade_aguda=True),
    ]

    resultado = classificar_toxicidade_aguda(ingredientes_oral, ViaExposicao.ORAL)
    import json
    print(json.dumps(resultado, indent=2, ensure_ascii=False))
