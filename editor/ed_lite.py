# -*- coding: utf-8 -*-
"""「編集」のサーバーの部品: 友人用 文字起こし簡易版(lite)。画面は lite.html・lite.js。計画は docs/plan/friend-lite-plan.md、
設計の正本は .design/friend-transcribe-lite/DESIGN_BRIEF.md。

文字起こし・保存・競合・履歴は「編集」と同じ部品(ed_jobs・ed_store)をそのまま使う。ここにあるのは簡易版だけのもの:
  - 状態(配信者の候補・話者の色の候補と保存した組み合わせ・続きの作業)と設定(作業者の名前)
  - 動画の受け取り(ドロップ = アップロード。ブラウザはドロップしたファイルの場所を教えないため)と長さの確認
  - 文字起こしの開始(簡易版の決まった設定)と、できた文書に付ける印(doc["lite"])と既定の話者
  - 作業の記録(<id>.lite-edits.jsonl。分割・結合・時刻・確定と、確定の前に再生したか)
  - 書き出し: Resolve 用ファイル(cut2resolve の pack。カットなし・字幕の型 lite・記号を除いた字幕)と送る用 zip(ytt_core/evaldata の形式)を1回で
名前は serve.py からも見える(serve.py が受け付けて、この部品へ転送する)。ほかの部品は `ed_xxx.名前` で呼ぶたびに読む。
"""
import json
import os
import re
import shutil
import subprocess
import tempfile
import threading
import time
import uuid
import zipfile
from pathlib import Path

from ytt_core import evaldata as _ev, fsio as _fsio, jobs as _heavy  # noqa: E402,F401
import ed_jobs  # noqa: E402,F401
import ed_state  # noqa: E402,F401
import ed_store  # noqa: E402,F401

LITE_MODEL = "large-v3-turbo"   # 3060 の 8GB に int8_float16 で収まり、large-v3 に近い精度で速い(計画の 2)。テストは環境変数 LITE_MODEL
COLORS_FILE = os.path.join(ed_state.ROOT, "lite-colors.json")
FALLBACK_COLORS = {"text": [{"name": "黄", "hex": "#FFE600"}, {"name": "白", "hex": "#FFFFFF"}], "outline": [{"name": "黒", "hex": "#000000"}]}
PACK_DIR_NAME, SEND_DIR_NAME = "Resolve用ファイル", "送る用ファイル"
README_NAME = "Resolveでの手順.txt"
TARGET_FPS = "30"               # Resolve のプロジェクトの fps(固定。60fps の動画でも 30fps のプロジェクトに置く。実機の確認は docs/plan/friend-lite-realcheck.md)
MAX_UPLOAD = 64 * 1024 ** 3     # ドロップで受け取る動画の上限(64GB)
MIN_FREE = 2 * 1024 ** 3        # 受け取ったあとに残す空き(2GB)
MAX_EDITS_BYTES = 32 * 1024 * 1024
MAX_OPS_PER_CALL = 500
HEX = re.compile(r"^#[0-9A-Fa-f]{6}$")
_lock = threading.Lock()
_exports = {}                   # tid -> 書き出しの進み具合 {"state", "phase", "result"?, "error"?}


# ---------------------------------------------------------------- 置き場所

def data_root():
    return os.path.dirname(ed_state.SETTINGS)


def settings_path():
    return os.path.join(data_root(), "lite.json")


def media_dir():
    return os.path.join(data_root(), "lite-media")


def out_root():
    """書き出しの置き場所: ドキュメント\\文字起こし簡易版(テストは環境変数 LITE_OUT_DIR)"""
    env = os.environ.get("LITE_OUT_DIR")
    if env:
        return os.path.abspath(env)
    home = os.path.expanduser("~")
    docs = os.path.join(home, "Documents")
    return os.path.join(docs if os.path.isdir(docs) else home, "文字起こし簡易版")


def edits_path(tid):
    return os.path.join(ed_state.TX_DIR, tid + ".lite-edits.jsonl")


