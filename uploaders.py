"""Uploads the video to YouTube Shorts, Instagram Reels and TikTok."""
import os
import shutil
import subprocess
import tempfile
import time
import requests


def _log(cb, msg):
    if cb:
        cb(msg)


def _checar(r):
    if not r.ok:
        raise RuntimeError(f"Error {r.status_code}: {r.text[:400]}")


# ------------------------------------------------------------------ YouTube
# O app define esta função para perguntar ao usuário como abrir o link de login (abrir ou copiar).
# Recebe (url, nome_da_plataforma). Se for None, o navegador padrão abre sozinho.
ABRIR_LINK = None
FECHAR_LINK = None  # chamada quando o login termina, para o app fechar a janelinha do link
_PAGINA_FIM = (
    "Done! Sign-in complete. You can close this tab and go back to the app."
    "<script>setTimeout(function(){window.close()},600)</script>"  # só funciona se o navegador permitir
)


def _nav_do_app(nome):
    """Nome de um 'navegador' que, em vez de abrir uma janela, entrega o link ao app. None = usar o padrão."""
    if not ABRIR_LINK:
        return None
    import webbrowser

    class Entrega(webbrowser.BaseBrowser):
        def open(self, url, new=0, autoraise=True):
            ABRIR_LINK(url, nome)
            return True

    webbrowser.register("ytk-link", None, Entrega("ytk-link"))
    return "ytk-link"


YT_ESCOPOS = [
    "https://www.googleapis.com/auth/youtube.upload",
    "https://www.googleapis.com/auth/youtube.readonly",  # só para mostrar o @ do canal; opcional
]


def postar_youtube(cfg, video, titulo, descricao, hashtags, log=None):
    from google.auth.transport.requests import Request
    from google.oauth2.credentials import Credentials
    from google_auth_oauthlib.flow import InstalledAppFlow
    from googleapiclient.discovery import build
    from googleapiclient.http import MediaFileUpload

    escopos = YT_ESCOPOS
    token_path = cfg.get("youtube_token_file") or "youtube_token.json"  # um arquivo por conta
    creds = None
    if os.path.exists(token_path):
        creds = Credentials.from_authorized_user_file(token_path)  # usa os escopos que já foram autorizados
    if not creds or not creds.valid:
        renovou = False
        if creds and creds.expired and creds.refresh_token:
            try:
                creds.refresh(Request())
                renovou = True
            except Exception as e:  # noqa: BLE001
                if "invalid_grant" not in str(e):
                    raise
                # o Google cancelou o login (acontece de tempos em tempos no modo de teste): pede de novo
                _log(log, "YouTube: sign-in expired, asking for authorization again.")
                try:
                    os.remove(token_path)
                except OSError:
                    pass
                creds = None
        if not renovou:
            segredo = cfg.get("youtube_client_secret", "")
            if not segredo or not os.path.exists(segredo):
                raise RuntimeError("YouTube: set the client_secret.json file in Settings.")
            _log(log, "YouTube: authorize access in the browser (first time only)...")
            try:
                try:
                    creds = InstalledAppFlow.from_client_secrets_file(segredo, escopos).run_local_server(
                        port=0, browser=_nav_do_app("YouTube"), success_message=_PAGINA_FIM,
                        prompt="select_account consent")
                except Exception as e:  # noqa: BLE001
                    if "scope" not in str(e).lower():
                        raise
                    # o projeto do Google não liberou o escopo de leitura: autoriza só o envio
                    creds = InstalledAppFlow.from_client_secrets_file(segredo, escopos[:1]).run_local_server(
                        port=0, browser=_nav_do_app("YouTube"), success_message=_PAGINA_FIM,
                        prompt="select_account consent")
            finally:
                if FECHAR_LINK:
                    FECHAR_LINK()
        with open(token_path, "w") as f:
            f.write(creds.to_json())

    yt = build("youtube", "v3", credentials=creds)
    tags = [h.lstrip("#") for h in hashtags]
    texto_hash = " ".join(hashtags + ["#Shorts"])
    corpo = {
        "snippet": {
            "title": titulo[:100],
            "description": f"{descricao}\n\n{texto_hash}",
            "tags": tags,
            "categoryId": "22",
        },
        "status": {
            "privacyStatus": cfg.get("youtube_privacidade", "public"),
            "selfDeclaredMadeForKids": False,
        },
    }
    media = MediaFileUpload(video, chunksize=8 * 1024 * 1024, resumable=True)
    req = yt.videos().insert(part="snippet,status", body=corpo, media_body=media)
    resp = None
    while resp is None:
        status, resp = req.next_chunk()
        if status:
            _log(log, f"YouTube: uploading {int(status.progress() * 100)}%")
    return f"https://youtube.com/shorts/{resp['id']}"


