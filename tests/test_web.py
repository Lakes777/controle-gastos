import re
import io
import zipfile
from datetime import date

import pytest
from fastapi.testclient import TestClient

from gastos.web.app import criar_app
from gastos.web.rotas import hoje
from tests.test_ofx import FATURA_ITAU

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


def test_pagina_inicial_e_arquivos_do_front(cliente):
    pagina = cliente.get("/")
    assert pagina.status_code == 200
    assert "Spendwise" in pagina.text
    for arquivo in ["app.js", "estilo.css"]:
        assert cliente.get(f"/static/{arquivo}").status_code == 200


def test_pagina_marca_o_javascript_antes_do_app_js(cliente):
    # A marca "js" precisa entrar antes do app.js (que vem com defer): é ela que esconde
    # as seções até as abas ficarem prontas, em vez de piscarem numa conexão lenta.
    pagina = cliente.get("/").text
    cabecalho = pagina.split("</head>")[0]
    assert 'document.documentElement.classList.add("js")' in cabecalho
    assert cabecalho.index('classList.add("js")') < cabecalho.index("/static/app.js")
    # E o CSS sabe esconder (com prazo para mostrar, caso o app.js nunca chegue).
    css = cliente.get("/static/estilo.css").text
    assert ".js:not(.com-abas) main > .aba" in css
    assert "@keyframes mostrar-sem-abas" in css


# ---------- Lobby (tela de entrada) ----------

PRANCHAS = ["barras", "rosca", "recibo", "moedas", "cartao", "calendario"]


def test_lobby_abre_na_raiz_sem_login(cliente):
    pagina = cliente.get("/")
    assert pagina.status_code == 200
    html = pagina.text
    assert 'id="lobby"' in html
    # O botão principal leva às abas, e o código fica a um clique
    assert 'href="#resumo" id="lobby-comecar"' in html
    # "Entrar na minha conta" só aparece pelo JavaScript, na versão online sem login
    assert re.search(r'<button[^>]*id="lobby-entrar"[^>]*\bhidden\b', html)
    assert "https://github.com/Lakes777/spendwise" in html
    # O nome no topo do app volta para o lobby
    assert 'id="link-lobby" href="/"' in html or 'href="/" id="link-lobby"' in html


def test_lobby_tem_um_h1_e_o_topo_com_menu_fica(cliente):
    html = cliente.get("/").text
    # Um h1 só: o nome grande do lobby. O nome no topo é título de nível 1 só nas abas
    # (o app.js tira o role="heading" dele no lobby).
    assert html.count("<h1") == 1
    assert 'id="topo-nome" role="heading" aria-level="1"' in html
    # O menu começa com Início, que leva ao lobby (endereço sem hash)
    menu = html.split('class="abas__lista"')[1].split("</ul>")[0]
    links = re.findall(r'href="([^"]+)"', menu)
    assert links == ["/", "#resumo", "#gastos", "#orcamento", "#recorrentes", "#importar"]
    css = cliente.get("/static/estilo.css").text
    # No lobby somem as abas, mas o topo (com o menu) continua
    assert ".em-lobby main" in css and ".em-lobby .topo" not in css
    # A marca do lobby entra no <head>, antes de a página aparecer (sem piscar as abas)
    cabecalho = html.split("</head>")[0]
    assert 'classList.add("em-lobby")' in cabecalho


@pytest.mark.parametrize("nome", PRANCHAS)
def test_pranchas_do_fundo_sao_servidas(cliente, nome):
    resposta = cliente.get(f"/static/pranchas/{nome}.svg")
    assert resposta.status_code == 200
    assert resposta.headers["content-type"].startswith("image/svg+xml")
    svg = resposta.text
    assert 'viewBox="0 0 520 300"' in svg
    # Desenho de traço, leve: nada de imagem embutida nem script
    assert "<image" not in svg and "<script" not in svg
    assert len(svg.encode()) < 12_000


def test_o_app_js_conhece_todas_as_pranchas(cliente):
    js = cliente.get("/static/app.js").text
    for nome in PRANCHAS:
        assert f'"{nome}"' in js


def test_faixas_do_lobby_param_com_menos_movimento(cliente):
    css = cliente.get("/static/estilo.css").text
    assert "@keyframes deslizar" in css
    assert "translate3d(-50%, 0, 0)" in css
    menos_movimento = css.split("@media (prefers-reduced-motion: reduce)")[1]
    assert "animation: none !important" in menos_movimento


