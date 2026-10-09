# -*- coding: utf-8 -*-
"""「編集」のサーバーの部品: 元の配信の YouTube の字幕を、校正の候補に出す(案 A1。ユーザー承認 2026-10-05。2つ目のエンジンの候補 ed_alt と同じ形)。

ねらい: 校正を速くする。スタジオで書き出した切り抜き(文書の clip = youtube-tools-clip/v1 に配信の ID と範囲がある)なら、
元の配信に YouTube が付けた字幕(配信者が付けた字幕があればそれ、無ければ自動字幕)の同じ範囲を、今の行と比べ、
食い違う所を行の「候補」(tier = "yt"。札「YT」)として出す。人が 1 押しで採る。**自動では書き換えない**。
  POST /api/ytcap {id}   ジョブ(kind "ytcap")を足す。配信の字幕を取り(配信ごとに作業データの ytcaps/<videoId>.json に置いて使い回す)、
                         文書の範囲を切り出して transcripts/<id>.ytcap.json に書く
  GET  /api/suggest?id=  学習の提案・alt の候補に yt の候補を足す(ed_learn.suggest_for_doc → ytcap_suggest)

決まり:
  - 取得は yt-dlp で**字幕だけ**(--skip-download。動画・音声は取らない)。こちらからは配信の ID を問い合わせるだけで、動画・音声を外へ送らない。
    yt-dlp の設定ファイル・クッキーは使わない(--ignore-config・--no-cookies)= 誰でも見られる配信だけ。非公開・限定公開・メンバー限定は断る
  - 配信の ID は 11 文字の決まった形だけ(スタジオの VID_RE と同じ)。URL は ID から自分で作る(文書の中の URL をそのまま渡さない)
  - **候補にだけ使う**。正解・学習・辞書の材料にしない。評価用の文書には出さない(ed_alt の評価用を断る決まりと同じ)
  - 文書(<id>.json)は書き換えない・updatedAt を動かさないので、編集を止めるジョブにしない
  - 比べ方は ed_alt の alt_diffs をそのまま使う(二重に書かない)。切り抜きの頭と終わりの食い違いは出さない(字幕の時刻で切るので、境目の言葉がずれる)

名前は serve.py からも見える(serve.py の _ED_MODULES の最後。ほかの部品と重ならないよう、名前は ytcap_ / YTCAP_ / _ytcap_ で始める)。
ほかの部品の名前は `ed_xxx.名前` の形で呼ぶたびに読む(差し替えが効くように。from … import はしない)。
"""
import json
import os
import re
import shutil
import subprocess
import sys
import threading
import time

import ed_alt  # noqa: E402,F401
import ed_jobs  # noqa: E402,F401
import ed_relink  # noqa: E402,F401
import ed_state  # noqa: E402,F401
from ytt import workdata as _workdata  # noqa: E402   (置き場所と版の今の値。RS3-0A に ed_state から移した)
import ed_store  # noqa: E402,F401
from ytt import fsio as _fsio, schemas as _yschemas, tools as _tools  # noqa: E402

