"""Testes do login da versão online (Postgres): cadastro com convite, sessões e segurança."""

from contextlib import closing
from datetime import date

import pytest
from argon2 import PasswordHasher
from fastapi.testclient import TestClient

from gastos.web.app import criar_app
from gastos.web.contas import MAXIMO_TENTATIVAS, Autenticacao
from gastos.web.demo import NOME_COOKIE, Demonstracao
from gastos.web.rotas import COOKIE_SESSAO, hoje

HOJE = date(2026, 9, 26)
CONVITE = "convite-de-teste"
SENHA = "senha-bem-forte"
# argon2 mais leve só nos testes (o de verdade gasta 64 MB e ~0,1 s por senha)
HASHER_RAPIDO = PasswordHasher(time_cost=1, memory_cost=1024, parallelism=1)


@pytest.fixture
def app(conectar_postgres):
    app = criar_app(
        demo=Demonstracao(conectar_postgres),
        autenticacao=Autenticacao(CONVITE, hasher=HASHER_RAPIDO),
    )
    app.dependency_overrides[hoje] = lambda: HOJE
    return app


def novo_cliente(app):
    cliente = TestClient(app)
    cliente.get("/")
    return cliente


@pytest.fixture
def cliente(app):
    return novo_cliente(app)


def cadastrar(cliente, email="ana@exemplo.com", senha=SENHA, convite=CONVITE):
    return cliente.post("/conta/cadastro", json={"email": email, "senha": senha, "convite": convite})


def entrar(cliente, email="ana@exemplo.com", senha=SENHA):
    return cliente.post("/conta/entrar", json={"email": email, "senha": senha})


def consultar(conectar, sql, valores=()):
    with closing(conectar()) as conexao:
        return conexao.execute(sql, valores).fetchall()


# ---------- Cadastro ----------


def test_cadastro_com_convite_ja_entra_na_conta_vazia(cliente):
    assert cliente.get("/info").json()["demo"] is True
    resposta = cadastrar(cliente, email=" Ana@Exemplo.com ")

    assert resposta.status_code == 201
    assert resposta.json() == {"email": "ana@exemplo.com"}
    assert cliente.get("/info").json() == {"demo": False, "email": "ana@exemplo.com", "cadastro": True}
    # A conta nova começa vazia (sem os exemplos da demonstração).
    assert cliente.get("/gastos").json() == []
    assert cliente.get("/recorrentes").json() == []


@pytest.mark.parametrize(
    "dados, status",
    [
        ({"convite": "errado"}, 403),
        ({"convite": ""}, 403),
        ({"senha": "curta"}, 422),
        ({"senha": "x" * 129}, 422),
        ({"email": "sem-arroba"}, 422),
        ({"email": "a@b"}, 422),
    ],
)
def test_cadastro_recusado(cliente, conectar_postgres, dados, status):
    assert cadastrar(cliente, **dados).status_code == status
    assert consultar(conectar_postgres, "SELECT * FROM contas WHERE tipo = 'usuario'") == []


def test_cadastro_fechado_sem_codigo_de_convite(conectar_postgres):
    app = criar_app(demo=Demonstracao(conectar_postgres), autenticacao=Autenticacao(None))
    cliente = novo_cliente(app)
    assert cliente.get("/info").json()["cadastro"] is False
    resposta = cadastrar(cliente, convite="")
    assert resposta.status_code == 403
    assert resposta.json()["detail"] == "O cadastro está fechado"


def test_email_repetido_mesmo_com_maiusculas(cliente, app):
    assert cadastrar(cliente).status_code == 201
    resposta = cadastrar(novo_cliente(app), email="ANA@exemplo.com")
    assert resposta.status_code == 409


def test_senha_guardada_com_argon2_nunca_em_texto(cliente, conectar_postgres):
    cadastrar(cliente)
    [linha] = consultar(conectar_postgres, "SELECT senha_hash FROM contas WHERE tipo = 'usuario'")
    assert linha["senha_hash"].startswith("$argon2id$")
    assert SENHA not in linha["senha_hash"]


# ---------- Entrar e sair ----------


def test_entrar_e_sair(app, cliente):
    cadastrar(cliente)
    cliente.post("/conta/sair")
    assert cliente.get("/info").json()["demo"] is True  # saiu: volta para a demonstração

    outro = novo_cliente(app)
    resposta = entrar(outro, email="ANA@exemplo.com")
    assert resposta.status_code == 200
    assert outro.get("/conta").json() == {"email": "ana@exemplo.com"}


def test_cookie_da_sessao_e_protegido(app, cliente):
    cadastrar(cliente)
    resposta = entrar(novo_cliente(app))
    cookie = resposta.headers["set-cookie"].lower()
    assert COOKIE_SESSAO in cookie and "httponly" in cookie and "samesite=lax" in cookie


