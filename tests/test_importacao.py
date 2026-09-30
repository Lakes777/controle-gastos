import io
from datetime import date
from decimal import Decimal

import pytest

from gastos.importacao import (
    CARTAO,
    CONTA,
    FormatoDesconhecido,
    LinhaInvalida,
    adivinhar_categoria,
    categorias_lembradas,
    ler_extrato,
    ler_nubank,
)
from gastos.importacao.comum import chave_da_descricao
from gastos.modelo import Gasto

FATURA = """date,title,amount
2026-09-05,Uber *Trip,23.59
2026-09-05,Uber *Trip,23.59
2026-09-06,Pagamento recebido,-500.00
2026-09-07,Netflix.com,55.90
2026-09-08,Estorno de compra,-12.00
"""

CONTA_CSV = """Data,Valor,Identificador,Descrição
01/09/2026,-45.90,id-1,Compra no débito - SUPERMERCADO CONDOR
02/09/2026,2500.00,id-2,Transferência recebida pelo Pix - EMPRESA
05/09/2026,-1200.00,id-3,Pagamento de fatura
06/09/2026,-100.00,id-4,Aplicação RDB
07/09/2026,-30.00,id-5,Transferência enviada pelo Pix - FULANO
"""


def ler(texto):
    return ler_nubank(io.StringIO(texto))


def test_fatura_do_cartao():
    extrato = ler(FATURA)

    assert extrato.formato == CARTAO
    gastos = [gasto for gasto, _ in extrato.itens]
    assert [(g.data, g.valor, g.categoria) for g in gastos] == [
        (date(2026, 9, 5), Decimal("23.59"), "transporte"),
        (date(2026, 9, 5), Decimal("23.59"), "transporte"),
        (date(2026, 9, 7), Decimal("55.90"), "assinaturas"),
    ]
    assert [i.motivo for i in extrato.ignorados] == ["pagamento ou estorno"] * 2


def test_fatura_duas_compras_iguais_no_mesmo_dia_tem_origens_diferentes():
    origens = [origem for _, origem in ler(FATURA).itens]

    assert origens[0] != origens[1]
    assert len(set(origens)) == 3


def test_fatura_origem_nao_muda_ao_ler_o_mesmo_arquivo_de_novo():
    assert [o for _, o in ler(FATURA).itens] == [o for _, o in ler(FATURA).itens]


def test_extrato_da_conta():
    extrato = ler(CONTA_CSV)

    assert extrato.formato == CONTA
    assert [(g.data, g.valor, g.categoria, origem) for g, origem in extrato.itens] == [
        (date(2026, 9, 1), Decimal("45.90"), "mercado", "nubank-conta:id-1"),
        (date(2026, 9, 7), Decimal("30.00"), "outros", "nubank-conta:id-5"),
    ]


def test_conta_ignora_entradas_pagamento_de_fatura_e_investimento():
    motivos = {i.descricao: i.motivo for i in ler(CONTA_CSV).ignorados}

    assert motivos["Pix recebido - EMPRESA"] == "entrada de dinheiro"
    assert "pagamento da fatura" in motivos["Pagamento de fatura"]
    assert "investido" in motivos["Aplicação RDB"]


def test_cabecalho_com_espacos_e_maiusculas_diferentes():
    extrato = ler(" Date , TITLE ,amount\n2026-09-05,Uber,10\n")

    assert extrato.formato == CARTAO
    assert len(extrato.itens) == 1


def test_arquivo_que_nao_e_do_nubank():
    with pytest.raises(FormatoDesconhecido):
        ler("numero;data;valor;categoria;descricao\n1;23/09/2026;30,00;lanche;almoço\n")


def test_arquivo_vazio():
    with pytest.raises(FormatoDesconhecido):
        ler("")


@pytest.mark.parametrize(
    "linha_ruim",
    [
        "2026-13-45,Uber,10",  # data impossível
        "2026-09-05,Uber,dez reais",  # valor que não é número
        "2026-09-05,Uber",  # faltou uma coluna
    ],
)
def test_linha_invalida_diz_qual_linha(linha_ruim):
    texto = "date,title,amount\n2026-09-01,Padaria,8.50\n" + linha_ruim + "\n"

    with pytest.raises(LinhaInvalida, match="linha 3"):
        ler(texto)


