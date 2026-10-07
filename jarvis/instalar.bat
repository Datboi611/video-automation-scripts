@echo off
chcp 65001 >nul
cd /d "%~dp0"
echo.
echo   === Instalando J.A.R.V.I.S. ===
echo.
set PY=
py -3.12 --version >nul 2>nul && set "PY=py -3.12"
if not defined PY python --version >nul 2>nul && set "PY=python"
if not defined PY (echo [!] Instala Python 3.12 desde https://www.python.org/downloads/release/python-31210/ marcando "Add python.exe to PATH" & pause & exit /b 1)
echo Usando:
%PY% --version
if exist .venv rmdir /s /q .venv
%PY% -m venv .venv || (echo [!] No pude crear el entorno & pause & exit /b 1)
call .venv\Scripts\activate.bat
python -m pip install --upgrade pip setuptools wheel
pip install --prefer-binary -r requirements.txt || (echo [!] Error instalando dependencias & pause & exit /b 1)
if not exist modelos mkdir modelos
if not exist modelos\vosk-model-small-en-us-0.15 (
  echo Descargando detector de palabra de activacion...
  powershell -NoProfile -Command "Invoke-WebRequest https://alphacephei.com/vosk/models/vosk-model-small-en-us-0.15.zip -OutFile modelos\vosk.zip; Expand-Archive modelos\vosk.zip -DestinationPath modelos -Force; Remove-Item modelos\vosk.zip"
)
if not exist config.json copy config.example.json config.json >nul
call crear_acceso_directo.bat
echo.
echo   Listo. 1) Abre config.json y pega tu clave gratis de Groq.  2) Ejecuta iniciar.bat
echo.
pause
