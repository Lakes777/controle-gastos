from datetime import date
from decimal import Decimal

import pytest

from gastos.recorrentes import (
    Recorrente,
    data_no_mes,
    datas_pendentes,
    mes_seguinte,
    meses_entre,
    primeiro_mes,
)


@pytest.mark.parametrize(
    "mes, dia, esperado",
    [
        ("2026-09", 5, date(2026, 9, 5)),
        ("2026-04", 31, date(2026, 4, 30)),  # abril tem 30 dias
        ("2026-02", 31, date(2026, 2, 28)),
        ("2028-02", 30, date(2028, 2, 29)),  # 2028 é bissexto
        ("2026-12", 31, date(2026, 12, 31)),
    ],
)
def test_data_no_mes_usa_o_ultimo_dia_em_mes_curto(mes, dia, esperado):
    assert data_no_mes(mes, dia) == esperado


@pytest.mark.parametrize(
    "mes, esperado", [("2026-09", "2026-10"), ("2026-12", "2027-01"), ("2026-01", "2026-02")]
)
def test_mes_seguinte_vira_o_ano(mes, esperado):
    assert mes_seguinte(mes) == esperado


def test_meses_entre():
    assert meses_entre("2026-01", "2026-03") == 2
    assert meses_entre("2025-10", "2026-09") == 11
    assert meses_entre("2026-09", "2026-09") == 0


@pytest.mark.parametrize(
    "dia, hoje, esperado",
    [
        (5, date(2026, 9, 26), "2026-10"),  # dia 5 já passou: começa no mês que vem
        (26, date(2026, 9, 26), "2026-09"),  # é hoje: entra neste mês
        (30, date(2026, 9, 26), "2026-09"),  # ainda vai chegar
        (5, date(2026, 12, 20), "2027-01"),  # virada do ano
        (31, date(2026, 9, 30), "2026-09"),  # dia 31 em setembro é o dia 30, que é hoje
    ],
)
def test_primeiro_mes_nunca_lanca_para_tras(dia, hoje, esperado):
    assert primeiro_mes(dia, hoje) == esperado


def aluguel(proximo_mes, dia=5):
    return Recorrente(Decimal("1200"), "aluguel", dia, proximo_mes)


def test_nada_pendente_antes_do_dia():
    assert datas_pendentes(aluguel("2026-10"), date(2026, 10, 4)) == []


def test_pendente_no_proprio_dia():
    assert datas_pendentes(aluguel("2026-10"), date(2026, 10, 5)) == [date(2026, 10, 5)]


def test_meses_sem_abrir_o_programa_sao_todos_lancados():
    datas = datas_pendentes(aluguel("2026-11"), date(2027, 2, 10))

    assert datas == [date(2026, 11, 5), date(2026, 12, 5), date(2027, 1, 5), date(2027, 2, 5)]


def test_proxima_data():
    assert aluguel("2026-02", dia=31).proxima_data == date(2026, 2, 28)
