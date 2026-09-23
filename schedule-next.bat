@echo off
rem ダブルクリックで「次の朝4時に auto-next.bat を1回だけ実行する」予約をタスクスケジューラに登録する(スリープ中なら起こして実行)
chcp 65001 >nul
cd /d "%~dp0"
where claude >nul 2>nul || (echo Claude Code が見つかりません。先にインストールして、一度 claude を起動してログインしてください & pause & exit /b 1)
powershell -NoProfile -ExecutionPolicy Bypass -Command "$d=(Get-Date).Date.AddHours(4); if((Get-Date) -gt $d){$d=$d.AddDays(1)}; $a=New-ScheduledTaskAction -Execute '%~dp0auto-next.bat' -WorkingDirectory '%~dp0'; $t=New-ScheduledTaskTrigger -Once -At $d; $s=New-ScheduledTaskSettingsSet -WakeToRun -StartWhenAvailable -ExecutionTimeLimit (New-TimeSpan -Hours 4); Register-ScheduledTask -TaskName 'youtube-tools-auto-next' -Action $a -Trigger $t -Settings $s -Force | Out-Null; Write-Host ('予約しました: ' + $d.ToString('M/d HH:mm'))"
echo 取り消すときは、タスクスケジューラで youtube-tools-auto-next を削除してください。結果は auto-next.log に残ります。
pause
