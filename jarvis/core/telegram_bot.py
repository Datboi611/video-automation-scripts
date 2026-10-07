"""JARVIS en el iPhone vía un bot de Telegram propio (gratis, sin abrir puertos).
- Chatea o manda notas de voz: se ejecutan en el PC y responde.
- /pantalla: captura de lo que pasa en el PC.  /hoy: agenda.  /estado: estado del PC.
Solo obedece al chat vinculado con el código de emparejamiento."""
import io
import os
import logging
import random
import threading
import time

import requests

log = logging.getLogger("jarvis")


class BotTelegram:
    def __init__(self, cfg, jarvis, guardar):
        self.cfg = cfg.setdefault("telegram_bot", {"token": "", "chat_id": ""})
        self.j = jarvis
        self.guardar = guardar  # función(clave, valor) que persiste en config.json
        self.codigo = None
        self._hilo = None

    @property
    def activo(self):
        return bool(self.cfg.get("token"))

    def _api(self, metodo, **kw):
        url = f"https://api.telegram.org/bot{self.cfg['token']}/{metodo}"
        r = requests.post(url, timeout=kw.pop("timeout", 30), **kw)
        r.raise_for_status()
        return r.json().get("result")

    # ---------- envío ----------
    def enviar(self, texto):
        if not (self.activo and self.cfg.get("chat_id")):
            return False
        try:
            self._api("sendMessage", data={"chat_id": self.cfg["chat_id"], "text": texto[:4000]})
            return True
        except Exception as e:
            log.warning("Telegram enviar: %s", e)
            return False

    def enviar_foto(self, jpeg, texto=""):
        self._api("sendPhoto", data={"chat_id": self.cfg["chat_id"], "caption": texto[:1000]},
                  files={"photo": ("pantalla.jpg", jpeg, "image/jpeg")}, timeout=60)

    def enviar_audio(self, ruta):
        with open(ruta, "rb") as f:
            self._api("sendAudio", data={"chat_id": self.cfg["chat_id"], "title": "JARVIS"},
                      files={"audio": ("jarvis.mp3", f, "audio/mpeg")}, timeout=60)

    # ---------- arranque ----------
    def configurar(self):
        """Deja el bot listo: nombre, descripción y menú de comandos."""
        try:
            self._api("setMyCommands", json={"commands": [
                {"command": "hoy", "description": "Mi agenda de hoy"},
                {"command": "pantalla", "description": "Ver la pantalla del PC"},
                {"command": "estado", "description": "Estado del PC y procesos"},
                {"command": "canvas", "description": "Novedades de Canvas"},
                {"command": "correo", "description": "Correos importantes"},
                {"command": "musica", "description": "Pausar o reanudar la música"},
            ]})
            self._api("setMyDescription", data={"description":
                      "J.A.R.V.I.S. — el asistente personal de Diego. Escríbeme o mándame notas de voz: "
                      "controlo su PC, su agenda, Canvas, correo y le aviso lo importante."})
            self._api("setMyShortDescription", data={"short_description": "Asistente personal estilo Stark."})
            self._api("setMyName", data={"name": "J.A.R.V.I.S."})
        except Exception as e:
            log.warning("No pude configurar el bot: %s", e)

    def enviar_voz(self, texto):
        """Nota de voz con la voz de JARVIS (sirve cuando la llamada de iPhone llega sin audio)."""
        if not (self.activo and self.cfg.get("chat_id")):
            return
        try:
            ruta = self.j.voz.archivo(texto)
            with open(ruta, "rb") as f:
                self._api("sendAudio", data={"chat_id": self.cfg["chat_id"], "title": "JARVIS", "performer": "JARVIS"},
                          files={"audio": ("aviso.mp3", f, "audio/mpeg")}, timeout=60)
            os.remove(ruta)
        except Exception as e:
            log.warning("Nota de voz: %s", e)

    def iniciar(self):
        if not self.activo or (self._hilo and self._hilo.is_alive()):
            return
        threading.Thread(target=self.configurar, daemon=True).start()
        if not self.cfg.get("chat_id"):
            self.codigo = f"{random.randint(0, 999999):06d}"
        self._hilo = threading.Thread(target=self._loop, daemon=True)
        self._hilo.start()

    def _loop(self):
        offset = None
        while True:
            try:
                datos = {"timeout": 50, "allowed_updates": '["message"]'}
                if offset:
                    datos["offset"] = offset
                for u in self._api("getUpdates", data=datos, timeout=60) or []:
                    offset = u["update_id"] + 1
                    if "message" in u:
                        threading.Thread(target=self._mensaje, args=(u["message"],), daemon=True).start()
            except Exception as e:
                log.warning("Telegram desconectado: %s", e)
                time.sleep(5)

    # ---------- recepción ----------
    def _mensaje(self, m):
        chat = str(m["chat"]["id"])
        texto = (m.get("text") or "").strip()
        if not self.cfg.get("chat_id"):
            if self.codigo and texto == self.codigo:
                self.cfg["chat_id"] = chat
                self.guardar("chat_id", chat)
                self.codigo = None
                self._api("sendMessage", data={"chat_id": chat, "text":
                          "Vinculado, jefe. Desde ahora le obedezco aquí también.\n"
                          "Escríbame o mándeme notas de voz. Comandos: /pantalla /hoy /estado"})
                self.j.decir("Su teléfono quedó vinculado, jefe.")
            else:
                self._api("sendMessage", data={"chat_id": chat, "text":
                          "Envíame el código de 6 dígitos que JARVIS muestra en tu PC."})
            return
        if chat != str(self.cfg["chat_id"]):
            return  # cualquier otro chat se ignora
        try:
            self._api("sendChatAction", data={"chat_id": chat, "action": "typing"}, timeout=10)
            if texto.startswith("/pantalla") or texto.lower() in ("pantalla", "qué pasa en mi pc"):
                return self._pantalla()
            if texto.startswith("/hoy"):
                texto = "¿Qué tengo hoy?"
            elif texto.startswith("/estado"):
                texto = "Dame el estado del PC y qué procesos estás haciendo."
            elif texto.startswith("/canvas"):
                texto = "¿Qué novedades y pendientes tengo en Canvas?"
            elif texto.startswith("/correo"):
                texto = "¿Tengo correos importantes sin leer?"
            elif texto.startswith("/musica"):
                texto = "Pausa la música" if getattr(getattr(self.j.herramientas, "musica", None), "sonando", False) else "Reanuda la música"
            elif texto.startswith("/start"):
                return self.enviar("A sus órdenes, jefe.")
            if m.get("voice") or m.get("audio"):
                texto = self._transcribir(m.get("voice") or m.get("audio"))
                if not texto:
                    return self.enviar("No le entendí la nota de voz, jefe.")
                self.enviar(f"🎙 {texto}")
            if not texto:
                return
            respuesta = self.j.procesar(texto, hablar=False, origen="telefono")
            self.enviar(respuesta)
            if "pantalla" in texto.lower() or "lo que estoy viendo" in texto.lower():
                self._pantalla(sin_texto=True)
        except Exception:
            log.exception("Error atendiendo Telegram")
            self.enviar("Hubo un error, jefe.")

    def _transcribir(self, archivo):
        info = self._api("getFile", data={"file_id": archivo["file_id"]})
        datos = requests.get(f"https://api.telegram.org/file/bot{self.cfg['token']}/{info['file_path']}",
                             timeout=60).content
        return self.j.oido.transcribir_archivo(datos, "nota.ogg")

    def _pantalla(self, sin_texto=False):
        import pyautogui
        img = pyautogui.screenshot()
        img.thumbnail((1920, 1920))
        buf = io.BytesIO()
        img.convert("RGB").save(buf, "JPEG", quality=75)
        self.enviar_foto(buf.getvalue(), "" if sin_texto else "Así está su PC ahora mismo, jefe.")
