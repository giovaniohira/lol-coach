"""Áudio e screenshot. TTS na fila pra não atropelar o jogo."""

from __future__ import annotations

import asyncio
import io
import os
import tempfile
import threading
import time
import wave
from queue import Queue

import numpy as np

VOICE = os.environ.get("COACH_VOICE", "pt-BR-AntonioNeural")
HOTKEY = os.environ.get("COACH_HOTKEY", "f8")
FS = 16000


class Speaker:
    def __init__(self):
        import pygame

        pygame.mixer.init()
        self._pygame = pygame
        self.q: Queue[str] = Queue(maxsize=4)
        self._thread = threading.Thread(target=self._run, daemon=True)
        self._thread.start()

    def say(self, text: str, drop_if_busy: bool = False) -> None:
        text = (text or "").strip()
        if not text:
            return
        print(f"coach: {text}")
        if drop_if_busy and self.q.full():
            return
        try:
            self.q.put_nowait(text)
        except Exception:
            pass

    def _run(self) -> None:
        while True:
            text = self.q.get()
            try:
                self._play(text)
            except Exception as e:
                print(f"tts falhou: {e}")

    def _play(self, text: str) -> None:
        import edge_tts

        fd, path = tempfile.mkstemp(suffix=".mp3")
        os.close(fd)
        try:
            asyncio.run(
                edge_tts.Communicate(text, VOICE, rate="+12%").save(path)
            )
            self._pygame.mixer.music.load(path)
            self._pygame.mixer.music.play()
            while self._pygame.mixer.music.get_busy():
                time.sleep(0.05)
            self._pygame.mixer.music.unload()
        finally:
            try:
                os.remove(path)
            except OSError:
                pass


def screenshot_jpeg(max_w: int = 512, quality: int = 32) -> bytes:
    import mss
    from PIL import Image

    with mss.mss() as s:
        raw = s.grab(s.monitors[1])
    img = Image.frombytes("RGB", raw.size, raw.bgra, "raw", "BGRX")
    if img.width > max_w:
        img = img.resize((max_w, int(img.height * max_w / img.width)), Image.Resampling.BILINEAR)
    buf = io.BytesIO()
    img.save(buf, format="JPEG", quality=quality, optimize=True)
    return buf.getvalue()


def record_while_held(key: str = HOTKEY, max_s: float = 12) -> np.ndarray:
    import sounddevice as sd

    try:
        import keyboard

        if not keyboard.is_pressed(key):
            return np.zeros(0, dtype=np.int16)
    except Exception:
        return np.zeros(0, dtype=np.int16)

    chunks: list[np.ndarray] = []
    started = time.time()
    with sd.InputStream(samplerate=FS, channels=1, dtype="int16") as stream:
        while time.time() - started < max_s and keyboard.is_pressed(key):
            data, _ = stream.read(1024)
            chunks.append(data.copy())
    if not chunks:
        return np.zeros(0, dtype=np.int16)
    return np.concatenate(chunks)


def record_seconds(sec: float = 6) -> np.ndarray:
    import sounddevice as sd

    audio = sd.rec(int(sec * FS), samplerate=FS, channels=1, dtype="int16")
    sd.wait()
    return audio.reshape(-1)


def to_wav_path(audio: np.ndarray) -> str:
    fd, path = tempfile.mkstemp(suffix=".wav")
    os.close(fd)
    with wave.open(path, "wb") as w:
        w.setnchannels(1)
        w.setsampwidth(2)
        w.setframerate(FS)
        w.writeframes(audio.tobytes())
    return path


def transcribe(audio: np.ndarray, client=None) -> str:
    if audio.size < FS * 0.35:
        return ""
    path = to_wav_path(audio)
    try:
        import speech_recognition as sr

        r = sr.Recognizer()
        with sr.AudioFile(path) as source:
            clip = r.record(source)
        return (r.recognize_google(clip, language="pt-BR") or "").strip()
    except Exception as e:
        print(f"stt falhou: {e}")
        return ""
    finally:
        try:
            os.remove(path)
        except OSError:
            pass


def beep() -> None:
    try:
        import winsound

        winsound.Beep(740, 70)
    except Exception:
        pass
