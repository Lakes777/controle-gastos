"""Cria a aplicação FastAPI e registra as rotas."""

from pathlib import Path

from fastapi import FastAPI, Request
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles

from gastos.armazenamento import Banco
from gastos.web.demo import Demonstracao
from gastos.web.rotas import (
    roteador_gastos,
    roteador_orcamentos,
    roteador_recorrentes,
    roteador_relatorios,
)

PASTA_STATIC = Path(__file__).parent / "static"


def criar_app(caminho_banco: Path | str | None = None, demo: Demonstracao | None = None) -> FastAPI:
    """Cria o app com um banco (uso pessoal) ou em modo demonstração (um banco por visitante)."""
    if (caminho_banco is None) == (demo is None):
        raise ValueError("Informe o caminho do banco ou a demonstração (um dos dois)")
    app = FastAPI(
        title="Controle de Gastos",
        description="Registre seus gastos, acompanhe o orçamento do mês e exporte para o Excel.",
        version="0.1.0",
    )
    # O mesmo Banco do terminal: a web e a linha de comando enxergam os mesmos gastos.
    app.state.banco = Banco(caminho_banco) if caminho_banco is not None else None
    app.state.demo = demo
    app.include_router(roteador_gastos)
    app.include_router(roteador_relatorios)
    app.include_router(roteador_orcamentos)
    app.include_router(roteador_recorrentes)

    # A página (HTML, CSS e JS) é servida pela própria API: um só servidor para tudo.
    app.mount("/static", StaticFiles(directory=PASTA_STATIC), name="static")

    @app.get("/", include_in_schema=False)
    def inicio(request: Request) -> FileResponse:
        pagina = FileResponse(PASTA_STATIC / "index.html")
        if demo is not None:
            # O cookie do visitante já vai com a página. Sem isso, os primeiros pedidos
            # da página (que saem todos juntos) criariam um visitante novo cada um.
            demo.identificar(request, pagina)
        return pagina

    @app.get("/saude", tags=["sistema"])
    def saude() -> dict[str, str]:
        """Responde se a API está no ar (útil para monitoramento)."""
        return {"status": "ok"}

    @app.get("/info", tags=["sistema"])
    def info() -> dict[str, bool]:
        """Diz se a API está em modo demonstração (a página mostra um aviso)."""
        return {"demo": demo is not None}

    return app