def export_record_path(tid):
    return os.path.join(ed_state.TX_DIR, tid + ".lite-export.json")


def lite_model():
    m = os.environ.get("LITE_MODEL", "").strip()
    return m if m and ed_state.valid_model(m) else LITE_MODEL


# ---------------------------------------------------------------- 設定・状態

def palette():
    """話者の色の候補 {"text": [{"name", "hex"}], "outline": [...]}(lite-colors.json。壊れていれば内蔵の最小限)"""
    try:
        d = _fsio.read_json_file(COLORS_FILE, 256 * 1024)
    except (OSError, UnicodeError, ValueError):
        d = None
    out = {}
    for k in ("text", "outline"):
        items = [{"name": str(c.get("name") or "")[:12], "hex": c["hex"].upper()} for c in (d or {}).get(k) or []
                 if isinstance(c, dict) and HEX.match(str(c.get("hex") or ""))][:12]
        out[k] = items or FALLBACK_COLORS[k]
    return out


def load_settings():
    try:
        d = _fsio.read_json_file(settings_path(), 1024 * 1024)
    except (OSError, UnicodeError, ValueError):
        d = None
    d = d if isinstance(d, dict) else {}
    styles = {}
    for name, st in (d.get("speakerStyles") or {}).items() if isinstance(d.get("speakerStyles"), dict) else []:
        if isinstance(st, dict) and HEX.match(str(st.get("color") or "")) and HEX.match(str(st.get("outline") or "")):
            styles[str(name)[:30]] = {"color": st["color"].upper(), "outline": st["outline"].upper()}
    return {"worker": str(d.get("worker") or "")[:30], "streamers": [str(s)[:40] for s in d.get("streamers") or [] if isinstance(s, str) and s.strip()][:20],
            "speakerStyles": dict(list(styles.items())[:100])}


def save_settings(patch):
    """POST /api/lite/settings {worker?, speakerStyles?: {名前: {color, outline}}}(話者の色の組み合わせは名前ごとに覚えて次から使う)"""
    with _lock:
        cur = load_settings()
        if isinstance(patch.get("worker"), str):
            cur["worker"] = re.sub(r"[\x00-\x1f\\/:*?\"<>|]", "", patch["worker"]).strip()[:30]
        if isinstance(patch.get("speakerStyles"), dict):
            for name, st in list(patch["speakerStyles"].items())[:50]:
                name = str(name).strip()[:30]
                if name and isinstance(st, dict) and HEX.match(str(st.get("color") or "")) and HEX.match(str(st.get("outline") or "")):
                    cur["speakerStyles"].pop(name, None)
                    cur["speakerStyles"][name] = {"color": st["color"].upper(), "outline": st["outline"].upper()}
            while len(cur["speakerStyles"]) > 100:
                cur["speakerStyles"].pop(next(iter(cur["speakerStyles"])))
        os.makedirs(data_root(), exist_ok=True)
        ed_state.atomic_write(settings_path(), json.dumps(cur, ensure_ascii=False, indent=1).encode("utf-8"))
        return cur


def _remember_streamer(name):
    with _lock:
        cur = load_settings()
        cur["streamers"] = [name] + [s for s in cur["streamers"] if s != name][:19]
        os.makedirs(data_root(), exist_ok=True)
        ed_state.atomic_write(settings_path(), json.dumps(cur, ensure_ascii=False, indent=1).encode("utf-8"))


def works(limit=30):
    """簡易版で作った文書(続きから再開・一覧)。新しい順"""
    out = []
    for tid in ed_store._tids():
        try:
            doc = ed_store.read_transcript(tid)
        except ed_state.ApiError:
            continue
        lite = doc.get("lite")
        if not isinstance(lite, dict):
            continue
        segs = [g for g in doc.get("segments") or [] if str(g.get("text") or "").strip()]
        rec = read_export_record(tid)
        out.append({"id": tid, "title": doc.get("title") or "", "streamer": lite.get("streamer") or "", "updatedAt": doc.get("updatedAt") or 0,
                    "createdAt": doc.get("createdAt") or 0, "rows": len(segs), "checked": sum(1 for g in segs if g.get("proofed") is True),
                    "mediaOk": os.path.isfile(str(doc.get("sourcePath") or "")), "exportedAt": (rec or {}).get("at") or 0})
    out.sort(key=lambda w: -w["updatedAt"])
    return out[:limit]


