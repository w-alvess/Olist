"""Etapa 1: ingestão dos nove .csv.gz da Olist no schema raw do olist.duckdb.

Execução:
    uv run python -m pipeline.ingestao

1. ESCOPO E NOMES
   Schema de destino: raw. Cada arquivo vira uma tabela com nome em
   português (ver ARQUIVOS_TABELAS), o mapa completo e literal da spec.
   Por quê: é o vocabulário digitado de memória nos JOINs das próximas aulas.

2. PROIBIÇÕES (a regra central desta etapa)
   Nenhuma conversão de tipo. Nenhuma linha descartada ou deduplicada.
   Nenhum nome de coluna alterado. Nenhum valor corrigido, preenchido ou
   normalizado. Data continua texto, nulo continua nulo.
   Por quê: a fronteira entre "o dado que chegou" e "o dado que eu decidi"
   precisa existir em algum lugar, e esse lugar é a passagem de raw para
   refined, na etapa 2. Se a correção acontecer aqui, a fronteira some.

3. REEXECUÇÃO
   Rodar dez vezes dá o mesmo resultado que rodar uma: a tabela é recriada
   (CREATE OR REPLACE), nunca acrescentada.
   Por quê: é o que permite errar sem medo.

4. LEITURA DO ARQUIVO
   encoding declarado como utf-8, nunca adivinhado. Os .csv.gz são lidos
   direto, sem descompactar. Campo vazio vira nulo, não string vazia.
   Por quê: adivinhar encoding troca acento sem aviso, e string vazia no
   lugar de nulo esconde a ausência do dado da etapa 2.

5. TIPAGEM
   Toda coluna entra como texto (dtype=str), inferência desligada.
   Por quê: inferência lê CEP com zero à esquerda como número e o zero
   desaparece sem aviso. A conversão acontece na etapa 2, onde é uma
   decisão registrada.

6. SAÍDA NA TELA
   Uma linha por tabela, com nome qualificado e contagem vinda do banco (não
   do DataFrame), milhar separado por ponto, e uma linha final com o total.
   stdout reconfigurado para utf-8.
   Por quê: essa saída é o único instrumento de conferência desta etapa, e
   no Prompt de Comando do Windows acento sai embaralhado por padrão.

7. ERRO
   Antes de abrir o banco, verifica se os nove arquivos existem. Faltando
   qualquer um: lista os que faltam, diz em que pasta procurou e encerra com
   sys.exit(1), sem ingerir nada.
   Por quê: ingerir oito de nove tabelas em silêncio produz um dashboard
   errado que parece certo.

Separação: este módulo não importa ui.py, não sobe servidor, não abre
navegador e não depende da extensão ui do DuckDB.
"""

import sys

import pandas as pd

from pipeline.db import PASTA_RAW, conectar, criar_schema, gravar

SCHEMA = "raw"

ARQUIVOS_TABELAS = {
    "olist_orders_dataset.csv.gz": "pedidos",
    "olist_order_items_dataset.csv.gz": "itens_pedido",
    "olist_order_payments_dataset.csv.gz": "pagamentos",
    "olist_order_reviews_dataset.csv.gz": "avaliacoes",
    "olist_customers_dataset.csv.gz": "clientes",
    "olist_sellers_dataset.csv.gz": "vendedores",
    "olist_products_dataset.csv.gz": "produtos",
    "product_category_name_translation.csv.gz": "traducao_categorias",
    "olist_geolocation_dataset.csv.gz": "geolocalizacao",
}


def _milhar(n: int) -> str:
    return f"{n:,}".replace(",", ".")


def ler_csv(caminho) -> pd.DataFrame:
    return pd.read_csv(
        caminho,
        compression="gzip",
        encoding="utf-8",
        dtype=str,
        # Por padrão o pandas também transforma textos como "NA", "null" e
        # "N/A" em nulo, o que seria corrigir valor. Só o campo vazio vira nulo.
        keep_default_na=False,
        na_values=[""],
    )


def main() -> None:
    sys.stdout.reconfigure(encoding="utf-8")

    faltando = [a for a in ARQUIVOS_TABELAS if not (PASTA_RAW / a).is_file()]
    if faltando:
        print(f"Arquivos não encontrados em {PASTA_RAW}:")
        for arquivo in faltando:
            print(f"  {arquivo}")
        print("Nada foi gravado.")
        sys.exit(1)

    con = conectar()
    try:
        criar_schema(con, SCHEMA)
        total = 0
        for arquivo, tabela in ARQUIVOS_TABELAS.items():
            df = ler_csv(PASTA_RAW / arquivo)
            contagem = gravar(con, df, SCHEMA, tabela)
            total += contagem
            print(f"{SCHEMA}.{tabela:<22} {_milhar(contagem):>12}")
        print(f"{'total':<26} {_milhar(total):>12}")
    finally:
        con.close()


if __name__ == "__main__":
    main()
