"""Texto a voz: voces neuronales de Microsoft (edge-tts, gratis) con respaldo offline (SAPI).
Habla frase por frase (la primera suena enseguida mientras se generan las siguientes)
y se puede interrumpir en cualquier momento."""
import asyncio
import logging
import math
import os
import queue
import re
import threading
import time
import uuid

os.environ.setdefault("PYGAME_HIDE_SUPPORT_PROMPT", "1")

log = logging.getLogger("jarvis")


def pulir(texto):
    """Quita etiquetas como 'Acotación:' y la pausa antes del vocativo (', jefe' -> ' jefe')."""
    texto = re.sub(r"[\(\[]\s*([^()\[\]]*)\s*[\)\]]", r"\1", texto)
    texto = re.sub(r"\b(acotaci[oó]n|aside|comentario)\s*(ingeniosa|breve)?\s*[:\-—]\s*(\w)", lambda m: m.group(3).upper(), texto, flags=re.I)
    texto = re.sub(r"\s*,\s*(jefe|señor|sir|boss)\b", r" \1", texto, flags=re.I)
    texto = re.sub(r"\b(jefe|señor|sir|boss)\s*,\s*", r"\1 ", texto, flags=re.I)
    return re.sub(r"\s+", " ", texto).strip()


def limpiar(texto):
    texto = pulir(texto)
    texto = re.sub(r"```.*?```", " ", texto, flags=re.S)
    texto = re.sub(r"https?://\S+", "el enlace", texto)
    texto = re.sub(r"[*_#`>|]", "", texto)
    return re.sub(r"\s+", " ", texto).strip()


def frases(texto):
    partes = re.split(r"(?<=[.!?…;:])\s+(?=[A-ZÁÉÍÓÚÑ¿¡\d])", texto)
    salida, buf = [], ""
    for p in partes:  # junta frases muy cortas para que no suene entrecortado
        buf = f"{buf} {p}".strip()
        if len(buf) > 40:
            salida.append(buf)
            buf = ""
    if buf:
        salida.append(buf)
    return salida


