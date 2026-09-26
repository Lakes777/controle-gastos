import argparse
import sys
import zipfile
from datetime import date
from decimal import Decimal

import pytest

from gastos.__main__ import dia_do_mes, formatar_reais, main, mes_valido, valor_positivo


@pytest.mark.parametrize(
    "texto, esperado",
    [
        ("45.90", Decimal("45.90")),
        ("45,90", Decimal("45.90")),
        ("1250", Decimal("1250")),
    ],
)
def test_valor_positivo_aceita_ponto_e_virgula(texto, esperado):
    assert valor_positivo(texto) == esperado


@pytest.mark.parametrize("texto", ["abc", "0", "-5", "nan", "infinity"])
def test_valor_positivo_rejeita_valores_invalidos(texto):
    with pytest.raises(argparse.ArgumentTypeError):
        valor_positivo(texto)


@pytest.mark.parametrize(
    "valor, esperado",
    [
        (Decimal("0.5"), "R$ 0,50"),
        (Decimal("45.9"), "R$ 45,90"),
        (Decimal("1250"), "R$ 1.250,00"),
        (Decimal("1234567.89"), "R$ 1.234.567,89"),
    ],
)
def test_formatar_reais(valor, esperado):
    assert formatar_reais(valor) == esperado


def rodar(monkeypatch, *argumentos):
    """Simula o usuário digitando `python -m gastos <argumentos>`."""
    monkeypatch.setattr(sys, "argv", ["gastos", *argumentos])
    main()


def test_fluxo_completo_adicionar_listar_resumo(tmp_path, monkeypatch, capsys):
    monkeypatch.chdir(tmp_path)  # os dados vão para uma pasta temporária

    rodar(monkeypatch, "adicionar", "45,90", "Mercado", "compras")
    rodar(monkeypatch, "adicionar", "12.50", "transporte", "--data", "2026-08-10")
    capsys.readouterr()  # descarta as mensagens de "Gasto adicionado"

    rodar(monkeypatch, "listar")
    saida = capsys.readouterr().out
    assert "mercado" in saida  # categoria foi salva em minúsculas
    assert "10/08/2026" in saida

    rodar(monkeypatch, "resumo", "--mes", "2026-08")
    saida = capsys.readouterr().out
    assert "transporte" in saida
    assert "mercado" not in saida  # gasto de outro mês ficou de fora
    assert "R$ 12,50" in saida


def test_listar_sem_gastos(tmp_path, monkeypatch, capsys):
    monkeypatch.chdir(tmp_path)

    rodar(monkeypatch, "listar")

    assert "Nenhum gasto registrado" in capsys.readouterr().out


def test_listar_mostra_o_numero_de_cada_gasto(tmp_path, monkeypatch, capsys):
    monkeypatch.chdir(tmp_path)
    rodar(monkeypatch, "adicionar", "10", "mercado")
    rodar(monkeypatch, "adicionar", "20", "lazer")
    capsys.readouterr()

    rodar(monkeypatch, "listar")

    linhas = capsys.readouterr().out.splitlines()
    assert linhas[0].split()[0] == "Nº"
    assert [linha.split()[0] for linha in linhas[1:]] == ["1", "2"]


def test_remover_pela_linha_de_comando(tmp_path, monkeypatch, capsys):
    monkeypatch.chdir(tmp_path)
    rodar(monkeypatch, "adicionar", "10", "mercado")
    rodar(monkeypatch, "adicionar", "23,59", "uber")
    capsys.readouterr()

    rodar(monkeypatch, "remover", "2")
    assert "Gasto 2 removido: R$ 23,59 em uber" in capsys.readouterr().out

    rodar(monkeypatch, "listar")
    saida = capsys.readouterr().out
    assert "mercado" in saida
    assert "uber" not in saida


def test_remover_numero_inexistente_da_erro(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)

    with pytest.raises(SystemExit) as erro:
        rodar(monkeypatch, "remover", "7")

    assert "Nenhum gasto com o número 7" in str(erro.value)


def test_editar_muda_so_os_campos_informados(tmp_path, monkeypatch, capsys):
    monkeypatch.chdir(tmp_path)
    rodar(monkeypatch, "adicionar", "23,59", "uber", "ida ao centro", "--data", "2026-09-23")
    capsys.readouterr()

    rodar(monkeypatch, "editar", "1", "--valor", "25", "--categoria", "Transporte")
    assert "Gasto 1 atualizado: R$ 25,00 em transporte (23/09/2026)" in capsys.readouterr().out

    rodar(monkeypatch, "listar")
    saida = capsys.readouterr().out
    assert "ida ao centro" in saida  # descrição não foi pedida, então não mudou
    assert "uber" not in saida


