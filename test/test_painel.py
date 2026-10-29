"""Testes de painel.py: critérios P1, P2 (exceção da recompra), P3 e P4."""

import duckdb
import pandas as pd
import pytest

import painel

# --- P4: formato -----------------------------------------------------------

def test_numero_usa_ponto_no_milhar_e_virgula_no_decimal():
    assert painel.numero(1234567.891, 2) == "1.234.567,89"


def test_numero_sem_casas_arredonda_para_inteiro():
    assert painel.numero(48210) == "48.210"
    assert painel.numero(12.6) == "13"


def test_reais_poe_o_prefixo_e_duas_casas():
    assert painel.reais(2500000.5) == "R$ 2.500.000,50"


def test_reais_abaixo_de_mil_nao_tem_ponto():
    assert painel.reais(87.3) == "R$ 87,30"


def test_pct_poe_o_sinal_e_uma_casa():
    assert painel.pct(81.24) == "81,2%"
    assert painel.pct(4.5, 2) == "4,50%"


def test_mes_escreve_abreviacao_e_ano():
    assert painel.mes(pd.Timestamp("2017-01-01")) == "jan/2017"
    assert painel.mes(pd.Timestamp("2018-12-01")) == "dez/2018"


# --- cartões (P3 faixa 1 e a exceção de P2) --------------------------------

def _dados_cartoes():
    return {
        "kpis": pd.DataFrame(
            {
                "ticket_medio": [160.0],
                "pct_cancelados": [0.75],
                "pct_frete": [12.5],
                "dias_entrega": [11.3],
                "nota_media": [4.1],
            }
        ),
        # 96,5% compraram uma vez; o complemento é a recompra.
        "recompra": pd.DataFrame(
            {"pedidos_por_cliente": [1, 2, 3], "pct_clientes": [96.5, 3.0, 0.5]}
        ),
        "entrega_no_prazo": pd.DataFrame({"pct_no_prazo": [88.4]}),
    }


def test_cartoes_sao_sete_na_ordem_da_tela():
    rotulos = [r.split(" · ")[0] for r, _ in painel.cartoes(_dados_cartoes())]
    assert rotulos == [
        "Ticket médio", "Cancelados", "Peso do frete", "Recompra",
        "No prazo", "Dias até entregar", "Nota média",
    ]


def test_recompra_e_cem_menos_a_linha_de_um_pedido():
    valores = dict(painel.cartoes(_dados_cartoes()))
    assert valores["Recompra · % de clientes com 2+ pedidos"] == "3,50%"


def test_cartoes_vem_formatados():
    valores = [v for _, v in painel.cartoes(_dados_cartoes())]
    assert valores == ["R$ 160,00", "0,75%", "12,5%", "3,50%", "88,4%", "11,3", "4,10"]


# --- P1: leitura -----------------------------------------------------------

def _banco_com_marts(tmp_path, monkeypatch):
    arquivo = tmp_path / "olist.duckdb"
    monkeypatch.setattr(painel, "ARQUIVO_BANCO", arquivo)
    with duckdb.connect(str(arquivo)) as con:
        con.execute("CREATE SCHEMA marts")
        # kpis: uma linha, como o mart 11
        con.execute("CREATE TABLE marts.kpis AS SELECT 160.0 AS ticket_medio")
        # recompra: duas linhas, 1 e 2 pedidos por cliente
        con.execute(
            "CREATE TABLE marts.recompra AS "
            "SELECT * FROM (VALUES (1, 96.5), (2, 3.5)) t(pedidos_por_cliente, pct_clientes)"
        )
    return arquivo


def test_ler_devolve_um_dataframe_por_mart(tmp_path, monkeypatch):
    _banco_com_marts(tmp_path, monkeypatch)
    dados = painel.ler(["kpis", "recompra"])
    assert sorted(dados) == ["kpis", "recompra"]
    assert len(dados["kpis"]) == 1
    assert len(dados["recompra"]) == 2


def test_ler_sem_banco_avisa_o_arquivo_que_falta(tmp_path, monkeypatch):
    monkeypatch.setattr(painel, "ARQUIVO_BANCO", tmp_path / "olist.duckdb")
    with pytest.raises(painel.MartsFaltando) as erro:
        painel.ler(["kpis"])
    assert erro.value.nomes == ["olist.duckdb"]
    # Ler não cria o banco.
    assert not (tmp_path / "olist.duckdb").exists()


def test_ler_lista_todos_os_marts_que_faltam(tmp_path, monkeypatch):
    _banco_com_marts(tmp_path, monkeypatch)
    with pytest.raises(painel.MartsFaltando) as erro:
        # clientes_por_uf também é nome de função em painel.py: tem que ser
        # tratado como mart faltando, não como objeto Python.
        painel.ler(["kpis", "vendas_mensais", "clientes_por_uf"])
    assert erro.value.nomes == ["marts.vendas_mensais", "marts.clientes_por_uf"]


