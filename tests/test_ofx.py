from datetime import date
from decimal import Decimal

import pytest

from gastos.importacao import CARTAO, CONTA, FormatoDesconhecido, LinhaInvalida, ler_extrato

# OFX 1.x (SGML), como o Inter e muitos bancos exportam: cabeçalho em linhas, tags sem
# fechamento e texto em Windows-1252. Nomes e números inventados.
CONTA_INTER = """OFXHEADER:100
DATA:OFXSGML
VERSION:102
SECURITY:NONE
ENCODING:USASCII
CHARSET:1252
COMPRESSION:NONE
OLDFILEUID:NONE
NEWFILEUID:NONE

<OFX>
<SIGNONMSGSRSV1>
<SONRS>
<STATUS><CODE>0<SEVERITY>INFO</STATUS>
<DTSERVER>20260927120000[-3:BRT]
<LANGUAGE>POR
<FI><ORG>Banco Inter S.A.<FID>077</FI>
</SONRS>
</SIGNONMSGSRSV1>
<BANKMSGSRSV1>
<STMTTRNRS>
<TRNUID>1
<STATUS><CODE>0<SEVERITY>INFO</STATUS>
<STMTRS>
<CURDEF>BRL
<BANKACCTFROM>
<BANKID>0077
<BRANCHID>0001
<ACCTID>12345678-9
<ACCTTYPE>CHECKING
</BANKACCTFROM>
<BANKTRANLIST>
<DTSTART>20260901
<DTEND>20260930
<STMTTRN>
<TRNTYPE>DEBIT
<DTPOSTED>20260901000000[-3:BRT]
<TRNAMT>-45.90
<FITID>202609010001
<MEMO>Compra no débito - Supermercado Condor
</STMTTRN>
<STMTTRN>
<TRNTYPE>CREDIT
<DTPOSTED>20260905
<TRNAMT>2500.00
<FITID>202609050001
<MEMO>Pix recebido - Empresa Exemplo
</STMTTRN>
<STMTTRN>
<TRNTYPE>DEBIT
<DTPOSTED>20260910
<TRNAMT>-1200.00
<FITID>202609100001
<MEMO>PAGAMENTO DE FATURA
</STMTTRN>
<STMTTRN>
<TRNTYPE>DEBIT
<DTPOSTED>20260911
<TRNAMT>-300.00
<FITID>202609110001
<MEMO>Aplicação CDB
</STMTTRN>
<STMTTRN>
<TRNTYPE>DEBIT
<DTPOSTED>20260912
<TRNAMT>-89.90
<FITID>202609120001
<MEMO>Farmácia São João &amp; Cia
</STMTTRN>
</BANKTRANLIST>
<LEDGERBAL><BALAMT>864.20<DTASOF>20260930</LEDGERBAL>
</STMTRS>
</STMTTRNRS>
</BANKMSGSRSV1>
</OFX>
"""

# OFX 2.x (XML) de uma fatura de cartão: tags fechadas, UTF-8 e a compra negativa.
FATURA_ITAU = """<?xml version="1.0" encoding="UTF-8" standalone="no"?>
<?OFX OFXHEADER="200" VERSION="220" SECURITY="NONE" OLDFILEUID="NONE" NEWFILEUID="NONE"?>
<OFX>
  <SIGNONMSGSRSV1><SONRS>
    <STATUS><CODE>0</CODE><SEVERITY>INFO</SEVERITY></STATUS>
    <DTSERVER>20260927</DTSERVER><LANGUAGE>POR</LANGUAGE>
    <FI><ORG>Itau</ORG><FID>341</FID></FI>
  </SONRS></SIGNONMSGSRSV1>
  <CREDITCARDMSGSRSV1><CCSTMTTRNRS><TRNUID>1</TRNUID>
    <STATUS><CODE>0</CODE><SEVERITY>INFO</SEVERITY></STATUS>
    <CCSTMTRS>
      <CURDEF>BRL</CURDEF>
      <CCACCTFROM><ACCTID>5555XXXXXXXX1234</ACCTID></CCACCTFROM>
      <BANKTRANLIST>
        <DTSTART>20260801</DTSTART><DTEND>20260831</DTEND>
        <STMTTRN>
          <TRNTYPE>DEBIT</TRNTYPE><DTPOSTED>20260803</DTPOSTED><TRNAMT>-23.59</TRNAMT>
          <FITID>f1</FITID><NAME>UBER *TRIP</NAME>
        </STMTTRN>
        <STMTTRN>
          <TRNTYPE>DEBIT</TRNTYPE><DTPOSTED>20260805</DTPOSTED><TRNAMT>-55.90</TRNAMT>
          <FITID>f2</FITID><NAME>NETFLIX.COM</NAME>
        </STMTTRN>
        <STMTTRN>
          <TRNTYPE>CREDIT</TRNTYPE><DTPOSTED>20260810</DTPOSTED><TRNAMT>600.00</TRNAMT>
          <FITID>f3</FITID><NAME>PAGAMENTO EFETUADO</NAME>
        </STMTTRN>
      </BANKTRANLIST>
    </CCSTMTRS>
  </CCSTMTTRNRS></CREDITCARDMSGSRSV1>
</OFX>
"""


