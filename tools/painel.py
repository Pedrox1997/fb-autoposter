"""Painel local de configuracao.

    python -m tools.painel

Abre http://127.0.0.1:8765 no navegador. Serve para escolher paginas, pastas e
horarios sem editar YAML na mao. Quem publica continua sendo o GitHub Actions -
o painel so escreve o config.yaml e manda para o repositorio.

Escuta apenas em 127.0.0.1: nao fica exposto na rede.
"""
import json
import os
import re
import subprocess
import sys
import threading
import webbrowser
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from urllib.parse import parse_qs, urlparse

sys.path.insert(0, __file__.rsplit("tools", 1)[0])

import yaml  # noqa: E402

from src import config, facebook, state  # noqa: E402
from src.sources import rclone  # noqa: E402

RAIZ = config.ROOT
CONFIG_YAML = os.path.join(RAIZ, "config.yaml")
ENV_LOCAL = os.path.join(RAIZ, ".env")
HTML = os.path.join(os.path.dirname(os.path.abspath(__file__)), "painel.html")
PORTA = 8765

FUSOS = [
    ("Brasil", "America/Sao_Paulo"),
    ("EUA - leste", "America/New_York"),
    ("EUA - oeste", "America/Los_Angeles"),
    ("Mexico", "America/Mexico_City"),
    ("Espanha", "Europe/Madrid"),
    ("Franca", "Europe/Paris"),
    ("Italia", "Europe/Rome"),
    ("Alemanha", "Europe/Berlin"),
    ("Portugal", "Europe/Lisbon"),
    ("Reino Unido", "Europe/London"),
]


# --------------------------------------------------------------- utilidades

MAX_PERFIS = 20

# Login do Facebook: o usuario autoriza numa tela e o painel recebe o token,
# em vez de ele copiar do Graph API Explorer na mao.
REDIRECT_URI = f"http://localhost:{PORTA}/oauth/retorno"
ESCOPOS = "pages_show_list,pages_read_engagement,pages_manage_posts"
GRAPH_OAUTH = "https://graph.facebook.com/v23.0/oauth/access_token"
DIALOGO = "https://www.facebook.com/v23.0/dialog/oauth"


def salvar_env(chave, valor):
    linhas = []
    if os.path.exists(ENV_LOCAL):
        with open(ENV_LOCAL, "r", encoding="utf-8") as f:
            linhas = [ln for ln in f.read().splitlines()
                      if ln.strip() and not ln.startswith(f"{chave}=")]
    linhas.append(f"{chave}={valor}")
    with open(ENV_LOCAL, "w", encoding="utf-8") as f:
        f.write("\n".join(linhas) + "\n")
    os.environ[chave] = valor


def app_configurado():
    config._carregar_env_local()
    return bool(os.environ.get("FB_APP_ID") and os.environ.get("FB_APP_SECRET"))


def url_login(slot):
    """Endereco da tela de autorizacao do Facebook."""
    from urllib.parse import urlencode
    if not app_configurado():
        return None
    parametros = {
        "client_id": os.environ["FB_APP_ID"],
        "redirect_uri": REDIRECT_URI,
        "scope": ESCOPOS,
        "response_type": "code",
        "state": slot,
        # forca a tela de escolha de paginas mesmo se ja autorizou antes
        "auth_type": "rerequest",
    }
    return f"{DIALOGO}?{urlencode(parametros)}"


def trocar_codigo(codigo):
    """code -> token curto -> token de longa duracao."""
    import requests
    curto = requests.get(GRAPH_OAUTH, timeout=60, params={
        "client_id": os.environ["FB_APP_ID"],
        "client_secret": os.environ["FB_APP_SECRET"],
        "redirect_uri": REDIRECT_URI,
        "code": codigo,
    })
    if curto.status_code >= 400:
        raise RuntimeError(curto.json().get("error", {}).get("message", curto.text[:200]))

    longo = requests.get(GRAPH_OAUTH, timeout=60, params={
        "grant_type": "fb_exchange_token",
        "client_id": os.environ["FB_APP_ID"],
        "client_secret": os.environ["FB_APP_SECRET"],
        "fb_exchange_token": curto.json()["access_token"],
    })
    if longo.status_code >= 400:
        raise RuntimeError(longo.json().get("error", {}).get("message", longo.text[:200]))
    return longo.json()["access_token"]


