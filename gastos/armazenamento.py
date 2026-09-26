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


class Banco:
    def __init__(self, caminho: Path | str = CAMINHO_PADRAO) -> None:
        self.caminho = Path(caminho)
        self.caminho.parent.mkdir(parents=True, exist_ok=True)
        with self._conectar() as conexao:
            conexao.execute(CRIAR_TABELA)
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
