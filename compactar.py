"""Compacta o vídeo só quando precisa, para caber no limite de tamanho da plataforma com a melhor qualidade possível."""
import os
import shutil
import subprocess
import tempfile
import time

import capa

# Limites de tamanho (MB) que o app respeita. São valores seguros, abaixo do máximo de cada plataforma.
LIMITES_MB = {"YouTube Shorts": 200, "Instagram Reels": 250, "TikTok": 200}
AUDIO_KBPS = 128
_SEM_JANELA = getattr(subprocess, "CREATE_NO_WINDOW", 0)
# nunca passa de 1080 de largura (vertical) ou 1920 (horizontal); dimensões sempre pares
_ESCALA = "scale='if(gt(iw,ih),min(1920,iw),min(1080,iw))':-2"


def _log(log, msg):
    if log:
        log(msg)


def ajustar(video, limite_mb, log=None, nome="", forcar=False):
    """Devolve (caminho, é_temporário). Se o vídeo já cabe no limite, devolve o próprio arquivo, sem recompressar.

    Se passar do limite, recodifica em duas passadas para chegar perto do limite (qualidade máxima dentro dele).
    """
    tamanho_mb = os.path.getsize(video) / (1024 * 1024)
    if not forcar and tamanho_mb <= limite_mb:
        return video, False
    ffmpeg = capa._ffmpeg()
    inf = capa.informacoes(video)
    if not ffmpeg or not inf or inf[0] < 1:
        _log(log, f"{nome}: could not compress, uploading the original ({tamanho_mb:.0f} MB).")
        return video, False

    dur = inf[0]
    # orçamento de bits: 93% do limite, menos o áudio
    total_kbps = limite_mb * 8192 * 0.93 / dur
    video_kbps = int(total_kbps - AUDIO_KBPS)
    if video_kbps < 250:
        _log(log, f"{nome}: the video is long for {limite_mb} MB, so quality will be low.")
        video_kbps = max(video_kbps, 150)

    pasta = tempfile.mkdtemp(prefix="compacta_")
    saida = os.path.join(tempfile.gettempdir(), f"compacto_{os.getpid()}_{int(time.time())}.mp4")
    log_passada = os.path.join(pasta, "passada")
    nulo = "NUL" if os.name == "nt" else "/dev/null"
    _log(log, f"{nome}: compressing {tamanho_mb:.0f} MB to fit {limite_mb} MB (may take a moment)...")
    base = [ffmpeg, "-y", "-i", video, "-vf", _ESCALA + ",format=yuv420p", "-c:v", "libx264", "-preset", "medium",
            "-b:v", f"{video_kbps}k", "-maxrate", f"{int(video_kbps * 1.5)}k", "-bufsize", f"{video_kbps * 2}k",
            "-passlogfile", log_passada]
    try:
        p1 = subprocess.run(base + ["-pass", "1", "-an", "-f", "mp4", nulo],
                            capture_output=True, timeout=3600, creationflags=_SEM_JANELA)
        if p1.returncode != 0:
            raise RuntimeError(p1.stderr.decode("utf-8", "ignore")[-200:])
        p2 = subprocess.run(base + ["-pass", "2", "-c:a", "aac", "-b:a", f"{AUDIO_KBPS}k", "-ar", "44100", "-ac", "2",
                                    "-movflags", "+faststart", saida],
                            capture_output=True, timeout=3600, creationflags=_SEM_JANELA)
        if p2.returncode != 0 or not os.path.exists(saida) or os.path.getsize(saida) == 0:
            raise RuntimeError(p2.stderr.decode("utf-8", "ignore")[-200:])
    except Exception as e:
        _log(log, f"{nome}: compression failed ({e}), uploading the original.")
        try:
            os.remove(saida)
        except OSError:
            pass
        return video, False
    finally:
        shutil.rmtree(pasta, ignore_errors=True)
    novo = os.path.getsize(saida) / (1024 * 1024)
    if novo >= tamanho_mb:  # não adiantou: usa o original
        os.remove(saida)
        return video, False
    _log(log, f"{nome}: video compressed, {tamanho_mb:.0f} MB → {novo:.0f} MB.")
    return saida, True


def normalizar(video, log=None, nome=""):
    """Recodifica num formato que todas as plataformas aceitam (H.264, 30 fps, dimensões pares, SAR 1, AAC).

    Serve de segunda tentativa quando uma plataforma recusa o arquivo (ex.: TikTok 'picture_size_check_failed').
    Devolve o caminho do arquivo temporário, ou None se não conseguir.
    """
    ffmpeg = capa._ffmpeg()
    if not ffmpeg:
        return None
    saida = os.path.join(tempfile.gettempdir(), f"normal_{os.getpid()}_{int(time.time())}.mp4")
    _log(log, f"{nome}: re-encoding the video to a standard format and trying again...")
    r = subprocess.run(
        [ffmpeg, "-y", "-i", video, "-vf", _ESCALA + ",setsar=1,format=yuv420p", "-r", "30", "-c:v", "libx264",
         "-preset", "veryfast", "-crf", "20", "-c:a", "aac", "-b:a", f"{AUDIO_KBPS}k", "-ar", "44100", "-ac", "2",
         "-movflags", "+faststart", "-map_metadata", "-1", "-metadata:s:v", "rotate=0", saida],
        capture_output=True, timeout=3600, creationflags=_SEM_JANELA,
    )
    if r.returncode != 0 or not os.path.exists(saida) or os.path.getsize(saida) == 0:
        _log(log, f"{nome}: could not re-encode the video.")
        return None
    return saida


def vertical(video, log=None, nome=""):
    """Converte um vídeo horizontal (16:9) em vertical 9:16 (1080x1920): o vídeo original fica no centro,
    com o fundo desfocado preenchendo o resto. Devolve (caminho, é_temporário); se já for vertical, devolve o próprio."""
    inf = capa.informacoes(video)
    if inf and inf[2] >= inf[1]:
        return video, False
    ffmpeg = capa._ffmpeg()
    if not ffmpeg:
        return video, False
    saida = os.path.join(tempfile.gettempdir(), f"vertical_{os.getpid()}_{int(time.time() * 1000)}.mp4")
    _log(log, f"{nome}: converting to vertical 9:16 with a blurred background...")
    filtro = (
        "[0:v]split=2[a][b];"
        "[a]scale=1080:1920:force_original_aspect_ratio=increase,crop=1080:1920,boxblur=30:5[fundo];"
        "[b]scale=1080:-2[frente];"
        "[fundo][frente]overlay=(W-w)/2:(H-h)/2,setsar=1,format=yuv420p[v]"
    )
    r = subprocess.run(
        [ffmpeg, "-y", "-i", video, "-filter_complex", filtro, "-map", "[v]", "-map", "0:a?", "-r", "30",
         "-c:v", "libx264", "-preset", "veryfast", "-crf", "20", "-c:a", "aac", "-b:a", f"{AUDIO_KBPS}k",
         "-ar", "44100", "-ac", "2", "-movflags", "+faststart", "-map_metadata", "-1", saida],
        capture_output=True, timeout=3600, creationflags=_SEM_JANELA,
    )
    if r.returncode != 0 or not os.path.exists(saida) or os.path.getsize(saida) == 0:
        _log(log, f"{nome}: could not convert to vertical; using the original.")
        return video, False
    return saida, True
