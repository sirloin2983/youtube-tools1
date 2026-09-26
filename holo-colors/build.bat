@echo off
rem Build HoloColors.exe with the C# compiler that ships with Windows (.NET Framework 4.x), run the tests,
rem and make dist\HoloColors.zip to send. Details: README.txt
setlocal
cd /d "%~dp0"
set "CSC=%WINDIR%\Microsoft.NET\Framework64\v4.0.30319\csc.exe"
if not exist "%CSC%" set "CSC=%WINDIR%\Microsoft.NET\Framework\v4.0.30319\csc.exe"
if not exist "%CSC%" (
  echo The C# compiler of .NET Framework 4 was not found: %CSC%
  goto fail
)
if not exist build mkdir build

rem A running copy locks the exe: ask it to quit first (it uses the normal data folder), and wait until it is gone.
tasklist /FI "IMAGENAME eq HoloColors.exe" 2>nul | find /I "HoloColors.exe" >nul
if errorlevel 1 goto quit_done
echo HoloColors is running. Quitting it to replace the exe - start it again after the build.
set "QUITTER=build\HoloColors.exe"
if not exist "%QUITTER%" set "QUITTER=dist\HoloColors\HoloColors.exe"
if exist "%QUITTER%" "%QUITTER%" --quit
set /a WAITS=0
:wait_quit
tasklist /FI "IMAGENAME eq HoloColors.exe" 2>nul | find /I "HoloColors.exe" >nul
if errorlevel 1 goto quit_done
set /a WAITS+=1
if %WAITS% geq 10 goto quit_done
ping -n 2 127.0.0.1 >nul
goto wait_quit
:quit_done

set "REFS=/r:System.dll /r:System.Core.dll /r:System.Drawing.dll /r:System.Windows.Forms.dll /r:System.Web.Extensions.dll"
echo [1/4] HoloColors.exe
"%CSC%" /nologo /codepage:65001 /target:winexe /optimize+ /warn:4 /out:build\HoloColors.exe /win32icon:src\app.ico /win32manifest:src\app.manifest /resource:src\app.ico,HoloColors.app.ico %REFS% src\*.cs
if errorlevel 1 goto fail
copy /y members.json build\members.json >nul

echo [2/4] tests
"%CSC%" /nologo /codepage:65001 /target:exe /out:build\HoloColorsTests.exe %REFS% /r:build\HoloColors.exe tests\*.cs
if errorlevel 1 goto fail
build\HoloColorsTests.exe
if errorlevel 1 goto fail

echo [3/4] dist\HoloColors
if exist dist\HoloColors rmdir /s /q dist\HoloColors
if exist dist\HoloColors (
  echo dist\HoloColors could not be removed. Quit HoloColors started from that folder, then run this again.
  goto fail
)
mkdir dist\HoloColors
copy /y build\HoloColors.exe dist\HoloColors\ >nul || goto fail
copy /y members.json dist\HoloColors\ >nul || goto fail
copy /y README.txt dist\HoloColors\ >nul || goto fail

rem Antivirus software may hold the new exe for a moment: retry, then check that the zip really has all 3 files.
echo [4/4] dist\HoloColors.zip
if exist dist\HoloColors.zip del /q dist\HoloColors.zip
powershell -NoProfile -ExecutionPolicy Bypass -Command "$ErrorActionPreference='Stop'; for ($i = 1; ; $i++) { try { Compress-Archive -Path 'dist\HoloColors' -DestinationPath 'dist\HoloColors.zip' -Force; break } catch { if ($i -ge 5) { Write-Host $_; exit 1 }; Start-Sleep -Seconds 1 } }; Add-Type -AssemblyName System.IO.Compression.FileSystem; $z = [IO.Compression.ZipFile]::OpenRead((Resolve-Path 'dist\HoloColors.zip').Path); $n = $z.Entries.Count; $z.Dispose(); if ($n -ne 3) { Write-Host ('The zip has ' + $n + ' files, expected 3'); exit 1 }"
if errorlevel 1 goto fail

echo.
echo Done. Send dist\HoloColors.zip to your friend.
if not "%1"=="--no-pause" pause
exit /b 0

:fail
echo.
echo Build failed.
if not "%1"=="--no-pause" pause
exit /b 1
