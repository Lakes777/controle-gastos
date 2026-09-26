"""Modo demonstração: cada visitante ganha uma cópia própria dos dados de exemplo.

Na versão online, qualquer pessoa pode adicionar, editar e apagar gastos. Para
um visitante não ver (nem estragar) o que outro fez, cada um recebe um cookie
com um número aleatório, e esse número aponta para um banco SQLite só dele,
numa pasta temporária. Os bancos antigos são apagados sozinhos.

O servidor da Vercel apaga a pasta temporária de tempos em tempos; aí os dados
voltam ao exemplo. Para uma demonstração, é exatamente o que se quer.
"""

import os
import re
import time
import uuid
from datetime import date, timedelta
from decimal import Decimal
from pathlib import Path

from fastapi import Request, Response

from gastos.armazenamento import Banco
from gastos.modelo import Gasto
from gastos.recorrentes import Recorrente, data_no_mes

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


def preencher_exemplos(banco: Banco, hoje: date) -> None:
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
    def __init__(self, pasta: Path | str, max_bancos: int = 500) -> None:
        self.pasta = Path(pasta)
        self.max_bancos = max_bancos

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

    def banco(self, visitante: str, hoje: date) -> Banco:
        """O banco do visitante; na primeira vez, criado já com os exemplos."""
        caminho = self.pasta / f"{visitante}.db"
        if not caminho.exists():
            self._apagar_antigos()
            # Preenche num arquivo provisório e só depois dá o nome final (os.replace
            # é atômico): dois pedidos ao mesmo tempo nunca veem um banco pela metade.
            provisorio = self.pasta / f"{visitante}-{uuid.uuid4().hex}.criando"
            preencher_exemplos(Banco(provisorio), hoje)
            os.replace(provisorio, caminho)
        return Banco(caminho)

    def _apagar_antigos(self) -> None:
        """Apaga os bancos vencidos e, se ainda houver muitos, os mais antigos."""
        if not self.pasta.exists():
            return
        bancos = sorted(self.pasta.glob("*.db"), key=lambda c: c.stat().st_mtime)
        limite = time.time() - VALIDADE.total_seconds()
        for indice, caminho in enumerate(bancos):
            if caminho.stat().st_mtime < limite or len(bancos) - indice >= self.max_bancos:
                caminho.unlink(missing_ok=True)
