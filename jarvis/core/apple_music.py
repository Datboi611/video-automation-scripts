"""Apple Music (app de Windows): abre la app, entra a una playlist por su nombre y le da a Reproducir.
Apple no tiene API para la app de escritorio, así que se maneja su interfaz con UI Automation (pywinauto)."""
import logging
import subprocess
import sys
import time
import unicodedata

log = logging.getLogger("jarvis")
APP_ID = r"shell:AppsFolder\AppleInc.AppleMusicWin_nzyj5cx40ttxa!App"
BOTON_PLAY = ("reproducir", "play", "reproducir todo", "play all")


def _norm(t):
    t = unicodedata.normalize("NFD", (t or "").lower())
    return "".join(c for c in t if unicodedata.category(c) != "Mn").strip(" .\"'“”")


def _ventana(timeout=20):
    from pywinauto import Desktop
    fin = time.time() + timeout
    while time.time() < fin:
        for w in Desktop(backend="uia").windows():
            try:
                if "apple music" in w.window_text().lower():
                    return w
            except Exception:
                pass
        time.sleep(0.5)
    return None


def _buscar(win, nombre, tipos=None):
    """Elemento cuyo nombre coincide con 'nombre' (exacto primero, luego que lo contenga)."""
    objetivo = _norm(nombre)
    exactos, parciales = [], []
    for el in win.descendants():
        try:
            if tipos and el.element_info.control_type not in tipos:
                continue
            n = _norm(el.window_text())
        except Exception:
            continue
        if not n:
            continue
        if n == objetivo:
            exactos.append(el)
        elif objetivo in n and len(n) < len(objetivo) + 25:
            parciales.append(el)
    return (exactos or parciales or [None])[0]


def _clic(el):
    try:
        el.invoke()
    except Exception:
        el.click_input()


def reproducir_playlist(nombre):
    if sys.platform != "win32":
        return "Apple Music solo se controla en Windows."
    try:
        import pywinauto  # noqa: F401
    except ImportError:
        return "Falta instalar pywinauto: actualice JARVIS con ACTUALIZAR_JARVIS.bat."
    win = _ventana(2)
    if not win:
        subprocess.Popen(["explorer.exe", APP_ID])
        win = _ventana(25)
    if not win:
        return "No pude abrir la app de Apple Music."
    try:
        win.restore()
        win.set_focus()
    except Exception:
        pass
    time.sleep(1)
    item = _buscar(win, nombre, ("ListItem", "TreeItem", "Hyperlink", "Button", "Text", "DataItem"))
    if not item:  # quizá está plegada: abro "Todas las playlists" y busco ahí
        todas = _buscar(win, "Todas las playlists") or _buscar(win, "All Playlists")
        if todas:
            _clic(todas)
            time.sleep(2)
            item = _buscar(win, nombre)
    if not item:
        return f"No encontré la playlist «{nombre}» en Apple Music."
    try:
        item.click_input()
    except Exception:
        _clic(item)
    time.sleep(2)
    for nom in BOTON_PLAY:
        boton = _buscar(win, nom, ("Button",))
        if boton and _norm(boton.window_text()) in BOTON_PLAY:
            _clic(boton)
            log.info("Apple Music: reproduciendo playlist %s", nombre)
            return f"Reproduciendo su playlist {nombre} en Apple Music."
    return f"Abrí la playlist {nombre}, pero no encontré el botón Reproducir."
