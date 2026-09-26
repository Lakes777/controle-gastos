"""Exporta os gastos para CSV, no formato que o Excel em português entende."""

import csv
from collections.abc import Iterable
from typing import TextIO

from gastos.modelo import Gasto

CABECALHO = ["numero", "data", "valor", "categoria", "descricao"]

# Texto que começa com estes caracteres vira fórmula no Excel ("CSV injection").
INICIO_DE_FORMULA = ("=", "+", "-", "@", "\t", "\r")


def texto_seguro(texto: str) -> str:
    """Põe um ' na frente de texto que o Excel executaria como fórmula."""
    return "'" + texto if texto.startswith(INICIO_DE_FORMULA) else texto


def escrever_csv(gastos: Iterable[Gasto], arquivo: TextIO) -> int:
    """Escreve os gastos no arquivo já aberto e devolve quantos foram escritos.

    Usa ; para separar as colunas e vírgula nos centavos, como o Excel
    em português espera. O módulo csv cuida de descrições com ; ou aspas.
    """
    escritor = csv.writer(arquivo, delimiter=";")
    escritor.writerow(CABECALHO)
    quantidade = 0
    for gasto in gastos:
        escritor.writerow(
            [
                gasto.id,
                f"{gasto.data:%d/%m/%Y}",
                f"{gasto.valor:.2f}".replace(".", ","),
                texto_seguro(gasto.categoria),
                texto_seguro(gasto.descricao),
            ]
        )
        quantidade += 1
    return quantidade