def test_editar_pode_apagar_a_descricao(tmp_path, monkeypatch, capsys):
    monkeypatch.chdir(tmp_path)
    rodar(monkeypatch, "adicionar", "10", "lanche", "coxinha")

    rodar(monkeypatch, "editar", "1", "--descricao", "")
    rodar(monkeypatch, "listar")

    assert "coxinha" not in capsys.readouterr().out


def test_editar_sem_nenhum_campo_da_erro(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    rodar(monkeypatch, "adicionar", "10", "lanche")

    with pytest.raises(SystemExit) as erro:
        rodar(monkeypatch, "editar", "1")

    assert "Diga o que mudar" in str(erro.value)


def test_editar_numero_inexistente_da_erro(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)

    with pytest.raises(SystemExit) as erro:
        rodar(monkeypatch, "editar", "7", "--valor", "5")

    assert "Nenhum gasto com o número 7" in str(erro.value)


def test_exportar_cria_csv_que_o_excel_entende(tmp_path, monkeypatch, capsys):
    monkeypatch.chdir(tmp_path)
    rodar(monkeypatch, "adicionar", "30", "lanche", "almoço", "--data", "2026-09-23")
    capsys.readouterr()

    rodar(monkeypatch, "exportar", "gastos.csv")

    assert "1 gasto(s) exportado(s) para gastos.csv" in capsys.readouterr().out
    conteudo = (tmp_path / "gastos.csv").read_bytes()
    assert conteudo.startswith(b"\xef\xbb\xbf")  # a marca (BOM) que avisa ao Excel que é UTF-8
    assert "1;23/09/2026;30,00;lanche;almoço" in conteudo.decode("utf-8-sig")


def test_exportar_filtra_por_mes(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    rodar(monkeypatch, "adicionar", "10", "agosto", "--data", "2026-08-31")
    rodar(monkeypatch, "adicionar", "20", "setembro", "--data", "2026-09-01")

    rodar(monkeypatch, "exportar", "setembro.csv", "--mes", "2026-09")

    texto = (tmp_path / "setembro.csv").read_text(encoding="utf-8-sig")
    assert "setembro" in texto
    assert "agosto" not in texto


def test_exportar_nao_sobrescreve_sem_pedir(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    existente = tmp_path / "importante.csv"
    existente.write_text("não pode sumir", encoding="utf-8")

    with pytest.raises(SystemExit) as erro:
        rodar(monkeypatch, "exportar", "importante.csv")

    assert "já existe" in str(erro.value)
    assert existente.read_text(encoding="utf-8") == "não pode sumir"


def test_exportar_com_sobrescrever_substitui(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    (tmp_path / "gastos.csv").write_text("antigo", encoding="utf-8")
    rodar(monkeypatch, "adicionar", "10", "mercado")

    rodar(monkeypatch, "exportar", "gastos.csv", "--sobrescrever")

    assert "mercado" in (tmp_path / "gastos.csv").read_text(encoding="utf-8-sig")


def test_exportar_xlsx_pela_extensao(tmp_path, monkeypatch, capsys):
    monkeypatch.chdir(tmp_path)
    rodar(monkeypatch, "adicionar", "30", "lanche")
    capsys.readouterr()

    rodar(monkeypatch, "exportar", "gastos.XLSX")

    assert "1 gasto(s) exportado(s)" in capsys.readouterr().out
    assert zipfile.is_zipfile(tmp_path / "gastos.XLSX")


def test_exportar_xlsx_nao_sobrescreve_sem_pedir(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    (tmp_path / "gastos.xlsx").write_bytes(b"planilha importante")

    with pytest.raises(SystemExit):
        rodar(monkeypatch, "exportar", "gastos.xlsx")

    assert (tmp_path / "gastos.xlsx").read_bytes() == b"planilha importante"


def test_grafico_por_categoria_e_por_mes(tmp_path, monkeypatch, capsys):
    monkeypatch.chdir(tmp_path)
    rodar(monkeypatch, "adicionar", "30", "lanche", "--data", "2026-09-23")
    rodar(monkeypatch, "adicionar", "10", "uber", "--data", "2026-08-05")
    capsys.readouterr()

    rodar(monkeypatch, "grafico")
    saida = capsys.readouterr().out
    assert "Gastos por categoria" in saida
    assert "lanche" in saida and "█" in saida

    rodar(monkeypatch, "grafico", "--por", "mes")
    saida = capsys.readouterr().out
    assert saida.index("ago/2026") < saida.index("set/2026")

    rodar(monkeypatch, "grafico", "--mes", "2026-08")
    saida = capsys.readouterr().out
    assert "(2026-08)" in saida
    assert "uber" in saida and "lanche" not in saida


def test_grafico_sem_gastos(tmp_path, monkeypatch, capsys):
    monkeypatch.chdir(tmp_path)

    rodar(monkeypatch, "grafico")

    assert "Nenhum gasto encontrado" in capsys.readouterr().out


@pytest.mark.parametrize("texto, esperado", [("2026-09", "2026-09"), ("2026-9", "2026-09")])
def test_mes_valido_normaliza_com_dois_digitos(texto, esperado):
    assert mes_valido(texto) == esperado


@pytest.mark.parametrize("texto", ["setembro", "2026-13", "09-2026", "2026/09", ""])
def test_mes_valido_rejeita_formatos_errados(texto):
    with pytest.raises(argparse.ArgumentTypeError):
        mes_valido(texto)


def test_mes_sem_zero_ainda_encontra_os_gastos(tmp_path, monkeypatch, capsys):
    monkeypatch.chdir(tmp_path)
    rodar(monkeypatch, "adicionar", "10", "mercado", "--data", "2026-09-05")
    capsys.readouterr()

    rodar(monkeypatch, "resumo", "--mes", "2026-9")

    assert "mercado" in capsys.readouterr().out


def test_orcamento_definir_ver_e_remover(tmp_path, monkeypatch, capsys):
    monkeypatch.chdir(tmp_path)
    rodar(monkeypatch, "adicionar", "420", "mercado", "--data", "2026-09-10")
    rodar(monkeypatch, "adicionar", "95", "lazer", "--data", "2026-09-12")
    rodar(monkeypatch, "orcamento", "definir", "Mercado", "500")
    rodar(monkeypatch, "orcamento", "definir", "lazer", "80")
    capsys.readouterr()

    rodar(monkeypatch, "orcamento", "--mes", "2026-09")
    saida = capsys.readouterr().out
    assert "Orçamento de set/2026" in saida
    assert "ATENÇÃO: sobram R$ 80,00" in saida  # mercado (categoria salva em minúsculas)
    assert "ESTOUROU em R$ 15,00" in saida  # lazer

    rodar(monkeypatch, "orcamento", "remover", "lazer")
    assert "Orçamento de lazer removido" in capsys.readouterr().out

    rodar(monkeypatch, "orcamento", "--mes", "2026-09")
    saida = capsys.readouterr().out
    assert "lazer" not in saida
    assert "mercado" in saida


def test_orcamento_sem_mes_mostra_o_mes_atual(tmp_path, monkeypatch, capsys):
    monkeypatch.chdir(tmp_path)
    rodar(monkeypatch, "adicionar", "100", "mercado")  # data de hoje
    rodar(monkeypatch, "orcamento", "definir", "mercado", "500")
    capsys.readouterr()

    rodar(monkeypatch, "orcamento")

    saida = capsys.readouterr().out
    assert "R$ 100,00 de R$ 500,00" in saida


def test_orcamento_sem_nenhum_definido(tmp_path, monkeypatch, capsys):
    monkeypatch.chdir(tmp_path)

    rodar(monkeypatch, "orcamento")

    assert "Nenhum orçamento definido" in capsys.readouterr().out


def test_remover_orcamento_inexistente_da_erro(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)

    with pytest.raises(SystemExit) as erro:
        rodar(monkeypatch, "orcamento", "remover", "lazer")

    assert "não tem orçamento" in str(erro.value)


def test_adicionar_avisa_como_ficou_o_orcamento_do_mes(tmp_path, monkeypatch, capsys):
    monkeypatch.chdir(tmp_path)
    rodar(monkeypatch, "orcamento", "definir", "mercado", "500")
    rodar(monkeypatch, "adicionar", "300", "mercado", "--data", "2026-09-01")
    rodar(monkeypatch, "adicionar", "999", "mercado", "--data", "2026-08-15")  # outro mês
    capsys.readouterr()

    rodar(monkeypatch, "adicionar", "120", "mercado", "--data", "2026-09-10")

    assert capsys.readouterr().out.splitlines()[-1] == (
        "Orçamento de mercado em set/2026: R$ 420,00 de R$ 500,00 (84%) "
        "- ATENÇÃO: sobram R$ 80,00"
    )


def test_adicionar_em_categoria_sem_orcamento_nao_avisa(tmp_path, monkeypatch, capsys):
    monkeypatch.chdir(tmp_path)
    rodar(monkeypatch, "orcamento", "definir", "mercado", "500")
    capsys.readouterr()

    rodar(monkeypatch, "adicionar", "50", "lazer")

    assert "Orçamento" not in capsys.readouterr().out


def test_editar_avisa_quando_o_orcamento_estoura(tmp_path, monkeypatch, capsys):
    monkeypatch.chdir(tmp_path)
    rodar(monkeypatch, "orcamento", "definir", "lazer", "80")
    rodar(monkeypatch, "adicionar", "50", "lazer", "--data", "2026-09-10")
    capsys.readouterr()

    rodar(monkeypatch, "editar", "1", "--valor", "95")

    assert "ESTOUROU em R$ 15,00" in capsys.readouterr().out


# --- Gastos recorrentes ---


def fingir_hoje(monkeypatch, ano, mes, dia):
    """Faz o programa achar que hoje é outra data."""
    monkeypatch.setattr("gastos.__main__.hoje", lambda: date(ano, mes, dia))


def test_recorrente_comeca_no_mes_que_vem_se_o_dia_ja_passou(tmp_path, monkeypatch, capsys):
    monkeypatch.chdir(tmp_path)
    fingir_hoje(monkeypatch, 2026, 9, 26)

    rodar(monkeypatch, "recorrente", "adicionar", "1200", "aluguel", "--dia", "5")

    saida = capsys.readouterr().out
    assert "Gasto recorrente 1: R$ 1.200,00 em aluguel, todo dia 5" in saida
    assert "Primeiro lançamento: 05/10/2026" in saida
    assert "Lançado" not in saida


def test_recorrente_e_lancado_quando_o_dia_chega(tmp_path, monkeypatch, capsys):
    monkeypatch.chdir(tmp_path)
    fingir_hoje(monkeypatch, 2026, 9, 26)
    rodar(monkeypatch, "recorrente", "adicionar", "1200", "aluguel", "--dia", "5")
    capsys.readouterr()

    fingir_hoje(monkeypatch, 2026, 10, 4)  # véspera: nada ainda
    rodar(monkeypatch, "listar")
    assert "Lançado" not in capsys.readouterr().out

    fingir_hoje(monkeypatch, 2026, 10, 5)  # chegou o dia: qualquer comando lança
    rodar(monkeypatch, "listar")
    saida = capsys.readouterr().out
    assert "Lançado automaticamente: R$ 1.200,00 em aluguel (05/10/2026)" in saida
    assert "05/10/2026" in saida.split("DESCRIÇÃO")[1]  # e já aparece na listagem

    rodar(monkeypatch, "listar")  # mesmo dia de novo: não repete
    assert "Lançado" not in capsys.readouterr().out


def test_recorrente_lanca_os_meses_que_ficaram_sem_abrir(tmp_path, monkeypatch, capsys):
    monkeypatch.chdir(tmp_path)
    fingir_hoje(monkeypatch, 2026, 9, 26)
    rodar(monkeypatch, "recorrente", "adicionar", "39,90", "internet", "--dia", "31")
    capsys.readouterr()

    fingir_hoje(monkeypatch, 2026, 12, 1)
    rodar(monkeypatch, "resumo")

    saida = capsys.readouterr().out
    assert saida.count("Lançado automaticamente") == 3
    for data in ["30/09/2026", "31/10/2026", "30/11/2026"]:  # dia 31 em mês de 30 dias
        assert data in saida


def test_recorrente_desde_lanca_os_meses_passados_na_hora(tmp_path, monkeypatch, capsys):
    monkeypatch.chdir(tmp_path)
    fingir_hoje(monkeypatch, 2026, 9, 26)
    rodar(monkeypatch, "orcamento", "definir", "streaming", "50")
    capsys.readouterr()

    rodar(
        monkeypatch, "recorrente", "adicionar", "55,90", "streaming", "--dia", "10",
        "--desde", "2026-08",
    )

    saida = capsys.readouterr().out
    assert saida.count("Lançado automaticamente") == 2
    assert "ESTOUROU em R$ 5,90" in saida  # o alerta de orçamento também aparece


def test_recorrente_desde_muito_antigo_e_recusado(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    fingir_hoje(monkeypatch, 2026, 9, 26)

    with pytest.raises(SystemExit) as erro:
        rodar(monkeypatch, "recorrente", "adicionar", "10", "x", "--dia", "5", "--desde", "2016-09")

    assert "no máximo 12 meses" in str(erro.value)


def test_recorrente_listar_e_remover(tmp_path, monkeypatch, capsys):
    monkeypatch.chdir(tmp_path)
    fingir_hoje(monkeypatch, 2026, 9, 26)
    rodar(monkeypatch, "recorrente", "adicionar", "1200", "aluguel", "apartamento", "--dia", "5")
    capsys.readouterr()

    rodar(monkeypatch, "recorrente")
    linha = capsys.readouterr().out.splitlines()[1]
    assert linha.split() == ["1", "5", "R$", "1.200,00", "aluguel", "05/10/2026", "apartamento"]

    rodar(monkeypatch, "recorrente", "remover", "1")
    assert "removido" in capsys.readouterr().out

    fingir_hoje(monkeypatch, 2026, 10, 5)
    rodar(monkeypatch, "recorrente")
    saida = capsys.readouterr().out
    assert "Nenhum gasto recorrente" in saida
    assert "Lançado" not in saida


def test_recorrente_remover_inexistente_da_erro(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)

    with pytest.raises(SystemExit) as erro:
        rodar(monkeypatch, "recorrente", "remover", "9")

    assert "Nenhum gasto recorrente com o número 9" in str(erro.value)


@pytest.mark.parametrize("texto", ["0", "32", "-1", "cinco", ""])
def test_dia_do_mes_rejeita_invalidos(texto):
    with pytest.raises(argparse.ArgumentTypeError):
        dia_do_mes(texto)


# --- Importar extrato do Nubank ---

FATURA_NUBANK = """date,title,amount
2026-09-05,Uber *Trip,23.59
2026-09-06,Pagamento recebido,-500.00
2026-09-07,Netflix.com,55.90
"""


def test_importar_simular_nao_salva_nada(tmp_path, monkeypatch, capsys):
    monkeypatch.chdir(tmp_path)
    (tmp_path / "fatura.csv").write_text(FATURA_NUBANK, encoding="utf-8")

    rodar(monkeypatch, "importar", "fatura.csv", "--simular")
    saida = capsys.readouterr().out
    assert "Arquivo reconhecido: fatura do cartão do Nubank" in saida
    assert "+ 05/09/2026      R$ 23,59  transporte    Uber *Trip" in saida
    assert "Pagamento recebido (ignorado: pagamento ou estorno)" in saida
    assert "2 gasto(s) seriam importados" in saida and "Nada foi salvo" in saida

    rodar(monkeypatch, "listar")
    assert "Nenhum gasto registrado" in capsys.readouterr().out


def test_importar_duas_vezes_nao_duplica(tmp_path, monkeypatch, capsys):
    monkeypatch.chdir(tmp_path)
    (tmp_path / "fatura.csv").write_text(FATURA_NUBANK, encoding="utf-8-sig")  # com BOM

    rodar(monkeypatch, "importar", "fatura.csv")
    assert "2 gasto(s) importado(s), 0 já importado(s) antes, 1 ignorado(s)" in (
        capsys.readouterr().out
    )

    rodar(monkeypatch, "importar", "fatura.csv")
    saida = capsys.readouterr().out
    assert "0 gasto(s) importado(s), 2 já importado(s) antes" in saida
    assert "+ " not in saida

    rodar(monkeypatch, "resumo")
    assert "R$ 79,49" in capsys.readouterr().out  # 23,59 + 55,90, uma vez só


@pytest.mark.parametrize(
    "conteudo, mensagem",
    [
        ("numero;data;valor\n1;23/09/2026;30,00\n", "Não parece um CSV do Nubank"),
        ("date,title,amount\n2026-09-05,Uber,23.59\n2026-99-99,Erro,1\n", "linha 3"),
    ],
)
def test_importar_arquivo_com_problema_nao_importa_nada(
    tmp_path, monkeypatch, capsys, conteudo, mensagem
):
    monkeypatch.chdir(tmp_path)
    (tmp_path / "extrato.csv").write_text(conteudo, encoding="utf-8")

    with pytest.raises(SystemExit) as erro:
        rodar(monkeypatch, "importar", "extrato.csv")

    assert "Nada foi importado" in str(erro.value) and mensagem in str(erro.value)
    rodar(monkeypatch, "listar")
    assert "Nenhum gasto registrado" in capsys.readouterr().out


def test_importar_arquivo_que_nao_existe(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)

    with pytest.raises(SystemExit) as erro:
        rodar(monkeypatch, "importar", "sumiu.csv")

    assert "Arquivo não encontrado: sumiu.csv" in str(erro.value)


def test_importar_arquivo_que_nao_e_utf8(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    (tmp_path / "antigo.csv").write_bytes("date,title,amount\n2026-09-05,Açaí,10\n".encode("cp1252"))

    with pytest.raises(SystemExit) as erro:
        rodar(monkeypatch, "importar", "antigo.csv")

    assert "não está em UTF-8" in str(erro.value)
