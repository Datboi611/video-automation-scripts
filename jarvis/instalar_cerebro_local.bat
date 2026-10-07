@echo off
chcp 65001 >nul
echo.
echo   === Cerebro local de respaldo para JARVIS (gratis, sin internet) ===
echo   Descarga unos 2 GB. Solo se usa si Groq, Gemini y Claude no responden.
echo.
where ollama >nul 2>nul
if errorlevel 1 (
  echo Instalando Ollama...
  winget install -e --id Ollama.Ollama --accept-source-agreements --accept-package-agreements
  set "PATH=%PATH%;%LOCALAPPDATA%\Programs\Ollama"
)
echo Descargando el modelo qwen2.5:3b...
ollama pull qwen2.5:3b
echo.
echo   Listo. Reinicia JARVIS: ahora siempre tendra un cerebro disponible.
pause
