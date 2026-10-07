"""Micrófono: palabra de activación (Vosk, offline), doble aplauso y grabación de órdenes."""
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
    on_estado(str), on_nivel(float), on_comando(audio_int16) -> bool (seguir conversando)."""

    def __init__(self, cfg, on_estado, on_nivel, on_comando):
        self.cfg = cfg
        self.on_estado, self.on_nivel, self.on_comando = on_estado, on_nivel, on_comando
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
        if not self.silencio.is_set():
            self.cola.put(datos[:, 0].copy())

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

    def _grabar(self, espera_max):
        """Graba hasta 0.9 s de silencio tras hablar. None si nadie habla."""
        umbral = max(self.ruido * 3.5, 0.012)
        frames, hablando, silencio, inicio = [], False, 0, time.time()
        while True:
            if self._manual.is_set():  # clic durante la escucha = cancelar
                self._manual.clear()
                return None
            frame = self._leer()
            if frame is None:
                continue
            x = frame.astype(np.float32) / 32768
            rms = float(np.sqrt(np.mean(x * x)))
            self.on_nivel(min(1.0, rms * 12))
            if rms > umbral:
                hablando, silencio = True, 0
            elif hablando:
                silencio += 1
            if hablando or len(frames) < 10:
                frames.append(frame)
            else:
                frames = frames[-10:] + [frame]  # conserva 300 ms previos
            dur = time.time() - inicio
            if not hablando and dur > espera_max:
                return None
            if hablando and (silencio > 30 or dur > 20):
                return np.concatenate(frames)

    def _loop(self):
        while True:
            try:
                self.on_estado("reposo")
                origen = self._esperar_activacion()
                log.info("Activado por %s", origen)
                beep()
                self._vaciar()
                espera = 7
                while True:
                    self.on_estado("escuchando")
                    audio = self._grabar(espera)
                    if audio is None:
                        break
                    seguir = self.on_comando(audio)
                    self._vaciar()
                    if self.rec:
                        self.rec.Reset()
                    if not (seguir and self.cfg["conversacion_continua"]):
                        break
                    espera = self.cfg["segundos_conversacion"]
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
