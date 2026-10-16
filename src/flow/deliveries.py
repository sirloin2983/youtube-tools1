# -*- coding: utf-8 -*-
"""② 管理の層 flow: 友人へ届けた記録(入口の作業データの logs/deliveries.jsonl)の読み口(OPT-M2。notes:plan/opt-manage.md の 7x-2)。

データの持ち主は ②(届けた = 起きた事実は起こした層。決定 3-48 の「切り抜きの印を 3 本に」)。④ の片付けは記録のファイルを直に読まず、
ここの delivered_requests だけを読む。書く口 record は D-SEND の段 1 でここへ寄せた(③ human/friend/friend_feedback.record_delivery は
ここへ渡すだけの薄い転送)。行の鍵 origin(request・auto・manual。flow/sendpolicy.ORIGINS)と endedAt(配信が終わった時刻。ミリ秒。分からなければ 0)は
D-SEND から。無い古い行は、依頼の id があれば request・無ければ auto として読む。既存の読み手は知らない鍵を無視する。
行の鍵 mode(実行の形。まとめて実行の full など。手で届けた・無い古い行は "")は MARKS-3 から(④ 案件が「まとめて実行の自動で送った切り抜き」を見分ける)。
ファイルの名前は書く側と同じ(テストが一致を見張る)。
切り抜きごとの「届けた」(MARKS-3。案件の一覧の clip.review・3 日の片付け)は delivered_marks で引く(案件には写さない)。
"""
import json
import os
import threading
import time

from ytt import fsio

LOG = "deliveries.jsonl"        # 届けた記録(入口の作業データの logs の中)
MAX_SCAN = 4 * 1024 * 1024      # 末尾から読む上限


def record(log_dir, zip_path, run, packs, marks=None, origin="request", ended_at=None):
    """zip を 出力\\ に置いたことを 1 行足す(あとで友人の「要らない」が来たときに中身を引くため・配信ごとの届けた時刻を引くため)。
    書けなくても届けるのは止めない。ended_at = 配信が終わった時刻(秒。分からなければ None = 0)。-> 書いた行(dict)"""
    marks = marks or {}
    end = int(ended_at * 1000) if isinstance(ended_at, (int, float)) and not isinstance(ended_at, bool) and ended_at > 0 else 0
    row = {"at": int(time.time() * 1000), "zip": os.path.basename(zip_path), "requestId": run.request_id or "", "runId": run.id,
           "videoId": run.video_id or "", "title": run.title or "", "origin": origin, "endedAt": end,
           "mode": getattr(run, "mode", None) if isinstance(getattr(run, "mode", None), str) else "",
           "packs":[{"dir": d, "path": (marks.get(d) or {}).get("path") or "", "markId": (marks.get(d) or {}).get("markId") or ""} for d in packs]}
    try:
        # 回さない(max_bytes None): find_delivery は今のファイルだけを見るので、回すと届けた記録を引けなくなる
        fsio.append_line(os.path.join(log_dir, LOG), json.dumps(row, ensure_ascii=False) + "\n", None)
    except OSError:
        pass
    return row


def origin_of(row):
    """行の出どころ。origin の鍵が無い古い行は、依頼の id があれば request・無ければ auto"""
    o = row.get("origin")
    if o in ("request", "auto", "manual"):
        return o
    return "request" if row.get("requestId") else "auto"


def delivered_videos(log_dir, origin=None):
    """-> {配信 id: 最後に届けた時刻(秒)}。origin を渡すとその出どころの行だけ(request・auto・manual)。読めなければ None(届けたかが分からない)"""
    got = rows(log_dir)
    if got is None:
        return None
    out = {}
    for d in got:
        vid, at = d.get("videoId"), d.get("at")
        if not isinstance(vid, str) or not vid or (origin is not None and origin_of(d) != origin):
            continue
        sec = at / 1000.0 if isinstance(at, (int, float)) and not isinstance(at, bool) and at > 0 else 0.0
        out[vid] = max(out.get(vid, 0.0), sec)
    return out


def rows(log_dir):
    """届けた記録の行(dict)を古い順に。末尾から MAX_SCAN まで。読めなければ None"""
    p = os.path.join(log_dir, LOG)
    try:
        size = os.path.getsize(p)
        with open(p, "rb") as f:
            if size > MAX_SCAN:
                f.seek(size - MAX_SCAN)
            text = f.read().decode("utf-8", "replace")
    except OSError:
        return None
    out = []
    for line in text.splitlines():
        try:
            d = json.loads(line)
        except ValueError:
            continue
        if isinstance(d, dict):
            out.append(d)
    return out


def delivered_requests(log_dir):
    """-> {依頼 id: 最後に届けた時刻(秒)}。時刻の無い古い行は 0(= ずっと前)。読めなければ None(届けたかが分からない)"""
    got = rows(log_dir)
    if got is None:
        return None
    out = {}
    for d in got:
        rid, at = d.get("requestId"), d.get("at")
        if not isinstance(rid, str) or not rid:
            continue
        sec = at / 1000.0 if isinstance(at, (int, float)) and not isinstance(at, bool) and at > 0 else 0.0
        out[rid] = max(out.get(rid, 0.0), sec)
    return out


def pack_name(pack_dir):
    """パックのフォルダ -> 突き合わせに使う名前(フォルダの名前。大文字小文字はそろえる)。分からなければ空の文字列"""
    return os.path.normcase(os.path.basename(pack_dir.rstrip("\\/"))) if isinstance(pack_dir, str) and pack_dir else ""


