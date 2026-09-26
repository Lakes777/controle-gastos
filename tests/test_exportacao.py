import csv
import io
from datetime import date
from decimal import Decimal

import pytest

from gastos.exportacao import escrever_csv, texto_seguro
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
