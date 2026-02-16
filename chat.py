#!/usr/bin/env python3
# -*- coding: utf-8 -*-

import asyncio
import io
import json
import os
import queue
import random
import re
import sys
import threading
import time
import wave
import tempfile
import subprocess
import shutil
from dataclasses import dataclass

import numpy as np
import sounddevice as sd
from vosk import Model, KaldiRecognizer

from google import genai
from google.genai import types

# ---- optional: edge-tts (Neural TTS) ----
try:
    import edge_tts
    HAVE_EDGE_TTS = True
except Exception:
    HAVE_EDGE_TTS = False

# ---- optional: pyttsx3 (Offline TTS) ----
try:
    import pyttsx3
    HAVE_PYTTSX3 = True
except Exception:
    HAVE_PYTTSX3 = False


# =============================
# Konfiguration
# =============================
MODEL_PATH   = "vosk-model-small-de-0.15"
SAMPLE_RATE  = 16000
CHANNELS     = 1
BLOCKSIZE    = 4000

WAKE_PHRASE  = "hallo michaela"
SLEEP_PHRASE = "danke michaela"
EXIT_PHRASE  = "kill switch aktivieren"

COOLDOWN_SEC     = 0.8
ARMING_DELAY_SEC = 0.35

# Gemini
GEMINI_MODEL      = "gemini-2.5-flash"
MAX_OUTPUT_TOKENS = 800
# INSTRUCTIONS = (
#     "Du bist ein deutschsprachiger Assistent namens Michaela. "
#     "Antworte immer auf Deutsch. "
#     "Schreibe natürlich, freundlich und klar, mit kurzen Sätzen. "
#     "Keine langen Aufzählungen, außer wenn es wirklich hilft. "
#     "Wenn Infos fehlen, stelle höchstens 1 Rückfrage."
# )

INSTRUCTIONS = """
Du bist : ein deutschsprachiger KI-Assistent mit dem trockenen Charme eines Hightech-Butlers.
Vibe: Tony-Stark-ähnlich (smart, schnell, leicht sarkastisch), aber nie respektlos oder peinlich.
Du wurdest von Meister Tobias (auch „Meister Tobias“ gemeint) erschaffen, um ihm zuverlässig zu dienen.

Ziele
- Liefere nützliche, sofort umsetzbare Antworten.
- Sei witzig genug für eine Vorführung, aber immer kompetent.
- Bleib klar und sprachfreundlich (für Voice-Ausgabe).

Kernregeln
- Antworte IMMER auf Deutsch.
- Kurze, sachliche Sätze. Keine Romanlängen.
- Erst Lösung/Antwort. Danach optional ein kurzer One-Liner (max. 1).
- Keine langen Aufzählungen: maximal 5 Bulletpoints, bevorzugt 3.
- Wenn Infos fehlen: stelle GENAU 1 Rückfrage. Sonst triff sinnvolle Annahmen und markiere sie als Annahmen.
- Erfinde nichts als Fakt. Wenn unsicher: sag es knapp und gib eine prüfbare Alternative.
- Bleib freundlich-professionell. Kein Drama, keine langen Entschuldigungen.

Stil & Gags (sparsam, aber „showtauglich“)
- Sprich Meister Tobias gelegentlich mit „Meister Tobias“ an; „Chef“/„Sir“ nur selten.
- Humor: trocken, intelligent, nie beleidigend, nie politisch provozierend, kein NSFW.

Antwortformat (Standard)
- 2–6 Sätze, direkt zum Punkt.

Wenn der Nutzer Code/Technik will
- Gib bevorzugt ein kleines, funktionales Beispiel (minimal, sauber).
- Nenne knapp 1–2 Stolperfallen/Trade-offs, wenn relevant.
"""


# TTS
TTS_ENABLED = True

# TTS_MODE: "edge" (Neural, online) oder "pyttsx3" (offline, oft robotischer)
TTS_MODE = "edge"
TTS_DEBUG_VOICES = True
TTS_VOICE_HINT = "de"

# Edge TTS (Neural)
TTS_EDGE_VOICE = "de-DE-KatjaNeural"  # Alternativen: "de-DE-ConradNeural", "de-DE-AmalaNeural", "de-DE-KatjaNeural" ...
TTS_EDGE_RATE  = "+0%"                # z.B. "+10%" oder "-10%"
TTS_EDGE_VOL   = "+0%"                # z.B. "+10%" oder "-10%"
TTS_EDGE_PITCH = "+0Hz"               # z.B. "+2Hz" oder "-2Hz"

