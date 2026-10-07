"""Memoria a largo plazo: datos que JARVIS recuerda entre sesiones."""
import json
import os
import threading


class Memoria:
    def __init__(self, ruta):
        self.ruta = ruta
        self._lock = threading.Lock()
        self.datos = []
        if os.path.exists(ruta):
            with open(ruta, encoding="utf-8") as f:
                self.datos = json.load(f)

    def _guardar(self):
        with open(self.ruta, "w", encoding="utf-8") as f:
            json.dump(self.datos, f, ensure_ascii=False, indent=2)

    def agregar(self, dato):
        with self._lock:
            self.datos.append(dato.strip())
            self._guardar()

    def olvidar(self, texto):
        with self._lock:
            antes = len(self.datos)
            self.datos = [d for d in self.datos if texto.lower() not in d.lower()]
            self._guardar()
            return antes - len(self.datos)

    def texto(self):
        return "\n".join(f"- {d}" for d in self.datos) or "(vacía)"
