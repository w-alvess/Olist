"""Testes de pipeline/marts.py (critérios 1 a 4 da docstring) e das regras de
sql/marts/01_vendas_mensais.sql e sql/marts/03_entrega_no_prazo.sql."""

import shutil
from decimal import Decimal
from pathlib import Path

import duckdb
import pytest

from pipeline import db, marts, transformacao

SQL_DO_PROJETO = Path(marts.__file__).resolve().parent.parent / "sql" / "marts"


def _preparar(tmp_path, monkeypatch, sem=None) -> tuple[Path, Path]:
    """Banco com as oito tabelas de refined, vazias, e uma pasta sql/ vazia."""
    arquivo = tmp_path / "olist.duckdb"
    monkeypatch.setattr(db, "_ARQUIVO_BANCO", arquivo)
    pasta = tmp_path / "sql"
    pasta.mkdir()
    monkeypatch.setattr(marts, "PASTA_SQL", pasta)
    with duckdb.connect(str(arquivo)) as con:
        con.execute("CREATE SCHEMA refined")
        for tabela, (_, colunas) in transformacao.TABELAS.items():
            if tabela == sem:
                continue
            campos = ", ".join(f"{destino} {tipo}" for _, destino, tipo in colunas)
            con.execute(f"CREATE TABLE refined.{tabela} ({campos})")
    return arquivo, pasta


def _consultar(arquivo: Path, sql: str) -> list[tuple]:
    with duckdb.connect(str(arquivo)) as con:
        return con.execute(sql).fetchall()


def _tabelas_marts(arquivo: Path) -> list[str]:
    return [
        t for (t,) in _consultar(
            arquivo,
            "SELECT table_name FROM information_schema.tables "
            "WHERE table_schema = 'marts' ORDER BY table_name",
        )
    ]


# --- pipeline/marts.py -----------------------------------------------------

def test_nome_da_tabela_e_o_arquivo_sem_o_prefixo(tmp_path, monkeypatch):
    arquivo, pasta = _preparar(tmp_path, monkeypatch)
    (pasta / "01_vendas_mensais.sql").write_text("SELECT 1 AS x", encoding="utf-8")
    marts.main()
    assert _tabelas_marts(arquivo) == ["vendas_mensais"]


def test_ponto_e_virgula_e_espacos_do_final_sao_tirados(tmp_path, monkeypatch):
    arquivo, pasta = _preparar(tmp_path, monkeypatch)
    (pasta / "01_a.sql").write_text("SELECT 1 AS x;  \n\n", encoding="utf-8")
    marts.main()
    assert _consultar(arquivo, "SELECT x FROM marts.a") == [(1,)]


def test_arquivo_com_bom_do_bloco_de_notas_executa(tmp_path, monkeypatch):
    arquivo, pasta = _preparar(tmp_path, monkeypatch)
    (pasta / "01_a.sql").write_text("SELECT 1 AS x", encoding="utf-8-sig")
    marts.main()
    assert _consultar(arquivo, "SELECT x FROM marts.a") == [(1,)]


def test_arquivos_rodam_em_ordem_alfabetica(tmp_path, monkeypatch):
    arquivo, pasta = _preparar(tmp_path, monkeypatch)
    # 02 lê o que 01 gravou: só funciona se 01 rodar antes.
    (pasta / "02_b.sql").write_text("SELECT x + 1 AS y FROM marts.a", encoding="utf-8")
    (pasta / "01_a.sql").write_text("SELECT 1 AS x", encoding="utf-8")
    marts.main()
    assert _consultar(arquivo, "SELECT y FROM marts.b") == [(2,)]


def test_arquivo_sem_prefixo_para_antes_de_executar(tmp_path, monkeypatch):
    arquivo, pasta = _preparar(tmp_path, monkeypatch)
    (pasta / "01_a.sql").write_text("SELECT 1 AS x", encoding="utf-8")
    # Sem NN_: não há nome de tabela definido.
    (pasta / "vendas.sql").write_text("SELECT 1 AS x", encoding="utf-8")
    with pytest.raises(SystemExit) as saida:
        marts.main()
    assert saida.value.code == 1
    assert _tabelas_marts(arquivo) == []


