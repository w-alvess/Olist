"""Painel do olist.duckdb: leitura dos marts, formatação e gráficos.

A página é app.py (uv run streamlit run app.py). Este módulo não importa
streamlit, e por isso o relatório HTML também pode usá-lo.

P1. LEITURA
    ler(marts) -> dict nome -> DataFrame. Para cada nome, só
    SELECT * FROM marts.<nome>. Nenhuma outra SQL.
    Conexão com duckdb.connect("olist.duckdb", read_only=True), aberta e
    fechada dentro de ler().
    Por quê: uma conexão aberta segura o arquivo, e com o painel de pé o
    pipeline.marts não conseguiria gravar.

P2. NENHUM CÁLCULO
    Proibido aqui e em app.py: agrupar, somar, tirar média, contar, juntar
    tabelas, pivotar e qualquer conta entre colunas. Permitido: ordenar,
    filtrar linhas, head(n), renomear coluna e formatar texto.
    (Os nomes dos métodos ficam de fora deste texto de propósito: o aceite é
    uma busca por eles neste arquivo e em app.py, e ela tem que voltar vazia.)
    Única exceção: Recompra = 100 - recompra.pct_clientes da linha
    pedidos_por_cliente = 1, porque o mart 05 guarda o complemento.
    Por quê: número novo na tela exige um .sql novo em marts. Se faltar um
    número, o que falta é um mart, não uma conta no Python.

P3. LAYOUT (app.py), de cima para baixo, layout="wide"
    Cabeçalho: título "Olist · visão da operação" à esquerda, filtro de
      período à direita (P5).
    Faixa 1: sete cartões (st.metric), nesta ordem, cada rótulo com a
      definição curta: Ticket médio, Cancelados, Peso do frete, Recompra,
      No prazo, Dias até entregar, Nota média.
    Faixa 2, largura inteira: faturamento mensal, linha com marcadores.
    Faixa 3, três colunas: receita por categoria (top 10, barras
      horizontais, maior em cima); mix de pagamento (barras por pct_valor);
      ticket médio por UF (barras horizontais, maior em cima).
    Faixa 4, três colunas: clientes por UF (barras horizontais, maior em
      cima); nota por categoria (10 primeiras por posicao_pior, pontos, pior
      em cima); concentração de vendedores (pct_acumulado por posicao, linha
      tracejada em 80).
    Cada gráfico: título com o número do mart ("01 · Faturamento mensal"),
    uma cor só, eixo com unidade, width="stretch".
    Por quê: a ordem da tela é a ordem da leitura: primeiro o resumo, depois
    o tempo, depois o detalhe.

P4. FORMATO
    reais(valor, casas=2)  -> "R$ 1.003.862,14"
    pct(valor, casas=1)    -> "93,2%"
    numero(valor, casas=0) -> "96.470"
    Milhar com ponto e decimal com vírgula, sempre, sem locale do sistema.
    Por quê: o resultado não pode depender da máquina de quem roda.
    Uma função por gráfico, recebendo o DataFrame e devolvendo a figura.
    Por quê: o relatório HTML reaproveita as mesmas funções.

P5. FILTRO DE PERÍODO
    st.select_slider com os meses de vendas_mensais, padrão de jan/2017 a
    ago/2018. Recorta só as linhas do faturamento mensal; os cartões e os
    outros gráficos não mudam, e a página diz "os cartões valem para o
    período inteiro".
    Por quê: recortar linha é SELECT; recalcular cartão por período seria
    regra de negócio fora do SQL.

P6. CACHE E ERRO
    Leitura com st.cache_data; o botão "Recarregar dados" limpa o cache.
    Sem olist.duckdb, ou faltando um dos marts de P3: st.error dizendo quais,
    com o comando "uv run python -m pipeline.marts", e st.stop().
    Por quê: tela com gráfico faltando parece dado faltando no negócio.
"""

from pathlib import Path

import duckdb
import pandas as pd
import plotly.express as px
import plotly.graph_objects as go

# Resolvido a partir deste arquivo, como em pipeline/db.py: rodar o streamlit
# de outra pasta não pode procurar o banco no lugar errado.
ARQUIVO_BANCO = Path(__file__).resolve().parent / "olist.duckdb"

