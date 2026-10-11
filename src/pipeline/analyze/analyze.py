"""解析(自動切り抜き ac/serve.py 由来。書き出し・手動の○×は持たない)。

音声(音量・高音域)・チャットのリプレイ・動画コメント欄のタイムスタンプから「盛り上がっている部分」を見つけ、区間の候補にする。
解析ジョブは辞書: state / phase / progress / error / cancel / proc / proc2 / chat / result。batch.py がこれを1本ずつ回す。
  new_job(spec) → run_analyze(job) → job["result"] = {source, candidates, series, signals, counts, warnings, spec}
"""
import glob
import gzip
import json
import math
import os
import re
import shutil
import time
import uuid

from . import levels  # 1 秒ごとの音量の測り方(配信中の検出と同じ 1 か所。OPT1)
from . import fetch  # 材料を取ってくる仕事とそのキャッシュ(OPT2)
from . import excite  # noqa: E402  盛り上がりの式(線 D の L1 で src/ytt_core/excite.py に移した。配信中の検出と同じ式。隣のファイル)
from ytt import yturl as _yturl   # URL・動画 ID の形と入力の判定(sources.py を畳んだ)
from ytt import fsio as _fsio, mediainfo as _media, procs as _procs, studio_env as _env  # noqa: E402  (RS3-4 にスタジオの common から。呼ぶたびに持ち主から読む)
from ytt.errors import ApiError, Cancelled
from ytt.textutil import fmt_ms, fmt_ts, num, permission_message, tail_reason   # 純粋な関数(差し替えない)
from .excite import (CAP, SENS, LAG_MAX, LAG_MIN_CORR, LAG_MIN_CONTRAST, smooth, median, local_baseline, robust_scale, audio_score, chat_z, shift_chat,  # noqa: E402,F401
                             chat_score, estimate_lag, head_ramp, comment_score, pick_clips, snap_quiet, downsample)   # 同じ名前で再公開(batch・テスト・e2e が analyze.X で呼ぶ)

MAX_DURATION = 12 * 3600
AUDIO_LEVEL_IDLE = 900   # 音量の解析(ffmpeg)で、この秒数まったく出力がなければ中止
HEAD_SEC_DEFAULT = 180   # 冒頭の減点をかける秒数(0で無効)
ARCHIVE_KEEP = 2000
SPEC_KEYS = ("count", "length", "sensitivity", "preRatio", "lag", "lagAuto", "headSec", "wAudio", "wChat", "wComments")   # 結果・archive に残す設定


def sig_cache_dir():
    return _env.p("cache", "signals")   # 音量の解析結果(動画IDごと)。感度・長さ・重みを変えた再解析で使い回す


# ---------- 入力の検査 ----------


def validate_live(o):
    """POST /api/videos/open {kind:"live", recorder, recording, url, title} → store.ensure に渡す source 辞書(id = 録画の id)。不正は ApiError。"""
    lv = _yturl.check_live(o)
    return {"kind": "live", "videoId": lv["recording"], "name": lv["recording"], "live": lv}


def validate_source(item):
    """キューに入れる1件({kind:"youtube", url|videoId} / {kind:"file", path}) → source 辞書。不正は ApiError。"""
    if not isinstance(item, dict):
        raise ApiError("bad_source", "入力が正しくありません", 400)
    if item.get("kind") == "file":
        p = _yturl.check_media_path(item.get("path"))
        return {"kind": "file", "path": p, "name": os.path.basename(p), "videoId": _yturl.file_video_id(p)}
    if item.get("kind") == "live" or _yturl.LIVE_ID_RE.match(str(item.get("videoId") or item.get("id") or "")):
        raise ApiError("bad_source", _yturl.LIVE_NO_ANALYZE, 400)   # ライブの録画は、YouTube としても file としても解析へ進めない(yt-dlp を呼ばない)
    vid = _yturl.parse_video_id(item.get("url") or item.get("videoId"))
    if not vid:
        raise ApiError("bad_source", "YouTube の動画URLではありません(watch?v=… / youtu.be/… / live/…)", 400)
    return {"kind": "youtube", "videoId": vid, "name": vid}


