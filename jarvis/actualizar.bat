@echo off
chcp 65001 >nul
cd /d "%~dp0"
echo Actualizando dependencias de JARVIS...
call .venv\Scripts\activate.bat
pip install --prefer-binary -r requirements.txt || (echo [!] Error actualizando & pause & exit /b 1)
echo.
echo   Listo. Abre JARVIS desde el icono del escritorio.
pause
