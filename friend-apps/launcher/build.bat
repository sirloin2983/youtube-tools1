@echo off
rem Build FriendInbox.exe (the launcher of the friend's inbox) with the C# compiler that ships with Windows (.NET Framework 4.x), then run the tests.
rem build\FriendInbox.exe goes into the friend zip (dev\build_friend_zip.py) next to RequestSender.exe. It is not committed.
rem Usage: build.bat [--no-pause]
setlocal
cd /d "%~dp0"
set "NOPAUSE="
for %%A in (%*) do (
  if /i "%%~A"=="--no-pause" set "NOPAUSE=1"
)
set "CSC=%WINDIR%\Microsoft.NET\Framework64\v4.0.30319\csc.exe"
if not exist "%CSC%" set "CSC=%WINDIR%\Microsoft.NET\Framework\v4.0.30319\csc.exe"
if not exist "%CSC%" (
  echo The C# compiler of .NET Framework 4 was not found: %CSC%
  goto fail
)
if not exist build mkdir build
set "REFS=/r:System.dll /r:System.Core.dll /r:System.Drawing.dll /r:System.Windows.Forms.dll /r:System.Web.Extensions.dll"

echo [1/2] FriendInbox.exe
"%CSC%" /nologo /codepage:65001 /target:winexe /optimize+ /warn:4 /out:build\FriendInbox.exe /win32manifest:src\app.manifest %REFS% src\*.cs ..\common\Json.cs ..\common\Log.cs
if errorlevel 1 goto fail

echo [2/2] tests
"%CSC%" /nologo /codepage:65001 /target:exe /out:build\FriendInboxTests.exe %REFS% /r:build\FriendInbox.exe tests\*.cs
if errorlevel 1 goto fail
build\FriendInboxTests.exe
if errorlevel 1 goto fail

echo.
echo Done. build\FriendInbox.exe
if not defined NOPAUSE pause
exit /b 0

:fail
echo.
echo Build failed.
if not defined NOPAUSE pause
exit /b 1
