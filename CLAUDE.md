# CLAUDE.md

@D:/Obsidian保管庫/youtube-tools/AGENTS.md

(共通の前提・ルールは資料の保管庫 `D:\Obsidian保管庫\youtube-tools` の AGENTS.md にまとめています。GPT/Codex と同じ内容を読むためです。リポジトリの AGENTS.md はそこへの案内だけ。Claude 専用の追記はこの下に書きます)

- セッションの最初(会話が要約された後も)に `py -3.12 dev/session_start.py [<領域>]` を流して今の状態を見る。子への指示文は `py -3.12 dev/session_start.py --brief <領域> --task "<一言>"` で下書きしてから start_session に渡す