YTCAP_SCHEMA = "youtube-tools-ytcap/v1"            # transcripts/<id>.ytcap.json(文書の範囲に切り出した字幕。形は alt.json に合わせる)
YTCAP_VIDEO_SCHEMA = "youtube-tools-ytcap-video/v1"   # ytcaps/<videoId>.json(配信 1 本ぶんの字幕。使い回す)
YTCAP_VID_RE = re.compile(r"^[\w-]{11}\Z", re.ASCII)   # 配信の ID(studio/common.py の VID_RE と同じ。ASCII のみ・末尾の改行も不可)
YTCAP_DIR = None                       # 配信ごとの字幕の置き場所。None = 作業データの ytcaps/(テストは差し替える)
YTCAP_TTL_SEC = 30 * 86400             # 取った字幕はこの間は取り直さない(同じ配信の別の切り抜きでも使い回す)
YTCAP_NONE_TTL_SEC = 86400             # 「字幕が無い」もこの間は覚える(自動字幕はアーカイブのあとしばらくして付くことがある)
YTCAP_TIMEOUT_SEC = 180                # yt-dlp の時間の上限
YTCAP_MAX_JSON3_BYTES = 64 * 1024 * 1024
YTCAP_MAX_CACHE_BYTES = 48 * 1024 * 1024
YTCAP_MAX_PIECES = 500000              # 1 本の配信の言葉の数の上限(十数時間の配信でも収まる)
YTCAP_MAX_FILES = 400                  # ytcaps/ に置く配信の数(超えたら古いものから消す)
YTCAP_MAX_BYTES = 32 * 1024 * 1024     # <id>.ytcap.json の上限
YTCAP_SEC_PER_CHAR = 0.2               # 言葉の時刻が無い字幕の、1 文字の長さの目安(切り抜きの境目で文字を割り振るため)
YTCAP_MIN_PIECE_SEC = 0.3              # 字幕の最後の言葉の長さの最小(次の字幕の始まりまで)
YTCAP_MANUAL_LANGS = ("ja", "ja-JP")   # 配信者が付けた字幕(優先)
YTCAP_AUTO_LANG = "ja-orig"            # 自動字幕(元の言葉が日本語のときだけある。"ja" の自動字幕は別の言葉からの翻訳のことがあるので使わない)
YTCAP_NOT_PUBLIC = {"private": "非公開", "unlisted": "限定公開", "premium_only": "有料", "subscriber_only": "メンバー限定", "needs_auth": "ログインが要る"}
YTCAP_MAX_ITEMS = 1000
YTCAP_KIND_LABELS = {"manual": "YouTube の字幕(配信者が付けたもの)", "auto": "YouTube の自動字幕"}
_YTCAP_NOTE_RE = re.compile(r"[\[［][^\]］]{0,20}[\]］]")   # [音楽] [拍手] などの音の説明(言葉ではない)
# 言いよどみ(フィラー)だけの違い。YouTube の自動字幕は「え、」「あの、」「おお。」まで書き、主のエンジン(Whisper)と人の最終は落とすことが多い
# (2026-10-05 に本物の 8 本で、yt の候補の外れの多くがこれだった)。句読点で区切って足した所が、比べる文字(alt_fold のあと = ひらがな・伸ばしなし)でこれだけなら出さない
_YTCAP_SEP_RE = re.compile(r"[、。,.?？!！]")
YTCAP_FILLER_RE = re.compile(r"^(?:えっと|あのう|あの|ええ|ああ|おお|うう|うん|まあ|ほう|ふん|はあ|うわ|わあ|へえ|ほお|[えあおうんま]っ?)+\Z")


# ---------- 文書 → 配信の ID と範囲 ----------
def ytcap_doc_range(doc):
    """文書の元の配信と、文書の範囲を配信の時刻に直したもの → {videoId, offset, a, b, docStart, docEnd}。
    文書の行の時刻 t(切り抜きの動画の先頭 = 0 秒)は、配信では offset + t(offset = clip の export.actualStart → range.start。ytt_core.schemas.clip_offset)。
    使えない(clip が無い・壊れている・YouTube の配信でない・ID の形が違う)ときは ApiError no_clip"""
    clip = doc.get("clip") if isinstance(doc, dict) else None
    if not isinstance(clip, dict):
        raise ed_state.ApiError("no_clip", "元の配信が分からない文書です(スタジオで書き出した切り抜きだけ、YouTube の字幕と比べられます)", 400)
    c, why = _yschemas.validate_clip(clip)
    if c is None:
        raise ed_state.ApiError("no_clip", "元の配信の情報が読めません。スタジオで書き出し直すと直ります", 400, {"detail": ".clip.json: %s" % why})   # 内部の名前は detail(S12)
    src = c.get("source") if isinstance(c.get("source"), dict) else {}
    if src.get("kind") != "youtube":
        raise ed_state.ApiError("no_clip", "元の動画が YouTube の配信ではありません(手元のファイル・リアルタイム切り抜きは、YouTube の字幕と時刻が合いません)", 400)
    vid = str(src.get("videoId") or "")
    if not YTCAP_VID_RE.match(vid):
        raise ed_state.ApiError("no_clip", "元の配信の ID の形が正しくありません", 400)
    off = float(_yschemas.clip_offset(c))
    ds = max(0.0, ed_state.num(doc.get("start"), 0.0) or 0.0)
    de = ed_state.num(doc.get("end"))
    if de is None:   # 文書が動画の最後まで: 切り抜きの長さ(元の配信の範囲)
        de = float(c["range"]["end"]) - off
        md = ed_state.num((c.get("media") or {}).get("durationSec")) if isinstance(c.get("media"), dict) else None
        if de <= ds and md:
            de = md
    if de <= ds:
        raise ed_state.ApiError("no_clip", "元の配信の範囲が正しくありません", 400)
    return {"videoId": vid, "offset": round(off, 3), "a": round(off + ds, 3), "b": round(off + de, 3), "docStart": round(ds, 3), "docEnd": round(de, 3)}


