"""Ponto de entrada: python -m gastos.web

Configuração por variáveis de ambiente (todas opcionais):
    GASTOS_BANCO  arquivo do banco (padrão: dados/gastos.db, o mesmo do terminal)
    HOST e PORT   endereço e porta (padrão: 127.0.0.1 e 8000)
"""

import os

import uvicorn

from gastos.armazenamento import CAMINHO_PADRAO
from gastos.web.app import criar_app


def main() -> None:
    caminho_banco = os.environ.get("GASTOS_BANCO", str(CAMINHO_PADRAO))
    host = os.environ.get("HOST", "127.0.0.1")
    porta = int(os.environ.get("PORT", "8000"))

    print(f"Gastos salvos em: {os.path.abspath(caminho_banco)}")
    print(f"Abra http://{host}:{porta} no navegador (Ctrl+C para parar).")
    uvicorn.run(criar_app(caminho_banco), host=host, port=porta)


if __name__ == "__main__":
    main()
