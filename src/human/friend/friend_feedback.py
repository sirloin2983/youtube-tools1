"""友人の「要らない」を PC 側に戻す(送るアプリ 2.6.0。notes:docs/spec/friend.md の 2-14。2026-10-08 ユーザー「不採用の場合こちらにフィードバック」)。

アプリは届いたパックを受け取らずに消すとき、受付のフォルダ(Dropbox の 切り抜き依頼\\)の直下に <zip の名前(.zip 抜き)>.feedback.json を置く:
  {"v": 1, "kind": "feedback", "verdict": "reject", "zip": "<依頼 id>__<題> 1-5.zip", "requestId": "...", "title": "...", "sentAt": "...", "origin"?: "request"|"auto"}
入口の受付(src/human/friend/intake.py)がそれを読んで apply を呼ぶ。apply は、届けた記録 logs/deliveries.jsonl(まとめて実行が zip を置くたびに
record_delivery で 1 行: zip の名前・依頼・配信・入っていたパックとスタジオのマーク)からその zip の中身を引き、M9 の「要らない」と同じ道
(cases.discard_clip。ただし mark_id は空)で切り抜きの動画・パック・途中のファイルを ごみ箱フォルダ へ(3 日で消える)。
スタジオのマークは変えない(2026-10-08 ユーザー決定: こちらが友人へ送る基準と友人が実際に採用する基準は別。マークの採用の記録は
見どころ検出の精度に使うので混ぜない)。不採用の記録は logs/friend_feedback.jsonl に 1 行(配信 id・マーク id・zip・パック・出どころ origin。あとで精度の道具が読める)。
出どころ origin(D-SEND 2-7)は request か auto: .feedback.json の任意の origin、無ければ届けた記録の出どころ(手で届けるは auto)、それも無ければ null。
文字起こしは消さない(精度のデータ)。
"""
import json
import os
import re
import time

from flow import deliveries
from ytt import fsio, tools

DELIVERIES_LOG = deliveries.LOG           # 届けた記録(入口の作業データの logs の中。持ち主は ② flow/deliveries)
FEEDBACK_LOG = "friend_feedback.jsonl"    # 友人の「要らない」の記録
SUFFIX = ".feedback.json"
# 判定: reject = 要らない(片付ける)/ made_video = 動画にした(F1 F6a。片付けずに記録だけ = 採用の数に数える)。
# 名前は送り返しの採否 returns.VERDICTS(keep・reject・made_video)と同じ(数え方をそろえる。keep は .feedback.json では送らない)
VERDICTS = ("reject", "made_video")
LABELS = {"reject": "要らない", "made_video": "動画にした"}
ORIGINS = ("request", "auto")   # 届いた物の出どころ(D-SEND 2-7。送り返しの returns.ORIGINS と同じ)
MAX_BYTES = 64 * 1024
MAX_SCAN = 4 * 1024 * 1024                # 届けた記録を末尾から読む上限
NAME_RE = re.compile(r'^[^\\/:*?"<>|\x00-\x1f]{1,200}$')


def record_delivery(log_dir, zip_path, run, packs, marks=None, origin="request", ended_at=None):
    """zip を 出力\\ に置いたことを deliveries.jsonl に 1 行。書く口は ② flow/deliveries.record(D-SEND でそちらへ寄せた。ここは渡すだけ)"""
    return deliveries.record(log_dir, zip_path, run, packs, marks, origin, ended_at)


def _append(log_dir, name, row):
    """log_dir/name(jsonl)に 1 行足す(フォルダが無ければ作る)。書けなければ OSError。
    回さない(ytt/fsio.append_line の max_bytes None: find_delivery は今のファイルだけを見るので、回すと届けた記録を引けなくなる)"""
    fsio.append_line(os.path.join(log_dir, name), json.dumps(row, ensure_ascii=False) + "\n", None)


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
    out = {"zip": z, "verdict": d["verdict"], "requestId": str(d.get("requestId") or "")[:64], "title": str(d.get("title") or "")[:200]}
    if d.get("origin") in ORIGINS:   # 届いた物の出どころ(D-SEND 2-7。任意。無い・知らない値は鍵ごと無し)
        out["origin"] = d["origin"]
    return out


def _origin(fb, row):
    """記録に残す出どころ(友人に見せる形 request か auto): 友人のアプリが書いた origin → 届けた記録の出どころ(手で届けるは auto)→ 分からなければ None"""
    if fb.get("origin") in ORIGINS:
        return fb["origin"]
    if row:
        return "request" if deliveries.origin_of(row) == "request" else "auto"
    return None