def validate_settings(req):
    """解析の設定(範囲外は丸める)。autoExport は廃止。maxHeight(画質の上限)も 0.24.0 で廃止(解析は音声しか取らず読んでいなかった。保存してある値は読み捨てる)。
    typePreset・typeOverride(配信タイプ別の重み。試験的)は 0.26.0 で機能ごと廃止(倍率が仮のまま効き目を測っていなかった。ユーザー決定 10-09。保存してある値は読み捨てる)。"""
    req = req if isinstance(req, dict) else {}
    sens = req.get("sensitivity") if req.get("sensitivity") in ("high", "normal", "low") else "normal"
    return {"useAudio": req.get("useAudio") is not False, "useChat": req.get("useChat") is not False,
            "useComments": req.get("useComments") is not False,
            "count": int(num(req.get("count"), 1, 30, 8)), "length": num(req.get("length"), 10, 120, 45), "preRatio": num(req.get("preRatio"), 0.3, 0.9, excite.PRE_RATIO_DEFAULT),
            "lag": num(req.get("lag"), 0, 30, 8), "lagAuto": req.get("lagAuto") is not False, "headSec": num(req.get("headSec"), 0, 600, HEAD_SEC_DEFAULT),
            "chatTimeout": int(num(req.get("chatTimeout"), 1, 120, 20)), "noCache": req.get("noCache") is True, "sensitivity": sens,
            "wAudio": num(req.get("wAudio"), 0, 3, 1.0), "wChat": num(req.get("wChat"), 0, 3, 1.0), "wComments": num(req.get("wComments"), 0, 3, 0.7)}


def make_spec(src, settings):
    """ファイル入力では、チャット・コメントは使えない。"""
    spec = dict(settings)
    spec["source"] = src
    if src["kind"] != "youtube":
        spec["useChat"] = spec["useComments"] = False
    return spec


# ---------- ジョブ ----------
def new_job(spec):
    return {"id": uuid.uuid4().hex[:10], "kind": "analyze", "state": "running", "phase": "開始", "progress": 0.0, "error": "", "spec": spec, "result": None,
            "cancel": False, "proc": None, "proc2": None, "proc3": None, "chat": None, "meta": None}


def chat_public(c):
    if not c:
        return None
    return {"state": c["state"], "elapsed": int((c["t1"] or time.time()) - c["t0"]), "bytes": c["bytes"]}


def cancel_job(job):
    job["cancel"] = True
    for k in ("proc", "proc2", "proc3"):
        _procs.terminate(job.get(k))


def skip_chat(job):
    """チャット待ちだけ打ち切る(音声などの解析は続ける)。"""
    c = job.get("chat")
    if c and c["state"] == "running":
        c["skip"] = True
        _procs.terminate(job.get("proc2"))
        return True
    return False


# ---------- 音量の解析結果のキャッシュ ----------
def sig_path(vid):
    return os.path.join(sig_cache_dir(), vid + ".json")


