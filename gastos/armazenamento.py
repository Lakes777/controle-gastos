"""Salva e carrega os gastos em um arquivo JSON."""

import json
from pathlib import Path

from gastos.modelo import Gasto

CAMINHO_PADRAO = Path("dados/gastos.json")


def carregar(caminho: Path = CAMINHO_PADRAO) -> list[Gasto]:
    """Lê os gastos do arquivo. Se o arquivo não existir, devolve lista vazia."""
    if not caminho.exists():
        return []

    with caminho.open(encoding="utf-8") as arquivo:
        dados = json.load(arquivo)

    return [Gasto.de_dict(item) for item in dados]


def salvar(gastos: list[Gasto], caminho: Path = CAMINHO_PADRAO) -> None:
    """Grava a lista de gastos no arquivo, criando a pasta se precisar."""
    caminho.parent.mkdir(parents=True, exist_ok=True)

    dados = [gasto.para_dict() for gasto in gastos]

    with caminho.open("w", encoding="utf-8") as arquivo:
        json.dump(dados, arquivo, ensure_ascii=False, indent=2)
