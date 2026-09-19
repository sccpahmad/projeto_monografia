"""
Validação do ICR em três dimensões (conforme a metodologia do TCC):

1. Entre instituições  -> ranking por trimestre (gerado nos scripts).
2. Temporal            -> evolução do ICR médio do sistema.
3. Macroeconômica      -> correlação do ICR médio com séries do SGS
                          (inadimplência, spread, etc.).
"""
from __future__ import annotations

import pandas as pd


def serie_sistema(df_icr: pd.DataFrame, ponderar_por_ativo: bool = True) -> pd.DataFrame:
    """ICR agregado do sistema por trimestre (média simples e ponderada)."""
    def agg(g: pd.DataFrame) -> pd.Series:
        media = g["ICR"].mean()
        if ponderar_por_ativo and g["ativo_total_mil"].sum() > 0:
            w = g["ativo_total_mil"].fillna(0)
            media_pond = (g["ICR"] * w).sum() / w.sum()
        else:
            media_pond = media
        return pd.Series(
            {
                "ICR_medio": media,  # ~0 por construção (escore-z); não plotar
                "ICR_mediana": g["ICR"].median(),
                "ICR_medio_ponderado": media_pond,
                "n_instituicoes": len(g),
                "pct_zona_risco": g.get("zona_risco", pd.Series(dtype=bool)).mean(),
            }
        )

    return df_icr.groupby("AnoMes").apply(agg, include_groups=False).reset_index()


def correlacao_macro(
    serie_sis: pd.DataFrame,
    macro_trim: pd.DataFrame,
    coluna_icr: str = "ICR_medio_ponderado",
) -> pd.DataFrame:
    """Correlaciona o ICR do sistema com as séries macro (mesmo trimestre).

    Espera-se correlação NEGATIVA com inadimplência/spread: sistema mais
    sólido (ICR maior) tende a conviver com menor inadimplência.
    """
    base = serie_sis.merge(macro_trim, on="AnoMes", how="inner")
    macro_cols = [c for c in macro_trim.columns if c != "AnoMes"]
    linhas = []
    for c in macro_cols:
        sub = base[[coluna_icr, c]].dropna()
        if len(sub) >= 3:
            pear = sub[coluna_icr].corr(sub[c], method="pearson")
            spear = sub[coluna_icr].corr(sub[c], method="spearman")
            linhas.append(
                {"serie_macro": c, "pearson": pear, "spearman": spear, "n": len(sub)}
            )
    return pd.DataFrame(linhas).sort_values("pearson")
