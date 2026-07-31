import hashlib
import os
import re
from dataclasses import dataclass

ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
DOWNLOAD_DIR = os.path.join(ROOT, "downloads")


@dataclass
class Item:
    id: str
    name: str
    size: int = 0
    created: str = ""
    extra: dict = None

    @property
    def base_name(self):
        return os.path.splitext(self.name)[0]


def sort_items(items, order):
    if order == "created":
        return sorted(items, key=lambda i: (i.created, i.name.lower()))
    if order == "random_stable":
        return sorted(items, key=lambda i: hashlib.md5(i.id.encode()).hexdigest())
    return sorted(items, key=lambda i: i.name.lower())


def local_path(item):
    os.makedirs(DOWNLOAD_DIR, exist_ok=True)
    safe = re.sub(r"[^A-Za-z0-9._-]", "_", item.name) or "video.mp4"
    key = hashlib.md5(item.id.encode()).hexdigest()[:10]
    return os.path.join(DOWNLOAD_DIR, f"{key}_{safe}")


def caption_for(item, captions, page):
    text = captions.get(item.base_name.lower(), "").strip()
    if not text:
        text = page.default_caption or item.base_name.replace("_", " ").replace("-", " ").strip()
    if page.hashtags and page.hashtags not in text:
        text = f"{text}\n\n{page.hashtags}"
    return text.strip()[:2200]
