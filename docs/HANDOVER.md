# HANDOVER — 次のセッションへの引き継ぎ(2026-09-26)

セッションを切り替えるたびに上書きする。詳しい経緯は `docs/WORKLOG.md`、ルールは `AGENTS.md`。

## 今の状態
- GitHub の main = fd6686c 以降。この後の未コミット(cut2resolve を ytt_core に・作業データをリポジトリの外へ)は WORKLOG の最後の記録を参照(push.bat で送る)
- 版: 入口 0.5.0・切り抜きスタジオ 0.4.0・文字起こし 0.13.0・cut2resolve 0.7.0・ytt_core(datadir を追加)
- 統合計画: 段階3 完了。段階4 の1つ目(作業データを `%LOCALAPPDATA%\youtube-tools\<ツールID>\` へ)は実機で移行済み(09-26 2:15。中身の一致も確認)
- 作業データの置き場所の仕組みと決まり: `docs/data-location.md`(`ytt_core/datadir.py`)
- 資料の正本はリポジトリ。統合計画だけは Claude Docs「動画編集ツール 統合計画」が正本(09-26 の状態に更新済み)
- ユーザーの指示: **作業中は 10〜20 分ごとに中間報告する**

## 次の作業(上から順に)
1. 以前の場所の片付け: `tools\cleanup_legacy_data.bat`(ユーザーが実行)。先に「すべて終了」。一覧を確かめて y → ごみ箱へ。結果を聞く
   (移行は 09-26 2:15 に完了し、中身の一致も確認済み。WORKLOG の最後の記録)
2. 段階4 の残り: 案件(配信1本)ごとの紐づけ・同時実行の上限・文字起こしをスタジオへ返す(進め方をユーザーと決める)
3. `0old`(約2GB・API キーを含む)・`.whisper_models`(約484MB・今のツールは使っていない)の扱いをユーザーに確認

## 注意
- Cowork(クラウド)は PC で git・移動・削除ができない。書き込んだら読み直して一致を確かめる。push はユーザーの push.bat
- **サーバーを動かすテストは先頭で `os.environ.setdefault("YTT_DATA_DIR", "inplace")`**(忘れると本物の作業データを読み書きする。ytt_core のテストが検査)
- 契約テスト `tools/test_resolve_pack_contract.py` は単独のコマンドで(app/test_mount.py と一緒に渡すと部品の名前が重なる)
- GPT(Codex)がこのフォルダで作業すると `.git\refs\codex\` に壊れた参照が残ることがある → push.bat が `bad object refs/codex/…` で止まったら `rmdir /s /q .git\refs\codex`
- 起動中の入口・ツールは古いコードのまま。コードを直したら「すべて終了」→ start-all.bat
- 文字起こし側に Resolve 用の計算を書き足さない(二重実装に戻さない。契約テストが検出する)
