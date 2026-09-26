"""Gastos recorrentes: os que se repetem todo mês, como aluguel e assinaturas.

Aqui ficam só as regras de datas; quem grava no banco é o armazenamento.
"""

import calendar
from dataclasses import dataclass
from datetime import date
from decimal import Decimal

MESES_PARA_TRAS = 12  # --desde pode voltar no máximo isso (evita lançar anos por engano)


@dataclass
class Recorrente:
    valor: Decimal
    categoria: str
    dia: int  # dia do mês em que o gasto acontece (1 a 31)
    proximo_mes: str  # AAAA-MM do próximo lançamento que ainda falta fazer
    descricao: str = ""
    id: int | None = None

    @property
    def proxima_data(self) -> date:
        return data_no_mes(self.proximo_mes, self.dia)


def data_no_mes(mes: str, dia: int) -> date:
    """Data do dia no mês AAAA-MM; em mês curto, usa o último dia (31 em abril vira 30)."""
    ano, numero = int(mes[:4]), int(mes[5:])
    ultimo_dia = calendar.monthrange(ano, numero)[1]
    return date(ano, numero, min(dia, ultimo_dia))


def mes_seguinte(mes: str) -> str:
    ano, numero = int(mes[:4]), int(mes[5:])
    return f"{ano + 1}-01" if numero == 12 else f"{ano}-{numero + 1:02d}"


def meses_entre(inicio: str, fim: str) -> int:
    """Quantos meses de inicio até fim (2026-01 a 2026-03 dá 2)."""
    return (int(fim[:4]) - int(inicio[:4])) * 12 + int(fim[5:]) - int(inicio[5:])


def primeiro_mes(dia: int, hoje: date) -> str:
    """Mês do primeiro lançamento quando o usuário não diz --desde.

    Nunca lança para trás sem pedir: se o dia deste mês já passou, começa no mês
    que vem (o gasto deste mês provavelmente já foi registrado à mão).
    """
    este_mes = f"{hoje:%Y-%m}"
    if data_no_mes(este_mes, dia) >= hoje:
        return este_mes
    return mes_seguinte(este_mes)


def datas_pendentes(recorrente: Recorrente, hoje: date) -> list[date]:
    """Todas as datas que já chegaram e ainda não foram lançadas, em ordem."""
    datas = []
    mes = recorrente.proximo_mes
    while (data := data_no_mes(mes, recorrente.dia)) <= hoje:
        datas.append(data)
        mes = mes_seguinte(mes)
    return datas