def token_usuario(slot="FB_USER_TOKEN"):
    config._carregar_env_local()
    return os.environ.get(slot, "").strip()


def slots_usados():
    config._carregar_env_local()
    return config.slots_de_token()


def proximo_slot():
    """Primeiro nome livre da sequencia FB_USER_TOKEN, _2, _3..."""
    usados = set(slots_usados())
    if "FB_USER_TOKEN" not in usados:
        return "FB_USER_TOKEN"
    for n in range(2, MAX_PERFIS + 1):
        if f"FB_USER_TOKEN_{n}" not in usados:
            return f"FB_USER_TOKEN_{n}"
    return None


def perfis_conectados():
    """Cada perfil com o nome da conta e quantas paginas ele traz."""
    saida = []
    for slot in slots_usados():
        item = {"slot": slot, "nome": "?", "paginas": 0, "erro": None}
        try:
            import requests
            eu = requests.get(f"{facebook.GRAPH}/me", timeout=30,
                              params={"fields": "name", "access_token": token_usuario(slot)})
            item["nome"] = eu.json().get("name", "?") if eu.status_code < 400 else "?"
            item["paginas"] = len(facebook.page_tokens(token_usuario(slot), cache_key=slot))
        except Exception as e:
            item["erro"] = str(e)[:160]
        saida.append(item)
    return saida


def salvar_token(valor, slot="FB_USER_TOKEN"):
    if not re.fullmatch(r"FB_USER_TOKEN(_\d+)?", slot or ""):
        slot = "FB_USER_TOKEN"
    linhas = []
    if os.path.exists(ENV_LOCAL):
        with open(ENV_LOCAL, "r", encoding="utf-8") as f:
            linhas = [ln for ln in f.read().splitlines()
                      if not ln.startswith(f"{slot}=")]
    linhas.append(f"{slot}={valor}")
    with open(ENV_LOCAL, "w", encoding="utf-8") as f:
        f.write("\n".join([ln for ln in linhas if ln.strip()]) + "\n")
    os.environ[slot] = valor
    facebook._tokens_cache.pop(slot, None)
    return _mandar_secret(slot, valor)


def _mandar_secret(nome, valor):
    """Cadastra o mesmo valor como GitHub Secret, para o robo tambem ter acesso."""
    try:
        proc = subprocess.run(["gh", "secret", "set", nome], cwd=RAIZ, input=valor,
                              capture_output=True, text=True, timeout=120)
        if proc.returncode == 0:
            return {"github": "ok"}
        return {"github": "falhou", "detalhe": (proc.stderr or "")[-200:]}
    except Exception as e:
        return {"github": "falhou", "detalhe": str(e)[:200]}


def listar_paginas():
    """Junta as paginas de todos os perfis conectados, sem repetir."""
    mapa, erros = {}, []
    for slot in slots_usados():
        try:
            for pid, dados in facebook.page_tokens(token_usuario(slot), cache_key=slot).items():
                mapa.setdefault(pid, {**dados, "slot": slot})
        except Exception as e:
            erros.append(f"{slot}: {e}")

    if not mapa and not erros:
        return {"erro": "sem_token", "paginas": []}
    return {
        "erro": " | ".join(erros) if erros else None,
        "paginas": [{"id": pid, "nome": d["name"], "perfil": d.get("slot")}
                    for pid, d in sorted(mapa.items(), key=lambda kv: kv[1]["name"].lower())],
    }


LINHA_LSD = re.compile(r"^\s*-?\d+\s+\S+\s+\S+\s+(\d+)\s+(.*)$")


def listar_pastas(caminho):
    """Subpastas com a quantidade de itens dentro de cada uma.

    Usa 'lsd' em vez de 'lsjson' porque ele ja traz a contagem de objetos de
    graca - assim da para ver onde tem conteudo sem abrir pasta por pasta.
    """
    caminho = (caminho or "onedrive:").strip()
    try:
        saida = rclone._run(["lsd", caminho], 300)
    except Exception as e:
        return {"erro": str(e), "pastas": []}

    pastas = []
    for linha in saida.splitlines():
        casou = LINHA_LSD.match(linha)
        if casou:
            pastas.append({"nome": casou.group(2).strip(), "itens": int(casou.group(1))})
    pastas.sort(key=lambda p: p["nome"].lower())
    return {"caminho": caminho, "pastas": pastas}


