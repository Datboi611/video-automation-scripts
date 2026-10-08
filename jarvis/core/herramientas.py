"""Herramientas que JARVIS puede usar para controlar Windows y el mundo exterior."""
import datetime as dt
import difflib
import json
import logging
import os
import re
import subprocess
import threading
import sys
import urllib.parse
import webbrowser

import requests

log = logging.getLogger("jarvis")
ES_WINDOWS = sys.platform == "win32"
SIN_VENTANA = 0x08000000 if ES_WINDOWS else 0

BLOQUEADOS = [
    r"\bformat(-volume)?\s+[a-z]:", r"\bdiskpart\b", r"\bbcdedit\b", r"\bcipher\s+/w",
    r"remove-item\s+.*[a-z]:\\\s*(-|$)", r"\brd\s+/s\s+/q\s+[a-z]:\\\s*$", r"\bdel\s+/[fsq].*[a-z]:\\\*",
]

ALIAS_PROCESOS = {
    "chrome": "chrome.exe", "google chrome": "chrome.exe", "edge": "msedge.exe", "firefox": "firefox.exe",
    "word": "winword.exe", "excel": "excel.exe", "powerpoint": "powerpnt.exe", "spotify": "spotify.exe",
    "bloc de notas": "notepad.exe", "notepad": "notepad.exe", "visual studio code": "code.exe",
    "vscode": "code.exe", "discord": "discord.exe", "whatsapp": "whatsapp.exe", "steam": "steam.exe",
    "calculadora": "calculatorapp.exe", "explorador": "explorer.exe", "teams": "ms-teams.exe",
}

CLIMA = {0: "despejado", 1: "mayormente despejado", 2: "parcialmente nublado", 3: "nublado", 45: "niebla",
         48: "niebla", 51: "llovizna", 53: "llovizna", 55: "llovizna intensa", 61: "lluvia ligera",
         63: "lluvia", 65: "lluvia fuerte", 71: "nieve", 80: "chubascos", 81: "chubascos", 82: "chubascos fuertes",
         95: "tormenta", 96: "tormenta con granizo", 99: "tormenta con granizo"}


def _ps(comando, timeout=60):
    r = subprocess.run(
        ["powershell", "-NoProfile", "-ExecutionPolicy", "Bypass", "-Command", comando],
        capture_output=True, text=True, timeout=timeout, creationflags=SIN_VENTANA,
        encoding="utf-8", errors="replace",
    )
    return (r.stdout + r.stderr).strip()


def _fecha(texto):
    texto = texto.strip().replace("T", " ")
    for fmt in ("%Y-%m-%d %H:%M", "%Y-%m-%d %H:%M:%S", "%H:%M"):
        try:
            d = dt.datetime.strptime(texto, fmt)
            if fmt == "%H:%M":
                hoy = dt.datetime.now()
                d = d.replace(year=hoy.year, month=hoy.month, day=hoy.day)
                if d < hoy:
                    d += dt.timedelta(days=1)
            return d
        except ValueError:
            pass
    raise ValueError("Formato de fecha inválido, usa 'YYYY-MM-DD HH:MM' o 'HH:MM'")


