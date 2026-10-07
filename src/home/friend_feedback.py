"""友人の「要らない」を PC 側に戻す(送るアプリ 2.6.0。docs/spec/friend-intake.md の 2-14。2026-10-08 ユーザー「不採用の場合こちらにフィードバック」)。

アプリは届いたパックを受け取らずに消すとき、受付のフォルダ(Dropbox の 切り抜き依頼\\)の直下に <zip の名前(.zip 抜き)>.feedback.json を置く:
  {"v": 1, "kind": "feedback", "verdict": "reject", "zip": "<依頼 id>__<題> 1-5.zip", "requestId": "...", "title": "...", "sentAt": "..."}
入口の受付(src/home/intake.py)がそれを読んで apply を呼ぶ。apply は、届けた記録 logs/deliveries.jsonl(まとめて実行が zip を置くたびに
record_delivery で 1 行: zip の名前・依頼・配信・入っていたパックとスタジオのマーク)からその zip の中身を引き、M9 の「要らない」と同じ道
(cases.discard_clip)で ① 切り抜きの動画・パック・途中のファイルを ごみ箱フォルダ へ(3 日で消える) ② スタジオのマークを不採用(rejected)に
(= スタジオの feedback.jsonl に誤検出として残り、見どころ検出の学習データになる)。結果は logs/friend_feedback.jsonl に 1 行。
文字起こしは消さない(精度のデータ)。マークの無いパック(友人の動画の依頼)は ① だけ。
"""
import json
import os
import re
import time

import cases
from ytt_core import fsio

DELIVERIES_LOG = "deliveries.jsonl"       # 届けた記録(入口の作業データの logs の中)
FEEDBACK_LOG = "friend_feedback.jsonl"    # 友人の「要らない」の記録
SUFFIX = ".feedback.json"
VERDICTS = ("reject",)
MAX_BYTES = 64 * 1024
MAX_SCAN = 4 * 1024 * 1024                # 届けた記録を末尾から読む上限
NAME_RE = re.compile(r'^[^\\/:*?"<>|\x00-\x1f]{1,200}$')


def record_delivery(log_dir, zip_path, run, packs, marks=None):
    """zip を 出力\\ に置いたことを deliveries.jsonl に 1 行(あとで友人の「要らない」が来たときに中身を引くため)。書けなくても届けるのは止めない"""
    marks = marks or {}
    row = {"at": int(time.time() * 1000), "zip": os.path.basename(zip_path), "requestId": run.request_id or "", "runId": run.id,
           "videoId": run.video_id or "", "title": run.title or "",
           "packs": [{"dir": d, "path": (marks.get(d) or {}).get("path") or "", "markId": (marks.get(d) or {}).get("markId") or ""} for d in packs]}
    try:
        os.makedirs(log_dir, exist_ok=True)
        with open(os.path.join(log_dir, DELIVERIES_LOG), "a", encoding="utf-8") as f:
            f.write(json.dumps(row, ensure_ascii=False) + "\n")
    except OSError:
        pass
    return row


def find_delivery(log_dir, zip_name):
    """deliveries.jsonl から、その zip の名前の最後の行。無ければ None"""
    p = os.path.join(log_dir, DELIVERIES_LOG)
    try:
        size = os.path.getsize(p)
        with open(p, "rb") as f:
            if size > MAX_SCAN:
                f.seek(size - MAX_SCAN)
            text = f.read().decode("utf-8", "replace")
    except OSError:
        return None
    found = None
    for line in text.splitlines():
        try:
            d = json.loads(line)
        except ValueError:
            continue
        if isinstance(d, dict) and d.get("zip") == zip_name:
            found = d
    return found


def parse(text):
    """アプリが置いた .feedback.json の中身を確かめる。-> {"zip", "verdict", "requestId", "title"}。形が違えば ValueError"""
    try:
        d = json.loads(text)
    except ValueError:
        raise ValueError("JSON として読めません")
    if not isinstance(d, dict) or d.get("v") != 1 or d.get("kind") != "feedback":
        raise ValueError("記録の形が正しくありません")
    if d.get("verdict") not in VERDICTS:
        raise ValueError("知らない判定です: %s" % str(d.get("verdict"))[:20])
    z = d.get("zip")
    if not isinstance(z, str) or not NAME_RE.match(z) or z in (".", "..") or not z.lower().endswith(".zip"):
        raise ValueError("zip の名前が正しくありません")
    return {"zip": z, "verdict": d["verdict"], "requestId": str(d.get("requestId") or "")[:64], "title": str(d.get("title") or "")[:200]}


def apply(log_dir, fb, studio=None, trash=None, log=None):
    """友人の「要らない」を当てる。-> {"ok", "summary", "packs": [...]}。届けた記録が無い・部品が無いときは ok False と理由"""
    log = log or (lambda msg: None)
    row = find_delivery(log_dir, fb["zip"])
    if not row:
        return {"ok": False, "reason": "届けた記録に %s がありません(この入口が届けたものではないか、記録が消えています)" % fb["zip"]}
    if trash is None or studio is None:
        return {"ok": False, "reason": "ごみ箱フォルダか切り抜きスタジオが使えません"}
    results, errors, rejected = [], [], 0
    for p in row.get("packs") or []:
        d, path, mid = str(p.get("dir") or ""), str(p.get("path") or ""), str(p.get("markId") or "")
        if not d and not path:
            continue
        try:
            moved, where, st = cases.discard_clip(trash, studio, row.get("videoId") or "", mid, path, d or None)
        except cases.ReviewError as e:
            errors.append(str(e))
            results.append({"dir": d, "error": str(e)})
            continue
        rejected += 1 if st == "rejected" else 0
        results.append({"dir": d, "moved": len(moved), "trash": where, "studio": st})
    rec = {"at": int(time.time() * 1000), "zip": fb["zip"], "verdict": fb["verdict"], "requestId": fb.get("requestId") or row.get("requestId") or "",
           "title": fb.get("title") or row.get("title") or "", "videoId": row.get("videoId") or "", "runId": row.get("runId") or "", "packs": results}
    try:
        os.makedirs(log_dir, exist_ok=True)
        with open(os.path.join(log_dir, FEEDBACK_LOG), "a", encoding="utf-8") as f:
            f.write(json.dumps(rec, ensure_ascii=False) + "\n")
    except OSError as e:
        log("友人の返事: 記録を書けませんでした(%s)" % (e.strerror or e.__class__.__name__))
    done = [r for r in results if "error" not in r]
    summary = "%d 本をごみ箱フォルダへ(スタジオのマークを不採用 %d 本)" % (len(done), rejected)
    if errors:
        summary += "。片付けられなかった %d 本: %s" % (len(errors), errors[0][:120])
    log("友人の返事: 要らない %s → %s" % (fb["zip"], summary))
    return {"ok": bool(done), "summary": summary, "packs": results}


def read_text(path, limit=MAX_BYTES):
    """.feedback.json を読む(大きすぎれば ValueError)"""
    if os.path.getsize(path) > limit:
        raise ValueError("ファイルが大きすぎます")
    return fsio.read_text_file(path, limit) if hasattr(fsio, "read_text_file") else open(path, "rb").read(limit).decode("utf-8-sig", "replace")
