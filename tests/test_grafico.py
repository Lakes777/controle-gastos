from datetime import date
from decimal import Decimal

import pytest

from gastos.grafico import barra, desenhar, somar_por_categoria, somar_por_mes
from gastos.modelo import Gasto


def gasto(valor, categoria="x", data=date(2026, 9, 1)):
    return Gasto(Decimal(valor), categoria, data=data)


def test_somar_por_categoria_da_maior_para_a_menor():
    gastos = [gasto("10", "lazer"), gasto("50", "mercado"), gasto("15", "lazer")]

    assert somar_por_categoria(gastos) == [
        ("mercado", Decimal("50")),
        ("lazer", Decimal("25")),
    ]


def test_somar_por_categoria_empate_em_ordem_alfabetica():
    gastos = [gasto("10", "uber"), gasto("10", "lanche")]

    assert [categoria for categoria, _ in somar_por_categoria(gastos)] == ["lanche", "uber"]


def test_somar_por_mes_em_ordem_cronologica():
    gastos = [
        gasto("5", data=date(2026, 1, 10)),
        gasto("7", data=date(2025, 12, 31)),
        gasto("3", data=date(2026, 1, 20)),
    ]

    assert somar_por_mes(gastos) == [
        ("dez/2025", Decimal("7")),
        ("jan/2026", Decimal("8")),
    ]


@pytest.mark.parametrize(
    "valor, esperado",
    [
        ("10", "██████████"),  # o maior valor ocupa a largura inteira
        ("5", "█████"),
        ("2.5", "██▌"),  # meio caractere
        ("0.125", "▏"),  # 1/8 de caractere
        ("0.001", "▏"),  # muito pequeno, mas ainda aparece
    ],
)
def test_barra_proporcional_com_precisao_de_um_oitavo(valor, esperado):
    assert barra(Decimal(valor), Decimal("10"), largura=10) == esperado


def test_desenhar_alinha_as_barras_e_mostra_valor_e_porcentagem():
    linhas = desenhar(
        [("lanche", Decimal("30")), ("uber", Decimal("23.59"))], largura=30
    )

    assert linhas[0].startswith("lanche  " + "█" * 30)
    assert linhas[1].startswith("uber    " + "█" * 23 + "▋")
    assert linhas[0].endswith("R$ 30,00   56%")
    assert linhas[1].endswith("R$ 23,59   44%")
    assert linhas[2].startswith("TOTAL") and linhas[2].endswith("R$ 53,59")
    # as colunas de valor ficam alinhadas, então todas as linhas de barra têm o mesmo tamanho
    assert len(linhas[0]) == len(linhas[1])


def test_desenhar_sem_dados_devolve_lista_vazia():
    assert desenhar([]) == []
