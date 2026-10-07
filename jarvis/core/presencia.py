"""¿Está el usuario en casa? Detecta si su iPhone está conectado al mismo WiFi que el PC.
Usa la 'Dirección Wi-Fi' (MAC) del teléfono y la tabla ARP de Windows. Sin apps ni costo.
El iPhone duerme su WiFi a ratos, por eso solo se considera 'fuera' tras varios minutos sin verlo."""
import ipaddress
import logging
import re
import socket
import subprocess
import sys
import threading
import time

log = logging.getLogger("jarvis")
SIN_VENTANA = 0x08000000 if sys.platform == "win32" else 0


def normalizar_mac(mac):
    limpio = re.sub(r"[^0-9a-f]", "", (mac or "").lower())
    return "-".join(limpio[i:i + 2] for i in range(0, 12, 2)) if len(limpio) == 12 else ""


def tabla_arp():
    """{mac: ip} de los dispositivos vistos recientemente en la red."""
    try:
        salida = subprocess.run(["arp", "-a"], capture_output=True, text=True, timeout=10,
                                creationflags=SIN_VENTANA).stdout
    except Exception:
        return {}
    tabla = {}
    for ip, mac in re.findall(r"(\d+\.\d+\.\d+\.\d+)\s+([0-9a-fA-F]{2}(?:[-:][0-9a-fA-F]{2}){5})", salida):
        tabla[normalizar_mac(mac)] = ip
    return tabla


def ip_local():
    s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    try:
        s.connect(("8.8.8.8", 80))
        return s.getsockname()[0]
    finally:
        s.close()


def tocar_red():
    """Envía un paquete UDP vacío a cada IP de la red local: obliga a Windows a resolver su ARP."""
    try:
        red = ipaddress.ip_network(ip_local() + "/24", strict=False)
    except Exception:
        return
    s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    for ip in red.hosts():
        try:
            s.sendto(b"", (str(ip), 5353))
        except OSError:
            pass
    s.close()


class Presencia:
    def __init__(self, cfg, al_salir, al_volver):
        self.cfg = cfg.setdefault("presencia", {})
        self.al_salir, self.al_volver = al_salir, al_volver
        self.ultima_vez = time.time()
        self.presente = True
        self.ip = None

    @property
    def mac(self):
        return normalizar_mac(self.cfg.get("telefono_mac", ""))

    def iniciar(self):
        threading.Thread(target=self._loop, daemon=True).start()

    def visto(self):
        if not self.mac:
            return True
        if self.ip:  # primero, solo la IP conocida (rápido)
            try:
                subprocess.run(["ping", "-n" if sys.platform == "win32" else "-c", "1", "-w", "800", self.ip],
                               capture_output=True, timeout=5, creationflags=SIN_VENTANA)
            except Exception:
                pass
        tabla = tabla_arp()
        if self.mac not in tabla:
            tocar_red()
            time.sleep(2)
            tabla = tabla_arp()
        if self.mac in tabla:
            self.ip = tabla[self.mac]
            return True
        return False

    def revisar(self):
        if not self.mac:
            self.presente = True
        elif self.visto():
            self.ultima_vez = time.time()
            if not self.presente:
                self.presente = True
                log.info("Teléfono de vuelta en casa")
                self.al_volver()
        elif self.presente and time.time() - self.ultima_vez > self.cfg.get("minutos_ausencia", 10) * 60:
            self.presente = False
            log.info("Teléfono fuera de la red: modo silencioso")
            self.al_salir()

    def _loop(self):
        while True:
            try:
                self.revisar()
            except Exception:
                log.exception("Presencia")
            time.sleep(45)
