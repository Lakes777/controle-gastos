"""Rotas da API.

/gastos: registrar, listar (geral ou de um mês), ver, editar e apagar.
/resumo: total do período e total por categoria.
/orcamentos: limite mensal por categoria e a situação do mês.
/recorrentes: gastos lançados sozinhos todo mês.
/exportar: baixa os gastos em planilha do Excel (.xlsx) ou CSV.
/importar: lê o CSV do Nubank ou o OFX de qualquer banco, mostra a prévia e salva os gastos revisados.
/conta: cadastro (com convite), entrar, sair e excluir a conta (só na versão online).
"""

import io
from collections.abc import Iterator
from contextlib import closing
from dataclasses import replace
from datetime import date, datetime, timedelta
from decimal import ROUND_HALF_UP, Decimal
from typing import Literal
from urllib.parse import urlsplit
from zoneinfo import ZoneInfo

import psycopg
from fastapi import APIRouter, Depends, HTTPException, Query, Request, Response, status

from gastos.armazenamento import Banco
from gastos.exportacao import escrever_csv, escrever_xlsx
from gastos.grafico import somar_por_categoria
from gastos.importacao import FormatoDesconhecido, LinhaInvalida, ler_extrato
from gastos.modelo import Gasto
from gastos.orcamento import Situacao, calcular
from gastos.recorrentes import MESES_PARA_TRAS, Recorrente, meses_entre, primeiro_mes
from gastos.web.banco_postgres import BancoPostgres
from gastos.web.contas import (
    VALIDADE_SESSAO,
    CadastroFechado,
    ConviteInvalido,
    EmailJaCadastrado,
    LoginBloqueado,
    normalizar_email,
)
from gastos.web.demo import LIMITE_GASTOS, LIMITE_RECORRENTES
from gastos.web.modelos import (
    PADRAO_MES,
    Cadastro,
    ConfirmacaoSenha,
    InfoSessao,
    Login,
    IgnoradoNaImportacao,
    ItemImportado,
    PedidoImportacao,
    PreviaImportacao,
    ResultadoImportacao,
    GastoAtualizacao,
    GastoNovo,
    GastoSalvo,
    OrcamentoNovo,
    RecorrenteNovo,
    RecorrenteSalvo,
    Resumo,
    SituacaoOrcamento,
    TotalCategoria,
)

roteador_gastos = APIRouter(prefix="/gastos", tags=["gastos"])
roteador_relatorios = APIRouter(tags=["relatórios"])
roteador_orcamentos = APIRouter(prefix="/orcamentos", tags=["orçamentos"])
roteador_recorrentes = APIRouter(prefix="/recorrentes", tags=["recorrentes"])
roteador_importacao = APIRouter(prefix="/importar", tags=["importação"])
roteador_conta = APIRouter(prefix="/conta", tags=["conta"])

COOKIE_SESSAO = "sessao"
# Contas de usuário também têm limite (o banco gratuito tem pouco espaço), bem maior que o da demo.
LIMITE_GASTOS_USUARIO = 20_000
LIMITE_RECORRENTES_USUARIO = 100

# As rotas funcionam com qualquer um dos dois: os métodos têm os mesmos nomes.
QualquerBanco = Banco | BancoPostgres

FiltroMes = Query(default=None, pattern=PADRAO_MES, description="Só um mês, no formato AAAA-MM")


# O servidor online roda no horário UTC; às 22h de Brasília já seria "amanhã" lá.
FUSO = ZoneInfo("America/Sao_Paulo")


def hoje() -> date:
    """Data de hoje no Brasil. É uma dependência para os testes poderem fingir outra data."""
    return datetime.now(FUSO).date()


def conferir_origem(request: Request) -> None:
    """Recusa pedidos que alteram dados vindos de outro site (proteção contra CSRF).

    O cookie SameSite=Lax já barra a maior parte; esta conferência é uma segunda
    barreira. O navegador sempre manda o cabeçalho Origin nesses pedidos.
    """
    if request.method in ("GET", "HEAD", "OPTIONS"):
        return
    origem = request.headers.get("origin")
    if origem and urlsplit(origem).netloc != request.headers.get("host"):
        raise HTTPException(status.HTTP_403_FORBIDDEN, "Pedido de outro site recusado")


