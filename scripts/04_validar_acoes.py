"""
ETAPA 5 (extra) — Validação do ICR com ações da B3.

Uso:
  python scripts/04_validar_acoes.py

Usa o painel 'sistemico' (instituições individuais, onde estão os grandes
bancos listados). Gera:
  data/raw/acoes_cotacoes.parquet
  data/processed/validacao_acoes.csv
  figuras/icr_vs_acao_<ticker>.png
"""
from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

import matplotlib  # noqa: E402

matplotlib.use("Agg")
import matplotlib.pyplot as plt  # noqa: E402
import pandas as pd  # noqa: E402

from icr import acoes  # noqa: E402
from icr.config import (  # noqa: E402
    DIR_FIGURAS,
    DIR_PROCESSED,
    DIR_RAW,
    carregar_config,
    dir_processed_painel,
    garantir_diretorios,
)


def _rotulo(anomes: int) -> str:
    return f"{anomes // 100}T{(anomes % 100) // 3}"


def main() -> None:
    garantir_diretorios()
    cfg = carregar_config()
    cfg_ac = cfg["acoes"]

    icr_path = dir_processed_painel("sistemico") / "icr.parquet"
    if not icr_path.exists():
        raise SystemExit("Painel 'sistemico' não construído — rode 02_construir_icr.py.")
    df_icr = pd.read_parquet(icr_path)

    print("Baixando cotações (Yahoo Finance)...")
    cot = acoes.baixar_cotacoes(
        cfg_ac["tickers"], cfg_ac["sufixo_yahoo"], cfg_ac["range"], cfg_ac["intervalo"]
    )
    if cot.empty:
        raise SystemExit("Nenhuma cotação obtida.")
    cot.to_parquet(DIR_RAW / "acoes_cotacoes.parquet", index=False)
    trim = acoes.trimestralizar(cot)

    corr = acoes.correlacionar(df_icr, trim)
    corr.to_csv(DIR_PROCESSED / "validacao_acoes.csv", index=False)
    print("\n== Correlação ICR x Ação (por banco listado) ==")
    print(corr.to_string(index=False) if not corr.empty else "(sem dados suficientes)")

    # Gráficos ICR x preço por banco
    nomes = {v: k for k, v in [(t, str(c).zfill(8)) for t, c in cfg_ac["tickers"].items()]}
    base = trim.merge(df_icr[["AnoMes", "CodInst", "ICR"]], on=["AnoMes", "CodInst"], how="inner")
    for ticker, g in base.groupby("ticker"):
        g = g.sort_values("AnoMes").dropna(subset=["ICR", "close"])
        if len(g) < 5:
            continue
        x = [_rotulo(a) for a in g["AnoMes"]]
        fig, ax1 = plt.subplots(figsize=(9, 4.5))
        ax1.plot(x, g["ICR"], "o-", color="tab:blue")
        ax1.set_ylabel("ICR do banco", color="tab:blue"); ax1.set_xlabel("Trimestre")
        ax1.tick_params(axis="x", rotation=90)
        ax2 = ax1.twinx()
        ax2.plot(x, g["close"], "s-", color="tab:green")
        ax2.set_ylabel(f"{ticker} (R$)", color="tab:green")
        ax1.set_title(f"ICR x preço da ação — {ticker}")
        fig.tight_layout(); fig.savefig(DIR_FIGURAS / f"icr_vs_acao_{ticker}.png", dpi=130)
        plt.close(fig)
    print(f"\nFiguras -> {DIR_FIGURAS}")


if __name__ == "__main__":
    main()
