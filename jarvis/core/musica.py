"""Música en segundo plano dentro de JARVIS (YouTube vía yt-dlp, se reproduce en la propia interfaz)."""
import logging
import urllib.parse
import webbrowser

log = logging.getLogger("jarvis")


class Musica:
    def __init__(self, ui):
        self.ui = ui
        self.cola = []
        self.actual = None

    def _buscar(self, busqueda, n=1):
        import yt_dlp
        opciones = {"format": "bestaudio[ext=m4a]/bestaudio", "quiet": True, "noplaylist": True,
                    "skip_download": True, "no_warnings": True}
        with yt_dlp.YoutubeDL(opciones) as y:
            info = y.extract_info(f"ytsearch{n}:{busqueda}", download=False)
        return [{"url": e["url"], "titulo": e.get("title", ""), "canal": e.get("uploader", "")}
                for e in info.get("entries", []) if e and e.get("url")]

    def reproducir(self, busqueda, varias=False):
        pistas = self._buscar(busqueda + ("" if varias else " audio"), 5 if varias else 1)
        if not pistas:
            return f"No encontré '{busqueda}' en YouTube."
        self.actual, self.cola = pistas[0], pistas[1:]
        self.ui("musica", self.actual)
        return f"Reproduciendo {self.actual['titulo']}."

    def siguiente(self):
        if not self.cola:
            return "No hay más canciones en la cola."
        self.actual = self.cola.pop(0)
        self.ui("musica", self.actual)
        return f"Siguiente: {self.actual['titulo']}."

    def control(self, accion, nivel=None):
        accion = accion.lower()
        if accion in ("siguiente", "next"):
            return self.siguiente()
        self.ui("musicaControl", accion, nivel)
        return "Hecho."

    @staticmethod
    def apple_music(busqueda):
        webbrowser.open("https://music.apple.com/search?term=" + urllib.parse.quote(busqueda))
        return "Abrí Apple Music con tu búsqueda."
