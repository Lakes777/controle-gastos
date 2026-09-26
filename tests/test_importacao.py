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
    ler_nubank,
)

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

    assert motivos["Transferência recebida pelo Pix - EMPRESA"] == "entrada de dinheiro"
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
