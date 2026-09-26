import threading
from contextlib import closing
from datetime import date

import pytest
from fastapi.testclient import TestClient

from gastos.armazenamento import Banco
from gastos.web.app import criar_app
from gastos.web.demo import (
    LIMITE_GASTOS,
    LIMITE_RECORRENTES,
    NOME_COOKIE,
    Demonstracao,
    mes_anterior,
    preencher_exemplos,
)
from gastos.web.rotas import hoje

HOJE = date(2026, 9, 26)


@pytest.fixture
def demo(conectar_postgres):
    return Demonstracao(conectar_postgres)


def novo_cliente(demo, dia=HOJE):
    app = criar_app(demo=demo)
    app.dependency_overrides[hoje] = lambda: dia
    return TestClient(app)


@pytest.fixture
def cliente(demo):
    cliente = novo_cliente(demo)
    cliente.get("/")  # como no navegador: a página chega primeiro, já com o cookie
    return cliente


def contar(conectar, tabela):
    with closing(conectar()) as conexao:
        return conexao.execute(f"SELECT count(*) AS n FROM {tabela}").fetchone()["n"]


# ---------- Dados de exemplo (não precisam de Postgres) ----------


@pytest.mark.parametrize(
    "mes, quantos, esperado",
    [("2026-09", 1, "2026-08"), ("2026-01", 1, "2025-12"), ("2026-02", 2, "2025-12")],
)
def test_mes_anterior(mes, quantos, esperado):
    assert mes_anterior(mes, quantos) == esperado


def test_exemplos_ficam_nos_ultimos_tres_meses_e_nunca_no_futuro(tmp_path):
    banco = Banco(tmp_path / "exemplo.db")
    dia = date(2026, 3, 2)  # começo do mês: vários dias do exemplo ainda não chegaram

    preencher_exemplos(banco, dia)

    datas = [g.data for g in banco.listar()]
    assert max(datas) == dia
    assert {f"{d:%Y-%m}" for d in datas} == {"2026-01", "2026-02", "2026-03"}
    assert set(banco.listar_orcamentos()) == {"mercado", "alimentação", "lazer"}
    # O aluguel (dia 5) já foi lançado em janeiro e fevereiro, e o de março ainda não.
    alugueis = [g.data for g in banco.listar() if g.categoria == "aluguel"]
    assert alugueis == [date(2026, 1, 5), date(2026, 2, 5)]


def test_uso_pessoal_nao_tem_limite_nem_cookie(tmp_path, monkeypatch):
    monkeypatch.setattr("gastos.web.rotas.LIMITE_GASTOS", 0)
    cliente = TestClient(criar_app(tmp_path / "gastos.db"))
    assert cliente.post("/gastos", json={"valor": "10", "categoria": "x"}).status_code == 201
    assert cliente.get("/info").json() == {"demo": False}
    assert NOME_COOKIE not in cliente.get("/").cookies


def test_precisa_de_banco_ou_demo():
    with pytest.raises(ValueError):
        criar_app()


# ---------- Demonstração com Postgres ----------


def test_pagina_entrega_o_cookie_do_visitante(demo):
    resposta = novo_cliente(demo).get("/")
    cookie = resposta.cookies.get(NOME_COOKIE)
    assert cookie and len(cookie) == 32
    assert "httponly" in resposta.headers["set-cookie"].lower()


def test_visitante_comeca_com_os_exemplos(cliente):
    assert cliente.get("/info").json() == {"demo": True}
    gastos = cliente.get("/gastos?mes=2026-09").json()
    assert len(gastos) == 9  # 7 do exemplo + aluguel e internet lançados sozinhos
    assert len(cliente.get("/recorrentes").json()) == 2
    assert cliente.get("/resumo?mes=2026-09").json()["total"] == "2088.95"


def test_remover_fica_gravado(cliente):
    gasto = cliente.get("/gastos").json()[-1]
    assert cliente.delete(f"/gastos/{gasto['id']}").status_code == 204
    # Online, este era o defeito: o gasto apagado "voltava" em outros pedidos.
    for _ in range(3):
        assert gasto["id"] not in [g["id"] for g in cliente.get("/gastos").json()]