def contar_videos(caminho):
    try:
        origem = rclone.RcloneSource(caminho)
        videos = origem.list_videos()
        return {"total": len(videos),
                "exemplos": [v.name for v in videos[:3]],
                "mb": round(sum(v.size or 0 for v in videos) / 1e6, 1)}
    except Exception as e:
        return {"erro": str(e), "total": 0, "exemplos": []}


def listar_remotes():
    """Contas de nuvem configuradas no rclone (onedrive, onedrive2, gdrive...)."""
    try:
        saida = rclone._run(["listremotes"], 60)
    except Exception:
        return []
    return [linha.strip().rstrip(":") for linha in saida.splitlines() if linha.strip()]


# Conexao de uma conta de nuvem pelo navegador, no mesmo espirito do "+ Perfil"
# do Facebook: o rclone abre a tela da Microsoft e devolve o token.
CONEXAO = {"estado": "parado", "mensagem": "", "remote": ""}


def _proximo_remote(base="onedrive"):
    existentes = set(listar_remotes())
    if base not in existentes:
        return base
    for n in range(2, 50):
        if f"{base}{n}" not in existentes:
            return f"{base}{n}"
    return None


def _extrair_token(saida):
    """O rclone imprime o token entre marcadores de 'paste'."""
    inicio = saida.find("{")
    fim = saida.rfind("}")
    if inicio == -1 or fim == -1 or fim < inicio:
        raise RuntimeError("O rclone não devolveu o token da conta.")
    trecho = saida[inicio:fim + 1]
    json.loads(trecho)  # valida
    return trecho


def _dados_do_drive(token_json):
    """drive_id e tipo, lidos da propria conta autorizada."""
    import requests
    acesso = json.loads(token_json).get("access_token", "")
    resposta = requests.get("https://graph.microsoft.com/v1.0/me/drive", timeout=60,
                            headers={"Authorization": f"Bearer {acesso}"})
    if resposta.status_code >= 400:
        raise RuntimeError(f"Não consegui identificar o OneDrive ({resposta.status_code}).")
    corpo = resposta.json()
    return corpo.get("id", ""), corpo.get("driveType", "personal")


def _conectar_nuvem(nome):
    """Roda em segundo plano: autoriza no navegador e grava o remote."""
    try:
        CONEXAO.update(estado="aguardando",
                       mensagem="Autorize a conta na janela do navegador que abriu.",
                       remote=nome)
        proc = subprocess.run([rclone.binario(), "authorize", "onedrive"],
                              capture_output=True, text=True, timeout=600,
                              encoding="utf-8", errors="replace")
        if proc.returncode != 0:
            raise RuntimeError((proc.stderr or "")[-300:] or "autorização cancelada")

        token = _extrair_token(proc.stdout + proc.stderr)
        CONEXAO.update(estado="salvando", mensagem="Autorizado. Identificando a conta…")

        drive_id, drive_type = _dados_do_drive(token)
        criar = [rclone.binario(), "config", "create", nome, "onedrive",
                 "token", token, "drive_id", drive_id, "drive_type", drive_type]
        conf = rclone._conf()
        if conf:
            criar[1:1] = ["--config", conf]
        feito = subprocess.run(criar, capture_output=True, text=True, timeout=120,
                               encoding="utf-8", errors="replace")
        if feito.returncode != 0:
            raise RuntimeError((feito.stderr or "")[-300:])

        _sincronizar_rclone_conf()
        CONEXAO.update(estado="ok", mensagem=f"Conta conectada como '{nome}'.")
    except Exception as e:
        CONEXAO.update(estado="erro", mensagem=str(e)[:300])


def _sincronizar_rclone_conf():
    """Manda a configuracao do rclone para o secret, para o robo enxergar a conta nova."""
    caminho = rclone._conf() or rclone._conf_do_usuario()
    if not caminho or not os.path.exists(caminho):
        return
    with open(caminho, "r", encoding="utf-8") as f:
        _mandar_secret("RCLONE_CONF", f.read())


def iniciar_conexao_nuvem():
    if CONEXAO["estado"] in ("aguardando", "salvando"):
        return {"ok": False, "erro": "Já existe uma conexão em andamento."}
    nome = _proximo_remote()
    if not nome:
        return {"ok": False, "erro": "Limite de contas atingido."}
    threading.Thread(target=_conectar_nuvem, args=(nome,), daemon=True).start()
    return {"ok": True, "remote": nome}


