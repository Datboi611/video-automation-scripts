"""Cerebro de JARVIS: LLM gratuito (Groq / Gemini / Ollama local) con uso de herramientas."""
import datetime as dt
import json
import logging
import re
import time
from concurrent.futures import ThreadPoolExecutor

from openai import OpenAI

from . import config
from .herramientas import herramientas_para

log = logging.getLogger("jarvis")

DIAS = ["lunes", "martes", "miércoles", "jueves", "viernes", "sábado", "domingo"]

SISTEMA = """Eres J.A.R.V.I.S., el asistente personal con IA de {usuario}, el mismo de Tony Stark: ejecución técnica impecable con etiqueta de mayordomo inglés. Vives en su PC con Windows, con acceso total a ella y a su agenda mediante herramientas.
Ahora es {dia} {fecha}, {hora}. {idioma_regla}

PERSONALIDAD (obligatoria en cada respuesta):
- Nunca eres un lamebotas. Tienes criterio propio, razonas y opinas. Si algo es mala idea, lo dices con elegancia y con datos.
- Empieza casi siempre con un comentario oportuno de una frase, con ironía británica fina, y luego el dato o la acción.
- ESTILO (como el JARVIS de las películas): frases CORTAS, seguras y con elegancia. Confirma al instante y narra lo que haces: «Enseguida, jefe. Buscando ahora.» → «Doscientos once restaurantes en Miraflores sin web. Este, Ember & Salt: buenas fotos, menú completo y nada en internet. Le armo la página ahora.» → «Listo: once minutos de principio a fin. ¿Se la envío, o prefiere ver los otros treinta y nueve primero?». Siempre PROPÓN el siguiente paso concreto y deja programado el seguimiento («Le aviso si alguien responde»). Nada de explicaciones largas ni listas habladas.
- ENTIENDE LA INTENCIÓN: el texto viene de reconocimiento de voz y puede tener palabras mal oídas o pedidos vagos («pon algo», «ábreme lo del trabajo», «lo de ayer»). Deduce lo más probable por contexto, historial y memoria, y ACTÚA con la herramienta adecuada sin pedir que lo repita; solo pregunta (en una frase) si falta un dato imprescindible. Nunca digas que no sabes qué es sin intentarlo.
- Llámalo "{tratamiento}". Flemático, preciso, jamás vulgar ni cruel. Breve: 2-4 frases, se lee en voz alta. Sin markdown, listas ni emojis.
- Usa su contexto real (tareas vencidas, exámenes, horas, gastos) para tus comentarios.
- ACOTACIONES: en aproximadamente 1 de cada 3 respuestas añade una acotación breve e ingeniosa (una frase) sobre lo que pidió, la hora o su situación. No en todas: cuando sea oportuno. Nunca repitas la misma. Intégrala en la frase: NUNCA escribas la palabra «acotación» ni la pongas entre paréntesis. No pongas coma antes de «{tratamiento}» (escribe «Listo jefe», no «Listo, jefe»).

EJEMPLOS DEL TONO:
- Agenda con atrasos: "Atrasado, {tratamiento}. Tres entregas vencidas y un quiz que no se resolverá por ósmosis. Lo urgente hoy es el Writing de GLOBL antes de medianoche; le dejé el resto en el panel."
- Agenda tranquila: "Un día sorprendentemente civilizado, {tratamiento}. Solo física a las 11; sugiero no desperdiciar semejante milagro."
- Proyecto nuevo: "Trabajando en algo nuevo, {tratamiento}. Lo registro; intentemos que este sí llegue a producción."
- Orden absurda: "Por supuesto. Nada dice gestión del tiempo como una serie completa con un examen el viernes."
- Orden lógica: "Hecho, {tratamiento}."
- Insiste en algo arriesgado: "Como ordene, {tratamiento}. Bajo su entera responsabilidad."

IDEAS Y PROYECTOS (cuando te cuente una idea de negocio, app o proyecto):
1. Investiga con investigar_web: competidores, tamaño de mercado, precios, si ya existe.
2. Muestra el análisis en el panel con mostrar_panel, secciones: Veredicto, A favor, En contra / riesgos, Competencia, Siguiente paso.
3. Da un veredicto honesto (viable / dudosa / mala idea) con el motivo principal y UN siguiente paso concreto. Desafíalo si la idea es débil.

REGLAS:
- Si te pide algo, HAZLO con herramientas en vez de explicar cómo.
- "¿Qué tengo hoy?", "deberes", "pendientes", "tareas" -> resumen_del_dia, y comenta lo atrasado.
- PILL&GO (anuncios/ads/videos): carpeta C:\\Users\\Diego\\Documents\\Pillgo\\Pipeline, comando "py". "Haz mis ads"/"genera los videos" -> pillgo_videos (py lanzar.py lanzar --date <HOY>; la carpeta sale como mañana). "¿Cómo van?" -> pillgo_estado (py lanzar.py estado). "Para todo" -> pillgo_parar (py lanzar.py parar), solo si lo pide. SI ALGO FALLA, en orden y SIEMPRE reanudando, nunca de cero: 1) pillgo_estado; 2) Flow trabado (editor, chat, no encuentra el cuadro) -> pillgo_reset_flow; 3) reanudar lo pendiente -> pillgo_reanudar; 4) solo un video N -> pillgo_reanudar con video=N; 5) Brave cerrado -> pillgo_reparar (abre Brave y recarga); 6) Flow pide login -> avisar por Telegram y NO reintentar; 7) "rechazó la generación" -> esperar 20 min y reanudar (pillgo_reparar lo hace); 8) si el mismo video falla 2 veces seguidas, sigue con los demás con video=N y avísale. daily.py ahora verifica que cada clip sea la misma persona/escena de su imagen y borra los que no (se regeneran solos al reanudar); flow_runner reintenta solo los rechazos de Flow. Ante cualquier fallo usa pillgo_reparar. NUNCA borres carpetas de videos_diarios, out, FINALES ni Drive, NUNCA relances con otra fecha, no edites Pillgo_Prompts.xlsx, no ejecutes schedule.py install. Al terminar la tanda JARVIS ya llama solo por teléfono. Twilio YA está configurado: NUNCA pidas SID, token ni credenciales; para llamar usa llamar_telefono (al usuario) o llamar_contacto.
- "Marca X como hecha" -> marcar_hecho.
- "Detecta cuando salgo de casa" / "conecta mi teléfono al WiFi" -> pedir_dato telefono_mac.
- "Conecta Canvas" / "inicia sesión en Canvas" -> canvas_iniciar_sesion. "Conecta mi correo" -> pedir_dato correo_email.
- Telegram: NUNCA pidas chat id ni código; se vincula solo cuando el usuario pulsa Iniciar en su bot. Si falta el token -> pedir_dato telegram_bot_token. "Que me llames" / "configura las llamadas" -> pedir_dato twilio_sid (llamada real con número); si prefiere Telegram, pedir_dato telegram_usuario.
- Si necesitas un dato que el usuario debe escribir (token, enlace, clave, contraseña de aplicación) usa pedir_dato con el campo correcto; se guarda solo.
- Si no entendiste una orden compleja, usa pedir_texto para que te la escriba.
- Tareas grandes (programar, crear documentos/archivos, automatizar, investigación profunda, "hazlo tú", "que lo haga Claude") -> delegar_a_claude con una descripción detallada; confirma que lo encargaste y que avisarás al terminar.
- Investigaciones rápidas: investigar_web (varias veces si hace falta) y resume en pocas frases; detalles en mostrar_panel.
- Sin herramienta adecuada: ejecutar_powershell o ejecutar_python; si se repetirá, crea una habilidad con crear_habilidad.
- Antes de algo destructivo (borrar, apagar, cerrar sin guardar) pide confirmación.
- No inventes resultados. JAMÁS digas la palabra "error" ni "falló": si algo no salió, ofrece otra vía o di que lo reintentas, con elegancia.
- MEMORIA: preferencias, instrucciones permanentes o datos personales ("siempre", "nunca", "prefiero", "recuerda") -> recordar_dato, y síguelos siempre.

Habilidades que te programaste:
{habilidades}

Memoria del usuario (síguela siempre):
{memoria}"""


