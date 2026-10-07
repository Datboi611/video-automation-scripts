"""Agenda del usuario: Google Calendar (enlace iCal secreto), Todoist y pendientes personales."""
import datetime as dt
import json
import logging
import os
import threading
import urllib.parse
import uuid
import webbrowser

import requests

log = logging.getLogger("jarvis")
DIAS = ["lunes", "martes", "miércoles", "jueves", "viernes", "sábado", "domingo"]


def _dia(d):
    hoy = dt.date.today()
    n = (d - hoy).days
    if n == 0:
        return "hoy"
    if n == 1:
        return "mañana"
    if n == -1:
        return "ayer"
    return f"{DIAS[d.weekday()]} {d.day}/{d.month}"


# ---------------- Google Calendar ----------------
class Calendario:
    def __init__(self, url_ics):
        self.url = (url_ics or "").strip()

    def eventos(self, dias=1, desde=None):
        if not self.url:
            return None
        import icalendar
        import recurring_ical_events

        r = requests.get(self.url, timeout=15)
        r.raise_for_status()
        cal = icalendar.Calendar.from_ical(r.content)
        inicio = desde or dt.date.today()
        fin = inicio + dt.timedelta(days=dias)
        salida = []
        for ev in recurring_ical_events.of(cal).between(inicio, fin):
            ini = ev.get("DTSTART").dt
            todo_el_dia = not isinstance(ini, dt.datetime)
            if not todo_el_dia and ini.tzinfo:
                ini = ini.astimezone().replace(tzinfo=None)
            salida.append({
                "titulo": str(ev.get("SUMMARY", "(sin título)")),
                "inicio": ini,
                "todo_el_dia": todo_el_dia,
                "lugar": str(ev.get("LOCATION", "") or ""),
            })
        salida.sort(key=lambda e: (e["inicio"] if isinstance(e["inicio"], dt.datetime)
                                   else dt.datetime.combine(e["inicio"], dt.time())))
        return salida

    def texto(self, dias=1):
        evs = self.eventos(dias)
        if evs is None:
            return "Google Calendar no está conectado (falta 'google_calendar_ics' en config.json)."
        if not evs:
            return "Sin eventos en el calendario."
        lineas = []
        for e in evs:
            d = e["inicio"]
            fecha = _dia(d.date() if isinstance(d, dt.datetime) else d)
            hora = "todo el día" if e["todo_el_dia"] else d.strftime("%H:%M")
            lineas.append(f"{fecha} {hora}: {e['titulo']}" + (f" ({e['lugar']})" if e["lugar"] else ""))
        return "\n".join(lineas)

    @staticmethod
    def agregar(titulo, inicio, duracion_min=60, detalles=""):
        """Abre Google Calendar con el evento prellenado (el usuario solo pulsa Guardar)."""
        fin = inicio + dt.timedelta(minutes=duracion_min)
        f = "%Y%m%dT%H%M%S"
        url = "https://calendar.google.com/calendar/render?" + urllib.parse.urlencode({
            "action": "TEMPLATE", "text": titulo, "details": detalles,
            "dates": f"{inicio.strftime(f)}/{fin.strftime(f)}"})
        webbrowser.open(url)
        return "Abrí Google Calendar con el evento listo; solo pulsa Guardar."


