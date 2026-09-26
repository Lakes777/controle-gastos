"""Entrada da versão online (Vercel): a Vercel procura a variável `app` neste arquivo.

Online, o app roda sempre em modo demonstração: cada visitante recebe uma cópia
própria dos dados de exemplo, num SQLite na pasta temporária do servidor.
Para usar com os seus dados, rode no seu computador: python -m gastos.web
"""

import tempfile
from pathlib import Path

from gastos.web.app import criar_app
from gastos.web.demo import Demonstracao

app = criar_app(demo=Demonstracao(Path(tempfile.gettempdir()) / "controle-gastos-demo"))
