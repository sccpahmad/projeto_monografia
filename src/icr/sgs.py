"""
Cliente do SGS — Sistema Gerenciador de Séries Temporais do Banco Central.

API pública e estável:
  https://api.bcb.gov.br/dados/serie/bcdata.sgs.{codigo}/dados?formato=json
        &dataInicial=DD/MM/AAAA&dataFinal=DD/MM/AAAA

Usada na validação macroeconômica do ICR (inadimplência, spread, Selic, etc.).
"""
from __future__ import annotations

import pandas as pd

from .http import criar_sessao, get_json

BASE = "https://api.bcb.gov.br/dados/serie/bcdata.sgs.{codigo}/dados"


def baixar_serie(
    codigo: int,
    data_inicial: str | None = None,
    data_final: str | None = None,
    sessao=None,
) -> pd.DataFrame:
    """Baixa uma série do SGS. Retorna DataFrame [data, valor]."""
    sessao = sessao or criar_sessao()
    url = BASE.format(codigo=codigo) + "?formato=json"
    if data_inicial:
        url += f"&dataInicial={data_inicial}"
    if data_final:
        url += f"&dataFinal={data_final}"
    dados = get_json(sessao, url)
    df = pd.DataFrame(dados)
    if df.empty:
        return pd.DataFrame(columns=["data", "valor"])
    df["data"] = pd.to_datetime(df["data"], format="%d/%m/%Y")
    df["valor"] = pd.to_numeric(df["valor"], errors="coerce")
    return df.sort_values("data").reset_index(drop=True)


def baixar_varias(
    series: dict[str, int],
    data_inicial: str | None = None,
    data_final: str | None = None,
    sessao=None,
) -> pd.DataFrame:
    """Baixa um conjunto de séries e retorna formato longo.

    series: {nome_legivel: codigo_sgs}
    Saída: colunas [data, serie, valor].
    """
    sessao = sessao or criar_sessao()
    partes = []
    for nome, codigo in series.items():
        try:
            df = baixar_serie(codigo, data_inicial, data_final, sessao=sessao)
        except Exception as exc:  # noqa: BLE001 — uma série ruim não derruba o resto
            print(f"  SGS {codigo:>6} ({nome}): ERRO ({exc}); pulando.")
            continue
        partes.append(df.assign(serie=nome, codigo=codigo))
        print(f"  SGS {codigo:>6} ({nome}): {len(df)} observações")
    return pd.concat(partes, ignore_index=True) if partes else pd.DataFrame()


def trimestralizar(df_longo: pd.DataFrame, como: str = "last") -> pd.DataFrame:
    """Converte séries (mensais/diárias) para frequência trimestral.

    Retorna formato largo indexado por trimestre (AnoMes de fim de trimestre),
    para casar com a periodicidade do IF.Data.
    """
    if df_longo.empty:
        return pd.DataFrame()
    df = df_longo.copy()
    df["trimestre"] = df["data"].dt.to_period("Q")
    agg = {"last": "last", "mean": "mean"}[como]
    largo = (
        df.sort_values("data")
        .groupby(["trimestre", "serie"])["valor"]
        .agg(agg)
        .unstack("serie")
    )
    # AnoMes no formato do IF.Data (fim de trimestre: 03,06,09,12)
    largo.index = largo.index.map(
        lambda p: p.year * 100 + p.month  # p.month já é 3,6,9,12
    )
    largo.index.name = "AnoMes"
    return largo.reset_index()
