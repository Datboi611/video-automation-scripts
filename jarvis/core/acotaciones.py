"""Acotaciones al estilo JARVIS para las respuestas rápidas: a veces, con contexto, sin repetir."""
import datetime as dt
import random

FRASES = {
    "abrir": [
        "Intente que no sea para ver videos de gatos, {j}.",
        "Siempre es un placer ver cómo multiplica las pestañas abiertas.",
        "Listo. La productividad empieza en cuanto deje de abrir cosas.",
        "Hecho. Le recuerdo que yo también sé buscar, por si le da pereza teclear.",
    ],
    "musica": [
        "Excelente elección para fingir que trabaja.",
        "Le subiría el volumen, pero sus vecinos ya tienen suficiente con usted.",
        "Música para concentrarse. Veremos cuánto dura la concentración.",
        "Si esto no le inspira, nada lo hará.",
    ],
    "videos": [
        "Producción en marcha. El Óscar tendrá que esperar a mañana.",
        "Cinco actores, cero quejas. Ojalá todos los equipos fueran así.",
        "Le sugiero no tocar Flow mientras tanto; los artistas son sensibles.",
    ],
    "pausa": ["Silencio restablecido. Casi había olvidado cómo sonaba.", "Pausado. El mundo agradece el respiro."],
    "llamada": [
        "Sí, le llamo a usted desde su propia casa. La tecnología es maravillosa.",
        "Conteste, por favor. No me gusta hablar con buzones.",
        "Considérelo un recordatorio con más presencia escénica.",
    ],
    "mensaje": ["Su iPhone ya tiene noticias mías.", "Enviado. Ahora tiene dos formas de ignorarme."],
    "hecho": [
        "Una menos. A este ritmo terminaremos para la próxima década.",
        "Tachado. Disfrute la sensación, no suele durar.",
        "Excelente. Que no se le suba a la cabeza.",
        "Anotado como hecho. Me permito un discreto aplauso.",
    ],
    "correo": ["Nada que no pueda esperar, salvo lo que sí.", "Le sugiero contestar antes de que se le olvide, que suele pasar."],
    "hora": ["Por si se lo pregunta, el tiempo sigue sin detenerse.", "Hora excelente para tachar algo de la lista."],
}

CONTEXTO = {
    "madrugada": ["Le recuerdo que dormir también es productivo, {j}.", "Son horas poco civilizadas, si me permite."],
    "atrasos": ["Por cierto, tiene {n} tareas atrasadas mirándole con reproche.",
                "Mientras tanto, sus {n} pendientes atrasados siguen ahí. Pacientes."],
}

_ultima = {"txt": ""}


def acotacion(tipo, cfg, herr=None, probabilidad=0.4):
    if random.random() > probabilidad:
        return ""
    j = cfg.get("tratamiento", "jefe")
    opciones = list(FRASES.get(tipo, []))
    hora = dt.datetime.now().hour
    if hora >= 1 and hora < 5:
        opciones += CONTEXTO["madrugada"] * 2
    try:
        pen = herr.agenda["pendientes"] if herr else None
        hoy = dt.date.today().isoformat()
        n = sum(1 for i in pen.abiertos() if i.get("fecha") and i["fecha"] < hoy) if pen else 0
        if n >= 2 and tipo in ("abrir", "musica", "hora"):
            opciones += [c.replace("{n}", str(n)) for c in CONTEXTO["atrasos"]]
    except Exception:
        pass
    opciones = [o for o in opciones if o != _ultima["txt"]]
    if not opciones:
        return ""
    elegida = random.choice(opciones).replace("{j}", j)
    _ultima["txt"] = elegida
    return " " + elegida
