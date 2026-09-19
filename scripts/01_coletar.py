"""
ETAPA 1 — Coleta de dados (IF.Data por painel + nomes + SGS).

Uso:
  python scripts/01_coletar.py

Gera:
  data/raw/<painel>/ifdata_rel{1,2,4}.parquet   (um conjunto por painel)
  data/raw/nomes_instituicoes.parquet           (compartilhado)
  data/raw/sgs_longo.parquet / sgs_trimestral.parquet (compartilhado)
"""
from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

import pandas as pd  # noqa: E402

from icr import ifdata, nomes, sgs  # noqa: E402
from icr.config import (  # noqa: E402
    DIR_RAW,
    carregar_config,
    dir_raw_painel,
    garantir_diretorios,
)
from icr.http import criar_sessao  # noqa: E402


def gerar_periodos(cfg_coleta: dict) -> list[int]:
    if cfg_coleta.get("periodos"):
        return list(cfg_coleta["periodos"])
    auto = cfg_coleta["periodos_auto"]
    ini, fim = int(auto["inicio"]), int(auto["fim"])
    periodos, ano, mes = [], ini // 100, ini % 100
    while ano * 100 + mes <= fim:
        periodos.append(ano * 100 + mes)
        mes += 3
        if mes > 12:
            ano, mes = ano + 1, 3
    return periodos


def coletar_painel(painel: dict, periodos: list[int], relatorios: list[int], sessao) -> None:
    nome, tipo = painel["nome"], painel["tipo"]
    destino = dir_raw_painel(nome)
    print(f"\n=== Painel '{nome}' (tipo={tipo}) ===")
    for rel in relatorios:
        partes = []
        for ano_mes in periodos:
            try:
                v = ifdata.baixar_valores(ano_mes, tipo, relatorio=rel, sessao=sessao)
            except Exception as exc:  # noqa: BLE001
                print(f"  rel {rel} {ano_mes}: ERRO ({exc})")
                continue
            if not v.empty:
                partes.append(ifdata.relatorio_largo(v))
        if partes:
            df = pd.concat(partes, ignore_index=True)
            df.to_parquet(destino / f"ifdata_rel{rel}.parquet", index=False)
            print(f"  -> {nome}/ifdata_rel{rel}.parquet "
                  f"({df.shape[0]} linhas, {df['AnoMes'].nunique()} trim.)")


def main() -> None:
    garantir_diretorios()
    cfg = carregar_config()
    sessao = criar_sessao()

    periodos = gerar_periodos(cfg["coleta"])
    relatorios = cfg["coleta"].get("relatorios", [1, 2, 4])
    print(f"IF.Data | {len(periodos)} trimestres ({periodos[0]}–{periodos[-1]}) "
          f"| relatórios={relatorios} | painéis={[p['nome'] for p in cfg['paineis']]}")

    for painel in cfg["paineis"]:
        coletar_painel(painel, periodos, relatorios, sessao)

    # --- Nomes (compartilhado) --------------------------------------------
    print("\n=== Nomes das instituições (portal IF.Data) ===")
    df_nomes = nomes.baixar_nomes(sessao=sessao)
    if not df_nomes.empty:
        df_nomes.to_parquet(DIR_RAW / "nomes_instituicoes.parquet", index=False)
        print(f"-> nomes_instituicoes.parquet ({len(df_nomes)} instituições)")

    # --- SGS (compartilhado) ----------------------------------------------
    print("\n=== SGS — séries macroeconômicas ===")
    longo = sgs.baixar_varias(
        cfg["sgs_series"],
        cfg["coleta"]["sgs_data_inicial"],
        cfg["coleta"]["sgs_data_final"],
        sessao=sessao,
    )
    longo.to_parquet(DIR_RAW / "sgs_longo.parquet", index=False)
    sgs.trimestralizar(longo, como="last").to_parquet(
        DIR_RAW / "sgs_trimestral.parquet", index=False
    )
    print(f"-> sgs_longo.parquet ({len(longo)} obs) + sgs_trimestral.parquet")
    print("\nColeta concluída.")


if __name__ == "__main__":
    main()
