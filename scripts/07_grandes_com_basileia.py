"""
ETAPA 7 (extra) — "Grandes bancos COM Basileia" (snapshot recente).

Combina duas fontes para superar a limitação da API Olinda:
  - Olinda tipo=3 (individual): balanço, resultado, liquidez, eficiência dos
    grandes bancos (Ativo correto).
  - Portal IF.Data (visão prudencial): Índice de Basileia/Imobilização,
    anexado por nome.

Resultado: ICR com CAMELS COMPLETO (incluindo Basileia) para os grandes bancos,
nos trimestres recentes disponíveis no portal (era 2025+).

Uso:
  python scripts/07_grandes_com_basileia.py
"""
from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

import pandas as pd  # noqa: E402

from icr import ifdata, indicadores as ind, portal, score  # noqa: E402
from icr.config import (  # noqa: E402
    DIR_PROCESSED,
    DIR_RAW,
    carregar_config,
    garantir_diretorios,
)
from icr.http import criar_sessao  # noqa: E402


def main() -> None:
    garantir_diretorios()
    cfg = carregar_config()
    sessao = criar_sessao()

    # 1) Basileia/Imobilização (portal, prudencial) — define os períodos
    print("Portal IF.Data — índices de capital (prudencial):")
    cap = portal.baixar_indices_capital(sessao=sessao)
    if cap.empty:
        raise SystemExit("Portal indisponível; não foi possível obter Basileia.")
    periodos = sorted(cap["AnoMes"].unique())
    print(f"Períodos com Basileia: {periodos}")

    # 2) Olinda tipo=3 (individual) para os mesmos períodos
    print("\nOlinda tipo=3 (individual) — balanço/resultado:")
    rels = {}
    for rel in (1, 2, 4):
        partes = []
        for per in periodos:
            try:
                v = ifdata.baixar_valores(per, 3, rel, sessao=sessao)
                if not v.empty:
                    partes.append(ifdata.relatorio_largo(v))
            except Exception as exc:  # noqa: BLE001
                print(f"  rel {rel} {per}: ERRO ({exc})")
        rels[rel] = pd.concat(partes, ignore_index=True) if partes else pd.DataFrame()
        print(f"  rel {rel}: {0 if rels[rel].empty else len(rels[rel])} linhas")

    if rels[1].empty:
        raise SystemExit("Sem dados do Olinda para os períodos do portal.")

    # 3) Indicadores (CAMELS sem Basileia) + nomes
    df = ind.construir_indicadores(rels[1], rels[2], rels[4])
    nomes = pd.read_parquet(DIR_RAW / "nomes_instituicoes.parquet") if (
        DIR_RAW / "nomes_instituicoes.parquet").exists() else pd.DataFrame()
    if not nomes.empty:
        df = df.merge(nomes[["CodInst", "nome"]], on="CodInst", how="left")
    df["nome"] = df.get("nome").fillna(df["CodInst"])

    # 4) Anexa Basileia do portal (crosswalk p/ grandes bancos) e filtra
    df = portal.anexar_basileia(df, cap, cfg.get("crosswalk_prudencial"))
    df = df[(df["ativo_total_mil"].fillna(0) >= cfg["filtro_instituicoes"]["ativo_total_minimo_mil"])
            & (df["basileia"].notna())].reset_index(drop=True)
    print(f"\nGrandes bancos com CAMELS completo (Basileia anexada): "
          f"{df['CodInst'].nunique()} instituições x {df['AnoMes'].nunique()} trim.")

    # 5) ICR — nos trimestres de 2025+ há quebra contábil na DRE (Res. CMN 4.966,
    #    perda esperada/IFRS 9): a Eficiência deixa de ser comparável. Este
    #    snapshot recente usa, portanto, apenas indicadores estáveis
    #    (Basileia, Alavancagem, ROA, ROE, Liquidez), sem Eficiência.
    df = df.drop(columns=["eficiencia"], errors="ignore")
    df_padr = score.padronizar(df, cfg["indicadores"], cfg["padronizacao"])
    orient = cfg.get("orientacao", "solidez")
    df_icr = score.calcular_icr(df_padr, cfg["indicadores"], orient)
    df_icr = score.classificar_risco(df_icr, cfg["zona_risco"]["percentil"], orient)
    df_icr.to_parquet(DIR_PROCESSED / "grandes_com_basileia.parquet", index=False)

    ultimo = int(df_icr["AnoMes"].max())
    rank = df_icr[df_icr["AnoMes"] == ultimo].sort_values("ICR", ascending=False)
    cols = [c for c in ["nome", "ICR", "faixa", "basileia", "alavancagem", "roa",
                        "roe", "liquidez", "eficiencia", "ativo_total_mil"] if c in rank.columns]
    rank[cols].to_csv(DIR_PROCESSED / f"grandes_com_basileia_{ultimo}.csv",
                      index=False, encoding="utf-8-sig")
    pd.set_option("display.width", 170, "display.max_columns", 25)
    # Foco nos bancos do crosswalk (sistemicamente relevantes)
    cw = {str(k).zfill(8) for k in cfg.get("crosswalk_prudencial", {})}
    grandes = rank[rank["CodInst"].isin(cw)].sort_values("ICR", ascending=False)
    print(f"\n== Grandes bancos — ICR com CAMELS COMPLETO, incl. Basileia ({ultimo}) ==")
    print(grandes[cols].to_string(index=False))
    print(f"\n-> data/processed/grandes_com_basileia_{ultimo}.csv "
          f"({df['CodInst'].nunique()} instituições no total)")


if __name__ == "__main__":
    main()