def state():
    """GET /api/lite/state: 画面の最初に読むもの"""
    import ed_learn   # 名簿(配信者の候補)
    r = ed_learn.load_roster()
    groups = [{"label": g.get("label"), "names": g.get("names")} for g in r.get("groups") or [] if g.get("id") != "units"]
    s = load_settings()
    return {"rules": list(_ev.RULES), "rulesVersion": _ev.RULES_VERSION, "formatVersion": _ev.FORMAT_VERSION, "palette": palette(),
            "settings": s, "groups": groups, "works": works(), "model": lite_model(), "outRoot": os.path.basename(out_root()),
            "ffmpeg": bool(ed_state.find_ffmpeg()), "fasterWhisper": ed_state.has_faster_whisper(), "cuda": ed_state.gpu_ready(),
            "nvidia": ed_state.nvidia_gpu()}


# ---------------------------------------------------------------- 動画の受け取り・確認・開始

def _safe_file_name(name):
    base = _ev.base_name(name)
    stem, ext = os.path.splitext(base)
    ext = ext.lower()
    if ext not in ed_state.MEDIA_TYPES:
        raise ed_state.ApiError("bad_ext", "動画・音声ファイルではないようです(対応: %s)" % " ".join(sorted(ed_state.MEDIA_TYPES)), 400)
    return _ev.safe_part(stem, 60) + ext


def receive_upload(rfile, length, name):
    """POST /api/lite/upload?name=(本文 = 動画のバイト列)→ 作業データの lite-media/ に保存して {"path", "name"}。
    名前は拡張子と使える文字だけ(場所は付けない)。大きさの上限・空きの確認・途中で切れたら書きかけを消す"""
    fname = _safe_file_name(name)
    if not isinstance(length, int) or length <= 0:
        raise ed_state.ApiError("bad_length", "ファイルの大きさが分かりません", 400)
    if length > MAX_UPLOAD:
        raise ed_state.ApiError("too_big", "動画が大きすぎます(64GB まで)", 413)
    d = media_dir()
    os.makedirs(d, exist_ok=True)
    if shutil.disk_usage(d).free < length + MIN_FREE:
        raise ed_state.ApiError("no_space", "ディスクの空きが足りません(動画の大きさ + 2GB が必要です)。「ファイルを選ぶ」から選ぶと、写さずに使えます", 507)
    final = os.path.join(d, "%s_%s" % (uuid.uuid4().hex[:8], fname))
    part = final + ".part"
    left = length
    try:
        with open(part, "wb") as f:
            while left > 0:
                chunk = rfile.read(min(4 * 1024 * 1024, left))
                if not chunk:
                    raise ed_state.ApiError("upload_cut", "受け取りが途中で切れました。もう一度ドロップしてください", 400)
                f.write(chunk)
                left -= len(chunk)
        os.replace(part, final)
    except BaseException:
        try:
            os.unlink(part)
        except OSError:
            pass
        raise
    return {"path": final, "name": fname}


def probe(req):
    """POST /api/lite/probe {path} → {"name", "durationSec", "video", "audio"}(読み込みの画面の長さの注意・確認に使う)"""
    src = ed_state.check_source(req.get("path"))
    dur, has_v, has_a = ed_store.probe_media(src)
    if not has_a:
        raise ed_state.ApiError("no_audio", "この動画には音声がありません。別のファイルを選んでください", 400)
    return {"name": os.path.basename(src), "durationSec": round(dur, 2) if dur else None, "video": has_v, "audio": has_a}


