# HANDOVER — 次のセッションへの引き継ぎ(2026-09-26)

セッションを切り替えるたびに上書きする。詳しい経緯は `docs/WORKLOG.md`、ルールは `AGENTS.md`。

## 今の状態
- GitHub の main = dac1b89(2026-09-26 0:57)。PC(Desktop\youtube-test)と一致。この後の未コミットは WORKLOG の最後の記録を参照
- 版: 入口 0.4.0・切り抜きスタジオ 0.3.0・文字起こし 0.11.0・cut2resolve 0.5.0・ytt_core 1.1.0
- 統合計画: 段階3(3ツールを入口に取り込む)完了。3-3(文字起こし・認識ワーカー tx_worker.py)は Windows 実機で確認済み
- 資料の正本はリポジトリ(09-26 決定)。claude.ai の Project には `claude/README.md`(案内)と `claude/integration-plan.md`(要約)だけ
- push.bat は ASCII だけの版(日本語の表示で cmd が行を読み違えるため)。取り込みの失敗を「接続できない」「衝突」「push の失敗」に分けて表示し、送れずに残ったコミットも次の実行で送る

## 次の作業(上から順に)
1. **Resolve パックの二重実装の一本化**(`transcribe-tool/resolve_export.py` と `cut2resolve/pack.py`)。
   AGENTS.md の【高】リスク: **先に契約テスト**(同じ transcript/v1・cut-plan/v1 から同じパックの中身ができること)を書いて緑にし、それを保ったまま `pack.py` に寄せる。
   一緒に cut2resolve の `.runtime`・siblings を ytt_core に切り替える(`docs/integration-plan.md` の「段階3-2で決めたこと」)
2. 段階4: 作業データをリポジトリの外へ(場所は未決。例 `%LOCALAPPDATA%\youtube-tools`)。コピーのみ・元は残す・削除はユーザー確認後。
   `.whisper_models`(約484MB)・`0old`(約2GB。API キーを含む)もリポジトリの外へ移すのが安全
3. 統合計画の正本(Claude Docs)と写しの 3-3 の状態を「実機確認済み」に更新

## 注意
- Cowork(クラウド)は PC で git・移動・削除ができない。書き込んだら読み直して一致を確かめる。push はユーザーの push.bat
- GPT(Codex)がこのフォルダで作業すると `.git\refs\codex\` に壊れた参照が残ることがある → push.bat が `bad object refs/codex/…` で止まったら `rmdir /s /q .git\refs\codex`
- PC に Python が2つある可能性(`__pycache__` に 3.10 と 3.12)。faster-whisper は入口と同じ Python で動いた(3-3 の実機確認)
- 起動中の入口・ツールは古いコードのまま。コードを直したら「すべて終了」→ start-all.bat
- `cut2resolve/exports/` の中の音割れの診断用フォルダは、消すようお願い済み(git の対象外。消したかは未確認)
