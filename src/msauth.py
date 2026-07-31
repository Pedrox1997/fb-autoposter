"""Autenticacao Microsoft (OAuth 2.0) para acessar o OneDrive via Graph.

O acesso anonimo a links de compartilhamento foi cortado pela Microsoft em
contas migradas para o SharePoint Online, entao o robo usa um app registrado:
um refresh token de longa duracao vira access token a cada execucao.
"""
import os
import time

import requests

SCOPES = "offline_access Files.Read.All User.Read"
TIMEOUT = 60


def _authority(tenant=None):
    tenant = tenant or os.environ.get("ONEDRIVE_TENANT", "consumers")
    return f"https://login.microsoftonline.com/{tenant}/oauth2/v2.0"


def refresh_access_token(client_id, refresh_token, tenant=None):
    """Troca o refresh token por um access token valido (~1h).

    Devolve (access_token, refresh_token). A Microsoft costuma devolver um
    refresh token NOVO a cada troca - quem chama deve persistir o novo, senao
    o acesso morre quando o original completar 90 dias.
    """
    data = {
        "client_id": client_id,
        "grant_type": "refresh_token",
        "refresh_token": refresh_token,
        "scope": SCOPES,
    }
    r = requests.post(f"{_authority(tenant)}/token", data=data, timeout=TIMEOUT)
    if r.status_code >= 400:
        raise RuntimeError(
            f"Microsoft recusou o refresh token [{r.status_code}]: {r.text[:300]}\n"
            "Refaca o login com: python -m tools.onedrive_login"
        )
    payload = r.json()
    return payload["access_token"], payload.get("refresh_token", refresh_token)


def device_code_login(client_id, tenant=None, on_prompt=print):
    """Login interativo unico, sem redirect URI nem client secret.

    Mostra um codigo, o usuario autoriza no navegador, e devolve o refresh
    token que sera guardado como secret.
    """
    start = requests.post(
        f"{_authority(tenant)}/devicecode",
        data={"client_id": client_id, "scope": SCOPES},
        timeout=TIMEOUT,
    )
    if start.status_code >= 400:
        raise RuntimeError(f"Falha ao iniciar login [{start.status_code}]: {start.text[:300]}")
    flow = start.json()

    on_prompt(flow.get("message") or
              f"Acesse {flow['verification_uri']} e digite o codigo {flow['user_code']}")

    intervalo = int(flow.get("interval", 5))
    limite = time.time() + int(flow.get("expires_in", 900))

    while time.time() < limite:
        time.sleep(intervalo)
        r = requests.post(
            f"{_authority(tenant)}/token",
            data={
                "client_id": client_id,
                "grant_type": "urn:ietf:params:oauth:grant-type:device_code",
                "device_code": flow["device_code"],
            },
            timeout=TIMEOUT,
        )
        if r.status_code < 400:
            return r.json()

        erro = r.json().get("error", "")
        if erro == "authorization_pending":
            continue
        if erro == "slow_down":
            intervalo += 5
            continue
        raise RuntimeError(f"Login falhou: {erro} - {r.json().get('error_description', '')[:200]}")

    raise RuntimeError("Tempo esgotado esperando a autorizacao no navegador.")