def _gh(*args):
    proc = subprocess.run(["gh", *args], cwd=RAIZ, capture_output=True,
                          text=True, timeout=120, encoding="utf-8", errors="replace")
    return proc.stdout if proc.returncode == 0 else ""


def ultimo_run():
    """Status da ultima execucao do robo no GitHub."""
    bruto = _gh("run", "list", "--limit", "1", "--json",
                "databaseId,status,conclusion,createdAt,url")
    try:
        itens = json.loads(bruto or "[]")
    except json.JSONDecodeError:
        return None
    return itens[0] if itens else None


def resumo():
    """Numeros do topo do painel. Nao toca na nuvem: e instantaneo."""
    from datetime import datetime, timezone
    cfg_bruto = ler_config()
    st = state.load()
    agora = datetime.now(timezone.utc)

    agendados, publicados_hoje = 0, 0
    for dados in st.get("pages", {}).values():
        for chave, item in dados.get("slots", {}).items():
            quando = item.get("scheduled_for") or ""
            try:
                momento = datetime.fromisoformat(quando)
            except ValueError:
                continue
            if momento.tzinfo is None:
                momento = momento.replace(tzinfo=timezone.utc)
            if momento > agora:
                agendados += 1
            elif momento.date() == agora.date():
                publicados_hoje += 1

    return {
        "paginas": len(cfg_bruto.get("pages", [])),
        "agendados": agendados,
        "publicados_hoje": publicados_hoje,
        "total_publicado": sum(len(d.get("used_files", []))
                               for d in st.get("pages", {}).values()),
        "ultimo_run": ultimo_run(),
    }


def estoque():
    """Quantos videos restam por pagina e por quantos dias dao. Consulta a nuvem."""
    st = state.load()
    saida = []
    for pagina in ler_config().get("pages", []):
        nome = pagina.get("name", "?")
        caminho = pagina.get("source") or ""
        slug = "".join(c if c.isalnum() else "-" for c in nome.lower()).strip("-")
        usados = set(st.get("pages", {}).get(slug, {}).get("used_files", []))
        por_dia = len(pagina.get("times") or ler_config().get("defaults", {}).get("times") or [])

        item = {"pagina": nome, "restantes": 0, "total": 0, "dias": None, "erro": None}
        try:
            videos = rclone.RcloneSource(caminho).list_videos()
            item["total"] = len(videos)
            item["restantes"] = len([v for v in videos if v.id not in usados])
            if por_dia:
                item["dias"] = round(item["restantes"] / por_dia, 1)
        except Exception as e:
            item["erro"] = str(e)[:160]
        saida.append(item)
    return {"paginas": saida}


def fila():
    """O que ja esta agendado e quais horarios vem em seguida."""
    from datetime import datetime, timedelta, timezone
    cfg = None
    try:
        cfg = config.load(CONFIG_YAML)
    except SystemExit:
        pass
    except Exception as e:
        return {"erro": str(e)[:200], "agendados": [], "previstos": []}

    st = state.load()
    agora = datetime.now(timezone.utc)

    agendados = []
    for slug, dados in st.get("pages", {}).items():
        for item in dados.get("slots", {}).values():
            try:
                momento = datetime.fromisoformat(item.get("scheduled_for") or "")
            except ValueError:
                continue
            if momento.tzinfo is None:
                momento = momento.replace(tzinfo=timezone.utc)
            if momento > agora:
                agendados.append({"pagina": slug, "quando": momento.isoformat(),
                                  "arquivo": item.get("file", ""),
                                  "post_id": item.get("post_id", "")})
    agendados.sort(key=lambda i: i["quando"])

    previstos = []
    if cfg:
        for pagina in cfg.pages:
            ocupados = set(st.get("pages", {}).get(pagina.slug, {}).get("slots", {}))
            for quando in config.upcoming_slots(pagina, agora, 72):
                if quando.isoformat() not in ocupados:
                    previstos.append({"pagina": pagina.name, "quando": quando.isoformat()})
    previstos.sort(key=lambda i: i["quando"])

    return {"agendados": agendados[:20], "previstos": previstos[:20]}


def rodar_agora(teste=False):
    args = ["workflow", "run", "autopost.yml"]
    if teste:
        args += ["-f", "teste_um_video=true", "-f", "dry_run=false"]
    saida = _gh(*args)
    return {"ok": bool(saida) or True,
            "mensagem": "Execução disparada. Acompanhe em Actions.",
            "url": "https://github.com/Pedrox1997/fb-autoposter/actions"}


