"""
Banco de substâncias — schema, importador do Anexo VI (ECHA) e ponte com
o motor de cálculo de classificação.

Este módulo é a "camada de dados" que discutimos: guarda, por substância
(CAS), a classificação harmonizada relevante, com rastreabilidade de
fonte. Por enquanto cobre apenas o que o motor de toxicidade aguda
consome; ao adicionar as próximas classes de perigo (irritação, CMR,
ambiental), a mesma tabela `substancias` é reaproveitada e novas tabelas
de classificação são adicionadas seguindo o padrão de `toxicidade_aguda`.
"""

import re
import sqlite3
from datetime import date
from pathlib import Path
from typing import Optional

import pandas as pd

from motor_toxicidade_aguda import Ingrediente, ViaExposicao
from motor_corrosao_irritacao import IngredientePeleOlhos
from pubchem_enriquecimento import buscar_classificacao_ghs, PubChemIndisponivel


# ---------------------------------------------------------------------------
# Schema
# ---------------------------------------------------------------------------

_SCHEMA = """
CREATE TABLE IF NOT EXISTS substancias (
    cas             TEXT PRIMARY KEY,
    ec_number       TEXT,
    nome            TEXT NOT NULL,
    fonte           TEXT NOT NULL,      -- 'ECHA_ANEXO_VI' | 'PUBCHEM' | 'MANUAL'
    fonte_versao    TEXT,               -- ex.: 'ATP 23' ou data do arquivo importado
    data_importacao TEXT NOT NULL
);

-- SEM chave única em (cas, via): o Anexo VI pode ter MAIS DE UMA linha
-- para o mesmo CAS (faixas de concentração da própria substância, ex.
-- ácido nítrico >70% vs ≤70%; ou variantes de forma física, ex. prata
-- maciça/pó/nano). Colapsar isso numa única linha por (cas, via) faz o
-- import mais recente sobrescrever silenciosamente o anterior de forma
-- arbitrária (dependendo da ordem das linhas no arquivo) — bug real
-- encontrado e corrigido nesta versão. Ver `faixa_concentracao_aplicavel`
-- e a lógica de resolução em `montar_ingredientes_por_via`.
CREATE TABLE IF NOT EXISTS toxicidade_aguda (
    id              INTEGER PRIMARY KEY AUTOINCREMENT,
    cas             TEXT NOT NULL,
    via             TEXT NOT NULL,      -- ver ViaExposicao (ou 'inalatoria_generica', só na importação)
    categoria       INTEGER,            -- 1-5, quando só a categoria é conhecida
    eta             REAL,               -- DL50/CL50 numérico, quando disponível
    estado_fisico   TEXT,               -- reservado para uso futuro
    faixa_min       REAL,               -- limite inferior de concentração da SUBSTÂNCIA (%) em que esta linha se aplica, se houver
    faixa_min_incl  INTEGER,            -- 1 = ">=", 0 = ">"
    faixa_max       REAL,               -- limite superior de concentração (%), se houver
    faixa_max_incl  INTEGER,            -- 1 = "<=", 0 = "<"
    nome_variante   TEXT,               -- nome exato da linha de origem (ex.: "nitric acid …% [C > 70 %]")
    fonte           TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_toxicidade_aguda_cas_via ON toxicidade_aguda (cas, via);

-- Lista curada de ingredientes presumidamente sem toxicidade aguda
-- relevante (água, açúcar, cloreto de sódio, etc. — conforme exemplo
-- dado na própria NBR 14725, 5.3.1.7.1-b). Isso é DIFERENTE de "sem
-- dado": aqui há uma afirmação positiva de ausência de perigo.
CREATE TABLE IF NOT EXISTS presumidos_sem_toxicidade_aguda (
    cas    TEXT PRIMARY KEY,
    nome   TEXT,
    fonte  TEXT NOT NULL
);

-- Classificação de corrosão/irritação à pele e lesão ocular por
-- substância. categoria_pele: '1A'|'1B'|'1C'|'1'|'2'|'3' (Annex VI/CLP
-- só popula 1A/1B/1C/1/2, mas o motor aceita '3' para uso com outras
-- fontes fiéis ao GHS puro). categoria_olhos: '1'|'2A'|'2B'|'2'.
-- Mesma observação da tabela de toxicidade aguda: sem PK único em cas,
-- por poder haver múltiplas linhas do Anexo VI por substância (faixas
-- de concentração ou variantes de forma física).
CREATE TABLE IF NOT EXISTS pele_olhos (
    id              INTEGER PRIMARY KEY AUTOINCREMENT,
    cas             TEXT NOT NULL,
    categoria_pele  TEXT,
    categoria_olhos TEXT,
    ph              REAL,
    faixa_min       REAL,
    faixa_min_incl  INTEGER,
    faixa_max       REAL,
    faixa_max_incl  INTEGER,
    nome_variante   TEXT,
    fonte           TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_pele_olhos_cas ON pele_olhos (cas);

-- Lista curada de ingredientes presumidamente sem perigo relevante à
-- pele/olhos (ex.: água) — mesma lógica de "afirmação positiva" da
-- tabela de toxicidade aguda.
CREATE TABLE IF NOT EXISTS presumidos_sem_perigo_pele_olhos (
    cas    TEXT PRIMARY KEY,
    nome   TEXT,
    fonte  TEXT NOT NULL
);
"""


# ---------------------------------------------------------------------------
# Faixas de concentração da própria substância (não da mistura) usadas em
# algumas entradas do Anexo VI para diferenciar a classificação conforme a
# pureza/concentração em que a substância se encontra — ex.: "nitric acid
# …% [C > 70 %]" vs "nitric acid …% [C ≤ 70 %]" (mesmo CAS, duas linhas).
# Confirmado contra o arquivo real do usuário: só a notação de faixa única
# ("C > X %", "C ≤ X %" etc.) aparece nele, mas o parser também cobre a
# notação de faixa dupla ("X % ≤ C < Y %"), documentada em outras versões
# do Anexo VI, por robustez.
# ---------------------------------------------------------------------------

_PADRAO_FAIXA_UNICA = re.compile(
    r"\bC\s*(?P<op>>=|<=|≥|≤|>|<)\s*(?P<val>[\d.,]+)\s*%", re.IGNORECASE
)
_PADRAO_FAIXA_DUPLA = re.compile(
    r"(?P<val1>[\d.,]+)\s*%\s*(?P<op1><=|≤|<)\s*C\s*(?P<op2><=|≤|<)\s*(?P<val2>[\d.,]+)\s*%",
    re.IGNORECASE,
)


