"""Modo demonstração: cada visitante ganha uma cópia própria dos dados de exemplo.

Na versão online, qualquer pessoa pode adicionar, editar e apagar gastos. Para
um visitante não ver (nem estragar) o que outro fez, cada um recebe um cookie
com um número aleatório, e esse número é a sua conta no Postgres: toda linha
do banco diz de qual conta ela é. As contas antigas são apagadas sozinhas.

Por que Postgres e não um SQLite por visitante? A Vercel roda o servidor em
várias cópias ao mesmo tempo, cada uma com a própria pasta temporária. Pedidos
de um mesmo visitante caíam em cópias diferentes, e um gasto apagado numa
"voltava" na outra. Com um banco só, todas as cópias enxergam o mesmo.
"""

import re
import uuid
from collections.abc import Callable, Iterator
from contextlib import closing, contextmanager
from datetime import date, timedelta
from decimal import Decimal

import psycopg
from fastapi import Request, Response

from gastos.armazenamento import Banco
from gastos.modelo import Gasto
from gastos.recorrentes import Recorrente, data_no_mes
from gastos.web.banco_postgres import BancoPostgres, criar_tabelas

NOME_COOKIE = "visitante_demo"
VALIDADE = timedelta(days=1)  # depois disso, o visitante recomeça do exemplo
PADRAO_VISITANTE = re.compile(r"^[0-9a-f]{32}$")  # uuid4().hex; nada de "../" no nome do arquivo

LIMITE_GASTOS = 300  # impede que alguém encha o servidor
LIMITE_RECORRENTES = 10

# (dia, valor, categoria, descrição) de cada mês de exemplo, contando a partir do atual.
GASTOS_DE_EXEMPLO = {
    0: [
        (6, "389.90", "mercado", "compras do mês"),
        (9, "42.50", "transporte", "uber"),
        (13, "86.40", "alimentação", "ifood"),
        (19, "54.00", "lazer", "cinema"),
        (21, "112.35", "mercado", "feira e padaria"),
        (23, "38.00", "transporte", "ônibus (recarga)"),
        (25, "65.90", "alimentação", "almoço com a turma"),
    ],
    1: [
        (8, "320.00", "mercado", "compras"),
        (14, "58.00", "alimentação", "pizza"),
        (22, "140.00", "lazer", "show"),
        (27, "35.00", "transporte", "uber"),
    ],
    2: [
        (10, "298.40", "mercado", "compras"),
        (18, "72.00", "lazer", "cinema e pipoca"),
    ],
}
ORCAMENTOS_DE_EXEMPLO = {"mercado": "600", "alimentação": "180", "lazer": "150"}
RECORRENTES_DE_EXEMPLO = [(5, "1200", "aluguel", "apartamento"), (15, "99.90", "internet", "")]


def mes_anterior(mes: str, quantos: int = 1) -> str:
    ano, numero = int(mes[:4]), int(mes[5:])
    total = ano * 12 + (numero - 1) - quantos
    return f"{total // 12}-{total % 12 + 1:02d}"


def preencher_exemplos(banco: Banco | BancoPostgres, hoje: date) -> None:
    """Coloca os dados de exemplo nos últimos 3 meses, sempre relativos a hoje.

    Assim o exemplo nunca fica velho. No mês atual, um dia que ainda não
    chegou vira hoje (não há gasto no futuro).
    """
    este_mes = f"{hoje:%Y-%m}"
    for meses_atras, gastos in GASTOS_DE_EXEMPLO.items():
        mes = mes_anterior(este_mes, meses_atras)
        for dia, valor, categoria, descricao in gastos:
            data = min(data_no_mes(mes, dia), hoje)
            banco.adicionar(Gasto(Decimal(valor), categoria, descricao, data))
    for categoria, limite in ORCAMENTOS_DE_EXEMPLO.items():
        banco.definir_orcamento(categoria, Decimal(limite))
    # Recorrentes desde 2 meses atrás: são lançados já na primeira visita.
    inicio = mes_anterior(este_mes, 2)
    for dia, valor, categoria, descricao in RECORRENTES_DE_EXEMPLO:
        banco.adicionar_recorrente(Recorrente(Decimal(valor), categoria, dia, inicio, descricao))
    banco.lancar_recorrentes(hoje)


class Demonstracao:
    def __init__(self, conectar: Callable[[], psycopg.Connection], max_contas: int = 5000) -> None:
        """conectar: função que abre uma conexão nova com o Postgres."""
        self.conectar = conectar
        self.max_contas = max_contas
        with closing(conectar()) as conexao:
            criar_tabelas(conexao)

    def identificar(self, request: Request, response: Response) -> str:
        """Devolve o número do visitante; se ele ainda não tem, cria e manda no cookie."""
        visitante = request.cookies.get(NOME_COOKIE, "")
        if PADRAO_VISITANTE.fullmatch(visitante):
            return visitante
        visitante = uuid.uuid4().hex
        https = request.headers.get("x-forwarded-proto", request.url.scheme) == "https"
        response.set_cookie(
            NOME_COOKIE,
            visitante,
            max_age=int(VALIDADE.total_seconds()),
            httponly=True,  # o JavaScript da página não precisa (nem pode) ler o cookie
            samesite="lax",
            secure=https,
        )
        return visitante

    @contextmanager
    def abrir(self, visitante: str, hoje: date) -> Iterator[BancoPostgres]:
        """Abre o banco do visitante (uma conexão por pedido); na primeira vez, com os exemplos."""
        with closing(self.conectar()) as conexao:
            yield self.preparar(conexao, visitante, hoje)

    def preparar(self, conexao: psycopg.Connection, visitante: str, hoje: date) -> BancoPostgres:
        """O banco do visitante numa conexão já aberta; na primeira vez, cria a conta com os exemplos."""
        banco = BancoPostgres(conexao, visitante)
        # Criar a conta e preencher os exemplos numa transação só. Se a página faz
        # vários pedidos juntos, o segundo INSERT espera o primeiro terminar e aí
        # não faz nada (ON CONFLICT): ninguém vê uma conta pela metade.
        with conexao.transaction():
            nova = conexao.execute(
                "INSERT INTO contas (id, tipo) VALUES (%s, 'demo') "
                "ON CONFLICT DO NOTHING RETURNING id",
                (visitante,),
            ).fetchone()
            if nova:
                preencher_exemplos(banco, hoje)
            else:
                # O cookie da demo só pode abrir conta de demo, nunca a de um usuário.
                tipo = conexao.execute(
                    "SELECT tipo FROM contas WHERE id = %s", (visitante,)
                ).fetchone()["tipo"]
                if tipo != "demo":
                    raise PermissionError("o cookie da demonstração aponta para uma conta de usuário")
        if nova:
            self._apagar_antigas(conexao)
        return banco

    def _apagar_antigas(self, conexao: psycopg.Connection) -> None:
        """Apaga as contas de demonstração vencidas e, se ainda houver muitas, as mais antigas.

        Só as de demonstração (tipo = 'demo'): contas de usuários nunca são apagadas aqui.
        Os gastos, orçamentos e recorrentes vão junto (ON DELETE CASCADE).
        """
        with conexao.transaction():
            conexao.execute(
                "DELETE FROM contas WHERE tipo = 'demo' AND criada_em < now() - %s", (VALIDADE,)
            )
            conexao.execute(
                "DELETE FROM contas WHERE tipo = 'demo' AND id IN "
                "(SELECT id FROM contas WHERE tipo = 'demo' ORDER BY criada_em DESC OFFSET %s)",
                (self.max_contas,),
            )
