"""De onde vem o publico da Pagina: seguidores por pais x alcance por pais.

    python -m tools.publico
    python -m tools.publico "Daily Blessings"

A Graph API nao lista seguidores um a um, mas entrega o AGREGADO por pais. Serve
para responder com numero a pergunta que decide tudo: a base esta podre, e o
alcance esta indo para onde?

Leitura do resultado:
  - seguidores num pais que nao e o seu = base inflada por farm
  - alcance nesse mesmo pais = os bots ESTAO recebendo entrega, e ai doi
  - alcance so no pais certo = os bots sao inertes, limpar nao muda nada
"""
import sys

sys.path.insert(0, __file__.rsplit("tools", 1)[0])

from src import config, facebook  # noqa: E402

# metricas pedidas uma a uma: se a Meta depreciar alguma, as outras sobrevivem
METRICAS = [
    ("page_fans_country", "lifetime", "Seguidores por pais"),
    ("page_fans_locale", "lifetime", "Seguidores por idioma"),
    ("page_impressions_by_country_unique", "days_28", "Alcance por pais (28 dias)"),
]


def insight(page, metrica, periodo):
    dados = facebook._request(
        "GET", "%s/%s/insights/%s" % (facebook.GRAPH, page.page_id, metrica),
        attempts=2, params={"period": periodo, "access_token": page.token})
    for bloco in dados.get("data", []):
        valores = bloco.get("values") or []
        if valores:
            return valores[-1].get("value") or {}
    return {}


def tabela(titulo, valores, total_ref=None):
    print("\n  %s" % titulo)
    if not valores:
        print("    (a Meta nao retornou essa metrica para esta pagina)")
        return
    total = sum(valores.values()) or 1
    for chave, n in sorted(valores.items(), key=lambda x: -x[1])[:12]:
        barra = "#" * int(round(n / total * 30))
        print("    %-6s %8d  %5.1f%%  %s" % (chave, n, n / total * 100, barra))
    if total_ref:
        print("    total: %d" % total)


def main():
    alvo = sys.argv[1].strip().lower() if len(sys.argv) > 1 else None
    cfg = config.load()
    paginas = [p for p in cfg.pages if not alvo or p.name.lower() == alvo]
    if not paginas:
        print("Pagina '%s' nao encontrada." % sys.argv[1])
        return 1

    for page in paginas:
        info = facebook.page_info(page)
        print("\n=== %s  |  %s seguidores"
              % (info.get("name"), info.get("fan_count", "?")))

        resultados = {}
        for metrica, periodo, titulo in METRICAS:
            try:
                valores = insight(page, metrica, periodo)
            except facebook.FacebookError as e:
                print("\n  %s\n    ! %s" % (titulo, e))
                continue
            resultados[metrica] = valores
            tabela(titulo, valores, total_ref=True)

        # o veredito: os paises que dominam a base tambem dominam a entrega?
        base = resultados.get("page_fans_country") or {}
        alcance = resultados.get("page_impressions_by_country_unique") or {}
        if base and alcance:
            top_base = max(base, key=base.get)
            top_alc = max(alcance, key=alcance.get)
            fatia = alcance.get(top_base, 0) / (sum(alcance.values()) or 1)
            print("\n  Veredito")
            print("    base concentrada em %s | alcance concentrado em %s"
                  % (top_base, top_alc))
            if fatia >= 0.25:
                print("    %.0f%% do alcance vai para %s -> a base suja ESTA "
                      "recebendo entrega e envenenando o sinal."
                      % (fatia * 100, top_base))
            else:
                print("    so %.0f%% do alcance vai para %s -> os seguidores de la "
                      "sao inertes. Limpar a base nao muda a entrega."
                      % (fatia * 100, top_base))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
