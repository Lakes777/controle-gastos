import argparse
import sys
from decimal import Decimal

import pytest

from gastos.__main__ import formatar_reais, main, valor_positivo


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
