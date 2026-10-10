"""② 取り込みの口(役割で組み直す RS6 a-5a。2026-10-10)。③ 人・④ データが入力の判定(① pipeline/analyze・ingest)を直に読まずに済む動詞。

- `probe(item)` : 入力 1 件(YouTube の URL・動画 ID・手元のファイルのパス・{kind, ...} の辞書)を見分けて {kind, id, title, source, live?} にそろえる。
  ② が足すこと = 文字だけの入力の見分け(ファイルがあればファイル・無ければ YouTube)・ライブの録画は {kind: "live"} だけ受け付ける(解析へは進めない)。
  不正な入力は ytt.errors.ApiError 400(bad_source)。`source` は動画の台帳(human/review/store)の ensure に渡す辞書。
- `prune_cache` は ytt/fsio へ、`check_live`・`LIVE_NO_ANALYZE` は ytt/yturl へ下ろした(純粋で ② の責任が無いので、動詞にしない)
"""
import os

from pipeline.analyze import analyze


def probe(item):
    """入力 1 件の判定。-> {"kind": "youtube" | "file" | "live", "id", "title", "source", "live"?}"""
    if isinstance(item, str):
        text = item.strip().strip('"')
        item = {"kind": "file", "path": text} if os.path.isfile(text) else {"kind": "youtube", "url": text}
    src = analyze.validate_live(item) if isinstance(item, dict) and item.get("kind") == "live" else analyze.validate_source(item)
    out = {"kind": src["kind"], "id": src["videoId"], "title": src.get("name", ""), "source": src}
    if src["kind"] == "live":
        out["live"] = src["live"]
    return out
