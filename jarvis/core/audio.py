"""Micrófono: palabra de activación (Vosk, offline), doble aplauso y grabación de órdenes."""
import collections
import json
import logging
import queue
import threading
import time

import numpy as np
import sounddevice as sd

log = logging.getLogger("jarvis")

SR = 16000
BLOQUE = 480  # 30 ms


class DetectorAplausos:
    """Detecta dos aplausos seguidos: picos fuertes y muy cortos sobre el ruido de fondo."""

    def __init__(self, umbral=0.30):
        self.umbral = umbral
        self.ruido = 0.01
        self.en_pico = False
        self.frames_pico = 0
        self.inicio_pico = 0.0
        self.aplausos = []

    def procesar(self, x, t):
        rms = float(np.sqrt(np.mean(x * x)))
        pico = float(np.max(np.abs(x)))
        if not self.en_pico:
            if pico > self.umbral and rms > self.ruido * 6:
                self.en_pico, self.frames_pico, self.inicio_pico = True, 1, t
            else:
                self.ruido = max(0.002, 0.95 * self.ruido + 0.05 * rms)
            return False
        self.frames_pico += 1
        if rms < max(self.ruido * 3, 0.02):
            self.en_pico = False
            if self.frames_pico <= 5:  # < 150 ms: es un aplauso, no voz ni música
                return self._registrar(self.inicio_pico)
        elif self.frames_pico > 6:
            self.en_pico = False
            self.aplausos.clear()
        return False

    def _registrar(self, t):
        self.aplausos = [a for a in self.aplausos if t - a < 1.0]
        self.aplausos.append(t)
        if len(self.aplausos) >= 2 and 0.12 < self.aplausos[-1] - self.aplausos[-2] < 0.9:
            self.aplausos.clear()
            return True
        return False


