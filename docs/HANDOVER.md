# HANDOVER — 次のセッションへの引き継ぎ(2026-09-26)

セッションを切り替えるたびに上書きする。詳しい経緯は `docs/WORKLOG.md`、ルールは `AGENTS.md`、ユーザー向けの使い方はリポジトリ直下の `README.txt`。

## 今の状態
- GitHub の main = 98073c1 以降。この後の未コミット(段階5・6)は WORKLOG の最後の記録を参照(push.bat で送る。同時に各ツールの start.bat・start.command が git rm される)
- 版: 入口 0.7.0・切り抜きスタジオ 0.6.0・文字起こし 0.14.1・cut2resolve 0.9.0・ytt_core(jobs・txindex)
- 統合計画: 段階1〜6 を実装済み。段階4 の置き場所の移動は実機確認済み。案件・セリフ・同時実行の上限(段階4)、まとめて実行・ラウドネス(段階5)、README の一本化・単独起動の廃止(段階6)は実機確認待ち
- 保留(ユーザー決定): 新着配信の監視、画面の形(ブラウザのまま / pywebview)、書き出し中にブラウザのタブが STATUS_ACCESS_VIOLATION で落ちた件(再現したら調べる)
- 資料の正本はリポジトリ。統合計画だけは Claude Docs「動画編集ツール 統合計画」が正本(09-26 の段階5・6 まで更新済み)
- ユーザーの指示: **作業中は 10〜20 分ごとに中間報告する**

## 次の作業(上から順に)
1. 実機確認(ユーザー): push.bat(start.bat の削除と検査が動くか)→「すべて終了」→ start-all.bat。
   案件の画面の「まとめて実行」(採用後を全部・文字起こしまで・解析から全部)、スタジオの書き出しのラウドネス(-14 LUFS で聞こえ方がそろうか)
2. 保留の項目は、ユーザーが言い出したら進める

## 注意
- Cowork(クラウド)は PC で git・移動・削除ができない。**消すファイルは tools/removals.txt に書く**(push.bat が git rm)。書き込んだら読み直して一致を確かめる。push はユーザーの push.bat
- push.bat はコミットの前に tools/push_helper.py check で個人データ・秘密情報を調べて止める。誤検出で止まったら検査(push_helper.py)を直す
- **サーバーを動かすテストは先頭で `os.environ.setdefault("YTT_DATA_DIR", "inplace")`**(忘れると本物の作業データを読み書きする。ytt_core のテストが検査)
- 重い処理は `ytt_core.jobs.SLOTS` を通す。文字起こしと切り抜きの紐づけは `ytt_core/txindex.py` だけ。他のツールのデータは読むだけ。まとめて実行はツールの API を呼ぶ(関数を直接呼ばない)
- 契約テスト `tools/test_resolve_pack_contract.py` は単独のコマンドで(app/test_mount.py と一緒に渡すと部品の名前が重なる)
- GPT(Codex)がこのフォルダで作業すると `.git\refs\codex\` に壊れた参照が残ることがある → push.bat が `bad object refs/codex/…` で止まったら `rmdir /s /q .git\refs\codex`
- 起動中の入口・ツールは古いコードのまま。コードを直したら「すべて終了」→ start-all.bat
