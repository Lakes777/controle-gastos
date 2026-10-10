"""Orçamento mensal por categoria: quanto já foi gasto em relação ao limite."""

from collections.abc import Iterable
from dataclasses import dataclass
from decimal import ROUND_HALF_UP, Decimal

from gastos.formatacao import formatar_reais
from gastos.grafico import barra
from gastos.modelo import Gasto

PORCENTAGEM_DE_ATENCAO = 80  # a partir daqui, o programa avisa que o limite está perto

OK, ATENCAO, ESTOUROU = "ok", "atencao", "estourou"


@dataclass(frozen=True)
class Situacao:
    categoria: str
    gasto: Decimal
    limite: Decimal

    @property
    def porcentagem(self) -> Decimal:
        return (self.gasto / self.limite * 100).to_integral_value(ROUND_HALF_UP)

    @property
    def restante(self) -> Decimal:
        return self.limite - self.gasto  # negativo quando estourou

    @property
    def nivel(self) -> str:
        # Compara os valores exatos, não a porcentagem arredondada:
        # R$ 500,01 de R$ 500,00 aparece como 100%, mas já estourou.
        if self.gasto > self.limite:
            return ESTOUROU
        if self.gasto * 100 >= self.limite * PORCENTAGEM_DE_ATENCAO:
            return ATENCAO
        return OK

    def aviso(self) -> str:
        """A situação por extenso (nunca só por símbolo ou cor)."""
        if self.nivel == ESTOUROU:
            return f"ESTOUROU em {formatar_reais(-self.restante)}"
        if self.nivel == ATENCAO:
            return f"ATENÇÃO: sobram {formatar_reais(self.restante)}"
        return f"sobram {formatar_reais(self.restante)}"


def calcular(gastos: Iterable[Gasto], orcamentos: dict[str, Decimal]) -> list[Situacao]:
    """Situação de cada categoria com orçamento, a partir dos gastos de um mês."""
    gastos = list(gastos)
    return [
        Situacao(
            categoria,
            sum((g.valor for g in gastos if g.categoria == categoria), Decimal("0")),
            limite,
        )
        for categoria, limite in sorted(orcamentos.items())
    ]


def somar(situacoes: Iterable[Situacao]) -> Situacao | None:
    """Todas as categorias com orçamento juntas (None se não há nenhuma).

    O nível do total pode ser ok mesmo com uma categoria estourada: por isso quem mostra
    o total deve mostrar também quantas estouraram (estouradas()).
    """
    situacoes = list(situacoes)
    if not situacoes:
        return None
    return Situacao(
        "todas",
        sum((s.gasto for s in situacoes), Decimal("0")),
        sum((s.limite for s in situacoes), Decimal("0")),
    )


def estouradas(situacoes: Iterable[Situacao]) -> list[str]:
    """As categorias que passaram do limite, em ordem alfabética."""
    return sorted(s.categoria for s in situacoes if s.nivel == ESTOUROU)


def nivel_do_total(total: Situacao, situacoes: Iterable[Situacao]) -> str:
    """O nível do total, mas nunca ok com uma categoria estourada: aí vira atenção."""
    if total.nivel == OK and estouradas(situacoes):
        return ATENCAO
    return total.nivel


def medidor(situacao: Situacao, largura: int = 10) -> str:
    """Barra de 0 a 100% do limite, com trilho ░ no que ainda falta."""
    if situacao.gasto == 0:
        return "░" * largura
    cheio = barra(min(situacao.gasto, situacao.limite), situacao.limite, largura)
    return cheio + "░" * (largura - len(cheio))


def desenhar(situacoes: list[Situacao]) -> list[str]:
    """Uma linha por categoria: gasto, limite, porcentagem, medidor e aviso."""
    if not situacoes:
        return []
    largura_rotulo = max(len(s.categoria) for s in situacoes)
    return [
        f"{s.categoria:<{largura_rotulo}}  {formatar_reais(s.gasto):>13} de "
        f"{formatar_reais(s.limite):<13} {s.porcentagem:>4}%  {medidor(s)}  {s.aviso()}"
        for s in situacoes
    ]