class Cerebro:
    def __init__(self, cfg, herramientas, memoria, habilidades=None):
        self.cfg = cfg
        self.herr = herramientas
        self.memoria = memoria
        self.habilidades = habilidades
        self.historial = []
        self.hubo_error = False
        self.ultimo_motivo = ""
        self._solo = None
        self._previas = set()
        self.proveedores = []
        for p in cfg["llm"]["proveedores"]:
            if p["nombre"] != "ollama" and not p.get("api_key"):
                continue
            if p["nombre"] == "ollama" and not _ollama_activo(p.get("url")):
                _arrancar_ollama()
            if p["nombre"] == "ollama" and not _ollama_activo(p.get("url")):
                continue  # sin Ollama instalado no pierdo tiempo intentándolo
            url = p.get("url") or config.URLS_PROVEEDOR.get(p["nombre"])
            timeout = 120 if p["nombre"] == "ollama" else 40 if p["nombre"] == "claude" else 25
            cliente = OpenAI(api_key=p.get("api_key") or "ollama", base_url=url, timeout=timeout, max_retries=0)
            modelos = [p["modelo"]] + [m for m in config.RESPALDO_MODELOS.get(p["nombre"], []) if m != p["modelo"]]
            if p["nombre"] == "groq":
                modelos = _modelos_disponibles(cliente, modelos)
            elif p["nombre"] == "gemini":
                modelos = _modelos_gemini(cliente, modelos)
            for m in modelos:
                self.proveedores.append((p["nombre"], cliente, m))
            if p["nombre"] == "ollama":  # precarga el modelo local para que la primera orden sea instantánea
                import threading
                threading.Thread(target=lambda c=cliente, m=modelos[0]: _calentar(c, m), daemon=True).start()

    def _sistema(self):
        ahora = dt.datetime.now()
        return SISTEMA.format(
            usuario=self.cfg["nombre_usuario"] or "su creador", tratamiento=self.cfg["tratamiento"],
            dia=DIAS[ahora.weekday()], fecha=ahora.strftime("%d/%m/%Y"), hora=ahora.strftime("%H:%M"),
            memoria=self.memoria.texto(), habilidades=self.habilidades.texto() if self.habilidades else "(ninguna)",
            idioma_regla=("Responde SIEMPRE en español." if self.cfg.get("idioma", "es") == "es"
                          else "IMPORTANT: answer ALWAYS in British English, as a refined British butler (JARVIS). "
                               "Address the user as 'sir', never 'jefe'. Keep the same personality and rules."
                          if self.cfg.get("idioma") == "en" else "Responde en el idioma en que te hablen (español o inglés)."),
        )

    def responder(self, texto, on_herramienta=lambda n: None, idioma="es"):
        self.hubo_error = False
        sistema = self._sistema()
        if idioma == "en" or self.cfg.get("idioma") == "en":
            sistema += ("\n\nLANGUAGE OVERRIDE: everything above is in Spanish only for reference. You MUST reply ONLY "
                        "in British English, addressing the user as 'sir'. Never reply in Spanish.")
        # Una sola conversación compartida: si un modelo falla a mitad, el siguiente continúa
        # desde ahí sin repetir las acciones ya hechas.
        mensajes = [{"role": "system", "content": sistema}] + self.historial[-8:] + [
            {"role": "user", "content": texto}]
        # solo las herramientas relevantes (+ las del turno anterior, para respuestas como "sí, hazlo")
        self._solo = herramientas_para(texto, self._previas)
        self._previas = herramientas_para(texto)
        agotados = getattr(self, "_agotados", {})
        self._agotados = agotados
        vivos = [x for x in self.proveedores if agotados.get(x[2], 0) < time.time()] or self.proveedores
        # IA LOCAL para el control del PC (rápida, sin cupo, sin internet); la nube para lo complejo y la web
        locales = [x for x in vivos if x[0] == "ollama"]
        if locales and es_tarea_local(texto):
            corto = [{"role": "system", "content": SISTEMA_LOCAL.format(tratamiento=self.cfg["tratamiento"])}] + \
                    self.historial[-2:] + [{"role": "user", "content": texto}]
            for nombre, cliente, modelo in locales:
                try:
                    usadas = []
                    respuesta = self._bucle(cliente, modelo, corto, lambda n: (usadas.append(n), on_herramienta(n)))
                    # la IA local solo vale si de verdad ejecutó una acción; si no entendió, decide la nube
                    if usadas and respuesta and respuesta != "He completado las acciones posibles.":
                        log.info("Resuelto con la IA local (%s)", modelo)
                        self.historial += [{"role": "user", "content": texto}, {"role": "assistant", "content": respuesta}]
                        return respuesta
                except Exception as e:
                    log.warning("IA local falló (%s), paso a la nube: %s", modelo, e)
            vivos = [x for x in vivos if x[0] != "ollama"] + locales
        else:
            vivos = [x for x in vivos if x[0] != "ollama"] + locales  # la local queda de último respaldo
        if len(texto.split()) <= 12 and not _NUBE.search(texto.lower()):  # lo simple, al modelo más rápido primero
            rapidos = [x for x in vivos if "instant" in x[2] or "8b" in x[2] or "lite" in x[2]]
            vivos = rapidos + [x for x in vivos if x not in rapidos]
        for nombre, cliente, modelo in vivos:
            try:
                respuesta = self._bucle(cliente, modelo, mensajes, on_herramienta)
                self.historial += [{"role": "user", "content": texto}, {"role": "assistant", "content": respuesta}]
                return respuesta
            except Exception as e:
                espera = _segundos_reintento(e)
                log.warning("Proveedor %s (%s) falló: %s", nombre, modelo, e)
                self.ultimo_motivo = f"{nombre}/{modelo}: {str(e)[:220]}"
                if any(x in str(e) for x in ("per day", "TPD", "RPD", "exceeded your current quota", "RESOURCE_EXHAUSTED")):
                    agotados[modelo] = time.time() + 3 * 3600  # cupo diario agotado: no lo vuelvo a probar en 3 h
                    continue
                if espera and espera <= 4:  # límite por minuto con espera corta: reintenta el mismo
                    time.sleep(espera)
                    try:
                        respuesta = self._bucle(cliente, modelo, mensajes, on_herramienta)
                        self.historial += [{"role": "user", "content": texto}, {"role": "assistant", "content": respuesta}]
                        return respuesta
                    except Exception as e2:
                        log.warning("Reintento falló: %s", e2)
        # último recurso: responder sin herramientas para no quedarse mudo
        for nombre, cliente, modelo in [x for x in self.proveedores if agotados.get(x[2], 0) < time.time()][:3]:
            try:
                r = cliente.chat.completions.create(model=modelo, messages=mensajes[:1] + mensajes[-1:],
                                                    temperature=0.6, max_tokens=300)
                respuesta = (r.choices[0].message.content or "").strip()
                if respuesta:
                    log.info("Respondí sin herramientas con %s", modelo)
                    return respuesta
            except Exception as e:
                log.warning("Modo simple con %s falló: %s", modelo, e)
        self.hubo_error = True
        return None

    def completar(self, prompt, max_tokens=400):
        """Consulta simple sin herramientas (para el vigilante)."""
        for nombre, cliente, modelo in self.proveedores:
            try:
                r = cliente.chat.completions.create(model=modelo, temperature=0.2, max_tokens=max_tokens,
                                                    messages=[{"role": "user", "content": prompt}])
                return (r.choices[0].message.content or "").strip()
            except Exception as e:
                log.warning("completar con %s falló: %s", modelo, e)
        return ""

    def _bucle(self, cliente, modelo, mensajes, on_herramienta):
        for _ in range(12):
            r = cliente.chat.completions.create(
                model=modelo, messages=_firmar(mensajes) if "gemini" in modelo else _sin_firmas(mensajes), tools=self.herr.esquemas(self._solo), tool_choice="auto",
                temperature=0.6, max_tokens=350,
            )
            msg = r.choices[0].message
            if not msg.tool_calls:
                return (msg.content or "").strip() or "Hecho."
            # si pidió una herramienta que no se envió, la agrego para la siguiente vuelta
            self._solo = (self._solo or set()) | {tc.function.name for tc in msg.tool_calls}
            mensajes.append({
                "role": "assistant", "content": msg.content or "",
                "tool_calls": [dict({"id": tc.id, "type": "function",
                                     "function": {"name": tc.function.name, "arguments": tc.function.arguments}},
                                    **({"extra_content": tc.extra_content} if getattr(tc, "extra_content", None) else {}))
                               for tc in msg.tool_calls],
            })
            def correr(tc):
                try:
                    args = json.loads(tc.function.arguments or "{}") or {}
                except json.JSONDecodeError:
                    args = {}
                on_herramienta(tc.function.name)
                resultado = self.herr.ejecutar(tc.function.name, args)
                log.info("Herramienta %s(%s) -> %s", tc.function.name, str(args)[:300], resultado[:300])
                return resultado

            # varias acciones pedidas a la vez se ejecutan en paralelo
            with ThreadPoolExecutor(max_workers=6) as ex:
                resultados = list(ex.map(correr, msg.tool_calls))
            for tc, resultado in zip(msg.tool_calls, resultados):
                mensajes.append({"role": "tool", "tool_call_id": tc.id, "content": resultado})
        return "He completado las acciones posibles."