def load_sig(vid):
    """保存済みの音量の解析結果(長さ・全帯域・高音域)。無い・壊れている・形が違うなら None。"""
    d = _fsio.read_json_or(sig_path(vid), {}, kind=dict)
    try:
        full, band, dur = d.get("full"), d.get("band"), d.get("dur")
        if d.get("v") != 1 or not isinstance(full, list) or not isinstance(band, list) or not isinstance(dur, (int, float)):
            return None
        if not (20 <= dur <= MAX_DURATION) or len(full) < 20 or len(band) < 20 or abs(len(full) - dur) > 5 or abs(len(band) - dur) > 5:
            return None
        if not all(isinstance(x, (int, float)) and -100 <= x <= 20 for x in full[:: max(1, len(full) // 500)] + band[:: max(1, len(band) // 500)]):
            return None
        os.utime(sig_path(vid), None)
        return {"dur": float(dur), "full": [float(x) for x in full], "band": [float(x) for x in band]}
    except (OSError, ValueError, TypeError):
        return None


def save_sig(vid, dur, full, band):
    try:
        data = {"v": 1, "dur": round(dur, 2), "full": [round(x, 1) for x in full], "band": [round(x, 1) for x in band]}
        _fsio.write_json(sig_path(vid), data, indent=None, separators=(",", ":"))   # 一時ファイル名を固定しない・Windows のロックは再試行
        _fsio.prune_cache(sig_cache_dir(), "*.json", fetch.CHAT_CACHE_KEEP)
    except OSError:
        pass




# ---------- 解析データの保存(archive: 後から重みや判定ロジックを実データで見直すための記録) ----------
ARCHIVE_ID_RE = re.compile(r"^[\w-]{1,40}\Z", re.ASCII)


def archive_path(vid):
    return _env.p("archive", vid + ".json.gz") if isinstance(vid, str) and ARCHIVE_ID_RE.match(vid) else None


def load_archive(vid):
    p = archive_path(vid)
    try:
        with gzip.open(p, "rt", encoding="utf-8") as f:
            d = json.load(f)
        return d if isinstance(d, dict) and d.get("v") == 1 else None
    except (OSError, ValueError, TypeError, EOFError):
        return None


def save_archive(vid, payload, run, keep=ARCHIVE_KEEP):
    """1秒ごとの材料(音量・チャット・コメントの時刻と文面)と、解析ごとの設定・候補(直近5回分)を cache とは別に残す。壊れたら次の解析で作り直す。"""
    p = archive_path(vid)
    if not p:
        return False
    old = load_archive(vid)
    runs = (old or {}).get("runs")
    runs = [r for r in runs if isinstance(r, dict)] if isinstance(runs, list) else []   # 壊れた履歴で保存が毎回失敗し続けないように
    payload = dict(payload, v=1, videoId=vid, runs=runs[-4:] + [run])
    try:
        _fsio.atomic_write(p, gzip.compress(json.dumps(payload, ensure_ascii=False, separators=(",", ":")).encode("utf-8"), 6))
        fs = sorted((os.path.getmtime(q), q) for q in glob.glob(os.path.join(glob.escape(os.path.dirname(p)), "*.json.gz")))
        for _, q in fs[:-keep]:
            os.remove(q)
        return True
    except OSError:
        return False


# ---------- 解析 ----------
def audio_levels(job, path, dur, wdir, p0=0.12, p1=0.48):
    """1秒ごとの音量(RMS, dB)を ffmpeg 1 回のデコードで全帯域と高音域(2kHz 超)の 2 系列に。-> (full, band)。
    測り方・値の扱い(-90〜20 dB)は levels.py の 1 か所(配信中の検出 live_excite_worker.measure_levels と同じ物。OPT1)。
    wdir = 結果のファイルを置く作業フォルダ。進み具合は job["progress"] の p0〜p1"""
    ff = _env.find_tool("ffmpeg")
    if not ff:
        raise ApiError("no_ffmpeg", "ffmpeg が見つかりません(README の準備手順を確認してください)")

    def on_time(sec):
        if dur:
            job["progress"] = p0 + (p1 - p0) * min(1.0, sec / dur)
    levels.clear(wdir)
    cmd = [ff, "-hide_banner", "-nostdin", "-loglevel", "error"] + levels.args(path) + ["-progress", "pipe:1", "-nostats"]
    try:
        rc, err = _procs.run_capture(job, cmd, None, idle_timeout=AUDIO_LEVEL_IDLE, what="音量の解析", cwd=wdir, on_time=on_time)
    finally:
        full, band = levels.collect(wdir)
    if rc != 0 or not full:
        raise ApiError("audio", "音声を解析できませんでした: " + (tail_reason(err) or "音声トラックがない可能性があります"), 400)
    return full, band


def parse_chat(path, n, extra=None):
    """live_chat.json → (1秒ごとの活気, 件数, 「草」などの件数)。extra に辞書を渡すと、1秒ごとの warm(「草」等の件数)/ uniq(発言した人数)/ paid(スパチャ件数)を入れる(記録用)。"""
    act = [0.0] * n
    total = warm_total = 0
    warm_s, paid_s, uniq_s = [0] * n, [0] * n, {}
    with open(path, encoding="utf-8", errors="replace") as f:
        for line in f:
            try:
                d = json.loads(line)
            except ValueError:
                continue
            ra = d.get("replayChatItemAction")
            if not isinstance(ra, dict):
                continue
            try:
                t = int(ra.get("videoOffsetTimeMsec")) / 1000.0
            except (TypeError, ValueError):
                continue
            if t < 0 or t >= n:
                continue
            for a in ra.get("actions") or []:
                item = ((a.get("addChatItemAction") or {}).get("item")) or {}
                kind, r = next(iter(item.items()), (None, None)) if item else (None, None)
                if not isinstance(r, dict):
                    continue
                w, warm, paid = excite.message_weight(kind, excite.message_text(r))   # 重み(「草」+1.5・スパチャ +4)は配信中の検出と同じ 1 か所
                if w is None:
                    continue
                if warm:
                    warm_total += 1
                    warm_s[int(t)] += 1
                if paid:
                    paid_s[int(t)] += 1
                act[int(t)] += w
                total += 1
                au = r.get("authorExternalChannelId")
                if au:
                    uniq_s.setdefault(int(t), set()).add(au)
    if extra is not None:
        extra["warm"], extra["paid"] = warm_s, paid_s
        extra["uniq"] = [len(uniq_s.get(i, ())) for i in range(n)]
    return act, total, warm_total


def _levels(job, spec, src, wdir, warnings):
    """音量(全体・高音域)を 1 秒ごとに。YouTube は前回の結果があれば再利用する。-> (dur, n, full, band)。full・band は長さ n にそろえる"""
    sig = load_sig(src["videoId"]) if src["kind"] == "youtube" and not spec["noCache"] else None
    if sig:   # 前回の音量の解析結果を再利用(ダウンロードも ffmpeg も不要)
        dur, full, band = sig["dur"], sig["full"], sig["band"]
        n = int(math.ceil(dur))
        warnings.append("音量の解析は前回の結果を再利用しました(最初からやり直すには、詳しい設定の「キャッシュを使わない」をオン)")
    else:
        media = src["path"] if src["kind"] == "file" else fetch.download_audio(job, src["videoId"], wdir)
        dur, _v, has_audio, _l = _media.media_info(media)   # 長さと音声の有無を1回で(ffmpeg が無ければ dur が None になり、下で止まる)
        if not dur or dur < 20:
            raise ApiError("bad_media", "動画の長さを読み取れません(または短すぎます)")
        if dur > MAX_DURATION:
            raise ApiError("too_long", "長すぎます(この動画は %s。解析できるのは %d 時間まで)" % (fmt_ts(dur)[:8], MAX_DURATION // 3600))
        if not has_audio:
            raise ApiError("no_audio", "このファイルには音声トラックがありません(音声・チャット・コメントのどれも使えないため、解析できません)")
        n = int(math.ceil(dur))
        job["phase"] = "音量(全体と高音域 = 笑い声・叫び)を解析中"
        full, band = audio_levels(job, media, dur, wdir, 0.12, 0.48)
        full, band = [round(x, 1) for x in full], [round(x, 1) for x in band]   # 保存するのと同じ精度にそろえる(キャッシュの有無で結果が変わらないように)
        dur = round(dur, 2)
        if src["kind"] == "youtube":
            save_sig(src["videoId"], dur, full, band)
    full = (full + [full[-1]] * n)[:n]
    band = (band + [band[-1]] * n)[:n]
    return dur, n, full, band


def _chat_signal(job, spec, n, comps, info, warnings):
    """チャットの取得(start_chat で始めたもの)を待って解析し、30 件以上なら comps["chat"] に入れる。
    -> {"act", "count", "warm", "extra"}(archive に残す材料。取れなければ act は None)"""
    out = {"act": None, "count": 0, "warm": 0, "extra": None}
    c = job["chat"]
    while c["state"] == "running":
        if job["cancel"]:
            raise Cancelled()
        job["phase"], job["progress"] = "チャットのリプレイを取得中(音声の解析は完了、経過 %s)" % fmt_ms(time.time() - c["t0"]), 0.5
        c["thread"].join(0.3)
    path, why = c["path"], c["why"]
    if c["cached"] and path:
        warnings.append("チャットは先読みで取得済みでした" if c.get("prefetched") else "チャットは前回の取得分を再利用しました")
    if not path:
        warnings.append(why)
        return out
    job["phase"] = "チャットを解析中"
    out["extra"] = {}
    out["act"], out["count"], out["warm"] = parse_chat(path, n, out["extra"])
    if out["count"] < 30:
        warnings.append("チャットの件数が少ない(%d件)ため、チャットは使っていません" % out["count"])
        return out
    cz = chat_z(out["act"])
    used_lag = spec["lag"]
    if spec["lagAuto"] and "audio" in comps:
        est, r = estimate_lag(comps["audio"], cz)
        if est is not None:
            used_lag = est
            warnings.append("チャットの遅れを自動推定しました: %d秒(音量との一致度 %.2f。設定の値は使っていません)" % (est, r))
        else:
            warnings.append("チャットの遅れは自動推定できなかったため、設定の%d秒を使いました" % round(used_lag))
    spec["lagUsed"] = used_lag
    comps["chat"] = shift_chat(cz, used_lag)
    info["chat"] = True
    return out


def _comment_signal(job, src, dur, n, comps, info, warnings, ctexts):
    """コメント欄の時刻の書き込み → comps["comments"]。-> 書き込みの一覧(無ければ None)。ctexts に本文が並ぶ(archive 用)"""
    job["phase"], job["progress"] = "コメント欄のタイムスタンプを取得中", 0.56
    st, why = fetch.fetch_comments(src["videoId"], dur, ctexts)
    if st is None:
        warnings.append(why)
        return None
    if not st:
        warnings.append("コメント欄に、時刻の書き込みが見つかりませんでした")
        return None
    comps["comments"] = comment_score(st, n)
    info["comments"] = True
    return st


def _weights(job, spec, warnings):
    """材料の重みと、記録用の付加情報(start_meta で始めたもの)を待つ。-> (wts, meta)。配信タイプ別の倍率は 0.26.0 で廃止"""
    wts = {"audio": spec["wAudio"], "chat": spec["wChat"], "comments": spec["wComments"]}
    meta = None
    mj = job.get("meta")
    if mj:
        mj["thread"].join(fetch.META_TIMEOUT + 5)
        meta = mj["data"]
        if meta is None and mj["why"]:
            warnings.append("動画の付加情報(記録用)を取得できませんでした: %s(解析には影響しません)" % mj["why"])
    return wts, meta


def _save_record(src, spec, dur, n, levels, chat, stamps, ctexts, meta, info, cands):
    """後から実データで見直すための記録(save_archive)。levels = (full, band)・chat = _chat_signal の結果(使わなかったときは None)。失敗しても解析は続ける"""
    try:
        full, band = levels
        payload = {"kind": src["kind"], "duration": round(dur, 1), "n": n, "at": int(time.time() * 1000), "meta": meta,
                   "full": [round(x, 1) for x in full], "band": [round(x, 1) for x in band],
                   "chat": ({"act": [round(x, 1) for x in chat["act"]], "count": chat["count"], "warmCount": chat["warm"], **(chat["extra"] or {})} if chat else None),
                   "stamps": ([[t, lk, round(w, 3), (ctexts[i] if i < len(ctexts) else "")] for i, (t, lk, w) in enumerate(stamps)] if stamps else None)}
        run = {"at": payload["at"], "spec": {k: spec[k] for k in SPEC_KEYS},
               "lagUsed": spec.get("lagUsed"), "signals": info,
               "candidates": [{"start": c["start"], "end": c["end"], "peak": c["peak"], "score": c["score"], "parts": c["parts"]} for c in cands]}
        save_archive(src["videoId"], payload, run)
    except Exception:
        pass


def _stop_helpers(job, wdir, chat_vid):
    """後始末: 途中で失敗・中止したときに付加情報・チャットの取得を残さない。作業フォルダを消し、チャットのキャッシュの使用中を外す"""
    mj = job.get("meta")
    if mj and mj["thread"].is_alive():
        _procs.terminate(job.get("proc3"))
        mj["thread"].join(5)
    c = job.get("chat")
    if c and c["state"] == "running":
        c["skip"] = True
        _procs.terminate(job.get("proc2"))
        c["thread"].join(10)
    shutil.rmtree(wdir, ignore_errors=True)
    if chat_vid:
        fetch.use_chat_cache(chat_vid, -1)


def run_analyze(job):
    """解析の 1 ジョブ(裏のスレッド): 素材の取得(音声・チャット・付加情報は同時に)→ 材料ごとの点数 → 重み付きの合計 → 山を区間に。
    結果は job["result"]、状態は job["state"]・job["phase"]・job["progress"]"""
    spec = job["spec"]
    src = spec["source"]
    wdir = os.path.join(fetch.work_dir(), job["id"])
    chat_vid = src["videoId"] if src["kind"] == "youtube" and spec["useChat"] else None
    if chat_vid:
        fetch.use_chat_cache(chat_vid, +1)   # 解析が終わるまで、この動画のチャットのキャッシュを消させない
    try:
        os.makedirs(wdir, exist_ok=True)
        if job["cancel"]:
            raise Cancelled()
        warnings = []
        job["state"], job["phase"] = "running", "素材を取得中"
        if spec["useChat"]:
            fetch.start_chat(job, src["videoId"], wdir, spec["chatTimeout"] * 60)   # 音声の取得・解析と同時に始める
        if src["kind"] == "youtube":
            fetch.start_meta(job, src["videoId"])   # 動画の付加情報(記録用)も同時に取得する
        dur, n, full, band = _levels(job, spec, src, wdir, warnings)
        comps, info = {}, {"audio": False, "chat": False, "comments": False}
        if spec["useAudio"]:
            comps["audio"] = audio_score(full, band)
            info["audio"] = True
        chat = _chat_signal(job, spec, n, comps, info, warnings) if spec["useChat"] else {"act": None, "count": 0, "warm": 0, "extra": None}
        ctexts = []
        stamps = _comment_signal(job, src, dur, n, comps, info, warnings, ctexts) if spec["useComments"] else None
        if not comps:
            raise ApiError("no_signal", "使える材料がありません(音声の解析をオンにするか、チャット・コメントが取れる動画を指定してください)")
        job["phase"], job["progress"] = "盛り上がりの区間を決定中", 0.6
        wts, meta = _weights(job, spec, warnings)
        total = [sum(wts[k] * comps[k][i] for k in comps) for i in range(n)]
        total = head_ramp(total, spec["headSec"])   # 冒頭は誤検出が多いので、なだらかに減点
        # 材料が重なるほど合計が大きくなる(音声・チャット・コメントが同じ場面を指すと強い)
        cands = excite.candidates(pick_clips(total, full, spec, n), comps)   # 山の前後の材料ごとの点数(parts)と理由の文(配信中の候補と同じ式)
        _save_record(src, spec, dur, n, (full, band), chat if info["chat"] else None, stamps, ctexts, meta, info, cands)
        series = {"n": n, "step": max(1.0, n / 600), "total": downsample(total), **{k: downsample(v) for k, v in comps.items()}}
        if job["cancel"]:
            raise Cancelled()
        job["result"] = {"source": {**src, "duration": round(dur, 1)}, "candidates": cands, "series": series, "signals": info,
                         "counts": {"chat": chat["count"], "chatWarm": chat["warm"], "commentStamps": len(stamps) if stamps else 0, "meta": bool(meta), "heatmap": len((meta or {}).get("heatmap") or [])},
                         "warnings": warnings, "spec": dict({k: spec[k] for k in SPEC_KEYS}, lag=spec.get("lagUsed", spec["lag"]))}
        job["state"], job["phase"], job["progress"] = "done", "解析が完了しました", 1.0
    except Cancelled:
        job["state"], job["phase"] = "cancelled", "中止しました"
    except ApiError as e:
        job["state"], job["error"], job["phase"] = "error", e.message, "失敗"
    except PermissionError as e:
        _env.log_failure("動画解析", e)
        job["state"], job["error"], job["phase"] = "error", permission_message(e), "失敗"
    except Exception as e:
        _env.log_failure("動画解析", e)
        job["state"], job["error"], job["phase"] = "error", "内部エラー: %s %s" % (e.__class__.__name__, str(e)[:200]), "失敗"
    finally:
        _stop_helpers(job, wdir, chat_vid)
