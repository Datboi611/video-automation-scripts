@echo off
chcp 65001 >nul
echo.
echo   === Conectar JARVIS con tu Claude (Claude Code) ===
echo.
where claude >nul 2>nul
if errorlevel 1 (
  echo Instalando Claude Code...
  powershell -NoProfile -ExecutionPolicy Bypass -Command "irm https://claude.ai/install.ps1 | iex"
)
echo.
echo Ahora se abrira Claude Code: inicia sesion con tu cuenta de Claude (la del plan Pro).
echo Cuando veas el mensaje de bienvenida, escribe /exit y cierra esta ventana.
echo.
pause
set "PATH=%PATH%;%USERPROFILE%\.local\bin"
claude
