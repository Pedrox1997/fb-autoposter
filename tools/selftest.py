"""Testes da logica pura (sem rede): horarios, links, legendas, estado.

    python -m tools.selftest
"""
import os
import sys
import tempfile
from datetime import datetime, time as dtime
from zoneinfo import ZoneInfo

sys.path.insert(0, __file__.rsplit("tools", 1)[0])

from src import config, state  # noqa: E402
from src.sources import base  # noqa: E402
from src.sources.gdrive import folder_id_from  # noqa: E402
from src.sources.onedrive import OneDriveSource, _share_id  # noqa: E402

TZ = ZoneInfo("America/Sao_Paulo")
falhas = []


def check(nome, cond, detalhe=""):
    print(f"  {'ok  ' if cond else 'FALHA'} {nome} {detalhe if not cond else ''}")
    if not cond:
        falhas.append(nome)


def page(**kw):
    defaults = dict(
        name="Teste", page_id="1", token="t", source_type="gdrive", source_ref="abc",
        tz=TZ, post_type="reel", times=[dtime(9, 0), dtime(13, 0), dtime(19, 30)],
        default_caption="", hashtags="", order="name",
    )
    defaults.update(kw)
    return config.Page(**defaults)


print("\n[horarios]")
p = page()
agora = datetime(2026, 7, 31, 10, 0, tzinfo=TZ)

slots = config.upcoming_slots(p, agora, 30)
check("so pega horarios futuros", all(s > agora for s in slots))
check("ordem cronologica", slots == sorted(slots))
check("13:00 de hoje e o primeiro", slots[0] == datetime(2026, 7, 31, 13, 0, tzinfo=TZ),
      f"veio {slots[0]}")
check("respeita o horizonte de 30h", all((s - agora).total_seconds() <= 30 * 3600 for s in slots))
check("nao repete horario", len(slots) == len(set(slots)))

virada = datetime(2026, 7, 31, 23, 50, tzinfo=TZ)
slots_virada = config.upcoming_slots(p, virada, 30)
check("atravessa a meia-noite", slots_virada[0] == datetime(2026, 8, 1, 9, 0, tzinfo=TZ),
      f"veio {slots_virada[0]}")

check("due_slot pega o horario vencido",
      config.due_slot(p, datetime(2026, 7, 31, 13, 20, tzinfo=TZ), 45)
      == datetime(2026, 7, 31, 13, 0, tzinfo=TZ))
check("due_slot ignora fora da tolerancia",
      config.due_slot(p, datetime(2026, 7, 31, 15, 0, tzinfo=TZ), 45) is None)
check("due_slot pega 19:30 de ontem apos a meia-noite",
      config.due_slot(page(times=[dtime(23, 50)]),
                      datetime(2026, 8, 1, 0, 20, tzinfo=TZ), 45)
      == datetime(2026, 7, 31, 23, 50, tzinfo=TZ))

print("\n[fuso por pagina]")
NY = ZoneInfo("America/New_York")
MX = ZoneInfo("America/Mexico_City")
usa = page(name="USA", tz=NY, times=[dtime(19, 0)])
br = page(name="BR", tz=TZ, times=[dtime(19, 0)])

# 10:00 em Brasilia = 09:00 em NY, entao as 19:00 de NY ainda estao por vir
slot_usa = config.upcoming_slots(usa, agora, 30)[0]
slot_br = config.upcoming_slots(br, agora, 30)[0]
check("19:00 da pagina dos EUA e no fuso de NY", slot_usa.hour == 19 and slot_usa.tzinfo is NY)
check("mesmo horario no config, instantes diferentes", slot_usa != slot_br)
check("EUA publica 1h depois do Brasil (horario de verao)",
      (slot_usa - slot_br).total_seconds() == 3600,
      f"diferenca de {(slot_usa - slot_br).total_seconds() / 3600}h")
check("fuso do Mexico tambem funciona",
      config.upcoming_slots(page(tz=MX, times=[dtime(19, 0)]), agora, 30)[0].tzinfo is MX)

# O robo roda em UTC no GitHub: o horario local da pagina tem que sair igual
utc_now = agora.astimezone(ZoneInfo("UTC"))
check("resultado nao muda se o robo roda em UTC",
      config.upcoming_slots(usa, utc_now, 30)[0] == slot_usa)

check("aceita horario 9:00 sem zero", config._parse_time("9:5") == dtime(9, 5))
check("aceita time do YAML", config._parse_time(dtime(7, 30)) == dtime(7, 30))

print("\n[deteccao de fonte]")
check("id puro -> gdrive", config._detect_source("auto", "1A2b3C") == "gdrive")
check("link do drive -> gdrive",
      config._detect_source("auto", "https://drive.google.com/drive/folders/1A2b") == "gdrive")
check("1drv.ms -> onedrive", config._detect_source("auto", "https://1drv.ms/f/s!abc") == "onedrive")
check("onedrive.live -> onedrive",
      config._detect_source("auto", "https://onedrive.live.com/?id=x") == "onedrive")
check("tipo explicito vence", config._detect_source("onedrive", "1A2b3C") == "onedrive")

