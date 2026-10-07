"""Vigilante: revisa la agenda sin que se lo pidas.
- Resumen matutino al teléfono.
- Aviso antes de cada evento del calendario.
- Revisiones durante el día de lo que vence hoy o está atrasado.
- Llamada por teléfono si a la hora de llamada sigue algo importante sin hacer."""
import datetime as dt
import json
import logging
import os
import threading
import time

log = logging.getLogger("jarvis")


def _hm(texto):
    h, m = texto.split(":")
    return dt.time(int(h), int(m))


class Vigilante:
    def __init__(self, cfg, jarvis, ruta):
        self.cfg = cfg.setdefault("vigilante", {})
        self.j = jarvis
        self.ruta = ruta
        self.hechos = {}
        if os.path.exists(ruta):
            try:
                with open(ruta, encoding="utf-8") as f:
                    self.hechos = json.load(f)
            except Exception:
                self.hechos = {}

    def _ya(self, clave):
        if clave in self.hechos:
            return True
        self.hechos[clave] = dt.datetime.now().isoformat(timespec="minutes")
        corte = (dt.date.today() - dt.timedelta(days=3)).isoformat()
        self.hechos = {k: v for k, v in self.hechos.items() if v >= corte}
        with open(self.ruta, "w", encoding="utf-8") as f:
            json.dump(self.hechos, f)
        return False

    def iniciar(self):
        threading.Thread(target=self._loop, daemon=True).start()

    def _loop(self):
        time.sleep(60)
        while True:
            try:
                self.revisar()
            except Exception:
                log.exception("Vigilante")
            time.sleep(120)

    def _silencio(self, ahora):
        ini, fin = (_hm(x) for x in self.cfg.get("silencio", ["23:00", "07:30"]))
        t = ahora.time()
        return t >= ini or t < fin if ini > fin else ini <= t < fin

    def _avisar(self, texto, urgente=False):
        """Telegram si está vinculado; si no, notificación ntfy. En el PC lo dice en voz alta."""
        if not self.j.bot or not self.j.bot.enviar(texto):
            try:
                self.j.telefono.notificar(texto, "JARVIS", 5 if urgente else 3)
            except Exception:
                pass

    def _pendientes_hoy(self):
        from . import paneles
        hoy = dt.date.today()
        tareas = paneles._tareas(self.j.herramientas, 1)
        venc = [t for t in tareas if t["fecha"] and t["fecha"] < hoy]
        de_hoy = [t for t in tareas if t["fecha"] == hoy]
        return venc, de_hoy

    def revisar(self):
        ahora = dt.datetime.now()
        hoy = ahora.date().isoformat()
        c = self.cfg
        trat = self.j.cfg["tratamiento"]

        # 1. Resumen matutino
        if ahora.time() >= _hm(c.get("resumen_matutino", "08:00")) and not self._ya(f"resumen-{hoy}"):
            venc, de_hoy = self._pendientes_hoy()
            lineas = [f"Buenos días, {trat}. Su día:"]
            cal = self.j.herramientas.agenda.get("calendario")
            if cal and cal.url:
                try:
                    lineas += [f"📅 {e['inicio'].strftime('%H:%M') if not e['todo_el_dia'] else 'Todo el día'} {e['titulo']}"
                               for e in cal.eventos(1)]
                except Exception:
                    pass
            lineas += [f"⏰ HOY: {t['x']}" for t in de_hoy]
            lineas += [f"⚠️ ATRASADO: {t['x']}" for t in venc[:8]]
            if len(lineas) == 1:
                lineas.append("Nada urgente. Un día sorprendentemente civilizado.")
            self._avisar("\n".join(lineas))

        # 2. Aviso antes de eventos del calendario
        cal = self.j.herramientas.agenda.get("calendario")
        if cal and cal.url and not self._silencio(ahora):
            try:
                margen = int(c.get("aviso_eventos_min", 30))
                for e in cal.eventos(1):
                    if e["todo_el_dia"]:
                        continue
                    falta = (e["inicio"] - ahora).total_seconds() / 60
                    if 0 < falta <= margen and not self._ya(f"ev-{e['titulo']}-{e['inicio']:%Y%m%d%H%M}"):
                        self._avisar(f"🔔 {trat}, en {int(falta)} min: {e['titulo']}"
                                     + (f" ({e['lugar']})" if e["lugar"] else ""), urgente=True)
                        self.j.decir(f"{trat.capitalize()}, en {int(falta)} minutos tiene {e['titulo']}.")
            except Exception as ex:
                log.warning("Vigilante calendario: %s", ex)

        # 3. Revisiones del día
        for h in c.get("revisiones", ["14:00", "19:00"]):
            if ahora.time() >= _hm(h) and not self._ya(f"rev-{hoy}-{h}"):
                venc, de_hoy = self._pendientes_hoy()
                if de_hoy or venc:
                    partes = []
                    if de_hoy:
                        partes.append("Vence hoy: " + "; ".join(t["x"] for t in de_hoy[:5]))
                    if venc:
                        partes.append(f"Atrasado ({len(venc)}): " + "; ".join(t["x"] for t in venc[:3]))
                    self._avisar(f"{trat.capitalize()}, recordatorio amistoso. " + " | ".join(partes))

        # 4. Llamada si a la hora de llamada sigue algo importante pendiente
        if (c.get("llamar_si_pendiente", True) and ahora.time() >= _hm(c.get("hora_llamada", "20:30"))
                and not self._silencio(ahora) and not self._ya(f"llamada-{hoy}")):
            venc, de_hoy = self._pendientes_hoy()
            importantes = [t for t in de_hoy if t.get("pri") == "alta"] or de_hoy
            if importantes:
                lista = ", ".join(t["x"] for t in importantes[:3])
                msg = f"{trat.capitalize()}, le habla JARVIS. Aún tiene pendiente para hoy: {lista}."
                try:
                    r = self.j.telefono.llamar(msg)
                    log.info("Llamada: %s", r)
                except Exception as e:
                    log.warning("No pude llamar: %s", e)
                self._avisar("📞 " + msg, urgente=True)
