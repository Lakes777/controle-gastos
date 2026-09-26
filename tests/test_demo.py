import os
import time
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
def pasta(tmp_path):
    return tmp_path / "demo"


def novo_cliente(pasta, dia=HOJE):
    app = criar_app(demo=Demonstracao(pasta))
    app.dependency_overrides[hoje] = lambda: dia
    return TestClient(app)


@pytest.fixture
def cliente(pasta):
    cliente = novo_cliente(pasta)
    cliente.get("/")  # como no navegador: a página chega primeiro, já com o cookie
    return cliente


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


def test_pagina_entrega_o_cookie_do_visitante(pasta):
    resposta = novo_cliente(pasta).get("/")
    cookie = resposta.cookies.get(NOME_COOKIE)
    assert cookie and len(cookie) == 32
    assert "httponly" in resposta.headers["set-cookie"].lower()


def test_visitante_comeca_com_os_exemplos(cliente):
    assert cliente.get("/info").json() == {"demo": True}
    gastos = cliente.get("/gastos?mes=2026-09").json()
    assert len(gastos) == 9  # 7 do exemplo + aluguel e internet lançados sozinhos
    assert len(cliente.get("/recorrentes").json()) == 2


def test_cada_visitante_ve_so_os_proprios_dados(pasta, cliente):
    outro = novo_cliente(pasta)
    outro.get("/")

    cliente.post("/gastos", json={"valor": "999", "categoria": "só meu"})
    for gasto in outro.get("/gastos").json():
        outro.delete(f"/gastos/{gasto['id']}")

    assert "só meu" in cliente.get("/categorias").json()
    assert "só meu" not in outro.get("/categorias").json()
    assert len(cliente.get("/gastos").json()) > 1
    assert outro.get("/gastos").json() == []


def test_cookie_invalido_vira_visitante_novo(pasta, cliente):
    # Um valor como "../../algo" nunca vira nome de arquivo.
    cliente.cookies.set(NOME_COOKIE, "../../etc/passwd")
    resposta = cliente.get("/gastos")
    assert resposta.status_code == 200
    assert resposta.cookies.get(NOME_COOKIE) != "../../etc/passwd"
    assert all(len(c.stem) == 32 for c in pasta.glob("*.db"))


def test_limite_de_gastos_na_demo(cliente, monkeypatch):
    monkeypatch.setattr("gastos.web.rotas.LIMITE_GASTOS", len(cliente.get("/gastos").json()))
    resposta = cliente.post("/gastos", json={"valor": "10", "categoria": "x"})
    assert resposta.status_code == 403
    assert "Remova algum" in resposta.json()["detail"]
    assert LIMITE_GASTOS == 300


def test_limite_de_recorrentes_na_demo(cliente):
    for _ in range(LIMITE_RECORRENTES - 2):  # o exemplo já tem 2
        assert cliente.post("/recorrentes", json={"valor": "1", "categoria": "x", "dia": 28}).status_code == 201
    resposta = cliente.post("/recorrentes", json={"valor": "1", "categoria": "x", "dia": 28})
    assert resposta.status_code == 403


def test_uso_pessoal_nao_tem_limite(tmp_path, monkeypatch):
    monkeypatch.setattr("gastos.web.rotas.LIMITE_GASTOS", 0)
    cliente = TestClient(criar_app(tmp_path / "gastos.db"))
    assert cliente.post("/gastos", json={"valor": "10", "categoria": "x"}).status_code == 201
    assert cliente.get("/info").json() == {"demo": False}
    assert NOME_COOKIE not in cliente.get("/").cookies


def test_bancos_vencidos_sao_apagados(pasta):
    demo = Demonstracao(pasta)
    velho = demo.banco("a" * 32, HOJE).caminho
    dois_dias_atras = time.time() - 2 * 24 * 3600
    os.utime(velho, (dois_dias_atras, dois_dias_atras))

    demo.banco("b" * 32, HOJE)

    assert not velho.exists()
    assert (pasta / f"{'b' * 32}.db").exists()


def test_quantidade_maxima_de_bancos(pasta):
    demo = Demonstracao(pasta, max_bancos=3)
    for letra in "abcde":
        demo.banco(letra * 32, HOJE)
    assert len(list(pasta.glob("*.db"))) == 3
    assert not list(pasta.glob("*.criando"))


def test_precisa_de_banco_ou_demo(tmp_path):
    with pytest.raises(ValueError):
        criar_app()
    with pytest.raises(ValueError):
        criar_app(tmp_path / "gastos.db", demo=Demonstracao(tmp_path))
