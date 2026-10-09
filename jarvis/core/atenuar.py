"""Baja el volumen de las demás apps (música de Apple Music, YouTube de JARVIS, Spotify...) mientras
el usuario habla con JARVIS, y lo restaura después. Usa las sesiones de audio de Windows (pycaw)."""
import logging
import os
import sys
import threading

log = logging.getLogger("jarvis")
_lock = threading.Lock()
_guardados = {}  # pid -> volumen original


def _es_jarvis(proceso):
    """La voz de JARVIS sale de python(w).exe; Windows recuerda el volumen por programa, así que nunca
    se toca ningún python (si no, la próxima vez JARVIS arrancaría bajito)."""
    try:
        return proceso.pid == os.getpid() or proceso.name().lower().startswith("python")
    except Exception:
        return False


def voz_a_tope():
    """Devuelve la voz de JARVIS al 100 % en el mezclador de Windows (por si quedó baja)."""
    if sys.platform != "win32":
        return
    try:
        import comtypes
        from pycaw.pycaw import AudioUtilities
        comtypes.CoInitialize()
        for s in AudioUtilities.GetAllSessions():
            if s.Process and _es_jarvis(s.Process):
                vol = s.SimpleAudioVolume
                if vol.GetMasterVolume() < 0.99:
                    vol.SetMasterVolume(1.0, None)
                if vol.GetMute():
                    vol.SetMute(0, None)
    except Exception as e:
        log.debug("No pude ajustar el volumen de JARVIS: %s", e)


def bajar(nivel=0.2):
    if sys.platform != "win32":
        return
    with _lock:
        try:
            import comtypes
            from pycaw.pycaw import AudioUtilities
            comtypes.CoInitialize()
            for s in AudioUtilities.GetAllSessions():
                if not s.Process or _es_jarvis(s.Process):
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


_cache = [0.0, False]


def hay_audio():
    """¿Suena algo en otra app (música)? Se consulta como mucho una vez por segundo."""
    import time
    if sys.platform != "win32":
        return False
    if time.time() - _cache[0] < 1:
        return _cache[1]
    sonando = False
    try:
        import comtypes
        from pycaw.pycaw import AudioUtilities, IAudioMeterInformation
        comtypes.CoInitialize()
        for s in AudioUtilities.GetAllSessions():
            if not s.Process or _es_jarvis(s.Process):
                continue
            medidor = s._ctl.QueryInterface(IAudioMeterInformation)
            if medidor.GetPeakValue() > 0.01:
                sonando = True
                break
    except Exception as e:
        log.debug("No pude medir el audio: %s", e)
    _cache[:] = [time.time(), sonando]
    return sonando
