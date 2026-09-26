"""Guarda os gastos num Postgres (usado na versão online).

Tem as mesmas operações do Banco em SQLite (armazenamento.py), para as rotas não
saberem qual dos dois estão usando. A diferença é que aqui várias pessoas dividem
o mesmo banco: cada linha pertence a uma conta, e toda consulta filtra pela conta.
Hoje a conta é um visitante da demonstração; um login no futuro criaria contas
do mesmo jeito.

Online, o servidor roda em várias cópias ao mesmo tempo. Por isso o banco não pode
ficar num arquivo (cada cópia teria o seu) e o lançamento de recorrentes trava as
linhas (FOR UPDATE) para duas cópias não lançarem o mesmo mês.
"""

from collections.abc import Iterator
from contextlib import contextmanager
from dataclasses import replace
from decimal import Decimal

import psycopg
from psycopg.rows import dict_row

from gastos.modelo import Gasto
from gastos.recorrentes import Recorrente, datas_pendentes, mes_seguinte

# Número qualquer, fixo: garante que só uma cópia do servidor cria as tabelas por vez.
TRAVA_DAS_TABELAS = 20260926

CRIAR_TABELAS = [
    """
    CREATE TABLE IF NOT EXISTS contas (
        id        TEXT PRIMARY KEY,
        criada_em TIMESTAMPTZ NOT NULL DEFAULT now()
    )
    """,
    # NUMERIC(12, 2): decimal exato com centavos (o Postgres tem o tipo certo para dinheiro;
    # no SQLite, que não tem, o valor fica em texto). ON DELETE CASCADE: apagar a conta
    # apaga tudo dela junto.
    """
    CREATE TABLE IF NOT EXISTS gastos (
        id        BIGINT GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
        conta     TEXT          NOT NULL REFERENCES contas (id) ON DELETE CASCADE,
        valor     NUMERIC(12, 2) NOT NULL CHECK (valor > 0),
        categoria TEXT          NOT NULL,
        descricao TEXT          NOT NULL DEFAULT '',
        data      DATE          NOT NULL
    )
    """,
    "CREATE INDEX IF NOT EXISTS gastos_conta_data ON gastos (conta, data)",
    """
    CREATE TABLE IF NOT EXISTS orcamentos (
        conta     TEXT          NOT NULL REFERENCES contas (id) ON DELETE CASCADE,
        categoria TEXT          NOT NULL,
        limite    NUMERIC(12, 2) NOT NULL CHECK (limite > 0),
        PRIMARY KEY (conta, categoria)
    )
    """,
    """
    CREATE TABLE IF NOT EXISTS recorrentes (
        id          BIGINT GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
        conta       TEXT          NOT NULL REFERENCES contas (id) ON DELETE CASCADE,
        valor       NUMERIC(12, 2) NOT NULL CHECK (valor > 0),
        categoria   TEXT          NOT NULL,
        descricao   TEXT          NOT NULL DEFAULT '',
        dia         INTEGER       NOT NULL CHECK (dia BETWEEN 1 AND 31),
        proximo_mes TEXT          NOT NULL  -- AAAA-MM: o mês que ainda falta lançar
    )
    """,
    "CREATE INDEX IF NOT EXISTS recorrentes_conta ON recorrentes (conta)",
]


def conectar(url: str, **extras) -> psycopg.Connection:
    # autocommit: cada operação abre a própria transação (com conexao.transaction()).
    # prepare_threshold=None: o "pooler" do Neon reaproveita conexões entre clientes,
    # e comandos preparados de um poderiam não existir para o outro.
    # extras: opções a mais da conexão (os testes usam para escolher o schema).
    return psycopg.connect(
        url, autocommit=True, prepare_threshold=None, row_factory=dict_row, **extras
    )


def criar_tabelas(conexao: psycopg.Connection) -> None:
    with conexao.transaction():
        conexao.execute("SELECT pg_advisory_xact_lock(%s)", (TRAVA_DAS_TABELAS,))
        for comando in CRIAR_TABELAS:
            conexao.execute(comando)


