"""Etapa 2: transformação do schema raw no schema refined do olist.duckdb.

Execução:
    uv run python -m pipeline.transformacao

1. ESCOPO
   Lê de raw, escreve em refined, nunca escreve em raw. Entram oito tabelas:
   pedidos, itens_pedido, pagamentos, clientes, vendedores, produtos,
   traducao_categorias, avaliacoes. geolocalizacao fica de fora.
   Por quê: raw é o registro do dado que chegou, e só continua confiável se
   ninguém mexer nele depois. geolocalizacao fica de fora porque nenhum mart
   do curso a usa, e não se limpa o que ninguém vai ler.

2. NOMES
   Colunas renomeadas para português em snake_case pelo mapa de TABELAS,
   completo e literal. Nenhuma coluna fora do mapa, nenhuma descartada.
   Por quê: é o vocabulário digitado de memória nos JOINs da aula 3. Um nome
   inventado aqui é um JOIN quebrado lá.

3. TIPOS
   Datas com hora (data_compra, data_aprovacao, data_envio, data_entrega,
   data_limite_envio, data_resposta): TIMESTAMP, formato declarado
   '%Y-%m-%d %H:%M:%S'.
   data_entrega_prevista e data_criacao: DATE.
   Por quê: data_entrega_prevista tem 00:00:00 nas 99.441 linhas, e guardar
   a hora seria inventar precisão. data_criacao tem 00:00:00 em 99.139 das
   99.224 avaliações; nas outras 85 é 01:00:00, efeito de horário de verão,
   não um horário de verdade.
   Dinheiro (preco, frete, valor): DECIMAL(10,2).
   Por quê: DOUBLE não representa centavos com exatidão, e soma de dinheiro
   tem que fechar.
   Contagens e medidas (item_seq, pagamento_seq, parcelas, tamanho_nome,
   tamanho_descricao, qtd_fotos, peso_g, comprimento_cm, altura_cm,
   largura_cm, nota): INTEGER.
   Todo o resto continua VARCHAR, inclusive cep_prefixo.
   Por quê: 23.995 clientes têm CEP começando com zero. CEP é identificador,
   nunca é somado, e como número perderia o zero.
   A conversão é feita em SQL pelo DuckDB, disparada pelo Python.
   Por quê: o dado já está no banco; trazê-lo para a memória só para
   converter tipo seria custo sem ganho.

4. CONVERSÃO QUE FALHA
   Para tudo. Só strptime e CAST, que estouram; nunca try_strptime,
   TRY_CAST ou errors="coerce", que transformam falha em nulo. Ao falhar:
   diz tabela, coluna e o valor que não converteu, e sys.exit(1).
   Por quê: um nulo fabricado pela conversão fica indistinguível, para
   sempre, de um nulo verdadeiro do dado.

5. DUPLICATAS
   Cada tabela tem uma chave (ver TABELAS). Em avaliacoes a chave é
   (avaliacao_id, pedido_id), porque o mesmo avaliacao_id aparece em mais de
   um pedido. Linha inteira repetida: mantém uma e conta quantas saíram.
   Chave repetida com conteúdo diferente: para, mostra a chave e as linhas
   conflitantes, sys.exit(1).
   Por quê: linha idêntica repetida não carrega informação nova; já entre
   duas versões diferentes, escolher uma em silêncio é decidir sem dizer
   que decidiu.

6. NULOS
   Nenhuma linha é apagada por ter nulo. Nenhum nulo é preenchido.
   Anomalias de negócio também ficam (pedido delivered sem data_entrega,
   data_envio antes da data_compra, pedido com mais de uma avaliação).
   Por quê: o nulo é informação. Pedido cancelado não tem data de entrega
   porque não foi entregue; produto sem categoria continua sem categoria
   (dar rótulo é decisão de mart, aula 3); avaliação sem texto é a regra,
   não a exceção. refined não corrige fato: quem decide o que fazer com ele
   é a pergunta que o mart responde.

7. SAÍDA NA TELA
   Uma linha por tabela (linhas que entram -> linhas que saem, duplicatas
   removidas) e, abaixo dela, indentadas, as colunas com nulo e a contagem.
   Contagens lidas do banco, milhar separado por ponto, linha final com o
   total, stdout reconfigurado para utf-8.
   Por quê: essa saída é o instrumento de conferência da etapa: entrada =
   saída e nulos depois = nulos antes se verificam olhando para ela. E no
   Prompt de Comando do Windows acento sai embaralhado por padrão.

8. REEXECUÇÃO
   CREATE OR REPLACE TABLE, nunca acrescenta. Rodar dez vezes = rodar uma.
   Por quê: é o que permite errar sem medo.

9. ERRO
   Antes de transformar, verifica se as oito tabelas de entrada existem em
   raw. Faltando qualquer uma: lista quais, manda rodar
   "uv run python -m pipeline.ingestao" e sys.exit(1).
   Por quê: transformar sete de oito tabelas em silêncio produz um mart
   errado que parece certo.
"""

