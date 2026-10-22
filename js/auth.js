/**
 * auth.js — cliente de autenticação/sessão para o Gerador de FDS.
 * ==================================================
 *
 * Fala com o Apps Script Web App que guarda o login e os dados da empresa
 * numa planilha privada (nunca neste repositório). A URL abaixo é pública
 * (é só o endereço do endpoint — qualquer um pode vê-la no código-fonte),
 * mas isso não dá acesso a nada: quem chama esse endpoint ainda precisa de
 * usuário e senha válidos cadastrados na planilha para fazer login.
 *
 * POST sempre com Content-Type: text/plain — propositalmente, para evitar
 * o preflight OPTIONS do CORS, que o Apps Script Web App não responde
 * corretamente. O corpo em si continua sendo JSON normal, só o cabeçalho
 * Content-Type muda.
 *
 * Composição/fórmula do produto NUNCA passa por aqui nem é enviada a
 * lugar nenhum — este módulo só cuida de login e dos dados cadastrais da
 * empresa (Seção 1 da FDS).
 */

const URL_WEBAPP = 'https://script.google.com/macros/s/AKfycbxJC7VkIoov_t3bHUkIojJqrySQIA0UbkojkCmQQJUFt7U0VWrYiWNV46f8kgD9cbBupw/exec';

// sessionStorage: token válido só nesta aba/sessão do navegador.
// localStorage: token persistente, usado quando o usuário marca "manter conectado".
const CHAVE_TOKEN_SESSAO = 'gerador_fds_auth_token';
const CHAVE_TOKEN_PERSISTENTE = 'gerador_fds_auth_token_persistente';

async function chamar_(acao, dados = {}) {
  let resp;
  try {
    resp = await fetch(URL_WEBAPP, {
      method: 'POST',
      headers: { 'Content-Type': 'text/plain;charset=utf-8' },
      body: JSON.stringify({ acao, ...dados }),
    });
  } catch {
    throw new Error('Não foi possível conectar ao servidor de login. Verifique sua conexão.');
  }
  if (!resp.ok) {
    throw new Error('Servidor de login respondeu com erro (' + resp.status + ').');
  }
  return resp.json();
}

function lerTokenArmazenado_() {
  return sessionStorage.getItem(CHAVE_TOKEN_SESSAO) || localStorage.getItem(CHAVE_TOKEN_PERSISTENTE) || null;
}

function guardarToken_(token, lembrar) {
  // Sempre limpa os dois primeiro, pra nunca deixar um token velho esquecido no outro.
  sessionStorage.removeItem(CHAVE_TOKEN_SESSAO);
  localStorage.removeItem(CHAVE_TOKEN_PERSISTENTE);
  if (!token) return;
  if (lembrar) {
    localStorage.setItem(CHAVE_TOKEN_PERSISTENTE, token);
  } else {
    sessionStorage.setItem(CHAVE_TOKEN_SESSAO, token);
  }
}

function limparToken_() {
  sessionStorage.removeItem(CHAVE_TOKEN_SESSAO);
  localStorage.removeItem(CHAVE_TOKEN_PERSISTENTE);
}

/**
 * Cliente de autenticação. Mantém o token em memória e em sessionStorage/
 * localStorage (conforme "lembrar"), e expõe as ações que a tela precisa:
 * login, logout, validar a sessão atual, buscar dados da empresa e trocar
 * a própria senha.
 */
export class Auth {
  constructor() {
    this.token = lerTokenArmazenado_();
    this.usuario = null; // { nome, admin, trocar_senha } — preenchido após login/validarSessao
  }

  estaLogado() {
    return !!this.token;
  }

  async login(usuario, senha, lembrar = false) {
    const resp = await chamar_('login', { usuario, senha, lembrar });
    if (!resp.ok) {
      throw new Error(resp.erro || 'Usuário ou senha inválidos.');
    }
    this.token = resp.token;
    guardarToken_(this.token, lembrar);
    this.usuario = { nome: resp.nome, admin: !!resp.admin, trocar_senha: !!resp.trocar_senha };
    return this.usuario;
  }

  logout() {
    this.token = null;
    this.usuario = null;
    limparToken_();
  }

  /**
   * Confirma com o servidor que a sessão atual ainda é válida. O servidor
   * checa, na hora, se o "sv" (versão da sessão) do token ainda bate com o
   * da planilha — é isso que torna a revogação instantânea (um admin pode
   * desativar alguém pelo menu da planilha e a sessão cai no próximo
   * carregamento, sem esperar cache nenhum expirar).
   *
   * Retorna true (válida), false (inválida — já limpa o token local) ou
   * null (não deu pra confirmar por falha de rede — mantém o token como
   * estava e deixa o chamador decidir se tenta de novo).
   */
  async validarSessao() {
    if (!this.token) return false;
    let resp;
    try {
      resp = await chamar_('validar_sessao', { token: this.token });
    } catch {
      return null;
    }
    if (!resp.ok) {
      this.logout();
      return false;
    }
    this.usuario = { nome: resp.nome, admin: !!resp.admin, trocar_senha: !!resp.trocar_senha };
    return true;
  }

  /** Helper para o carregamento da página: true só quando a sessão foi de fato confirmada pelo servidor. */
  async sessaoValidaAoCarregar() {
    if (!this.token) return false;
    return (await this.validarSessao()) === true;
  }

  async obterDadosEmpresa() {
    if (!this.token) throw new Error('Não autenticado.');
    const resp = await chamar_('dados_empresa', { token: this.token });
    if (!resp.ok) {
      if (/sessao invalida/i.test(resp.erro || '')) this.logout();
      throw new Error(resp.erro || 'Não foi possível obter os dados da empresa.');
    }
    return resp.empresa;
  }

  async trocarSenha(senhaAtual, senhaNova) {
    if (!this.token) throw new Error('Não autenticado.');
    // Mantém o mesmo tipo de armazenamento ("lembrar" ou não) que já estava em uso.
    const lembrar = !!localStorage.getItem(CHAVE_TOKEN_PERSISTENTE);
    const resp = await chamar_('trocar_senha', {
      token: this.token,
      senha_atual: senhaAtual,
      senha_nova: senhaNova,
    });
    if (!resp.ok) {
      throw new Error(resp.erro || 'Não foi possível trocar a senha.');
    }
    this.token = resp.token;
    guardarToken_(this.token, lembrar);
    if (this.usuario) this.usuario.trocar_senha = false;
    return true;
  }
}

export const auth = new Auth();
