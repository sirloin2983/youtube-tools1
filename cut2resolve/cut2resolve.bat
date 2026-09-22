@echo off
rem Drag and drop a video (and optionally a cut list .txt / subtitle .srt) onto this bat.
rem Auto silence cut + rough-cut video are ON here. Use cut2resolve.py directly for other options.
chcp 65001 >nul
where py >nul 2>nul
if %errorlevel%==0 (
  py -3 "%~dp0cut2resolve.py" %* --silence --render
) else (
  python "%~dp0cut2resolve.py" %* --silence --render
)
echo.
pause
