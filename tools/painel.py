"""Painel local de configuracao.

    python -m tools.painel

Abre http://127.0.0.1:8765 no navegador. Serve para escolher paginas, pastas e
horarios sem editar YAML na mao. Quem publica continua sendo o GitHub Actions -
o painel so escreve o config.yaml e manda para o repositorio.

Escuta apenas em 127.0.0.1: nao fica exposto na rede.
"""
import json
import os
import subprocess
import sys
import threading
import webbrowser
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from urllib.parse import parse_qs, urlparse

sys.path.insert(0, __file__.rsplit("tools", 1)[0])

import yaml  # noqa: E402

from src import config, facebook  # noqa: E402
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

def token_usuario():
    config._carregar_env_local()
    return os.environ.get("FB_USER_TOKEN", "").strip()


def salvar_token(valor):
    linhas = []
    if os.path.exists(ENV_LOCAL):
        with open(ENV_LOCAL, "r", encoding="utf-8") as f:
            linhas = [ln for ln in f.read().splitlines()
                      if not ln.startswith("FB_USER_TOKEN=")]
    linhas.append(f"FB_USER_TOKEN={valor}")
    with open(ENV_LOCAL, "w", encoding="utf-8") as f:
        f.write("\n".join(linhas) + "\n")
    os.environ["FB_USER_TOKEN"] = valor


def listar_paginas():
    token = token_usuario()
    if not token:
        return {"erro": "sem_token", "paginas": []}
    try:
        mapa = facebook.page_tokens(token)
    except Exception as e:
        return {"erro": str(e), "paginas": []}
    return {"paginas": [{"id": pid, "nome": d["name"]} for pid, d in sorted(
        mapa.items(), key=lambda kv: kv[1]["name"].lower())]}


def listar_pastas(caminho):
    """Subpastas de um caminho do rclone, para navegar ate a pasta dos videos."""
    caminho = (caminho or "onedrive:").strip()
    try:
        saida = rclone._run(["lsjson", "--dirs-only", caminho], 300)
        itens = json.loads(saida or "[]")
    except Exception as e:
        return {"erro": str(e), "pastas": []}
    return {
        "caminho": caminho,
        "pastas": sorted([i["Name"] for i in itens], key=str.lower),
    }


def contar_videos(caminho):
    try:
        origem = rclone.RcloneSource(caminho)
        videos = origem.list_videos()
        return {"total": len(videos),
                "exemplos": [v.name for v in videos[:3]],
                "mb": round(sum(v.size or 0 for v in videos) / 1e6, 1)}
    except Exception as e:
        return {"erro": str(e), "total": 0, "exemplos": []}


def ler_config():
    with open(CONFIG_YAML, "r", encoding="utf-8") as f:
        return yaml.safe_load(f) or {}


def escrever_config(dados):
    """Reescreve o config.yaml preservando as chaves globais existentes."""
    atual = ler_config()
    atual["timezone"] = dados.get("timezone", atual.get("timezone", "America/Sao_Paulo"))
    atual["defaults"] = dados.get("defaults", atual.get("defaults", {}))
    atual["pages"] = dados.get("pages", [])

    with open(CONFIG_YAML, "w", encoding="utf-8") as f:
        f.write("# Gerado pelo painel (python -m tools.painel).\n"
                "# Pode editar na mao: o painel le o que estiver aqui.\n\n")
        yaml.safe_dump(atual, f, allow_unicode=True, sort_keys=False, width=120)
    return {"ok": True, "paginas": len(atual["pages"])}


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
                "tem_token": bool(token_usuario()),
                "tem_rclone": bool(_rclone_ok()),
                "fusos": [{"nome": n, "tz": t} for n, t in FUSOS],
                "config": ler_config(),
            })

        if rota.path == "/api/paginas":
            return self._responder(listar_paginas())

        if rota.path == "/api/pastas":
            return self._responder(listar_pastas(query.get("caminho", [""])[0]))

        if rota.path == "/api/contar":
            return self._responder(contar_videos(query.get("caminho", [""])[0]))

        self._responder({"erro": "rota desconhecida"}, 404)

    def do_POST(self):
        tamanho = int(self.headers.get("Content-Length") or 0)
        try:
            dados = json.loads(self.rfile.read(tamanho) or "{}")
        except json.JSONDecodeError:
            return self._responder({"erro": "json invalido"}, 400)

        rota = urlparse(self.path).path
        try:
            if rota == "/api/token":
                salvar_token(dados.get("token", "").strip())
                return self._responder({"ok": True})
            if rota == "/api/salvar":
                return self._responder(escrever_config(dados))
            if rota == "/api/publicar":
                return self._responder(publicar_no_github())
            if rota == "/api/testar":
                return self._responder(testar_pagina(dados.get("pagina", "")))
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