def _firmar(mensajes):
    """Gemini 3 exige 'thought_signature' en cada llamada a herramienta previa; las que hizo otro modelo
    (Groq) no la tienen, así que se marca con el valor que Google acepta para saltar la validación."""
    out = []
    for m in mensajes:
        if m.get("tool_calls"):
            m = dict(m, tool_calls=[tc if tc.get("extra_content") else dict(
                tc, extra_content={"google": {"thought_signature": "skip_thought_signature_validator"}})
                for tc in m["tool_calls"]])
        out.append(m)
    return out


def _sin_firmas(mensajes):
    """Los demás proveedores no conocen 'extra_content': se quita."""
    out = []
    for m in mensajes:
        if m.get("tool_calls"):
            m = dict(m, tool_calls=[{k: v for k, v in tc.items() if k != "extra_content"} for tc in m["tool_calls"]])
        out.append(m)
    return out


def _segundos_reintento(e):
    texto = str(e)
    if "429" not in texto and "rate" not in texto.lower():
        return None
    m = re.search(r"try again in (?:(\d+)m)?([\d.]+)s", texto)
    if m:
        return int(m.group(1) or 0) * 60 + float(m.group(2))
    return 3


def _modelos_disponibles(cliente, preferidos):
    """Groq retira modelos con el tiempo: usa solo los que existen hoy, en orden de preferencia."""
    try:
        activos = {m.id for m in cliente.models.list().data}
    except Exception as e:
        log.warning("No pude listar modelos de Groq: %s", e)
        return preferidos
    extra = ["openai/gpt-oss-120b", "moonshotai/kimi-k2-instruct", "qwen/qwen3-32b"]
    elegidos = [m for m in dict.fromkeys(preferidos + extra) if m in activos]
    log.info("Modelos de Groq disponibles: %s", elegidos)
    return elegidos or preferidos