import sys

import duckdb

from pipeline.db import conectar, criar_schema

ORIGEM = "raw"
DESTINO = "refined"

_FORMATO_DATA_HORA = "%Y-%m-%d %H:%M:%S"

# tabela -> (chave, [(coluna em raw, coluna em refined, tipo)])
TABELAS = {
    "pedidos": (
        ("pedido_id",),
        [
            ("order_id", "pedido_id", "VARCHAR"),
            ("customer_id", "cliente_id", "VARCHAR"),
            ("order_status", "status", "VARCHAR"),
            ("order_purchase_timestamp", "data_compra", "TIMESTAMP"),
            ("order_approved_at", "data_aprovacao", "TIMESTAMP"),
            ("order_delivered_carrier_date", "data_envio", "TIMESTAMP"),
            ("order_delivered_customer_date", "data_entrega", "TIMESTAMP"),
            ("order_estimated_delivery_date", "data_entrega_prevista", "DATE"),
        ],
    ),
    "itens_pedido": (
        ("pedido_id", "item_seq"),
        [
            ("order_id", "pedido_id", "VARCHAR"),
            ("order_item_id", "item_seq", "INTEGER"),
            ("product_id", "produto_id", "VARCHAR"),
            ("seller_id", "vendedor_id", "VARCHAR"),
            ("shipping_limit_date", "data_limite_envio", "TIMESTAMP"),
            ("price", "preco", "DECIMAL(10,2)"),
            ("freight_value", "frete", "DECIMAL(10,2)"),
        ],
    ),
    "pagamentos": (
        ("pedido_id", "pagamento_seq"),
        [
            ("order_id", "pedido_id", "VARCHAR"),
            ("payment_sequential", "pagamento_seq", "INTEGER"),
            ("payment_type", "tipo", "VARCHAR"),
            ("payment_installments", "parcelas", "INTEGER"),
            ("payment_value", "valor", "DECIMAL(10,2)"),
        ],
    ),
    "clientes": (
        ("cliente_id",),
        [
            ("customer_id", "cliente_id", "VARCHAR"),
            ("customer_unique_id", "cliente_unico_id", "VARCHAR"),
            ("customer_zip_code_prefix", "cep_prefixo", "VARCHAR"),
            ("customer_city", "cidade", "VARCHAR"),
            ("customer_state", "uf", "VARCHAR"),
        ],
    ),
    "vendedores": (
        ("vendedor_id",),
        [
            ("seller_id", "vendedor_id", "VARCHAR"),
            ("seller_zip_code_prefix", "cep_prefixo", "VARCHAR"),
            ("seller_city", "cidade", "VARCHAR"),
            ("seller_state", "uf", "VARCHAR"),
        ],
    ),
    "produtos": (
        ("produto_id",),
        [
            ("product_id", "produto_id", "VARCHAR"),
            ("product_category_name", "categoria", "VARCHAR"),
            ("product_name_lenght", "tamanho_nome", "INTEGER"),
            ("product_description_lenght", "tamanho_descricao", "INTEGER"),
            ("product_photos_qty", "qtd_fotos", "INTEGER"),
            ("product_weight_g", "peso_g", "INTEGER"),
            ("product_length_cm", "comprimento_cm", "INTEGER"),
            ("product_height_cm", "altura_cm", "INTEGER"),
            ("product_width_cm", "largura_cm", "INTEGER"),
        ],
    ),
    "traducao_categorias": (
        ("categoria",),
        [
            ("product_category_name", "categoria", "VARCHAR"),
            ("product_category_name_english", "categoria_en", "VARCHAR"),
        ],
    ),
    "avaliacoes": (
        ("avaliacao_id", "pedido_id"),
        [
            ("review_id", "avaliacao_id", "VARCHAR"),
            ("order_id", "pedido_id", "VARCHAR"),
            ("review_score", "nota", "INTEGER"),
            ("review_comment_title", "titulo", "VARCHAR"),
            ("review_comment_message", "comentario", "VARCHAR"),
            ("review_creation_date", "data_criacao", "DATE"),
            ("review_answer_timestamp", "data_resposta", "TIMESTAMP"),
        ],
    ),
}

