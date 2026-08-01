"""Acesso a nuvem via rclone.

Escolhido depois que a Microsoft passou a exigir app registrado no Azure para
ler o OneDrive - e a conta pessoal do usuario nao pode registrar app. O rclone
tem registro proprio na Microsoft e resolve a autenticacao sozinho, alem de ja
trazer retomada de download, retry e controle de banda.

PAGE1_SOURCE vira o caminho no remote, ex: "onedrive:Videos/Daily Blessings".
"""
import glob
import json
import os
import shutil
import subprocess

from .base import Item, local_path, sort_items, ROOT

VIDEO_EXT = (".mp4", ".mov", ".m4v", ".webm", ".avi", ".mkv")
CONF_PATH = os.path.join(ROOT, "rclone.conf")
TIMEOUT_LIST = 300
TIMEOUT_DOWNLOAD = 3600

# Lixo de sincronizacao do OneDrive/Office: sao copias dos videos reais e
# fariam o robo postar o mesmo conteudo duas vezes.
PREFIXOS_TEMPORARIOS = ("~tmp", "~$", ".~", "._")
SUFIXOS_TEMPORARIOS = (".partial", ".tmp", ".crdownload", ".download")

_conf_pronto = None
_binario_cache = []


def descartavel(nome):
    baixo = nome.lower()
    return (baixo.startswith(PREFIXOS_TEMPORARIOS)
            or baixo.endswith(SUFIXOS_TEMPORARIOS))


def binario():
    """Caminho do rclone. Nao depende so do PATH: no Windows o winget instala
    numa pasta que nem todo shell enxerga."""
    if _binario_cache:
        return _binario_cache[0]

    candidatos = [os.environ.get("RCLONE_BIN", "").strip(), shutil.which("rclone")]

    local = os.environ.get("LOCALAPPDATA", "")
    if local:
        candidatos.append(os.path.join(local, "Microsoft", "WinGet", "Links", "rclone.exe"))
        candidatos += glob.glob(os.path.join(
            local, "Microsoft", "WinGet", "Packages", "Rclone.Rclone*", "*", "rclone.exe"))

    for programas in (os.environ.get("ProgramFiles"), os.environ.get("ProgramFiles(x86)")):
        if programas:
            candidatos.append(os.path.join(programas, "rclone", "rclone.exe"))
    candidatos += ["/usr/bin/rclone", "/usr/local/bin/rclone"]

    for caminho in candidatos:
        if caminho and os.path.exists(caminho):
            _binario_cache.append(caminho)
            return caminho

    raise RuntimeError(
        "rclone nao encontrado. Instale com: winget install Rclone.Rclone "
        "(ou aponte a variavel RCLONE_BIN para o executavel)."
    )


def _conf_do_usuario():
    """Configuracao que o proprio rclone criou na maquina (uso local)."""
    candidatos = []
    if os.environ.get("APPDATA"):
        candidatos.append(os.path.join(os.environ["APPDATA"], "rclone", "rclone.conf"))
    lar = os.path.expanduser("~")
    candidatos += [
        os.path.join(lar, ".config", "rclone", "rclone.conf"),
        os.path.join(lar, ".rclone.conf"),
    ]
    for caminho in candidatos:
        if os.path.exists(caminho) and os.path.getsize(caminho) > 0:
            return caminho
    return None


def _conf():
    """Caminho do rclone.conf, ou None para deixar o rclone usar o padrao dele.

    No GitHub o conteudo vem do secret RCLONE_CONF; na maquina do usuario
    aproveita a configuracao que o 'rclone config' ja criou.
    """
    global _conf_pronto
    if _conf_pronto:
        return _conf_pronto if _conf_pronto != "padrao" else None

    if os.path.exists(CONF_PATH) and os.path.getsize(CONF_PATH) > 0:
        _conf_pronto = CONF_PATH
        return CONF_PATH

    conteudo = os.environ.get("RCLONE_CONF", "").strip()
    if conteudo:
        with open(CONF_PATH, "w", encoding="utf-8") as f:
            f.write(conteudo + "\n")
        os.chmod(CONF_PATH, 0o600)
        _conf_pronto = CONF_PATH
        return CONF_PATH

    if _conf_do_usuario():
        _conf_pronto = "padrao"
        return None

    raise RuntimeError(
        "Nenhuma configuracao do rclone encontrada. Rode 'rclone config' nesta "
        "maquina, ou cadastre o secret RCLONE_CONF no GitHub."
    )


def _run(args, timeout):
    conf = _conf()
    cmd = [binario()]
    if conf:
        cmd += ["--config", conf]
    cmd += ["--retries", "5", "--low-level-retries", "10", "--timeout", "120s"] + args
    # encoding explicito: no Windows o padrao e a codepage local (cp1252) e os
    # nomes com emoji quebram a decodificacao - silenciosamente, devolvendo vazio.
    proc = subprocess.run(cmd, capture_output=True, text=True, timeout=timeout,
                          encoding="utf-8", errors="replace")
    if proc.returncode != 0:
        erro = (proc.stderr or proc.stdout or "").strip()[-600:]
        raise RuntimeError(f"rclone falhou ({proc.returncode}): {erro}")
    return proc.stdout


class RcloneSource:
    label = "rclone"

    def __init__(self, ref, order="name"):
        self.remote = ref.strip().rstrip("/")
        if ":" not in self.remote:
            raise ValueError(
                f"Caminho invalido para rclone: '{ref}'. Use o formato "
                "'onedrive:Pasta/Subpasta'."
            )
        self.order = order
        self._cache = None

    def _entries(self):
        if self._cache is None:
            saida = _run(["lsjson", "--files-only", self.remote], TIMEOUT_LIST)
            self._cache = json.loads(saida or "[]")
        return self._cache

    def list_videos(self):
        brutos = [f for f in self._entries() if f["Name"].lower().endswith(VIDEO_EXT)]
        validos = [f for f in brutos if not descartavel(f["Name"])]

        descartados = len(brutos) - len(validos)
        if descartados:
            print(f"    {descartados} arquivo(s) temporario(s) do OneDrive ignorado(s)")

        itens = [
            Item(
                id=f.get("ID") or f["Path"],
                name=f["Name"],
                size=int(f.get("Size") or 0),
                created=f.get("ModTime", ""),
                extra={"path": f["Path"]},
            )
            for f in validos
        ]
        return sort_items(itens, self.order)

    def captions(self):
        legendas = {}
        for f in self._entries():
            if not f["Name"].lower().endswith(".txt"):
                continue
            try:
                texto = _run(["cat", f"{self.remote}/{f['Path']}"], TIMEOUT_LIST)
                legendas[os.path.splitext(f["Name"])[0].lower()] = texto.strip()
            except Exception as e:
                print(f"    ! falha lendo legenda {f['Name']}: {e}")
        return legendas

    def download(self, item):
        dest = local_path(item)
        if os.path.exists(dest) and os.path.getsize(dest) > 0:
            return dest

        origem = f"{self.remote}/{(item.extra or {}).get('path', item.name)}"
        _run(["copyto", origem, dest, "--stats-one-line", "--stats", "30s"],
             TIMEOUT_DOWNLOAD)

        if not os.path.exists(dest) or os.path.getsize(dest) == 0:
            raise RuntimeError(f"rclone nao trouxe o arquivo {item.name}")
        return dest