class Escucha:
    """Hilo de escucha. Callbacks:
    on_estado(str), on_nivel(float), on_comando(audio_int16) -> bool (hubo conversación real)."""

    def __init__(self, cfg, on_estado, on_nivel, on_comando, on_despertar=lambda: None):
        self.cfg = cfg
        self.on_estado, self.on_nivel, self.on_comando = on_estado, on_nivel, on_comando
        self.on_despertar = on_despertar
        self.on_interrupcion = lambda: None
        self.ultimo = time.time()
        self._eco = 0.02
        self._eco_frames = 0
        self._previo = collections.deque(maxlen=25)
        self.cola = queue.Queue()
        self.silencio = threading.Event()  # activo mientras JARVIS habla
        self._manual = threading.Event()
        act = cfg["activacion"]
        self.aplausos = DetectorAplausos(act["umbral_aplauso"]) if act["aplausos"] else None
        self.palabra = act["palabra"].lower().strip()
        self.rec = self._crear_reconocedor(act["modelo_vosk"])
        self.ruido = 0.01

    def _crear_reconocedor(self, ruta):
        try:
            from vosk import KaldiRecognizer, Model, SetLogLevel
        except ImportError:
            log.warning("Vosk no instalado: solo aplausos/clic para activar.")
            return None
        SetLogLevel(-1)
        try:
            modelo = Model(ruta)
        except Exception:
            log.warning("No se encontró el modelo Vosk en %s", ruta)
            return None
        try:
            frases = [self.palabra, "hey " + self.palabra, "oye " + self.palabra, "[unk]"]
            return KaldiRecognizer(modelo, SR, json.dumps(frases))
        except Exception:
            log.exception("No pude crear el detector de palabra")
            return None

    # --- API pública ---
    def iniciar(self):
        self.stream = sd.InputStream(
            samplerate=SR, channels=1, dtype="int16", blocksize=BLOQUE,
            device=self.cfg.get("microfono"), callback=self._callback,
        )
        self.stream.start()
        threading.Thread(target=self._loop, daemon=True).start()

    def activar(self):
        self._manual.set()

    # --- interno ---
    def _callback(self, datos, frames, tiempo, estado):
        frame = datos[:, 0].copy()
        if not self.silencio.is_set():
            self._eco_frames = 0
            self.cola.put(frame)
            return
        # JARVIS está hablando: el micrófono oye su voz (eco). Si aparece una voz claramente más
        # fuerte que ese eco durante ~0.25 s, es el usuario interrumpiendo.
        x = frame.astype(np.float32) / 32768
        rms = float(np.sqrt(np.mean(x * x)))
        self._previo.append(frame)
        if not self.cfg.get("interrumpir", True):
            return
        umbral = max(self.ruido * 6, self._eco * self.cfg.get("factor_interrupcion", 2.8), 0.03)
        if rms > umbral:
            self._eco_frames += 1
        else:
            self._eco_frames = max(0, self._eco_frames - 1)
            self._eco = 0.97 * self._eco + 0.03 * rms  # nivel típico del eco
        if self._eco_frames >= 8:
            self._eco_frames = 0
            log.info("Interrupción del usuario detectada")
            self.silencio.clear()
            for f in self._previo:  # no perder el inicio de lo que dijo
                self.cola.put(f)
            self._previo.clear()
            self.on_interrupcion()

    def _vaciar(self):
        while not self.cola.empty():
            self.cola.get_nowait()

    def _leer(self, timeout=0.1):
        try:
            return self.cola.get(timeout=timeout)
        except queue.Empty:
            return None

    def _detecta_palabra(self, frame):
        if not self.rec:
            return False
        if self.rec.AcceptWaveform(frame.tobytes()):
            texto = json.loads(self.rec.Result()).get("text", "")
        else:
            texto = json.loads(self.rec.PartialResult()).get("partial", "")
        if self.palabra in texto:
            self.rec.Reset()
            return True
        return False

    def _esperar_activacion(self):
        while True:
            if self._manual.is_set():
                self._manual.clear()
                return "manual"
            frame = self._leer()
            if frame is None:
                continue
            x = frame.astype(np.float32) / 32768
            rms = float(np.sqrt(np.mean(x * x)))
            if rms < self.ruido * 2:
                self.ruido = max(0.003, 0.97 * self.ruido + 0.03 * rms)
            if self.aplausos and self.aplausos.procesar(x, time.time()):
                return "aplauso"
            if self._detecta_palabra(frame):
                return "voz"

    def actividad(self):
        """Reinicia el contador de inactividad (también al escribir en la interfaz)."""
        self.ultimo = time.time()

    def dormir(self):
        self.ultimo = 0

    def _grabar(self, espera_max):
        """Graba una frase (termina tras ~1.6 s de silencio, configurable). None si nadie habla."""
        frames, hablando, silencio, voz, inicio = [], False, 0, 0, time.time()
        fin_silencio = int(self.cfg.get("segundos_silencio", 1.6) / 0.03)
        while True:
            self._manual.clear()
            frame = self._leer()
            if frame is None:
                if time.time() - inicio > espera_max:
                    return None
                continue
            x = frame.astype(np.float32) / 32768
            rms = float(np.sqrt(np.mean(x * x)))
            # al empezar a hablar exige más volumen; ya hablando, basta con voz suave (pausas, finales de frase)
            umbral = max(self.ruido * (3.5 if not hablando else 2.2), 0.012 if not hablando else 0.008)
            self.on_nivel(min(1.0, rms * 12))
            if rms > umbral:
                hablando, silencio, voz = True, 0, voz + 1
            elif hablando:
                silencio += 1
            else:
                self.ruido = max(0.003, 0.98 * self.ruido + 0.02 * rms)
            if hablando or len(frames) < 10:
                frames.append(frame)
            else:
                frames = frames[-10:] + [frame]  # conserva 300 ms previos
            if hablando and silencio > fin_silencio:
                if voz < 8:  # ruido corto (golpe, tos): se ignora
                    frames, hablando, silencio, voz = [], False, 0, 0
                    continue
                return np.concatenate(frames)
            if hablando and len(frames) > 30 * 20:  # máximo 30 s
                return np.concatenate(frames)
            if not hablando and time.time() - inicio > espera_max:
                return None

    def _loop(self):
        """Siempre escuchando. Tras N minutos sin hablar entra en reposo;
        se despierta con «Jarvis», doble aplauso o clic en la esfera."""
        reposo = self.cfg["minutos_reposo"] * 60
        self.ultimo = time.time()
        while True:
            try:
                if time.time() - self.ultimo > reposo:
                    self.on_estado("dormido")
                    origen = self._esperar_activacion()
                    log.info("Despertado por %s", origen)
                    beep()
                    self._vaciar()
                    self.ultimo = time.time()
                    self.on_despertar()
                self.on_estado("escuchando")
                restante = reposo - (time.time() - self.ultimo)
                audio = self._grabar(espera_max=max(1, min(30, restante)))
                if audio is None:
                    continue
                if self.on_comando(audio):
                    self.ultimo = time.time()
                self._vaciar()
                if self.rec:
                    self.rec.Reset()
            except Exception:
                log.exception("Error en el bucle de escucha")
                time.sleep(1)


def beep():
    t = np.linspace(0, 0.12, int(SR * 0.12), False)
    tono = 0.18 * np.sin(2 * np.pi * 880 * t) * np.exp(-t * 25)
    tono += 0.12 * np.sin(2 * np.pi * 1320 * t) * np.exp(-t * 30)
    try:
        sd.play(tono.astype(np.float32), SR)
    except Exception:
        pass
