"""Lanza la tanda diaria DESVINCULADA de la terminal y de Jarvis (Programador de tareas de Windows),
y arranca un VIGÍA que la revisa cada 5 minutos, la relanza si se corta y avisa por Telegram.

  py lanzar.py lanzar --date AAAA-MM-DD -> tanda de esa fecha + vigía
  py lanzar.py              -> tanda de hoy (fecha = mañana, el plan va un día adelantado) + vigía
  py lanzar.py 2026-10-09   -> esa fecha concreta
  py lanzar.py estado       -> ¿corre la tanda? ¿corre el vigía? últimas líneas del log
  py lanzar.py parar        -> detiene tanda y vigía
  py lanzar.py telegram-test-> manda un mensaje de prueba a Telegram

Telegram: usa el bot que Jarvis ya tiene (Documents\\jarvis\\config.json > telegram_bot). Opcional: telegram.json aquí con {"token": "...", "chat_id": "..."}
"""
import json, subprocess, sys, time, urllib.parse, urllib.request
from datetime import date, datetime, timedelta
from pathlib import Path

HERE = Path(__file__).resolve().parent
TASK, TASK_VIGIA = "PillgoAhora", "PillgoVigia"
LOG, LOG_VIGIA = HERE / "lanzar_log.txt", HERE / "vigia_log.txt"
PS = ["powershell", "-NoProfile", "-ExecutionPolicy", "Bypass", "-Command"]
CADA = 300            # el vigía revisa cada 5 min
SIN_ACTIVIDAD = 25    # minutos sin tocar ningún log => colgado
MAX_RELANZ = 6
OBJETIVO = 5


def ps(cmd):
    return subprocess.run(PS + [cmd], capture_output=True, text=True).stdout


def pids(patron):
    out = ps(f"Get-CimInstance Win32_Process | Where-Object {{ $_.CommandLine -match '{patron}' }} | Select-Object -ExpandProperty ProcessId")
    return [x.strip() for x in out.split() if x.strip().isdigit()]


def tanda_pids():
    return pids(r"daily\.py|flow_runner\.py|pipeline\.py")


def vigia_pids():
    return pids(r"lanzar\.py.*vigilar")


def vlog(msg):
    linea = f"[{datetime.now():%Y-%m-%d %H:%M:%S}] {msg}"
    print(linea, flush=True)
    try:
        with open(LOG_VIGIA, "a", encoding="utf-8") as f:
            f.write(linea + "\n")
    except Exception:
        pass


JARVIS_CFG = Path.home() / "Documents" / "jarvis" / "config.json"


def credenciales_telegram():
    """telegram.json de esta carpeta; si no existe, usa el bot que Jarvis ya tiene en su config.json."""
    for f, clave in ((HERE / "telegram.json", None), (JARVIS_CFG, "telegram_bot")):
        try:
            c = json.loads(f.read_text(encoding="utf-8-sig"))
            c = c.get(clave, {}) if clave else c
            if c.get("token"):
                return str(c["token"]), str(c.get("chat_id") or "")
        except Exception:
            continue
    return None, None


def telegram(msg):
    """Manda un aviso a Telegram. Si no está configurado, solo lo deja en vigia_log.txt."""
    vlog(f"AVISO: {msg}")
    token, chat = credenciales_telegram()
    if not token:
        vlog("(no encuentro el token de Telegram: no se envió)")
        return False
    try:
        if not chat:  # sin chat_id: tomar el del último mensaje que le escribiste al bot
            r = json.loads(urllib.request.urlopen(f"https://api.telegram.org/bot{token}/getUpdates", timeout=20).read())
            ids = [u["message"]["chat"]["id"] for u in r.get("result", []) if "message" in u]
            if not ids:
                vlog("(el bot no tiene chat_id: escríbele cualquier mensaje al bot en Telegram)"); return False
            chat = str(ids[-1])
        data = urllib.parse.urlencode({"chat_id": chat, "text": "Pill&Go · " + msg}).encode()
        urllib.request.urlopen(urllib.request.Request(f"https://api.telegram.org/bot{token}/sendMessage", data=data), timeout=20).read()
        return True
    except Exception as e:
        vlog(f"(no pude enviar a Telegram: {type(e).__name__})")
    return False


def finales(fecha):
    d = HERE / "videos_diarios" / fecha / "FINALES"
    return len(list(d.glob("*.mp4"))) if d.exists() else 0


def ultima_actividad(fecha):
    fs = [HERE / "videos_diarios" / fecha / "log.txt", LOG]
    ts = [f.stat().st_mtime for f in fs if f.exists()]
    return datetime.fromtimestamp(max(ts)) if ts else None


def tail(path, n=40):
    try:
        return Path(path).read_text(encoding="utf-8", errors="replace").splitlines()[-n:]
    except Exception:
        return []


