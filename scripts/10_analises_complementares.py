"""
ETAPA 10 — Análises complementares solicitadas na revisão da monografia.

Reproduz os números acrescentados ao texto na versão revisada:
  (a) Tabela 10 — comparação entre classificadores (regressão logística, floresta
      aleatória e gradient boosting) com o MESMO split temporal e embargo do EWS;
  (b) Seção 4.7 — precisão/revocação/F1 no limiar de Youden escolhido no TESTE
      (como no script 06) e no limiar escolhido numa VALIDAÇÃO TEMPORAL INTERNA ao
      treino (sem usar o teste);
  (c) Seção 5.5 — EWS do regime IFRS 9 avaliado fora do tempo: treino nos três
      primeiros pares de trimestres (t -> t+1) e teste no último par.

Pré-requisitos: scripts 01, 02, 06 e 09 já executados.
Saídas: data/processed/comparacao_classificadores.csv
        data/processed/distress_limiar_youden.csv
        data/processed/ews2025_oot.csv

Uso:
  python scripts/10_analises_complementares.py
"""
from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

import numpy as np  # noqa: E402
import pandas as pd  # noqa: E402
from sklearn.ensemble import GradientBoostingClassifier, RandomForestClassifier  # noqa: E402
from sklearn.linear_model import LogisticRegression  # noqa: E402
from sklearn.metrics import (average_precision_score, brier_score_loss,  # noqa: E402
                             precision_recall_fscore_support, roc_auc_score, roc_curve)
from sklearn.pipeline import make_pipeline  # noqa: E402
from sklearn.preprocessing import StandardScaler  # noqa: E402

from icr import distress  # noqa: E402
from icr.config import DIR_PROCESSED, carregar_config, dir_processed_painel  # noqa: E402


def _ks(y, p) -> float:
    f, t, _ = roc_curve(y, p)
    return float((t - f).max())


def _youden(y, p) -> float:
    f, t, thr = roc_curve(y, p)
    return float(thr[(t - f).argmax()])


def _rotulo(q: int) -> str:
    return f"{q // 4}T{q % 4 + 1}"