def start(req):
    """POST /api/lite/start {path, streamer, sourceUrl?} → 文字起こしのジョブ(public_job)。配信者の名前は必須"""
    streamer = re.sub(r"[\x00-\x1f]", "", str(req.get("streamer") or "")).strip()[:40]
    if not streamer:
        raise ed_state.ApiError("no_streamer", "配信者の名前を選んでください", 400)
    url = _ev.safe_url(req.get("sourceUrl"))
    if str(req.get("sourceUrl") or "").strip() and not url:
        raise ed_state.ApiError("bad_url", "元の動画の URL は https:// から始まる形で入れてください(空のままでもかまいません)", 400)
    spec = ed_jobs.validate_job({"sourcePath": req.get("path"), "model": lite_model(), "language": "ja", "vadMode": "weak", "autoDict": False,
                                 "autoGloss": False, "autoContext": False, "autoLearned": False, "wordSplit": True, "autoRedo": False})
    spec["lite"] = {"streamer": streamer, "sourceUrl": url, "rulesVersion": _ev.RULES_VERSION, "formatVersion": _ev.FORMAT_VERSION}
    job = ed_jobs.add_job(spec)
    _remember_streamer(streamer)
    return ed_jobs.public_job(job)


def on_new_doc(spec, doc):
    """新しくできた文書に簡易版の印と既定の話者(配信者。保存した色の組み合わせか、色の候補の最初)を付ける(ed_jobs.run_job が呼ぶ)"""
    lite = spec.get("lite")
    if not isinstance(lite, dict):
        return
    doc["lite"] = dict(lite)
    name = lite.get("streamer") or "話者1"
    st = load_settings()["speakerStyles"].get(name)
    pal = palette()
    doc["speakers"] = [{"id": "A", "name": name[:30], "color": (st or {}).get("color") or pal["text"][0]["hex"],
                        "outline": (st or {}).get("outline") or pal["outline"][0]["hex"]}]
    for g in doc.get("segments") or []:
        g["speaker"] = "A"


# ---------------------------------------------------------------- 作業の記録

def append_ops(req):
    """POST /api/lite/ops {id, ops: [...]} → 作業の記録に足す(evaldata.sanitize_op を通したものだけ)。-> {"saved": 件数}"""
    tid = re.sub(r"[^0-9a-f]", "", str(req.get("id") or ""))[:12]
    if not tid or not os.path.isfile(ed_store.tx_path(tid)):
        raise ed_state.ApiError("not_found", "作業が見つかりません", 404)
    ops = req.get("ops") if isinstance(req.get("ops"), list) else []
    lines = []
    for o in ops[:MAX_OPS_PER_CALL]:
        s = _ev.sanitize_op(o)
        if s:
            lines.append(json.dumps(s, ensure_ascii=False, separators=(",", ":")))
    if not lines:
        return {"saved": 0}
    p = edits_path(tid)
    with _lock:
        try:
            size = os.path.getsize(p)
        except OSError:
            size = 0
        data = ("\n".join(lines) + "\n").encode("utf-8")
        if size + len(data) > MAX_EDITS_BYTES:
            return {"saved": 0, "full": True}
        with open(p, "ab") as f:
            f.write(data)
    return {"saved": len(lines)}


def read_edits(tid):
    try:
        with open(edits_path(tid), "rb") as f:
            return f.read(MAX_EDITS_BYTES)
    except OSError:
        return b""


# ---------------------------------------------------------------- 書き出し

def read_export_record(tid):
    try:
        d = _fsio.read_json_file(export_record_path(tid), 256 * 1024)
    except (OSError, UnicodeError, ValueError):
        return None
    return d if isinstance(d, dict) else None


def work_name(doc, tid):
    """作業のフォルダと zip の名前(日付_配信者_作業ID)。日付は文書を作った日(書き出し直しても同じ名前)"""
    ms = doc.get("createdAt") or doc.get("updatedAt") or int(time.time() * 1000)
    date = time.strftime("%Y-%m-%d", time.localtime(ms / 1000))
    return date, _ev.zip_name(date, (doc.get("lite") or {}).get("streamer") or "", tid)[:-len(_ev.ZIP_SUFFIX)]


