"""
Resolução dos nomes das instituições (CodInst -> Nome).

Como o endpoint oficial `IfDataCadastro` (Olinda) está retornando HTTP 500,
este módulo usa o backend de arquivos do portal IF.Data, que foi
engenharia-reversa a partir do próprio site:

  Índice de arquivos:
    https://www3.bcb.gov.br/ifdata/rest/relatorios            (2000–2024)
    https://www3.bcb.gov.br/ifdata/rest/relatorios2025a2030   (2025+)
  Conteúdo de um arquivo:
    https://www3.bcb.gov.br/ifdata/rest/arquivos?nomeArquivo=<caminho>

Cada período tem arquivos `cadastro<periodo>_<tipo>.json` (tipos 1005, 1006,
1009) cujos registros trazem: c0=código, c2=nome, c5=segmento, c7=controle.
O código `c0` corresponde ao `CodInst` da API Olinda sem zeros à esquerda.

Como os nomes são estáveis no tempo, buscamos o cadastro do período mais
recente que estiver disponível e aplicamos a todos os trimestres do estudo.
"""
from __future__ import annotations

import pandas as pd

from .http import criar_sessao

IDX_ANTIGO = "https://www3.bcb.gov.br/ifdata/rest/relatorios"
IDX_NOVO = "https://www3.bcb.gov.br/ifdata/rest/relatorios2025a2030"
ARQUIVO = "https://www3.bcb.gov.br/ifdata/rest/arquivos?nomeArquivo={}"
HEADERS = {"Content-Type": "application/json; charset=utf-8"}


def _indice(sessao) -> list[dict]:
    """Lista de períodos e arquivos, do mais novo para o mais antigo."""
    itens = []
    for url in (IDX_NOVO, IDX_ANTIGO):
        try:
            r = sessao.get(url, timeout=60, headers=HEADERS)
            r.raise_for_status()
            itens.extend(r.json())
        except Exception:  # noqa: BLE001
            continue
    return sorted(itens, key=lambda e: e.get("dt", 0), reverse=True)


def _baixar_cadastros_periodo(sessao, entrada: dict) -> pd.DataFrame:
    """Baixa e une os cadastros (tipos 1005/1006/1009) de um período."""
    registros = {}
    for f in entrada.get("files", []):
        caminho = f.get("f", "")
        if "cadastro" not in caminho:
            continue
        try:
            r = sessao.get(ARQUIVO.format(caminho), timeout=90, headers=HEADERS)
            r.raise_for_status()
            dados = r.json()
        except Exception:  # noqa: BLE001
            continue
        if not isinstance(dados, list):
            continue
        for reg in dados:
            cod = str(reg.get("c0", "")).zfill(8)
            registros[cod] = {
                "CodInst": cod,
                "nome": reg.get("c2"),
                "segmento": reg.get("c5"),
                "controle": reg.get("c7"),
            }
    return pd.DataFrame(registros.values())


def baixar_nomes(sessao=None, max_periodos: int = 8) -> pd.DataFrame:
    """Tabela CodInst -> nome a partir do cadastro mais recente disponível.

    Tenta os períodos do mais novo para o mais antigo até obter um cadastro
    não-vazio (contorna instabilidades pontuais do servidor do BCB).
    """
    sessao = sessao or criar_sessao()
    indice = _indice(sessao)
    for entrada in indice[:max_periodos]:
        df = _baixar_cadastros_periodo(sessao, entrada)
        if not df.empty:
            print(f"  Nomes obtidos do cadastro {entrada.get('dt')}: {len(df)} instituições")
            df["fonte_cadastro"] = entrada.get("dt")
            return df
    print("  [aviso] não foi possível obter nomes (portal indisponível).")
    return pd.DataFrame(columns=["CodInst", "nome", "segmento", "controle"])
