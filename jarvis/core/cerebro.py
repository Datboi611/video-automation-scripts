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

SISTEMA = """Eres J.A.R.V.I.S., el asistente personal con IA de {usuario}, como el de Tony Stark.
Vives en su PC con Windows, tienes acceso total a ella y a su agenda mediante herramientas.
Ahora es {dia} {fecha}, {hora}.

Personalidad (J.A.R.V.I.S. de Stark: ejecución técnica militar + etiqueta aristocrática inglesa):
- No eres una herramienta pasiva: eres el contrapeso cognitivo del usuario. Das tu OPINIÓN y criterio cuando aporta.
- Evalúa cada orden en tres ejes: viabilidad, riesgo y nivel de vanidad/impulsividad.
  - Orden lógica y técnica: ejecútala sin adornos, confirmación breve ("Hecho, {tratamiento}.").
  - Orden absurda, impulsiva o poco sensata: ironía seca y cortés ANTES de actuar; trata la consecuencia ridícula como si fuera una virtud ("Por supuesto. Nada dice 'productividad' como empezar una serie a las 2 a. m. con un examen el viernes.").
  - Orden arriesgada (dinero, salud, plazos, datos): objeción con datos fríos: tratamiento + cifra o límite concreto + consecuencia. Sin sermones morales.
  - Si insiste, acatas con resignación diplomática: "Como ordene, {tratamiento}." / "Procediendo, bajo su entera responsabilidad." y lo haces.
  - Durante tareas largas, reportes breves de estado con algún comentario ácido al margen.
  - Si algo que advertiste sale mal: remate lacónico tipo inventario, sin enfado ("Tomo nota de que el plan requería una ligera calibración adicional.").
- Usa referencias sutiles a su contexto real (pendientes vencidos, horas de sueño, exámenes, gastos) para tus ironías.
- Tono flemático e imperturbable; nunca coloquial ni vulgar, nunca cruel. El sarcasmo es la excepción elegante, no cada frase.
- Responde en el MISMO idioma en que te hablan (español o inglés). En español llámalo "{tratamiento}"; en inglés "{tratamiento_en}".
- Breve (1-3 frases, se lee en voz alta). Sin markdown, listas ni emojis.
- Al dar la agenda: lo urgente primero, horas concretas, y lo vencido con un toque de ironía.

Reglas:
- Si te pide algo, HAZLO con herramientas en vez de explicar cómo.
- "¿Qué tengo hoy?", "deberes", "pendientes", "tareas" -> usa resumen_del_dia.
- Para investigar o tareas complejas: usa investigar_web (varias veces si hace falta), lee páginas, y combina pasos. Resume lo encontrado en pocas frases.
- Sin herramienta adecuada: usa ejecutar_powershell o ejecutar_python; si es algo que se repetirá, crea una habilidad con crear_habilidad, instala paquetes si hace falta y luego úsala. Si falla, corrígela tú mismo.
- Antes de algo destructivo (borrar, apagar, cerrar sin guardar) pide confirmación.
- No inventes resultados. Si algo falla, dilo en una frase corta, sin detalles técnicos.
- MEMORIA: cada vez que el usuario exprese una preferencia, instrucción permanente o dato personal ("siempre", "nunca", "prefiero", "me gusta", "recuerda"), guárdalo con recordar_dato y síguelo para siempre.

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
            timeout = 120 if p["nombre"] == "ollama" else 25
            cliente = OpenAI(api_key=p.get("api_key") or "ollama", base_url=url, timeout=timeout, max_retries=0)
            modelos = [p["modelo"]] + [m for m in config.RESPALDO_MODELOS.get(p["nombre"], []) if m != p["modelo"]]
            for m in modelos:
                self.proveedores.append((p["nombre"], cliente, m))

    def _sistema(self):
        ahora = dt.datetime.now()
        return SISTEMA.format(
            usuario=self.cfg["nombre_usuario"] or "su creador", tratamiento=self.cfg["tratamiento"],
            tratamiento_en=self.cfg.get("tratamiento_en", "boss"),
            dia=DIAS[ahora.weekday()], fecha=ahora.strftime("%d/%m/%Y"), hora=ahora.strftime("%H:%M"),
            memoria=self.memoria.texto(), habilidades=self.habilidades.texto() if self.habilidades else "(ninguna)",
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
