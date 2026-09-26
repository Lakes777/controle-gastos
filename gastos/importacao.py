"""Lê o extrato em CSV do Nubank (fatura do cartão ou extrato da conta).

O formato é reconhecido pelo cabeçalho:
- fatura do cartão:  date,title,amount           (2026-09-05; gasto é positivo;
                     o valor pode vir como "41,80" e o negativo como "- 84,00")
- extrato da conta:  Data,Valor,Identificador,Descrição   (05/09/2026; gasto é negativo)

Os dois formatos foram conferidos com arquivos reais.
"""

import csv
import re
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
    ("assinaturas", [
        "netflix", "spotify", "amazon prime", "prime video", "disney", "youtube", "hbo",
        "apple.com/bill",
    ]),
    ("compras", ["mercado livre", "mercadolivre", "shopee", "amazon", "aliexpress", "magalu", "shein"]),
    ("educação", [
        "puc", "faculdade", "universidade", "mensalidade", "escola", "colégio", "colegio",
        "curso", "alura", "udemy",
    ]),
    ("mercado", [
        "mercado", "supermerc", "atacad", "assai", "carrefour", "condor", "hortifruti",
        "angeloni", "muffato",
    ]),
    ("transporte", ["uber", "99app", "99 pop", "cabify", "posto", "combustiv", "estacionamento"]),
    ("alimentação", ["ifood", "rappi", "restaurante", "lanchonete", "padaria", "pizza", "burger"]),
    ("lazer", ["steam", "playstation", "xbox", "nintendo", "cinema", "ingresso"]),
    ("saúde", ["farmacia", "farmácia", "drogaria", "raia", "panvel", "droga"]),
]
SEM_CATEGORIA = "outros"

# Saídas da conta que não são gastos: somá-las contaria o mesmo dinheiro duas vezes.
IGNORAR_NA_CONTA = [
    ("pagamento de fatura", "pagamento da fatura; as compras vêm da fatura do cartão"),
    ("rdb", "dinheiro guardado/investido, não é gasto"),
    ("caixinha", "dinheiro guardado/investido, não é gasto"),
]


# Pix no Crédito: o Nubank põe o valor na conta (entrada "por cartão de crédito") e manda o
# Pix na hora. Quem paga é o cartão, e as parcelas aparecem na fatura como "Pix no Crédito".
CREDITO_PARA_PIX = "valor adicionado na conta por cartão de crédito"
MOTIVO_PIX_NO_CREDITO = "pago com Pix no Crédito; as parcelas vêm na fatura do cartão"

# "Transferência enviada pelo Pix - NOME - •••.123.456-•• - BANCO (0077) Agência: 1 Conta: 2-3"
# vira "Pix enviado - NOME" (sem CPF, banco, agência e conta, que só poluem a lista).
PADRAO_PIX = re.compile(
    r"^Transferência (enviada|recebida) pelo Pix - (.+?)"
    r"(?: - •••.*| \(Transferência (?:enviada|recebida)\))?$"
)


def limpar_descricao(descricao: str) -> str:
    achou = PADRAO_PIX.match(descricao)
    if not achou:
        return descricao
    direcao, nome = achou.groups()
    return f"Pix {'enviado' if direcao == 'enviada' else 'recebido'} - {nome.strip()}"


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
    """Aceita os jeitos que o Nubank já usou: '41.80', '"41,80"', '1.234,56' e '- 84,00'."""
    limpo = texto.replace(" ", "").replace("\u00a0", "")  # "- 84,00" vira "-84,00"
    if "," in limpo:  # formato brasileiro: ponto separa milhar, vírgula separa centavos
        limpo = limpo.replace(".", "").replace(",", ".")
    try:
        valor = Decimal(limpo)
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


def _ler_linha_conta(linha: dict) -> tuple[date, Decimal, str, str]:
    """Data, valor, identificador e descrição (já limpa) de uma linha do extrato da conta."""
    data = datetime.strptime(linha["data"].strip(), "%d/%m/%Y").date()
    valor = _valor(linha["valor"])
    return data, valor, linha["identificador"].strip(), limpar_descricao(linha["descrição"].strip())


def _separar_conta(linhas: list[tuple[date, Decimal, str, str]], extrato: Extrato) -> None:
    """Decide o que é gasto no extrato da conta.

    Precisa ver o arquivo inteiro: a entrada do Pix no Crédito pode vir antes ou
    depois do Pix que ela pagou.
    """
    creditos_para_pix: Counter = Counter(
        (data, valor)
        for data, valor, _, descricao in linhas
        if valor > 0 and descricao.lower().startswith(CREDITO_PARA_PIX)
    )
    for data, valor, identificador, descricao in linhas:
        if valor >= 0:
            extrato.ignorados.append(Ignorado(data, descricao, valor, "entrada de dinheiro"))
            continue
        motivo = next((m for trecho, m in IGNORAR_NA_CONTA if trecho in descricao.lower()), None)
        if motivo is None and descricao.startswith("Pix enviado") and creditos_para_pix[(data, -valor)]:
            creditos_para_pix[(data, -valor)] -= 1  # cada entrada cobre um Pix só
            motivo = MOTIVO_PIX_NO_CREDITO
        if motivo:
            extrato.ignorados.append(Ignorado(data, descricao, -valor, motivo))
            continue
        # O extrato da conta já traz um identificador único por transação.
        gasto = Gasto(-valor, adivinhar_categoria(descricao), descricao, data)
        extrato.itens.append((gasto, f"nubank-conta:{identificador}"))


def ler_nubank(arquivo: TextIO) -> Extrato:
    """Lê o CSV inteiro. Se uma linha tiver problema, levanta LinhaInvalida
    (e quem chamou não importa nada)."""
    leitor = csv.DictReader(arquivo)
    # Nomes das colunas em minúsculas e sem espaços, para não depender de detalhes.
    leitor.fieldnames = [nome.strip().lower() for nome in (leitor.fieldnames or [])]
    colunas = set(leitor.fieldnames)

    if {"date", "title", "amount"} <= colunas:
        extrato = Extrato(CARTAO)
    elif {"data", "valor", "identificador", "descrição"} <= colunas:
        extrato = Extrato(CONTA)
    else:
        raise FormatoDesconhecido(
            "Não parece um CSV do Nubank. O cabeçalho deveria ser "
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
        _separar_conta(linhas_da_conta, extrato)
    return extrato
