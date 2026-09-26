@echo off
rem Double-click: move the OLD copies of the work data (inside each tool folder) to the Recycle Bin,
rem after checking that they were copied to %LOCALAPPDATA%\youtube-tools. Shows the list and asks first.
rem Details: docs\data-location.md
setlocal
cd /d "%~dp0.."
chcp 65001 >nul
set PYTHONIOENCODING=utf-8
py -3 --version >nul 2>&1
if %errorlevel%==0 goto usepy
python --version >nul 2>&1
if %errorlevel%==0 goto usepython
echo Python 3 was not found.
pause
goto :eof
:usepy
py -3 tools\cleanup_legacy_data.py %*
goto finish
:usepython
python tools\cleanup_legacy_data.py %*
:finish
echo.
pause
