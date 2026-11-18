"""Horários de pico para o público dos EUA (fuso de Nova York) e espera até o horário agendado.

Os horários abaixo são um ponto de partida montado a partir de estudos públicos de 2026
(Buffer, Sprout Social e outros). Eles não concordam em tudo, então usei os pontos em comum.
Depois de algumas semanas, compare com as estatísticas da sua própria conta e ajuste a tabela.
"""
import sys
import time
from datetime import datetime, timedelta, timezone

try:
    from zoneinfo import ZoneInfo

    FUSO = ZoneInfo("America/New_York")
except Exception:  # Windows sem o pacote tzdata
    FUSO = None

# (dia da semana, hora, minuto) em horário de Nova York. Segunda = 0 ... Domingo = 6
PICOS = {
    "YouTube Shorts": [(0, 18, 0), (2, 18, 0), (3, 18, 0), (4, 16, 0), (5, 17, 0), (6, 15, 0)],
    "Instagram Reels": [(0, 17, 0), (1, 18, 0), (2, 9, 0), (2, 18, 0), (3, 9, 0), (3, 18, 0), (5, 11, 0), (6, 12, 0)],
    "TikTok": [(0, 13, 0), (1, 19, 0), (3, 19, 0), (4, 19, 0), (5, 9, 0), (5, 20, 0), (6, 9, 0)],
}

DIAS = ["Mon", "Tue", "Wed", "Thu", "Fri", "Sat", "Sun"]


def segundos_ate(alvo):
    """Segundos até `alvo`, contados em UTC (certo mesmo na troca de horário de verão)."""
    return (alvo.astimezone(timezone.utc) - datetime.now(timezone.utc)).total_seconds()


def proximo_pico(plataforma, agora=None):
    """Próximo horário de pico (com pelo menos 2 minutos de folga) para a plataforma."""
    if FUSO is None:
        raise RuntimeError("The tzdata package is missing. Run iniciar.bat again to install it.")
    agora = (agora or datetime.now(FUSO)).astimezone(FUSO)
    limite = (agora + timedelta(minutes=2)).astimezone(timezone.utc)
    achados = []
    for d in range(0, 9):
        dia = (agora + timedelta(days=d)).date()
        for wd, h, m in PICOS[plataforma]:
            if dia.weekday() == wd:
                alvo = datetime(dia.year, dia.month, dia.day, h, m, tzinfo=FUSO)
                if alvo.astimezone(timezone.utc) > limite:
                    achados.append(alvo)
    return min(achados)


def _fmt(dt):
    return f"{DIAS[dt.weekday()]} {dt:%H:%M}"


def descrever(alvo):
    """Ex.: 'Thu 18:00 New York time · Thu 19:00 your time'."""
    return f"{_fmt(alvo)} New York time · {_fmt(alvo.astimezone())} your time"


def duracao(segundos):
    s = max(0, int(segundos))
    d, resto = divmod(s, 86400)
    h, resto = divmod(resto, 3600)
    m = resto // 60
    if d:
        return f"{d}d {h}h"
    if h:
        return f"{h}h {m:02d}min"
    return f"{m} min"


def faltam(alvo):
    return duracao(segundos_ate(alvo))


def esperar(alvo, cancelar, aviso=None):
    """Espera até `alvo`. Devolve False se `cancelar` (threading.Event) for acionado."""
    ultimo_aviso = time.time()
    while True:
        falta = segundos_ate(alvo)
        if falta <= 0:
            return True
        if aviso and time.time() - ultimo_aviso > 1800:  # a cada 30 minutos
            aviso(f"{duracao(falta)} left")
            ultimo_aviso = time.time()
        if cancelar.wait(timeout=min(20, falta)):
            return False


def evitar_suspensao(ligar):
    """No Windows, impede o computador de dormir enquanto espera o horário agendado."""
    if sys.platform != "win32":
        return
    try:
        import ctypes

        ES_CONTINUOUS = 0x80000000
        ES_SYSTEM_REQUIRED = 0x00000001
        ctypes.windll.kernel32.SetThreadExecutionState(ES_CONTINUOUS | (ES_SYSTEM_REQUIRED if ligar else 0))
    except Exception:
        pass
