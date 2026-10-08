"""J.A.R.V.I.S. — asistente de voz en español para Windows.
Ejecuta: python main.py   (o iniciar.bat)
"""
import datetime as dt
import json
import logging
import os
import random
import re
import sys
import threading
import time

import webview

from core import config
from core.cerebro import Cerebro
from core.habilidades import Habilidades
from core.herramientas import Herramientas
from core.correo import Correo
from core.integraciones import Calendario, Pendientes, Todoist
from core.musica import Musica
from core import paneles
from core.acotaciones import acotacion
from core.telegram_bot import BotTelegram
from core.vigilante import Vigilante
from core.claude_code import ClaudeCode
from core.canvas import Canvas
from core.presencia import Presencia, normalizar_mac
from core.llamadas_vivo import LlamadasVivo
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
        return f"Son las {ahora.strftime('%H:%M')}, {cfg['tratamiento']}." + acotacion("hora", cfg)
    if re.search(r"qu[eé] (d[ií]a|fecha) es hoy|what('s| is) (the date|today)", t):
        meses = ["enero", "febrero", "marzo", "abril", "mayo", "junio", "julio", "agosto", "septiembre",
                 "octubre", "noviembre", "diciembre"]
        dias = ["lunes", "martes", "miércoles", "jueves", "viernes", "sábado", "domingo"]
        if idioma == "en":
            return f"Today is {ahora.strftime('%A, %B %d')}, {cfg.get('tratamiento_en', 'boss')}."
        return f"Hoy es {dias[ahora.weekday()]} {ahora.day} de {meses[ahora.month - 1]}, {cfg['tratamiento']}."
    return None


