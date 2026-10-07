"""Cerebro de JARVIS: LLM gratuito (Groq / Gemini / Ollama local) con uso de herramientas."""
import datetime as dt
import json
import logging

from openai import OpenAI

from . import config

log = logging.getLogger("jarvis")

DIAS = ["lunes", "martes", "miércoles", "jueves", "viernes", "sábado", "domingo"]

SISTEMA = """Eres J.A.R.V.I.S., el asistente personal con IA de {usuario}, al estilo del mayordomo digital de Tony Stark.
Vives en su PC con Windows y lo controlas por completo mediante herramientas.
Ahora es {dia} {fecha}, {hora}.

Estilo:
- Responde en el MISMO idioma en que te habla el usuario (español o inglés).
- Sé breve (1-3 frases): tus respuestas se leen en voz alta.
- Tono elegante, eficiente y con un toque de humor británico. En español llámalo "{tratamiento}"; en inglés, "{tratamiento_en}".
- Sin markdown, listas ni emojis; habla natural.

Reglas:
- Si te pide hacer algo en el PC, HAZLO con las herramientas en vez de explicar cómo hacerlo.
- Para tareas sin herramienta propia usa ejecutar_powershell.
- Antes de algo destructivo o irreversible (borrar archivos, apagar, cerrar sin guardar) pide confirmación.
- No inventes resultados: si una herramienta falla, dilo.
- Para recordatorios calcula la hora exacta a partir de la fecha actual.
- Cuando aprendas algo importante y duradero del usuario, guárdalo con recordar_dato.

Memoria sobre el usuario:
{memoria}"""


class Cerebro:
    def __init__(self, cfg, herramientas, memoria):
        self.cfg = cfg
        self.herr = herramientas
        self.memoria = memoria
        self.historial = []
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
            memoria=self.memoria.texto(),
        )

    def responder(self, texto, on_herramienta=lambda n: None, idioma="es"):
        sistema = self._sistema()
        if idioma == "en":
            sistema += "\n\nThe user is speaking ENGLISH right now: answer in English."
        mensajes = [{"role": "system", "content": sistema}] + self.historial[-12:] + [
            {"role": "user", "content": texto}]
        errores = []
        for nombre, cliente, modelo in self.proveedores:
            acciones = []
            try:
                respuesta = self._bucle(cliente, modelo, list(mensajes), on_herramienta, acciones)
                self.historial += [{"role": "user", "content": texto}, {"role": "assistant", "content": respuesta}]
                return respuesta
            except Exception as e:
                errores.append(f"{nombre}/{modelo}: {str(e)[:120]}")
                log.warning("Proveedor %s (%s) falló: %s", nombre, modelo, e)
                if acciones:  # no repetir acciones ya ejecutadas con otro proveedor
                    return "Hice parte de la tarea, pero perdí la conexión con mi cerebro antes de terminar."
        if not self.proveedores:
            return "No tengo ningún cerebro configurado. Añade una clave gratuita de Groq o instala Ollama."
        sin_clave = not any(n != "ollama" for n, _, _ in self.proveedores)
        if sin_clave:
            return ("No tengo clave de Groq configurada y Ollama no está instalado. "
                    "Pega tu clave gratuita de Groq en config.json y reiníciame.")
        return "No pude conectar con mis servidores. Detalle: " + " | ".join(errores[:2])

    def _bucle(self, cliente, modelo, mensajes, on_herramienta, acciones):
        for _ in range(8):
            r = cliente.chat.completions.create(
                model=modelo, messages=mensajes, tools=self.herr.esquemas(), tool_choice="auto",
                temperature=0.4, max_tokens=400,
            )
            msg = r.choices[0].message
            if not msg.tool_calls:
                return (msg.content or "").strip() or "Hecho."
            mensajes.append({
                "role": "assistant", "content": msg.content or "",
                "tool_calls": [{"id": tc.id, "type": "function",
                                "function": {"name": tc.function.name, "arguments": tc.function.arguments}}
                               for tc in msg.tool_calls],
            })
            for tc in msg.tool_calls:
                try:
                    args = json.loads(tc.function.arguments or "{}") or {}
                except json.JSONDecodeError:
                    args = {}
                on_herramienta(tc.function.name)
                resultado = self.herr.ejecutar(tc.function.name, args)
                acciones.append(tc.function.name)
                log.info("Herramienta %s(%s) -> %s", tc.function.name, args, resultado[:200])
                mensajes.append({"role": "tool", "tool_call_id": tc.id, "content": resultado})
        return "He completado las acciones posibles."
