"""Canvas LMS (University of Utah: utah.instructure.com).
Dos formas de entrar:
- Token personal (si la universidad lo permite).
- Sesión del navegador: el usuario inicia sesión una vez (uNID + Duo) en una ventana de Edge que abre JARVIS;
  JARVIS guarda esa sesión y la renueva solo en segundo plano mientras la universidad lo permita."""
import datetime as dt
import json
import logging
import os
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


class SesionExpirada(Exception):
    pass


class Canvas:
    def __init__(self, url, token, carpeta_datos=None):
        self.url = (url or "https://utah.instructure.com").rstrip("/")
        self.token = (token or "").strip()
        self._cursos = None
        self.carpeta = carpeta_datos or "."
        self.ruta_cookies = os.path.join(self.carpeta, "canvas_sesion.json")
        self.perfil = os.path.join(self.carpeta, "navegador_canvas")
        self.web = requests.Session()
        self.web.headers["User-Agent"] = "Mozilla/5.0 (Windows NT 10.0; Win64; x64) JARVIS"
        self._cargar_cookies()

    # ---------- sesión del navegador ----------
    @property
    def conectado(self):
        return bool(self.token or self.web.cookies)

    def _cargar_cookies(self):
        if os.path.exists(self.ruta_cookies):
            try:
                with open(self.ruta_cookies, encoding="utf-8") as f:
                    for c in json.load(f):
                        self.web.cookies.set(c["name"], c["value"], domain=c["domain"], path=c.get("path", "/"))
            except Exception as e:
                log.warning("Cookies de Canvas: %s", e)

    def iniciar_sesion(self, visible=True, espera=300):
        """Abre Edge con un perfil propio de JARVIS. Visible: el usuario inicia sesión (uNID + Duo).
        Invisible: reutiliza la sesión guardada para renovar las cookies sin molestar."""
        from playwright.sync_api import sync_playwright
        with sync_playwright() as p:
            ctx = None
            exe = os.environ.get("JARVIS_NAVEGADOR")
            opciones = ([{"executable_path": exe}] if exe else []) + [{"channel": "msedge"}, {"channel": "chrome"}, {}]
            for op in opciones:
                try:
                    ctx = p.chromium.launch_persistent_context(self.perfil, headless=not visible,
                                                               viewport={"width": 1100, "height": 800}, **op)
                    break
                except Exception as e:
                    log.warning("Navegador %s no disponible: %s", op, str(e)[:120])
            if ctx is None:
                raise RuntimeError("No encontré Edge ni Chrome.")
            try:
                pagina = ctx.pages[0] if ctx.pages else ctx.new_page()
                pagina.goto(self.url, wait_until="domcontentloaded", timeout=60000)
                limite = dt.datetime.now() + dt.timedelta(seconds=espera if visible else 25)
                while dt.datetime.now() < limite:
                    u = pagina.url
                    if u.startswith(self.url) and "/login" not in u:
                        try:
                            pagina.wait_for_selector("#application, #dashboard, .ic-app", timeout=5000)
                        except Exception:
                            pass
                        host = self.url.split("//")[1].split("/")[0].split(":")[0]
                        cookies = [c for c in ctx.cookies() if "instructure" in c["domain"] or
                                   c["domain"].lstrip(".") in host or host.endswith(c["domain"].lstrip("."))]
                        os.makedirs(self.carpeta, exist_ok=True)
                        with open(self.ruta_cookies, "w", encoding="utf-8") as f:
                            json.dump(cookies, f)
                        self.web.cookies.clear()
                        self._cargar_cookies()
                        self._cursos = None
                        return True
                    pagina.wait_for_timeout(1500)
                return False
            finally:
                ctx.close()

    def _get(self, ruta, **params):
        params = {"per_page": 50, **params}
        if self.token:
            r = requests.get(f"{self.url}/api/v1/{ruta}", headers={"Authorization": f"Bearer {self.token}"},
                             params=params, timeout=20)
            r.raise_for_status()
            return r.json()
        for intento in range(2):
            r = self.web.get(f"{self.url}/api/v1/{ruta}", params=params, timeout=20, allow_redirects=False)
            if r.status_code == 200:
                texto = r.text
                if texto.startswith("while(1);"):  # Canvas protege el JSON en sesiones de navegador
                    texto = texto[len("while(1);"):]
                return json.loads(texto)
            if intento == 0 and r.status_code in (301, 302, 401, 403):
                try:  # renovar la sesión en segundo plano, sin ventana
                    if self.iniciar_sesion(visible=False):
                        continue
                except Exception as e:
                    log.warning("No pude renovar la sesión de Canvas: %s", e)
            raise SesionExpirada("La sesión de Canvas expiró")
        raise SesionExpirada("La sesión de Canvas expiró")

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
        if not self.conectado:
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
        if busqueda and self.conectado:
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
