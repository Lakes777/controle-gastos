"""Importa extratos: CSV do Nubank e OFX de qualquer banco.

ler_extrato recebe os bytes do arquivo e reconhece o formato pelo conteúdo (não pelo
nome, que o usuário pode ter trocado).
"""

import io
from collections.abc import Sequence

from gastos.importacao.comum import (
    CARTAO,
    CONTA,
    Extrato,
    FormatoDesconhecido,
    Ignorado,
    LinhaInvalida,
    MAXIMO_DE_NOMES,
    adivinhar_categoria,
    tirar_transferencias_para_voce,
    validar_meu_nome,
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
    "MAXIMO_DE_NOMES",
    "adivinhar_categoria",
    "ler_extrato",
    "ler_nubank",
    "ler_ofx",
    "validar_meu_nome",
]


def ler_extrato(conteudo: bytes, meus_nomes: Sequence[str] = ()) -> Extrato:
    """Lê o arquivo inteiro com o leitor certo.

    O que foi enviado para um dos meus_nomes (outra conta do usuário) vai para os ignorados.
    Levanta FormatoDesconhecido, LinhaInvalida ou, se um CSV não estiver em UTF-8,
    UnicodeDecodeError (o OFX aceita também Windows-1252).
    """
    if parece_ofx(conteudo):
        extrato = ler_ofx(decodificar(conteudo))
    else:
        texto = conteudo.decode("utf-8-sig")  # aceita com ou sem a marca BOM no começo
        if texto.lstrip().startswith("Extrato Conta Corrente"):
            # O CSV do Inter não tem identificador por transação; o OFX dele tem.
            raise FormatoDesconhecido(
                "Este é o CSV do Inter. Baixe o mesmo extrato em OFX: ele traz um "
                "identificador por transação, que evita importar o mesmo gasto duas vezes."
            )
        extrato = ler_nubank(io.StringIO(texto, newline=""))
    tirar_transferencias_para_voce(extrato, meus_nomes)
    return extrato
