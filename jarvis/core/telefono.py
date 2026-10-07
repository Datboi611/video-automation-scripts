"""Conexión con el teléfono, 100% gratis:
- ntfy.sh: notificaciones push (app ntfy en Android/iPhone) y control remoto.
- CallMeBot: llamadas de voz y mensajes por Telegram.
"""
import json
import logging
import threading
import time

import requests

log = logging.getLogger("jarvis")


class Telefono:
    def __init__(self, cfg):
        t = cfg["telefono"]
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

    def llamar(self, mensaje):
        if not self.telegram:
            return "No hay usuario de Telegram configurado (telefono.telegram_usuario)."
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
