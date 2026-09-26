"""Lê o extrato em CSV do Nubank (fatura do cartão ou extrato da conta).

O formato é reconhecido pelo cabeçalho:
- fatura do cartão:  date,title,amount           (2026-09-05; gasto é positivo)
- extrato da conta:  Data,Valor,Identificador,Descrição   (05/09/2026; gasto é negativo)
"""

import csv
from collections import Counter
from dataclasses import dataclass, field
from datetime import date, datetime
from decimal import Decimal, InvalidOperation
from typing import TextIO

from gastos.modelo import Gasto

CARTAO, CONTA = "fatura do cartão", "extrato da conta"

# A categoria é adivinhada pela descrição: vale a primeira regra que combinar.
# A ordem importa: "amazon prime" (assinatura) vem antes de "amazon" (compras),
# e "mercado livre" (compras) antes de "mercado".
REGRAS_DE_CATEGORIA = [
    ("assinaturas", ["netflix", "spotify", "amazon prime", "prime video", "disney", "youtube", "hbo"]),
    ("compras", ["mercado livre", "mercadolivre", "shopee", "amazon", "aliexpress", "magalu", "shein"]),
    ("mercado", ["mercado", "supermerc", "atacad", "assai", "carrefour", "condor", "hortifruti"]),
    ("transporte", ["uber", "99app", "99 pop", "cabify", "posto", "combustiv", "estacionamento"]),
    ("alimentação", ["ifood", "rappi", "restaurante", "lanchonete", "padaria", "pizza", "burger"]),
    ("saúde", ["farmacia", "farmácia", "drogaria", "raia", "panvel", "droga"]),
]
SEM_CATEGORIA = "outros"

# Saídas da conta que não são gastos: somá-las contaria o mesmo dinheiro duas vezes.
IGNORAR_NA_CONTA = [
    ("pagamento de fatura", "pagamento da fatura; as compras vêm da fatura do cartão"),
    ("rdb", "dinheiro guardado/investido, não é gasto"),
    ("caixinha", "dinheiro guardado/investido, não é gasto"),
]


class FormatoDesconhecido(Exception):
    """O arquivo não parece um CSV do Nubank."""


class LinhaInvalida(Exception):
    """Uma linha do CSV tem data ou valor que não dá para entender."""


@dataclass
class Ignorado:
    data: date
    descricao: str
    valor: Decimal
    motivo: str


@dataclass
class Extrato:
    formato: str
    itens: list[tuple[Gasto, str]] = field(default_factory=list)  # (gasto, origem)
    ignorados: list[Ignorado] = field(default_factory=list)


def adivinhar_categoria(descricao: str) -> str:
    texto = descricao.lower()
    for categoria, palavras in REGRAS_DE_CATEGORIA:
        if any(palavra in texto for palavra in palavras):
            return categoria
    return SEM_CATEGORIA


def _valor(texto: str) -> Decimal:
    try:
        valor = Decimal(texto.strip())
    except InvalidOperation:
        raise ValueError(f"valor inválido: {texto!r}")
    if not valor.is_finite():
        raise ValueError(f"valor inválido: {texto!r}")
    return valor


def _ler_linha_cartao(linha: dict, extrato: Extrato, repeticoes: Counter) -> None:
    data = date.fromisoformat(linha["date"].strip())
    descricao = linha["title"].strip()
    valor = _valor(linha["amount"])
    if valor <= 0:
        extrato.ignorados.append(Ignorado(data, descricao, valor, "pagamento ou estorno"))
        return
    # A fatura não tem identificador. A origem é montada com data, descrição e valor,
    # mais um contador: duas compras iguais no mesmo dia (dois cafés) são duas.
    chave = f"{data}|{descricao}|{valor}"
    repeticoes[chave] += 1
    origem = f"nubank-cartao:{chave}|{repeticoes[chave]}"
    extrato.itens.append((Gasto(valor, adivinhar_categoria(descricao), descricao, data), origem))


def _ler_linha_conta(linha: dict, extrato: Extrato, repeticoes: Counter) -> None:
    data = datetime.strptime(linha["data"].strip(), "%d/%m/%Y").date()
    descricao = linha["descrição"].strip()
    valor = _valor(linha["valor"])
    if valor >= 0:
        extrato.ignorados.append(Ignorado(data, descricao, valor, "entrada de dinheiro"))
        return
    motivo = next((m for trecho, m in IGNORAR_NA_CONTA if trecho in descricao.lower()), None)
    if motivo:
        extrato.ignorados.append(Ignorado(data, descricao, -valor, motivo))
        return
    # O extrato da conta já traz um identificador único por transação.
    origem = f"nubank-conta:{linha['identificador'].strip()}"
    extrato.itens.append((Gasto(-valor, adivinhar_categoria(descricao), descricao, data), origem))


def ler_nubank(arquivo: TextIO) -> Extrato:
    """Lê o CSV inteiro. Se uma linha tiver problema, levanta LinhaInvalida
    (e quem chamou não importa nada)."""
    leitor = csv.DictReader(arquivo)
    # Nomes das colunas em minúsculas e sem espaços, para não depender de detalhes.
    leitor.fieldnames = [nome.strip().lower() for nome in (leitor.fieldnames or [])]
    colunas = set(leitor.fieldnames)

    if {"date", "title", "amount"} <= colunas:
        extrato, ler_linha = Extrato(CARTAO), _ler_linha_cartao
    elif {"data", "valor", "identificador", "descrição"} <= colunas:
        extrato, ler_linha = Extrato(CONTA), _ler_linha_conta
    else:
        raise FormatoDesconhecido(
            "Não parece um CSV do Nubank. O cabeçalho deveria ser "
            "'date,title,amount' (fatura do cartão) ou "
            "'Data,Valor,Identificador,Descrição' (extrato da conta)."
        )

    repeticoes: Counter = Counter()
    for linha in leitor:
        try:
            ler_linha(linha, extrato, repeticoes)
        except (ValueError, AttributeError) as erro:
            # AttributeError: a linha tem menos colunas que o cabeçalho (o campo vem None).
            raise LinhaInvalida(f"linha {leitor.line_num}: {erro}") from erro
    return extrato