def tarea(nombre, inner):
    tr = f'cmd /c "{inner}"'
    subprocess.run(["schtasks", "/Delete", "/TN", nombre, "/F"], capture_output=True)
    r = subprocess.run(["schtasks", "/Create", "/TN", nombre, "/SC", "ONCE", "/ST", "23:59", "/TR", tr, "/IT", "/F"],
                       capture_output=True, text=True)
    if r.returncode != 0:
        return False, r.stdout + r.stderr
    r = subprocess.run(["schtasks", "/Run", "/TN", nombre], capture_output=True, text=True)
    return r.returncode == 0, r.stdout + r.stderr


def iniciar_tanda(fecha):
    py = sys.executable
    return tarea(TASK, f'cd /d "{HERE}" && "{py}" -u daily.py --date {fecha} >> "{LOG}" 2>&1')


def iniciar_vigia(fecha):
    py = sys.executable
    return tarea(TASK_VIGIA, f'cd /d "{HERE}" && "{py}" -u lanzar.py vigilar {fecha} >> "{LOG_VIGIA}" 2>&1')


def parar_tanda():
    for p in tanda_pids():
        subprocess.run(["taskkill", "/PID", p, "/F", "/T"], capture_output=True)
    subprocess.run(["schtasks", "/End", "/TN", TASK], capture_output=True)


def parar():
    for p in vigia_pids():
        subprocess.run(["taskkill", "/PID", p, "/F", "/T"], capture_output=True)
    subprocess.run(["schtasks", "/End", "/TN", TASK_VIGIA], capture_output=True)
    parar_tanda()
    print("Detenido (tanda y vigía).")


def estado():
    t, v = tanda_pids(), vigia_pids()
    print("TANDA:", "CORRIENDO" if t else "NO está corriendo", t)
    print("VIGÍA:", "ACTIVO" if v else "NO activo", v)
    for nombre, f in (("lanzar_log.txt", LOG), ("vigia_log.txt", LOG_VIGIA)):
        if f.exists():
            print(f"---- últimas líneas de {nombre} ----")
            print("\n".join(tail(f, 15)))


FIRMAS = [  # (clave, texto en el log, qué pasó, arreglo)
    ("login",   "pide iniciar sesión",            "Flow pide iniciar sesión en Google. Entra a mano al Brave de Flow.", None),
    ("rechazo", "Flow rechazó la generación",     "Flow rechaza generar (cola/cuota). Espero 20 min y reanudo.", "esperar"),
    ("sinimg",  "No apareció la imagen",          "No salió la imagen en 10 min. Recargo Flow y reanudo ese video.", "reset"),
    ("editor",  "No encuentro el cuadro",         "Flow quedó en editor/panel de chat. Recargo el proyecto y reanudo.", "reset"),
    ("cerrado", "has been closed",                "Se cerró Brave/la pestaña. Reabro Brave y reanudo.", "reset"),
    ("conexion","ECONNREFUSED",                   "Brave sin puerto 9222. Reabro Brave y reanudo.", "reset"),
    ("proyecto","No pude abrir el proyecto",      "No pude abrir el proyecto en Flow. Revisa Brave.", None),
    ("imgfallo","imágenes falló",                 "Falló la generación de imágenes de un video. Reanudo solo lo que falta.", "reset"),
    ("vidfallo","videos falló",                   "Falló la generación de clips de un video. Reanudo solo lo que falta.", "reset"),
]


def reset_flow():
    py = sys.executable
    r = subprocess.run([py, "-u", "daily.py", "--reset"], cwd=HERE, capture_output=True, text=True, timeout=300)
    vlog("reset_flow: " + (r.stdout + r.stderr).strip()[-200:])
    return r.returncode == 0


def lineas_nuevas(fecha, pos):
    """Líneas añadidas a los logs desde la última revisión. pos = {ruta: bytes leídos}."""
    out = []
    for f in (HERE / "videos_diarios" / fecha / "log.txt", LOG):
        try:
            sz = f.stat().st_size
        except Exception:
            continue
        ini = pos.get(str(f), max(0, sz - 20000))
        if sz < ini: ini = 0
        with open(f, "rb") as fh:
            fh.seek(ini); out += fh.read().decode("utf-8", "replace").splitlines()
        pos[str(f)] = sz
    return out


def pendientes(fecha):
    d = HERE / "videos_diarios" / fecha / "FINALES"
    hechos = {p.name.split("_VIDEO-TERMINADO_")[-1][:2] for p in d.glob("*.mp4")} if d.exists() else set()
    return [i for i in range(1, OBJETIVO + 1) if f"{i:02d}" not in hechos]


