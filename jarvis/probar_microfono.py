"""Prueba el micrófono que usa JARVIS: muestra los micrófonos, graba 5 s y dice qué oyó."""
import numpy as np
import sounddevice as sd

from core import config
from core.oido import Oido

cfg = config.cargar()
mic = cfg.get("microfono")
print("Micrófonos disponibles:")
for i, d in enumerate(sd.query_devices()):
    if d["max_input_channels"] > 0:
        print(f"  [{i}] {d['name']}")
actual = sd.query_devices(mic if mic is not None else sd.default.device[0])
print(f"\nJARVIS usa: {actual['name']}  (config.json -> \"microfono\": {mic})")
input("\nPulsa Enter y habla 5 segundos (ej. «Jarvis, qué hora es»)...")
audio = sd.rec(5 * 16000, samplerate=16000, channels=1, dtype="int16", device=mic)
sd.wait()
x = audio[:, 0].astype(np.float32) / 32768
rms = np.sqrt(np.mean(x.reshape(-1, 480) ** 2, axis=1))
print(f"\nNivel máximo: {rms.max():.4f}   (JARVIS empieza a oír desde 0.005)")
if rms.max() < 0.002:
    print("[X] El micrófono no capta nada: está silenciado, es el equivocado o Windows le negó el permiso.\n"
          "    Ajustes de Windows > Privacidad > Micrófono: permitir a las apps de escritorio.\n"
          "    O pon en config.json \"microfono\": <número de la lista de arriba>.")
elif rms.max() < 0.005:
    print("[!] Se oye muy bajo: sube el volumen del micrófono en Windows (Sonido > Entrada) o acércate.")
else:
    print("[OK] El micrófono capta bien.")
oido = Oido(cfg)
texto = oido.transcribir(audio[:, 0])
print("Transcripción:", repr(texto) if texto else f"(nada) {getattr(oido, 'ultimo_error', '')}")
