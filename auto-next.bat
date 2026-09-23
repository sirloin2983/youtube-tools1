@echo off
rem 無人で Claude Code に docs/NEXT_TASKS.md の続きをさせる(schedule-next.bat がタスクスケジューラから呼ぶ)
chcp 65001 >nul
cd /d "%~dp0"
set LOG=auto-next.log
echo ===== %date% %time% 開始 ===== >> %LOG%
where claude >nul 2>nul || (echo Claude Code が見つかりません >> %LOG% & exit /b 1)
rem 実行前の状態を控えとしてコミット(何かあってもここへ戻せる)
git add -A >> %LOG% 2>&1
git commit -q -m "自動実行前の控え %date% %time:~0,5%" >> %LOG% 2>&1
claude -p "docs/NEXT_TASKS.md を読み、AGENTS.md のルールと docs/WORKLOG.md の最後の数件を確認してから、状態が「未」のタスクを上から順に進めてください。各タスクが終わるたびに NEXT_TASKS.md の状態を「済」にし、WORKLOG に記録してコミットしてください。push はしないでください。これは無人の自動実行です。質問できないので、設計の判断が必要な所・依存の追加が必要な所では実装を止め、判断が必要な点を WORKLOG と NEXT_TASKS.md に書いて終了してください。応答は日本語で。" --permission-mode acceptEdits --max-turns 300 --allowedTools "Read,Edit,Write,Glob,Grep,Bash(python:*),Bash(py:*),Bash(node:*),Bash(git status:*),Bash(git diff:*),Bash(git log:*),Bash(git add:*),Bash(git commit:*)" >> %LOG% 2>&1
echo ===== %date% %time% 終了(終了コード %errorlevel%) ===== >> %LOG%