def pegar_banco(
    request: Request, response: Response, dia: date = Depends(hoje)
) -> Iterator[QualquerBanco]:
    # Com yield, o FastAPI roda o que vem depois (fechar a conexão) ao fim do pedido.
    request.state.usuario = None
    demo = request.app.state.demo
    if demo is None:
        banco = request.app.state.banco  # SQLite guardado no app ao criá-lo
        # Igual ao terminal: antes de qualquer coisa, lança os recorrentes cuja data chegou.
        banco.lancar_recorrentes(dia)
        yield banco
        return
    # Online: quem tem sessão usa a própria conta; os outros, a demonstração (veja demo.py).
    with closing(demo.conectar()) as conexao:
        token = request.cookies.get(COOKIE_SESSAO)
        usuario = request.app.state.autenticacao.conta_da_sessao(conexao, token) if token else None
        if usuario:
            request.state.usuario = usuario
            banco = BancoPostgres(conexao, usuario["id"])
        else:
            try:
                banco = demo.preparar(conexao, demo.identificar(request, response), dia)
            except PermissionError:
                raise HTTPException(status.HTTP_403_FORBIDDEN, "Cookie de demonstração inválido")
        banco.lancar_recorrentes(dia)
        yield banco


def pegar_conexao(request: Request) -> Iterator[psycopg.Connection]:
    """Conexão com o Postgres para as rotas de conta (o login só existe online)."""
    demo = request.app.state.demo
    if demo is None:
        raise HTTPException(
            status.HTTP_404_NOT_FOUND, "O login só existe na versão online (no computador, não precisa)"
        )
    with closing(demo.conectar()) as conexao:
        yield conexao


def para_resposta(gasto: Gasto) -> GastoSalvo:
    return GastoSalvo(
        id=gasto.id,
        valor=gasto.valor,
        categoria=gasto.categoria,
        descricao=gasto.descricao,
        data=gasto.data,
    )


def buscar_ou_404(banco: QualquerBanco, gasto_id: int) -> Gasto:
    gasto = banco.buscar(gasto_id)
    if gasto is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, f"Nenhum gasto com o número {gasto_id}")
    return gasto


def conferir_limite(request: Request, quantidade: int, o_que: str, novos: int = 1) -> None:
    """Na versão online, impede que alguém encha o servidor (no computador, não há limite)."""
    if request.app.state.demo is None:
        return
    usuario = request.state.usuario
    if o_que == "gastos":
        limite = LIMITE_GASTOS_USUARIO if usuario else LIMITE_GASTOS
    else:
        limite = LIMITE_RECORRENTES_USUARIO if usuario else LIMITE_RECORRENTES
    if quantidade + novos > limite:
        quem = "Sua conta" if usuario else "A demonstração"
        raise HTTPException(
            status.HTTP_403_FORBIDDEN,
            f"{quem} aceita até {limite} {o_que}. Remova algum para adicionar outro.",
        )


def porcentagem(parte: Decimal, total: Decimal) -> int:
    return int((parte / total * 100).to_integral_value(ROUND_HALF_UP)) if total else 0


# ---------- Gastos ----------


@roteador_gastos.post(
    "", status_code=status.HTTP_201_CREATED, responses={403: {"description": "Limite da demo"}}
)
def adicionar(
    novo: GastoNovo,
    request: Request,
    banco: QualquerBanco = Depends(pegar_banco),
    dia: date = Depends(hoje),
) -> GastoSalvo:
    """Registra um gasto. Sem data, vale hoje."""
    conferir_limite(request, len(banco.listar()), "gastos")
    gasto = Gasto(novo.valor, novo.categoria, novo.descricao, novo.data or dia)
    return para_resposta(banco.adicionar(gasto))


@roteador_gastos.get("")
def listar(mes: str | None = FiltroMes, banco: QualquerBanco = Depends(pegar_banco)) -> list[GastoSalvo]:
    """Lista os gastos em ordem cronológica."""
    return [para_resposta(gasto) for gasto in banco.listar(mes=mes)]


@roteador_gastos.get("/{gasto_id}", responses={404: {"description": "Gasto não encontrado"}})
def ver(gasto_id: int, banco: QualquerBanco = Depends(pegar_banco)) -> GastoSalvo:
    return para_resposta(buscar_ou_404(banco, gasto_id))


@roteador_gastos.patch("/{gasto_id}", responses={404: {"description": "Gasto não encontrado"}})
def editar(
    gasto_id: int, mudancas: GastoAtualizacao, banco: QualquerBanco = Depends(pegar_banco)
) -> GastoSalvo:
    """Muda só os campos enviados."""
    gasto = buscar_ou_404(banco, gasto_id)
    # exclude_unset: o que não veio no JSON fica de fora (e não muda).
    campos = mudancas.model_dump(exclude_unset=True)
    # Um campo enviado como null também não muda (valor, categoria e data são obrigatórios).
    editado = replace(gasto, **{nome: valor for nome, valor in campos.items() if valor is not None})
    banco.atualizar(editado)
    return para_resposta(editado)