_LARGURA_NOME = max(len(f"{DESTINO}.{t}") for t in TABELAS)


def _ident(nome: str) -> str:
    return '"' + nome.replace('"', '""') + '"'


def _milhar(n: int) -> str:
    return f"{n:,}".replace(",", ".")


def _converter(coluna: str, tipo: str) -> str:
    col = _ident(coluna)
    if tipo == "VARCHAR":
        return col
    if tipo == "TIMESTAMP":
        return f"strptime({col}, '{_FORMATO_DATA_HORA}')"
    if tipo == "DATE":
        # O texto em raw sempre traz hora; ler com o formato completo e só
        # então truncar faz um valor fora do formato estourar em vez de passar.
        return f"CAST(strptime({col}, '{_FORMATO_DATA_HORA}') AS DATE)"
    return f"CAST({col} AS {tipo})"


def _select_convertido(tabela: str) -> str:
    _, colunas = TABELAS[tabela]
    campos = ",\n  ".join(
        f"{_converter(origem, tipo)} AS {_ident(destino)}"
        for origem, destino, tipo in colunas
    )
    return f"SELECT DISTINCT\n  {campos}\nFROM {ORIGEM}.{_ident(tabela)}"


def _fetch(con: duckdb.DuckDBPyConnection, sql: str) -> list[tuple]:
    # fetchall sempre: no DuckDB 2 um resultado lido pela metade deixa a
    # conexão ocupada (ver db.gravar).
    return con.execute(sql).fetchall()


def _abortar(linhas: list[str]) -> None:
    for linha in linhas:
        print(linha)
    print("Nada foi gravado em refined.")
    sys.exit(1)


def _diagnosticar_conversao(
    con: duckdb.DuckDBPyConnection, tabela: str, erro: duckdb.Error
) -> None:
    # O erro do DuckDB traz o valor que não converteu, mas não a coluna.
    # Reconverter uma coluna por vez, com as mesmas funções estritas, aponta
    # qual é sem recorrer a TRY_CAST/try_strptime.
    _, colunas = TABELAS[tabela]
    for origem, destino, tipo in colunas:
        if tipo == "VARCHAR":
            continue
        try:
            _fetch(
                con,
                f"SELECT count({_converter(origem, tipo)}) "
                f"FROM {ORIGEM}.{_ident(tabela)}",
            )
        except duckdb.Error as e:
            _abortar(
                [
                    (
                        f"Conversão falhou em {ORIGEM}.{tabela}, coluna {origem} "
                        f"(-> {destino} {tipo})."
                    ),
                    f"  {e}",
                ]
            )
    raise erro


