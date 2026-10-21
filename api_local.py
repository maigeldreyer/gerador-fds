"""
API local do Gerador de FDS
============================

Pequeno servidor Flask que expõe o motor de cálculo (toxicidade aguda +
corrosão/irritação à pele + lesão ocular) para a tela HTML consumir via
fetch(). Roda 100% na máquina do usuário — a tela publicada faz
requisições para http://localhost:5000, então este servidor precisa
estar rodando localmente para os botões "Calcular classificação" e
"Gerar FDS em PDF" funcionarem.

Como rodar:
    pip install flask   (se ainda não tiver)
    python3 api_local.py
    -> abre em http://localhost:5000 (a própria tela também é servida
       daqui, em "/", para evitar problemas de CORS/arquivo local)

Este módulo é só a camada de integração (HTTP + validação de entrada).
Toda a lógica de classificação já foi implementada e testada
separadamente em motor_toxicidade_aguda.py, motor_corrosao_irritacao.py
e banco_substancias.py — este arquivo não reimplementa nenhuma regra da
norma, só orquestra chamadas a esses módulos. A montagem da FDS completa
e a geração do PDF ficam em gerador_fds.py; os perfis de empresa (Seção 1,
reaproveitáveis entre produtos) ficam em perfis_empresa.py.
"""

import io
import os

from flask import Flask, jsonify, request, send_file, send_from_directory

from banco_substancias import BancoSubstancias
from motor_toxicidade_aguda import classificar_todas_as_vias
from motor_corrosao_irritacao import classificar_corrosao_irritacao_pele, classificar_lesao_ocular
from gerador_fds import montar_dados_fds, gerar_pdf_fds
from perfis_empresa import RepositorioPerfisEmpresa

CAMINHO_DB = os.environ.get("FDS_DB_PATH", "substancias.db")
PASTA_ESTATICA = os.path.dirname(os.path.abspath(__file__))

app = Flask(__name__)
_repo_perfis = RepositorioPerfisEmpresa()


@app.after_request
def _permitir_cors(resposta):
    # A tela pode estar publicada em outra origem (ex.: claude.ai) e
    # rodar no navegador do usuário, que então chama este servidor local
    # — por isso liberamos CORS de forma ampla aqui. Isso é seguro porque
    # o servidor só escuta em localhost, então só o próprio computador do
    # usuário consegue alcançá-lo.
    resposta.headers["Access-Control-Allow-Origin"] = "*"
    resposta.headers["Access-Control-Allow-Headers"] = "Content-Type"
    resposta.headers["Access-Control-Allow-Methods"] = "GET, POST, OPTIONS"
    return resposta


@app.route("/")
def index():
    return send_from_directory(PASTA_ESTATICA, "gerador-fds.html")


def _validar_entrada(dados: dict):
    """Validação de entrada compartilhada por /api/classificar e
    /api/gerar_fds — ambos recebem produto + composição no mesmo formato
    e precisam das mesmas checagens antes de acionar os motores.

    Retorna (nome_produto, estado_fisico, formula, soma_concentracoes,
    erros_validacao). Quando `erros_validacao` não está vazio, o chamador
    deve responder 400 e não prosseguir."""
    nome_produto = (dados.get("nome_produto") or "").strip()
    estado_fisico = dados.get("estado_fisico")
    composicao = dados.get("composicao", [])

    erros_validacao = []
    if not nome_produto:
        erros_validacao.append("Nome do produto é obrigatório.")
    if estado_fisico not in ("liquido", "solido_pulverulento"):
        erros_validacao.append('estado_fisico deve ser "liquido" ou "solido_pulverulento".')
    if not composicao:
        erros_validacao.append("A composição da mistura não pode estar vazia.")

    formula = []
    soma_concentracoes = 0.0
    for i, item in enumerate(composicao):
        nome = (item.get("nome") or "").strip()
        cas = (item.get("cas") or "").strip()
        try:
            concentracao = float(item.get("concentracao"))
        except (TypeError, ValueError):
            erros_validacao.append(f"Linha {i + 1}: concentração inválida.")
            continue
        if not nome:
            erros_validacao.append(f"Linha {i + 1}: nome da substância é obrigatório.")
            continue
        if not cas:
            erros_validacao.append(
                f"Linha {i + 1} ('{nome}'): Nº CAS é obrigatório — o motor busca a "
                f"classificação de perigo pelo CAS, sem ele a substância não pode ser avaliada."
            )
            continue
        formula.append({
            "nome": nome,
            "cas": cas,
            "concentracao": concentracao,
            "segredo_industrial": bool(item.get("segredo_industrial")),
        })
        soma_concentracoes += concentracao

    if not erros_validacao and abs(soma_concentracoes - 100.0) > 0.5:
        erros_validacao.append(
            f"A soma das concentrações é {soma_concentracoes:.2f}%, não 100%. "
            f"Corrija a fórmula antes de calcular a classificação."
        )

    return nome_produto, estado_fisico, formula, soma_concentracoes, erros_validacao


