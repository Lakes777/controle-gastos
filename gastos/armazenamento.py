"""Guarda os gastos num arquivo SQLite.

Usa o sqlite3 que já vem com o Python, com SQL escrito à mão, sem ORM.
Cada operação abre e fecha a própria conexão.
"""

import json
import sqlite3
from collections.abc import Iterator
from contextlib import closing, contextmanager
from dataclasses import replace
from datetime import date
from decimal import Decimal
from pathlib import Path

from gastos.modelo import Gasto
from gastos.recorrentes import Recorrente, datas_pendentes, mes_seguinte

CAMINHO_PADRAO = Path("dados/gastos.db")

CRIAR_TABELA = """
CREATE TABLE IF NOT EXISTS gastos (
    id        INTEGER PRIMARY KEY AUTOINCREMENT,
    valor     TEXT    NOT NULL,  -- texto, não REAL: REAL é float e perderia centavos
    categoria TEXT    NOT NULL,
    descricao TEXT    NOT NULL DEFAULT '',
    data      TEXT    NOT NULL   -- AAAA-MM-DD: em texto, a ordem alfabética é a cronológica
)
"""

CRIAR_TABELA_ORCAMENTOS = """
CREATE TABLE IF NOT EXISTS orcamentos (
    categoria TEXT PRIMARY KEY,  -- cada categoria tem no máximo um orçamento
    limite    TEXT NOT NULL      -- limite por mês; em texto pelo mesmo motivo do valor
)
"""

CRIAR_TABELA_RECORRENTES = """
CREATE TABLE IF NOT EXISTS recorrentes (
    id          INTEGER PRIMARY KEY AUTOINCREMENT,
    valor       TEXT    NOT NULL,
    categoria   TEXT    NOT NULL,
    descricao   TEXT    NOT NULL DEFAULT '',
    dia         INTEGER NOT NULL CHECK (dia BETWEEN 1 AND 31),
    proximo_mes TEXT    NOT NULL  -- AAAA-MM: o mês que ainda falta lançar
)
"""


