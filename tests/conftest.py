import os
import uuid

import pytest

# Os testes com Postgres só rodam se esta variável tiver o endereço de um banco,
# ex.: GASTOS_TESTE_POSTGRES=postgresql://postgres@127.0.0.1:5432/postgres
URL_POSTGRES = os.environ.get("GASTOS_TESTE_POSTGRES")


@pytest.fixture
def conectar_postgres():
    """Função que abre conexões num schema novo, só deste teste (apagado no fim)."""
    if not URL_POSTGRES:
        pytest.skip("defina GASTOS_TESTE_POSTGRES para rodar os testes com Postgres")
    from gastos.web.banco_postgres import conectar

    esquema = f"teste_{uuid.uuid4().hex}"
    with conectar(URL_POSTGRES) as conexao:
        conexao.execute(f'CREATE SCHEMA "{esquema}"')
    yield lambda: conectar(URL_POSTGRES, options=f"-c search_path={esquema}")
    with conectar(URL_POSTGRES) as conexao:
        conexao.execute(f'DROP SCHEMA "{esquema}" CASCADE')
