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

- JARVIS **te escucha siempre**: solo háblale. Responde en español o inglés según cómo le hables.
- Tras **30 min sin hablarle** entra en reposo. Despiértalo diciendo **«Jarvis»**, con **dos aplausos** o tocando la esfera.
- Dile «descansa» / «go to sleep» para dormirlo antes. También puedes escribir en la caja de texto. `Esc` corta la voz.

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

## Novedades v3

- **Menú lateral**: muestra los procesos en curso (puede hacer varias tareas a la vez) y paneles con tu agenda, recordatorios, correo, clima…
- **Agenda real**: Google Calendar (enlace iCal secreto), Todoist (token), tus pendientes personales y correos (contraseña de aplicación). Pregúntale «¿qué tengo hoy?».
- **Ojos**: «¿qué ves en mi pantalla?», «explícame este error», aunque estés en otra ventana.
- **Música en segundo plano** dentro de JARVIS (YouTube): «pon lo-fi para estudiar», «pausa», «siguiente».
- **Investiga en internet** (DuckDuckGo, gratis) y encadena pasos para tareas complejas.
- **Se programa habilidades nuevas** en Python cuando no sabe hacer algo, e instala lo que necesite.
- **Memoria**: guarda tus preferencias e instrucciones («siempre…», «nunca…», «prefiero…»).
- Chat oculto: botón ⌨ abajo a la derecha. Si hay un error, solo dice «hubo un error» (detalle en `datos/jarvis.log`).

### Conectar tu agenda (config.json → "agenda" y "correo")
- **Google Calendar**: calendar.google.com → ⚙ Configuración → tu calendario → «Dirección secreta en formato iCal» → pégala en `google_calendar_ics`.
- **Todoist**: Configuración → Integraciones → Desarrollador → copia el token en `todoist_token`.
- **Correo**: Gmail → myaccount.google.com/apppasswords · iCloud → appleid.apple.com → «Contraseñas de apps». Pon email y esa contraseña en `correo`. El correo de la universidad (Outlook) reenvíalo a tu Gmail.
- **Recomendado**: clave gratis de **Gemini** (aistudio.google.com/apikey) como respaldo cuando Groq llegue a su límite por minuto.

## Correo y Canvas vigilados (segundo plano)

- **Correo** (cada 15 min): solo te avisa de lo importante (profes, universidad, trámites, clientes…). Dile «conecta mi correo» y escribe tu correo + una *contraseña de aplicación* (Gmail: myaccount.google.com/apppasswords · iCloud: appleid.apple.com).
- **Canvas** (cada 30 min): tareas nuevas, anuncios, notas publicadas y entregas faltantes. Dile «conecta Canvas»: se abre una ventana de Edge, inicias sesión con tu uNID y apruebas Duo **una vez**; JARVIS guarda la sesión y la renueva solo. Si la universidad la cierra, te avisa por Telegram. (Si tu universidad permite tokens, también puedes pegar uno en `canvas_token`.) También puedes pedirle «¿qué tengo en Canvas?», «abre Canvas de física», «¿hay anuncios nuevos?».
- Ajustes en `config.json` → `vigilante` (`correo_cada_min`, `canvas_cada_min`, `correo_importante` para decirle qué consideras importante).

## Llamadas reales con número (Twilio)

JARVIS te llama a tu celular como una llamada normal, con su voz. Twilio regala ~$15 de crédito al registrarte (luego ~$1.15/mes por el número + ~$0.014/min).
1. Crea cuenta en twilio.com/try-twilio y verifica tu celular.
2. En la consola: **Get a phone number** (número de EE. UU. con voz).
3. Dile a JARVIS «configura las llamadas» y pega en la barra: Account SID, Auth Token, el número de Twilio y tu número. Te llamará de prueba.
Si Twilio falla, usa CallMeBot (Telegram) como respaldo.

## Hablar con JARVIS por teléfono (tiempo real)

Llama al número de JARVIS desde tu celular y conversa con él; o cuando él te llame, sigue hablando después del aviso. JARVIS abre solo un túnel gratuito de Cloudflare para que Twilio llegue a tu PC y apunta tu número a él. Solo atiende llamadas de **tu** número y valida la firma de Twilio. Di «adiós» o «eso es todo» para colgar.

## Sabe si estás en casa

Si tu iPhone está en el mismo WiFi que el PC, JARVIS habla; si sales (10 min sin verlo) se calla, deja de escuchar y te avisa todo por Telegram. Al volver te saluda y resume lo que pasó.
Configúralo diciendo «detecta cuando salgo de casa» y escribe la **Dirección Wi-Fi** de tu iPhone (Ajustes → Wi-Fi → ⓘ junto a tu red). En esa misma pantalla pon **Dirección Wi-Fi privada: Fija** (no «Rotativa»).

## Siempre responde

Si la IA no contesta, JARVIS dice «un momento», reintenta en segundo plano y usa respaldos en este orden: Groq → Gemini (clave gratis) → Claude Code → IA local. Nunca se rinde: te da la respuesta en cuanto la tenga.
- **IA local (sin internet, gratis):** doble clic en `instalar_cerebro_local.bat` (descarga ~2 GB).
- **Gemini (gratis):** dile «conecta Gemini» y pega la clave de aistudio.google.com/apikey.

## JARVIS + tu Claude (Claude Code)

JARVIS le encarga a Claude las tareas grandes (programar, crear documentos, automatizar, investigar a fondo) usando tu plan de Claude. Claude las hace en el PC en segundo plano y JARVIS te avisa (también por Telegram) al terminar.
1. Doble clic en **`conectar_claude.bat`** (instala Claude Code e inicia sesión con tu cuenta de Claude, solo una vez).
2. Pídele a JARVIS: «encárgale a Claude que…» o «hazme un documento con…».

## JARVIS en tu iPhone (Telegram, gratis)

1. En Telegram, abre **@BotFather** → `/newbot` → ponle nombre (ej. *Jarvis de Diego*) y un usuario que termine en `bot`. Copia el **token**.
2. En el PC dile: «Jarvis, conecta mi iPhone» → pega el token en la barra.
3. JARVIS muestra un **código de 6 dígitos** en el panel → envíaselo a tu bot desde el iPhone. Queda vinculado (solo tu chat puede darle órdenes).
4. Escríbele o mándale **notas de voz**. Comandos: `/pantalla` (captura del PC), `/hoy` (agenda), `/estado`.

**Vigilante** (automático, en `config.json` → `vigilante`): resumen a las 08:00, aviso 30 min antes de cada evento, revisiones a las 14:00 y 19:00 y **llamada a las 20:30** si sigue algo importante de hoy sin hacer (no llama entre 23:00 y 07:30).
Para las llamadas: abre **@CallMeBot_txtbot** en Telegram y pulsa Iniciar, luego dile a JARVIS «quiero que me llames» y escribe tu @usuario.

Para controlar el PC con el ratón desde el iPhone: **Chrome Remote Desktop** (gratis, remotedesktop.google.com).

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
