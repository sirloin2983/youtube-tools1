# -*- coding: utf-8 -*-
"""リアルタイム切り抜き(線 D)の失敗の集約(M3。plan/line-d-auto-pack.md の 4)。

書き出し(src/home/live_export.py のジョブ = 入口の作業データの live/exports.json)と、書き出したあとの文字起こし・パック
(まとめて実行 = logs/autorun-runs.jsonl。ジョブの runId で紐づける)の失敗を、**1 つの関数(failure_of)で 1 つの文にする**。
同じ文を 3 か所に出す: 「調子」(Live.health の failures → ホームの画面)・スタジオの LIVE の帯(GET /live/api/exports のジョブの failure と、
帯が今までどおり出す欄 = 書き出しの失敗は error・それ以外は warning)・確認の一覧(M9。これから)。
人が触らない時間が長いほど、失敗に気づく場所が要る(計画の 5 の 2: 黙って消えない)。

数えるもの(kind):
  export     書き出しに失敗した(ジョブの state が error。欠けで「要差し替え」も)
  handoff    書き出しはできたが、まとめて実行へ渡せなかった(ジョブの handoffError。入口 0.39.0 から記録する)
  transcribe 渡したまとめて実行が、文字起こし(話者分離を含む)で失敗した(記録の steps の error の段)
  pack       同じく、パック・届ける段で失敗した
  afterStream 配信後の全自動(M7。src/home/live_archive.py の afterStream)が止まった(アーカイブの解析・時刻合わせ・採用。録画ごと。after_stream_failure)
人が中止した(cancelled)・取り消した書き出しは数えない(失敗ではない)。読むだけ(どのファイルも書き換えない)。
"""
import os
import threading

from ytt_core import fsio

KIND_LABELS = {"export": "書き出し", "handoff": "まとめて実行へ渡す", "transcribe": "文字起こし", "pack": "パック", "afterStream": "配信後の自動"}
TX_STEPS = ("transcribe", "diarize")         # 文字起こしの側の段(src/home/autorun.py の STEP_LABELS の鍵)
PACK_STEPS = ("pack", "deliver")             # パックの側の段
WINDOW_SEC = 7 * 24 * 3600                   # 「調子」に出す期間(まとめて実行の失敗の数と同じ 7 日)
MAX_LIST = 20                                # 「調子」に出す数(新しい順)
RUNS_READ_BYTES = 512 * 1024                 # まとめて実行の記録は末尾からこれだけ読む(1 件 1〜2KB)
REASON_MAX = 300


def _reason(s):
    s = " ".join(str(s or "").split())
    return s[:REASON_MAX]


def _name(job):
    """失敗の文の頭に付ける名前: 書き出したファイルの名前 → マークのラベル → 「マーク n」"""
    p = job.get("path") if isinstance(job.get("path"), str) else ""
    if p:
        return os.path.basename(p)
    if job.get("label"):
        return "「%s」" % str(job["label"])[:80]
    return "マーク %s" % (job.get("n") or "?")


def failure_of(job, run=None):
    """書き出しのジョブ 1 つ(と、渡したまとめて実行の記録 run)-> 失敗 {"kind", "kindLabel", "text"} か None(失敗していない)。
    **失敗の文はここだけで作る**(調子・LIVE の帯・確認の一覧が同じ文を出す)"""
    if not isinstance(job, dict):
        return None
    name = _name(job)
    if job.get("state") == "error":
        why = _reason(job.get("error") or job.get("message")) or "理由が分かりません"
        tail = "(アーカイブで本番版に作り直せます)" if job.get("needsArchive") else ""
        return {"kind": "export", "kindLabel": KIND_LABELS["export"], "text": "%s: 書き出しに失敗しました: %s%s" % (name, why, tail)}
    if job.get("state") != "done":
        return None
    if job.get("handoffError"):
        return {"kind": "handoff", "kindLabel": KIND_LABELS["handoff"], "text": "%s: %s" % (name, _reason(job["handoffError"]))}
    if isinstance(run, dict) and run.get("state") == "error":
        steps = [s for s in run.get("steps") or [] if isinstance(s, dict)]
        bad = next((s for s in steps if s.get("state") == "error"), None)
        kind = "pack" if (bad or {}).get("key") in PACK_STEPS else "transcribe"   # 段が分からない失敗は最初の段(文字起こし)の側に数える
        why = _reason(run.get("error") or (bad or {}).get("detail") or run.get("message")) or "理由が分かりません"
        if why.startswith(KIND_LABELS[kind]):   # まとめて実行の理由がもう段の名前で始まっている(「文字起こしに失敗しました: …」)なら重ねない
            return {"kind": kind, "kindLabel": KIND_LABELS[kind], "text": "%s: %s" % (name, why)}
        return {"kind": kind, "kindLabel": KIND_LABELS[kind], "text": "%s: %sに失敗しました: %s" % (name, KIND_LABELS[kind], why)}
    return None


