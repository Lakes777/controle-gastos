"""Lê extratos em OFX, o formato padrão que quase todo banco exporta (Inter, Itaú, Nubank...).

Existem duas versões do OFX, e as duas são lidas igual:
- 1.x (SGML): cabeçalho "OFXHEADER:100" e tags sem fechamento (<TRNAMT>-45.90)
- 2.x (XML):  cabeçalho <?xml ...?> e tags fechadas (<TRNAMT>-45.90</TRNAMT>)

Cada transação fica num bloco <STMTTRN> com a data (DTPOSTED), o valor (TRNAMT, saída
negativa), a descrição (MEMO e/ou NAME) e um identificador único dado pelo banco (FITID).
"""

import hashlib
import html
import re
from collections import Counter
from datetime import date, datetime

from gastos.importacao.comum import (
    CARTAO,
    CONTA,
    Extrato,
    Ignorado,
    LinhaInvalida,
    adivinhar_categoria,
    ler_valor,
    limpar_descricao,
    separar_conta,
)
from gastos.modelo import Gasto

# Código do banco (o mesmo da TED/Pix) -> nome mostrado na prévia.
BANCOS = {
    1: "Banco do Brasil",
    33: "Santander",
    77: "Inter",
    104: "Caixa",
    237: "Bradesco",
    260: "Nubank",
    336: "C6 Bank",
    341: "Itaú",
}

TRANSACAO = re.compile(r"<STMTTRN>(.*?)</STMTTRN>", re.S | re.I)
# A fatura do cartão vem num bloco próprio (CREDITCARDMSGSRSV1 / CCSTMTRS).
FATURA = re.compile(r"<(CREDITCARDMSGSRSV1|CCSTMTRS)>", re.I)


def parece_ofx(conteudo: bytes) -> bool:
    return re.search(rb"<OFX>", conteudo, re.I) is not None


def decodificar(conteudo: bytes) -> str:
    """Muitos bancos ainda gravam o OFX em Windows-1252 (o cabeçalho diz CHARSET:1252),
    outros em UTF-8. Um texto em 1252 com acento quase nunca é UTF-8 válido, então
    tenta UTF-8 primeiro."""
    try:
        return conteudo.decode("utf-8-sig")
    except UnicodeDecodeError:
        return conteudo.decode("cp1252", errors="replace")


def _campo(bloco: str, nome: str) -> str | None:
    """O texto de <NOME>, com ou sem a tag de fechamento."""
    achou = re.search(rf"<{nome}>([^<]*)", bloco, re.I)
    if not achou:
        return None
    # "&amp;" vira "&", e espaços repetidos viram um só.
    return " ".join(html.unescape(achou.group(1)).split())


def _data(texto: str | None) -> date:
    # "20260905", "20260905120000" ou "20260905120000[-3:BRT]": a data são os 8 primeiros dígitos.
    if not texto or not re.match(r"\d{8}", texto):
        raise ValueError(f"data inválida: {texto!r}")
    return datetime.strptime(texto[:8], "%Y%m%d").date()


def _descricao(bloco: str) -> str:
    nome, memo = _campo(bloco, "NAME") or "", _campo(bloco, "MEMO") or ""
    if nome and memo and nome.lower() not in memo.lower() and memo.lower() not in nome.lower():
        return f"{nome} - {memo}"
    return limpar_descricao(max(nome, memo, key=len))


def _curto(chave: str) -> str:
    # A origem cabe numa coluna de até 300 caracteres; chaves muito longas viram um hash.
    return chave if len(chave) <= 100 else hashlib.sha256(chave.encode()).hexdigest()[:32]


def _banco(texto: str) -> tuple[str, str]:
    """(código, nome) do banco. O código vem do BANKID (conta) ou do FID (cartão)."""
    codigo = _campo(texto, "BANKID") or _campo(texto, "FID") or ""
    if codigo.isdigit() and int(codigo) in BANCOS:
        return str(int(codigo)), BANCOS[int(codigo)]
    nome = _campo(texto, "ORG") or "banco"
    return codigo or nome, nome


def ler_ofx(texto: str) -> Extrato:
    """Lê o OFX inteiro. Se uma transação tiver problema, levanta LinhaInvalida
    (e quem chamou não importa nada)."""
    codigo, nome_do_banco = _banco(texto)
    formato = CARTAO if FATURA.search(texto) else CONTA
    extrato = Extrato(formato, nome_do_banco, "OFX")
    # O número da conta não fica guardado: só um resumo dele, para separar duas contas
    # do mesmo banco (o FITID só é único dentro de uma conta).
    conta = hashlib.sha256((_campo(texto, "ACCTID") or "").encode()).hexdigest()[:8]
    prefixo = f"ofx:{codigo}:{conta}:"

    repeticoes: Counter = Counter()
    linhas = []
    for numero, bloco in enumerate(TRANSACAO.findall(texto), start=1):
        try:
            data = _data(_campo(bloco, "DTPOSTED"))
            valor = ler_valor(_campo(bloco, "TRNAMT") or "")
        except ValueError as erro:
            raise LinhaInvalida(f"transação {numero}: {erro}") from erro
        descricao = _descricao(bloco)
        # Sem FITID (raro), a origem é montada como na fatura do Nubank. Com FITID repetido
        # no mesmo arquivo (acontece em alguns bancos), um contador separa as transações.
        chave = _campo(bloco, "FITID") or f"{data}|{descricao}|{valor}"
        repeticoes[chave] += 1
        if repeticoes[chave] > 1:
            chave += f"#{repeticoes[chave]}"
        linhas.append((data, valor, prefixo + _curto(chave), descricao))

    if formato == CONTA:
        separar_conta(linhas, extrato)
        return extrato
    # Na fatura em OFX, a compra também é negativa; o que é positivo é pagamento ou estorno.
    for data, valor, origem, descricao in linhas:
        if valor >= 0:
            extrato.ignorados.append(Ignorado(data, descricao, valor, "pagamento ou estorno"))
        else:
            gasto = Gasto(-valor, adivinhar_categoria(descricao), descricao, data)
            extrato.itens.append((gasto, origem))
    return extrato
