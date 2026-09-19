"""
Cliente do IF.Data (Olinda / OData) do Banco Central.

Endpoint base:
  https://olinda.bcb.gov.br/olinda/servico/IFDATA/versao/v1/odata/

Funções (descobertas via $metadata):
  ListaDeRelatorio()                          -> lista de relatórios
  IfDataValores(AnoMes, TipoInstituicao, Relatorio) -> valores (formato longo)
  IfDataCadastro(AnoMes)                      -> cadastro das instituições

ATENÇÃO (achados empíricos, jun/2026):
  * 'Relatorio' deve ser o NÚMERO do relatório como string (ex.: '1' = Resumo),
    e não o nome. Passar o nome retorna 200 com 0 linhas.
  * 'TipoInstituicao' aceita 1, 2 ou 3.
  * IfDataCadastro está retornando HTTP 500 no servidor do BCB justamente nos
    trimestres com dados. Por isso o cliente tenta o cadastro mas degrada com
    elegância (segue sem os nomes, usando o CodInst como rótulo).
"""
from __future__ import annotations

import pandas as pd

from .http import criar_sessao, get_json

BASE = "https://olinda.bcb.gov.br/olinda/servico/IFDATA/versao/v1/odata"

# Relatórios mais úteis para o ICR (número -> nome)
RELATORIOS = {
    1: "Resumo",
    2: "Ativo",
    3: "Passivo",
    4: "Demonstração de Resultado",
    5: "Informações de Capital",
}


def listar_relatorios(sessao=None) -> pd.DataFrame:
    sessao = sessao or criar_sessao()
    url = f"{BASE}/ListaDeRelatorio()?$format=json"
    dados = get_json(sessao, url)
    return pd.DataFrame(dados.get("value", []))


def baixar_valores(
    ano_mes: int,
    tipo_instituicao: int,
    relatorio: int,
    sessao=None,
) -> pd.DataFrame:
    """Baixa um relatório do IF.Data em formato longo.

    Saída: uma linha por (CodInst, NomeColuna), com a coluna 'Saldo'.
    """
    sessao = sessao or criar_sessao()
    url = (
        f"{BASE}/IfDataValores(AnoMes=@AnoMes,TipoInstituicao=@TipoInstituicao,"
        f"Relatorio=@Relatorio)?@AnoMes={ano_mes}"
        f"&@TipoInstituicao={tipo_instituicao}&@Relatorio='{relatorio}'"
        f"&$format=json"
    )
    dados = get_json(sessao, url)
    df = pd.DataFrame(dados.get("value", []))
    if not df.empty:
        df["Saldo"] = pd.to_numeric(df["Saldo"], errors="coerce")
    return df


def baixar_cadastro(ano_mes: int, sessao=None) -> pd.DataFrame:
    """Tenta baixar o cadastro (nomes/UF/segmento). Pode falhar (bug 500 BCB).

    Retorna DataFrame vazio em caso de falha, sem interromper o pipeline.
    """
    sessao = sessao or criar_sessao()
    url = f"{BASE}/IfDataCadastro(AnoMes=@AnoMes)?@AnoMes={ano_mes}&$format=json"
    try:
        dados = get_json(sessao, url, tentativas=2)
        return pd.DataFrame(dados.get("value", []))
    except Exception as exc:  # noqa: BLE001
        print(f"  [aviso] IfDataCadastro({ano_mes}) indisponível ({exc}).")
        return pd.DataFrame()


def limpar_coluna(nome: str) -> str:
    """Normaliza o nome da coluna do IF.Data.

    Nos relatórios 2 (Ativo) e 4 (DRE), o `NomeColuna` vem com a fórmula
    contábil após uma quebra de linha, p.ex. 'Disponibilidades \\n(a)'.
    Aqui ficamos só com o rótulo legível ('Disponibilidades').
    """
    return str(nome).split("\n")[0].strip()


def relatorio_largo(df_valores: pd.DataFrame) -> pd.DataFrame:
    """Pivota qualquer relatório (long -> wide): uma linha por instituição.

    Funciona para o Resumo (rel. 1) e também para Ativo (2) e DRE (4),
    limpando os nomes de coluna que trazem a fórmula contábil.
    """
    if df_valores.empty:
        return pd.DataFrame()
    df = df_valores.copy()
    df["NomeColuna"] = df["NomeColuna"].map(limpar_coluna)
    largo = df.pivot_table(
        index=["AnoMes", "CodInst"],
        columns="NomeColuna",
        values="Saldo",
        aggfunc="first",
    ).reset_index()
    largo.columns.name = None
    # AnoMes vem como texto da API; normaliza p/ int (uniformiza com o SGS e
    # evita armadilha de merge por tipo em consumidores diretos do parquet cru).
    largo["AnoMes"] = pd.to_numeric(largo["AnoMes"], errors="coerce").astype(int)
    return largo


# Alias mantido por compatibilidade.
resumo_largo = relatorio_largo
