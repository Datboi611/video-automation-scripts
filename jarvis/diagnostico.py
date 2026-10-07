"""Revisa que todo funcione. Uso: doble clic en diagnostico.bat"""
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from core import config, diagnostico  # noqa: E402

print("\n  === Diagnóstico de JARVIS ===\n")
resultado = diagnostico.revisar(config.cargar())
print(resultado)
with open(os.path.join(config.DATOS, "diagnostico.txt"), "w", encoding="utf-8") as f:
    f.write(resultado)
print("\n(Guardado en datos\\diagnostico.txt — mándale una captura a Claude si algo sale con ❌)\n")
