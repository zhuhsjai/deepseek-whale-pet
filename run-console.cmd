@echo off
cd /d "%~dp0"
where python >nul 2>nul
if %errorlevel%==0 (
  python "%~dp0desk_pet.py"
) else (
  py -3 "%~dp0desk_pet.py"
)
pause