def _num(texto: str) -> float:
    return float(texto.replace(",", "."))


def extrair_faixa_concentracao(nome_quimico: str):
    """Procura notação de faixa de concentração no nome/rótulo da linha do
    Anexo VI. Devolve (faixa_min, faixa_min_incl, faixa_max, faixa_max_incl);
    todos None se a linha não tiver faixa (aplica-se em qualquer concentração)."""
    if not isinstance(nome_quimico, str):
        return None, None, None, None

    m2 = _PADRAO_FAIXA_DUPLA.search(nome_quimico)
    if m2:
        return (_num(m2.group("val1")), m2.group("op1") in ("<=", "≤"),
                _num(m2.group("val2")), m2.group("op2") in ("<=", "≤"))

    m1 = _PADRAO_FAIXA_UNICA.search(nome_quimico)
    if m1:
        op, val = m1.group("op"), _num(m1.group("val"))
        if op in (">=", "≥"):
            return val, True, None, None
        if op == ">":
            return val, False, None, None
        if op in ("<=", "≤"):
            return None, None, val, True
        if op == "<":
            return None, None, val, False

    return None, None, None, None


def faixa_contem(concentracao: float, faixa_min, faixa_min_incl, faixa_max, faixa_max_incl) -> bool:
    """True se `concentracao` satisfaz a faixa (None em min/max = sem limite
    naquele lado — logo, uma linha sem faixa alguma sempre retorna True)."""
    if faixa_min is not None:
        ok = concentracao >= faixa_min if faixa_min_incl else concentracao > faixa_min
        if not ok:
            return False
    if faixa_max is not None:
        ok = concentracao <= faixa_max if faixa_max_incl else concentracao < faixa_max
        if not ok:
            return False
    return True


