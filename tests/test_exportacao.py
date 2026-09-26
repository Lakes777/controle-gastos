import csv
import io
import zipfile
from datetime import date
from decimal import Decimal
from xml.etree import ElementTree

import pytest

from gastos.exportacao import escrever_csv, escrever_xlsx, texto_seguro
from gastos.modelo import Gasto


def exportar(gastos):
    """Escreve num arquivo de mentira (na memória) e devolve o texto."""
    arquivo = io.StringIO(newline="")
    escrever_csv(gastos, arquivo)
    return arquivo.getvalue()


def test_formato_brasileiro_com_ponto_e_virgula():
    texto = exportar([Gasto(Decimal("1250.5"), "aluguel", "setembro", date(2026, 9, 5), id=3)])

    assert texto.splitlines() == [
        "numero;data;valor;categoria;descricao",
        "3;05/09/2026;1250,50;aluguel;setembro",
    ]


def test_devolve_quantos_gastos_escreveu():
    gastos = [Gasto(Decimal("1"), "a", id=1), Gasto(Decimal("2"), "b", id=2)]

    assert escrever_csv(gastos, io.StringIO()) == 2
    assert escrever_csv([], io.StringIO()) == 0


def test_descricao_com_ponto_e_virgula_e_aspas_nao_quebra_as_colunas():
    descricao = 'pizza; refri e "sobremesa"'
    texto = exportar([Gasto(Decimal("80"), "lazer", descricao, date(2026, 9, 1), id=1)])

    linhas = list(csv.reader(io.StringIO(texto), delimiter=";"))

    assert len(linhas[1]) == 5
    assert linhas[1][4] == descricao


@pytest.mark.parametrize("perigoso", ["=1+1", "+5", "-3", "@SOMA(A1)", "=HYPERLINK(\"x\")"])
def test_texto_que_viraria_formula_ganha_apostrofo(perigoso):
    assert texto_seguro(perigoso) == "'" + perigoso


def test_texto_normal_fica_igual():
    assert texto_seguro("almoço com a equipe") == "almoço com a equipe"
    assert texto_seguro("") == ""


def test_descricao_perigosa_sai_protegida_no_csv():
    texto = exportar([Gasto(Decimal("1"), "golpe", "=1+1", date(2026, 9, 1), id=1)])

    assert texto.splitlines()[1].endswith(";'=1+1")


# --- Planilha do Excel (.xlsx) ---

NS = {"x": "http://schemas.openxmlformats.org/spreadsheetml/2006/main"}


def exportar_xlsx(gastos):
    """Gera o .xlsx na memória e devolve as linhas da planilha (elementos XML)."""
    arquivo = io.BytesIO()
    escrever_xlsx(gastos, arquivo)
    with zipfile.ZipFile(arquivo) as pacote:
        assert pacote.testzip() is None  # nenhum arquivo corrompido dentro do .zip
        for nome in pacote.namelist():
            ElementTree.fromstring(pacote.read(nome))  # todo XML precisa ser válido
        planilha = ElementTree.fromstring(pacote.read("xl/worksheets/sheet1.xml"))
    return planilha.findall("x:sheetData/x:row", NS)


def celulas(linha):
    """Devolve {"A": elemento, "B": ...} de uma linha, pela letra da coluna."""
    return {c.get("r").rstrip("0123456789"): c for c in linha.findall("x:c", NS)}


def texto(celula):
    return celula.find("x:is/x:t", NS).text or ""


def test_xlsx_guarda_valor_como_numero_e_data_como_data():
    linhas = exportar_xlsx(
        [Gasto(Decimal("30"), "lanche", "almoço", date(2026, 9, 23), id=1)]
    )

    gasto = celulas(linhas[1])
    assert gasto["A"].find("x:v", NS).text == "1"
    assert gasto["B"].find("x:v", NS).text == "46288"  # 23/09/2026 contado em dias pelo Excel
    assert gasto["C"].find("x:v", NS).text == "30"
    assert gasto["C"].get("t") is None  # sem t="...": é número, não texto
    assert texto(gasto["D"]) == "lanche"
    assert texto(gasto["E"]) == "almoço"


def test_xlsx_tem_titulos_e_linha_de_total_com_formula():
    linhas = exportar_xlsx(
        [
            Gasto(Decimal("30"), "lanche", data=date(2026, 9, 23), id=1),
            Gasto(Decimal("23.59"), "uber", data=date(2026, 9, 23), id=2),
        ]
    )

    assert [texto(c) for c in celulas(linhas[0]).values()] == [
        "Nº", "Data", "Valor", "Categoria", "Descrição"
    ]
    total = celulas(linhas[3])
    assert texto(total["B"]) == "TOTAL"
    assert total["C"].find("x:f", NS).text == "SUM(C2:C3)"
    assert total["C"].find("x:v", NS).text == "53.59"


def test_xlsx_sem_gastos_tem_so_os_titulos():
    assert len(exportar_xlsx([])) == 1


def test_xlsx_escapa_caracteres_especiais_do_xml():
    descricao = 'pizza <grande> & "refri"\x01'  # \x01 é proibido no XML

    linhas = exportar_xlsx([Gasto(Decimal("80"), "lazer", descricao, date(2026, 9, 1), id=1)])

    assert texto(celulas(linhas[1])["E"]) == 'pizza <grande> & "refri"'


def test_xlsx_devolve_quantos_gastos_escreveu():
    gastos = [Gasto(Decimal("1"), "a", id=1), Gasto(Decimal("2"), "b", id=2)]

    assert escrever_xlsx(gastos, io.BytesIO()) == 2
