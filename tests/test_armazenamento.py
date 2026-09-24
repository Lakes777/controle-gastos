from datetime import date
from decimal import Decimal

from gastos.armazenamento import carregar, salvar
from gastos.modelo import Gasto


def test_carregar_arquivo_inexistente_devolve_lista_vazia(tmp_path):
    assert carregar(tmp_path / "nao_existe.json") == []


def test_salvar_e_carregar_devolve_os_mesmos_gastos(tmp_path):
    caminho = tmp_path / "gastos.json"
    gastos = [
        Gasto(Decimal("45.90"), "mercado", "compras", date(2026, 9, 23)),
        Gasto(Decimal("12.50"), "transporte", "", date(2026, 9, 20)),
    ]

    salvar(gastos, caminho)

    assert carregar(caminho) == gastos


def test_salvar_cria_a_pasta_se_nao_existir(tmp_path):
    caminho = tmp_path / "pasta" / "nova" / "gastos.json"

    salvar([], caminho)

    assert caminho.exists()


def test_acentos_ficam_legiveis_no_arquivo(tmp_path):
    caminho = tmp_path / "gastos.json"

    salvar([Gasto(Decimal("30"), "alimentação", "almoço")], caminho)

    assert "almoço" in caminho.read_text(encoding="utf-8")
