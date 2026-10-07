"""Convierte la agenda en paneles por secciones para el menú lateral.
Formato: [{"t": título, "tono": crit|warn|ok|info, "items": [{"x": texto, "sub": detalle, "tags": [[texto, tono]]}]}]"""
import datetime as dt
import logging

log = logging.getLogger("jarvis")
DIAS = ["lun", "mar", "mié", "jue", "vie", "sáb", "dom"]


def _cuando(fecha):
    hoy = dt.date.today()
    n = (fecha - hoy).days
    if n < 0:
        return ("hace %d d" % -n if n < -1 else "ayer"), "crit"
    if n == 0:
        return "hoy", "warn"
    if n == 1:
        return "mañana", "info"
    return f"{DIAS[fecha.weekday()]} {fecha.day}", "info"


def _tareas(herr, dias):
    """Une Todoist y pendientes personales en una sola lista con fecha y origen."""
    tareas = []
    pen = herr.agenda.get("pendientes")
    if pen:
        for i in pen.abiertos():
            tareas.append({"x": i["texto"], "proyecto": i.get("proyecto", ""), "pri": i.get("prioridad"),
                           "fecha": dt.date.fromisoformat(i["fecha"]) if i.get("fecha") else None})
    tod = herr.agenda.get("todoist")
    if tod and tod.token:
        try:
            for t in tod.tareas(f"overdue | {max(1, dias)} days") or []:
                d = (t.get("due") or {}).get("date", "")[:10]
                tareas.append({"x": t["content"], "proyecto": "Todoist",
                               "pri": "alta" if t.get("priority", 1) >= 3 else None,
                               "fecha": dt.date.fromisoformat(d) if d else None})
        except Exception as e:
            log.warning("Todoist en panel: %s", e)
    return tareas


def _item(t):
    tags = []
    if t["fecha"]:
        tags.append(list(_cuando(t["fecha"])))
    if t.get("pri") == "alta":
        tags.append(["alta", "warn"])
    return {"x": t["x"], "sub": t.get("proyecto", ""), "tags": tags}


def agenda(herr, dias=1):
    hoy = dt.date.today()
    tareas = _tareas(herr, dias)
    secciones = []
    venc = [t for t in tareas if t["fecha"] and t["fecha"] < hoy]
    de_hoy = [t for t in tareas if t["fecha"] == hoy]
    prox = sorted([t for t in tareas if t["fecha"] and hoy < t["fecha"] <= hoy + dt.timedelta(days=max(dias, 3))],
                  key=lambda t: t["fecha"])
    alta = [t for t in tareas if not t["fecha"] and t.get("pri") == "alta"]
    cal = herr.agenda.get("calendario")
    if cal and cal.url:
        try:
            evs = cal.eventos(max(1, dias))
            secciones.append({"t": "Calendario", "tono": "info", "items": [
                {"x": e["titulo"], "sub": e["lugar"],
                 "tags": [["todo el día" if e["todo_el_dia"] else e["inicio"].strftime("%H:%M"), "info"]]}
                for e in evs] or [{"x": "Sin eventos", "sub": "", "tags": []}]})
        except Exception as e:
            log.warning("Calendario en panel: %s", e)
    for titulo, lista, tono in (("Atrasado", venc, "crit"), ("Hoy", de_hoy, "warn"),
                                ("Próximos días", prox, "info"), ("Prioridad alta sin fecha", alta[:8], "warn")):
        if lista:
            secciones.append({"t": titulo, "tono": tono, "items": [_item(t) for t in lista]})
    rec = herr.recordatorios.listar() if herr.recordatorios else []
    if rec:
        secciones.append({"t": "Recordatorios", "tono": "ok", "items": [
            {"x": r["mensaje"], "sub": "", "tags": [[r["cuando"][5:].replace("-", "/"), "info"]]} for r in rec[:6]]})
    return secciones or [{"t": "Todo al día", "tono": "ok", "items": [{"x": "No hay nada pendiente", "sub": "", "tags": []}]}]


def por_proyecto(herr, proyecto=None):
    grupos = {}
    for t in _tareas(herr, 7):
        if proyecto and proyecto.lower() not in t["proyecto"].lower():
            continue
        grupos.setdefault(t["proyecto"] or "General", []).append(t)
    orden = {"alta": 0, "media": 1, "baja": 2}
    return [{"t": p, "tono": "info", "items": [_item(t) for t in sorted(
        ts, key=lambda t: (t["fecha"] or dt.date.max, orden.get(t.get("pri"), 3)))]}
        for p, ts in grupos.items()]


def desde_texto(texto):
    """Panel genérico: líneas 'TÍTULO:' se vuelven secciones y el resto viñetas."""
    secciones, actual = [], None
    for linea in texto.splitlines():
        l = linea.strip(" -•\t")
        if not l:
            continue
        if l.endswith(":") and len(l) < 60 or (l.isupper() and len(l) < 60):
            actual = {"t": l.rstrip(":").capitalize(), "tono": "info", "items": []}
            secciones.append(actual)
            continue
        if actual is None:
            actual = {"t": "", "tono": "info", "items": []}
            secciones.append(actual)
        actual["items"].append({"x": l, "sub": "", "tags": []})
    return secciones
