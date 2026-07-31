"""Ponto de entrada: le as pastas, casa video x horario e publica/agenda."""
import os
import sys
import traceback
from datetime import datetime, timedelta

from . import config, facebook, media, sources, state
from .sources.base import caption_for

DRY_RUN = os.environ.get("DRY_RUN", "").strip().lower() in ("1", "true", "yes")
MIN_LEAD_MINUTES = 20  # o Facebook exige pelo menos 10 min de antecedencia


def _fmt(dt):
    return dt.strftime("%d/%m %H:%M")


def _next_playable(src, queue, page, cfg, st, problems):
    """Tira da fila o proximo video que realmente pode ir ao ar.

    Video invalido ou que nao baixa nao consome o horario: seguimos para o
    proximo da fila, e o horario so fica vago se a fila inteira acabar.
    """
    while queue:
        item = queue.pop(0)
        try:
            path = src.download(item)
        except Exception as e:
            print(f"     ! download de '{item.name}' falhou: {e}")
            problems.append(f"{page.name}: download de '{item.name}' -> {e}")
            continue

        if cfg.validate_media:
            errors, warnings = media.check(path, page.post_type)
            for w in warnings:
                print(f"     aviso: {w}")
            if errors:
                print(f"     PULADO '{item.name}': {'; '.join(errors)}")
                state.mark_rejected(st, page.slug, item.id, item.name, errors)
                problems.append(f"{page.name}: '{item.name}' invalido ({errors[0]})")
                _cleanup(path)
                continue

        return item, path

    return None, None


def _cleanup(path):
    try:
        os.remove(path)
    except OSError:
        pass


def process_page(cfg, st, page, now):
    print(f"\n=== {page.name} ({page.post_type}) - {page.source_type} - fuso {page.tz}")

    problems = []
    src = sources.get(page)
    videos = src.list_videos()
    if not videos:
        print("  ! pasta sem videos")
        return 0, [f"{page.name}: pasta vazia"]

    rejected = state.rejected_ids(st, page.slug)
    used = state.used_file_ids(st, page.slug) | rejected
    queue = [v for v in videos if v.id not in used]

    if not queue:
        if cfg.recycle:
            print("  fila esgotada -> reciclando a pasta do inicio")
            state.reset_used(st, page.slug)
            queue = [v for v in videos if v.id not in rejected]
        else:
            msg = f"{page.name}: sem videos novos ({len(videos)} na pasta, todos ja usados)"
            print(f"  ! {msg}")
            return 0, [msg]

    if cfg.mode == "schedule":
        slots = [
            s for s in config.upcoming_slots(page, now, cfg.horizon_hours)
            if s >= now + timedelta(minutes=MIN_LEAD_MINUTES)
            and not state.slot_taken(st, page.slug, s.isoformat())
        ]
    else:
        due = config.due_slot(page, now, cfg.tolerance_minutes)
        slots = [due] if due and not state.slot_taken(st, page.slug, due.isoformat()) else []

    if not slots:
        print("  nada a fazer agora")
        return 0, problems

    print(f"  {len(queue)} video(s) na fila | {len(slots)} horario(s) em aberto")
    captions = src.captions()

    posted = 0
    tentativas = {}
    falhas_seguidas = 0

    for slot in slots:
        print(f"\n  -> {_fmt(slot)}")
        item, path = _next_playable(src, queue, page, cfg, st, problems)
        if not item:
            problems.append(f"{page.name}: acabaram os videos utilizaveis em {_fmt(slot)}")
            break

        print(f"     {item.name}")
        caption = caption_for(item, captions, page)
        when_ts = int(slot.timestamp()) if cfg.mode == "schedule" else None

        if DRY_RUN:
            print(f"     [DRY RUN] legenda: {caption[:80]!r}")
            _cleanup(path)
            continue

        try:
            post_id = facebook.publish(page, path, caption, when_ts)
            print(f"     OK {'agendado' if when_ts else 'publicado'} | id={post_id}")
            state.record(st, page.slug, slot.isoformat(), item.id, item.name,
                         post_id, slot.isoformat())
            state.prune_slots(st, page.slug)
            posted += 1
            falhas_seguidas = 0
        except Exception as e:
            print(f"     FALHOU: {e}")
            problems.append(f"{page.name}: '{item.name}' em {_fmt(slot)} -> {e}")
            falhas_seguidas += 1

            # Volta para o FIM da fila: um video problematico ganha nova chance,
            # mas nao trava os horarios seguintes.
            tentativas[item.id] = tentativas.get(item.id, 0) + 1
            if tentativas[item.id] < 2:
                queue.append(item)
            else:
                print(f"     '{item.name}' falhou 2x - fica para o proximo run")

            # Disjuntor: 3 falhas seguidas = problema na API, nao no video.
            # Melhor parar do que gastar todos os horarios do dia batendo na parede.
            if falhas_seguidas >= 3:
                problems.append(
                    f"{page.name}: 3 falhas seguidas - abortando a pagina "
                    "(Graph API instavel ou token invalido)"
                )
                _cleanup(path)
                break
        finally:
            _cleanup(path)

    return posted, problems


def run():
    cfg = config.load()
    st = state.load()
    now = datetime.now(cfg.tz)

    print(f"Rodando em {now:%d/%m/%Y %H:%M} ({cfg.tz}) | modo={cfg.mode}"
          + (" | DRY RUN" if DRY_RUN else ""))

    total, problems = 0, []
    for page in cfg.pages:
        _warn_token(page)
        try:
            posted, page_problems = process_page(cfg, st, page, now)
            total += posted
            problems.extend(page_problems)
        except Exception as e:
            traceback.print_exc()
            problems.append(f"{page.name}: erro geral -> {e}")

    state.save(st)

    print(f"\n--- Resumo: {total} post(s) processado(s)")
    if problems:
        print("--- Pendencias:")
        for p in problems:
            print(f"  * {p}")

    _write_summary(total, problems)
    # Um video ruim nao derruba o run inteiro; uma pane real (nada saiu e houve
    # erro) falha o workflow e o GitHub te manda o e-mail de alerta.
    if problems and total == 0:
        sys.exit(1)


def _warn_token(page):
    expires = facebook.token_expires_at(page)
    if expires:
        left = datetime.fromtimestamp(expires) - datetime.now()
        if left.days < 10:
            print(f"  !! ATENCAO: token da pagina '{page.name}' expira em {left.days} dia(s)")


def _write_summary(total, problems):
    path = os.environ.get("GITHUB_STEP_SUMMARY")
    if not path:
        return
    with open(path, "a", encoding="utf-8") as f:
        f.write(f"### Postador\n\n**{total}** post(s) processado(s).\n\n")
        if problems:
            f.write("Pendencias:\n\n")
            for p in problems:
                f.write(f"- {p}\n")


if __name__ == "__main__":
    run()
