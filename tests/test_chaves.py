"""Testes das chaves de acesso (versão online, Postgres): para um programa do próprio
usuário, como o bot do Telegram, lançar gastos sem guardar a senha."""

from contextlib import closing
from datetime import date

import pytest
from argon2 import PasswordHasher
from fastapi.testclient import TestClient

from gastos.web.app import criar_app
from gastos.web.contas import LIMITE_CHAVES, PREFIXO_CHAVE, Autenticacao, hash_do_token
from gastos.web.demo import NOME_COOKIE, Demonstracao
from gastos.web.rotas import hoje

HOJE = date(2026, 9, 26)
CONVITE = "convite-de-teste"
SENHA = "senha-bem-forte"
HASHER_RAPIDO = PasswordHasher(time_cost=1, memory_cost=1024, parallelism=1)
GASTO = {"valor": "35.00", "categoria": "mercado", "descricao": "pão e leite"}


@pytest.fixture
def app(conectar_postgres):
    app = criar_app(
        demo=Demonstracao(conectar_postgres),
        autenticacao=Autenticacao(CONVITE, hasher=HASHER_RAPIDO),
    )
    app.dependency_overrides[hoje] = lambda: HOJE
    return app


def novo_usuario(app, email="ana@exemplo.com"):
    cliente = TestClient(app)
    cliente.get("/")
    resposta = cliente.post("/conta/cadastro", json={"email": email, "senha": SENHA, "convite": CONVITE})
    assert resposta.status_code == 201
    return cliente


@pytest.fixture
def ana(app):
    return novo_usuario(app)


def criar_chave(cliente, nome="Bot do Telegram"):
    return cliente.post("/conta/chaves", json={"nome": nome})


def bot(app, token):
    """Um cliente sem cookie nenhum, só com a chave (como o bot)."""
    return TestClient(app, headers={"Authorization": f"Bearer {token}"})


def consultar(conectar, sql, valores=()):
    with closing(conectar()) as conexao:
        return conexao.execute(sql, valores).fetchall()


# ---------- Criar, listar e apagar ----------


def test_token_aparece_so_na_criacao(ana):
    resposta = criar_chave(ana, nome="  Bot do Telegram  ")
    assert resposta.status_code == 201
    chave = resposta.json()
    assert chave["nome"] == "Bot do Telegram"
    assert chave["token"].startswith(PREFIXO_CHAVE) and len(chave["token"]) > 40
    assert chave["usada_em"] is None

    [listada] = ana.get("/conta/chaves").json()
    assert "token" not in listada
    assert chave["token"] not in str(listada)
    assert listada == {k: v for k, v in chave.items() if k != "token"}


def test_no_banco_fica_so_o_hash_da_chave(ana, conectar_postgres):
    token = criar_chave(ana).json()["token"]
    [linha] = consultar(conectar_postgres, "SELECT * FROM chaves")
    assert token not in str(linha)
    assert linha["token_hash"] == hash_do_token(token) and len(linha["token_hash"]) == 64


def test_cada_chave_e_diferente(ana):
    primeira = criar_chave(ana).json()["token"]
    segunda = criar_chave(ana).json()["token"]
    assert primeira != segunda


@pytest.mark.parametrize("nome", ["", "   ", "x" * 61])
def test_nome_da_chave_invalido(ana, nome):
    assert criar_chave(ana, nome=nome).status_code == 422
    assert ana.get("/conta/chaves").json() == []


def test_limite_de_chaves(ana):
    for numero in range(LIMITE_CHAVES):
        assert criar_chave(ana, nome=f"chave {numero}").status_code == 201
    resposta = criar_chave(ana)
    assert resposta.status_code == 403
    assert resposta.json()["detail"].startswith(f"Sua conta aceita até {LIMITE_CHAVES} chaves")
    # Apagando uma, cabe outra.
    primeira = ana.get("/conta/chaves").json()[0]["id"]
    assert ana.delete(f"/conta/chaves/{primeira}").status_code == 204
    assert criar_chave(ana).status_code == 201


