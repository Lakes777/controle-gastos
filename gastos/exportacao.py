"""Exporta os gastos para CSV ou para planilha do Excel (.xlsx)."""

import csv
import re
import zipfile
from collections.abc import Iterable
from datetime import date
from typing import BinaryIO, TextIO
from xml.sax.saxutils import escape

from gastos.modelo import Gasto

CABECALHO = ["numero", "data", "valor", "categoria", "descricao"]

# Texto que começa com estes caracteres vira fórmula no Excel ("CSV injection").
INICIO_DE_FORMULA = ("=", "+", "-", "@", "\t", "\r")


def texto_seguro(texto: str) -> str:
    """Põe um ' na frente de texto que o Excel executaria como fórmula."""
    return "'" + texto if texto.startswith(INICIO_DE_FORMULA) else texto


def escrever_csv(gastos: Iterable[Gasto], arquivo: TextIO) -> int:
    """Escreve os gastos no arquivo já aberto e devolve quantos foram escritos.

    Usa ; para separar as colunas e vírgula nos centavos, como o Excel
    em português espera. O módulo csv cuida de descrições com ; ou aspas.
    """
    escritor = csv.writer(arquivo, delimiter=";")
    escritor.writerow(CABECALHO)
    quantidade = 0
    for gasto in gastos:
        escritor.writerow(
            [
                gasto.id,
                f"{gasto.data:%d/%m/%Y}",
                f"{gasto.valor:.2f}".replace(".", ","),
                texto_seguro(gasto.categoria),
                texto_seguro(gasto.descricao),
            ]
        )
        quantidade += 1
    return quantidade


# --- Planilha do Excel (.xlsx) ---
#
# Um .xlsx é um arquivo .zip com arquivos XML dentro (padrão Office Open XML).
# Diferente do CSV, ele guarda o valor como número e a data como data, e por
# isso abre certo em qualquer Excel, seja o Windows em português ou em inglês.
# Aqui vai só o mínimo que o Excel exige, escrito à mão, sem bibliotecas.

_CABECALHO_XML = '<?xml version="1.0" encoding="UTF-8" standalone="yes"?>\n'
_PRINCIPAL = "http://schemas.openxmlformats.org/spreadsheetml/2006/main"
_RELACOES = "http://schemas.openxmlformats.org/package/2006/relationships"
_TIPO_REL = "http://schemas.openxmlformats.org/officeDocument/2006/relationships"
_TIPO_OFFICE = "application/vnd.openxmlformats-officedocument.spreadsheetml"

# Arquivos que são sempre iguais: o "índice" do pacote e os estilos.
_ARQUIVOS_FIXOS = {
    "[Content_Types].xml": (
        '<Types xmlns="http://schemas.openxmlformats.org/package/2006/content-types">'
        '<Default Extension="rels" '
        'ContentType="application/vnd.openxmlformats-package.relationships+xml"/>'
        '<Default Extension="xml" ContentType="application/xml"/>'
        f'<Override PartName="/xl/workbook.xml" ContentType="{_TIPO_OFFICE}.sheet.main+xml"/>'
        '<Override PartName="/xl/worksheets/sheet1.xml" '
        f'ContentType="{_TIPO_OFFICE}.worksheet+xml"/>'
        f'<Override PartName="/xl/styles.xml" ContentType="{_TIPO_OFFICE}.styles+xml"/>'
        "</Types>"
    ),
    "_rels/.rels": (
        f'<Relationships xmlns="{_RELACOES}">'
        f'<Relationship Id="rId1" Type="{_TIPO_REL}/officeDocument" Target="xl/workbook.xml"/>'
        "</Relationships>"
    ),
    "xl/workbook.xml": (
        f'<workbook xmlns="{_PRINCIPAL}" xmlns:r="{_TIPO_REL}">'
        '<sheets><sheet name="Gastos" sheetId="1" r:id="rId1"/></sheets>'
        "</workbook>"
    ),
    "xl/_rels/workbook.xml.rels": (
        f'<Relationships xmlns="{_RELACOES}">'
        f'<Relationship Id="rId1" Type="{_TIPO_REL}/worksheet" Target="worksheets/sheet1.xml"/>'
        f'<Relationship Id="rId2" Type="{_TIPO_REL}/styles" Target="styles.xml"/>'
        "</Relationships>"
    ),
    # Estilos, na ordem de <cellXfs>: 0 normal, 1 negrito, 2 data, 3 reais, 4 reais em negrito
    "xl/styles.xml": (
        f'<styleSheet xmlns="{_PRINCIPAL}">'
        '<numFmts count="2">'
        '<numFmt numFmtId="164" formatCode="dd/mm/yyyy"/>'
        '<numFmt numFmtId="165" formatCode="&quot;R$&quot; #,##0.00"/>'
        "</numFmts>"
        '<fonts count="2">'
        '<font><sz val="11"/><name val="Calibri"/></font>'
        '<font><b/><sz val="11"/><name val="Calibri"/></font>'
        "</fonts>"
        '<fills count="2"><fill><patternFill patternType="none"/></fill>'
        '<fill><patternFill patternType="gray125"/></fill></fills>'
        '<borders count="1"><border><left/><right/><top/><bottom/><diagonal/></border></borders>'
        '<cellStyleXfs count="1"><xf numFmtId="0" fontId="0" fillId="0" borderId="0"/></cellStyleXfs>'
        '<cellXfs count="5">'
        '<xf numFmtId="0" fontId="0" fillId="0" borderId="0" xfId="0"/>'
        '<xf numFmtId="0" fontId="1" fillId="0" borderId="0" xfId="0" applyFont="1"/>'
        '<xf numFmtId="164" fontId="0" fillId="0" borderId="0" xfId="0" applyNumberFormat="1"/>'
        '<xf numFmtId="165" fontId="0" fillId="0" borderId="0" xfId="0" applyNumberFormat="1"/>'
        '<xf numFmtId="165" fontId="1" fillId="0" borderId="0" xfId="0" '
        'applyNumberFormat="1" applyFont="1"/>'
        "</cellXfs>"
        '<cellStyles count="1"><cellStyle name="Normal" xfId="0" builtinId="0"/></cellStyles>'
        "</styleSheet>"
    ),
}

