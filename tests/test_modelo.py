from datetime import date
from decimal import Decimal

from gastos.modelo import Gasto


def test_campos_opcionais_tem_valor_padrao():
    gasto = Gasto(Decimal("10"), "mercado")

    assert gasto.descricao == ""
    assert gasto.data == date.today()


def test_para_dict_converte_para_texto():
    gasto = Gasto(Decimal("45.90"), "mercado", "compras", date(2026, 9, 23))

    assert gasto.para_dict() == {
        "valor": "45.90",
        "categoria": "mercado",
        "descricao": "compras",
        "data": "2026-09-23",
    }


def test_ida_e_volta_pelo_dict_devolve_o_mesmo_gasto():
    original = Gasto(Decimal("12.50"), "transporte", "uber", date(2026, 9, 20))

    copia = Gasto.de_dict(original.para_dict())

    assert copia == original


def test_de_dict_sem_descricao_usa_texto_vazio():
    gasto = Gasto.de_dict({"valor": "5", "categoria": "lanche", "data": "2026-01-01"})

    assert gasto.descricao == ""