# Os marts que a tela de P3 usa.
MARTS = [
    "kpis",
    "recompra",
    "entrega_no_prazo",
    "vendas_mensais",
    "top_categorias",
    "mix_pagamento",
    "ticket_medio_por_estado",
    "clientes_por_uf",
    "nota_por_categoria",
    "vendedores_pareto",
]

# Período padrão do faturamento mensal (P5), compartilhado por app.py e
# relatorio.py para os dois mostrarem o mesmo recorte.
INICIO_PADRAO = pd.Timestamp("2017-01-01")
FIM_PADRAO = pd.Timestamp("2018-08-01")

COR = "#2a6f97"
ALTURA = 520

_MESES = ["jan", "fev", "mar", "abr", "mai", "jun",
          "jul", "ago", "set", "out", "nov", "dez"]


class MartsFaltando(Exception):
    """O banco não existe ou não tem todos os marts pedidos."""

    def __init__(self, nomes: list[str]):
        self.nomes = nomes
        super().__init__(", ".join(nomes))


def _ident(nome: str) -> str:
    return '"' + nome.replace('"', '""') + '"'


def ler(marts: list[str]) -> dict[str, pd.DataFrame]:
    # Levanta exceção em vez de devolver o dict incompleto: st.cache_data não
    # guarda exceção, então basta rodar o pipeline e recarregar a página.
    if not ARQUIVO_BANCO.is_file():
        raise MartsFaltando([ARQUIVO_BANCO.name])
    dados, faltando = {}, []
    con = duckdb.connect(str(ARQUIVO_BANCO), read_only=True)
    # Sem isto, mart faltando com o nome de uma função deste módulo
    # (clientes_por_uf...) acha a função Python em vez de dar CatalogException.
    con.execute("SET python_enable_replacements = false")
    try:
        for nome in marts:
            try:
                dados[nome] = con.execute(f"SELECT * FROM marts.{_ident(nome)}").df()
            except duckdb.CatalogException:
                faltando.append(f"marts.{nome}")
    finally:
        con.close()
    if faltando:
        raise MartsFaltando(faltando)
    return dados


# --- formato ---------------------------------------------------------------

def numero(valor: float, casas: int = 0) -> str:
    # Formata no padrão americano e troca os separadores: não depende de locale.
    texto = f"{valor:,.{casas}f}"
    return texto.replace(",", "_").replace(".", ",").replace("_", ".")


def reais(valor: float, casas: int = 2) -> str:
    return f"R$ {numero(valor, casas)}"


def pct(valor: float, casas: int = 1) -> str:
    return f"{numero(valor, casas)}%"


def mes(data) -> str:
    """2017-01-01 -> "jan/2017"."""
    return f"{_MESES[data.month - 1]}/{data.year}"


# --- cartões ---------------------------------------------------------------

def cartoes(dados: dict[str, pd.DataFrame]) -> list[tuple[str, str]]:
    """Os sete cartões de P3, como (rótulo, valor formatado), na ordem da tela."""
    kpis = dados["kpis"].iloc[0]
    recompra = dados["recompra"]
    um_pedido = recompra[recompra["pedidos_por_cliente"] == 1]["pct_clientes"].iloc[0]
    no_prazo = dados["entrega_no_prazo"]["pct_no_prazo"].iloc[0]
    return [
        ("Ticket médio · receita por pedido válido", reais(kpis["ticket_medio"])),
        ("Cancelados · % de todos os pedidos", pct(kpis["pct_cancelados"], 2)),
        ("Peso do frete · % do frete no valor pago", pct(kpis["pct_frete"], 1)),
        # A única conta permitida pela spec (P2): o mart 05 guarda o complemento.
        ("Recompra · % de clientes com 2+ pedidos", pct(100 - um_pedido, 2)),
        ("No prazo · % dos entregues até a data prevista", pct(no_prazo, 1)),
        ("Dias até entregar · média da compra à entrega", numero(kpis["dias_entrega"], 1)),
        ("Nota média · avaliações de 1 a 5", numero(kpis["nota_media"], 2)),
    ]


# --- gráficos --------------------------------------------------------------

