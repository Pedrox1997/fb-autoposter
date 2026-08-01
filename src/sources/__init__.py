"""Fontes de video: rclone (OneDrive e afins) e Google Drive."""
from .base import Item, caption_for  # noqa: F401  (reexport p/ o main)
from .gdrive import GoogleDriveSource
from .rclone import RcloneSource


def get(page):
    if page.source_type in ("rclone", "onedrive"):
        return RcloneSource(page.source_ref, order=page.order)
    return GoogleDriveSource(page.source_ref, order=page.order)