def test_dois_arquivos_para_a_mesma_tabela_param_antes_de_executar(tmp_path, monkeypatch):
    arquivo, pasta = _preparar(tmp_path, monkeypatch)
    # DuckDB não diferencia maiúsculas: os dois iriam para marts.vendas.
    (pasta / "01_Vendas.sql").write_text("SELECT 1 AS x", encoding="utf-8")
    (pasta / "02_vendas.sql").write_text("SELECT 2 AS x", encoding="utf-8")
    with pytest.raises(SystemExit) as saida:
        marts.main()
    assert saida.value.code == 1
    assert _tabelas_marts(arquivo) == []


def test_pasta_sem_sql_encerra_e_deixa_o_schema_como_estava(tmp_path, monkeypatch):
    arquivo, pasta = _preparar(tmp_path, monkeypatch)
    (pasta / "01_a.sql").write_text("SELECT 1 AS x", encoding="utf-8")
    marts.main()
    (pasta / "01_a.sql").unlink()
    with pytest.raises(SystemExit) as saida:
        marts.main()
    assert saida.value.code == 1
    assert _tabelas_marts(arquivo) == ["a"]


def test_refined_incompleto_encerra_antes_de_tudo(tmp_path, monkeypatch):
    arquivo, pasta = _preparar(tmp_path, monkeypatch, sem="avaliacoes")
    (pasta / "01_a.sql").write_text("SELECT 1 AS x", encoding="utf-8")
    with pytest.raises(SystemExit) as saida:
        marts.main()
    assert saida.value.code == 1
    assert _tabelas_marts(arquivo) == []


def test_mart_vazio_encerra_e_deixa_o_schema_como_estava(tmp_path, monkeypatch):
    arquivo, pasta = _preparar(tmp_path, monkeypatch)
    (pasta / "01_a.sql").write_text("SELECT 1 AS x", encoding="utf-8")
    marts.main()
    # Segunda execução: 01 muda de conteúdo e 02 volta sem linha nenhuma.
    (pasta / "01_a.sql").write_text("SELECT 2 AS x", encoding="utf-8")
    (pasta / "02_vazio.sql").write_text("SELECT 1 AS x WHERE false", encoding="utf-8")
    with pytest.raises(SystemExit) as saida:
        marts.main()
    assert saida.value.code == 1
    assert _tabelas_marts(arquivo) == ["a"]
    assert _consultar(arquivo, "SELECT x FROM marts.a") == [(1,)]


def test_sql_com_erro_encerra_e_deixa_o_schema_como_estava(tmp_path, monkeypatch):
    arquivo, pasta = _preparar(tmp_path, monkeypatch)
    (pasta / "01_a.sql").write_text("SELECT 1 AS x", encoding="utf-8")
    marts.main()
    (pasta / "02_quebrado.sql").write_text("SELECT * FROM refined.nao_existe", encoding="utf-8")
    with pytest.raises(SystemExit) as saida:
        marts.main()
    assert saida.value.code == 1
    assert _tabelas_marts(arquivo) == ["a"]


def test_arquivo_apagado_faz_o_mart_sumir_na_execucao_seguinte(tmp_path, monkeypatch):
    arquivo, pasta = _preparar(tmp_path, monkeypatch)
    (pasta / "01_a.sql").write_text("SELECT 1 AS x", encoding="utf-8")
    (pasta / "02_b.sql").write_text("SELECT 2 AS x", encoding="utf-8")
    marts.main()
    (pasta / "02_b.sql").unlink()
    marts.main()
    assert _tabelas_marts(arquivo) == ["a"]


def test_plural_usa_singular_so_para_um():
    assert marts._plural(1, "mart") == "1 mart"
    assert marts._plural(1234, "linha") == "1.234 linhas"


# --- sql/marts/01_vendas_mensais.sql ---------------------------------------

def _rodar_mart_do_projeto(tmp_path, monkeypatch, nome_arquivo, pedidos, itens=()):
    arquivo, pasta = _preparar(tmp_path, monkeypatch)
    shutil.copy(SQL_DO_PROJETO / nome_arquivo, pasta / nome_arquivo)
    with duckdb.connect(str(arquivo)) as con:
        con.executemany(
            "INSERT INTO refined.pedidos "
            "(pedido_id, status, data_compra, data_entrega, data_entrega_prevista) "
            "VALUES (?, ?, ?, ?, ?)",
            pedidos,
        )
        if itens:
            con.executemany(
                "INSERT INTO refined.itens_pedido (pedido_id, item_seq, preco) VALUES (?, ?, ?)",
                itens,
            )
    marts.main()
    return arquivo


