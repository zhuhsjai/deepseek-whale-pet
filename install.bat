@echo off
cd /d "%~dp0"
where py >nul 2>nul
if %errorlevel%==0 (
  py -3 -m pip install -r requirements.txt
) else (
  python -m pip install -r requirements.txt
)
echo.
echo 依赖安装完成，双击 start-pet.cmd 启动桌宠。
pause
