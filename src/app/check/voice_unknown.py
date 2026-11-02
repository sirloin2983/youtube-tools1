"""誰の声のカード(ソロの 10 秒 speaker:solo・コラボの 10 秒 speaker:collab)で [分からない] にしたカードの控え(11-02 ユーザー「わからないにしたやつ記憶しておいてほしい」)。

[分からない] を押したとき(human/check/apply.unknown が登録の keep を呼ぶ)、カードの音(ソロは選んだ 10 秒だけ)を
<app>/check/unknown-voice/<分からないの行の id>.wav に写し、<app>/check/unknown-voice.jsonl に 1 行足す:
  {id: 分からないの行の id, card, kind, source, video, key, piece?: [頭, 末](ソロの 48 秒の中の 10 秒), title, people, file, at}
研究の側が元の音(speaker-solo/・speaker-collab/)を置き直しても、答えの記録(answers.jsonl)が 1 世代回っても残る。
作業データの片付け(manage/keep/cleanup)は app/check を見ないので消えない。声は覚えない・カードはもう出さない(apply の分からないのまま)。
一覧は listing(Z で戻した分からないは外す)= dev/unknown_voices.py が出す
"""
import json
import os
import time

from human.check import answerlog
from ytt import fsio

DIR_NAME, INDEX_NAME = "unknown-voice", "unknown-voice.jsonl"
MAX_INDEX_BYTES = 8 * 1024 * 1024


def keep(app_dir, card, row, data, at=None):
    """分からないの控えを書く。data = 音のバイト列(無ければ記録だけ)・at = 答えた時刻(ミリ秒。既定は今 = 前の分を後から控えるとき用)。-> 写したファイルか None"""
    if not app_dir or not row.get("id"):
        return None
    t = card.get("target") or {}
    path = None
    if data:
        path = os.path.join(app_dir, "check", DIR_NAME, row["id"] + ".wav")
        os.makedirs(os.path.dirname(path), exist_ok=True)
        with open(path, "wb") as f:
            f.write(data)
    line = {"id": row["id"], "card": card.get("id"), "kind": card.get("kind"), "source": card.get("source"), "video": t.get("videoId"),
            "key": t.get("solo") or t.get("collab"), "title": (card.get("case") or {}).get("title"), "people": card.get("people"),
            "file": os.path.relpath(path, app_dir) if path else None, "at": int(at if at is not None else time.time() * 1000)}
    if t.get("piece"):
        line["piece"] = t["piece"]
    fsio.append_line(os.path.join(app_dir, "check", INDEX_NAME), json.dumps(line, ensure_ascii=False) + "\n", MAX_INDEX_BYTES, keep_old=True)   # 回すときも消さない(.old へ)
    return path


def listing(app_dir):
    """分からないにしたカードの一覧(古い順・Z で戻した分は外す)-> [{..., file(絶対パスか None), day}]"""
    p = os.path.join(app_dir, "check", INDEX_NAME)
    paths = [x for x in (p + ".old", p) if os.path.isfile(x)]   # 回した古い分(.old)が先
    if not paths:
        return []
    undone = answerlog.state(app_dir).undone
    out = []
    for path in paths:
        with open(path, encoding="utf-8", errors="replace") as f:
            for ln in f:
                try:
                    r = json.loads(ln)
                except ValueError:
                    continue
                if not isinstance(r, dict) or r.get("id") in undone:
                    continue
                r["file"] = os.path.join(app_dir, r["file"]) if r.get("file") else None
                r["day"] = time.strftime("%Y-%m-%d", time.localtime((r.get("at") or 0) / 1000))
                out.append(r)
    return out
