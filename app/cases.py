"""案件(配信1本)ごとの紐づけ(統合計画の段階4)。入口の「案件」画面(app/cases.html)の中身を作る。

案件 = 切り抜きスタジオの動画1本(配信・ファイル)。その下に、書き出した切り抜きと、それぞれの文字起こし・パックを並べる。
紐づけは、各ツールが持っているデータを**読むたびに組み立て直す**(各ツールの記録と食い違わないように。2026-09-26 ユーザーと決定):
  - 切り抜き … スタジオの data.json の「書き出し済み」のマーク(書き出した mp4 の絶対パスを持つ)
  - 文字起こし … 文字起こしツールの transcripts/*.json(元の動画のパスが切り抜きと同じ。無ければ .clip.json の配信・マークが同じ。
                規則は ytt_core/txindex.py にあり、スタジオのセリフの表示と共通)
  - パック … 切り抜きの隣の <名前>_pack フォルダ(cut2resolve の既定の出力先)
案件ファイル(<作業データ>\\app\\cases.json)に持つのは、人が付ける状態・メモと、最後に見えた紐づけ(元のファイルを消しても履歴が残るように)。
各ツールのデータは読むだけで、書き換えない。
"""
import json
import os
import threading
import time

from ytt_core import datadir, fsio, txindex

SCHEMA = "youtube-tools-cases/v1"
STATUSES = ("", "working", "posted", "skipped")        # 未設定・作業中・投稿済み・見送り
STATUS_LABELS = {"": "未設定", "working": "作業中", "posted": "投稿済み", "skipped": "見送り"}
MAX_MEMO = 2000
MAX_JSON = 64 * 1024 * 1024
_lock = threading.Lock()


def _read_json(path, limit=MAX_JSON):
    try:
        return fsio.read_json_file(path, limit)
    except (OSError, UnicodeError, ValueError):
        return None


def locations(repo_root, env=None):
    """{"studio": data.json, "transcripts": フォルダ, "cases": cases.json}。各ツールと同じ規則で置き場所を決める"""
    env = os.environ if env is None else env
    studio_home = env.get("STUDIO_HOME") or datadir.tool_dir("studio", os.path.join(repo_root, "clip-studio"), env)
    app_home = datadir.tool_dir("app", os.path.join(repo_root, "app"), env)
    return {"studio": os.path.join(studio_home, "data.json"), "transcripts": txindex.folder(repo_root, env),
            "cases": os.path.join(app_home, "cases.json")}


# ---------------------------------------------------------------- 各ツールのデータを読む(読むだけ)

def read_studio(path):
    d = _read_json(path)
    videos = d.get("videos") if isinstance(d, dict) else None
    return videos if isinstance(videos, dict) else {}


def read_transcripts(folder):
    """文字起こしの一覧(ytt_core.txindex。スタジオのセリフの表示と同じ読み方・紐づけの規則)"""
    return txindex.load(folder)


def find_pack(media_path):
    """切り抜きの隣の <名前>_pack(cut2resolve の既定の出力先)。-> {"dir", "textplus", "updatedAt"} か None"""
    if not media_path:
        return None
    d = os.path.join(os.path.dirname(media_path), os.path.splitext(os.path.basename(media_path))[0] + "_pack")
    plan = os.path.join(d, "cut-plan.json")
    if not os.path.isfile(plan):
        return None
    try:
        mt = int(os.path.getmtime(plan) * 1000)
    except OSError:
        mt = 0
    return {"dir": d, "textplus": os.path.isfile(os.path.join(d, "textplus-import.json")), "updatedAt": mt}


# ---------------------------------------------------------------- 組み立て

