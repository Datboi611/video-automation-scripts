@echo off
chcp 65001 >nul
echo.
echo   === Voz de George en espanol, gratis y local (XTTS-v2) ===
echo   Clona la voz de George a partir de voces\george_es.wav y la genera en tu PC.
echo   Descarga unos 4 GB (PyTorch + modelo). Va rapido con tu tarjeta grafica NVIDIA.
echo.
cd /d "%~dp0"
if not exist ".venv\Scripts\python.exe" (echo [!] Ejecuta esto dentro de la carpeta de JARVIS. & pause & exit /b 1)
".venv\Scripts\python.exe" -m pip install --upgrade pip
".venv\Scripts\python.exe" -m pip install torch torchaudio --index-url https://download.pytorch.org/whl/cu121
".venv\Scripts\python.exe" -m pip install coqui-tts
echo Descargando el modelo y probando la voz...
set COQUI_TOS_AGREED=1
".venv\Scripts\python.exe" -c "from TTS.api import TTS; TTS('tts_models/multilingual/multi-dataset/xtts_v2'); print('OK')"
echo.
echo   Listo. Abre JARVIS y dile: "Jarvis, usa la voz de George".
pause
