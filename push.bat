@echo off
rem ダブルクリックで、このフォルダの変更を GitHub に保存する。add → 確認 → commit → pull → push
chcp 65001 >nul
cd /d "%~dp0"
where git >nul 2>nul || (echo git が見つかりません。Git for Windows を入れてください & pause & exit /b 1)
git add -A
git diff --cached --quiet && (echo 保存する変更はありません & pause & exit /b 0)
echo 次のファイルを保存します:
git status --short
echo.
echo 個人データ（文字起こし・設定・音声など）は .gitignore で除外済みです。見覚えのないファイルがあれば n で中止してください。
set "OK="
set /p OK=GitHub に保存しますか? (y/N): 
if /i not "%OK%"=="y" (git reset -q & echo 中止しました。何も変更していません & pause & exit /b 0)
git commit -q -m "更新 %date% %time:~0,5%" || (echo commit に失敗しました & pause & exit /b 1)
git pull --rebase -q || (echo GitHub 側の変更との取り込みで衝突しました。Claude に相談してください & pause & exit /b 1)
git push -q || (echo push に失敗しました。ネットワークか認証を確認してください & pause & exit /b 1)
echo 完了しました
pause