def export_start(req):
    """POST /api/lite/export {id} → 書き出しを始める(別のスレッド。進み具合は GET /api/lite/export?id=)"""
    tid = re.sub(r"[^0-9a-f]", "", str(req.get("id") or ""))[:12]
    doc = ed_store.read_transcript(tid)
    if not isinstance(doc.get("lite"), dict):
        raise ed_state.ApiError("not_lite", "簡易版で作った作業ではありません", 400)
    with _lock:
        cur = _exports.get(tid)
        if cur and cur.get("state") in ("waiting", "running"):
            raise ed_state.ApiError("busy", "書き出しの途中です", 409)
        t = {"state": "running", "phase": "準備しています", "at": time.time()}
        _exports[tid] = t
    threading.Thread(target=_export_run, args=(tid, t), daemon=True, name="lite-export").start()
    return dict(t)


def export_status(tid):
    tid = re.sub(r"[^0-9a-f]", "", str(tid or ""))[:12]
    with _lock:
        t = _exports.get(tid)
        return dict(t) if t else {"state": "none", "record": read_export_record(tid)}


def _export_run(tid, t):
    try:
        with _heavy.SLOTS.slot(ed_state.TOOL_ID, "書き出し " + tid, on_wait=lambda: t.update(state="waiting", phase=_heavy.WAIT_MESSAGE)):
            t.update(state="running")
            res = export_now(tid, lambda msg: t.update(phase=msg))
        t.update(state="done", phase="できました", result=res)
    except ed_state.ApiError as e:
        t.update(state="error", code=e.code, error=e.message)
    except Exception as e:   # 想定外でもサーバーは止めない
        ed_state.log.exception("簡易版の書き出しで例外")
        t.update(state="error", code="internal", error="内部エラー: %s %s" % (e.__class__.__name__, str(e)[:200]))


def export_now(tid, say=lambda m: None):
    """Resolve 用ファイルと送る用 zip を作る -> {"folder", "zip", "zipName", "pack", "warnings": [...], "judge": {...}, "counts"}。
    出力先: <out_root>\\<日付_配信者_作業ID>\\Resolve用ファイル\\ と 送る用ファイル\\<日付_配信者_作業ID>.zip(何度でも作り直せる = 上書き)"""
    doc = ed_store.read_transcript(tid)
    lite = doc.get("lite")
    if not isinstance(lite, dict):
        raise ed_state.ApiError("not_lite", "簡易版で作った作業ではありません", 400)
    src = str(doc.get("sourcePath") or "")
    if not src or not os.path.isfile(src):
        raise ed_state.ApiError("source_missing", "元の動画が見つかりません(動画を移動・削除・名前の変更をしていないか確かめてください)", 400)
    date, name = work_name(doc, tid)
    base = os.path.join(out_root(), name)
    pack_dir, send_dir = os.path.join(base, PACK_DIR_NAME), os.path.join(base, SEND_DIR_NAME)
    say("Resolve 用ファイルを作っています(動画のコピーに時間がかかることがあります)")
    pinfo = build_pack(doc, pack_dir)
    say("送る用ファイルを作っています(音声を取り出しています)")
    zpath, judged, counts = build_zip(doc, tid, send_dir, date, name, pinfo)
    warnings = list(pinfo["warnings"])
    if counts["unchecked"]:
        warnings.append("まだ確認していない行が %d 行あります(送る用ファイルでは、確認済みの行だけが使われます)" % counts["unchecked"])
    if judged["notes"]["badMarkRows"]:
        warnings.append("記号の形が違う行が %d 行あります([?] と [笑] だけを使ってください。その行は評価に使われません)" % judged["notes"]["badMarkRows"])
    if not judged["work"]["use"]:
        warnings += judged["work"]["reasons"]
    rec = {"at": int(time.time() * 1000), "folder": base, "zip": zpath, "pack": pack_dir, "counts": counts}
    ed_state.atomic_write(export_record_path(tid), json.dumps(rec, ensure_ascii=False).encode("utf-8"))
    return {"folder": os.path.basename(base), "zipName": os.path.basename(zpath), "packName": PACK_DIR_NAME, "warnings": warnings,
            "judge": {"work": judged["work"], "notes": judged["notes"]}, "counts": counts, "captions": pinfo["captions"]}