def test_ler_fecha_a_conexao_e_o_pipeline_consegue_gravar(tmp_path, monkeypatch):
    arquivo = _banco_com_marts(tmp_path, monkeypatch)
    painel.ler(["kpis"])
    # Com a conexão read_only ainda aberta, o DuckDB recusaria esta.
    with duckdb.connect(str(arquivo)) as con:
        con.execute("CREATE TABLE marts.nova AS SELECT 1 AS x")
        assert con.execute("SELECT x FROM marts.nova").fetchall() == [(1,)]


# --- P3/P4: uma função por gráfico -----------------------------------------

def _pontos(fig) -> int:
    return len(fig.data[0].x)


def test_faturamento_mensal_tem_um_ponto_por_mes():
    # Três meses fora de ordem: o gráfico ordena.
    df = pd.DataFrame(
        {
            "mes": pd.to_datetime(["2017-03-01", "2017-01-01", "2017-02-01"]),
            "receita": [300.0, 100.0, 200.0],
        }
    )
    fig = painel.faturamento_mensal(df)
    assert _pontos(fig) == 3
    assert list(fig.data[0].y) == [100.0, 200.0, 300.0]


def test_receita_por_categoria_tem_uma_barra_por_categoria():
    df = pd.DataFrame({"categoria": ["a", "b", "c"], "receita": [10.0, 30.0, 20.0]})
    assert _pontos(painel.receita_por_categoria(df)) == 3


def test_receita_por_categoria_mostra_as_dez_maiores_com_a_maior_em_cima():
    # Doze categorias: c00 tem receita 0, c11 tem receita 11.
    df = pd.DataFrame(
        {"categoria": [f"c{i:02d}" for i in range(12)], "receita": [float(i) for i in range(12)]}
    )
    fig = painel.receita_por_categoria(df)
    assert list(fig.data[0].y) == [f"c{i:02d}" for i in range(11, 1, -1)]
    assert fig.layout.yaxis.autorange == "reversed"


def test_mix_pagamento_tem_uma_barra_por_tipo():
    df = pd.DataFrame(
        {"tipo": ["boleto", "credit_card", "voucher"], "pct_valor": [20.0, 75.0, 5.0]}
    )
    assert _pontos(painel.mix_pagamento(df)) == 3


def test_ticket_medio_por_uf_tem_uma_barra_por_uf():
    df = pd.DataFrame({"uf": ["SP", "RJ", "AC", "MG"], "ticket_medio": [120.0, 140.0, 200.0, 130.0]})
    fig = painel.ticket_medio_por_uf(df)
    assert _pontos(fig) == 4
    # Maior em cima: primeira barra é a do maior ticket.
    assert fig.data[0].y[0] == "AC"


def test_clientes_por_uf_tem_uma_barra_por_uf():
    df = pd.DataFrame({"uf": ["SP", "RJ"], "clientes": [500, 120]})
    assert _pontos(painel.clientes_por_uf(df)) == 2


def test_nota_por_categoria_tem_um_ponto_por_categoria():
    df = pd.DataFrame(
        {"categoria": ["a", "b", "c"], "nota_media": [3.1, 3.9, 4.5], "posicao_pior": [1, 2, 3]}
    )
    assert _pontos(painel.nota_por_categoria(df)) == 3


def test_nota_por_categoria_mostra_as_dez_piores():
    # Doze categorias; posicao_pior 1 é a pior.
    df = pd.DataFrame(
        {
            "categoria": [f"c{i:02d}" for i in range(1, 13)],
            "nota_media": [3.0 + i / 10 for i in range(1, 13)],
            "posicao_pior": list(range(1, 13)),
        }
    )
    fig = painel.nota_por_categoria(df)
    assert list(fig.data[0].y) == [f"c{i:02d}" for i in range(1, 11)]


def test_concentracao_vendedores_tem_um_ponto_por_vendedor_e_linha_em_80():
    df = pd.DataFrame({"posicao": [1, 2, 3, 4], "pct_acumulado": [50.0, 80.0, 95.0, 100.0]})
    fig = painel.concentracao_vendedores(df)
    assert _pontos(fig) == 4
    assert fig.layout.shapes[0].y0 == 80


def test_grafico_tem_titulo_com_numero_do_mart_e_uma_cor_so():
    df = pd.DataFrame({"uf": ["SP", "RJ"], "clientes": [500, 120]})
    fig = painel.clientes_por_uf(df)
    assert fig.layout.title.text == "12 · Clientes por UF"
    assert fig.data[0].marker.color == painel.COR