def build(videos, transcripts, saved=None, pack_finder=find_pack):
    """-> {"cases": [...], "unlinked": [文字起こし]}。saved: cases.json の中身(状態・メモ・最後に見えた紐づけ)"""
    saved = saved or {}
    used = set()
    cases = []
    for vid, v in videos.items():
        if not isinstance(v, dict):
            continue
        marks = [m for m in (v.get("marks") or []) if isinstance(m, dict)]
        clips = []
        for m in sorted((m for m in marks if m.get("status") == "exported"), key=lambda m: (m.get("start") or 0)):
            path = m.get("path") if isinstance(m.get("path"), str) else ""
            tx, n, ids = txindex.pick(transcripts, vid, m.get("id"), path)
            used.update(ids)
            clips.append({"markId": str(m.get("id") or ""), "label": str(m.get("label") or "")[:80], "start": m.get("start"), "end": m.get("end"),
                          "file": str(m.get("file") or ""), "path": path, "exists": bool(path) and os.path.isfile(path),
                          "transcript": txindex.summary(tx) if tx else None, "transcripts": n, "pack": pack_finder(path) if path else None})
        s = saved.get(vid) if isinstance(saved.get(vid), dict) else {}
        cases.append({"id": vid, "kind": v.get("kind") or "", "title": str(v.get("title") or v.get("fileName") or vid)[:120],
                      "channel": str(v.get("channel") or "")[:100], "duration": v.get("duration") or 0,
                      "marks": {"total": len(marks), "adopted": sum(1 for m in marks if m.get("status") == "adopted"),
                                "exported": len(clips), "candidates": sum(1 for m in marks if not m.get("status"))},
                      "clips": clips, "status": s.get("status") if s.get("status") in STATUSES else "",
                      "memo": str(s.get("memo") or "")[:MAX_MEMO], "statusUpdatedAt": s.get("statusUpdatedAt") or 0,
                      "updatedAt": v.get("updatedAt") or 0, "gone": False})
    # スタジオから消えた動画も、状態・メモを付けていれば、最後に見えた紐づけで残す
    for cid, s in saved.items():
        if cid not in videos and isinstance(s, dict) and (s.get("status") or s.get("memo")) and isinstance(s.get("last"), dict):
            last = dict(s["last"], id=cid, status=s.get("status") if s.get("status") in STATUSES else "",
                        memo=str(s.get("memo") or "")[:MAX_MEMO], gone=True)
            cases.append(last)
    cases.sort(key=lambda c: -(c.get("updatedAt") or 0))
    unlinked = [dict(txindex.summary(t), sourcePath=t["sourcePath"]) for t in transcripts if t["id"] not in used]
    unlinked.sort(key=lambda t: -t["updatedAt"])
    return {"cases": cases, "unlinked": unlinked}


# ---------------------------------------------------------------- 案件ファイル

def load_saved(path):
    d = _read_json(path, 16 * 1024 * 1024)
    if not isinstance(d, dict) or d.get("schema") != SCHEMA or not isinstance(d.get("cases"), dict):
        return {}
    return d["cases"]


def _write(path, saved):
    os.makedirs(os.path.dirname(path), exist_ok=True)
    fsio.write_json(path, {"schema": SCHEMA, "cases": saved})


def snapshot(repo_root, env=None):
    """画面用の一覧。最後に見えた紐づけ(状態・メモを付けた案件だけ)を案件ファイルに残す"""
    loc = locations(repo_root, env)
    with _lock:
        saved = load_saved(loc["cases"])
        res = build(read_studio(loc["studio"]), read_transcripts(loc["transcripts"]), saved)
        changed = False
        for c in res["cases"]:
            s = saved.get(c["id"])
            if s is not None and not c["gone"]:
                last = {k: c[k] for k in ("kind", "title", "channel", "duration", "marks", "clips", "updatedAt")}
                if s.get("last") != last:
                    s["last"] = last
                    changed = True
        if changed:
            try:
                _write(loc["cases"], saved)
            except OSError:
                pass
    res["casesFile"] = loc["cases"]
    return res


def update(repo_root, case_id, status=None, memo=None, env=None):
    """状態・メモを付ける。-> 更新後の {status, memo, statusUpdatedAt}"""
    if not isinstance(case_id, str) or not (1 <= len(case_id) <= 64) or not all(ch.isalnum() or ch in "-_" for ch in case_id):
        raise ValueError("案件の指定が正しくありません")
    if status is not None and status not in STATUSES:
        raise ValueError("状態が正しくありません")
    if memo is not None and (not isinstance(memo, str) or len(memo) > MAX_MEMO):
        raise ValueError("メモは %d 文字までです" % MAX_MEMO)
    loc = locations(repo_root, env)
    with _lock:
        saved = load_saved(loc["cases"])
        s = saved.setdefault(case_id, {})
        if status is not None:
            s["status"] = status
            s["statusUpdatedAt"] = int(time.time() * 1000)
        if memo is not None:
            s["memo"] = memo
        if not s.get("status") and not s.get("memo"):
            saved.pop(case_id, None)   # 何も付けていない案件は持たない(ファイルを小さく)
        _write(loc["cases"], saved)
        return {"status": s.get("status", ""), "memo": s.get("memo", ""), "statusUpdatedAt": s.get("statusUpdatedAt", 0)}
