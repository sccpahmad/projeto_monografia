"""
ETAPA 9 (extensão) — ICR 2.0: índice IFRS-9 nativo (2025+) com CAMELS completo.

A reforma contábil de 2025 (Res. CMN 4.966) passou a divulgar a Perda Esperada,
permitindo cobrir a dimensão 'A' (Asset quality) do CAMELS — ausente no índice de
2016–2024 — via CUSTO DE RISCO. Este script:
  1. constrói o ICR 2.0 (8 indicadores, CAMELS completo) para os trimestres de
     2025+, com Basileia dos grandes bancos (portal);
  2. (§5.3) valida o índice ANTIGO: as faixas do ICR de 2024 (regime antigo, sem
     dados de provisão) preveem o custo de risco realizado em 2025?
  3. (§5.4) avalia o poder preditivo do PRÓPRIO ICR 2.0: usado como escore em t,
     ele ordena o distress (Basileia<10,5% ou ROE<-30%) do trimestre t+1?

Uso:
  python scripts/09_icr2_ifrs9.py

Gera:
  data/processed/icr2_ifrs9.parquet, ranking_icr2_<ultimo>.csv, validacao_reforma.csv,
  icr2_preditividade.csv, icr2_metricas.csv, icr2_sensibilidade.csv, importancia_modelos.csv
  figuras/icr2_custo_risco.png, icr2_validacao.png, icr2_preditividade.png,
  importancia_modelos.png
"""
from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

import matplotlib  # noqa: E402

matplotlib.use("Agg")
import matplotlib.pyplot as plt  # noqa: E402
import pandas as pd  # noqa: E402

from icr import icr2, ifdata, portal, score  # noqa: E402
from icr import explicabilidade as expl  # noqa: E402
from icr.config import (  # noqa: E402
    DIR_FIGURAS,
    DIR_PROCESSED,
    DIR_RAW,
    carregar_config,
    dir_processed_painel,
    garantir_diretorios,
)
from icr.http import criar_sessao  # noqa: E402


def _rotulo(anomes: int) -> str:
    return f"{anomes // 100}T{(anomes % 100) // 3}"


