@echo off
setlocal
cd /d "%~dp0"
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
py -3 serve.py
goto finish
:usepython
python serve.py
:finish
echo.
echo ----------------------------------------------------------
echo  Server stopped (exit code %errorlevel%). Log: work\serve.log in this folder.
echo ----------------------------------------------------------
pause
