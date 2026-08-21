"""Funde dois arquivos de estado em vez de deixar o git resolver por texto.

Duas execucoes simultaneas escrevem o mesmo state/posted.json e o
'git pull --rebase' trava num conflito - o registro do que ja foi postado
nao pode se perder, senao o robo republica o video.

    python -m tools.mesclar_estado <estado_desta_execucao.json>

Le o arquivo indicado, funde com o state/posted.json atual (que deve estar na
versao do repositorio) e grava a uniao dos dois.
"""
import json
import os
import sys

sys.path.insert(0, __file__.rsplit("tools", 1)[0])

from src import state  # noqa: E402


def ler(caminho):
    if not caminho or not os.path.exists(caminho):
        return {"pages": {}}
    with open(caminho, "r", encoding="utf-8") as f:
        try:
            dados = json.load(f)
        except json.JSONDecodeError:
            return {"pages": {}}
    dados.setdefault("pages", {})
    return dados


def fundir(base, novo):
    """Uniao dos dois lados: nada que ja foi publicado pode sumir."""
    resultado = {"pages": {}}
    slugs = set(base.get("pages", {})) | set(novo.get("pages", {}))

    for slug in slugs:
        a = base.get("pages", {}).get(slug, {})
        b = novo.get("pages", {}).get(slug, {})

        ciclo_a = int(a.get("ciclo", 0) or 0)
        ciclo_b = int(b.get("ciclo", 0) or 0)

        if ciclo_a != ciclo_b:
            # Reciclagem e remocao intencional: quem recomecou a pasta tem a
            # lista certa. Unir aqui devolveria os videos que acabaram de sair
            # da fila, e o robo republicaria sempre o primeiro.
            recente = a if ciclo_a > ciclo_b else b
            usados = list(recente.get("used_files", []))
        else:
            usados = list(a.get("used_files", []))
            for file_id in b.get("used_files", []):
                if file_id not in usados:
                    usados.append(file_id)

        resultado["pages"][slug] = {
            "used_files": usados,
            "ciclo": max(ciclo_a, ciclo_b),
            # o historico de posts nunca se perde, mesmo trocando de ciclo
            "rejected": {**a.get("rejected", {}), **b.get("rejected", {})},
            "slots": {**a.get("slots", {}), **b.get("slots", {})},
        }
    return resultado


def main():
    meu = ler(sys.argv[1] if len(sys.argv) > 1 else "")
    do_repo = ler(state.STATE_PATH)

    fundido = fundir(do_repo, meu)
    state.save(fundido)

    total = sum(len(p["used_files"]) for p in fundido["pages"].values())
    print(f"estado fundido: {len(fundido['pages'])} pagina(s), {total} video(s) registrados")
    return 0


if __name__ == "__main__":
    sys.exit(main())