# ---------- ジョブの指定 ----------
def ytcap_info():
    """/api/tools の ytcap: yt-dlp が使えるか(画面のボタンの理由)"""
    try:
        ytcap_command()
        return {"ready": True, "why": ""}
    except ed_state.ApiError as e:
        return {"ready": False, "why": e.message}


def ytcap_spec(tid, req=None):
    """YouTube の字幕を取って比べるジョブの指定。断る: 評価用・文字の無い文書・元の配信が分からない・同じ文書で実行中"""
    tid = str(tid or "")
    doc = ed_store.read_transcript(tid)
    if doc.get("evalSet") is True:
        raise ed_state.ApiError("eval_set", "評価用の文字起こしには、YouTube の字幕の候補を出しません(定点の正解が字幕に寄らないように)", 400)
    src = doc.get("sourcePath")
    if src and ed_relink.in_eval_dir(os.path.abspath(str(src))):   # 印が無くても評価用のフォルダの動画は評価用(文字起こしと同じ扱い)
        raise ed_state.ApiError("eval_set", "評価用のフォルダの動画には、YouTube の字幕の候補を出しません", 400)
    if not ed_store.doc_has_rows(doc):
        raise ed_state.ApiError("empty", "文字の無い文書です(先に文字起こしをしてください)", 400)
    rng = ytcap_doc_range(doc)
    if ed_jobs.tid_busy(tid, ("ytcap",)):
        raise ed_state.ApiError("busy", "この文書は、もう YouTube の字幕を取っている最中です", 409)
    return dict(rng, tid=tid, title="YouTube の字幕と比べる: " + (str(doc.get("title") or "") or "無題")[:100])


def ytcap_after_transcribe(job, spec, tid):
    """文字起こしのジョブ(run_job)が終わったあと: 設定 autoYtcap がオンで評価用でなければ、ytcap のジョブを足す。
    元の配信が分からない文書・評価用は黙って飛ばす。失敗しても文字起こしの結果には影響しない"""
    if not spec.get("autoYtcap") or spec.get("evalSet"):
        return
    try:
        ed_jobs.add_job(ytcap_spec(tid, {}), "ytcap")
    except ed_state.ApiError as e:
        if e.code not in ("no_clip", "eval_set"):
            ed_state.add_warning(job, "YouTube の字幕を取るのを始められませんでした: " + e.message)
    except Exception as e:   # 想定外でも、書き終えた文字起こしのジョブを失敗にしない
        ed_state.log.warning("YouTube の字幕を取るのを始められませんでした: %s %s", tid, e)


# ---------- yt-dlp で字幕を取る ----------
def ytcap_command():
    """yt-dlp を動かすコマンドの先頭。場所はスタジオと同じ決め方(環境変数 TRANSCRIBE_YTDLP → PATH。ytt_core.tools.find_tool)。
    TRANSCRIBE_YTDLP が .py なら、この Python で動かす(テストの偽の yt-dlp)"""
    p = _tools.find_tool("yt-dlp", "TRANSCRIBE_YTDLP")
    if not p:
        raise ed_state.ApiError("no_ytdlp", "yt-dlp が見つかりません(README の準備手順を確認してください)", 400)
    return [sys.executable, p] if p.lower().endswith(".py") else [p]


def ytcap_classify(err, rc):
    """yt-dlp の失敗 → ApiError(理由を分ける)。err = 標準エラーの終わりの方"""
    t = str(err or "")
    low = t.lower()
    if "private video" in low:
        return ed_state.ApiError("not_public", "非公開の配信です(公開の配信だけ、字幕を取れます)", 400)
    if "members-only" in low or "members only" in low or "join this channel" in low:
        return ed_state.ApiError("not_public", "メンバー限定の配信です(公開の配信だけ、字幕を取れます)", 400)
    if "confirm you" in low and "bot" in low:
        return ed_state.ApiError("bot_check", "YouTube にボットの確認を求められました。しばらく時間をおいてから、もう一度試してください", 503)
    if "confirm your age" in low or "age-restricted" in low or "age restricted" in low:
        return ed_state.ApiError("not_public", "年齢制限のある配信です(ログインが要るため、字幕を取れません)", 400)
    if "http error 429" in low or "too many requests" in low:
        return ed_state.ApiError("too_many", "YouTube から「要求が多すぎる」と断られました。しばらく時間をおいてから、もう一度試してください", 503)
    if "video unavailable" in low or "has been removed" in low or "no longer available" in low or "not available" in low or "does not exist" in low:
        return ed_state.ApiError("unavailable", "配信が見つかりません(削除・非公開になった可能性があります)", 404)
    if "will begin" in low or "premieres in" in low or "is live" in low:
        return ed_state.ApiError("live", "配信中・配信予定の動画です(アーカイブになってから取ってください)", 400)
    line = next((l.strip() for l in reversed(t.splitlines()) if l.strip().startswith("ERROR")), "") or next((l.strip() for l in reversed(t.splitlines()) if l.strip()), "")
    return ed_state.ApiError("fetch_failed", "YouTube の字幕を取れませんでした" + (": " + line[:200] if line else "(終了コード %s)" % rc), 502)