class BancoPostgres:
    def __init__(self, conexao: psycopg.Connection, conta: str) -> None:
        self.conexao = conexao
        self.conta = conta

    @contextmanager
    def _transacao(self) -> Iterator[psycopg.Connection]:
        # Confirma no final, ou desfaz tudo se der erro. Dentro de outra transação,
        # vira um "savepoint" (uma transação dentro da outra).
        with self.conexao.transaction():
            yield self.conexao

    @staticmethod
    def _para_gasto(linha: dict) -> Gasto:
        return Gasto(
            valor=linha["valor"],  # NUMERIC já chega como Decimal
            categoria=linha["categoria"],
            descricao=linha["descricao"],
            data=linha["data"],
            id=linha["id"],
        )

    def _inserir(self, conexao: psycopg.Connection, gasto: Gasto) -> int:
        # Os valores vão por marcadores (%s), nunca colados no texto do SQL (evita SQL injection).
        linha = conexao.execute(
            "INSERT INTO gastos (conta, valor, categoria, descricao, data) "
            "VALUES (%s, %s, %s, %s, %s) RETURNING id",
            (self.conta, gasto.valor, gasto.categoria, gasto.descricao, gasto.data),
        ).fetchone()
        return linha["id"]

    # ---------- Gastos ----------

    def adicionar(self, gasto: Gasto) -> Gasto:
        with self._transacao() as conexao:
            novo_id = self._inserir(conexao, gasto)
        return replace(gasto, id=novo_id)

    def listar(self, mes: str | None = None) -> list[Gasto]:
        sql = "SELECT * FROM gastos WHERE conta = %s"
        valores: tuple = (self.conta,)
        if mes is not None:
            sql += " AND to_char(data, 'YYYY-MM') = %s"
            valores += (mes,)
        sql += " ORDER BY data, id"
        linhas = self.conexao.execute(sql, valores).fetchall()
        return [self._para_gasto(linha) for linha in linhas]

    def buscar(self, id: int) -> Gasto | None:
        linha = self.conexao.execute(
            "SELECT * FROM gastos WHERE id = %s AND conta = %s", (id, self.conta)
        ).fetchone()
        return self._para_gasto(linha) if linha else None

    def atualizar(self, gasto: Gasto) -> bool:
        with self._transacao() as conexao:
            cursor = conexao.execute(
                "UPDATE gastos SET valor = %s, categoria = %s, descricao = %s, data = %s "
                "WHERE id = %s AND conta = %s",
                (gasto.valor, gasto.categoria, gasto.descricao, gasto.data, gasto.id, self.conta),
            )
        return cursor.rowcount > 0

    def remover(self, id: int) -> bool:
        with self._transacao() as conexao:
            cursor = conexao.execute(
                "DELETE FROM gastos WHERE id = %s AND conta = %s", (id, self.conta)
            )
        return cursor.rowcount > 0

    # ---------- Orçamentos ----------

    def definir_orcamento(self, categoria: str, limite: Decimal) -> None:
        with self._transacao() as conexao:
            conexao.execute(
                "INSERT INTO orcamentos (conta, categoria, limite) VALUES (%s, %s, %s) "
                "ON CONFLICT (conta, categoria) DO UPDATE SET limite = excluded.limite",
                (self.conta, categoria, limite),
            )

    def remover_orcamento(self, categoria: str) -> bool:
        with self._transacao() as conexao:
            cursor = conexao.execute(
                "DELETE FROM orcamentos WHERE conta = %s AND categoria = %s",
                (self.conta, categoria),
            )
        return cursor.rowcount > 0

    def listar_orcamentos(self) -> dict[str, Decimal]:
        linhas = self.conexao.execute(
            "SELECT categoria, limite FROM orcamentos WHERE conta = %s ORDER BY categoria",
            (self.conta,),
        ).fetchall()
        return {linha["categoria"]: linha["limite"] for linha in linhas}

    # ---------- Recorrentes ----------

    @staticmethod
    def _para_recorrente(linha: dict) -> Recorrente:
        return Recorrente(
            valor=linha["valor"],
            categoria=linha["categoria"],
            dia=linha["dia"],
            proximo_mes=linha["proximo_mes"],
            descricao=linha["descricao"],
            id=linha["id"],
        )

    def adicionar_recorrente(self, recorrente: Recorrente) -> Recorrente:
        with self._transacao() as conexao:
            linha = conexao.execute(
                "INSERT INTO recorrentes (conta, valor, categoria, descricao, dia, proximo_mes) "
                "VALUES (%s, %s, %s, %s, %s, %s) RETURNING id",
                (
                    self.conta,
                    recorrente.valor,
                    recorrente.categoria,
                    recorrente.descricao,
                    recorrente.dia,
                    recorrente.proximo_mes,
                ),
            ).fetchone()
        return replace(recorrente, id=linha["id"])

    def listar_recorrentes(self) -> list[Recorrente]:
        linhas = self.conexao.execute(
            "SELECT * FROM recorrentes WHERE conta = %s ORDER BY dia, id", (self.conta,)
        ).fetchall()
        return [self._para_recorrente(linha) for linha in linhas]

    def remover_recorrente(self, id: int) -> bool:
        with self._transacao() as conexao:
            cursor = conexao.execute(
                "DELETE FROM recorrentes WHERE id = %s AND conta = %s", (id, self.conta)
            )
        return cursor.rowcount > 0

    def lancar_recorrentes(self, hoje) -> list[Gasto]:
        """Lança os recorrentes cuja data chegou (mesma regra do Banco em SQLite).

        FOR UPDATE trava as linhas dos recorrentes até o fim da transação. Se dois
        pedidos chegam juntos, o segundo espera o primeiro terminar e já enxerga o
        proximo_mes avançado: nenhum mês é lançado duas vezes.
        """
        lancados = []
        with self._transacao() as conexao:
            linhas = conexao.execute(
                "SELECT * FROM recorrentes WHERE conta = %s ORDER BY dia, id FOR UPDATE",
                (self.conta,),
            ).fetchall()
            for recorrente in map(self._para_recorrente, linhas):
                datas = datas_pendentes(recorrente, hoje)
                if not datas:
                    continue
                for data in datas:
                    gasto = Gasto(recorrente.valor, recorrente.categoria, recorrente.descricao, data)
                    lancados.append(replace(gasto, id=self._inserir(conexao, gasto)))
                conexao.execute(
                    "UPDATE recorrentes SET proximo_mes = %s WHERE id = %s",
                    (mes_seguinte(f"{datas[-1]:%Y-%m}"), recorrente.id),
                )
        return sorted(lancados, key=lambda g: (g.data, g.id))
