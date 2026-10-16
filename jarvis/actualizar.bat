@echo off
chcp 65001 >nul
cd /d "%~dp0"
echo Descargando la ultima version de JARVIS...
set "Z=%TEMP%\jarvis_nuevo"
if exist "%Z%" rmdir /s /q "%Z%"
mkdir "%Z%"
powershell -NoProfile -Command "Invoke-WebRequest 'https://codeload.github.com/datboi611/video-automation-scripts/zip/refs/heads/claude/fervent-feynman-75e4cj' -OutFile '%Z%\j.zip'; Expand-Archive '%Z%\j.zip' '%Z%' -Force" || (echo [!] No se pudo descargar & pause & exit /b 1)
for /d %%D in ("%Z%\video-automation-scripts-*") do robocopy "%%D\jarvis" "%~dp0." /E /XF config.json /XD datos .venv voces >nul
echo Actualizando dependencias...
call .venv\Scripts\activate.bat
pip install --prefer-binary -q -r requirements.txt
echo.
echo   Listo. Cierra JARVIS y abrelo de nuevo.
pause
