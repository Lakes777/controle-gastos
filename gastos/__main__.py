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
from gastos.importacao import (
    MAXIMO_DE_NOMES,
    FormatoDesconhecido,
    LinhaInvalida,
    categorias_lembradas,
    ler_extrato,
    validar_meu_nome,
)
from gastos.modelo import Gasto
from gastos.orcamento import calcular
from gastos.orcamento import desenhar as desenhar_orcamento
from gastos.recorrentes import MESES_PARA_TRAS, Recorrente, meses_entre, primeiro_mes


def hoje() -> date:
    """Data de hoje. Fica numa função para os testes poderem fingir outra data."""
    return date.today()


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


def numeros(texto: str) -> set[int]:
    """'1,3' -> {1, 3}: as linhas da prévia que o usuário quer deixar de fora."""
    try:
        escolhidos = {int(parte) for parte in texto.split(",") if parte.strip()}
    except ValueError:
        raise argparse.ArgumentTypeError("use os números da lista separados por vírgula, ex.: 1,3")
    if not escolhidos:
        raise argparse.ArgumentTypeError("informe ao menos um número")
    return escolhidos


def nome_valido(texto: str) -> str:
    try:
        return validar_meu_nome(texto)
    except ValueError as erro:
        raise argparse.ArgumentTypeError(str(erro))


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


def dia_do_mes(texto: str) -> int:
    """Confere o dia do mês de um gasto recorrente (1 a 31)."""
    if not texto.isdigit() or not 1 <= int(texto) <= 31:
        raise argparse.ArgumentTypeError(f"dia inválido: {texto} (use de 1 a 31)")
    return int(texto)


def lancar_recorrentes(banco: Banco) -> None:
    """Lança os gastos recorrentes cuja data chegou e conta ao usuário o que foi lançado."""
    for gasto in banco.lancar_recorrentes(hoje()):
        print(
            f"Lançado automaticamente: {formatar_reais(gasto.valor)} em {gasto.categoria} "
            f"({gasto.data:%d/%m/%Y})"
        )
        avisar_orcamento(banco, gasto)


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


def cmd_importar(args: argparse.Namespace) -> None:
    try:
        with open(args.arquivo, "rb") as arquivo:
            conteudo = arquivo.read()
    except FileNotFoundError:
        sys.exit(f"Arquivo não encontrado: {args.arquivo}")

    banco = Banco()
    meus_nomes = banco.listar_meus_nomes()
    try:
        # Em bytes: quem descobre o formato (CSV ou OFX) e a codificação é ler_extrato.
        extrato = ler_extrato(conteudo, meus_nomes, categorias_lembradas(banco.listar()))
    except UnicodeDecodeError:
        sys.exit("O CSV não está em UTF-8. Exporte o CSV de novo pelo Nubank.")
    except (FormatoDesconhecido, LinhaInvalida) as erro:
        sys.exit(f"Nada foi importado. {erro}")

    ja_importadas = banco.origens_existentes()
    novos = [(gasto, origem) for gasto, origem in extrato.itens if origem not in ja_importadas]
    repetidos = len(extrato.itens) - len(novos)
    pular = args.pular or set()
    if fora := sorted(n for n in pular if not 1 <= n <= len(novos)):
        sys.exit(f"Nada foi importado. --pular: a lista de novos não tem o número {fora[0]}.")

    print(f"Arquivo reconhecido: {extrato.nome}")
    print()
    for numero, (gasto, origem) in enumerate(novos, start=1):
        pulado = numero in pular
        print(
            f"  {'x' if pulado else '+'}{numero:>3}  {gasto.data:%d/%m/%Y}  "
            f"{formatar_reais(gasto.valor):>12}  {gasto.categoria:<12}  {gasto.descricao}"
            + (" (categoria lembrada)" if origem in extrato.lembradas else "")
            + (" (pulado)" if pulado else "")
        )
    for ignorado in extrato.ignorados:
        print(
            f"  -     {ignorado.data:%d/%m/%Y}  {formatar_reais(abs(ignorado.valor)):>12}  "
            f"{ignorado.descricao} (ignorado: {ignorado.motivo})"
        )
    print()

    novos = [item for numero, item in enumerate(novos, start=1) if numero not in pular]
    contagem = (
        (f"{len(pular)} pulado(s), " if pular else "")
        + f"{repetidos} já importado(s) antes, {len(extrato.ignorados)} ignorado(s)"
    )
    if args.simular:
        print(f"Simulação: {len(novos)} gasto(s) seriam importados, {contagem}. Nada foi salvo.")
        if novos:
            print("Para deixar linhas de fora: --pular com os números da lista (ex.: --pular 1,3)")
        if not meus_nomes and any(g.descricao.startswith("Pix enviado") for g, _ in novos):
            print(
                "Algum Pix foi para outra conta sua? Cadastre seu nome e ele deixa de contar "
                'como gasto: python -m gastos meu-nome adicionar "Nome Sobrenome"'
            )
        return
    importados = banco.importar(novos)
    print(f"{len(importados)} gasto(s) importado(s), {contagem}")
    if importados:
        print(
            "Para corrigir uma categoria: python -m gastos editar <nº> --categoria <nova> "
            "(as próximas compras da mesma loja já vêm com ela)"
        )


