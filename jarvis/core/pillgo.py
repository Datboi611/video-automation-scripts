"""TAREA: generar los 5 videos diarios de Pill&Go, siguiendo exactamente el procedimiento de Diego.

1. PowerShell en C:\\Users\\Diego\\Documents\\Pillgo\\Pipeline
2. py -u daily.py --date <mañana>   (el plan va un día adelantado)
3. Esperar sin interrumpir (puede tardar horas); nunca abrir un segundo daily.py.
4. Si no conecta con Flow / puerto 9222: py flow_runner.py launch, confirmar sesión y repetir el MISMO comando.
5. Si se corta por error: repetir el MISMO comando (los que ya tienen FINAL.mp4 se saltan solos).
6. Al terminar: contar videos en videos_diarios\\<fecha>\\FINALES y en G:\\Mi unidad\\Pillgo\\<fecha>\\FINALES y avisar.

NUNCA: borrar out\\, FINALES ni Drive; editar Pillgo_Prompts.xlsx; ejecutar schedule.py install."""
import collections
import datetime as dt
import glob
import logging
import os
import re
import subprocess
import sys
import threading
import time

log = logging.getLogger("jarvis")
SIN_VENTANA = 0x08000000 if sys.platform == "win32" else 0

PIPELINE = r"C:\Users\Diego\Documents\Pillgo\Pipeline"
VIDEOS = r"C:\Users\Diego\Documents\Pillgo\videos_diarios"
DRIVE = r"G:\Mi unidad\Pillgo"
ESPERADOS = 5
MAX_REINTENTOS = 6
ERROR_FLOW = re.compile(r"no se pudo conectar a flow|9222|connect.*flow|ECONNREFUSED", re.I)