NORMAL, NEGRITO, DATA, REAIS, REAIS_NEGRITO = range(5)
TITULOS_XLSX = ["Nº", "Data", "Valor", "Categoria", "Descrição"]
LARGURAS = [6, 12, 14, 16, 40]

# O Excel conta as datas em dias desde 30/12/1899 (46288 = 23/09/2026).
_DIA_ZERO_DO_EXCEL = date(1899, 12, 30)

# Caracteres de controle que o XML não aceita (só tab e quebras de linha são permitidos).
_PROIBIDOS_NO_XML = re.compile(r"[\x00-\x08\x0b\x0c\x0e-\x1f]")


def _celula_texto(referencia: str, texto: str, estilo: int = NORMAL) -> str:
    # Texto numa célula do .xlsx nunca é executado como fórmula,
    # então aqui não é preciso a proteção do CSV.
    limpo = escape(_PROIBIDOS_NO_XML.sub("", texto))
    return (
        f'<c r="{referencia}" t="inlineStr" s="{estilo}">'
        f'<is><t xml:space="preserve">{limpo}</t></is></c>'
    )


def _celula_numero(referencia: str, numero: object, estilo: int = NORMAL) -> str:
    return f'<c r="{referencia}" s="{estilo}"><v>{numero}</v></c>'


def _planilha(gastos: list[Gasto]) -> str:
    linhas = [
        '<row r="1">'
        + "".join(_celula_texto(f"{coluna}1", titulo, NEGRITO)
                  for coluna, titulo in zip("ABCDE", TITULOS_XLSX))
        + "</row>"
    ]
    for numero_linha, gasto in enumerate(gastos, start=2):
        n = numero_linha
        linhas.append(
            f'<row r="{n}">'
            + _celula_numero(f"A{n}", gasto.id)
            + _celula_numero(f"B{n}", (gasto.data - _DIA_ZERO_DO_EXCEL).days, DATA)
            + _celula_numero(f"C{n}", gasto.valor, REAIS)
            + _celula_texto(f"D{n}", gasto.categoria)
            + _celula_texto(f"E{n}", gasto.descricao)
            + "</row>"
        )
    if gastos:
        # Linha de total com fórmula: se o usuário mudar um valor no Excel, o total acompanha.
        n = len(gastos) + 2
        total = sum(gasto.valor for gasto in gastos)
        linhas.append(
            f'<row r="{n}">'
            + _celula_texto(f"B{n}", "TOTAL", NEGRITO)
            + f'<c r="C{n}" s="{REAIS_NEGRITO}"><f>SUM(C2:C{n - 1})</f><v>{total}</v></c>'
            + "</row>"
        )

    colunas = "".join(
        f'<col min="{i}" max="{i}" width="{largura}" customWidth="1"/>'
        for i, largura in enumerate(LARGURAS, start=1)
    )
    return (
        f'<worksheet xmlns="{_PRINCIPAL}">'
        # Congela a linha dos títulos: ela fica visível ao rolar a planilha.
        '<sheetViews><sheetView workbookViewId="0">'
        '<pane ySplit="1" topLeftCell="A2" activePane="bottomLeft" state="frozen"/>'
        "</sheetView></sheetViews>"
        f"<cols>{colunas}</cols>"
        f"<sheetData>{''.join(linhas)}</sheetData>"
        "</worksheet>"
    )


def escrever_xlsx(gastos: Iterable[Gasto], arquivo: BinaryIO) -> int:
    """Escreve os gastos como planilha do Excel e devolve quantos foram escritos."""
    gastos = list(gastos)
    conteudo = dict(_ARQUIVOS_FIXOS)
    conteudo["xl/worksheets/sheet1.xml"] = _planilha(gastos)
    with zipfile.ZipFile(arquivo, "w", compression=zipfile.ZIP_DEFLATED) as pacote:
        for nome, xml in conteudo.items():
            pacote.writestr(nome, _CABECALHO_XML + xml)
    return len(gastos)