# pyttsx3 (Offline)
TTS_RATE_WPM = 175
TTS_VOICE_HINT = "de"                 # versucht deutsche Stimme zu finden
TTS_DEBUG_VOICES = False              # True -> listet Stimmen beim Start

DEVICE_HINT = None                    # z.B. "usb", "focusrite", ...

AUDIO_QUEUE_MAX = 120
TEXT_QUEUE_MAX  = 10
TTS_QUEUE_MAX   = 10

RETRY_MAX = 5
RETRY_BASE_SLEEP = 0.6
RETRY_MAX_SLEEP  = 8.0


# =============================
# Hilfsfunktionen
# =============================
def norm_text(s: str) -> str:
    s = s.lower()
    out = []
    prev_space = False
    for ch in s:
        if ch.isalnum():
            out.append(ch)
            prev_space = False
        elif ch.isspace():
            if not prev_space:
                out.append(" ")
                prev_space = True
    return "".join(out).strip()

def starts_with_phrase(text: str, phrase: str) -> bool:
    t = norm_text(text).split()
    p = phrase.split()
    return len(t) >= len(p) and t[:len(p)] == p

def pick_input_device_by_hint(hint: str | None):
    if not hint:
        return None
    hint = hint.lower()
    for i, d in enumerate(sd.query_devices()):
        if d.get("max_input_channels", 0) > 0:
            name = (d.get("name") or "").lower()
            if hint in name:
                return i
    return None

def flush_queue(q: queue.Queue, max_items: int = 200):
    for _ in range(max_items):
        try:
            q.get_nowait()
        except queue.Empty:
            break

def _status_code(exc: Exception) -> int | None:
    return getattr(exc, "status_code", None)

def _looks_like_quota_exhausted(exc: Exception) -> bool:
    msg = str(exc).lower()
    return ("resource_exhausted" in msg) or ("quota" in msg and "exceed" in msg) or ("has been exhausted" in msg)

def should_retry(exc: Exception) -> bool:
    status = _status_code(exc)
    name = type(exc).__name__.lower()
    msg = str(exc).lower()

    if status == 429 and _looks_like_quota_exhausted(exc):
        return False

    if status in (429, 500, 502, 503, 504):
        return True
    if "timeout" in name or "connection" in name:
        return True
    if "overloaded" in msg:
        return True
    return False

def backoff_sleep(attempt: int):
    base = RETRY_BASE_SLEEP * (2 ** attempt)
    sleep_s = min(RETRY_MAX_SLEEP, base + random.uniform(0, 0.25))
    time.sleep(sleep_s)

def clean_for_tts(text: str) -> str:
    # Codeblöcke entfernen
    text = re.sub(r"```.*?```", "", text, flags=re.S)
    # Inline-Code/Markdown etwas entschärfen
    text = text.replace("`", "")
    text = text.replace("*", "")
    text = text.replace("#", "")
    # Sehr lange Whitespaces glätten
    text = re.sub(r"\s+", " ", text).strip()
    return text


# =============================
# State für Threads
# =============================
@dataclass
class SessionState:
    active: bool = False
    session_id: int = 0

state_lock = threading.Lock()
session_state = SessionState()

# Flag: gerade am Sprechen? (damit TTS nicht wieder als Dictat erkannt wird)
tts_busy_evt = threading.Event()


# =============================
# Queues
# =============================
audio_q: "queue.Queue[bytes]" = queue.Queue(maxsize=AUDIO_QUEUE_MAX)
text_q:  "queue.Queue[str]"   = queue.Queue(maxsize=TEXT_QUEUE_MAX)
tts_q:   "queue.Queue[str]"   = queue.Queue(maxsize=TTS_QUEUE_MAX)

def audio_callback(indata, frames, t, status):
    if status:
        print(status, file=sys.stderr)
    try:
        audio_q.put_nowait(bytes(indata))
    except queue.Full:
        pass