S = "string"
# (nombre, descripción, {parámetro: (tipo, descripción)}, [obligatorios])  — descripciones cortas = menos tokens
SPECS = [
    ("resumen_del_dia", "Agenda completa: eventos de Google Calendar, tareas de Todoist, pendientes personales y recordatorios. Úsalo para '¿qué tengo hoy?', '¿qué deberes/pendientes tengo?'.",
     {"dias": ("integer", "Días a incluir (1=hoy, 7=semana)")}, []),
    ("calendario", "Eventos de Google Calendar de los próximos días.", {"dias": ("integer", "Días")}, []),
    ("agregar_evento", "Agenda un evento en Google Calendar.",
     {"titulo": (S, "Título"), "fecha_hora": (S, "'YYYY-MM-DD HH:MM'"), "duracion_min": ("integer", "Minutos")}, ["titulo", "fecha_hora"]),
    ("todoist", "Tareas de Todoist. filtro de Todoist p. ej. 'today | overdue', '7 days', '#Universidad'.", {"filtro": (S, "Filtro")}, []),
    ("todoist_agregar", "Crea una tarea en Todoist.", {"contenido": (S, "Tarea"), "fecha": (S, "Fecha en lenguaje natural, p. ej. 'mañana 5pm'")}, ["contenido"]),
    ("todoist_completar", "Marca como hecha una tarea de Todoist.", {"texto": (S, "Parte del nombre")}),
    ("pendientes", "Pendientes personales por proyecto (Pill&Go, Ezma, Universidad, Trámites, Carrera, Startups, Finanzas).",
     {"proyecto": (S, "Proyecto opcional"), "solo_urgentes": ("boolean", "Solo vencidos/próximos/alta prioridad")}, []),
    ("pendiente_agregar", "Agrega un pendiente personal.",
     {"texto": (S, "Pendiente"), "proyecto": (S, "Proyecto"), "fecha": (S, "YYYY-MM-DD"), "prioridad": (S, "alta/media/baja")}, ["texto"]),
    ("marcar_hecho", "Marca una tarea como hecha en Todoist y en los pendientes personales.", {"texto": (S, "Parte del nombre de la tarea")}),
    ("pedir_dato", "Muestra la barra para que el usuario escriba un dato de configuración y lo guarda solo (token de Todoist, enlace iCal de Google Calendar, clave de Gemini/Claude).",
     {"campo": (S, "todoist_token | google_calendar_ics | gemini_api_key | claude_api_key | groq_api_key | elevenlabs_api_key | telegram_bot_token | telegram_chat_id | telegram_usuario | canvas_token | correo_email | correo_app_password | telefono_mac | shopify | twilio_sid | twilio_token | twilio_numero | mi_numero"),
      "motivo": (S, "Texto que verá en la barra")}, ["campo"]),
    ("mostrar_panel", "Muestra información estructurada en el menú lateral (análisis de ideas, investigaciones, listas).",
     {"titulo": (S, "Título"), "secciones": ("array", "Lista de {titulo, puntos:[texto]}")}, ["titulo", "secciones"]),
    ("pedir_texto", "Abre una caja de texto para que el usuario ESCRIBA algo que no entendiste por voz (un enlace, código, nombre raro, tarea compleja).",
     {"motivo": (S, "Qué necesitas que escriba")}),
    ("shopify_ventas", "Ventas de la tienda Shopify (Ezma Shop): pedidos, total vendido, pendientes de envío.", {"dias": ("integer", "1=hoy, 7=semana")}, []),
    ("shopify_pedidos", "Últimos pedidos de Shopify con cliente, monto, estado y productos.", {"cantidad": ("integer", "Cuántos")}, []),
    ("shopify_inventario", "Stock y precios de productos en Shopify.", {"busqueda": (S, "Producto, opcional")}, []),
    ("pillgo_videos", "Genera los 5 videos diarios de Pill&Go: ejecuta 'py lanzar.py' (tanda con fecha de mañana desvinculada en el Programador de tareas + vigía que relanza y avisa por Telegram).", {}),
    ("pillgo_estado", "Estado de la generación de videos de Pill&Go en curso.", {}),
    ("pillgo_parar", "Detiene la tanda de videos de Pill&Go y su vigía (solo si el usuario lo pide).", {}),
    ("diagnostico", "Revisa que todos los servicios funcionen (IA, Telegram, llamadas, voz, Todoist, Canvas, correo).", {}),
    ("canvas", "Canvas de la universidad: pendientes/próximas entregas, anuncios, notas y mensajes, cursos.",
     {"que": (S, "pendientes | anuncios | notas | cursos")}, []),
    ("canvas_abrir", "Abre Canvas en el navegador (un curso o una tarea concreta).", {"busqueda": (S, "Curso o tarea, opcional")}, []),
    ("canvas_iniciar_sesion", "Abre una ventana para que el usuario inicie sesión en Canvas (uNID + Duo) una vez; JARVIS guarda la sesión. Úsalo para 'conecta Canvas'.", {}),
    ("correo", "Lee correos (personal y de la universidad): no leídos o buscando un texto.",
     {"cuenta": (S, "personal/universidad, opcional"), "buscar": (S, "Texto a buscar, opcional"),
      "solo_no_leidos": ("boolean", "Solo no leídos (por defecto sí)")}, []),
    ("enviar_correo", "Envía un correo. Confirma destinatario y texto con el usuario antes.",
     {"para": (S, "Email destino"), "asunto": (S, "Asunto"), "cuerpo": (S, "Texto"), "cuenta": (S, "personal/universidad")},
     ["para", "asunto", "cuerpo"]),
    ("abrir_aplicacion", "Abre un programa o app de Windows.", {"nombre": (S, "Nombre")}),
    ("cerrar_aplicacion", "Cierra un programa.", {"nombre": (S, "Nombre")}),
    ("abrir_web", "Abre una URL.", {"url": (S, "URL")}),
    ("buscar_en_internet", "Busca en Google o YouTube y lo abre.", {"consulta": (S, "Qué buscar"), "sitio": (S, "google/youtube")}, ["consulta"]),
    ("investigar_web", "Busca en internet y lee las mejores páginas para investigar algo (noticias, precios, cómo hacer algo, datos actuales). Puedes encadenar varias búsquedas.",
     {"consulta": (S, "Qué investigar"), "paginas": ("integer", "Páginas a leer (1-4)")}, ["consulta"]),
    ("leer_pagina", "Lee el texto de una página web.", {"url": (S, "URL")}),
    ("consultar_wikipedia", "Resumen de Wikipedia (español).", {"tema": (S, "Tema")}),
    ("clima", "Clima actual y pronóstico.", {"ciudad": (S, "Ciudad")}),
    ("ver_pantalla", "Tus OJOS: mira la pantalla (aunque el usuario esté en otra ventana). Úsalo cuando diga 'esto', 'lo que estoy viendo', 'mi pantalla', 'este error', etc.", {"pregunta": (S, "Qué mirar")}),
    ("delegar_a_claude", "Encarga a Claude (Claude Code, el plan del usuario) una tarea compleja o larga que haga él mismo en el PC: programar, crear o editar documentos y archivos, investigaciones profundas, automatizaciones. Corre en segundo plano y avisa al terminar.",
     {"tarea": (S, "Tarea completa y detallada"), "carpeta": (S, "Carpeta de trabajo opcional")}, ["tarea"]),
    ("preguntar_a_claude", "Abre claude.ai en el navegador con una pregunta (solo si pide verlo él mismo).", {"pregunta": (S, "Pregunta")}),
    ("ejecutar_powershell", "Ejecuta PowerShell. Para cualquier tarea del sistema sin herramienta propia.", {"comando": (S, "Comando")}),
    ("ejecutar_python", "Ejecuta código Python y devuelve lo impreso.", {"codigo": (S, "Código")}),
    ("controlar_volumen", "Volumen del PC.", {"accion": (S, "subir/bajar/silenciar/fijar"), "nivel": ("integer", "0-100")}, ["accion"]),
    ("poner_musica", "Pone música de YouTube en segundo plano dentro de JARVIS (sin abrir ventanas). varias=true para una mezcla/cola.",
     {"busqueda": (S, "Canción, artista o género"), "varias": ("boolean", "Varias canciones")}, ["busqueda"]),
    ("controlar_musica", "Controla la música de JARVIS.", {"accion": (S, "pausar/reanudar/siguiente/detener/volumen"), "nivel": ("integer", "Volumen 0-100")}, ["accion"]),
    ("apple_music", "Reproduce una PLAYLIST del usuario en su app de Apple Music, por nombre (p. ej. 'General', 'Marvin Gaye').", {"busqueda": (S, "Nombre exacto de la playlist")}),
    ("controlar_multimedia", "Teclas multimedia de Windows (Spotify, Apple Music…).", {"accion": (S, "pausar/siguiente/anterior")}),
    ("escribir_texto", "Escribe texto en la ventana activa.", {"texto": (S, "Texto")}),
    ("presionar_teclas", "Pulsa teclas, p. ej. 'ctrl+c', 'win+d'.", {"teclas": (S, "Teclas con +")}),
    ("captura_pantalla", "Guarda una captura en Imágenes.", {}),
    ("info_sistema", "CPU, RAM, batería, disco.", {}),
    ("buscar_archivos", "Busca archivos por nombre.", {"nombre": (S, "Nombre"), "carpeta": (S, "Carpeta")}, ["nombre"]),
    ("listar_carpeta", "Lista el contenido de una carpeta.", {"ruta": (S, "Ruta")}),
    ("abrir_archivo", "Abre un archivo o carpeta.", {"ruta": (S, "Ruta")}),
    ("leer_archivo", "Lee un archivo de texto.", {"ruta": (S, "Ruta")}),
    ("escribir_archivo", "Crea o sobrescribe un archivo de texto.", {"ruta": (S, "Ruta"), "contenido": (S, "Contenido")}),
    ("energia", "bloquear/suspender/apagar/reiniciar/cancelar. Confirma antes de apagar.", {"accion": (S, "Acción")}),
    ("crear_recordatorio", "Recordatorio/alarma: avisa en PC y teléfono; puede llamar.",
     {"mensaje": (S, "Qué"), "en_minutos": ("number", "Minutos"), "fecha_hora": (S, "'YYYY-MM-DD HH:MM' o 'HH:MM'"),
      "llamar": ("boolean", "Llamar al vencer"), "repetir_diario": ("boolean", "Diario")}, ["mensaje"]),
    ("listar_recordatorios", "Recordatorios pendientes.", {}),
    ("borrar_recordatorio", "Borra recordatorios.", {"texto": (S, "Id o texto")}),
    ("recordar_dato", "Guarda un dato duradero del usuario.", {"dato": (S, "Dato")}),
    ("olvidar_dato", "Borra un dato de memoria.", {"texto": (S, "Texto")}),
    ("notificar_telefono", "Notificación push al teléfono.", {"mensaje": (S, "Mensaje")}),
    ("llamar_telefono", "Llama al celular del usuario y le dice un mensaje (número real con Twilio, o Telegram).", {"mensaje": (S, "Mensaje")}),
    ("mensaje_telegram", "Mensaje de Telegram al usuario.", {"mensaje": (S, "Mensaje")}),
    ("crear_habilidad", "Programa e instala una habilidad nueva en Python cuando no tengas herramienta para algo. El código define ejecutar(**kwargs) -> str.",
     {"nombre": (S, "nombre_corto"), "descripcion": (S, "Qué hace y qué argumentos recibe"), "codigo": (S, "Código Python completo")}),
    ("usar_habilidad", "Ejecuta una habilidad instalada.", {"nombre": (S, "Nombre"), "argumentos": ("object", "Argumentos")}, ["nombre"]),
    ("instalar_paquete", "Instala un paquete de Python (pip) que necesite una habilidad.", {"paquete": (S, "Paquete")}),
    ("cambiar_voz", "Cambia la voz de JARVIS. Para la voz más humana (ElevenLabs) usa pedir_dato con elevenlabs_api_key.", {"voz": (S, "Voz de edge-tts, p. ej. es-MX-JorgeNeural, en-US-AndrewMultilingualNeural"), "idioma": (S, "es/en")}, ["voz"]),
]


