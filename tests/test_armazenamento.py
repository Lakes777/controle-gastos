import json
from datetime import date
from decimal import Decimal

import pytest

from gastos.armazenamento import Banco
from gastos.modelo import Gasto


def test_banco_novo_comeca_vazio(tmp_path):
    assert Banco(tmp_path / "gastos.db").listar() == []


def test_cria_a_pasta_se_nao_existir(tmp_path):
    caminho = tmp_path / "pasta" / "nova" / "gastos.db"

    Banco(caminho)

    assert caminho.exists()


def test_adicionar_devolve_o_gasto_com_id(tmp_path):
    banco = Banco(tmp_path / "gastos.db")

    primeiro = banco.adicionar(Gasto(Decimal("10"), "mercado"))
    segundo = banco.adicionar(Gasto(Decimal("20"), "lazer"))

    assert primeiro.id == 1
    assert segundo.id == 2


def test_dados_continuam_la_ao_abrir_de_novo(tmp_path):
    caminho = tmp_path / "gastos.db"
    salvo = Banco(caminho).adicionar(
        Gasto(Decimal("45.90"), "alimentação", "almoço", date(2026, 9, 23))
    )

    assert Banco(caminho).listar() == [salvo]


def test_valor_volta_exato_sem_erro_de_float(tmp_path):
    banco = Banco(tmp_path / "gastos.db")
    banco.adicionar(Gasto(Decimal("0.10"), "a"))
    banco.adicionar(Gasto(Decimal("0.20"), "b"))

    total = sum(gasto.valor for gasto in banco.listar())

    assert total == Decimal("0.30")


def test_listar_em_ordem_cronologica(tmp_path):
    banco = Banco(tmp_path / "gastos.db")
    banco.adicionar(Gasto(Decimal("1"), "c", data=date(2026, 9, 30)))
    banco.adicionar(Gasto(Decimal("2"), "a", data=date(2026, 1, 5)))
    banco.adicionar(Gasto(Decimal("3"), "b", data=date(2026, 9, 1)))

    datas = [gasto.data for gasto in banco.listar()]

    assert datas == sorted(datas)


def test_listar_filtra_por_mes(tmp_path):
    banco = Banco(tmp_path / "gastos.db")
    banco.adicionar(Gasto(Decimal("1"), "agosto", data=date(2026, 8, 31)))
    banco.adicionar(Gasto(Decimal("2"), "setembro", data=date(2026, 9, 1)))
    banco.adicionar(Gasto(Decimal("3"), "ano passado", data=date(2025, 9, 15)))

    categorias = [gasto.categoria for gasto in banco.listar(mes="2026-09")]

    assert categorias == ["setembro"]


# --- Migração do gastos.json das versões antigas ---


def criar_json_antigo(pasta, itens):
    caminho = pasta / "gastos.json"
    caminho.write_text(json.dumps(itens, ensure_ascii=False), encoding="utf-8")
    return caminho


def test_importa_os_gastos_do_json_antigo(tmp_path):
    criar_json_antigo(
        tmp_path,
        [
            {"valor": "45.90", "categoria": "mercado", "descricao": "compras", "data": "2026-09-23"},
            {"valor": "12.50", "categoria": "transporte", "data": "2026-09-20"},
        ],
    )

    gastos = Banco(tmp_path / "gastos.db").listar()

    assert gastos == [
        Gasto(Decimal("12.50"), "transporte", "", date(2026, 9, 20), id=2),
        Gasto(Decimal("45.90"), "mercado", "compras", date(2026, 9, 23), id=1),
    ]


def test_json_antigo_vira_backup_e_nao_e_importado_duas_vezes(tmp_path):
    antigo = criar_json_antigo(
        tmp_path, [{"valor": "5", "categoria": "lanche", "data": "2026-01-01"}]
    )

    Banco(tmp_path / "gastos.db")
    banco = Banco(tmp_path / "gastos.db")  # abre de novo

    assert not antigo.exists()
    assert (tmp_path / "gastos.json.migrado").exists()
    assert len(banco.listar()) == 1


def test_json_quebrado_nao_importa_nada_pela_metade(tmp_path):
    antigo = criar_json_antigo(
        tmp_path,
        [
            {"valor": "5", "categoria": "lanche", "data": "2026-01-01"},
            {"valor": "7", "categoria": "sem data"},  # falta a data
        ],
    )

    with pytest.raises(KeyError):
        Banco(tmp_path / "gastos.db")

    assert antigo.exists()  # o original continua lá, intacto
    antigo.unlink()
    assert Banco(tmp_path / "gastos.db").listar() == []


# --- Buscar e remover ---


def test_buscar_devolve_o_gasto_ou_none(tmp_path):
    banco = Banco(tmp_path / "gastos.db")
    salvo = banco.adicionar(Gasto(Decimal("10"), "mercado"))

    assert banco.buscar(salvo.id) == salvo
    assert banco.buscar(999) is None


def test_remover_apaga_so_o_gasto_escolhido(tmp_path):
    banco = Banco(tmp_path / "gastos.db")
    fica = banco.adicionar(Gasto(Decimal("10"), "fica"))
    sai = banco.adicionar(Gasto(Decimal("20"), "sai"))

    assert banco.remover(sai.id) is True
    assert banco.listar() == [fica]


def test_remover_id_inexistente_devolve_false(tmp_path):
    assert Banco(tmp_path / "gastos.db").remover(999) is False


def test_numero_de_gasto_removido_nao_e_reaproveitado(tmp_path):
    banco = Banco(tmp_path / "gastos.db")
    banco.adicionar(Gasto(Decimal("1"), "a"))
    ultimo = banco.adicionar(Gasto(Decimal("2"), "b"))
    banco.remover(ultimo.id)

    novo = banco.adicionar(Gasto(Decimal("3"), "c"))

    assert novo.id == ultimo.id + 1
