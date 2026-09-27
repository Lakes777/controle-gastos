"""Lê o extrato em CSV do Nubank (fatura do cartão ou extrato da conta).

O formato é reconhecido pelo cabeçalho:
- fatura do cartão:  date,title,amount           (2026-09-05; gasto é positivo;
                     o valor pode vir como "41,80" e o negativo como "- 84,00")
- extrato da conta:  Data,Valor,Identificador,Descrição   (05/09/2026; gasto é negativo)

Os dois formatos foram conferidos com arquivos reais.
"""

import csv
from collections import Counter
from datetime import date, datetime
from decimal import Decimal
from typing import TextIO

from gastos.importacao.comum import (
    CARTAO,
    CONTA,
    Extrato,
    FormatoDesconhecido,
    Ignorado,
    LinhaInvalida,
    adivinhar_categoria,
    ler_valor,
    limpar_descricao,
    separar_conta,
)
from gastos.modelo import Gasto


def _ler_linha_cartao(linha: dict, extrato: Extrato, repeticoes: Counter) -> None:
    data = date.fromisoformat(linha["date"].strip())
    descricao = linha["title"].strip()
    valor = ler_valor(linha["amount"])
    if valor <= 0:
        extrato.ignorados.append(Ignorado(data, descricao, valor, "pagamento ou estorno"))
        return
    # A fatura não tem identificador. A origem é montada com data, descrição e valor,
    # mais um contador: duas compras iguais no mesmo dia (dois cafés) são duas.
    chave = f"{data}|{descricao}|{valor}"
    repeticoes[chave] += 1
    origem = f"nubank-cartao:{chave}|{repeticoes[chave]}"
    extrato.itens.append((Gasto(valor, adivinhar_categoria(descricao), descricao, data), origem))


def _ler_linha_conta(linha: dict) -> tuple[date, Decimal, str, str]:
    """Data, valor, origem e descrição (já limpa) de uma linha do extrato da conta."""
    data = datetime.strptime(linha["data"].strip(), "%d/%m/%Y").date()
    valor = ler_valor(linha["valor"])
    # O extrato da conta já traz um identificador único por transação.
    origem = f"nubank-conta:{linha['identificador'].strip()}"
    return data, valor, origem, limpar_descricao(linha["descrição"].strip())


def ler_nubank(arquivo: TextIO) -> Extrato:
    """Lê o CSV inteiro. Se uma linha tiver problema, levanta LinhaInvalida
    (e quem chamou não importa nada)."""
    leitor = csv.DictReader(arquivo)
    # Nomes das colunas em minúsculas e sem espaços, para não depender de detalhes.
    leitor.fieldnames = [nome.strip().lower() for nome in (leitor.fieldnames or [])]
    colunas = set(leitor.fieldnames)

    if {"date", "title", "amount"} <= colunas:
        extrato = Extrato(CARTAO, "Nubank", "CSV")
    elif {"data", "valor", "identificador", "descrição"} <= colunas:
        extrato = Extrato(CONTA, "Nubank", "CSV")
    else:
        raise FormatoDesconhecido(
            "O arquivo não é um OFX nem um CSV do Nubank. O cabeçalho do CSV deveria ser "
            "'date,title,amount' (fatura do cartão) ou "
            "'Data,Valor,Identificador,Descrição' (extrato da conta)."
        )

    repeticoes: Counter = Counter()
    linhas_da_conta = []
    for linha in leitor:
        try:
            if extrato.formato == CARTAO:
                _ler_linha_cartao(linha, extrato, repeticoes)
            else:
                linhas_da_conta.append(_ler_linha_conta(linha))
        except (ValueError, AttributeError) as erro:
            # AttributeError: a linha tem menos colunas que o cabeçalho (o campo vem None).
            raise LinhaInvalida(f"linha {leitor.line_num}: {erro}") from erro
    if extrato.formato == CONTA:
        separar_conta(linhas_da_conta, extrato)
    return extrato