_marks_cache, _marks_lock = {}, threading.Lock()   # 記録のパス -> ((更新時刻, 大きさ), 結果)。変わったときだけ読み直す


def delivered_marks(log_dir):
    """切り抜きごとの届けた -> (by_mark, by_pack)。by_mark = {(配信, スタジオのマーク): {"at" ミリ秒, "zip", "origin", "mode"}}・
    by_pack = {パックの名前(pack_name): 同じ形 + "videoId"・"markId"}(配信かマークの空の行 = マークの空の古い行・配信の空の行だけ。パックのフォルダの名前から引く)。
    同じ切り抜きを二度届けたら新しい方。全文を読む(末尾だけではない)。読むのはファイルが変わったときだけ(更新時刻と大きさで覚える)。
    記録が無ければ ({}, {})(まだ何も届けていない)・読めなければ None(届けたかが分からない)。返す辞書は覚えた物なので書き換えない"""
    p = os.path.join(log_dir, LOG) if log_dir else ""
    try:
        st = os.stat(p)
    except FileNotFoundError:
        return {}, {}
    except (OSError, ValueError):
        return None
    sig = (st.st_mtime_ns, st.st_size)
    key = os.path.normcase(os.path.abspath(p))
    with _marks_lock:
        hit = _marks_cache.get(key)
        if hit and hit[0] == sig:
            return hit[1]
    try:
        with open(p, "rb") as f:
            text = f.read().decode("utf-8", "replace")
    except OSError:
        return None
    by_mark, by_pack = {}, {}
    for line in text.splitlines():
        try:
            d = json.loads(line)
        except ValueError:
            continue
        if not isinstance(d, dict) or not isinstance(d.get("packs"), list):
            continue
        at = d.get("at")
        at = int(at) if isinstance(at, (int, float)) and not isinstance(at, bool) and at > 0 else 0
        vid = d.get("videoId") if isinstance(d.get("videoId"), str) else ""
        base = {"at": at, "zip": str(d.get("zip") or "")[:200], "origin": origin_of(d), "mode": d.get("mode") if isinstance(d.get("mode"), str) else ""}
        for pk in d["packs"]:
            if not isinstance(pk, dict):
                continue
            mid = pk.get("markId") if isinstance(pk.get("markId"), str) else ""
            if vid and mid:
                if at >= (by_mark.get((vid, mid)) or {}).get("at", -1):
                    by_mark[(vid, mid)] = dict(base)
                continue
            name = pack_name(pk.get("dir"))   # 配信かマークの分からない行だけ(名前がぶつかる相手を減らす)
            if name and at >= (by_pack.get(name) or {}).get("at", -1):
                by_pack[name] = dict(base, videoId=vid, markId=mid)
    res = (by_mark, by_pack)
    with _marks_lock:
        _marks_cache[key] = (sig, res)
    return res


# ---- 送らなかった記録(ds1・3-71 m3e。前は ④ 案件の 採用.json の auto[マーク].notSent・origin "full" に写していた)
NOT_SENT_LOG = "not-sent.jsonl"   # まとめて実行の自動で送る形(D-SEND)で送らなかった切り抜き(届けた記録の隣)


def record_not_sent(log_dir, video_id, mark_id, code, text, run_id=""):
    """送らなかった切り抜きを 1 行足す(段 deliver の判定 = flow/sendpolicy の理由の鍵 code と文 text・預けた分の 48 時間切れ expired)。
    ④ 案件はこれを not_sent_marks で引き、送らなかった理由の札と「まとめて実行の切り抜き」(品質のカード)を出す。
    書けなければ OSError(呼び手 flow/delivery が段を止めずにログへ)。-> 書いた行"""
    row = {"at": int(time.time() * 1000), "videoId": str(video_id or ""), "markId": str(mark_id or ""), "code": str(code or "")[:40],
           "text": str(text or "")[:200], "runId": str(run_id or "")}
    fsio.append_line(os.path.join(log_dir, NOT_SENT_LOG), json.dumps(row, ensure_ascii=False) + "\n", None)
    return row


def not_sent_marks(log_dir):
    """-> {(配信, スタジオのマーク): {"code", "text", "at" ミリ秒}}(同じ切り抜きは新しい方)。無い・読めなければ {}(札が出ないだけ)。
    末尾から MAX_SCAN まで。届けたあとに出さないのは読み手(④ 案件)が届けた記録と重ねて決める"""
    p = os.path.join(log_dir, NOT_SENT_LOG) if log_dir else ""
    try:
        size = os.path.getsize(p)
        with open(p, "rb") as f:
            if size > MAX_SCAN:
                f.seek(size - MAX_SCAN)
            text = f.read().decode("utf-8", "replace")
    except (OSError, ValueError):
        return {}
    out = {}
    for line in text.splitlines():
        try:
            d = json.loads(line)
        except ValueError:
            continue
        if not isinstance(d, dict) or not isinstance(d.get("code"), str) or not d["code"]:
            continue
        vid, mid = d.get("videoId"), d.get("markId")
        if not (isinstance(vid, str) and vid and isinstance(mid, str) and mid):
            continue
        at = d.get("at")
        at = int(at) if isinstance(at, (int, float)) and not isinstance(at, bool) and at > 0 else 0
        if at >= (out.get((vid, mid)) or {}).get("at", -1):
            out[(vid, mid)] = {"code": d["code"][:40], "text": str(d.get("text") or "")[:200], "at": at}
    return out
