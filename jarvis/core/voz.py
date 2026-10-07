"""Texto a voz: voces neuronales de Microsoft (edge-tts, gratis) con respaldo offline (SAPI)."""
import asyncio
import logging
import math
import os
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


class Voz:
    def __init__(self, cfg, carpeta, on_nivel=lambda v: None):
        self.cfg = cfg["voz"]
        self.carpeta = os.path.join(carpeta, "tts")
        os.makedirs(self.carpeta, exist_ok=True)
        self.on_nivel = on_nivel
        self._parar = threading.Event()
        self._mixer = False

    def detener(self):
        self._parar.set()
        if self._mixer:
            import pygame
            pygame.mixer.stop()

    def hablar(self, texto):
        texto = limpiar(texto)
        if not texto:
            return
        self._parar.clear()
        if self.cfg["motor"] == "edge":
            try:
                return self._edge(texto)
            except Exception as e:
                log.warning("edge-tts falló (%s), uso voz offline", e)
        self._sapi(texto)

    def _edge(self, texto):
        import edge_tts
        import numpy as np
        import pygame

        ruta = os.path.join(self.carpeta, f"{uuid.uuid4().hex}.mp3")

        async def generar():
            await edge_tts.Communicate(texto, self.cfg["voz"], rate=self.cfg["velocidad"]).save(ruta)

        asyncio.run(generar())
        if not self._mixer:
            pygame.mixer.init()
            self._mixer = True
        sonido = pygame.mixer.Sound(ruta)
        # Envolvente de volumen para animar la esfera con la voz real
        try:
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
        self.on_nivel(0)
        try:
            os.remove(ruta)
        except OSError:
            pass

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
                self.on_nivel(0.35 + 0.3 * abs(math.sin(t * 7)))
                t += 0.05
                time.sleep(0.05)
            self.on_nivel(0)

        threading.Thread(target=animar, daemon=True).start()
        try:
            motor.say(texto)
            motor.runAndWait()
        finally:
            fin.set()
