# 💰 Controle de Gastos

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
- **Listar** todos os gastos em ordem cronológica
- **Resumir** o total por categoria, com filtro por mês
- Aceita valores com vírgula (`45,90`) ou ponto (`45.90`)
- Valida o que o usuário digita (valores negativos, texto inválido e datas erradas são recusados)
- Dados salvos localmente em JSON, fora do controle de versão

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

# Listar todos os gastos
python -m gastos listar

# Resumo por categoria (geral ou de um mês)
python -m gastos resumo
python -m gastos resumo --mes 2026-09

# Ajuda
python -m gastos --help
```

Exemplo de listagem:

```
20/09/2026      R$ 12,50  transporte
23/09/2026      R$ 45,90  mercado       compras da semana
```

## Testes

```bash
python -m venv .venv
source .venv/bin/activate
pip install -r requirements-dev.txt
pytest
```

A suíte cobre o modelo de dados, a leitura e gravação em arquivo e o fluxo completo da linha de comando. Os testes usam pastas temporárias e nunca tocam nos dados reais.

## Estrutura do projeto

```
controle-gastos/
├── gastos/
│   ├── __main__.py       # linha de comando (argparse)
│   ├── armazenamento.py  # salvar e carregar em JSON
│   └── modelo.py         # a classe Gasto
└── tests/                # testes com pytest
```

## Decisões técnicas

- **`Decimal` em vez de `float` para dinheiro:** `float` acumula erros de arredondamento (`0.1 + 0.2 = 0.30000000000000004`); `Decimal` faz contas exatas.
- **Biblioteca padrão apenas:** `argparse`, `json`, `dataclasses` e `pathlib` resolvem o problema sem dependências externas.
- **Caminho do arquivo como parâmetro:** permite que os testes usem arquivos temporários, isolados dos dados reais.
- **Dados fora do Git:** a pasta `dados/` está no `.gitignore`, então informações financeiras pessoais nunca vão para o repositório.

## Próximos passos

- [ ] Editar e remover gastos
- [ ] Migrar o armazenamento para SQLite
- [ ] Exportar para CSV
- [ ] Gráficos de gastos por mês
- [ ] Versão web com API REST (FastAPI)