def apply(log_dir, fb, trash=None, log=None, discard=None):
    """友人の「要らない」を当てる: 届けた記録にあるパックと切り抜きの動画を ごみ箱フォルダ へ(3 日で消える)、記録を friend_feedback.jsonl に。
    スタジオのマークは変えない(2026-10-08 ユーザー決定: こちらが友人へ送る基準と友人が実際に採用する基準は別。マークの採用の記録は
    見どころ検出の精度に使うので混ぜない)。不採用の記録は markId つきでこのファイルに残す。
    discard: 切り抜き 1 本ぶんを ごみ箱 へ移す関数(入口が cases.discard_clip を渡す。形は discard(trash, studio, video_id, mark_id, media, pack)
    -> (移したもの, ごみ箱の場所, スタジオの返事)。失敗は ValueError の子 cases.ReviewError か OSError)。案件の部品 cases を読み込まないための口
    -> {"ok", "summary", "packs": [...]}。届けた記録が無い・部品が無いときは ok False と理由"""
    log = log or (lambda msg: None)
    row = find_delivery(log_dir, fb["zip"])
    if fb.get("verdict") == "made_video":
        return _record_made(log_dir, fb, row, log)
    if not row:
        return {"ok": False, "reason": "届けた記録に %s がありません(この入口が届けたものではないか、記録が消えています)" % fb["zip"]}
    if trash is None:
        return {"ok": False, "reason": "ごみ箱フォルダが使えません"}
    if discard is None:
        return {"ok": False, "reason": "切り抜きを片付ける部品が使えません"}
    results, errors = [], []
    for p in row.get("packs") or []:
        d, path, mid = str(p.get("dir") or ""), str(p.get("path") or ""), str(p.get("markId") or "")
        if not d and not path:
            continue
        try:
            moved, where, _st = discard(trash, None, row.get("videoId") or "", "", path, d or None)   # mark_id を空 = マークは触らない
        except (ValueError, OSError) as e:   # cases.ReviewError は ValueError の子
            errors.append(str(e))
            results.append({"dir": d, "markId": mid, "error": str(e)})
            continue
        results.append({"dir": d, "markId": mid, "moved": len(moved), "trash": where})
    rec = {"at": int(time.time() * 1000), "zip": fb["zip"], "verdict": fb["verdict"], "requestId": fb.get("requestId") or row.get("requestId") or "",
           "title": fb.get("title") or row.get("title") or "", "videoId": row.get("videoId") or "", "runId": row.get("runId") or "", "packs": results,
           "origin": _origin(fb, row)}
    try:
        _append(log_dir, FEEDBACK_LOG, rec)
    except OSError as e:
        log("友人の返事: 記録を書けませんでした(%s)" % tools.why(e))
    done = [r for r in results if "error" not in r]
    summary = "%d 本をごみ箱フォルダへ(スタジオのマークはそのまま。記録は %s)" % (len(done), FEEDBACK_LOG)
    if errors:
        summary += "。片付けられなかった %d 本: %s" % (len(errors), errors[0][:120])
    log("友人の返事: 要らない %s → %s" % (fb["zip"], summary))
    return {"ok": bool(done), "summary": summary, "packs": results}


def _record_made(log_dir, fb, row, log):
    """友人の「動画にした」(F1 F6a): 何も片付けず、friend_feedback.jsonl に verdict made_video の 1 行だけ(届けた記録が無くても残す = 数える)"""
    row = row or {}
    packs = [{"dir": str(p.get("dir") or ""), "markId": str(p.get("markId") or "")} for p in row.get("packs") or [] if isinstance(p, dict)]
    rec = {"at": int(time.time() * 1000), "zip": fb["zip"], "verdict": "made_video", "requestId": fb.get("requestId") or row.get("requestId") or "",
           "title": fb.get("title") or row.get("title") or "", "videoId": row.get("videoId") or "", "runId": row.get("runId") or "", "packs": packs,
           "origin": _origin(fb, row)}
    try:
        _append(log_dir, FEEDBACK_LOG, rec)
    except OSError as e:
        log("友人の返事: 記録を書けませんでした(%s)" % tools.why(e))
        return {"ok": False, "reason": "記録を書けませんでした(%s)" % tools.why(e)}
    summary = "記録だけ(片付けない。記録は %s)" % FEEDBACK_LOG + ("" if row else "。届けた記録にこの zip はありません")
    log("友人の返事: 動画にした %s → %s" % (fb["zip"], summary))
    return {"ok": True, "summary": summary, "packs": packs}


def read_text(path, limit=MAX_BYTES):
    """.feedback.json を読む(大きすぎれば ValueError・読めなければ OSError。BOM は外す・壊れた文字は置き換える)"""
    with open(path, "rb") as f:
        raw = f.read(limit + 1)
    if len(raw) > limit:
        raise ValueError("ファイルが大きすぎます")
    return raw.decode("utf-8-sig", "replace")
