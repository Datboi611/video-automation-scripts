"""Herramientas que JARVIS puede usar para controlar Windows y el mundo exterior."""
import datetime as dt
import difflib
import json
import logging
import os
import re
import subprocess
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
SPECS = [
    ("abrir_aplicacion", "Abre cualquier programa o app instalada en Windows (Chrome, Spotify, Word, WhatsApp, juegos, configuración...).",
     {"nombre": (S, "Nombre de la aplicación")}),
    ("cerrar_aplicacion", "Cierra un programa abierto.", {"nombre": (S, "Nombre del programa")}),
    ("abrir_web", "Abre una página web o URL en el navegador.", {"url": (S, "URL o dominio")}),
    ("buscar_en_internet", "Busca algo en Google o YouTube y lo abre en el navegador.",
     {"consulta": (S, "Qué buscar"), "sitio": (S, "'google' o 'youtube'")}, ["consulta"]),
    ("consultar_wikipedia", "Obtiene un resumen de Wikipedia en español para responder preguntas de conocimiento.",
     {"tema": (S, "Tema a consultar")}),
    ("clima", "Clima actual y pronóstico de hoy/mañana de una ciudad.", {"ciudad": (S, "Ciudad")}),
    ("ejecutar_powershell", "Ejecuta un comando de PowerShell en el PC y devuelve la salida. Úsalo para cualquier tarea del sistema que no tenga herramienta propia (archivos, carpetas, red, procesos, wifi, etc.).",
     {"comando": (S, "Comando de PowerShell")}),
    ("controlar_volumen", "Sube, baja, silencia o fija el volumen del PC.",
     {"accion": (S, "'subir', 'bajar', 'silenciar', 'fijar'"), "nivel": ("integer", "0-100 si accion es 'fijar'")}, ["accion"]),
    ("controlar_multimedia", "Controla la música/vídeo que suena.",
     {"accion": (S, "'pausar', 'siguiente', 'anterior'")}),
    ("escribir_texto", "Escribe (pega) texto en la ventana activa, como si el usuario lo tecleara.",
     {"texto": (S, "Texto a escribir")}),
    ("presionar_teclas", "Pulsa una tecla o combinación, p. ej. 'ctrl+c', 'alt+tab', 'win+d', 'enter'.",
     {"teclas": (S, "Teclas separadas por +")}),
    ("captura_pantalla", "Hace una captura de pantalla y la guarda en Imágenes.", {}),
    ("info_sistema", "Estado del PC: CPU, RAM, batería, disco y programas que más consumen.", {}),
    ("buscar_archivos", "Busca archivos por nombre en la carpeta del usuario.",
     {"nombre": (S, "Parte del nombre del archivo"), "carpeta": (S, "Carpeta opcional")}, ["nombre"]),
    ("abrir_archivo", "Abre un archivo o carpeta con su programa predeterminado.", {"ruta": (S, "Ruta completa")}),
    ("leer_archivo", "Lee el contenido de texto de un archivo.", {"ruta": (S, "Ruta completa")}),
    ("energia", "Bloquear, suspender, apagar, reiniciar el PC o cancelar un apagado. Pide confirmación antes de apagar/reiniciar.",
     {"accion": (S, "'bloquear', 'suspender', 'apagar', 'reiniciar', 'cancelar'")}),
    ("crear_recordatorio", "Crea un recordatorio/alarma. Avisa en el PC, envía notificación al teléfono y, si se pide, llama por teléfono.",
     {"mensaje": (S, "Qué recordar"), "en_minutos": ("number", "Dentro de cuántos minutos"),
      "fecha_hora": (S, "'YYYY-MM-DD HH:MM' o 'HH:MM'"), "llamar": ("boolean", "Llamar al teléfono al vencer"),
      "repetir_diario": ("boolean", "Repetir cada día")}, ["mensaje"]),
    ("listar_recordatorios", "Lista los recordatorios pendientes.", {}),
    ("borrar_recordatorio", "Borra recordatorios por id o texto.", {"texto": (S, "Id o parte del mensaje")}),
    ("recordar_dato", "Guarda en memoria permanente un dato sobre el usuario o una preferencia.", {"dato": (S, "Dato a recordar")}),
    ("olvidar_dato", "Borra datos de la memoria permanente.", {"texto": (S, "Texto del dato a olvidar")}),
    ("notificar_telefono", "Envía una notificación push al teléfono del usuario.", {"mensaje": (S, "Mensaje")}),
    ("llamar_telefono", "Llama al teléfono del usuario (Telegram) y le dice un mensaje por voz.", {"mensaje": (S, "Mensaje")}),
    ("mensaje_telegram", "Envía un mensaje de texto al Telegram del usuario.", {"mensaje": (S, "Mensaje")}),
]


class Herramientas:
    def __init__(self, memoria, recordatorios, telefono):
        self.memoria, self.recordatorios, self.telefono = memoria, recordatorios, telefono
        self._apps = None

    def esquemas(self):
        out = []
        for spec in SPECS:
            nombre, desc, props = spec[:3]
            req = spec[3] if len(spec) > 3 else list(props)
            out.append({"type": "function", "function": {
                "name": nombre, "description": desc,
                "parameters": {"type": "object",
                               "properties": {k: {"type": t, "description": d} for k, (t, d) in props.items()},
                               "required": req}}})
        return out

    def ejecutar(self, nombre, args):
        fn = getattr(self, nombre, None)
        if not fn or nombre.startswith("_") or nombre not in {s[0] for s in SPECS}:
            return f"Herramienta desconocida: {nombre}"
        try:
            return str(fn(**args))[:4000]
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

    def notificar_telefono(self, mensaje):
        return self.telefono.notificar(mensaje)

    def llamar_telefono(self, mensaje):
        return self.telefono.llamar(mensaje)

    def mensaje_telegram(self, mensaje):
        return self.telefono.mensaje_telegram(mensaje)
