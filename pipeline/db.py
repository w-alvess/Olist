"""Conexão com o olist.duckdb, compartilhada pelas quatro etapas do curso.

Expõe exatamente:
    PASTA_RAW                        Path da pasta raw/ com os nove .csv.gz
    conectar()                       abre o olist.duckdb, criando se faltar
    criar_schema(con, nome)          CREATE SCHEMA IF NOT EXISTS
    gravar(con, df, schema, tabela)  grava e devolve a contagem lida do banco

D1. CAMINHOS
    PASTA_RAW e o olist.duckdb são resolvidos a partir da localização deste
    arquivo (a pasta acima de pipeline/), nunca do diretório corrente.
    Por quê: rodar o script de outra pasta não pode criar um olist.duckdb
    vazio no lugar errado, que parece ingestão quebrada.

D2. TRÊS FUNÇÕES E UMA CONSTANTE, NADA MAIS
    Este módulo não lê CSV, não conhece nome de tabela, não imprime nada e
    não converte tipo. Quem decide tudo isso é cada etapa.
    Por quê: as aulas 2, 3 e 4 importam este arquivo. Regra de negócio
    escondida aqui valeria para todas as etapas sem aparecer em nenhuma spec.

D3. gravar
    Recria a tabela (CREATE OR REPLACE TABLE schema.tabela) com as colunas e
    os tipos do DataFrame, sem alterar nada: coluna str vira VARCHAR, nulo
    continua NULL. Não deixa view ou tabela temporária para trás. Devolve
    SELECT count(*) da tabela recém-gravada, lido do banco.
    Por quê: a contagem que aparece na tela tem que ser a do que foi gravado,
    não a do que estava na memória. E recriar em vez de acrescentar faz a
    reexecução ser idempotente.

D4. CONEXÃO
    conectar() devolve a conexão aberta; quem chama é quem fecha. Este módulo
    não guarda conexão global.
    Por quê: importar o módulo não pode abrir banco nem criar arquivo, e o
    olist.duckdb aceita um único processo escrevendo. Conexão esquecida
    aberta trava a próxima etapa.
"""

from pathlib import Path

import duckdb
import pandas as pd

_RAIZ = Path(__file__).resolve().parent.parent

PASTA_RAW = _RAIZ / "raw"
_ARQUIVO_BANCO = _RAIZ / "olist.duckdb"


def _ident(nome: str) -> str:
    return '"' + nome.replace('"', '""') + '"'


def conectar() -> duckdb.DuckDBPyConnection:
    return duckdb.connect(str(_ARQUIVO_BANCO))


def criar_schema(con: duckdb.DuckDBPyConnection, nome: str) -> None:
    con.execute(f"CREATE SCHEMA IF NOT EXISTS {_ident(nome)}")


def gravar(
    con: duckdb.DuckDBPyConnection, df: pd.DataFrame, schema: str, tabela: str
) -> int:
    alvo = f"{_ident(schema)}.{_ident(tabela)}"
    # A view registrada é só a ponte DataFrame -> tabela; o finally garante
    # que ela some mesmo se o CREATE falhar.
    view = "_gravar_df"
    con.register(view, df)
    try:
        con.execute(f"CREATE OR REPLACE TABLE {alvo} AS SELECT * FROM {view}")
    finally:
        con.unregister(view)
    # fetchall, não fetchone: no DuckDB 2 um resultado lido pela metade deixa
    # a conexão ocupada e o próximo comando da etapa falha.
    return con.execute(f"SELECT count(*) FROM {alvo}").fetchall()[0][0]
