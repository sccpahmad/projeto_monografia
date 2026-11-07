"""
ETAPA 6 — Modelo de Alerta Precoce (EWS): previsão de distress bancário.

Usa o painel 'prudencial' (tem Basileia, essencial para o rótulo de capital,
e 36 trimestres de profundidade). Gera:
  data/processed/distress_metricas.csv
  data/processed/distress_importancias.csv, distress_shap.csv, distress_tuning.csv
  data/processed/distress_watchlist.csv
  figuras/distress_importancias.png
  figuras/distress_roc.png

Uso:
  python scripts/06_modelo_distress.py [painel]   # painel padrão: prudencial
"""
from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

import matplotlib  # noqa: E402

matplotlib.use("Agg")
import matplotlib.pyplot as plt  # noqa: E402
import pandas as pd  # noqa: E402

from icr import distress  # noqa: E402
from icr.config import (  # noqa: E402
    DIR_FIGURAS,
    DIR_PROCESSED,
    carregar_config,
    dir_processed_painel,
    garantir_diretorios,
)


def main() -> None:
    garantir_diretorios()
    cfg = carregar_config()
    painel = sys.argv[1] if len(sys.argv) > 1 else "prudencial"

    ind_path = dir_processed_painel(painel) / "indicadores.parquet"
    if not ind_path.exists():
        raise SystemExit(f"Sem indicadores do painel '{painel}'. Rode 02_construir_icr.py.")
    df = pd.read_parquet(ind_path)

    dd = cfg.get("distress", {})
    d = distress.marcar_distress(
        df,
        basileia_min=dd.get("basileia_min", 10.5),
        roe_min=dd.get("roe_min", -30.0),
        horizonte=dd.get("horizonte", 4),
    )
    base_rate = d.loc[d["horizonte_observavel"], "alvo"].mean()
    print(f"Painel '{painel}' | distress (Basileia<{dd.get('basileia_min',10.5)} "
          f"ou ROE<{dd.get('roe_min',-30)}) em t+1..t+{dd.get('horizonte',4)}")
    print(f"Taxa-base de distress futuro: {base_rate:.2%}")

    res = distress.treinar_avaliar(d, embargo=dd.get("horizonte", 4))
    metr = res["metricas"]
    print("\n== Desempenho out-of-time ==")
    for k, v in metr.items():
        print(f"  {k}: {v}")
    pd.DataFrame([metr]).to_csv(DIR_PROCESSED / "distress_metricas.csv", index=False)

    res["importancias"].to_csv(DIR_PROCESSED / "distress_importancias.csv", index=False)
    print("\n== Importância das variáveis (impureza/Gini) ==")
    print(res["importancias"].to_string(index=False))

    # --- SHAP (não circular: alvo externo ao ICR) --------------------------
    shap_imp = distress.importancia_shap(res)
    if shap_imp is not None:
        shap_imp.to_csv(DIR_PROCESSED / "distress_shap.csv", index=False)
        print("\n== Importância SHAP (|valor| médio, teste out-of-time) ==")
        print(shap_imp.round(3).to_string(index=False))

    # --- Justificativa empírica dos hiperparâmetros (default vs. tuned) -----
    tun = distress.tunar_hiperparametros(d, embargo=dd.get("horizonte", 4))
    pd.DataFrame([
        {"modelo": "default", "auc_teste": round(tun["default"]["auc"], 4),
         "ks_teste": round(tun["default"]["ks"], 4)},
        {"modelo": f"tuned {tun['tuned']['cfg']}", "auc_teste": round(tun["tuned"]["auc"], 4),
         "ks_teste": round(tun["tuned"]["ks"], 4)},
    ]).to_csv(DIR_PROCESSED / "distress_tuning.csv", index=False, encoding="utf-8-sig")
    print("\n== Tuning de hiperparâmetros (busca com validação temporal interna) ==")
    print(f"  default: AUC={tun['default']['auc']:.4f}  KS={tun['default']['ks']:.4f}")
    print(f"  tuned  : AUC={tun['tuned']['auc']:.4f}  KS={tun['tuned']['ks']:.4f}  cfg={tun['tuned']['cfg']}")
    print(f"  -> ganho do tuning no teste: dAUC={tun['tuned']['auc']-tun['default']['auc']:+.4f} "
          "(defaults justificados quando ~0 ou negativo)")

    # --- Avaliação completa do classificador (rara/desbalanceada) ----------
    av = distress.avaliar_classificacao(res["teste"])
    print("\n== Avaliação da classificação (teste out-of-time) ==")
    print(f"  AUC-ROC={av['auc_roc']:.3f}  AUC-PR={av['auc_pr']:.3f}  KS={av['ks']:.3f}")
    print(f"  Limiar (Youden)={av['limiar']:.3f}  ->  "
          f"recall={av['recall']:.2f}  precisão={av['precisao']:.2f}  F1={av['f1']:.2f}")
    print(f"  Matriz de confusão [[VN,FP],[FN,VP]] = {av['matriz_confusao'].tolist()}")
    pd.DataFrame([{k: v for k, v in av.items() if k != "matriz_confusao"}]).to_csv(
        DIR_PROCESSED / "distress_avaliacao.csv", index=False)
    ganho = distress.tabela_ganho(res["teste"]["alvo"], res["teste"]["prob_distress"])
    ganho.to_csv(DIR_PROCESSED / "distress_ganho.csv", index=False)
    print(f"  Decil de maior risco captura {ganho['captura_acum'].iloc[0]:.0%} dos casos "
          f"(lift {ganho['lift'].iloc[0]:.1f}x)")

    # --- Calibração + robustez ao limiar -----------------------------------
    pp, pt, brier = distress.curva_calibracao(res["teste"])
    print(f"  Brier score = {brier:.4f} (calibração das probabilidades; menor é melhor)")
    linha = {k: v for k, v in av.items() if k != "matriz_confusao"}
    linha["brier"] = brier
    pd.DataFrame([linha]).to_csv(DIR_PROCESSED / "distress_avaliacao.csv", index=False)

    sens = distress.sensibilidade_limiares(df)
    sens.to_csv(DIR_PROCESSED / "distress_sensibilidade.csv", index=False)
    print("\n== Sensibilidade aos limiares (AUC/KS estáveis => robusto) ==")
    print(sens.round(3).to_string(index=False))

    wl = distress.watchlist(d, res)
    wl.to_csv(DIR_PROCESSED / "distress_watchlist.csv", index=False, encoding="utf-8-sig")
    print("\n== Watchlist: maior probabilidade de distress (trimestre atual) ==")
    print(wl.head(10).to_string(index=False))

    _plot_importancias(res["importancias"])
    _plot_roc(res["teste"])
    _plot_avaliacao(res["teste"], av, ganho)
    _plot_robustez(pp, pt, brier, sens)
    print(f"\nFiguras -> {DIR_FIGURAS}")


