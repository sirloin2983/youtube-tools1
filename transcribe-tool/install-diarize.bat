@echo off
setlocal
cd /d "%~dp0"

py -3 --version >nul 2>&1
if %errorlevel%==0 goto usepy
python --version >nul 2>&1
if %errorlevel%==0 goto usepython
goto nopython

:usepy
py -3 -m pip install -U sherpa-onnx numpy
goto finish

:usepython
python -m pip install -U sherpa-onnx numpy
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
echo.
if errorlevel 1 (
  echo Install failed. See the message above.
) else (
  echo Done. Close this window, then start the tool again with start.bat.
)
pause
