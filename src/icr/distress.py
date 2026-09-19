"""
Modelo de Alerta Precoce (EWS) — previsão de distress bancário.

Diferente da explicabilidade do ICR (que é circular, pois o alvo derivaria do
próprio índice), aqui o alvo é um EVENTO FUTURO e observável:

  Evento de distress em (i, t)  :=
        Basileia < `basileia_min`  (quebra do requerimento + colchão)
     OR ROE      < `roe_min`       (prejuízo severo corroendo o capital)

  Alvo y(i, t) = 1 se houver evento de distress em ALGUM dos próximos
                 `horizonte` trimestres (t+1 .. t+h).

As variáveis explicativas são os indicadores no trimestre t. O modelo aprende
a antecipar a deterioração com ~1 ano de antecedência — exatamente a proposta
de um EWS (cf. Betz et al., 2014; Lang, Peltonen & Sarlin, 2018).

Split TEMPORAL (treina no passado, testa no futuro). Para evitar vazamento de
look-ahead no limiar do split, aplica-se um EMBARGO: os últimos `embargo`
trimestres antes do corte são removidos do treino, pois seus rótulos
(que olham t+1..t+h) dependeriam de eventos do período de teste. Usa-se
embargo = horizonte.
"""
from __future__ import annotations

import numpy as np
import pandas as pd

FEATURES_PADRAO = [
    "basileia", "alavancagem", "roa", "roe", "liquidez", "eficiencia", "imobilizacao",
]


def _quarter_index(anomes: pd.Series) -> pd.Series:
    """AnoMes (AAAAMM, fim de trimestre) -> índice trimestral contínuo."""
    ano = anomes // 100
    tri = (anomes % 100) // 3  # 1..4
    return ano * 4 + (tri - 1)


def marcar_distress(
    df: pd.DataFrame,
    basileia_min: float = 10.5,
    roe_min: float = -30.0,
    horizonte: int = 4,
) -> pd.DataFrame:
    """Adiciona 'evento_distress' (no trimestre) e 'alvo' (evento em t+1..t+h)."""
    d = df.copy()
    d["qidx"] = _quarter_index(d["AnoMes"])

    evento = pd.Series(False, index=d.index)
    if "basileia" in d.columns and d["basileia"].notna().any():
        evento = evento | (d["basileia"] < basileia_min)
    if "roe" in d.columns:
        evento = evento | (d["roe"] < roe_min)
    d["evento_distress"] = evento.fillna(False)

    # alvo: existe evento em t+1..t+h para a MESMA instituição
    eventos = d[d["evento_distress"]][["CodInst", "qidx"]].copy()
    ev_por_inst = eventos.groupby("CodInst")["qidx"].apply(set).to_dict()

    def _tem_evento_futuro(row) -> bool:
        s = ev_por_inst.get(row["CodInst"])
        if not s:
            return False
        return any((row["qidx"] + k) in s for k in range(1, horizonte + 1))

    d["alvo"] = d.apply(_tem_evento_futuro, axis=1).astype(int)

    # só mantém linhas cujo horizonte futuro é observável
    qmax = d["qidx"].max()
    d["horizonte_observavel"] = d["qidx"] <= (qmax - horizonte)
    return d


def split_temporal(d: pd.DataFrame, qidx_corte: int, embargo: int = 0):
    """Treino = trimestres <= (corte - embargo); Teste = > corte.

    O embargo remove os `embargo` trimestres imediatamente antes do corte, cujos
    rótulos (que olham t+1..t+h) dependeriam de eventos do período de teste.
    """
    base = d[d["horizonte_observavel"]].copy()
    treino = base[base["qidx"] <= qidx_corte - embargo]
    teste = base[base["qidx"] > qidx_corte]
    return treino, teste


