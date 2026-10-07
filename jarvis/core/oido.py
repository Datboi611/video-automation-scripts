"""Voz a texto: Whisper en Groq (gratis, ultra rápido) o faster-whisper local (offline)."""
import io
import logging
import wave

import numpy as np

from . import config

log = logging.getLogger("jarvis")

ALUCINACIONES = (
    "gracias por ver", "subtítulos", "amara.org", "suscríbete", "thanks for watching",
    "thank you for watching", "like and subscribe",
)


def _wav(audio):
    buf = io.BytesIO()
    with wave.open(buf, "wb") as w:
        w.setnchannels(1)
        w.setsampwidth(2)
        w.setframerate(16000)
        w.writeframes(audio.tobytes())
    return buf.getvalue()


class Oido:
    def __init__(self, cfg):
        self.cfg = cfg
        self.key_groq = config.clave(cfg, "groq")
        self.motor = cfg["stt"]["motor"]
        if self.motor == "auto":
            self.motor = "groq" if self.key_groq else "local"
        self._local = None
        self._groq = None

    def _transcribir_groq(self, audio):
        if self._groq is None:
            from openai import OpenAI
            self._groq = OpenAI(api_key=self.key_groq, base_url=config.URLS_PROVEEDOR["groq"], timeout=20)
        r = self._groq.audio.transcriptions.create(
            model="whisper-large-v3-turbo", file=("voz.wav", _wav(audio)),
            response_format="verbose_json", prompt="Jarvis.",
        )
        return r.text, getattr(r, "language", "") or ""

    def _transcribir_local(self, audio):
        if self._local is None:
            from faster_whisper import WhisperModel
            self._local = WhisperModel(self.cfg["stt"]["modelo_local"], device="cpu", compute_type="int8")
        segs, info = self._local.transcribe(
            audio.astype(np.float32) / 32768, beam_size=1, initial_prompt="Jarvis.",
        )
        return " ".join(s.text for s in segs), info.language

    def transcribir(self, audio):
        """Devuelve (texto, idioma) con idioma 'es' o 'en'."""
        if self.motor == "groq":
            try:
                texto, idioma = self._transcribir_groq(audio)
            except Exception as e:
                log.warning("Groq STT falló (%s), uso modelo local", e)
                texto, idioma = self._transcribir_local(audio)
        else:
            texto, idioma = self._transcribir_local(audio)
        texto = texto.strip()
        idioma = "en" if idioma.lower() in ("en", "english") else "es"
        bajo = texto.lower()
        if len(texto) < 2 or any(a in bajo for a in ALUCINACIONES) and len(texto) < 40:
            return "", idioma
        return texto, idioma