def _calcular_classificacao(banco: BancoSubstancias, formula: list, estado_fisico: str):
    """Roda os dois motores de cálculo (toxicidade aguda + corrosão/
    irritação à pele/olhos) sobre a fórmula já validada. Compartilhado por
    /api/classificar e /api/gerar_fds para nunca haver dois caminhos de
    cálculo divergentes."""
    ingredientes_toxicidade, avisos_toxicidade = banco.montar_ingredientes_por_via(
        formula, estado_fisico_produto=estado_fisico
    )
    resultado_toxicidade_aguda = classificar_todas_as_vias(ingredientes_toxicidade)

    ingredientes_pele_olhos, avisos_pele_olhos = banco.montar_ingredientes_pele_olhos(formula)
    resultado_pele = classificar_corrosao_irritacao_pele(ingredientes_pele_olhos)
    resultado_olhos = classificar_lesao_ocular(ingredientes_pele_olhos)

    return resultado_toxicidade_aguda, resultado_pele, resultado_olhos, avisos_toxicidade + avisos_pele_olhos


@app.route("/api/classificar", methods=["POST", "OPTIONS"])
def classificar():
    if request.method == "OPTIONS":
        return "", 204

    dados = request.get_json(force=True, silent=True)
    if not dados:
        return jsonify({"erro": "Corpo da requisição ausente ou não é JSON válido."}), 400

    nome_produto, estado_fisico, formula, soma_concentracoes, erros_validacao = _validar_entrada(dados)
    if erros_validacao:
        erro_principal = "Fórmula não fecha em 100%." if any("100%" in e for e in erros_validacao) else "Dados de entrada inválidos."
        return jsonify({"erro": erro_principal, "detalhes": erros_validacao}), 400

    banco = BancoSubstancias(CAMINHO_DB)
    try:
        resultado_toxicidade_aguda, resultado_pele, resultado_olhos, avisos = _calcular_classificacao(
            banco, formula, estado_fisico
        )
    finally:
        banco.close()

    return jsonify({
        "produto": nome_produto,
        "soma_concentracoes": round(soma_concentracoes, 2),
        "toxicidade_aguda": resultado_toxicidade_aguda,
        "corrosao_irritacao_pele": resultado_pele,
        "lesao_ocular": resultado_olhos,
        "avisos": avisos,
    })


