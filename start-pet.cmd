@echo off
cd /d "%~dp0"
where pythonw >nul 2>nul
if %errorlevel%==0 (
  start "" pythonw "%~dp0desk_pet.py"
) else (
  start "" python "%~dp0desk_pet.py"
)
exit
