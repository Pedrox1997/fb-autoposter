"""OneDrive via Microsoft Graph com app registrado (OAuth).

O acesso anonimo a links de compartilhamento nao funciona em contas migradas
para o SharePoint Online - todas as rotas anonimas devolvem 401. Por isso o
robo autentica com um refresh token de longa duracao.

A pasta pode ser indicada de duas formas:
  - link de compartilhamento (https://1drv.ms/... ou https://onedrive.live.com/...)
  - caminho dentro do seu OneDrive (ex: /Videos/DailyBlessings)
"""
import base64
import os

import requests

from .. import ghsecrets, msauth
from .base import Item, local_path, sort_items

GRAPH = "https://graph.microsoft.com/v1.0"
VIDEO_EXT = (".mp4", ".mov", ".m4v", ".webm", ".avi", ".mkv")
TIMEOUT = 120
_token_cache = {}


def _access_token():
    """Access token valido, renovado a partir do refresh token guardado."""
    if "value" in _token_cache:
        return _token_cache["value"]

    client_id = os.environ.get("ONEDRIVE_CLIENT_ID", "").strip()
    refresh = os.environ.get("ONEDRIVE_REFRESH_TOKEN", "").strip()
    if not (client_id and refresh):
        raise RuntimeError(
            "Faltam os secrets ONEDRIVE_CLIENT_ID e/ou ONEDRIVE_REFRESH_TOKEN. "
            "Gere-os com: python -m tools.onedrive_login"
        )

    token, novo_refresh = msauth.refresh_access_token(client_id, refresh)
    _token_cache["value"] = token

    # A Microsoft entrega um refresh token novo a cada troca. Guardar o novo e
    # o que mantem o acesso vivo alem dos 90 dias do original.
    if novo_refresh and novo_refresh != refresh:
        if ghsecrets.available():
            if ghsecrets.update("ONEDRIVE_REFRESH_TOKEN", novo_refresh):
                print("    refresh token do OneDrive renovado")
        else:
            print("    ! GH_PAT nao configurado: o refresh token nao sera renovado "
                  "automaticamente (reautorize a cada ~90 dias)")

    return token


def _share_id(link):
    """Converte o link de compartilhamento no id que a Graph entende."""
    encoded = base64.urlsafe_b64encode(link.strip().encode("utf-8")).decode("ascii")
    return "u!" + encoded.rstrip("=")


def _get(url, params=None):
    r = requests.get(
        url,
        params=params,
        headers={"Authorization": f"Bearer {_access_token()}"},
        timeout=TIMEOUT,
    )
    if r.status_code == 404:
        raise RuntimeError(
            "OneDrive devolveu 404: confira o link/caminho da pasta em PAGE1_SOURCE."
        )
    if r.status_code in (401, 403):
        raise RuntimeError(
            f"OneDrive negou acesso [{r.status_code}]: {r.text[:200]}\n"
            "A conta que autorizou o app precisa enxergar essa pasta."
        )
    r.raise_for_status()
    return r.json()


class OneDriveSource:
    label = "OneDrive"

    def __init__(self, ref, order="name"):
        self.ref = ref.strip()
        self.order = order
        self._cache = None

    def _base_url(self):
        if self.ref.startswith("http"):
            return f"{GRAPH}/shares/{_share_id(self.ref)}/driveItem"
        caminho = self.ref.strip("/")
        return f"{GRAPH}/me/drive/root:/{caminho}:"

    def _entries(self):
        if self._cache is not None:
            return self._cache

        url = f"{self._base_url()}/children"
        itens, proxima = [], url
        params = {"$top": 200, "$select": "id,name,size,file,folder,fileSystemInfo"}
        while proxima:
            page = _get(proxima, params)
            itens.extend(page.get("value", []))
            proxima = page.get("@odata.nextLink")
            params = None  # o nextLink ja vem completo

        self._cache = itens
        return itens

    def list_videos(self):
        itens = [
            Item(
                id=f["id"],
                name=f["name"],
                size=int(f.get("size") or 0),
                created=(f.get("fileSystemInfo") or {}).get("createdDateTime", ""),
            )
            for f in self._entries()
            if "folder" not in f and f["name"].lower().endswith(VIDEO_EXT)
        ]
        return sort_items(itens, self.order)

    def captions(self):
        legendas = {}
        for f in self._entries():
            if "folder" in f or not f["name"].lower().endswith(".txt"):
                continue
            try:
                legendas[os.path.splitext(f["name"])[0].lower()] = self._read_text(f["id"])
            except Exception as e:
                print(f"    ! falha lendo legenda {f['name']}: {e}")
        return legendas

    def _read_text(self, item_id):
        r = requests.get(
            f"{GRAPH}/me/drive/items/{item_id}/content",
            headers={"Authorization": f"Bearer {_access_token()}"},
            timeout=TIMEOUT,
        )
        r.raise_for_status()
        return r.text.strip()

    def _download_url(self, item):
        """URL de download curta duracao, pedida na hora do uso."""
        if self.ref.startswith("http"):
            url = f"{GRAPH}/shares/{_share_id(self.ref)}/driveItem/children"
            for f in _get(url, {"$select": "id,name,@microsoft.graph.downloadUrl"}).get("value", []):
                if f.get("id") == item.id:
                    return f.get("@microsoft.graph.downloadUrl")
            raise RuntimeError(f"Sem URL de download para {item.name}")

        data = _get(f"{GRAPH}/me/drive/items/{item.id}",
                    {"$select": "id,@microsoft.graph.downloadUrl"})
        url = data.get("@microsoft.graph.downloadUrl")
        if not url:
            raise RuntimeError(f"Sem URL de download para {item.name}")
        return url

    def download(self, item):
        dest = local_path(item)
        if os.path.exists(dest) and os.path.getsize(dest) > 0:
            return dest

        tmp = dest + ".part"
        url = self._download_url(item)

        for tentativa in range(1, 5):
            baixado = os.path.getsize(tmp) if os.path.exists(tmp) else 0
            headers = {"Range": f"bytes={baixado}-"} if baixado else {}
            try:
                with requests.get(url, headers=headers, stream=True, timeout=TIMEOUT) as r:
                    if baixado and r.status_code == 200:  # servidor ignorou o Range
                        baixado = 0
                    r.raise_for_status()
                    with open(tmp, "ab" if baixado else "wb") as f:
                        for chunk in r.iter_content(chunk_size=4 * 1024 * 1024):
                            if chunk:
                                f.write(chunk)
                break
            except requests.RequestException as e:
                if tentativa == 4:
                    raise
                print(f"    ! download falhou ({e}); retomando ({tentativa + 1}/4)")
                url = self._download_url(item)  # a URL expira rapido

        os.replace(tmp, dest)
        return dest
