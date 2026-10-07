"""Vigilante: revisa la agenda sin que se lo pidas.
- Resumen matutino al teléfono.
- Aviso antes de cada evento del calendario.
- Revisiones durante el día de lo que vence hoy o está atrasado.
- Llamada por teléfono si a la hora de llamada sigue algo importante sin hacer."""
import datetime as dt
import json
import logging
import os
import re
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
        self._ultimo = {}
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
        corte = (dt.date.today() - dt.timedelta(days=30)).isoformat()
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

    def _avisar(self, texto, urgente=False, voz=None):
        """Telegram si está vinculado (si no, ntfy) y además lo DICE en voz alta en el PC, sin esperar a que le hablen."""
        if not self.j.bot or not self.j.bot.enviar(texto):
            try:
                self.j.telefono.notificar(texto, "JARVIS", 5 if urgente else 3)
            except Exception:
                pass
        if voz is not False and not self._silencio(dt.datetime.now()):
            hablado = voz or re.sub(r"[^\w\s,.:;¿?¡!áéíóúñÁÉÍÓÚÑ()/-]", "", texto.split("\n")[0]).strip()
            try:  # solo habla si el usuario está en casa (si no, lo guarda para cuando vuelva)
                threading.Thread(target=self.j.avisar_por_voz, args=(hablado,), daemon=True).start()
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
            voz = (f"Buenos días, {trat}. Hoy tiene {len(de_hoy)} pendientes"
                   + (f" y {len(venc)} atrasados; sugiero empezar por {(venc or de_hoy)[0]['x']}." if venc
                      else (f"; lo primero es {de_hoy[0]['x']}." if de_hoy else ". Un día sorprendentemente civilizado.")))
            self._avisar("\n".join(lineas), voz=voz)

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
                                     + (f" ({e['lugar']})" if e["lugar"] else ""), urgente=True,
                                     voz=f"{trat.capitalize()}, en {int(falta)} minutos tiene {e['titulo']}.")
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
                    self._avisar(f"{trat.capitalize()}, recordatorio amistoso. " + " | ".join(partes),
                                 voz=f"{trat.capitalize()}, recordatorio amistoso: " + ". ".join(partes)[:300])

        # 4. Correo: solo lo importante
        cada = int(c.get("correo_cada_min", 15)) * 60
        if time.time() - self._ultimo.get("correo", 0) >= cada:
            self._ultimo["correo"] = time.time()
            self._revisar_correo(trat)

        # 5. Canvas: tareas nuevas, anuncios, notas, entregas faltantes
        cada = int(c.get("canvas_cada_min", 30)) * 60
        if time.time() - self._ultimo.get("canvas", 0) >= cada:
            self._ultimo["canvas"] = time.time()
            self._revisar_canvas(trat)

        # 6. Tareas nuevas en Todoist (las que agregas desde el celular u otro lado)
        if time.time() - self._ultimo.get("todoist", 0) >= 600:
            self._ultimo["todoist"] = time.time()
            self._revisar_todoist(trat)

        # 7. Llamada si a la hora de llamada sigue algo importante pendiente
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
                self._avisar("📞 " + msg, urgente=True, voz=msg)

    def _revisar_correo(self, trat):
        correo = self.j.herramientas.agenda.get("correo")
        if not correo or not correo._elegir():
            return
        nuevos = [m for m in correo.nuevos() if m["id"] not in self.hechos]
        if not nuevos:
            return
        for m in nuevos:
            self._ya(m["id"])
        lista = "\n".join(f"{i}. [{m['cuenta']}] De: {m['de']} | Asunto: {m['asunto']} | {m['texto'][:200]}"
                          for i, m in enumerate(nuevos, 1))
        criterio = self.cfg.get("correo_importante", "")
        respuesta = self.j.cerebro.completar(
            "Eres el filtro de correo de un estudiante universitario y emprendedor. De estos correos nuevos, "
            "elige SOLO los importantes (profesores, universidad, trámites, bancos, pedidos/clientes, trabajo, "
            "entrevistas, fechas límite, personas reales que esperan respuesta). Ignora publicidad, newsletters "
            f"y notificaciones automáticas. {criterio}\nResponde una línea por correo importante con el formato "
            "'N: resumen de una frase en español'. Si ninguno es importante responde exactamente NINGUNO.\n\n" + lista)
        if not respuesta or "NINGUNO" in respuesta.upper():
            return
        import re
        respuesta = "\n".join("• " + re.sub(r"^\s*\d+[:.)-]\s*", "", l) for l in respuesta.splitlines() if l.strip())
        primeros = [l.lstrip("• ") for l in respuesta.splitlines()[:2]]
        self._avisar(f"📧 {trat.capitalize()}, correo importante:\n{respuesta}", urgente=True,
                     voz=f"{trat.capitalize()}, correo importante. " + " ".join(primeros))
        self.j.ui("panel", "Correo importante", [{"t": "Nuevos", "tono": "warn", "items": [
            {"x": l.lstrip("• "), "sub": "", "tags": []} for l in respuesta.splitlines() if l.strip()]}])

    def _revisar_canvas(self, trat):
        from .canvas import SesionExpirada
        cv = self.j.herramientas.agenda.get("canvas")
        if not cv or not cv.conectado:
            return
        nuevos = []
        try:
            items = cv.pendientes() + cv.anuncios(dias=3) + cv.novedades()
        except SesionExpirada:
            if not self._ya(f"canvas-sesion-{dt.date.today()}"):
                self._avisar(f"🎓 {trat.capitalize()}, la universidad cerró la sesión de Canvas. "
                             "Cuando esté en el PC, dígame «inicia sesión en Canvas» y apruebe Duo.")
            return
        except Exception as e:
            log.warning("Vigilante Canvas: %s", e)
            return
        primera = not any(k.startswith("cv-") for k in self.hechos)
        for i in items:
            if not self._ya("cv-" + i["id"]) and not primera:
                nuevos.append(i)
        if not nuevos:
            return  # la primera vez solo memoriza lo que ya existe, sin avisar de todo
        lineas = []
        for i in nuevos[:10]:
            etiqueta = {"anuncio": "📢", "falta": "⚠️ Sin entregar:", "tarea": "📝"}.get(i["tipo"], "🎓")
            f = f" (vence {i['fecha']:%d/%m %H:%M})" if i.get("fecha") and i["tipo"] in ("tarea", "falta") else ""
            lineas.append(f"{etiqueta} [{i['curso']}] {i['titulo']}{f}")
        dicho = "; ".join(f"{i['titulo']} de {i['curso']}" for i in nuevos[:2])
        self._avisar(f"🎓 {trat.capitalize()}, novedades en Canvas:\n" + "\n".join(lineas),
                     voz=f"{trat.capitalize()}, novedades en Canvas: {dicho}" + (f", y {len(nuevos) - 2} más." if len(nuevos) > 2 else "."))
        self.j.ui("panel", "Canvas", [{"t": "Novedades", "tono": "info", "items": [
            {"x": i["titulo"], "sub": i["curso"], "tags": [[i["tipo"], "warn" if i["tipo"] == "falta" else "info"]]}
            for i in nuevos[:10]]}])

    def _revisar_todoist(self, trat):
        tod = self.j.herramientas.agenda.get("todoist")
        if not tod or not tod.token:
            return
        try:
            tareas = tod.todas() or []
        except Exception as e:
            log.warning("Vigilante Todoist: %s", e)
            return
        primera = not any(k.startswith("td-") for k in self.hechos)
        nuevas = [t for t in tareas if not self._ya(f"td-{t['id']}") and not primera]
        if nuevas:
            nombres = ", ".join(t["content"] for t in nuevas[:3])
            self._avisar(f"📝 {trat.capitalize()}, tarea nueva en Todoist: {nombres}",
                         voz=f"{trat.capitalize()}, anoté una tarea nueva en su lista: {nombres}.")
