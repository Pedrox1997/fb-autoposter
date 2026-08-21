"""Fontes de video: rclone (OneDrive e afins) e Google Drive."""
from .base import Item, caption_for  # noqa: F401  (reexport p/ o main)
from .composta import FonteComposta
from .gdrive import GoogleDriveSource
from .rclone import RcloneSource


def _uma(referencia, order):
    ref = str(referencia).strip()
    if ":" in ref and not ref.startswith("/") and not ref.lower().startswith("http"):
        return RcloneSource(ref, order=order)
    return GoogleDriveSource(ref, order=order)


def get(page):
    """Uma pasta, ou varias em fila quando a etiqueta lista mais de uma."""
    refs = page.source_refs or [page.source_ref]
    if len(refs) == 1:
        if page.source_type in ("rclone", "onedrive"):
            return RcloneSource(refs[0], order=page.order)
        return GoogleDriveSource(refs[0], order=page.order)
    return FonteComposta([_uma(r, page.order) for r in refs])