@pytest.mark.parametrize(
    "descricao, categoria",
    [
        ("UBER *TRIP HELP.UBER.COM", "transporte"),
        ("Ifood *Restaurante", "alimentação"),
        ("Amazon Prime Video", "assinaturas"),  # antes de "amazon" (compras)
        ("AMAZON MARKETPLACE", "compras"),
        ("Mercado Livre", "compras"),  # antes de "mercado"
        ("Supermercado Condor", "mercado"),
        ("Drogaria Raia", "saúde"),
        ("Apple.Com/Bill", "assinaturas"),
        ("Pag*Steam - Parcela 2/3", "lazer"),
        ("Angeloni Super Loja", "mercado"),
        ("Pagamento de boleto efetuado - PUC PR CAMPUS CURITIBA", "educação"),
        ("Mensalidade Faculdade Exemplo", "educação"),
        ("Alura Cursos", "educação"),
        ("Viking Barbearia", "outros"),  # "bar" dentro de Barbearia não vira lazer
        ("Loja qualquer", "outros"),
    ],
)
def test_adivinhar_categoria(descricao, categoria):
    assert adivinhar_categoria(descricao) == categoria


def test_valor_zero_nao_vira_gasto_em_nenhum_formato():
    fatura = ler("date,title,amount\n2026-09-05,Ajuste,0.00\n")
    conta = ler("Data,Valor,Identificador,Descrição\n05/09/2026,0.00,id-9,Ajuste\n")

    assert fatura.itens == [] and len(fatura.ignorados) == 1
    assert conta.itens == [] and len(conta.ignorados) == 1


# Como a fatura real do Nubank vem (conferido num arquivo exportado em 2026):
# valor com vírgula e entre aspas, e negativo com espaço depois do sinal.
FATURA_FORMATO_REAL = '''date,title,amount
2026-08-02,Loja Online* Exemplo,"41,80"
2026-08-01,Barbearia Exemplo,"70,00"
2026-07-29,Pagamento recebido,"- 84,00"
2026-07-28,Notebook Exemplo,"1.234,56"
'''


def test_fatura_no_formato_real_com_virgula_e_sinal_separado():
    extrato = ler(FATURA_FORMATO_REAL)

    assert [g.valor for g, _ in extrato.itens] == [
        Decimal("41.80"),
        Decimal("70.00"),
        Decimal("1234.56"),
    ]
    assert [(i.descricao, i.valor) for i in extrato.ignorados] == [
        ("Pagamento recebido", Decimal("-84.00"))
    ]


# Linhas no formato real do extrato da conta (conferido com um arquivo de verdade),
# com nomes, CPFs e contas inventados.
EXTRATO_REAL = """Data,Valor,Identificador,Descrição
01/08/2026,241.50,a1,Transferência recebida pelo Pix - MARIA DA SILVA - •••.121.369-•• - BCO DO BRASIL S.A. (0001) Agência: 1534 Conta: 42098-0
01/08/2026,-222.39,a2,Compra no débito via NuPay - iFood
03/08/2026,-1.00,a3,Transferência enviada pelo Pix - JOANA SOUZA - •••.355.749-•• - BANCO INTER (0077) Agência: 1 Conta: 23650327-8
04/08/2026,-182.00,a4,Transferência enviada pelo Pix - PEDRO SANTOS (Transferência enviada)
05/08/2026,-2088.75,a5,Pagamento de boleto efetuado - PUC PR CAMPUS CURITIBA
11/08/2026,50.00,a6,Valor adicionado na conta por cartão de crédito - Valor adicionado para Pix no Crédito
11/08/2026,-50.00,a7,Transferência enviada pelo Pix - CARLOS LIMA - •••.465.549-•• - BANCO INTER (0077) Agência: 1 Conta: 15922889-1
28/08/2026,-222.00,a8,Transferência enviada pelo Pix - CARLOS LIMA - •••.465.549-•• - BANCO INTER (0077) Agência: 1 Conta: 15922889-1
28/08/2026,222.00,a9,Valor adicionado na conta por cartão de crédito - Valor adicionado para Pix no Crédito
29/08/2026,-80.00,a10,Transferência enviada pelo Pix - CARLOS LIMA - •••.465.549-•• - BANCO INTER (0077) Agência: 1 Conta: 15922889-1
"""


def test_extrato_real_da_conta():
    extrato = ler(EXTRATO_REAL)

    assert [(g.descricao, g.valor, g.categoria) for g, _ in extrato.itens] == [
        ("Compra no débito via NuPay - iFood", Decimal("222.39"), "alimentação"),
        ("Pix enviado - JOANA SOUZA", Decimal("1.00"), "outros"),
        ("Pix enviado - PEDRO SANTOS", Decimal("182.00"), "outros"),
        ("Pagamento de boleto efetuado - PUC PR CAMPUS CURITIBA", Decimal("2088.75"), "educação"),
        ("Pix enviado - CARLOS LIMA", Decimal("80.00"), "outros"),  # sem crédito no dia: é gasto
    ]