def _pack_mod():
    import resolve_export
    try:
        return resolve_export._load_pack()
    except resolve_export.ResolveExportError as e:
        raise ed_state.ApiError("no_pack", str(e), 500)


def subtitle_doc(doc):
    """Resolve 用の字幕の文書: [?]・[笑] を除き、空になった行は入れない(記号を除いた文字数で折り返す = pack の wrap がこの文字で数える)"""
    rows = []
    for g in doc.get("segments") or []:
        text = _ev.strip_marks(g.get("text"))
        if text:
            rows.append(dict(g, text=text))
    return dict(doc, segments=rows)


def build_pack(doc, pack_dir):
    """カットなし(動画全体を残す)・字幕の型 lite・話者ごとの文字の色とふちの色。-> {"captions", "fps", "width", "height", "durationSec", "warnings"}"""
    pack, tp = _pack_mod()
    sdoc = subtitle_doc(doc)
    if not sdoc["segments"]:
        raise ed_state.ApiError("no_rows", "字幕にする行がありません(すべての行が空か、記号だけです)", 400)
    pio = ed_state.pio()
    tmp = tempfile.mkdtemp(prefix="lite-pack-")
    try:
        tpath = os.path.join(tmp, "input.transcript.json")
        with open(tpath, "w", encoding="utf-8") as f:
            json.dump(pio.build_transcript_v1(sdoc, ed_state.SERVER_VERSION), f, ensure_ascii=False)
        dur = ed_state.num(doc.get("duration")) or ed_state.media_duration(doc["sourcePath"]) or 0
        try:
            req = pack.Request(video=Path(doc["sourcePath"]), transcript=Path(tpath), keep_pairs=[(0.0, float(dur))] if dur else None,
                               **dict(pack.EDIT_KEEPS, base="list" if dur else "all"))
            plan = pack.plan_cut(req)
            w, h = int(plan.meta["w"]), int(plan.meta["h"])
            horizontal = w >= h
            target = tp.parse_target(TARGET_FPS, "1920x1080" if horizontal else "1080x1920")
            colors = {s["name"]: s["color"] for s in doc.get("speakers") or [] if HEX.match(str(s.get("color") or ""))}
            outlines = {s["name"]: s["outline"] for s in doc.get("speakers") or [] if HEX.match(str(s.get("outline") or ""))}
            res = pack.build_pack(plan, Path(pack_dir), textplus=True, textplus_target=target, backup=False, plan_file=False, readme_file=False,
                                  textplus_wrap=tp.WRAP_DEFAULT["horizontal" if horizontal else "vertical"], force=True,
                                  speaker_colors=colors or None, speaker_outlines=outlines or None, textplus_style="lite")
        except pack.ToolError as e:
            raise ed_state.ApiError("pack_failed", "Resolve 用ファイルを作れませんでした: %s" % e, 400)
        ed_state.atomic_write(os.path.join(pack_dir, README_NAME), ("﻿" + res["readme"]).encode("utf-8"))
        fps = plan.meta["fps"]
        return {"captions": len(plan.cues_out or []), "fps": "%d/%d" % (fps[0], fps[1]), "fpsValue": round(fps[0] / fps[1], 3), "width": w, "height": h,
                "durationSec": round(float(dur or 0), 2), "warnings": list(res["warnings"])}
    finally:
        shutil.rmtree(tmp, ignore_errors=True)


