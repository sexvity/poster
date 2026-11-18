"""Geração de título, descrição e hashtags em inglês (público dos EUA) com a API gratuita do Gemini."""
import json
import re
import time

import requests

# Tenta os modelos em ordem; se um não existir (404), passa para o próximo.
MODELOS = ["gemini-3.5-flash-lite", "gemini-3.1-flash-lite", "gemini-3.8-flash"]
URL_BASE = "https://generativelanguage.googleapis.com/v1beta/models/{modelo}:generateContent"


def sem_hashtags(texto):
    """Tira qualquer #palavra do texto (as hashtags só podem ficar no campo próprio)."""
    t = re.sub(r"#\w+", "", str(texto))
    return re.sub(r"[ \t]+", " ", re.sub(r"[ \t]+\n", "\n", t)).strip()


def lista_hashtags(texto):
    """Lê '#a #b a,b' e devolve ['#a', '#b'] sem repetir."""
    achadas = re.findall(r"[A-Za-z0-9_]+", str(texto))
    return list(dict.fromkeys("#" + h.lower() for h in achadas if h))


def _limpar_hashtags(lista):
    saida = []
    for h in lista:
        h = re.sub(r"[^A-Za-z0-9_]", "", str(h)).lower()  # só letras e números, como o público dos EUA usa
        if h:
            saida.append("#" + h)
    return list(dict.fromkeys(saida))  # remove repetidas


def gerar(api_key, descricao, nome_arquivo="", qtd_hashtags=8, quadros=None):
    if not api_key:
        raise RuntimeError("Gemini key missing. Open Settings and paste the key.")

    prompt = f"""You are a short-form video growth strategist for the US market (TikTok, Instagram Reels, YouTube Shorts).
The audience is American. Write in natural US English, the way Americans actually talk online.
Use current US slang and cultural references only where they genuinely fit the topic, never forced or cringe.

The creator describes the video below. The description may be in Portuguese: understand it and adapt it for
an American audience instead of translating word for word.

Video description from the creator: {descricao or '(no description)'}
File name: {nome_arquivo}
{"Frames sampled from the video, in order, are attached after this text. Base the copy on what you actually SEE in them plus the creator's description. The creator's description wins on facts the frames cannot show (city, event, names). NEVER invent details that neither the frames nor the description support: time of day, weather, place, landmarks, brands, numbers or people. If something is unclear, stay vague instead of guessing." if quadros else ""}

Return:
- "title": a scroll-stopping hook, max 70 characters, NO hashtags and no # symbol, no quotation marks, no emojis.
  Be honest: never promise something the video does not show.
- "description": 1-2 short sentences with a hook, ending with a question or call to action that invites comments. NO hashtags and no # symbol in it: hashtags go only in the "hashtags" field.
- "hashtags": exactly {qtd_hashtags} hashtags, lowercase, letters and numbers only, no spaces, no duplicates:
  2-3 broad high-reach tags that are popular in the US (for example fyp, viral, trending),
  3-4 niche tags specific to this topic, and 1-2 tags tied to US culture or communities around the topic.
Answer ONLY with JSON: {{"title": "...", "description": "...", "hashtags": ["...", "..."]}}"""

    partes = [{"text": prompt}]
    for b64 in quadros or []:
        partes.append({"inline_data": {"mime_type": "image/jpeg", "data": b64}})
    corpo = {
        "contents": [{"parts": partes}],
        "generationConfig": {"responseMimeType": "application/json", "temperature": 0.8},
    }
    r = None
    # Se um modelo estiver fora do ar (404) ou sobrecarregado (500/503), tenta de novo e passa para o próximo.
    for modelo in MODELOS:
        for tentativa in range(2):
            try:
                r = requests.post(
                    URL_BASE.format(modelo=modelo),
                    headers={"x-goog-api-key": api_key, "Content-Type": "application/json"},
                    json=corpo,
                    timeout=90,
                )
            except requests.RequestException:
                r = None
                time.sleep(2)
                continue
            if r.status_code in (500, 502, 503, 504):
                time.sleep(2 + 3 * tentativa)
                continue
            break
        if r is not None and r.status_code not in (404, 500, 502, 503, 504):
            break
    if r is None:
        raise RuntimeError("Cannot reach Gemini. Check your internet connection and try again.")
    if r.status_code in (500, 502, 503, 504):
        raise RuntimeError("Gemini is overloaded right now (temporary error). Wait a minute and click again.")
    if r.status_code == 429:
        raise RuntimeError("Gemini free limit reached. Wait a minute and try again.")
    if r.status_code in (400, 403):
        raise RuntimeError(f"Gemini rejected the key or the request ({r.status_code}): {r.text[:200]}")
    if r.status_code == 404:
        raise RuntimeError("No Gemini model was found. Please report it so the model list can be updated.")
    r.raise_for_status()

    texto = r.json()["candidates"][0]["content"]["parts"][0]["text"]
    dados = json.loads(texto)
    if isinstance(dados, list) and dados:
        dados = dados[0]
    titulo = dados.get("title") or dados.get("titulo") or ""
    desc = dados.get("description") or dados.get("descricao") or ""
    return {
        "titulo": sem_hashtags(str(titulo).strip().strip('"'))[:100],
        "descricao": sem_hashtags(desc),
        "hashtags": _limpar_hashtags(dados.get("hashtags", [])),
    }