# ---------- Importação do Nubank ----------

FATURA = """date,title,amount
2026-09-05,Uber *Trip,23.59
2026-09-05,Uber *Trip,23.59
2026-09-06,Pagamento recebido,-500.00
2026-09-07,Netflix.com,"55,90"
"""

EXTRATO_CONTA = """Data,Valor,Identificador,Descrição
01/09/2026,-45.90,id-1,Compra no débito - SUPERMERCADO CONDOR
02/09/2026,2500.00,id-2,Transferência recebida pelo Pix - EMPRESA
05/09/2026,-1200.00,id-3,Pagamento de fatura
"""


def previa(cliente, texto):
    return cliente.post("/importar/previa", content=texto.encode(), headers={"Content-Type": "text/csv"})


def test_previa_da_fatura_nao_salva_nada(cliente):
    resposta = previa(cliente, FATURA)

    assert resposta.status_code == 200
    dados = resposta.json()
    assert dados["formato"] == "fatura do cartão do Nubank (CSV)"
    assert [(n["data"], n["valor"], n["categoria"]) for n in dados["novos"]] == [
        ("2026-09-05", "23.59", "transporte"),
        ("2026-09-05", "23.59", "transporte"),  # duas corridas iguais no mesmo dia são duas
        ("2026-09-07", "55.90", "assinaturas"),
    ]
    assert dados["repetidos"] == 0
    assert [(i["valor"], i["motivo"]) for i in dados["ignorados"]] == [("-500.00", "pagamento ou estorno")]
    assert cliente.get("/gastos").json() == []


def test_previa_do_extrato_da_conta(cliente):
    dados = previa(cliente, EXTRATO_CONTA).json()
    assert dados["formato"] == "extrato da conta do Nubank (CSV)"
    assert [n["descricao"] for n in dados["novos"]] == ["Compra no débito - SUPERMERCADO CONDOR"]
    assert len(dados["ignorados"]) == 2


def test_importar_com_categoria_corrigida_e_sem_repetir(cliente):
    novos = previa(cliente, FATURA).json()["novos"]
    novos[2]["categoria"] = "Lazer"  # o usuário corrigiu na prévia

    assert cliente.post("/importar", json={"itens": novos}).json() == {"importados": 3, "repetidos": 0}
    assert [g["categoria"] for g in cliente.get("/gastos").json()] == ["transporte", "transporte", "lazer"]

    # O mesmo arquivo de novo: a prévia já mostra que tudo foi importado.
    dados = previa(cliente, FATURA).json()
    assert (dados["novos"], dados["repetidos"]) == ([], 3)

    # E mesmo que a página mande de novo, nada se repete.
    assert cliente.post("/importar", json={"itens": novos}).json() == {"importados": 0, "repetidos": 3}
    assert len(cliente.get("/gastos").json()) == 3

    # Um mês depois, a Netflix já vem com a categoria que o usuário escolheu; a loja nova, não.
    outubro = "date,title,amount\n2026-10-07,Netflix.com,55.90\n2026-10-08,Loja Nova,9.00\n"
    novos = previa(cliente, outubro).json()["novos"]
    assert [(n["categoria"], n["lembrada"]) for n in novos] == [("lazer", True), ("outros", False)]

    # O "lembrada" volta no pedido (a página manda o item inteiro) e não muda o que é salvo.
    assert cliente.post("/importar", json={"itens": novos}).json() == {"importados": 2, "repetidos": 0}
    assert [g["categoria"] for g in cliente.get("/gastos").json()][-2:] == ["lazer", "outros"]


def test_importar_valida_os_itens(cliente):
    item = {"origem": "x", "valor": "-5", "categoria": "x", "data": "2026-09-01"}
    assert cliente.post("/importar", json={"itens": [item]}).status_code == 422
    assert cliente.post("/importar", json={"itens": [{**item, "valor": "5", "origem": ""}]}).status_code == 422
    assert cliente.get("/gastos").json() == []


@pytest.mark.parametrize(
    "conteudo, trecho",
    [
        (b"nome,idade\nana,30\n", "não é um OFX nem um CSV do Nubank"),
        ("date,title,amount\n2026-09-01,Uber,abc\n".encode(), "linha 2"),
        ("date,title,amount\n2026-09-01,Café,5\n".encode("latin-1"), "UTF-8"),
    ],
)
def test_previa_recusa_arquivo_invalido(cliente, conteudo, trecho):
    resposta = cliente.post("/importar/previa", content=conteudo)
    assert resposta.status_code == 422
    assert trecho in resposta.json()["detail"]