def _ytcap_run(job, cmd, work):
    """yt-dlp を動かす(取り消し・時間の上限)。→ (終了コード, 標準出力, 標準エラーの終わり)"""
    out_p, err_p = os.path.join(work, "stdout.txt"), os.path.join(work, "stderr.txt")
    with open(out_p, "wb") as fo, open(err_p, "wb") as fe:
        # 窓を出さない・画面の操作が先に CPU を取る(「通常より下」の優先度)
        proc = subprocess.Popen(cmd, stdin=subprocess.DEVNULL, stdout=fo, stderr=fe, cwd=work, creationflags=_tools.no_window_flags(priority="low"))
        job["proc"] = proc   # cancel_job が止める(yt-dlp の exe は中で子のプロセスを起こすので、下で子ごと止める = tools.kill_tree)
        t0 = time.monotonic()
        try:
            while proc.poll() is None:
                if job.get("cancel"):
                    _tools.kill_tree(proc)
                    raise ed_jobs.Cancelled()
                if time.monotonic() - t0 > YTCAP_TIMEOUT_SEC:
                    _tools.kill_tree(proc)
                    raise ed_state.ApiError("timeout", "YouTube の字幕の取得が %d 秒を超えたのでやめました。しばらく時間をおいてから、もう一度試してください" % YTCAP_TIMEOUT_SEC, 504)
                time.sleep(0.2)
        finally:
            job["proc"] = None
    with open(out_p, "rb") as f:
        out = f.read(4 * 1024 * 1024).decode("utf-8", "replace")
    with open(err_p, "rb") as f:
        f.seek(0, 2)
        f.seek(max(0, f.tell() - 16000))
        err = f.read().decode("utf-8", "replace")
    if job.get("cancel"):
        raise ed_jobs.Cancelled()
    return proc.returncode, out, err


def ytcap_parse_print(out):
    """--print の行(YTCAP<TAB>公開の範囲<TAB>配信の状態<TAB>手で作った字幕の言語の JSON)→ (availability, live_status, 手の字幕の言語の集合) か None"""
    for line in str(out or "").splitlines():
        if line.startswith("YTCAP\t"):
            parts = line.split("\t", 3)
            if len(parts) < 4:
                return None
            try:
                subs = json.loads(parts[3]) if parts[3] not in ("", "NA") else {}
            except ValueError:
                subs = {}
            return parts[1], parts[2], set(subs) if isinstance(subs, dict) else set()
    return None


