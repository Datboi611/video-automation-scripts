"""Correo por IMAP/SMTP (Gmail, iCloud, Outlook personal…) con contraseña de aplicación."""
import email
import email.header
import email.utils
import imaplib
import logging
import smtplib
from email.mime.text import MIMEText

log = logging.getLogger("jarvis")

SERVIDORES = {
    "gmail.com": ("imap.gmail.com", "smtp.gmail.com"),
    "icloud.com": ("imap.mail.me.com", "smtp.mail.me.com"),
    "me.com": ("imap.mail.me.com", "smtp.mail.me.com"),
    "outlook.com": ("outlook.office365.com", "smtp.office365.com"),
    "hotmail.com": ("outlook.office365.com", "smtp.office365.com"),
    "yahoo.com": ("imap.mail.yahoo.com", "smtp.mail.yahoo.com"),
}


def _dec(valor):
    partes = []
    for texto, cod in email.header.decode_header(valor or ""):
        partes.append(texto.decode(cod or "utf-8", errors="replace") if isinstance(texto, bytes) else texto)
    return "".join(partes).strip()


def _cuerpo(msg):
    for parte in msg.walk() if msg.is_multipart() else [msg]:
        if parte.get_content_type() == "text/plain" and not parte.get_filename():
            datos = parte.get_payload(decode=True) or b""
            return datos.decode(parte.get_content_charset() or "utf-8", errors="replace")
    return ""


class Cuenta:
    def __init__(self, c):
        self.nombre = c.get("nombre", "correo")
        self.email = c.get("email", "").strip()
        self.clave = c.get("app_password", "").replace(" ", "")
        dominio = self.email.split("@")[-1].lower()
        imap, smtp = SERVIDORES.get(dominio, (None, None))
        self.imap = c.get("imap") or imap
        self.smtp = c.get("smtp") or smtp

    @property
    def lista(self):
        return bool(self.email and self.clave and self.imap)

    def _conectar(self):
        m = imaplib.IMAP4_SSL(self.imap, 993, timeout=20)
        m.login(self.email, self.clave)
        m.select("INBOX", readonly=True)
        return m

    def buscar(self, criterio="UNSEEN", maximo=8):
        m = self._conectar()
        try:
            _, ids = m.search(None, criterio)
            ids = ids[0].split()[-maximo:][::-1]
            correos = []
            for i in ids:
                _, datos = m.fetch(i, "(BODY.PEEK[])")
                msg = email.message_from_bytes(datos[0][1])
                correos.append({
                    "id": _dec(msg.get("Message-ID")) or f"{self.email}-{i.decode()}",
                    "cuenta": self.nombre,
                    "de": email.utils.parseaddr(_dec(msg.get("From")))[0] or _dec(msg.get("From")),
                    "asunto": _dec(msg.get("Subject")) or "(sin asunto)",
                    "fecha": _dec(msg.get("Date"))[:22],
                    "texto": " ".join(_cuerpo(msg).split())[:600],
                })
            return correos
        finally:
            m.logout()

    def enviar(self, para, asunto, cuerpo):
        msg = MIMEText(cuerpo, "plain", "utf-8")
        msg["From"], msg["To"], msg["Subject"] = self.email, para, asunto
        with smtplib.SMTP(self.smtp, 587, timeout=20) as s:
            s.starttls()
            s.login(self.email, self.clave)
            s.send_message(msg)


class Correo:
    def __init__(self, cuentas):
        self.cuentas = [Cuenta(c) for c in cuentas or []]

    def _elegir(self, cuenta=None):
        listas = [c for c in self.cuentas if c.lista]
        if cuenta:
            listas = [c for c in listas if cuenta.lower() in (c.nombre + c.email).lower()] or listas
        return listas

    def resumen(self, cuenta=None, solo_no_leidos=True, buscar=None, maximo=6):
        cuentas = self._elegir(cuenta)
        if not cuentas:
            return "No hay correos conectados (sección 'correo' en config.json)."
        criterio = f'(TEXT "{buscar}")' if buscar else ("UNSEEN" if solo_no_leidos else "ALL")
        salida = []
        for c in cuentas:
            try:
                cs = c.buscar(criterio, maximo)
                salida.append(f"{c.nombre.upper()} ({len(cs)}):" + ("".join(
                    f"\n- {x['de']}: {x['asunto']} — {x['texto'][:160]}" for x in cs) or " nada nuevo"))
            except Exception as e:
                log.warning("Correo %s falló: %s", c.email, e)
                salida.append(f"{c.nombre.upper()}: no pude conectar")
        return "\n\n".join(salida)

    def nuevos(self, maximo=15):
        """No leídos de hoy en todas las cuentas (para el vigilante)."""
        hoy = __import__("datetime").date.today().strftime("%d-%b-%Y")
        salida = []
        for c in self._elegir():
            try:
                salida += c.buscar(f'(UNSEEN SINCE "{hoy}")', maximo)
            except Exception as e:
                log.warning("Vigilante correo %s: %s", c.email, e)
        return salida

    def enviar(self, para, asunto, cuerpo, cuenta=None):
        cuentas = self._elegir(cuenta)
        if not cuentas:
            return "No hay correos conectados."
        cuentas[0].enviar(para, asunto, cuerpo)
        return f"Correo enviado a {para} desde {cuentas[0].email}."