# ---------------------------------------------------------------- Instagram
def _achar_contas_ig(token, ver, log):
    """Lista (id, nome) das contas do Instagram ligadas às Páginas do token."""
    achadas = []
    try:
        x = requests.get(
            f"https://graph.facebook.com/{ver}/me/accounts",
            params={"fields": "name,instagram_business_account{id,username}", "access_token": token},
            timeout=30,
        )
        _log(log, f"Token Pages: {x.status_code} {x.text[:300]}")
        for pagina in x.json().get("data", []):
            ig = pagina.get("instagram_business_account")
            if ig and ig.get("id"):
                achadas.append((ig["id"], ig.get("username") or pagina.get("name", "")))
    except Exception as e:
        _log(log, f"Could not list the Pages: {e}")
    try:
        p = requests.get(
            f"https://graph.facebook.com/{ver}/me/permissions",
            params={"access_token": token},
            timeout=30,
        )
        dadas = [i["permission"] for i in p.json().get("data", []) if i.get("status") == "granted"]
        _log(log, "Token permissions: " + (", ".join(dadas) or "none"))
    except Exception as e:
        _log(log, f"Could not list the permissions: {e}")
    return achadas


def _diagnosticar_instagram(uid, token, ver, log):
    """Mostra no log o que cada servidor diz sobre o token (sem exibir o token)."""
    _log(log, f"Diagnostics: the token starts with '{token[:2]}' and is {len(token)} characters long.")
    for h in ("graph.facebook.com", "graph.instagram.com"):
        for rotulo, caminho, campos in (
            ("token", "me", "id,name"),
            ("account", uid, "id,username"),
        ):
            try:
                x = requests.get(
                    f"https://{h}/{ver}/{caminho}",
                    params={"fields": campos, "access_token": token},
                    timeout=30,
                )
                _log(log, f"Diagnostics {h} [{rotulo}]: {x.status_code} {x.text[:220]}")
            except Exception as e:
                _log(log, f"Diagnostics {h} [{rotulo}]: failed ({e})")


def _preparar_video(video, log=None):
    """Converte para MP4 H.264 + AAC (formato que o Reels aceita). Devolve o caminho a enviar."""
    try:
        import imageio_ffmpeg
        ffmpeg = imageio_ffmpeg.get_ffmpeg_exe()
    except Exception:
        ffmpeg = shutil.which("ffmpeg")
    if not ffmpeg:
        _log(log, "Instagram: ffmpeg not found, uploading the original video.")
        return video

    saida = os.path.join(tempfile.gettempdir(), f"reels_{os.getpid()}_{int(time.time())}.mp4")
    _log(log, "Instagram: converting the video to Reels format (may take a moment)...")
    cmd = [
        ffmpeg, "-y", "-i", video,
        "-vf", "scale=trunc(iw/2)*2:trunc(ih/2)*2,fps=30",
        "-c:v", "libx264", "-preset", "veryfast", "-crf", "23", "-pix_fmt", "yuv420p",
        "-c:a", "aac", "-b:a", "128k", "-ar", "44100", "-ac", "2",
        "-movflags", "+faststart", saida,
    ]
    try:
        r = subprocess.run(
            cmd, capture_output=True, timeout=1800,
            creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0),
        )
        if r.returncode != 0 or not os.path.exists(saida) or os.path.getsize(saida) == 0:
            _log(log, "Instagram: could not convert, uploading the original. " + r.stderr.decode("utf-8", "ignore")[-200:])
            return video
    except Exception as e:
        _log(log, f"Instagram: conversion failed ({e}), uploading the original.")
        return video
    _log(log, f"Instagram: video converted ({os.path.getsize(saida) // 1024} KB).")
    return saida


