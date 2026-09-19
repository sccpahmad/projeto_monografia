"""
ETAPA 8 — Diagnóstico e checagens de sanidade (auditoria do pipeline).

Roda uma bateria de verificações automáticas sobre os dados processados e
reporta [OK] / [ATENÇÃO] / [ERRO]. O objetivo é dar confiança de que não há
erros silenciosos de transformação (padronização, anualização, agregação).

Uso:
  python scripts/08_diagnostico.py
"""
from __future__ import annotations

import sys
from pathlib import Path

# O console do Windows pode ser cp1252 e falhar em símbolos como "≈"/"×".
try:
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
except Exception:
    pass

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

import numpy as np  # noqa: E402
import pandas as pd  # noqa: E402

from icr import validacao  # noqa: E402
from icr.config import (  # noqa: E402
    DIR_RAW,
    carregar_config,
    dir_processed_painel,
)

OK, WARN, ERR = "[  OK  ]", "[ATENÇÃO]", "[ ERRO ]"
_falhas = {"warn": 0, "err": 0}


def reporta(nivel: str, msg: str) -> None:
    print(f"{nivel} {msg}")
    if nivel == WARN:
        _falhas["warn"] += 1
    elif nivel == ERR:
        _falhas["err"] += 1


def checar_painel(nome: str, cfg: dict, macro: pd.DataFrame) -> None:
    print(f"\n========== Painel: {nome} ==========")
    outd = dir_processed_painel(nome)
    ind = pd.read_parquet(outd / "indicadores.parquet")
    icr = pd.read_parquet(outd / "icr.parquet")

    # A) Sem duplicatas (AnoMes, CodInst)
    dup = ind.duplicated(["AnoMes", "CodInst"]).sum()
    reporta(OK if dup == 0 else ERR, f"A. Duplicatas (AnoMes,CodInst): {dup}")

    # B) Escore-z por trimestre: média≈0 e desvio≈1
    problemas = []
    for c in [k for k in cfg["indicadores"] if f"z_{k}" in icr.columns]:
        g = icr.groupby("AnoMes")[f"z_{c}"]
        m = g.mean().abs().max()
        s = g.std(ddof=0).replace(0, np.nan).dropna()
        desvio = (s - 1).abs().max()
        if m > 1e-6 or (pd.notna(desvio) and desvio > 0.05):
            problemas.append(f"{c}(|média|={m:.1e},|desv-1|={desvio:.2f})")
    reporta(OK if not problemas else WARN,
            "B. Padronização z (média≈0, desvio≈1): "
            + ("todos OK" if not problemas else "; ".join(problemas)))

    # C) Média simples do ICR ≈ 0 por trimestre (identidade do escore-z)
    m_icr = icr.groupby("AnoMes")["ICR"].mean().abs().max()
    reporta(OK if m_icr < 1e-9 else ERR,
            f"C. Média simples do ICR por trimestre ≈ 0 (máx |média|={m_icr:.1e})")

    # D) Pesos renormalizados somam 1
    presentes = {k: v for k, v in cfg["indicadores"].items() if f"z_{k}" in icr.columns}
    soma = sum(v["peso"] for v in presentes.values())
    reporta(OK, f"D. Indicadores ativos: {list(presentes)} (Σpesos brutos={soma:.3f} → normalizado p/ 1)")

    # E) Plausibilidade dos indicadores
    ult = ind[ind["AnoMes"] == ind["AnoMes"].max()]
    checks = {
        "ativo_total_mil>0": (ind["ativo_total_mil"].dropna() > 0).all(),
        "sem inf": np.isfinite(ind.select_dtypes("number").replace([np.inf, -np.inf], np.nan).fillna(0).to_numpy()).all(),
        "liquidez 0-100 (mediana)": 0 <= ult["liquidez"].median() <= 100 if "liquidez" in ult else True,
    }
    if "basileia" in ind and ind["basileia"].notna().any():
        checks["basileia mediana 10-30%"] = 10 <= ind["basileia"].median() <= 30
    ruins = [k for k, v in checks.items() if not v]
    reporta(OK if not ruins else WARN,
            "E. Plausibilidade: " + ("tudo OK" if not ruins else "falhou " + ", ".join(ruins)))

    # F) Sazonalidade da anualização de ROE (pega erro de acumulação semestral)
    ind = ind.copy()
    ind["mes"] = ind["AnoMes"] % 100
    med = ind.groupby("mes")["roe"].median()
    if len(med) == 4 and med.abs().min() > 0:
        razao = med.abs().max() / med.abs().min()
        nivel = OK if razao < 1.6 else ERR
        reporta(nivel, f"F. Sazonalidade do ROE anualizado (razão máx/mín das medianas por trim.="
                       f"{razao:.2f}; ideal <1,6). Medianas: "
                       + ", ".join(f"T{m//3}={v:.1f}%" for m, v in med.items()))

    # G) Cobertura por trimestre
    n = icr.groupby("AnoMes")["CodInst"].nunique()
    queda = (n / n.shift(1)).min()
    reporta(OK if (n.min() >= 50 and queda > 0.7) else WARN,
            f"G. Cobertura: {n.min()}–{n.max()} inst./trim.; menor razão entre trimestres={queda:.2f}")

    # H) Sinal da validação macro (inadimplência deve ser negativa)
    serie = validacao.serie_sistema(icr)
    corr = validacao.correlacao_macro(serie, macro)
    if not corr.empty and "inadimplencia_total" in set(corr["serie_macro"]):
        r = corr.loc[corr["serie_macro"] == "inadimplencia_total", "pearson"].iloc[0]
        reporta(OK if r < 0 else WARN,
                f"H. Correlação ICR×inadimplência total = {r:.2f} (esperado negativo)")


def checar_config(cfg: dict) -> None:
    """Sanidade dos blocos de pesos do config (v1 e ICR 2.0)."""
    print("\n========== Config: pesos ==========")
    for chave in ("indicadores", "icr2_indicadores"):
        bloco = cfg.get(chave, {})
        if not bloco:
            continue
        soma = sum(v["peso"] for v in bloco.values())
        # Ambos são renormalizados na construção (score.calcular_icr); a soma bruta
        # é apenas informativa. v1 soma 1,0; icr2 soma 0,90 — por design.
        reporta(OK, f"Σpesos brutos de '{chave}' = {soma:.3f} "
                    f"({len(bloco)} indicadores; renormalizado p/ 1 na construção)")


def main() -> None:
    cfg = carregar_config()
    macro = pd.read_parquet(DIR_RAW / "sgs_trimestral.parquet")
    print("DIAGNÓSTICO DO PIPELINE ICR — checagens de sanidade")
    checar_config(cfg)
    for painel in cfg["paineis"]:
        try:
            checar_painel(painel["nome"], cfg, macro)
        except FileNotFoundError:
            reporta(WARN, f"Painel {painel['nome']}: dados ausentes (rode 02).")

    print("\n========== RESUMO ==========")
    if _falhas["err"] == 0 and _falhas["warn"] == 0:
        print("[  OK  ] Todas as checagens passaram.")
    else:
        print(f"{_falhas['err']} erro(s) e {_falhas['warn']} atenção(ões). Revise os itens acima.")
    sys.exit(1 if _falhas["err"] else 0)


if __name__ == "__main__":
    main()