@roteador_gastos.delete(
    "/{gasto_id}",
    status_code=status.HTTP_204_NO_CONTENT,
    responses={404: {"description": "Gasto não encontrado"}},
)
def remover(gasto_id: int, banco: QualquerBanco = Depends(pegar_banco)) -> None:
    if not banco.remover(gasto_id):
        raise HTTPException(status.HTTP_404_NOT_FOUND, f"Nenhum gasto com o número {gasto_id}")


# ---------- Relatórios ----------


@roteador_relatorios.get("/resumo")
def resumo(mes: str | None = FiltroMes, banco: QualquerBanco = Depends(pegar_banco)) -> Resumo:
    """Total do período e de cada categoria, da maior para a menor."""
    gastos = banco.listar(mes=mes)
    totais = somar_por_categoria(gastos)
    total = sum((valor for _, valor in totais), Decimal("0"))
    return Resumo(
        mes=mes,
        total=total,
        quantidade=len(gastos),
        por_categoria=[
            TotalCategoria(categoria=nome, total=valor, porcentagem=porcentagem(valor, total))
            for nome, valor in totais
        ],
    )


@roteador_relatorios.get("/meses")
def meses(banco: QualquerBanco = Depends(pegar_banco)) -> list[str]:
    """Meses (AAAA-MM) que têm pelo menos um gasto, do mais recente para o mais antigo."""
    return sorted({f"{gasto.data:%Y-%m}" for gasto in banco.listar()}, reverse=True)


@roteador_relatorios.get("/categorias")
def categorias(banco: QualquerBanco = Depends(pegar_banco)) -> list[str]:
    """Categorias já usadas (em gastos ou orçamentos), em ordem alfabética."""
    usadas = {gasto.categoria for gasto in banco.listar()} | set(banco.listar_orcamentos())
    return sorted(usadas)


@roteador_relatorios.get(
    "/exportar",
    response_class=Response,
    responses={200: {"description": "O arquivo, para baixar"}},
)
def exportar(
    formato: Literal["xlsx", "csv"] = "xlsx",
    mes: str | None = FiltroMes,
    banco: QualquerBanco = Depends(pegar_banco),
) -> Response:
    """Baixa os gastos numa planilha do Excel (.xlsx) ou em CSV."""
    gastos = banco.listar(mes=mes)
    if formato == "xlsx":
        arquivo = io.BytesIO()  # um "arquivo" na memória, sem tocar no disco
        escrever_xlsx(gastos, arquivo)
        conteudo = arquivo.getvalue()
        tipo = "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"
    else:
        texto = io.StringIO(newline="")
        escrever_csv(gastos, texto)
        # utf-8-sig: avisa ao Excel que é UTF-8 (senão "almoço" vira "almoÃ§o").
        conteudo = texto.getvalue().encode("utf-8-sig")
        tipo = "text/csv; charset=utf-8"
    nome = f"gastos-{mes}.{formato}" if mes else f"gastos.{formato}"
    # attachment: o navegador baixa o arquivo em vez de tentar abri-lo.
    return Response(
        conteudo, media_type=tipo, headers={"Content-Disposition": f'attachment; filename="{nome}"'}
    )


# ---------- Orçamentos ----------


def para_situacao(situacao: Situacao) -> SituacaoOrcamento:
    return SituacaoOrcamento(
        categoria=situacao.categoria,
        limite=situacao.limite,
        gasto=situacao.gasto,
        restante=situacao.restante,
        porcentagem=int(situacao.porcentagem),
        nivel=situacao.nivel,
        aviso=situacao.aviso(),
    )


@roteador_orcamentos.get("")
def situacao_do_mes(
    mes: str | None = Query(
        default=None, pattern=PADRAO_MES, description="AAAA-MM (padrão: o mês atual)"
    ),
    banco: QualquerBanco = Depends(pegar_banco),
    dia: date = Depends(hoje),
) -> list[SituacaoOrcamento]:
    """Quanto já foi gasto de cada orçamento no mês."""
    mes = mes or f"{dia:%Y-%m}"
    return [para_situacao(s) for s in calcular(banco.listar(mes=mes), banco.listar_orcamentos())]


