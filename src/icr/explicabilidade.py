"""
Explicabilidade do ICR.

Dois níveis, do mais honesto ao mais "vitrine de ML":

1. Decomposição exata (recomendada): como o ICR é linear nos indicadores,
   a contribuição de cada indicador é exatamente peso_j * sinal_j * z_ij.
   Isso já responde "o que mais pesou no score de cada banco" — sem caixa preta.

2. SHAP sobre um modelo de árvore que prevê a 'zona de risco': serve para
   demonstrar a técnica (feature importance / SHAP) exigida no TCC. Como o
   alvo é derivado do próprio ICR, há circularidade — o ganho real aparece
   quando o alvo for um evento EXTERNO (ex.: distress futuro). Documentado.
"""
from __future__ import annotations

import numpy as np
import pandas as pd


def importancia_por_contribuicao(df_icr: pd.DataFrame, indicadores: dict) -> pd.DataFrame:
    """Importância média = média do |contribuição| de cada indicador."""
    linhas = []
    for nome in indicadores:
        col = f"contrib_{nome}"
        if col in df_icr.columns:
            linhas.append(
                {
                    "indicador": nome,
                    "contrib_abs_media": df_icr[col].abs().mean(),
                    "contrib_media": df_icr[col].mean(),
                }
            )
    out = pd.DataFrame(linhas).sort_values("contrib_abs_media", ascending=False)
    total = out["contrib_abs_media"].sum() or 1.0
    out["importancia_pct"] = 100 * out["contrib_abs_media"] / total
    return out.reset_index(drop=True)


def shap_zona_risco(df_icr: pd.DataFrame, indicadores: dict):
    """Treina GradientBoosting para prever a zona de risco e calcula SHAP.

    Retorna (modelo, df_shap_resumo) ou (None, None) se shap/sklearn ausentes.
    """
    try:
        import shap
        from sklearn.ensemble import GradientBoostingClassifier
    except Exception as exc:  # noqa: BLE001
        print(f"  [aviso] SHAP/sklearn indisponível: {exc}")
        return None, None

    # Só usa indicadores que existem E têm dados (evita zerar a amostra quando
    # um indicador, p.ex. Basileia, está ausente no universo escolhido).
    feats = [n for n in indicadores if n in df_icr.columns and df_icr[n].notna().any()]
    dados = df_icr.dropna(subset=feats + ["zona_risco"])
    X = dados[feats].to_numpy()
    y = dados["zona_risco"].astype(int).to_numpy()
    if y.sum() < 5 or len(np.unique(y)) < 2:
        print("  [aviso] amostra insuficiente para SHAP.")
        return None, None

    modelo = GradientBoostingClassifier(random_state=42)
    modelo.fit(X, y)

    explainer = shap.TreeExplainer(modelo)
    valores = explainer.shap_values(X)
    if isinstance(valores, list):  # versões antigas devolvem lista por classe
        valores = valores[1]

    resumo = (
        pd.DataFrame({"indicador": feats, "shap_abs_medio": np.abs(valores).mean(0)})
        .sort_values("shap_abs_medio", ascending=False)
        .reset_index(drop=True)
    )
    return modelo, resumo