def test_pix_no_credito_nao_conta_duas_vezes():
    # O Pix pago com o cartão aparece na fatura ("Pix no Crédito", às vezes parcelado).
    # Na conta, ele vem como uma entrada "por cartão de crédito" e um Pix enviado do
    # mesmo valor no mesmo dia (em qualquer ordem): o Pix enviado é ignorado.
    pix_no_credito = [i for i in ler(EXTRATO_REAL).ignorados if "Pix no Crédito" in i.motivo]
    assert [(i.data, i.valor) for i in pix_no_credito] == [
        (date(2026, 8, 11), Decimal("50.00")),
        (date(2026, 8, 28), Decimal("222.00")),
    ]


def test_um_credito_so_cobre_um_pix():
    texto = """Data,Valor,Identificador,Descrição
11/08/2026,50.00,c1,Valor adicionado na conta por cartão de crédito - Valor adicionado para Pix no Crédito
11/08/2026,-50.00,c2,Transferência enviada pelo Pix - ANA
11/08/2026,-50.00,c3,Transferência enviada pelo Pix - ANA
11/08/2026,-49.99,c4,Transferência enviada pelo Pix - ANA
"""
    extrato = ler(texto)
    assert [(g.valor, o) for g, o in extrato.itens] == [
        (Decimal("50.00"), "nubank-conta:c3"),
        (Decimal("49.99"), "nubank-conta:c4"),
    ]


def test_descricao_do_pix_sem_cpf_banco_e_conta():
    extrato = ler(EXTRATO_REAL)
    descricoes = [g.descricao for g, _ in extrato.itens] + [i.descricao for i in extrato.ignorados]
    assert "Pix recebido - MARIA DA SILVA" in descricoes
    for descricao in descricoes:
        assert "•••" not in descricao and "Agência" not in descricao and "Conta:" not in descricao


# ---------- Categorias lembradas ----------


@pytest.mark.parametrize(
    "descricao, chave",
    [
        ("Paradojabar", "paradojabar"),
        ("Pag*Steam - Parcela 2/3", "pag steam"),
        ("PAG STEAM", "pag steam"),
        ("Raia140", "raia"),
        ("Café  Moinho", "cafe moinho"),
        ("Pix no Crédito - Fulano - 2/8", "pix no credito fulano"),
        ("", ""),
        ("123 / 45", ""),
        ("PIX TRANSF 29/09", ""),  # genérica: não diz a loja
        ("COMPRA CARTAO 1234", ""),
        ("Pix enviado - Gabriel Souza", "pix enviado gabriel souza"),
    ],
)
def test_chave_da_descricao(descricao, chave):
    assert chave_da_descricao(descricao) == chave


def test_categorias_lembradas_usa_a_mais_recente_e_ignora_outros():
    gastos = [
        Gasto(Decimal("30"), "alimentação", "Paradojabar", date(2026, 7, 4)),
        Gasto(Decimal("30"), "lazer", "PARADOJABAR", date(2026, 8, 1)),
        Gasto(Decimal("30"), "outros", "Paradojabar", date(2026, 8, 2)),  # "outros" não apaga a escolha
        Gasto(Decimal("10"), "outros", "Casa Vecchia", date(2026, 8, 3)),
        Gasto(Decimal("5"), "lanche", "", date(2026, 8, 4)),  # sem descrição, não há loja
    ]
    assert categorias_lembradas(gastos) == {"paradojabar": "lazer"}


def test_ler_extrato_troca_o_palpite_pela_categoria_lembrada():
    fatura = """date,title,amount
2026-09-05,Uber *Trip,23.59
2026-09-06,Paradojabar,40.00
2026-09-07,Loja Nova,10.00
"""
    lembradas = {"uber trip": "trabalho", "paradojabar": "lazer"}
    extrato = ler_extrato(fatura.encode(), lembradas=lembradas)

    assert [g.categoria for g, _ in extrato.itens] == ["trabalho", "lazer", "outros"]
    assert extrato.lembradas == {origem for _, origem in extrato.itens[:2]}
    assert ler_extrato(fatura.encode()).lembradas == set()


def test_categoria_lembrada_vence_a_regra():
    fatura = "date,title,amount\n2026-09-05,Mercado*Mercadolivre,80.00\n"
    assert [g.categoria for g, _ in ler_extrato(fatura.encode()).itens] == ["compras"]
    lembradas = categorias_lembradas([Gasto(Decimal("50"), "presentes", "MERCADO*MERCADOLIVRE")])
    [(gasto, _)] = ler_extrato(fatura.encode(), lembradas=lembradas).itens
    assert gasto.categoria == "presentes"