def main() -> None:
    garantir_diretorios()
    cfg = carregar_config()
    sessao = criar_sessao()
    ind_cfg = cfg["icr2_indicadores"]

    # 1) Basileia/Imobilização (portal) — define os períodos 2025+
    print("Portal IF.Data — índices de capital (prudencial):")
    cap = portal.baixar_indices_capital(sessao=sessao)
    if cap.empty:
        raise SystemExit("Portal indisponível.")
    periodos = sorted(int(p) for p in cap["AnoMes"].unique())
    print(f"Períodos IFRS-9 disponíveis: {periodos}")

    # 2) Indicadores IFRS-9 por trimestre (Olinda tipo=3)
    partes = []
    for per in periodos:
        r1 = ifdata.relatorio_largo(ifdata.baixar_valores(per, 3, 1, sessao=sessao))
        r2 = ifdata.relatorio_largo(ifdata.baixar_valores(per, 3, 2, sessao=sessao))
        r4 = ifdata.relatorio_largo(ifdata.baixar_valores(per, 3, 4, sessao=sessao))
        partes.append(icr2.construir_indicadores_ifrs9(r1, r2, r4))
    pan = pd.concat(partes, ignore_index=True)

    # 3) Nomes + Basileia/Imobilização + filtro
    nomes = pd.read_parquet(DIR_RAW / "nomes_instituicoes.parquet")
    pan = pan.merge(nomes[["CodInst", "nome"]], on="CodInst", how="left")
    pan["nome"] = pan["nome"].fillna(pan["CodInst"])
    pan = portal.anexar_basileia(pan, cap, cfg.get("crosswalk_prudencial"))
    pan = pan[(pan["basileia"].notna())
              & (pan["ativo_total_mil"].fillna(0) >= cfg["filtro_instituicoes"]["ativo_total_minimo_mil"])]
    pan = pan.reset_index(drop=True)
    print(f"Instituições no ICR 2.0: {pan['CodInst'].nunique()} × {pan['AnoMes'].nunique()} trim.")

    # 4) ICR 2.0 (CAMELS completo)
    padr = score.padronizar(pan, ind_cfg, cfg["padronizacao"])
    df = score.calcular_icr(padr, ind_cfg, "solidez")
    df = score.classificar_risco(df, cfg["zona_risco"]["percentil"], "solidez")
    df.to_parquet(DIR_PROCESSED / "icr2_ifrs9.parquet", index=False)

    ultimo = int(df["AnoMes"].max())
    cw = {str(k).zfill(8) for k in cfg.get("crosswalk_prudencial", {})}
    cols = ["nome", "ICR", "faixa", "basileia", "custo_risco", "roa", "roe",
            "liquidez", "eficiencia", "alavancagem", "imobilizacao", "ativo_total_mil"]
    cols = [c for c in cols if c in df.columns]
    rank = df[df["AnoMes"] == ultimo].sort_values("ICR", ascending=False)
    rank[cols].to_csv(DIR_PROCESSED / f"ranking_icr2_{ultimo}.csv", index=False, encoding="utf-8-sig")

    grandes = rank[rank["CodInst"].isin(cw)]
    pd.set_option("display.width", 200, "display.max_columns", 20)
    print(f"\n== ICR 2.0 — CAMELS completo (IFRS-9) — grandes bancos ({ultimo}) ==")
    print(grandes[[c for c in ["nome", "ICR", "faixa", "basileia", "custo_risco",
                               "roe", "liquidez", "eficiencia"] if c in grandes.columns]]
          .round(2).to_string(index=False))
    print("\n== Importância dos indicadores no ICR 2.0 ==")
    imp = expl.importancia_por_contribuicao(df, ind_cfg)
    print(imp.round(3).to_string(index=False))

    # 5) VALIDAÇÃO: faixas do ICR de 2024 x custo de risco realizado em 2025
    print("\n== Validação: ICR de 2024 (regime antigo) prevê o custo de risco de 2025? ==")
    cr = (pd.concat([icr2.custo_de_risco(
        ifdata.relatorio_largo(ifdata.baixar_valores(p, 3, 1, sessao=sessao)),
        ifdata.relatorio_largo(ifdata.baixar_valores(p, 3, 4, sessao=sessao)))
        for p in periodos]).groupby("CodInst")["custo_risco"].mean()
        .rename("custo_risco_2025"))
    old = pd.read_parquet(dir_processed_painel("sistemico") / "icr.parquet")
    old24 = old[old["AnoMes"] == 202412][["CodInst", "ICR", "faixa"]]
    m = old24.merge(cr, on="CodInst", how="inner").dropna(subset=["ICR", "custo_risco_2025"])
    lo, hi = m["custo_risco_2025"].quantile([0.01, 0.99])
    m = m[m["custo_risco_2025"].between(lo, hi)]

    pear = m["ICR"].corr(m["custo_risco_2025"])
    spear = m["ICR"].corr(m["custo_risco_2025"], method="spearman")
    ordem = ["Crítico", "Atenção", "Adequado", "Sólido"]
    g = m.groupby("faixa")["custo_risco_2025"].agg(["mean", "median", "count"]).reindex(ordem)
    print(f"  n={len(m)} | Pearson={pear:.3f} | Spearman={spear:.3f} (esperado negativo)")
    print(g.round(3).to_string())
    g.reset_index().to_csv(DIR_PROCESSED / "validacao_reforma.csv", index=False, encoding="utf-8-sig")

    # 6) Figuras
    _fig_custo_risco(grandes, ultimo)
    _fig_validacao(g)
    print(f"\nFiguras -> {DIR_FIGURAS}")

    # 7) Poder preditivo prospectivo do PRÓPRIO ICR 2.0 (§5.4): escore em t -> distress em t+1
    _avaliar_preditividade_icr2(df)

    # 8) Importância das variáveis nos DOIS modelos de alerta precoce (§5.5)
    _comparar_importancia_modelos(df)