def _preparar_video_seguro(video, log=None):
    """Conversão conservadora para quando o Instagram recusa o arquivo (ProcessingFailed): mapeia só 1 vídeo + 1 áudio,
    remove metadados/rotação, H.264 High 4.0, 30 fps constante, GOP de 2 s, AAC 48 kHz estéreo, até 1080 de largura."""
    try:
        import imageio_ffmpeg
        ffmpeg = imageio_ffmpeg.get_ffmpeg_exe()
    except Exception:
        ffmpeg = shutil.which("ffmpeg")
    if not ffmpeg:
        return None
    saida = os.path.join(tempfile.gettempdir(), f"reels_safe_{os.getpid()}_{int(time.time())}.mp4")
    _log(log, "Instagram: Instagram refused the video format, converting it and trying again...")
    cmd = [
        ffmpeg, "-y", "-i", video, "-map", "0:v:0", "-map", "0:a:0?", "-sn", "-dn",
        "-vf", "scale='min(1080,iw)':-2,setsar=1,fps=30,format=yuv420p",
        "-c:v", "libx264", "-profile:v", "high", "-level", "4.0", "-preset", "medium", "-crf", "22",
        "-maxrate", "8M", "-bufsize", "16M", "-g", "60", "-bf", "2",
        "-c:a", "aac", "-b:a", "128k", "-ar", "48000", "-ac", "2",
        "-movflags", "+faststart", "-map_metadata", "-1", "-metadata:s:v", "rotate=0", saida,
    ]
    try:
        r = subprocess.run(cmd, capture_output=True, timeout=3600,
                           creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0))
        if r.returncode != 0 or not os.path.exists(saida) or os.path.getsize(saida) == 0:
            _log(log, "Instagram: safe re-encode failed. " + r.stderr.decode("utf-8", "ignore")[-200:])
            return None
    except Exception as e:
        _log(log, f"Instagram: safe re-encode failed ({e}).")
        return None
    _log(log, f"Instagram: safe version ready ({os.path.getsize(saida) // 1024} KB).")
    return saida


def postar_instagram(cfg, video, legenda, log=None):
    pronto = preparar_instagram(video, log, cfg.get("prefs", {}).get("compactar", True))
    extra = None
    try:
        try:
            return _postar_instagram_arquivo(cfg, pronto, legenda, log)
        except RuntimeError as e:
            txt = str(e)
            if "ProcessingFailed" not in txt and "processing failed" not in txt.lower() and "rejected the video" not in txt \
                    and "ERROR" not in txt:
                raise
            # parte do original (não do já convertido) com um perfil bem conservador e tenta de novo
            extra = _preparar_video_seguro(video, log)
            if not extra:
                raise
            return _postar_instagram_arquivo(cfg, extra, legenda, log)
    finally:
        for p in (pronto, extra):
            if p and p != video:
                try:
                    os.remove(p)
                except OSError:
                    pass


def preparar_instagram(video, log=None, compactar_ligado=True):
    """Devolve o arquivo a enviar: o original, ou compactado se passar do limite de tamanho. Não converte o formato."""
    import compactar

    pronto = video  # envia o original; só converte se o Instagram recusar (ver postar_instagram)
    if compactar_ligado:
        menor, temporario = compactar.ajustar(pronto, compactar.LIMITES_MB["Instagram Reels"], log, "Instagram")
        if temporario:
            if pronto != video:
                try:
                    os.remove(pronto)
                except OSError:
                    pass
            pronto = menor
    return pronto


