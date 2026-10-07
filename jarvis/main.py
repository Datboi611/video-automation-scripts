"""J.A.R.V.I.S. — asistente de voz en español para Windows.
Ejecuta: python main.py   (o iniciar.bat)
"""
import datetime as dt
import json
import logging
import os
import sys
import threading

import webview

from core import config
from core.cerebro import Cerebro
from core.herramientas import Herramientas
from core.memoria import Memoria
from core.recordatorios import Recordatorios
from core.telefono import Telefono
from core.voz import Voz

os.makedirs(config.DATOS, exist_ok=True)
logging.basicConfig(
    level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s",
    handlers=[logging.FileHandler(os.path.join(config.DATOS, "jarvis.log"), encoding="utf-8"),
              logging.StreamHandler(sys.stdout) if sys.stdout else logging.NullHandler()],
)
log = logging.getLogger("jarvis")


class Jarvis:
    def __init__(self):
        self.cfg = config.cargar()
        self.ventana = None
        self.listo = threading.Event()
        self.lock = threading.Lock()
        self.escucha = None

    # ---------- Interfaz ----------
    def ui(self, fn, *args):
        if not self.ventana or not self.listo.is_set():
            return
        try:
            self.ventana.evaluate_js(f"window.J && J.{fn}({','.join(json.dumps(a) for a in args)})")
        except Exception:
            pass

    def estado(self, s):
        self.ui("setState", s)

    def nivel(self, v):
        self.ui("setLevel", round(v, 3))

    # ---------- Arranque ----------
    def iniciar(self):
        self.listo.wait(30)
        c = self.cfg
        self.ui("setStatus", "Cargando módulos…")
        self.memoria = Memoria(os.path.join(config.DATOS, "memoria.json"))
        self.telefono = Telefono(c)
        self.recordatorios = Recordatorios(os.path.join(config.DATOS, "recordatorios.json"), self.recordatorio_vencido)
        self.herramientas = Herramientas(self.memoria, self.recordatorios, self.telefono)
        self.cerebro = Cerebro(c, self.herramientas, self.memoria)
        self.voz = Voz(c, config.DATOS, on_nivel=self.nivel)
        self.recordatorios.iniciar()

        try:
            from core.audio import Escucha
            from core.oido import Oido
            self.oido = Oido(c)
            self.escucha = Escucha(c, self.estado, self.nivel, self.comando_de_voz, self.despertar)
            modos = ["di «" + c["activacion"]["palabra"].capitalize() + "»" if self.escucha.rec else None,
                     "aplaude dos veces" if c["activacion"]["aplausos"] else None, "toca la esfera"]
            self.ui("setHint", f"Te escucho siempre · tras {c['minutos_reposo']} min sin hablar descanso; "
                               "para despertarme: " + ", ".join(m for m in modos if m))
        except Exception as e:
            log.exception("Micrófono no disponible")
            self.ui("setHint", f"Micrófono no disponible ({e}). Puedes escribirme.")

        if c["telefono"]["control_remoto"]:
            self.telefono.escuchar_ordenes(self.orden_remota)

        if not self.cerebro.proveedores:
            self.ui("addMsg", "sistema", "No hay cerebro configurado: añade tu clave gratuita de Groq en config.json o instala Ollama.")
        h = dt.datetime.now().hour
        saludo = "Buenos días" if 5 <= h < 12 else "Buenas tardes" if h < 20 else "Buenas noches"
        self.decir(f"{saludo}, {c['tratamiento']}. Todos los sistemas operativos. Le escucho.")
        try:
            self.escucha.iniciar()
        except Exception as e:
            log.exception("No pude abrir el micrófono")
            self.escucha = None
            self.ui("setHint", f"Micrófono no disponible ({e}). Puedes escribirme.")
            self.estado("reposo")

    # ---------- Flujo principal ----------
    def decir(self, texto, idioma="es"):
        self.ui("addMsg", "jarvis", texto)
        self.estado("hablando")
        if self.escucha:
            self.escucha.silencio.set()
        try:
            self.voz.hablar(texto, idioma)
        finally:
            if self.escucha:
                self.escucha.silencio.clear()

    def procesar(self, texto, hablar=True, idioma="es"):
        if self.escucha:
            self.escucha.actividad()
        with self.lock:
            self.ui("addMsg", "usuario", texto)
            self.estado("pensando")
            respuesta = self.cerebro.responder(
                texto, on_herramienta=lambda n: self.ui("setStatus", f"Ejecutando {n}…"), idioma=idioma)
            if hablar:
                self.decir(respuesta, idioma)
            else:
                self.ui("addMsg", "jarvis", respuesta)
            self.estado("reposo")
            return respuesta

    def comando_de_voz(self, audio):
        self.estado("pensando")
        texto, idioma = self.oido.transcribir(audio)
        if not texto:
            return False
        limpio = texto.lower().strip(" .!¡?¿,")
        if any(f in limpio for f in ("descansa", "duérmete", "duermete", "modo reposo", "go to sleep", "sleep mode")):
            self.ui("addMsg", "usuario", texto)
            self.decir("Entrando en reposo. Aplauda o diga Jarvis cuando me necesite." if idioma == "es"
                       else "Going to sleep. Clap or say Jarvis when you need me.", idioma)
            self.escucha.dormir()
            return False
        self.procesar(texto, idioma=idioma)
        return True

    def despertar(self):
        self.decir(f"¿Sí, {self.cfg['tratamiento']}?")

    def recordatorio_vencido(self, r):
        aviso = f"{self.cfg['tratamiento'].capitalize()}, le recuerdo: {r['mensaje']}"
        for accion in (lambda: self.telefono.notificar(r["mensaje"], "Recordatorio JARVIS", 5),
                       lambda: self.telefono.llamar(aviso) if r["llamar"] else None):
            try:
                accion()
            except Exception as e:
                log.warning("Aviso al teléfono falló: %s", e)
        with self.lock:
            self.decir(aviso)
            self.estado("reposo")

    def orden_remota(self, texto):
        respuesta = self.procesar(texto, hablar=False)
        try:
            self.telefono.notificar(respuesta, "JARVIS responde", 3)
        except Exception as e:
            log.warning("No pude responder al teléfono: %s", e)


