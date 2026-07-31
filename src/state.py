"""Controle do que ja foi postado. Vive em state/posted.json e volta commitado
ao repo no fim de cada execucao - e o que garante que nada seja postado duas vezes."""
import json
import os

from .config import ROOT

STATE_PATH = os.path.join(ROOT, "state", "posted.json")


def load():
    if not os.path.exists(STATE_PATH):
        return {"pages": {}}
    with open(STATE_PATH, "r", encoding="utf-8") as f:
        try:
            data = json.load(f)
        except json.JSONDecodeError:
            print("  ! state/posted.json ilegivel - comecando do zero")
            data = {}
    data.setdefault("pages", {})
    return data


def save(data):
    os.makedirs(os.path.dirname(STATE_PATH), exist_ok=True)
    tmp = STATE_PATH + ".tmp"
    with open(tmp, "w", encoding="utf-8") as f:
        json.dump(data, f, indent=2, ensure_ascii=False, sort_keys=True)
    os.replace(tmp, STATE_PATH)


def _page(data, slug):
    p = data["pages"].setdefault(slug, {})
    p.setdefault("used_files", [])
    p.setdefault("rejected", {})
    p.setdefault("slots", {})
    return p


def used_file_ids(data, slug):
    return set(_page(data, slug)["used_files"])


def rejected_ids(data, slug):
    return set(_page(data, slug)["rejected"])


def reset_used(data, slug):
    _page(data, slug)["used_files"] = []


def slot_taken(data, slug, slot_key):
    return slot_key in _page(data, slug)["slots"]


def record(data, slug, slot_key, file_id, file_name, post_id, when_iso):
    p = _page(data, slug)
    if file_id not in p["used_files"]:
        p["used_files"].append(file_id)
    p["slots"][slot_key] = {
        "file_id": file_id,
        "file": file_name,
        "post_id": post_id,
        "scheduled_for": when_iso,
    }


def mark_rejected(data, slug, file_id, file_name, reasons):
    _page(data, slug)["rejected"][file_id] = {"file": file_name, "reasons": reasons}


def prune_slots(data, slug, keep=500):
    """Impede o arquivo de crescer para sempre."""
    p = _page(data, slug)
    excess = len(p["slots"]) - keep
    if excess > 0:
        for key in sorted(p["slots"])[:excess]:
            del p["slots"][key]
