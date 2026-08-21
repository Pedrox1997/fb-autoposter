"""Caca bots nos comentarios das Paginas e bloqueia em massa.

    python -m tools.antibot                      # varre tudo, so relatorio
    python -m tools.antibot "Daily Blessings"    # uma pagina so
    python -m tools.antibot --posts 60           # profundidade da varredura
    python -m tools.antibot --limiar 4           # mais/menos rigoroso
    python -m tools.antibot --aplicar            # bloqueia de verdade
    python -m tools.antibot --aplicar --apagar   # bloqueia e apaga os comentarios
    python -m tools.antibot --listar             # quem ja esta bloqueado
    python -m tools.antibot --desfazer           # desbloqueia o que ELE bloqueou

Sem --aplicar nada e alterado: o padrao e relatorio. A Graph API nao expoe a
lista de seguidores, entao o alvo aqui e quem COMENTA - que e onde bot aparece.
"""
import argparse
import csv
import json
import os
import re
import sys
import time
from collections import defaultdict
from datetime import datetime, timezone

sys.path.insert(0, __file__.rsplit("tools", 1)[0])

from src import config, facebook  # noqa: E402

ROOT = config.ROOT
ARQ_BLOQUEADOS = os.path.join(ROOT, "state", "bloqueados.json")
ARQ_BRANCA = os.path.join(ROOT, "state", "nunca_bloquear.json")
ARQ_RELATORIO = os.path.join(ROOT, "state", "antibot_relatorio.csv")

LOTE = 50          # ids por chamada de bloqueio
PAUSA_LOTE = 2     # segundos entre lotes, para nao bater no limite da Pagina
LIMIAR = 5         # pontos a partir dos quais o autor e tratado como bot

# ------------------------------------------------------------------ heuristica

RE_LINK = re.compile(r"(https?://|www\.|wa\.me/|t\.me/|bit\.ly|cutt\.ly|tinyurl)", re.I)
RE_TELEFONE = re.compile(r"(\+?\d[\d\s().-]{8,}\d)")
RE_DIGITOS_NOME = re.compile(r"\d{4,}")
RE_EMOJI_SO = re.compile(r"^[\W_]+$", re.U)

GOLPE = {
    "recuperacao": ("recover", "recuperar conta", "hacked", "hackeada", "hacker",
                    "restore your account", "conta desativada", "disabled account"),
    "investimento": ("bitcoin", "btc", "crypto", "forex", "trading", "investimento",
                     "lucro garantido", "renda extra", "profit", "earn $", "ganhe r$"),
    "contato": ("whatsapp", "telegram", "inbox me", "dm me", "chama no zap",
                "click the link", "clique no link", "link na bio"),
    "adulto": ("hot girls", "sexy", "xxx", "onlyfans", "nudes"),
}


def pontuar(autor, comentarios):
    """Devolve (pontos, motivos) para um autor a partir de todos os comentarios dele."""
    pontos, motivos = 0, []
    textos = [(c.get("message") or "").strip() for c in comentarios]
    juntos = " ".join(textos).lower()

    if any(RE_LINK.search(t) for t in textos):
        pontos += 4
        motivos.append("link externo")

    if any(RE_TELEFONE.search(t) for t in textos):
        pontos += 3
        motivos.append("telefone no comentario")

    for rotulo, termos in GOLPE.items():
        if any(termo in juntos for termo in termos):
            pontos += 3
            motivos.append("termo de " + rotulo)

    # mesma frase colada em posts diferentes = copia e cola de robo
    por_texto = defaultdict(set)
    for c, t in zip(comentarios, textos):
        if len(t) >= 8:
            por_texto[t.lower()].add(c["_post"])
    # 3-5 posts sozinho nao bloqueia: fa devoto tambem repete "God bless you all".
    # So a partir de 6 a repeticao ja basta para cruzar o limiar por conta propria.
    repetido = max((len(v) for v in por_texto.values()), default=0)
    if repetido >= 3:
        pontos += 8 if repetido >= 10 else 6 if repetido >= 6 else 4
        motivos.append("mesmo texto em %d posts" % repetido)

    # rajada: muitos comentarios em poucos segundos
    quando = sorted(c["_ts"] for c in comentarios if c.get("_ts"))
    if len(quando) >= 5:
        for i in range(len(quando) - 4):
            if quando[i + 4] - quando[i] <= 60:
                pontos += 3
                motivos.append("rajada de 5 comentarios em 60s")
                break

    if len(comentarios) >= 12:
        pontos += 2
        motivos.append("%d comentarios na varredura" % len(comentarios))

    if RE_DIGITOS_NOME.search(autor.get("name") or ""):
        pontos += 1
        motivos.append("nome com sequencia de digitos")

    if len(textos) >= 6 and all(RE_EMOJI_SO.match(t) for t in textos if t):
        pontos += 1
        motivos.append("so emoji, em volume")

    return pontos, motivos


