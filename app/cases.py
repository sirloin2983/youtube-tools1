"""案件(配信1本)ごとの紐づけ(統合計画の段階4)。入口の「案件」画面(app/cases.html)の中身を作る。

案件 = 切り抜きスタジオの動画1本(配信・ファイル)。その下に、書き出した切り抜きと、それぞれの文字起こし・パックを並べる。
紐づけは、各ツールが持っているデータを**読むたびに組み立て直す**(各ツールの記録と食い違わないように。2026-09-26 ユーザーと決定):
  - 切り抜き … スタジオの data.json の「書き出し済み」のマーク(書き出した mp4 の絶対パスを持つ)
  - 文字起こし … 文字起こしツールの transcripts/*.json(元の動画のパスが切り抜きと同じ。無ければ .clip.json の配信・マークが同じ。
                規則は ytt_core/txindex.py にあり、スタジオのセリフの表示と共通)
  - パック … 切り抜きの隣の <名前>_pack フォルダ(cut2resolve の既定の出力先)
案件ファイル(<作業データ>\\app\\cases.json)に持つのは、人が付ける状態・メモと、最後に見えた紐づけ(元のファイルを消しても履歴が残るように)。
各ツールのデータは読むだけで、書き換えない。

画面が一覧(1件1行)を組み立てやすいように、案件1件ごとに追加で持たせる項目(2026-09-26 画面の見直し。既存の項目は変えない):
  - streamedAt: 「いつの配信か」の目安(ms)。① スタジオの解析結果(analysis.uploadDate、実際の配信日)② 無ければ案件が
    スタジオに追加された時刻(createdAt)③ それも無ければ updatedAt、の順(デモ環境や解析前の動画では ①が無い)
  - tx: 切り抜き全体の文字起こし・校正の進み具合の合計 {clips, withTranscript, segments, proofed}
  - packs: 切り抜き全体のパックの有無の合計 {have, total, textplus}
  - next: 一覧に出す「次にやること」1つ {kind, label, count} か None(すべて済み)。書き出し → 文字起こし → 校正 → パックの順で
    最初に残っている作業
  - remaining: next も含めた残作業の合計件数(並び替え「次にやることが多い順」に使う)
"""
import datetime
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
    """切り抜きの隣の <名前>_pack(cut2resolve の既定の出力先)。-> {"dir", "textplus", "updatedAt"} か None。
    規則は ytt_core/txindex.pack_info の1か所(文字起こしの一覧と同じ判定)"""
    return txindex.pack_info(media_path)


def _upload_date_ms(s):
    """analysis.uploadDate("YYYYMMDD")→ ms。形が違えば 0"""
    if isinstance(s, str) and len(s) == 8 and s.isdigit():
        try:
            d = datetime.datetime(int(s[:4]), int(s[4:6]), int(s[6:8]), tzinfo=datetime.timezone.utc)
            return int(d.timestamp() * 1000)
        except ValueError:
            return 0
    return 0


def _int_ms(x):
    return x if isinstance(x, int) and not isinstance(x, bool) and x > 0 else 0


def _stream_time(v):
    """「いつの配信か」の目安(ms)。解析で分かった配信日 → 案件が増えた時刻 → 最後に触った時刻、の順"""
    an = v.get("analysis") if isinstance(v.get("analysis"), dict) else {}
    return _upload_date_ms(an.get("uploadDate")) or _int_ms(v.get("createdAt")) or _int_ms(v.get("updatedAt"))


def _case_extras(c):
    """一覧の1行に要る合計・「次にやること」(2026-09-26)。clips・marks だけから作れるので、案件の生成元(スタジオに
    まだある配信・消えた配信の最後に見えた内容)のどちらでも同じ規則で計算できる"""
    clips = c.get("clips") or []
    total = len(clips)
    with_tx = [cl["transcript"] for cl in clips if cl.get("transcript")]
    have_pack = sum(1 for cl in clips if cl.get("pack"))
    to_export = int((c.get("marks") or {}).get("adopted") or 0)                                    # 採用済みでまだ書き出していない
    missing_tx = sum(1 for cl in clips if not cl.get("transcript"))                                 # 書き出し済みで文字起こしがまだ
    proofing = sum(1 for t in with_tx if t.get("proofed", 0) < t.get("segments", 0))                # 文字起こしはあるが校正が残っている
    missing_pack = total - have_pack                                                                # 書き出し済みでパックがまだ
    steps = ((to_export, "export", "書き出し"), (missing_tx, "transcribe", "文字起こし"),
             (proofing, "proof", "校正"), (missing_pack, "pack", "パックを作る"))
    nxt = next(({"kind": k, "label": lb, "count": n} for n, k, lb in steps if n > 0), None)
    return {"tx": {"clips": total, "withTranscript": len(with_tx), "segments": sum(t["segments"] for t in with_tx),
                   "proofed": sum(t["proofed"] for t in with_tx)},
            "packs": {"have": have_pack, "total": total, "textplus": sum(1 for cl in clips if cl.get("pack") and cl["pack"].get("textplus"))},
            "next": nxt, "remaining": to_export + missing_tx + proofing + missing_pack,
            "streamedAt": c.get("streamedAt") or c.get("updatedAt") or 0}


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
                      "updatedAt": v.get("updatedAt") or 0, "streamedAt": _stream_time(v), "gone": False})
    # スタジオから消えた動画も、状態・メモを付けていれば、最後に見えた紐づけで残す
    for cid, s in saved.items():
        if cid not in videos and isinstance(s, dict) and (s.get("status") or s.get("memo")) and isinstance(s.get("last"), dict):
            last = dict(s["last"], id=cid, status=s.get("status") if s.get("status") in STATUSES else "",
                        memo=str(s.get("memo") or "")[:MAX_MEMO], gone=True)
            cases.append(last)
    for c in cases:
        c.update(_case_extras(c))
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
                last = {k: c[k] for k in ("kind", "title", "channel", "duration", "marks", "clips", "updatedAt", "streamedAt")}
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