def cmd_meu_nome(args: argparse.Namespace) -> None:
    banco = Banco()
    if args.acao == "adicionar":
        if len(banco.listar_meus_nomes()) >= MAXIMO_DE_NOMES:
            sys.exit(f"Já há {MAXIMO_DE_NOMES} nomes cadastrados (o máximo).")
        if not banco.adicionar_meu_nome(args.nome):
            sys.exit(f"O nome {args.nome} já estava cadastrado.")
        print(f"Nome cadastrado: {args.nome}. Pix enviado para ele não conta como gasto ao importar.")
        return
    if args.acao == "remover":
        if not banco.remover_meu_nome(args.nome):
            sys.exit(f"O nome {args.nome} não estava cadastrado.")
        print(f"Nome removido: {args.nome}")
        return

    nomes = banco.listar_meus_nomes()
    if not nomes:
        print('Nenhum nome cadastrado. Cadastre com: meu-nome adicionar "Nome Sobrenome"')
        return
    print("Pix enviado para estes nomes não conta como gasto ao importar:")
    for nome in nomes:
        print(f"  {nome}")


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
    mes = args.mes or f"{hoje():%Y-%m}"
    situacoes = calcular(banco.listar(mes=mes), orcamentos)
    print(f"Orçamento de {nome_do_mes(int(mes[:4]), int(mes[5:]))}")
    print()
    for linha in desenhar_orcamento(situacoes):
        print(linha)


def cmd_recorrente(args: argparse.Namespace) -> None:
    banco = Banco()
    if args.acao == "adicionar":
        if args.desde is None:
            proximo = primeiro_mes(args.dia, hoje())
        elif meses_entre(args.desde, f"{hoje():%Y-%m}") > MESES_PARA_TRAS:
            sys.exit(f"O --desde pode voltar no máximo {MESES_PARA_TRAS} meses.")
        else:
            proximo = args.desde
        novo = banco.adicionar_recorrente(
            Recorrente(args.valor, args.categoria.lower(), args.dia, proximo, args.descricao)
        )
        quando = f"todo dia {novo.dia}" + (" (ou o último dia do mês)" if novo.dia > 28 else "")
        print(
            f"Gasto recorrente {novo.id}: {formatar_reais(novo.valor)} em {novo.categoria}, "
            f"{quando}"
        )
        print(f"Primeiro lançamento: {novo.proxima_data:%d/%m/%Y}")
        lancar_recorrentes(banco)  # com --desde no passado, os meses que já passaram entram agora
        return
    if args.acao == "remover":
        if not banco.remover_recorrente(args.id):
            sys.exit(f"Nenhum gasto recorrente com o número {args.id}.")
        print(f"Gasto recorrente {args.id} removido (os gastos já lançados continuam)")
        return

    # Sem ação: lista os recorrentes.
    recorrentes = banco.listar_recorrentes()
    if not recorrentes:
        print("Nenhum gasto recorrente. Crie um com: recorrente adicionar 1200 aluguel --dia 5")
        return
    print(f"{'Nº':>4}  {'DIA':>3}  {'VALOR':>12}  {'CATEGORIA':<12}  {'PRÓXIMO':<10}  DESCRIÇÃO")
    for r in recorrentes:
        print(
            f"{r.id:>4}  {r.dia:>3}  {formatar_reais(r.valor):>12}  {r.categoria:<12}  "
            f"{r.proxima_data:%d/%m/%Y}  {r.descricao}"
        )


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
        default=hoje(),
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

    p_importar = subparsers.add_parser(
        "importar", help="importa o CSV do Nubank ou o OFX de qualquer banco (fatura ou conta)"
    )
    p_importar.add_argument("arquivo", help="o arquivo .csv (Nubank) ou .ofx baixado do banco")
    p_importar.add_argument(
        "--simular", action="store_true", help="mostra o que seria importado, sem salvar"
    )
    p_importar.add_argument(
        "--pular", type=numeros, metavar="1,3", help="deixa de fora essas linhas da lista de novos"
    )
    p_importar.set_defaults(funcao=cmd_importar)

    p_meu_nome = subparsers.add_parser(
        "meu-nome",
        help="seu nome como aparece nos extratos: Pix para você mesmo não é gasto (sem ação: lista)",
    )
    p_meu_nome.set_defaults(funcao=cmd_meu_nome, acao=None)
    acoes_nome = p_meu_nome.add_subparsers(dest="acao")
    p_nome_adicionar = acoes_nome.add_parser("adicionar", help="cadastra um nome")
    p_nome_adicionar.add_argument("nome", type=nome_valido, help='ex.: "Ana Souza Lima"')
    p_nome_remover = acoes_nome.add_parser("remover", help="apaga um nome")
    p_nome_remover.add_argument("nome")

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

    p_recorrente = subparsers.add_parser(
        "recorrente", help="gastos que se repetem todo mês (sem ação: lista)"
    )
    p_recorrente.set_defaults(funcao=cmd_recorrente, acao=None)
    acoes_rec = p_recorrente.add_subparsers(dest="acao")
    p_rec_adicionar = acoes_rec.add_parser("adicionar", help="cria um gasto recorrente")
    p_rec_adicionar.add_argument("valor", type=valor_positivo, help="ex.: 1200 ou 39,90")
    p_rec_adicionar.add_argument("categoria", help="ex.: aluguel, internet")
    p_rec_adicionar.add_argument("descricao", nargs="?", default="", help="opcional")
    p_rec_adicionar.add_argument(
        "--dia", type=dia_do_mes, required=True, help="dia do mês em que o gasto acontece"
    )
    p_rec_adicionar.add_argument(
        "--desde",
        type=mes_valido,
        help="primeiro mês, AAAA-MM (padrão: a próxima vez que o dia chegar)",
    )
    p_rec_remover = acoes_rec.add_parser("remover", help="para de lançar um gasto recorrente")
    p_rec_remover.add_argument("id", type=int, help="o número mostrado em 'recorrente'")

    args = parser.parse_args()
    # Antes de qualquer comando, lança os gastos recorrentes cuja data já chegou.
    lancar_recorrentes(Banco())
    args.funcao(args)


if __name__ == "__main__":
    main()
