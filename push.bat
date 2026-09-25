@echo off
rem ダブルクリックで、このフォルダの変更を GitHub に保存する。add → 確認 → commit → 取り込み(fetch + rebase)→ push
rem 2026-09-26: 取り込みの失敗を「GitHub に接続できない」と「衝突」に分けて表示する。
rem             push できずにこの PC に残った保存(コミット)も、次に実行したときに送る。衝突したときは取り込みを取り消して元の状態に戻す
chcp 65001 >nul
cd /d "%~dp0"
where git >nul 2>nul || (echo git が見つかりません。Git for Windows を入れてください & pause & exit /b 1)
git add -A
git diff --cached --quiet
if errorlevel 1 goto ask

rem 新しい変更は無い。前回 GitHub に送れなかった保存が残っていれば送る
set "AHEAD="
for /f %%N in ('git rev-list --count "@{u}..HEAD" 2^>nul') do set "AHEAD=%%N"
if not defined AHEAD goto nothing
if "%AHEAD%"=="0" goto nothing
echo 新しい変更はありませんが、まだ GitHub に送っていない保存が %AHEAD% 件あります。送ります。
goto sync

:nothing
echo 保存する変更はありません
pause
exit /b 0

:ask
echo 次のファイルを保存します:
git status --short
echo.
echo 個人データ（文字起こし・設定・音声など）は .gitignore で除外済みです。見覚えのないファイルがあれば n で中止してください。
set "OK="
set /p OK=GitHub に保存しますか? (y/N): 
if /i not "%OK%"=="y" (git reset -q & echo 中止しました。何も変更していません & pause & exit /b 0)
git commit -q -m "更新 %date% %time:~0,5%" || (echo commit に失敗しました & pause & exit /b 1)

:sync
git fetch -q origin
if errorlevel 1 goto nonet
git rebase -q origin/main
if errorlevel 1 goto conflict
git push -q
if errorlevel 1 goto pushfail
echo 完了しました
pause
exit /b 0

:nonet
echo.
echo GitHub に接続できませんでした（ネットワーク、または GitHub のログインを確認してください）。
echo 保存（コミット）はこの PC に残っています。つながる状態で、もう一度 push.bat を実行すれば送られます。
pause
exit /b 1

:conflict
git rebase --abort >nul 2>nul
echo.
echo GitHub 側の変更と同じ所を変えていて、自動で取り込めませんでした。取り込みは取り消し、保存はこの PC に残っています。
echo Claude に相談してください。
pause
exit /b 1

:pushfail
echo.
echo push に失敗しました（ネットワーク、または GitHub のログインを確認してください）。保存はこの PC に残っています。もう一度 push.bat を実行すれば送られます。
pause
exit /b 1
