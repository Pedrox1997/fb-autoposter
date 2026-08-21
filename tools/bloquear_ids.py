"""Bloqueia em massa pela Graph API a partir do CSV lido no navegador.

    python -m tools.bloquear_ids seguidores.csv                    # so classifica
    python -m tools.bloquear_ids seguidores.csv --aplicar          # bloqueia
    python -m tools.bloquear_ids seguidores.csv --pagina "Nome"    # escolhe a pagina
    python -m tools.bloquear_ids --desfazer --pagina "Nome"        # desbloqueia

Por que isso existe: ID de Pagina e publico e o edge /blocked aceita "User or
Page IDs". Entao, quando os seguidores-robo sao PAGINAS, o navegador so precisa
LER os ids (modo "listar" do bloquear_seguidores.js) e o bloqueio acontece pela
API oficial - 50 por chamada, sem clique, sem automacao de interface.

Perfil pessoal nao funciona assim: o id e escopado e a Graph nao resolve. Esses
ficam separados num CSV a parte, para o caminho do clique.
"""
import argparse
import csv
import json
import os
import sys
import time

sys.path.insert(0, __file__.rsplit("tools", 1)[0])

from src import config, facebook  # noqa: E402

ROOT = config.ROOT
ARQ_BLOQUEADOS = os.path.join(ROOT, "state", "bloqueados.json")
LOTE_RESOLVE = 50
LOTE_BLOQUEIO = 50
PAUSA = 2


def ler_csv(caminho):
    """Aceita o CSV do navegador (nome;ref;perfil) ou uma lista crua de ids."""
    itens, vistos = [], set()
    with open(caminho, "r", encoding="utf-8-sig", newline="") as f:
        amostra = f.read(2048)
        f.seek(0)
        if ";" in amostra or "," in amostra:
            leitor = csv.DictReader(f, delimiter=";" if ";" in amostra else ",")
            campos = [c.lower() for c in (leitor.fieldnames or [])]
            if "ref" in campos or "id" in campos:
                chave = "ref" if "ref" in campos else "id"
                for linha in leitor:
                    ref = (linha.get(chave) or linha.get(chave.upper()) or "").strip()
                    nome = (linha.get("nome") or linha.get("name") or "").strip()
                    if ref and ref not in vistos:
                        vistos.add(ref)
                        itens.append({"ref": ref, "nome": nome})
                return itens
        f.seek(0)
        for linha in f:
            ref = linha.strip().strip('"')
            if ref and ref.lower() not in ("ref", "id") and ref not in vistos:
                vistos.add(ref)
                itens.append({"ref": ref, "nome": ""})
    return itens


