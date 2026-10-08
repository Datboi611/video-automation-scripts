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


VOCABULARIO = ("Jarvis, Diego. Todoist, Google Calendar, YouTube, Apple Music, Pill&Go, Ezma Shop, Plancitope, "
               "Canvas, Notion, WhatsApp, Chrome, pestaña. ¿Qué tengo pendiente hoy? Pon música. Recuérdame.")


def limpiar_audio(audio):
    """Quita zumbido grave y normaliza el volumen para que Whisper entienda mejor."""
    x = audio.astype(np.float32)
    x -= x.mean()
    # paso-alto (~80 Hz): resta la media móvil, elimina zumbido de ventilador/red eléctrica
    c = np.cumsum(np.concatenate([np.zeros(100), x, np.full(100, x[-1] if len(x) else 0)]))
    y = x - (c[200:] - c[:-200])[: len(x)] / 200
    pico = np.percentile(np.abs(y), 99.5) or 1
    y *= min(20.0, 0.6 * 32767 / pico)
    return np.clip(y, -32767, 32767).astype(np.int16)


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
        global VOCABULARIO
        if cfg.get("vocabulario"):
            VOCABULARIO = cfg["vocabulario"] + ". " + VOCABULARIO

    def _transcribir_groq(self, audio):
        if self._groq is None:
            from openai import OpenAI
            self._groq = OpenAI(api_key=self.key_groq, base_url=config.URLS_PROVEEDOR["groq"], timeout=20)
        wav = _wav(audio)
        if self.cfg.get("idioma", "es") == "en":
            r = self._groq.audio.transcriptions.create(
                model="whisper-large-v3", file=("voz.wav", wav), language="en", prompt=VOCABULARIO, temperature=0)
            return r.text, "en"
        if self.cfg.get("idioma", "es") == "es":
            r = self._groq.audio.transcriptions.create(
                model="whisper-large-v3", file=("voz.wav", wav), language="es", prompt=VOCABULARIO, temperature=0)
            return r.text, "es"
        r = self._groq.audio.transcriptions.create(
            model="whisper-large-v3", file=("voz.wav", wav), response_format="verbose_json",
            prompt=VOCABULARIO, temperature=0,
        )
        idioma = (getattr(r, "language", "") or "").lower()
        if idioma not in ("es", "spanish", "en", "english"):
            # idioma raro = probablemente entendió mal: se fuerza español
            r = self._groq.audio.transcriptions.create(
                model="whisper-large-v3", file=("voz.wav", wav), language="es", prompt=VOCABULARIO, temperature=0)
            idioma = "es"
        return r.text, idioma

    def _transcribir_local(self, audio):
        if self._local is None:
            from faster_whisper import WhisperModel
            self._local = WhisperModel(self.cfg["stt"]["modelo_local"], device="cpu", compute_type="int8")
        x = audio.astype(np.float32) / 32768
        if self.cfg.get("idioma", "es") in ("es", "en"):
            fijo = self.cfg.get("idioma", "es")
            segs, _ = self._local.transcribe(x, beam_size=3, language=fijo, initial_prompt=VOCABULARIO, vad_filter=True)
            return " ".join(s.text for s in segs), fijo
        if False:
            segs, _ = self._local.transcribe(x, beam_size=3, language="es", initial_prompt=VOCABULARIO, vad_filter=True)
            return " ".join(s.text for s in segs), "es"
        segs, info = self._local.transcribe(x, beam_size=3, initial_prompt=VOCABULARIO, vad_filter=True)
        if info.language not in ("es", "en"):
            segs, info = self._local.transcribe(x, beam_size=3, language="es", initial_prompt=VOCABULARIO)
        return " ".join(s.text for s in segs), info.language

    def transcribir(self, audio):
        """Devuelve (texto, idioma) con idioma 'es' o 'en'."""
        audio = limpiar_audio(audio)
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

    def transcribir_archivo(self, datos, nombre="nota.ogg"):
        """Notas de voz del teléfono (ogg/m4a/mp3)."""
        try:
            if self.key_groq:
                if self._groq is None:
                    from openai import OpenAI
                    self._groq = OpenAI(api_key=self.key_groq, base_url=config.URLS_PROVEEDOR["groq"], timeout=30)
                r = self._groq.audio.transcriptions.create(
                    model="whisper-large-v3", file=(nombre, datos), language="es", prompt=VOCABULARIO, temperature=0)
                return r.text.strip()
            import tempfile
            with tempfile.NamedTemporaryFile(suffix="." + nombre.split(".")[-1], delete=False) as f:
                f.write(datos)
            if self._local is None:
                from faster_whisper import WhisperModel
                self._local = WhisperModel(self.cfg["stt"]["modelo_local"], device="cpu", compute_type="int8")
            segs, _ = self._local.transcribe(f.name, language="es", initial_prompt=VOCABULARIO)
            return " ".join(s.text for s in segs).strip()
        except Exception as e:
            log.warning("No pude transcribir la nota de voz: %s", e)
            return ""
