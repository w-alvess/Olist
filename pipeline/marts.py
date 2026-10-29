"""Etapa 3: marts do olist.duckdb, um por arquivo de sql/marts/.

Execução:
    uv run python -m pipeline.marts

1. ESCOPO
   Lê de refined, escreve no schema marts. Nunca escreve em raw nem em
   refined. O schema marts é apagado e recriado a cada execução
   (DROP SCHEMA IF EXISTS marts CASCADE).
   Por quê: um mart cujo arquivo foi apagado não pode continuar existindo no
   banco.

2. UM ARQUIVO, UMA TABELA
   Lê todos os sql/marts/*.sql em ordem alfabética. Nome da tabela = nome do
   arquivo sem a extensão e sem o prefixo numérico:
     sql/marts/01_vendas_mensais.sql -> marts.vendas_mensais
   Executa: CREATE TABLE marts.<nome> AS <conteúdo do arquivo>
   Tira espaços e um ponto e vírgula do final do conteúdo, e nada mais.
   O Python não altera, não monta e não completa a SQL.
   Por quê: a regra de negócio mora inteira no arquivo .sql.

3. SAÍDA NA TELA
   Uma linha por mart, com a contagem vinda do banco, milhar com ponto:
     ✓ marts.vendas_mensais        24 linhas
   Linha final com o número de marts e o total de linhas. stdout
   reconfigurado para utf-8.
   Por quê: a contagem tem que ser a do que foi gravado, não a de uma
   estimativa. E no Prompt de Comando do Windows acento sai embaralhado por
   padrão.

4. ERRO
   Antes de tudo: se faltar qualquer uma das oito tabelas em refined, lista
   quais, diz para rodar "uv run python -m pipeline.transformacao" e
   sys.exit(1).
   Por quê: mart sobre refined incompleto dá número errado que parece certo.
   Se sql/marts/ não tiver nenhum arquivo: avisa e sys.exit(1).
   Por quê: rodar sem arquivo apagaria todos os marts do dashboard.
   Antes de executar qualquer SQL: arquivo sem prefixo NN_ ou dois arquivos
   que dão o mesmo nome de tabela -> lista quais e sys.exit(1).
   Por quê: sem prefixo não há nome de tabela definido, e dois arquivos para
   a mesma tabela fariam um sobrescrever o outro em silêncio.
   Se um .sql falhar: mostra o nome do arquivo e a mensagem do DuckDB, não
   executa os seguintes, sys.exit(1).
   Por quê: quem vai corrigir precisa saber em que arquivo mexer.
   Se um mart voltar com zero linhas: mostra o nome e sys.exit(1).
   Por quê: mart vazio é quase sempre um JOIN que não casou, e um dashboard
   vazio parece um negócio parado.
   Tudo roda numa transação só: se qualquer passo falhar (inclusive o mart
   vazio), o schema marts volta a ser o da última execução que deu certo.
   Por quê: um schema pela metade quebra o dashboard sem avisar.
"""

import re
import sys
from pathlib import Path

import duckdb

from pipeline.db import conectar, criar_schema
from pipeline.transformacao import DESTINO as ORIGEM
from pipeline.transformacao import TABELAS as TABELAS_ORIGEM

DESTINO = "marts"

# Resolvido a partir deste arquivo, como o olist.duckdb em db.py: rodar de
# outra pasta não pode ler um sql/marts/ que não é o do projeto.
PASTA_SQL = Path(__file__).resolve().parent.parent / "sql" / "marts"

_PREFIXO = re.compile(r"^\d{2}_(.+)$")


def _ident(nome: str) -> str:
    return '"' + nome.replace('"', '""') + '"'


def _milhar(n: int) -> str:
    return f"{n:,}".replace(",", ".")


def _plural(n: int, palavra: str) -> str:
    return f"{_milhar(n)} {palavra}{'' if n == 1 else 's'}"


def _fetch(con: duckdb.DuckDBPyConnection, sql: str) -> list[tuple]:
    # fetchall sempre: no DuckDB 2 um resultado lido pela metade deixa a
    # conexão ocupada (ver db.gravar).
    return con.execute(sql).fetchall()


def _abortar(linhas: list[str]) -> None:
    for linha in linhas:
        print(linha)
    print(f"Schema {DESTINO} mantido como na última execução que deu certo.")
    sys.exit(1)


