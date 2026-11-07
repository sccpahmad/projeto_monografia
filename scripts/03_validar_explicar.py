"""
ETAPA 4/5 — Validação (temporal + macro) e Explicabilidade, por painel,
mais uma comparação entre painéis.

Uso:
  python scripts/03_validar_explicar.py
"""
from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

import matplotlib  # noqa: E402

matplotlib.use("Agg")
import matplotlib.pyplot as plt  # noqa: E402
import pandas as pd  # noqa: E402

from icr import explicabilidade as expl  # noqa: E402
from icr import validacao  # noqa: E402
from icr.config import (  # noqa: E402
    DIR_FIGURAS,
    DIR_RAW,
    carregar_config,
    dir_figuras_painel,
    dir_processed_painel,
    garantir_diretorios,
)


def _rotulo(anomes: int) -> str:
    return f"{anomes // 100}T{(anomes % 100) // 3}"


def validar_painel(painel: dict, cfg: dict, macro: pd.DataFrame) -> pd.DataFrame:
    nome = painel["nome"]
    outd = dir_processed_painel(nome)
    figd = dir_figuras_painel(nome)
    icr_path = outd / "icr.parquet"
    if not icr_path.exists():
        print(f"[{nome}] sem icr.parquet; pulando.")
        return pd.DataFrame()
    df_icr = pd.read_parquet(icr_path)
    print(f"\n=== Painel '{nome}' ===")

    serie = validacao.serie_sistema(df_icr, ponderar_por_ativo=True)
    serie.to_csv(outd / "serie_sistema.csv", index=False)

    corr = validacao.correlacao_macro(serie, macro)
    corr.to_csv(outd / "correlacao_macro.csv", index=False)
    print("Correlação ICR x SGS (top |pearson|):")
    print(corr.reindex(corr["pearson"].abs().sort_values(ascending=False).index)
          .head(5).to_string(index=False) if not corr.empty else "(vazio)")

    imp = expl.importancia_por_contribuicao(df_icr, cfg["indicadores"])
    imp.to_csv(outd / "importancia_indicadores.csv", index=False)
    _, shap_resumo = expl.shap_zona_risco(df_icr, cfg["indicadores"])
    if shap_resumo is not None:
        shap_resumo.to_csv(outd / "shap_zona_risco.csv", index=False)

    _plot_temporal(serie, figd, nome)
    _plot_icr_vs_macro(serie, macro, figd, nome)
    _plot_importancia(imp, figd)
    print(f"Figuras -> {figd}")
    return serie.assign(painel=nome)


def _plot_temporal(serie, figd, nome):
    if serie.empty:
        return
    x = [_rotulo(a) for a in serie["AnoMes"]]
    fig, ax = plt.subplots(figsize=(9, 4.5))
    ax.plot(x, serie["ICR_medio_ponderado"], marker="o", label="ICR (pond. por ativo)")
    ax.plot(x, serie["ICR_mediana"], "--s", label="ICR (mediana)")
    ax.axhline(0, color="grey", lw=0.8)
    ax.set_title(f"Evolução do ICR do sistema — painel {nome}")
    ax.set_xlabel("Trimestre"); ax.set_ylabel("ICR (maior = mais sólido)")
    ax.tick_params(axis="x", rotation=90); ax.legend()
    fig.tight_layout(); fig.savefig(figd / "icr_temporal.png", dpi=130); plt.close(fig)


def _plot_icr_vs_macro(serie, macro, figd, nome):
    if "inadimplencia_total" not in macro.columns:
        return
    base = serie.merge(macro, on="AnoMes", how="inner").dropna(
        subset=["ICR_medio_ponderado", "inadimplencia_total"])
    if base.empty:
        return
    x = [_rotulo(a) for a in base["AnoMes"]]
    fig, ax1 = plt.subplots(figsize=(9, 4.5))
    ax1.plot(x, base["ICR_medio_ponderado"], "o-", color="tab:blue")
    ax1.set_ylabel("ICR do sistema", color="tab:blue"); ax1.set_xlabel("Trimestre")
    ax1.tick_params(axis="x", rotation=90)
    ax2 = ax1.twinx()
    ax2.plot(x, base["inadimplencia_total"], "s-", color="tab:red")
    ax2.set_ylabel("Inadimplência total (%)", color="tab:red")
    ax1.set_title(f"ICR x Inadimplência (SGS 21082) — painel {nome}")
    fig.tight_layout(); fig.savefig(figd / "icr_vs_inadimplencia.png", dpi=130); plt.close(fig)


def _plot_importancia(imp, figd):
    imp = imp[imp["importancia_pct"] > 0]
    if imp.empty:
        return
    fig, ax = plt.subplots(figsize=(7, 4))
    ax.barh(imp["indicador"], imp["importancia_pct"], color="tab:purple")
    ax.invert_yaxis(); ax.set_xlabel("Importância (% do |contribuição| total)")
    ax.set_title("Indicadores que mais movem o ICR")
    fig.tight_layout(); fig.savefig(figd / "importancia_indicadores.png", dpi=130); plt.close(fig)


def _plot_comparacao(series_paineis):
    series = [s for s in series_paineis if not s.empty]
    if len(series) < 2:
        return
    fig, ax = plt.subplots(figsize=(9, 4.5))
    for s in series:
        x = [_rotulo(a) for a in s["AnoMes"]]
        ax.plot(x, s["ICR_medio_ponderado"], marker="o", label=s["painel"].iloc[0])
    ax.axhline(0, color="grey", lw=0.8)
    ax.set_title("Comparação do ICR do sistema entre painéis")
    ax.set_xlabel("Trimestre"); ax.set_ylabel("ICR (pond. ativo)")
    ax.tick_params(axis="x", rotation=90); ax.legend()
    fig.tight_layout(); fig.savefig(DIR_FIGURAS / "comparacao_paineis.png", dpi=130); plt.close(fig)
    print(f"\nComparação -> {DIR_FIGURAS / 'comparacao_paineis.png'}")


def main() -> None:
    garantir_diretorios()
    cfg = carregar_config()
    macro = pd.read_parquet(DIR_RAW / "sgs_trimestral.parquet")
    series = [validar_painel(p, cfg, macro) for p in cfg["paineis"]]
    _plot_comparacao(series)


if __name__ == "__main__":
    main()
