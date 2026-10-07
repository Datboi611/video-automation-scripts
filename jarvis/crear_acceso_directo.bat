@echo off
chcp 65001 >nul
cd /d "%~dp0"
powershell -NoProfile -Command "$w=New-Object -ComObject WScript.Shell; $s=$w.CreateShortcut([Environment]::GetFolderPath('Desktop')+'\JARVIS.lnk'); $s.TargetPath='%~dp0.venv\Scripts\pythonw.exe'; $s.Arguments='main.py'; $s.WorkingDirectory='%~dp0'; $s.IconLocation='%~dp0ui\jarvis.ico'; $s.Description='J.A.R.V.I.S. asistente de voz'; $s.Save()"
echo Acceso directo JARVIS creado en el escritorio.