def ytcap_fetch(job, vid):
    """配信 1 本の字幕を yt-dlp で取る → 字幕の記録(YTCAP_VIDEO_SCHEMA。kind = manual / auto / none)。失敗は ApiError(覚えない)"""
    if not YTCAP_VID_RE.match(str(vid or "")):   # 引数に入るので、形を確かめてから(呼ぶ側でも確かめている)
        raise ed_state.ApiError("no_clip", "元の配信の ID の形が正しくありません", 400)
    cmd0 = ytcap_command()
    work = os.path.join(_workdata.TMP_DIR, job["id"] + "-ytcap")
    shutil.rmtree(work, ignore_errors=True)
    os.makedirs(work, exist_ok=True)
    try:
        langs = ",".join(YTCAP_MANUAL_LANGS + (YTCAP_AUTO_LANG,))
        cmd = cmd0 + ["--ignore-config", "--no-cookies", "--no-cookies-from-browser", "--no-playlist", "--no-warnings", "--no-progress",
                      "--skip-download", "--no-simulate", "--write-subs", "--write-auto-subs", "--sub-langs", langs, "--sub-format", "json3",
                      "--socket-timeout", "30", "--print", "YTCAP\t%(availability)s\t%(live_status)s\t%(subtitles)j",
                      "-o", os.path.join(work.replace("%", "%%"), "cap.%(ext)s"),   # 出力の名前は % 書式なので、フォルダの % は %%
                      "--", "https://www.youtube.com/watch?v=" + vid]   # URL は検査した ID から作る(文書の中の URL は使わない)
        job["phase"] = "YouTube の字幕を取得中"
        rc, out, err = _ytcap_run(job, cmd, work)
        info = ytcap_parse_print(out)
        avail, live, manual = info if info else ("", "", set())
        if avail in YTCAP_NOT_PUBLIC:
            raise ed_state.ApiError("not_public", "%sの配信です(公開の配信だけ、字幕を取れます)" % YTCAP_NOT_PUBLIC[avail], 400)
        if live in ("is_live", "is_upcoming"):
            raise ed_state.ApiError("live", "配信中・配信予定の動画です(アーカイブになってから取ってください)", 400)
        pick = None
        for lang in YTCAP_MANUAL_LANGS:   # 配信者が付けた字幕を優先
            p = os.path.join(work, "cap.%s.json3" % lang)
            if lang in manual and os.path.isfile(p):
                pick = ("manual", lang, p)
                break
        if pick is None and os.path.isfile(os.path.join(work, "cap.%s.json3" % YTCAP_AUTO_LANG)):
            pick = ("auto", YTCAP_AUTO_LANG, os.path.join(work, "cap.%s.json3" % YTCAP_AUTO_LANG))
        now = ed_state.now_ms()
        if pick is None:
            if rc != 0 or info is None:   # 取れなかった(非公開・削除・ボットの確認など)
                raise ytcap_classify(err, rc)
            return {"schema": YTCAP_VIDEO_SCHEMA, "videoId": vid, "kind": "none", "lang": "", "at": now, "availability": avail, "cues": []}
        if os.path.getsize(pick[2]) > YTCAP_MAX_JSON3_BYTES:
            raise ed_state.ApiError("too_big", "字幕のファイルが大きすぎます", 400)
        try:
            raw = _fsio.read_json_file(pick[2], YTCAP_MAX_JSON3_BYTES)
        except (OSError, UnicodeError, ValueError) as e:
            raise ed_state.ApiError("fetch_failed", "YouTube の字幕を読めませんでした(%s)" % e.__class__.__name__, 502)
        cues = ytcap_parse_json3(raw)
        return {"schema": YTCAP_VIDEO_SCHEMA, "videoId": vid, "kind": pick[0], "lang": pick[1], "at": now, "availability": avail, "cues": cues}
    finally:
        shutil.rmtree(work, ignore_errors=True)


def ytcap_parse_json3(obj):
    """YouTube の json3 → 字幕(cue)の並び [[[開始ミリ秒, 終了ミリ秒, 文字], …], …](時刻は配信の先頭から)。
    自動字幕は言葉ごとの時刻(segs の tOffsetMs)がある。終わりは同じ字幕の次の言葉・最後の言葉は次の字幕の始まりまで(長さの目安で上限)。
    改行だけの行(aAppend)・[音楽] などの音の説明は捨てる"""
    evs = obj.get("events") if isinstance(obj, dict) else None
    items = []
    for e in evs if isinstance(evs, list) else []:
        if not isinstance(e, dict) or not isinstance(e.get("segs"), list):
            continue
        t0 = ed_state.num(e.get("tStartMs"))
        if t0 is None or t0 < 0:
            continue
        ws = []
        for s in e["segs"]:
            if not isinstance(s, dict) or not isinstance(s.get("utf8"), str):
                continue
            txt = _YTCAP_NOTE_RE.sub("", s["utf8"].replace("\n", " "))
            off = ed_state.num(s.get("tOffsetMs"), 0.0) or 0.0
            if txt.strip():
                ws.append([int(t0 + max(0.0, off)), txt])
        if ws:
            items.append((int(t0), ws))
    items.sort(key=lambda x: x[0])
    cues, total = [], 0
    for k, (_t0, ws) in enumerate(items):
        nxt = items[k + 1][0] if k + 1 < len(items) else None
        ws.sort(key=lambda w: w[0])
        cue = []
        for j, (t, txt) in enumerate(ws):
            if j + 1 < len(ws):
                e = ws[j + 1][0]
            else:
                e = t + int(max(YTCAP_MIN_PIECE_SEC, len(txt.strip()) * YTCAP_SEC_PER_CHAR) * 1000)   # 表示の長さ dDurationMs は話した長さと合わないので使わない
                if nxt is not None and nxt > t:
                    e = min(e, nxt)
            cue.append([t, max(t + 1, e), txt])
        cues.append(cue)
        total += len(cue)
        if total > YTCAP_MAX_PIECES:
            raise ed_state.ApiError("too_big", "字幕が長すぎます(言葉が %d を超えました)" % YTCAP_MAX_PIECES, 400)
    return cues


