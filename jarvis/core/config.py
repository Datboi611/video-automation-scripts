"""Carga de configuración: config.json + valores por defecto + variables de entorno."""
import copy
import json
import os

BASE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
DATOS = os.path.join(BASE, "datos")
MODELOS = os.path.join(BASE, "modelos")

DEFAULTS = {
    "nombre_usuario": "",
    "tratamiento": "jefe",
    "tratamiento_en": "boss",
    "activacion": {
        "palabra": "jarvis",
        "aplausos": True,
        "umbral_aplauso": 0.30,
        "modelo_vosk": "modelos/vosk-model-small-en-us-0.15",
    },
    "llm": {
        "proveedores": [
            {"nombre": "groq", "api_key": "", "modelo": "meta-llama/llama-4-scout-17b-16e-instruct"},
            {"nombre": "gemini", "api_key": "", "modelo": "gemini-2.5-flash"},
            {"nombre": "ollama", "modelo": "qwen2.5:3b", "url": "http://localhost:11434/v1"},
        ]
    },
    "stt": {"motor": "auto", "modelo_local": "small"},
    # Mayordomo: español castellano formal y británico en inglés, algo más grave y pausado
    # Voz natural: sin alterar el tono (bajarlo distorsiona). motor "elevenlabs" = la más humana (opcional).
    "voz": {"motor": "edge", "voz": "es-ES-AlvaroNeural", "voz_en": "en-GB-RyanNeural",
            "velocidad": "+0%", "tono": "+0Hz", "elevenlabs_api_key": "", "elevenlabs_voz": "JBFqnCBsd6RMkjVDRZzb"},
    "agenda": {"google_calendar_ics": "", "todoist_token": "", "canvas_url": "https://utah.instructure.com", "canvas_token": ""},
    "telefono": {
        "ntfy_servidor": "https://ntfy.sh",
        "ntfy_tema": "",
        "telegram_usuario": "",
        "control_remoto": False,
        # Llamadas reales con número (Twilio): twilio.com/try-twilio
        "twilio_sid": "", "twilio_token": "", "twilio_numero": "", "mi_numero": "",
        "twilio_voz": "Polly.Andres-Neural",
    },
    "telegram_bot": {"token": "", "chat_id": ""},
    "vigilante": {"resumen_matutino": "08:00", "revisiones": ["14:00", "19:00"], "aviso_eventos_min": 30,
                  "llamar_si_pendiente": True, "hora_llamada": "20:30", "silencio": ["23:00", "07:30"],
                  "correo_cada_min": 15, "canvas_cada_min": 30, "correo_importante": ""},
    "presencia": {"telefono_mac": "", "minutos_ausencia": 10},
    "idioma": "es",  # "es" = siempre español; "auto" = español o inglés según cómo hables
    "minutos_reposo": 30,
    "segundos_silencio": 1.6,
    "interrumpir": True,
    "factor_interrupcion": 2.8,
    "vocabulario": "",
    "microfono": None,
}

URLS_PROVEEDOR = {
    "claude": "https://api.anthropic.com/v1/",
    "groq": "https://api.groq.com/openai/v1",
    "gemini": "https://generativelanguage.googleapis.com/v1beta/openai/",
    "ollama": "http://localhost:11434/v1",
}

ENV_KEYS = {"groq": "GROQ_API_KEY", "gemini": "GEMINI_API_KEY", "claude": "ANTHROPIC_API_KEY"}

MODELO_INICIAL = {"claude": "claude-sonnet-5-5", "gemini": "gemini-2.5-flash", "groq": "meta-llama/llama-4-scout-17b-16e-instruct"}

# Modelos de respaldo dentro del mismo proveedor (si uno falla o se retira, prueba el siguiente)
RESPALDO_MODELOS = {
    # ordenados por cupo diario gratis y velocidad (scout: 500K tokens/día; 70b: solo 100K/día)
    "groq": ["meta-llama/llama-4-scout-17b-16e-instruct", "llama-3.3-70b-versatile", "openai/gpt-oss-120b",
             "openai/gpt-oss-20b", "moonshotai/kimi-k2-instruct", "llama-3.1-8b-instant"],
    "gemini": ["gemini-2.5-flash", "gemini-2.5-flash-lite", "gemini-2.0-flash"],
}


def _merge(base, extra):
    for k, v in extra.items():
        if k.startswith("_"):
            continue
        if isinstance(v, dict) and isinstance(base.get(k), dict):
            _merge(base[k], v)
        else:
            base[k] = v