def _estilo(fig: go.Figure, titulo: str) -> go.Figure:
    # separators=",." faz o plotly escrever eixo e tooltip com vírgula decimal
    # e ponto de milhar, no mesmo padrão de P4.
    fig.update_traces(marker_color=COR, line_color=COR, selector={"type": "scatter"})
    fig.update_traces(marker_color=COR, selector={"type": "bar"})
    fig.update_layout(
        title=titulo,
        separators=",.",
        height=ALTURA,
        margin={"l": 10, "r": 10, "t": 50, "b": 10},
        showlegend=False,
    )
    return fig


def _barras_horizontais(df, x, y, titulo, eixo_x, eixo_y, hover):
    # Barras horizontais com a primeira linha do DataFrame em cima: o plotly
    # desenha a primeira categoria embaixo, então o eixo é invertido.
    fig = px.bar(df, x=x, y=y, orientation="h")
    fig.update_traces(hovertemplate=hover)
    fig.update_yaxes(title=eixo_y, autorange="reversed")
    fig.update_xaxes(title=eixo_x)
    return _estilo(fig, titulo)


def faturamento_mensal(df: pd.DataFrame) -> go.Figure:
    fig = px.line(df.sort_values("mes"), x="mes", y="receita", markers=True)
    fig.update_traces(hovertemplate="%{x|%m/%Y}<br>R$ %{y:,.2f}<extra></extra>")
    fig.update_xaxes(title="Mês da compra", tickformat="%m/%Y")
    fig.update_yaxes(title="Receita (R$)", tickprefix="R$ ")
    return _estilo(fig, "01 · Faturamento mensal")


def receita_por_categoria(df: pd.DataFrame) -> go.Figure:
    top = df.sort_values("receita", ascending=False).head(10)
    return _barras_horizontais(
        top, "receita", "categoria", "02 · Receita por categoria (top 10)",
        "Receita (R$)", "Categoria", "%{y}<br>R$ %{x:,.2f}<extra></extra>",
    )


def mix_pagamento(df: pd.DataFrame) -> go.Figure:
    fig = px.bar(df.sort_values("pct_valor", ascending=False), x="tipo", y="pct_valor")
    fig.update_traces(hovertemplate="%{x}<br>%{y:,.1f}% do valor<extra></extra>")
    fig.update_xaxes(title="Tipo de pagamento")
    fig.update_yaxes(title="% do valor pago", ticksuffix="%")
    return _estilo(fig, "07 · Mix de pagamento")


def ticket_medio_por_uf(df: pd.DataFrame) -> go.Figure:
    return _barras_horizontais(
        df.sort_values("ticket_medio", ascending=False),
        "ticket_medio", "uf", "06 · Ticket médio por UF",
        "Ticket médio (R$)", "UF do cliente", "%{y}<br>R$ %{x:,.2f}<extra></extra>",
    )


def clientes_por_uf(df: pd.DataFrame) -> go.Figure:
    return _barras_horizontais(
        df.sort_values("clientes", ascending=False),
        "clientes", "uf", "12 · Clientes por UF",
        "Clientes (pessoas)", "UF do cliente", "%{y}<br>%{x:,.0f} clientes<extra></extra>",
    )


def nota_por_categoria(df: pd.DataFrame) -> go.Figure:
    piores = df.sort_values("posicao_pior").head(10)
    fig = px.scatter(piores, x="nota_media", y="categoria")
    fig.update_traces(
        marker_size=12, hovertemplate="%{y}<br>nota %{x:,.2f}<extra></extra>"
    )
    fig.update_xaxes(title="Nota média (1 a 5)")
    fig.update_yaxes(title="Categoria", autorange="reversed")
    return _estilo(fig, "04 · Nota por categoria (10 piores)")


def concentracao_vendedores(df: pd.DataFrame) -> go.Figure:
    fig = px.line(df.sort_values("posicao"), x="posicao", y="pct_acumulado")
    fig.update_traces(
        hovertemplate="%{x:,.0f} vendedores<br>%{y:,.2f}% da receita<extra></extra>"
    )
    fig.add_hline(y=80, line_dash="dash", line_color="gray")
    fig.update_xaxes(title="Vendedores (posição por receita)")
    fig.update_yaxes(title="% acumulado da receita", ticksuffix="%")
    return _estilo(fig, "09 · Concentração de vendedores")
