"""Testes do BancoPostgres.

Os primeiros rodam nos dois bancos (SQLite e Postgres): as rotas usam qualquer
um deles, então os dois precisam se comportar igual. Os do fim são só do
Postgres: contas separadas e vários pedidos ao mesmo tempo.
"""

import threading
from contextlib import closing
from datetime import date
from decimal import Decimal

import pytest

from gastos.armazenamento import Banco
from gastos.modelo import Gasto
from gastos.recorrentes import Recorrente
from gastos.web.banco_postgres import BancoPostgres, criar_tabelas


def criar_conta(conexao, conta):
    conexao.execute("INSERT INTO contas (id) VALUES (%s)", (conta,))


@pytest.fixture
def postgres(conectar_postgres):
    """Uma conexão com as tabelas criadas e a conta "a" pronta."""
    with closing(conectar_postgres()) as conexao:
        criar_tabelas(conexao)
        criar_conta(conexao, "a")
        yield conexao


@pytest.fixture(params=["sqlite", "postgres"])
def banco(request, tmp_path):
    if request.param == "sqlite":
        return Banco(tmp_path / "gastos.db")
    return BancoPostgres(request.getfixturevalue("postgres"), "a")


# ---------- Nos dois bancos ----------


def test_adicionar_listar_em_ordem_e_filtrar_por_mes(banco):
    banco.adicionar(Gasto(Decimal("10"), "mercado", "", date(2026, 9, 20)))
    novo = banco.adicionar(Gasto(Decimal("20.50"), "lazer", "cinema", date(2026, 8, 31)))
    banco.adicionar(Gasto(Decimal("30"), "mercado", "", date(2026, 9, 1)))

    assert novo.id is not None
    assert [g.valor for g in banco.listar()] == [Decimal("20.50"), Decimal("30"), Decimal("10")]
    assert [g.valor for g in banco.listar(mes="2026-09")] == [Decimal("30"), Decimal("10")]
    assert banco.buscar(novo.id) == novo


def test_centavos_voltam_exatos(banco):
    gasto = banco.adicionar(Gasto(Decimal("0.10"), "x", "", date(2026, 9, 1)))
    banco.adicionar(Gasto(Decimal("0.20"), "x", "", date(2026, 9, 1)))
    assert sum(g.valor for g in banco.listar()) == Decimal("0.30")
    assert isinstance(banco.buscar(gasto.id).valor, Decimal)


def test_atualizar_e_remover(banco):
    gasto = banco.adicionar(Gasto(Decimal("10"), "mercado", "", date(2026, 9, 1)))
    editado = Gasto(Decimal("15"), "lazer", "pipoca", date(2026, 9, 2), id=gasto.id)

    assert banco.atualizar(editado)
    assert banco.buscar(gasto.id) == editado
    assert banco.remover(gasto.id)
    assert banco.buscar(gasto.id) is None
    assert not banco.remover(gasto.id)
    assert not banco.atualizar(editado)


def test_orcamentos(banco):
    banco.definir_orcamento("mercado", Decimal("500"))
    banco.definir_orcamento("lazer", Decimal("100"))
    banco.definir_orcamento("mercado", Decimal("650.50"))  # troca o limite

    assert banco.listar_orcamentos() == {"lazer": Decimal("100"), "mercado": Decimal("650.50")}
    assert banco.remover_orcamento("lazer")
    assert not banco.remover_orcamento("lazer")
    assert list(banco.listar_orcamentos()) == ["mercado"]


def test_recorrentes_lancados_uma_vez_so(banco):
    rec = banco.adicionar_recorrente(Recorrente(Decimal("1200"), "aluguel", 5, "2026-08"))

    lancados = banco.lancar_recorrentes(date(2026, 9, 26))

    assert [g.data for g in lancados] == [date(2026, 8, 5), date(2026, 9, 5)]
    assert banco.lancar_recorrentes(date(2026, 9, 26)) == []
    [salvo] = banco.listar_recorrentes()
    assert salvo.proximo_mes == "2026-10"
    assert banco.remover_recorrente(rec.id)
    assert banco.listar_recorrentes() == []
    assert len(banco.listar()) == 2  # os gastos já lançados continuam


# ---------- Só no Postgres ----------


def test_cada_conta_so_ve_e_mexe_no_que_e_dela(postgres):
    criar_conta(postgres, "b")
    a, b = BancoPostgres(postgres, "a"), BancoPostgres(postgres, "b")
    gasto_de_a = a.adicionar(Gasto(Decimal("10"), "mercado", "", date(2026, 9, 1)))
    a.definir_orcamento("mercado", Decimal("100"))
    a.adicionar_recorrente(Recorrente(Decimal("5"), "x", 1, "2026-10"))

    assert b.listar() == []
    assert b.buscar(gasto_de_a.id) is None
    assert b.listar_orcamentos() == {}
    assert b.listar_recorrentes() == []
    # Mesmo sabendo o número, b não consegue editar nem apagar o gasto de a.
    assert not b.atualizar(Gasto(Decimal("1"), "hack", "", date(2026, 9, 1), id=gasto_de_a.id))
    assert not b.remover(gasto_de_a.id)
    assert a.buscar(gasto_de_a.id) == gasto_de_a


def test_apagar_a_conta_apaga_tudo_dela(postgres):
    a = BancoPostgres(postgres, "a")
    a.adicionar(Gasto(Decimal("10"), "mercado", "", date(2026, 9, 1)))
    a.definir_orcamento("mercado", Decimal("100"))
    a.adicionar_recorrente(Recorrente(Decimal("5"), "x", 1, "2026-10"))

    postgres.execute("DELETE FROM contas WHERE id = 'a'")

    for tabela in ["gastos", "orcamentos", "recorrentes"]:
        assert postgres.execute(f"SELECT count(*) AS n FROM {tabela}").fetchone()["n"] == 0


def test_valor_invalido_e_recusado_pelo_proprio_banco(postgres):
    import psycopg

    with pytest.raises(psycopg.errors.CheckViolation):
        BancoPostgres(postgres, "a").adicionar(Gasto(Decimal("-1"), "x", "", date(2026, 9, 1)))


def test_pedidos_simultaneos_nao_lancam_o_mesmo_mes_duas_vezes(postgres, conectar_postgres):
    BancoPostgres(postgres, "a").adicionar_recorrente(
        Recorrente(Decimal("1200"), "aluguel", 5, "2026-07")
    )
    comecar = threading.Barrier(8)

    def pedido():
        with closing(conectar_postgres()) as conexao:
            comecar.wait()  # todos disparam juntos, como os pedidos da página
            BancoPostgres(conexao, "a").lancar_recorrentes(date(2026, 9, 26))

    threads = [threading.Thread(target=pedido) for _ in range(8)]
    for thread in threads:
        thread.start()
    for thread in threads:
        thread.join()

    datas = [g.data for g in BancoPostgres(postgres, "a").listar()]
    assert datas == [date(2026, 7, 5), date(2026, 8, 5), date(2026, 9, 5)]


def test_criar_tabelas_de_novo_nao_estraga_nada(postgres):
    a = BancoPostgres(postgres, "a")
    a.adicionar(Gasto(Decimal("10"), "mercado", "", date(2026, 9, 1)))
    criar_tabelas(postgres)
    assert len(a.listar()) == 1
