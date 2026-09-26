"""Formatos dos dados: o que a API recebe e o que ela devolve.

O Pydantic valida tudo antes de chegar ao banco: valor zero, negativo ou com
três casas decimais, categoria vazia e datas inválidas são recusados com erro 422.

Os valores em reais saem como texto ("45.90"), não como número: no JSON, um
número vira float no JavaScript e poderia perder centavos.
"""

from datetime import date
from decimal import Decimal
from typing import Annotated

from pydantic import AfterValidator, BaseModel, ConfigDict, Field, PlainSerializer

# Até 2 casas decimais (centavos) e no máximo R$ 9.999.999.999,99.
# PlainSerializer: na resposta, o Decimal vira texto com o valor exato.
Reais = Annotated[
    Decimal,
    Field(gt=0, max_digits=12, decimal_places=2),
    PlainSerializer(str, return_type=str, when_used="json"),
]
ReaisResposta = Annotated[Decimal, PlainSerializer(str, return_type=str, when_used="json")]

# Igual ao terminal: "Mercado" e "mercado" são a mesma categoria.
Categoria = Annotated[str, Field(min_length=1, max_length=40), AfterValidator(str.lower)]
Descricao = Annotated[str, Field(max_length=200)]

# AAAA-MM, com o mês sempre em dois dígitos (é assim que o banco compara).
PADRAO_MES = r"^\d{4}-(0[1-9]|1[0-2])$"


class GastoNovo(BaseModel):
    """Dados para registrar um gasto."""

    model_config = ConfigDict(
        str_strip_whitespace=True,
        json_schema_extra={
            "examples": [
                {
                    "valor": "45.90",
                    "categoria": "mercado",
                    "descricao": "compras da semana",
                    "data": "2026-09-26",
                }
            ]
        },
    )

    valor: Reais
    categoria: Categoria
    descricao: Descricao = ""
    data: date | None = Field(default=None, description="Padrão: hoje")


class GastoAtualizacao(BaseModel):
    """Campos para editar um gasto. Só os enviados mudam."""

    model_config = ConfigDict(str_strip_whitespace=True)

    valor: Reais | None = None
    categoria: Categoria | None = None
    descricao: Descricao | None = None
    data: date | None = None


class GastoSalvo(BaseModel):
    id: int
    valor: ReaisResposta
    categoria: str
    descricao: str
    data: date


class TotalCategoria(BaseModel):
    categoria: str
    total: ReaisResposta
    porcentagem: int = Field(description="Parte do total do período, arredondada")


class Resumo(BaseModel):
    mes: str | None = Field(description="O mês resumido, ou None para todos os meses")
    total: ReaisResposta
    quantidade: int
    por_categoria: list[TotalCategoria] = Field(description="Da maior para a menor")


class OrcamentoNovo(BaseModel):
    limite: Reais


class SituacaoOrcamento(BaseModel):
    categoria: str
    limite: ReaisResposta
    gasto: ReaisResposta
    restante: ReaisResposta = Field(description="Negativo quando estourou")
    porcentagem: int
    nivel: str = Field(description="ok, atencao (a partir de 80%) ou estourou")
    aviso: str


class RecorrenteNovo(BaseModel):
    """Gasto que se repete todo mês, como aluguel ou assinatura."""

    model_config = ConfigDict(
        str_strip_whitespace=True,
        json_schema_extra={
            "examples": [{"valor": "1200", "categoria": "aluguel", "descricao": "", "dia": 5}]
        },
    )

    valor: Reais
    categoria: Categoria
    descricao: Descricao = ""
    dia: int = Field(ge=1, le=31, description="Em mês curto, 31 cai no último dia")
    desde: str | None = Field(
        default=None,
        pattern=PADRAO_MES,
        description="Primeiro mês (AAAA-MM). Padrão: a próxima vez que o dia chegar",
    )


class RecorrenteSalvo(BaseModel):
    id: int
    valor: ReaisResposta
    categoria: str
    descricao: str
    dia: int
    proxima_data: date