def ler_config():
    with open(CONFIG_YAML, "r", encoding="utf-8") as f:
        return yaml.safe_load(f) or {}


def escrever_config(dados):
    """Reescreve o config.yaml preservando as chaves globais existentes."""
    atual = ler_config()
    atual["timezone"] = dados.get("timezone", atual.get("timezone", "America/Sao_Paulo"))
    atual["defaults"] = dados.get("defaults", atual.get("defaults", {}))
    atual["grupos"] = dados.get("grupos", [])
    atual["pages"] = dados.get("pages", [])
    if not atual["pages"]:
        atual.pop("pages", None)

    total = sum(len(g.get("paginas", [])) for g in atual["grupos"]) + len(atual.get("pages", []))

    with open(CONFIG_YAML, "w", encoding="utf-8") as f:
        f.write("# Gerado pelo painel (python -m tools.painel).\n"
                "# Cada 'grupo' e uma etiqueta: as paginas dela dividem a mesma pasta,\n"
                "# sem que o mesmo video se repita numa pagina.\n\n")
        yaml.safe_dump(atual, f, allow_unicode=True, sort_keys=False, width=120)
    return {"ok": True, "paginas": total, "etiquetas": len(atual["grupos"])}


def git(*args, timeout=180):
    return subprocess.run(["git", "-C", RAIZ, *args],
                          capture_output=True, text=True, timeout=timeout)


def publicar_no_github():
    add = git("add", "config.yaml")
    if add.returncode != 0:
        return {"ok": False, "erro": add.stderr[-300:]}

    if git("diff", "--cached", "--quiet").returncode == 0:
        return {"ok": True, "mensagem": "Nada mudou desde o ultimo envio."}

    com = git("commit", "-m", "painel: atualiza configuracao das paginas")
    if com.returncode != 0:
        return {"ok": False, "erro": com.stdout[-300:] or com.stderr[-300:]}

    git("pull", "--rebase", "--autostash", "origin", "main")
    push = git("push", "origin", "main")
    if push.returncode != 0:
        return {"ok": False, "erro": push.stderr[-400:]}
    return {"ok": True, "mensagem": "Configuracao enviada. O robo ja usa a partir do proximo horario."}


def testar_pagina(nome):
    ambiente = {**os.environ, "TESTE_ESCOLHA": "menor"}
    proc = subprocess.run(
        [sys.executable, "-m", "tools.testar_post", nome],
        cwd=RAIZ, capture_output=True, text=True, timeout=1800, env=ambiente,
    )
    return {"ok": proc.returncode == 0, "saida": (proc.stdout + proc.stderr)[-4000:]}


# ------------------------------------------------------------------ servidor

