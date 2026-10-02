"""Cria a aplicação FastAPI e registra as rotas."""

from pathlib import Path

from fastapi import Depends, FastAPI, Request
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles

from gastos.armazenamento import Banco
from gastos.web.contas import Autenticacao
from gastos.web.demo import Demonstracao
from gastos.web.rotas import (
    conferir_origem,
    roteador_conta,
    roteador_gastos,
    roteador_importacao,
    roteador_orcamentos,
    roteador_recorrentes,
    roteador_relatorios,
)

PASTA_STATIC = Path(__file__).parent / "static"


def criar_app(
    caminho_banco: Path | str | None = None,
    demo: Demonstracao | None = None,
    autenticacao: Autenticacao | None = None,
) -> FastAPI:
    """Cria o app para uso pessoal (SQLite, sem login) ou online (Postgres: demonstração
    para visitantes e contas de usuário com login)."""
    if (caminho_banco is None) == (demo is None):
        raise ValueError("Informe o caminho do banco ou a demonstração (um dos dois)")
    if autenticacao is not None and demo is None:
        raise ValueError("O login só existe na versão online (com a demonstração)")
    app = FastAPI(
        title="Spendwise",
        description="Registre seus gastos, acompanhe o orçamento do mês e exporte para o Excel.",
        version="0.1.0",
    )
    # O mesmo Banco do terminal: a web e a linha de comando enxergam os mesmos gastos.
    app.state.banco = Banco(caminho_banco) if caminho_banco is not None else None
    app.state.demo = demo
    # Online, sempre há login (sem código de convite, o cadastro fica fechado).
    app.state.autenticacao = autenticacao or (Autenticacao(None) if demo else None)
    # Toda rota confere se o pedido veio da própria página (proteção contra CSRF).
    protecao = [Depends(conferir_origem)]
    for roteador in [
        roteador_gastos,
        roteador_relatorios,
        roteador_orcamentos,
        roteador_recorrentes,
        roteador_importacao,
        roteador_conta,
    ]:
        app.include_router(roteador, dependencies=protecao)

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

    return app
