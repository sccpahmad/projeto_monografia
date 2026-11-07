"""
Padronização (z-score) e construção do Índice Composto de Risco (ICR).

ICR_i = sum_j ( peso_j * sinal_j * z_ij )

onde z_ij é o indicador j da instituição i padronizado DENTRO do trimestre,
e sinal_j orienta todos os indicadores na direção "solidez" (quanto maior,
mais sólido). A zona de risco é o percentil inferior do ICR.
"""
from __future__ import annotations

import numpy as np
import pandas as pd


def _winsorizar(s: pd.Series, limites) -> pd.Series:
    lo, hi = s.quantile(limites[0]), s.quantile(limites[1])
    return s.clip(lower=lo, upper=hi)


def _padronizar_grupo(s: pd.Series, metodo: str) -> pd.Series:
    if metodo == "robusto":
        med = s.median()
        iqr = s.quantile(0.75) - s.quantile(0.25)
        escala = iqr / 1.349 if iqr and not np.isnan(iqr) else np.nan
        return (s - med) / escala if escala else s * 0.0
    # zscore padrão
    mu, sd = s.mean(), s.std(ddof=0)
    return (s - mu) / sd if sd else s * 0.0


def padronizar(
    df_ind: pd.DataFrame,
    indicadores: dict,
    cfg_padr: dict,
) -> pd.DataFrame:
    """Adiciona colunas z_<indicador> padronizadas por trimestre."""
    df = df_ind.copy()
    metodo = cfg_padr.get("metodo", "zscore")
    winsor = cfg_padr.get("winsorizar", True)
    limites = cfg_padr.get("winsor_limites", [0.01, 0.99])
    por = cfg_padr.get("por", "AnoMes")

    for nome in indicadores:
        if nome not in df.columns:
            continue
        col = df[nome]
        if winsor:
            col = df.groupby(por)[nome].transform(lambda s: _winsorizar(s, limites))
        df[f"z_{nome}"] = col.groupby(df[por]).transform(
            lambda s: _padronizar_grupo(s, metodo)
        )
    return df


def calcular_icr(
    df_padr: pd.DataFrame,
    indicadores: dict,
    orientacao: str = "solidez",
) -> pd.DataFrame:
    """Calcula o ICR e a contribuição de cada indicador (decomposição exata)."""
    df = df_padr.copy()

    # Renormaliza pesos para somar 1 (considerando só indicadores presentes).
    presentes = {n: m for n, m in indicadores.items() if f"z_{n}" in df.columns}
    soma_pesos = sum(m["peso"] for m in presentes.values()) or 1.0

    icr = pd.Series(0.0, index=df.index)
    for nome, meta in presentes.items():
        peso = meta["peso"] / soma_pesos
        sinal = meta.get("sinal", 1)
        contrib = peso * sinal * df[f"z_{nome}"].fillna(0)
        df[f"contrib_{nome}"] = contrib
        icr = icr + contrib

    if orientacao == "risco":
        icr = -icr
        for nome in presentes:
            df[f"contrib_{nome}"] = -df[f"contrib_{nome}"]

    df["ICR"] = icr
    # Percentil dentro do trimestre (0 = pior, 1 = melhor em 'solidez').
    df["ICR_percentil"] = df.groupby("AnoMes")["ICR"].rank(pct=True)
    return df


def classificar_risco(
    df_icr: pd.DataFrame,
    percentil: float = 0.10,
    orientacao: str = "solidez",
) -> pd.DataFrame:
    """Marca a 'zona de risco' (piores instituições) por trimestre."""
    df = df_icr.copy()
    if orientacao == "solidez":
        df["zona_risco"] = df["ICR_percentil"] <= percentil
    else:
        df["zona_risco"] = df["ICR_percentil"] >= (1 - percentil)

    # Faixa qualitativa por quartis do ICR (apenas para leitura humana).
    # Sob 'solidez', ICR maior = mais sólido; sob 'risco', o ICR já vem negado
    # (maior = mais arriscado), então os rótulos são invertidos para manter a
    # coerência com zona_risco (o quartil superior recebe 'Crítico').
    faixas = ["Crítico", "Atenção", "Adequado", "Sólido"]
    if orientacao != "solidez":
        faixas = faixas[::-1]
    df["faixa"] = df.groupby("AnoMes")["ICR"].transform(
        lambda s: pd.qcut(s.rank(method="first"), 4, labels=faixas)
    )
    return df
