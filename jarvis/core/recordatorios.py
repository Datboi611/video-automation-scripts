"""Recordatorios persistentes con aviso en PC, notificación y llamada al teléfono."""
import datetime as dt
import json
import logging
import os
import threading
import time
import uuid

log = logging.getLogger("jarvis")
FMT = "%Y-%m-%d %H:%M"


class Recordatorios:
    def __init__(self, ruta, on_vencido):
        self.ruta = ruta
        self.on_vencido = on_vencido
        self._lock = threading.Lock()
        self.items = []
        if os.path.exists(ruta):
            with open(ruta, encoding="utf-8") as f:
                self.items = json.load(f)

    def _guardar(self):
        with open(self.ruta, "w", encoding="utf-8") as f:
            json.dump(self.items, f, ensure_ascii=False, indent=2)

    def crear(self, mensaje, cuando, llamar=False, repetir_diario=False):
        item = {
            "id": uuid.uuid4().hex[:6],
            "mensaje": mensaje,
            "cuando": cuando.strftime(FMT),
            "llamar": bool(llamar),
            "repetir_diario": bool(repetir_diario),
        }
        with self._lock:
            self.items.append(item)
            self._guardar()
        return item

    def listar(self):
        with self._lock:
            return sorted(self.items, key=lambda i: i["cuando"])

    def borrar(self, texto):
        with self._lock:
            antes = len(self.items)
            t = texto.lower()
            self.items = [i for i in self.items if i["id"] != texto and t not in i["mensaje"].lower()]
            self._guardar()
            return antes - len(self.items)

    def iniciar(self):
        threading.Thread(target=self._loop, daemon=True).start()

    def _loop(self):
        while True:
            ahora = dt.datetime.now()
            vencidos = []
            with self._lock:
                for i in list(self.items):
                    if dt.datetime.strptime(i["cuando"], FMT) <= ahora:
                        vencidos.append(dict(i))
                        if i["repetir_diario"]:
                            nuevo = dt.datetime.strptime(i["cuando"], FMT)
                            while nuevo <= ahora:
                                nuevo += dt.timedelta(days=1)
                            i["cuando"] = nuevo.strftime(FMT)
                        else:
                            self.items.remove(i)
                if vencidos:
                    self._guardar()
            for v in vencidos:
                try:
                    self.on_vencido(v)
                except Exception:
                    log.exception("Error avisando recordatorio")
            time.sleep(10)