ICONO = os.path.join(config.BASE, "ui", "jarvis.ico")


def poner_icono(ventana):
    """Icono propio en la ventana y la barra de tareas de Windows (en vez del de Python)."""
    if sys.platform != "win32":
        return
    try:
        from System import Action
        from System.Drawing import Icon
        form = ventana.native
        form.Invoke(Action(lambda: setattr(form, "Icon", Icon(ICONO))))
    except Exception as e:
        log.warning("No pude poner el icono: %s", e)


class Api:
    """Funciones que la interfaz (JavaScript) puede llamar."""

    def __init__(self, jarvis):
        self._j = jarvis

    def enviar(self, texto):
        if texto.strip():
            threading.Thread(target=self._j.procesar, args=(texto.strip(),), daemon=True).start()

    def activar(self):
        if self._j.escucha:
            self._j.escucha.activar()

    def detener(self):
        if getattr(self._j, "voz", None):
            self._j.voz.detener()

    def info(self):
        import psutil
        bat = psutil.sensors_battery()
        return {"cpu": psutil.cpu_percent(), "ram": psutil.virtual_memory().percent,
                "bat": round(bat.percent) if bat else None}


def main():
    if sys.platform == "win32":
        try:  # que Windows agrupe la ventana como "JARVIS" y no como Python
            import ctypes
            ctypes.windll.shell32.SetCurrentProcessExplicitAppUserModelID("Jarvis.Asistente")
        except Exception:
            pass
    jarvis = Jarvis()
    ui = os.path.join(config.BASE, "ui", "index.html")
    jarvis.ventana = webview.create_window(
        "J.A.R.V.I.S.", ui, js_api=Api(jarvis), width=1180, height=800,
        min_size=(760, 560), background_color="#01040c",
    )
    jarvis.ventana.events.loaded += jarvis.listo.set
    jarvis.ventana.events.shown += lambda: poner_icono(jarvis.ventana)
    webview.start(jarvis.iniciar, icon=ICONO)


if __name__ == "__main__":
    main()