def test_chave_apagada_da_401(app, ana):
    chave = criar_chave(ana).json()
    assert bot(app, chave["token"]).get("/categorias").status_code == 200

    assert ana.delete(f"/conta/chaves/{chave['id']}").status_code == 204
    assert ana.get("/conta/chaves").json() == []
    resposta = bot(app, chave["token"]).post("/gastos", json=GASTO)
    assert resposta.status_code == 401
    assert resposta.json() == {"detail": "Chave de acesso inválida ou apagada"}
    assert resposta.headers["www-authenticate"] == "Bearer"


def test_nao_apaga_chave_de_outro_usuario(app, ana):
    chave = criar_chave(ana).json()
    bruno = novo_usuario(app, email="bruno@exemplo.com")
    assert bruno.delete(f"/conta/chaves/{chave['id']}").status_code == 404
    assert bruno.get("/conta/chaves").json() == []
    assert bot(app, chave["token"]).get("/gastos").status_code == 200


def test_chaves_exigem_login(app):
    visitante = TestClient(app)
    assert visitante.get("/conta/chaves").status_code == 401
    assert criar_chave(visitante).status_code == 401
    assert visitante.delete("/conta/chaves/1").status_code == 401


def test_chaves_nao_existem_no_uso_pessoal(tmp_path):
    cliente = TestClient(criar_app(tmp_path / "gastos.db"))
    assert criar_chave(cliente).status_code == 404
    assert cliente.get("/conta/chaves").status_code == 404


# ---------- Usar a chave (Authorization: Bearer) ----------


def test_bearer_adiciona_gasto_na_conta_do_dono(app, ana, conectar_postgres):
    token = criar_chave(ana).json()["token"]
    cliente_bot = bot(app, token)

    resposta = cliente_bot.post("/gastos", json=GASTO)
    assert resposta.status_code == 201
    assert resposta.json() == {**GASTO, "id": resposta.json()["id"], "data": "2026-09-26"}
    # O gasto aparece para a dona, pelo site.
    assert [g["descricao"] for g in ana.get("/gastos").json()] == ["pão e leite"]
    assert cliente_bot.get("/categorias").json() == ["mercado"]
    # O bot não ganhou cookie de visitante da demonstração.
    assert NOME_COOKIE not in resposta.cookies
    [linha] = consultar(conectar_postgres, "SELECT usada_em FROM chaves")
    assert linha["usada_em"] is not None
    assert ana.get("/conta/chaves").json()[0]["usada_em"] is not None


def test_bearer_vale_para_as_outras_rotas_de_gastos(app, ana):
    cliente_bot = bot(app, criar_chave(ana).json()["token"])
    gasto = cliente_bot.post("/gastos", json=GASTO).json()
    assert cliente_bot.patch(f"/gastos/{gasto['id']}", json={"valor": "40.00"}).json()["valor"] == "40.00"
    assert cliente_bot.get("/resumo").json()["total"] == "40.00"
    assert cliente_bot.put("/orcamentos/mercado", json={"limite": "500"}).status_code == 200
    assert cliente_bot.get("/info").json() == {"demo": False, "email": "ana@exemplo.com", "cadastro": True}
    assert cliente_bot.delete(f"/gastos/{gasto['id']}").status_code == 204
    assert ana.get("/gastos").json() == []


def test_chave_nao_ve_dados_de_outro_usuario(app, ana):
    ana.post("/gastos", json={"valor": "10", "categoria": "de ana"})
    gasto_de_ana = ana.get("/gastos").json()[0]["id"]
    bruno = novo_usuario(app, email="bruno@exemplo.com")
    bot_do_bruno = bot(app, criar_chave(bruno).json()["token"])

    assert bot_do_bruno.get("/gastos").json() == []
    assert bot_do_bruno.get("/categorias").json() == []
    assert bot_do_bruno.get(f"/gastos/{gasto_de_ana}").status_code == 404
    assert bot_do_bruno.delete(f"/gastos/{gasto_de_ana}").status_code == 404
    bot_do_bruno.post("/gastos", json=GASTO)
    assert [g["categoria"] for g in ana.get("/gastos").json()] == ["de ana"]