# Categorías: a cada pedido solo se envían las herramientas relevantes (ahorra tokens y límites gratis)
NUCLEO = {"pillgo_videos", "pillgo_estado", "pillgo_parar", "diagnostico", "delegar_a_claude", "pedir_dato", "mostrar_panel", "pedir_texto", "marcar_hecho", "ver_pantalla", "ejecutar_powershell", "ejecutar_python", "abrir_aplicacion", "recordar_dato",
          "crear_habilidad", "usar_habilidad", "investigar_web", "crear_recordatorio", "resumen_del_dia"}
CATEGORIAS = {
    "agenda": (r"tengo|pendiente|tarea|deber|agenda|calendario|horario|evento|record|alarma|todoist|hoy|mañana|semana|"
               r"cita|reuni|examen|quiz|homework|schedule|task|remind|plan|organiza|proyecto|hecho|termin|complet",
               {"resumen_del_dia", "calendario", "agregar_evento", "todoist", "todoist_agregar", "todoist_completar",
                "pendientes", "pendiente_agregar", "marcar_hecho", "crear_recordatorio", "listar_recordatorios",
                "borrar_recordatorio"}),
    "correo": (r"correo|mail|inbox|bandeja|mensaje de|escrib.* a |responde", {"correo", "enviar_correo"}),
    "canvas": (r"canvas|curso|clase|profe|nota|calificaci|entrega|assignment|anuncio|universidad|homework|quiz|tarea",
               {"canvas", "canvas_abrir", "canvas_iniciar_sesion"}),
    "musica": (r"m[uú]sica|canci|pon |reproduc|playlist|youtube|apple|spotify|pausa|reanuda|volumen|sube|baja|"
               r"siguiente|anterior|play|song|music|det[eé]n|calla|silencio",
               {"poner_musica", "controlar_musica", "apple_music", "controlar_multimedia", "controlar_volumen"}),
    "pc": (r"abre|cierra|archivo|carpeta|documento|powershell|ejecuta|pantalla|captura|tecla|escribe|copia|pega|apaga|"
           r"bloquea|reinicia|suspende|sistema|bater|ram|cpu|disco|instala|programa|app|ventana|descarga|open|close|file",
           {"cerrar_aplicacion", "escribir_texto", "presionar_teclas", "captura_pantalla", "info_sistema",
            "buscar_archivos", "listar_carpeta", "abrir_archivo", "leer_archivo", "escribir_archivo", "energia",
            "instalar_paquete", "controlar_volumen"}),
    "web": (r"busca|investiga|internet|web|google|wikipedia|qu[ié]n es|qu[eé] es|clima|tiempo|noticia|precio|p[aá]gina|"
            r"search|research|weather|news|claude|link|url",
            {"leer_pagina", "consultar_wikipedia", "clima", "abrir_web", "buscar_en_internet", "preguntar_a_claude"}),
    "shopify": (r"shopify|tienda|ezma|vend|venta|pedido|orden|stock|inventario|producto|cliente",
                {"shopify_ventas", "shopify_pedidos", "shopify_inventario"}),
    "telefono": (r"tel[eé]fono|celular|iphone|llam|notifica|telegram|avísame|avisame|phone|call|bot|casa|salgo|presencia",
                 {"notificar_telefono", "llamar_telefono", "mensaje_telegram"}),
    "memoria": (r"olvida|memoria|voz|habla m[aá]s|habilidad|aprende|forget|voice",
                {"olvidar_dato", "cambiar_voz", "usar_habilidad", "crear_habilidad"}),
}