class Banco:
    def __init__(self, caminho: Path | str = CAMINHO_PADRAO) -> None:
        self.caminho = Path(caminho)
        self.caminho.parent.mkdir(parents=True, exist_ok=True)
        with self._conectar() as conexao:
            conexao.execute(CRIAR_TABELA)
            # Bancos criados por versões antigas ganham a tabela nova aqui, sem perder nada.
            conexao.execute(CRIAR_TABELA_ORCAMENTOS)
            conexao.execute(CRIAR_TABELA_RECORRENTES)
        self._importar_json_antigo()

    @contextmanager
    def _conectar(self) -> Iterator[sqlite3.Connection]:
        with closing(sqlite3.connect(self.caminho)) as conexao:
            conexao.row_factory = sqlite3.Row  # linhas acessíveis por nome: linha["valor"]
            with conexao:  # confirma (commit) no final, ou desfaz tudo se der erro
                yield conexao

    def _importar_json_antigo(self) -> None:
        """Traz os gastos do gastos.json usado pelas versões antigas do programa.

        O arquivo não é apagado: vira gastos.json.migrado, como backup. Com o
        nome novo, a importação não acontece de novo na próxima vez.
        """
        antigo = self.caminho.with_suffix(".json")
        if not antigo.exists():
            return

        with antigo.open(encoding="utf-8") as arquivo:
            gastos = [Gasto.de_dict(item) for item in json.load(arquivo)]

        with self._conectar() as conexao:
            for gasto in gastos:
                self._inserir(conexao, gasto)
            # Renomeia ainda dentro da transação: se falhar, as inserções são
            # desfeitas e nada fica importado pela metade.
            antigo.rename(antigo.with_name(antigo.name + ".migrado"))

    @staticmethod
    def _inserir(conexao: sqlite3.Connection, gasto: Gasto) -> int:
        # Os valores vão por marcadores (?), nunca colados no texto do SQL.
        # Isso evita SQL injection.
        cursor = conexao.execute(
            "INSERT INTO gastos (valor, categoria, descricao, data) VALUES (?, ?, ?, ?)",
            (str(gasto.valor), gasto.categoria, gasto.descricao, gasto.data.isoformat()),
        )
        return cursor.lastrowid

    @staticmethod
    def _para_gasto(linha: sqlite3.Row) -> Gasto:
        return Gasto(
            valor=Decimal(linha["valor"]),
            categoria=linha["categoria"],
            descricao=linha["descricao"],
            data=date.fromisoformat(linha["data"]),
            id=linha["id"],
        )

    def adicionar(self, gasto: Gasto) -> Gasto:
        """Salva o gasto e devolve uma cópia dele com o id preenchido."""
        with self._conectar() as conexao:
            novo_id = self._inserir(conexao, gasto)
        return replace(gasto, id=novo_id)

    def listar(self, mes: str | None = None) -> list[Gasto]:
        """Devolve os gastos em ordem cronológica, de todos os meses ou de um (AAAA-MM)."""
        sql = "SELECT * FROM gastos"
        valores: tuple = ()
        if mes is not None:
            sql += " WHERE substr(data, 1, 7) = ?"  # "2026-09-23" -> "2026-09"
            valores = (mes,)
        sql += " ORDER BY data, id"
        with self._conectar() as conexao:
            linhas = conexao.execute(sql, valores).fetchall()
        return [self._para_gasto(linha) for linha in linhas]

    def buscar(self, id: int) -> Gasto | None:
        """Devolve o gasto com esse id, ou None se ele não existir."""
        with self._conectar() as conexao:
            linha = conexao.execute("SELECT * FROM gastos WHERE id = ?", (id,)).fetchone()
        return self._para_gasto(linha) if linha else None

    def atualizar(self, gasto: Gasto) -> bool:
        """Grava os novos dados do gasto. Devolve False se não havia gasto com esse id."""
        with self._conectar() as conexao:
            cursor = conexao.execute(
                "UPDATE gastos SET valor = ?, categoria = ?, descricao = ?, data = ? "
                "WHERE id = ?",
                (
                    str(gasto.valor),
                    gasto.categoria,
                    gasto.descricao,
                    gasto.data.isoformat(),
                    gasto.id,
                ),
            )
        return cursor.rowcount > 0

    def remover(self, id: int) -> bool:
        """Apaga o gasto. Devolve False se não havia gasto com esse id."""
        with self._conectar() as conexao:
            cursor = conexao.execute("DELETE FROM gastos WHERE id = ?", (id,))
        return cursor.rowcount > 0  # rowcount: quantas linhas o comando afetou

    def definir_orcamento(self, categoria: str, limite: Decimal) -> None:
        """Cria ou troca o limite mensal da categoria."""
        with self._conectar() as conexao:
            # "upsert": insere; se a categoria já existe (conflito na chave), só troca o limite.
            conexao.execute(
                "INSERT INTO orcamentos (categoria, limite) VALUES (?, ?) "
                "ON CONFLICT (categoria) DO UPDATE SET limite = excluded.limite",
                (categoria, str(limite)),
            )

    def remover_orcamento(self, categoria: str) -> bool:
        """Apaga o orçamento. Devolve False se a categoria não tinha orçamento."""
        with self._conectar() as conexao:
            cursor = conexao.execute("DELETE FROM orcamentos WHERE categoria = ?", (categoria,))
        return cursor.rowcount > 0

    def listar_orcamentos(self) -> dict[str, Decimal]:
        """Devolve {categoria: limite mensal}, em ordem alfabética."""
        with self._conectar() as conexao:
            linhas = conexao.execute("SELECT * FROM orcamentos ORDER BY categoria").fetchall()
        return {linha["categoria"]: Decimal(linha["limite"]) for linha in linhas}

    @staticmethod
    def _para_recorrente(linha: sqlite3.Row) -> Recorrente:
        return Recorrente(
            valor=Decimal(linha["valor"]),
            categoria=linha["categoria"],
            dia=linha["dia"],
            proximo_mes=linha["proximo_mes"],
            descricao=linha["descricao"],
            id=linha["id"],
        )

    def adicionar_recorrente(self, recorrente: Recorrente) -> Recorrente:
        """Salva o recorrente e devolve uma cópia dele com o id preenchido."""
        with self._conectar() as conexao:
            cursor = conexao.execute(
                "INSERT INTO recorrentes (valor, categoria, descricao, dia, proximo_mes) "
                "VALUES (?, ?, ?, ?, ?)",
                (
                    str(recorrente.valor),
                    recorrente.categoria,
                    recorrente.descricao,
                    recorrente.dia,
                    recorrente.proximo_mes,
                ),
            )
        return replace(recorrente, id=cursor.lastrowid)

    def listar_recorrentes(self) -> list[Recorrente]:
        with self._conectar() as conexao:
            linhas = conexao.execute("SELECT * FROM recorrentes ORDER BY dia, id").fetchall()
        return [self._para_recorrente(linha) for linha in linhas]

    def remover_recorrente(self, id: int) -> bool:
        """Para de lançar o recorrente. Os gastos já lançados continuam."""
        with self._conectar() as conexao:
            cursor = conexao.execute("DELETE FROM recorrentes WHERE id = ?", (id,))
        return cursor.rowcount > 0

    def lancar_recorrentes(self, hoje: date) -> list[Gasto]:
        """Lança os gastos recorrentes cuja data já chegou e devolve os que foram lançados.

        Tudo numa transação só: cada gasto é inserido junto com o avanço do
        proximo_mes. Se algo falhar no meio, nada é lançado, e nunca um mês
        é lançado duas vezes.
        """
        lancados = []
        with self._conectar() as conexao:
            linhas = conexao.execute("SELECT * FROM recorrentes ORDER BY dia, id").fetchall()
            for recorrente in map(self._para_recorrente, linhas):
                datas = datas_pendentes(recorrente, hoje)
                if not datas:
                    continue
                for data in datas:
                    gasto = Gasto(recorrente.valor, recorrente.categoria, recorrente.descricao, data)
                    lancados.append(replace(gasto, id=self._inserir(conexao, gasto)))
                conexao.execute(
                    "UPDATE recorrentes SET proximo_mes = ? WHERE id = ?",
                    (mes_seguinte(f"{datas[-1]:%Y-%m}"), recorrente.id),
                )
        return sorted(lancados, key=lambda g: (g.data, g.id))
