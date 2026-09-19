"""
Exportação do ranking de risco: HTML interativo (ordenável) e Excel formatado.

- O HTML é autocontido (ordena ao clicar no cabeçalho; cores por faixa) e não
  depende de nada além do navegador.
- O Excel usa openpyxl (no requirements.txt); se ausente, avisa e segue.
"""
from __future__ import annotations

from pathlib import Path

import pandas as pd

CORES_FAIXA = {
    "Sólido": "#1a9850",
    "Adequado": "#91cf60",
    "Atenção": "#fee08b",
    "Crítico": "#d73027",
}
COLUNAS = [
    "posicao", "nome", "ICR", "faixa", "basileia", "alavancagem", "roa", "roe",
    "imobilizacao", "liquidez", "eficiencia", "ativo_total_mil",
]
ROTULOS = {
    "posicao": "#", "nome": "Instituição", "ICR": "ICR", "faixa": "Faixa",
    "basileia": "Basileia %", "alavancagem": "Alavanc.", "roa": "ROA %",
    "roe": "ROE %", "imobilizacao": "Imob. %", "liquidez": "Liquidez %",
    "eficiencia": "Efic. %", "ativo_total_mil": "Ativo (R$ mil)",
}


def preparar_ranking(df_icr: pd.DataFrame, anomes: int) -> pd.DataFrame:
    rank = df_icr[df_icr["AnoMes"] == anomes].sort_values("ICR", ascending=False).copy()
    rank.insert(0, "posicao", range(1, len(rank) + 1))
    cols = [c for c in COLUNAS if c in rank.columns]
    return rank[cols].reset_index(drop=True)


def _fmt(df: pd.DataFrame) -> pd.DataFrame:
    df = df.copy()
    for c in df.columns:
        if c in ("ICR", "basileia", "alavancagem", "roa", "roe", "imobilizacao",
                 "liquidez", "eficiencia"):
            df[c] = pd.to_numeric(df[c], errors="coerce").round(2)
        if c == "ativo_total_mil":
            df[c] = pd.to_numeric(df[c], errors="coerce").round(0)
    return df


def exportar_html(rankings: dict[str, pd.DataFrame], caminho: Path, anomes: int) -> None:
    """rankings = {nome_painel: df_ranking}. Gera um HTML com abas por painel."""
    secoes = []
    for painel, df in rankings.items():
        secoes.append(_tabela_html(_fmt(df), painel))
    html = _SHELL.replace("{{TITULO}}", f"Ranking ICR — {anomes}").replace(
        "{{SECOES}}", "\n".join(secoes)
    )
    caminho.write_text(html, encoding="utf-8")


def _tabela_html(df: pd.DataFrame, painel: str) -> str:
    cab = "".join(f"<th onclick='sortT(this)'>{ROTULOS.get(c, c)}</th>" for c in df.columns)
    linhas = []
    for _, r in df.iterrows():
        cor = CORES_FAIXA.get(str(r.get("faixa", "")), "#ffffff")
        tds = []
        for c in df.columns:
            v = r[c]
            estilo = f"background:{cor}" if c == "faixa" else ""
            tds.append(f"<td style='{estilo}'>{'' if pd.isna(v) else v}</td>")
        linhas.append("<tr>" + "".join(tds) + "</tr>")
    return (f"<h2>Painel: {painel}</h2><table><thead><tr>{cab}</tr></thead>"
            f"<tbody>{''.join(linhas)}</tbody></table>")


def exportar_excel(rankings: dict[str, pd.DataFrame], caminho: Path) -> bool:
    """Excel com uma aba por painel, cabeçalho fixo, autofiltro e cores por faixa."""
    try:
        from openpyxl.styles import Font, PatternFill
        from openpyxl.utils import get_column_letter
    except Exception:  # noqa: BLE001
        print("  [aviso] openpyxl ausente; pulei o Excel. Instale com: pip install openpyxl")
        return False

    with pd.ExcelWriter(caminho, engine="openpyxl") as xl:
        for painel, df in rankings.items():
            d = _fmt(df).rename(columns=ROTULOS)
            aba = painel[:31]
            d.to_excel(xl, sheet_name=aba, index=False)
            ws = xl.sheets[aba]
            ws.freeze_panes = "A2"
            ws.auto_filter.ref = ws.dimensions
            for cell in ws[1]:
                cell.font = Font(bold=True, color="FFFFFF")
                cell.fill = PatternFill("solid", fgColor="404040")
            # cor por faixa
            faixa_col = None
            for j, cell in enumerate(ws[1], start=1):
                if cell.value == ROTULOS["faixa"]:
                    faixa_col = j
            if faixa_col:
                for i in range(2, ws.max_row + 1):
                    v = ws.cell(i, faixa_col).value
                    cor = CORES_FAIXA.get(str(v), "#FFFFFF").lstrip("#")
                    ws.cell(i, faixa_col).fill = PatternFill("solid", fgColor=cor)
            for j, col in enumerate(d.columns, start=1):
                ws.column_dimensions[get_column_letter(j)].width = max(10, min(40, len(str(col)) + 6))
    return True


_SHELL = """<!doctype html><html lang='pt-br'><head><meta charset='utf-8'>
<title>{{TITULO}}</title>
<style>
 body{font-family:Segoe UI,Arial,sans-serif;margin:24px;color:#222}
 h1{font-size:20px} h2{font-size:16px;margin-top:28px}
 table{border-collapse:collapse;width:100%;font-size:13px;box-shadow:0 1px 4px #0002}
 th,td{border:1px solid #ddd;padding:6px 8px;text-align:right}
 td:nth-child(2){text-align:left} th{background:#404040;color:#fff;cursor:pointer;position:sticky;top:0}
 tr:nth-child(even){background:#f7f7f7}
 .nota{color:#666;font-size:12px;margin:8px 0 20px}
</style></head><body>
<h1>{{TITULO}}</h1>
<p class='nota'>Clique no cabeçalho para ordenar. Cores na coluna Faixa:
verde = sólido, vermelho = crítico. ICR maior = mais sólido.</p>
{{SECOES}}
<script>
function sortT(th){
 var t=th.closest('table'),tb=t.tBodies[0],i=[...th.parentNode.children].indexOf(th);
 var asc=th.dataset.asc=th.dataset.asc==='1'?'0':'1';
 [...tb.rows].sort(function(a,b){
   var x=a.cells[i].innerText,y=b.cells[i].innerText;
   var nx=parseFloat(x.replace(',','.')),ny=parseFloat(y.replace(',','.'));
   if(!isNaN(nx)&&!isNaN(ny)){x=nx;y=ny}
   return (x>y?1:x<y?-1:0)*(asc==='1'?1:-1);
 }).forEach(function(r){tb.appendChild(r)});
}
</script></body></html>"""
