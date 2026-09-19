"""
Engenharia dos indicadores prudenciais (CAMELS completo) a partir de três
relatórios do IF.Data:

  Relatório 1 (Resumo) -> Basileia, Imobilização, Ativo, PL, Lucro Líquido
  Relatório 2 (Ativo)  -> componentes líquidos do ativo (Liquidez)
  Relatório 4 (DRE)    -> despesas e receitas (Eficiência)

Dimensões CAMELS cobertas:
  C (Capital)     : Basileia, Alavancagem
  E (Earnings)    : ROA, ROE
  M (Management)  : Imobilização, Eficiência (custo/receita)
  L (Liquidity)   : Ativos líquidos / Ativo total

Observação sobre rentabilidade:
  No IF.Data o resultado (DRE) é ACUMULADO POR SEMESTRE (reinicia em jan e jul,
  conforme o balancete semestral do COSIF). ROA/ROE são anualizados por
  12/(mês dentro do semestre): mar=x4, jun=x2, set=x4, dez=x2. Já a Eficiência
  é razão de dois fluxos do mesmo período, então não precisa de anualização.
"""
from __future__ import annotations

import numpy as np
import pandas as pd


def _num(s):
    return pd.to_numeric(s, errors="coerce")


def _col(frame: pd.DataFrame, nome: str) -> pd.Series:
    """Coluna numérica do frame, ou série de NaN se ela não existir."""
    if nome in frame.columns:
        return pd.to_numeric(frame[nome], errors="coerce")
    return pd.Series(np.nan, index=frame.index)


def _divisao(num, den) -> pd.Series:
    """Divisão segura (evita divisão por zero / valores não numéricos)."""
    num, den = _num(num), _num(den)
    den = den.where(den != 0, np.nan)
    return num / den


def construir_indicadores(
    rel1: pd.DataFrame,
    rel2: pd.DataFrame | None = None,
    rel4: pd.DataFrame | None = None,
) -> pd.DataFrame:
    """Recebe os relatórios (formato largo) e devolve os indicadores do ICR."""
    df = rel1.copy()
    df["AnoMes"] = pd.to_numeric(df["AnoMes"], errors="coerce").astype(int)
    df["CodInst"] = df["CodInst"].astype(str)

    # ATENÇÃO: no IF.Data o resultado (DRE) é acumulado POR SEMESTRE (balancete
    # semestral do COSIF): reinicia em jan e em jul. Portanto o mês relevante
    # para anualizar é o mês DENTRO do semestre (mar=3, jun=6, set=3, dez=6).
    mes = df["AnoMes"] % 100
    mes_no_semestre = ((mes - 1) % 6) + 1
    fator_anual = 12.0 / mes_no_semestre.replace(0, np.nan)

    out = pd.DataFrame()
    out["AnoMes"] = df["AnoMes"]
    out["CodInst"] = df["CodInst"]

    # --- C: Capital ---------------------------------------------------------
    out["basileia"] = _num(df.get("Índice de Basileia")) * 100
    out["alavancagem"] = _divisao(df.get("Ativo Total"), df.get("Patrimônio Líquido"))

    # --- E: Earnings --------------------------------------------------------
    ll_anual = _num(df.get("Lucro Líquido")) * fator_anual
    out["roa"] = _divisao(ll_anual, df.get("Ativo Total")) * 100
    out["roe"] = _divisao(ll_anual, df.get("Patrimônio Líquido")) * 100

    # --- M: Management ------------------------------------------------------
    out["imobilizacao"] = _num(df.get("Índice de Imobilização")) * 100

    # --- Descritivos --------------------------------------------------------
    out["ativo_total_mil"] = _num(df.get("Ativo Total"))
    out["credito_sobre_ativo"] = (
        _divisao(df.get("Carteira de Crédito Classificada"), df.get("Ativo Total")) * 100
    )

    # --- L: Liquidity (relatório 2 - Ativo) --------------------------------
    if rel2 is not None and not rel2.empty:
        a = rel2.copy()
        a["AnoMes"] = pd.to_numeric(a["AnoMes"], errors="coerce").astype(int)
        a["CodInst"] = a["CodInst"].astype(str)
        # TVM: no plano de contas antigo era uma coluna única; a partir de 2025
        # (Res. 4.966) virou 'Títulos e Valores Mobiliários' + 'Instrumentos
        # Derivativos'. Reconhecemos as duas convenções.
        tvm = _col(a, "TVM e Instrumentos Financeiros Derivativos")
        tvm = tvm.fillna(
            _col(a, "Títulos e Valores Mobiliários").fillna(0)
            + _col(a, "Instrumentos Derivativos (d)").fillna(0)
        )
        liquidos = (
            _col(a, "Disponibilidades").fillna(0)
            + _col(a, "Aplicações Interfinanceiras de Liquidez").fillna(0)
            + tvm.fillna(0)
        )
        a["liquidez"] = _divisao(liquidos, _col(a, "Ativo Total")) * 100
        out = out.merge(a[["AnoMes", "CodInst", "liquidez"]], on=["AnoMes", "CodInst"], how="left")

    # --- M: Eficiência (relatório 4 - DRE) ---------------------------------
    if rel4 is not None and not rel4.empty:
        d = rel4.copy()
        d["AnoMes"] = pd.to_numeric(d["AnoMes"], errors="coerce").astype(int)
        d["CodInst"] = d["CodInst"].astype(str)
        despesas = (
            _col(d, "Despesas de Pessoal").abs().fillna(0)
            + _col(d, "Despesas Administrativas").abs().fillna(0)
        )
        receitas = (
            _col(d, "Resultado de Intermediação Financeira").fillna(0)
            + _col(d, "Rendas de Prestação de Serviços").fillna(0)
            + _col(d, "Rendas de Tarifas Bancárias").fillna(0)
        )
        # Razão custo/receita só faz sentido com receita operacional positiva.
        receitas = receitas.where(receitas > 0, np.nan)
        d["eficiencia"] = (despesas / receitas) * 100
        out = out.merge(d[["AnoMes", "CodInst", "eficiencia"]], on=["AnoMes", "CodInst"], how="left")

    return out


def aplicar_filtro(
    df_ind: pd.DataFrame,
    ativo_minimo_mil: float,
    exigir_basileia: bool = True,
) -> pd.DataFrame:
    """Mantém apenas instituições relevantes (porte mínimo / reporta Basileia)."""
    df = df_ind.copy()
    n0 = len(df)
    df = df[df["ativo_total_mil"].fillna(0) >= ativo_minimo_mil]
    tem_basileia = "basileia" in df.columns and df["basileia"].notna().any()
    if exigir_basileia and tem_basileia:
        df = df[df["basileia"].notna()]
    elif exigir_basileia:
        print("  [aviso] Basileia indisponível neste universo (tipo != 1); "
              "filtro de Basileia ignorado. Capital será representado pela alavancagem.")
    print(
        f"  Filtro de instituições: {n0} -> {len(df)} "
        f"(ativo >= R$ {ativo_minimo_mil/1e6:.1f} bi)"
    )
    return df.reset_index(drop=True)