# ---------- 配信ごとの字幕の置き場所(使い回す) ----------
def ytcap_dir():
    return YTCAP_DIR or os.path.join(_workdata.DATA_DIR, "ytcaps")


def ytcap_video_path(vid):
    if not YTCAP_VID_RE.match(str(vid or "")):   # ファイル名に使うので、決まった形だけ
        raise ed_state.ApiError("no_clip", "元の配信の ID の形が正しくありません", 400)
    return os.path.join(ytcap_dir(), vid + ".json")


def ytcap_valid_cache(d, vid=None):
    """配信ごとの字幕の記録として使える形か(測る道具 dev/eval_alt.py も使う)"""
    return (isinstance(d, dict) and d.get("schema") == YTCAP_VIDEO_SCHEMA and d.get("kind") in ("manual", "auto", "none")
            and isinstance(d.get("cues"), list) and isinstance(d.get("at"), (int, float)) and (vid is None or d.get("videoId") == vid))


def ytcap_load(vid):
    """ytcaps/<videoId>.json(形が違えば None)"""
    try:
        d = _fsio.read_json_file(ytcap_video_path(vid), YTCAP_MAX_CACHE_BYTES)
    except (OSError, UnicodeError, ValueError, ed_state.ApiError):
        return None
    return d if ytcap_valid_cache(d, vid) else None


def ytcap_fresh(d, now_ms=None):
    """取り直さなくてよいか(字幕は 30 日・「字幕が無い」は 1 日)"""
    now_ms = ed_state.now_ms() if now_ms is None else now_ms
    ttl = YTCAP_NONE_TTL_SEC if d.get("kind") == "none" else YTCAP_TTL_SEC
    return 0 <= now_ms - d["at"] < ttl * 1000


def _ytcap_prune():
    """ytcaps/ が YTCAP_MAX_FILES を超えたら、古い(更新日時の)ものから消す"""
    try:
        fs = [os.path.join(ytcap_dir(), n) for n in os.listdir(ytcap_dir()) if n.endswith(".json")]
        if len(fs) <= YTCAP_MAX_FILES:
            return
        fs.sort(key=lambda p: os.path.getmtime(p))
        for p in fs[:len(fs) - YTCAP_MAX_FILES]:
            os.unlink(p)
    except OSError:
        pass


_ytcap_vid_locks = {}
_ytcap_vid_locks_lock = threading.Lock()


def ytcap_get(job, vid):
    """配信の字幕(使い回し → 無い・古ければ取る)。同じ配信を同時に 2 回取らない。字幕が無ければ ApiError no_captions"""
    with _ytcap_vid_locks_lock:
        lk = _ytcap_vid_locks.setdefault(vid, threading.Lock())
    with lk:
        d = ytcap_load(vid)
        if d and ytcap_fresh(d):
            job["ytcapReused"] = True
        else:
            d = ytcap_fetch(job, vid)
            data = json.dumps(d, ensure_ascii=False, separators=(",", ":")).encode("utf-8")
            if len(data) > YTCAP_MAX_CACHE_BYTES:
                raise ed_state.ApiError("too_big", "字幕が大きすぎます", 400)
            os.makedirs(ytcap_dir(), exist_ok=True)
            ed_state.atomic_write(ytcap_video_path(vid), data)
            _ytcap_prune()
    if d["kind"] == "none":
        raise ed_state.ApiError("no_captions", "この配信には日本語の字幕がありません(配信者が付けた字幕も、自動字幕も無い)", 400)
    return d


