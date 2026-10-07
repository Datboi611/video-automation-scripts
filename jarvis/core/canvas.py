"""Canvas LMS (University of Utah: utah.instructure.com) con un token personal.
Canvas → Cuenta → Configuración → «+ Nuevo token de acceso»."""
import datetime as dt
import logging
import re
import webbrowser

import requests

log = logging.getLogger("jarvis")


def _limpio(html):
    return " ".join(re.sub(r"<[^>]+>", " ", html or "").split())


def _fecha(iso):
    if not iso:
        return None
    return dt.datetime.fromisoformat(iso.replace("Z", "+00:00")).astimezone().replace(tzinfo=None)


class Canvas:
    def __init__(self, url, token):
        self.url = (url or "https://utah.instructure.com").rstrip("/")
        self.token = (token or "").strip()
        self._cursos = None

    def _get(self, ruta, **params):
        r = requests.get(f"{self.url}/api/v1/{ruta}", headers={"Authorization": f"Bearer {self.token}"},
                         params={"per_page": 50, **params}, timeout=20)
        r.raise_for_status()
        return r.json()

    def cursos(self):
        if self._cursos is None:
            cs = self._get("courses", enrollment_state="active")
            self._cursos = {c["id"]: c.get("course_code") or c.get("name", "") for c in cs if not c.get("access_restricted_by_date")}
        return self._cursos

    # ---------- consultas ----------
    def pendientes(self):
        """Próximas entregas y lo que falta entregar."""
        salida = []
        for t in self._get("users/self/todo"):
            a = t.get("assignment") or {}
            salida.append({"id": f"todo-{a.get('id')}", "tipo": "tarea", "curso": self.cursos().get(t.get("course_id"), ""),
                           "titulo": a.get("name", t.get("title", "")), "fecha": _fecha(a.get("due_at")),
                           "url": a.get("html_url", "")})
        for a in self._get("users/self/missing_submissions", include=["course"]):
            salida.append({"id": f"falta-{a['id']}", "tipo": "falta", "curso": (a.get("course") or {}).get("course_code", ""),
                           "titulo": a["name"], "fecha": _fecha(a.get("due_at")), "url": a.get("html_url", "")})
        return salida

    def anuncios(self, dias=7):
        if not self.cursos():
            return []
        desde = (dt.date.today() - dt.timedelta(days=dias)).isoformat()
        datos = self._get("announcements", start_date=desde,
                          **{"context_codes[]": [f"course_{i}" for i in self.cursos()]})
        return [{"id": f"anuncio-{a['id']}", "tipo": "anuncio",
                 "curso": self.cursos().get(int(a.get("context_code", "course_0").split("_")[1]), ""),
                 "titulo": a["title"], "texto": _limpio(a.get("message"))[:400], "fecha": _fecha(a.get("posted_at")),
                 "url": a.get("html_url", "")} for a in datos]

    def novedades(self):
        """Stream de actividad: notas publicadas, mensajes, comentarios, tareas nuevas."""
        salida = []
        for e in self._get("users/self/activity_stream", only_active_courses=True):
            tipo = e.get("type")
            if tipo == "Submission" and e.get("score") is not None:
                titulo = f"Nota publicada: {(e.get('assignment') or {}).get('name', e.get('title', ''))} → {e.get('score')}"
            elif tipo in ("Conversation", "Message"):
                titulo = f"Mensaje: {e.get('title', '')}"
            elif tipo == "DiscussionTopic":
                titulo = f"Discusión: {e.get('title', '')}"
            else:
                continue
            salida.append({"id": f"act-{e['id']}-{e.get('updated_at', '')}", "tipo": tipo,
                           "curso": self.cursos().get(e.get("course_id"), ""), "titulo": titulo,
                           "texto": _limpio(e.get("message"))[:300], "fecha": _fecha(e.get("updated_at")),
                           "url": e.get("html_url", "")})
        return salida

    def texto(self, que="pendientes"):
        if not self.token:
            return "Canvas no está conectado."
        que = (que or "pendientes").lower()
        if "anunc" in que:
            items = self.anuncios()
        elif "nota" in que or "novedad" in que or "mensaje" in que:
            items = self.novedades()
        elif "curso" in que:
            return "Cursos: " + ", ".join(self.cursos().values())
        else:
            items = self.pendientes()
        if not items:
            return "Nada en Canvas para eso."
        lineas = []
        for i in items[:15]:
            f = i["fecha"].strftime("%a %d/%m %H:%M") if i.get("fecha") else ""
            extra = " (NO ENTREGADA)" if i["tipo"] == "falta" else ""
            lineas.append(f"[{i['curso']}] {i['titulo']}{extra} {f}".strip()
                          + (f" — {i['texto'][:150]}" if i.get("texto") else ""))
        return "\n".join(lineas)

    def abrir(self, busqueda=None):
        url = self.url
        if busqueda and self.token:
            b = busqueda.lower()
            for i in self.pendientes() + self.anuncios():
                if b in i["titulo"].lower() or b in i["curso"].lower():
                    url = i["url"] or url
                    break
            else:
                for cid, nombre in self.cursos().items():
                    if b in nombre.lower():
                        url = f"{self.url}/courses/{cid}"
                        break
        webbrowser.open(url)
        return "Abrí Canvas."