def _postar_instagram_arquivo(cfg, video, legenda, log=None):
    uid = cfg.get("instagram_user_id", "")
    token = cfg.get("instagram_access_token", "")
    if not uid or not token:
        raise RuntimeError("Instagram: set the account ID and token in Settings.")
    ver = cfg.get("instagram_api_version", "v21.0")
    # Tokens gerados pelo botão "Gerar token" (login do Instagram, começam com "IG")
    # só funcionam em graph.instagram.com. Tokens do Facebook / usuário do sistema
    # (começam com "EAA") usam graph.facebook.com.
    token = token.strip()
    uid = uid.strip()
    principal = cfg.get("instagram_host") or ("graph.facebook.com" if token.startswith("EA") else "graph.instagram.com")
    outro = "graph.instagram.com" if principal == "graph.facebook.com" else "graph.facebook.com"

    host, r, primeira = principal, None, None
    for h in (principal, outro):
        host = h
        _log(log, f"Instagram: creating the Reel (via {host})...")
        r = requests.post(
            f"https://{host}/{ver}/{uid}/media",
            data={"media_type": "REELS", "upload_type": "resumable", "caption": legenda, "access_token": token},
            timeout=60,
        )
        if r.ok:
            break
        if primeira is None:
            primeira = r  # o erro do endereço certo é o que importa
        _log(log, f"Instagram: {host} responded {r.status_code}: {r.text[:200]}")

    if not r.ok and token.startswith("EA"):
        # Token do Facebook: procura as contas do Instagram ligadas às suas Páginas
        _log(log, "Instagram: looking for Instagram accounts linked to the token...")
        contas = _achar_contas_ig(token, ver, log)
        for conta_id, nome in contas:
            _log(log, f"Instagram: trying account {nome} (ID {conta_id})...")
            host = "graph.facebook.com"
            r2 = requests.post(
                f"https://{host}/{ver}/{conta_id}/media",
                data={"media_type": "REELS", "upload_type": "resumable", "caption": legenda, "access_token": token},
                timeout=60,
            )
            if r2.ok:
                r = r2
                cfg["instagram_user_id"] = conta_id  # guarda o ID certo
                _log(log, f"Instagram: the correct ID is {conta_id}. Saved to Settings.")
                break
        if not contas:
            _log(log, "Instagram: no Instagram account is linked to a Page of this token.")

    if not r.ok:
        _diagnosticar_instagram(uid, token, ver, log)
        _checar(primeira or r)  # mostra o erro do endereço certo, e não o do reserva
    _checar(r)
    base = f"https://{host}/{ver}"
    container = r.json()["id"]

    _log(log, "Instagram: uploading the video...")
    tamanho = os.path.getsize(video)
    with open(video, "rb") as f:
        corpo = f.read()  # o arquivo inteiro em memória: corpo simples, sem envio em streaming
    for tentativa in range(1, 4):
        r = requests.post(
            f"https://rupload.facebook.com/ig-api-upload/{ver}/{container}",
            headers={"Authorization": f"OAuth {token}", "offset": "0", "file_size": str(tamanho),
                     "Content-Type": "application/octet-stream"},
            data=corpo,
            timeout=1800,
        )
        if r.ok:
            break
        _log(log, f"Instagram: upload attempt {tentativa}/3 failed: {r.status_code} {r.text[:200]} "
                  f"[trace {r.headers.get('x-fb-trace-id') or r.headers.get('x-fb-debug') or '-'}]")
        try:
            est = requests.get(f"{base}/{container}", params={"fields": "status_code,status,video_status",
                                                              "access_token": token}, timeout=60)
            _log(log, f"Instagram: container status: {est.text[:300]}")
        except Exception:
            pass
        if tentativa < 3:
            time.sleep(10 * tentativa)
    _checar(r)
    del corpo

    _log(log, "Instagram: waiting for processing...")
    for _ in range(72):
        s = requests.get(
            f"{base}/{container}",
            params={"fields": "status_code,status", "access_token": token},
            timeout=60,
        ).json()
        codigo = s.get("status_code")
        if codigo == "FINISHED":
            break
        if codigo in ("ERROR", "EXPIRED"):
            raise RuntimeError(f"Instagram rejected the video: {s}")
        time.sleep(5)
    else:
        raise RuntimeError("Instagram: processing took too long.")

    _log(log, "Instagram: video ready, waiting 30 s before publishing (Meta sometimes needs this)...")
    time.sleep(30)
    r = None
    for tentativa in range(1, 5):
        r = requests.post(
            f"{base}/{uid}/media_publish",
            data={"creation_id": container, "access_token": token},
            timeout=120,
        )
        if r.ok:
            return f"published (id {r.json().get('id')})"
        _log(log, f"Instagram: publishing failed (attempt {tentativa}/4): {r.text[:160]}")
        try:
            est = requests.get(
                f"{base}/{container}",
                params={"fields": "status_code,status", "access_token": token},
                timeout=60,
            )
            _log(log, f"Instagram: video status on Instagram: {est.text[:300]}")
        except Exception as e:
            _log(log, f"Instagram: could not check the video status ({e})")
        if tentativa < 4:
            time.sleep(30 * tentativa)
    _checar(r)


