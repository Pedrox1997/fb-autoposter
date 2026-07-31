"""Simulacao do fluxo completo com Drive e Facebook falsos (sem rede).

Cobre justamente o que nao pode dar errado: post duplicado, horario queimado
por video ruim, e falha de publicacao devolvendo o video para a fila.

    python -m tools.simulate
"""
import os
import sys
import tempfile
from datetime import datetime, time as dtime
from zoneinfo import ZoneInfo

sys.path.insert(0, __file__.rsplit("tools", 1)[0])

from src import config, facebook, main, media, sources, state  # noqa: E402
from src.sources.base import Item  # noqa: E402

TZ = ZoneInfo("America/Sao_Paulo")
AGORA = datetime(2026, 7, 31, 3, 0, tzinfo=TZ)
falhas = []


def check(nome, cond, detalhe=""):
    print(f"  {'ok  ' if cond else 'FALHA'} {nome} {detalhe if not cond else ''}")
    if not cond:
        falhas.append(nome)


class FakeSource:
    label = "Fake"

    def __init__(self, nomes, quebrar_download=()):
        self.itens = [Item(id=f"id-{n}", name=n, size=10_000_000) for n in nomes]
        self.quebrar_download = set(quebrar_download)
        self.baixados = []

    def list_videos(self):
        return list(self.itens)

    def captions(self):
        return {}

    def download(self, item):
        if item.name in self.quebrar_download:
            raise RuntimeError("conexao caiu")
        self.baixados.append(item.name)
        path = os.path.join(TMP, item.name)
        with open(path, "wb") as f:
            f.write(b"0" * 1024)
        return path


class FakeFacebook:
    def __init__(self, falhar=()):
        self.falhar = set(falhar)
        self.publicados = []

    def __call__(self, page, path, caption, when_ts=None):
        nome = os.path.basename(path)
        if nome in self.falhar:
            raise RuntimeError("Graph API fora do ar")
        self.publicados.append((nome, when_ts))
        return f"post-{len(self.publicados)}"


def cenario(nomes, *, invalidos=(), falhar_publish=(), quebrar_download=(),
            recycle=False, st=None):
    """Roda process_page com fontes falsas e devolve (posts, problemas, fb, st)."""
    src = FakeSource(nomes, quebrar_download)
    fb = FakeFacebook(falhar_publish)

    sources.get = lambda page: src
    facebook.publish = fb
    media.check = lambda path, tipo: (
        (["invalido de proposito"], []) if os.path.basename(path) in invalidos else ([], [])
    )

    cfg = config.Config(tz=TZ, mode="schedule", horizon_hours=30, tolerance_minutes=45,
                        recycle=recycle, validate_media=True, pages=[])
    page = config.Page(name="Teste", page_id="1", token="t", source_type="fake",
                       source_ref="x", tz=TZ, post_type="reel",
                       times=[dtime(9, 0), dtime(13, 0), dtime(19, 30)],
                       default_caption="Legenda", hashtags="", order="name")

    st = st if st is not None else {"pages": {}}
    posts, problemas = main.process_page(cfg, st, page, AGORA)
    return posts, problemas, fb, st


TMP = tempfile.mkdtemp()
state.STATE_PATH = os.path.join(TMP, "posted.json")

# Rodando as 03:00 com horizonte de 30h, a janela pega os 3 horarios de hoje
# mais o primeiro de amanha - esse adiantamento e proposital: se o run de
# amanha falhar, o post das 09:00 ja esta agendado no Facebook.
print("\n[caso 1] 5 videos, janela de 4 horarios")
posts, probs, fb, st = cenario(["01.mp4", "02.mp4", "03.mp4", "04.mp4", "05.mp4"])
check("agendou 4 posts", posts == 4, f"veio {posts}")
check("na ordem do nome",
      [p[0] for p in fb.publicados] == ["01.mp4", "02.mp4", "03.mp4", "04.mp4"])
check("cada um num horario diferente", len({p[1] for p in fb.publicados}) == 4)
check("agendou 09:00 primeiro",
      fb.publicados[0][1] == int(datetime(2026, 7, 31, 9, 0, tzinfo=TZ).timestamp()))
check("sem pendencias", probs == [], str(probs))
check("apagou os temporarios", not [f for f in os.listdir(TMP) if f.endswith(".mp4")])

