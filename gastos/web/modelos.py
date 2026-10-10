"""Formatos dos dados: o que a API recebe e o que ela devolve.

O Pydantic valida tudo antes de chegar ao banco: valor zero, negativo ou com
três casas decimais, categoria vazia e datas inválidas são recusados com erro 422.

Os valores em reais saem como texto ("45.90"), não como número: no JSON, um
número vira float no JavaScript e poderia perder centavos.
"""

from datetime import date, datetime
from decimal import Decimal
from typing import Annotated

from pydantic import AfterValidator, BaseModel, BeforeValidator, ConfigDict, Field, PlainSerializer

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


class TotalOrcamento(BaseModel):
    """Todas as categorias com orçamento somadas, para o anel do Resumo."""

    limite: ReaisResposta
    gasto: ReaisResposta
    restante: ReaisResposta = Field(description="Negativo quando estourou")
    porcentagem: int
    nivel: str = Field(
        description="ok, atencao (a partir de 80% ou com alguma categoria estourada) ou estourou"
    )
    categorias: int = Field(description="Quantas categorias têm orçamento")
    estouradas: list[str] = Field(description="Categorias que passaram do limite")


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


class ItemImportado(BaseModel):
    """Um gasto do extrato: na prévia (sugestão) e no pedido de importação (revisado)."""

    model_config = ConfigDict(str_strip_whitespace=True)

    origem: str = Field(
        min_length=1, max_length=300, description="Identifica a linha do extrato (evita repetir)"
    )
    valor: Reais
    categoria: Categoria
    descricao: Descricao = ""
    data: date
    lembrada: bool = Field(
        default=False, description="Na prévia: a categoria é a que o usuário já deu a essa loja"
    )


class IgnoradoNaImportacao(BaseModel):
    data: date
    descricao: str
    valor: ReaisResposta
    motivo: str


class PreviaImportacao(BaseModel):
    formato: str = Field(description="Ex.: extrato da conta do Inter (OFX)")
    novos: list[ItemImportado] = Field(description="Ainda não importados; a categoria é um palpite")
    repetidos: int = Field(description="Já importados antes (ficam de fora)")
    ignorados: list[IgnoradoNaImportacao] = Field(description="Não são gastos, com o motivo")


class PedidoImportacao(BaseModel):
    itens: list[ItemImportado] = Field(max_length=2000)


class MeuNome(BaseModel):
    nome: str = Field(max_length=200, description="Nome e sobrenome, como aparecem no extrato")


class ResultadoImportacao(BaseModel):
    importados: int
    repetidos: int = Field(description="Já estavam no banco e foram pulados")


# ---------- Conta (login) ----------

# O e-mail perde os espaços das pontas (o teclado do celular costuma pôr um no fim).
# A senha, não: ela é conferida exatamente como foi digitada.
Email = Annotated[
    str,
    BeforeValidator(lambda texto: texto.strip() if isinstance(texto, str) else texto),
    Field(max_length=254, pattern=r"^[^@\s]+@[^@\s]+\.[^@\s]+$"),
]
# Mínimo de 8 caracteres; o máximo evita que alguém mande um texto gigante para o argon2.
Senha = Annotated[str, Field(min_length=8, max_length=128)]


class Cadastro(BaseModel):
    email: Email
    senha: Senha
    convite: str = Field(max_length=200)


class Login(BaseModel):
    email: Annotated[str, BeforeValidator(str.strip), Field(max_length=254)]
    senha: str = Field(max_length=128)


class ConfirmacaoSenha(BaseModel):
    senha: str = Field(max_length=128)


class InfoSessao(BaseModel):
    demo: bool = Field(description="Quem está usando é um visitante da demonstração")
    email: str | None = Field(description="E-mail do usuário logado, se houver")
    cadastro: bool = Field(description="Dá para criar conta (o servidor tem código de convite)")


# ---------- Chaves de acesso ----------


class ChaveNova(BaseModel):
    model_config = ConfigDict(str_strip_whitespace=True)

    nome: str = Field(
        min_length=1, max_length=60, description='Para lembrar onde a chave é usada (ex.: "Bot do Telegram")'
    )


class ChaveSalva(BaseModel):
    """Uma chave na lista: nunca traz o token, só o nome e as datas."""

    id: int
    nome: str
    criada_em: datetime
    usada_em: datetime | None = Field(description="Último pedido feito com a chave (null: nunca usada)")


class ChaveCriada(ChaveSalva):
    token: str = Field(description="A chave em si. Aparece só agora: o servidor guarda apenas o hash dela")
