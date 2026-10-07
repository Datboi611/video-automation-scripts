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
from core import paneles
from core.telegram_bot import BotTelegram
from core.vigilante import Vigilante
from core.claude_code import ClaudeCode
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


SITIOS = {"google": "google.com", "youtube": "youtube.com", "gmail": "mail.google.com", "correo": "mail.google.com",
          "whatsapp web": "web.whatsapp.com", "netflix": "netflix.com", "canvas": "utah.instructure.com",
          "todoist": "app.todoist.com", "notion": "notion.so", "claude": "claude.ai", "chatgpt": "chatgpt.com",
          "calendario": "calendar.google.com", "google calendar": "calendar.google.com", "drive": "drive.google.com",
          "instagram": "instagram.com", "tiktok": "tiktok.com", "facebook": "facebook.com", "x": "x.com",
          "shopify": "admin.shopify.com", "plancitope": "plancitope.com"}


def accion_rapida(texto, herr, cfg):
    """Órdenes simples que se ejecutan al instante, sin gastar IA."""
    t = re.sub(r"^(oye |hey |ok )?jarvis[,.]?\s*", "", texto.lower()).strip(" .!¡?¿")
    t = re.sub(r"\s*(por favor|porfa|please)$", "", t)
    j = cfg["tratamiento"]
    m = re.match(r"^(?:puedes |podr[ií]as )?(?:abre|abrir|[aá]breme|open)\s+(?:el |la |los |mi |un )?(.+)$", t)
    if m and len(m.group(1)) < 40:
        destino = m.group(1).strip()
        if destino in SITIOS or re.search(r"\.(com|net|org|io|ai|edu|pe)\b", destino):
            herr.ejecutar("abrir_web", {"url": SITIOS.get(destino, destino)})
        else:
            r = herr.ejecutar("abrir_aplicacion", {"nombre": destino})
            if r.startswith("No encontr"):
                return None  # que lo resuelva la IA
        return f"Abriendo {destino}, {j}."
    m = re.match(r"^(?:pon|ponme|reproduce|play)\s+(?:algo de |m[uú]sica de |la canci[oó]n |canciones de |m[uú]sica )?(.+)$", t)
    if m and herr.musica and not re.search(r"\b(alarma|recordatorio|timer|temporizador)\b", t):
        r = herr.ejecutar("poner_musica", {"busqueda": m.group(1), "varias": True})
        return r if r.startswith("No") else f"Enseguida, {j}. {r}"
    if re.fullmatch(r"(pausa|pausar|pausa la m[uú]sica|para la m[uú]sica|det[eé]n la m[uú]sica|stop|silencio)", t):
        herr.ejecutar("controlar_musica", {"accion": "pausar"})
        return "Hecho."
    if re.fullmatch(r"(contin[uú]a|reanuda|sigue)( la m[uú]sica)?|play", t):
        herr.ejecutar("controlar_musica", {"accion": "reanudar"})
        return "Reanudando."
    if re.fullmatch(r"(siguiente|la siguiente|siguiente canci[oó]n|next|cambia de canci[oó]n|otra canci[oó]n)", t):
        return herr.ejecutar("controlar_musica", {"accion": "siguiente"})
    m = re.match(r"^(?:marca|marcar|completa|tacha)\s+(.+?)\s+como\s+(?:hech[ao]|completad[ao]|terminad[ao]|lista|listo)$", t) \
        or re.match(r"^(?:ya )?(?:hice|termin[eé]|complet[eé])\s+(?:el |la |los |las )?(.+)$", t)
    if m:
        return herr.ejecutar("marcar_hecho", {"texto": m.group(1)})
    return None


