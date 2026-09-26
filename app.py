"""Entrada da versão online (Vercel): a Vercel procura a variável `app` neste arquivo.

Online, o app roda sempre em modo demonstração: cada visitante recebe uma cópia
própria dos dados de exemplo, guardada no Postgres (Neon). A Vercel entrega o
endereço do banco na variável de ambiente DATABASE_URL.
Para usar com os seus dados, rode no seu computador: python -m gastos.web
"""

import os

from gastos.web.app import criar_app
from gastos.web.banco_postgres import conectar
from gastos.web.demo import Demonstracao

URL_BANCO = os.environ["DATABASE_URL"]

app = criar_app(demo=Demonstracao(lambda: conectar(URL_BANCO)))
