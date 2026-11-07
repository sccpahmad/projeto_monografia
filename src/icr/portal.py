"""
Fonte complementar: arquivos do portal IF.Data (rest/arquivos).

Por que existe: a API Olinda não traz a Basileia dos grandes bancos (ver README
3.1). O portal, porém, publica os índices de capital da visão PRUDENCIAL —
incluindo os conglomerados dos grandes bancos — em arquivos JSON estáticos.

Limitação conhecida: o endpoint de arquivos serve bem a era 2025+ (poucos
trimestres); períodos antigos retornam 'Erro interno' no servidor do BCB. Por
isso este módulo é usado como ENRIQUECIMENTO recente (anexa Basileia/Imobilização
aos grandes bancos do painel sistêmico), não como série histórica.

Formato (engenharia reversa):
  rest/relatorios2025a2030      -> índice de períodos/arquivos (era 2025+)
  cadastro<per>_1009.json       -> instituições da visão prudencial: c0=código, c2=nome
  dados<per>_1.json             -> report 1 com índices de capital por entidade:
                                   entidade {'e': código, 'v': [{'i': campo, 'v': valor}]}
                                   campo 79664 = Índice de Basileia (fração)
                                   campo 79662 = Índice de Imobilização (fração)
"""
from __future__ import annotations

import unicodedata

import pandas as pd

from .http import criar_sessao

IDX_NOVO = "https://www3.bcb.gov.br/ifdata/rest/relatorios2025a2030"
ARQ = "https://www3.bcb.gov.br/ifdata/rest/arquivos?nomeArquivo={}"
HEADERS = {"Content-Type": "application/json; charset=utf-8"}
CAMPO_BASILEIA = 79664
CAMPO_IMOB = 79662

# tokens (formas societárias) removidos ao normalizar nomes para o cruzamento.
# NÃO removemos conectivos/marcas (BRASIL, DO...) para não colidir nomes.
_LIXO = {"BANCO", "BCO", "PRUDENCIAL", "FINANCEIRO", "SA", "LTDA",
         "MULTIPLO", "CONGLOMERADO"}


def normalizar_nome(nome: str) -> str:
    s = unicodedata.normalize("NFKD", str(nome)).encode("ascii", "ignore").decode()
    s = s.upper()
    s = "".join(ch if ch.isalnum() else " " for ch in s)  # remove pontuação
    toks = [t for t in s.split() if t not in _LIXO]
    return " ".join(toks)


def _periodos_disponiveis(sessao) -> list[dict]:
    r = sessao.get(IDX_NOVO, timeout=60, headers=HEADERS)
    r.raise_for_status()
    return sorted(r.json(), key=lambda e: e.get("dt", 0), reverse=True)


def baixar_indices_capital(sessao=None, max_periodos: int = 8) -> pd.DataFrame:
    """Basileia/Imobilização da visão prudencial, por período disponível.

    Retorna [AnoMes, CodInstPrud, nome, nome_norm, basileia, imobilizacao].
    """
    sessao = sessao or criar_sessao()
    try:
        indice = _periodos_disponiveis(sessao)
    except Exception as exc:  # noqa: BLE001
        print(f"  [aviso] índice do portal indisponível ({exc}).")
        return pd.DataFrame()

    linhas = []
    for entrada in indice[:max_periodos]:
        per = entrada.get("dt")
        files = {Path_basename(f["f"]): f["f"] for f in entrada.get("files", [])}
        # nome exato do arquivo (âncora na extensão evita casar dados{per}_10.json etc.)
        cad_f = next((v for k, v in files.items() if k == f"cadastro{per}_1009.json"), None)
        dados_f = next((v for k, v in files.items() if k == f"dados{per}_1.json"), None)
        if not cad_f or not dados_f:
            continue
        try:
            cad = sessao.get(ARQ.format(cad_f), timeout=120, headers=HEADERS).json()
            dados = sessao.get(ARQ.format(dados_f), timeout=120, headers=HEADERS).json()
        except Exception as exc:  # noqa: BLE001
            print(f"  [aviso] {per}: arquivos indisponíveis ({exc}).")
            continue
        nomes = {str(c["c0"]): c["c2"] for c in cad}
        ents = dados.get("values", []) if isinstance(dados, dict) else []
        for e in ents:
            cod = str(e["e"])
            if cod not in nomes:
                continue
            fv = {p["i"]: p["v"] for p in e["v"]}
            bas = fv.get(CAMPO_BASILEIA)
            if not bas:
                continue
            linhas.append({
                "AnoMes": per, "CodInstPrud": cod, "nome": nomes[cod],
                "nome_norm": normalizar_nome(nomes[cod]),
                "basileia": bas * 100,
                "imobilizacao": (fv.get(CAMPO_IMOB) or 0) * 100,
            })
        print(f"  portal {per}: {sum(1 for x in linhas if x['AnoMes']==per)} instituições com Basileia")
    return pd.DataFrame(linhas)


def anexar_basileia(
    df_sistemico: pd.DataFrame,
    cap: pd.DataFrame,
    crosswalk: dict | None = None,
) -> pd.DataFrame:
    """Anexa Basileia/Imobilização (portal) ao painel sistêmico.

    Cruzamento por nome normalizado e trimestre. Para os grandes bancos, cujo
    nome difere entre as fontes (ex.: 'ITAÚ UNIBANCO S.A.' x 'ITAU - PRUDENCIAL'),
    usa-se um `crosswalk` {CodInst: nome_prudencial}. Onde o portal não tem o
    período, casa pelo mais recente disponível (nomes são estáveis).
    """
    if cap.empty:
        df = df_sistemico.copy()
        df["basileia"] = pd.NA
        return df
    d = df_sistemico.drop(
        columns=[c for c in ("basileia", "imobilizacao") if c in df_sistemico.columns]
    ).copy()
    d["nome_norm"] = d["nome"].map(normalizar_nome)
    if crosswalk:
        mapa = {str(k).zfill(8): normalizar_nome(v) for k, v in crosswalk.items()}
        cod = d["CodInst"].astype(str)
        d.loc[cod.isin(mapa), "nome_norm"] = cod.map(mapa)

    # 1) match exato por (AnoMes, nome) — Basileia do próprio trimestre
    cap_q = cap[["AnoMes", "nome_norm", "basileia", "imobilizacao"]]
    out = d.merge(cap_q, on=["AnoMes", "nome_norm"], how="left")

    # 2) fallback: nome -> Basileia mais recente disponível
    cap_recente = (cap.sort_values("AnoMes")
                   .groupby("nome_norm")[["basileia", "imobilizacao"]].last())
    for col in ("basileia", "imobilizacao"):
        falta = out[col].isna()
        out.loc[falta, col] = out.loc[falta, "nome_norm"].map(cap_recente[col])
    return out


def Path_basename(p: str) -> str:
    return p.replace("\\", "/").split("/")[-1]
