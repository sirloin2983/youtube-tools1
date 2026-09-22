@echo off
setlocal
cd /d "%~dp0"

py -3 --version >nul 2>&1
if %errorlevel%==0 goto usepy
python --version >nul 2>&1
if %errorlevel%==0 goto usepython
goto nopython

:usepy
py -3 serve.py
goto finish

:usepython
python serve.py
goto finish

:nopython
echo.
echo Python 3 was not found.
echo Install it from https://www.python.org/downloads/
echo (check "Add python.exe to PATH" in the installer), then run this file again.
echo.
pause
goto :eof

:finish
if errorlevel 1 (
  echo.
  echo The server stopped with an error. See the message above.
  pause
)
