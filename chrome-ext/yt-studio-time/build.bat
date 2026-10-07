@echo off
rem Run the node tests and make dist\YtStudioTime.zip (the Chrome extension) to send to a friend. Details: README.txt
rem The zip has one folder yt-studio-time with manifest.json, main.js and README.txt (no tests, no build.bat).
rem node: the one on PATH, or the node.exe that ships with Playwright (python 3.10). The e2e (tests\e2e_fake_studio.py) is not run here.
setlocal
cd /d "%~dp0"

echo [1/3] tests
set "NODE=node"
where node >nul 2>nul
if errorlevel 1 (
  for /f "usebackq delims=" %%p in (`py -3.10 -c "import playwright,os;print(os.path.join(os.path.dirname(playwright.__file__),'driver','node.exe'))"`) do set "NODE=%%p"
)
if not exist "%NODE%" (
  if /i not "%NODE%"=="node" (
    echo node was not found: %NODE%
    goto fail
  )
)
"%NODE%" --test tests\test_main.cjs
if errorlevel 1 goto fail

echo [2/3] dist\yt-studio-time
if exist dist\yt-studio-time rmdir /s /q dist\yt-studio-time
if exist dist\yt-studio-time (
  echo dist\yt-studio-time could not be removed. Close what holds it, then run this again.
  goto fail
)
mkdir dist\yt-studio-time
copy /y manifest.json dist\yt-studio-time\ >nul || goto fail
copy /y main.js dist\yt-studio-time\ >nul || goto fail
copy /y README.txt dist\yt-studio-time\ >nul || goto fail

echo [3/3] dist\YtStudioTime.zip
if exist dist\YtStudioTime.zip del /q dist\YtStudioTime.zip
powershell -NoProfile -ExecutionPolicy Bypass -Command "$ErrorActionPreference='Stop'; Compress-Archive -Path 'dist\yt-studio-time' -DestinationPath 'dist\YtStudioTime.zip' -Force; Add-Type -AssemblyName System.IO.Compression.FileSystem; $z = [IO.Compression.ZipFile]::OpenRead((Resolve-Path 'dist\YtStudioTime.zip').Path); $n = $z.Entries.Count; $z.Dispose(); if ($n -ne 3) { Write-Host ('The zip has ' + $n + ' files, expected 3'); exit 1 }"
if errorlevel 1 goto fail

echo.
echo Done. Send dist\YtStudioTime.zip to your friend. How to install is in README.txt (inside the zip too).
if not "%1"=="--no-pause" pause
exit /b 0

:fail
echo.
echo Build failed.
if not "%1"=="--no-pause" pause
exit /b 1