# ------------------------------------------------------------------- TikTok
def _tiktok_token(cfg):
    if cfg.get("tiktok_refresh_token"):
        if cfg.get("tiktok_client_key") and cfg.get("tiktok_client_secret"):
            # o desenvolvedor usa o próprio app do TikTok
            r = requests.post(
                "https://open.tiktokapis.com/v2/oauth/token/",
                data={
                    "client_key": cfg["tiktok_client_key"],
                    "client_secret": cfg["tiktok_client_secret"],
                    "grant_type": "refresh_token",
                    "refresh_token": cfg["tiktok_refresh_token"],
                },
                timeout=60,
            )
        else:
            # versão pública: quem guarda o segredo é o servidor-ponte
            import tiktok_auth

            r = requests.post(
                tiktok_auth.RELAY + "/tiktok/refresh", json={"refresh_token": cfg["tiktok_refresh_token"]}, timeout=60
            )
        try:
            d = r.json()
        except ValueError:
            d = {}
        if d.get("access_token"):
            cfg["tiktok_access_token"] = d["access_token"]
            if d.get("refresh_token"):
                cfg["tiktok_refresh_token"] = d["refresh_token"]
    token = cfg.get("tiktok_access_token", "")
    if not token:
        raise RuntimeError("TikTok: not connected. Use Settings > TikTok > Connect.")
    return token


def tiktok_creator_info(cfg):
    """Dados da conta que vai postar: nome, opções de privacidade, interações permitidas e duração máxima."""
    token = _tiktok_token(cfg)
    r = requests.post(
        "https://open.tiktokapis.com/v2/post/publish/creator_info/query/",
        headers={"Authorization": f"Bearer {token}", "Content-Type": "application/json; charset=UTF-8"},
        json={},
        timeout=30,
    )
    _checar(r)
    return r.json().get("data", {})