@roteador_orcamentos.put("/{categoria}")
def definir_orcamento(
    categoria: str, orcamento: OrcamentoNovo, banco: QualquerBanco = Depends(pegar_banco)
) -> dict[str, str]:
    """Cria ou troca o limite mensal da categoria."""
    categoria = categoria.strip().lower()
    if not categoria:
        raise HTTPException(status.HTTP_422_UNPROCESSABLE_CONTENT, "Informe a categoria")
    banco.definir_orcamento(categoria, orcamento.limite)
    return {"categoria": categoria, "limite": str(orcamento.limite)}


@roteador_orcamentos.delete(
    "/{categoria}",
    status_code=status.HTTP_204_NO_CONTENT,
    responses={404: {"description": "A categoria não tem orçamento"}},
)
def remover_orcamento(categoria: str, banco: QualquerBanco = Depends(pegar_banco)) -> None:
    categoria = categoria.strip().lower()
    if not banco.remover_orcamento(categoria):
        raise HTTPException(status.HTTP_404_NOT_FOUND, f"A categoria {categoria} não tem orçamento")


# ---------- Recorrentes ----------


def para_recorrente(recorrente: Recorrente) -> RecorrenteSalvo:
    return RecorrenteSalvo(
        id=recorrente.id,
        valor=recorrente.valor,
        categoria=recorrente.categoria,
        descricao=recorrente.descricao,
        dia=recorrente.dia,
        proxima_data=recorrente.proxima_data,
    )


@roteador_recorrentes.get("")
def listar_recorrentes(banco: QualquerBanco = Depends(pegar_banco)) -> list[RecorrenteSalvo]:
    return [para_recorrente(r) for r in banco.listar_recorrentes()]


@roteador_recorrentes.post(
    "", status_code=status.HTTP_201_CREATED, responses={403: {"description": "Limite da demo"}}
)
def adicionar_recorrente(
    novo: RecorrenteNovo,
    request: Request,
    banco: QualquerBanco = Depends(pegar_banco),
    dia: date = Depends(hoje),
) -> RecorrenteSalvo:
    """Cria um gasto recorrente. Com "desde" no passado, os meses que já passaram entram agora."""
    conferir_limite(request, len(banco.listar_recorrentes()), "recorrentes")
    if novo.desde is None:
        proximo = primeiro_mes(novo.dia, dia)
    elif meses_entre(novo.desde, f"{dia:%Y-%m}") > MESES_PARA_TRAS:
        raise HTTPException(
            status.HTTP_422_UNPROCESSABLE_CONTENT,
            f"O início pode voltar no máximo {MESES_PARA_TRAS} meses",
        )
    else:
        proximo = novo.desde
    recorrente = banco.adicionar_recorrente(
        Recorrente(novo.valor, novo.categoria, novo.dia, proximo, novo.descricao)
    )
    banco.lancar_recorrentes(dia)
    # Relê do banco: se meses passados foram lançados, o próximo mês já avançou.
    atualizado = next(r for r in banco.listar_recorrentes() if r.id == recorrente.id)
    return para_recorrente(atualizado)


@roteador_recorrentes.delete(
    "/{recorrente_id}",
    status_code=status.HTTP_204_NO_CONTENT,
    responses={404: {"description": "Recorrente não encontrado"}},
)
def remover_recorrente(recorrente_id: int, banco: QualquerBanco = Depends(pegar_banco)) -> None:
    """Para de lançar o recorrente. Os gastos já lançados continuam."""
    if not banco.remover_recorrente(recorrente_id):
        raise HTTPException(
            status.HTTP_404_NOT_FOUND, f"Nenhum gasto recorrente com o número {recorrente_id}"
        )


# ---------- Importação do Nubank ----------

TAMANHO_MAXIMO_ARQUIVO = 2_000_000  # 2 MB: um extrato de anos ainda cabe com folga

CORPO_ARQUIVO = {
    "requestBody": {
        "required": True,
        "content": {"application/octet-stream": {"schema": {"type": "string", "format": "binary"}}},
        "description": "O arquivo baixado do banco: CSV do Nubank ou OFX (fatura do cartão ou conta)",
    }
}


async def ler_arquivo(request: Request) -> bytes:
    """Lê o arquivo enviado no corpo do pedido, como veio (bytes).

    A página manda o arquivo direto no corpo, então não é preciso formulário com
    upload (multipart) nem biblioteca a mais.
    """
    corpo = await request.body()
    if len(corpo) > TAMANHO_MAXIMO_ARQUIVO:
        raise HTTPException(
            status.HTTP_413_CONTENT_TOO_LARGE, "Arquivo grande demais (o máximo é 2 MB)"
        )
    return corpo


