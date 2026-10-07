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
- Llámalo "{tratamiento}". Flemático, preciso, jamás vulgar ni cruel. Breve: 2-4 frases, se lee en voz alta. Sin markdown, listas ni emojis.
- Usa su contexto real (tareas vencidas, exámenes, horas, gastos) para tus comentarios.

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
- "Marca X como hecha" -> marcar_hecho.
- "Conecta Canvas" -> pedir_dato canvas_token. "Conecta mi correo" -> pedir_dato correo_email.
- "Conecta mi iPhone/Telegram" -> pedir_dato telegram_bot_token. "Que me llames" -> pedir_dato telegram_usuario.
- Si necesitas un dato que el usuario debe escribir (token, enlace, clave, contraseña de aplicación) usa pedir_dato con el campo correcto; se guarda solo.
- Si no entendiste una orden compleja, usa pedir_texto para que te la escriba.
- Tareas grandes (programar, crear documentos/archivos, automatizar, investigación profunda, "hazlo tú", "que lo haga Claude") -> delegar_a_claude con una descripción detallada; confirma que lo encargaste y que avisarás al terminar.
- Investigaciones rápidas: investigar_web (varias veces si hace falta) y resume en pocas frases; detalles en mostrar_panel.
- Sin herramienta adecuada: ejecutar_powershell o ejecutar_python; si se repetirá, crea una habilidad con crear_habilidad.
- Antes de algo destructivo (borrar, apagar, cerrar sin guardar) pide confirmación.
- No inventes resultados. Si algo falla, dilo en una frase corta, sin detalles técnicos.
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
        self._solo = None
        self._previas = set()
        self.proveedores = []
        for p in cfg["llm"]["proveedores"]:
            if p["nombre"] != "ollama" and not p.get("api_key"):
                continue
            url = p.get("url") or config.URLS_PROVEEDOR.get(p["nombre"])
            timeout = 120 if p["nombre"] == "ollama" else 40 if p["nombre"] == "claude" else 25
            cliente = OpenAI(api_key=p.get("api_key") or "ollama", base_url=url, timeout=timeout, max_retries=0)
            modelos = [p["modelo"]] + [m for m in config.RESPALDO_MODELOS.get(p["nombre"], []) if m != p["modelo"]]
            for m in modelos:
                self.proveedores.append((p["nombre"], cliente, m))

    def _sistema(self):
        ahora = dt.datetime.now()
        return SISTEMA.format(
            usuario=self.cfg["nombre_usuario"] or "su creador", tratamiento=self.cfg["tratamiento"],
            dia=DIAS[ahora.weekday()], fecha=ahora.strftime("%d/%m/%Y"), hora=ahora.strftime("%H:%M"),
            memoria=self.memoria.texto(), habilidades=self.habilidades.texto() if self.habilidades else "(ninguna)",
            idioma_regla=("Responde SIEMPRE en español." if self.cfg.get("idioma", "es") == "es"
                          else "Responde en el idioma en que te hablen (español o inglés)."),
        )

    def responder(self, texto, on_herramienta=lambda n: None, idioma="es"):
        self.hubo_error = False
        sistema = self._sistema()
        if idioma == "en":
            sistema += "\n\nThe user is speaking ENGLISH right now: answer in English."
        # Una sola conversación compartida: si un modelo falla a mitad, el siguiente continúa
        # desde ahí sin repetir las acciones ya hechas.
        mensajes = [{"role": "system", "content": sistema}] + self.historial[-8:] + [
            {"role": "user", "content": texto}]
        # solo las herramientas relevantes (+ las del turno anterior, para respuestas como "sí, hazlo")
        self._solo = herramientas_para(texto, self._previas)
        self._previas = herramientas_para(texto)
        for nombre, cliente, modelo in self.proveedores:
            try:
                respuesta = self._bucle(cliente, modelo, mensajes, on_herramienta)
                self.historial += [{"role": "user", "content": texto}, {"role": "assistant", "content": respuesta}]
                return respuesta
            except Exception as e:
                espera = _segundos_reintento(e)
                log.warning("Proveedor %s (%s) falló: %s", nombre, modelo, e)
                if espera and espera <= 4:  # límite por minuto con espera corta: reintenta el mismo
                    time.sleep(espera)
                    try:
                        respuesta = self._bucle(cliente, modelo, mensajes, on_herramienta)
                        self.historial += [{"role": "user", "content": texto}, {"role": "assistant", "content": respuesta}]
                        return respuesta
                    except Exception as e2:
                        log.warning("Reintento falló: %s", e2)
        self.hubo_error = True
        if not any(n != "ollama" for n, _, _ in self.proveedores):
            return ("Hubo un error: no tengo clave de Groq configurada." if idioma == "es"
                    else "There was an error: no Groq key configured.")
        return (f"Hubo un error, {self.cfg['tratamiento']}. Inténtelo de nuevo en un momento." if idioma == "es"
                else f"There was an error, {self.cfg.get('tratamiento_en', 'boss')}. Please try again in a moment.")

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
                model=modelo, messages=mensajes, tools=self.herr.esquemas(self._solo), tool_choice="auto",
                temperature=0.7, max_tokens=500,
            )
            msg = r.choices[0].message
            if not msg.tool_calls:
                return (msg.content or "").strip() or "Hecho."
            # si pidió una herramienta que no se envió, la agrego para la siguiente vuelta
            self._solo = (self._solo or set()) | {tc.function.name for tc in msg.tool_calls}
            mensajes.append({
                "role": "assistant", "content": msg.content or "",
                "tool_calls": [{"id": tc.id, "type": "function",
                                "function": {"name": tc.function.name, "arguments": tc.function.arguments}}
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


def _segundos_reintento(e):
    texto = str(e)
    if "429" not in texto and "rate" not in texto.lower():
        return None
    m = re.search(r"try again in (?:(\d+)m)?([\d.]+)s", texto)
    if m:
        return int(m.group(1) or 0) * 60 + float(m.group(2))
    return 3