def _plot_importancias(imp: pd.DataFrame) -> None:
    fig, ax = plt.subplots(figsize=(7, 4))
    ax.barh(imp["feature"], imp["importancia"], color="tab:orange")
    ax.invert_yaxis(); ax.set_xlabel("Importância (Gini)")
    ax.set_title("EWS — variáveis que mais preveem distress")
    fig.tight_layout(); fig.savefig(DIR_FIGURAS / "distress_importancias.png", dpi=130)
    plt.close(fig)


def _plot_roc(teste: pd.DataFrame) -> None:
    try:
        from sklearn.metrics import roc_curve
    except Exception:  # noqa: BLE001
        return
    if teste["alvo"].sum() == 0:
        return
    fpr, tpr, _ = roc_curve(teste["alvo"], teste["prob_distress"])
    fig, ax = plt.subplots(figsize=(5.5, 5))
    ax.plot(fpr, tpr, color="tab:red", lw=2)
    ax.plot([0, 1], [0, 1], "--", color="grey")
    ax.set_xlabel("Falso positivo"); ax.set_ylabel("Verdadeiro positivo")
    ax.set_title("EWS — Curva ROC (teste out-of-time)")
    fig.tight_layout(); fig.savefig(DIR_FIGURAS / "distress_roc.png", dpi=130)
    plt.close(fig)


