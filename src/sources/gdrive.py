"""Google Drive via Service Account: le a pasta compartilhada, sem login interativo."""
import io
import json
import os
import re

from google.oauth2 import service_account
from googleapiclient.discovery import build
from googleapiclient.http import MediaIoBaseDownload

from .base import Item, local_path, sort_items, ROOT

SCOPES = ["https://www.googleapis.com/auth/drive.readonly"]
_service = None


def _client():
    global _service
    if _service is not None:
        return _service

    raw = os.environ.get("GOOGLE_SERVICE_ACCOUNT_JSON", "").strip()
    if raw:
        info = json.loads(raw)
    else:
        path = os.environ.get(
            "GOOGLE_SERVICE_ACCOUNT_FILE", os.path.join(ROOT, "service-account.json")
        )
        if not os.path.exists(path):
            raise RuntimeError(
                "Credencial do Drive nao encontrada: defina a secret "
                "GOOGLE_SERVICE_ACCOUNT_JSON ou coloque service-account.json na raiz."
            )
        with open(path, "r", encoding="utf-8") as f:
            info = json.load(f)

    creds = service_account.Credentials.from_service_account_info(info, scopes=SCOPES)
    _service = build("drive", "v3", credentials=creds, cache_discovery=False)
    return _service


def folder_id_from(ref):
    """Aceita o ID puro ou qualquer formato de link de pasta do Drive."""
    ref = ref.strip()
    if not ref.startswith("http"):
        return ref
    for pattern in (r"/folders/([A-Za-z0-9_-]+)", r"[?&]id=([A-Za-z0-9_-]+)"):
        m = re.search(pattern, ref)
        if m:
            return m.group(1)
    raise ValueError(f"Nao consegui extrair o ID da pasta do link: {ref}")


class GoogleDriveSource:
    label = "Google Drive"

    def __init__(self, ref, order="name"):
        self.folder_id = folder_id_from(ref)
        self.order = order

    def _list(self, extra_query):
        files, token = [], None
        query = f"'{self.folder_id}' in parents and trashed = false and {extra_query}"
        while True:
            resp = (
                _client()
                .files()
                .list(
                    q=query,
                    fields="nextPageToken, files(id, name, size, mimeType, createdTime)",
                    pageSize=200,
                    supportsAllDrives=True,
                    includeItemsFromAllDrives=True,
                    pageToken=token,
                )
                .execute()
            )
            files.extend(resp.get("files", []))
            token = resp.get("nextPageToken")
            if not token:
                return files

    def list_videos(self):
        items = [
            Item(
                id=f["id"],
                name=f["name"],
                size=int(f.get("size") or 0),
                created=f.get("createdTime", ""),
            )
            for f in self._list("mimeType contains 'video/'")
        ]
        return sort_items(items, self.order)

    def captions(self):
        """{'nome-base-do-video': legenda} a partir dos .txt na mesma pasta."""
        out = {}
        for f in self._list("mimeType = 'text/plain'"):
            base = os.path.splitext(f["name"])[0].lower()
            try:
                data = _client().files().get_media(fileId=f["id"], supportsAllDrives=True).execute()
                out[base] = data.decode("utf-8", errors="replace").strip()
            except Exception as e:  # legenda quebrada nao pode derrubar o post
                print(f"    ! falha lendo legenda {f['name']}: {e}")
        return out

    def download(self, item):
        dest = local_path(item)
        if os.path.exists(dest) and os.path.getsize(dest) > 0:
            return dest

        request = _client().files().get_media(fileId=item.id, supportsAllDrives=True)
        tmp = dest + ".part"
        with io.FileIO(tmp, "wb") as buf:
            downloader = MediaIoBaseDownload(buf, request, chunksize=16 * 1024 * 1024)
            done = False
            while not done:
                status, done = downloader.next_chunk(num_retries=5)
                if status:
                    print(f"    baixando {int(status.progress() * 100)}%")
        os.replace(tmp, dest)
        return dest
