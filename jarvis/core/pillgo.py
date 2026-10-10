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
            dias = [fecha, (dt.date.fromisoformat(fecha) + dt.timedelta(days=1)).isoformat()]
            hechos = max(len(glob.glob(os.path.join(c, d, "FINALES", "*.mp4"))) for c in carpetas for d in dias)
            if hechos >= ESPERADOS:
                horas = (time.time() - inicio) / 3600
                self.estado = "terminado"
                self.avisar(f"Pill&Go: listos los {hechos} videos del {fecha} ({horas:.1f} h).", urgente=True, llamar=True)
                return

    def _args_lanzar(self, fecha):
        """`py lanzar.py lanzar --date F` si su lanzar.py lo admite; si no, `py lanzar.py F`."""
        try:
            ayuda = self._lanzar("ayuda", timeout=30) or ""
        except Exception:
            ayuda = ""
        return ["lanzar", "--date", fecha] if "lanzar --date" in ayuda else [fecha]

    def _carpeta(self):
        return self._lanzador() or self.pipeline

    def _py(self, *args, timeout=300, esperar=True):
        """Corre `py ...` en la carpeta del Pipeline. Con esperar=False queda desvinculado (sigue aunque JARVIS se cierre)."""
        if esperar:
            r = subprocess.run(["py", *args], cwd=self._carpeta(), capture_output=True, text=True, encoding="utf-8",
                               errors="replace", timeout=timeout, creationflags=SIN_VENTANA)
            return (r.stdout + r.stderr).strip()
        registro = open(os.path.join(self._carpeta(), "lanzar_log.txt"), "a", encoding="utf-8")
        subprocess.Popen(["py", *args], cwd=self._carpeta(), stdout=registro, stderr=subprocess.STDOUT,
                         creationflags=SIN_VENTANA | 0x00000008 | 0x00000200)  # DETACHED + NEW_PROCESS_GROUP
        return ""

    def _log_reciente(self, n=80):
        fecha = self.fecha or dt.date.today().isoformat()
        lineas = []
        for d in (fecha, (dt.date.fromisoformat(fecha) + dt.timedelta(days=1)).isoformat()):
            for ruta in (os.path.join(self._carpeta(), "videos_diarios", d, "log.txt"), os.path.join(self.videos, d, "log.txt")):
                try:
                    lineas += open(ruta, encoding="utf-8", errors="replace").read().splitlines()[-n:]
                except OSError:
                    pass
        try:
            lineas += open(os.path.join(self._carpeta(), "lanzar_log.txt"), encoding="utf-8",
                           errors="replace").read().splitlines()[-n:]
        except OSError:
            pass
        return "\n".join(lineas)

    def reset_flow(self):
        """Paso 2: Flow trabado (editor, chat, no encuentra el cuadro)."""
        r = self._py("-u", "daily.py", "--reset")
        return "Flow recargado." if "recargado" in r.lower() else "Recargué Flow: " + r[-200:]

    def reanudar(self, solo=None):
        """Pasos 3 y 4: reanuda lo pendiente (o solo el video N). Nunca empieza de cero ni cambia la fecha."""
        if self._daily_corriendo():
            return "La tanda sigue corriendo; no abro otra. Si está trabada, primero pídame recargar Flow."
        fecha = self.fecha or dt.date.today().isoformat()
        args = ["-u", "daily.py", "--date", fecha] + (["--only", str(int(solo))] if solo else [])
        self._py(*args, esperar=False)
        if not solo:
            threading.Thread(target=self._seguir, daemon=True).start()
        return f"Reanudando {'el video ' + str(solo) if solo else 'lo pendiente'} del {fecha}, desde donde quedó."

    def reparar(self):
        """Procedimiento de Diego si algo falla, en orden. Siempre reanuda, nunca empieza de cero."""
        estado = self._lanzar("estado", timeout=60) or ""
        if "TANDA: CORRIENDO" in estado:
            return "La tanda está corriendo; el vigía la cuida. No toco nada."
        log_txt = self._log_reciente()
        # 6) login: avisar y no reintentar
        if "pide iniciar sesión" in log_txt or "accounts.google.com" in log_txt:
            self.avisar("Pill&Go: Flow pide iniciar sesión en Google. Entre a mano al Brave de Flow; no reintento.",
                        urgente=True)
            return "Flow pide iniciar sesión: le avisé por Telegram y no reintento."
        # 8) el mismo video falló 2+ veces seguidas: seguir con los demás uno por uno y avisar
        fallos = re.findall(r"(\d{2})_[\w-]+?: \S+ falló|ERROR (\d{2})_", log_txt)
        cuenta = {}
        for a, b in fallos:
            cuenta[a or b] = cuenta.get(a or b, 0) + 1
        malos = sorted(int(k) for k, n in cuenta.items() if n >= 2)
        # 7) Flow rechazó / cola llena / sin video en 30 min: esperar 20 min y reanudar
        if re.search(r"rechazó la generación|\[espera\]|\[espera_img\]|cola llena|sin créditos", log_txt.split("\n")[-1] + "\n" +
                     "\n".join(log_txt.splitlines()[-15:])):
            def esperar_y_reanudar():
                time.sleep(20 * 60)
                self.avisar("Pill&Go: pasaron 20 min del rechazo/cola de Flow; reanudo. " + self._reanudar_sin(malos))
            threading.Thread(target=esperar_y_reanudar, daemon=True).start()
            return "Flow rechazó o tenía cola llena: espero 20 minutos y reanudo lo pendiente."
        pasos = []
        # 5) Brave cerrado
        if re.search(r"has been closed|ECONNREFUSED|9222|puerto de depuraci|No pude conectar al navegador", log_txt):
            subprocess.Popen(["py", "flow_runner.py", "launch"], cwd=self._carpeta(), creationflags=SIN_VENTANA)
            time.sleep(20)
            pasos.append("abrí Brave")
        # 2) Flow trabado (editor, chat, cuadro, ingredientes, imagen de la biblioteca)
        try:
            pasos.append(self.reset_flow())
        except Exception as e:
            pasos.append(f"no pude recargar Flow ({str(e)[:80]})")
        # 3/4) reanudar (los clips con otra persona ya los borró daily.py: se regeneran solos)
        pasos.append(self._reanudar_sin(malos))
        if malos:
            self.avisar(f"Pill&Go: el video {', '.join(map(str, malos))} falló 2 veces seguidas; sigo con los demás.",
                        urgente=True)
        return "Pill&Go: " + "; ".join(pasos)

    def _reanudar_sin(self, malos):
        """Reanuda todo; si hay videos que fallaron 2 veces, corre los demás uno por uno con --only."""
        if not malos:
            return self.reanudar()
        fecha = self.fecha or dt.date.today().isoformat()
        otros = [n for n in range(1, ESPERADOS + 1) if n not in malos]

        def en_serie():
            for n in otros:
                self._py("-u", "daily.py", "--date", fecha, "--only", str(n), timeout=4 * 3600)
            self.avisar(f"Pill&Go: terminé los videos {otros}; el {malos} necesita revisión manual.", urgente=True)
        threading.Thread(target=en_serie, daemon=True).start()
        return f"Sigo con los videos {otros} uno por uno (salto el {malos})."

    def parar(self):
        r = self._lanzar("parar")
        return "Detuve la tanda de Pill&Go y su vigía." if r is not None else "No encontré lanzar.py."

    # ---------- tarea ----------
    def iniciar(self):
        if not os.path.isdir(self.pipeline):
            return f"No encuentro la carpeta {self.pipeline}."
        try:
            self.fecha = dt.date.today().isoformat()  # se lanza con la fecha de HOY (la carpeta sale como mañana)
            r = self._lanzar(*self._args_lanzar(self.fecha))
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
