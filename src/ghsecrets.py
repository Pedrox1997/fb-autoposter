"""Atualiza um GitHub Secret pela API.

Serve para uma coisa so: guardar o refresh token novo que a Microsoft devolve
a cada execucao. Sem isso o acesso ao OneDrive morreria em ~90 dias.
Se o PAT nao estiver configurado, o robo apenas avisa e segue funcionando.
"""
import os
from base64 import b64encode

import requests

API = "https://api.github.com"
TIMEOUT = 60


def available():
    return bool(os.environ.get("GH_PAT") and os.environ.get("GITHUB_REPOSITORY"))


def update(name, value):
    """Grava o valor no secret. Devolve True se conseguiu."""
    pat = os.environ.get("GH_PAT", "").strip()
    repo = os.environ.get("GITHUB_REPOSITORY", "").strip()
    if not (pat and repo):
        return False

    try:
        from nacl import encoding, public
    except ImportError:
        print("    ! PyNaCl ausente - nao consegui girar o refresh token")
        return False

    headers = {
        "Authorization": f"Bearer {pat}",
        "Accept": "application/vnd.github+json",
        "X-GitHub-Api-Version": "2022-11-28",
    }

    try:
        key = requests.get(
            f"{API}/repos/{repo}/actions/secrets/public-key", headers=headers, timeout=TIMEOUT
        )
        key.raise_for_status()
        key = key.json()

        chave = public.PublicKey(key["key"].encode("utf-8"), encoding.Base64Encoder())
        sealed = public.SealedBox(chave).encrypt(value.encode("utf-8"))

        resp = requests.put(
            f"{API}/repos/{repo}/actions/secrets/{name}",
            headers=headers,
            json={"encrypted_value": b64encode(sealed).decode(), "key_id": key["key_id"]},
            timeout=TIMEOUT,
        )
        resp.raise_for_status()
        return True
    except Exception as e:
        print(f"    ! nao consegui atualizar o secret {name}: {e}")
        return False
