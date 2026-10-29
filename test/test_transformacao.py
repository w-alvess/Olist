"""Testes de pipeline/transformacao.py: critérios 1 a 9 da docstring do módulo."""

from datetime import date, datetime
from decimal import Decimal
from pathlib import Path

import duckdb
import pytest

from pipeline import db, transformacao

# Uma linha válida por tabela de raw, tudo texto, como a ingestão grava.
LINHAS_VALIDAS = {
    "pedidos": [
        ("p1", "c1", "delivered", "2017-01-05 10:00:00", "2017-01-05 11:00:00",
         "2017-01-06 09:00:00", "2017-01-10 15:00:00", "2017-01-10 00:00:00"),
    ],
    "itens_pedido": [("p1", "1", "prod1", "v1", "2017-01-07 10:00:00", "100.50", "15.25")],
    "pagamentos": [("p1", "1", "credit_card", "2", "115.75")],
    # CEP com zero à esquerda: tem que continuar texto.
    "clientes": [("c1", "u1", "01310", "sao paulo", "SP")],
    "vendedores": [("v1", "04567", "sao paulo", "SP")],
    "produtos": [("prod1", "moveis", "40", "300", "2", "500", "20", "10", "15")],
    "traducao_categorias": [("moveis", "furniture")],
    "avaliacoes": [("r1", "p1", "5", None, None, "2017-01-11 00:00:00", "2017-01-12 08:30:00")],
}


def _preparar(tmp_path, monkeypatch, trocar=None, sem=None) -> Path:
    """Cria raw com as oito tabelas (e geolocalizacao) num banco em tmp_path."""
    linhas = {**LINHAS_VALIDAS, **(trocar or {})}
    arquivo = tmp_path / "olist.duckdb"
    monkeypatch.setattr(db, "_ARQUIVO_BANCO", arquivo)
    with duckdb.connect(str(arquivo)) as con:
        con.execute("CREATE SCHEMA raw")
        for tabela, (_, colunas) in transformacao.TABELAS.items():
            if tabela == sem:
                continue
            nomes = [origem for origem, _, _ in colunas]
            con.execute(
                f"CREATE TABLE raw.{tabela} ({', '.join(f'{n} VARCHAR' for n in nomes)})"
            )
            marcas = ", ".join("?" for _ in nomes)
            con.executemany(f"INSERT INTO raw.{tabela} VALUES ({marcas})", linhas[tabela])
        con.execute("CREATE TABLE raw.geolocalizacao (geolocation_zip_code_prefix VARCHAR)")
        con.execute("INSERT INTO raw.geolocalizacao VALUES ('01310')")
    return arquivo


def _consultar(arquivo: Path, sql: str) -> list[tuple]:
    with duckdb.connect(str(arquivo)) as con:
        return con.execute(sql).fetchall()


def _tipo(arquivo: Path, tabela: str, coluna: str) -> str:
    return _consultar(
        arquivo,
        "SELECT data_type FROM information_schema.columns "
        f"WHERE table_schema = 'refined' AND table_name = '{tabela}' "
        f"AND column_name = '{coluna}'",
    )[0][0]


def _refined_existe(arquivo: Path) -> bool:
    return _consultar(
        arquivo,
        "SELECT count(*) FROM information_schema.schemata WHERE schema_name = 'refined'",
    ) == [(1,)]


def test_duplicata_exata_sai_e_fica_uma(tmp_path, monkeypatch):
    pedido = LINHAS_VALIDAS["pedidos"][0]
    # A mesma linha duas vezes: sai uma.
    arquivo = _preparar(tmp_path, monkeypatch, trocar={"pedidos": [pedido, pedido]})
    transformacao.main()
    assert _consultar(arquivo, "SELECT count(*) FROM refined.pedidos") == [(1,)]


def test_raw_nao_e_alterado(tmp_path, monkeypatch):
    pedido = LINHAS_VALIDAS["pedidos"][0]
    arquivo = _preparar(tmp_path, monkeypatch, trocar={"pedidos": [pedido, pedido]})
    transformacao.main()
    # A duplicata sai em refined, mas continua em raw.
    assert _consultar(arquivo, "SELECT count(*) FROM raw.pedidos") == [(2,)]


def test_chave_repetida_com_conteudo_diferente_encerra_sem_gravar(tmp_path, monkeypatch):
    pedido = LINHAS_VALIDAS["pedidos"][0]
    # Mesmo pedido_id, status diferente: não dá para escolher em silêncio.
    outro = (pedido[0], pedido[1], "canceled") + pedido[3:]
    arquivo = _preparar(tmp_path, monkeypatch, trocar={"pedidos": [pedido, outro]})
    with pytest.raises(SystemExit) as saida:
        transformacao.main()
    assert saida.value.code == 1
    assert not _refined_existe(arquivo)


def test_mesma_avaliacao_em_dois_pedidos_nao_e_conflito(tmp_path, monkeypatch):
    avaliacao = LINHAS_VALIDAS["avaliacoes"][0]
    # Mesmo avaliacao_id em outro pedido: a chave é (avaliacao_id, pedido_id).
    em_outro_pedido = (avaliacao[0], "p2") + avaliacao[2:]
    arquivo = _preparar(
        tmp_path, monkeypatch, trocar={"avaliacoes": [avaliacao, em_outro_pedido]}
    )
    transformacao.main()
    assert _consultar(arquivo, "SELECT count(*) FROM refined.avaliacoes") == [(2,)]


