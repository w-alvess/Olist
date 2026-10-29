"""Entrada do painel no Streamlit Community Cloud. A página é app.py.

Execução:
    uv run streamlit run streamlit_app.py

S1. BANCO GERADO NO SERVIDOR
    Se o olist.duckdb não existe, roda as três etapas do pipeline a partir de
    raw/ (pipeline.ingestao, pipeline.transformacao, pipeline.marts) e só
    depois carrega app.py. Com o banco presente, não roda nada.
    Por quê: o olist.duckdb passa de 100 MB e não vai para o GitHub; o
    pipeline inteiro leva uns 10 segundos.

S2. UMA VEZ POR PROCESSO
    A preparação fica em st.cache_resource: várias pessoas abrindo o link ao
    mesmo tempo não disparam o pipeline em paralelo.
"""

import runpy
import subprocess
import sys
from pathlib import Path

import streamlit as st

RAIZ = Path(__file__).resolve().parent
ETAPAS = ["pipeline.ingestao", "pipeline.transformacao", "pipeline.marts"]


@st.cache_resource(show_spinner="Gerando o banco a partir dos CSVs da Olist...")
def preparar_banco() -> None:
    if (RAIZ / "olist.duckdb").is_file():
        return
    for etapa in ETAPAS:
        subprocess.run([sys.executable, "-m", etapa], cwd=RAIZ, check=True)


preparar_banco()
runpy.run_path(str(RAIZ / "app.py"), run_name="__main__")
