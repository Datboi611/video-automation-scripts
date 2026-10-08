"""Apple Music (app de Windows): abre la app, entra a una playlist por su nombre y le da a Reproducir.
Apple no tiene API para la app de escritorio, así que se maneja su interfaz con UI Automation (pywinauto)."""
import difflib
import logging
import subprocess
import sys
import time
import unicodedata

log = logging.getLogger("jarvis")
APP_ID = r"shell:AppsFolder\AppleInc.AppleMusicWin_nzyj5cx40ttxa!App"
BOTON_PLAY = ("reproducir", "play", "reproducir todo", "play all")
BOTON_ALEATORIO = ("aleatorio", "shuffle", "reproduccion aleatoria", "reproducir en orden aleatorio", "mezclar")


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


def _elementos(win):
    salida = []
    for el in win.descendants():
        try:
            n = _norm(el.window_text())
            if n:
                salida.append((n, el))
        except Exception:
            pass
    return salida


def _buscar(win, nombre, tipos=None, intentos=3):
    """Elemento cuyo nombre se parece a 'nombre' (exacto, contenido o muy parecido). Reintenta porque
    el reproductor web de Apple Music (Chromium) carga su árbol de accesibilidad poco a poco."""
    objetivo = _norm(nombre)
    for i in range(intentos):
        mejor, puntaje = None, 0.0
        for n, el in _elementos(win):
            try:
                if tipos and el.element_info.control_type not in tipos:
                    continue
            except Exception:
                continue
            if n == objetivo:
                p = 1.0
            elif n.startswith(objetivo + " ") or n.startswith(objetivo + ","):
                p = 0.95
            else:
                p = difflib.SequenceMatcher(None, n, objetivo).ratio()
            if p > puntaje:
                mejor, puntaje = el, p
        if puntaje >= 0.8:
            return mejor
        time.sleep(1)
    return None


def _boton_cabecera(win, nombres):
    """Botón de la cabecera de la playlist (no el de la barra del reproductor de abajo)."""
    try:
        alto = win.rectangle().top + (win.rectangle().height() * 0.6)
    except Exception:
        alto = 10 ** 6
    for n, el in _elementos(win):
        try:
            if n in nombres and el.element_info.control_type == "Button" and el.rectangle().top < alto:
                return el
        except Exception:
            pass
    return None


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
        win = _ventana(15)
    if not win:  # sin la app de la Store: el reproductor web en el navegador
        import webbrowser
        webbrowser.open("https://music.apple.com/library/all-playlists/")
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
        log.warning("Apple Music: no encontré %r. Elementos visibles: %s", nombre,
                    sorted({n for n, _ in _elementos(win)})[:150])
        return f"No encontré la playlist «{nombre}» en Apple Music."
    try:
        item.click_input()
    except Exception:
        _clic(item)
    time.sleep(2.5)
    for nombres, modo in ((BOTON_ALEATORIO, "en aleatorio"), (BOTON_PLAY, "")):  # siempre aleatorio si se puede
        for _ in range(3):
            boton = _boton_cabecera(win, nombres)
            if boton:
                _clic(boton)
                log.info("Apple Music: reproduciendo playlist %s %s", nombre, modo)
                return f"Reproduciendo su playlist {nombre} {modo} en Apple Music.".replace("  ", " ")
            time.sleep(1)
    return f"Abrí la playlist {nombre}, pero no encontré el botón de reproducir."
