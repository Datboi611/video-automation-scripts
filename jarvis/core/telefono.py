"""Conexión con el teléfono, 100% gratis:
- ntfy.sh: notificaciones push (app ntfy en Android/iPhone) y control remoto.
- CallMeBot: llamadas de voz y mensajes por Telegram.
"""
import json
import logging
import urllib.parse
import re
import threading
import time

import requests

log = logging.getLogger("jarvis")


def normalizar_numero(numero):
    """+1 por defecto (EE. UU.) si escribió el número sin código de país."""
    d = re.sub(r"\D", "", numero or "")
    if not d:
        return ""
    if len(d) == 10:
        d = "1" + d
    return "+" + d


class Telefono:
    def __init__(self, cfg):
        t = cfg["telefono"]
        for k in ("twilio_numero", "mi_numero"):
            if t.get(k):
                t[k] = normalizar_numero(t[k])
        self.cfg_tel = t
        self.solo_alerta = False
        self.servidor = t["ntfy_servidor"].rstrip("/")
        self.tema = t["ntfy_tema"].strip()
        self.telegram = t["telegram_usuario"].strip()
        if self.telegram and not self.telegram.startswith("@"):
            self.telegram = "@" + self.telegram

    def notificar(self, mensaje, titulo="JARVIS", prioridad=4):
        if not self.tema:
            return "No hay tema de ntfy configurado (telefono.ntfy_tema en config.json)."
        r = requests.post(
            f"{self.servidor}/{self.tema}",
            data=mensaje.encode("utf-8"),
            headers={"Title": titulo.encode("utf-8"), "Priority": str(prioridad), "Tags": "robot"},
            timeout=15,
        )
        r.raise_for_status()
        return "Notificación enviada al teléfono."

    @property
    def twilio_listo(self):
        t = self.cfg_tel
        return all(t.get(k) for k in ("twilio_sid", "twilio_token", "twilio_numero", "mi_numero"))

    def llamar_twilio(self, mensaje):
        """Llamada telefónica REAL a tu número (contestas y escuchas a JARVIS)."""
        from xml.sax.saxutils import escape
        t = self.cfg_tel
        voz = t.get("twilio_voz", "Polly.Andres-Neural")
        decir = f'<Say voice="{voz}" language="es-MX">{escape(mensaje[:900])}</Say>'
        twiml = (f'<Response><Pause length="1"/>{decir}<Pause length="1"/>'
                 f'<Say voice="{voz}" language="es-MX">Repito.</Say>{decir}</Response>')
        url_api = f"https://api.twilio.com/2010-04-01/Accounts/{t['twilio_sid']}/Calls.json"
        base = {"To": t["mi_numero"], "From": t["twilio_numero"]}
        # Las cuentas de prueba no aceptan el parámetro Twiml: se entrega el guion por URL (Twimlets echo,
        # servicio de Twilio). Si eso fallara, se prueba el Twiml directo (cuentas de pago).
        intentos = [
            {**base, "Url": "https://twimlets.com/echo?" + urllib.parse.urlencode({"Twiml": twiml}), "Method": "GET"},
            {**base, "Twiml": twiml},
            {**base, "Url": "https://twimlets.com/message?" + urllib.parse.urlencode({"Message[0]": mensaje[:500]}),
             "Method": "GET"},
        ]
        # Cuenta de prueba: solo admite las plantillas de Twilio. El teléfono suena igual (alerta real)
        # y el mensaje completo llega por Telegram en texto y nota de voz.
        plantillas = [{**base, "Url": f"https://webhooks.twilio.com/v1/Voice/Template/{p}"}
                      for p in ("voice_text_to_speech", "voice_say", "voice_speech_recognition")]
        ultimo = ""
        orden = plantillas + intentos if self.solo_alerta else intentos + plantillas
        for datos in orden:
            n = len(intentos) if datos in plantillas else 0
            r = requests.post(url_api, auth=(t["twilio_sid"], t["twilio_token"]), timeout=20, data=datos)
            if r.status_code < 400:
                if n >= len(intentos):
                    self.solo_alerta = True
                    return "Llamando a su teléfono (cuenta de prueba: el mensaje va por Telegram)."
                self.solo_alerta = False
                return "Llamando a su teléfono."
            try:
                ultimo = r.json().get("message", r.text[:200])
            except ValueError:
                ultimo = r.text[:200]
            log.warning("Twilio rechazó un intento: %s", ultimo)
        raise RuntimeError(ultimo)

    def llamar(self, mensaje):
        error_twilio = None
        if self.twilio_listo:
            try:
                return self.llamar_twilio(mensaje)
            except Exception as e:
                error_twilio = str(e)
                log.warning("Twilio falló, uso CallMeBot: %s", e)
        if not self.telegram:
            if error_twilio:
                return f"Twilio rechazó la llamada: {error_twilio[:150]}"
            return "Las llamadas no están configuradas. Dígame «configura las llamadas»."
        r = requests.get(
            "https://api.callmebot.com/start.php",
            # cc=yes: copia en texto (en iPhone la llamada suena pero Telegram no reproduce el audio)
            params={"user": self.telegram, "text": mensaje[:250], "lang": "es-ES-Standard-B", "rpt": 2, "cc": "yes"},
            timeout=40,
        )
        r.raise_for_status()
        if "not authorized" in r.text.lower() or "error" in r.text.lower()[:200]:
            return "CallMeBot no pudo llamar: abre @CallMeBot_txtbot en Telegram y pulsa Iniciar."
        return "Llamada iniciada por Telegram."

    def mensaje_telegram(self, mensaje):
        if not self.telegram:
            return "No hay usuario de Telegram configurado (telefono.telegram_usuario)."
        r = requests.get(
            "https://api.callmebot.com/text.php",
            params={"user": self.telegram, "text": mensaje},
            timeout=30,
        )
        r.raise_for_status()
        return "Mensaje enviado por Telegram."

    def escuchar_ordenes(self, callback):
        """Escucha el tema '<tema>-ordenes': lo que envíes desde la app ntfy lo ejecuta JARVIS."""
        if not self.tema:
            return
        url = f"{self.servidor}/{self.tema}-ordenes/json"

        def loop():
            while True:
                try:
                    with requests.get(url, stream=True, timeout=(10, 120)) as r:
                        for linea in r.iter_lines():
                            if not linea:
                                continue
                            ev = json.loads(linea)
                            if ev.get("event") == "message" and ev.get("message"):
                                callback(ev["message"])
                except Exception as e:
                    log.warning("ntfy desconectado: %s", e)
                time.sleep(5)

        threading.Thread(target=loop, daemon=True).start()
