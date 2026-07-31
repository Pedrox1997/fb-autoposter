"""Diagnostico: valida token, pasta e horarios SEM postar nada.

    python -m tools.check
"""
import sys
from datetime import datetime, timedelta

sys.path.insert(0, __file__.rsplit("tools", 1)[0])

from src import config, facebook, sources, state  # noqa: E402


def main():
    cfg = config.load()
    st = state.load()
    now = datetime.now(cfg.tz)
    print(f"Agora: {now:%d/%m/%Y %H:%M} ({cfg.tz}) | modo={cfg.mode}\n")

    problems = 0

    for page in cfg.pages:
        print(f"=== {page.name}")

        try:
            info = facebook.page_info(page)
            print(f"  [ok] Pagina conectada: {info.get('name')} (id {info.get('id')})")
        except Exception as e:
            print(f"  [ERRO] token/pagina: {e}")
            problems += 1
            continue

        expires = facebook.token_expires_at(page)
        if expires == 0 or expires is None:
            print("  [ok] Token sem data de expiracao")
        else:
            left = datetime.fromtimestamp(expires) - datetime.now()
            flag = "ok" if left.days > 10 else "ATENCAO"
            print(f"  [{flag}] Token expira em {left.days} dia(s) ({datetime.fromtimestamp(expires):%d/%m/%Y})")
            if left.days <= 10:
                problems += 1

        try:
            src = sources.get(page)
            videos = src.list_videos()
            print(f"  [ok] {src.label}: {len(videos)} video(s) encontrado(s)")
            for v in videos[:5]:
                mb = f"{v.size / 1e6:.1f} MB" if v.size else "tamanho ?"
                print(f"        - {v.name} ({mb})")
            if len(videos) > 5:
                print(f"        ... +{len(videos) - 5}")
            if not videos:
                problems += 1
        except Exception as e:
            print(f"  [ERRO] fonte de video: {e}")
            problems += 1
            continue

        used = state.used_file_ids(st, page.slug)
        restantes = len([v for v in videos if v.id not in used])
        print(f"  [info] {len(used)} ja postado(s) | {restantes} na fila")

        slots = [
            s for s in config.upcoming_slots(page, now, cfg.horizon_hours)
            if s >= now + timedelta(minutes=20)
            and not state.slot_taken(st, page.slug, s.isoformat())
        ]
        print(f"  [info] proximos horarios em aberto ({len(slots)}) - fuso {page.tz}:")
        for s in slots[:6]:
            print(f"        {s:%d/%m %H:%M} (no Brasil: {s.astimezone(cfg.tz):%d/%m %H:%M})")

        if restantes < len(slots):
            print(f"  [ATENCAO] videos insuficientes para preencher os horarios")
            problems += 1
        print()

    print("Tudo certo." if not problems else f"{problems} ponto(s) de atencao acima.")
    return 1 if problems else 0


if __name__ == "__main__":
    sys.exit(main())
