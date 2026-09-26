import io
import zipfile
from datetime import date

import pytest
from fastapi.testclient import TestClient

from gastos.web.app import criar_app
from gastos.web.rotas import hoje

HOJE = date(2026, 9, 26)


@pytest.fixture
def cliente(tmp_path):
    app = criar_app(tmp_path / "gastos.db")
    # Finge que hoje é 26/09/2026, para os testes não dependerem do dia em que rodam.
    app.dependency_overrides[hoje] = lambda: HOJE
    return TestClient(app)


def adicionar(cliente, valor="45.90", categoria="mercado", **extras):
    resposta = cliente.post("/gastos", json={"valor": valor, "categoria": categoria, **extras})
    assert resposta.status_code == 201, resposta.text
    return resposta.json()


# ---------- Gastos ----------


def test_adicionar_devolve_o_gasto_com_numero_e_data_de_hoje(cliente):
    gasto = adicionar(cliente, "45.90", " Mercado ", descricao="compras da semana")
    assert gasto == {
        "id": 1,
        "valor": "45.90",
        "categoria": "mercado",
        "descricao": "compras da semana",
        "data": "2026-09-26",
    }


def test_valor_sai_como_texto_exato(cliente):
    # Como número JSON, 0.1 + 0.2 viraria 0.30000000000000004 no JavaScript.
    assert adicionar(cliente, "0.10")["valor"] == "0.10"


@pytest.mark.parametrize("valor", ["0", "-5", "1.999", "abc", "NaN", "Infinity", "45,90"])
def test_adicionar_recusa_valor_invalido(cliente, valor):
    resposta = cliente.post("/gastos", json={"valor": valor, "categoria": "mercado"})
    assert resposta.status_code == 422
    assert cliente.get("/gastos").json() == []


@pytest.mark.parametrize("categoria", ["", "   ", "x" * 41])
def test_adicionar_recusa_categoria_invalida(cliente, categoria):
    resposta = cliente.post("/gastos", json={"valor": "10", "categoria": categoria})
    assert resposta.status_code == 422


def test_adicionar_recusa_data_invalida(cliente):
    resposta = cliente.post(
        "/gastos", json={"valor": "10", "categoria": "mercado", "data": "2026-02-30"}
    )
    assert resposta.status_code == 422


def test_listar_em_ordem_cronologica_e_filtrar_por_mes(cliente):
    adicionar(cliente, "10", data="2026-09-20")
    adicionar(cliente, "20", data="2026-08-31")
    adicionar(cliente, "30", data="2026-09-01")

    assert [g["valor"] for g in cliente.get("/gastos").json()] == ["20", "30", "10"]
    assert [g["valor"] for g in cliente.get("/gastos?mes=2026-09").json()] == ["30", "10"]


@pytest.mark.parametrize("mes", ["2026-9", "2026-13", "setembro"])
def test_filtro_de_mes_invalido(cliente, mes):
    assert cliente.get(f"/gastos?mes={mes}").status_code == 422


def test_editar_muda_so_os_campos_enviados(cliente):
    adicionar(cliente, "45.90", "mercado", descricao="compras", data="2026-09-10")

    resposta = cliente.patch("/gastos/1", json={"categoria": "Lazer", "valor": None})

    assert resposta.status_code == 200
    assert resposta.json() == {
        "id": 1,
        "valor": "45.90",
        "categoria": "lazer",
        "descricao": "compras",
        "data": "2026-09-10",
    }
    assert cliente.get("/gastos/1").json() == resposta.json()


def test_editar_pode_apagar_a_descricao(cliente):
    adicionar(cliente, descricao="compras")
    assert cliente.patch("/gastos/1", json={"descricao": ""}).json()["descricao"] == ""


def test_editar_valida_os_dados(cliente):
    adicionar(cliente)
    assert cliente.patch("/gastos/1", json={"valor": "-1"}).status_code == 422
    assert cliente.get("/gastos/1").json()["valor"] == "45.90"


def test_remover(cliente):
    adicionar(cliente)
    assert cliente.delete("/gastos/1").status_code == 204
    assert cliente.get("/gastos").json() == []


@pytest.mark.parametrize(
    "metodo, json", [("get", None), ("patch", {"valor": "10"}), ("delete", None)]
)
def test_gasto_inexistente_da_404(cliente, metodo, json):
    resposta = cliente.request(metodo, "/gastos/99", json=json)
    assert resposta.status_code == 404
    assert resposta.json()["detail"] == "Nenhum gasto com o número 99"


# ---------- Relatórios ----------


def test_resumo_por_categoria_da_maior_para_a_menor(cliente):
    adicionar(cliente, "30", "transporte")
    adicionar(cliente, "50", "mercado")
    adicionar(cliente, "20", "mercado", data="2026-08-01")

    assert cliente.get("/resumo").json() == {
        "mes": None,
        "total": "100",
        "quantidade": 3,
        "por_categoria": [
            {"categoria": "mercado", "total": "70", "porcentagem": 70},
            {"categoria": "transporte", "total": "30", "porcentagem": 30},
        ],
    }
    assert cliente.get("/resumo?mes=2026-08").json()["total"] == "20"


def test_resumo_sem_gastos(cliente):
    assert cliente.get("/resumo?mes=2026-09").json() == {
        "mes": "2026-09",
        "total": "0",
        "quantidade": 0,
        "por_categoria": [],
    }


def test_meses_e_categorias(cliente):
    adicionar(cliente, categoria="transporte", data="2026-08-15")
    adicionar(cliente, categoria="mercado", data="2026-09-01")
    adicionar(cliente, categoria="mercado", data="2026-09-02")
    cliente.put("/orcamentos/lazer", json={"limite": "100"})

    assert cliente.get("/meses").json() == ["2026-09", "2026-08"]
    assert cliente.get("/categorias").json() == ["lazer", "mercado", "transporte"]


