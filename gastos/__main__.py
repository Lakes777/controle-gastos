"""Interface de linha de comando: python -m gastos <comando>."""

import argparse
import sys
from dataclasses import replace
from datetime import date, datetime
from decimal import Decimal, InvalidOperation

from gastos.armazenamento import Banco
from gastos.exportacao import escrever_csv, escrever_xlsx
from gastos.formatacao import formatar_reais, nome_do_mes
from gastos.grafico import desenhar, somar_por_categoria, somar_por_mes
from gastos.modelo import Gasto
from gastos.orcamento import calcular
from gastos.orcamento import desenhar as desenhar_orcamento


def valor_positivo(texto: str) -> Decimal:
    """Converte o texto digitado em Decimal, aceitando vírgula ou ponto."""
    try:
        valor = Decimal(texto.replace(",", "."))
    except InvalidOperation:
        raise argparse.ArgumentTypeError(f"valor inválido: {texto}")
    if not valor.is_finite():
        raise argparse.ArgumentTypeError(f"valor inválido: {texto}")
    if valor <= 0:
        raise argparse.ArgumentTypeError("o valor precisa ser maior que zero")
    return valor


def mes_valido(texto: str) -> str:
    """Confere o mês (AAAA-MM) e o devolve sempre com dois dígitos: 2026-9 vira 2026-09."""
    try:
        data = datetime.strptime(texto, "%Y-%m")
    except ValueError:
        raise argparse.ArgumentTypeError(f"mês inválido: {texto} (use AAAA-MM, ex.: 2026-09)")
    return f"{data.year:04d}-{data.month:02d}"


def avisar_orcamento(banco: Banco, gasto: Gasto) -> None:
    """Se a categoria do gasto tem orçamento, mostra como ficou o mês desse gasto."""
    limite = banco.listar_orcamentos().get(gasto.categoria)
    if limite is None:
        return
    [situacao] = calcular(banco.listar(mes=f"{gasto.data:%Y-%m}"), {gasto.categoria: limite})
    print(
        f"Orçamento de {situacao.categoria} em {nome_do_mes(gasto.data.year, gasto.data.month)}: "
        f"{formatar_reais(situacao.gasto)} de {formatar_reais(situacao.limite)} "
        f"({situacao.porcentagem}%) - {situacao.aviso()}"
    )


def cmd_adicionar(args: argparse.Namespace) -> None:
    banco = Banco()
    novo = banco.adicionar(
        Gasto(
            valor=args.valor,
            categoria=args.categoria.lower(),
            descricao=args.descricao,
            data=args.data,
        )
    )
    print(f"Gasto adicionado: {formatar_reais(novo.valor)} em {novo.categoria}")
    avisar_orcamento(banco, novo)


def cmd_listar(args: argparse.Namespace) -> None:
    gastos = Banco().listar()
    if not gastos:
        print("Nenhum gasto registrado ainda.")
        return

    print(f"{'Nº':>4}  {'DATA':<10}  {'VALOR':>12}  {'CATEGORIA':<12}  DESCRIÇÃO")
    for gasto in gastos:  # o banco já devolve em ordem cronológica
        print(
            f"{gasto.id:>4}  {gasto.data:%d/%m/%Y}  {formatar_reais(gasto.valor):>12}  "
            f"{gasto.categoria:<12}  {gasto.descricao}"
        )


def cmd_editar(args: argparse.Namespace) -> None:
    # Só os campos que o usuário digitou (os outros ficam None e não mudam).
    mudancas = {
        campo: valor
        for campo, valor in {
            "valor": args.valor,
            "categoria": args.categoria.lower() if args.categoria else None,
            "descricao": args.descricao,
            "data": args.data,
        }.items()
        if valor is not None
    }
    if not mudancas:
        sys.exit("Diga o que mudar: --valor, --categoria, --descricao e/ou --data")

    banco = Banco()
    gasto = banco.buscar(args.id)
    if gasto is None:
        sys.exit(f"Nenhum gasto com o número {args.id}. Veja os números com: listar")

    editado = replace(gasto, **mudancas)
    banco.atualizar(editado)
    print(
        f"Gasto {editado.id} atualizado: {formatar_reais(editado.valor)} em "
        f"{editado.categoria} ({editado.data:%d/%m/%Y})"
    )
    avisar_orcamento(banco, editado)