print("\n[links]")
check("extrai id de /folders/", folder_id_from("https://drive.google.com/drive/folders/1AbC_-9?usp=sharing") == "1AbC_-9")
check("extrai id de ?id=", folder_id_from("https://drive.google.com/open?id=1XyZ") == "1XyZ")
check("id puro passa direto", folder_id_from("1XyZ") == "1XyZ")
tok = _share_id("https://1drv.ms/f/s!AbC")
check("share id do onedrive comeca com u!", tok.startswith("u!"))
check("share id sem padding", not tok.endswith("="))
check("share id e base64url (sem + nem /)", "+" not in tok and "/" not in tok[2:])

print("\n[onedrive: link x caminho]")
por_link = OneDriveSource("https://1drv.ms/f/c/123/AbC")
por_caminho = OneDriveSource("/Videos/Daily Blessings")
check("link vira endpoint de shares", "/shares/u!" in por_link._base_url())
check("caminho vira endpoint do proprio drive",
      por_caminho._base_url().endswith("/me/drive/root:/Videos/Daily Blessings:"),
      por_caminho._base_url())
check("caminho tolera barra no inicio e no fim",
      OneDriveSource("/Videos/")._base_url() == OneDriveSource("Videos")._base_url())

print("\n[legendas]")
item = base.Item(id="1", name="historia_da_vovo.mp4")
check("usa o .txt da pasta",
      base.caption_for(item, {"historia_da_vovo": "Legenda propria"}, page()) == "Legenda propria")
check("cai no default", base.caption_for(item, {}, page(default_caption="Padrao")) == "Padrao")
check("sem nada, limpa o nome do arquivo",
      base.caption_for(item, {}, page()) == "historia da vovo")
com_tags = base.caption_for(item, {}, page(default_caption="Oi", hashtags="#fe"))
check("anexa hashtags", com_tags == "Oi\n\n#fe", repr(com_tags))
check("nao duplica hashtags",
      base.caption_for(item, {"historia_da_vovo": "Oi #fe"}, page(hashtags="#fe")) == "Oi #fe")
check("corta em 2200 chars",
      len(base.caption_for(item, {"historia_da_vovo": "x" * 5000}, page())) == 2200)

print("\n[ordenacao]")
itens = [base.Item(id="c", name="03.mp4", created="2026-01-03"),
         base.Item(id="a", name="01.mp4", created="2026-01-02"),
         base.Item(id="b", name="02.mp4", created="2026-01-01")]
check("por nome", [i.name for i in base.sort_items(itens, "name")] == ["01.mp4", "02.mp4", "03.mp4"])
check("por data", [i.name for i in base.sort_items(itens, "created")] == ["02.mp4", "01.mp4", "03.mp4"])
check("random_stable e deterministico",
      base.sort_items(itens, "random_stable") == base.sort_items(itens, "random_stable"))

print("\n[estado]")
tmp = tempfile.mkdtemp()
state.STATE_PATH = os.path.join(tmp, "posted.json")
st = state.load()
check("comeca vazio", st == {"pages": {}})
state.record(st, "pag", "2026-07-31T09:00", "vid1", "a.mp4", "post1", "2026-07-31T09:00")
state.record(st, "pag", "2026-07-31T09:00", "vid1", "a.mp4", "post1", "2026-07-31T09:00")
check("nao duplica o video usado", state.used_file_ids(st, "pag") == {"vid1"})
check("horario marcado como ocupado", state.slot_taken(st, "pag", "2026-07-31T09:00"))
check("outro horario segue livre", not state.slot_taken(st, "pag", "2026-07-31T13:00"))
state.mark_rejected(st, "pag", "vid2", "b.mp4", ["curto demais"])
check("rejeitado fica registrado", state.rejected_ids(st, "pag") == {"vid2"})
state.save(st)
recarregado = state.load()
check("sobrevive ao salvar/recarregar", state.used_file_ids(recarregado, "pag") == {"vid1"})
state.reset_used(recarregado, "pag")
check("reciclagem limpa os usados", state.used_file_ids(recarregado, "pag") == set())
check("reciclagem preserva os rejeitados", state.rejected_ids(recarregado, "pag") == {"vid2"})

for i in range(600):
    state.record(recarregado, "p2", f"2026-01-01T{i:04d}", f"v{i}", "x.mp4", "id", "w")
state.prune_slots(recarregado, "p2", keep=500)
check("prune limita o historico", len(recarregado["pages"]["p2"]["slots"]) == 500)

print("\n[secrets]")
os.environ["ALL_SECRETS"] = '{"PAGE1_ID": "123", "PAGE1_TOKEN": "abc"}'
config._bootstrap_secrets()
check("injeta secrets no ambiente", os.environ.get("PAGE1_ID") == "123")
check("consome ALL_SECRETS", "ALL_SECRETS" not in os.environ)
os.environ["ALL_SECRETS"] = "{quebrado"
config._bootstrap_secrets()
check("nao quebra com json invalido", True)

print()
if falhas:
    print(f"{len(falhas)} FALHA(S): {', '.join(falhas)}")
    sys.exit(1)
print("Todos os testes passaram.")
