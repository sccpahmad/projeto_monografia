"""
Cliente HTTP robusto para as APIs do Banco Central.

Por que este módulo existe:
- As APIs do BCB (olinda.bcb.gov.br e api.bcb.gov.br) usam HTTPS. Em redes
  corporativas com proxy de inspeção TLS, o Python pode falhar com
  'CERTIFICATE_VERIFY_FAILED' mesmo a conexão sendo válida.
- A solução limpa é usar o repositório de certificados do próprio sistema
  operacional via 'truststore'. Se não estiver instalado, caímos no certifi
  padrão; e, em último caso, é possível desligar a verificação por variável
  de ambiente ICR_VERIFY_SSL=false (NÃO recomendado fora de desenvolvimento).
"""
from __future__ import annotations

import os
import time
import warnings

import requests

_TRUSTSTORE_OK = False
try:  # melhor caminho: confiar no cert store do SO
    import truststore

    truststore.inject_into_ssl()
    _TRUSTSTORE_OK = True
except Exception:  # pragma: no cover - ambiente sem truststore
    pass


def _verificar_ssl() -> bool:
    return os.getenv("ICR_VERIFY_SSL", "true").strip().lower() not in (
        "0",
        "false",
        "no",
        "nao",
        "não",
    )


def criar_sessao() -> requests.Session:
    """Cria uma sessão requests configurada para as APIs do BCB."""
    sessao = requests.Session()
    sessao.headers.update(
        {"User-Agent": "ICR-TCC/0.1 (+pesquisa academica USP eEDB-007)"}
    )
    sessao.verify = _verificar_ssl()
    if not sessao.verify:
        warnings.filterwarnings("ignore", message="Unverified HTTPS request")
        try:
            import urllib3

            urllib3.disable_warnings(urllib3.exceptions.InsecureRequestWarning)
        except Exception:
            pass
    return sessao


def get_json(
    sessao: requests.Session,
    url: str,
    *,
    tentativas: int = 4,
    timeout: int = 90,
    espera: float = 2.0,
):
    """GET com retentativas exponenciais. Retorna o JSON decodificado.

    As APIs do BCB às vezes devolvem 500/timeout intermitente; retentar
    resolve a maioria dos casos.
    """
    ultimo_erro = None
    for i in range(tentativas):
        try:
            resp = sessao.get(url, timeout=timeout)
            resp.raise_for_status()
            return resp.json()
        except Exception as exc:  # noqa: BLE001
            ultimo_erro = exc
            if i < tentativas - 1:
                time.sleep(espera * (i + 1))
    raise RuntimeError(f"Falha ao acessar {url}: {ultimo_erro}")
