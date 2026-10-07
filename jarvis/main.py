"""J.A.R.V.I.S. — asistente de voz en español para Windows.
Ejecuta: python main.py   (o iniciar.bat)
"""
import datetime as dt
import json
import logging
import os
import re
import sys
import threading

import webview

from core import config
from core.cerebro import Cerebro
from core.habilidades import Habilidades
from core.herramientas import Herramientas
from core.correo import Correo
from core.integraciones import Calendario, Pendientes, Todoist
from core.musica import Musica
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


PREFERENCIA = re.compile(r"\b(siempre|nunca|prefiero|me gusta|no me gusta|recuerda que|acuérdate|de ahora en adelante|"
                         r"a partir de ahora|always|never|i prefer|remember that|from now on)\b", re.I)


def guardar_preferencia(texto, memoria):
    """Guarda al instante instrucciones permanentes del usuario (además de lo que guarde el LLM)."""
    if PREFERENCIA.search(texto) and len(texto) < 300 and texto not in memoria.datos:
        memoria.agregar(f"Instrucción del usuario: {texto}")


def respuesta_rapida(texto, idioma, cfg):
    """Respuestas instantáneas sin IA para lo más común."""
    t = texto.lower()
    ahora = dt.datetime.now()
    if re.search(r"qu[eé] hora es|what time is it|dime la hora", t):
        if idioma == "en":
            return f"It's {ahora.strftime('%I:%M %p').lstrip('0')}, {cfg.get('tratamiento_en', 'boss')}."
        return f"Son las {ahora.strftime('%H:%M')}, {cfg['tratamiento']}."
    if re.search(r"qu[eé] (d[ií]a|fecha) es hoy|what('s| is) (the date|today)", t):
        meses = ["enero", "febrero", "marzo", "abril", "mayo", "junio", "julio", "agosto", "septiembre",
                 "octubre", "noviembre", "diciembre"]
        dias = ["lunes", "martes", "miércoles", "jueves", "viernes", "sábado", "domingo"]
        if idioma == "en":
            return f"Today is {ahora.strftime('%A, %B %d')}, {cfg.get('tratamiento_en', 'boss')}."
        return f"Hoy es {dias[ahora.weekday()]} {ahora.day} de {meses[ahora.month - 1]}, {cfg['tratamiento']}."
    return None


PANEL = {  # herramienta -> título del menú lateral donde se muestra su resultado
    "resumen_del_dia": "Tu día", "calendario": "Calendario", "todoist": "Todoist", "pendientes": "Pendientes",
    "listar_recordatorios": "Recordatorios", "correo": "Correo", "clima": "Clima", "info_sistema": "Sistema",
    "ver_pantalla": "Lo que veo", "buscar_archivos": "Archivos", "listar_carpeta": "Carpeta",
}


