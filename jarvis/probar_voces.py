"""Escucha varias voces gratuitas y elige la que más te guste para JARVIS.
Uso: doble clic en probar_voces.bat"""
import json
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from core import config  # noqa: E402
from core.voz import Voz  # noqa: E402

VOCES = [
    ("1", "es-ES-AlvaroNeural", "-2%", "-6Hz", "Mayordomo castellano (por defecto)"),
    ("2", "es-MX-JorgeNeural", "-2%", "-8Hz", "Latino, grave"),
    ("3", "es-AR-TomasNeural", "-2%", "-6Hz", "Rioplatense"),
    ("4", "es-CO-GonzaloNeural", "-2%", "-6Hz", "Colombiano neutro"),
    ("5", "en-GB-RyanNeural", "-2%", "-6Hz", "Británico (el JARVIS original, en inglés)"),
    ("6", "en-GB-ThomasNeural", "-2%", "-4Hz", "Británico formal"),
    ("7", "en-US-AndrewMultilingualNeural", "+0%", "-4Hz", "Multilingüe natural (habla español)"),
]
FRASE_ES = "Buenas tardes, jefe. Nada dice productividad como empezar una serie con un examen el viernes."
FRASE_EN = "Good afternoon, sir. Nothing says productivity like starting a series with an exam on Friday."

cfg = config.cargar()
for n, voz, vel, tono, desc in VOCES:
    print(f"{n}) {voz} — {desc}")
    cfg["voz"].update({"voz": voz, "voz_en": voz, "velocidad": vel, "tono": tono, "motor": "edge"})
    Voz(cfg, config.DATOS).hablar(FRASE_EN if voz.startswith("en-GB") else FRASE_ES,
                                  "en" if voz.startswith("en-GB") else "es")

eleccion = input("\nNúmero de la voz para ESPAÑOL (Enter = no cambiar): ").strip()
eleccion_en = input("Número de la voz para INGLÉS (Enter = no cambiar): ").strip()
for clave, num in (("voz", eleccion), ("voz_en", eleccion_en)):
    for n, voz, vel, tono, _ in VOCES:
        if n == num:
            config.guardar_valor(["voz", clave], voz)
            config.guardar_valor(["voz", "tono"], tono)
            print(f"Guardado {clave} = {voz}")
print("Listo. Reinicia JARVIS.")
