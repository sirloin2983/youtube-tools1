@echo off
rem ダブルクリックで Claude Code を開き、docs/NEXT_TASKS.md の続きから作業を始める
chcp 65001 >nul
cd /d "%~dp0"
where claude >nul 2>nul || (echo Claude Code が見つかりません。インストールしてください & pause & exit /b 1)
claude "/next"