def _prop(tipo, desc):
    if tipo == "array":
        return {"type": "array", "description": desc, "items": {"type": "object", "properties": {
            "titulo": {"type": "string"}, "puntos": {"type": "array", "items": {"type": "string"}}}}}
    return {"type": tipo, "description": desc}


def herramientas_para(texto, extra=()):
    t = texto.lower()
    nombres = set(NUCLEO) | set(extra)
    for patron, grupo in CATEGORIAS.values():
        if re.search(patron, t):
            nombres |= grupo
    return nombres


class Herramientas:
    def __init__(self, memoria, recordatorios, telefono, cfg=None, agenda=None, habilidades=None, voz=None):
        self.memoria, self.recordatorios, self.telefono = memoria, recordatorios, telefono
        self.cfg = cfg or {}
        self.agenda = agenda or {}
        self.habilidades = habilidades
        self.voz = voz
        self._apps = None
        self.on_resultado = lambda nombre, args, resultado: None
        self.musica = None
        self.claude = None
        self.pillgo = None

    def esquemas(self, solo=None):
        out = []
        for spec in SPECS:
            nombre, desc, props = spec[:3]
            if solo is not None and nombre not in solo:
                continue
            req = spec[3] if len(spec) > 3 else list(props)
            out.append({"type": "function", "function": {
                "name": nombre, "description": desc,
                "parameters": {"type": "object",
                               "properties": {k: _prop(t, d) for k, (t, d) in props.items()},
                               "required": req}}})
        return out

    def ejecutar(self, nombre, args):
        fn = getattr(self, nombre, None)
        if not fn or nombre.startswith("_") or nombre not in {s[0] for s in SPECS}:
            return f"Herramienta desconocida: {nombre}"
        args = {k: v for k, v in (args or {}).items() if v is not None}
        try:
            resultado = str(fn(**args))[:7000]
            try:
                self.on_resultado(nombre, args, resultado)
            except Exception:
                pass
            return resultado
        except Exception as e:
            log.exception("Error en herramienta %s", nombre)
            return f"Error: {e}"

    # ---------- Aplicaciones ----------
    def _lista_apps(self):
        if self._apps is None:
            try:
                datos = json.loads(_ps("Get-StartApps | Select-Object Name, AppID | ConvertTo-Json -Compress") or "[]")
                self._apps = {a["Name"].lower(): a["AppID"] for a in (datos if isinstance(datos, list) else [datos])}
            except Exception:
                self._apps = {}
        return self._apps

    def abrir_aplicacion(self, nombre):
        n = nombre.lower().strip()
        especiales = {"configuración": "ms-settings:", "configuracion": "ms-settings:", "ajustes": "ms-settings:",
                      "explorador": "explorer", "explorador de archivos": "explorer", "administrador de tareas": "taskmgr",
                      "cmd": "cmd", "símbolo del sistema": "cmd", "terminal": "wt", "panel de control": "control"}
        if n in especiales:
            os.startfile(especiales[n]) if ":" in especiales[n] else subprocess.Popen(especiales[n], shell=True)
            return f"Abriendo {nombre}."
        apps = self._lista_apps()
        candidato = next((k for k in apps if k == n), None) or next((k for k in apps if n in k), None)
        if not candidato:
            parecidos = difflib.get_close_matches(n, apps.keys(), n=1, cutoff=0.6)
            candidato = parecidos[0] if parecidos else None
        if candidato:
            subprocess.Popen(["explorer.exe", f"shell:AppsFolder\\{apps[candidato]}"])
            return f"Abriendo {candidato}."
        try:
            os.startfile(n)
            return f"Abriendo {nombre}."
        except OSError:
            return f"No encontré la aplicación '{nombre}'."

    def cerrar_aplicacion(self, nombre):
        import psutil
        n = nombre.lower().strip()
        objetivo = ALIAS_PROCESOS.get(n, n)
        cerrados = 0
        for p in psutil.process_iter(["name"]):
            pn = (p.info["name"] or "").lower()
            if pn == objetivo or (len(n) > 2 and n.replace(" ", "") in pn):
                try:
                    p.terminate()
                    cerrados += 1
                except Exception:
                    pass
        return f"Cerré {cerrados} proceso(s) de {nombre}." if cerrados else f"{nombre} no está abierto."

    # ---------- Web ----------
    def abrir_web(self, url):
        if not url.startswith("http"):
            url = "https://" + url
        webbrowser.open(url)
        return f"Abriendo {url}."

    def buscar_en_internet(self, consulta, sitio="google"):
        q = urllib.parse.quote_plus(consulta)
        url = (f"https://www.youtube.com/results?search_query={q}" if "you" in (sitio or "").lower()
               else f"https://www.google.com/search?q={q}")
        webbrowser.open(url)
        return f"Buscando '{consulta}'."

    def consultar_wikipedia(self, tema):
        h = {"User-Agent": "JARVIS-asistente/1.0"}
        r = requests.get("https://es.wikipedia.org/w/api.php", headers=h, timeout=10, params={
            "action": "query", "list": "search", "srsearch": tema, "format": "json", "srlimit": 1})
        res = r.json()["query"]["search"]
        if not res:
            return "Sin resultados en Wikipedia."
        titulo = res[0]["title"].replace(" ", "_")
        r = requests.get(f"https://es.wikipedia.org/api/rest_v1/page/summary/{urllib.parse.quote(titulo)}", headers=h, timeout=10)
        return r.json().get("extract", "Sin resumen.")

    def clima(self, ciudad):
        g = requests.get("https://geocoding-api.open-meteo.com/v1/search",
                         params={"name": ciudad, "count": 1, "language": "es"}, timeout=10).json()
        if not g.get("results"):
            return f"No encontré la ciudad {ciudad}."
        lugar = g["results"][0]
        c = requests.get("https://api.open-meteo.com/v1/forecast", timeout=10, params={
            "latitude": lugar["latitude"], "longitude": lugar["longitude"], "timezone": "auto", "forecast_days": 2,
            "current": "temperature_2m,apparent_temperature,relative_humidity_2m,weather_code,wind_speed_10m",
            "daily": "temperature_2m_max,temperature_2m_min,precipitation_probability_max,weather_code"}).json()
        a, d = c["current"], c["daily"]
        return (f"{lugar['name']}, {lugar.get('country', '')}: ahora {a['temperature_2m']}°C "
                f"(sensación {a['apparent_temperature']}°C), {CLIMA.get(a['weather_code'], 'variable')}, "
                f"humedad {a['relative_humidity_2m']}%, viento {a['wind_speed_10m']} km/h. "
                f"Hoy: {d['temperature_2m_min'][0]}-{d['temperature_2m_max'][0]}°C, lluvia {d['precipitation_probability_max'][0]}%. "
                f"Mañana: {d['temperature_2m_min'][1]}-{d['temperature_2m_max'][1]}°C, "
                f"{CLIMA.get(d['weather_code'][1], 'variable')}, lluvia {d['precipitation_probability_max'][1]}%.")

    # ---------- Sistema ----------
    def ejecutar_powershell(self, comando):
        if any(re.search(p, comando, re.I) for p in BLOQUEADOS):
            return "Comando bloqueado por seguridad (podría destruir el sistema)."
        return _ps(comando) or "Comando ejecutado (sin salida)."

    def controlar_volumen(self, accion, nivel=None):
        import pyautogui
        accion = accion.lower()
        if accion.startswith("silen") or accion == "mute":
            pyautogui.press("volumemute")
            return "Silencio activado/desactivado."
        if accion == "fijar" and nivel is not None:
            nivel = max(0, min(100, int(nivel)))
            try:
                from pycaw.pycaw import AudioUtilities
                altavoz = AudioUtilities.GetSpeakers()
                try:
                    vol = altavoz.EndpointVolume
                except AttributeError:
                    from ctypes import POINTER, cast
                    from comtypes import CLSCTX_ALL
                    from pycaw.pycaw import IAudioEndpointVolume
                    vol = cast(altavoz.Activate(IAudioEndpointVolume._iid_, CLSCTX_ALL, None), POINTER(IAudioEndpointVolume))
                vol.SetMasterVolumeLevelScalar(nivel / 100, None)
            except Exception:
                pyautogui.press("volumedown", presses=50)
                pyautogui.press("volumeup", presses=nivel // 2)
            return f"Volumen al {nivel}%."
        tecla = "volumeup" if accion.startswith("sub") else "volumedown"
        pyautogui.press(tecla, presses=5)
        return f"Volumen {'subido' if tecla == 'volumeup' else 'bajado'}."

    def controlar_multimedia(self, accion):
        import pyautogui
        tecla = {"pausar": "playpause", "reproducir": "playpause", "siguiente": "nexttrack",
                 "anterior": "prevtrack"}.get(accion.lower(), "playpause")
        pyautogui.press(tecla)
        return "Hecho."

    def escribir_texto(self, texto):
        import pyautogui
        import pyperclip
        pyperclip.copy(texto)
        pyautogui.hotkey("ctrl", "v")
        return "Texto escrito."

    def presionar_teclas(self, teclas):
        import pyautogui
        mapa = {"windows": "win", "control": "ctrl", "intro": "enter", "escape": "esc", "suprimir": "delete"}
        partes = [mapa.get(t.strip().lower(), t.strip().lower()) for t in teclas.split("+")]
        pyautogui.hotkey(*partes)
        return f"Pulsé {teclas}."

    def captura_pantalla(self):
        import pyautogui
        carpeta = os.path.join(os.path.expanduser("~"), "Pictures", "JARVIS")
        os.makedirs(carpeta, exist_ok=True)
        ruta = os.path.join(carpeta, dt.datetime.now().strftime("captura_%Y%m%d_%H%M%S.png"))
        pyautogui.screenshot(ruta)
        return f"Captura guardada en {ruta}."

    def info_sistema(self):
        import psutil
        bat = psutil.sensors_battery()
        disco = psutil.disk_usage(os.path.expanduser("~"))
        procs = sorted(psutil.process_iter(["name", "memory_percent"]),
                       key=lambda p: p.info["memory_percent"] or 0, reverse=True)[:5]
        return (f"CPU {psutil.cpu_percent(interval=0.5)}%, RAM {psutil.virtual_memory().percent}%, "
                f"disco {disco.percent}% usado ({disco.free // 2**30} GB libres)"
                + (f", batería {bat.percent:.0f}%{' cargando' if bat.power_plugged else ''}" if bat else "")
                + ". Más memoria: " + ", ".join(p.info["name"] for p in procs) + ".")

    def buscar_archivos(self, nombre, carpeta=None):
        base = carpeta or os.path.expanduser("~")
        hallados = []
        for raiz, dirs, archivos in os.walk(base):
            dirs[:] = [d for d in dirs if not d.startswith(".") and d not in ("AppData", "node_modules", "$Recycle.Bin")]
            for a in archivos:
                if nombre.lower() in a.lower():
                    hallados.append(os.path.join(raiz, a))
                    if len(hallados) >= 15:
                        return "\n".join(hallados)
        return "\n".join(hallados) or "No encontré archivos con ese nombre."

    def abrir_archivo(self, ruta):
        os.startfile(os.path.expandvars(os.path.expanduser(ruta)))
        return f"Abriendo {ruta}."

    def leer_archivo(self, ruta):
        with open(os.path.expandvars(os.path.expanduser(ruta)), encoding="utf-8", errors="replace") as f:
            return f.read(3500)

    def energia(self, accion):
        accion = accion.lower()
        cmds = {"bloquear": "rundll32.exe user32.dll,LockWorkStation",
                "suspender": "rundll32.exe powrprof.dll,SetSuspendState 0,1,0",
                "apagar": "shutdown /s /t 30", "reiniciar": "shutdown /r /t 30", "cancelar": "shutdown /a"}
        if accion not in cmds:
            return "Acción no válida."
        subprocess.Popen(cmds[accion], shell=True, creationflags=SIN_VENTANA)
        return {"apagar": "El equipo se apagará en 30 segundos.", "reiniciar": "Reinicio en 30 segundos.",
                "cancelar": "Apagado cancelado."}.get(accion, "Hecho.")

    # ---------- Recordatorios, memoria y teléfono ----------
    def crear_recordatorio(self, mensaje, en_minutos=None, fecha_hora=None, llamar=False, repetir_diario=False):
        if en_minutos:
            cuando = dt.datetime.now() + dt.timedelta(minutes=float(en_minutos))
        elif fecha_hora:
            cuando = _fecha(fecha_hora)
        else:
            return "Necesito saber cuándo: en_minutos o fecha_hora."
        r = self.recordatorios.crear(mensaje, cuando, llamar, repetir_diario)
        return f"Recordatorio {r['id']} para {r['cuando']}" + (" con llamada." if llamar else ".")

    def listar_recordatorios(self):
        items = self.recordatorios.listar()
        return "\n".join(f"[{i['id']}] {i['cuando']}: {i['mensaje']}" + (" (llamada)" if i["llamar"] else "")
                         + (" (diario)" if i["repetir_diario"] else "") for i in items) or "No hay recordatorios."

    def borrar_recordatorio(self, texto):
        return f"Borrados: {self.recordatorios.borrar(texto)}."

    def recordar_dato(self, dato):
        self.memoria.agregar(dato)
        return "Guardado en memoria."

    def olvidar_dato(self, texto):
        return f"Olvidados: {self.memoria.olvidar(texto)}."

    def _bot_listo(self):
        bot = getattr(self, "bot", None)
        return bot if bot and bot.activo and bot.cfg.get("chat_id") else None

    def notificar_telefono(self, mensaje):
        bot = self._bot_listo()
        if bot and bot.enviar(mensaje):
            return "Mensaje enviado a su iPhone por Telegram."
        if self.telefono.tema:
            return self.telefono.notificar(mensaje)
        return self._sin_bot()

    def mensaje_telegram(self, mensaje):
        return self.notificar_telefono(mensaje)

    def _sin_bot(self):
        bot = getattr(self, "bot", None)
        if bot and bot.activo and bot.codigo:
            return (f"Su iPhone aún no está vinculado: envíe el código {bot.codigo} a su bot de Telegram "
                    "y vuelva a pedírmelo.")
        return "Su iPhone no está conectado. Dígame «conecta mi iPhone» para configurarlo."

    def llamar_telefono(self, mensaje):
        try:
            r = self.telefono.llamar(mensaje)
        except Exception as e:
            log.warning("Llamada falló: %s", e)
            r = "No pude completar la llamada."
        bot = self._bot_listo()
        if bot:  # copia en audio y texto por si la llamada no entra
            bot.enviar("📞 " + mensaje)
            threading.Thread(target=bot.enviar_voz, args=(mensaje,), daemon=True).start()
        return r

    # ---------- Agenda ----------
    def resumen_del_dia(self, dias=1):
        dias = max(1, int(dias))
        partes = []
        cal, tod, pen = self.agenda.get("calendario"), self.agenda.get("todoist"), self.agenda.get("pendientes")
        for titulo, fn in (("CALENDARIO", lambda: cal.texto(dias)),
                           ("CORREOS NO LEÍDOS", lambda: self.agenda["correo"].resumen(maximo=4)
                            if self.agenda.get("correo") and self.agenda["correo"]._elegir() else "(sin correo conectado)"),
                           ("TODOIST", lambda: tod.texto("overdue | today" if dias == 1 else f"overdue | {dias} days")),
                           ("PENDIENTES PERSONALES", lambda: pen.texto(solo_urgentes=dias <= 2)),
                           ("RECORDATORIOS", self.listar_recordatorios)):
            try:
                r = fn()
                if "no está conectado" in r or "sin correo conectado" in r:
                    continue
                partes.append(f"{titulo}:\n{r}")
            except Exception as e:
                partes.append(f"{titulo}: error ({e})")
        return "\n\n".join(partes)

    def calendario(self, dias=1):
        return self.agenda["calendario"].texto(max(1, int(dias)))

    def agregar_evento(self, titulo, fecha_hora, duracion_min=60):
        from .integraciones import Calendario
        return Calendario.agregar(titulo, _fecha(fecha_hora), int(duracion_min))

    def _sin_todoist(self):
        if not self.agenda["todoist"].token:
            self.pedir_dato("todoist_token")
            return "Todoist no está conectado: abrí la barra para que pegue su token. Díselo brevemente."
        return None

    def todoist(self, filtro="today | overdue"):
        return self._sin_todoist() or self.agenda["todoist"].texto(filtro)

    def todoist_agregar(self, contenido, fecha=None):
        return self._sin_todoist() or self.agenda["todoist"].agregar(contenido, fecha)

    def todoist_completar(self, texto):
        return self._sin_todoist() or self.agenda["todoist"].completar(texto)

    def pendientes(self, proyecto=None, solo_urgentes=False):
        return self.agenda["pendientes"].texto(proyecto, solo_urgentes)

    def pendiente_agregar(self, texto, proyecto="General", fecha=None, prioridad="media"):
        return self.agenda["pendientes"].agregar(texto, proyecto, fecha, prioridad)

    def marcar_hecho(self, texto):
        """Completa la tarea en Todoist (si está conectado) y en los pendientes personales."""
        hechos = []
        tod = self.agenda.get("todoist")
        if tod and tod.token:
            try:
                r = tod.completar(texto)
                if not r.startswith("No encontr"):
                    hechos.append(r)
            except Exception as e:
                log.warning("Todoist completar falló: %s", e)
        r = self.agenda["pendientes"].completar(texto)
        if not r.startswith("No encontr"):
            hechos.append(r)
        return " ".join(hechos) or f"No encontré ninguna tarea con '{texto}'."

    def pedir_texto(self, motivo="Escríbeme"):
        if getattr(self, "ui", None):
            self.ui("pedirTexto", motivo)
        return "Abrí una caja de texto para que el usuario escriba. Dile brevemente qué necesitas."

    # ---------- Visión, Claude, archivos ----------
    def ver_pantalla(self, pregunta="¿Qué hay en la pantalla?"):
        import base64
        import io

        import pyautogui
        from openai import OpenAI

        from . import config
        img = pyautogui.screenshot()
        img.thumbnail((1600, 1600))
        buf = io.BytesIO()
        img.convert("RGB").save(buf, "JPEG", quality=80)
        b64 = base64.b64encode(buf.getvalue()).decode()
        mensaje = [{"role": "user", "content": [
            {"type": "text", "text": f"Eres JARVIS mirando la pantalla de tu jefe. {pregunta} Responde en español, "
                                     "breve (2-4 frases), concreto y útil; si hay un error dile cómo arreglarlo."},
            {"type": "image_url", "image_url": {"url": f"data:image/jpeg;base64,{b64}"}}]}]
        errores = []
        for prov, modelo in (("gemini", "gemini-flash-lite-latest"), ("gemini", "gemini-flash-latest"),
                             ("groq", "meta-llama/llama-4-scout-17b-16e-instruct")):
            clave = config.clave(self.cfg, prov)
            if not clave:
                continue
            try:
                c = OpenAI(api_key=clave, base_url=config.URLS_PROVEEDOR[prov], timeout=40, max_retries=0)
                r = c.chat.completions.create(model=modelo, messages=mensaje, max_tokens=400)
                return r.choices[0].message.content
            except Exception as e:
                errores.append(f"{prov}: {e}")
        # respaldo: Claude Code (plan del usuario) mira la captura guardada en disco
        try:
            import subprocess
            import sys
            from .claude_code import ruta_claude
            exe = ruta_claude()
            if exe:
                ruta = os.path.join(config.DATOS, "pantalla.jpg")
                img.convert("RGB").save(ruta, "JPEG", quality=80)
                r = subprocess.run([exe, "-p", f"Lee la imagen {ruta} (captura de mi pantalla). {pregunta} "
                                    "Responde como JARVIS en español, 2-4 frases.", "--allowedTools", "Read",
                                    "--output-format", "text"], capture_output=True, text=True, timeout=120,
                                   encoding="utf-8", errors="replace",
                                   creationflags=0x08000000 if sys.platform == "win32" else 0)
                if (r.stdout or "").strip():
                    return r.stdout.strip()
        except Exception as e:
            errores.append(f"claude: {e}")
        log.warning("Visión falló: %s", " | ".join(errores))
        return "No pude analizar la pantalla ahora mismo; las IA con visión están sin cupo."

    def preguntar_a_claude(self, pregunta):
        webbrowser.open("https://claude.ai/new?q=" + urllib.parse.quote(pregunta))
        return "Abrí Claude con tu pregunta."

    def listar_carpeta(self, ruta="~"):
        ruta = os.path.expandvars(os.path.expanduser(ruta))
        items = sorted(os.listdir(ruta))[:80]
        return "\n".join(("[carpeta] " if os.path.isdir(os.path.join(ruta, i)) else "") + i for i in items) or "Vacía."

    def escribir_archivo(self, ruta, contenido):
        ruta = os.path.expandvars(os.path.expanduser(ruta))
        os.makedirs(os.path.dirname(ruta) or ".", exist_ok=True)
        with open(ruta, "w", encoding="utf-8") as f:
            f.write(contenido)
        return f"Archivo guardado: {ruta}"

    # ---------- Autoaprendizaje ----------
    def crear_habilidad(self, nombre, descripcion, codigo):
        return self.habilidades.crear(nombre, descripcion, codigo)

    def usar_habilidad(self, nombre, argumentos=None):
        if isinstance(argumentos, str):
            try:
                argumentos = json.loads(argumentos or "{}")
            except json.JSONDecodeError:
                argumentos = {}
        return self.habilidades.usar(nombre, argumentos)

    def instalar_paquete(self, paquete):
        return self.habilidades.instalar_paquete(paquete)

    def ejecutar_python(self, codigo):
        return self.habilidades.ejecutar_python(codigo)

    def cambiar_voz(self, voz, idioma="es"):
        clave = "voz_en" if idioma == "en" else "voz"
        self.cfg["voz"][clave] = voz
        from . import config
        config.guardar_valor(["voz", clave], voz)
        return f"Voz cambiada a {voz}."

    # ---------- Correo ----------
    def correo(self, cuenta=None, buscar=None, solo_no_leidos=True):
        if not self.agenda["correo"]._elegir():
            self.pedir_dato("correo_email")
            return "El correo no está conectado: abrí la barra para que escriba su correo. Díselo brevemente."
        return self.agenda["correo"].resumen(cuenta, solo_no_leidos, buscar)

    def enviar_correo(self, para, asunto, cuerpo, cuenta=None):
        return self.agenda["correo"].enviar(para, asunto, cuerpo, cuenta)

    # ---------- Música ----------
    def poner_musica(self, busqueda, varias=False):
        return self.musica.reproducir(busqueda, varias)

    def controlar_musica(self, accion, nivel=None):
        return self.musica.control(accion, nivel)

    def apple_music(self, busqueda):
        from .apple_music import reproducir_playlist
        r = reproducir_playlist(busqueda)
        self.apple_activa = r.startswith("Reproduciendo")
        if self.apple_activa and self.musica:
            try:
                self.musica.controlar("pausar")  # que no suenen dos músicas a la vez
            except Exception:
                pass
        return r

    # ---------- Investigación web ----------
    def investigar_web(self, consulta, paginas=3):
        try:
            from ddgs import DDGS
        except ImportError:
            from duckduckgo_search import DDGS
        res = list(DDGS().text(consulta, max_results=8))
        if not res:
            return "Sin resultados."
        salida = ["RESULTADOS:"] + [f"- {r['title']}: {r['body']} ({r['href']})" for r in res[:8]]
        for r in res[:max(0, min(4, int(paginas)))]:
            try:
                salida.append(f"\nPÁGINA {r['href']}:\n" + _texto_pagina(r["href"], 1800))
            except Exception:
                pass
        return "\n".join(salida)[:7000]

    def leer_pagina(self, url):
        return _texto_pagina(url, 5000)


    # ---------- Configuración desde la barra y paneles ----------
    def pedir_dato(self, campo, motivo=None):
        textos = {"todoist_token": "Pega tu token de API de Todoist",
                  "google_calendar_ics": "Pega la dirección secreta iCal de Google Calendar",
                  "gemini_api_key": "Pega tu clave de Gemini (aistudio.google.com/apikey)",
                  "claude_api_key": "Pega tu clave de API de Claude (console.anthropic.com)",
                  "groq_api_key": "Pega tu clave de Groq",
                  "elevenlabs_api_key": "Pega tu clave de ElevenLabs (elevenlabs.io → API Keys)",
                  "telegram_bot_token": "Pega el token de tu bot de Telegram (te lo da @BotFather)",
                  "telegram_usuario": "Escribe tu @usuario de Telegram (para las llamadas)",
                  "telegram_chat_id": "Escribe tu Id de Telegram (te lo da @userinfobot)",
                  "canvas_token": "Pega tu token de Canvas (Cuenta → Configuración → Nuevo token de acceso)",
                  "correo_email": "Escribe tu correo personal (Gmail o iCloud)",
                  "shopify": "Pega tu tienda y token juntos, ej: ezmashop.myshopify.com shpat_xxxx",
                  "telefono_mac": "Escribe la Dirección Wi-Fi de tu iPhone (Ajustes → Wi-Fi → ⓘ)",
                  "twilio_sid": "Pega tu Account SID de Twilio (empieza con AC)",
                  "twilio_token": "Pega tu Auth Token de Twilio",
                  "twilio_numero": "Escribe el número que te dio Twilio (ej. +18015551234)",
                  "mi_numero": "Escribe TU número de celular con código de país (ej. +18015550000)",
                  "correo_app_password": "Pega la contraseña de aplicación de tu correo"}
        if campo not in textos:
            return f"Campo no válido. Opciones: {', '.join(textos)}."
        if getattr(self, "ui", None):
            self.ui("pedirTexto", motivo or textos[campo], campo)
        return "Barra abierta: el usuario lo escribirá y se guardará automáticamente. Díselo en una frase."

    def mostrar_panel(self, titulo, secciones):
        sec = []
        for s in secciones or []:
            if isinstance(s, dict):
                puntos = s.get("puntos") or s.get("items") or []
                sec.append({"t": s.get("titulo", ""), "tono": "info",
                            "items": [{"x": str(p), "sub": "", "tags": []} for p in puntos]})
            else:
                sec.append({"t": "", "tono": "info", "items": [{"x": str(s), "sub": "", "tags": []}]})
        if getattr(self, "ui", None):
            self.ui("panel", titulo, sec)
        return "Mostrado en el panel."


    def _shop(self):
        sh = self.agenda.get("shopify")
        if not sh or not sh.listo:
            self.pedir_dato("shopify")
            return None
        return sh

    def shopify_ventas(self, dias=1):
        sh = self._shop()
        return sh.ventas(dias) if sh else "Shopify no está conectado: abrí la barra para que pegue tienda y token."

    def shopify_pedidos(self, cantidad=5):
        sh = self._shop()
        return sh.pedidos(cantidad) if sh else "Shopify no está conectado: abrí la barra."

    def shopify_inventario(self, busqueda=""):
        sh = self._shop()
        return sh.inventario(busqueda) if sh else "Shopify no está conectado: abrí la barra."

    def pillgo_videos(self):
        return self.pillgo.iniciar()

    def pillgo_estado(self):
        return self.pillgo.resumen()

    def pillgo_parar(self):
        return self.pillgo.parar()

    def diagnostico(self):
        from . import diagnostico
        return diagnostico.revisar(self.cfg, self)

    def canvas(self, que="pendientes"):
        from .canvas import SesionExpirada
        cv = self.agenda.get("canvas")
        if not cv or not cv.conectado:
            return self.canvas_iniciar_sesion()
        try:
            return cv.texto(que)
        except SesionExpirada:
            return self.canvas_iniciar_sesion()

    def canvas_iniciar_sesion(self):
        import threading
        cv = self.agenda["canvas"]

        def abrir():
            try:
                ok = cv.iniciar_sesion(visible=True)
            except Exception as e:
                log.warning("Login Canvas: %s", e)
                ok = False
            if getattr(self, "al_conectar_canvas", None):
                self.al_conectar_canvas(ok)

        threading.Thread(target=abrir, daemon=True).start()
        return ("Abrí una ventana de Canvas: el usuario debe iniciar sesión con su uNID y aprobar Duo; "
                "la ventana se cierra sola al terminar. Díselo en una frase.")

    def canvas_abrir(self, busqueda=None):
        return self.agenda["canvas"].abrir(busqueda)

    def delegar_a_claude(self, tarea, carpeta=None):
        return self.claude.delegar(tarea, carpeta)


    def canvas(self, que="pendientes"):
        from .canvas import SesionExpirada
        cv = self.agenda.get("canvas")
        if not cv or not cv.conectado:
            return self.canvas_iniciar_sesion()
        try:
            return cv.texto(que)
        except SesionExpirada:
            return self.canvas_iniciar_sesion()

    def canvas_iniciar_sesion(self):
        import threading
        cv = self.agenda["canvas"]

        def abrir():
            try:
                ok = cv.iniciar_sesion(visible=True)
            except Exception as e:
                log.warning("Login Canvas: %s", e)
                ok = False
            if getattr(self, "al_conectar_canvas", None):
                self.al_conectar_canvas(ok)

        threading.Thread(target=abrir, daemon=True).start()
        return ("Abrí una ventana de Canvas: el usuario debe iniciar sesión con su uNID y aprobar Duo; "
                "la ventana se cierra sola al terminar. Díselo en una frase.")

    def canvas_abrir(self, busqueda=None):
        return self.agenda["canvas"].abrir(busqueda)

    def delegar_a_claude(self, tarea, carpeta=None):
        return self.claude.delegar(tarea, carpeta)


def _texto_pagina(url, limite):
    from bs4 import BeautifulSoup
    r = requests.get(url, timeout=12, headers={"User-Agent": "Mozilla/5.0 JARVIS"})
    sopa = BeautifulSoup(r.text, "html.parser")
    for t in sopa(["script", "style", "nav", "footer", "header", "aside", "form"]):
        t.decompose()
    return " ".join(sopa.get_text(" ").split())[:limite]

