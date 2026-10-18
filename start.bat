@echo off
rem Double-click to start all three tools (studio, editor, cut2resolve) and open the portal page.
rem Details: src\app\README.txt
setlocal
cd /d "%~dp0"
title youtube-tools
rem Python 3.12 when its packages are installed (setup\requirements.txt is tested there),
rem then 3.10 (the old one, kept for a while), then any Python 3.
py -3.12 -c "import faster_whisper" >nul 2>&1
if %errorlevel%==0 goto usepy312
py -3.10 --version >nul 2>&1
if %errorlevel%==0 goto usepy310
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
:usepy312
py -3.12 src\app\server.py %*
goto finish
:usepy310
py -3.10 src\app\server.py %*
goto finish
:usepy
py -3 src\app\server.py %*
goto finish
:usepython
python src\app\server.py %*
:finish
if errorlevel 1 (
  echo.
  echo The launcher stopped with an error. See the messages above and %LOCALAPPDATA%\youtube-tools\app\logs\launcher.log.
  pause
)
