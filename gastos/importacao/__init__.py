"""Importa extratos: CSV do Nubank e OFX de qualquer banco.

ler_extrato recebe os bytes do arquivo e reconhece o formato pelo conteúdo (não pelo
nome, que o usuário pode ter trocado).
"""

import io

from gastos.importacao.comum import (
    CARTAO,
    CONTA,
    Extrato,
    FormatoDesconhecido,
    Ignorado,
    LinhaInvalida,
    adivinhar_categoria,
)
from gastos.importacao.nubank import ler_nubank
from gastos.importacao.ofx import decodificar, ler_ofx, parece_ofx

__all__ = [
    "CARTAO",
    "CONTA",
    "Extrato",
    "FormatoDesconhecido",
    "Ignorado",
    "LinhaInvalida",
    "adivinhar_categoria",
    "ler_extrato",
    "ler_nubank",
    "ler_ofx",
]


def ler_extrato(conteudo: bytes) -> Extrato:
    """Lê o arquivo inteiro com o leitor certo.

    Levanta FormatoDesconhecido, LinhaInvalida ou, se um CSV não estiver em UTF-8,
    UnicodeDecodeError (o OFX aceita também Windows-1252).
    """
    if parece_ofx(conteudo):
        return ler_ofx(decodificar(conteudo))
    texto = conteudo.decode("utf-8-sig")  # aceita com ou sem a marca BOM no começo
    return ler_nubank(io.StringIO(texto, newline=""))