def classificar(page, itens):
    """Resolve os refs em lote. Devolve (paginas, nao_resolvidos).

    O que a Graph resolve com id/apelido publico e Pagina. Perfil pessoal
    devolve erro - e justamente por isso ele nao da para bloquear por API.
    """
    paginas, nao = [], []
    for i in range(0, len(itens), LOTE_RESOLVE):
        bloco = itens[i:i + LOTE_RESOLVE]
        refs = ",".join(x["ref"] for x in bloco)
        try:
            dados = facebook._request(
                "GET", facebook.GRAPH, attempts=2,
                params={"ids": refs, "fields": "id,name,category,link",
                        "access_token": page.token})
        except facebook.FacebookError as e:
            # um ref invalido derruba o lote inteiro: cai para um a um
            print("    lote %d falhou (%s) - resolvendo individualmente"
                  % (i // LOTE_RESOLVE + 1, e.code))
            dados = {}
            for x in bloco:
                try:
                    dados[x["ref"]] = facebook._request(
                        "GET", "%s/%s" % (facebook.GRAPH, x["ref"]), attempts=1,
                        params={"fields": "id,name,category,link",
                                "access_token": page.token})
                except facebook.FacebookError:
                    pass

        for x in bloco:
            info = dados.get(x["ref"]) or {}
            if info.get("id") and info.get("category"):
                paginas.append({"ref": x["ref"], "id": str(info["id"]),
                                "nome": info.get("name") or x["nome"],
                                "categoria": info.get("category")})
            else:
                nao.append(x)
        print("    resolvidos %d/%d" % (min(i + LOTE_RESOLVE, len(itens)), len(itens)))
    return paginas, nao


def bloquear(page, ids):
    ok, falhas = [], []
    for i in range(0, len(ids), LOTE_BLOQUEIO):
        lote = ids[i:i + LOTE_BLOQUEIO]
        try:
            resp = facebook._request(
                "POST", "%s/%s/blocked" % (facebook.GRAPH, page.page_id), attempts=3,
                data={"user": ",".join(lote), "access_token": page.token})
        except facebook.FacebookError as e:
            if e.code == 283:
                print("  ! Falta pages_manage_metadata no token. Reconecte o perfil.")
                return ok, ids[i:]
            print("  ! lote %d: %s" % (i // LOTE_BLOQUEIO + 1, e))
            falhas.extend(lote)
            continue
        for pid in lote:
            r = resp.get(pid, resp.get("success"))
            (ok if r is True or r is None else falhas).append(pid)
        print("    lote %d: %d enviados | ok acumulado %d"
              % (i // LOTE_BLOQUEIO + 1, len(lote), len(ok)))
        if i + LOTE_BLOQUEIO < len(ids):
            time.sleep(PAUSA)
    return ok, falhas


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


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("csv", nargs="?", help="seguidores.csv baixado pelo navegador")
    ap.add_argument("--pagina", help="nome da pagina no config.yaml")
    ap.add_argument("--aplicar", action="store_true", help="bloqueia de verdade")
    ap.add_argument("--desfazer", action="store_true", help="desbloqueia o registrado")
    args = ap.parse_args()

    cfg = config.load()
    alvo = args.pagina.strip().lower() if args.pagina else None
    paginas = [p for p in cfg.pages if not alvo or p.name.lower() == alvo]
    if not paginas:
        print("Pagina nao encontrada no config.yaml.")
        return 1
    page = paginas[0]
    print("=== %s" % page.name)

    registro = carregar(ARQ_BLOQUEADOS, {})

    if args.desfazer:
        ids = list((registro.get(str(page.page_id)) or {}).keys())
        if not ids:
            print("  nada registrado")
            return 0
        print("  desbloqueando %d" % len(ids))
        for i in range(0, len(ids), LOTE_BLOQUEIO):
            lote = ids[i:i + LOTE_BLOQUEIO]
            try:
                facebook._request(
                    "DELETE", "%s/%s/blocked" % (facebook.GRAPH, page.page_id),
                    params={"user": ",".join(lote), "access_token": page.token})
                print("    lote %d: %d" % (i // LOTE_BLOQUEIO + 1, len(lote)))
            except facebook.FacebookError as e:
                print("  ! %s" % e)
            time.sleep(PAUSA)
        registro.pop(str(page.page_id), None)
        salvar(ARQ_BLOQUEADOS, registro)
        return 0

    if not args.csv:
        print("Informe o CSV. Ex: python -m tools.bloquear_ids seguidores.csv")
        return 1

    itens = ler_csv(args.csv)
    print("  %d refs no arquivo" % len(itens))

    ja = registro.get(str(page.page_id)) or {}
    itens = [x for x in itens if x["ref"] not in ja]

    print("  classificando (Pagina resolve pela Graph, perfil pessoal nao)...")
    pags, nao = classificar(page, itens)
    print("\n  Paginas (bloqueaveis pela API): %d" % len(pags))
    print("  Perfis pessoais / nao resolvidos: %d" % len(nao))

    for p in pags[:15]:
        print("    %-18s %-30s %s" % (p["id"], p["nome"][:30], p["categoria"]))
    if len(pags) > 15:
        print("    ... e mais %d" % (len(pags) - 15))

    if nao:
        resto = os.path.join(ROOT, "state", "perfis_pessoais.csv")
        os.makedirs(os.path.dirname(resto), exist_ok=True)
        with open(resto, "w", newline="", encoding="utf-8-sig") as f:
            w = csv.writer(f, delimiter=";")
            w.writerow(["nome", "ref"])
            w.writerows([[x["nome"], x["ref"]] for x in nao])
        print("\n  Perfis pessoais em %s" % resto)
        print("  Esses so pelo caminho do clique (bloquear_seguidores.js).")

    if not args.aplicar:
        print("\nNada foi alterado. Rode com --aplicar para bloquear as Paginas.")
        return 0
    if not pags:
        print("\nNenhuma Pagina para bloquear.")
        return 0

    print("\n  bloqueando %d Paginas..." % len(pags))
    ok, falhas = bloquear(page, [p["id"] for p in pags])
    destino = registro.setdefault(str(page.page_id), {})
    for p in pags:
        if p["id"] in ok:
            destino[p["ref"]] = {"id": p["id"], "name": p["nome"],
                                 "categoria": p["categoria"]}
    salvar(ARQ_BLOQUEADOS, registro)
    print("  bloqueadas: %d | falhas: %d" % (len(ok), len(falhas)))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