class Jarvis:
    def __init__(self):
        self.cfg = config.cargar()
        self.ventana = None
        self.listo = threading.Event()
        self.lock_voz = threading.Lock()
        self.escucha = None
        self.activos = 0
        self._n = 0

    # ---------- Interfaz ----------
    def ui(self, fn, *args):
        if not self.ventana or not self.listo.is_set():
            return
        try:
            self.ventana.evaluate_js(f"window.J && J.{fn}({','.join(json.dumps(a, default=str) for a in args)})")
        except Exception:
            pass

    def estado(self, s):
        if s in ("reposo", "escuchando") and self.activos:
            s = "pensando"  # aún hay procesos trabajando
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
        self.voz = Voz(c, config.DATOS, on_nivel=self.nivel)
        agenda = {
            "calendario": Calendario(c["agenda"]["google_calendar_ics"]),
            "todoist": Todoist(c["agenda"]["todoist_token"]),
            "pendientes": Pendientes(os.path.join(config.DATOS, "pendientes.json")),
            "correo": Correo(c.get("correo", [])),
        }
        self.habilidades = Habilidades(os.path.join(config.BASE, "habilidades"))
        self.herramientas = Herramientas(self.memoria, self.recordatorios, self.telefono, cfg=c,
                                         agenda=agenda, habilidades=self.habilidades, voz=self.voz)
        self.herramientas.musica = Musica(self.ui)
        self.herramientas.on_resultado = self.mostrar_resultado
        self.cerebro = Cerebro(c, self.herramientas, self.memoria, self.habilidades)
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
            self.ui("setHint", "Micrófono no disponible. Puedes escribirme.")
            self.ui("mostrarChat")

        if c["telefono"]["control_remoto"]:
            self.telefono.escuchar_ordenes(self.orden_remota)

        if not self.cerebro.proveedores:
            self.ui("addMsg", "sistema", "Falta tu clave gratuita de Groq en config.json.")
            self.ui("mostrarChat")
        h = dt.datetime.now().hour
        saludo = "Buenos días" if 5 <= h < 12 else "Buenas tardes" if h < 20 else "Buenas noches"
        self.decir(f"{saludo}, {c['tratamiento']}. Todos los sistemas operativos. Le escucho.")
        try:
            self.escucha.iniciar()
        except Exception:
            log.exception("No pude abrir el micrófono")
            self.escucha = None
            self.ui("setHint", "Micrófono no disponible. Puedes escribirme.")
            self.ui("mostrarChat")
            self.estado("reposo")

    def mostrar_resultado(self, nombre, args, resultado):
        if nombre in PANEL:
            self.ui("panel", PANEL[nombre], resultado)
        elif nombre in ("crear_recordatorio", "borrar_recordatorio"):
            self.ui("panel", "Recordatorios", self.herramientas.listar_recordatorios())
        elif nombre in ("todoist_agregar", "todoist_completar"):
            self.ui("panel", "Todoist", self.herramientas.todoist())
        elif nombre in ("pendiente_agregar", "pendiente_completar"):
            self.ui("panel", "Pendientes", self.herramientas.pendientes())

    # ---------- Flujo principal ----------
    def decir(self, texto, idioma="es"):
        with self.lock_voz:  # varias respuestas a la vez se dicen por turnos
            self.ui("addMsg", "jarvis", texto)
            self.ui("setState", "hablando")
            if self.escucha:
                self.escucha.silencio.set()
            try:
                self.voz.hablar(texto, idioma)
            finally:
                if self.escucha:
                    self.escucha.silencio.clear()
                self.estado("escuchando" if self.escucha else "reposo")

    def procesar(self, texto, hablar=True, idioma="es"):
        """Cada pedido es un proceso independiente: pueden correr varios a la vez."""
        if self.escucha:
            self.escucha.actividad()
        self._n += 1
        pid = self._n
        self.activos += 1
        self.ui("addMsg", "usuario", texto)
        self.ui("proceso", pid, texto, "en curso")
        error = False
        try:
            respuesta = respuesta_rapida(texto, idioma, self.cfg)
            if not respuesta:
                self.estado("pensando")
                guardar_preferencia(texto, self.memoria)
                respuesta = self.cerebro.responder(
                    texto, on_herramienta=lambda n: self.ui("proceso", pid, texto, n.replace("_", " ")),
                    idioma=idioma)
                error = self.cerebro.hubo_error
        except Exception:
            log.exception("Error procesando")
            respuesta, error = f"Hubo un error, {self.cfg['tratamiento']}.", True
        finally:
            self.activos -= 1
        self.ui("proceso", pid, texto, "error" if error else "hecho")
        if error:
            self.ui("addMsg", "sistema", "Hubo un error. Repítelo o escríbeme aquí.")
            self.ui("mostrarChat")
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
            self.estado("escuchando")
            return False
        limpio = texto.lower().strip(" .!¡?¿,")
        if any(f in limpio for f in ("descansa", "duérmete", "duermete", "modo reposo", "go to sleep", "sleep mode")):
            self.ui("addMsg", "usuario", texto)
            self.decir("Entrando en reposo. Aplauda o diga Jarvis cuando me necesite." if idioma == "es"
                       else "Going to sleep. Clap or say Jarvis when you need me.", idioma)
            self.escucha.dormir()
            return False
        # en segundo plano: sigo escuchando mientras trabajo
        threading.Thread(target=self.procesar, args=(texto,), kwargs={"idioma": idioma}, daemon=True).start()
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
        self.ui("panel", "Recordatorio", r["mensaje"])
        self.decir(aviso)

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

    def musica(self, accion):
        m = getattr(getattr(self._j, "herramientas", None), "musica", None)
        if m and accion == "siguiente":
            threading.Thread(target=m.siguiente, daemon=True).start()

    def info(self):
        import psutil
        bat = psutil.sensors_battery()
        return {"cpu": psutil.cpu_percent(), "ram": psutil.virtual_memory().percent,
                "bat": round(bat.percent) if bat else None}


def main():
    # permitir que la música suene en la interfaz sin hacer clic primero
    os.environ.setdefault("WEBVIEW2_ADDITIONAL_BROWSER_ARGUMENTS", "--autoplay-policy=no-user-gesture-required")
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