def test_https_marca_o_cookie_como_secure(app, cliente):
    cadastrar(cliente)
    resposta = novo_cliente(app).post(
        "/conta/entrar",
        json={"email": "ana@exemplo.com", "senha": SENHA},
        headers={"x-forwarded-proto": "https"},
    )
    assert "secure" in resposta.headers["set-cookie"].lower()


def test_mesma_mensagem_para_email_inexistente_e_senha_errada(cliente):
    cadastrar(cliente)
    sem_conta = entrar(cliente, email="ninguem@exemplo.com")
    senha_errada = entrar(cliente, senha="senha-errada")
    assert sem_conta.status_code == senha_errada.status_code == 401
    assert sem_conta.json() == senha_errada.json() == {"detail": "E-mail ou senha incorretos"}


def test_bloqueia_depois_de_senhas_erradas_demais(app, cliente):
    cadastrar(cliente)
    atacante = novo_cliente(app)
    for _ in range(MAXIMO_TENTATIVAS):
        assert entrar(atacante, senha="chute-errado").status_code == 401
    # Bloqueado até com a senha certa, e o erro diz para esperar.
    resposta = entrar(atacante)
    assert resposta.status_code == 429
    assert "15 minutos" in resposta.json()["detail"]


def test_login_certo_zera_as_tentativas(app, cliente, conectar_postgres):
    cadastrar(cliente)
    for _ in range(MAXIMO_TENTATIVAS - 1):
        entrar(novo_cliente(app), senha="chute-errado")
    assert entrar(novo_cliente(app)).status_code == 200
    assert consultar(conectar_postgres, "SELECT * FROM tentativas_login") == []


def test_sair_invalida_a_sessao_no_servidor(app, cliente):
    cadastrar(cliente)
    token = cliente.cookies.get(COOKIE_SESSAO)
    cliente.post("/conta/sair")

    # Mesmo que alguém tenha copiado o cookie antes, ele não vale mais.
    ladrao = novo_cliente(app)
    ladrao.cookies.set(COOKIE_SESSAO, token)
    assert ladrao.get("/conta").status_code == 401
    assert ladrao.get("/info").json()["demo"] is True


def test_no_banco_fica_so_o_hash_do_token(cliente, conectar_postgres):
    cadastrar(cliente)
    token = cliente.cookies.get(COOKIE_SESSAO)
    [sessao] = consultar(conectar_postgres, "SELECT token_hash FROM sessoes")
    assert sessao["token_hash"] != token and len(sessao["token_hash"]) == 64


def test_sessao_vencida_nao_vale(cliente, conectar_postgres):
    cadastrar(cliente)
    consultar_sem_resultado = "UPDATE sessoes SET expira_em = now() - interval '1 second'"
    with closing(conectar_postgres()) as conexao:
        conexao.execute(consultar_sem_resultado)
    assert cliente.get("/conta").status_code == 401


@pytest.mark.parametrize("token", ["", "abc", "x" * 500, "'; DROP TABLE sessoes; --"])
def test_token_inventado_nao_entra(app, token):
    cliente = novo_cliente(app)
    cliente.cookies.set(COOKIE_SESSAO, token)
    assert cliente.get("/conta").status_code == 401
    assert cliente.get("/gastos").status_code == 200  # segue na demonstração


# ---------- Dados de cada um ----------


def test_cada_usuario_ve_so_os_proprios_gastos(app, cliente):
    cadastrar(cliente)
    cliente.post("/gastos", json={"valor": "10", "categoria": "de ana"})
    bruno = novo_cliente(app)
    cadastrar(bruno, email="bruno@exemplo.com")

    gasto_de_ana = cliente.get("/gastos").json()[0]["id"]
    assert bruno.get("/gastos").json() == []
    assert bruno.get(f"/gastos/{gasto_de_ana}").status_code == 404
    assert bruno.patch(f"/gastos/{gasto_de_ana}", json={"valor": "1"}).status_code == 404
    assert bruno.delete(f"/gastos/{gasto_de_ana}").status_code == 404
    assert cliente.get(f"/gastos/{gasto_de_ana}").json()["valor"] == "10.00"


def test_visitante_da_demo_nao_ve_dados_de_usuario(app, cliente):
    cadastrar(cliente)
    cliente.post("/gastos", json={"valor": "10", "categoria": "secreto"})
    visitante = novo_cliente(app)
    assert "secreto" not in visitante.get("/categorias").json()


def test_cookie_da_demo_nao_abre_conta_de_usuario(app, cliente, conectar_postgres):
    cadastrar(cliente)
    [conta] = consultar(conectar_postgres, "SELECT id FROM contas WHERE tipo = 'usuario'")
    atacante = TestClient(app)
    atacante.cookies.set(NOME_COOKIE, conta["id"])  # "u_..." nem tem o formato do cookie da demo
    resposta = atacante.get("/gastos")
    assert resposta.status_code == 200
    assert resposta.cookies.get(NOME_COOKIE) != conta["id"]  # virou um visitante novo