def vigilar(fecha):
    if len(vigia_pids()) > 1:   # ya hay otro vigía (yo cuento como uno)
        vlog("Ya hay un vigía activo; salgo."); return
    vlog(f"Vigía iniciado para {fecha}.")
    telegram(f"Vigía activo. Tanda {fecha} en marcha, reviso cada {CADA // 60} min. Faltan slots: {pendientes(fecha)}")
    relanz, inicio, avisados, sin_sesion, pos = 0, datetime.now(), {}, False, {}
    lineas_nuevas(fecha, pos)
    ultimo_n = finales(fecha)
    while True:
        time.sleep(CADA)
        n = finales(fecha)
        if n > ultimo_n:
            telegram(f"🎬 Video listo ({n}/{OBJETIVO}). Faltan slots: {pendientes(fecha)}")
            ultimo_n, relanz = n, 0
        if n >= OBJETIVO:
            telegram(f"✅ Listos los {n} videos de {fecha}.")
            return
        if datetime.now() - inicio > timedelta(hours=14):
            telegram(f"⚠ Llevo 14 horas y solo hay {n}/{OBJETIVO}. Dejo de vigilar. Faltan: {pendientes(fecha)}")
            return
        nuevas = "\n".join(lineas_nuevas(fecha, pos))
        accion = None
        for clave, txt, msg, fix in FIRMAS:
            if txt in nuevas:
                avisados[clave] = avisados.get(clave, 0) + 1
                if avisados[clave] <= 3:
                    telegram(f"⚠ {msg}  [{n}/{OBJETIVO}]")
                if clave == "login":
                    sin_sesion = True
                elif fix == "esperar":
                    accion = accion or "esperar"
                elif fix == "reset" and accion != "esperar":
                    accion = "reset"
        if sin_sesion and "pide iniciar sesión" not in nuevas and tanda_pids():
            sin_sesion = False
        if sin_sesion:
            continue
        colgada = False
        act = ultima_actividad(fecha)
        if act and tanda_pids() and datetime.now() - act > timedelta(minutes=SIN_ACTIVIDAD):
            colgada = True
            telegram(f"⚠ {SIN_ACTIVIDAD}+ min sin avanzar ({n}/{OBJETIVO}). Reinicio.")
        if tanda_pids() and not colgada:
            # la tanda sigue viva; si hay fallo la dejo seguir (ya cierra, espera y recarga sola entre videos)
            continue
        # tanda muerta o colgada -> arreglar desde donde quedó
        if relanz >= MAX_RELANZ:
            telegram(f"❌ {MAX_RELANZ} relanzamientos sin avanzar ({n}/{OBJETIVO}). Faltan: {pendientes(fecha)}. Necesito ayuda manual.")
            return
        relanz += 1
        parar_tanda(); time.sleep(10)
        if accion == "esperar":
            telegram("⏳ Espero 20 min por el rechazo de Flow antes de reanudar.")
            time.sleep(20 * 60)
        try:
            reset_flow()
        except Exception as e:
            vlog(f"reset_flow falló: {e}")
        ok, info = iniciar_tanda(fecha)   # reanuda: salta imágenes/clips/finales ya hechos
        telegram(f"🔧 Reanudo desde donde quedó (intento {relanz}/{MAX_RELANZ}). Faltan: {pendientes(fecha)}" if ok
                 else f"❌ No pude relanzar: {info[:200]}")


def lanzar(fecha):
    if tanda_pids():
        print("Ya hay una tanda corriendo. No lanzo otra (se pisarían en Flow). Mira: py lanzar.py estado")
    else:
        ok, info = iniciar_tanda(fecha)
        if not ok:
            print("No pude lanzar la tanda:", info); return
        print(f"Tanda {fecha} lanzada y desvinculada de la terminal.")
    if not vigia_pids():
        ok, info = iniciar_vigia(fecha)
        print("Vigía activado (revisa cada 5 min, relanza y avisa por Telegram)." if ok else f"No pude activar el vigía: {info}")
    if not credenciales_telegram()[0]:
        print("AVISO: no encuentro el bot de Telegram (ni telegram.json ni el config de Jarvis): no habrá avisos.")
    time.sleep(6)
    estado()


if __name__ == "__main__":
    a = sys.argv[1] if len(sys.argv) > 1 else ""
    if a == "lanzar":  # py lanzar.py lanzar --date AAAA-MM-DD
        a = sys.argv[sys.argv.index("--date") + 1] if "--date" in sys.argv else ""
    manana = (date.today() + timedelta(days=1)).isoformat()
    if a == "estado": estado()
    elif a == "parar": parar()
    elif a == "vigilar": vigilar(sys.argv[2] if len(sys.argv) > 2 else manana)
    elif a == "telegram-test": print("Enviado" if telegram("Mensaje de prueba ✅") else "No se pudo enviar (revisa telegram.json)")
    elif a in ("ayuda", "-h", "--help"): print(__doc__)
    else: lanzar(a or manana)
