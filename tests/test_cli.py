import argparse
import sys
import zipfile
from decimal import Decimal

import pytest

from gastos.__main__ import formatar_reais, main, mes_valido, valor_positivo


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
