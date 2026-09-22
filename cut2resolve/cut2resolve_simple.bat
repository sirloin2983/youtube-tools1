@echo off
rem Drag and drop a video, a cut list (.txt) and a subtitle file (.srt) onto this bat together.
chcp 65001 >nul
where py >nul 2>nul
if %errorlevel%==0 (
  py -3 "%~dp0cut2resolve_simple.py" %*
) else (
  python "%~dp0cut2resolve_simple.py" %*
)
echo.
pause