@pytest.mark.parametrize(
    "cabecalho",
    [
        "Bearer sw_inventada",
        "Bearer ",
        "Basic YW5hOnNlbmhh",
        "sw_sem_o_bearer",
        "Bearer '; DROP TABLE chaves; --",
    ],
)
def test_chave_invalida_da_401_mesmo_com_cookie(app, ana, cabecalho):
    # Mesmo com o cookie da Ana junto, uma chave errada não cai na sessão nem na demo.
    resposta = ana.get("/gastos", headers={"Authorization": cabecalho})
    assert resposta.status_code == 401
    assert resposta.json()["detail"] in (
        "Chave de acesso inválida ou apagada",
        "Use o cabeçalho Authorization: Bearer <sua chave de acesso>",
    )
    assert ana.post("/gastos", json=GASTO, headers={"Authorization": cabecalho}).status_code == 401
    assert ana.get("/gastos").json() == []


def test_excluir_conta_apaga_as_chaves(app, ana, conectar_postgres):
    token = criar_chave(ana).json()["token"]
    assert ana.post("/conta/excluir", json={"senha": SENHA}).status_code == 204
    assert consultar(conectar_postgres, "SELECT * FROM chaves") == []
    assert bot(app, token).get("/gastos").status_code == 401


def test_rotas_da_conta_recusam_chave(app, ana):
    token = criar_chave(ana).json()["token"]
    cliente_bot = bot(app, token)
    for metodo, rota, corpo in [
        ("GET", "/conta", None),
        ("GET", "/conta/chaves", None),
        ("POST", "/conta/chaves", {"nome": "outra"}),
        ("DELETE", "/conta/chaves/1", None),
        ("POST", "/conta/excluir", {"senha": SENHA}),
        ("POST", "/conta/sair", None),
    ]:
        resposta = cliente_bot.request(metodo, rota, json=corpo)
        assert resposta.status_code == 403, rota
        assert "não aceitam chave" in resposta.json()["detail"]
    # Nem a chave junto com o cookie certo abre essas rotas.
    resposta = ana.post("/conta/excluir", json={"senha": SENHA}, headers={"Authorization": f"Bearer {token}"})
    assert resposta.status_code == 403
    assert len(ana.get("/conta/chaves").json()) == 1


# ---------- CSRF ----------

DE_FORA = {"origin": "https://site-malicioso.example"}


def test_cookie_continua_exigindo_a_mesma_origem(ana):
    assert ana.post("/gastos", json=GASTO, headers=DE_FORA).status_code == 403
    assert ana.post("/conta/chaves", json={"nome": "x"}, headers=DE_FORA).status_code == 403
    assert ana.get("/conta/chaves").json() == []
    assert ana.post("/conta/chaves", json={"nome": "x"}, headers={"origin": "http://testserver"}).status_code == 201


def test_pedido_com_chave_nao_confere_a_origem(app, ana):
    token = criar_chave(ana).json()["token"]
    resposta = bot(app, token).post("/gastos", json=GASTO, headers=DE_FORA)
    assert resposta.status_code == 201


def test_chave_invalida_de_outro_site_nao_usa_o_cookie(ana):
    # Pular a conferência da origem é seguro porque, com o cabeçalho, o cookie é ignorado.
    resposta = ana.post("/gastos", json=GASTO, headers={**DE_FORA, "Authorization": "Bearer sw_x"})
    assert resposta.status_code == 401
    assert ana.get("/gastos").json() == []


def test_no_uso_pessoal_o_cabecalho_e_ignorado_e_a_origem_conferida(tmp_path):
    cliente = TestClient(criar_app(tmp_path / "gastos.db"))
    com_chave = {"Authorization": "Bearer qualquer"}
    assert cliente.post("/gastos", json=GASTO, headers=com_chave).status_code == 201
    assert cliente.post("/gastos", json=GASTO, headers={**com_chave, **DE_FORA}).status_code == 403


# ---------- Migração ----------


def test_tabela_de_chaves_criada_em_banco_antigo(conectar_postgres):
    # Um banco de antes das chaves já tem as outras tabelas; criar de novo acrescenta só a nova.
    Demonstracao(conectar_postgres)
    with closing(conectar_postgres()) as conexao:
        conexao.execute("DROP TABLE chaves")
    Demonstracao(conectar_postgres)
    assert consultar(conectar_postgres, "SELECT * FROM chaves") == []
