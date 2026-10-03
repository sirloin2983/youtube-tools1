@echo off
setlocal
cd /d "%~dp0"

rem One-shot setup after reinstalling Windows. ASCII only (no Japanese in .bat files).
rem Installs with winget (skips what is already installed): Python 3.10, ffmpeg, yt-dlp, Deno.
rem Then runs install.bat (Python packages). Dev tools (Playwright) are optional.
rem Visual Studio Build Tools and Vulkan SDK need a license agreement, so they are NOT installed here.

echo ============================================================
echo  youtube-tools bootstrap
echo ============================================================
echo.
echo This will install with winget (only what is missing):
echo   Python 3.10, ffmpeg, yt-dlp, Deno
echo and then run setup\install.bat for the Python packages.
echo.
echo NOTE: by running this file you ACCEPT the winget package and
echo source agreements on your own behalf
echo (--accept-package-agreements --accept-source-agreements).
echo If you do not agree, close this window now.
echo.
pause

where winget >nul 2>&1
if errorlevel 1 (
  echo.
  echo [FAILED] winget was not found. Install "App Installer" from the Microsoft Store, then run this file again.
  goto fail
)

echo.
echo [1/5] Python 3.10
py -3.10 --version >nul 2>&1
if not errorlevel 1 (
  echo   already installed: skip
) else (
  call :wingetinstall Python.Python.3.10
  if errorlevel 1 goto fail
)

echo.
echo [2/5] ffmpeg
call :wingetinstall Gyan.FFmpeg
if errorlevel 1 goto fail

echo.
echo [3/5] yt-dlp
call :wingetinstall yt-dlp.yt-dlp
if errorlevel 1 goto fail

echo.
echo [4/5] Deno
call :wingetinstall DenoLand.Deno
if errorlevel 1 goto fail

echo.
echo NOTE: commands installed just now (py, ffmpeg, yt-dlp, deno) are found only in a NEW
echo command prompt (PATH is read when a prompt starts). If the next step cannot find
echo py -3.10, close this window, open a new command prompt and run setup\bootstrap.bat again.

echo.
echo [5/5] Python packages (setup\install.bat)
py -3.10 --version >nul 2>&1
if errorlevel 1 (
  echo.
  echo [FAILED] py -3.10 is not available in this window yet. Open a NEW command prompt and run setup\bootstrap.bat again.
  goto fail
)
rem install.bat cannot report failure through its exit code, so run it in a child cmd and check the result below.
cmd /c ""%~dp0install.bat""
py -3.10 -c "import faster_whisper" >nul 2>&1
if errorlevel 1 (
  echo.
  echo [FAILED] Python packages: faster_whisper could not be imported after install.bat. See the messages above.
  goto fail
)
echo   Python packages OK

echo.
set "DEVANS="
set /p DEVANS=Install dev tools for tests (Playwright + chromium)? Not needed to use the tools. [y/N]: 
if /i not "%DEVANS%"=="y" goto afterdev
echo.
py -3.10 -m pip install -r "%~dp0requirements-dev.txt"
if errorlevel 1 (
  echo.
  echo [FAILED] pip install of requirements-dev.txt
  goto fail
)
py -3.10 -m playwright install chromium
if errorlevel 1 (
  echo.
  echo [FAILED] playwright install chromium
  goto fail
)
:afterdev

echo.
echo ============================================================
echo  Done. Next (manual) steps
echo ============================================================
echo  - Optional, for GPU transcription (whisper.cpp Vulkan). These need a license
echo    agreement, so install them yourself:
echo      Visual Studio Build Tools 2022 (C++ workload):
echo        https://visualstudio.microsoft.com/downloads/  (Tools for Visual Studio)
echo      Vulkan SDK:
echo        https://vulkan.lunarg.com/sdk/home  (or: winget install --id KhronosGroup.VulkanSDK -e)
echo    Then run setup\build-whisper-vulkan.bat
echo  - To restore your work data from the backup, see "docs\spec\data-location.md"
echo    (section on copying back; close the app first).
echo  - Start the tools with start.bat in the parent folder.
echo.
pause
goto :eof

:wingetinstall
rem %1 = winget package id. Skips when already installed.
winget list --id %1 -e --accept-source-agreements >nul 2>&1
if not errorlevel 1 (
  echo   already installed: %1 - skip
  exit /b 0
)
echo   installing %1 ...
winget install --id %1 -e --accept-package-agreements --accept-source-agreements
if errorlevel 1 (
  echo.
  echo [FAILED] winget install %1
  exit /b 1
)
exit /b 0

:fail
echo.
echo Stopped because of the failure above. Fix it and run setup\bootstrap.bat again
echo (steps that are already done are skipped).
echo.
pause
exit /b 1
