"""Conversar con JARVIS por teléfono en tiempo real (Twilio + túnel gratuito de Cloudflare).
- Llamas al número de JARVIS desde tu celular y hablas con él; o él te llama y la conversación sigue.
- Twilio transcribe lo que dices (<Gather input="speech">), JARVIS lo procesa y responde con voz.
- Seguridad: solo atiende llamadas de TU número y valida la firma de Twilio en cada petición."""
import base64
import hashlib
import hmac
import http.server
import logging
import os
import re
import subprocess
import sys
import threading
import time
import urllib.parse
import uuid
from xml.sax.saxutils import escape

import requests

log = logging.getLogger("jarvis")
SIN_VENTANA = 0x08000000 if sys.platform == "win32" else 0
PUERTO = 8787
DESPEDIDAS = re.compile(r"\b(adi[oó]s|chao|chau|eso es todo|nada m[aá]s|cuelga|hasta luego|ya est[aá]|es todo)\b"
                        r"|^\W*(no|nop|nope|nada|no gracias|no,? gracias|gracias|listo|ya|ok|est[aá] bien|perfecto)\W*$", re.I)


class LlamadasVivo:
    def __init__(self, jarvis, carpeta):
        self.j = jarvis
        self.carpeta = carpeta
        self.url = None  # https://xxxx.trycloudflare.com
        self.pendientes = {}  # id -> respuesta (o None mientras piensa)
        self.carpeta_audio = os.path.join(carpeta, "audio_llamadas")
        os.makedirs(self.carpeta_audio, exist_ok=True)

    @property
    def t(self):
        return self.j.cfg["telefono"]

    # ---------- arranque ----------
    def iniciar(self):
        if not self.j.telefono.twilio_listo:
            return
        threading.Thread(target=self._servidor, daemon=True).start()
        threading.Thread(target=self._tunel, daemon=True).start()

    def _servidor(self):
        dueno = self

        class Manejador(http.server.BaseHTTPRequestHandler):
            def log_message(self, *a):
                pass

            def do_GET(self):  # audios de JARVIS (voz de ElevenLabs) que Twilio reproduce en la llamada
                m = re.fullmatch(r"/audio/([a-f0-9]{32})\.mp3", self.path)
                ruta = os.path.join(dueno.carpeta_audio, m.group(1) + ".mp3") if m else ""
                if not ruta or not os.path.exists(ruta):
                    self.send_response(404)
                    self.end_headers()
                    return
                with open(ruta, "rb") as f:
                    datos = f.read()
                self.send_response(200)
                self.send_header("Content-Type", "audio/mpeg")
                self.send_header("Content-Length", str(len(datos)))
                self.end_headers()
                self.wfile.write(datos)

            def do_POST(self):
                largo = int(self.headers.get("Content-Length", 0) or 0)
                cuerpo = self.rfile.read(largo).decode("utf-8", "replace")
                params = dict(urllib.parse.parse_qsl(cuerpo, keep_blank_values=True))
                xml = dueno.atender(self.path, params, self.headers.get("X-Twilio-Signature", ""))
                datos = xml.encode("utf-8")
                self.send_response(200)
                self.send_header("Content-Type", "text/xml; charset=utf-8")
                self.send_header("Content-Length", str(len(datos)))
                self.end_headers()
                self.wfile.write(datos)

        try:
            http.server.ThreadingHTTPServer(("127.0.0.1", PUERTO), Manejador).serve_forever()
        except OSError as e:
            log.warning("No pude abrir el servidor de llamadas: %s", e)

    def _cloudflared(self):
        exe = os.path.join(self.carpeta, "cloudflared.exe" if sys.platform == "win32" else "cloudflared")
        if not os.path.exists(exe):
            log.info("Descargando cloudflared (túnel gratuito)…")
            nombre = "cloudflared-windows-amd64.exe" if sys.platform == "win32" else "cloudflared-linux-amd64"
            r = requests.get(f"https://github.com/cloudflare/cloudflared/releases/latest/download/{nombre}",
                             timeout=120)
            r.raise_for_status()
            with open(exe, "wb") as f:
                f.write(r.content)
            if sys.platform != "win32":
                os.chmod(exe, 0o755)
        return exe

    def _tunel(self):
        while True:
            try:
                exe = self._cloudflared()
                proc = subprocess.Popen([exe, "tunnel", "--url", f"http://127.0.0.1:{PUERTO}", "--no-autoupdate"],
                                        stdout=subprocess.PIPE, stderr=subprocess.STDOUT, text=True,
                                        creationflags=SIN_VENTANA)
                for linea in proc.stdout:
                    m = re.search(r"https://[a-z0-9-]+\.trycloudflare\.com", linea)
                    if m and m.group(0) != self.url:
                        self.url = m.group(0)
                        log.info("Túnel de llamadas activo: %s", self.url)
                        time.sleep(3)
                        self._configurar_numero()
                proc.wait()
            except Exception as e:
                log.warning("Túnel de llamadas caído: %s", e)
            self.url = None
            time.sleep(20)

    def _configurar_numero(self):
        """Apunta el número de JARVIS a este PC para que pueda recibir tus llamadas."""
        self.j.telefono.autocorregir_numeros()
        t = self.t
        api = f"https://api.twilio.com/2010-04-01/Accounts/{t['twilio_sid']}/IncomingPhoneNumbers"
        auth = (t["twilio_sid"], t["twilio_token"])
        try:
            r = requests.get(api + ".json", auth=auth, params={"PhoneNumber": t["twilio_numero"]}, timeout=20)
            numeros = r.json().get("incoming_phone_numbers", [])
            if not numeros:
                return log.warning("No encontré %s en su cuenta de Twilio", t["twilio_numero"])
            sid = numeros[0]["sid"]
            r = requests.post(f"{api}/{sid}.json", auth=auth, timeout=20,
                              data={"VoiceUrl": self.url + "/voz", "VoiceMethod": "POST"})
            r.raise_for_status()
            log.info("Número %s listo para recibir llamadas", t["twilio_numero"])
        except Exception as e:
            log.warning("No pude configurar el número de Twilio: %s", e)

    # ---------- seguridad ----------
    def _firma_valida(self, ruta, params, firma):
        if not self.url or not firma:
            return False
        datos = self.url + ruta + "".join(k + params[k] for k in sorted(params))
        esperada = base64.b64encode(hmac.new(self.t["twilio_token"].encode(), datos.encode(), hashlib.sha1).digest()).decode()
        return hmac.compare_digest(esperada, firma)

    # ---------- conversación ----------
    def _voz(self):
        return self.t.get("twilio_voz", "Polly.Andres-Neural")

    def _decir(self, texto):
        """Con ElevenLabs configurado, la llamada usa la misma voz de JARVIS (George); si no, la de Twilio."""
        voz = self.j.cfg.get("voz", {})
        if self.url and voz.get("elevenlabs_api_key"):
            try:
                ruta = self.j.voz._generar_11(texto[:900])
                nombre = uuid.uuid4().hex
                os.replace(ruta, os.path.join(self.carpeta_audio, nombre + ".mp3"))
                self._limpiar_audios()
                return f"<Play>{self.url}/audio/{nombre}.mp3</Play>"
            except Exception as e:
                log.warning("Voz de ElevenLabs en llamada no disponible: %s", e)
        return f'<Say voice="{self._voz()}" language="es-MX">{escape(texto[:1500])}</Say>'

    def _limpiar_audios(self):
        limite = time.time() - 3600
        for f in os.listdir(self.carpeta_audio):
            ruta = os.path.join(self.carpeta_audio, f)
            if os.path.getmtime(ruta) < limite:
                try:
                    os.remove(ruta)
                except OSError:
                    pass

    def _escuchar(self, texto=""):
        return (f'<Gather input="speech" language="es-MX" speechTimeout="auto" speechModel="phone_call" '
                f'action="/voz/respuesta" method="POST" actionOnEmptyResult="true">{self._decir(texto) if texto else ""}'
                f'</Gather><Redirect method="POST">/voz/respuesta</Redirect>')

    def atender(self, ruta, params, firma):
        if not self._firma_valida(ruta, params, firma):
            log.warning("Petición de llamada rechazada (firma inválida): %s", ruta)
            return "<Response><Reject/></Response>"
        mio = self.t["mi_numero"]
        if params.get("Direction", "").startswith("inbound") and params.get("From") != mio:
            return "<Response><Reject/></Response>"  # solo su celular puede hablar con JARVIS
        ruta_base = ruta.split("?")[0]
        q = dict(urllib.parse.parse_qsl(urllib.parse.urlparse(ruta).query))
        jefe = self.j.cfg["tratamiento"]

        if ruta_base == "/voz":  # inicio: llamada entrante o saliente de JARVIS
            saludo = q.get("msg") or f"¿Sí, {jefe}? Le escucho."
            return f"<Response>{self._escuchar(saludo)}</Response>"

        if ruta_base == "/voz/respuesta":
            texto = (params.get("SpeechResult") or "").strip()
            if not texto:
                vacios = int(q.get("v", 0)) + 1
                if vacios >= 2:
                    return f"<Response>{self._decir(f'Quedo atento, {jefe}. Hasta luego.')}<Hangup/></Response>"
                return f'<Response>{self._escuchar("¿Sigue ahí?").replace("/voz/respuesta", f"/voz/respuesta?v={vacios}")}</Response>'
            if DESPEDIDAS.search(texto):
                return f"<Response>{self._decir(f'A su servicio, {jefe}.')}<Hangup/></Response>"
            pid = uuid.uuid4().hex[:8]
            self.pendientes[pid] = None

            def pensar():
                try:
                    self.pendientes[pid] = self.j.procesar(texto, hablar=False, origen="telefono", sincrono=True)
                except Exception:
                    log.exception("Llamada en vivo")
                    self.pendientes[pid] = f"Deme un momento más, {jefe}."

            threading.Thread(target=pensar, daemon=True).start()
            return self._esperar(pid, intento=0)

        if ruta_base == "/voz/espera":
            return self._esperar(q.get("id", ""), int(q.get("n", 0)))

        return f"<Response>{self._escuchar()}</Response>"

    def _esperar(self, pid, intento):
        """Twilio solo espera ~15 s por respuesta: si JARVIS tarda, se hace una pausa breve y se vuelve a consultar."""
        limite = time.time() + 8
        while time.time() < limite:
            r = self.pendientes.get(pid)
            if r:
                self.pendientes.pop(pid, None)
                return f"<Response>{self._escuchar(r + ' ¿Algo más?')}</Response>"
            time.sleep(0.25)
        if intento >= 16:
            self.pendientes.pop(pid, None)
            return f"<Response>{self._escuchar('Sigo trabajando en eso; se lo mando por Telegram al terminar. ¿Algo más?')}</Response>"
        aviso = self._decir("Un momento.") if intento == 0 else ""
        return f'<Response>{aviso}<Pause length="1"/><Redirect method="POST">/voz/espera?id={pid}&amp;n={intento + 1}</Redirect></Response>'

    # ---------- llamada saliente conversacional ----------
    def llamar_y_conversar(self, mensaje):
        if not self.url:
            return None
        t = self.t
        url = self.url + "/voz?" + urllib.parse.urlencode({"msg": mensaje + " ¿Algo más, " + self.j.cfg["tratamiento"] + "?"})
        r = requests.post(f"https://api.twilio.com/2010-04-01/Accounts/{t['twilio_sid']}/Calls.json",
                          auth=(t["twilio_sid"], t["twilio_token"]), timeout=20,
                          data={"To": t["mi_numero"], "From": t["twilio_numero"], "Url": url})
        if r.status_code >= 400:
            raise RuntimeError(r.json().get("message", r.text[:200]))
        return "Llamando a su teléfono."