def test_colunas_sao_renomeadas_pelo_mapa(tmp_path, monkeypatch):
    arquivo = _preparar(tmp_path, monkeypatch)
    transformacao.main()
    colunas = _consultar(
        arquivo,
        "SELECT column_name FROM information_schema.columns "
        "WHERE table_schema = 'refined' AND table_name = 'pedidos' ORDER BY ordinal_position",
    )
    assert [c for (c,) in colunas] == [
        "pedido_id", "cliente_id", "status", "data_compra", "data_aprovacao",
        "data_envio", "data_entrega", "data_entrega_prevista",
    ]


def test_datas_com_hora_viram_timestamp(tmp_path, monkeypatch):
    arquivo = _preparar(tmp_path, monkeypatch)
    transformacao.main()
    assert _tipo(arquivo, "pedidos", "data_compra") == "TIMESTAMP"
    assert _tipo(arquivo, "avaliacoes", "data_resposta") == "TIMESTAMP"
    assert _consultar(arquivo, "SELECT data_compra FROM refined.pedidos") == [
        (datetime(2017, 1, 5, 10, 0, 0),)
    ]


def test_data_entrega_prevista_e_data_criacao_viram_date(tmp_path, monkeypatch):
    arquivo = _preparar(tmp_path, monkeypatch)
    transformacao.main()
    assert _tipo(arquivo, "pedidos", "data_entrega_prevista") == "DATE"
    assert _tipo(arquivo, "avaliacoes", "data_criacao") == "DATE"
    assert _consultar(arquivo, "SELECT data_entrega_prevista FROM refined.pedidos") == [
        (date(2017, 1, 10),)
    ]


def test_dinheiro_vira_decimal_com_centavos_exatos(tmp_path, monkeypatch):
    arquivo = _preparar(tmp_path, monkeypatch)
    transformacao.main()
    assert _tipo(arquivo, "itens_pedido", "preco") == "DECIMAL(10,2)"
    assert _tipo(arquivo, "pagamentos", "valor") == "DECIMAL(10,2)"
    assert _consultar(arquivo, "SELECT preco, frete FROM refined.itens_pedido") == [
        (Decimal("100.50"), Decimal("15.25"))
    ]


def test_contagens_e_medidas_viram_integer(tmp_path, monkeypatch):
    arquivo = _preparar(tmp_path, monkeypatch)
    transformacao.main()
    assert _tipo(arquivo, "avaliacoes", "nota") == "INTEGER"
    assert _tipo(arquivo, "produtos", "peso_g") == "INTEGER"


def test_cep_continua_texto_com_o_zero(tmp_path, monkeypatch):
    arquivo = _preparar(tmp_path, monkeypatch)
    transformacao.main()
    assert _tipo(arquivo, "clientes", "cep_prefixo") == "VARCHAR"
    assert _consultar(arquivo, "SELECT cep_prefixo FROM refined.clientes") == [("01310",)]


def test_dinheiro_que_nao_converte_encerra_sem_virar_nulo(tmp_path, monkeypatch):
    item = LINHAS_VALIDAS["itens_pedido"][0]
    # Preço com vírgula decimal: CAST para DECIMAL falha.
    invalido = item[:5] + ("100,50",) + item[6:]
    arquivo = _preparar(tmp_path, monkeypatch, trocar={"itens_pedido": [invalido]})
    with pytest.raises(SystemExit) as saida:
        transformacao.main()
    assert saida.value.code == 1
    assert not _refined_existe(arquivo)


def test_data_fora_do_formato_encerra_sem_virar_nulo(tmp_path, monkeypatch):
    pedido = LINHAS_VALIDAS["pedidos"][0]
    # Data no formato brasileiro: strptime com '%Y-%m-%d %H:%M:%S' falha.
    invalido = pedido[:3] + ("05/01/2017 10:00:00",) + pedido[4:]
    arquivo = _preparar(tmp_path, monkeypatch, trocar={"pedidos": [invalido]})
    with pytest.raises(SystemExit) as saida:
        transformacao.main()
    assert saida.value.code == 1
    assert not _refined_existe(arquivo)


def test_data_nula_continua_nula_e_a_linha_fica(tmp_path, monkeypatch):
    pedido = LINHAS_VALIDAS["pedidos"][0]
    # Pedido cancelado: sem envio e sem entrega.
    cancelado = ("p2", "c1", "canceled", "2017-01-08 09:00:00", None, None, None,
                 "2017-01-20 00:00:00")
    arquivo = _preparar(tmp_path, monkeypatch, trocar={"pedidos": [pedido, cancelado]})
    transformacao.main()
    assert _consultar(
        arquivo, "SELECT data_envio, data_entrega FROM refined.pedidos WHERE pedido_id = 'p2'"
    ) == [(None, None)]


def test_geolocalizacao_fica_fora_de_refined(tmp_path, monkeypatch):
    arquivo = _preparar(tmp_path, monkeypatch)
    transformacao.main()
    tabelas = _consultar(
        arquivo,
        "SELECT table_name FROM information_schema.tables "
        "WHERE table_schema = 'refined' ORDER BY table_name",
    )
    assert [t for (t,) in tabelas] == sorted(transformacao.TABELAS)


def test_rodar_duas_vezes_da_o_mesmo_resultado_que_rodar_uma(tmp_path, monkeypatch):
    arquivo = _preparar(tmp_path, monkeypatch)
    transformacao.main()
    transformacao.main()
    assert _consultar(arquivo, "SELECT count(*) FROM refined.pedidos") == [(1,)]


def test_tabela_faltando_em_raw_encerra_sem_transformar(tmp_path, monkeypatch):
    arquivo = _preparar(tmp_path, monkeypatch, sem="avaliacoes")
    with pytest.raises(SystemExit) as saida:
        transformacao.main()
    assert saida.value.code == 1
    assert not _refined_existe(arquivo)