class Voz:
    def __init__(self, cfg, carpeta, on_nivel=lambda v: None):
        self.cfg = cfg["voz"]
        self.raiz = cfg
        self.carpeta = os.path.join(carpeta, "tts")
        os.makedirs(self.carpeta, exist_ok=True)
        self.on_nivel = on_nivel
        self.on_aviso = lambda texto: None
        self._parar = threading.Event()
        self._mixer = False
        self.hablando = False

    def detener(self):
        self._parar.set()
        if self._mixer:
            import pygame
            pygame.mixer.stop()

    def hablar(self, texto, idioma="es"):
        texto = limpiar(texto)
        if not texto:
            return
        if self.idioma_fijo() == "en":
            idioma = "en"
        self._parar.clear()
        self.hablando = True
        try:
            if self.cfg["motor"] == "elevenlabs" and self.cfg.get("elevenlabs_api_key"):
                try:
                    return self._por_frases(texto, self._generar_11)
                except Exception as e:  # sin cuota o sin internet: pasa a la voz gratis
                    log.warning("ElevenLabs falló, uso edge-tts: %s", e)
                    if not getattr(self, "_avisado_11", False):
                        self._avisado_11 = True
                        txt = str(e)
                        motivo = ("se acabó el cupo gratis de este mes" if any(x in txt for x in ("401", "quota", "402", "429"))
                                  else "no respondió")
                        try:
                            self.on_aviso(f"La voz de George (ElevenLabs) {motivo}; uso la voz gratis mientras tanto.")
                        except Exception:
                            pass
            if self.cfg["motor"] in ("edge", "elevenlabs"):
                elegida = self.cfg.get("voz_en") if idioma == "en" else self.cfg["voz"]
                respaldo = "en-GB-RyanNeural" if idioma == "en" else "es-ES-AlvaroNeural"
                for voz in dict.fromkeys([elegida, respaldo]):
                    try:
                        return self._por_frases(texto, lambda t, v=voz: self._generar(t, v))
                    except Exception as e:
                        log.warning("edge-tts falló con %s: %s", voz, e)
            self._sapi(texto)
        finally:
            self.hablando = False
            self.on_nivel(0)

    def idioma_fijo(self):
        return self.raiz.get("idioma", "es")

    def archivo(self, texto):
        """Genera un mp3 con la voz de JARVIS (para notas de voz por Telegram)."""
        texto = limpiar(texto)
        if self.cfg["motor"] == "elevenlabs" and self.cfg.get("elevenlabs_api_key"):
            try:
                return self._generar_11(texto)
            except Exception:
                pass
        return self._generar(texto, self.cfg.get("voz_en") if self.idioma_fijo() == "en" else self.cfg["voz"])

    # ---------- edge-tts por frases ----------
    def _generar(self, texto, voz):
        import edge_tts
        ruta = os.path.join(self.carpeta, f"{uuid.uuid4().hex}.mp3")

        async def gen():
            await edge_tts.Communicate(texto, voz, rate=self.cfg.get("velocidad", "+0%"),
                                       pitch=self.cfg.get("tono", "+0Hz")).save(ruta)

        asyncio.run(gen())
        return ruta

    def _generar_11(self, texto):
        import requests
        voz = self.cfg.get("elevenlabs_voz") or "JBFqnCBsd6RMkjVDRZzb"  # George: británico, cálido
        r = requests.post(
            f"https://api.elevenlabs.io/v1/text-to-speech/{voz}?output_format=mp3_44100_128",
            headers={"xi-api-key": self.cfg["elevenlabs_api_key"]}, timeout=20,
            json={"text": texto, "model_id": self.cfg.get("elevenlabs_modelo", "eleven_flash_v2_5"),
                  "language_code": "es",
                  "voice_settings": {"stability": 0.45, "similarity_boost": 0.8, "style": 0.25, "speed": 1.0}})
        r.raise_for_status()
        ruta = os.path.join(self.carpeta, f"{uuid.uuid4().hex}.mp3")
        with open(ruta, "wb") as f:
            f.write(r.content)
        return ruta

    def _por_frases(self, texto, generar):
        import pygame
        partes = frases(texto)
        listas = queue.Queue()
        error = []

        def productor():  # genera la siguiente frase mientras suena la actual
            for p in partes:
                if self._parar.is_set():
                    break
                try:
                    listas.put(generar(p))
                except Exception as e:
                    error.append(e)
                    break
            listas.put(None)

        threading.Thread(target=productor, daemon=True).start()
        if not self._mixer:
            pygame.mixer.init()
            self._mixer = True
        sonó = False
        while True:
            ruta = listas.get()
            if ruta is None:
                break
            if not self._parar.is_set():
                self._reproducir(ruta)
                sonó = True
            try:
                os.remove(ruta)
            except OSError:
                pass
        if error and not sonó:
            raise error[0]

    def _reproducir(self, ruta):
        import numpy as np
        import pygame
        sonido = pygame.mixer.Sound(ruta)
        try:  # envolvente de volumen para animar la esfera con la voz real
            arr = np.abs(pygame.sndarray.array(sonido).astype(np.float32))
            mono = arr.mean(axis=1) if arr.ndim == 2 else arr
            hop = pygame.mixer.get_init()[0] // 20
            env = np.array([mono[i:i + hop].mean() for i in range(0, len(mono), hop)])
            env = env / (env.max() or 1)
        except Exception:
            env = None
        canal = sonido.play()
        inicio = time.time()
        while canal.get_busy() and not self._parar.is_set():
            i = int((time.time() - inicio) * 20)
            self.on_nivel(float(env[i]) if env is not None and i < len(env) else 0.4)
            time.sleep(0.05)
        canal.stop()

    # ---------- voz offline de Windows ----------
    def _sapi(self, texto):
        import pyttsx3
        try:
            import comtypes
            comtypes.CoInitialize()  # SAPI necesita COM en este hilo
        except Exception:
            pass
        motor = pyttsx3.init()
        for v in motor.getProperty("voices"):
            if "spanish" in v.name.lower() or "español" in v.name.lower() or "es-" in v.id.lower():
                motor.setProperty("voice", v.id)
                break
        fin = threading.Event()

        def animar():
            t = 0
            while not fin.is_set():
                if self._parar.is_set():
                    motor.stop()
                self.on_nivel(0.35 + 0.3 * abs(math.sin(t * 7)))
                t += 0.05
                time.sleep(0.05)

        threading.Thread(target=animar, daemon=True).start()
        try:
            motor.say(texto)
            motor.runAndWait()
        finally:
            fin.set()