# ---------- 文書の範囲に切り出す(純粋な関数) ----------
def ytcap_cut(cues, a, b, offset):
    """字幕(配信の時刻)から [a, b) 秒の所を切り出し、文書の時刻(配信の時刻 − offset)の行 [{start, end, text}] にする。
    言葉は文字ごとに時刻を割り振り(言葉の長さを字数で等分)、真ん中の時刻が範囲の中の文字だけを残す。1 つの字幕 = 1 行"""
    a_ms, b_ms = a * 1000.0, b * 1000.0
    rows = []
    for cue in cues or []:
        if not isinstance(cue, list) or not cue:
            continue
        try:
            if cue[-1][1] <= a_ms or cue[0][0] >= b_ms:
                continue
        except (TypeError, IndexError):
            continue
        txt, t_first, t_last = [], None, None
        for w in cue:
            if not (isinstance(w, list) and len(w) == 3 and isinstance(w[2], str)):
                continue
            t, e, s = float(w[0]), float(w[1]), w[2]
            n = len(s)
            if not n:
                continue
            step = max(0.0, e - t) / n
            for i, ch in enumerate(s):
                c0 = t + i * step
                if a_ms <= c0 + step / 2 < b_ms:
                    txt.append(ch)
                    t_first = c0 if t_first is None else t_first
                    t_last = c0 + step
        text = "".join(txt).strip()
        if text and t_first is not None:
            rows.append({"start": round(t_first / 1000.0 - offset, 2), "end": round(max(t_last, t_first + 1) / 1000.0 - offset, 2), "text": text[:ed_state.MAX_TEXT]})
    rows.sort(key=lambda r: r["start"])
    return rows


def ytcap_doc_rows(doc, cache):
    """文書と配信の字幕の記録 → (文書の時刻の行, 範囲 ytcap_doc_range)。測る道具も使う(読むだけ)"""
    rng = ytcap_doc_range(doc)
    return ytcap_cut(cache.get("cues") or [], rng["a"], rng["b"], rng["offset"]), rng


def ytcap_filler_only(wrong, right):
    """YouTube の字幕が、句読点で区切った言いよどみを足しただけの候補か(例: 「よ」→「よ。あの」・「て」→「て。え」)。
    句読点の無い 1 文字の足し(「す」→「ます」・「なで」→「なんで」)は本当の直しのことがあるので、言いよどみにしない"""
    if right.startswith(wrong):
        extra = right[len(wrong):]
    elif right.endswith(wrong):
        extra = right[:len(right) - len(wrong)]
    else:
        return False
    return bool(_YTCAP_SEP_RE.search(extra)) and bool(YTCAP_FILLER_RE.match(ed_alt.alt_fold(extra)))


def ytcap_diffs(rows, yt_rows):
    """今の行と YouTube の字幕の食い違い → (候補 [{… tier: "yt"}], 数えた理由)。比べ方は ed_alt.alt_diffs そのまま(二重に書かない)。
    加えて、切り抜きの頭と終わりの食い違い(最初の行の頭・最後の行の終わりにかかる候補)は出さない(clipEdge。字幕の時刻で切るので、境目の言葉がずれる)。
    言いよどみだけを足す・消す候補も出さない(filler。YTCAP_FILLER_RE)"""
    items, stats = ed_alt.alt_diffs(rows, yt_rows)
    stats = dict(stats, clipEdge=0, filler=0)
    texts = [g for g in rows or [] if isinstance(g, dict) and str(g.get("text") or "").strip() and ed_state.num(g.get("start")) is not None]
    if not texts:
        return [], stats
    first = min(texts, key=lambda g: ed_state.num(g.get("start")))
    last = max(texts, key=lambda g: (ed_state.num(g.get("end"), 0.0) or 0.0, ed_state.num(g.get("start"))))
    out = []
    for x in items:
        if first.get("id") == x["seg"] and not ed_alt.alt_fold(str(first["text"])[:x["i"]]):
            stats["clipEdge"] += 1
            continue
        if last.get("id") == x["seg"] and not ed_alt.alt_fold(str(last["text"])[x["i"] + len(x["wrong"]):]):
            stats["clipEdge"] += 1
            continue
        if ytcap_filler_only(x["wrong"], x["right"]):
            stats["filler"] += 1
            continue
        out.append(dict(x, tier="yt"))
    return out, stats


# ---------- ジョブ ----------
def ytcap_path(tid):
    return os.path.join(_workdata.TX_DIR, tid + ".ytcap.json")


def read_ytcap(tid):
    """<id>.ytcap.json(形が違えば None)"""
    if not ed_state.TID_RE.match(str(tid or "")):
        return None
    return ed_state.read_schema_json(ytcap_path(tid), YTCAP_MAX_BYTES, YTCAP_SCHEMA, "rows")