def test_cada_visitante_ve_so_os_proprios_dados(demo, cliente):
    outro = novo_cliente(demo)
    outro.get("/")

    cliente.post("/gastos", json={"valor": "999", "categoria": "só meu"})
    for gasto in outro.get("/gastos").json():
        assert outro.delete(f"/gastos/{gasto['id']}").status_code == 204

    assert "só meu" in cliente.get("/categorias").json()
    assert "só meu" not in outro.get("/categorias").json()
    assert len(cliente.get("/gastos").json()) > 1
    assert outro.get("/gastos").json() == []


def test_visitante_nao_mexe_no_gasto_de_outro_pelo_numero(demo, cliente):
    outro = novo_cliente(demo)
    outro.get("/")
    alheio = cliente.get("/gastos").json()[0]["id"]

    assert outro.get(f"/gastos/{alheio}").status_code == 404
    assert outro.patch(f"/gastos/{alheio}", json={"valor": "1"}).status_code == 404
    assert outro.delete(f"/gastos/{alheio}").status_code == 404
    assert cliente.get(f"/gastos/{alheio}").status_code == 200


def test_cookie_invalido_vira_visitante_novo(demo, conectar_postgres, cliente):
    cliente.cookies.set(NOME_COOKIE, "'; DROP TABLE contas; --")
    resposta = cliente.get("/gastos")
    assert resposta.status_code == 200
    assert len(resposta.cookies.get(NOME_COOKIE)) == 32
    with closing(conectar_postgres()) as conexao:
        contas = [linha["id"] for linha in conexao.execute("SELECT id FROM contas")]
    assert all(len(conta) == 32 for conta in contas)


def test_pedidos_simultaneos_de_um_visitante_novo(demo, conectar_postgres):
    # A página faz 5 pedidos juntos. Só uma conta pode ser criada, com um exemplo só.
    comecar = threading.Barrier(6)
    erros = []

    def pedido():
        try:
            comecar.wait()
            with demo.abrir("c" * 32, HOJE) as banco:
                banco.lancar_recorrentes(HOJE)
        except Exception as erro:  # noqa: BLE001 - o teste mostra qualquer erro
            erros.append(erro)

    threads = [threading.Thread(target=pedido) for _ in range(6)]
    for thread in threads:
        thread.start()
    for thread in threads:
        thread.join()

    assert erros == []
    assert contar(conectar_postgres, "contas") == 1
    assert contar(conectar_postgres, "recorrentes") == 2
    assert contar(conectar_postgres, "gastos") == 13 + 6  # exemplos + 3 meses de aluguel e internet


def test_limite_de_gastos_na_demo(cliente, monkeypatch):
    monkeypatch.setattr("gastos.web.rotas.LIMITE_GASTOS", len(cliente.get("/gastos").json()))
    resposta = cliente.post("/gastos", json={"valor": "10", "categoria": "x"})
    assert resposta.status_code == 403
    assert "Remova algum" in resposta.json()["detail"]
    assert LIMITE_GASTOS == 300


def test_limite_de_recorrentes_na_demo(cliente):
    for _ in range(LIMITE_RECORRENTES - 2):  # o exemplo já tem 2
        resposta = cliente.post("/recorrentes", json={"valor": "1", "categoria": "x", "dia": 28})
        assert resposta.status_code == 201
    resposta = cliente.post("/recorrentes", json={"valor": "1", "categoria": "x", "dia": 28})
    assert resposta.status_code == 403


def test_contas_vencidas_sao_apagadas_com_tudo_delas(demo, conectar_postgres):
    with demo.abrir("a" * 32, HOJE):
        pass
    with closing(conectar_postgres()) as conexao:
        conexao.execute("UPDATE contas SET criada_em = now() - interval '2 days'")

    with demo.abrir("b" * 32, HOJE):
        pass

    with closing(conectar_postgres()) as conexao:
        assert [l["id"] for l in conexao.execute("SELECT id FROM contas")] == ["b" * 32]
        donos = {l["conta"] for l in conexao.execute("SELECT DISTINCT conta FROM gastos")}
    assert donos == {"b" * 32}


def test_quantidade_maxima_de_contas(conectar_postgres):
    demo = Demonstracao(conectar_postgres, max_contas=3)
    for letra in "abcde":
        with demo.abrir(letra * 32, HOJE):
            pass
    assert contar(conectar_postgres, "contas") == 3