def treinar_avaliar(
    d: pd.DataFrame,
    features: list[str] | None = None,
    fracao_treino: float = 0.7,
    embargo: int = 4,
):
    """Treina um classificador e avalia no período de teste (out-of-time).

    Retorna dict com métricas, importâncias e o modelo.
    """
    try:
        from sklearn.ensemble import GradientBoostingClassifier
        from sklearn.metrics import (
            average_precision_score,
            roc_auc_score,
        )
    except Exception as exc:  # noqa: BLE001
        raise RuntimeError(f"scikit-learn indisponível: {exc}")

    feats = [f for f in (features or FEATURES_PADRAO)
             if f in d.columns and d[f].notna().any()]
    base = d[d["horizonte_observavel"]].dropna(subset=feats + ["alvo"]).copy()

    # corte temporal: (fracao_treino*n)-ésimo trimestre ordenado (split posicional)
    qs = np.sort(base["qidx"].unique())
    corte = qs[min(int(len(qs) * fracao_treino), len(qs) - 1)]
    treino, teste = split_temporal(base, corte, embargo=embargo)

    Xtr, ytr = treino[feats].to_numpy(), treino["alvo"].to_numpy()
    Xte, yte = teste[feats].to_numpy(), teste["alvo"].to_numpy()

    modelo = GradientBoostingClassifier(random_state=42)
    modelo.fit(Xtr, ytr)
    p_te = modelo.predict_proba(Xte)[:, 1]

    metr = {
        "n_treino": len(treino),
        "n_teste": len(teste),
        "taxa_distress_treino": float(ytr.mean()),
        "taxa_distress_teste": float(yte.mean()),
        "trimestre_corte": int(corte),
        "auc_roc": float(roc_auc_score(yte, p_te)) if yte.sum() else None,
        "auc_pr": float(average_precision_score(yte, p_te)) if yte.sum() else None,
    }
    importancias = (
        pd.DataFrame({"feature": feats, "importancia": modelo.feature_importances_})
        .sort_values("importancia", ascending=False)
        .reset_index(drop=True)
    )
    return {"modelo": modelo, "features": feats, "metricas": metr,
            "importancias": importancias, "teste": teste.assign(prob_distress=p_te)}


def watchlist(d: pd.DataFrame, resultado: dict, top: int = 15) -> pd.DataFrame:
    """Aplica o modelo ao trimestre mais recente -> ranking de risco futuro."""
    modelo, feats = resultado["modelo"], resultado["features"]
    ultimo = d["AnoMes"].max()
    atual = d[d["AnoMes"] == ultimo].dropna(subset=feats).copy()
    atual["prob_distress"] = modelo.predict_proba(atual[feats].to_numpy())[:, 1]
    cols = [c for c in ["nome", "prob_distress", "basileia", "roe", "liquidez",
                        "eficiencia", "ativo_total_mil", "CodInst"] if c in atual.columns]
    return atual.sort_values("prob_distress", ascending=False)[cols].head(top).reset_index(drop=True)


# ---------------------------------------------------------------------------
# Avaliação da classificação (métricas adequadas a eventos raros/desbalanceados)
# ---------------------------------------------------------------------------
def ks_youden(y_true, prob):
    """Estatística KS e limiar de Youden.

    Em credit scoring, KS = máxima separação entre as taxas de verdadeiros e
    falsos positivos ao longo do escore: KS = max(TPR − FPR). O limiar onde
    isso ocorre (Youden's J) é um ponto de corte natural para a matriz de
    confusão. Retorna (ks, limiar, (fpr, tpr, thr)).
    """
    from sklearn.metrics import roc_curve

    fpr, tpr, thr = roc_curve(y_true, prob)
    j = tpr - fpr
    i = int(j.argmax())
    return float(j[i]), float(thr[i]), (fpr, tpr, thr)


def tabela_ganho(y_true, prob, grupos: int = 10) -> pd.DataFrame:
    """Tabela de lift/ganho por decil de risco (grupo 1 = maior probabilidade).

    Mostra o valor operacional de uma watchlist: ao inspecionar os X% de maior
    escore, quanto dos casos de distress são capturados (ganho acumulado) e
    quantas vezes acima do acaso (lift).
    """
    df = (
        pd.DataFrame({"y": np.asarray(y_true), "p": np.asarray(prob)})
        .sort_values("p", ascending=False)
        .reset_index(drop=True)
    )
    base = df["y"].mean() or np.nan
    df["grupo"] = pd.qcut(df.index, grupos, labels=range(1, grupos + 1))
    g = df.groupby("grupo", observed=True).agg(n=("y", "size"), positivos=("y", "sum"))
    g["taxa_distress"] = g["positivos"] / g["n"]
    g["lift"] = g["taxa_distress"] / base
    g["captura_acum"] = g["positivos"].cumsum() / df["y"].sum()
    return g.reset_index()


