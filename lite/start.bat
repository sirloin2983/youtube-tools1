@echo off
rem Friend-facing simplified transcription (docs\plan\friend-lite-plan.md). Double-click to start.
rem This file only prepares uv and Python 3.10, then hands over to lite\lite_start.py (update, packages, launch).
rem Keep it ASCII only and keep the python line ending with "& exit /b": the updater may rewrite this file while it runs.
setlocal
cd /d "%~dp0.."
title youtube-tools lite
if exist "%USERPROFILE%\.local\bin\uv.exe" set "PATH=%USERPROFILE%\.local\bin;%PATH%"
where uv >nul 2>&1
if %errorlevel%==0 goto haveuv
echo.
echo "uv" (the tool that prepares Python) is not installed yet.
echo It will be downloaded from the official site https://astral.sh/uv .
choice /c YN /m "Install uv now"
if errorlevel 2 goto nouv
powershell -NoProfile -ExecutionPolicy Bypass -Command "irm https://astral.sh/uv/install.ps1 | iex"
set "PATH=%USERPROFILE%\.local\bin;%PATH%"
where uv >nul 2>&1
if not %errorlevel%==0 goto nouv
:haveuv
if exist "lite\.venv\Scripts\python.exe" goto run
echo Preparing Python 3.10 (first time only)...
uv venv lite\.venv --python 3.10
if not %errorlevel%==0 goto failed
:run
"lite\.venv\Scripts\python.exe" lite\lite_start.py %* & exit /b
:nouv
echo.
echo Could not install uv. Install it from https://docs.astral.sh/uv/ and run this file again.
pause
exit /b 1
:failed
echo.
echo Could not prepare Python. Check the internet connection and run this file again.
pause
exit /b 1
