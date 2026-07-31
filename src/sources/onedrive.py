"""OneDrive por link de compartilhamento publico (sem app Azure).

Usa a API anonima de 'shares'. Requer que o link esteja como
'Qualquer pessoa com o link' - conta pessoal (onedrive.live.com / 1drv.ms).
Links de OneDrive Business/SharePoint exigem app registrado na Microsoft.
"""
import base64
import os

import requests

from .base import Item, local_path, sort_items

API = "https://api.onedrive.com/v1.0"
VIDEO_EXT = (".mp4", ".mov", ".m4v", ".webm", ".avi", ".mkv")
TIMEOUT = 60


def share_token(link):
    """Converte o link de compartilhamento no token 'u!<base64url>'."""
    encoded = base64.urlsafe_b64encode(link.strip().encode("utf-8")).decode("ascii")
    return "u!" + encoded.rstrip("=")


def _resolve(link):
    """Expande encurtadores (1drv.ms) para o link canonico."""
    if "1drv.ms" not in link:
        return link
    try:
        r = requests.get(link, allow_redirects=True, timeout=TIMEOUT)
        return r.url or link
    except requests.RequestException:
        return link


def _get(url, params=None):
    r = requests.get(url, params=params, timeout=TIMEOUT)
    if r.status_code == 404:
        raise RuntimeError(
            "OneDrive retornou 404. Verifique se o link esta como "
            "'Qualquer pessoa com o link pode ver' e se nao expirou."
        )
    if r.status_code in (401, 403):
        raise RuntimeError(
            "OneDrive negou acesso anonimo (401/403). Links de conta "
            "Business/SharePoint precisam de app registrado na Microsoft."
        )
    r.raise_for_status()
    return r.json()


class OneDriveSource:
    label = "OneDrive"

    def __init__(self, ref, order="name"):
        self.link = _resolve(ref.strip())
        self.token = share_token(self.link)
        self.order = order
        self._cache = None

    def _entries(self):
        """Lista bruta de arquivos do link (pasta inteira ou arquivo unico)."""
        if self._cache is not None:
            return self._cache

        root = _get(f"{API}/shares/{self.token}/root", {"expand": "children"})

        if "folder" not in root:
            self._cache = [root]
            return self._cache

        items = list(root.get("children", []))
        next_link = root.get("children@odata.nextLink")
        while next_link:
            page = _get(next_link)
            items.extend(page.get("value", []))
            next_link = page.get("@odata.nextLink")

        self._cache = items
        return self._cache

    def list_videos(self):
        items = []
        for f in self._entries():
            if "folder" in f:
                continue
            if not f["name"].lower().endswith(VIDEO_EXT):
                continue
            items.append(
                Item(
                    id=f["id"],
                    name=f["name"],
                    size=int(f.get("size") or 0),
                    created=(f.get("fileSystemInfo") or {}).get("createdDateTime", ""),
                    extra={"url": f.get("@content.downloadUrl")},
                )
            )
        return sort_items(items, self.order)

    def captions(self):
        out = {}
        for f in self._entries():
            if "folder" in f or not f["name"].lower().endswith(".txt"):
                continue
            url = f.get("@content.downloadUrl")
            if not url:
                continue
            try:
                r = requests.get(url, timeout=TIMEOUT)
                r.raise_for_status()
                out[os.path.splitext(f["name"])[0].lower()] = r.text.strip()
            except requests.RequestException as e:
                print(f"    ! falha lendo legenda {f['name']}: {e}")
        return out

    def _download_url(self, item):
        url = (item.extra or {}).get("url")
        if url:
            return url
        # downloadUrl expira; se preciso, recarrega a listagem
        self._cache = None
        for f in self._entries():
            if f.get("id") == item.id:
                return f.get("@content.downloadUrl")
        raise RuntimeError(f"Sem URL de download para {item.name}")

    def download(self, item):
        dest = local_path(item)
        if os.path.exists(dest) and os.path.getsize(dest) > 0:
            return dest

        tmp = dest + ".part"
        url = self._download_url(item)

        for attempt in range(1, 5):
            done = os.path.getsize(tmp) if os.path.exists(tmp) else 0
            headers = {"Range": f"bytes={done}-"} if done else {}
            try:
                with requests.get(url, headers=headers, stream=True, timeout=TIMEOUT) as r:
                    if done and r.status_code == 200:  # servidor ignorou o Range
                        done = 0
                    r.raise_for_status()
                    with open(tmp, "wb" if not done else "ab") as f:
                        for chunk in r.iter_content(chunk_size=4 * 1024 * 1024):
                            if chunk:
                                f.write(chunk)
                break
            except requests.RequestException as e:
                if attempt == 4:
                    raise
                print(f"    ! download falhou ({e}); retomando (tentativa {attempt + 1}/4)")
                url = self._download_url(item)

        os.replace(tmp, dest)
        return dest