def test_limpeza_da_demo_nunca_apaga_conta_de_usuario(app, cliente, conectar_postgres):
    cadastrar(cliente)
    cliente.post("/gastos", json={"valor": "10", "categoria": "x"})
    with closing(conectar_postgres()) as conexao:
        conexao.execute("UPDATE contas SET criada_em = now() - interval '400 days'")

    demo = Demonstracao(conectar_postgres, max_contas=1)
    for letra in "abc":  # visitantes novos disparam a limpeza (por idade e por quantidade)
        with demo.abrir(letra * 32, HOJE):
            pass

    usuarios = consultar(conectar_postgres, "SELECT id FROM contas WHERE tipo = 'usuario'")
    assert len(usuarios) == 1
    assert len(cliente.get("/gastos").json()) == 1


def test_usuario_nao_tem_o_limite_da_demo(cliente, monkeypatch):
    cadastrar(cliente)
    monkeypatch.setattr("gastos.web.rotas.LIMITE_GASTOS", 0)
    assert cliente.post("/gastos", json={"valor": "10", "categoria": "x"}).status_code == 201
    monkeypatch.setattr("gastos.web.rotas.LIMITE_GASTOS_USUARIO", 1)
    resposta = cliente.post("/gastos", json={"valor": "10", "categoria": "x"})
    assert resposta.status_code == 403
    assert resposta.json()["detail"].startswith("Sua conta aceita até 1 gastos")


# ---------- Excluir conta ----------


def test_excluir_conta_pede_a_senha_e_apaga_tudo(cliente, conectar_postgres):
    cadastrar(cliente)
    cliente.post("/gastos", json={"valor": "10", "categoria": "x"})
    cliente.put("/orcamentos/x", json={"limite": "100"})

    assert cliente.post("/conta/excluir", json={"senha": "errada"}).status_code == 403
    assert cliente.post("/conta/excluir", json={"senha": SENHA}).status_code == 204

    assert consultar(conectar_postgres, "SELECT * FROM contas WHERE tipo = 'usuario'") == []
    assert consultar(conectar_postgres, "SELECT * FROM sessoes") == []
    assert cliente.get("/info").json()["demo"] is True
    assert entrar(cliente).status_code == 401


def test_excluir_sem_estar_logado(cliente):
    assert cliente.post("/conta/excluir", json={"senha": SENHA}).status_code == 401


# ---------- CSRF e uso pessoal ----------


def test_pedido_de_outro_site_e_recusado(cliente):
    cadastrar(cliente)
    de_fora = {"origin": "https://site-malicioso.example"}
    resposta = cliente.post("/gastos", json={"valor": "10", "categoria": "x"}, headers=de_fora)
    assert resposta.status_code == 403
    assert cliente.post("/conta/sair", headers=de_fora).status_code == 403
    # Da própria página (mesma origem), funciona.
    mesma = {"origin": "http://testserver"}
    assert cliente.post("/gastos", json={"valor": "10", "categoria": "x"}, headers=mesma).status_code == 201


def test_login_nao_existe_no_uso_pessoal(tmp_path):
    cliente = TestClient(criar_app(tmp_path / "gastos.db"))
    assert cadastrar(cliente).status_code == 404
    assert entrar(cliente).status_code == 404
    assert cliente.get("/info").json() == {"demo": False, "email": None, "cadastro": False}


def test_login_exige_modo_online(tmp_path):
    with pytest.raises(ValueError):
        criar_app(tmp_path / "gastos.db", autenticacao=Autenticacao(CONVITE))


def test_migracao_de_contas_antigas(conectar_postgres):
    # O banco online tinha contas só com id e criada_em (antes do login).
    with closing(conectar_postgres()) as conexao:
        conexao.execute("CREATE TABLE contas (id TEXT PRIMARY KEY, criada_em TIMESTAMPTZ NOT NULL DEFAULT now())")
        conexao.execute("INSERT INTO contas (id) VALUES (%s)", ("a" * 32,))
    Demonstracao(conectar_postgres)  # cria/migra as tabelas
    [conta] = consultar(conectar_postgres, "SELECT tipo, email FROM contas")
    assert (conta["tipo"], conta["email"]) == ("demo", None)


def test_espacos_no_email_sao_ignorados_mas_na_senha_nao(app, cliente):
    assert cadastrar(cliente, email=" ana@exemplo.com ", senha=" com espaços ").status_code == 201
    assert entrar(novo_cliente(app), email="ana@exemplo.com ", senha=" com espaços ").status_code == 200
    assert entrar(novo_cliente(app), senha="com espaços").status_code == 401
