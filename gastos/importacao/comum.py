"""O que todos os leitores de extrato usam: o resultado, os erros, os valores e as categorias."""

import re
import unicodedata
from collections import Counter
from collections.abc import Sequence
from dataclasses import dataclass, field
from datetime import date
from decimal import Decimal, InvalidOperation

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
# Cada banco escreve de um jeito ("Pagamento de fatura", "PAGTO FATURA CARTAO"...).
MOTIVO_FATURA = "pagamento da fatura; as compras vêm da fatura do cartão"
MOTIVO_GUARDADO = "dinheiro guardado/investido, não é gasto"
IGNORAR_NA_CONTA = [
    (re.compile(r"\bpag(amento|to)?\.? *(de |da )?fatura", re.I), MOTIVO_FATURA),
    (re.compile(r"\b(rdb|cdb|caixinha|aplica(ção|cao))\b", re.I), MOTIVO_GUARDADO),
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


# Pix para uma conta sua (do Inter para o Nubank, por exemplo) só troca o dinheiro de lugar.
# O usuário cadastra o próprio nome, e o que for enviado para ele não conta como gasto.
MOTIVO_PARA_VOCE = "transferência para uma conta sua"
MAXIMO_DE_NOMES = 10


class FormatoDesconhecido(Exception):
    """O arquivo não é de nenhum formato que o programa sabe ler."""


class LinhaInvalida(Exception):
    """Uma linha (ou transação) tem data ou valor que não dá para entender."""


@dataclass
class Ignorado:
    data: date
    descricao: str
    valor: Decimal
    motivo: str


@dataclass
class Extrato:
    formato: str  # CARTAO ou CONTA
    banco: str  # "Nubank", "Inter"...
    arquivo: str  # "CSV" ou "OFX"
    itens: list[tuple[Gasto, str]] = field(default_factory=list)  # (gasto, origem)
    ignorados: list[Ignorado] = field(default_factory=list)

    @property
    def nome(self) -> str:
        """Ex.: 'extrato da conta do Inter (OFX)'."""
        return f"{self.formato} do {self.banco} ({self.arquivo})"


def limpar_descricao(descricao: str) -> str:
    achou = PADRAO_PIX.match(descricao)
    if not achou:
        return descricao
    direcao, nome = achou.groups()
    return f"Pix {'enviado' if direcao == 'enviada' else 'recebido'} - {nome.strip()}"


def adivinhar_categoria(descricao: str) -> str:
    texto = descricao.lower()
    for categoria, palavras in REGRAS_DE_CATEGORIA:
        if any(palavra in texto for palavra in palavras):
            return categoria
    return SEM_CATEGORIA


def ler_valor(texto: str) -> Decimal:
    """Aceita '41.80', '41,80', '1.234,56' e '- 84,00'."""
    limpo = texto.replace(" ", "").replace(" ", "")  # "- 84,00" vira "-84,00"
    if "," in limpo:  # formato brasileiro: ponto separa milhar, vírgula separa centavos
        limpo = limpo.replace(".", "").replace(",", ".")
    try:
        valor = Decimal(limpo)
    except InvalidOperation:
        raise ValueError(f"valor inválido: {texto!r}")
    if not valor.is_finite():
        raise ValueError(f"valor inválido: {texto!r}")
    return valor


def separar_conta(linhas: list[tuple[date, Decimal, str, str]], extrato: Extrato) -> None:
    """Decide o que é gasto num extrato de conta: linhas (data, valor, origem, descrição),
    com saída negativa.

    Precisa ver o arquivo inteiro: a entrada do Pix no Crédito pode vir antes ou
    depois do Pix que ela pagou.
    """
    creditos_para_pix: Counter = Counter(
        (data, valor)
        for data, valor, _, descricao in linhas
        if valor > 0 and descricao.lower().startswith(CREDITO_PARA_PIX)
    )
    for data, valor, origem, descricao in linhas:
        if valor >= 0:
            extrato.ignorados.append(Ignorado(data, descricao, valor, "entrada de dinheiro"))
            continue
        motivo = next((m for padrao, m in IGNORAR_NA_CONTA if padrao.search(descricao)), None)
        if motivo is None and descricao.startswith("Pix enviado") and creditos_para_pix[(data, -valor)]:
            creditos_para_pix[(data, -valor)] -= 1  # cada entrada cobre um Pix só
            motivo = MOTIVO_PIX_NO_CREDITO
        if motivo:
            extrato.ignorados.append(Ignorado(data, descricao, -valor, motivo))
            continue
        gasto = Gasto(-valor, adivinhar_categoria(descricao), descricao, data)
        extrato.itens.append((gasto, origem))


def sem_acentos(texto: str) -> str:
    """'André  LAGOS' -> 'andre lagos': os bancos escrevem o mesmo nome de jeitos diferentes."""
    decomposto = unicodedata.normalize("NFKD", texto)  # "é" vira "e" + acento separado
    sem = "".join(letra for letra in decomposto if not unicodedata.combining(letra))
    return " ".join(sem.lower().split())


def validar_meu_nome(nome: str) -> str:
    """Espaços arrumados; pede nome e sobrenome, porque só "Ana" acharia "Ana Paula" também."""
    nome = " ".join(nome.split())
    if len(nome.split()) < 2:
        raise ValueError("informe nome e sobrenome, como aparecem no extrato")
    if len(nome) > 100:
        raise ValueError("nome longo demais (o máximo é 100 caracteres)")
    return nome


def tirar_transferencias_para_voce(extrato: Extrato, meus_nomes: Sequence[str]) -> None:
    """Passa para os ignorados os gastos cuja descrição tem um dos nomes do usuário."""
    padroes = [
        re.compile(rf"\b{re.escape(sem_acentos(nome))}\b") for nome in meus_nomes if nome.strip()
    ]
    if not padroes:
        return
    gastos = []
    for gasto, origem in extrato.itens:
        if any(padrao.search(sem_acentos(gasto.descricao)) for padrao in padroes):
            extrato.ignorados.append(Ignorado(gasto.data, gasto.descricao, gasto.valor, MOTIVO_PARA_VOCE))
        else:
            gastos.append((gasto, origem))
    extrato.itens = gastos
