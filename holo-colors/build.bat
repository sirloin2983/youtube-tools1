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

rem A running copy locks build\HoloColors.exe: ask it to quit first.
if exist build\HoloColors.exe (
  build\HoloColors.exe --quit
  ping -n 2 127.0.0.1 >nul
)

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
mkdir dist\HoloColors
copy /y build\HoloColors.exe dist\HoloColors\ >nul
copy /y members.json dist\HoloColors\ >nul
copy /y README.txt dist\HoloColors\ >nul

echo [4/4] dist\HoloColors.zip
powershell -NoProfile -ExecutionPolicy Bypass -Command "Compress-Archive -Path 'dist\HoloColors' -DestinationPath 'dist\HoloColors.zip' -Force"
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