def test_exportar_xlsx_do_mes(cliente):
    adicionar(cliente, "45.90", data="2026-09-10")
    adicionar(cliente, "10", data="2026-08-10")

    resposta = cliente.get("/exportar?formato=xlsx&mes=2026-09")

    assert resposta.status_code == 200
    assert resposta.headers["content-disposition"] == 'attachment; filename="gastos-2026-09.xlsx"'
    with zipfile.ZipFile(io.BytesIO(resposta.content)) as pacote:
        planilha = pacote.read("xl/worksheets/sheet1.xml").decode()
    assert "45.90" in planilha
    assert ">10<" not in planilha


def test_exportar_csv_com_bom_para_o_excel(cliente):
    adicionar(cliente, "45.90", descricao="almoço")

    resposta = cliente.get("/exportar?formato=csv")

    assert resposta.headers["content-disposition"] == 'attachment; filename="gastos.csv"'
    assert resposta.content.startswith("﻿".encode())
    assert "almoço" in resposta.content.decode("utf-8-sig")


def test_exportar_formato_desconhecido(cliente):
    assert cliente.get("/exportar?formato=pdf").status_code == 422


# ---------- Orçamentos ----------


def test_orcamento_do_mes_atual(cliente):
    adicionar(cliente, "90", "mercado")
    adicionar(cliente, "500", "mercado", data="2026-08-01")  # outro mês: não conta

    assert cliente.put("/orcamentos/Mercado", json={"limite": "100"}).json() == {
        "categoria": "mercado",
        "limite": "100",
    }
    assert cliente.get("/orcamentos").json() == [
        {
            "categoria": "mercado",
            "limite": "100",
            "gasto": "90",
            "restante": "10",
            "porcentagem": 90,
            "nivel": "atencao",
            "aviso": "ATENÇÃO: sobram R$ 10,00",
        }
    ]
    assert cliente.get("/orcamentos?mes=2026-08").json()[0]["nivel"] == "estourou"


def test_definir_orcamento_de_novo_troca_o_limite(cliente):
    cliente.put("/orcamentos/mercado", json={"limite": "100"})
    cliente.put("/orcamentos/mercado", json={"limite": "250.50"})
    [situacao] = cliente.get("/orcamentos").json()
    assert situacao["limite"] == "250.50"


def test_orcamento_recusa_limite_invalido(cliente):
    assert cliente.put("/orcamentos/mercado", json={"limite": "0"}).status_code == 422
    assert cliente.put("/orcamentos/%20", json={"limite": "10"}).status_code == 422


def test_remover_orcamento(cliente):
    cliente.put("/orcamentos/mercado", json={"limite": "100"})
    assert cliente.delete("/orcamentos/Mercado").status_code == 204
    assert cliente.get("/orcamentos").json() == []
    assert cliente.delete("/orcamentos/mercado").status_code == 404


# ---------- Recorrentes ----------


def test_recorrente_sem_desde_comeca_na_proxima_vez_que_o_dia_chegar(cliente):
    resposta = cliente.post(
        "/recorrentes", json={"valor": "1200", "categoria": "aluguel", "dia": 5}
    )

    assert resposta.status_code == 201
    assert resposta.json() == {
        "id": 1,
        "valor": "1200",
        "categoria": "aluguel",
        "descricao": "",
        "dia": 5,
        "proxima_data": "2026-10-05",  # o dia 5 de setembro já passou
    }
    assert cliente.get("/gastos").json() == []


def test_recorrente_com_desde_lanca_os_meses_que_passaram(cliente):
    resposta = cliente.post(
        "/recorrentes",
        json={"valor": "55.90", "categoria": "streaming", "dia": 10, "desde": "2026-08"},
    )

    assert resposta.json()["proxima_data"] == "2026-10-10"
    assert [g["data"] for g in cliente.get("/gastos").json()] == ["2026-08-10", "2026-09-10"]


def test_recorrente_e_lancado_quando_o_dia_chega(cliente):
    cliente.post("/recorrentes", json={"valor": "1200", "categoria": "aluguel", "dia": 5})

    cliente.app.dependency_overrides[hoje] = lambda: date(2026, 10, 5)

    [gasto] = cliente.get("/gastos").json()
    assert (gasto["data"], gasto["valor"]) == ("2026-10-05", "1200")
    # Consultar de novo não lança duas vezes.
    assert len(cliente.get("/gastos").json()) == 1


@pytest.mark.parametrize(
    "extras", [{"dia": 0}, {"dia": 32}, {"dia": 5, "desde": "2025-08"}, {"dia": 5, "desde": "2026-8"}]
)
def test_recorrente_recusa_dados_invalidos(cliente, extras):
    resposta = cliente.post("/recorrentes", json={"valor": "10", "categoria": "x", **extras})
    assert resposta.status_code == 422
    assert cliente.get("/recorrentes").json() == []


def test_remover_recorrente_mantem_os_gastos_lancados(cliente):
    cliente.post(
        "/recorrentes", json={"valor": "10", "categoria": "x", "dia": 1, "desde": "2026-09"}
    )

    assert cliente.delete("/recorrentes/1").status_code == 204
    assert cliente.get("/recorrentes").json() == []
    assert len(cliente.get("/gastos").json()) == 1
    assert cliente.delete("/recorrentes/1").status_code == 404


def test_saude(cliente):
    assert cliente.get("/saude").json() == {"status": "ok"}
