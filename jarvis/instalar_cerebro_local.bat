@echo off
chcp 65001 >nul
echo.
echo   === IA local de JARVIS (gratis, sin internet) ===
echo   Se encarga del control del PC (abrir, cerrar, volumen, ventanas...) al instante.
echo   La nube (Groq/Gemini/Claude) queda para busquedas y tareas complejas.
echo   Descarga unos 2 GB, solo una vez.
echo.
where ollama >nul 2>nul
if errorlevel 1 (
  echo Instalando Ollama...
  winget install -e --id Ollama.Ollama --accept-source-agreements --accept-package-agreements
  set "PATH=%PATH%;%LOCALAPPDATA%\Programs\Ollama"
)
rem mantener el modelo cargado en memoria para responder al instante
setx OLLAMA_KEEP_ALIVE -1 >nul
start "" /min ollama serve
timeout /t 5 >nul
echo Descargando el modelo qwen2.5:3b (rapido y bueno usando herramientas)...
ollama pull qwen2.5:3b
echo.
echo   Listo. Cierra y vuelve a abrir JARVIS.
pause
