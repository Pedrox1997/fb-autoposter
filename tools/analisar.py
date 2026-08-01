"""Compara o desempenho dos videos ja publicados na Pagina.

    python -m tools.analisar                 # primeira pagina do config
    python -m tools.analisar "Nome da Pagina"

Mostra views, duracao e formato de cada video recente. Serve para responder
com numero, e nao com achismo, por que um video rende e outro nao.
"""
import sys
from datetime import datetime

import requests

sys.path.insert(0, __file__.rsplit("tools", 1)[0])

from src import config, facebook  # noqa: E402

LIMITE = 25


def buscar_videos(page):
    campos = ("id,title,description,length,created_time,permalink_url,"
              "video_insights.metric(total_video_views,total_video_impressions)")
    dados = facebook._request(
        "GET", f"{facebook.GRAPH}/{page.page_id}/videos",
        params={"fields": campos, "limit": LIMITE, "access_token": page.token})
    return dados.get("data", [])


def metrica(video, nome):
    for bloco in (video.get("video_insights") or {}).get("data", []):
        if bloco.get("name") == nome:
            valores = bloco.get("values") or [{}]
            return valores[0].get("value", 0)
    return 0


def main():
    alvo = sys.argv[1].strip().lower() if len(sys.argv) > 1 else None
    cfg = config.load()
    paginas = [p for p in cfg.pages if not alvo or p.name.lower() == alvo]
    if not paginas:
        print(f"Pagina '{sys.argv[1]}' nao encontrada.")
        return 1
    page = paginas[0]

    print(f"Pagina: {page.name}\n")
    try:
        videos = buscar_videos(page)
    except Exception as e:
        print(f"[ERRO] {e}")
        return 1

    if not videos:
        print("Nenhum video encontrado.")
        return 0

    linhas = []
    for v in videos:
        duracao = float(v.get("length") or 0)
        linhas.append({
            "quando": (v.get("created_time") or "")[:16].replace("T", " "),
            "dur": duracao,
            # ate 90s e vertical, o Facebook trata como Reels
            "formato": "Reels?" if 0 < duracao <= 90 else "video",
            "views": metrica(v, "total_video_views"),
            "alcance": metrica(v, "total_video_impressions"),
            "titulo": (v.get("description") or v.get("title") or "")[:44],
        })

    print(f"{'quando':<17}{'dur':>7}{'formato':>9}{'views':>8}{'alcance':>9}  titulo")
    print("-" * 96)
    for ln in sorted(linhas, key=lambda i: i["quando"], reverse=True):
        print(f"{ln['quando']:<17}{ln['dur']:>6.0f}s{ln['formato']:>9}"
              f"{ln['views']:>8}{ln['alcance']:>9}  {ln['titulo']}")

    curtos = [ln for ln in linhas if 0 < ln["dur"] <= 90]
    longos = [ln for ln in linhas if ln["dur"] > 90]
    print()
    for rotulo, grupo in (("ate 90s (elegivel a Reels)", curtos), ("acima de 90s", longos)):
        if grupo:
            media = sum(i["views"] for i in grupo) / len(grupo)
            print(f"  {rotulo}: {len(grupo)} video(s), media de {media:.0f} views")
    return 0


if __name__ == "__main__":
    sys.exit(main())