def test_previa_recusa_arquivo_grande(cliente, monkeypatch):
    monkeypatch.setattr("gastos.web.rotas.TAMANHO_MAXIMO_ARQUIVO", 10)
    assert previa(cliente, FATURA).status_code == 413


def test_csv_com_bom_do_excel(cliente):
    resposta = cliente.post("/importar/previa", content=FATURA.encode("utf-8-sig"))
    assert len(resposta.json()["novos"]) == 3


def test_csv_de_exemplo_importa_certinho(cliente):
    exemplo = cliente.get("/importar/exemplo.csv")
    assert exemplo.headers["content-disposition"] == 'attachment; filename="Nubank_exemplo.csv"'

    dados = previa(cliente, exemplo.text).json()

    assert len(dados["novos"]) == 8 and len(dados["ignorados"]) == 2
    assert max(n["data"] for n in dados["novos"]) == "2026-09-25"  # datas relativas a hoje
    assert {n["categoria"] for n in dados["novos"]} >= {"mercado", "transporte", "assinaturas"}


def test_importar_ofx_pela_pagina(cliente):
    def previa():
        return cliente.post(
            "/importar/previa",
            content=FATURA_ITAU.encode(),
            headers={"Content-Type": "application/octet-stream"},
        ).json()

    dados = previa()
    assert dados["formato"] == "fatura do cartão do Itaú (OFX)"
    assert [(n["valor"], n["categoria"]) for n in dados["novos"]] == [
        ("23.59", "transporte"),
        ("55.90", "assinaturas"),
    ]
    resultado = cliente.post("/importar", json={"itens": dados["novos"]}).json()
    assert resultado == {"importados": 2, "repetidos": 0}
    assert (previa()["novos"], previa()["repetidos"]) == ([], 2)


def test_meus_nomes_pela_api(cliente):
    assert cliente.get("/importar/meus-nomes").json() == []

    resposta = cliente.post("/importar/meus-nomes", json={"nome": " Ana   Lima "})
    assert (resposta.status_code, resposta.json()) == (201, ["Ana Lima"])
    assert cliente.post("/importar/meus-nomes", json={"nome": "ANA LIMA"}).status_code == 409

    sem_sobrenome = cliente.post("/importar/meus-nomes", json={"nome": "Ana"})
    assert sem_sobrenome.status_code == 422
    assert sem_sobrenome.json()["detail"].startswith("Informe nome e sobrenome")

    assert cliente.delete("/importar/meus-nomes/ana%20lima").status_code == 204
    assert cliente.delete("/importar/meus-nomes/Ana%20Lima").status_code == 404
    assert cliente.get("/importar/meus-nomes").json() == []


def test_meus_nomes_tem_limite(cliente, monkeypatch):
    monkeypatch.setattr("gastos.web.rotas.MAXIMO_DE_NOMES", 1)
    assert cliente.post("/importar/meus-nomes", json={"nome": "Ana Lima"}).status_code == 201
    assert cliente.post("/importar/meus-nomes", json={"nome": "Ana Souza"}).status_code == 403


def test_previa_ignora_pix_para_o_proprio_nome(cliente):
    extrato = """Data,Valor,Identificador,Descrição
01/09/2026,-50.00,a1,Transferência enviada pelo Pix - ANA LIMA - •••.1-•• - BANCO INTER (0077) Agência: 1 Conta: 2-3
02/09/2026,-20.00,a2,Transferência enviada pelo Pix - JOANA REIS
"""
    assert len(previa(cliente, extrato).json()["novos"]) == 2

    cliente.post("/importar/meus-nomes", json={"nome": "Ana Lima"})
    dados = previa(cliente, extrato).json()
    assert [n["descricao"] for n in dados["novos"]] == ["Pix enviado - JOANA REIS"]
    assert dados["ignorados"][0]["motivo"] == "transferência para uma conta sua"


def test_previa_do_csv_do_inter_pede_o_ofx(cliente):
    resposta = previa(cliente, " Extrato Conta Corrente \nConta ;1\n")
    assert resposta.status_code == 422
    assert "Baixe o mesmo extrato em OFX" in resposta.json()["detail"]