def _verificar_origem(con: duckdb.DuckDBPyConnection) -> None:
    existentes = {
        nome
        for (nome,) in _fetch(
            con,
            f"SELECT table_name FROM information_schema.tables "
            f"WHERE table_schema = '{ORIGEM}'",
        )
    }
    faltando = [t for t in TABELAS_ORIGEM if t not in existentes]
    if faltando:
        _abortar(
            [f"Tabelas não encontradas no schema {ORIGEM}:"]
            + [f"  {ORIGEM}.{t}" for t in faltando]
            + ["Rode antes: uv run python -m pipeline.transformacao"]
        )


def _listar_marts() -> list[tuple[str, Path]]:
    # Ordena pelo nome do arquivo, não pelo Path: no Windows a comparação de
    # Path ignora maiúsculas e a ordem mudaria conforme o sistema.
    arquivos = sorted(PASTA_SQL.glob("*.sql"), key=lambda p: p.name)
    if not arquivos:
        _abortar([f"Nenhum arquivo .sql em {PASTA_SQL}."])

    sem_prefixo = []
    por_nome: dict[str, list[Path]] = {}
    marts = []
    for arquivo in arquivos:
        casou = _PREFIXO.match(arquivo.stem)
        if not casou:
            sem_prefixo.append(arquivo)
            continue
        nome = casou.group(1)
        # DuckDB não diferencia maiúsculas em nome de tabela: 01_Vendas e
        # 02_vendas iriam para a mesma marts.vendas.
        por_nome.setdefault(nome.lower(), []).append(arquivo)
        marts.append((nome, arquivo))

    repetidos = [grupo for grupo in por_nome.values() if len(grupo) > 1]
    linhas = []
    if sem_prefixo:
        linhas.append("Arquivos sem prefixo NN_ (ex.: 01_vendas_mensais.sql):")
        linhas += [f"  {a.name}" for a in sem_prefixo]
    for grupo in repetidos:
        nome = _PREFIXO.match(grupo[0].stem).group(1)
        linhas.append(f"Arquivos que dão a mesma tabela {DESTINO}.{nome}:")
        linhas += [f"  {a.name}" for a in grupo]
    if linhas:
        _abortar(linhas + ["Nenhuma SQL foi executada."])
    return marts


def _ler_sql(arquivo: Path) -> str:
    # utf-8-sig descarta o BOM que o Bloco de Notas grava no início; com ele
    # o DuckDB acusaria erro de sintaxe num arquivo que parece correto.
    sql = arquivo.read_text(encoding="utf-8-sig").rstrip()
    if sql.endswith(";"):
        sql = sql[:-1].rstrip()
    return sql


def main() -> None:
    sys.stdout.reconfigure(encoding="utf-8")

    con = conectar()
    try:
        _verificar_origem(con)
        marts = _listar_marts()
        consultas = [(nome, arquivo, _ler_sql(arquivo)) for nome, arquivo in marts]
        largura = max(len(f"{DESTINO}.{nome}") for nome, _ in marts)

        con.execute("BEGIN TRANSACTION")
        try:
            con.execute(f"DROP SCHEMA IF EXISTS {_ident(DESTINO)} CASCADE")
            criar_schema(con, DESTINO)
            total = 0
            for nome, arquivo, sql in consultas:
                alvo = f"{_ident(DESTINO)}.{_ident(nome)}"
                try:
                    con.execute(f"CREATE TABLE {alvo} AS {sql}")
                except duckdb.Error as e:
                    _abortar([f"✗ {arquivo.name} falhou:", f"  {e}"])
                linhas = _fetch(con, f"SELECT count(*) FROM {alvo}")[0][0]
                if linhas == 0:
                    _abortar(
                        [
                            f"✗ {DESTINO}.{nome} voltou com 0 linhas ({arquivo.name}).",
                            "  Confira os JOINs e os filtros.",
                        ]
                    )
                total += linhas
                print(
                    f"✓ {f'{DESTINO}.{nome}':<{largura}} "
                    f"{_milhar(linhas):>9} {'linha' if linhas == 1 else 'linhas'}"
                )
            con.execute("COMMIT")
        except BaseException:
            con.execute("ROLLBACK")
            raise

        print(f"{_plural(len(consultas), 'mart')}, {_plural(total, 'linha')} no total")
    finally:
        con.close()


if __name__ == "__main__":
    main()
