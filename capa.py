"""Escolhe com o Gemini o melhor quadro do vídeo para ser a capa (thumbnail)."""
import base64
import json
import os
import re
import shutil
import subprocess
import tempfile

import requests

import ai

QUADROS = 8
_SEM_JANELA = getattr(subprocess, "CREATE_NO_WINDOW", 0)


def _ffmpeg():
    try:
        import imageio_ffmpeg

        return imageio_ffmpeg.get_ffmpeg_exe()
    except Exception:
        return shutil.which("ffmpeg")


def _duracao(ffmpeg, video):
    r = subprocess.run([ffmpeg, "-i", video], capture_output=True, creationflags=_SEM_JANELA)
    m = re.search(r"Duration:\s*(\d+):(\d+):(\d+\.?\d*)", r.stderr.decode("utf-8", "ignore"))
    if not m:
        return 0.0
    h, mi, s = m.groups()
    return int(h) * 3600 + int(mi) * 60 + float(s)


def informacoes(video):
    """(duração em segundos, largura, altura) ou None se não conseguir ler."""
    ffmpeg = _ffmpeg()
    if not ffmpeg:
        return None
    try:
        r = subprocess.run([ffmpeg, "-i", video], capture_output=True, creationflags=_SEM_JANELA, timeout=60)
        txt = r.stderr.decode("utf-8", "ignore")
        m = re.search(r"Duration:\s*(\d+):(\d+):(\d+\.?\d*)", txt)
        dur = int(m.group(1)) * 3600 + int(m.group(2)) * 60 + float(m.group(3)) if m else 0.0
        v = re.search(r"Video:.*?(\d{2,5})x(\d{2,5})", txt)
        if not v:
            return None
        larg, alt = int(v.group(1)), int(v.group(2))
        giro = re.search(r"rotate\s*:\s*(-?\d+)", txt)
        if giro and abs(int(giro.group(1))) % 180 == 90:  # vídeo de celular gravado de lado
            larg, alt = alt, larg
        return dur, larg, alt
    except Exception:
        return None


def extrair_quadros(video, qtd=QUADROS, largura=360):
    """Tira `qtd` quadros espalhados pelo vídeo. Devolve [(segundos, jpeg em base64), ...]."""
    ffmpeg = _ffmpeg()
    if not ffmpeg:
        return []
    dur = _duracao(ffmpeg, video)
    if dur < 2:
        return []
    pasta = tempfile.mkdtemp(prefix="quadros_")
    saida = []
    try:
        # sem o começo e o fim (costumam ser pretos ou de transição)
        for i in range(qtd):
            t = dur * (0.06 + 0.88 * i / max(1, qtd - 1))
            arq = os.path.join(pasta, f"{i}.jpg")
            subprocess.run(
                [ffmpeg, "-y", "-ss", f"{t:.2f}", "-i", video, "-frames:v", "1",
                 "-vf", f"scale={largura}:-2", "-q:v", "5", arq],
                capture_output=True, timeout=120, creationflags=_SEM_JANELA,
            )
            if os.path.exists(arq) and os.path.getsize(arq) > 0:
                with open(arq, "rb") as f:
                    saida.append((t, base64.b64encode(f.read()).decode()))
        return saida
    except Exception:
        return saida
    finally:
        shutil.rmtree(pasta, ignore_errors=True)


def extrair_audio(video, segundos=60):
    """Primeiros `segundos` do áudio, mono 16 kHz em WAV (base64), para a IA descobrir o idioma falado. None se não houver."""
    ffmpeg = _ffmpeg()
    if not ffmpeg:
        return None
    pasta = tempfile.mkdtemp(prefix="audio_")
    arq = os.path.join(pasta, "a.wav")
    try:
        subprocess.run(
            [ffmpeg, "-y", "-i", video, "-t", str(segundos), "-vn", "-ac", "1", "-ar", "16000",
             "-c:a", "pcm_s16le", arq],
            capture_output=True, timeout=180, creationflags=_SEM_JANELA,
        )
        if os.path.exists(arq) and 20000 < os.path.getsize(arq) < 8_000_000:
            with open(arq, "rb") as f:
                return base64.b64encode(f.read()).decode()
    except Exception:
        pass
    finally:
        shutil.rmtree(pasta, ignore_errors=True)
    return None


def escolher(api_key, video, descricao="", log=None):
    """Devolve o instante (em milissegundos) do melhor quadro, ou None se não der."""
    ffmpeg = _ffmpeg()
    if not ffmpeg or not api_key:
        return None
    dur = _duracao(ffmpeg, video)
    if dur < 2:
        return None
    pasta = tempfile.mkdtemp(prefix="capa_")
    try:
        # quadros espalhados, sem o começo e o fim (costumam ser pretos ou de transição)
        tempos = [dur * (0.06 + 0.88 * i / (QUADROS - 1)) for i in range(QUADROS)]
        partes = []
        for i, t in enumerate(tempos):
            arq = os.path.join(pasta, f"{i}.jpg")
            subprocess.run(
                [ffmpeg, "-y", "-ss", f"{t:.2f}", "-i", video, "-frames:v", "1",
                 "-vf", "scale=360:-2", "-q:v", "5", arq],
                capture_output=True, timeout=120, creationflags=_SEM_JANELA,
            )
            if os.path.exists(arq) and os.path.getsize(arq) > 0:
                with open(arq, "rb") as f:
                    partes.append((i, base64.b64encode(f.read()).decode()))
        if len(partes) < 2:
            return None

        pedido = [{"text": (
            "These are frames from a short vertical video for a US audience on TikTok. "
            f"Video topic: {descricao or 'unknown'}. Each frame is preceded by its number. "
            "Pick the single best frame to use as the cover thumbnail: sharp (not motion-blurred), "
            "well lit, subject clearly visible, an interesting or curiosity-provoking moment, "
            "no eyes half-closed, no black or transition frames. "
            'Answer ONLY with JSON: {"frame": <number>}'
        )}]
        for i, b64 in partes:
            pedido.append({"text": f"Frame {i}:"})
            pedido.append({"inline_data": {"mime_type": "image/jpeg", "data": b64}})
        corpo = {
            "contents": [{"parts": pedido}],
            "generationConfig": {"responseMimeType": "application/json", "temperature": 0.2},
        }
        r = None
        for modelo in ai.MODELOS:
            r = requests.post(
                ai.URL_BASE.format(modelo=modelo),
                headers={"x-goog-api-key": api_key, "Content-Type": "application/json"},
                json=corpo, timeout=90,
            )
            if r.status_code != 404:
                break
        if not r.ok:
            if log:
                log(f"Cover: Gemini did not respond ({r.status_code}), using the default frame.")
            return None
        dados = json.loads(r.json()["candidates"][0]["content"]["parts"][0]["text"])
        if isinstance(dados, list) and dados:
            dados = dados[0]
        n = int(dados["frame"])
        if n < 0 or n >= QUADROS:
            return None
        ms = int(tempos[n] * 1000)
        if log:
            log(f"Cover: AI picked the frame at {tempos[n]:.1f}s.")
        return ms
    except Exception as e:
        if log:
            log(f"Cover: could not choose ({e}), using the default frame.")
        return None
    finally:
        shutil.rmtree(pasta, ignore_errors=True)