def _migrar(usuario, ruta):
    """Actualiza un config.json viejo a los nuevos valores por defecto."""
    v = usuario.get("_version", 1)
    if v >= 5:
        return
    if v == 4:
        _a_v5(usuario)
        usuario["_version"] = 5
        with open(ruta, "w", encoding="utf-8") as f:
            json.dump(usuario, f, ensure_ascii=False, indent=2)
        return
    if v == 3:
        _a_v4(usuario)
        _a_v5(usuario)
        usuario["_version"] = 5
        with open(ruta, "w", encoding="utf-8") as f:
            json.dump(usuario, f, ensure_ascii=False, indent=2)
        return
    if usuario.get("tratamiento") == "señor":
        usuario["tratamiento"] = "jefe"
    for k in ("conversacion_continua", "segundos_conversacion"):
        usuario.pop(k, None)
    voz = usuario.setdefault("voz", {})
    if voz.get("voz") in (None, "es-MX-JorgeNeural"):
        voz["voz"] = "en-US-AndrewMultilingualNeural"
    if voz.get("voz_en") in (None, "en-GB-RyanNeural"):
        voz["voz_en"] = "en-US-AndrewMultilingualNeural"
    if voz.get("velocidad") in (None, "+8%", "+25%"):
        voz["velocidad"] = "+8%"
    usuario.setdefault("agenda", {"google_calendar_ics": "", "todoist_token": ""})
    _a_v4(usuario)
    _a_v5(usuario)
    usuario["_version"] = 5
    with open(ruta, "w", encoding="utf-8") as f:
        json.dump(usuario, f, ensure_ascii=False, indent=2)


def _a_v4(usuario):
    """v4: modelo con más cupo diario y voz de mayordomo."""
    for p in usuario.get("llm", {}).get("proveedores", []):
        if p.get("nombre") == "groq" and p.get("modelo") == "llama-3.3-70b-versatile":
            p["modelo"] = "meta-llama/llama-4-scout-17b-16e-instruct"
    voz = usuario.setdefault("voz", {})
    if voz.get("voz") in (None, "en-US-AndrewMultilingualNeural", "es-MX-JorgeNeural"):
        voz["voz"] = "es-ES-AlvaroNeural"
    if voz.get("voz_en") in (None, "en-US-AndrewMultilingualNeural", "en-GB-RyanNeural"):
        voz["voz_en"] = "en-GB-RyanNeural"
    if voz.get("velocidad") in (None, "+8%", "+25%"):
        voz["velocidad"] = "-2%"
    voz.setdefault("tono", "-6Hz")


def _a_v5(usuario):
    """v5: voz natural, sin bajar el tono artificialmente."""
    voz = usuario.setdefault("voz", {})
    if voz.get("tono") in (None, "-6Hz", "-4Hz", "-8Hz"):
        voz["tono"] = "+0Hz"
    if voz.get("velocidad") in (None, "-2%"):
        voz["velocidad"] = "+0%"
    voz.setdefault("elevenlabs_api_key", "")
    voz.setdefault("elevenlabs_voz", "JBFqnCBsd6RMkjVDRZzb")


def cargar():
    cfg = copy.deepcopy(DEFAULTS)
    ruta = os.path.join(BASE, "config.json")
    if os.path.exists(ruta):
        with open(ruta, encoding="utf-8") as f:
            usuario = json.load(f)
        _migrar(usuario, ruta)
        _merge(cfg, usuario)
    for p in cfg["llm"]["proveedores"]:
        p["api_key"] = (p.get("api_key") or "").strip()
        env = ENV_KEYS.get(p["nombre"])
        if env and not p.get("api_key") and os.environ.get(env):
            p["api_key"] = os.environ[env]
    modelo = cfg["activacion"]["modelo_vosk"]
    if not os.path.isabs(modelo):
        cfg["activacion"]["modelo_vosk"] = os.path.join(BASE, modelo)
    os.makedirs(DATOS, exist_ok=True)
    return cfg


def clave(cfg, proveedor):
    for p in cfg["llm"]["proveedores"]:
        if p["nombre"] == proveedor and p.get("api_key"):
            return p["api_key"]
    return None


def guardar_valor(camino, valor):
    """Cambia un valor dentro de config.json (p. ej. ["voz", "voz"])."""
    ruta = os.path.join(BASE, "config.json")
    datos = {}
    if os.path.exists(ruta):
        with open(ruta, encoding="utf-8") as f:
            datos = json.load(f)
    d = datos
    for k in camino[:-1]:
        d = d.setdefault(k, {})
    d[camino[-1]] = valor
    with open(ruta, "w", encoding="utf-8") as f:
        json.dump(datos, f, ensure_ascii=False, indent=2)