def _fig_custo_risco(grandes: pd.DataFrame, ultimo: int) -> None:
    d = grandes.dropna(subset=["custo_risco"]).sort_values("custo_risco", ascending=True)
    if d.empty:
        return
    fig, ax = plt.subplots(figsize=(8, 4.5))
    ax.barh(d["nome"].str.slice(0, 24), d["custo_risco"], color="tab:red")
    ax.set_xlabel("Custo de risco — perda esperada / ativo (% a.a.)")
    ax.set_title(f"Custo de risco dos grandes bancos ({_rotulo(ultimo)}, IFRS 9)")
    fig.tight_layout(); fig.savefig(DIR_FIGURAS / "icr2_custo_risco.png", dpi=130)
    plt.close(fig)


def _fig_validacao(g: pd.DataFrame) -> None:
    g = g.dropna()
    if g.empty:
        return
    fig, ax = plt.subplots(figsize=(7, 4.5))
    x = list(g.index)
    ax.bar(x, g["mean"], color="tab:orange", label="média")
    ax.plot(x, g["median"], "ko--", label="mediana")
    ax.set_ylabel("Custo de risco realizado em 2025 (%)")
    ax.set_title("Faixa do ICR em 2024 × custo de risco médio em 2025")
    ax.legend()
    fig.tight_layout(); fig.savefig(DIR_FIGURAS / "icr2_validacao.png", dpi=130)
    plt.close(fig)


def _pares_distress(df: pd.DataFrame, bmin: float = 10.5, rmin: float = -30.0) -> pd.DataFrame:
    """Pares (t -> t+1) com ICR 2.0 em t e rótulo de distress em t+1."""
    d = df.copy()
    d["CodInst"] = d["CodInst"].astype(str)
    pers = sorted(int(p) for p in d["AnoMes"].unique())
    linhas = []
    for t, t1 in zip(pers[:-1], pers[1:]):
        a = d[d["AnoMes"] == t][["CodInst", "ICR"]].rename(columns={"ICR": "ICRt"})
        b = d[d["AnoMes"] == t1][["CodInst", "basileia", "roe"]]
        m = a.merge(b, on="CodInst", how="inner").dropna(subset=["ICRt"])
        m["distress"] = ((m["basileia"] < bmin) | (m["roe"] < rmin)).astype(int)
        m["t"] = t
        linhas.append(m)
    return pd.concat(linhas, ignore_index=True)


