@echo off
rem Build RequestSender.exe with the C# compiler that ships with Windows (.NET Framework 4.x), run the tests,
rem and make dist\RequestSender.zip to send to the friend. Details: README.txt
rem config.json (the Dropbox key) goes into the zip only when it exists here. It is never compiled into the exe.
setlocal
cd /d "%~dp0"
set "CSC=%WINDIR%\Microsoft.NET\Framework64\v4.0.30319\csc.exe"
if not exist "%CSC%" set "CSC=%WINDIR%\Microsoft.NET\Framework\v4.0.30319\csc.exe"
if not exist "%CSC%" (
  echo The C# compiler of .NET Framework 4 was not found: %CSC%
  goto fail
)
if not exist build mkdir build

for %%I in ("%CSC%") do set "FW=%%~dpI"
rem In-app player of the preview video (2.7.0): WPF MediaElement in an ElementHost. These ship with .NET Framework 4 (no install).
set "WPF=/lib:%FW%WPF /r:PresentationCore.dll /r:PresentationFramework.dll /r:WindowsBase.dll /r:WindowsFormsIntegration.dll /r:System.Xaml.dll"
set "REFS=/r:System.dll /r:System.Core.dll /r:System.Drawing.dll /r:System.Windows.Forms.dll /r:System.Web.Extensions.dll /r:System.IO.Compression.dll /r:System.IO.Compression.FileSystem.dll %WPF%"
echo [1/4] RequestSender.exe
"%CSC%" /nologo /codepage:65001 /target:winexe /optimize+ /warn:4 /out:build\RequestSender.exe /win32manifest:src\app.manifest %REFS% src\*.cs ..\common\*.cs
if errorlevel 1 goto fail
copy /y ..\holo-colors\members.json build\members.json >nul || goto fail

echo [2/4] tests
"%CSC%" /nologo /codepage:65001 /target:exe /out:build\RequestSenderTests.exe %REFS% /r:build\RequestSender.exe tests\*.cs
if errorlevel 1 goto fail
build\RequestSenderTests.exe
if errorlevel 1 goto fail

echo [3/4] dist\RequestSender
rem Delete the exe first: if it is still running, del fails and we stop before rmdir removes the other files (README, members.json, config.json).
if exist dist\RequestSender\RequestSender.exe del /q dist\RequestSender\RequestSender.exe
if exist dist\RequestSender\RequestSender.exe (
  echo dist\RequestSender\RequestSender.exe is in use. Quit RequestSender started from that folder, then run this again. Nothing was removed.
  goto fail
)
if exist dist\RequestSender rmdir /s /q dist\RequestSender
if exist dist\RequestSender (
  echo dist\RequestSender could not be removed. Quit RequestSender started from that folder, then run this again.
  goto fail
)
mkdir dist\RequestSender
copy /y build\RequestSender.exe dist\RequestSender\ >nul || goto fail
copy /y ..\holo-colors\members.json dist\RequestSender\ >nul || goto fail
copy /y README.txt dist\RequestSender\ >nul || goto fail
set EXPECT=3
if exist config.json (
  copy /y config.json dist\RequestSender\ >nul || goto fail
  set EXPECT=4
) else (
  echo NOTE: config.json is not here, so the zip has no key. Make it first: python dev\dropbox_auth.py ^<app key^> - run it in the repository top folder
)

rem Antivirus software may hold the new exe for a moment: retry, then check that the zip really has all the files.
echo [4/4] dist\RequestSender.zip
if exist dist\RequestSender.zip del /q dist\RequestSender.zip
powershell -NoProfile -ExecutionPolicy Bypass -Command "$ErrorActionPreference='Stop'; for ($i = 1; ; $i++) { try { Compress-Archive -Path 'dist\RequestSender' -DestinationPath 'dist\RequestSender.zip' -Force; break } catch { if ($i -ge 5) { Write-Host $_; exit 1 }; Start-Sleep -Seconds 1 } }; Add-Type -AssemblyName System.IO.Compression.FileSystem; $z = [IO.Compression.ZipFile]::OpenRead((Resolve-Path 'dist\RequestSender.zip').Path); $n = $z.Entries.Count; $z.Dispose(); if ($n -ne %EXPECT%) { Write-Host ('The zip has ' + $n + ' files, expected %EXPECT%'); exit 1 }"
if errorlevel 1 goto fail

echo.
if "%EXPECT%"=="4" (
  echo Done. Send dist\RequestSender.zip to your friend. It contains the key: send it privately.
) else (
  echo Done, but without config.json the friend cannot send anything yet.
)
if not "%1"=="--no-pause" pause
exit /b 0

:fail
echo.
echo Build failed.
if not "%1"=="--no-pause" pause
exit /b 1