PEDIDOS_01 = [
    # p1: entregue em janeiro, com dois itens
    ("p1", "delivered", "2017-01-05 10:00:00", None, None),
    # p2: cancelado em janeiro
    ("p2", "canceled", "2017-01-20 10:00:00", None, None),
    # p3: indisponível em janeiro
    ("p3", "unavailable", "2017-01-25 10:00:00", None, None),
    # p4: entregue em fevereiro, um item
    ("p4", "delivered", "2017-02-03 10:00:00", None, None),
]
ITENS_01 = [
    ("p1", 1, Decimal("100.00")),
    ("p1", 2, Decimal("50.00")),
    ("p2", 1, Decimal("30.00")),
    ("p3", 1, Decimal("7.00")),
    ("p4", 1, Decimal("20.00")),
]


def test_pedido_com_dois_itens_conta_uma_vez(tmp_path, monkeypatch):
    arquivo = _rodar_mart_do_projeto(
        tmp_path, monkeypatch, "01_vendas_mensais.sql", PEDIDOS_01, ITENS_01
    )
    # Janeiro: só p1 é válido; seus dois itens somam 100,00 + 50,00.
    assert _consultar(
        arquivo, "SELECT pedidos, receita FROM marts.vendas_mensais WHERE mes = '2017-01-01'"
    ) == [(1, Decimal("150.00"))]


def test_cancelado_e_indisponivel_ficam_fora_da_receita(tmp_path, monkeypatch):
    arquivo = _rodar_mart_do_projeto(
        tmp_path, monkeypatch, "01_vendas_mensais.sql", PEDIDOS_01, ITENS_01
    )
    # Os 30,00 de p2 e os 7,00 de p3 não entram: total 150,00 + 20,00.
    assert _consultar(arquivo, "SELECT sum(receita) FROM marts.vendas_mensais") == [
        (Decimal("170.00"),)
    ]


def test_vendas_mensais_tem_uma_linha_por_mes_de_compra(tmp_path, monkeypatch):
    arquivo = _rodar_mart_do_projeto(
        tmp_path, monkeypatch, "01_vendas_mensais.sql", PEDIDOS_01, ITENS_01
    )
    assert _consultar(arquivo, "SELECT mes::VARCHAR FROM marts.vendas_mensais") == [
        ("2017-01-01",), ("2017-02-01",)
    ]


# --- sql/marts/03_entrega_no_prazo.sql -------------------------------------

PEDIDOS_03 = [
    # a: entregue às 15h do dia previsto -> no prazo
    ("a", "delivered", "2017-01-01 10:00:00", "2017-01-10 15:00:00", "2017-01-10"),
    # b: entregue às 08h do dia seguinte ao previsto -> atrasado
    ("b", "delivered", "2017-01-01 10:00:00", "2017-01-11 08:00:00", "2017-01-10"),
    # c: entregue um dia antes -> no prazo
    ("c", "delivered", "2017-01-01 10:00:00", "2017-01-09 23:00:00", "2017-01-10"),
    # d: delivered sem data de entrega -> fora do denominador
    ("d", "delivered", "2017-01-01 10:00:00", None, "2017-01-10"),
    # e: ainda em trânsito -> fora do denominador
    ("e", "shipped", "2017-01-01 10:00:00", None, "2017-01-10"),
]


def test_entrega_no_dia_previsto_a_tarde_esta_no_prazo(tmp_path, monkeypatch):
    arquivo = _rodar_mart_do_projeto(
        tmp_path, monkeypatch, "03_entrega_no_prazo.sql", PEDIDOS_03[:1]
    )
    assert _consultar(
        arquivo, "SELECT no_prazo, atrasados FROM marts.entrega_no_prazo"
    ) == [(1, 0)]


def test_entrega_no_prazo_conta_so_entregues_com_data(tmp_path, monkeypatch):
    arquivo = _rodar_mart_do_projeto(
        tmp_path, monkeypatch, "03_entrega_no_prazo.sql", PEDIDOS_03
    )
    # Denominador a, b, c; no prazo a e c; atrasado b; 2 de 3 = 66,7%.
    assert _consultar(
        arquivo,
        "SELECT entregues, no_prazo, atrasados, pct_no_prazo::VARCHAR "
        "FROM marts.entrega_no_prazo",
    ) == [(3, 2, 1, "66.7")]