def cmd_exportar(args: argparse.Namespace) -> None:
    gastos = Banco().listar(mes=args.mes)
    # "x" cria o arquivo e falha se ele já existir; "w" substitui sem perguntar.
    modo = "w" if args.sobrescrever else "x"
    try:
        if args.arquivo.lower().endswith(".xlsx"):
            with open(args.arquivo, modo + "b") as arquivo:  # "b": arquivo binário (.zip)
                quantidade = escrever_xlsx(gastos, arquivo)
        else:
            # utf-8-sig: avisa ao Excel que é UTF-8 (senão "almoço" vira "almoÃ§o").
            # newline="": o módulo csv cuida das quebras de linha sozinho.
            with open(args.arquivo, modo, encoding="utf-8-sig", newline="") as arquivo:
                quantidade = escrever_csv(gastos, arquivo)
    except FileExistsError:
        sys.exit(f"O arquivo {args.arquivo} já existe. Use --sobrescrever para substituí-lo.")
    print(f"{quantidade} gasto(s) exportado(s) para {args.arquivo}")


def cmd_remover(args: argparse.Namespace) -> None:
    banco = Banco()
    gasto = banco.buscar(args.id)
    if gasto is None:
        # sys.exit com texto: mostra a mensagem como erro e sai com código 1
        sys.exit(f"Nenhum gasto com o número {args.id}. Veja os números com: listar")
    banco.remover(args.id)
    print(
        f"Gasto {gasto.id} removido: {formatar_reais(gasto.valor)} em {gasto.categoria} "
        f"({gasto.data:%d/%m/%Y})"
    )


def cmd_resumo(args: argparse.Namespace) -> None:
    gastos = Banco().listar(mes=args.mes)

    if not gastos:
        print("Nenhum gasto encontrado.")
        return

    por_categoria = sorted(somar_por_categoria(gastos))  # aqui, em ordem alfabética
    for categoria, total in por_categoria:
        print(f"{categoria:<12}  {formatar_reais(total):>12}")
    print("-" * 26)
    print(f"{'TOTAL':<12}  {formatar_reais(sum(total for _, total in por_categoria)):>12}")


def cmd_grafico(args: argparse.Namespace) -> None:
    gastos = Banco().listar(mes=args.mes)
    if not gastos:
        print("Nenhum gasto encontrado.")
        return

    if args.por == "mes":
        titulo, totais = "Gastos por mês", somar_por_mes(gastos)
    else:
        titulo, totais = "Gastos por categoria", somar_por_categoria(gastos)
    if args.mes:
        titulo += f" ({args.mes})"

    print(titulo)
    print()
    for linha in desenhar(totais):
        print(linha)


def cmd_orcamento(args: argparse.Namespace) -> None:
    banco = Banco()
    if args.acao == "definir":
        categoria = args.categoria.lower()
        banco.definir_orcamento(categoria, args.limite)
        print(f"Orçamento de {categoria}: {formatar_reais(args.limite)} por mês")
        return
    if args.acao == "remover":
        categoria = args.categoria.lower()
        if not banco.remover_orcamento(categoria):
            sys.exit(f"A categoria {categoria} não tem orçamento.")
        print(f"Orçamento de {categoria} removido")
        return

    # Sem ação: mostra a situação do mês.
    orcamentos = banco.listar_orcamentos()
    if not orcamentos:
        print("Nenhum orçamento definido. Crie um com: orcamento definir mercado 500")
        return
    mes = args.mes or f"{date.today():%Y-%m}"
    situacoes = calcular(banco.listar(mes=mes), orcamentos)
    print(f"Orçamento de {nome_do_mes(int(mes[:4]), int(mes[5:]))}")
    print()
    for linha in desenhar_orcamento(situacoes):
        print(linha)


