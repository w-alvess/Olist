"""Relatório HTML estático do painel Olist. A spec do painel está em painel.py.

Execução:
    uv run python relatorio.py

R1. MESMAS FUNÇÕES
    Lê os marts com painel.ler(), formata com painel.reais/pct/numero e monta
    os gráficos com as funções de painel.py. Não importa streamlit e não
    desenha gráfico que não esteja em painel.py.
    Por quê: o número e o gráfico do relatório têm que ser os do app.py.

R2. UM ARQUIVO
    Escreve relatorio.html na raiz, com as quatro faixas do app.py na mesma
    ordem e os cartões em HTML simples, numa grade. Cada gráfico sai de
    figura.to_html(full_html=False): o primeiro com include_plotlyjs="cdn",
    os outros com include_plotlyjs=False, e todos com div_id fixo ("g01",
    "g02"...).
    Por quê: sem div_id fixo o plotly sorteia um id novo a cada execução, e
    o arquivo muda sem o dado mudar.

R3. SEM FILTRO
    O faturamento mostra o período padrão do app.py (jan/2017 a ago/2018), e
    o título diz o período.

R4. RODAPÉ
    "Dados de 25/10/2026 14:03": data e hora em que o arquivo foi gerado.
    Por quê: o arquivo não fala com o banco; quem lê precisa saber de quando
    é o número.

R5. SAÍDA NA TELA
    Caminho do arquivo e tamanho em KB, stdout em utf-8.
"""

import sys
from datetime import datetime
from html import escape
from pathlib import Path

import painel

ARQUIVO = Path(__file__).resolve().parent / "relatorio.html"

_CSS = """
:root { --texto: #1f2933; --suave: #616e7c; --borda: #d9dee3; --fundo: #ffffff; }
* { box-sizing: border-box; }
body { margin: 0; padding: 24px 16px; font-family: system-ui, sans-serif;
       color: var(--texto); background: var(--fundo); }
main { max-width: 1600px; margin: 0 auto; }
h1 { margin: 0 0 20px; font-size: 1.8rem; }
.grade { display: grid; gap: 16px; margin-bottom: 16px; }
.cartoes { grid-template-columns: repeat(7, minmax(0, 1fr)); }
.tres { grid-template-columns: repeat(3, minmax(0, 1fr)); }
.cartao { border: 1px solid var(--borda); border-radius: 8px; padding: 12px; }
.cartao .rotulo { font-size: 0.85rem; color: var(--suave); }
.cartao .valor { font-size: 1.6rem; margin-top: 6px; }
footer { margin-top: 24px; font-size: 0.85rem; color: var(--suave); }
@media (max-width: 1100px) {
  .cartoes { grid-template-columns: repeat(2, minmax(0, 1fr)); }
  .tres { grid-template-columns: minmax(0, 1fr); }
}
"""


def _cartoes(dados) -> str:
    itens = "".join(
        f'<div class="cartao"><div class="rotulo">{escape(rotulo)}</div>'
        f'<div class="valor">{escape(valor)}</div></div>'
        for rotulo, valor in painel.cartoes(dados)
    )
    return f'<section class="grade cartoes">{itens}</section>'


def _graficos(figuras) -> list[str]:
    # A biblioteca do plotly entra uma vez, no primeiro gráfico; os outros
    # usam a mesma que já foi carregada.
    return [
        figura.to_html(
            full_html=False,
            include_plotlyjs="cdn" if i == 1 else False,
            div_id=f"g{i:02d}",
        )
        for i, figura in enumerate(figuras, start=1)
    ]


def montar(dados, gerado_em: datetime) -> str:
    vendas = dados["vendas_mensais"].sort_values("mes")
    recorte = vendas[
        (vendas["mes"] >= painel.INICIO_PADRAO) & (vendas["mes"] <= painel.FIM_PADRAO)
    ]
    faturamento = painel.faturamento_mensal(recorte)
    faturamento.update_layout(
        title=f"01 · Faturamento mensal · {painel.mes(painel.INICIO_PADRAO)} "
        f"a {painel.mes(painel.FIM_PADRAO)}"
    )

    g = _graficos([
        faturamento,
        painel.receita_por_categoria(dados["top_categorias"]),
        painel.mix_pagamento(dados["mix_pagamento"]),
        painel.ticket_medio_por_uf(dados["ticket_medio_por_estado"]),
        painel.clientes_por_uf(dados["clientes_por_uf"]),
        painel.nota_por_categoria(dados["nota_por_categoria"]),
        painel.concentracao_vendedores(dados["vendedores_pareto"]),
    ])

    return f"""<!doctype html>
<html lang="pt-BR">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>Olist · visão da operação</title>
<style>{_CSS}</style>
</head>
<body>
<main>
<h1>Olist · visão da operação</h1>
{_cartoes(dados)}
<section>{g[0]}</section>
<section class="grade tres">{g[1]}{g[2]}{g[3]}</section>
<section class="grade tres">{g[4]}{g[5]}{g[6]}</section>
<footer>Dados de {gerado_em:%d/%m/%Y %H:%M}</footer>
</main>
</body>
</html>
"""


def main() -> None:
    sys.stdout.reconfigure(encoding="utf-8")
    try:
        dados = painel.ler(painel.MARTS)
    except painel.MartsFaltando as e:
        print("Não encontrado: " + ", ".join(e.nomes))
        print("Rode antes: uv run python -m pipeline.marts")
        sys.exit(1)

    ARQUIVO.write_text(montar(dados, datetime.now()), encoding="utf-8")
    kb = ARQUIVO.stat().st_size / 1024
    print(f"{ARQUIVO}  {painel.numero(kb, 1)} KB")


if __name__ == "__main__":
    main()
