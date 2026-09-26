"""Formatação de valores para mostrar ao usuário."""

from decimal import Decimal


def formatar_reais(valor: Decimal) -> str:
    """Formata 1234.5 como 'R$ 1.234,50'."""
    texto = f"{valor:,.2f}"
    texto = texto.replace(",", "_").replace(".", ",").replace("_", ".")
    return f"R$ {texto}"


MESES = ["jan", "fev", "mar", "abr", "mai", "jun", "jul", "ago", "set", "out", "nov", "dez"]


def nome_do_mes(ano: int, mes: int) -> str:
    """Formata o mês 9 de 2026 como 'set/2026'."""
    return f"{MESES[mes - 1]}/{ano}"
