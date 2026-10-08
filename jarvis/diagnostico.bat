@echo off
chcp 65001 >nul
set "J=%~dp0"
if exist "%J%.venv\Scripts\python.exe" goto correr
rem No está aquí: buscar la instalación por el acceso directo del escritorio o carpetas habituales
set "J="
for /f "usebackq delims=" %%D in (`powershell -NoProfile -Command "$l=[Environment]::GetFolderPath('Desktop')+'\JARVIS.lnk'; if(Test-Path $l){(New-Object -ComObject WScript.Shell).CreateShortcut($l).WorkingDirectory}"`) do set "J=%%D"
if defined J if not "%J:~-1%"=="\" set "J=%J%\"
if defined J if exist "%J%.venv\Scripts\python.exe" goto correr
for %%C in ("%USERPROFILE%\Documents\jarvis\" "%USERPROFILE%\Documents\jarvis\jarvis\" "%USERPROFILE%\OneDrive\Documents\jarvis\" "%USERPROFILE%\Downloads\jarvis\") do (
  if exist "%%~C.venv\Scripts\python.exe" set "J=%%~C" & goto correr
)
echo [!] No encontre la instalacion de JARVIS. Dile a JARVIS: "haz un diagnostico".
pause
exit /b 1
:correr
echo Revisando JARVIS en: %J%
cd /d "%J%"
".venv\Scripts\python.exe" diagnostico.py
pause
