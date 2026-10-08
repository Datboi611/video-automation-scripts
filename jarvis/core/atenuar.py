"""Baja el volumen de las demás apps (música de Apple Music, YouTube de JARVIS, Spotify...) mientras
el usuario habla con JARVIS, y lo restaura después. Usa las sesiones de audio de Windows (pycaw)."""
import logging
import os
import sys
import threading

log = logging.getLogger("jarvis")
_lock = threading.Lock()
_guardados = {}  # pid -> volumen original


def bajar(nivel=0.2):
    if sys.platform != "win32":
        return
    with _lock:
        try:
            import comtypes
            from pycaw.pycaw import AudioUtilities
            comtypes.CoInitialize()
            for s in AudioUtilities.GetAllSessions():
                if not s.Process or s.Process.pid == os.getpid():
                    continue  # la voz de JARVIS no se baja
                vol = s.SimpleAudioVolume
                pid = s.Process.pid
                if pid not in _guardados:
                    _guardados[pid] = vol.GetMasterVolume()
                vol.SetMasterVolume(min(_guardados[pid], _guardados[pid] * nivel), None)
        except Exception as e:
            log.debug("No pude atenuar el audio: %s", e)


def restaurar():
    if sys.platform != "win32" or not _guardados:
        return
    with _lock:
        try:
            import comtypes
            from pycaw.pycaw import AudioUtilities
            comtypes.CoInitialize()
            for s in AudioUtilities.GetAllSessions():
                if s.Process and s.Process.pid in _guardados:
                    s.SimpleAudioVolume.SetMasterVolume(_guardados[s.Process.pid], None)
        except Exception as e:
            log.debug("No pude restaurar el audio: %s", e)
        _guardados.clear()