class BancoSubstancias:
    def __init__(self, caminho_db: str = "substancias.db"):
        self.caminho_db = caminho_db
        self.conn = sqlite3.connect(caminho_db)
        self.conn.execute("PRAGMA foreign_keys = ON;")
        self._migrar_schema_antigo_se_necessario()
        self.conn.executescript(_SCHEMA)
        self.conn.commit()

    def _migrar_schema_antigo_se_necessario(self):
        """Bancos criados antes da correção de faixas de concentração
        tinham PRIMARY KEY (cas, via)/(cas) em toxicidade_aguda/pele_olhos,
        o que colapsava silenciosamente múltiplas linhas do Anexo VI para
        o mesmo CAS. Se detectar o schema antigo, derruba essas duas
        tabelas (dados nelas já eram não-confiáveis, por definição do bug)
        para serem recriadas com o schema novo — exige reimportar o Anexo
        VI depois, o que é avisado no retorno do próprio importador."""
        for tabela in ("toxicidade_aguda", "pele_olhos"):
            cur = self.conn.execute(f"PRAGMA table_info({tabela})")
            colunas = {row[1] for row in cur.fetchall()}
            if colunas and "faixa_min" not in colunas:
                self.conn.execute(f"DROP TABLE {tabela}")
        self.conn.commit()

    def close(self):
        self.conn.close()

    # -----------------------------------------------------------------
    # Inserção manual (útil para testes e para substâncias sem entrada
    # no Anexo VI, preenchidas a partir de PubChem/GESTIS/ficha do
    # fornecedor)
    # -----------------------------------------------------------------

    def upsert_substancia(self, cas: str, nome: str, fonte: str,
                           ec_number: Optional[str] = None,
                           fonte_versao: Optional[str] = None):
        self.conn.execute(
            """INSERT INTO substancias (cas, ec_number, nome, fonte, fonte_versao, data_importacao)
               VALUES (?, ?, ?, ?, ?, ?)
               ON CONFLICT(cas) DO UPDATE SET
                    nome=excluded.nome, fonte=excluded.fonte,
                    fonte_versao=excluded.fonte_versao,
                    data_importacao=excluded.data_importacao""",
            (cas, ec_number, nome, fonte, fonte_versao, date.today().isoformat()),
        )
        self.conn.commit()

    def marcar_sem_toxicidade_aguda(self, cas: str, nome: str, fonte: str = "MANUAL"):
        """Registra que uma substância é presumidamente sem toxicidade aguda
        relevante (ex.: água, cloreto de sódio) — para não ser confundida
        com 'sem dado disponível'."""
        self.conn.execute(
            """INSERT INTO presumidos_sem_toxicidade_aguda (cas, nome, fonte)
               VALUES (?, ?, ?)
               ON CONFLICT(cas) DO UPDATE SET nome=excluded.nome, fonte=excluded.fonte""",
            (cas, nome, fonte),
        )
        self.conn.commit()

    def upsert_toxicidade_aguda(self, cas: str, via, categoria: Optional[int] = None,
                                 eta: Optional[float] = None,
                                 estado_fisico: Optional[str] = None,
                                 fonte: str = "MANUAL"):
        """Uso MANUAL/pontual (sem faixa de concentração): mantém no máximo
        uma linha por (cas, via) para essa origem, substituindo a anterior —
        é o comportamento correto quando você está cadastrando uma
        substância à mão, sem múltiplas variantes. O importador do Anexo VI
        usa `_inserir_toxicidade_aguda_variante` em vez disso, porque ali
        múltiplas linhas por (cas, via) são legítimas (faixas de
        concentração/formas físicas distintas)."""
        via_str = via.value if isinstance(via, ViaExposicao) else via  # aceita 'inalatoria_generica'
        self.conn.execute(
            "DELETE FROM toxicidade_aguda WHERE cas = ? AND via = ? AND faixa_min IS NULL AND faixa_max IS NULL",
            (cas, via_str),
        )
        self.conn.execute(
            """INSERT INTO toxicidade_aguda (cas, via, categoria, eta, estado_fisico, fonte)
               VALUES (?, ?, ?, ?, ?, ?)""",
            (cas, via_str, categoria, eta, estado_fisico, fonte),
        )
        self.conn.commit()

    def _inserir_toxicidade_aguda_variante(self, cas: str, via_str: str, categoria: Optional[int],
                                            faixa_min, faixa_min_incl, faixa_max, faixa_max_incl,
                                            nome_variante: str, fonte: str):
        """Usado pela importação do Anexo VI: sempre INSERE uma nova linha,
        nunca substitui — porque o mesmo (cas, via) pode legitimamente ter
        mais de uma linha de origem (faixas de concentração, formas
        físicas). A resolução de qual linha usar acontece depois, em
        `montar_ingredientes_por_via`, com base na concentração real do
        ingrediente na fórmula."""
        self.conn.execute(
            """INSERT INTO toxicidade_aguda
               (cas, via, categoria, faixa_min, faixa_min_incl, faixa_max, faixa_max_incl, nome_variante, fonte)
               VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)""",
            (cas, via_str, categoria, faixa_min,
             int(faixa_min_incl) if faixa_min_incl is not None else None,
             faixa_max, int(faixa_max_incl) if faixa_max_incl is not None else None,
             nome_variante, fonte),
        )

    def marcar_sem_perigo_pele_olhos(self, cas: str, nome: str, fonte: str = "MANUAL"):
        self.conn.execute(
            """INSERT INTO presumidos_sem_perigo_pele_olhos (cas, nome, fonte)
               VALUES (?, ?, ?)
               ON CONFLICT(cas) DO UPDATE SET nome=excluded.nome, fonte=excluded.fonte""",
            (cas, nome, fonte),
        )
        self.conn.commit()

    def upsert_pele_olhos(self, cas: str, categoria_pele: Optional[str] = None,
                           categoria_olhos: Optional[str] = None,
                           ph: Optional[float] = None, fonte: str = "MANUAL"):
        """Uso MANUAL/pontual — ver docstring de `upsert_toxicidade_aguda`
        para a mesma lógica aplicada aqui (substitui a linha manual
        anterior sem faixa; a importação do Anexo VI usa
        `_inserir_pele_olhos_variante`, que sempre insere)."""
        self.conn.execute(
            "DELETE FROM pele_olhos WHERE cas = ? AND faixa_min IS NULL AND faixa_max IS NULL",
            (cas,),
        )
        self.conn.execute(
            """INSERT INTO pele_olhos (cas, categoria_pele, categoria_olhos, ph, fonte)
               VALUES (?, ?, ?, ?, ?)""",
            (cas, categoria_pele, categoria_olhos, ph, fonte),
        )
        self.conn.commit()

    def _inserir_pele_olhos_variante(self, cas: str, categoria_pele: Optional[str],
                                      categoria_olhos: Optional[str],
                                      faixa_min, faixa_min_incl, faixa_max, faixa_max_incl,
                                      nome_variante: str, fonte: str):
        self.conn.execute(
            """INSERT INTO pele_olhos
               (cas, categoria_pele, categoria_olhos, faixa_min, faixa_min_incl, faixa_max, faixa_max_incl,
                nome_variante, fonte)
               VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)""",
            (cas, categoria_pele, categoria_olhos, faixa_min,
             int(faixa_min_incl) if faixa_min_incl is not None else None,
             faixa_max, int(faixa_max_incl) if faixa_max_incl is not None else None,
             nome_variante, fonte),
        )

    # -----------------------------------------------------------------
    # Importador da planilha do Anexo VI (ECHA)
    # -----------------------------------------------------------------
    #
    # Colunas esperadas (conforme layout oficial do Anexo VI / CLP Tabela 3.1):
    #   Index No | Chemical Name (ou "International Chemical Identification")
    #   EC No | CAS No
    #   Hazard Class and Category Code(s)          <- multi-linha, uma classe por linha
    #   Classification Hazard Statement Code(s)    <- multi-linha
    #   Specific Conc. Limits, M-factors (and ATEs) / "M, SCL, ATE"
    #   Notes
    #
    # ATENÇÃO: nomes de coluna variam um pouco entre versões/ATPs da
    # planilha da ECHA. Este importador tenta casar por substring
    # (case-insensitive); ajuste `MAPA_COLUNAS` se sua planilha usar
    # nomes diferentes. Além disso, a planilha "unofficial" da ECHA
    # normalmente tem uma linha de disclaimer antes do cabeçalho real —
    # por isso o parâmetro `header_row` (0-based) do método de import.

    MAPA_COLUNAS = {
        "cas": ["cas no", "cas number", "cas"],
        "ec": ["ec no", "ec number"],
        "nome": ["international chemical identification", "chemical name", "substance name"],
        "classificacao": ["hazard class and category code"],
        "h_codes": ["classification hazard statement code", "hazard statement code"],
        "scl": ["specific conc", "conc. limits", "m-factor", "m, scl, ate"],
    }

    _H_PARA_VIA = {
        "H300": ("oral", 1), "H301": ("oral", 3), "H302": ("oral", 4),
        "H310": ("dermica", 1), "H311": ("dermica", 3), "H312": ("dermica", 4),
        # Anexo VI não distingue gás/vapor/poeira-névoa para inalação — fica
        # como categoria genérica; a via real (vapor ou poeira/névoa) só é
        # decidida ao montar os ingredientes, a partir do estado físico do
        # PRODUTO final (não da matéria-prima).
        "H330": ("inalatoria_generica", 1), "H331": ("inalatoria_generica", 3), "H332": ("inalatoria_generica", 4),
    }

    def _achar_coluna(self, colunas, chaves) -> Optional[str]:
        colunas_lower = {c: str(c).lower() for c in colunas}
        for chave in chaves:
            for original, lower in colunas_lower.items():
                if chave in lower:
                    return original
        return None

    @staticmethod
    def _extrair_categoria_acute_tox(linha_classificacao: str) -> Optional[int]:
        m = re.search(r"acute\s+tox\.?\s*(\d)", linha_classificacao, re.IGNORECASE)
        return int(m.group(1)) if m else None

    def _parse_toxicidade_aguda(self, texto_classificacao: str, texto_h_codes: str):
        """Retorna (resultados, avisos), onde resultados é uma lista de
        (via, categoria) extraída de uma célula de classificação + sua
        célula de H-codes.

        Estratégia: filtrar SÓ as linhas 'Acute Tox. N' da classificação e
        SÓ os códigos H3xx (toxicidade aguda) dos H-codes, e parear esses
        dois subconjuntos posicionalmente. Isso é mais robusto que parear
        a linha inteira, porque classes de perigo físico (ex.: 'Press.
        Gas') às vezes aparecem na coluna de classificação sem H-code
        próprio, o que desalinharia uma contagem linha-a-linha ingênua —
        confirmado contra entradas reais do arquivo do usuário (ex.: CAS
        10294-34-5, tricloreto de boro)."""
        if not isinstance(texto_classificacao, str) or not isinstance(texto_h_codes, str):
            return [], []

        linhas_acute_tox = [
            l.strip() for l in texto_classificacao.splitlines()
            if re.search(r"acute\s+tox\.?\s*\d", l, re.IGNORECASE)
        ]
        # A regex já inclui o "H" no padrão, então findall devolve o
        # código completo (ex.: "H330") — NÃO reprefixar com "H" de novo
        # (bug anterior gerava "HH330", que nunca batia com _H_PARA_VIA).
        h_codes_acute_tox = re.findall(r"H3(?:00|01|02|10|11|12|30|31|32)", texto_h_codes)

        avisos = []
        resultados = []

        if len(linhas_acute_tox) != len(h_codes_acute_tox):
            if linhas_acute_tox or h_codes_acute_tox:
                avisos.append(
                    f"Contagem de 'Acute Tox.' ({len(linhas_acute_tox)}) não bate com a "
                    f"contagem de H-codes de toxicidade aguda ({len(h_codes_acute_tox)}) "
                    f"para classificação={texto_classificacao!r} / H={texto_h_codes!r}. "
                    f"Pulado — requer conferência manual."
                )
            return [], avisos

        for classe_linha, h_code in zip(linhas_acute_tox, h_codes_acute_tox):
            if h_code not in self._H_PARA_VIA:
                continue
            via_str, categoria_base = self._H_PARA_VIA[h_code]
            categoria = self._extrair_categoria_acute_tox(classe_linha) or categoria_base
            resultados.append((via_str, categoria))

        return resultados, avisos

    @staticmethod
    def _extrair_subcategoria_pele_corr(linha: str) -> str:
        """'Skin Corr. 1A' -> '1A'; 'Skin Corr. 1' -> '1'."""
        m = re.search(r"skin\s+corr\.?\s*(1[abc]?)", linha, re.IGNORECASE)
        return m.group(1).upper() if m else "1"

    @staticmethod
    def _extrair_categoria_pele_irrit(linha: str) -> str:
        """'Skin Irrit. 2' -> '2' (CLP só usa Categoria 2; a Categoria 3
        existe no GHS puro e é aceita pelo motor, mas o Anexo VI/CLP
        nunca a popula)."""
        m = re.search(r"skin\s+irrit\.?\s*(\d)", linha, re.IGNORECASE)
        return m.group(1) if m else "2"

    @staticmethod
    def _extrair_subcategoria_olhos_irrit(linha: str) -> str:
        """'Eye Irrit. 2' -> '2'; 'Eye Irrit. 2A'/'2B' -> '2A'/'2B'."""
        m = re.search(r"eye\s+irrit\.?\s*(2[ab]?)", linha, re.IGNORECASE)
        return m.group(1).upper() if m else "2"

    def _parse_pele_olhos(self, texto_classificacao: str, texto_h_codes: str):
        """Retorna (categoria_pele, categoria_olhos, avisos), extraídos da
        mesma célula de classificação e de H-codes usada para toxicidade
        aguda. Mesma estratégia de filtro-e-pareamento posicional: filtra
        só as linhas 'Skin Corr./Irrit.' e seus H-codes (H314/H315), e só
        as linhas 'Eye Dam./Irrit.' e seus H-codes (H318/H319) — cada
        classe de perigo tratada como um subconjunto pareado
        independente, para não ser afetada por outras classes (CMR,
        sensibilização, etc.) que aparecem na mesma célula."""
        if not isinstance(texto_classificacao, str) or not isinstance(texto_h_codes, str):
            return None, None, []

        avisos = []

        linhas_pele = [
            l.strip() for l in texto_classificacao.splitlines()
            if re.search(r"skin\s+(corr|irrit)\.?", l, re.IGNORECASE)
        ]
        h_pele = re.findall(r"H31[45]", texto_h_codes)

        categoria_pele = None
        if len(linhas_pele) == len(h_pele) and linhas_pele:
            # espera-se no máximo 1 entrada de pele por substância na prática,
            # mas trata múltiplas mantendo a mais severa (corrosivo > irritante)
            candidatos_pele = []
            for linha, h in zip(linhas_pele, h_pele):
                if h == "H314":
                    candidatos_pele.append(self._extrair_subcategoria_pele_corr(linha))
                elif h == "H315":
                    candidatos_pele.append(self._extrair_categoria_pele_irrit(linha))
            if candidatos_pele:
                ordem = ["1A", "1B", "1C", "1", "2", "3"]
                candidatos_pele.sort(key=lambda c: ordem.index(c) if c in ordem else len(ordem))
                categoria_pele = candidatos_pele[0]
        elif linhas_pele or h_pele:
            avisos.append(
                f"Contagem de linhas 'Skin Corr./Irrit.' ({len(linhas_pele)}) não bate com "
                f"H314/H315 ({len(h_pele)}) para classificação={texto_classificacao!r} / "
                f"H={texto_h_codes!r}. Pulado — requer conferência manual."
            )

        linhas_olhos = [
            l.strip() for l in texto_classificacao.splitlines()
            if re.search(r"eye\s+(dam|irrit)\.?", l, re.IGNORECASE)
        ]
        h_olhos = re.findall(r"H31[89]", texto_h_codes)

        categoria_olhos = None
        if len(linhas_olhos) == len(h_olhos) and linhas_olhos:
            candidatos_olhos = []
            for linha, h in zip(linhas_olhos, h_olhos):
                if h == "H318":
                    candidatos_olhos.append("1")
                elif h == "H319":
                    candidatos_olhos.append(self._extrair_subcategoria_olhos_irrit(linha))
            if candidatos_olhos:
                ordem = ["1", "2A", "2", "2B"]
                candidatos_olhos.sort(key=lambda c: ordem.index(c) if c in ordem else len(ordem))
                categoria_olhos = candidatos_olhos[0]
        elif linhas_olhos or h_olhos:
            avisos.append(
                f"Contagem de linhas 'Eye Dam./Irrit.' ({len(linhas_olhos)}) não bate com "
                f"H318/H319 ({len(h_olhos)}) para classificação={texto_classificacao!r} / "
                f"H={texto_h_codes!r}. Pulado — requer conferência manual."
            )

        return categoria_pele, categoria_olhos, avisos

    def importar_anexo_vi(self, caminho_excel: str, fonte_versao: Optional[str] = None,
                           sheet_name=0, header_row: int = 0) -> dict:
        """Importa a planilha do Anexo VI. `header_row` é o índice (0-based)
        da linha real de cabeçalhos — na planilha "unofficial" da ECHA, a
        primeira linha costuma ser um aviso/disclaimer, então o cabeçalho
        real fica algumas linhas abaixo (ex.: header_row=2 no arquivo
        ATP23 verificado). Devolve um resumo da importação (linhas lidas,
        substâncias novas/atualizadas, avisos) em vez de nada — para você
        poder auditar o que entrou no banco."""
        df = pd.read_excel(caminho_excel, sheet_name=sheet_name, header=header_row, dtype=str)
        colunas = list(df.columns)

        col_cas = self._achar_coluna(colunas, self.MAPA_COLUNAS["cas"])
        col_nome = self._achar_coluna(colunas, self.MAPA_COLUNAS["nome"])
        col_ec = self._achar_coluna(colunas, self.MAPA_COLUNAS["ec"])
        col_classe = self._achar_coluna(colunas, self.MAPA_COLUNAS["classificacao"])
        col_h = self._achar_coluna(colunas, self.MAPA_COLUNAS["h_codes"])

        faltantes = [n for n, c in
                     [("CAS", col_cas), ("Nome", col_nome), ("Classificação", col_classe), ("H-codes", col_h)]
                     if c is None]
        if faltantes:
            raise ValueError(
                f"Não consegui localizar as colunas: {', '.join(faltantes)}. "
                f"Colunas encontradas na planilha: {colunas}. "
                f"Ajuste BancoSubstancias.MAPA_COLUNAS conforme o layout real do seu arquivo."
            )

        versao = fonte_versao or f"importado em {date.today().isoformat()}"

        # Idempotência: apaga TODAS as linhas de origem ECHA_ANEXO_VI antes
        # de reimportar (qualquer versão anterior), para que rodar o import
        # de novo não acumule linhas duplicadas. Cadastros MANUAIS (outra
        # fonte) não são afetados.
        self.conn.execute("DELETE FROM toxicidade_aguda WHERE fonte LIKE 'ECHA_ANEXO_VI%'")
        self.conn.execute("DELETE FROM pele_olhos WHERE fonte LIKE 'ECHA_ANEXO_VI%'")
        self.conn.commit()

        resumo = {"linhas_lidas": len(df), "substancias_gravadas": 0,
                  "linhas_sem_cas": 0, "linhas_sem_toxicidade_aguda": 0,
                  "linhas_com_pele_ou_olhos": 0,
                  "cas_com_multiplas_linhas": 0,
                  "avisos_parser": []}

        for _, linha in df.iterrows():
            cas = str(linha[col_cas]).strip() if pd.notna(linha[col_cas]) else None
            if not cas or cas.lower() == "nan" or cas == "-":
                resumo["linhas_sem_cas"] += 1
                continue

            nome = str(linha[col_nome]).strip() if pd.notna(linha[col_nome]) else cas
            ec = str(linha[col_ec]).strip() if col_ec and pd.notna(linha[col_ec]) else None

            self.upsert_substancia(cas=cas, nome=nome, ec_number=ec,
                                    fonte="ECHA_ANEXO_VI", fonte_versao=versao)
            resumo["substancias_gravadas"] += 1

            faixa_min, faixa_min_incl, faixa_max, faixa_max_incl = extrair_faixa_concentracao(nome)

            pares, avisos_linha = self._parse_toxicidade_aguda(
                linha[col_classe] if pd.notna(linha[col_classe]) else "",
                linha[col_h] if pd.notna(linha[col_h]) else "",
            )
            if avisos_linha:
                resumo["avisos_parser"].extend(f"CAS {cas}: {a}" for a in avisos_linha)
            if not pares:
                resumo["linhas_sem_toxicidade_aguda"] += 1
            for via_str, categoria in pares:
                self._inserir_toxicidade_aguda_variante(
                    cas=cas, via_str=via_str, categoria=categoria,
                    faixa_min=faixa_min, faixa_min_incl=faixa_min_incl,
                    faixa_max=faixa_max, faixa_max_incl=faixa_max_incl,
                    nome_variante=nome, fonte=f"ECHA_ANEXO_VI ({versao})",
                )

            cat_pele, cat_olhos, avisos_pele_olhos = self._parse_pele_olhos(
                linha[col_classe] if pd.notna(linha[col_classe]) else "",
                linha[col_h] if pd.notna(linha[col_h]) else "",
            )
            if avisos_pele_olhos:
                resumo["avisos_parser"].extend(f"CAS {cas}: {a}" for a in avisos_pele_olhos)
            if cat_pele is not None or cat_olhos is not None:
                resumo["linhas_com_pele_ou_olhos"] += 1
                self._inserir_pele_olhos_variante(
                    cas=cas, categoria_pele=cat_pele, categoria_olhos=cat_olhos,
                    faixa_min=faixa_min, faixa_min_incl=faixa_min_incl,
                    faixa_max=faixa_max, faixa_max_incl=faixa_max_incl,
                    nome_variante=nome, fonte=f"ECHA_ANEXO_VI ({versao})",
                )

        self.conn.commit()

        cur = self.conn.execute("""
            SELECT COUNT(*) FROM (
                SELECT cas FROM toxicidade_aguda WHERE fonte LIKE 'ECHA_ANEXO_VI%'
                GROUP BY cas, via HAVING COUNT(*) > 1
            )
        """)
        resumo["cas_com_multiplas_linhas"] = cur.fetchone()[0]

        return resumo

    # -----------------------------------------------------------------
    # Ponte com o motor: monta os Ingrediente(...) por via, a partir da
    # fórmula informada pelo usuário na tela (CAS + concentração).
    # -----------------------------------------------------------------

    def montar_ingredientes_por_via(self, formula: list[dict], estado_fisico_produto: str) -> tuple[dict, list[str]]:
        """
        formula: lista de {"cas": str, "nome": str, "concentracao": float}
        estado_fisico_produto: "liquido" ou "solido_pulverulento" — define
            qual via inalatória (vapor ou poeira/névoa) é usada na conversão
            de categoria->ETA (Tabela 17). Sem isso, a via inalatória não
            pode ser calculada corretamente (produtos líquidos/sólidos usam
            vapor/poeira, nunca "gás" — a categoria "gases" da Tabela 16/17
            não se aplica a este portfólio, mesmo que o produto seja
            pungente/muito volátil).

        Retorna (ingredientes_por_via, avisos):
          - ingredientes_por_via: dict[ViaExposicao] -> list[Ingrediente],
            pronto para `classificar_todas_as_vias`.
          - avisos: mensagens sobre substâncias sem dado de toxicidade
            aguda no banco (nem categoria, nem ETA) — precisam ser
            preenchidas manualmente ou complementadas via PubChem antes
            do cálculo ser considerado confiável.
        """
        if estado_fisico_produto not in ("liquido", "solido_pulverulento"):
            raise ValueError('estado_fisico_produto deve ser "liquido" ou "solido_pulverulento"')

        via_inalatoria_relevante = (
            ViaExposicao.INALATORIA_VAPORES if estado_fisico_produto == "liquido"
            else ViaExposicao.INALATORIA_POEIRAS_NEVOAS
        )
        # A via "inalatoria_gases" nunca é usada para este portfólio — ver
        # observação do usuário: produtos são só líquidos ou sólidos
        # pulverulentos, nunca gases propriamente ditos, por mais pungentes
        # que sejam.
        vias_a_calcular = [ViaExposicao.ORAL, ViaExposicao.DERMICA, via_inalatoria_relevante]

        avisos = []
        ingredientes_por_via: dict[ViaExposicao, list[Ingrediente]] = {
            via: [] for via in vias_a_calcular
        }

        for item in formula:
            cas = item["cas"]
            nome = item.get("nome", cas)
            concentracao = item["concentracao"]

            presumido_seguro = self.conn.execute(
                "SELECT 1 FROM presumidos_sem_toxicidade_aguda WHERE cas = ?", (cas,)
            ).fetchone()
            if presumido_seguro:
                for via in vias_a_calcular:
                    ingredientes_por_via[via].append(
                        Ingrediente(nome=nome, cas=cas, concentracao=concentracao,
                                    sem_toxicidade_aguda=True)
                    )
                continue

            linhas = self.conn.execute(
                """SELECT via, categoria, eta, faixa_min, faixa_min_incl, faixa_max, faixa_max_incl, nome_variante
                   FROM toxicidade_aguda WHERE cas = ?""",
                (cas,),
            ).fetchall()

            if not linhas:
                avisos.append(
                    f"'{nome}' (CAS {cas}) não tem entrada de toxicidade aguda no banco "
                    f"(nem no Anexo VI, nem cadastro manual). Ele entrará no cálculo como "
                    f"ETA desconhecida em todas as vias — se a concentração for ≥ 1%, "
                    f"nenhuma via terá ETA definitiva até você complementar o dado."
                )
                for via in vias_a_calcular:
                    ingredientes_por_via[via].append(
                        Ingrediente(nome=nome, cas=cas, concentracao=concentracao)
                    )
                continue

            # Agrupa por via (já remapeando 'inalatoria_generica' para a via
            # real do produto), porque uma mesma substância pode ter mais de
            # uma linha na MESMA via — faixas de concentração da própria
            # substância (ex.: ácido nítrico >70% vs ≤70%) ou variantes de
            # forma física (ex.: prata maciça/pó/nano) que o Anexo VI lista
            # como entradas separadas sob o mesmo CAS.
            linhas_por_via: dict[ViaExposicao, list] = {}
            for via_str, categoria, eta, faixa_min, faixa_min_incl, faixa_max, faixa_max_incl, nome_variante in linhas:
                via = via_inalatoria_relevante if via_str == "inalatoria_generica" else ViaExposicao(via_str)
                if via not in vias_a_calcular:
                    continue
                linhas_por_via.setdefault(via, []).append(
                    (categoria, eta, faixa_min, bool(faixa_min_incl) if faixa_min_incl is not None else None,
                     faixa_max, bool(faixa_max_incl) if faixa_max_incl is not None else None, nome_variante)
                )

            vias_presentes = set()
            for via, candidatas in linhas_por_via.items():
                if len(candidatas) == 1:
                    categoria, eta, *_ = candidatas[0]
                else:
                    aplicaveis = [c for c in candidatas
                                  if faixa_contem(concentracao, c[2], c[3], c[4], c[5])]
                    if len(aplicaveis) == 1:
                        categoria, eta, *_ = aplicaveis[0]
                    else:
                        # Ambíguo: nenhuma faixa bateu com exatidão, ou mais
                        # de uma bateu (faixas sobrepostas / entradas sem
                        # faixa parseável, como variantes de forma física).
                        # Escolha segura: usa a classificação MAIS SEVERA
                        # entre todas as candidatas (nunca a "mais branda" por
                        # omissão) e avisa explicitamente para revisão humana
                        # — evita repetir o bug anterior de sobrescrita
                        # silenciosa por ordem de importação.
                        candidatas_com_categoria = [c for c in candidatas if c[0] is not None]
                        escolhida = min(candidatas_com_categoria, key=lambda c: c[0]) \
                            if candidatas_com_categoria else candidatas[0]
                        categoria, eta = escolhida[0], escolhida[1]
                        variantes = "; ".join(
                            f"{c[6] or '(sem nome de variante)'} → Categoria {c[0]}" for c in candidatas
                        )
                        avisos.append(
                            f"'{nome}' (CAS {cas}) tem {len(candidatas)} entradas diferentes no Anexo VI "
                            f"para toxicidade aguda ({via.value}), e a concentração informada "
                            f"({concentracao}%) não identificou uma única faixa aplicável com "
                            f"segurança: {variantes}. Usada a mais severa (Categoria {categoria}) "
                            f"por precaução — confirme manualmente qual variante corresponde à "
                            f"matéria-prima real antes de finalizar a FDS."
                        )

                vias_presentes.add(via)
                ingredientes_por_via[via].append(
                    Ingrediente(nome=nome, cas=cas, concentracao=concentracao,
                                eta=eta, categoria=categoria)
                )

            # Para vias sem entrada no banco (ex.: substância só tem
            # classificação oral, não dérmica), o ingrediente entra como
            # ETA desconhecida nessa via específica, não como "sem
            # toxicidade aguda" — são coisas diferentes: a segunda
            # afirma positivamente que não há perigo (água, sal); a
            # primeira só significa "não temos o dado".
            for via in vias_a_calcular:
                if via not in vias_presentes:
                    ingredientes_por_via[via].append(
                        Ingrediente(nome=nome, cas=cas, concentracao=concentracao)
                    )

        return ingredientes_por_via, avisos

    def montar_ingredientes_pele_olhos(self, formula: list[dict]) -> tuple[list[IngredientePeleOlhos], list[str]]:
        """
        formula: lista de {"cas": str, "nome": str, "concentracao": float}

        Retorna (ingredientes, avisos), prontos para
        `classificar_corrosao_irritacao_pele` e `classificar_lesao_ocular`
        do motor_corrosao_irritacao. Ao contrário da toxicidade aguda, pele
        e olhos usam a MESMA lista de ingredientes para as duas classes de
        perigo (cada IngredientePeleOlhos carrega categoria_pele E
        categoria_olhos simultaneamente).
        """
        # Ordem de severidade (menor = mais severo) usada apenas para o
        # desempate "mais severo + aviso" quando o Anexo VI traz mais de
        # uma linha para o mesmo CAS (faixa de concentração da própria
        # substância ou variante de forma física) e a concentração da
        # fórmula não permite identificar com segurança qual linha se
        # aplica — mesmo critério já usado em montar_ingredientes_por_via.
        ordem_pele = {"1A": 0, "1B": 1, "1C": 2, "1": 3, "2": 4, "3": 5}
        ordem_olhos = {"1": 0, "2A": 1, "2B": 2, "2": 3}

        avisos = []
        ingredientes = []

        for item in formula:
            cas = item["cas"]
            nome = item.get("nome", cas)
            concentracao = item["concentracao"]

            presumido_seguro = self.conn.execute(
                "SELECT 1 FROM presumidos_sem_perigo_pele_olhos WHERE cas = ?", (cas,)
            ).fetchone()
            if presumido_seguro:
                ingredientes.append(IngredientePeleOlhos(
                    nome=nome, cas=cas, concentracao=concentracao, sem_perigo_pele_olhos=True
                ))
                continue

            candidatas = self.conn.execute(
                """SELECT categoria_pele, categoria_olhos, ph,
                          faixa_min, faixa_min_incl, faixa_max, faixa_max_incl, nome_variante
                   FROM pele_olhos WHERE cas = ?""",
                (cas,),
            ).fetchall()
            candidatas = [
                (cp, co, ph, fmin, bool(fmin_i) if fmin_i is not None else None,
                 fmax, bool(fmax_i) if fmax_i is not None else None, variante)
                for (cp, co, ph, fmin, fmin_i, fmax, fmax_i, variante) in candidatas
                if not (cp is None and co is None)
            ]

            if not candidatas:
                avisos.append(
                    f"'{nome}' (CAS {cas}) não tem classificação de pele/olhos no banco "
                    f"(nem no Anexo VI, nem cadastro manual). Ele NÃO contribuirá para o "
                    f"cálculo de corrosão/irritação — se for um componente relevante "
                    f"(ex.: ≥1%), complemente o dado antes de considerar o resultado final."
                )
                ingredientes.append(IngredientePeleOlhos(nome=nome, cas=cas, concentracao=concentracao))
                continue

            if len(candidatas) == 1:
                categoria_pele, categoria_olhos, ph, *_ = candidatas[0]
            else:
                aplicaveis = [c for c in candidatas
                              if faixa_contem(concentracao, c[3], c[4], c[5], c[6])]
                if len(aplicaveis) == 1:
                    categoria_pele, categoria_olhos, ph, *_ = aplicaveis[0]
                else:
                    # Ambíguo (nenhuma faixa bateu, ou mais de uma bateu —
                    # faixas sobrepostas ou variantes de forma física sem
                    # faixa parseável). Escolha segura: nunca sobrescrever
                    # silenciosamente por ordem de importação — usa a
                    # combinação mais severa (pele e olhos avaliados
                    # separadamente, já que uma variante pode ser pior em
                    # pele e outra pior em olhos) e avisa para revisão
                    # humana antes de finalizar a FDS.
                    com_pele = [c for c in candidatas if c[0] is not None and c[0] in ordem_pele]
                    com_olhos = [c for c in candidatas if c[1] is not None and c[1] in ordem_olhos]
                    escolhida_pele = min(com_pele, key=lambda c: ordem_pele[c[0]]) if com_pele else None
                    escolhida_olhos = min(com_olhos, key=lambda c: ordem_olhos[c[1]]) if com_olhos else None

                    categoria_pele = escolhida_pele[0] if escolhida_pele else None
                    categoria_olhos = escolhida_olhos[1] if escolhida_olhos else None
                    # pH: usa o da linha escolhida para pele (mais relevante
                    # para a via não-aditiva de corrosão), com fallback para
                    # a linha escolhida para olhos.
                    ph = (escolhida_pele[2] if escolhida_pele else None)
                    if ph is None and escolhida_olhos is not None:
                        ph = escolhida_olhos[2]

                    variantes = "; ".join(
                        f"{c[7] or '(sem nome de variante)'} → pele {c[0] or '—'} / olhos {c[1] or '—'}"
                        for c in candidatas
                    )
                    avisos.append(
                        f"'{nome}' (CAS {cas}) tem {len(candidatas)} entradas diferentes no Anexo VI "
                        f"para pele/olhos, e a concentração informada ({concentracao}%) não "
                        f"identificou uma única faixa aplicável com segurança: {variantes}. "
                        f"Usada a combinação mais severa (pele {categoria_pele or '—'} / "
                        f"olhos {categoria_olhos or '—'}) por precaução — confirme manualmente "
                        f"qual variante corresponde à matéria-prima real antes de finalizar a FDS."
                    )

            ingredientes.append(IngredientePeleOlhos(
                nome=nome, cas=cas, concentracao=concentracao,
                categoria_pele=categoria_pele, categoria_olhos=categoria_olhos, ph=ph,
            ))

        return ingredientes, avisos

    # -----------------------------------------------------------------
    # Enriquecimento via PubChem — só preenche LACUNAS, nunca sobrescreve
    # dados já vindos do Anexo VI (ver pubchem_enriquecimento.py para o
    # aviso de validação: a chamada HTTP real não pôde ser testada ao
    # vivo no ambiente onde este projeto foi construído).
    # -----------------------------------------------------------------

    _H_ACUTE_PARA_VIA = {
        "H300": "oral", "H301": "oral", "H302": "oral",
        "H310": "dermica", "H311": "dermica", "H312": "dermica",
        "H330": "inalatoria_generica", "H331": "inalatoria_generica", "H332": "inalatoria_generica",
    }

    def enriquecer_faltantes_com_pubchem(self, cas_lista: list[str]) -> dict:
        """Para cada CAS da lista, consulta a PubChem SOMENTE se a
        substância não tiver nenhuma entrada de toxicidade aguda ou de
        pele/olhos vinda do Anexo VI. Grava o resultado com fonte
        identificada como PubChem (incluindo o percentual de
        notificadores), e nunca sobrescreve uma entrada já existente do
        Anexo VI. Retorna um resumo com o que foi enriquecido, o que
        continuou sem dado, e os conflitos encontrados — para revisão
        humana antes de confiar no resultado."""
        resumo = {
            "consultadas": 0, "enriquecidas_toxicidade_aguda": 0,
            "enriquecidas_pele_olhos": 0, "sem_dado_na_pubchem": [],
            "conflitos": [], "erros_api": [],
        }

        for cas in cas_lista:
            ja_tem_toxicidade = self.conn.execute(
                "SELECT 1 FROM toxicidade_aguda WHERE cas = ? AND fonte LIKE 'ECHA_ANEXO_VI%'", (cas,)
            ).fetchone()
            ja_tem_pele_olhos = self.conn.execute(
                "SELECT 1 FROM pele_olhos WHERE cas = ? AND fonte LIKE 'ECHA_ANEXO_VI%'", (cas,)
            ).fetchone()

            if ja_tem_toxicidade and ja_tem_pele_olhos:
                continue  # já coberto pelo Anexo VI, não precisa da PubChem

            resumo["consultadas"] += 1
            try:
                resultado = buscar_classificacao_ghs(cas)
            except PubChemIndisponivel as e:
                resumo["erros_api"].append(f"CAS {cas}: {e}")
                continue

            if not resultado.encontrado or not resultado.classificacoes:
                resumo["sem_dado_na_pubchem"].append(cas)
                continue

            if resultado.conflitos:
                resumo["conflitos"].extend(f"CAS {cas}: {c}" for c in resultado.conflitos)

            if not ja_tem_toxicidade:
                for h_code, via_str in self._H_ACUTE_PARA_VIA.items():
                    candidatas = [c for c in resultado.classificacoes if c.h_code.upper() == h_code]
                    if not candidatas:
                        continue
                    candidatas.sort(key=lambda c: c.percentual_notificadores or 0, reverse=True)
                    melhor = candidatas[0]
                    categoria = self._extrair_categoria_acute_tox(melhor.categoria_texto)
                    if categoria is None:
                        continue
                    self.upsert_toxicidade_aguda(
                        cas=cas, via=via_str, categoria=categoria,
                        fonte=f"PUBCHEM ({melhor.percentual_notificadores:.0f}% dos notificadores)",
                    )
                    resumo["enriquecidas_toxicidade_aguda"] += 1

            if not ja_tem_pele_olhos:
                cat_pele = None
                cat_olhos = None
                candidatas_pele = [c for c in resultado.classificacoes
                                    if re.match(r"skin\s+(corr|irrit)", c.categoria_texto, re.IGNORECASE)]
                if candidatas_pele:
                    candidatas_pele.sort(key=lambda c: c.percentual_notificadores or 0, reverse=True)
                    melhor = candidatas_pele[0]
                    cat_pele = (self._extrair_subcategoria_pele_corr(melhor.categoria_texto)
                                if melhor.h_code.upper() == "H314"
                                else self._extrair_categoria_pele_irrit(melhor.categoria_texto))

                candidatas_olhos = [c for c in resultado.classificacoes
                                     if re.match(r"eye\s+(dam|irrit)", c.categoria_texto, re.IGNORECASE)]
                if candidatas_olhos:
                    candidatas_olhos.sort(key=lambda c: c.percentual_notificadores or 0, reverse=True)
                    melhor = candidatas_olhos[0]
                    cat_olhos = ("1" if melhor.h_code.upper() == "H318"
                                 else self._extrair_subcategoria_olhos_irrit(melhor.categoria_texto))

                if cat_pele or cat_olhos:
                    pct_ref = (candidatas_pele or candidatas_olhos)[0].percentual_notificadores or 0
                    self.upsert_pele_olhos(
                        cas=cas, categoria_pele=cat_pele, categoria_olhos=cat_olhos,
                        fonte=f"PUBCHEM ({pct_ref:.0f}% dos notificadores)",
                    )
                    resumo["enriquecidas_pele_olhos"] += 1

        return resumo


