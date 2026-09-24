"""Define o que é um gasto."""

from dataclasses import dataclass, field
from datetime import date
from decimal import Decimal


@dataclass
class Gasto:
    valor: Decimal
    categoria: str
    descricao: str = ""
    data: date = field(default_factory=date.today)

    def para_dict(self) -> dict:
        """Converte o gasto num dicionário simples, pronto para virar JSON."""
        return {
            "valor": str(self.valor),
            "categoria": self.categoria,
            "descricao": self.descricao,
            "data": self.data.isoformat(),
        }

    @classmethod
    def de_dict(cls, dados: dict) -> "Gasto":
        """Cria um gasto a partir de um dicionário lido do JSON."""
        return cls(
            valor=Decimal(dados["valor"]),
            categoria=dados["categoria"],
            descricao=dados.get("descricao", ""),
            data=date.fromisoformat(dados["data"]),
        )
