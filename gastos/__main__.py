"""Interface de linha de comando: python -m gastos <comando>."""

import argparse
import sys
from collections import defaultdict
from datetime import date
from decimal import Decimal, InvalidOperation

from gastos.armazenamento import Banco
from gastos.modelo import Gasto


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


def formatar_reais(valor: Decimal) -> str:
    """Formata 1234.5 como 'R$ 1.234,50'."""
    texto = f"{valor:,.2f}"
    texto = texto.replace(",", "_").replace(".", ",").replace("_", ".")
    return f"R$ {texto}"


def cmd_adicionar(args: argparse.Namespace) -> None:
    novo = Banco().adicionar(
        Gasto(
            valor=args.valor,
            categoria=args.categoria.lower(),
            descricao=args.descricao,
            data=args.data,
        )
    )
    print(f"Gasto adicionado: {formatar_reais(novo.valor)} em {novo.categoria}")


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

    por_categoria: dict[str, Decimal] = defaultdict(Decimal)
    for gasto in gastos:
        por_categoria[gasto.categoria] += gasto.valor

    for categoria, total in sorted(por_categoria.items()):
        print(f"{categoria:<12}  {formatar_reais(total):>12}")
    print("-" * 26)
    print(f"{'TOTAL':<12}  {formatar_reais(sum(por_categoria.values())):>12}")


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

    p_remover = subparsers.add_parser("remover", help="apaga um gasto pelo número")
    p_remover.add_argument("id", type=int, help="o número mostrado em 'listar'")
    p_remover.set_defaults(funcao=cmd_remover)

    p_resumo = subparsers.add_parser("resumo", help="total por categoria")
    p_resumo.add_argument("--mes", help="filtra por mês no formato AAAA-MM")
    p_resumo.set_defaults(funcao=cmd_resumo)

    args = parser.parse_args()
    args.funcao(args)


if __name__ == "__main__":
    main()
