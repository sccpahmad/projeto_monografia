"""
ICR 2.0 — indicadores sob o plano de contas do IFRS 9 (Resolução CMN nº 4.966),
vigente no IF.Data a partir de 2025.

A reforma reestruturou os relatórios de Ativo e de Resultado, mas, ao introduzir
o modelo de PERDA ESPERADA, passou a divulgar o custo de risco de crédito — o que
permite cobrir a dimensão 'A' (Asset quality) do CAMELS, ausente no índice de
2016–2024. Este módulo constrói os oito indicadores do CAMELS completo (C, A, M,
E, L) sob o novo plano de contas, para a visão de Instituição Individual (tipo 3).

Decisões de mapeamento (novo plano de contas):
- Liquidez  = (Disponibilidades + Aplic. Interfin. + TVM + Derivativos) / Ativo.
- Eficiência = (Desp. Pessoal + Desp. Administrativas) / RECEITA BRUTA
              (pré-provisão), para não sobrepor o efeito das provisões — que é
              medido separadamente pelo custo de risco.
- Custo de risco (A) = |Resultado com Perda Esperada de Op. de Crédito| / Ativo,
              anualizado pelo fator semestral.
"""
from __future__ import annotations

import numpy as np
import pandas as pd


def _col(frame: pd.DataFrame, nome: str) -> pd.Series:
    if nome in frame.columns:
        return pd.to_numeric(frame[nome], errors="coerce")
    return pd.Series(np.nan, index=frame.index)


def _div(num, den) -> pd.Series:
    num = pd.to_numeric(num, errors="coerce")
    den = pd.to_numeric(den, errors="coerce")
    return num / den.where(den != 0, np.nan)


def _fator_anual(ano_mes: int) -> float:
    """Anualização semestral (o resultado do IF.Data acumula por semestre)."""
    mes = ano_mes % 100
    return 12.0 / (((mes - 1) % 6) + 1)


def construir_indicadores_ifrs9(
    rel1: pd.DataFrame, rel2: pd.DataFrame, rel4: pd.DataFrame
) -> pd.DataFrame:
    """Constrói os indicadores do ICR 2.0 (exceto Basileia/Imobilização, que vêm
    do portal via `portal.anexar_basileia`)."""
    per = int(pd.to_numeric(rel1["AnoMes"], errors="coerce").iloc[0])
    fa = _fator_anual(per)
    ll = _col(rel1, "Lucro Líquido") * fa
    ativo = _col(rel1, "Ativo Total")

    o = pd.DataFrame({"AnoMes": rel1["AnoMes"], "CodInst": rel1["CodInst"]})
    o["alavancagem"] = _div(_col(rel1, "Ativo Total"), _col(rel1, "Patrimônio Líquido"))
    o["roa"] = _div(ll, ativo) * 100
    o["roe"] = _div(ll, _col(rel1, "Patrimônio Líquido")) * 100
    o["ativo_total_mil"] = ativo

    # --- L: Liquidez (relatório 2, plano de contas novo) -------------------
    liq = (
        _col(rel2, "Disponibilidades").fillna(0)
        + _col(rel2, "Aplicações Interfinanceiras de Liquidez").fillna(0)
        + _col(rel2, "Títulos e Valores Mobiliários").fillna(0)
        + _col(rel2, "Instrumentos Derivativos (d)").fillna(0)
    )
    l2 = rel2[["AnoMes", "CodInst"]].copy()
    l2["liquidez"] = _div(liq, _col(rel2, "Ativo Total")) * 100

    # --- M: Eficiência (receita bruta) + A: Custo de risco (relatório 4) ---
    desp = _col(rel4, "Despesas de Pessoal").abs().fillna(0) + _col(
        rel4, "Despesas Administrativas"
    ).abs().fillna(0)
    receita_bruta = (
        _col(rel4, "Rendas de Operações de Crédito").fillna(0)
        + _col(rel4, "Rendas de Títulos e Valores Mobiliários").fillna(0)
        + _col(rel4, "Rendas de Aplicações Interfinanceiras de Liquidez").fillna(0)
        + _col(rel4, "Rendas de Tarifas Bancárias").fillna(0)
        + _col(rel4, "Outras Rendas de Prestação de Serviços").fillna(0)
        + _col(rel4, "Resultado com Serviços por Transações de Pagamento").fillna(0)
    )
    perda = _col(rel4, "Resultado com Perda Esperada de Operações de Crédito").abs() * fa
    d4 = rel4[["AnoMes", "CodInst"]].copy()
    d4["eficiencia"] = _div(desp, receita_bruta.where(receita_bruta > 0, np.nan)) * 100
    # Numerador (perda esperada) vem do rel4; o denominador (Ativo Total) prefere o
    # rel4, mas cai para o Ativo do rel1 (sempre populado) quando a coluna do rel4
    # está ausente/nula — assim custo_risco fica robusto a mudanças de plano de
    # contas e consistente com roa/roe/alavancagem e com custo_de_risco().
    d4["_perda_esperada"] = perda
    d4["_ativo_rel4"] = _col(rel4, "Ativo Total")

    out = o.merge(l2, on=["AnoMes", "CodInst"], how="left").merge(
        d4, on=["AnoMes", "CodInst"], how="left"
    )
    ativo_den = out["_ativo_rel4"].where(out["_ativo_rel4"].notna(), out["ativo_total_mil"])
    out["custo_risco"] = _div(out["_perda_esperada"], ativo_den) * 100
    return out.drop(columns=["_perda_esperada", "_ativo_rel4"])


def custo_de_risco(rel1: pd.DataFrame, rel4: pd.DataFrame) -> pd.DataFrame:
    """Custo de risco isolado (|perda esperada| anualizada / ativo, %) — usado na
    validação da capacidade preditiva do índice de 2024 sobre 2025."""
    per = int(pd.to_numeric(rel1["AnoMes"], errors="coerce").iloc[0])
    fa = _fator_anual(per)
    perda = _col(rel4, "Resultado com Perda Esperada de Operações de Crédito").abs() * fa
    d = rel4[["CodInst"]].assign(_pe=perda.values)
    d = rel1[["CodInst"]].assign(_ativo=_col(rel1, "Ativo Total").values).merge(
        d, on="CodInst", how="left"
    )
    d["custo_risco"] = _div(d["_pe"], d["_ativo"]) * 100
    return d[["CodInst", "custo_risco"]]