class PillGo:
    def __init__(self, avisar, carpeta_datos, cfg=None):
        self.avisar = avisar  # función(texto, urgente=False) -> voz + Telegram
        self.carpeta_datos = carpeta_datos
        c = (cfg or {}).get("pillgo", {})
        self.pipeline = c.get("pipeline", PIPELINE)
        self.videos = c.get("videos", VIDEOS)
        self.drive = c.get("drive", DRIVE)
        self.hilo = None
        self.fecha = None
        self.ultimas = collections.deque(maxlen=12)
        self.estado = "inactivo"
        self.inicio = None

    # ---------- utilidades ----------
    @staticmethod
    def _daily_corriendo():
        try:
            import psutil
            for p in psutil.process_iter(["cmdline"]):
                if any("daily.py" in (a or "") for a in (p.info["cmdline"] or [])):
                    return True
        except Exception:
            pass
        return False

    def _contar(self, base):
        carpeta = os.path.join(base, self.fecha, "FINALES")
        return len(glob.glob(os.path.join(carpeta, "*.mp4"))), carpeta

    def _ps(self, comando, registro):
        """Ejecuta en PowerShell dentro de la carpeta del Pipeline, guardando todo en el registro."""
        cmd = ["powershell", "-NoProfile", "-ExecutionPolicy", "Bypass", "-Command",
               f"Set-Location '{self.pipeline}'; {comando}"]
        proc = subprocess.Popen(cmd, stdout=subprocess.PIPE, stderr=subprocess.STDOUT, text=True,
                                encoding="utf-8", errors="replace", creationflags=SIN_VENTANA)
        hubo_error_flow = False
        with open(registro, "a", encoding="utf-8") as f:
            f.write(f"\n===== {dt.datetime.now():%H:%M:%S} > {comando}\n")
            for linea in proc.stdout:
                f.write(linea)
                f.flush()
                if linea.strip():
                    self.ultimas.append(linea.strip()[:200])
                if ERROR_FLOW.search(linea):
                    hubo_error_flow = True
        return proc.wait(), hubo_error_flow

    # ---------- lanzar.py (tanda desvinculada + vigía con avisos por Telegram) ----------
    def _lanzador(self):
        """Ruta de lanzar.py junto a daily.py; si no existe, se copia el de JARVIS (extras/lanzar.py)."""
        import shutil
        for d in (self.pipeline, os.path.dirname(self.pipeline)):
            ruta = os.path.join(d, "lanzar.py")
            if os.path.exists(ruta) and os.path.exists(os.path.join(d, "daily.py")):
                return d
        if os.path.exists(os.path.join(self.pipeline, "daily.py")):
            origen = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "extras", "lanzar.py")
            if os.path.exists(origen):
                shutil.copy(origen, os.path.join(self.pipeline, "lanzar.py"))
                return self.pipeline
        return None

    def _lanzar(self, *args, timeout=90):
        carpeta = self._lanzador()
        if not carpeta:
            return None
        r = subprocess.run(["py", "-u", "lanzar.py", *args], cwd=carpeta, capture_output=True, text=True,
                           encoding="utf-8", errors="replace", timeout=timeout, creationflags=SIN_VENTANA)
        return (r.stdout + r.stderr).strip()

    def _seguir(self):
        """Mientras JARVIS esté abierto, cuenta los FINALES cada 5 min y llama al terminar."""
        fecha, inicio = self.fecha, time.time()
        carpetas = [self.videos, os.path.join(self.pipeline, "videos_diarios")]
        while time.time() - inicio < 16 * 3600 and self.fecha == fecha:
            time.sleep(300)
            hechos = max(len(glob.glob(os.path.join(c, fecha, "FINALES", "*.mp4"))) for c in carpetas)
            if hechos >= ESPERADOS:
                horas = (time.time() - inicio) / 3600
                self.estado = "terminado"
                self.avisar(f"Pill&Go: listos los {hechos} videos del {fecha} ({horas:.1f} h).", urgente=True, llamar=True)
                return

    def parar(self):
        r = self._lanzar("parar")
        return "Detuve la tanda de Pill&Go y su vigía." if r is not None else "No encontré lanzar.py."

    # ---------- tarea ----------
    def iniciar(self):
        if not os.path.isdir(self.pipeline):
            return f"No encuentro la carpeta {self.pipeline}."
        try:
            self.fecha = (dt.date.today() + dt.timedelta(days=1)).isoformat()
            r = self._lanzar(self.fecha)
            if r is not None:
                self.estado, self.inicio = "lanzado con lanzar.py", time.time()
                if "Ya hay una tanda corriendo" in r:
                    return "Ya hay una tanda de Pill&Go corriendo; no lanzo otra. El vigía la está cuidando."
                if "No pude lanzar" in r:
                    return "No pude lanzar la tanda: " + r.split("No pude lanzar la tanda:")[-1][:200]
                threading.Thread(target=self._seguir, daemon=True).start()
                return (f"Tanda de Pill&Go para el {self.fecha} lanzada por el Programador de tareas, independiente de mí. "
                        "El vigía la revisa cada 5 minutos y la relanza si se corta; cuando termine le aviso por Telegram "
                        "y le llamo por teléfono.")
        except Exception as e:
            log.warning("lanzar.py falló, uso el método interno: %s", e)
        return self._iniciar_interno()

    def _iniciar_interno(self):
        if self.hilo and self.hilo.is_alive():
            return f"Ya estoy generando los videos del {self.fecha}. Le aviso al terminar."
        if self._daily_corriendo():
            return "Ya hay un daily.py corriendo en el PC; no abro otro, como usted indicó."
        if not os.path.isdir(self.pipeline):
            return f"No encuentro la carpeta {self.pipeline}."
        self.fecha = (dt.date.today() + dt.timedelta(days=1)).isoformat()  # el plan va un día adelantado
        self.hilo = threading.Thread(target=self._correr, daemon=True)
        self.hilo.start()
        return (f"Generando los 5 videos de Pill&Go para el {self.fecha}. Puede tardar varias horas; "
                "no cierre el Brave de Flow. Le aviso al terminar.")

    def _correr(self):
        self.inicio = time.time()
        self.estado = "generando"
        registro = os.path.join(self.carpeta_datos, f"pillgo_{self.fecha}.log")
        comando = f"py -u daily.py --date {self.fecha}"
        errores = []
        reintentos = 0
        flow_lanzado = 0
        while True:
            codigo, error_flow = self._ps(comando, registro)
            hechos, _ = self._contar(self.videos)
            if hechos >= ESPERADOS and codigo == 0:
                break
            if error_flow and flow_lanzado < 2:
                flow_lanzado += 1
                self.estado = "abriendo Flow"
                errores.append("Flow no estaba conectado (puerto 9222)")
                # flow_runner deja Brave abierto: se lanza aparte, sin esperar a que termine
                subprocess.Popen(["powershell", "-NoProfile", "-Command",
                                  f"Set-Location '{self.pipeline}'; py flow_runner.py launch"],
                                 creationflags=SIN_VENTANA)
                self.avisar("Pill&Go: abrí Brave con Flow. Confirme que tenga la sesión iniciada; "
                            "en 2 minutos vuelvo a lanzar los videos.", urgente=True)
                time.sleep(120)
                self.estado = "generando"
                continue
            if hechos >= ESPERADOS:
                break
            reintentos += 1
            if reintentos > MAX_REINTENTOS:
                errores.append(f"se cortó {reintentos} veces; me detuve para no insistir sin fin")
                break
            errores.append(f"se cortó (código {codigo}); repetí el mismo comando")
            log.info("Pill&Go: reintento %s", reintentos)
            time.sleep(15)
        self._informe(errores, registro)

    def _informe(self, errores, registro):
        locales, carpeta = self._contar(self.videos)
        try:
            en_drive, _ = self._contar(self.drive)
        except Exception:
            en_drive = 0
        horas = (time.time() - self.inicio) / 3600
        self.estado = "terminado"
        ok = locales >= ESPERADOS and en_drive >= ESPERADOS
        texto = (f"🎬 Pill&Go {self.fecha}: {locales}/{ESPERADOS} videos en FINALES, {en_drive}/{ESPERADOS} copiados "
                 f"a Drive ({horas:.1f} h).")
        if errores:
            texto += "\nIncidencias: " + "; ".join(dict.fromkeys(errores))
        if not ok:
            texto += f"\nRevise el registro: {registro}"
        self.avisar(texto, urgente=not ok)

    def resumen(self):
        try:
            r = self._lanzar("estado", timeout=60)
            if r is not None:
                return "Pill&Go:\n" + "\n".join(r.splitlines()[:12])
        except Exception as e:
            log.warning("lanzar.py estado: %s", e)
        if self.estado == "inactivo":
            return "No hay generación de videos en curso."
        hechos = self._contar(self.videos)[0] if self.fecha else 0
        mins = int((time.time() - self.inicio) / 60) if self.inicio else 0
        ultimas = "\n".join(list(self.ultimas)[-4:])
        return f"Pill&Go {self.fecha}: {self.estado}, {hechos}/{ESPERADOS} videos listos, {mins} min.\nÚltimo registro:\n{ultimas}"
