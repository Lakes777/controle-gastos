"""Cria a aplicação FastAPI e registra as rotas."""

from pathlib import Path

from fastapi import FastAPI

from gastos.armazenamento import Banco
from gastos.web.rotas import (
    roteador_gastos,
    roteador_orcamentos,
    roteador_recorrentes,
    roteador_relatorios,
)


def criar_app(caminho_banco: Path | str) -> FastAPI:
    app = FastAPI(
        title="Controle de Gastos",
        description="Registre seus gastos, acompanhe o orçamento do mês e exporte para o Excel.",
        version="0.1.0",
    )
    # O mesmo Banco do terminal: a web e a linha de comando enxergam os mesmos gastos.
    app.state.banco = Banco(caminho_banco)
    app.include_router(roteador_gastos)
    app.include_router(roteador_relatorios)
    app.include_router(roteador_orcamentos)
    app.include_router(roteador_recorrentes)

    @app.get("/saude", tags=["sistema"])
    def saude() -> dict[str, str]:
        """Responde se a API está no ar (útil para monitoramento)."""
        return {"status": "ok"}

    return app
