"""Entrada da versão online (Vercel): a Vercel procura a variável `app` neste arquivo.

Online, quem não entra numa conta usa a demonstração: cada visitante recebe uma
cópia própria dos dados de exemplo. Quem tem conta entra com e-mail e senha.
Tudo fica no Postgres (Neon). Variáveis de ambiente (configuradas na Vercel):
    DATABASE_URL    endereço do banco (a integração do Neon preenche sozinha)
    CODIGO_CONVITE  código para criar conta (sem ele, o cadastro fica fechado)
Para usar com os seus dados, rode no seu computador: python -m gastos.web
"""

import os

from gastos.web.app import criar_app
from gastos.web.banco_postgres import conectar
from gastos.web.contas import Autenticacao
from gastos.web.demo import Demonstracao

URL_BANCO = os.environ["DATABASE_URL"]

app = criar_app(
    demo=Demonstracao(lambda: conectar(URL_BANCO)),
    autenticacao=Autenticacao(os.environ.get("CODIGO_CONVITE")),
)