def run_ytcap(job):
    """配信の字幕を取り(使い回し)、文書の範囲を切り出して <id>.ytcap.json に書く。文書は書き換えない(updatedAt も動かさない)"""
    spec = job["spec"]
    tid = spec["tid"]
    with ed_jobs.job_errors(job, log="YouTube の字幕の取得で例外"):
        job["state"], job["phase"] = "running", "YouTube の字幕を確かめ中"
        cache = ytcap_get(job, spec["videoId"])
        if job["cancel"]:
            raise ed_jobs.Cancelled()
        with ed_store._save_lock:   # 取る間に文書が消えていたら書かない(削除と同じロック。消したあとに付き物だけが生き返らないように)
            if not os.path.isfile(ed_store.tx_path(tid)):
                raise ed_state.ApiError("not_found", "字幕を取る間に文書が消されました", 404)
            doc = ed_store.read_transcript(tid)
            rows, rng = ytcap_doc_rows(doc, cache)   # 取る間に文書の範囲が変わっていても、今の範囲で切る
            body = {"schema": YTCAP_SCHEMA, "id": tid, "source": "youtube", "kind": cache["kind"], "lang": cache.get("lang", ""), "videoId": rng["videoId"],
                    "at": ed_state.now_ms(), "fetchedAt": cache["at"], "offset": rng["offset"], "streamRange": [rng["a"], rng["b"]],
                    "range": [rng["docStart"], rng["docEnd"]], "rows": rows}
            ed_state.atomic_write(ytcap_path(tid), json.dumps(body, ensure_ascii=False, separators=(",", ":")).encode("utf-8"))
        with _ytcap_cache_lock:
            _ytcap_cache.pop(tid, None)
        job["segments"] = len(rows)
        ed_jobs.job_done(job, tid, "完了(%s・%d 行%s)" % ("配信者の字幕" if cache["kind"] == "manual" else "自動字幕", len(rows), "・取ってあった字幕" if job.get("ytcapReused") else ""))


# ---------- 提案(GET /api/suggest)に足す ----------
_ytcap_cache = {}   # tid -> (鍵, (候補, 数えた理由))
_ytcap_cache_lock = threading.Lock()


def ytcap_suggest(tid, doc, dismissed, taken, alt_items):
    """文書への yt の候補 → (候補, 情報 {kind, lang, videoId, at, fetchedAt, count, agree, skipped} か None)。
    評価用・ytcap.json が無い文書は ([], None)。却下した候補(dismissed = {"seg|誤=>正"})・学習の提案(taken)と重なる位置は出さない。
    2つ目のエンジンの候補(alt_items)と同じ行・同じ位置・同じ直しなら、yt を足さずに alt の項目に also: ["yt"] を付ける(2 つが一致 = 札「別・YT」)。
    同じ位置で違う直しなら alt を優先(yt は出さない)"""
    if doc.get("evalSet") is True:
        return [], None
    stamp = ed_state.file_stamp(ytcap_path(tid))
    if stamp is None:
        return [], None
    yt = read_ytcap(tid)
    if not yt:
        return [], None
    items, stats = ed_alt.alt_cached(_ytcap_cache, _ytcap_cache_lock, tid, (stamp, doc.get("updatedAt"), len(doc.get("segments") or [])),
                                     lambda: ytcap_diffs(doc.get("segments") or [], yt.get("rows") or []))
    spans = ed_alt.alt_spans_of(taken)
    alts = {}
    for x in alt_items:
        alts.setdefault(x.get("seg"), []).append(x)
    out, agree = [], 0
    for x in items:
        if ed_alt.alt_skip(x, dismissed, spans):
            continue   # 却下した・学習の提案を優先
        same = next((y for y in alts.get(x["seg"], []) if y["i"] == x["i"] and y["wrong"] == x["wrong"] and y["right"] == x["right"]), None)
        if same is not None:   # 2つ目のエンジンと一致: 1 つにまとめ、両方の札を出す
            same["also"] = sorted(set(same.get("also") or []) | {"yt"})
            agree += 1
            continue
        if any(x["i"] < y["i"] + len(y["wrong"]) and y["i"] < x["i"] + len(x["wrong"]) for y in alts.get(x["seg"], [])):
            continue   # 同じ位置で違う直し: 2つ目のエンジンを優先
        out.append(dict(x))
        if len(out) >= YTCAP_MAX_ITEMS:
            break
    info = {"kind": str(yt.get("kind") or ""), "lang": str(yt.get("lang") or ""), "videoId": str(yt.get("videoId") or ""), "at": yt.get("at"),
            "fetchedAt": yt.get("fetchedAt"), "label": YTCAP_KIND_LABELS.get(yt.get("kind"), "YouTube の字幕"), "count": len(out) + agree, "agree": agree, "skipped": stats}
    return out, info
