@echo off
setlocal
cd /d "%~dp0"

rem Build whisper.cpp for the GPU (Vulkan, e.g. AMD Radeon) from the official source at a fixed commit.
rem Needs: Git, Visual Studio 2022 (C++), Vulkan SDK (winget install --id KhronosGroup.VulkanSDK -e).
py -3.10 --version >nul 2>&1
if %errorlevel%==0 (py -3.10 build_whisper_vulkan.py %* & goto finish)
py -3 --version >nul 2>&1
if %errorlevel%==0 (py -3 build_whisper_vulkan.py %* & goto finish)
python build_whisper_vulkan.py %*

:finish
echo.
pause