print("\n[caso 2] rodar de novo no mesmo dia (o que evita post duplicado)")
posts2, probs2, fb2, _ = cenario(["01.mp4", "02.mp4", "03.mp4", "04.mp4", "05.mp4"], st=st)
check("nao republica nada", posts2 == 0, f"veio {posts2}")
check("nenhuma chamada ao Facebook", fb2.publicados == [])

print("\n[caso 3] video invalido nao pode queimar o horario")
posts3, probs3, fb3, _ = cenario(["01.mp4", "02.mp4", "03.mp4", "04.mp4"],
                                 invalidos={"02.mp4"})
check("os 3 horarios foram preenchidos", posts3 == 3, f"veio {posts3}")
check("pulou o invalido e usou o seguinte",
      [p[0] for p in fb3.publicados] == ["01.mp4", "03.mp4", "04.mp4"],
      str([p[0] for p in fb3.publicados]))
check("registrou o motivo", any("invalido" in p for p in probs3), str(probs3))

print("\n[caso 4] Facebook fora do ar em um post")
posts4, probs4, fb4, st4 = cenario(["01.mp4", "02.mp4", "03.mp4"], falhar_publish={"02.mp4"})
check("os outros 2 sairam", posts4 == 2, f"veio {posts4}")
check("reportou a falha", any("Graph API" in p for p in probs4), str(probs4))
check("video que falhou NAO foi marcado como usado",
      "id-02.mp4" not in state.used_file_ids(st4, "teste"))
check("horario que falhou continua livre",
      not state.slot_taken(st4, "teste", datetime(2026, 7, 31, 13, 0, tzinfo=TZ).isoformat()))
check("video ruim nao travou os horarios seguintes",
      [p[0] for p in fb4.publicados] == ["01.mp4", "03.mp4"],
      str([p[0] for p in fb4.publicados]))

print("\n[caso 5] download falhando")
posts5, probs5, fb5, _ = cenario(["01.mp4", "02.mp4", "03.mp4", "04.mp4"],
                                 quebrar_download={"01.mp4"})
check("seguiu com os que baixaram", posts5 == 3, f"veio {posts5}")
check("nao publicou o que nao baixou", "01.mp4" not in [p[0] for p in fb5.publicados])

print("\n[caso 6] videos insuficientes")
posts6, probs6, fb6, _ = cenario(["01.mp4"])
check("publicou o que tinha", posts6 == 1, f"veio {posts6}")
check("avisou que faltou video", any("acabaram" in p for p in probs6), str(probs6))

print("\n[caso 7] pasta esgotada com recycle ligado")
st_esgotado = {"pages": {"teste": {
    "used_files": ["id-01.mp4", "id-02.mp4", "id-03.mp4"], "rejected": {}, "slots": {}}}}
posts7, probs7, fb7, _ = cenario(["01.mp4", "02.mp4", "03.mp4"], recycle=True, st=st_esgotado)
check("reciclou e voltou a postar", posts7 == 3, f"veio {posts7}")
check("recomecou do primeiro video", fb7.publicados[0][0] == "01.mp4")

print("\n[caso 7b] pasta esgotada SEM recycle")
st_esgotado2 = {"pages": {"teste": {
    "used_files": ["id-01.mp4", "id-02.mp4", "id-03.mp4"], "rejected": {}, "slots": {}}}}
posts7b, probs7b, fb7b, _ = cenario(["01.mp4", "02.mp4", "03.mp4"], st=st_esgotado2)
check("nao repete post sem autorizacao", posts7b == 0)
check("avisa que a pasta acabou", any("ja usados" in p for p in probs7b), str(probs7b))

print("\n[caso 7c] Graph API totalmente fora do ar (disjuntor)")
nomes = [f"{i:02d}.mp4" for i in range(1, 9)]
posts7c, probs7c, fb7c, _ = cenario(nomes, falhar_publish=set(nomes))
check("nao publicou nada", posts7c == 0)
check("parou depois de 3 falhas", len([p for p in probs7c if "->" in p]) == 3,
      str(len(probs7c)))
check("acionou o disjuntor", any("abortando" in p for p in probs7c), str(probs7c))

print("\n[caso 8] pasta vazia")
posts8, probs8, fb8, _ = cenario([])
check("nao publica nada", posts8 == 0)
check("avisa pasta vazia", any("vazia" in p for p in probs8), str(probs8))

print()
if falhas:
    print(f"{len(falhas)} FALHA(S): {', '.join(falhas)}")
    sys.exit(1)
print("Simulacao completa sem falhas.")