def extract_flac(src, dst, start=0.0, end=None):
    """評価用の音声: 16kHz・モノラルの FLAC(10 分で数 MB)"""
    ff = ed_state.find_ffmpeg()
    if not ff:
        raise ed_state.ApiError("no_ffmpeg", "ffmpeg が見つかりません", 400)
    cmd = [ff, "-hide_banner", "-nostdin", "-y", "-v", "error"]
    if start:
        cmd += ["-ss", "%.3f" % start]
    cmd += ["-i", src]
    if end:
        cmd += ["-t", "%.3f" % max(0.0, end - start)]
    cmd += ["-vn", "-ac", "1", "-ar", "16000", "-c:a", "flac", "-f", "flac", dst]
    try:
        p = subprocess.run(cmd, stdin=subprocess.DEVNULL, stdout=subprocess.PIPE, stderr=subprocess.PIPE, timeout=6 * 3600)
    except (OSError, subprocess.SubprocessError) as e:
        raise ed_state.ApiError("audio_failed", "音声を取り出せませんでした: %s" % e, 500)
    if p.returncode != 0 or not os.path.isfile(dst):
        tail = (p.stderr or b"").decode("utf-8", "replace").strip().splitlines()[-1:] or [""]
        raise ed_state.ApiError("audio_failed", "音声を取り出せませんでした: %s" % _ev.scrub_paths(tail[0][:200]), 500)


def bundle_parts(doc, tid, date, pinfo, edits_bytes):
    """送る用 zip の JSON の中身 {"asr_raw.json", "final.json", "meta.json"} と判定(書く前。パスは除いたあと)"""
    lite = doc.get("lite") or {}
    asr = ed_jobs.read_asr(tid)
    if asr:
        raw_segs, run, source = asr["segments"], asr.get("run") or {}, "asr"
    else:   # 生出力が無い(簡易版より前の文書)ときは、文書の機械の出力で代わりにする
        raw_segs = [dict(o, words=[]) for o in doc.get("original") or [] if isinstance(o, dict)]
        run, source = ((doc.get("recognition") or {}).get("runs") or [{}])[-1], "original"
    names = {s.get("id"): s.get("name") or s.get("id") for s in doc.get("speakers") or []}
    rows = []
    for g in ed_state.pio().sorted_segments(doc):
        rows.append({"id": str(g.get("id") or ""), "start": round(float(g["start"]), 3), "end": round(float(g["end"]), 3),
                     "text": str(g.get("text") or ""), "speaker": names.get(g.get("speaker"), "") or "", "speakerId": str(g.get("speaker") or ""),
                     "checked": g.get("proofed") is True, "tags": list(g.get("tags") or []), "raw": _ev.raw_links(g, raw_segs)})
    tool = {"name": "editor-lite", "version": str(ed_state.SERVER_VERSION or "")}
    common = {"format": _ev.FORMAT, "formatVersion": _ev.FORMAT_VERSION, "workId": tid}
    final = dict(common, speakers=[{"id": str(k), "name": str(v)} for k, v in names.items()], rows=rows)
    asr_raw = dict(common, source=source, tool=tool, run=run, segments=raw_segs)
    edits = _ev.read_edits(edits_bytes)
    judged = _ev.judge(final, asr_raw, edits)
    used_names = sorted({r["speaker"] for r in rows if r["checked"] and r["speaker"]})
    counts = {"rows": len(rows), "checked": sum(1 for r in rows if r["checked"]), "unchecked": sum(1 for r in rows if not r["checked"]),
              "usable": sum(1 for c in judged["rows"] if c["use"]), "edits": len(edits)}
    meta = dict(common, rulesVersion=lite.get("rulesVersion") or _ev.RULES_VERSION, rules=list(_ev.RULES), streamer=lite.get("streamer") or "",
                performers=used_names, sourceUrl=_ev.safe_url(lite.get("sourceUrl")), sourceName=_ev.base_name(doc.get("sourceName") or doc.get("sourcePath")),
                durationSec=pinfo.get("durationSec"), fps=pinfo.get("fps"), fpsValue=pinfo.get("fpsValue"),
                width=pinfo.get("width"), height=pinfo.get("height"), worker=load_settings()["worker"], date=date,
                exportedAt=time.strftime("%Y-%m-%dT%H:%M:%S%z"), tool=tool, model=str(run.get("model") or doc.get("model") or ""),
                counts=counts, notes=judged["notes"])
    parts = {"asr_raw.json": asr_raw, "final.json": final, "meta.json": meta}
    parts = {k: _ev.scrub_paths(v) for k, v in parts.items()}
    left = [(k, w) for k, v in parts.items() for w in _ev.find_abs_paths(v)]
    if left:   # 除いたあとも残っていたら送らない(個人の情報が入るおそれ)
        raise ed_state.ApiError("path_left", "送る用ファイルに PC の場所が残ってしまうため、作るのをやめました: %s" % left[0][0], 500)
    return parts, judged, counts


