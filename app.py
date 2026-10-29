"""Página do painel Olist. A spec está em painel.py.

Execução:
    uv run streamlit run app.py
"""

import pandas as pd
import streamlit as st

import painel


@st.cache_data
def ler() -> dict[str, pd.DataFrame]:
    return painel.ler(painel.MARTS)


st.set_page_config(page_title="Olist · visão da operação", layout="wide")

col_titulo, col_filtro = st.columns([2, 1])
col_titulo.title("Olist · visão da operação")
# O filtro precisa dos meses lidos do banco, mas o botão tem que limpar o
# cache antes da leitura: o container reserva o lugar do filtro acima do botão.
area_filtro = col_filtro.container()
if col_filtro.button("Recarregar dados"):
    st.cache_data.clear()

try:
    dados = ler()
except painel.MartsFaltando as e:
    st.error(
        "Não encontrado: " + ", ".join(e.nomes) + ".\n\n"
        "Rode: `uv run python -m pipeline.marts` e clique em Recarregar dados."
    )
    st.stop()

vendas = dados["vendas_mensais"].sort_values("mes")
meses = list(vendas["mes"])
with area_filtro:
    inicio, fim = st.select_slider(
        "Período do faturamento mensal",
        options=meses,
        value=(painel.INICIO_PADRAO, painel.FIM_PADRAO),
        format_func=painel.mes,
    )
    st.caption("O filtro recorta só o faturamento mensal: os cartões valem para o período inteiro.")

for coluna, (rotulo, valor) in zip(st.columns(7), painel.cartoes(dados)):
    coluna.metric(rotulo, valor)

recorte = vendas[(vendas["mes"] >= inicio) & (vendas["mes"] <= fim)]
st.plotly_chart(painel.faturamento_mensal(recorte), width="stretch")

c1, c2, c3 = st.columns(3)
c1.plotly_chart(painel.receita_por_categoria(dados["top_categorias"]), width="stretch")
c2.plotly_chart(painel.mix_pagamento(dados["mix_pagamento"]), width="stretch")
c3.plotly_chart(painel.ticket_medio_por_uf(dados["ticket_medio_por_estado"]), width="stretch")

c1, c2, c3 = st.columns(3)
c1.plotly_chart(painel.clientes_por_uf(dados["clientes_por_uf"]), width="stretch")
c2.plotly_chart(painel.nota_por_categoria(dados["nota_por_categoria"]), width="stretch")
c3.plotly_chart(painel.concentracao_vendedores(dados["vendedores_pareto"]), width="stretch")