# --------------------------------------------------------------------- coleta

def buscar_posts(page, quantos):
    posts, url = [], "%s/%s/posts" % (facebook.GRAPH, page.page_id)
    params = {"fields": "id,created_time,permalink_url", "limit": min(quantos, 100),
              "access_token": page.token}
    while url and len(posts) < quantos:
        dados = facebook._request("GET", url, params=params)
        posts.extend(dados.get("data", []))
        url = (dados.get("paging") or {}).get("next")
        params = None
    return posts[:quantos]


def buscar_comentarios(page, post_id):
    saida, url = [], "%s/%s/comments" % (facebook.GRAPH, post_id)
    params = {"fields": "id,message,created_time,from{id,name}", "filter": "stream",
              "limit": 100, "access_token": page.token}
    while url:
        try:
            dados = facebook._request("GET", url, params=params, attempts=2)
        except facebook.FacebookError as e:
            print("    ! comentarios de %s: %s" % (post_id, e))
            return saida
        saida.extend(dados.get("data", []))
        url = (dados.get("paging") or {}).get("next")
        params = None
    return saida


def ts(iso):
    try:
        return datetime.strptime(iso, "%Y-%m-%dT%H:%M:%S%z").timestamp()
    except (TypeError, ValueError):
        return 0


def varrer(page, quantos):
    """{psid: {'name', 'comentarios': [...]}} de tudo que comentou nos posts recentes."""
    posts = buscar_posts(page, quantos)
    print("  %d posts para varrer" % len(posts))
    autores = {}
    for i, post in enumerate(posts, 1):
        for c in buscar_comentarios(page, post["id"]):
            autor = c.get("from") or {}
            psid = str(autor.get("id") or "")
            if not psid or psid == str(page.page_id):
                continue          # sem 'from' (privacidade) ou a propria Pagina
            c["_post"] = post["id"]
            c["_ts"] = ts(c.get("created_time"))
            reg = autores.setdefault(psid, {"name": autor.get("name", ""),
                                            "comentarios": []})
            reg["comentarios"].append(c)
        if i % 10 == 0 or i == len(posts):
            print("    %d/%d posts | %d autores" % (i, len(posts), len(autores)))
    return autores


# ---------------------------------------------------------------- persistencia

def carregar(caminho, padrao):
    if not os.path.exists(caminho):
        return padrao
    with open(caminho, "r", encoding="utf-8") as f:
        try:
            return json.load(f)
        except json.JSONDecodeError:
            return padrao


def salvar(caminho, dados):
    os.makedirs(os.path.dirname(caminho), exist_ok=True)
    with open(caminho, "w", encoding="utf-8") as f:
        json.dump(dados, f, ensure_ascii=False, indent=2)


# ---------------------------------------------------------------------- acoes