def _conflitos_de_chave(con: duckdb.DuckDBPyConnection, tabela: str) -> None:
    chave, colunas = TABELAS[tabela]
    lista_chave = ", ".join(_ident(c) for c in chave)
    sql = f"""
        WITH dedup AS ({_select_convertido(tabela)}),
        repetidas AS (
            SELECT {lista_chave} FROM dedup
            GROUP BY {lista_chave} HAVING count(*) > 1
        )
        SELECT dedup.* FROM dedup JOIN repetidas USING ({lista_chave})
        ORDER BY ALL
    """
    try:
        conflitantes = _fetch(con, sql)
    except duckdb.Error as e:
        _diagnosticar_conversao(con, tabela, e)
    if not conflitantes:
        return

    nomes = [destino for _, destino, _ in colunas]
    posicoes = [nomes.index(c) for c in chave]
    linhas = [
        (
            f"Chave repetida com conteúdo diferente em {DESTINO}.{tabela} "
            f"(chave: {', '.join(chave)}):"
        )
    ]
    for linha in conflitantes:
        valor_chave = ", ".join(str(linha[p]) for p in posicoes)
        linhas.append(f"  [{valor_chave}] {dict(zip(nomes, linha))}")
    _abortar(linhas)


def _transformar(con: duckdb.DuckDBPyConnection, tabela: str) -> tuple[int, int]:
    alvo = f"{DESTINO}.{_ident(tabela)}"
    con.execute(f"CREATE OR REPLACE TABLE {alvo} AS {_select_convertido(tabela)}")
    entrada = _fetch(con, f"SELECT count(*) FROM {ORIGEM}.{_ident(tabela)}")[0][0]
    saida = _fetch(con, f"SELECT count(*) FROM {alvo}")[0][0]
    return entrada, saida


def _nulos(con: duckdb.DuckDBPyConnection, tabela: str) -> list[tuple[str, int]]:
    _, colunas = TABELAS[tabela]
    nomes = [destino for _, destino, _ in colunas]
    contagens = ", ".join(f"count(*) - count({_ident(n)})" for n in nomes)
    linha = _fetch(con, f"SELECT {contagens} FROM {DESTINO}.{_ident(tabela)}")[0]
    return [(n, q) for n, q in zip(nomes, linha) if q > 0]


def main() -> None:
    sys.stdout.reconfigure(encoding="utf-8")

    con = conectar()
    try:
        existentes = {
            nome
            for (nome,) in _fetch(
                con,
                f"SELECT table_name FROM information_schema.tables "
                f"WHERE table_schema = '{ORIGEM}'",
            )
        }
        faltando = [t for t in TABELAS if t not in existentes]
        if faltando:
            print(f"Tabelas não encontradas no schema {ORIGEM}:")
            for tabela in faltando:
                print(f"  {ORIGEM}.{tabela}")
            print('Rode antes: uv run python -m pipeline.ingestao')
            sys.exit(1)

        # Conversão e chave são validadas nas oito tabelas antes de gravar a
        # primeira: falha na sexta não deixa cinco tabelas novas ao lado de
        # três antigas. E fora de transação, porque erro dentro dela aborta a
        # transação e impede o diagnóstico coluna a coluna.
        for tabela in TABELAS:
            _conflitos_de_chave(con, tabela)

        con.execute("BEGIN TRANSACTION")
        try:
            criar_schema(con, DESTINO)
            total_entrada = total_saida = 0
            for tabela in TABELAS:
                entrada, saida = _transformar(con, tabela)
                total_entrada += entrada
                total_saida += saida
                nome = f"{DESTINO}.{tabela}"
                print(
                    f"{nome:<{_LARGURA_NOME}} {_milhar(entrada):>7} -> "
                    f"{_milhar(saida):>7} linhas  "
                    f"({_milhar(entrada - saida)} duplicatas)"
                )
                nulos = _nulos(con, tabela)
                if nulos:
                    lista = ", ".join(f"{c} {_milhar(q)}" for c, q in nulos)
                    print(f"    nulos mantidos: {lista}")
            con.execute("COMMIT")
        except BaseException:
            con.execute("ROLLBACK")
            raise

        print(
            f"{'total':<{_LARGURA_NOME}} {_milhar(total_entrada):>7} -> "
            f"{_milhar(total_saida):>7} linhas  "
            f"({_milhar(total_entrada - total_saida)} duplicatas)"
        )
    finally:
        con.close()


if __name__ == "__main__":
    main()
