@echo off
rem Double-click to start all three tools (clip-studio, transcribe-tool, cut2resolve) and open the portal page.
rem Details: app\README.txt
setlocal
cd /d "%~dp0"
title youtube-tools
py -3 --version >nul 2>&1
if %errorlevel%==0 goto usepy
python --version >nul 2>&1
if %errorlevel%==0 goto usepython
echo.
echo Python 3 was not found.
echo Install it from https://www.python.org/downloads/  (check "Add python.exe to PATH"), then run this file again.
echo.
pause
goto :eof
:usepy
py -3 app\launch.py %*
goto finish
:usepython
python app\launch.py %*
:finish
if errorlevel 1 (
  echo.
  echo The launcher stopped with an error. See the messages above and app\logs\launcher.log.
  pause
)
