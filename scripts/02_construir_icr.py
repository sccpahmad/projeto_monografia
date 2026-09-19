"""
ETAPA 2/3 — Indicadores CAMELS e ICR, para cada painel.

Uso:
  python scripts/02_construir_icr.py

Para cada painel lê data/raw/<painel>/ifdata_rel{1,2,4}.parquet e gera:
  data/processed/<painel>/indicadores.parquet
  data/processed/<painel>/icr.parquet
  data/processed/<painel>/ranking_<ultimo>.csv
"""
from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

import pandas as pd  # noqa: E402

from icr import indicadores as ind  # noqa: E402
from icr import score  # noqa: E402
from icr.config import (  # noqa: E402
    DIR_RAW,
    carregar_config,
    dir_processed_painel,
    dir_raw_painel,
    garantir_diretorios,
)


def _ler(caminho: Path) -> pd.DataFrame:
    return pd.read_parquet(caminho) if caminho.exists() else pd.DataFrame()


def construir_painel(painel: dict, cfg: dict, nomes: pd.DataFrame) -> None:
    nome = painel["nome"]
    rawd = dir_raw_painel(nome)
    outd = dir_processed_painel(nome)
    print(f"\n=== Painel '{nome}' ===")

    rel1 = _ler(rawd / "ifdata_rel1.parquet")
    if rel1.empty:
        print("  (sem dados; rode 01_coletar.py)")
        return
    rel2 = _ler(rawd / "ifdata_rel2.parquet")
    rel4 = _ler(rawd / "ifdata_rel4.parquet")

    df_ind = ind.construir_indicadores(rel1, rel2, rel4)
    df_ind = ind.aplicar_filtro(
        df_ind,
        cfg["filtro_instituicoes"]["ativo_total_minimo_mil"],
        cfg["filtro_instituicoes"]["exigir_basileia"],
    )
    if not nomes.empty:
        df_ind = df_ind.merge(
            nomes[["CodInst", "nome", "segmento", "controle"]], on="CodInst", how="left"
        )
    if "nome" not in df_ind.columns:
        df_ind["nome"] = None
    df_ind["nome"] = df_ind["nome"].fillna(df_ind["CodInst"])
    df_ind.to_parquet(outd / "indicadores.parquet", index=False)

    df_padr = score.padronizar(df_ind, cfg["indicadores"], cfg["padronizacao"])
    orient = cfg.get("orientacao", "solidez")
    df_icr = score.calcular_icr(df_padr, cfg["indicadores"], orient)
    df_icr = score.classificar_risco(df_icr, cfg["zona_risco"]["percentil"], orient)
    df_icr.to_parquet(outd / "icr.parquet", index=False)

    ultimo = int(df_icr["AnoMes"].max())
    # Remove rankings de execuções anteriores (janelas diferentes) para que
    # data/processed reflita exatamente a janela da config atual.
    for _antigo in outd.glob("ranking_*.csv"):
        _antigo.unlink()
    rank = df_icr[df_icr["AnoMes"] == ultimo].sort_values("ICR", ascending=False)
    cols = [c for c in [
        "nome", "ICR", "ICR_percentil", "faixa", "zona_risco", "basileia",
        "alavancagem", "roa", "roe", "imobilizacao", "liquidez", "eficiencia",
        "ativo_total_mil", "CodInst",
    ] if c in rank.columns]
    rank[cols].to_csv(outd / f"ranking_{ultimo}.csv", index=False, encoding="utf-8-sig")
    print(f"  -> icr.parquet ({len(df_icr)} linhas) + ranking_{ultimo}.csv")

    prev = [c for c in ["nome", "ICR", "faixa", "basileia", "roe", "liquidez",
                        "eficiencia", "ativo_total_mil"] if c in rank.columns]
    grandes = rank.sort_values("ativo_total_mil", ascending=False).head(8)
    pd.set_option("display.width", 170, "display.max_columns", 25)
    print(f"  Top por ativo ({ultimo}):")
    print(grandes[prev].to_string(index=False))


def main() -> None:
    garantir_diretorios()
    cfg = carregar_config()
    nomes = _ler(DIR_RAW / "nomes_instituicoes.parquet")
    for painel in cfg["paineis"]:
        construir_painel(painel, cfg, nomes)


if __name__ == "__main__":
    main()
