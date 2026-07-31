"""Fontes de video: Google Drive (service account) e OneDrive (link publico)."""
from .base import Item, caption_for  # noqa: F401  (reexport p/ o main)
from .gdrive import GoogleDriveSource
from .onedrive import OneDriveSource


def get(page):
    if page.source_type == "onedrive":
        return OneDriveSource(page.source_ref, order=page.order)
    return GoogleDriveSource(page.source_ref, order=page.order)