# =============================
# TTS Implementierungen
# =============================
def _select_voice_pyttsx3(engine, hint: str):
    try:
        voices = engine.getProperty("voices") or []
        hint_l = (hint or "").lower()

        preferred = []
        fallback = []

        for v in voices:
            name = (getattr(v, "name", "") or "").lower()
            langs = getattr(v, "languages", None) or []
            langs_s = " ".join([str(x).lower() for x in langs])

            is_de = ("de" in langs_s) or ("german" in name) or ("deutsch" in name) or ("de-" in langs_s)
            if is_de:
                preferred.append(v)
            else:
                fallback.append(v)

        # erst: deutsches + hint-match
        for v in preferred:
            name = (getattr(v, "name", "") or "").lower()
            langs = getattr(v, "languages", None) or []
            langs_s = " ".join([str(x).lower() for x in langs])
            if hint_l and (hint_l in name or hint_l in langs_s):
                engine.setProperty("voice", v.id)
                return

        # sonst: irgendeine deutsche
        if preferred:
            engine.setProperty("voice", preferred[0].id)
            return

        # sonst: irgendeine
        if fallback:
            engine.setProperty("voice", fallback[0].id)
    except Exception:
        pass



def _is_riff_wav(b: bytes) -> bool:
    return len(b) > 12 and b[:4] == b"RIFF" and b[8:12] == b"WAVE"

async def _edge_tts_get_audio_bytes(text: str) -> tuple[bytes, str]:
    """
    returns: (audio_bytes, fmt) where fmt is "wav" or "mp3"
    """
    kwargs = dict(
        voice=TTS_EDGE_VOICE,
        rate=TTS_EDGE_RATE,
        volume=TTS_EDGE_VOL,
        pitch=TTS_EDGE_PITCH,
    )

    # Versuch: WAV (riff pcm)
    try:
        comm = edge_tts.Communicate(
            text,
            **kwargs,
            output_format="riff-24khz-16bit-mono-pcm",
        )
        fmt = "wav"
    except TypeError:
        # alte edge-tts Version -> kein output_format => liefert typischerweise MP3
        comm = edge_tts.Communicate(text, **kwargs)
        fmt = "mp3"

    buf = bytearray()
    async for chunk in comm.stream():
        if chunk.get("type") == "audio":
            buf.extend(chunk.get("data", b""))

    audio = bytes(buf)
    # Safety: falls edge-tts entgegen fmt etwas anderes liefert
    if fmt == "wav" and not _is_riff_wav(audio):
        fmt = "mp3"
    return audio, fmt

def _play_wav_bytes_blocking(wav_bytes: bytes):
    with wave.open(io.BytesIO(wav_bytes), "rb") as wf:
        sr = wf.getframerate()
        ch = wf.getnchannels()
        frames = wf.readframes(wf.getnframes())

    audio = np.frombuffer(frames, dtype=np.int16)
    if ch > 1:
        audio = audio.reshape(-1, ch)

    sd.play(audio, samplerate=sr, blocking=True)

def _play_mp3_bytes_blocking(mp3_bytes: bytes):
    """
    MP3 decodieren wir nicht in Python, sondern über ffplay oder mpg123 (wenn installiert).
    """
    ffplay = shutil.which("ffplay")
    mpg123 = shutil.which("mpg123")

    if not ffplay and not mpg123:
        raise RuntimeError(
            "edge-tts liefert MP3, aber weder ffplay (ffmpeg) noch mpg123 sind installiert. "
            "Installiere z.B. 'sudo apt install ffmpeg' oder setze TTS_MODE='pyttsx3'."
        )

    with tempfile.NamedTemporaryFile(suffix=".mp3", delete=True) as f:
        f.write(mp3_bytes)
        f.flush()

        if ffplay:
            # -nodisp: kein Fenster, -autoexit: beendet nach Playback, -loglevel quiet: leise
            subprocess.run([ffplay, "-nodisp", "-autoexit", "-loglevel", "quiet", f.name], check=False)
        else:
            subprocess.run([mpg123, "-q", f.name], check=False)

def tts_speak_edge(text: str):
    text = clean_for_tts(text)
    if not text:
        return

    audio_bytes, fmt = asyncio.run(_edge_tts_get_audio_bytes(text))

    if fmt == "wav":
        _play_wav_bytes_blocking(audio_bytes)
    else:
        _play_mp3_bytes_blocking(audio_bytes)