def main() -> None:
    parser = argparse.ArgumentParser(
        prog="gastos", description="Controle de gastos pessoais no terminal."
    )
    subparsers = parser.add_subparsers(dest="comando", required=True)

    p_adicionar = subparsers.add_parser("adicionar", help="registra um novo gasto")
    p_adicionar.add_argument("valor", type=valor_positivo, help="ex.: 45.90 ou 45,90")
    p_adicionar.add_argument("categoria", help="ex.: mercado, transporte, lazer")
    p_adicionar.add_argument("descricao", nargs="?", default="", help="opcional")
    p_adicionar.add_argument(
        "--data",
        type=date.fromisoformat,
        default=date.today(),
        help="data no formato AAAA-MM-DD (padrão: hoje)",
    )
    p_adicionar.set_defaults(funcao=cmd_adicionar)

    p_listar = subparsers.add_parser("listar", help="mostra todos os gastos")
    p_listar.set_defaults(funcao=cmd_listar)

    p_editar = subparsers.add_parser("editar", help="muda dados de um gasto pelo número")
    p_editar.add_argument("id", type=int, help="o número mostrado em 'listar'")
    p_editar.add_argument("--valor", type=valor_positivo, help="novo valor")
    p_editar.add_argument("--categoria", help="nova categoria")
    p_editar.add_argument("--descricao", help='nova descrição ("" apaga a descrição)')
    p_editar.add_argument("--data", type=date.fromisoformat, help="nova data (AAAA-MM-DD)")
    p_editar.set_defaults(funcao=cmd_editar)

    p_exportar = subparsers.add_parser(
        "exportar", help="salva os gastos em planilha do Excel (.xlsx) ou CSV"
    )
    p_exportar.add_argument("arquivo", help="ex.: gastos.xlsx ou gastos.csv")
    p_exportar.add_argument("--mes", type=mes_valido, help="exporta só um mês, no formato AAAA-MM")
    p_exportar.add_argument(
        "--sobrescrever", action="store_true", help="substitui o arquivo se ele já existir"
    )
    p_exportar.set_defaults(funcao=cmd_exportar)

    p_remover = subparsers.add_parser("remover", help="apaga um gasto pelo número")
    p_remover.add_argument("id", type=int, help="o número mostrado em 'listar'")
    p_remover.set_defaults(funcao=cmd_remover)

    p_resumo = subparsers.add_parser("resumo", help="total por categoria")
    p_resumo.add_argument("--mes", type=mes_valido, help="filtra por mês no formato AAAA-MM")
    p_resumo.set_defaults(funcao=cmd_resumo)

    p_grafico = subparsers.add_parser("grafico", help="gráfico de barras dos gastos")
    p_grafico.add_argument(
        "--por",
        choices=["categoria", "mes"],
        default="categoria",
        help="agrupar por categoria (padrão) ou por mês",
    )
    p_grafico.add_argument("--mes", type=mes_valido, help="só um mês, no formato AAAA-MM")
    p_grafico.set_defaults(funcao=cmd_grafico)

    p_orcamento = subparsers.add_parser(
        "orcamento", help="limite mensal por categoria (sem ação: mostra a situação do mês)"
    )
    p_orcamento.add_argument(
        "--mes", type=mes_valido, help="mês a mostrar, no formato AAAA-MM (padrão: o atual)"
    )
    p_orcamento.set_defaults(funcao=cmd_orcamento, acao=None)
    acoes = p_orcamento.add_subparsers(dest="acao")
    p_definir = acoes.add_parser("definir", help="cria ou troca o limite de uma categoria")
    p_definir.add_argument("categoria", help="ex.: mercado")
    p_definir.add_argument("limite", type=valor_positivo, help="limite por mês, ex.: 500")
    p_remover_orc = acoes.add_parser("remover", help="apaga o orçamento de uma categoria")
    p_remover_orc.add_argument("categoria")

    args = parser.parse_args()
    args.funcao(args)


if __name__ == "__main__":
    main()
