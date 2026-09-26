"""Rotas da API.

/gastos: registrar, listar (geral ou de um mês), ver, editar e apagar.
/resumo: total do período e total por categoria.
/orcamentos: limite mensal por categoria e a situação do mês.
/recorrentes: gastos lançados sozinhos todo mês.
/exportar: baixa os gastos em planilha do Excel (.xlsx) ou CSV.
"""

import io
from dataclasses import replace
from datetime import date, datetime
from decimal import ROUND_HALF_UP, Decimal
from typing import Literal
from zoneinfo import ZoneInfo

from fastapi import APIRouter, Depends, HTTPException, Query, Request, Response, status

from gastos.armazenamento import Banco
from gastos.exportacao import escrever_csv, escrever_xlsx
from gastos.grafico import somar_por_categoria
from gastos.modelo import Gasto
from gastos.orcamento import Situacao, calcular
from gastos.recorrentes import MESES_PARA_TRAS, Recorrente, meses_entre, primeiro_mes
from gastos.web.demo import LIMITE_GASTOS, LIMITE_RECORRENTES
from gastos.web.modelos import (
    PADRAO_MES,
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

FiltroMes = Query(default=None, pattern=PADRAO_MES, description="Só um mês, no formato AAAA-MM")


# O servidor online roda no horário UTC; às 22h de Brasília já seria "amanhã" lá.
FUSO = ZoneInfo("America/Sao_Paulo")


def hoje() -> date:
    """Data de hoje no Brasil. É uma dependência para os testes poderem fingir outra data."""
    return datetime.now(FUSO).date()


def pegar_banco(request: Request, response: Response, dia: date = Depends(hoje)) -> Banco:
    demo = request.app.state.demo
    if demo is None:
        banco: Banco = request.app.state.banco  # guardado no app ao criá-lo
    else:
        # Na demonstração, cada visitante tem o próprio banco (veja demo.py).
        banco = demo.banco(demo.identificar(request, response), dia)
    # Igual ao terminal: antes de qualquer coisa, lança os recorrentes cuja data chegou.
    banco.lancar_recorrentes(dia)
    return banco


def para_resposta(gasto: Gasto) -> GastoSalvo:
    return GastoSalvo(
        id=gasto.id,
        valor=gasto.valor,
        categoria=gasto.categoria,
        descricao=gasto.descricao,
        data=gasto.data,
    )


def buscar_ou_404(banco: Banco, gasto_id: int) -> Gasto:
    gasto = banco.buscar(gasto_id)
    if gasto is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, f"Nenhum gasto com o número {gasto_id}")
    return gasto


def conferir_limite(request: Request, quantidade: int, limite: int, o_que: str) -> None:
    """Na demonstração online, impede que alguém encha o servidor."""
    if request.app.state.demo is not None and quantidade >= limite:
        raise HTTPException(
            status.HTTP_403_FORBIDDEN,
            f"A demonstração aceita até {limite} {o_que}. Remova algum para adicionar outro.",
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
    banco: Banco = Depends(pegar_banco),
    dia: date = Depends(hoje),
) -> GastoSalvo:
    """Registra um gasto. Sem data, vale hoje."""
    conferir_limite(request, len(banco.listar()), LIMITE_GASTOS, "gastos")
    gasto = Gasto(novo.valor, novo.categoria, novo.descricao, novo.data or dia)
    return para_resposta(banco.adicionar(gasto))


@roteador_gastos.get("")
def listar(mes: str | None = FiltroMes, banco: Banco = Depends(pegar_banco)) -> list[GastoSalvo]:
    """Lista os gastos em ordem cronológica."""
    return [para_resposta(gasto) for gasto in banco.listar(mes=mes)]


@roteador_gastos.get("/{gasto_id}", responses={404: {"description": "Gasto não encontrado"}})
def ver(gasto_id: int, banco: Banco = Depends(pegar_banco)) -> GastoSalvo:
    return para_resposta(buscar_ou_404(banco, gasto_id))


@roteador_gastos.patch("/{gasto_id}", responses={404: {"description": "Gasto não encontrado"}})
def editar(
    gasto_id: int, mudancas: GastoAtualizacao, banco: Banco = Depends(pegar_banco)
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
def remover(gasto_id: int, banco: Banco = Depends(pegar_banco)) -> None:
    if not banco.remover(gasto_id):
        raise HTTPException(status.HTTP_404_NOT_FOUND, f"Nenhum gasto com o número {gasto_id}")


# ---------- Relatórios ----------


@roteador_relatorios.get("/resumo")
def resumo(mes: str | None = FiltroMes, banco: Banco = Depends(pegar_banco)) -> Resumo:
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
def meses(banco: Banco = Depends(pegar_banco)) -> list[str]:
    """Meses (AAAA-MM) que têm pelo menos um gasto, do mais recente para o mais antigo."""
    return sorted({f"{gasto.data:%Y-%m}" for gasto in banco.listar()}, reverse=True)


@roteador_relatorios.get("/categorias")
def categorias(banco: Banco = Depends(pegar_banco)) -> list[str]:
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
    banco: Banco = Depends(pegar_banco),
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
    banco: Banco = Depends(pegar_banco),
    dia: date = Depends(hoje),
) -> list[SituacaoOrcamento]:
    """Quanto já foi gasto de cada orçamento no mês."""
    mes = mes or f"{dia:%Y-%m}"
    return [para_situacao(s) for s in calcular(banco.listar(mes=mes), banco.listar_orcamentos())]


@roteador_orcamentos.put("/{categoria}")
def definir_orcamento(
    categoria: str, orcamento: OrcamentoNovo, banco: Banco = Depends(pegar_banco)
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
def remover_orcamento(categoria: str, banco: Banco = Depends(pegar_banco)) -> None:
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
def listar_recorrentes(banco: Banco = Depends(pegar_banco)) -> list[RecorrenteSalvo]:
    return [para_recorrente(r) for r in banco.listar_recorrentes()]


@roteador_recorrentes.post(
    "", status_code=status.HTTP_201_CREATED, responses={403: {"description": "Limite da demo"}}
)
def adicionar_recorrente(
    novo: RecorrenteNovo,
    request: Request,
    banco: Banco = Depends(pegar_banco),
    dia: date = Depends(hoje),
) -> RecorrenteSalvo:
    """Cria um gasto recorrente. Com "desde" no passado, os meses que já passaram entram agora."""
    conferir_limite(request, len(banco.listar_recorrentes()), LIMITE_RECORRENTES, "recorrentes")
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
def remover_recorrente(recorrente_id: int, banco: Banco = Depends(pegar_banco)) -> None:
    """Para de lançar o recorrente. Os gastos já lançados continuam."""
    if not banco.remover_recorrente(recorrente_id):
        raise HTTPException(
            status.HTTP_404_NOT_FOUND, f"Nenhum gasto recorrente com o número {recorrente_id}"
        )
