"""Publica UM video agora, para validar a ligacao inteira de ponta a ponta.

    python -m tools.testar_post              # primeira pagina do config
    python -m tools.testar_post "Nome da Pagina"

Publica de verdade: o post vai ao ar na Pagina. Use DRY_RUN=1 para ensaiar.
"""
import os
import sys
from datetime import datetime

sys.path.insert(0, __file__.rsplit("tools", 1)[0])

from src import config, facebook, media, sources, state  # noqa: E402
from src.sources.base import caption_for  # noqa: E402

DRY_RUN = os.environ.get("DRY_RUN", "").strip().lower() in ("1", "true", "yes")


def main():
    alvo = sys.argv[1].strip().lower() if len(sys.argv) > 1 else None

    cfg = config.load()
    paginas = [p for p in cfg.pages if not alvo or p.name.lower() == alvo]
    if not paginas:
        print(f"Pagina '{sys.argv[1]}' nao encontrada no config.yaml")
        return 1

    page = paginas[0]
    st = state.load()
    print(f"Pagina: {page.name} (id {page.page_id}) | tipo: {page.post_type}")
    print(f"Pasta:  {page.source_ref}\n")

    try:
        info = facebook.page_info(page)
        print(f"[ok] conectado em '{info.get('name')}'")
    except Exception as e:
        print(f"[ERRO] token/pagina: {e}")
        return 1

    src = sources.get(page)
    videos = src.list_videos()
    if not videos:
        print("[ERRO] nenhum video na pasta")
        return 1
    print(f"[ok] {len(videos)} video(s) na pasta")

    usados = state.used_file_ids(st, page.slug) | state.rejected_ids(st, page.slug)
    fila = [v for v in videos if v.id not in usados]
    if not fila:
        print("[ERRO] todos os videos ja foram usados")
        return 1

    # o menor primeiro: teste mais rapido
    item = sorted(fila, key=lambda v: v.size or 0)[0]
    print(f"\nEscolhido: {item.name} ({(item.size or 0) / 1e6:.1f} MB)")

    caminho = src.download(item)
    print(f"[ok] baixado")

    erros, avisos = media.check(caminho, page.post_type)
    for a in avisos:
        print(f"     aviso: {a}")
    if erros:
        print(f"[ERRO] video invalido: {'; '.join(erros)}")
        return 1

    legenda = caption_for(item, src.captions(), page)
    print(f"Legenda: {legenda[:120]!r}")

    if DRY_RUN:
        print("\n[DRY RUN] pararia aqui - nada foi publicado.")
        return 0

    print("\nPublicando agora...")
    post_id = facebook.publish(page, caminho, legenda, None)

    print(f"\n[ok] PUBLICADO | id={post_id}")
    print(f"     https://www.facebook.com/{post_id}")

    state.record(st, page.slug, f"teste-{datetime.now():%Y%m%dT%H%M%S}",
                 item.id, item.name, post_id, datetime.now().isoformat())
    state.save(st)

    try:
        os.remove(caminho)
    except OSError:
        pass
    return 0


if __name__ == "__main__":
    sys.exit(main())
