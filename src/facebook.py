"""Publicacao na Graph API: Reels e video de feed, com upload retomavel,
retry em erro transitorio e agendamento nativo do Facebook."""
import os
import time

import requests

VERSION = os.environ.get("FB_API_VERSION", "v23.0")
GRAPH = f"https://graph.facebook.com/{VERSION}"
GRAPH_VIDEO = f"https://graph-video.facebook.com/{VERSION}"
TIMEOUT = 300
CHUNK = 8 * 1024 * 1024

# Erros que valem nova tentativa (instabilidade, limite temporario, timeout)
RETRYABLE_CODES = {1, 2, 4, 17, 32, 341, 613}


class FacebookError(RuntimeError):
    def __init__(self, message, code=None, subcode=None, retryable=False):
        super().__init__(message)
        self.code = code
        self.subcode = subcode
        self.retryable = retryable


def _parse_error(resp):
    try:
        err = resp.json().get("error", {})
    except ValueError:
        err = {}
    code = err.get("code")
    msg = err.get("error_user_msg") or err.get("message") or resp.text[:400]
    retryable = resp.status_code >= 500 or resp.status_code == 429 or code in RETRYABLE_CODES
    return FacebookError(
        f"[{resp.status_code}] code={code} {msg}",
        code=code,
        subcode=err.get("error_subcode"),
        retryable=retryable,
    )


def _request(method, url, *, attempts=4, **kwargs):
    kwargs.setdefault("timeout", TIMEOUT)
    delay = 5
    last = None
    for attempt in range(1, attempts + 1):
        try:
            resp = requests.request(method, url, **kwargs)
            if resp.status_code < 400:
                try:
                    return resp.json()
                except ValueError:
                    return {"raw": resp.text}
            last = _parse_error(resp)
            if not last.retryable:
                raise last
        except requests.RequestException as e:
            last = FacebookError(f"rede: {e}", retryable=True)

        if attempt < attempts:
            print(f"    ! {last} -> nova tentativa em {delay}s ({attempt}/{attempts - 1})")
            time.sleep(delay)
            delay *= 2

    raise last


# ---------------------------------------------------------------- diagnostico

def page_info(page):
    return _request("GET", f"{GRAPH}/{page.page_id}",
                    params={"fields": "id,name,fan_count", "access_token": page.token})


_tokens_cache = {}


def page_tokens(user_token, cache_key="map"):
    """{page_id: {'name', 'token'}} a partir de um token de usuario.

    Com muitas paginas, evita cadastrar um secret por pagina: um unico token de
    usuario de longa duracao entrega o token de todas as Paginas que ele
    administra. Os tokens de Pagina assim derivados nao expiram.
    """
    if cache_key in _tokens_cache:
        return _tokens_cache[cache_key]

    mapa = {}
    url = f"{GRAPH}/me/accounts"
    params = {"fields": "name,id,access_token", "limit": 100, "access_token": user_token}
    while url:
        data = _request("GET", url, params=params)
        for p in data.get("data", []):
            mapa[str(p["id"])] = {"name": p.get("name", ""), "token": p["access_token"]}
        url = (data.get("paging") or {}).get("next")
        params = None  # o link de paginacao ja vem completo

    _tokens_cache[cache_key] = mapa
    return mapa


def token_expires_at(page):
    """Timestamp de expiracao do token (0 = nunca expira). None se indisponivel."""
    try:
        data = _request(
            "GET", f"{GRAPH}/debug_token", attempts=2,
            params={"input_token": page.token, "access_token": page.token},
        )
        return data.get("data", {}).get("expires_at")
    except FacebookError:
        return None


# --------------------------------------------------------------------- reels

def publish_reel(page, path, caption, when_ts=None):
    size = os.path.getsize(path)

    start = _request(
        "POST", f"{GRAPH}/{page.page_id}/video_reels",
        data={"upload_phase": "start", "access_token": page.token},
    )
    video_id = start["video_id"]
    upload_url = start["upload_url"]

    _upload_rupload(upload_url, path, size, page.token)

    params = {
        "upload_phase": "finish",
        "video_id": video_id,
        "description": caption,
        "access_token": page.token,
    }
    if when_ts:
        params["video_state"] = "SCHEDULED"
        params["scheduled_publish_time"] = int(when_ts)
    else:
        params["video_state"] = "PUBLISHED"

    _request("POST", f"{GRAPH}/{page.page_id}/video_reels", params=params)
    return video_id


