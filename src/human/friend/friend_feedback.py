"""友人の「要らない」を PC 側で片付ける(notes:docs/spec/friend.md の 2-14。ユーザー「不採用の場合こちらにフィードバック」)。

友人のアプリは判断を送り返しの .verdict.json(v 2)で返す。送り返しの受け取り(returns.scan)が、Dropbox で届けたパックの bad・unknown を apply に渡す
(入口の受付 intake が feedback= で returns へつなぐ)。apply は、届けた記録 logs/deliveries.jsonl(まとめて実行が zip を置くたびに
record_delivery で 1 行: zip の名前・依頼・配信・入っていたパックとスタジオのマーク)からその zip の中身を引き、M9 の「要らない」と同じ道
(cases.discard_clip。ただし mark_id は空)で切り抜きの動画・パック・途中のファイルを ごみ箱フォルダ へ(3 日で消える)。
スタジオのマークは変えない(ユーザー決定: こちらが友人へ送る基準と友人が実際に採用する基準は別。マークの採用の記録は
見どころ検出の精度に使うので混ぜない)。友人の「要らない」の記録は人の判断の記録 judgments.jsonl の 1 つだけ(10-19 ③ の統合 Q3。
前の logs/friend_feedback.jsonl は書かない・消さない。片付けに要る物は届けた記録 deliveries.jsonl とごみ箱の manifest.jsonl にある)。
文字起こしは消さない(精度のデータ)。
"""
import json
import os
import time

from flow import deliveries
from human import judgments
from ytt import tools

DELIVERIES_LOG = deliveries.LOG           # 届けた記録(入口の作業データの logs の中。持ち主は ② flow/deliveries)
MAX_SCAN = 4 * 1024 * 1024                # 届けた記録を末尾から読む上限


def record_delivery(log_dir, zip_path, run, packs, marks=None, origin="request"):
    """zip を 出力\\ に置いたことを deliveries.jsonl に 1 行。書く口は ② flow/deliveries.record(D-SEND でそちらへ寄せた。ここは渡すだけ)"""
    return deliveries.record(log_dir, zip_path, run, packs, marks, origin)


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


def _app_dir(log_dir):
    """作業データの app(judgments.jsonl・friend-returns の置き場所)。log_dir は入口の logs(app の直下)"""
    return os.path.dirname(os.path.normpath(log_dir))


def _judge(app_dir, log, **row):
    """人の判断の記録(judgments)に 1 行。書けなければ(空の欄 = markId の無い古い行も含む)ログに残して飛ばす。書けた行を返す(飛ばしたら None)"""
    try:
        return judgments.record(app_dir, **row)
    except (ValueError, OSError) as e:
        log("友人の返事: 人の判断の記録に書けませんでした(%s)" % tools.why(e))
        return None


def _judge_friend(log_dir, fb, row, what, at, log):
    """友人の「要らない」(reject)を人の判断の記録に、届けた記録のパックの markId ごとに 1 行(who friend・via friend_file)。
    届けた記録が無ければ何も書かない(パックが無い)。key の末尾は markId(無い古い行はパックの名前)"""
    if not row:
        return
    origin = deliveries.origin_of(row)
    for p in row.get("packs") or []:
        if not isinstance(p, dict):
            continue
        pack = os.path.basename(str(p.get("dir") or ""))
        mid = str(p.get("markId") or "")
        _judge(_app_dir(log_dir), log, who="friend", what=what, origin=origin, via="friend_file",
               videoId=str(row.get("videoId") or "") if mid else "", markId=mid, at=at,
               key="ff:%d:%s:%s" % (at, fb["zip"], mid or pack),
               ref={"zip": fb["zip"], "pack": pack, "requestId": fb.get("requestId") or row.get("requestId") or "", "runId": row.get("runId") or ""})


def apply(log_dir, fb, trash=None, log=None, discard=None):
    """友人の「要らない」を当てる: 届けた記録にあるパックと切り抜きの動画を ごみ箱フォルダ へ(3 日で消える)。
    スタジオのマークは変えない(ユーザー決定: こちらが友人へ送る基準と友人が実際に採用する基準は別。マークの採用の記録は
    見どころ検出の精度に使うので混ぜない)。判断は judgments.jsonl だけ(judged でなければここで reject を markId ごとに書く)。
    discard: 切り抜き 1 本ぶんを ごみ箱 へ移す関数(入口が cases.discard_clip を渡す。形は discard(trash, studio, video_id, mark_id, media, pack)
    -> (移したもの, ごみ箱の場所, スタジオの返事)。失敗は ValueError の子 cases.ReviewError か OSError)。案件の部品 cases を読み込まないための口
    fb = {"zip", "verdict": "reject", "requestId", "title", "origin"?, "judged"?}(judged = 判断の記録は送り返しの受け取りが書いた = ここでは片付けだけ)
    -> {"ok", "summary", "packs": [...]}。届けた記録が無い・部品が無いときは ok False と理由"""
    log = log or (lambda msg: None)
    row = find_delivery(log_dir, fb["zip"])
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
    if not fb.get("judged"):   # 送り返しの .verdict.json から来た物は、そちらが判断の記録を書いた(ここで reject を足すと bad を後から不明で上書きする)
        _judge_friend(log_dir, fb, row, "reject", int(time.time() * 1000), log)
    done = [r for r in results if "error" not in r]
    summary = "%d 本をごみ箱フォルダへ(スタジオのマークはそのまま。判断は judgments.jsonl)" % len(done)
    if errors:
        summary += "。片付けられなかった %d 本: %s" % (len(errors), errors[0][:120])
    log("友人の返事: 要らない %s → %s" % (fb["zip"], summary))
    return {"ok": bool(done), "summary": summary, "packs": results}
