@echo off
chcp 65001 >nul
cd /d "%~dp0"
powershell -NoProfile -Command "$w=New-Object -ComObject WScript.Shell; $s=$w.CreateShortcut([Environment]::GetFolderPath('Startup')+'\JARVIS.lnk'); $s.TargetPath='%~dp0.venv\Scripts\pythonw.exe'; $s.Arguments='main.py'; $s.WorkingDirectory='%~dp0'; $s.IconLocation='%~dp0ui\jarvis.ico'; $s.Save()"
echo JARVIS se iniciara automaticamente al encender Windows.
pause