def transacao(fitid="t1", valor="-10.00", memo="Loja", data="20260901"):
    return (
        f"<STMTTRN><TRNTYPE>DEBIT<DTPOSTED>{data}<TRNAMT>{valor}"
        + (f"<FITID>{fitid}" if fitid else "")
        + f"<MEMO>{memo}</STMTTRN>"
    )


def conta(*transacoes, banco="077", acctid="111"):
    return (
        f"<OFX><BANKMSGSRSV1><STMTRS><BANKACCTFROM><BANKID>{banco}<ACCTID>{acctid}"
        f"</BANKACCTFROM><BANKTRANLIST>{''.join(transacoes)}</BANKTRANLIST>"
        "</STMTRS></BANKMSGSRSV1></OFX>"
    ).encode()


def test_conta_do_inter_em_ofx_1_com_windows_1252():
    extrato = ler_extrato(CONTA_INTER.encode("cp1252"))

    assert (extrato.formato, extrato.banco, extrato.arquivo) == (CONTA, "Inter", "OFX")
    assert extrato.nome == "extrato da conta do Inter (OFX)"
    assert [(g.data, g.valor, g.categoria, g.descricao) for g, _ in extrato.itens] == [
        (date(2026, 9, 1), Decimal("45.90"), "mercado", "Compra no débito - Supermercado Condor"),
        (date(2026, 9, 12), Decimal("89.90"), "saúde", "Farmácia São João & Cia"),
    ]


def test_conta_ignora_entrada_pagamento_de_fatura_e_investimento():
    motivos = {i.descricao: i.motivo for i in ler_extrato(CONTA_INTER.encode("cp1252")).ignorados}

    assert motivos["Pix recebido - Empresa Exemplo"] == "entrada de dinheiro"
    assert "pagamento da fatura" in motivos["PAGAMENTO DE FATURA"]
    assert "investido" in motivos["Aplicação CDB"]


def test_o_mesmo_ofx_em_utf_8_da_o_mesmo_resultado():
    em_1252 = ler_extrato(CONTA_INTER.encode("cp1252"))
    em_utf8 = ler_extrato(CONTA_INTER.encode("utf-8"))

    assert em_1252.itens == em_utf8.itens


def test_fatura_do_cartao_em_ofx_2_xml():
    extrato = ler_extrato(FATURA_ITAU.encode())

    assert extrato.nome == "fatura do cartão do Itaú (OFX)"
    assert extrato.formato == CARTAO
    assert [(g.data, g.valor, g.categoria) for g, _ in extrato.itens] == [
        (date(2026, 8, 3), Decimal("23.59"), "transporte"),
        (date(2026, 8, 5), Decimal("55.90"), "assinaturas"),
    ]
    assert [(i.descricao, i.motivo) for i in extrato.ignorados] == [
        ("PAGAMENTO EFETUADO", "pagamento ou estorno")
    ]


