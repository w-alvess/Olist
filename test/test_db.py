"""Testes de pipeline/db.py: critérios D1 a D4 da docstring do módulo."""

from pathlib import Path

import duckdb
import pandas as pd
import pytest

from pipeline import db


def _banco_temporario(tmp_path, monkeypatch) -> Path:
    arquivo = tmp_path / "olist.duckdb"
    monkeypatch.setattr(db, "_ARQUIVO_BANCO", arquivo)
    return arquivo


def test_pasta_raw_vem_da_pasta_do_projeto_e_nao_do_diretorio_corrente(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    raiz = Path(db.__file__).resolve().parent.parent
    assert db.PASTA_RAW == raiz / "raw"
    assert tmp_path not in db.PASTA_RAW.parents


def test_conectar_cria_o_banco_quando_ele_falta(tmp_path, monkeypatch):
    arquivo = _banco_temporario(tmp_path, monkeypatch)
    assert not arquivo.exists()
    con = db.conectar()
    con.close()
    assert arquivo.is_file()


def test_conectar_devolve_a_conexao_aberta_para_quem_chama(tmp_path, monkeypatch):
    _banco_temporario(tmp_path, monkeypatch)
    con = db.conectar()
    try:
        assert con.execute("SELECT 41 + 1").fetchall() == [(42,)]
    finally:
        con.close()


def test_criar_schema_pode_rodar_duas_vezes(tmp_path):
    with duckdb.connect(str(tmp_path / "t.duckdb")) as con:
        db.criar_schema(con, "raw")
        db.criar_schema(con, "raw")
        schemas = con.execute(
            "SELECT count(*) FROM information_schema.schemata WHERE schema_name = 'raw'"
        ).fetchall()
    assert schemas == [(1,)]


def test_gravar_devolve_a_contagem_lida_do_banco(tmp_path):
    # Três linhas, uma delas repetida: gravar não descarta nada.
    df = pd.DataFrame({"id": ["a", "b", "b"]}, dtype=str)
    with duckdb.connect(str(tmp_path / "t.duckdb")) as con:
        db.criar_schema(con, "raw")
        devolvido = db.gravar(con, df, "raw", "t")
        no_banco = con.execute("SELECT count(*) FROM raw.t").fetchall()[0][0]
    assert devolvido == 3
    assert no_banco == 3


def test_gravar_duas_vezes_recria_a_tabela_em_vez_de_acrescentar(tmp_path):
    with duckdb.connect(str(tmp_path / "t.duckdb")) as con:
        db.criar_schema(con, "raw")
        db.gravar(con, pd.DataFrame({"id": ["a", "b", "c"]}, dtype=str), "raw", "t")
        # Segunda gravação com duas linhas: o resultado é 2, não 5.
        devolvido = db.gravar(con, pd.DataFrame({"id": ["x", "y"]}, dtype=str), "raw", "t")
    assert devolvido == 2


def test_gravar_mantem_texto_como_varchar_e_nulo_como_null(tmp_path):
    df = pd.DataFrame(
        {
            # CEP com zero à esquerda: tem que continuar texto, com o zero.
            "cep": ["01310", None],
        },
        dtype=str,
    )
    with duckdb.connect(str(tmp_path / "t.duckdb")) as con:
        db.criar_schema(con, "raw")
        db.gravar(con, df, "raw", "t")
        tipo = con.execute(
            "SELECT data_type FROM information_schema.columns "
            "WHERE table_schema = 'raw' AND table_name = 't' AND column_name = 'cep'"
        ).fetchall()
        valores = con.execute("SELECT cep FROM raw.t ORDER BY cep NULLS LAST").fetchall()
    assert tipo == [("VARCHAR",)]
    assert valores == [("01310",), (None,)]


def test_gravar_nao_deixa_view_para_tras(tmp_path):
    with duckdb.connect(str(tmp_path / "t.duckdb")) as con:
        db.criar_schema(con, "raw")
        db.gravar(con, pd.DataFrame({"id": ["a"]}, dtype=str), "raw", "t")
        views = con.execute(
            "SELECT count(*) FROM duckdb_views() WHERE view_name = '_gravar_df'"
        ).fetchall()
    assert views == [(0,)]


def test_gravar_nao_deixa_view_para_tras_mesmo_quando_o_create_falha(tmp_path):
    with duckdb.connect(str(tmp_path / "t.duckdb")) as con:
        # Schema que não existe: o CREATE falha.
        with pytest.raises(duckdb.CatalogException):
            db.gravar(con, pd.DataFrame({"id": ["a"]}, dtype=str), "nao_existe", "t")
        views = con.execute(
            "SELECT count(*) FROM duckdb_views() WHERE view_name = '_gravar_df'"
        ).fetchall()
    assert views == [(0,)]