def _avaliar_preditividade_icr2(df: pd.DataFrame) -> None:
    """§5.4 — o próprio ICR 2.0, usado como escore (sem reestimação), prevê um evento
    de distress (Basileia < 10,5% ou ROE < −30%) no trimestre seguinte? Reproduz, para
    2025+, o mesmo painel de métricas do EWS de 2024 (AUC-ROC, AUC-PR, KS, matriz de
    confusão, ganho/lift, Brier e sensibilidade aos limiares).

    Salva icr2_preditividade.csv (por par), icr2_metricas.csv, icr2_sensibilidade.csv
    e figuras/icr2_preditividade.png (painel 2×3).
    """
    try:
        import numpy as np
        from sklearn.linear_model import LogisticRegression
        from sklearn.metrics import (average_precision_score, brier_score_loss,
                                      confusion_matrix, precision_recall_curve,
                                      precision_recall_fscore_support, roc_auc_score,
                                      roc_curve)
    except Exception as exc:  # noqa: BLE001
        print(f"  [aviso] dependência indisponível p/ preditividade do ICR 2.0 ({exc}).")
        return
    ev = _pares_distress(df)
    if ev["distress"].sum() == 0:
        print("  [aviso] sem eventos de distress no horizonte IFRS-9 (janela curta).")
        return
    y = ev["distress"].to_numpy()
    risk = (-ev["ICRt"]).to_numpy()          # escore de risco: ICR baixo => risco alto

    auc = roc_auc_score(y, risk)
    ap = average_precision_score(y, risk)
    fpr, tpr, thr = roc_curve(y, risk)
    ks = float((tpr - fpr).max()); thr_y = float(thr[(tpr - fpr).argmax()])
    pred = (risk >= thr_y).astype(int)
    cm = confusion_matrix(y, pred)
    prec, rec, f1, _ = precision_recall_fscore_support(y, pred, average="binary", zero_division=0)
    prc_p, prc_r, _ = precision_recall_curve(y, risk)
    o = pd.DataFrame({"y": y, "risk": risk}).sort_values("risk", ascending=False).reset_index(drop=True)
    o["dec"] = pd.qcut(o.index, 10, labels=range(1, 11))
    gd = o.groupby("dec", observed=True).agg(n=("y", "size"), pos=("y", "sum"))
    captura = gd["pos"].cumsum() / o["y"].sum()
    lift = (gd["pos"].iloc[0] / gd["n"].iloc[0]) / o["y"].mean()
    frac = np.arange(1, len(o) + 1) / len(o); cap = np.cumsum(o["y"].to_numpy()) / o["y"].sum()
    # Brier: calibração logística do escore -> probabilidade, avaliada FORA DO TEMPO
    tt = sorted(ev["t"].unique()); tr = ev[ev["t"].isin(tt[:-1])]; te = ev[ev["t"] == tt[-1]]
    lr = LogisticRegression().fit((-tr["ICRt"]).to_numpy().reshape(-1, 1), tr["distress"].to_numpy())
    brier = float(brier_score_loss(te["distress"].to_numpy(),
                                   lr.predict_proba((-te["ICRt"]).to_numpy().reshape(-1, 1))[:, 1]))

    print("\n== §5.4 Poder preditivo prospectivo do ICR 2.0 (escore em t -> distress em t+1) ==")
    print(f"  n={len(y)} pares, eventos={int(y.sum())} ({100*y.mean():.1f}%)")
    print(f"  AUC-ROC={auc:.3f}  AUC-PR={ap:.3f}  KS={ks:.3f}  "
          f"prec={prec:.3f} rec={rec:.3f} F1={f1:.3f}  Brier(oot)={brier:.3f}")
    print(f"  decil de maior risco captura {100*captura.iloc[0]:.0f}% dos eventos (lift {lift:.1f}x)")

    # por par (estabilidade)
    reg = [{"par": "POOLED", "n": len(y), "eventos": int(y.sum()), "auc": round(float(auc), 3)}]
    for t, gg in ev.groupby("t"):
        if gg["distress"].sum() > 0:
            reg.append({"par": _rotulo(int(t)), "n": len(gg), "eventos": int(gg["distress"].sum()),
                        "auc": round(float(roc_auc_score(gg["distress"], -gg["ICRt"])), 3)})
    pd.DataFrame(reg).to_csv(DIR_PROCESSED / "icr2_preditividade.csv", index=False, encoding="utf-8-sig")
    pd.DataFrame([
        {"metrica": "n_pares", "valor": len(y)}, {"metrica": "eventos", "valor": int(y.sum())},
        {"metrica": "taxa_base", "valor": round(float(y.mean()), 4)},
        {"metrica": "auc_roc", "valor": round(float(auc), 3)}, {"metrica": "auc_pr", "valor": round(float(ap), 3)},
        {"metrica": "ks", "valor": round(ks, 3)}, {"metrica": "precisao", "valor": round(float(prec), 3)},
        {"metrica": "revocacao", "valor": round(float(rec), 3)}, {"metrica": "f1", "valor": round(float(f1), 3)},
        {"metrica": "brier_oot", "valor": round(brier, 3)},
        {"metrica": "captura_decil_top", "valor": round(float(captura.iloc[0]), 3)},
        {"metrica": "lift_decil_top", "valor": round(float(lift), 1)},
    ]).to_csv(DIR_PROCESSED / "icr2_metricas.csv", index=False, encoding="utf-8-sig")

    # Sensibilidade aos limiares (como no §4.7)
    sens = []
    for bm in (8.0, 10.5, 11.0):
        for rm in (-20.0, -30.0, -40.0):
            e = _pares_distress(df, bm, rm); yy = e["distress"].to_numpy(); rr = (-e["ICRt"]).to_numpy()
            if yy.sum() == 0:
                continue
            f2, t2, _ = roc_curve(yy, rr)
            sens.append({"basileia_min": bm, "roe_min": rm, "taxa_base": round(float(yy.mean()), 4),
                         "auc_roc": round(float(roc_auc_score(yy, rr)), 3), "ks": round(float((t2 - f2).max()), 3)})
    pd.DataFrame(sens).to_csv(DIR_PROCESSED / "icr2_sensibilidade.csv", index=False, encoding="utf-8-sig")

    # Figura painel 2×3 (espelha o painel de avaliação do EWS de 2024)
    fig, ax = plt.subplots(2, 3, figsize=(13, 8))
    ax[0, 0].plot(fpr, tpr, "b", lw=2, label=f"AUC={auc:.3f}"); ax[0, 0].plot([0, 1], [0, 1], "--", c="gray")
    ax[0, 0].set_title("Curva ROC"); ax[0, 0].set_xlabel("FPR"); ax[0, 0].set_ylabel("TPR"); ax[0, 0].legend(loc="lower right")
    ax[0, 1].plot(prc_r, prc_p, "g", lw=2, label=f"AUC-PR={ap:.3f}"); ax[0, 1].axhline(y.mean(), ls="--", c="gray", label=f"base {y.mean():.3f}")
    ax[0, 1].set_title("Precisão-Revocação"); ax[0, 1].set_xlabel("Revocação"); ax[0, 1].set_ylabel("Precisão"); ax[0, 1].legend()
    xs = np.linspace(risk.min(), risk.max(), 200)
    cdf_pos = np.array([(risk[y == 1] <= v).mean() for v in xs]); cdf_neg = np.array([(risk[y == 0] <= v).mean() for v in xs])
    ax[0, 2].plot(xs, cdf_neg, label="não-distress"); ax[0, 2].plot(xs, cdf_pos, label="distress")
    ax[0, 2].axvline(xs[np.argmax(np.abs(cdf_neg - cdf_pos))], ls=":", c="r")
    ax[0, 2].set_title(f"KS = {ks:.3f}"); ax[0, 2].set_xlabel("escore de risco (−ICR 2.0)"); ax[0, 2].legend()
    ax[1, 0].hist(ev["ICRt"][y == 0], bins=30, alpha=.6, density=True, label="não-distress")
    ax[1, 0].hist(ev["ICRt"][y == 1], bins=30, alpha=.6, density=True, label="distress")
    ax[1, 0].set_title("Distribuição do ICR 2.0 por classe"); ax[1, 0].set_xlabel("ICR 2.0 em t"); ax[1, 0].legend()
    ax[1, 1].imshow(cm, cmap="Blues"); ax[1, 1].set_title(f"Matriz de confusão (Youden)\nprec={prec:.2f} rec={rec:.2f} F1={f1:.2f}")
    for (i, j), v in np.ndenumerate(cm):
        ax[1, 1].text(j, i, str(v), ha="center", va="center", color="white" if v > cm.max() / 2 else "black")
    ax[1, 1].set_xticks([0, 1]); ax[1, 1].set_xticklabels(["prev. 0", "prev. 1"])
    ax[1, 1].set_yticks([0, 1]); ax[1, 1].set_yticklabels(["real 0", "real 1"])
    ax[1, 2].plot(frac, cap, "b", lw=2); ax[1, 2].plot([0, 1], [0, 1], "--", c="gray")
    ax[1, 2].axvline(.1, ls=":", c="r", label=f"decil top: {100*captura.iloc[0]:.0f}%")
    ax[1, 2].set_title("Curva de ganho"); ax[1, 2].set_xlabel("fração inspecionada"); ax[1, 2].set_ylabel("captura de eventos"); ax[1, 2].legend(loc="lower right")
    fig.suptitle("Avaliação prospectiva do ICR 2.0 (IFRS 9, 2025–2026): escore em t → distress em t+1", fontsize=12)
    fig.tight_layout(rect=[0, 0, 1, 0.97]); fig.savefig(DIR_FIGURAS / "icr2_preditividade.png", dpi=110)
    plt.close(fig)