def postar_tiktok(cfg, video, legenda, log=None, capa_ms=None, opcoes=None):
    token = _tiktok_token(cfg)
    tamanho = os.path.getsize(video)
    MB = 1024 * 1024
    if tamanho <= 64 * MB:
        chunk, total = tamanho, 1
    else:
        chunk = 32 * MB
        total = tamanho // chunk  # o último pedaço absorve o resto

    o = opcoes or {"privacidade": cfg.get("tiktok_privacidade", "SELF_ONLY")}
    info_post = {
        "title": legenda[:2200],
        "privacy_level": o["privacidade"],
        "disable_comment": not o.get("comentar", False),
        "disable_duet": not o.get("dueto", False),
        "disable_stitch": not o.get("stitch", False),
    }
    if o.get("comercial"):
        info_post["brand_organic_toggle"] = bool(o.get("proprio"))
        info_post["brand_content_toggle"] = bool(o.get("terceiros"))
    if capa_ms is not None:
        info_post["video_cover_timestamp_ms"] = int(capa_ms)
    _log(log, "TikTok: starting upload..." + (f" (cover at {capa_ms} ms)" if capa_ms is not None else " (no cover chosen)"))
    r = requests.post(
        "https://open.tiktokapis.com/v2/post/publish/video/init/",
        headers={"Authorization": f"Bearer {token}", "Content-Type": "application/json; charset=UTF-8"},
        json={
            "post_info": info_post,
            "source_info": {
                "source": "FILE_UPLOAD",
                "video_size": tamanho,
                "chunk_size": chunk,
                "total_chunk_count": total,
            },
        },
        timeout=60,
    )
    if not r.ok and "unaudited_client" in r.text:
        raise RuntimeError(
            "The TikTok app has not been audited yet: the TikTok account must be PRIVATE "
            "(TikTok > Settings and privacy > Privacy > Private account) "
            "and the post privacy must be SELF_ONLY. This is no longer required after the audit."
        )
    _checar(r)
    dados = r.json().get("data", {})
    publish_id, upload_url = dados.get("publish_id"), dados.get("upload_url")
    if not upload_url:
        raise RuntimeError(f"TikTok did not return the upload URL: {r.text[:300]}")

    with open(video, "rb") as f:
        for i in range(total):
            inicio = i * chunk
            fim = tamanho - 1 if i == total - 1 else inicio + chunk - 1
            f.seek(inicio)
            pedaco = f.read(fim - inicio + 1)
            rr = requests.put(
                upload_url,
                headers={
                    "Content-Type": "video/mp4",
                    "Content-Length": str(len(pedaco)),
                    "Content-Range": f"bytes {inicio}-{fim}/{tamanho}",
                },
                data=pedaco,
                timeout=900,
            )
            _checar(rr)
            _log(log, f"TikTok: uploading {int((fim + 1) / tamanho * 100)}%")

    for _ in range(36):
        s = requests.post(
            "https://open.tiktokapis.com/v2/post/publish/status/fetch/",
            headers={"Authorization": f"Bearer {token}", "Content-Type": "application/json; charset=UTF-8"},
            json={"publish_id": publish_id},
            timeout=60,
        ).json()
        estado = s.get("data", {}).get("status")
        if estado == "PUBLISH_COMPLETE":
            return "published"
        if estado == "FAILED":
            raise RuntimeError(f"TikTok failed: {s.get('data', {}).get('fail_reason')}")
        time.sleep(5)
    return "uploaded (TikTok is still processing)"


def youtube_canal(cfg):
    """@ do canal conectado. None = não conectado; "" = conectado, mas sem permissão de leitura para ver o nome."""
    caminho = cfg.get("youtube_token_file") or "youtube_token.json"
    if not os.path.exists(caminho):
        return None
    from google.auth.transport.requests import Request
    from google.oauth2.credentials import Credentials
    from googleapiclient.discovery import build

    creds = Credentials.from_authorized_user_file(caminho)
    if YT_ESCOPOS[1] not in (creds.scopes or []):
        return ""
    if not creds.valid:
        creds.refresh(Request())
    itens = build("youtube", "v3", credentials=creds).channels().list(part="snippet", mine=True).execute().get("items", [])
    if not itens:
        return ""
    s = itens[0]["snippet"]
    return s.get("customUrl") or s.get("title", "")


def instagram_usuario(cfg):
    """@ da conta do Instagram conectada, ou None se não estiver configurada."""
    uid = (cfg.get("instagram_user_id") or "").strip()
    token = (cfg.get("instagram_access_token") or "").strip()
    if not uid or not token:
        return None
    host = cfg.get("instagram_host") or ("graph.facebook.com" if token.startswith("EA") else "graph.instagram.com")
    r = requests.get(
        f"https://{host}/{cfg.get('instagram_api_version', 'v21.0')}/{uid}",
        params={"fields": "username", "access_token": token}, timeout=30,
    )
    if not r.ok:
        raise RuntimeError(r.text[:150])
    return "@" + r.json().get("username", "")


def tiktok_usuario(cfg):
    """@ da conta do TikTok conectada, ou None se não estiver conectada."""
    if not (cfg.get("tiktok_access_token") or cfg.get("tiktok_refresh_token")):
        return None
    info = tiktok_creator_info(cfg)
    return "@" + info["creator_username"] if info.get("creator_username") else (info.get("creator_nickname") or "")