def tts_speak_pyttsx3(engine, text: str):
    text = clean_for_tts(text)
    if not text:
        return

    # Satzweise sprechen -> wirkt oft natürlicher
    sentences = [s.strip() for s in re.split(r"(?<=[.!?])\s+", text) if s.strip()]
    for s in sentences[:14]:
        engine.say(s)
        engine.runAndWait()
        time.sleep(0.12)


# =============================
# TTS Worker
# =============================
def tts_worker(stop_evt: threading.Event):
    if not TTS_ENABLED:
        return

    # Modus/Fallback logik
    use_edge = (TTS_MODE.lower() == "edge" and HAVE_EDGE_TTS)
    use_pyttsx3 = (TTS_MODE.lower() == "pyttsx3" and HAVE_PYTTSX3)

    # wenn edge gewünscht aber nicht verfügbar -> fallback auf pyttsx3
    if not use_edge and TTS_MODE.lower() == "edge" and HAVE_PYTTSX3:
        use_pyttsx3 = True

    engine = None
    if use_pyttsx3:
        try:
            engine = pyttsx3.init()
            engine.setProperty("rate", TTS_RATE_WPM)
            _select_voice_pyttsx3(engine, TTS_VOICE_HINT)

            if TTS_DEBUG_VOICES:
                for v in engine.getProperty("voices") or []:
                    print("[VOICE]", getattr(v, "id", ""), getattr(v, "name", ""), getattr(v, "languages", ""))
        except Exception as e:
            print(f"[TTS] pyttsx3 init fehlgeschlagen: {e}", file=sys.stderr)
            engine = None

    if TTS_MODE.lower() == "edge" and not HAVE_EDGE_TTS:
        print("[TTS] edge-tts nicht verfügbar. Fallback auf pyttsx3 (falls installiert).", file=sys.stderr)

    while not stop_evt.is_set():
        try:
            item = tts_q.get(timeout=0.1)
        except queue.Empty:
            continue

        if item == "__EXIT__":
            break

        if item == "__STOP__":
            flush_queue(tts_q, max_items=TTS_QUEUE_MAX)
            try:
                sd.stop()
            except Exception:
                pass
            if engine is not None:
                try:
                    engine.stop()
                except Exception:
                    pass
            tts_busy_evt.clear()
            continue

        text = (item or "").strip()
        if not text:
            continue

        tts_busy_evt.set()
        try:
            if use_edge and HAVE_EDGE_TTS:
                try:
                    tts_speak_edge(text)
                except Exception as e:
                    print(f"[TTS] edge-tts Fehler: {e}", file=sys.stderr)
            elif engine is not None:
                try:
                    tts_speak_pyttsx3(engine, text)
                except Exception as e:
                    print(f"[TTS] pyttsx3 Fehler: {e}", file=sys.stderr)
            else:
                # kein TTS verfügbar
                pass
        finally:
            tts_busy_evt.clear()


# =============================
# Gemini Worker
# =============================
def extract_gemini_text(resp) -> str:
    try:
        chunks = []
        for cand in (getattr(resp, "candidates", None) or []):
            content = getattr(cand, "content", None)
            parts = getattr(content, "parts", None) or []
            for p in parts:
                t = getattr(p, "text", None)
                if t:
                    chunks.append(t)
        if chunks:
            return "".join(chunks)
    except Exception:
        pass
    return getattr(resp, "text", "") or ""