def _comparar_importancia_modelos(df: pd.DataFrame) -> None:
    """§5.5 — importância das variáveis nos DOIS modelos de alerta precoce: o EWS de
    2016–2024 (distress_importancias.csv, do script 06) e um GBM treinado sobre os oito
    indicadores do ICR 2.0 (2025+). Salva importancia_modelos.csv e a figura comparativa.
    """
    try:
        import numpy as np
        from sklearn.ensemble import GradientBoostingClassifier
    except Exception as exc:  # noqa: BLE001
        print(f"  [aviso] dependência indisponível p/ comparação de importância ({exc}).")
        return
    imp24_path = DIR_PROCESSED / "distress_importancias.csv"
    if not imp24_path.exists():
        print("  [aviso] distress_importancias.csv ausente (rode o script 06); comparação pulada.")
        return
    imp24 = pd.read_csv(imp24_path).rename(columns={"importancia": "ews_2024"})
    FE = ["basileia", "alavancagem", "roa", "roe", "imobilizacao", "liquidez",
          "eficiencia", "custo_risco"]
    d = df.copy(); d["CodInst"] = d["CodInst"].astype(str)
    pers = sorted(int(p) for p in d["AnoMes"].unique())
    rows = []
    for t, t1 in zip(pers[:-1], pers[1:]):
        a = d[d["AnoMes"] == t][["CodInst"] + FE]
        b = d[d["AnoMes"] == t1][["CodInst", "basileia", "roe"]].rename(
            columns={"basileia": "b1", "roe": "r1"})
        m = a.merge(b, on="CodInst", how="inner").dropna(subset=FE)
        m["distress"] = ((m["b1"] < 10.5) | (m["r1"] < -30.0)).astype(int)
        rows.append(m)
    ev = pd.concat(rows, ignore_index=True)
    g = GradientBoostingClassifier(random_state=42).fit(ev[FE].to_numpy(), ev["distress"].to_numpy())
    tab = (pd.DataFrame({"feature": FE, "ews_2025": g.feature_importances_})
           .merge(imp24[["feature", "ews_2024"]], on="feature", how="left"))
    tab["ews_2024"] = tab["ews_2024"].fillna(0.0)
    tab = tab.sort_values("ews_2024", ascending=False).reset_index(drop=True)
    tab[["feature", "ews_2024", "ews_2025"]].round(3).to_csv(
        DIR_PROCESSED / "importancia_modelos.csv", index=False, encoding="utf-8-sig")
    print("\n== §5.5 Importância das variáveis nos dois modelos (EWS 2024 vs 2025) ==")
    print(tab[["feature", "ews_2024", "ews_2025"]].round(3).to_string(index=False))

    lab = {"roe": "ROE", "roa": "ROA", "eficiencia": "Eficiência", "basileia": "Basileia",
           "imobilizacao": "Imobilização", "liquidez": "Liquidez",
           "alavancagem": "Alavancagem", "custo_risco": "Custo de risco"}
    t2 = tab.sort_values("ews_2024"); y = np.arange(len(t2)); h = 0.4
    fig, ax = plt.subplots(figsize=(8.5, 5))
    ax.barh(y + h / 2, t2["ews_2024"], h, label="EWS 2016–2024", color="tab:blue")
    ax.barh(y - h / 2, t2["ews_2025"], h, label="EWS 2025–2026 (IFRS 9)", color="tab:orange")
    ax.set_yticks(y); ax.set_yticklabels([lab.get(f, f) for f in t2["feature"]])
    ax.set_xlabel("Importância da variável (gradient boosting)")
    ax.set_title("Importância das variáveis nos dois modelos de alerta precoce")
    ax.legend(loc="lower right")
    fig.tight_layout(); fig.savefig(DIR_FIGURAS / "importancia_modelos.png", dpi=120)
    plt.close(fig)


if __name__ == "__main__":
    main()