@roteador_importacao.post(
    "/previa",
    openapi_extra=CORPO_ARQUIVO,
    responses={
        413: {"description": "Arquivo grande demais"},
        422: {"description": "Não é um CSV do Nubank nem um OFX"},
    },
)
def previa(
    conteudo: bytes = Depends(ler_arquivo), banco: QualquerBanco = Depends(pegar_banco)
) -> PreviaImportacao:
    """Mostra o que seria importado, sem salvar nada."""
    try:
        extrato = ler_extrato(conteudo)
    except UnicodeDecodeError:
        raise HTTPException(
            status.HTTP_422_UNPROCESSABLE_CONTENT,
            "O CSV não está em UTF-8. Baixe o CSV de novo pelo Nubank.",
        )
    except (FormatoDesconhecido, LinhaInvalida) as erro:
        raise HTTPException(status.HTTP_422_UNPROCESSABLE_CONTENT, f"Nada foi importado. {erro}")

    ja_importadas = banco.origens_existentes()
    novos = [
        ItemImportado(
            origem=origem,
            valor=gasto.valor,
            categoria=gasto.categoria,
            descricao=gasto.descricao[:200],
            data=gasto.data,
        )
        for gasto, origem in extrato.itens
        if origem not in ja_importadas
    ]
    return PreviaImportacao(
        formato=extrato.nome,
        novos=novos,
        repetidos=len(extrato.itens) - len(novos),
        ignorados=[
            IgnoradoNaImportacao(data=i.data, descricao=i.descricao, valor=i.valor, motivo=i.motivo)
            for i in extrato.ignorados
        ],
    )


@roteador_importacao.post("", responses={403: {"description": "Limite da demo"}})
def importar(
    pedido: PedidoImportacao, request: Request, banco: QualquerBanco = Depends(pegar_banco)
) -> ResultadoImportacao:
    """Salva os gastos revisados na prévia (com a categoria que o usuário escolheu).

    Tudo numa transação só; um gasto cuja origem já está no banco é pulado.
    """
    conferir_limite(request, len(banco.listar()), "gastos", novos=len(pedido.itens))
    itens = [
        (Gasto(item.valor, item.categoria, item.descricao, item.data), item.origem)
        for item in pedido.itens
    ]
    importados = banco.importar(itens)
    return ResultadoImportacao(importados=len(importados), repetidos=len(itens) - len(importados))


# (dias atrás, descrição, valor) da fatura de exemplo; valores negativos são pagamento e estorno.
FATURA_DE_EXEMPLO = [
    (1, "Supermercado Condor", "184.37"),
    (2, "Uber *Trip", "23.59"),
    (2, "Uber *Trip", "23.59"),
    (4, "Ifood *Restaurante", "47.80"),
    (6, "Netflix.com", "55.90"),
    (8, "Drogaria Raia", "32.45"),
    (9, "Pagamento recebido", "-600.00"),
    (11, "Steam Games", "79.99"),
    (12, "Estorno de compra", "-15.00"),
    (14, "Posto Ipiranga", "150.00"),
]


@roteador_importacao.get("/exemplo.csv", response_class=Response)
def exemplo(dia: date = Depends(hoje)) -> Response:
    """Uma fatura do cartão de mentira, no formato do Nubank, para testar a importação."""
    linhas = ["date,title,amount"] + [
        f"{dia - timedelta(days=dias):%Y-%m-%d},{descricao},{valor}"
        for dias, descricao, valor in FATURA_DE_EXEMPLO
    ]
    return Response(
        "\n".join(linhas) + "\n",
        media_type="text/csv; charset=utf-8",
        headers={"Content-Disposition": 'attachment; filename="Nubank_exemplo.csv"'},
    )


# ---------- Conta (login) ----------


@roteador_relatorios.get("/info", tags=["sistema"])
def info(request: Request, banco: QualquerBanco = Depends(pegar_banco)) -> InfoSessao:
    """Diz à página quem está usando: a demonstração, um usuário logado ou o uso pessoal."""
    autenticacao = request.app.state.autenticacao
    usuario = request.state.usuario
    return InfoSessao(
        demo=request.app.state.demo is not None and usuario is None,
        email=usuario["email"] if usuario else None,
        cadastro=autenticacao is not None and autenticacao.cadastro_aberto,
    )


