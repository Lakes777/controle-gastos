"""Formatação de valores para mostrar ao usuário."""

from decimal import Decimal


def formatar_reais(valor: Decimal) -> str:
    """Formata 1234.5 como 'R$ 1.234,50'."""
    texto = f"{valor:,.2f}"
    texto = texto.replace(",", "_").replace(".", ",").replace("_", ".")
    return f"R$ {texto}"
