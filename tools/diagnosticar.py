"""Compara, na API, posts publicados na hora com posts agendados.

    python -m tools.diagnosticar

Le os posts registrados em state/posted.json e mostra privacidade, estado de
publicacao e status de cada um - para descobrir por que uns aparecem para o
publico e outros nao, em vez de adivinhar.
"""
import sys

sys.path.insert(0, __file__.rsplit("tools", 1)[0])

from src import config, facebook, state  # noqa: E402

CAMPOS = ("id,privacy,published,scheduled_publish_time,status,created_time,"
          "permalink_url,is_crosspost_video,content_category")
LIMITE = 12


def olhar(page, post_id):
    try:
        return facebook._request("GET", f"{facebook.GRAPH}/{post_id}", attempts=2,
                                 params={"fields": CAMPOS, "access_token": page.token})
    except Exception as e:
        return {"erro": str(e)[:120]}


def main():
    cfg = config.load()
    st = state.load()

    for page in cfg.pages:
        dados = st.get("pages", {}).get(page.slug, {})
        slots = dados.get("slots", {})
        if not slots:
            continue

        print(f"\n=== {page.name}")
        print(f"{'origem':<10}{'privacidade':<14}{'publicado':<11}{'status':<12}  arquivo")
        print("-" * 92)

        # os mais recentes primeiro, misturando agendados e imediatos
        for chave in sorted(slots, reverse=True)[:LIMITE]:
            item = slots[chave]
            info = olhar(page, item.get("post_id"))
            origem = "imediato" if chave.startswith("teste") else "agendado"

            if info.get("erro"):
                print(f"{origem:<10}{'?':<14}{'?':<11}{'ERRO':<12}  {info['erro']}")
                continue

            privacidade = (info.get("privacy") or {}).get("value", "?")
            publicado = str(info.get("published", "?"))
            situacao = (info.get("status") or {}).get("video_status", "?")
            print(f"{origem:<10}{privacidade:<14}{publicado:<11}{situacao:<12}  "
                  f"{item.get('file','')[:34]}")

    print("\nprivacidade EVERYONE = visivel para todos.")
    print("Se os agendados mostram algo diferente dos imediatos, achamos a causa.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
