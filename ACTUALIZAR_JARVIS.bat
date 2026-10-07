@echo off
chcp 65001 >nul
title Actualizando J.A.R.V.I.S.
echo.
echo   === Actualizando J.A.R.V.I.S. ===
echo.
set "ORIGEN=%~dp0jarvis"
if not exist "%ORIGEN%\main.py" (echo [!] Extrae el zip completo y ejecuta este archivo desde la carpeta extraida. & pause & exit /b 1)

rem 1) Buscar donde esta instalado JARVIS (por el acceso directo del escritorio o carpetas habituales)
set "DESTINO="
for /f "usebackq delims=" %%D in (`powershell -NoProfile -Command "$l=[Environment]::GetFolderPath('Desktop')+'\JARVIS.lnk'; if(Test-Path $l){$s=(New-Object -ComObject WScript.Shell).CreateShortcut($l); if($s.WorkingDirectory){$s.WorkingDirectory}else{Split-Path $s.TargetPath}}"`) do set "DESTINO=%%D"
if defined DESTINO if "%DESTINO:~-1%"=="\" set "DESTINO=%DESTINO:~0,-1%"
if defined DESTINO if not exist "%DESTINO%\main.py" if exist "%DESTINO%\..\..\main.py" for %%P in ("%DESTINO%\..\..") do set "DESTINO=%%~fP"
if defined DESTINO if not exist "%DESTINO%\main.py" set "DESTINO="
for %%C in ("%USERPROFILE%\Documents\jarvis" "%USERPROFILE%\Documents\jarvis\jarvis" "%USERPROFILE%\OneDrive\Documents\jarvis" "%USERPROFILE%\OneDrive\Documentos\jarvis" "%USERPROFILE%\Downloads\jarvis" "%USERPROFILE%\Downloads\jarvis\jarvis" "C:\jarvis") do (
  if not defined DESTINO if exist "%%~C\.venv\Scripts\python.exe" set "DESTINO=%%~C"
)
if not defined DESTINO (
  echo [!] No encontre una instalacion de JARVIS. Haremos una instalacion nueva en Documentos\jarvis.
  set "DESTINO=%USERPROFILE%\Documents\jarvis"
)
echo JARVIS esta en: %DESTINO%
echo.

rem 2) Cerrar JARVIS si esta abierto
taskkill /f /im pythonw.exe >nul 2>nul

rem 3) Copiar todo (incluye tu config.json) sin tocar el entorno ni tus datos
robocopy "%ORIGEN%" "%DESTINO%" /E /XD .venv datos /NFL /NDL /NJH /NJS /NP >nul
echo [OK] Archivos actualizados (incluida tu configuracion).

rem 4) Instalar lo que falte
if not exist "%DESTINO%\.venv\Scripts\python.exe" (
  echo Primera instalacion: esto tarda unos minutos...
  pushd "%DESTINO%"
  call instalar.bat
  popd
) else (
  echo Instalando componentes nuevos...
  "%DESTINO%\.venv\Scripts\python.exe" -m pip install -q --prefer-binary -r "%DESTINO%\requirements.txt"
)
pushd "%DESTINO%"
call crear_acceso_directo.bat >nul
popd

rem 5) Abrir JARVIS
start "" /D "%DESTINO%" "%DESTINO%\.venv\Scripts\pythonw.exe" main.py
echo.
echo   Listo. JARVIS se esta abriendo con la version nueva.
echo.
timeout /t 8
