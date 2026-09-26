"""Gráfico de barras no terminal, desenhado com caracteres Unicode."""

from collections import defaultdict
from collections.abc import Iterable
from decimal import ROUND_HALF_UP, Decimal

from gastos.formatacao import formatar_reais, nome_do_mes
from gastos.modelo import Gasto

# Blocos de 1/8 a 8/8 de largura: a barra fica com precisão de 1/8 de caractere.
BLOCOS = " ▏▎▍▌▋▊▉█"

def somar_por_categoria(gastos: Iterable[Gasto]) -> list[tuple[str, Decimal]]:
    """Total de cada categoria, da maior para a menor (empate: ordem alfabética)."""
    totais: dict[str, Decimal] = defaultdict(Decimal)
    for gasto in gastos:
        totais[gasto.categoria] += gasto.valor
    return sorted(totais.items(), key=lambda item: (-item[1], item[0]))


def somar_por_mes(gastos: Iterable[Gasto]) -> list[tuple[str, Decimal]]:
    """Total de cada mês, em ordem cronológica, com rótulos como 'set/2026'."""
    totais: dict[tuple[int, int], Decimal] = defaultdict(Decimal)
    for gasto in gastos:
        totais[(gasto.data.year, gasto.data.month)] += gasto.valor
    return [(nome_do_mes(ano, mes), total) for (ano, mes), total in sorted(totais.items())]


def barra(valor: Decimal, maximo: Decimal, largura: int) -> str:
    """Barra proporcional a valor/maximo; o maior valor ocupa a largura inteira."""
    oitavos = int((valor / maximo * largura * 8).to_integral_value(ROUND_HALF_UP))
    oitavos = max(oitavos, 1)  # um gasto pequeno ainda aparece, com pelo menos ▏
    cheios, resto = divmod(oitavos, 8)
    return BLOCOS[8] * cheios + (BLOCOS[resto] if resto else "")


def desenhar(totais: list[tuple[str, Decimal]], largura: int = 30) -> list[str]:
    """Monta as linhas do gráfico: rótulo, barra, valor e porcentagem do total."""
    if not totais:
        return []
    maximo = max(total for _, total in totais)
    soma = sum(total for _, total in totais)
    largura_rotulo = max(len(rotulo) for rotulo, _ in totais)
    linhas = []
    for rotulo, total in totais:
        porcentagem = (total / soma * 100).to_integral_value(ROUND_HALF_UP)
        linhas.append(
            f"{rotulo:<{largura_rotulo}}  {barra(total, maximo, largura):<{largura}}  "
            f"{formatar_reais(total):>13}  {porcentagem:>3}%"
        )
    linhas.append(
        f"{'TOTAL':<{largura_rotulo}}  {'':<{largura}}  {formatar_reais(soma):>13}"
    )
    return linhas