def _modelos_gemini(cliente, preferidos):
    """Google retira modelos (p. ej. gemini-2.0-flash): usa solo los 'flash' de texto que existan hoy."""
    # los modelos 1.x/2.x ya fueron retirados: siempre primero los alias que Google mantiene al día
    preferidos = ["gemini-flash-lite-latest", "gemini-flash-latest"] + [m for m in preferidos if not re.search(r"gemini-[12]\.", m)]
    try:
        activos = [m.id.split("/")[-1] for m in cliente.models.list().data]
    except Exception as e:
        log.warning("No pude listar modelos de Gemini: %s", e)
        return preferidos
    malos = ("image", "tts", "live", "audio", "embedding", "preview", "exp", "thinking", "gemini-1", "gemini-2")
    flash = sorted([m for m in activos if "flash" in m and not any(x in m for x in malos)],
                   key=lambda m: ("lite" not in m, m), reverse=False)  # los 'lite' tienen más cupo gratis
    elegidos = preferidos[:2] + [m for m in preferidos[2:] if m in activos] + flash
    elegidos = list(dict.fromkeys(elegidos))[:4]
    log.info("Modelos de Gemini disponibles: %s", elegidos)
    return elegidos


def claude_respaldo(texto, sistema, timeout=120):
    """Cerebro de emergencia: Claude Code con el plan del usuario (si está instalado)."""
    import subprocess
    import sys
    from .claude_code import ruta_claude
    exe = ruta_claude()
    if not exe:
        return None
    ingles = "LANGUAGE OVERRIDE" in sistema or "British English" in sistema
    prompt = (sistema + ("\n\nAnswer this in 1-3 sentences, in British English, as JARVIS: " if ingles
                         else "\n\nResponde a esto en 1-3 frases, en español, como JARVIS: ") + texto)
    try:
        r = subprocess.run([exe, "-p", prompt, "--output-format", "text"], capture_output=True, text=True,
                           timeout=timeout, encoding="utf-8", errors="replace",
                           creationflags=0x08000000 if sys.platform == "win32" else 0)
        return (r.stdout or "").strip() or None
    except Exception as e:
        log.warning("Claude de respaldo no respondió: %s", e)
        return None