def bloquear(page, psids):
    """POST /{page-id}/blocked em lotes. Devolve (ok, falhas)."""
    ok, falhas = [], []
    for i in range(0, len(psids), LOTE):
        lote = psids[i:i + LOTE]
        try:
            resp = facebook._request(
                "POST", "%s/%s/blocked" % (facebook.GRAPH, page.page_id), attempts=3,
                data={"psid": ",".join(lote), "access_token": page.token})
        except facebook.FacebookError as e:
            if e.code == 283:
                print("  ! Sem permissao pages_manage_metadata. Reconecte o perfil "
                      "no painel concedendo essa permissao.")
                return ok, psids[i:]
            print("  ! lote %d: %s" % (i // LOTE + 1, e))
            falhas.extend(lote)
            continue
        # a API responde {"<psid>": true} ou {"<psid>": {"error": ...}}
        for psid in lote:
            r = resp.get(psid, resp.get("success"))
            (ok if r is True or r is None else falhas).append(psid)
        print("    lote %d: %d enviados" % (i // LOTE + 1, len(lote)))
        if i + LOTE < len(psids):
            time.sleep(PAUSA_LOTE)
    return ok, falhas


def desbloquear(page, psids):
    for i in range(0, len(psids), LOTE):
        lote = psids[i:i + LOTE]
        try:
            facebook._request("DELETE", "%s/%s/blocked" % (facebook.GRAPH, page.page_id),
                              attempts=3,
                              params={"psid": ",".join(lote), "access_token": page.token})
            print("    lote %d: %d desbloqueados" % (i // LOTE + 1, len(lote)))
        except facebook.FacebookError as e:
            print("  ! lote %d: %s" % (i // LOTE + 1, e))
        if i + LOTE < len(psids):
            time.sleep(PAUSA_LOTE)


def apagar_comentarios(page, ids):
    apagados = 0
    for cid in ids:
        try:
            facebook._request("DELETE", "%s/%s" % (facebook.GRAPH, cid), attempts=2,
                              params={"access_token": page.token})
            apagados += 1
        except facebook.FacebookError as e:
            print("    ! comentario %s: %s" % (cid, e))
    print("    %d/%d comentarios apagados" % (apagados, len(ids)))


def listar_bloqueados(page):
    saida, url = [], "%s/%s/blocked" % (facebook.GRAPH, page.page_id)
    params = {"limit": 100, "access_token": page.token}
    while url:
        dados = facebook._request("GET", url, params=params)
        saida.extend(dados.get("data", []))
        url = (dados.get("paging") or {}).get("next")
        params = None
    return saida


# ----------------------------------------------------------------------- main

def main():
    ap = argparse.ArgumentParser(add_help=True)
    ap.add_argument("pagina", nargs="?", help="nome da pagina (padrao: todas)")
    ap.add_argument("--posts", type=int, default=30, help="posts recentes a varrer")
    ap.add_argument("--limiar", type=int, default=LIMIAR, help="pontos para virar bot")
    ap.add_argument("--aplicar", action="store_true", help="bloqueia de verdade")
    ap.add_argument("--apagar", action="store_true", help="apaga tambem os comentarios")
    ap.add_argument("--listar", action="store_true", help="mostra quem ja esta bloqueado")
    ap.add_argument("--desfazer", action="store_true", help="desbloqueia o que ele bloqueou")
    args = ap.parse_args()

    cfg = config.load()
    alvo = args.pagina.strip().lower() if args.pagina else None
    paginas = [p for p in cfg.pages if not alvo or p.name.lower() == alvo]
    if not paginas:
        print("Pagina '%s' nao encontrada no config.yaml." % args.pagina)
        return 1

    registro = carregar(ARQ_BLOQUEADOS, {})
    branca = set(carregar(ARQ_BRANCA, []))
    linhas = []

    for page in paginas:
        print("\n=== %s" % page.name)

        if args.listar:
            for b in listar_bloqueados(page):
                print("  %s  %s" % (b.get("id"), b.get("name", "")))
            continue

        if args.desfazer:
            psids = list((registro.get(str(page.page_id)) or {}).keys())
            if not psids:
                print("  nada registrado para desfazer")
                continue
            print("  desbloqueando %d" % len(psids))
            desbloquear(page, psids)
            registro.pop(str(page.page_id), None)
            salvar(ARQ_BLOQUEADOS, registro)
            continue

        autores = varrer(page, args.posts)
        ja = registro.get(str(page.page_id)) or {}
        suspeitos = []
        for psid, reg in autores.items():
            if psid in branca or psid in ja:
                continue
            pontos, motivos = pontuar(reg, reg["comentarios"])
            if pontos >= args.limiar:
                suspeitos.append((psid, reg, pontos, motivos))

        suspeitos.sort(key=lambda x: -x[2])
        print("  %d autores | %d suspeitos (limiar %d)"
              % (len(autores), len(suspeitos), args.limiar))

        for psid, reg, pontos, motivos in suspeitos:
            amostra = (reg["comentarios"][0].get("message") or "")[:70].replace("\n", " ")
            print("    [%2d] %-28s %-50s | %s"
                  % (pontos, reg["name"][:28], "; ".join(motivos)[:50], amostra))
            linhas.append([page.name, psid, reg["name"], pontos, "; ".join(motivos),
                           len(reg["comentarios"]), amostra])

        if not args.aplicar or not suspeitos:
            if args.aplicar:
                print("  nada a bloquear")
            continue

        psids = [s[0] for s in suspeitos]
        print("  bloqueando %d..." % len(psids))
        ok, falhas = bloquear(page, psids)
        agora = datetime.now(timezone.utc).isoformat(timespec="seconds")
        destino = registro.setdefault(str(page.page_id), {})
        for psid, reg, pontos, motivos in suspeitos:
            if psid in ok:
                destino[psid] = {"name": reg["name"], "pontos": pontos,
                                 "motivos": motivos, "quando": agora}
        salvar(ARQ_BLOQUEADOS, registro)
        print("  bloqueados: %d | falhas: %d" % (len(ok), len(falhas)))

        if args.apagar:
            ids = [c["id"] for s in suspeitos if s[0] in ok for c in s[1]["comentarios"]]
            print("  apagando %d comentarios..." % len(ids))
            apagar_comentarios(page, ids)

    if linhas:
        os.makedirs(os.path.dirname(ARQ_RELATORIO), exist_ok=True)
        with open(ARQ_RELATORIO, "w", newline="", encoding="utf-8-sig") as f:
            w = csv.writer(f, delimiter=";")
            w.writerow(["pagina", "psid", "nome", "pontos", "motivos",
                        "comentarios", "amostra"])
            w.writerows(linhas)
        print("\nRelatorio: %s" % ARQ_RELATORIO)
        if not args.aplicar:
            print("Nada foi alterado. Rode com --aplicar para bloquear.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
