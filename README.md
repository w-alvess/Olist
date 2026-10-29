# Olist · visão da operação

Pipeline de dados sobre o [dataset público de e-commerce da Olist](https://www.kaggle.com/datasets/olistbr/brazilian-ecommerce), com DuckDB, marts em SQL, painel em Streamlit e relatório HTML estático.

## Estrutura

```
raw/            nove .csv.gz originais da Olist
pipeline/
  db.py         conexão com o olist.duckdb, compartilhada pelas etapas
  ingestao.py   etapa 1: CSVs  -> schema raw
  transformacao.py  etapa 2: raw -> schema refined (tipos, chaves, nulos)
  marts.py      etapa 3: refined -> schema marts, um mart por arquivo de sql/marts/
sql/marts/      consultas dos marts (vendas mensais, top categorias, entrega no prazo...)
painel.py       spec do painel: leitura dos marts, formatação e gráficos
app.py          painel Streamlit
relatorio.py    gera relatorio.html com os mesmos números e gráficos do painel
ui.py           abre o olist.duckdb no navegador pela extensão ui do DuckDB
test/           testes com pytest
```

## Como rodar

Requer [uv](https://docs.astral.sh/uv/) e Python 3.13+.

```bash
uv sync
```

O `olist.duckdb` não está no repositório (passa de 100 MB). Para gerá-lo a partir de `raw/`, rode as três etapas em ordem:

```bash
uv run python -m pipeline.ingestao
uv run python -m pipeline.transformacao
uv run python -m pipeline.marts
```

Depois disso:

```bash
uv run streamlit run app.py   # painel interativo
uv run python relatorio.py    # gera relatorio.html
uv run python ui.py           # explorador do banco em http://localhost:4213
```

## Painel online

O painel é publicado no [Streamlit Community Cloud](https://share.streamlit.io) a partir de `streamlit_app.py`. Como o `olist.duckdb` não está no repositório, esse arquivo roda as três etapas do pipeline na primeira subida do servidor (uns 10 segundos) e depois abre o `app.py`.

## Testes e lint

```bash
uv run pytest --cov
uv run ruff check .
```
