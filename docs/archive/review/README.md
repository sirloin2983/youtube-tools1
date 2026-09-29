# 2026-09-24 全ツールの見直し・UI 刷新(まとめ)

ユーザーの依頼:「現状のツールすべてのコードを読み直して改善できる箇所があれば修正。UI 面もスタイリッシュな見た目に変更。細かい機能追加も可。将来一つのパイプラインで流れる前提で作る」
決めた方針(ユーザーの回答): ダーク/ライト切り替え、受け渡しの形式だけ統一(将来のアプリ統合を見据える)、cut2resolve に専用画面、納品は別フォルダ(`_new`)に置いて確認後に入れ替え。

## 版
| ツール | 前 | 後 |
|---|---|---|
| 切り抜きスタジオ | 0.1.8 | **0.2.0** |
| 文字起こしツール | 0.9.9 | **0.10.0** |
| cut2resolve | 0.1.3 | **0.2.0**(srt2resolve 0.1.4) |

## 共通
- `ui-kit/`: 共通の見た目(色の変数・部品・ダーク/ライト・「他のツール」メニュー)。正本1つを `tools/sync_ui_kit.py` で各ツールへ写す。ずれは `tools/test_ui_kit_sync.py` で検出
- `docs/pipeline.md`: 受け渡しの約束 v1(clip/v1・transcript/v1・cut-plan/v1、画面リンク、`.runtime` とポート共有、統合に向けた書き方、API 一覧)
- 3つのサーバー: 他のツールの画面からのリンクで開くと 403 になっていた問題を修正(画面への遷移だけ許可、iframe・API は拒否)、`/api/siblings`
- `tools/e2e_pipeline.py`: スタジオの書き出し → 文字起こし(.clip.json を読む・動画の隣に transcript/v1 を保存)→ cut2resolve(残す行で試算・パック)の通し確認

## 各ツールの詳しい報告
- [clip-studio-backend.md](clip-studio-backend.md) — 不具合 23 件(末尾をまたぐ書き出しの失敗、feedback.jsonl の古い記録の消失、registry.json の初期化、Windows のポート二重使用 ほか)、.clip.json、/api/state の環境チェック
- [clip-studio-frontend.md](clip-studio-frontend.md) — 画面の刷新、不具合 19 件(ダークの白い入力欄、空欄保存で API キーが消える、2回押し確認の残り ほか)、受け渡しリンク、キー一覧、設定の引き出し
- [transcribe-backend.md](transcribe-backend.md) — 不具合 17 件(話者判別・再認識の結果と画面の保存の競合、ネットワークパスの自動アクセス、Resolve パッケージの長さ ほか)、受け渡しの API
- [transcribe-frontend.md](transcribe-frontend.md) — 画面の刷新(行の状態の見分け)、不具合 16 件、`?media=`・元の配信の表示・動画の隣に保存・cut2resolve で開く
- [cut2resolve.md](cut2resolve.md) — 処理の共通化(pack.py)、不具合修正、専用画面(新規)

## テスト(統合後の main で全部実行)
- スタジオ: Python 単体 すべて OK、test_review.cjs 14/14、e2e_analyze OK、e2e_ui 70/70
- 文字起こし: 単体 80 件 OK、test_document_save.cjs 9/9、e2e_ui_v098 / v08 / eval_v093 / handoff すべて OK、v07・v09 は想定内の「版 v0.9.4」だけ失敗
- cut2resolve: 単体 161 件 OK、e2e_ui 19/19
- 共通: test_ui_kit_sync OK、e2e_pipeline すべて OK

## ユーザーに判断してほしいこと(安全な既定で進めた)
1. スタジオの強調色がピンク → 全ツール共通の紫(ui-kit)
2. スタジオの設定を「右から出る引き出し」に
3. スタジオの ] [ を一覧の並び順どおりに移動(時刻順表示では従来どおり)
4. data.json が壊れたとき `.bak` から自動で戻すか(今は退避して空で起動)
5. 文字起こし由来の「残す区間」で、行と行の間のすき間を残すか(今は残さない)
6. `?clip=` で開いたときタイトルを自動で入れるか

## 実機(Windows)で確かめてほしいこと
- 3つの画面の見た目(フォント)・ダーク/ライト切り替え、他のツールへのリンク
- ポートの独占(同じポートで2つ起動しない)、黒い画面の×で閉じたときの `.runtime` の後始末
- 実際の yt-dlp・faster-whisper・DaVinci Resolve での動作(画面から作ったパックの取り込み)
