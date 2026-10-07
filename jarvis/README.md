# J.A.R.V.I.S. — Asistente de voz en español para Windows

Asistente personal estilo Iron Man: interfaz holográfica azul, se activa diciendo **«Jarvis»** o con **dos aplausos**, controla el PC, recuerda cosas, te avisa en el celular y hasta **te llama**. Todo con herramientas **gratuitas**.

| Pieza | Herramienta gratuita |
|---|---|
| Activación «Jarvis» | Vosk (offline) |
| Activación por aplausos | Detector propio (offline) |
| Voz → texto | Whisper en Groq (gratis, rapidísimo) o faster-whisper local (offline) |
| Cerebro (IA) | Groq Llama 3.3 70B → Gemini Flash → Ollama local (respaldo automático) |
| Texto → voz | Voces neuronales de Microsoft (edge-tts) o voz de Windows (offline) |
| Notificaciones al celular | ntfy.sh |
| Llamadas al celular | CallMeBot (llamada de Telegram) |
| Interfaz | pywebview (HTML/Canvas) |

## Instalación (en la laptop con Windows)

1. Instala **Python 3.12** desde https://www.python.org/downloads/ y marca **«Add python.exe to PATH»**.
2. Copia la carpeta `jarvis` a la laptop y haz doble clic en **`instalar.bat`**.
3. Saca tu clave gratis de Groq en https://console.groq.com/keys y pégala en `config.json` → `llm.proveedores[0].api_key`.
   - Opcional: clave gratis de Gemini en https://aistudio.google.com/apikey (respaldo).
   - Opcional 100 % offline y para siempre: instala [Ollama](https://ollama.com) y ejecuta `ollama pull qwen2.5:7b`.
4. Pon tu nombre en `nombre_usuario`.
5. Doble clic en **`iniciar.bat`**. Para que arranque solo con Windows: **`inicio_automatico.bat`**.

## Cómo usarlo

- Di **«Jarvis»**, aplaude **dos veces** o toca la esfera → suena un *bip* → da tu orden.
- Tras responder sigue escuchando unos segundos (conversación continua). Di «gracias» para terminar.
- También puedes escribir en la caja de texto. `Esc` corta la voz.

Ejemplos:
- «Jarvis, abre Spotify y pon la siguiente canción»
- «Sube el volumen al 40»
- «¿Cómo está el clima en Lima mañana?»
- «Recuérdame en 20 minutos sacar la ropa y llámame por teléfono»
- «Todos los días a las 8 recuérdame tomar agua»
- «Busca el archivo del contrato y ábrelo»
- «¿Cuánta batería me queda? ¿Qué está consumiendo RAM?»
- «Cierra Chrome», «bloquea el PC», «haz una captura de pantalla»
- «Recuerda que mi reunión de los lunes es a las 10»

## Conectar tu celular (gratis)

**Notificaciones (ntfy):**
1. Instala la app **ntfy** (Android / iPhone).
2. Suscríbete a un tema con un nombre largo y secreto, p. ej. `jarvis-diego-8f3k2q`.
3. Pon ese nombre en `config.json` → `telefono.ntfy_tema`.

**Llamadas (Telegram + CallMeBot):**
1. Necesitas un `@usuario` en Telegram.
2. Autoriza al bot: abre https://api.callmebot.com/telegram y sigue el paso (escribir a **@CallMeBot_txtbot**).
3. Pon tu `@usuario` en `telefono.telegram_usuario`.

**Control remoto desde el celular (opcional):** activa `"control_remoto": true` y suscríbete en ntfy a `<tu_tema>-ordenes`. Lo que publiques ahí lo ejecuta JARVIS y te responde por notificación. Usa un nombre de tema difícil de adivinar: quien lo conozca puede darle órdenes a tu PC.

## Ajustes útiles (`config.json`)

- `voz.voz`: `es-MX-JorgeNeural`, `es-ES-AlvaroNeural`, `es-PE-AlexNeural`, `es-CO-GonzaloNeural`…
- `activacion.umbral_aplauso`: súbelo (0.4–0.5) si se activa solo; bájalo (0.2) si no detecta tus aplausos.
- `activacion.aplausos`: `false` para desactivar aplausos.
- `microfono`: número o nombre del micrófono si no usa el correcto (`python -m sounddevice` los lista).
- `tratamiento`: cómo te llama («señor», «jefe», tu nombre…).

## Seguridad

- JARVIS tiene control total del PC. Pide confirmación antes de apagar o borrar, y bloquea comandos destructivos (formatear discos, etc.).
- `config.json` guarda tus claves: no lo compartas.
- Registro de actividad en `datos/jarvis.log`; memoria y recordatorios en `datos/`.

## Sobre «gratis de por vida»

- Ollama + Whisper local + voz de Windows funcionan **100 % offline y sin coste para siempre**.
- Groq, Gemini, edge-tts, ntfy y CallMeBot son gratuitos hoy pero dependen de terceros. Si alguno deja de funcionar, JARVIS pasa solo al siguiente respaldo.
