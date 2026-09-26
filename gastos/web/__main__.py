"""Ponto de entrada: python -m gastos.web

Configuração por variáveis de ambiente (todas opcionais):
    GASTOS_BANCO  arquivo do banco (padrão: dados/gastos.db, o mesmo do terminal)
    GASTOS_DEMO   "1" liga o modo demonstração (cada visitante com dados de exemplo)
    HOST e PORT   endereço e porta (padrão: 127.0.0.1 e 8000)
"""

import os
import tempfile
from pathlib import Path

import uvicorn

from gastos.armazenamento import CAMINHO_PADRAO
from gastos.web.app import criar_app
from gastos.web.demo import Demonstracao


def main() -> None:
    caminho_banco = os.environ.get("GASTOS_BANCO", str(CAMINHO_PADRAO))
    host = os.environ.get("HOST", "127.0.0.1")
    porta = int(os.environ.get("PORT", "8000"))

    if os.environ.get("GASTOS_DEMO", "").lower() in {"1", "true", "sim"}:
        pasta = Path(tempfile.gettempdir()) / "controle-gastos-demo"
        print(f"Modo demonstração: bancos dos visitantes em {pasta}")
        app = criar_app(demo=Demonstracao(pasta))
    else:
        print(f"Gastos salvos em: {os.path.abspath(caminho_banco)}")
        app = criar_app(caminho_banco)
    print(f"Abra http://{host}:{porta} no navegador (Ctrl+C para parar).")
    uvicorn.run(app, host=host, port=porta)


if __name__ == "__main__":
    main()
