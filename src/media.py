"""Checagem previa do arquivo com ffprobe. Um video invalido e pulado antes
do upload, para nao queimar o horario com um post que o Facebook rejeitaria."""
import json
import os
import shutil
import subprocess

REEL_MIN_SEC = 3
REEL_MAX_SEC = 90
MAX_BYTES = 4 * 1024 * 1024 * 1024  # limite pratico da Graph API


def probe(path):
    if not shutil.which("ffprobe"):
        return None
    try:
        out = subprocess.run(
            ["ffprobe", "-v", "quiet", "-print_format", "json",
             "-show_format", "-show_streams", path],
            capture_output=True, text=True, timeout=120, check=True,
        ).stdout
        return json.loads(out)
    except (subprocess.SubprocessError, json.JSONDecodeError):
        return None


def escolher_formato(path):
    """Decide entre Reels e video de feed olhando o arquivo.

    Reels tem esteira de recomendacao propria e alcanca quem nao segue a
    pagina, mas so aceita ate 90s. Video de feed aceita qualquer duracao e
    fica restrito a base de seguidores. Na duvida, video - um Reels recusado
    perderia o horario.
    """
    info = probe(path)
    if not info:
        return "video", "sem ffprobe: enviando como video de feed"

    video = next((s for s in info.get("streams", []) if s.get("codec_type") == "video"), None)
    if not video:
        return "video", "sem faixa de video"

    duracao = float(info.get("format", {}).get("duration") or video.get("duration") or 0)
    largura = int(video.get("width") or 0)
    altura = int(video.get("height") or 0)
    proporcao = largura / altura if altura else 0

    if duracao > REEL_MAX_SEC:
        return "video", f"{duracao:.0f}s (acima de {REEL_MAX_SEC}s): vai como video de feed"
    if duracao < REEL_MIN_SEC:
        return "video", f"{duracao:.0f}s (abaixo de {REEL_MIN_SEC}s): vai como video de feed"
    if proporcao > 0.75:
        return "video", f"{largura}x{altura} nao e vertical: vai como video de feed"

    return "reel", f"{duracao:.0f}s vertical: vai como Reels"


def check(path, post_type):
    """Retorna (erros, avisos). Erros pulam o video; avisos so aparecem no log."""
    errors, warnings = [], []

    size = os.path.getsize(path)
    if size == 0:
        return ["arquivo vazio"], []
    if size > MAX_BYTES:
        errors.append(f"arquivo grande demais ({size / 1e9:.1f} GB)")

    info = probe(path)
    if not info:
        return errors, ["ffprobe indisponivel - enviando sem validar"]

    video = next((s for s in info.get("streams", []) if s.get("codec_type") == "video"), None)
    if not video:
        return ["sem faixa de video"], warnings

    duration = float(info.get("format", {}).get("duration") or video.get("duration") or 0)
    width = int(video.get("width") or 0)
    height = int(video.get("height") or 0)

    if post_type == "reel":
        if duration and duration < REEL_MIN_SEC:
            errors.append(f"curto demais para Reels ({duration:.1f}s, minimo {REEL_MIN_SEC}s)")
        if duration > REEL_MAX_SEC:
            # nao e erro: o publish tenta Reels e cai para video de feed sozinho
            warnings.append(f"{duration:.0f}s acima do limite de Reels - "
                            "se o Facebook recusar, vai como video de feed")
        if width and height:
            ratio = width / height
            if ratio > 0.75:
                warnings.append(f"nao e vertical ({width}x{height}) - o Facebook vai cortar")
            if height < 960:
                warnings.append(f"resolucao baixa ({width}x{height}), ideal >= 1080x1920")

    if not any(s.get("codec_type") == "audio" for s in info.get("streams", [])):
        warnings.append("video sem audio")

    return errors, warnings
