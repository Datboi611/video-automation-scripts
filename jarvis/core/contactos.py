"""Agenda de contactos de JARVIS: se importa desde un archivo .vcf (iPhone / iCloud / Google) y se usa para
llamar a cualquier persona y darle un recado con la voz de JARVIS."""
import difflib
import glob
import json
import os
import re
import unicodedata


def _norm(t):
    t = unicodedata.normalize("NFD", (t or "").lower())
    return re.sub(r"\s+", " ", "".join(c for c in t if unicodedata.category(c) != "Mn")).strip()


class Contactos:
    def __init__(self, carpeta_datos):
        self.ruta = os.path.join(carpeta_datos, "contactos.json")
        try:
            with open(self.ruta, encoding="utf-8") as f:
                self.lista = json.load(f)
        except Exception:
            self.lista = []

    def _guardar(self):
        with open(self.ruta, "w", encoding="utf-8") as f:
            json.dump(self.lista, f, ensure_ascii=False, indent=1)

    def agregar(self, nombre, numero):
        numero = re.sub(r"[^\d+]", "", numero)
        self.lista = [c for c in self.lista if _norm(c["nombre"]) != _norm(nombre)]
        self.lista.append({"nombre": nombre.strip(), "numeros": [numero]})
        self._guardar()

    def importar_vcf(self, ruta):
        texto = open(ruta, encoding="utf-8", errors="replace").read()
        texto = re.sub(r"\r?\n[ \t]", "", texto)  # líneas continuadas del formato vCard
        nuevos = 0
        for tarjeta in re.findall(r"BEGIN:VCARD(.*?)END:VCARD", texto, re.S | re.I):
            nombre = re.search(r"^FN[^:]*:(.+)$", tarjeta, re.M | re.I)
            if not nombre:
                n = re.search(r"^N[^:]*:(.+)$", tarjeta, re.M | re.I)
                partes = n.group(1).split(";") if n else []
                nombre_txt = " ".join(p for p in (partes[1:2] + partes[:1]) if p).strip()
            else:
                nombre_txt = nombre.group(1).strip()
            tels = [re.sub(r"[^\d+]", "", t) for t in re.findall(r"^(?:item\d+\.)?TEL[^:]*:(.+)$", tarjeta, re.M | re.I)]
            tels = [t for t in tels if len(re.sub(r"\D", "", t)) >= 7]
            if nombre_txt and tels:
                self.lista = [c for c in self.lista if _norm(c["nombre"]) != _norm(nombre_txt)]
                self.lista.append({"nombre": nombre_txt, "numeros": list(dict.fromkeys(tels))})
                nuevos += 1
        self._guardar()
        return nuevos

    def importar_auto(self):
        """Busca el .vcf más reciente en Descargas, Escritorio y Documentos (y OneDrive)."""
        casa = os.path.expanduser("~")
        carpetas = ["Downloads", "Descargas", "Desktop", "Escritorio", "Documents", "Documentos",
                    os.path.join("OneDrive", "Desktop"), os.path.join("OneDrive", "Escritorio"),
                    os.path.join("OneDrive", "Documents"), os.path.join("OneDrive", "Documentos")]
        archivos = [a for c in carpetas for a in glob.glob(os.path.join(casa, c, "*.vcf"))]
        if not archivos:
            return None, 0
        ruta = max(archivos, key=os.path.getmtime)
        return ruta, self.importar_vcf(ruta)

    def buscar(self, nombre):
        """Contacto más parecido al nombre dicho (tolera apodos parciales y errores de dictado)."""
        objetivo = _norm(nombre)
        mejor, puntaje = None, 0.0
        for c in self.lista:
            n = _norm(c["nombre"])
            if n == objetivo:
                return c
            p = difflib.SequenceMatcher(None, n, objetivo).ratio()
            if objetivo in n.split() or n.startswith(objetivo):
                p = max(p, 0.9)
            if p > puntaje:
                mejor, puntaje = c, p
        return mejor if puntaje >= 0.7 else None


def internacional(numero):
    """Número con código de país. Sin código: 9 dígitos que empiezan en 9 = celular de Perú (+51);
    10 dígitos = EE. UU. (+1). Con 00 delante se toma como prefijo internacional."""
    n = re.sub(r"[^\d+]", "", numero or "")
    if n.startswith("+"):
        return n
    if n.startswith("00"):
        return "+" + n[2:]
    if len(n) == 9 and n.startswith("9"):
        return "+51" + n
    if len(n) == 11 and n.startswith("51"):
        return "+" + n
    if len(n) == 10:
        return "+1" + n
    if len(n) == 11 and n.startswith("1"):
        return "+" + n
    return "+" + n