def main() -> None:
    cfg = carregar_config()
    dd = cfg.get("distress", {})
    h = dd.get("horizonte", 4)

    # ---------------- (a) comparação de classificadores -----------------------
    df = pd.read_parquet(dir_processed_painel("prudencial") / "indicadores.parquet")
    d = distress.marcar_distress(df, dd.get("basileia_min", 10.5), dd.get("roe_min", -30.0), h)
    feats = [f for f in distress.FEATURES_PADRAO if f in d.columns and d[f].notna().any()]
    base = d[d["horizonte_observavel"]].dropna(subset=feats + ["alvo"])
    qs = np.sort(base["qidx"].unique())
    corte = qs[min(int(len(qs) * 0.7), len(qs) - 1)]
    tr, te = distress.split_temporal(base, corte, embargo=h)
    print(f"Treino {_rotulo(tr.qidx.min())}–{_rotulo(tr.qidx.max())} (n={len(tr)}) | "
          f"embargo {_rotulo(corte - h + 1)}–{_rotulo(corte)} | "
          f"teste {_rotulo(te.qidx.min())}–{_rotulo(te.qidx.max())} (n={len(te)})")
    Xtr, ytr, Xte, yte = tr[feats].to_numpy(), tr["alvo"].to_numpy(), te[feats].to_numpy(), te["alvo"].to_numpy()

    modelos = {
        "Regressão logística": make_pipeline(StandardScaler(), LogisticRegression(max_iter=2000)),
        "Floresta aleatória": RandomForestClassifier(n_estimators=500, min_samples_leaf=20,
                                                     random_state=42, n_jobs=-1),
        "Gradient boosting (adotado)": GradientBoostingClassifier(random_state=42),
    }
    linhas, p_gb = [], None
    for nome, m in modelos.items():
        p = m.fit(Xtr, ytr).predict_proba(Xte)[:, 1]
        if nome.startswith("Gradient"):
            p_gb = p
        linhas.append({"modelo": nome, "auc_roc": roc_auc_score(yte, p),
                       "auc_pr": average_precision_score(yte, p), "ks": _ks(yte, p),
                       "brier": brier_score_loss(yte, p)})
    comp = pd.DataFrame(linhas).round(3)
    comp.to_csv(DIR_PROCESSED / "comparacao_classificadores.csv", index=False, encoding="utf-8-sig")
    print("\n== Tabela 10: comparação entre classificadores ==")
    print(comp.to_string(index=False))

    # ---------------- (b) limiar de Youden: teste vs. validação interna -------
    qtr = np.sort(tr["qidx"].unique())
    corte_v = qtr[int(len(qtr) * 0.8)]
    tr_in, val = distress.split_temporal(tr, corte_v, embargo=h)
    g_val = GradientBoostingClassifier(random_state=42).fit(tr_in[feats].to_numpy(), tr_in["alvo"].to_numpy())
    lim_val = _youden(val["alvo"].to_numpy(), g_val.predict_proba(val[feats].to_numpy())[:, 1])
    lim_te = _youden(yte, p_gb)
    lim = []
    for origem, thr in [("teste (script 06)", lim_te), ("validação interna ao treino", lim_val)]:
        pr, rc, f1, _ = precision_recall_fscore_support(yte, (p_gb >= thr).astype(int),
                                                        average="binary", zero_division=0)
        lim.append({"limiar_escolhido_em": origem, "limiar": thr, "precisao": pr,
                    "revocacao": rc, "f1": f1})
    lim = pd.DataFrame(lim).round(3)
    lim.to_csv(DIR_PROCESSED / "distress_limiar_youden.csv", index=False, encoding="utf-8-sig")
    print(f"\n== Limiar de Youden (validação: ajuste {_rotulo(tr_in.qidx.min())}–{_rotulo(tr_in.qidx.max())}, "
          f"validação {_rotulo(val.qidx.min())}–{_rotulo(val.qidx.max())}) ==")
    print(lim.to_string(index=False))

    # ---------------- (c) EWS 2025–2026 fora do tempo ---------------------------
    caminho = DIR_PROCESSED / "icr2_ifrs9.parquet"
    if not caminho.exists():
        print("\n[aviso] icr2_ifrs9.parquet ausente (rode o script 09); etapa (c) pulada.")
        return
    i2 = pd.read_parquet(caminho)
    i2["CodInst"] = i2["CodInst"].astype(str)
    fe = ["basileia", "alavancagem", "roa", "roe", "imobilizacao", "liquidez", "eficiencia", "custo_risco"]
    pers = sorted(int(p) for p in i2["AnoMes"].unique())
    pares = []
    for t, t1 in zip(pers[:-1], pers[1:]):
        a = i2[i2["AnoMes"] == t][["CodInst", "ICR"] + fe]
        b = i2[i2["AnoMes"] == t1][["CodInst", "basileia", "roe"]].rename(columns={"basileia": "b1", "roe": "r1"})
        m = a.merge(b, on="CodInst").dropna(subset=fe)
        m["y"] = ((m["b1"] < 10.5) | (m["r1"] < -30.0)).astype(int)
        m["t"] = t
        pares.append(m)
    ev = pd.concat(pares, ignore_index=True)
    ult = pers[-2]
    trn, tst = ev[ev["t"] < ult], ev[ev["t"] == ult]
    g = GradientBoostingClassifier(random_state=42).fit(trn[fe].to_numpy(), trn["y"].to_numpy())
    p = g.predict_proba(tst[fe].to_numpy())[:, 1]
    out = pd.DataFrame([{
        "treino_pares": len(trn), "teste_par": f"{ult}->{pers[-1]}", "teste_n": len(tst),
        "teste_eventos": int(tst["y"].sum()),
        "auc_roc_ews2025": round(roc_auc_score(tst["y"], p), 3), "ks_ews2025": round(_ks(tst["y"], p), 3),
        "auc_roc_icr2_mesmo_par": round(roc_auc_score(tst["y"], -tst["ICR"]), 3),
    }])
    out.to_csv(DIR_PROCESSED / "ews2025_oot.csv", index=False, encoding="utf-8-sig")
    print("\n== Seção 5.5: EWS 2025–2026 fora do tempo ==")
    print(out.to_string(index=False))


if __name__ == "__main__":
    main()