class Painel(BaseHTTPRequestHandler):
    def _responder(self, dados, status=200):
        corpo = json.dumps(dados, ensure_ascii=False).encode("utf-8")
        self.send_response(status)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Content-Length", str(len(corpo)))
        self.end_headers()
        self.wfile.write(corpo)

    def do_GET(self):
        rota = urlparse(self.path)
        query = parse_qs(rota.query)

        if rota.path in ("/", "/index.html"):
            with open(HTML, "rb") as f:
                corpo = f.read()
            self.send_response(200)
            self.send_header("Content-Type", "text/html; charset=utf-8")
            self.send_header("Content-Length", str(len(corpo)))
            self.end_headers()
            self.wfile.write(corpo)
            return

        if rota.path == "/api/estado":
            return self._responder({
                "tem_token": bool(slots_usados()),
                "perfis": perfis_conectados(),
                "proximo_slot": proximo_slot(),
                "app_ok": app_configurado(),
                "redirect_uri": REDIRECT_URI,
                "tem_rclone": bool(_rclone_ok()),
                "fusos": [{"nome": n, "tz": t} for n, t in FUSOS],
                "config": ler_config(),
            })

        if rota.path == "/api/paginas":
            return self._responder(listar_paginas())

        if rota.path == "/oauth/entrar":
            slot = query.get("slot", [""])[0] or proximo_slot()
            destino = url_login(slot)
            if not destino:
                return self._responder({"erro": "app nao configurado"}, 400)
            self.send_response(302)
            self.send_header("Location", destino)
            self.end_headers()
            return

        if rota.path == "/oauth/retorno":
            return self._retorno_oauth(query)

        if rota.path == "/api/pastas":
            return self._responder(listar_pastas(query.get("caminho", [""])[0]))

        if rota.path == "/api/contar":
            return self._responder(contar_videos(query.get("caminho", [""])[0]))

        if rota.path == "/api/resumo":
            return self._responder(resumo())

        if rota.path == "/api/estoque":
            return self._responder(estoque())

        if rota.path == "/api/fila":
            return self._responder(fila())

        if rota.path == "/api/remotes":
            return self._responder({"remotes": listar_remotes()})

        if rota.path == "/api/nuvem/status":
            return self._responder(dict(CONEXAO, remotes=listar_remotes()))

        self._responder({"erro": "rota desconhecida"}, 404)

    def _pagina_simples(self, titulo, texto, cor="#0e8a4f"):
        corpo = f"""<!doctype html><meta charset="utf-8">
        <body style="font:16px system-ui;padding:40px;max-width:620px;margin:auto">
        <h2 style="color:{cor}">{titulo}</h2><p>{texto}</p>
        <p><a href="/">Voltar ao painel</a></p>
        <script>setTimeout(()=>location.href="/", 2500)</script></body>""".encode("utf-8")
        self.send_response(200)
        self.send_header("Content-Type", "text/html; charset=utf-8")
        self.send_header("Content-Length", str(len(corpo)))
        self.end_headers()
        self.wfile.write(corpo)

    def _retorno_oauth(self, query):
        if query.get("error"):
            return self._pagina_simples(
                "Autorizacao cancelada",
                query.get("error_description", ["Você recusou a permissão."])[0], "#c0392b")

        codigo = query.get("code", [""])[0]
        slot = query.get("state", ["FB_USER_TOKEN"])[0]
        if not codigo:
            return self._pagina_simples("Faltou o código", "O Facebook não devolveu o código.",
                                        "#c0392b")
        try:
            token = trocar_codigo(codigo)
            salvar_token(token, slot)
            quantas = len(listar_paginas().get("paginas", []))
            return self._pagina_simples(
                "Perfil conectado",
                f"{quantas} página(s) disponíveis. Voltando ao painel...")
        except Exception as e:
            return self._pagina_simples("Não consegui conectar", str(e)[:400], "#c0392b")

    def do_POST(self):
        tamanho = int(self.headers.get("Content-Length") or 0)
        try:
            dados = json.loads(self.rfile.read(tamanho) or "{}")
        except json.JSONDecodeError:
            return self._responder({"erro": "json invalido"}, 400)

        rota = urlparse(self.path).path
        try:
            if rota == "/api/token":
                resultado = salvar_token(dados.get("token", "").strip(),
                                         dados.get("slot", "FB_USER_TOKEN"))
                return self._responder({"ok": True, **resultado})
            if rota == "/api/app":
                salvar_env("FB_APP_ID", dados.get("app_id", "").strip())
                salvar_env("FB_APP_SECRET", dados.get("app_secret", "").strip())
                return self._responder({"ok": True, "redirect_uri": REDIRECT_URI})
            if rota == "/api/salvar":
                return self._responder(escrever_config(dados))
            if rota == "/api/publicar":
                return self._responder(publicar_no_github())
            if rota == "/api/testar":
                return self._responder(testar_pagina(dados.get("pagina", "")))
            if rota == "/api/rodar":
                return self._responder(rodar_agora(bool(dados.get("teste"))))
            if rota == "/api/nuvem/conectar":
                return self._responder(iniciar_conexao_nuvem())
        except Exception as e:
            return self._responder({"ok": False, "erro": str(e)}, 500)

        self._responder({"erro": "rota desconhecida"}, 404)

    def log_message(self, *_):
        pass  # silencia o log de cada request


def _rclone_ok():
    try:
        rclone.binario()
        return True
    except Exception:
        return False


def main():
    endereco = f"http://127.0.0.1:{PORTA}"
    servidor = ThreadingHTTPServer(("127.0.0.1", PORTA), Painel)
    print(f"Painel no ar: {endereco}\nCtrl+C para encerrar.")
    threading.Timer(1.0, lambda: webbrowser.open(endereco)).start()
    try:
        servidor.serve_forever()
    except KeyboardInterrupt:
        print("\nEncerrado.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