def _plot_avaliacao(teste: pd.DataFrame, av: dict, ganho: pd.DataFrame) -> None:
    """Painel 2x3: ROC, Precision-Recall, KS, distribuição do escore, matriz de
    confusão e curva de ganho — as principais formas de avaliar um classificador
    de evento raro."""
    try:
        from sklearn.metrics import precision_recall_curve, roc_curve
    except Exception:  # noqa: BLE001
        return
    if teste["alvo"].sum() == 0:
        return
    import numpy as np

    y = teste["alvo"].to_numpy(); p = teste["prob_distress"].to_numpy()
    fpr, tpr, _ = roc_curve(y, p)
    prec, rec, _ = precision_recall_curve(y, p)
    srt = pd.DataFrame({"y": y, "p": p}).sort_values("p").reset_index(drop=True)
    srt["cg"] = (srt.y == 0).cumsum() / (srt.y == 0).sum()
    srt["cb"] = (srt.y == 1).cumsum() / (srt.y == 1).sum()
    cm = av["matriz_confusao"]

    fig, ax = plt.subplots(2, 3, figsize=(15, 9))
    ax[0,0].plot(fpr, tpr, "r"); ax[0,0].plot([0,1],[0,1],"--",color="grey")
    ax[0,0].set_title(f"ROC (AUC={av['auc_roc']:.2f})"); ax[0,0].set_xlabel("FPR"); ax[0,0].set_ylabel("TPR")
    ax[0,1].plot(rec, prec, "b"); ax[0,1].axhline(av["taxa_base"], ls="--", color="grey")
    ax[0,1].set_title(f"Precision-Recall (AP={av['auc_pr']:.2f})"); ax[0,1].set_xlabel("Recall"); ax[0,1].set_ylabel("Precisão")
    ax[0,2].plot(srt.p, srt.cg, label="saudáveis"); ax[0,2].plot(srt.p, srt.cb, label="distress")
    ax[0,2].set_title(f"KS={av['ks']:.2f}"); ax[0,2].set_xlabel("Escore"); ax[0,2].set_ylabel("% acum."); ax[0,2].legend()
    ax[1,0].hist(p[y==0], bins=40, density=True, alpha=.5, label="saudável")
    ax[1,0].hist(p[y==1], bins=40, density=True, alpha=.5, label="distress")
    ax[1,0].set_title("Distribuição do escore"); ax[1,0].set_xlabel("prob."); ax[1,0].legend()
    ax[1,1].imshow(cm, cmap="Blues")
    for i in range(2):
        for j in range(2):
            ax[1,1].text(j, i, cm[i, j], ha="center", va="center", fontsize=12)
    ax[1,1].set_xticks([0,1]); ax[1,1].set_xticklabels(["prev.saud.","prev.dist."])
    ax[1,1].set_yticks([0,1]); ax[1,1].set_yticklabels(["real saud.","real dist."])
    ax[1,1].set_title(f"Matriz de confusão (lim={av['limiar']:.3f})")
    ax[1,2].plot(range(1, len(ganho)+1), ganho["captura_acum"], "o-")
    ax[1,2].plot([1, len(ganho)], [1/len(ganho), 1], "--", color="grey")
    ax[1,2].set_title("Curva de ganho"); ax[1,2].set_xlabel("Decis (maior risco→)"); ax[1,2].set_ylabel("% distress capturado")
    fig.suptitle("EWS — avaliação do classificador (teste out-of-time)", fontsize=14)
    fig.tight_layout(); fig.savefig(DIR_FIGURAS / "distress_avaliacao.png", dpi=130)
    plt.close(fig)


def _plot_robustez(pp, pt, brier: float, sens: pd.DataFrame) -> None:
    """Calibração (esquerda) + AUC por grade de limiares (direita)."""
    fig, ax = plt.subplots(1, 2, figsize=(12, 4.6))
    ax[0].plot(pp, pt, "o-", label="modelo")
    ax[0].plot([0, pp.max()], [0, pp.max()], "--", color="grey", label="calibração perfeita")
    ax[0].set_xlabel("Probabilidade prevista"); ax[0].set_ylabel("Frequência observada")
    ax[0].set_title(f"Calibração (Brier = {brier:.3f})"); ax[0].legend()

    piv = sens.pivot(index="basileia_min", columns="roe_min", values="auc_roc")
    im = ax[1].imshow(piv.values, cmap="Greens", vmin=0.75, vmax=0.90)
    ax[1].set_xticks(range(len(piv.columns))); ax[1].set_xticklabels(piv.columns)
    ax[1].set_yticks(range(len(piv.index))); ax[1].set_yticklabels(piv.index)
    for i in range(piv.shape[0]):
        for j in range(piv.shape[1]):
            ax[1].text(j, i, f"{piv.values[i, j]:.2f}", ha="center", va="center")
    ax[1].set_xlabel("ROE mínimo (%)"); ax[1].set_ylabel("Basileia mínima (%)")
    ax[1].set_title("AUC-ROC por combinação de limiares"); fig.colorbar(im, ax=ax[1])
    fig.tight_layout(); fig.savefig(DIR_FIGURAS / "distress_robustez.png", dpi=130)
    plt.close(fig)


if __name__ == "__main__":
    main()