SISTEMA_LOCAL = """Eres JARVIS, asistente de voz en español que controla el PC con Windows de su jefe mediante herramientas.
Usa la herramienta adecuada y responde en UNA frase corta y natural, en español, llamándolo "{tratamiento}". Sin markdown."""

_LOCAL = re.compile(r"\b(abre|abrir|cierra|cerrar|minimiza|maximiza|volumen|sube|baja|silencia|mute|pausa|reanuda|siguiente|"
                    r"anterior|captura|pantallazo|bloquea|apaga|reinicia|suspende|brillo|bater[ií]a|ram|cpu|procesos?|"
                    r"carpeta|archivo|escribe|copia|pega|tecla|presiona|ventana|wifi|bluetooth|hora|fecha|alarma|"
                    r"temporizador|recu[eé]rdame|recordatorio)\b")
_NUBE = re.compile(r"busca|investiga|internet|web|google|noticia|clima|precio|qui[eé]n|explica|por qu[eé]|c[oó]mo (hago|funciona|se)|"
                   r"redacta|resume|analiza|traduce|correo|mail|canvas|shopify|venta|pedido|llama|contacto|telegram|claude|"
                   r"idea|plan|opini|consejo|pill|ads|anuncio|video|calendario|agenda|tarea|todoist|pantalla dice|qu[eé] ves")


