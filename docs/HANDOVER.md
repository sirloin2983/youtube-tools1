# HANDOVER — 次のセッションへの引き継ぎ(2026-09-26)

セッションを切り替えるたびに上書きする。詳しい経緯は `docs/WORKLOG.md`、ルールは `AGENTS.md`。

## 今の状態
- GitHub の main = 928c3b1 以降。この後の未コミット(Resolve パックの一本化)は WORKLOG の最後の記録を参照(push.bat で送る)
- 版: 入口 0.4.0・切り抜きスタジオ 0.3.0・文字起こし 0.12.0・cut2resolve 0.6.0・ytt_core 1.1.0
- 統合計画: 段階3 完了(3-3 は Windows 実機で確認済み。Resolve パックの一本化は 09-26 に実装、実機確認待ち)
- Resolve パックを作るのは `cut2resolve/pack.py` だけ。文字起こしの zip は pack を呼ぶだけ。契約テスト `tools/test_resolve_pack_contract.py`、経緯は `docs/resolve-pack-unification.md`
- 資料の正本はリポジトリ(09-26 決定)。統合計画だけは Claude Docs「動画編集ツール 統合計画」が正本(09-26 の状態に更新済み)

## 次の作業(上から順に)
1. 実機確認: 「すべて終了」→ start-all.bat → 文字起こし画面の「Resolveパッケージ(zip)」→ 展開 → 友人へ.txt の手順で Resolve に取り込めるか
   (スタジオの余白つき素材ありで、クリップの端を前後に延ばせるか)。cut2resolve の Text+ パックでも余白つき素材が入るか
2. cut2resolve の `.runtime`・siblings を ytt_core に切り替える(`docs/integration-plan.md` の「段階3-2で決めたこと」)
3. 段階4: 作業データをリポジトリの外へ(場所は未決。例 `%LOCALAPPDATA%\youtube-tools`)。コピーのみ・元は残す・削除はユーザー確認後。
   `.whisper_models`(約484MB)・`0old`(約2GB。API キーを含む)もリポジトリの外へ移すのが安全

## 注意
- Cowork(クラウド)は PC で git・移動・削除ができない。書き込んだら読み直して一致を確かめる。push はユーザーの push.bat
- GPT(Codex)がこのフォルダで作業すると `.git\refs\codex\` に壊れた参照が残ることがある → push.bat が `bad object refs/codex/…` で止まったら `rmdir /s /q .git\refs\codex`
- PC に Python が2つある可能性(`__pycache__` に 3.10 と 3.12)。faster-whisper は入口と同じ Python で動いた(3-3 の実機確認)
- 起動中の入口・ツールは古いコードのまま。コードを直したら「すべて終了」→ start-all.bat
- 文字起こし側に Resolve 用の計算を書き足さない(二重実装に戻さない。契約テストが検出する)
