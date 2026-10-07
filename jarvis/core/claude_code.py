"""Delegar tareas complejas a Claude Code (incluido en el plan de Claude del usuario).
Se ejecuta en segundo plano: `claude -p "<tarea>"` y avisa al terminar."""
import logging
import os
import shutil
import subprocess
import sys
import threading

log = logging.getLogger("jarvis")
SIN_VENTANA = 0x08000000 if sys.platform == "win32" else 0


def ruta_claude():
    exe = shutil.which("claude") or shutil.which("claude.exe") or shutil.which("claude.cmd")
    if not exe and sys.platform == "win32":
        for p in (os.path.expandvars(r"%USERPROFILE%\.local\bin\claude.exe"),
                  os.path.expandvars(r"%APPDATA%\npm\claude.cmd")):
            if os.path.exists(p):
                return p
    return exe


class ClaudeCode:
    def __init__(self, on_terminado):
        self.on_terminado = on_terminado  # función(tarea, resultado, ok)
        self.en_curso = {}

    def delegar(self, tarea, carpeta=None):
        exe = ruta_claude()
        if not exe:
            return ("Claude Code no está instalado. Pídele al usuario que abra conectar_claude.bat "
                    "en la carpeta de JARVIS (una sola vez) y vuelva a pedirlo.")
        carpeta = os.path.expandvars(os.path.expanduser(carpeta or "~"))
        instrucciones = ("Eres el brazo ejecutor de JARVIS, el asistente del usuario, en su PC con Windows. "
                         "Haz la tarea completa tú mismo. Al final responde en español con un resumen breve "
                         "(máximo 5 líneas) de lo que hiciste y dónde quedó el resultado.\n\nTarea: " + tarea)
        cmd = [exe, "-p", instrucciones, "--output-format", "text", "--permission-mode", "acceptEdits",
               "--allowedTools", "Bash", "Read", "Write", "Edit", "Glob", "Grep", "WebSearch", "WebFetch"]

        def correr():
            try:
                r = subprocess.run(cmd, cwd=carpeta, capture_output=True, text=True, timeout=1800,
                                   encoding="utf-8", errors="replace", creationflags=SIN_VENTANA)
                ok = r.returncode == 0
                salida = (r.stdout or r.stderr or "").strip()
            except subprocess.TimeoutExpired:
                ok, salida = False, "Se pasó de 30 minutos y lo detuve."
            except Exception as e:
                ok, salida = False, str(e)
            log.info("Claude Code terminó (%s): %s", ok, salida[:300])
            self.en_curso.pop(tarea, None)
            self.on_terminado(tarea, salida, ok)

        self.en_curso[tarea] = threading.Thread(target=correr, daemon=True)
        self.en_curso[tarea].start()
        return "Tarea delegada a Claude Code; está trabajando en segundo plano y avisará al terminar."