def _rupload_offset(upload_url, token):
    """Quanto o Facebook ja recebeu - permite retomar em vez de reenviar tudo."""
    try:
        data = _request("GET", upload_url, attempts=2,
                        headers={"Authorization": f"OAuth {token}"})
        return int(data.get("start_offset", 0))
    except (FacebookError, ValueError, TypeError):
        return 0


def _upload_rupload(upload_url, path, size, token):
    delay = 5
    for attempt in range(1, 5):
        offset = _rupload_offset(upload_url, token) if attempt > 1 else 0
        if offset >= size:
            return
        try:
            with open(path, "rb") as f:
                f.seek(offset)
                resp = requests.post(
                    upload_url,
                    headers={
                        "Authorization": f"OAuth {token}",
                        "offset": str(offset),
                        "file_size": str(size),
                        "Content-Type": "application/octet-stream",
                    },
                    data=f,
                    timeout=TIMEOUT,
                )
            if resp.status_code < 400:
                return
            err = _parse_error(resp)
            if not err.retryable and attempt > 1:
                raise err
            last = err
        except requests.RequestException as e:
            last = FacebookError(f"rede no upload: {e}", retryable=True)

        if attempt < 4:
            print(f"    ! upload falhou ({last}); retomando em {delay}s")
            time.sleep(delay)
            delay *= 2

    raise last


# ---------------------------------------------------------- video de feed

def publish_video(page, path, caption, when_ts=None):
    """Upload em chunks (start/transfer/finish) - retoma pelo offset em caso de erro."""
    size = os.path.getsize(path)

    session = _request(
        "POST", f"{GRAPH_VIDEO}/{page.page_id}/videos",
        data={"upload_phase": "start", "file_size": size, "access_token": page.token},
    )
    session_id = session["upload_session_id"]
    video_id = session["video_id"]
    start_offset = int(session["start_offset"])
    end_offset = int(session["end_offset"])

    with open(path, "rb") as f:
        while start_offset < end_offset:
            f.seek(start_offset)
            chunk = f.read(min(CHUNK, end_offset - start_offset))
            resp = _request(
                "POST", f"{GRAPH_VIDEO}/{page.page_id}/videos",
                data={
                    "upload_phase": "transfer",
                    "upload_session_id": session_id,
                    "start_offset": start_offset,
                    "access_token": page.token,
                },
                files={"video_file_chunk": ("chunk", chunk, "application/octet-stream")},
            )
            start_offset = int(resp["start_offset"])
            end_offset = int(resp["end_offset"])
            print(f"    enviado {min(100, int(start_offset / size * 100))}%")

    finish = {
        "upload_phase": "finish",
        "upload_session_id": session_id,
        "description": caption,
        "access_token": page.token,
    }
    if when_ts:
        finish["published"] = "false"
        finish["scheduled_publish_time"] = int(when_ts)

    _request("POST", f"{GRAPH_VIDEO}/{page.page_id}/videos", data=finish)
    return video_id


def publish(page, path, caption, when_ts=None, post_type=None):
    """Publica no formato pedido, com uma rede de seguranca.

    Reels tem esteira de recomendacao propria (alcanca quem nao segue a
    pagina), mas a API recusa arquivos fora do padrao dela - duracao acima do
    limite, proporcao errada. Quando isso acontece, publicamos como video de
    feed em vez de perder o horario. O finish do Reels so acontece no fim,
    entao uma recusa nao deixa post pela metade.
    """
    tipo = (post_type or page.post_type or "video").lower()

    if tipo != "reel":
        return publish_video(page, path, caption, when_ts)

    try:
        return publish_reel(page, path, caption, when_ts)
    except FacebookError as e:
        if e.retryable:
            raise
        print(f"     ! Reels recusado ({e}); publicando como video de feed")
        return publish_video(page, path, caption, when_ts)