class Jarvis:
    def __init__(self):
        self.cfg = config.cargar()
        self.ventana = None
        self.listo = threading.Event()
        self.lock_voz = threading.Lock()
        self.escucha = None
        self.bot = None
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
        self.herramientas.ui = self.ui
        self.herramientas.claude = ClaudeCode(self.claude_termino)
        self.herramientas.on_resultado = self.mostrar_resultado
        self.cerebro = Cerebro(c, self.herramientas, self.memoria, self.habilidades)
        self.recordatorios.iniciar()

        try:
            from core.audio import Escucha
            from core.oido import Oido
            self.oido = Oido(c)
            self.escucha = Escucha(c, self.estado, self.nivel, self.comando_de_voz, self.despertar)
            self.escucha.on_interrupcion = self.voz.detener
            modos = ["di «" + c["activacion"]["palabra"].capitalize() + "»" if self.escucha.rec else None,
                     "aplaude dos veces" if c["activacion"]["aplausos"] else None, "toca la esfera"]
            self.ui("setHint", f"Te escucho siempre · tras {c['minutos_reposo']} min sin hablar descanso; "
                               "para despertarme: " + ", ".join(m for m in modos if m))
        except Exception as e:
            log.exception("Micrófono no disponible")
            self.ui("setHint", "Micrófono no disponible. Puedes escribirme.")
            self.ui("pedirTexto", "Escríbeme tu orden…")

        if c["telefono"]["control_remoto"]:
            self.telefono.escuchar_ordenes(self.orden_remota)

        # JARVIS en el iPhone (bot de Telegram) y vigilante de la agenda
        self.bot = BotTelegram(c, self, lambda k, v: config.guardar_valor(["telegram_bot", k], v))
        self.iniciar_bot()
        self.vigilante = Vigilante(c, self, os.path.join(config.DATOS, "avisos.json"))
        self.vigilante.iniciar()

        if not self.cerebro.proveedores:
            self.ui("pedirTexto", "Falta tu clave de Groq en config.json")
        h = dt.datetime.now().hour
        saludo = "Buenos días" if 5 <= h < 12 else "Buenas tardes" if h < 20 else "Buenas noches"
        self.decir(f"{saludo}, {c['tratamiento']}. Todos los sistemas operativos. Le escucho.")
        try:
            self.escucha.iniciar()
        except Exception:
            log.exception("No pude abrir el micrófono")
            self.escucha = None
            self.ui("setHint", "Micrófono no disponible. Puedes escribirme.")
            self.ui("pedirTexto", "Escríbeme tu orden…")
            self.estado("reposo")

    def mostrar_resultado(self, nombre, args, resultado):
        h = self.herramientas
        try:
            if nombre in ("resumen_del_dia", "todoist", "calendario", "listar_recordatorios", "crear_recordatorio",
                          "borrar_recordatorio", "todoist_agregar", "marcar_hecho", "pendiente_agregar"):
                self.ui("panel", "Tu día", paneles.agenda(h, int(args.get("dias", 1) or 1)))
            elif nombre == "pendientes":
                self.ui("panel", "Pendientes por proyecto", paneles.por_proyecto(h, args.get("proyecto")))
            elif nombre in PANEL:
                self.ui("panel", PANEL[nombre], paneles.desde_texto(resultado))
        except Exception:
            log.exception("No pude armar el panel")

    def claude_termino(self, tarea, resultado, ok):
        t = self.cfg["tratamiento"]
        self.ui("panel", "Claude", [{"t": "Terminado" if ok else "Falló", "tono": "ok" if ok else "crit",
                                     "items": [{"x": l, "sub": "", "tags": []} for l in resultado.splitlines() if l.strip()][:15]
                                     or [{"x": "(sin respuesta)", "sub": "", "tags": []}]}])
        resumen = resultado.strip().split("\n")[0][:220] if ok else ""
        self.decir(f"{t.capitalize()}, Claude terminó: {resumen}" if ok
                   else f"{t.capitalize()}, la tarea que le encargué a Claude no salió bien.")
        if self.bot:
            self.bot.enviar(("✅ Claude terminó:\n" if ok else "❌ Claude falló:\n") + resultado[:3500])

    def iniciar_bot(self):
        if not self.bot.activo:
            return
        self.bot.iniciar()
        if self.bot.codigo:
            self.ui("panel", "Vincular iPhone", [{"t": "Código", "tono": "warn", "items": [
                {"x": " ".join(self.bot.codigo), "sub": "Envíalo a tu bot en Telegram desde el iPhone", "tags": []}]}])

    def guardar_campo(self, campo, valor):
        """Lo que el usuario escribe en la barra cuando JARVIS le pide un dato."""
        valor = valor.strip()
        c = self.cfg
        if campo in ("todoist_token", "google_calendar_ics"):
            c["agenda"][campo] = valor
            config.guardar_valor(["agenda", campo], valor)
            if campo == "todoist_token":
                self.herramientas.agenda["todoist"].token = valor
                try:
                    self.herramientas.agenda["todoist"].tareas("today")
                    msg = f"Todoist conectado, {c['tratamiento']}. Sus tareas ya no tienen dónde esconderse."
                except Exception:
                    msg = "Guardé el token, pero Todoist lo rechazó. Revise que esté completo."
            else:
                self.herramientas.agenda["calendario"].url = valor
                msg = f"Calendario conectado, {c['tratamiento']}."
        elif campo == "telegram_bot_token":
            c.setdefault("telegram_bot", {})["token"] = valor
            c["telegram_bot"]["chat_id"] = ""
            config.guardar_valor(["telegram_bot"], {"token": valor, "chat_id": ""})
            self.bot = BotTelegram(c, self, lambda k, v: config.guardar_valor(["telegram_bot", k], v))
            try:
                self.bot._api("getMe")
            except Exception:
                return self.decir("Telegram rechazó ese token, jefe. Revise que esté completo.")
            self.iniciar_bot()
            msg = (f"Bot conectado, {c['tratamiento']}. Envíele desde su iPhone el código que le muestro en el panel: "
                   f"{' '.join(self.bot.codigo or '')}.")
        elif campo == "telegram_usuario":
            u = valor if valor.startswith("@") else "@" + valor
            c["telefono"]["telegram_usuario"] = u
            self.telefono.telegram = u
            config.guardar_valor(["telefono", "telegram_usuario"], u)
            msg = f"Listo, {c['tratamiento']}. Si se le olvida algo importante, le llamaré a {u}."
        elif campo == "elevenlabs_api_key":
            c["voz"]["elevenlabs_api_key"] = valor
            c["voz"]["motor"] = "elevenlabs"
            config.guardar_valor(["voz", "elevenlabs_api_key"], valor)
            config.guardar_valor(["voz", "motor"], "elevenlabs")
            msg = f"Voz nueva activada, {c['tratamiento']}. Confío en que esta le resulte bastante más humana."
        elif campo.endswith("_api_key"):
            prov = campo.replace("_api_key", "")
            lista = c["llm"]["proveedores"]
            p = next((x for x in lista if x["nombre"] == prov), None)
            if not p:
                p = {"nombre": prov, "modelo": config.MODELO_INICIAL.get(prov, "")}
                lista.insert(0 if prov == "claude" else len(lista), p)
            p["api_key"] = valor
            config.guardar_valor(["llm", "proveedores"], lista)
            self.cerebro = Cerebro(c, self.herramientas, self.memoria, self.habilidades)
            msg = f"Clave de {prov.capitalize()} guardada y activa, {c['tratamiento']}."
        else:
            return
        self.decir(msg)

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

    def procesar(self, texto, hablar=True, idioma="es", origen="voz"):
        """Cada pedido es un proceso independiente: pueden correr varios a la vez."""
        if self.escucha:
            self.escucha.actividad()
        self._n += 1
        pid = self._n
        self.activos += 1
        self.ui("addMsg", "usuario", texto)
        self.ui("proceso", pid, ("📱 " if origen == "telefono" else "") + texto, "en curso")
        error = False
        try:
            respuesta = respuesta_rapida(texto, idioma, self.cfg) or accion_rapida(texto, self.herramientas, self.cfg)
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
        self.ui("proceso", pid, ("📱 " if origen == "telefono" else "") + texto, "error" if error else "hecho")
        if hablar:
            self.decir(respuesta, idioma)
        else:
            self.ui("addMsg", "jarvis", respuesta)
            self.estado("reposo")
        return respuesta

    def comando_de_voz(self, audio):
        self.estado("pensando")
        texto, idioma = self.oido.transcribir(audio)
        if self.cfg.get("idioma", "es") == "es":
            idioma = "es"
        if not texto:
            self.estado("escuchando")
            return False
        limpio = texto.lower().strip(" .!¡?¿,")
        musica = self.herramientas.musica
        if musica and musica.sonando and "jarvis" not in limpio:
            return False  # con música sonando, el micrófono oye la canción: solo respondo si me llaman
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

    def enviar(self, texto, campo=None):
        if not texto.strip():
            return
        if campo:
            threading.Thread(target=self._j.guardar_campo, args=(campo, texto), daemon=True).start()
        else:
            threading.Thread(target=self._j.procesar, args=(texto.strip(),), daemon=True).start()

    def activar(self):
        if self._j.escucha:
            self._j.escucha.activar()

    def detener(self):
        if getattr(self._j, "voz", None):
            self._j.voz.detener()

    def musica(self, accion):
        m = getattr(getattr(self._j, "herramientas", None), "musica", None)
        if not m:
            return
        if accion == "siguiente":
            threading.Thread(target=m.siguiente, daemon=True).start()
        else:
            m.sonando = accion in ("reanudar", "play")

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