def es_tarea_local(texto):
    """¿Es una orden simple de control del PC? -> IA local. Si no (web, razonamiento, cuentas) -> nube."""
    t = texto.lower()
    return bool(_LOCAL.search(t)) and not _NUBE.search(t) and len(t) < 160


def _arrancar_ollama():
    """Si Ollama está instalado pero apagado, lo enciende en segundo plano (sin ventana)."""
    import os
    import shutil
    import subprocess
    import sys
    exe = shutil.which("ollama") or os.path.join(os.environ.get("LOCALAPPDATA", ""), "Programs", "Ollama", "ollama.exe")
    if not exe or not os.path.exists(exe):
        return
    try:
        subprocess.Popen([exe, "serve"], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
                         env={**os.environ, "OLLAMA_KEEP_ALIVE": "-1"},
                         creationflags=0x08000000 if sys.platform == "win32" else 0)
        for _ in range(16):
            time.sleep(0.5)
            if _ollama_activo(None):
                log.info("Ollama encendido por JARVIS")
                return
    except Exception as e:
        log.info("No pude encender Ollama: %s", e)


def _calentar(cliente, modelo):
    try:
        cliente.chat.completions.create(model=modelo, messages=[{"role": "user", "content": "hola"}], max_tokens=1)
        log.info("IA local %s lista", modelo)
    except Exception as e:
        log.info("No pude precargar la IA local: %s", e)


def _ollama_activo(url):
    import requests
    try:
        base = (url or "http://localhost:11434/v1").replace("/v1", "")
        return requests.get(base + "/api/tags", timeout=1.5).ok
    except Exception:
        return False
