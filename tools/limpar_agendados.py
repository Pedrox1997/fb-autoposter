"""Apaga posts agendados e devolve os videos para a fila.

    python -m tools.limpar_agendados            # so lista (nao apaga)
    python -m tools.limpar_agendados --apagar   # apaga de verdade

Serve quando os agendamentos precisam ser refeitos - por exemplo, posts
criados enquanto o app estava em modo de desenvolvimento, que nascem
invisiveis para o publico e continuam assim mesmo depois de publicar o app.
"""
import sys
from datetime import datetime, timezone

sys.path.insert(0, __file__.rsplit("tools", 1)[0])

from src import config, facebook, state  # noqa: E402

APAGAR = "--apagar" in sys.argv


def futuros(dados_da_pagina):
    """Slots com horario ainda por vir - sao os agendamentos vivos."""
    agora = datetime.now(timezone.utc)
    saida = []
    for chave, item in dados_da_pagina.get("slots", {}).items():
        try:
            quando = datetime.fromisoformat(item.get("scheduled_for") or "")
        except ValueError:
            continue
        if quando.tzinfo is None:
            quando = quando.replace(tzinfo=timezone.utc)
        if quando > agora:
            saida.append((chave, item, quando))
    return sorted(saida, key=lambda t: t[2])


def main():
    cfg = config.load()
    st = state.load()
    total_apagados = 0

    for page in cfg.pages:
        dados = st.get("pages", {}).get(page.slug, {})
        pendentes = futuros(dados)

        print(f"\n=== {page.name}: {len(pendentes)} agendamento(s) por vir")
        if not pendentes:
            continue

        for chave, item, quando in pendentes:
            print(f"  {quando:%d/%m %H:%M}  {item.get('file','')[:52]}")
            if not APAGAR:
                continue

            post_id = item.get("post_id")
            try:
                facebook._request("DELETE", f"{facebook.GRAPH}/{post_id}", attempts=2,
                                  params={"access_token": page.token})
                print("      apagado no Facebook")
            except Exception as e:
                print(f"      ! nao consegui apagar ({e}) - siga apagando pela pagina")

            # tira do registro: o video volta a ficar disponivel
            dados.get("slots", {}).pop(chave, None)
            usados = dados.get("used_files", [])
            if item.get("file_id") in usados:
                usados.remove(item["file_id"])
            total_apagados += 1

    if APAGAR:
        state.save(st)
        print(f"\n{total_apagados} agendamento(s) removido(s). "
              "Os videos voltaram para a fila.")
    else:
        print("\nNada foi apagado. Rode com --apagar para efetivar.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