def build_zip(doc, tid, send_dir, date, name, pinfo):
    """送る用 zip(evaldata.FILES)を send_dir に作る -> (パス, 判定, 数)。作ったあと evaldata.check_zip で自分でも確かめる"""
    edits_bytes = read_edits(tid)
    parts, judged, counts = bundle_parts(doc, tid, date, pinfo, edits_bytes)
    os.makedirs(send_dir, exist_ok=True)
    tmp = tempfile.mkdtemp(prefix="lite-zip-")
    try:
        flac = os.path.join(tmp, "audio.flac")
        a = ed_state.num(doc.get("start")) or 0.0
        b = ed_state.num(doc.get("end")) if doc.get("whole") is False else None
        extract_flac(doc["sourcePath"], flac, a, b)
        out = os.path.join(send_dir, name + _ev.ZIP_SUFFIX)
        part = out + ".part"
        clean_edits = b"".join((json.dumps(o, ensure_ascii=False, separators=(",", ":")) + "\n").encode("utf-8") for o in _ev.read_edits(edits_bytes))
        with zipfile.ZipFile(part, "w", compression=zipfile.ZIP_DEFLATED, allowZip64=True) as z:
            z.write(flac, "audio.flac", compress_type=zipfile.ZIP_STORED)
            for fname in ("asr_raw.json", "final.json", "meta.json"):
                z.writestr(fname, json.dumps(parts[fname], ensure_ascii=False, indent=1))
            z.writestr("edits.jsonl", clean_edits)
        _ok, problems = _ev.check_zip(part)
        if problems:
            os.unlink(part)
            raise ed_state.ApiError("zip_invalid", "送る用ファイルの確認で問題が見つかりました: %s" % problems[0], 500)
        _fsio.replace_retry(part, out)
        return out, judged, counts
    finally:
        shutil.rmtree(tmp, ignore_errors=True)


def open_folder(req):
    """POST /api/lite/open {id, what: send|pack|base} → 前回の書き出しのフォルダを開く(記録にあり、書き出しの置き場所の中のフォルダだけ)"""
    tid = re.sub(r"[^0-9a-f]", "", str(req.get("id") or ""))[:12]
    rec = read_export_record(tid)
    if not rec:
        raise ed_state.ApiError("not_found", "まだ書き出していません", 404)
    what = req.get("what") if req.get("what") in ("send", "pack", "base") else "send"
    path = {"send": os.path.dirname(str(rec.get("zip") or "")), "pack": rec.get("pack"), "base": rec.get("folder")}[what]
    root = os.path.normcase(os.path.realpath(out_root()))
    real = os.path.normcase(os.path.realpath(str(path or "")))
    if not real.startswith(root + os.sep) or not os.path.isdir(real):
        raise ed_state.ApiError("not_found", "フォルダが見つかりません(移動・削除したかもしれません)", 404)
    _start_folder(real)
    return {"opened": True}


def _start_folder(path):
    if os.name == "nt":
        os.startfile(path)  # noqa: S606(フォルダだけ。確かめてから)
    else:   # pragma: no cover - Windows 以外(テスト用)
        subprocess.Popen(["open" if os.uname().sysname == "Darwin" else "xdg-open", path], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
