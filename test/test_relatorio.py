"""Testes de relatorio.py: critérios R1 a R5 da docstring do módulo."""

import json
import re
from datetime import datetime
from pathlib import Path

import duckdb
import pytest

import painel
import relatorio


def _preparar(tmp_path, monkeypatch) -> Path:
    """Banco com os dez marts de painel.MARTS e saída do relatório em tmp_path."""
    banco = tmp_path / "olist.duckdb"
    monkeypatch.setattr(painel, "ARQUIVO_BANCO", banco)
    saida = tmp_path / "relatorio.html"
    monkeypatch.setattr(relatorio, "ARQUIVO", saida)
    with duckdb.connect(str(banco)) as con:
        con.execute("CREATE SCHEMA marts")
        con.execute(
            "CREATE TABLE marts.kpis AS SELECT 160.0 AS ticket_medio, 0.75 AS pct_cancelados, "
            "12.5 AS pct_frete, 11.3 AS dias_entrega, 4.1 AS nota_media"
        )
        con.execute(
            "CREATE TABLE marts.recompra AS SELECT * FROM "
            "(VALUES (1, 96.5), (2, 3.5)) t(pedidos_por_cliente, pct_clientes)"
        )
        con.execute("CREATE TABLE marts.entrega_no_prazo AS SELECT 88.4 AS pct_no_prazo")
        con.execute(
            "CREATE TABLE marts.vendas_mensais AS SELECT * FROM (VALUES "
            # dez/2016: antes do período padrão, fica fora do gráfico
            "(DATE '2016-12-01', 10.0), "
            # jan/2017 e ago/2018: as duas pontas do período, ficam
            "(DATE '2017-01-01', 20.0), "
            "(DATE '2018-08-01', 30.0), "
            # set/2018: depois do período padrão, fica fora
            "(DATE '2018-09-01', 40.0)"
            ") t(mes, receita)"
        )
        con.execute(
            "CREATE TABLE marts.top_categorias AS SELECT * FROM "
            "(VALUES ('moveis', 300.0), ('livros', 100.0)) t(categoria, receita)"
        )
        con.execute(
            "CREATE TABLE marts.mix_pagamento AS SELECT * FROM "
            "(VALUES ('credit_card', 80.0), ('boleto', 20.0)) t(tipo, pct_valor)"
        )
        con.execute(
            "CREATE TABLE marts.ticket_medio_por_estado AS SELECT * FROM "
            "(VALUES ('SP', 120.0), ('AC', 200.0)) t(uf, ticket_medio)"
        )
        con.execute(
            "CREATE TABLE marts.clientes_por_uf AS SELECT * FROM "
            "(VALUES ('SP', 500), ('AC', 10)) t(uf, clientes)"
        )
        con.execute(
            "CREATE TABLE marts.nota_por_categoria AS SELECT * FROM "
            "(VALUES ('moveis', 3.5, 1), ('livros', 4.5, 2)) t(categoria, nota_media, posicao_pior)"
        )
        con.execute(
            "CREATE TABLE marts.vendedores_pareto AS SELECT * FROM "
            "(VALUES (1, 70.0), (2, 100.0)) t(posicao, pct_acumulado)"
        )
    return saida


def _congelar_relogio(monkeypatch, momento: datetime) -> None:
    class Relogio(datetime):
        @classmethod
        def now(cls, tz=None):
            return momento

    monkeypatch.setattr(relatorio, "datetime", Relogio)


def test_gera_o_arquivo_no_caminho_configurado(tmp_path, monkeypatch):
    saida = _preparar(tmp_path, monkeypatch)
    relatorio.main()
    assert saida.is_file()
    assert "<title>Olist · visão da operação</title>" in saida.read_text(encoding="utf-8")


def test_rodar_duas_vezes_muda_so_o_rodape(tmp_path, monkeypatch):
    saida = _preparar(tmp_path, monkeypatch)
    _congelar_relogio(monkeypatch, datetime(2026, 10, 25, 14, 3))
    relatorio.main()
    primeira = saida.read_text(encoding="utf-8").splitlines()
    _congelar_relogio(monkeypatch, datetime(2026, 10, 26, 9, 30))
    relatorio.main()
    segunda = saida.read_text(encoding="utf-8").splitlines()

    diferentes = [(a, b) for a, b in zip(primeira, segunda) if a != b]
    assert len(primeira) == len(segunda)
    assert diferentes == [
        ("<footer>Dados de 25/10/2026 14:03</footer>", "<footer>Dados de 26/10/2026 09:30</footer>")
    ]


def test_sem_banco_encerra_sem_escrever_o_arquivo(tmp_path, monkeypatch):
    monkeypatch.setattr(painel, "ARQUIVO_BANCO", tmp_path / "olist.duckdb")
    saida = tmp_path / "relatorio.html"
    monkeypatch.setattr(relatorio, "ARQUIVO", saida)
    with pytest.raises(SystemExit) as erro:
        relatorio.main()
    assert erro.value.code == 1
    assert not saida.exists()


def test_os_sete_graficos_tem_div_id_fixo_e_plotly_entra_uma_vez(tmp_path, monkeypatch):
    saida = _preparar(tmp_path, monkeypatch)
    relatorio.main()
    html = saida.read_text(encoding="utf-8")
    for i in range(1, 8):
        assert f'id="g{i:02d}"' in html
    assert 'id="g08"' not in html
    assert html.count("cdn.plot.ly") == 1


def test_faturamento_mostra_so_o_periodo_padrao_e_diz_qual_e(tmp_path, monkeypatch):
    saida = _preparar(tmp_path, monkeypatch)
    relatorio.main()
    html = saida.read_text(encoding="utf-8")
    # O plotly grava os textos no JSON com escapes (· e / viram \uXXXX): decodifica.
    textos = [json.loads(t) for t in re.findall(r'"text":("(?:[^"\\]|\\.)*")', html)]
    assert "01 · Faturamento mensal · jan/2017 a ago/2018" in textos
    assert "2017-01-01" in html
    assert "2018-08-01" in html
    assert "2016-12-01" not in html
    assert "2018-09-01" not in html


def test_cartoes_saem_formatados_pelo_painel(tmp_path, monkeypatch):
    saida = _preparar(tmp_path, monkeypatch)
    relatorio.main()
    html = saida.read_text(encoding="utf-8")
    assert '<div class="valor">R$ 160,00</div>' in html
    assert '<div class="valor">3,50%</div>' in html
