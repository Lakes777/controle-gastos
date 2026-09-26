# 💰 Controle de Gastos

[![Testes](https://github.com/Lakes777/controle-gastos/actions/workflows/testes.yml/badge.svg)](https://github.com/Lakes777/controle-gastos/actions/workflows/testes.yml)

Aplicativo de linha de comando para registrar e acompanhar gastos pessoais, feito em Python puro.

```
$ python -m gastos resumo --mes 2026-09
alimentação       R$ 342,80
mercado           R$ 489,90
transporte        R$ 127,50
--------------------------
TOTAL             R$ 960,20
```

## Funcionalidades

- **Adicionar** gastos com valor, categoria, descrição e data
- **Listar** todos os gastos em ordem cronológica, cada um com seu número
- **Editar** um gasto pelo número, mudando só os campos informados
- **Remover** um gasto pelo número
- **Resumir** o total por categoria, com filtro por mês
- **Exportar** para CSV (geral ou de um mês), pronto para abrir no Excel ou no Google Planilhas
- Aceita valores com vírgula (`45,90`) ou ponto (`45.90`)
- Valida o que o usuário digita (valores negativos, texto inválido e datas erradas são recusados)
- Dados salvos localmente num banco SQLite, fora do controle de versão
- Quem usava a versão antiga (JSON) tem os gastos importados automaticamente

## Instalação

Requer **Python 3.10+**. Não há dependências externas para usar o programa.

```bash
git clone https://github.com/Lakes777/controle-gastos.git
cd controle-gastos
```

## Como usar

```bash
# Adicionar um gasto (a descrição é opcional; a data padrão é hoje)
python -m gastos adicionar 45,90 mercado "compras da semana"
python -m gastos adicionar 12.50 transporte --data 2026-09-20

# Listar todos os gastos (com o número de cada um)
python -m gastos listar

# Editar o gasto número 2 (só muda o que for informado)
python -m gastos editar 2 --valor 25,00 --categoria transporte
python -m gastos editar 2 --descricao ""    # apaga a descrição

# Remover o gasto número 2
python -m gastos remover 2

# Resumo por categoria (geral ou de um mês)
python -m gastos resumo
python -m gastos resumo --mes 2026-09

# Exportar para CSV (abre no Excel); não sobrescreve arquivo existente sem pedir
python -m gastos exportar gastos.csv
python -m gastos exportar setembro.csv --mes 2026-09
python -m gastos exportar gastos.csv --sobrescrever

# Ajuda
python -m gastos --help
```

Exemplo de listagem:

```
  Nº  DATA               VALOR  CATEGORIA     DESCRIÇÃO
   2  20/09/2026      R$ 12,50  transporte
   1  23/09/2026      R$ 45,90  mercado       compras da semana
```

## Testes

```bash
python -m venv .venv
source .venv/bin/activate
pip install -r requirements-dev.txt
pytest
```

A suíte cobre o modelo de dados, o banco SQLite (incluindo a migração do JSON antigo, a edição e a remoção), a exportação para CSV e o fluxo completo da linha de comando. Os testes usam pastas temporárias e nunca tocam nos dados reais.

## Estrutura do projeto

```
controle-gastos/
├── gastos/
│   ├── __main__.py       # linha de comando (argparse)
│   ├── armazenamento.py  # banco SQLite (sqlite3, SQL à mão)
│   ├── exportacao.py     # exportar para CSV
│   └── modelo.py         # a classe Gasto
└── tests/                # testes com pytest
```

## Decisões técnicas

- **`Decimal` em vez de `float` para dinheiro:** `float` acumula erros de arredondamento (`0.1 + 0.2 = 0.30000000000000004`); `Decimal` faz contas exatas.
- **SQLite com o `sqlite3` da biblioteca padrão:** um banco de verdade num único arquivo, sem servidor e sem instalar nada. O SQL é escrito à mão, com marcadores (`?`) para evitar SQL injection.
- **Valor guardado como `TEXT`, não `REAL`:** o `REAL` do SQLite é um `float` e traria de volta os erros de centavos; em texto (`"45.90"`), o `Decimal` volta exato. Há um teste que falha se a coluna virar `REAL`.
- **Migração sem perder dados:** ao abrir o banco, um `gastos.json` antigo é importado numa única transação e renomeado para `gastos.json.migrado` (backup). Se algo falhar, nada fica importado pela metade.
- **Números de gasto nunca reaproveitados:** a tabela usa `AUTOINCREMENT`, então, depois de remover o gasto 5, nenhum gasto novo recebe o 5. Um número anotado nunca passa a apontar para outro gasto.
- **CSV no formato do Excel brasileiro:** colunas separadas por `;` (a vírgula já é usada nos centavos) e arquivo em `utf-8-sig`, cuja marca inicial (BOM) faz o Excel mostrar os acentos certos.
- **Proteção contra CSV injection:** texto que começa com `=`, `+`, `-` ou `@` seria executado como fórmula pelo Excel; ele é exportado com um `'` na frente, e aparece só como texto.
- **Biblioteca padrão apenas:** `argparse`, `sqlite3`, `csv`, `dataclasses` e `pathlib` resolvem o problema sem dependências externas.
- **Caminho do arquivo como parâmetro:** permite que os testes usem arquivos temporários, isolados dos dados reais.
- **Dados fora do Git:** a pasta `dados/` está no `.gitignore`, então informações financeiras pessoais nunca vão para o repositório.

## Próximos passos

- [x] Editar e remover gastos
- [x] Migrar o armazenamento para SQLite
- [x] Exportar para CSV
- [ ] Gráficos de gastos por mês
- [ ] Versão web com API REST (FastAPI)
