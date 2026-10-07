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


def limpiar(texto):
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
        self.carpeta = os.path.join(carpeta, "tts")
        os.makedirs(self.carpeta, exist_ok=True)
        self.on_nivel = on_nivel
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
        self._parar.clear()
        self.hablando = True
        try:
            if self.cfg["motor"] == "edge":
                elegida = self.cfg.get("voz_en") if idioma == "en" else self.cfg["voz"]
                respaldo = "en-GB-RyanNeural" if idioma == "en" else "es-ES-AlvaroNeural"
                for voz in dict.fromkeys([elegida, respaldo]):
                    try:
                        return self._edge(texto, voz)
                    except Exception as e:
                        log.warning("edge-tts falló con %s: %s", voz, e)
            self._sapi(texto)
        finally:
            self.hablando = False
            self.on_nivel(0)

    # ---------- edge-tts por frases ----------
    def _generar(self, texto, voz):
        import edge_tts
        ruta = os.path.join(self.carpeta, f"{uuid.uuid4().hex}.mp3")

        async def gen():
            await edge_tts.Communicate(texto, voz, rate=self.cfg.get("velocidad", "+0%"),
                                       pitch=self.cfg.get("tono", "+0Hz")).save(ruta)

        asyncio.run(gen())
        return ruta

    def _edge(self, texto, voz):
        import pygame
        partes = frases(texto)
        listas = queue.Queue()
        error = []

        def productor():  # genera la siguiente frase mientras suena la actual
            for p in partes:
                if self._parar.is_set():
                    break
                try:
                    listas.put(self._generar(p, voz))
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