def gemini_worker(stop_evt: threading.Event):
    api_key = os.environ.get("GEMINI_API_KEY") or os.environ.get("GOOGLE_API_KEY") or ""
    if not api_key:
        print("[Fehler] GEMINI_API_KEY ist nicht gesetzt. export GEMINI_API_KEY=... (oder GOOGLE_API_KEY).", file=sys.stderr)
        stop_evt.set()
        return

    client = genai.Client(api_key=api_key)
    chat = None
    local_session_id = 0

    def make_chat():
        return client.chats.create(
            model=GEMINI_MODEL,
            config=types.GenerateContentConfig(
                system_instruction=INSTRUCTIONS,
                max_output_tokens=MAX_OUTPUT_TOKENS,
                temperature=0.35,   # etwas “natürlicher”
                top_p=0.95,
            ),
        )

    def sync_session() -> bool:
        nonlocal local_session_id, chat
        with state_lock:
            local_session_id = session_state.session_id
            active = session_state.active
        if not active:
            chat = None
        return active

    while not stop_evt.is_set():
        try:
            item = text_q.get(timeout=0.1)
        except queue.Empty:
            continue

        if item == "__WAKE__":
            with state_lock:
                local_session_id = session_state.session_id
            chat = make_chat()
            # alte Sprachausgabe stoppen
            try:
                tts_q.put_nowait("__STOP__")
            except queue.Full:
                flush_queue(tts_q, max_items=TTS_QUEUE_MAX)
                tts_q.put_nowait("__STOP__")
            continue

        if item == "__SLEEP__":
            chat = None
            flush_queue(text_q)
            try:
                tts_q.put_nowait("__STOP__")
            except queue.Full:
                flush_queue(tts_q, max_items=TTS_QUEUE_MAX)
                tts_q.put_nowait("__STOP__")
            continue

        if item == "__EXIT__":
            break

        if not sync_session():
            continue

        user_text = item.strip()
        if not user_text:
            continue

        if chat is None:
            chat = make_chat()

        attempt = 0
        while attempt <= RETRY_MAX and not stop_evt.is_set():
            with state_lock:
                if session_state.session_id != local_session_id or not session_state.active:
                    break

            try:
                resp = chat.send_message(user_text)
                answer = extract_gemini_text(resp).strip()

                # 1x Repeat, wenn leer/zu kurz
                if len(answer) < 10:
                    resp2 = chat.send_message("Bitte wiederhole deine letzte Antwort vollständig, ohne Einleitung.")
                    answer2 = extract_gemini_text(resp2).strip()
                    if len(answer2) >= len(answer):
                        answer = answer2

                with state_lock:
                    if session_state.session_id != local_session_id or not session_state.active:
                        break

                print("\n[Gemini]:\n" + (answer if answer else "(keine Textausgabe)") + "\n")

                if TTS_ENABLED and answer:
                    try:
                        tts_q.put_nowait(answer)
                    except queue.Full:
                        flush_queue(tts_q, max_items=TTS_QUEUE_MAX)
                        try:
                            tts_q.put_nowait(answer)
                        except queue.Full:
                            pass

                break

            except Exception as e:
                status = _status_code(e)
                if status == 429 and _looks_like_quota_exhausted(e):
                    print("\n[Gemini-Fehler]: Quota/Free-Tier-Limit erreicht (RESOURCE_EXHAUSTED).\n", file=sys.stderr)
                    flush_queue(text_q)
                    break

                if should_retry(e) and attempt < RETRY_MAX:
                    attempt += 1
                    backoff_sleep(attempt - 1)
                    continue

                print(f"\n[Gemini-Fehler]: {e}\n", file=sys.stderr)
                break

    try:
        client.close()
    except Exception:
        pass