PANEL = {  # herramienta -> título del menú lateral donde se muestra su resultado
    "canvas": "Canvas", "diagnostico": "Diagnóstico",
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
        return f"Abriendo {destino}, {j}." + acotacion("abrir", cfg, herr)
    m = re.match(r"^(?:pon|ponme|reproduce|play)\s+(?:algo de |m[uú]sica de |la canci[oó]n |canciones de |m[uú]sica )?(.+)$", t)
    if m and herr.musica and not re.search(r"\b(alarma|recordatorio|timer|temporizador)\b", t):
        r = herr.ejecutar("poner_musica", {"busqueda": m.group(1), "varias": True})
        return r if r.startswith("No") else f"Enseguida, {j}. {r}" + acotacion("musica", cfg, herr)
    if re.fullmatch(r"(pausa|pausar|pausa la m[uú]sica|para la m[uú]sica|det[eé]n la m[uú]sica|stop|silencio)", t):
        herr.ejecutar("controlar_musica", {"accion": "pausar"})
        return "Hecho." + acotacion("pausa", cfg, herr)
    if re.fullmatch(r"(contin[uú]a|reanuda|sigue)( la m[uú]sica)?|play", t):
        herr.ejecutar("controlar_musica", {"accion": "reanudar"})
        return "Reanudando."
    if re.fullmatch(r"(siguiente|la siguiente|siguiente canci[oó]n|next|cambia de canci[oó]n|otra canci[oó]n)", t):
        return herr.ejecutar("controlar_musica", {"accion": "siguiente"})
    # llamadas y mensajes al teléfono: directo, sin depender de la IA
    t = re.sub(r"^(?:haz|has|realiza|hazme|inicia)\s+(?:la|una)\s+llamada(?:\s+ahora)?", "llámame", t)
    m = re.match(r"^(?:ll[aá]mame|hazme una llamada|llama a mi (?:celular|tel[eé]fono|iphone))"
                 r"(?:\s+en\s+(\d+)\s*(?:minutos?|min))?(?:\s*(?:para|y|a)\s+(.*))?$", t)
    if m:
        minutos, motivo = m.group(1), (m.group(2) or "").strip()
        motivo = re.sub(r"^(?:recordarme|decirme|dime|avisarme)\s+(?:que\s+)?", "", motivo)
        if motivo in ("", "probar", "prueba", "una prueba", "probarlo", "ver si funciona"):
            motivo = ""
        if minutos:
            r = herr.ejecutar("crear_recordatorio", {"mensaje": motivo or "Llamada programada", "en_minutos": int(minutos),
                                                     "llamar": True})
            return (f"Le llamaré en {minutos} minutos, {j}." + acotacion("llamada", cfg, herr)) if r.startswith("Recordatorio") else r
        msg = (f"{j.capitalize()}, le habla JARVIS. " + (f"Le recuerdo: {motivo}." if motivo
               else "Esta es una llamada de prueba. Todo funciona correctamente."))
        r = herr.ejecutar("llamar_telefono", {"mensaje": msg})
        return (f"Llamándole ahora, {j}." + acotacion("llamada", cfg, herr)) if r.startswith(("Llamando", "Llamada")) else r
    m = re.match(r"^(?:m[aá]ndame|env[ií]ame|escr[ií]beme|manda|env[ií]a)\s+(?:un\s+)?(?:mensaje|texto|nota|aviso)?"
                 r"\s*(?:(?:por|al|a mi|a)\s+(?:telegram|celular|tel[eé]fono|iphone|m[oó]vil))?\s*"
                 r"(?:diciendo|que diga|con|que|:)?\s*(.*)$", t)
    if m and re.search(r"mensaje|texto|nota|aviso|telegram|celular|tel[eé]fono|iphone", t):
        cuerpo = re.sub(r"^(de )?prueba$", "", m.group(1).strip()) or "Prueba de JARVIS ✅ Todo funciona, jefe."
        r = herr.ejecutar("notificar_telefono", {"mensaje": cuerpo[:1].upper() + cuerpo[1:]})
        return (f"Enviado a su iPhone, {j}." + acotacion("mensaje", cfg, herr)) if r.startswith(("Mensaje enviado", "Notificación")) else r
    if re.search(r"\b(revisa|checa|chequea|mira|lee|tengo|hay)\b.*\b(correo|correos|mail|mails|email|inbox|bandeja)\b", t):
        r = herr.ejecutar("correo", {"solo_no_leidos": True})
        if "no está conectado" in r:
            return f"Su correo aún no está conectado, {j}. Escriba su dirección en la barra que le abrí."
        if r.startswith("Error"):
            return f"Su correo no me deja entrar ahora, {j}. Probablemente la contraseña de aplicación cambió; dígame «conecta mi correo» y lo arreglamos."
        correos = [l[2:] for l in r.splitlines() if l.startswith("- ")]
        if not correos:
            return f"Bandeja limpia, {j}. Nada nuevo sin leer."
        de, _, resto = correos[0].partition(":")
        asunto = resto.split("—")[0].strip()
        return (f"Tiene {len(correos)} correo{'s' if len(correos) > 1 else ''} sin leer, {j}. "
                f"El más reciente es de {de.strip()}: {asunto}. Le dejé el resto en el panel." + acotacion("correo", cfg, herr))
    if re.search(r"\b(conecta|vincula|configura|enlaza)\b.*\b(iphone|tel[eé]fono|celular|telegram|bot|m[oó]vil)\b", t) \
            and not re.search(r"llam", t):
        bot = getattr(herr, "bot", None)
        if not bot or not bot.activo:
            herr.ejecutar("pedir_dato", {"campo": "telegram_bot_token"})
            return f"Pegue en la barra el token que le dio BotFather, {j}. Lo demás lo hago yo."
        if not bot.cfg.get("chat_id"):
            return f"Ya casi, {j}. Abra su bot en Telegram y pulse Iniciar; lo vinculo yo solo."
        return f"Su iPhone ya está vinculado, {j}." + acotacion("mensaje", cfg, herr)
    if re.fullmatch(r"(haz|hazte|corre|ejecuta)( un)? (diagn[oó]stico|chequeo|revisi[oó]n)( del sistema| de todo)?|diagn[oó]stico", t):
        return herr.ejecutar("diagnostico", {})
    m = re.match(r"^(?:marca|marcar|completa|tacha)\s+(.+?)\s+como\s+(?:hech[ao]|completad[ao]|terminad[ao]|lista|listo)$", t) \
        or re.match(r"^(?:ya )?(?:hice|termin[eé]|complet[eé])\s+(?:el |la |los |las )?(.+)$", t)
    if m:
        r = herr.ejecutar("marcar_hecho", {"texto": m.group(1)})
        return r + (acotacion("hecho", cfg, herr, 0.6) if not r.startswith("No encontr") else "")
    return None


PATRONES_CLAVE = [
    (r"\b\d{8,11}:[A-Za-z0-9_-]{30,}\b", "telegram_bot_token"),
    (r"\bgsk_[A-Za-z0-9]{20,}\b", "groq_api_key"),
    (r"\bsk_[a-f0-9]{40,}\b", "elevenlabs_api_key"),
    (r"\bAIza[0-9A-Za-z_-]{30,}\b", "gemini_api_key"),
    (r"\bAC[a-f0-9]{32}\b", "twilio_sid"),
]


def datos_twilio(texto):
    """Si pegó los datos de Twilio juntos: SID, token y números (el primero es el de Twilio, el segundo el suyo)."""
    sid = re.search(r"\bAC[a-f0-9]{32}\b", texto)
    if not sid:
        return None
    resto = texto.replace(sid.group(0), " ")
    token = re.search(r"\b[a-f0-9]{32}\b", resto)
    numeros = re.findall(r"\+?\d[\d\s().-]{8,}\d", resto.replace(token.group(0), " ") if token else resto)
    datos = {"twilio_sid": sid.group(0)}
    if token:
        datos["twilio_token"] = token.group(0)
    if len(numeros) >= 1:
        datos["twilio_numero"] = numeros[0]
    if len(numeros) >= 2:
        datos["mi_numero"] = numeros[1]
    return datos


def detectar_clave(texto):
    for patron, campo in PATRONES_CLAVE:
        m = re.search(patron, texto)
        if m:
            return campo, m.group(0)
    return None, None


class Jarvis:
    def __init__(self):
        self.cfg = config.cargar()
        self.ventana = None
        self.listo = threading.Event()
        self.lock_voz = threading.Lock()
        self.escucha = None
        self.bot = None
        self.presencia = None
        self.avisos_ausente = []
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
            "canvas": Canvas(c["agenda"].get("canvas_url"), c["agenda"].get("canvas_token"), config.DATOS),
        }
        self.habilidades = Habilidades(os.path.join(config.BASE, "habilidades"))
        self.herramientas = Herramientas(self.memoria, self.recordatorios, self.telefono, cfg=c,
                                         agenda=agenda, habilidades=self.habilidades, voz=self.voz)
        self.herramientas.musica = Musica(self.ui)
        self.herramientas.ui = self.ui
        self.herramientas.claude = ClaudeCode(self.claude_termino)
        self.herramientas.al_conectar_canvas = self.canvas_conectado
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
        self.herramientas.bot = self.bot
        self.iniciar_bot()
        self.vigilante = Vigilante(c, self, os.path.join(config.DATOS, "avisos.json"))
        self.vigilante.iniciar()
        # ¿estás en casa? (iPhone en el mismo WiFi) -> puede hablar; si no, silencio y todo por Telegram
        self.presencia = Presencia(c, self.salio_de_casa, self.volvio_a_casa)
        self.presencia.iniciar()
        # hablar con JARVIS por teléfono en tiempo real (llamas al número de JARVIS o él te llama)
        self.vivo = LlamadasVivo(self, config.DATOS)
        self.telefono.vivo = self.vivo
        self.vivo.iniciar()

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

    # ---------- Presencia ----------
    def puede_hablar(self):
        return not self.presencia or self.presencia.presente

    def avisar_por_voz(self, texto):
        """Avisos por iniciativa propia: los dice si estás en casa; si no, los guarda para cuando vuelvas."""
        if self.puede_hablar():
            self.decir(texto)
        else:
            self.avisos_ausente.append(texto)

    def salio_de_casa(self):
        if self.escucha:
            self.escucha.dormir()
        self.ui("setHint", "Fuera de casa: modo silencioso, todo va a tu Telegram")
        if self.bot:
            self.bot.enviar(f"🚪 Detecté que salió de casa, {self.cfg['tratamiento']}. Modo silencioso: le aviso todo por aquí.")

    def volvio_a_casa(self):
        t = self.cfg["tratamiento"]
        if self.escucha:
            self.escucha.actividad()
        pendientes, self.avisos_ausente = self.avisos_ausente, []
        msg = f"Bienvenido de vuelta, {t}."
        if pendientes:
            msg += f" Mientras no estaba hubo {len(pendientes)} novedades. La más reciente: {pendientes[-1]}"
        self.ui("setHint", "Te escucho siempre")
        self.decir(msg)

    def canvas_conectado(self, ok):
        t = self.cfg["tratamiento"]
        if not ok:
            return self.decir(f"No se completó el inicio de sesión en Canvas, {t}. Lo intentamos cuando quiera.")
        try:
            n = len(self.herramientas.agenda["canvas"].cursos())
            self.decir(f"Canvas conectado, {t}. Vigilo sus {n} cursos; ninguna tarea nueva pasará desapercibida.")
            self.mostrar_resultado("canvas", {}, self.herramientas.canvas("pendientes"))
        except Exception:
            log.exception("Canvas tras login")
            self.decir(f"Inicié sesión, {t}, pero Canvas no me dejó leer los cursos. Revisaré más tarde.")

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
        if not self.bot.cfg.get("chat_id"):
            self.ui("panel", "Vincular iPhone", [{"t": "Un paso", "tono": "warn", "items": [
                {"x": "Abre tu bot en Telegram y pulsa Iniciar", "sub": "Se vincula solo", "tags": []}]}])

    def guardar_twilio(self, datos):
        from core.telefono import normalizar_numero
        c = self.cfg
        for k, v in datos.items():
            if k in ("twilio_numero", "mi_numero"):
                v = normalizar_numero(v)
            c["telefono"][k] = v
            config.guardar_valor(["telefono", k], v)
        faltan = [k for k in ("twilio_sid", "twilio_token", "twilio_numero", "mi_numero") if not c["telefono"].get(k)]
        if not faltan and getattr(self, "vivo", None) and not self.vivo.url:
            self.vivo.iniciar()
        if faltan:
            self.herramientas.pedir_dato(faltan[0])
            return self.decir("Guardé lo de Twilio. Me falta un dato; lo pido en la barra.")
        try:
            self.telefono.llamar_twilio(f"Hola {c['tratamiento']}, le habla JARVIS. Llamadas configuradas correctamente.")
            self.decir(f"Llamadas configuradas, {c['tratamiento']}. Le estoy llamando ahora; conteste.")
        except Exception as e:
            log.warning("Prueba Twilio: %s", e)
            self.decir(f"Guardé los datos, {c['tratamiento']}, pero Twilio no aceptó la llamada. "
                       "Le dejo el motivo en el panel.")
            self.ui("panel", "Twilio", [{"t": "Motivo", "tono": "crit", "items": [{"x": str(e)[:300], "sub": "", "tags": []}]}])

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
            self.herramientas.bot = self.bot
            self.iniciar_bot()
            msg = (f"Bot conectado, {c['tratamiento']}. Ahora abra su bot en Telegram desde el iPhone y pulse Iniciar; "
                   "lo vinculo yo solo.")
        elif campo == "canvas_token":
            c["agenda"]["canvas_token"] = valor
            config.guardar_valor(["agenda", "canvas_token"], valor)
            cv = self.herramientas.agenda["canvas"]
            cv.token, cv._cursos = valor, None
            try:
                n = len(cv.cursos())
                msg = f"Canvas conectado, {c['tratamiento']}. Vigilo sus {n} cursos; ninguna tarea nueva pasará desapercibida."
            except Exception:
                msg = "Guardé el token, pero Canvas lo rechazó. Revise que esté completo."
        elif campo in ("correo_email", "correo_app_password"):
            cuentas = c.setdefault("correo", [])
            if not cuentas:
                cuentas.append({"nombre": "personal", "email": "", "app_password": ""})
            cuentas[0]["email" if campo == "correo_email" else "app_password"] = valor
            config.guardar_valor(["correo"], cuentas)
            self.herramientas.agenda["correo"] = Correo(cuentas)
            if campo == "correo_email":
                self.herramientas.pedir_dato("correo_app_password")
                msg = ("Anotado. Ahora pegue la contraseña de aplicación: en Gmail, myaccount.google.com/apppasswords; "
                       "en iCloud, appleid.apple.com, contraseñas de apps.")
            else:
                try:
                    self.herramientas.agenda["correo"].cuentas[0].buscar("UNSEEN", 1)
                    msg = f"Correo conectado, {c['tratamiento']}. Le avisaré solo de lo que importe."
                except Exception:
                    msg = "El correo rechazó esa contraseña. Asegúrese de usar una contraseña de aplicación, no la normal."
        elif campo == "telefono_mac":
            mac = normalizar_mac(valor)
            if not mac:
                return self.decir("Esa dirección no parece válida, jefe. Son 12 caracteres, como a1:b2:c3:d4:e5:f6.")
            c.setdefault("presencia", {})["telefono_mac"] = mac
            config.guardar_valor(["presencia", "telefono_mac"], mac)
            visto = self.presencia.visto()
            msg = (f"Listo, {c['tratamiento']}. Veo su iPhone en la red: cuando salga de casa me callaré." if visto else
                   f"Guardado, {c['tratamiento']}, pero no veo su iPhone en este WiFi ahora. "
                   "Revise que la dirección Wi-Fi privada esté en modo fija.")
        elif campo in ("twilio_sid", "twilio_token", "twilio_numero", "mi_numero"):
            if campo in ("twilio_numero", "mi_numero"):
                from core.telefono import normalizar_numero
                valor = normalizar_numero(valor)
            c["telefono"][campo] = valor
            config.guardar_valor(["telefono", campo], valor)
            siguiente = {"twilio_sid": "twilio_token", "twilio_token": "twilio_numero", "twilio_numero": "mi_numero"}.get(campo)
            if siguiente:
                self.herramientas.pedir_dato(siguiente)
                msg = "Anotado. Siguiente dato en la barra."
            else:
                try:
                    self.telefono.llamar_twilio(f"Hola {c['tratamiento']}, le habla JARVIS. Prueba de llamada exitosa. "
                                                "Desde ahora le llamaré cuando algo no pueda esperar.")
                    msg = f"Le estoy llamando como prueba, {c['tratamiento']}. Conteste."
                except Exception as e:
                    log.warning("Prueba Twilio: %s", e)
                    msg = ("Guardé los datos, pero Twilio rechazó la llamada. Si su cuenta es de prueba, "
                           "verifique su número en Twilio, en Verified Caller IDs.")
        elif campo == "telegram_chat_id":
            cid = re.sub(r"[^\d-]", "", valor)
            if not cid:
                return self.decir("Ese no parece un Id de Telegram, jefe. Son solo números, se lo da @userinfobot.")
            c.setdefault("telegram_bot", {})["chat_id"] = cid
            config.guardar_valor(["telegram_bot", "chat_id"], cid)
            if self.bot:
                self.bot.cfg["chat_id"], self.bot.codigo = cid, None
                ok = self.bot.enviar("✅ Vinculado, jefe. Desde ahora le obedezco aquí también. Comandos: /hoy /pantalla /estado")
            else:
                ok = False
            msg = (f"Teléfono vinculado, {c['tratamiento']}. Le acabo de escribir por Telegram." if ok else
                   "Guardé su Id, pero no pude escribirle: abra su bot en Telegram, pulse Iniciar y pídame un mensaje de prueba.")
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
        tw = datos_twilio(texto)
        if tw and len(tw) > 1:
            self.guardar_twilio(tw)
            return "Configurado."
        campo, valor = detectar_clave(texto)
        if campo:  # pegó un token o clave: lo guardo directo, sin preguntar
            self.guardar_campo(campo, valor)
            return "Configurado."
        self._n += 1
        pid = self._n
        self.activos += 1
        self.ui("addMsg", "usuario", texto)
        self.ui("proceso", pid, ("📱 " if origen == "telefono" else "") + texto, "en curso")
        error = False
        try:
            respuesta = respuesta_rapida(texto, idioma, self.cfg) or accion_rapida(texto, self.herramientas, self.cfg)
            if respuesta and respuesta.lower().startswith("error"):
                respuesta = None  # que lo resuelva la IA por otra vía
            if not respuesta:
                self.estado("pensando")
                guardar_preferencia(texto, self.memoria)
                respuesta = self.cerebro.responder(
                    texto, on_herramienta=lambda n: self.ui("proceso", pid, texto, n.replace("_", " ")),
                    idioma=idioma)
                error = self.cerebro.hubo_error or not respuesta
        except Exception:
            log.exception("Fallo procesando")
            error = True
        finally:
            self.activos -= 1
        etiqueta = ("📱 " if origen == "telefono" else "") + texto
        if error:
            # nunca "hubo un error": aviso natural y sigo intentándolo en segundo plano
            self.ui("proceso", pid, etiqueta, "reintentando…")
            respuesta = random.choice([f"Un momento, {self.cfg['tratamiento']}, estoy en ello.",
                                       f"Deme unos segundos, {self.cfg['tratamiento']}. Mis servidores van algo lentos.",
                                       f"Enseguida, {self.cfg['tratamiento']}. Lo estoy resolviendo."])
            threading.Thread(target=self._reintentar, args=(texto, idioma, origen, pid, etiqueta, hablar),
                             daemon=True).start()
        else:
            self.ui("proceso", pid, etiqueta, "hecho")
        if hablar:
            self.decir(respuesta, idioma)
        else:
            self.ui("addMsg", "jarvis", respuesta)
            self.estado("reposo")
        return respuesta

    def _reintentar(self, texto, idioma, origen, pid, etiqueta, hablar):
        """Reintenta en silencio; si Groq no vuelve, usa a Claude como cerebro de respaldo."""
        from core.cerebro import claude_respaldo
        respuesta = None
        for espera in (6, 20, 45):
            time.sleep(espera)
            try:
                r = self.cerebro.responder(texto, idioma=idioma)
                if r and not self.cerebro.hubo_error:
                    respuesta = r
                    break
            except Exception:
                log.exception("Reintento")
        if not respuesta:
            self.ui("proceso", pid, etiqueta, "consultando a Claude")
            respuesta = claude_respaldo(texto, self.cerebro._sistema())
        intento = 0
        while not respuesta:  # no me rindo: sigo hasta tener la respuesta
            intento += 1
            self.ui("proceso", pid, etiqueta, f"reintentando ({intento})")
            if intento == 1 and hablar:
                self.decir(f"Sigo trabajando en lo que me pidió, {self.cfg['tratamiento']}. Le aviso apenas lo tenga.")
            time.sleep(min(120, 30 * intento))
            try:
                self.cerebro = Cerebro(self.cfg, self.herramientas, self.memoria, self.habilidades)  # refresca modelos
                r = self.cerebro.responder(texto, idioma=idioma)
                if r and not self.cerebro.hubo_error:
                    respuesta = r
                    break
            except Exception:
                log.exception("Reintento largo")
            respuesta = claude_respaldo(texto, self.cerebro._sistema()) if intento % 3 == 0 else None
        self.ui("proceso", pid, etiqueta, "hecho")
        if origen == "telefono" and self.bot:
            self.bot.enviar(respuesta)
        elif hablar:
            self.decir(respuesta, idioma)

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
        if self.bot and not self.puede_hablar():
            self.bot.enviar("⏰ " + aviso)
        self.avisar_por_voz(aviso)

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
        tw = datos_twilio(texto)
        if tw and len(tw) > 1:
            threading.Thread(target=self._j.guardar_twilio, args=(tw,), daemon=True).start()
            return
        detectado, valor = detectar_clave(texto)
        if detectado and (not campo or campo != detectado):
            campo, texto = detectado, valor  # reconoce la clave aunque la barra pidiera otra cosa
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
