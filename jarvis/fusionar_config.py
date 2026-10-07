"""Usado por ACTUALIZAR_JARVIS.bat: une el config.json nuevo con el anterior sin perder lo que JARVIS
ya había guardado (vinculación de Telegram, correo, Canvas...). Gana el valor nuevo si no está vacío."""
import json
import sys


def unir(nuevo, viejo):
    if isinstance(nuevo, dict) and isinstance(viejo, dict):
        for k, v in viejo.items():
            nuevo[k] = unir(nuevo[k], v) if k in nuevo else v
        return nuevo
    if nuevo in ("", None, []) and viejo not in ("", None, []):
        return viejo
    return nuevo


ruta_nuevo, ruta_viejo = sys.argv[1], sys.argv[2]
with open(ruta_nuevo, encoding="utf-8") as f:
    nuevo = json.load(f)
try:
    with open(ruta_viejo, encoding="utf-8") as f:
        viejo = json.load(f)
except Exception:
    viejo = {}
with open(ruta_nuevo, "w", encoding="utf-8") as f:
    json.dump(unir(nuevo, viejo), f, ensure_ascii=False, indent=2)
print("[OK] Configuración unida (se conservaron tus datos guardados).")
