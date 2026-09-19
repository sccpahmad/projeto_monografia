"""Carregamento de configuração e localização de diretórios do projeto."""
from __future__ import annotations

from pathlib import Path

import yaml

# Raiz do projeto = duas pastas acima deste arquivo (src/icr/config.py)
RAIZ = Path(__file__).resolve().parents[2]
DIR_CONFIG = RAIZ / "config"
DIR_DADOS = RAIZ / "data"
DIR_RAW = DIR_DADOS / "raw"
DIR_PROCESSED = DIR_DADOS / "processed"
DIR_FIGURAS = RAIZ / "figuras"


def carregar_config(caminho: str | Path | None = None) -> dict:
    """Lê o YAML de configuração de indicadores."""
    caminho = Path(caminho) if caminho else DIR_CONFIG / "indicadores.yaml"
    with open(caminho, "r", encoding="utf-8") as fh:
        return yaml.safe_load(fh)


def garantir_diretorios() -> None:
    for d in (DIR_RAW, DIR_PROCESSED, DIR_FIGURAS):
        d.mkdir(parents=True, exist_ok=True)


# --- Diretórios por painel (prudencial, sistêmico, ...) ---------------------
def dir_raw_painel(nome: str) -> Path:
    p = DIR_RAW / nome
    p.mkdir(parents=True, exist_ok=True)
    return p


def dir_processed_painel(nome: str) -> Path:
    p = DIR_PROCESSED / nome
    p.mkdir(parents=True, exist_ok=True)
    return p


def dir_figuras_painel(nome: str) -> Path:
    p = DIR_FIGURAS / nome
    p.mkdir(parents=True, exist_ok=True)
    return p
