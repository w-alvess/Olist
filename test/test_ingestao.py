"""Testes de pipeline/ingestao.py: critérios 1 a 7 da docstring do módulo."""

import gzip
from pathlib import Path

import duckdb
import pytest

from pipeline import db, ingestao

# Um CSV pequeno por arquivo esperado. O conteúdo das colunas não importa para
# a ingestão; só pedidos e clientes carregam os casos de borda.
CSVS = {
    "olist_orders_dataset.csv.gz": (
        "order_id,order_status,order_delivered_customer_date\n"
        # pedido entregue, data preenchida
        "p1,delivered,2017-01-10 15:00:00\n"
        # pedido cancelado: data de entrega vazia, tem que virar nulo
        "p2,canceled,\n"
        # linha duplicada de p1: a ingestão não deduplica
        "p1,delivered,2017-01-10 15:00:00\n"
    ),
    "olist_order_items_dataset.csv.gz": (
        "order_id,order_item_id,price\n"
        # pedido com dois itens
        "p1,1,100.00\n"
        "p1,2,50.00\n"
    ),
    "olist_order_payments_dataset.csv.gz": "order_id,payment_value\np1,150.00\n",
    "olist_order_reviews_dataset.csv.gz": (
        "review_id,order_id,review_comment_title\n"
        # título literal "NA": é texto, não nulo
        "r1,p1,NA\n"
    ),
    "olist_customers_dataset.csv.gz": (
        "customer_id,customer_zip_code_prefix,customer_city\n"
        # CEP com zero à esquerda e cidade com acento
        "c1,01310,são paulo\n"
    ),
    "olist_sellers_dataset.csv.gz": "seller_id,seller_state\nv1,SP\n",
    "olist_products_dataset.csv.gz": "product_id,product_category_name\nprod1,moveis\n",
    "product_category_name_translation.csv.gz": (
        "product_category_name,product_category_name_english\nmoveis,furniture\n"
    ),
    "olist_geolocation_dataset.csv.gz": "geolocation_zip_code_prefix\n01310\n04567\n",
}


def _preparar(tmp_path, monkeypatch, sem: str | None = None) -> Path:
    pasta = tmp_path / "raw"
    pasta.mkdir()
    for nome, texto in CSVS.items():
        if nome == sem:
            continue
        with gzip.open(pasta / nome, "wt", encoding="utf-8", newline="") as f:
            f.write(texto)
    monkeypatch.setattr(ingestao, "PASTA_RAW", pasta)
    arquivo = tmp_path / "olist.duckdb"
    monkeypatch.setattr(db, "_ARQUIVO_BANCO", arquivo)
    return arquivo


def _consultar(arquivo: Path, sql: str) -> list[tuple]:
    with duckdb.connect(str(arquivo)) as con:
        return con.execute(sql).fetchall()


def test_cada_csv_vira_uma_tabela_com_as_mesmas_linhas(tmp_path, monkeypatch):
    arquivo = _preparar(tmp_path, monkeypatch)
    ingestao.main()
    for nome, tabela in ingestao.ARQUIVOS_TABELAS.items():
        # Linhas do CSV menos o cabeçalho.
        esperado = CSVS[nome].count("\n") - 1
        assert _consultar(arquivo, f"SELECT count(*) FROM raw.{tabela}") == [(esperado,)]


def test_linha_duplicada_nao_e_descartada(tmp_path, monkeypatch):
    arquivo = _preparar(tmp_path, monkeypatch)
    ingestao.main()
    assert _consultar(arquivo, "SELECT count(*) FROM raw.pedidos WHERE order_id = 'p1'") == [(2,)]


def test_nomes_de_coluna_nao_mudam(tmp_path, monkeypatch):
    arquivo = _preparar(tmp_path, monkeypatch)
    ingestao.main()
    colunas = _consultar(
        arquivo,
        "SELECT column_name FROM information_schema.columns "
        "WHERE table_schema = 'raw' AND table_name = 'pedidos' ORDER BY ordinal_position",
    )
    assert colunas == [("order_id",), ("order_status",), ("order_delivered_customer_date",)]


def test_toda_coluna_entra_como_texto(tmp_path, monkeypatch):
    arquivo = _preparar(tmp_path, monkeypatch)
    ingestao.main()
    tipos = _consultar(
        arquivo,
        "SELECT DISTINCT data_type FROM information_schema.columns WHERE table_schema = 'raw'",
    )
    assert tipos == [("VARCHAR",)]


def test_cep_com_zero_a_esquerda_mantem_o_zero(tmp_path, monkeypatch):
    arquivo = _preparar(tmp_path, monkeypatch)
    ingestao.main()
    assert _consultar(arquivo, "SELECT customer_zip_code_prefix FROM raw.clientes") == [("01310",)]


def test_campo_vazio_vira_nulo(tmp_path, monkeypatch):
    arquivo = _preparar(tmp_path, monkeypatch)
    ingestao.main()
    assert _consultar(
        arquivo, "SELECT order_delivered_customer_date FROM raw.pedidos WHERE order_id = 'p2'"
    ) == [(None,)]


def test_texto_na_continua_texto_e_nao_vira_nulo(tmp_path, monkeypatch):
    arquivo = _preparar(tmp_path, monkeypatch)
    ingestao.main()
    assert _consultar(arquivo, "SELECT review_comment_title FROM raw.avaliacoes") == [("NA",)]


def test_acento_em_utf8_chega_sem_troca(tmp_path, monkeypatch):
    arquivo = _preparar(tmp_path, monkeypatch)
    ingestao.main()
    assert _consultar(arquivo, "SELECT customer_city FROM raw.clientes") == [("são paulo",)]


def test_rodar_duas_vezes_da_o_mesmo_resultado_que_rodar_uma(tmp_path, monkeypatch):
    arquivo = _preparar(tmp_path, monkeypatch)
    ingestao.main()
    ingestao.main()
    assert _consultar(arquivo, "SELECT count(*) FROM raw.pedidos") == [(3,)]


def test_arquivo_faltando_encerra_sem_gravar_nada(tmp_path, monkeypatch):
    arquivo = _preparar(tmp_path, monkeypatch, sem="olist_sellers_dataset.csv.gz")
    with pytest.raises(SystemExit) as saida:
        ingestao.main()
    assert saida.value.code == 1
    # O banco nem chega a ser aberto.
    assert not arquivo.exists()


def test_milhar_usa_ponto():
    assert ingestao._milhar(1234567) == "1.234.567"