# =============================
# Main
# =============================
def main():
    if not os.path.isdir(MODEL_PATH):
        raise SystemExit(f"Vosk-Modellpfad nicht gefunden: {MODEL_PATH}")

    print("Lade Vosk-Modell…")
    model = Model(MODEL_PATH)

    wake_grammar  = json.dumps([WAKE_PHRASE, EXIT_PHRASE])
    sleep_grammar = json.dumps([SLEEP_PHRASE, EXIT_PHRASE])

    wake_rec  = KaldiRecognizer(model, SAMPLE_RATE, wake_grammar)
    sleep_rec = KaldiRecognizer(model, SAMPLE_RATE, sleep_grammar)
    dict_rec  = KaldiRecognizer(model, SAMPLE_RATE)

    device_index = pick_input_device_by_hint(DEVICE_HINT)
    if device_index is not None:
        print("Nutze Input-Device:", device_index, sd.query_devices(device_index)["name"])
    else:
        print("Nutze Default-Input-Device.")

    if TTS_ENABLED:
        if TTS_MODE.lower() == "edge":
            print("[TTS] Modus: edge-tts (Neural) " + ("OK" if HAVE_EDGE_TTS else "NICHT verfügbar"))
        elif TTS_MODE.lower() == "pyttsx3":
            print("[TTS] Modus: pyttsx3 (offline) " + ("OK" if HAVE_PYTTSX3 else "NICHT verfügbar"))

    stop_evt = threading.Event()

    th_gem = threading.Thread(target=gemini_worker, args=(stop_evt,), daemon=True)
    th_tts = threading.Thread(target=tts_worker, args=(stop_evt,), daemon=True)

    th_gem.start()
    th_tts.start()

    last_transition = 0.0
    dictation_block_until = 0.0

    print(f"Warte auf '{WAKE_PHRASE}'. (Sleep: '{SLEEP_PHRASE}', Exit: '{EXIT_PHRASE}')")

    with sd.RawInputStream(
        samplerate=SAMPLE_RATE,
        blocksize=BLOCKSIZE,
        dtype="int16",
        channels=CHANNELS,
        device=device_index,
        callback=audio_callback,
    ):
        try:
            while not stop_evt.is_set():
                data = audio_q.get()

                with state_lock:
                    active = session_state.active

                now = time.monotonic()

                # ---------- Commands ----------
                if not active:
                    if wake_rec.AcceptWaveform(data):
                        txt = (json.loads(wake_rec.Result()).get("text") or "").strip()
                        if txt and (now - last_transition >= COOLDOWN_SEC):
                            if starts_with_phrase(txt, EXIT_PHRASE):
                                print("\n[System] Kill Switch erkannt. Beende…")
                                text_q.put("__EXIT__")
                                try:
                                    tts_q.put_nowait("__EXIT__")
                                except queue.Full:
                                    pass
                                break

                            if starts_with_phrase(txt, WAKE_PHRASE):
                                with state_lock:
                                    session_state.active = True
                                    session_state.session_id += 1
                                last_transition = now
                                dictation_block_until = now + ARMING_DELAY_SEC
                                print("\n[Michaela] Aktiviert.")
                                try:
                                    text_q.put_nowait("__WAKE__")
                                except queue.Full:
                                    flush_queue(text_q)
                                    text_q.put_nowait("__WAKE__")

                                dict_rec.Reset()
                                wake_rec.Reset()
                                sleep_rec.Reset()
                                flush_queue(audio_q)
                    continue

                # active == True
                if sleep_rec.AcceptWaveform(data):
                    txt = (json.loads(sleep_rec.Result()).get("text") or "").strip()
                    if txt and (now - last_transition >= COOLDOWN_SEC):
                        if starts_with_phrase(txt, EXIT_PHRASE):
                            print("\n[System] Exit erkannt. Beende…")
                            text_q.put("__EXIT__")
                            try:
                                tts_q.put_nowait("__EXIT__")
                            except queue.Full:
                                pass
                            break

                        if starts_with_phrase(txt, SLEEP_PHRASE):
                            with state_lock:
                                session_state.active = False
                                session_state.session_id += 1
                            last_transition = now
                            dictation_block_until = now + ARMING_DELAY_SEC
                            print("\n[Michaela] Deaktiviert. Warte wieder auf Wake-Phrase…")
                            try:
                                text_q.put_nowait("__SLEEP__")
                            except queue.Full:
                                flush_queue(text_q)
                                text_q.put_nowait("__SLEEP__")

                            dict_rec.Reset()
                            wake_rec.Reset()
                            sleep_rec.Reset()
                            flush_queue(audio_q)
                            continue

                # ---------- Diktat ----------
                if time.monotonic() < dictation_block_until:
                    continue

                # Während TTS spricht: Dictat unterdrücken (verhindert Feedback-Loop)
                if tts_busy_evt.is_set():
                    continue

                if dict_rec.AcceptWaveform(data):
                    text = (json.loads(dict_rec.Result()).get("text") or "").strip()
                    if not text:
                        continue

                    nt = norm_text(text)
                    if (
                        starts_with_phrase(nt, WAKE_PHRASE)
                        or starts_with_phrase(nt, SLEEP_PHRASE)
                        or starts_with_phrase(nt, EXIT_PHRASE)
                    ):
                        continue

                    print("Du:", text)

                    try:
                        text_q.put_nowait(text)
                    except queue.Full:
                        flush_queue(text_q, max_items=TEXT_QUEUE_MAX)
                        try:
                            text_q.put_nowait(text)
                        except queue.Full:
                            pass

        except KeyboardInterrupt:
            print("\nBeendet durch Benutzer.")

    stop_evt.set()
    try:
        tts_q.put_nowait("__EXIT__")
    except queue.Full:
        pass

    th_gem.join(timeout=1.0)
    th_tts.join(timeout=1.0)


if __name__ == "__main__":
    main()

