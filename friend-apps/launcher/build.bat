@echo off
rem Build FriendApp.exe (the friend's app: a window with WebView2 that starts the Python part as a child) with the C# compiler of .NET Framework 4.x, then run the tests.
rem The WebView2 DLLs come from the official NuGet package (dev\fetch_webview2.py, pinned version and SHA-256) into lib\ (not committed).
rem build\FriendApp.exe and the 3 DLLs go into the friend zip (dev\build_friend_zip.py). They are not committed.
rem Usage: build.bat [--no-pause]
setlocal
cd /d "%~dp0"
set "NOPAUSE="
for %%A in (%*) do (
  if /i "%%~A"=="--no-pause" set "NOPAUSE=1"
)
set "CSC=%WINDIR%\Microsoft.NET\Framework64\v4.0.30319\csc.exe"
if not exist "%CSC%" (
  echo The 64-bit C# compiler of .NET Framework 4 was not found: %CSC%
  goto fail
)

echo [1/3] WebView2 DLLs
py -3.10 ..\..\dev\fetch_webview2.py --out lib
if errorlevel 1 goto fail

if not exist build mkdir build
set "REFS=/r:System.dll /r:System.Core.dll /r:System.Drawing.dll /r:System.Windows.Forms.dll /r:System.Web.Extensions.dll /r:lib\Microsoft.Web.WebView2.Core.dll /r:lib\Microsoft.Web.WebView2.WinForms.dll"

echo [2/3] FriendApp.exe
"%CSC%" /nologo /codepage:65001 /target:winexe /platform:x64 /optimize+ /warn:4 /out:build\FriendApp.exe /win32manifest:src\app.manifest %REFS% src\*.cs ..\common\Json.cs ..\common\Log.cs
if errorlevel 1 goto fail
copy /y lib\*.dll build\ >nul
if errorlevel 1 goto fail

echo [3/3] tests
"%CSC%" /nologo /codepage:65001 /target:exe /platform:x64 /out:build\FriendAppTests.exe %REFS% /r:build\FriendApp.exe tests\*.cs
if errorlevel 1 goto fail
build\FriendAppTests.exe
if errorlevel 1 goto fail

echo.
echo Done. build\FriendApp.exe
if not defined NOPAUSE pause
exit /b 0

:fail
echo.
echo Build failed.
if not defined NOPAUSE pause
exit /b 1
