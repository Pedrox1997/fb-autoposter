"""Leitura do config.yaml + resolucao dos segredos vindos do ambiente."""
import json
import os
import sys
from dataclasses import dataclass, field
from datetime import datetime, time as dtime, timedelta
from zoneinfo import ZoneInfo

import yaml

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))


@dataclass
class Page:
    name: str
    page_id: str
    token: str
    source_type: str
    source_ref: str
    tz: ZoneInfo = None          # fuso proprio da pagina (fallback: o global)
    post_type: str = "reel"
    times: list = field(default_factory=list)
    default_caption: str = ""
    hashtags: str = ""
    order: str = "name"

    @property
    def slug(self):
        return "".join(c if c.isalnum() else "-" for c in self.name.lower()).strip("-")


@dataclass
class Config:
    tz: ZoneInfo
    mode: str
    horizon_hours: int
    tolerance_minutes: int
    recycle: bool
    validate_media: bool
    pages: list


def _env(name, page_name):
    val = os.environ.get(name, "").strip()
    if not val:
        print(f"  ! Secret ausente: {name} (pagina '{page_name}')")
    return val


def _detect_source(kind, ref):
    """rclone quando o valor tem a forma 'remote:caminho'; senao, Google Drive."""
    if kind and kind != "auto":
        return kind
    low = ref.lower()
    if low.startswith("http"):
        if "drive.google" in low or "docs.google" in low:
            return "gdrive"
        return "rclone"
    if ":" in ref and not ref.startswith("/"):
        return "rclone"
    return "gdrive"


def _bootstrap_secrets():
    """O workflow injeta todas as GitHub Secrets em ALL_SECRETS. Assim, adicionar
    uma pagina nova exige mexer so no config.yaml, nunca no YAML do workflow."""
    blob = os.environ.pop("ALL_SECRETS", "").strip()
    if not blob:
        return
    try:
        data = json.loads(blob)
    except json.JSONDecodeError:
        print("  ! ALL_SECRETS ilegivel - usando apenas variaveis de ambiente")
        return
    for key, value in data.items():
        if isinstance(value, str) and not os.environ.get(key):
            os.environ[key] = value


def load(path=None):
    _bootstrap_secrets()
    path = path or os.path.join(ROOT, "config.yaml")
    with open(path, "r", encoding="utf-8") as f:
        raw = yaml.safe_load(f)

    tz = ZoneInfo(raw.get("timezone", "America/Sao_Paulo"))
    pages = []

    for p in raw.get("pages", []):
        name = p["name"]
        page_id = _env(p["page_id_env"], name)
        token = _env(p["token_env"], name)

        src = p.get("source", {}) or {}
        ref = _env(src.get("env", ""), name) if src.get("env") else ""

        if not (page_id and token and ref):
            print(f"  ! Pagina '{name}' incompleta -> ignorada")
            continue

        times = sorted({_parse_time(t) for t in p.get("times", [])})
        if not times:
            print(f"  ! Pagina '{name}' sem horarios -> ignorada")
            continue

        try:
            page_tz = ZoneInfo(p["timezone"]) if p.get("timezone") else tz
        except Exception:
            print(f"  ! fuso '{p.get('timezone')}' invalido em '{name}' -> usando o global")
            page_tz = tz

        pages.append(
            Page(
                name=name,
                page_id=page_id,
                token=token,
                source_type=_detect_source(src.get("type", "auto"), ref),
                source_ref=ref,
                tz=page_tz,
                post_type=p.get("post_type", "reel").lower(),
                times=times,
                default_caption=(p.get("default_caption") or "").strip(),
                hashtags=(p.get("hashtags") or "").strip(),
                order=p.get("order", "name"),
            )
        )

    if not pages:
        print("\nERRO: nenhuma pagina utilizavel. Confira os GitHub Secrets.")
        sys.exit(1)

    return Config(
        tz=tz,
        mode=raw.get("mode", "schedule").lower(),
        horizon_hours=int(raw.get("schedule_horizon_hours", 30)),
        tolerance_minutes=int(raw.get("now_tolerance_minutes", 45)),
        recycle=bool(raw.get("recycle_when_empty", False)),
        validate_media=bool(raw.get("validate_media", True)),
        pages=pages,
    )


def _parse_time(value):
    """Aceita '09:00', '9:00' e o time que o YAML converteu sozinho."""
    if isinstance(value, dtime):
        return value.replace(second=0, microsecond=0)
    h, _, m = str(value).strip().partition(":")
    return dtime(int(h), int(m or 0))


def upcoming_slots(page, now, horizon_hours):
    """Horarios da pagina entre agora e o horizonte, no fuso DELA.

    Os horarios do config sao sempre lidos no fuso da propria pagina - uma
    página dos EUA às 19:00 significa 19:00 em Nova York, não em Brasília.
    """
    local_now = now.astimezone(page.tz)
    limit = local_now + timedelta(hours=horizon_hours)
    slots = []
    for offset in range(0, horizon_hours // 24 + 2):
        day = local_now.date() + timedelta(days=offset)
        for t in page.times:
            dt = datetime.combine(day, t, tzinfo=page.tz)
            if local_now < dt <= limit:
                slots.append(dt)
    return sorted(slots)


def due_slot(page, now, tolerance_minutes):
    """No mode 'now': horario mais recente que venceu dentro da tolerancia."""
    local_now = now.astimezone(page.tz)
    best = None
    for offset in (0, -1):
        day = local_now.date() + timedelta(days=offset)
        for t in page.times:
            dt = datetime.combine(day, t, tzinfo=page.tz)
            elapsed = (local_now - dt).total_seconds() / 60
            if 0 <= elapsed <= tolerance_minutes and (best is None or dt > best):
                best = dt
    return best