def avaliar_classificacao(teste: pd.DataFrame, limiar: float | None = None) -> dict:
    """Painel de métricas para o conjunto de teste (colunas 'alvo', 'prob_distress').

    Retorna AUC-ROC, AUC-PR, KS, limiar de corte, matriz de confusão e
    precisão/recall/F1 no ponto de corte.
    """
    from sklearn.metrics import (
        average_precision_score,
        confusion_matrix,
        precision_recall_fscore_support,
        roc_auc_score,
    )

    y = teste["alvo"].to_numpy()
    p = teste["prob_distress"].to_numpy()
    ks, thr_youden, _ = ks_youden(y, p)
    limiar = thr_youden if limiar is None else limiar
    pred = (p >= limiar).astype(int)
    cm = confusion_matrix(y, pred)
    prec, rec, f1, _ = precision_recall_fscore_support(
        y, pred, average="binary", zero_division=0
    )
    return {
        "auc_roc": float(roc_auc_score(y, p)),
        "auc_pr": float(average_precision_score(y, p)),
        "ks": ks,
        "limiar": float(limiar),
        "matriz_confusao": cm,          # [[VN, FP], [FN, VP]]
        "precisao": float(prec),
        "recall": float(rec),
        "f1": float(f1),
        "taxa_base": float(y.mean()),
    }


def curva_calibracao(teste: pd.DataFrame, n_bins: int = 10):
    """Confiabilidade das probabilidades previstas.

    Agrupa as previsões em faixas e compara a probabilidade média prevista com a
    frequência real de distress observada. Um modelo bem calibrado fica sobre a
    diagonal. Retorna (prob_prevista, prob_observada, brier). O Brier score
    (menor = melhor) resume o erro quadrático das probabilidades.
    """
    from sklearn.calibration import calibration_curve
    from sklearn.metrics import brier_score_loss

    y = teste["alvo"].to_numpy()
    p = teste["prob_distress"].to_numpy()
    prob_true, prob_pred = calibration_curve(y, p, n_bins=n_bins, strategy="quantile")
    return prob_pred, prob_true, float(brier_score_loss(y, p))


def sensibilidade_limiares(
    df: pd.DataFrame,
    basileias=(8.0, 10.5, 11.0),
    roes=(-20.0, -30.0, -40.0),
    horizonte: int = 4,
) -> pd.DataFrame:
    """Robustez do EWS à definição de distress.

    Reconstrói o rótulo e reestima o modelo para cada combinação de limiares de
    Basileia e ROE, reportando taxa-base, AUC-ROC e KS. Se o desempenho for
    estável na grade, o resultado não depende de uma escolha arbitrária de corte.
    """
    linhas = []
    for bmin in basileias:
        for rmin in roes:
            d = marcar_distress(df, bmin, rmin, horizonte)
            base = d.loc[d["horizonte_observavel"], "alvo"].mean()
            try:
                av = avaliar_classificacao(treinar_avaliar(d, embargo=horizonte)["teste"])
                linhas.append({"basileia_min": bmin, "roe_min": rmin,
                               "taxa_base": float(base), "auc_roc": av["auc_roc"], "ks": av["ks"]})
            except Exception:  # noqa: BLE001
                linhas.append({"basileia_min": bmin, "roe_min": rmin,
                               "taxa_base": float(base), "auc_roc": None, "ks": None})
    return pd.DataFrame(linhas)


