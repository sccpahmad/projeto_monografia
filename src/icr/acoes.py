"""
Validação com ações da B3 (4ª camada prevista na proposta).

Cotações via API pública do Yahoo Finance (sem chave):
  https://query1.finance.yahoo.com/v8/finance/chart/{ticker}.SA?range=10y&interval=3mo

Hipótese: bancos com ICR mais alto (mais sólidos) tendem a entregar melhor
desempenho/valuation. Cruzamos a série trimestral do ICR de cada banco listado
(painel sistêmico) com o preço e o retorno da ação.
"""
from __future__ import annotations

import pandas as pd

from .http import criar_sessao, get_json

CHART = "https://query1.finance.yahoo.com/v8/finance/chart/{tk}?range={rng}&interval={itv}"
# Yahoo exige um User-Agent de navegador.
UA = {"User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64)"}


def baixar_cotacoes(
    tickers: dict[str, str],
    sufixo: str = ".SA",
    rng: str = "10y",
    intervalo: str = "3mo",
    sessao=None,
) -> pd.DataFrame:
    """Baixa cotações. tickers = {ticker_B3: CodInst}. Saída longa."""
    sessao = sessao or criar_sessao()
    partes = []
    for ticker, codinst in tickers.items():
        url = CHART.format(tk=ticker + sufixo, rng=rng, itv=intervalo)
        try:
            j = get_json_headers(sessao, url)
            res = j["chart"]["result"][0]
            ts = res["timestamp"]
            close = res["indicators"]["quote"][0]["close"]
        except Exception as exc:  # noqa: BLE001
            print(f"  {ticker}: ERRO ({exc})")
            continue
        df = pd.DataFrame({"data": pd.to_datetime(ts, unit="s"), "close": close})
        df = df.dropna(subset=["close"])
        df["ticker"] = ticker
        df["CodInst"] = str(codinst).zfill(8)
        partes.append(df)
        print(f"  {ticker} ({codinst}): {len(df)} cotações")
    return pd.concat(partes, ignore_index=True) if partes else pd.DataFrame()


def get_json_headers(sessao, url):
    resp = sessao.get(url, timeout=60, headers=UA)
    resp.raise_for_status()
    return resp.json()


def trimestralizar(cotacoes: pd.DataFrame) -> pd.DataFrame:
    """Preço de fechamento por trimestre + retorno trimestral. AnoMes alinhado."""
    if cotacoes.empty:
        return pd.DataFrame()
    df = cotacoes.copy()
    df["trimestre"] = df["data"].dt.to_period("Q")
    g = (
        df.sort_values("data")
        .groupby(["CodInst", "ticker", "trimestre"])["close"]
        .last()
        .reset_index()
    )
    g["AnoMes"] = g["trimestre"].map(lambda p: p.year * 100 + p.month)
    g["retorno"] = g.groupby("ticker")["close"].pct_change() * 100
    return g.drop(columns="trimestre")


def correlacionar(df_icr: pd.DataFrame, acoes_trim: pd.DataFrame) -> pd.DataFrame:
    """Correlaciona, por banco, o ICR com o preço e com o retorno da ação."""
    if acoes_trim.empty:
        return pd.DataFrame()
    icr = df_icr[["AnoMes", "CodInst", "ICR"]].copy()
    icr["dICR"] = icr.sort_values("AnoMes").groupby("CodInst")["ICR"].diff()
    base = acoes_trim.merge(icr, on=["AnoMes", "CodInst"], how="inner")
    linhas = []
    for ticker, g in base.groupby("ticker"):
        g = g.dropna(subset=["ICR", "close"])
        if len(g) >= 5:
            linhas.append({
                "ticker": ticker,
                "n": len(g),
                "corr_ICR_preco": g["ICR"].corr(g["close"]),
                "corr_dICR_retorno": g.dropna(subset=["dICR", "retorno"])["dICR"].corr(
                    g.dropna(subset=["dICR", "retorno"])["retorno"]),
            })
    return pd.DataFrame(linhas)