# ---------------- Todoist ----------------
class Todoist:
    API = "https://api.todoist.com/api/v1"

    def __init__(self, token):
        self.token = (token or "").strip()

    def _h(self):
        return {"Authorization": f"Bearer {self.token}"}

    def tareas(self, filtro="today | overdue"):
        if not self.token:
            return None
        r = requests.get(f"{self.API}/tasks/filter", headers=self._h(), timeout=15,
                         params={"query": filtro, "lang": "es", "limit": 100})
        r.raise_for_status()
        datos = r.json()
        return datos.get("results", datos) if isinstance(datos, dict) else datos

    def texto(self, filtro="today | overdue"):
        ts = self.tareas(filtro)
        if ts is None:
            return "Todoist no está conectado (falta 'todoist_token' en config.json)."
        if not ts:
            return "Sin tareas en Todoist para ese filtro."
        lineas = []
        for t in ts:
            due = (t.get("due") or {}).get("date", "")[:10]
            cuando = ""
            if due:
                d = dt.date.fromisoformat(due)
                cuando = ("VENCIDA " if d < dt.date.today() else "") + _dia(d) + ": "
            lineas.append(f"{cuando}{t['content']}" + (" (prioridad alta)" if t.get("priority", 1) >= 3 else ""))
        return "\n".join(lineas)

    def agregar(self, contenido, fecha=None):
        if not self.token:
            return "Todoist no está conectado."
        datos = {"content": contenido}
        if fecha:
            datos.update({"due_string": fecha, "due_lang": "es"})
        r = requests.post(f"{self.API}/tasks", headers=self._h(), json=datos, timeout=15)
        r.raise_for_status()
        return f"Tarea creada en Todoist: {contenido}."

    def completar(self, texto):
        ts = self.tareas(f"search: {texto}") or []
        if not ts:
            return f"No encontré en Todoist una tarea con '{texto}'."
        t = ts[0]
        r = requests.post(f"{self.API}/tasks/{t['id']}/close", headers=self._h(), timeout=15)
        r.raise_for_status()
        return f"Completada en Todoist: {t['content']}."


# ---------------- Pendientes personales ----------------
class Pendientes:
    """Lista propia de pendientes por proyecto (importada del Panel Personal)."""

    def __init__(self, ruta):
        self.ruta = ruta
        self._lock = threading.Lock()
        self.items = []
        if os.path.exists(ruta):
            with open(ruta, encoding="utf-8") as f:
                self.items = json.load(f)

    def _guardar(self):
        with open(self.ruta, "w", encoding="utf-8") as f:
            json.dump(self.items, f, ensure_ascii=False, indent=2)

    def abiertos(self):
        return [i for i in self.items if not i.get("hecho")]

    def texto(self, proyecto=None, solo_urgentes=False):
        its = self.abiertos()
        if proyecto:
            p = proyecto.lower()
            its = [i for i in its if p in i.get("proyecto", "").lower()]
        if solo_urgentes:
            limite = (dt.date.today() + dt.timedelta(days=2)).isoformat()
            its = [i for i in its if (i.get("fecha") and i["fecha"] <= limite) or i.get("prioridad") == "alta"]
        if not its:
            return "No hay pendientes personales" + (f" en {proyecto}." if proyecto else ".")
        orden = {"alta": 0, "media": 1, "baja": 2}
        its.sort(key=lambda i: (i.get("fecha") or "9999", orden.get(i.get("prioridad"), 3)))
        lineas = []
        for i in its:
            f = ""
            if i.get("fecha"):
                d = dt.date.fromisoformat(i["fecha"])
                f = ("VENCIDO " if d < dt.date.today() else "") + _dia(d) + ": "
            lineas.append(f"[{i['proyecto']}] {f}{i['texto']}" + (" (alta)" if i.get("prioridad") == "alta" else ""))
        return "\n".join(lineas)

    def agregar(self, texto, proyecto="General", fecha=None, prioridad="media"):
        with self._lock:
            self.items.append({"id": uuid.uuid4().hex[:6], "proyecto": proyecto, "texto": texto,
                               "fecha": fecha, "prioridad": prioridad, "hecho": False})
            self._guardar()
        return f"Pendiente agregado en {proyecto}."

    def completar(self, texto):
        t = texto.lower()
        with self._lock:
            hechos = [i for i in self.abiertos() if t in i["texto"].lower()]
            for i in hechos[:1]:
                i["hecho"] = True
            self._guardar()
        return f"Marcado como hecho: {hechos[0]['texto']}." if hechos else f"No encontré un pendiente con '{texto}'."
