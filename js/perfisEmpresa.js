/**
 * Perfis de empresa — armazenamento local e CRUD
 * ==================================================
 *
 * Porte 1:1 de perfis_empresa.py / PerfisEmpresa.php: JSON em disco ->
 * `localStorage` do navegador. Os dados da Seção 1 da FDS (razão social,
 * CNPJ, endereço, telefones, e-mail) variam por produto/cliente, mas o
 * usuário não quer redigitá-los toda vez — por isso ficam salvos como
 * "perfis" reutilizáveis, agora no localStorage (por origem/domínio,
 * nunca enviados a lugar nenhum).
 *
 * Cada perfil tem um `id` estável (gerado uma vez, na criação, via
 * `crypto.randomUUID()`) para que a tela possa selecioná-lo num <select>
 * sem depender do nome (que pode mudar).
 *
 * Este módulo não sabe nada sobre FDS/classificação — é só armazenamento
 * de cadastro, reaproveitado tanto pela geração de PDF quanto por
 * qualquer outro uso futuro que precise dos dados da empresa.
 */

const CHAVE_PADRAO = "gerador_fds_perfis_empresa";

export const CAMPOS_PERFIL = ["razao_social", "cnpj", "endereco", "telefone", "email", "telefone_emergencia"];

function _uuid() {
  if (typeof crypto !== "undefined" && typeof crypto.randomUUID === "function") {
    return crypto.randomUUID();
  }
  // Fallback (navegadores muito antigos / contexto não seguro): UUID v4 simples.
  return "xxxxxxxx-xxxx-4xxx-yxxx-xxxxxxxxxxxx".replace(/[xy]/g, (c) => {
    const r = (Math.random() * 16) | 0;
    const v = c === "x" ? r : (r & 0x3) | 0x8;
    return v.toString(16);
  });
}

/**
 * Repositório simples de perfis de empresa, persistido no `localStorage`.
 * Não usa IndexedDB de propósito: são poucos registros (empresas/clientes
 * do próprio usuário), sem necessidade de consultas complexas — leitura/
 * escrita completa de um objeto JSON é mais simples e síncrona.
 */
export class RepositorioPerfisEmpresa {
  constructor(chave = CHAVE_PADRAO) {
    this.chave = chave;
    if (localStorage.getItem(this.chave) === null) {
      this._salvarTudo({});
    }
  }

  _carregarTudo() {
    const bruto = localStorage.getItem(this.chave);
    if (bruto === null) return {};
    try {
      return JSON.parse(bruto);
    } catch {
      return {};
    }
  }

  _salvarTudo(perfis) {
    localStorage.setItem(this.chave, JSON.stringify(perfis));
  }

  /** Retorna a lista de perfis (id + campos), ordenada por razão social, para popular um <select> na tela. */
  listar() {
    const perfis = this._carregarTudo();
    const lista = Object.entries(perfis).map(([id, dados]) => ({ id, ...dados }));
    lista.sort((a, b) => (a.razao_social || "").toLowerCase().localeCompare((b.razao_social || "").toLowerCase()));
    return lista;
  }

  obter(perfilId) {
    const perfis = this._carregarTudo();
    const dados = perfis[perfilId];
    if (dados === undefined) return null;
    return { id: perfilId, ...dados };
  }

  /**
   * Cria um novo perfil (perfilId omitido/null) ou atualiza um existente.
   * Só persiste os campos conhecidos (CAMPOS_PERFIL) — qualquer outra
   * chave em `dados` é ignorada, para o armazenamento nunca acumular lixo.
   */
  salvar(dados, perfilId = null) {
    const perfis = this._carregarTudo();
    const registro = {};
    for (const campo of CAMPOS_PERFIL) {
      registro[campo] = (dados[campo] || "").toString().trim();
    }

    if (!registro.razao_social) {
      throw new Error("Razão social é obrigatória para salvar um perfil de empresa.");
    }

    let id = perfilId;
    if (id === null || !(id in perfis)) {
      id = id || _uuid();
    }
    perfis[id] = registro;
    this._salvarTudo(perfis);
    return { id, ...registro };
  }

  excluir(perfilId) {
    const perfis = this._carregarTudo();
    if (!(perfilId in perfis)) return false;
    delete perfis[perfilId];
    this._salvarTudo(perfis);
    return true;
  }
}
