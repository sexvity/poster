"""Login com o TikTok (Login Kit para desktop, com PKCE) e troca do código pelos tokens."""
import hashlib
import secrets
import socket
import sys
import threading
import time
import webbrowser
from http.server import BaseHTTPRequestHandler, HTTPServer
from urllib.parse import parse_qs, urlencode, urlparse

import requests

# Versão pública: o programa só tem a client key (que é pública). O client_secret fica no servidor-ponte.
RELAY = "https://ytk-relay.feengg2.workers.dev"
CLIENT_KEY_PUBLICA = "awvns92evorlrdyi"
PORTA = 3455
REDIRECT = f"http://127.0.0.1:{PORTA}/callback/"  # cadastre exatamente este endereço no TikTok
ESCOPOS = "user.info.basic,video.publish"
AUTORIZAR = "https://www.tiktok.com/v2/auth/authorize/"
TOKEN = "https://open.tiktokapis.com/v2/oauth/token/"

PAGINA_OK = (
    "<html><head><meta charset='utf-8'></head><body style='font-family:sans-serif;background:#0d0f14;color:#e8eaf0;"
    "text-align:center;padding-top:80px'><h2>Done!</h2><p>You are connected. You can close this tab and go back to the app.</p>"
    "<script>setTimeout(function(){window.close()},600)</script></body></html>"
)


class Servidor(HTTPServer):
    # no Windows, SO_REUSEADDR deixaria dois servidores na mesma porta (e não combina com o modo exclusivo)
    allow_reuse_address = sys.platform != "win32"

    def server_bind(self):
        if sys.platform == "win32":
            self.socket.setsockopt(socket.SOL_SOCKET, socket.SO_EXCLUSIVEADDRUSE, 1)
        HTTPServer.server_bind(self)


_em_andamento = threading.Lock()


def _quem_usa():
    """No Windows, descobre qual programa está segurando a porta."""
    dica = "Close other programs and try again."
    if sys.platform != "win32":
        return dica
    try:
        import subprocess

        saida = subprocess.run(["netstat", "-ano"], capture_output=True, timeout=10).stdout.decode("utf-8", "replace")
        pids = {l.split()[-1] for l in saida.splitlines() if f":{PORTA} " in l}
        if pids:
            return f"Program(s) using the port (PID): {', '.join(sorted(pids))}. End them in Task Manager > Details."
    except Exception:
        pass
    return dica + " If nothing works, restart the computer."


def conectar(cfg, log=None, tempo_max=300, abrir=True, ao_url=None):
    """Abre o navegador, espera a autorização e guarda os tokens em `cfg`. Só uma conexão por vez."""
    if not _em_andamento.acquire(blocking=False):
        raise RuntimeError(
            "A TikTok connection is already waiting for authorization. Finish it in the browser "
            "(or close the app and reopen it) before clicking again."
        )
    try:
        return _conectar(cfg, log, tempo_max, abrir, ao_url)
    finally:
        _em_andamento.release()


def _conectar(cfg, log, tempo_max, abrir, ao_url):
    chave = cfg.get("tiktok_client_key", "") or CLIENT_KEY_PUBLICA
    segredo = cfg.get("tiktok_client_secret", "")  # vazio = versão pública, usa o servidor-ponte

    # PKCE: o TikTok documenta o desafio como SHA-256 em hexadecimal
    verificador = secrets.token_urlsafe(64)[:96]
    desafio = hashlib.sha256(verificador.encode()).hexdigest()
    estado = secrets.token_urlsafe(16)
    url = AUTORIZAR + "?" + urlencode(
        {
            "client_key": chave,
            "response_type": "code",
            "scope": ESCOPOS,
            "redirect_uri": REDIRECT,
            "state": estado,
            "code_challenge": desafio,
            "code_challenge_method": "S256",
        }
    )

    recebido = {}

    class Receber(BaseHTTPRequestHandler):
        def do_GET(self):
            q = parse_qs(urlparse(self.path).query)
            if "code" in q or "error" in q:
                recebido.update({k: v[0] for k, v in q.items()})
            self.send_response(200)
            self.send_header("Content-Type", "text/html; charset=utf-8")
            self.end_headers()
            self.wfile.write(PAGINA_OK.encode("utf-8"))

        def log_message(self, *args):  # sem ruído no console
            pass

    try:
        servidor = Servidor(("127.0.0.1", PORTA), Receber)
    except OSError as e:
        raise RuntimeError(f"Port {PORTA} is in use ({e}). {_quem_usa()}")
    servidor.timeout = 2
    try:
        if ao_url:
            ao_url(url)
        if abrir:
            if log:
                log("TikTok: opening the browser, authorize the app there...")
            webbrowser.open(url)
        elif log:
            log("TikTok: choose how to open the sign-in link in the window that appeared.")
        limite = time.time() + tempo_max
        while not recebido and time.time() < limite:
            servidor.handle_request()
    finally:
        servidor.server_close()

    if not recebido:
        raise RuntimeError("Timed out waiting for TikTok authorization.")
    if "error" in recebido:
        raise RuntimeError(f"TikTok refused: {recebido.get('error_description') or recebido['error']}")
    if recebido.get("state") != estado:
        raise RuntimeError("The TikTok response does not match (different state). Try again.")

    if segredo:
        r = requests.post(
            TOKEN,
            data={
                "client_key": chave,
                "client_secret": segredo,
                "code": recebido["code"],
                "grant_type": "authorization_code",
                "redirect_uri": REDIRECT,
                "code_verifier": verificador,
            },
            headers={"Content-Type": "application/x-www-form-urlencoded"},
            timeout=60,
        )
    else:
        r = requests.post(
            RELAY + "/tiktok/token",
            json={"code": recebido["code"], "code_verifier": verificador, "redirect_uri": REDIRECT},
            timeout=60,
        )
    try:
        dados = r.json()
    except ValueError:
        raise RuntimeError(f"Unexpected response while connecting ({r.status_code}): {r.text[:200]}")
    if "access_token" not in dados:
        raise RuntimeError(f"TikTok did not return the token: {str(dados)[:300]}")
    cfg["tiktok_access_token"] = dados["access_token"]
    cfg["tiktok_refresh_token"] = dados.get("refresh_token", "")
    if log:
        log("TikTok connected.")
    return True


def desconectar(cfg, log=None):
    """Revoga o acesso no TikTok e apaga os tokens guardados. Na próxima conexão o TikTok mostra todas as permissões."""
    token = cfg.get("tiktok_access_token", "")
    if token:
        if cfg.get("tiktok_client_secret"):
            r = requests.post(
                "https://open.tiktokapis.com/v2/oauth/revoke/",
                data={
                    "client_key": cfg.get("tiktok_client_key", ""),
                    "client_secret": cfg["tiktok_client_secret"],
                    "token": token,
                },
                headers={"Content-Type": "application/x-www-form-urlencoded"},
                timeout=60,
            )
        else:
            r = requests.post(RELAY + "/tiktok/revoke", json={"token": token}, timeout=60)
        if log:
            log(f"TikTok: access revoked ({r.status_code}).")
    cfg["tiktok_access_token"] = ""
    cfg["tiktok_refresh_token"] = ""