def after_stream_failure(info):
    """録画ごとの記録(src/home/live_archive.py の archive.json の 1 件。afterStream を持つ)-> 失敗 {"kind", "kindLabel", "text"} か None。
    配信後の全自動(M7)が止まった理由の文はここだけで作る"""
    a = info.get("afterStream") if isinstance(info, dict) else None
    if not isinstance(a, dict) or a.get("state") != "error":
        return None
    title = str(a.get("title") or "").strip()
    name = "「%s」" % title[:80] if title else "録画 %s" % (info.get("recording") or "?")
    return {"kind": "afterStream", "kindLabel": KIND_LABELS["afterStream"],
            "text": "%s: 配信後の自動の切り抜きに失敗しました: %s" % (name, _reason(a.get("message")) or "理由が分かりません")}


class Reader:
    """まとめて実行の記録(autorun-runs.jsonl)を、変わったときだけ読み直す(帯は数秒ごとに問い合わせるため)。-> {run の id: 記録}"""

    def __init__(self, runs_log):
        self.runs_log = runs_log
        self._lock = threading.Lock()
        self._key = None
        self._runs = {}

    def runs(self):
        if not self.runs_log:
            return {}
        key = []
        for p in (self.runs_log, self.runs_log + ".1"):
            try:
                st = os.stat(p)
                key.append((st.st_mtime_ns, st.st_size))
            except OSError:
                key.append(None)
        key = tuple(key)
        with self._lock:
            if key != self._key:
                import autorun   # 記録の読み方は 1 か所(read_runs_log)。ここで読むのは、live だけを読むテストで要らないため
                recs = autorun.read_runs_log(self.runs_log, RUNS_READ_BYTES)
                self._runs = {r["id"]: r for r in recs if isinstance(r, dict) and isinstance(r.get("id"), str)}
                self._key = key
            return self._runs


def collect(jobs, runs, now=None, window=WINDOW_SEC, limit=MAX_LIST):
    """書き出しのジョブの一覧(exports.json の jobs)と まとめて実行の記録({id: 記録})-> 失敗の一覧(新しい順。window 秒より古いものは入れない)。
    各要素 {"jobId", "recorder", "recording", "markId", "runId", "kind", "kindLabel", "text", "at"(ISO)}"""
    import live_export   # ここで読む(live_export がこのモジュールを読むので、循環を避ける)
    out = []
    for j in jobs or []:
        if not isinstance(j, dict):
            continue
        f = failure_of(j, runs.get(j.get("runId")) if j.get("runId") else None)
        if f is None:
            continue
        at = j.get("updated") or j.get("created") or ""
        t = live_export.iso_epoch(at)
        if now is not None and t is not None and now - t > window:
            continue
        out.append(dict(f, jobId=j.get("id"), recorder=j.get("recorder"), recording=j.get("recording"), markId=j.get("markId"),
                        runId=j.get("runId") or "", at=at))
    out.sort(key=lambda x: x["at"], reverse=True)
    return out[:limit] if limit else out


def read_jobs(store_dir):
    """入口の作業データの live/exports.json のジョブ(読むだけ。無い・読めないときは [])"""
    import live_export
    try:
        d = fsio.read_json_file(os.path.join(store_dir, "exports.json"), 8 * 1024 * 1024)
    except (OSError, ValueError):
        return []
    jobs = d.get("jobs") if isinstance(d, dict) and d.get("schema") == live_export.JOBS_SCHEMA else None
    return [j for j in jobs if isinstance(j, dict)] if isinstance(jobs, list) else []