if __name__ == "__main__":
    # Demonstração com dados inseridos manualmente (sem depender ainda do
    # arquivo real do Anexo VI) — mostra a ponte funcionando de ponta a
    # ponta: banco -> Ingrediente -> motor de cálculo.
    from motor_toxicidade_aguda import classificar_todas_as_vias
    import json

    banco = BancoSubstancias(":memory:")

    # Simula o que viria do Anexo VI real para 2 substâncias:
    banco.upsert_substancia("68891-38-3", "Lauril éter sulfato de sódio", fonte="MANUAL")
    banco.upsert_toxicidade_aguda("68891-38-3", ViaExposicao.ORAL, categoria=4, fonte="MANUAL")

    banco.upsert_substancia("7647-14-5", "Cloreto de sódio", fonte="MANUAL")
    banco.marcar_sem_toxicidade_aguda("7647-14-5", "Cloreto de sódio", fonte="NBR 14725:2023, 5.3.1.7.1-b (exemplo)")

    banco.upsert_substancia("7732-18-5", "Água", fonte="MANUAL")
    banco.marcar_sem_toxicidade_aguda("7732-18-5", "Água", fonte="NBR 14725:2023, 5.3.1.7.1-b (exemplo)")

    # Substância propositalmente SEM cadastro nenhum, para mostrar o aviso:
    formula = [
        {"cas": "68891-38-3", "nome": "Lauril éter sulfato de sódio", "concentracao": 5.4},
        {"cas": "7647-14-5", "nome": "Cloreto de sódio", "concentracao": 1.0},
        {"cas": "7732-18-5", "nome": "Água", "concentracao": 92.6},
        {"cas": "0000-00-0", "nome": "Fragrância X (sem cadastro)", "concentracao": 1.0},
    ]

    ingredientes_por_via, avisos = banco.montar_ingredientes_por_via(formula, estado_fisico_produto="liquido")

    print("=== Avisos ===")
    for a in avisos:
        print("-", a)

    print("\n=== Classificação (via oral) ===")
    resultado_oral = classificar_todas_as_vias({ViaExposicao.ORAL: ingredientes_por_via[ViaExposicao.ORAL]})
    print(json.dumps(resultado_oral, indent=2, ensure_ascii=False))
