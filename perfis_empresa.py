"""
Perfis de empresa — armazenamento local (JSON) e CRUD
========================================================

Os dados da Seção 1 da FDS (razão social, CNPJ, endereço, telefones,
e-mail) variam por produto/cliente, mas o usuário não quer redigitá-los
toda vez — por isso ficam salvos como "perfis" reutilizáveis, num arquivo
JSON local (`perfis_empresa.json`), sem exigir banco de dados adicional.

Cada perfil tem um `id` estável (gerado uma vez, na criação) para que a
tela possa selecioná-lo num campo <select> e o backend possa recuperá-lo
sem depender do nome (que pode mudar).

Este módulo não sabe nada sobre FDS/classificação — é só armazenamento
de cadastro, reaproveitado tanto pela geração de PDF quanto por qualquer
outro uso futuro que precise dos dados da empresa.
"""

import json
import os
import uuid
from typing import Optional

_CAMINHO_PADRAO = os.path.join(os.path.dirname(os.path.abspath(__file__)), "perfis_empresa.json")

CAMPOS_PERFIL = ("razao_social", "cnpj", "endereco", "telefone", "email", "telefone_emergencia")


class RepositorioPerfisEmpresa:
    """Repositório simples de perfis de empresa, persistido em um único
    arquivo JSON. Não usa SQLite de propósito: são poucos registros
    (empresas/clientes do próprio usuário), sem necessidade de consultas
    complexas — um arquivo JSON de leitura/escrita completa é mais simples
    de inspecionar e editar manualmente, se necessário."""

    def __init__(self, caminho: Optional[str] = None):
        self.caminho = caminho or os.environ.get("FDS_PERFIS_PATH") or _CAMINHO_PADRAO
        if not os.path.exists(self.caminho):
            self._salvar_tudo({})

    def _carregar_tudo(self) -> dict:
        with open(self.caminho, encoding="utf-8") as f:
            return json.load(f)

    def _salvar_tudo(self, perfis: dict) -> None:
        tmp = self.caminho + ".tmp"
        with open(tmp, "w", encoding="utf-8") as f:
            json.dump(perfis, f, ensure_ascii=False, indent=2)
        os.replace(tmp, self.caminho)

    def listar(self) -> list:
        """Retorna a lista de perfis (id + campos), ordenada por razão
        social, para popular um <select> na tela."""
        perfis = self._carregar_tudo()
        lista = [{"id": pid, **dados} for pid, dados in perfis.items()]
        lista.sort(key=lambda p: (p.get("razao_social") or "").lower())
        return lista

    def obter(self, perfil_id: str) -> Optional[dict]:
        perfis = self._carregar_tudo()
        dados = perfis.get(perfil_id)
        if dados is None:
            return None
        return {"id": perfil_id, **dados}

    def salvar(self, dados: dict, perfil_id: Optional[str] = None) -> dict:
        """Cria um novo perfil (perfil_id=None) ou atualiza um existente.
        Só persiste os campos conhecidos (CAMPOS_PERFIL) — qualquer outra
        chave em `dados` é ignorada, para o arquivo nunca acumular lixo."""
        perfis = self._carregar_tudo()
        registro = {campo: (dados.get(campo) or "").strip() for campo in CAMPOS_PERFIL}

        if not registro["razao_social"]:
            raise ValueError("Razão social é obrigatória para salvar um perfil de empresa.")

        if perfil_id is None or perfil_id not in perfis:
            perfil_id = perfil_id or str(uuid.uuid4())
        perfis[perfil_id] = registro
        self._salvar_tudo(perfis)
        return {"id": perfil_id, **registro}

    def excluir(self, perfil_id: str) -> bool:
        perfis = self._carregar_tudo()
        if perfil_id not in perfis:
            return False
        del perfis[perfil_id]
        self._salvar_tudo(perfis)
        return True


# ---------------------------------------------------------------------------
# Teste funcional rápido
# ---------------------------------------------------------------------------
if __name__ == "__main__":
    import tempfile

    with tempfile.TemporaryDirectory() as tmpdir:
        caminho = os.path.join(tmpdir, "perfis_teste.json")
        repo = RepositorioPerfisEmpresa(caminho)

        assert repo.listar() == []

        p1 = repo.salvar({
            "razao_social": "Minha Empresa Química Ltda.",
            "cnpj": "00.000.000/0001-00",
            "endereco": "Rua Exemplo, 123",
            "telefone": "(11) 0000-0000",
            "email": "contato@minhaempresa.com.br",
            "telefone_emergencia": "0800-000-0000",
        })
        assert p1["id"]

        p2 = repo.salvar({"razao_social": "Outra Empresa S.A."})

        lista = repo.listar()
        assert len(lista) == 2, lista
        assert lista[0]["razao_social"] == "Minha Empresa Química Ltda."  # ordem alfabética

        obtido = repo.obter(p1["id"])
        assert obtido["cnpj"] == "00.000.000/0001-00"

        atualizado = repo.salvar({"razao_social": "Minha Empresa Química Ltda. (atualizada)", "cnpj": "11.111.111/0001-11"}, perfil_id=p1["id"])
        assert atualizado["id"] == p1["id"]
        assert repo.obter(p1["id"])["razao_social"].endswith("(atualizada)")
        assert len(repo.listar()) == 2  # não duplicou

        assert repo.excluir(p2["id"]) is True
        assert len(repo.listar()) == 1
        assert repo.excluir("id-inexistente") is False

        try:
            repo.salvar({"razao_social": ""})
            raise AssertionError("deveria ter recusado razão social vazia")
        except ValueError:
            pass

        print("OK — todos os testes de RepositorioPerfisEmpresa passaram.")
