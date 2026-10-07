"""Habilidades que JARVIS se programa a sí mismo.
Cada habilidad es un archivo habilidades/<nombre>.py con:
    DESCRIPCION = "qué hace"
    def ejecutar(**kwargs) -> str
"""
import importlib.util
import logging
import os
import re
import subprocess
import sys

log = logging.getLogger("jarvis")
SIN_VENTANA = 0x08000000 if sys.platform == "win32" else 0


class Habilidades:
    def __init__(self, carpeta):
        self.carpeta = carpeta
        os.makedirs(carpeta, exist_ok=True)

    def _ruta(self, nombre):
        return os.path.join(self.carpeta, re.sub(r"[^a-z0-9_]", "_", nombre.lower()) + ".py")

    def listar(self):
        out = {}
        for f in sorted(os.listdir(self.carpeta)):
            if f.endswith(".py"):
                try:
                    with open(os.path.join(self.carpeta, f), encoding="utf-8") as fh:
                        m = re.search(r'DESCRIPCION\s*=\s*["\'](.+?)["\']', fh.read())
                    out[f[:-3]] = m.group(1) if m else ""
                except OSError:
                    pass
        return out

    def texto(self):
        h = self.listar()
        return "\n".join(f"- {k}: {v}" for k, v in h.items()) or "(ninguna todavía)"

    def crear(self, nombre, descripcion, codigo):
        if "def ejecutar" not in codigo:
            return "El código debe definir una función ejecutar(**kwargs) que devuelva un texto."
        ruta = self._ruta(nombre)
        cabecera = f'DESCRIPCION = {descripcion!r}\n\n' if "DESCRIPCION" not in codigo else ""
        with open(ruta, "w", encoding="utf-8") as f:
            f.write(cabecera + codigo)
        try:
            compile(cabecera + codigo, ruta, "exec")
        except SyntaxError as e:
            return f"Guardada, pero tiene un error de sintaxis (línea {e.lineno}): {e.msg}. Corrígela."
        return f"Habilidad '{os.path.basename(ruta)[:-3]}' instalada. Ya puedes usarla con usar_habilidad."

    def usar(self, nombre, argumentos=None):
        ruta = self._ruta(nombre)
        if not os.path.exists(ruta):
            return f"No existe la habilidad '{nombre}'. Disponibles: {', '.join(self.listar()) or 'ninguna'}."
        spec = importlib.util.spec_from_file_location(f"habilidad_{nombre}", ruta)
        mod = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(mod)
        return str(mod.ejecutar(**(argumentos or {})))

    @staticmethod
    def instalar_paquete(paquete):
        if not re.fullmatch(r"[A-Za-z0-9_.\-\[\]=<>~]+", paquete):
            return "Nombre de paquete no válido."
        r = subprocess.run([sys.executable, "-m", "pip", "install", "--prefer-binary", paquete],
                           capture_output=True, text=True, timeout=600, creationflags=SIN_VENTANA)
        return (f"Paquete {paquete} instalado." if r.returncode == 0
                else "Error instalando: " + (r.stderr or r.stdout)[-800:])

    @staticmethod
    def ejecutar_python(codigo):
        exe = sys.executable.replace("pythonw.exe", "python.exe")
        r = subprocess.run([exe, "-c", codigo], capture_output=True, text=True, timeout=120,
                           creationflags=SIN_VENTANA, encoding="utf-8", errors="replace")
        return ((r.stdout or "") + (r.stderr or "")).strip()[-3500:] or "Ejecutado (sin salida)."
