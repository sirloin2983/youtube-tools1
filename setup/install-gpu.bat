@echo off
setlocal
cd /d "%~dp0"

rem Python 3.10 first (versions in requirements*.txt are tested there), then any Python 3.
py -3.10 --version >nul 2>&1
if %errorlevel%==0 goto usepy310
py -3 --version >nul 2>&1
if %errorlevel%==0 goto usepy
python --version >nul 2>&1
if %errorlevel%==0 goto usepython
goto nopython

:usepy310
py -3.10 -m pip install -U nvidia-cublas-cu12 "nvidia-cudnn-cu12==9.*"
goto finish

:usepy
py -3 -m pip install -U nvidia-cublas-cu12 "nvidia-cudnn-cu12==9.*"
goto finish

:usepython
python -m pip install -U nvidia-cublas-cu12 "nvidia-cudnn-cu12==9.*"
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
  echo Done. Close this window, then restart the tools with start.bat in the parent folder (youtube-tools).
)
pause
