"""Voz a texto: Whisper en Groq (gratis, ultra rápido) o faster-whisper local (offline)."""
import io
import logging
import wave

import numpy as np

from . import config

log = logging.getLogger("jarvis")

ALUCINACIONES = (
    "gracias por ver", "subtítulos", "amara.org", "suscríbete", "¡gracias!", "gracias.",
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
            model="whisper-large-v3-turbo", file=("voz.wav", _wav(audio)), language="es",
            prompt="Jarvis, abre Chrome, recuérdame, pon música.",
        )
        return r.text

    def _transcribir_local(self, audio):
        if self._local is None:
            from faster_whisper import WhisperModel
            self._local = WhisperModel(self.cfg["stt"]["modelo_local"], device="cpu", compute_type="int8")
        segs, _ = self._local.transcribe(
            audio.astype(np.float32) / 32768, language="es", beam_size=1,
            initial_prompt="Jarvis, abre Chrome, recuérdame, pon música.",
        )
        return " ".join(s.text for s in segs)

    def transcribir(self, audio):
        texto = ""
        if self.motor == "groq":
            try:
                texto = self._transcribir_groq(audio)
            except Exception as e:
                log.warning("Groq STT falló (%s), uso modelo local", e)
                texto = self._transcribir_local(audio)
        else:
            texto = self._transcribir_local(audio)
        texto = texto.strip()
        if len(texto) < 2 or any(a == texto.lower() or a in texto.lower() and len(texto) < 40 for a in ALUCINACIONES):
            return ""
        return texto
