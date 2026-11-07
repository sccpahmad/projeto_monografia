"""
ETAPA extra — Exporta o ranking de risco do trimestre mais recente.

Uso:
  python scripts/05_exportar_relatorio.py

Gera:
  data/processed/ranking_ICR.html   (interativo, ordenável — abre no navegador)
  data/processed/ranking_ICR.xlsx   (se openpyxl instalado)
"""
from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

import pandas as pd  # noqa: E402

from icr import relatorio  # noqa: E402
from icr.config import (  # noqa: E402
    DIR_PROCESSED,
    carregar_config,
    dir_processed_painel,
    garantir_diretorios,
)


def main() -> None:
    garantir_diretorios()
    cfg = carregar_config()

    rankings, ultimo = {}, None
    for painel in cfg["paineis"]:
        p = dir_processed_painel(painel["nome"]) / "icr.parquet"
        if not p.exists():
            continue
        df = pd.read_parquet(p)
        ultimo = int(df["AnoMes"].max())
        rankings[painel["nome"]] = relatorio.preparar_ranking(df, ultimo)

    if not rankings:
        raise SystemExit("Nenhum painel com icr.parquet — rode 02_construir_icr.py.")

    html = DIR_PROCESSED / "ranking_ICR.html"
    relatorio.exportar_html(rankings, html, ultimo)
    print(f"-> {html}")

    xlsx = DIR_PROCESSED / "ranking_ICR.xlsx"
    if relatorio.exportar_excel(rankings, xlsx):
        print(f"-> {xlsx}")


if __name__ == "__main__":
    main()