def importancia_shap(resultado: dict):
    """Importância SHAP (|valor| médio) das variáveis do EWS no conjunto de teste.

    Complementa a importância por impureza (`feature_importances_`). Diferentemente do
    SHAP sobre a zona de risco (que é circular, pois deriva do próprio ICR), aqui o alvo
    é o distress futuro — externo ao índice. Retorna DataFrame ou None se SHAP ausente.
    """
    try:
        import shap
    except Exception as exc:  # noqa: BLE001
        print(f"  [aviso] SHAP indisponível: {exc}")
        return None
    modelo, feats, teste = resultado["modelo"], resultado["features"], resultado["teste"]
    valores = shap.TreeExplainer(modelo).shap_values(teste[feats].to_numpy())
    if isinstance(valores, list):  # versões antigas devolvem lista por classe
        valores = valores[1]
    out = (pd.DataFrame({"feature": feats, "shap_abs_medio": np.abs(valores).mean(0)})
           .sort_values("shap_abs_medio", ascending=False).reset_index(drop=True))
    out["shap_pct"] = 100 * out["shap_abs_medio"] / out["shap_abs_medio"].sum()
    return out


def tunar_hiperparametros(
    d: pd.DataFrame, features: list[str] | None = None,
    fracao_treino: float = 0.7, embargo: int = 4, n_amostras: int = 45,
) -> dict:
    """Compara o GBM com hiperparâmetros PADRÃO vs. AJUSTADOS por busca aleatória, com
    validação temporal INTERNA ao treino (sem tocar no conjunto de teste).

    Justifica empiricamente a escolha dos defaults: se o ajuste não supera o padrão no
    teste out-of-time, os defaults são a escolha parcimoniosa. Retorna dict com AUC/KS.
    """
    import itertools
    import random

    from sklearn.ensemble import GradientBoostingClassifier
    from sklearn.metrics import roc_auc_score, roc_curve

    def _ks(y, p):
        f, t, _ = roc_curve(y, p)
        return float((t - f).max())

    feats = [f for f in (features or FEATURES_PADRAO)
             if f in d.columns and d[f].notna().any()]
    base = d[d["horizonte_observavel"]].dropna(subset=feats + ["alvo"]).copy()
    qs = np.sort(base["qidx"].unique())
    corte = qs[min(int(len(qs) * fracao_treino), len(qs) - 1)]
    treino, teste = split_temporal(base, corte, embargo=embargo)
    Xtr, ytr = treino[feats].to_numpy(), treino["alvo"].to_numpy()
    Xte, yte = teste[feats].to_numpy(), teste["alvo"].to_numpy()

    m0 = GradientBoostingClassifier(random_state=42).fit(Xtr, ytr)
    p0 = m0.predict_proba(Xte)[:, 1]

    # validação temporal DENTRO do treino (para não ajustar no teste)
    qtr = np.sort(treino["qidx"].unique())
    corte_v = qtr[int(len(qtr) * 0.8)]
    tr_in, val = split_temporal(treino, corte_v, embargo=embargo)
    grid = {"n_estimators": [50, 100, 200, 300], "learning_rate": [0.02, 0.05, 0.1, 0.2],
            "max_depth": [2, 3, 4, 5], "subsample": [0.7, 0.85, 1.0],
            "min_samples_leaf": [1, 5, 20, 50]}
    random.seed(0)
    amostra = random.sample(list(itertools.product(*grid.values())), n_amostras)
    best = None
    for combo in amostra:
        cfg = dict(zip(grid.keys(), combo))
        mm = GradientBoostingClassifier(random_state=42, **cfg).fit(
            tr_in[feats].to_numpy(), tr_in["alvo"].to_numpy())
        a = roc_auc_score(val["alvo"], mm.predict_proba(val[feats].to_numpy())[:, 1]) \
            if val["alvo"].sum() else 0.0
        if best is None or a > best[0]:
            best = (a, cfg)
    mt = GradientBoostingClassifier(random_state=42, **best[1]).fit(Xtr, ytr)
    pt = mt.predict_proba(Xte)[:, 1]
    return {
        "default": {"auc": float(roc_auc_score(yte, p0)), "ks": _ks(yte, p0)},
        "tuned": {"cfg": best[1], "auc_val": float(best[0]),
                  "auc": float(roc_auc_score(yte, pt)), "ks": _ks(yte, pt)},
    }
