"""Diagnóstico: prueba cada servicio y dice exactamente qué funciona y qué no."""
import logging

import requests

from . import config

log = logging.getLogger("jarvis")


def _p(nombre, fn):
    try:
        return f"✅ {nombre}: {fn()}"
    except Exception as e:
        texto = str(e)
        if hasattr(e, "response") and getattr(e, "response", None) is not None:
            try:
                texto = f"{e.response.status_code} {e.response.text[:160]}"
            except Exception:
                pass
        return f"❌ {nombre}: {texto[:220]}"


def revisar(cfg, herr=None):
    r = []

    def groq():
        from openai import OpenAI
        k = config.clave(cfg, "groq")
        if not k:
            raise RuntimeError("sin clave")
        c = OpenAI(api_key=k, base_url=config.URLS_PROVEEDOR["groq"], timeout=20, max_retries=0)
        from .cerebro import _modelos_disponibles
        preferidos = [next(p["modelo"] for p in cfg["llm"]["proveedores"] if p["nombre"] == "groq")] + \
            config.RESPALDO_MODELOS["groq"]
        disponibles = _modelos_disponibles(c, list(dict.fromkeys(preferidos)))
        if not disponibles:
            raise RuntimeError("ningún modelo disponible")
        modelo = disponibles[0]
        c.chat.completions.create(model=modelo, max_tokens=5, messages=[{"role": "user", "content": "di ok"}])
        if herr:  # también con herramientas, que es como trabaja de verdad
            c.chat.completions.create(model=modelo, max_tokens=50, tool_choice="auto",
                                      tools=herr.esquemas({"llamar_telefono", "notificar_telefono", "mostrar_panel"}),
                                      messages=[{"role": "user", "content": "hola"}])
        return f"cerebro OK ({modelo}; respaldo: {', '.join(disponibles[1:4]) or 'ninguno'})"
    r.append(_p("IA (Groq)", groq))

    tb = cfg.get("telegram_bot", {})

    def telegram():
        if not tb.get("token"):
            raise RuntimeError("sin token del bot")
        x = requests.get(f"https://api.telegram.org/bot{tb['token']}/getMe", timeout=15)
        x.raise_for_status()
        nombre = x.json()["result"]["username"]
        if not tb.get("chat_id"):
            return f"@{nombre} conectado, pero FALTA vincular el iPhone (envíale el código del panel)"
        y = requests.post(f"https://api.telegram.org/bot{tb['token']}/sendMessage", timeout=15,
                          data={"chat_id": tb["chat_id"], "text": "🔧 Diagnóstico de JARVIS: Telegram OK"})
        y.raise_for_status()
        return f"@{nombre} vinculado; te mandé un mensaje de prueba"
    r.append(_p("Telegram", telegram))

    t = cfg["telefono"]

    def twilio():
        if not all(t.get(k) for k in ("twilio_sid", "twilio_token", "twilio_numero", "mi_numero")):
            raise RuntimeError("faltan datos (SID, token, número de Twilio o tu número)")
        x = requests.get(f"https://api.twilio.com/2010-04-01/Accounts/{t['twilio_sid']}.json",
                         auth=(t["twilio_sid"], t["twilio_token"]), timeout=15)
        x.raise_for_status()
        cuenta = x.json()
        y = requests.get(f"https://api.twilio.com/2010-04-01/Accounts/{t['twilio_sid']}/OutgoingCallerIds.json",
                         auth=(t["twilio_sid"], t["twilio_token"]), timeout=15)
        verificados = [c["phone_number"] for c in y.json().get("outgoing_caller_ids", [])] if y.ok else []
        extra = ""
        if cuenta.get("type") == "Trial" and t["mi_numero"] not in verificados:
            extra = f" — OJO: tu número {t['mi_numero']} NO está en Verified Caller IDs"
        return f"cuenta {cuenta.get('status')} ({cuenta.get('type')}), llama desde {t['twilio_numero']} a {t['mi_numero']}{extra}"
    r.append(_p("Llamadas (Twilio)", twilio))

    v = cfg["voz"]

    def eleven():
        if not v.get("elevenlabs_api_key"):
            return "no configurado (usa la voz gratis)"
        x = requests.get("https://api.elevenlabs.io/v1/user/subscription", timeout=15,
                         headers={"xi-api-key": v["elevenlabs_api_key"]})
        x.raise_for_status()
        d = x.json()
        return f"OK, quedan {d.get('character_limit', 0) - d.get('character_count', 0)} caracteres este mes"
    r.append(_p("Voz ElevenLabs", eleven))

    def todoist():
        tok = cfg["agenda"].get("todoist_token")
        if not tok:
            return "no configurado"
        x = requests.get("https://api.todoist.com/api/v1/tasks", headers={"Authorization": f"Bearer {tok}"},
                         params={"limit": 50}, timeout=15)
        x.raise_for_status()
        d = x.json()
        return f"OK, {len(d.get('results', d))} tareas activas"
    r.append(_p("Todoist", todoist))

    if herr and herr.agenda.get("canvas"):
        cv = herr.agenda["canvas"]
        r.append(_p("Canvas", lambda: f"OK, {len(cv.cursos())} cursos" if cv.conectado else "no conectado (di «conecta Canvas»)"))
    if herr and herr.agenda.get("correo"):
        co = herr.agenda["correo"]
        r.append(_p("Correo", lambda: (co.cuentas[0].buscar("UNSEEN", 1) and "OK") or "OK" if co._elegir()
                    else "no conectado (di «conecta mi correo»)"))
    return "\n".join(r)