def gravar_sessao(request: Request, response: Response, token: str) -> None:
    https = request.headers.get("x-forwarded-proto", request.url.scheme) == "https"
    response.set_cookie(
        COOKIE_SESSAO,
        token,
        max_age=int(VALIDADE_SESSAO.total_seconds()),
        httponly=True,  # o JavaScript não lê o cookie (um script injetado não rouba a sessão)
        samesite="lax",  # outros sites não conseguem mandar o cookie num POST
        secure=https,  # só vai por HTTPS
    )


def usuario_logado(request: Request, conexao: psycopg.Connection = Depends(pegar_conexao)) -> dict:
    token = request.cookies.get(COOKIE_SESSAO)
    usuario = request.app.state.autenticacao.conta_da_sessao(conexao, token) if token else None
    if usuario is None:
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, "Você não está logado")
    return usuario


@roteador_conta.post(
    "/cadastro",
    status_code=status.HTTP_201_CREATED,
    responses={
        403: {"description": "Convite errado ou cadastro fechado"},
        409: {"description": "E-mail já cadastrado"},
    },
)
def cadastrar(
    dados: Cadastro,
    request: Request,
    response: Response,
    conexao: psycopg.Connection = Depends(pegar_conexao),
) -> dict[str, str]:
    """Cria a conta (precisa do código de convite) e já entra nela."""
    autenticacao = request.app.state.autenticacao
    try:
        conta = autenticacao.cadastrar(conexao, dados.email, dados.senha, dados.convite)
    except CadastroFechado:
        raise HTTPException(status.HTTP_403_FORBIDDEN, "O cadastro está fechado")
    except ConviteInvalido:
        raise HTTPException(status.HTTP_403_FORBIDDEN, "Código de convite errado")
    except EmailJaCadastrado:
        raise HTTPException(status.HTTP_409_CONFLICT, "Já existe uma conta com esse e-mail")
    gravar_sessao(request, response, autenticacao.criar_sessao(conexao, conta))
    return {"email": normalizar_email(dados.email)}


@roteador_conta.post(
    "/entrar",
    responses={
        401: {"description": "E-mail ou senha incorretos"},
        429: {"description": "Tentativas demais"},
    },
)
def entrar(
    dados: Login,
    request: Request,
    response: Response,
    conexao: psycopg.Connection = Depends(pegar_conexao),
) -> dict[str, str]:
    autenticacao = request.app.state.autenticacao
    try:
        conta = autenticacao.entrar(conexao, dados.email, dados.senha)
    except LoginBloqueado:
        raise HTTPException(
            status.HTTP_429_TOO_MANY_REQUESTS,
            "Muitas tentativas com senha errada. Espere 15 minutos e tente de novo.",
        )
    if conta is None:
        # A mesma mensagem para e-mail inexistente e senha errada.
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, "E-mail ou senha incorretos")
    gravar_sessao(request, response, autenticacao.criar_sessao(conexao, conta))
    return {"email": normalizar_email(dados.email)}


@roteador_conta.post("/sair", status_code=status.HTTP_204_NO_CONTENT)
def sair(
    request: Request, response: Response, conexao: psycopg.Connection = Depends(pegar_conexao)
) -> None:
    """Encerra a sessão no servidor (o cookie antigo deixa de valer) e apaga o cookie."""
    token = request.cookies.get(COOKIE_SESSAO)
    if token:
        request.app.state.autenticacao.sair(conexao, token)
    response.delete_cookie(COOKIE_SESSAO)


@roteador_conta.get("", responses={401: {"description": "Não está logado"}})
def minha_conta(usuario: dict = Depends(usuario_logado)) -> dict[str, str]:
    return {"email": usuario["email"]}


@roteador_conta.post(
    "/excluir",
    status_code=status.HTTP_204_NO_CONTENT,
    responses={401: {"description": "Não está logado"}, 403: {"description": "Senha errada"}},
)
def excluir_conta(
    dados: ConfirmacaoSenha,
    request: Request,
    response: Response,
    usuario: dict = Depends(usuario_logado),
    conexao: psycopg.Connection = Depends(pegar_conexao),
) -> None:
    """Apaga a conta e todos os dados dela. Pede a senha de novo, por segurança."""
    autenticacao = request.app.state.autenticacao
    if not autenticacao.conferir_senha(conexao, usuario["id"], dados.senha):
        raise HTTPException(status.HTTP_403_FORBIDDEN, "Senha errada")
    autenticacao.excluir_conta(conexao, usuario["id"])
    response.delete_cookie(COOKIE_SESSAO)
