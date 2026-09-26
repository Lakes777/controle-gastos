from datetime import date
from decimal import Decimal

import pytest

from gastos.modelo import Gasto
from gastos.orcamento import ATENCAO, ESTOUROU, OK, Situacao, calcular, desenhar, medidor


def situacao(gasto, limite="500"):
    return Situacao("mercado", Decimal(gasto), Decimal(limite))


@pytest.mark.parametrize(
    "gasto, nivel",
    [
        ("0", OK),
        ("399.99", OK),  # 79,99%: ainda não avisa
        ("400", ATENCAO),  # exatamente 80%
        ("500", ATENCAO),  # exatamente no limite: ainda não estourou
        ("500.01", ESTOUROU),  # um centavo acima
    ],
)
def test_nivel_nas_fronteiras(gasto, nivel):
    assert situacao(gasto).nivel == nivel


def test_um_centavo_acima_aparece_como_100_por_cento_mas_estourou():
    s = situacao("500.01")

    assert s.porcentagem == 100
    assert s.nivel == ESTOUROU
    assert s.aviso() == "ESTOUROU em R$ 0,01"


def test_avisos_por_extenso():
    assert situacao("100").aviso() == "sobram R$ 400,00"
    assert situacao("420").aviso() == "ATENÇÃO: sobram R$ 80,00"
    assert situacao("595").aviso() == "ESTOUROU em R$ 95,00"


@pytest.mark.parametrize(
    "gasto, esperado",
    [
        ("0", "░░░░░░░░░░"),
        ("250", "█████░░░░░"),
        ("420", "████████▍░"),
        ("500", "██████████"),
        ("900", "██████████"),  # passou do limite: a barra para no 100%
    ],
)
def test_medidor(gasto, esperado):
    assert medidor(situacao(gasto)) == esperado


def test_calcular_soma_so_a_categoria_e_inclui_categoria_sem_gastos():
    gastos = [
        Gasto(Decimal("300"), "mercado", data=date(2026, 9, 1)),
        Gasto(Decimal("120"), "mercado", data=date(2026, 9, 9)),
        Gasto(Decimal("999"), "aluguel", data=date(2026, 9, 5)),  # sem orçamento: fica de fora
    ]
    orcamentos = {"mercado": Decimal("500"), "lazer": Decimal("80")}

    assert calcular(gastos, orcamentos) == [
        Situacao("lazer", Decimal("0"), Decimal("80")),
        Situacao("mercado", Decimal("420"), Decimal("500")),
    ]


def test_desenhar_alinha_as_categorias():
    linhas = desenhar([situacao("420"), Situacao("uber", Decimal("10"), Decimal("50"))])

    assert linhas[0].startswith("mercado  ")
    assert linhas[1].startswith("uber     ")
    assert "84%" in linhas[0] and "ATENÇÃO" in linhas[0]
    assert desenhar([]) == []
