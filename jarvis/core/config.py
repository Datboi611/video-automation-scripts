"""Carga de configuración: config.json + valores por defecto + variables de entorno."""
import copy
import json
import os

BASE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
DATOS = os.path.join(BASE, "datos")
MODELOS = os.path.join(BASE, "modelos")

DEFAULTS = {
    "nombre_usuario": "",
    "tratamiento": "señor",
    "activacion": {
        "palabra": "jarvis",
        "aplausos": True,
        "umbral_aplauso": 0.30,
        "modelo_vosk": "modelos/vosk-model-small-en-us-0.15",
    },
    "llm": {
        "proveedores": [
            {"nombre": "groq", "api_key": "", "modelo": "llama-3.3-70b-versatile"},
            {"nombre": "gemini", "api_key": "", "modelo": "gemini-2.5-flash"},
            {"nombre": "ollama", "modelo": "qwen2.5:7b", "url": "http://localhost:11434/v1"},
        ]
    },
    "stt": {"motor": "auto", "modelo_local": "small"},
    "voz": {"motor": "edge", "voz": "es-MX-JorgeNeural", "velocidad": "+8%"},
    "telefono": {
        "ntfy_servidor": "https://ntfy.sh",
        "ntfy_tema": "",
        "telegram_usuario": "",
        "control_remoto": False,
    },
    "conversacion_continua": True,
    "segundos_conversacion": 6,
    "microfono": None,
}

URLS_PROVEEDOR = {
    "groq": "https://api.groq.com/openai/v1",
    "gemini": "https://generativelanguage.googleapis.com/v1beta/openai/",
    "ollama": "http://localhost:11434/v1",
}

ENV_KEYS = {"groq": "GROQ_API_KEY", "gemini": "GEMINI_API_KEY"}


def _merge(base, extra):
    for k, v in extra.items():
        if k.startswith("_"):
            continue
        if isinstance(v, dict) and isinstance(base.get(k), dict):
            _merge(base[k], v)
        else:
            base[k] = v


def cargar():
    cfg = copy.deepcopy(DEFAULTS)
    ruta = os.path.join(BASE, "config.json")
    if os.path.exists(ruta):
        with open(ruta, encoding="utf-8") as f:
            _merge(cfg, json.load(f))
    for p in cfg["llm"]["proveedores"]:
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