def test_origem_usa_o_fitid_e_nao_guarda_o_numero_da_conta():
    origens = [origem for _, origem in ler_extrato(CONTA_INTER.encode("cp1252")).itens]

    assert origens[0].startswith("ofx:77:") and origens[0].endswith(":202609010001")
    assert all("12345678" not in origem for origem in origens)


def test_origem_nao_muda_ao_ler_o_mesmo_arquivo_de_novo():
    def origens():
        return [o for _, o in ler_extrato(FATURA_ITAU.encode()).itens]

    assert origens() == origens()


def test_mesmo_fitid_em_contas_diferentes_nao_se_confunde():
    [(_, origem_a)] = ler_extrato(conta(transacao("t1"), acctid="111")).itens
    [(_, origem_b)] = ler_extrato(conta(transacao("t1"), acctid="222")).itens

    assert origem_a != origem_b


def test_fitid_repetido_no_arquivo_vira_duas_transacoes():
    extrato = ler_extrato(conta(transacao("t1", memo="Café"), transacao("t1", memo="Café")))

    origens = [o for _, o in extrato.itens]
    assert len(origens) == 2 and origens[0] != origens[1]


def test_sem_fitid_a_origem_vem_da_data_descricao_e_valor():
    extrato = ler_extrato(conta(transacao(None), transacao(None)))

    origens = [o for _, o in extrato.itens]
    assert len(set(origens)) == 2
    assert "2026-09-01|Loja|-10.00" in origens[0]


def test_nome_e_memo_diferentes_vao_os_dois_na_descricao():
    bloco = (
        "<STMTTRN><DTPOSTED>20260901<TRNAMT>-5<FITID>x"
        "<NAME>PIX ENVIADO<MEMO>Joana Souza</STMTTRN>"
    )
    [(gasto, _)] = ler_extrato(conta(bloco)).itens

    assert gasto.descricao == "PIX ENVIADO - Joana Souza"


def test_banco_fora_da_lista_usa_o_nome_do_arquivo():
    texto = FATURA_ITAU.replace("<ORG>Itau</ORG><FID>341</FID>", "<ORG>Banco Exemplo</ORG><FID>999</FID>")

    assert ler_extrato(texto.encode()).banco == "Banco Exemplo"


@pytest.mark.parametrize(
    "ruim",
    [
        transacao("t2", data="2026-09-01"),  # data fora do padrão
        transacao("t2", valor="dez reais"),  # valor que não é número
        "<STMTTRN><DTPOSTED>20260901<FITID>t2<MEMO>Sem valor</STMTTRN>",
    ],
)
def test_transacao_invalida_diz_qual_e_nada_e_lido(ruim):
    with pytest.raises(LinhaInvalida, match="transação 2"):
        ler_extrato(conta(transacao("t1"), ruim))


def test_ofx_sem_transacoes():
    extrato = ler_extrato(conta())

    assert extrato.itens == [] and extrato.ignorados == []


def test_csv_continua_indo_para_o_leitor_do_nubank():
    extrato = ler_extrato(b"date,title,amount\n2026-09-05,Uber,10\n")

    assert extrato.nome == "fatura do cartão do Nubank (CSV)"


def test_csv_fora_do_utf_8_e_recusado():
    with pytest.raises(UnicodeDecodeError):
        ler_extrato("date,title,amount\n2026-09-05,Café,10\n".encode("cp1252"))


def test_arquivo_que_nao_e_nem_csv_nem_ofx():
    with pytest.raises(FormatoDesconhecido, match="não é um OFX nem um CSV do Nubank"):
        ler_extrato(b"%PDF-1.7 um extrato em PDF")


@pytest.mark.parametrize(
    "descricao, ignorado",
    [
        ("PAGTO FATURA CARTAO", True),
        ("Pagamento fatura Inter", True),
        ("PAG FATURA", True),
        ("Aplicacao Poupanca", True),
        ("Pagamento de boleto - Condominio", False),
        ("Aplicativo de Transporte", False),  # "aplica" dentro de outra palavra não conta
    ],
)
def test_jeitos_diferentes_de_escrever_fatura_e_investimento(descricao, ignorado):
    extrato = ler_extrato(conta(transacao(memo=descricao)))

    assert (len(extrato.ignorados) == 1) is ignorado

