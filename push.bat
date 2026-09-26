@echo off
rem Double-click to save the changes in this folder to GitHub: add -> confirm -> commit -> fetch + rebase -> push.
rem This file is ASCII only on purpose: cmd.exe misreads long UTF-8 (Japanese) lines after "chcp 65001"
rem and runs a fragment of a line as a command (seen 2026-09-26). Keep it ASCII, like start-all.bat.
rem A commit that could not be pushed stays on this PC and is sent the next time this file is run.
setlocal
cd /d "%~dp0"
where git >nul 2>nul || (echo [ERROR] git was not found. Install Git for Windows. & pause & exit /b 1)
set "PY="
py -3 --version >nul 2>&1 && set "PY=py -3"
if not defined PY python --version >nul 2>&1 && set "PY=python"
if not defined PY (echo [ERROR] Python 3 was not found. & pause & exit /b 1)

rem 1. Delete the files listed in tools\removals.txt (git rm: only files tracked by git; they stay in the history).
%PY% tools\push_helper.py removals
if errorlevel 1 (echo [ERROR] tools\removals.txt could not be applied. Nothing was saved. Please show this message to Claude. & pause & exit /b 1)
git add -A
rem 2. Stop if personal data or secrets (API keys, data.json, transcripts, videos, logs...) are about to be committed.
%PY% tools\push_helper.py check
if errorlevel 1 (git reset -q & echo Nothing was saved. & pause & exit /b 1)
git diff --cached --quiet
if errorlevel 1 goto ask

rem Nothing new to commit. Send commits that were saved on this PC but not pushed yet.
set "AHEAD="
for /f %%N in ('git rev-list --count "@{u}..HEAD" 2^>nul') do set "AHEAD=%%N"
if not defined AHEAD goto nothing
if "%AHEAD%"=="0" goto nothing
echo No new changes, but %AHEAD% saved commit(s) have not been sent to GitHub yet. Sending them now.
goto sync

:nothing
echo Nothing to save. Everything is already on GitHub.
pause
exit /b 0

:ask
echo These files will be saved:
git status --short
echo.
echo Personal data (transcripts, settings, audio, etc.) is excluded by .gitignore and checked by tools\push_helper.py.
echo If you see a file you do not recognize, answer n.
set "OK="
set /p OK=Save to GitHub? (y/N): 
if /i not "%OK%"=="y" (git reset -q & echo Cancelled. Nothing was changed. & pause & exit /b 0)
git commit -q -m "update %date% %time:~0,5%" || (echo [ERROR] commit failed. & pause & exit /b 1)

:sync
echo.
echo Connecting to GitHub...
git fetch origin
if errorlevel 1 goto nonet
git rebase -q origin/main
if errorlevel 1 goto conflict
git push
if errorlevel 1 goto pushfail
echo.
echo Done.
pause
exit /b 0

:nonet
echo.
echo [ERROR] Could not connect to GitHub (network or GitHub sign-in).
echo Your commit is still saved on this PC. Run push.bat again when the connection works.
echo Please copy the whole message above and show it to Claude.
pause
exit /b 1

:conflict
git rebase --abort >nul 2>nul
echo.
echo [ERROR] GitHub has changes to the same lines. The merge was undone; your commit is still saved on this PC.
echo Please show this message to Claude.
pause
exit /b 1

:pushfail
echo.
echo [ERROR] push failed (network or GitHub sign-in). Your commit is still saved on this PC.
echo Please copy the whole message above and show it to Claude.
pause
exit /b 1