@app.route("/api/gerar_fds", methods=["POST", "OPTIONS"])
def gerar_fds():
    """Roda a mesma classificação de /api/classificar e, em seguida,
    monta a FDS completa (16 seções) e devolve o PDF pronto para
    download — nada de HTML intermediário, conforme decidido na
    entrevista com o usuário."""
    if request.method == "OPTIONS":
        return "", 204

    dados = request.get_json(force=True, silent=True)
    if not dados:
        return jsonify({"erro": "Corpo da requisição ausente ou não é JSON válido."}), 400

    nome_produto, estado_fisico, formula, soma_concentracoes, erros_validacao = _validar_entrada(dados)
    if erros_validacao:
        erro_principal = "Fórmula não fecha em 100%." if any("100%" in e for e in erros_validacao) else "Dados de entrada inválidos."
        return jsonify({"erro": erro_principal, "detalhes": erros_validacao}), 400

    perfil_empresa = dados.get("perfil_empresa") or {}
    perfil_empresa_id = dados.get("perfil_empresa_id")
    if perfil_empresa_id:
        perfil_salvo = _repo_perfis.obter(perfil_empresa_id)
        if perfil_salvo is None:
            return jsonify({"erro": "Dados de entrada inválidos.", "detalhes": [f"Perfil de empresa '{perfil_empresa_id}' não encontrado."]}), 400
        perfil_empresa = perfil_salvo

    produto_info = dict(dados.get("produto_info") or {})
    produto_info["nome_produto"] = nome_produto
    campos_extras = dados.get("campos_extras") or {}
    numero_revisao = str(dados.get("numero_revisao") or "01")

    banco = BancoSubstancias(CAMINHO_DB)
    try:
        resultado_toxicidade_aguda, resultado_pele, resultado_olhos, avisos = _calcular_classificacao(
            banco, formula, estado_fisico
        )

        dados_fds = montar_dados_fds(
            perfil_empresa=perfil_empresa,
            produto_info=produto_info,
            composicao=formula,
            estado_fisico=estado_fisico,
            resultado_toxicidade_aguda=resultado_toxicidade_aguda,
            resultado_pele=resultado_pele,
            resultado_olhos=resultado_olhos,
            banco=banco,
            campos_extras=campos_extras,
            numero_revisao=numero_revisao,
        )

        buffer_pdf = io.BytesIO()
        gerar_pdf_fds(dados_fds, buffer_pdf)
    finally:
        banco.close()

    buffer_pdf.seek(0)
    nome_arquivo = "FDS_" + "".join(c if c.isalnum() else "_" for c in nome_produto).strip("_") + ".pdf"
    return send_file(
        buffer_pdf,
        mimetype="application/pdf",
        as_attachment=True,
        download_name=nome_arquivo or "FDS.pdf",
    )


@app.route("/api/perfis", methods=["GET", "POST", "OPTIONS"])
def perfis():
    if request.method == "OPTIONS":
        return "", 204
    if request.method == "GET":
        return jsonify(_repo_perfis.listar())

    dados = request.get_json(force=True, silent=True) or {}
    try:
        perfil = _repo_perfis.salvar(dados)
    except ValueError as e:
        return jsonify({"erro": "Dados de entrada inválidos.", "detalhes": [str(e)]}), 400
    return jsonify(perfil), 201


@app.route("/api/perfis/<perfil_id>", methods=["GET", "PUT", "DELETE", "OPTIONS"])
def perfil_individual(perfil_id):
    if request.method == "OPTIONS":
        return "", 204

    if request.method == "GET":
        perfil = _repo_perfis.obter(perfil_id)
        if perfil is None:
            return jsonify({"erro": "Perfil não encontrado."}), 404
        return jsonify(perfil)

    if request.method == "PUT":
        dados = request.get_json(force=True, silent=True) or {}
        if _repo_perfis.obter(perfil_id) is None:
            return jsonify({"erro": "Perfil não encontrado."}), 404
        try:
            perfil = _repo_perfis.salvar(dados, perfil_id=perfil_id)
        except ValueError as e:
            return jsonify({"erro": "Dados de entrada inválidos.", "detalhes": [str(e)]}), 400
        return jsonify(perfil)

    # DELETE
    if _repo_perfis.excluir(perfil_id):
        return "", 204
    return jsonify({"erro": "Perfil não encontrado."}), 404


if __name__ == "__main__":
    if not os.path.exists(CAMINHO_DB):
        print(f"AVISO: banco de dados '{CAMINHO_DB}' não encontrado. "
              f"Rode a importação do Anexo VI primeiro (ver banco_substancias.py).")
    app.run(host="127.0.0.1", port=5000, debug=True)
