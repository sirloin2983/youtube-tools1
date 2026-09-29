"""まとめて実行(統合計画の段階5。2026-09-26)。入口の「案件」の画面から、配信1本ぶんの作業を順に自動で流す。

形は3つ(ユーザー決定「選べるようにする」):
  full        解析から全部   … (未解析なら)解析 → 自動マークの上位を採用 → 書き出し → 文字起こし → Resolve パック
  adopted     採用後を全部   … 採用したマークの書き出し → 文字起こし → Resolve パック(切り抜きの良し悪しは人が決める)
  transcribe  文字起こしまで … 採用したマークの書き出し → 文字起こし(パックは校正してから人が作る)

作り:
- 各ツールの**公開している API を HTTP で呼ぶ**(入口と同じ 127.0.0.1。取り込んだツールは入口のポートの /studio/ など、子プロセスのツールはそのポート)。
  ツールの中の関数を直接呼ばないのは、画面から使うときと同じ検査・同じジョブ管理(重い処理の順番待ち ytt_core.jobs を含む)を通すため。
- どの段も「まだ無いものだけ」作る(書き出し済み・文字起こし済み・パック済みは飛ばす)。途中で止めても、もう一度押せば続きから進む。
  文字起こしの有無は ytt_core.txindex(案件の画面・スタジオのセリフと同じ規則)、パックの有無は cases.find_pack で見る。
- スタジオの ① 探す で選んだ配信(まだスタジオに無い YouTube の配信)は start_new で「解析から全部」に入れる。解析のキューに入れると
  スタジオに配信ができるので、それまでは受け取った題名で進める(docs/followup-2026-09-27.md の 5)。
- 1本ずつ順に処理する(キュー)。同じ配信を2つ同時には入れない。入口を終えると、実行中・順番待ちの分は消える(もう一度押せば続きから)。
- 自動で採用したマークは、人の判定ではないので学習の記録(スタジオの feedback)に入れない(スタジオの /api/video/adopt-top)。
- 解析の設定は既定値(解析の画面の設定はブラウザの中にしか無いため)。書き出しはスタジオの ③ の設定(画質・音量のそろえ方)、
  文字起こしは「編集」(文字起こし)の設定(モデルなど)を使う。パックは、「編集」でカットを決めてあればそのとおり(cut2resolve の spec.keeps。
  作った記録も「編集」に残す = 作り直しの知らせ)、無ければ文字起こしの行だけを残す規則(preset transcript-rows)。どちらも Text+(字幕の元の行が無ければ Text+ なし)。
"""
import http.client
import json
import os
import re
import urllib.parse
import threading
import time
import uuid

from ytt_core import colors, txindex

MODES = {"full": "解析から全部", "adopted": "採用後を全部", "transcribe": "文字起こしまで"}
STEP_LABELS = {"analyze": "解析", "adopt": "採用(自動)", "export": "書き出し", "transcribe": "文字起こし", "pack": "Resolve パック"}
MODE_STEPS = {"full": ("analyze", "adopt", "export", "transcribe", "pack"), "adopted": ("export", "transcribe", "pack"),
              "transcribe": ("export", "transcribe"), "doc": ("transcribe", "pack")}
# 文書単位の実行(docs/edit-tool-design.md の 12 ⑦(b)): 「編集」の履歴で選んだ文書を、行が無ければ文字起こし → パック。
# カットがある文書はカットのとおり(ユーザー決定 2026-09-27。配信単位の実行と同じ)。パックがあるときは既定で飛ばす(overwrite で上書き)
# 状態の言葉(気が利く画面へ 段4。どの入口の画面もこの言葉で出す = snapshot の labels)
STEP_STATE_LABELS = {"wait": "待ち", "run": "実行中", "done": "済み", "skip": "飛ばした", "warn": "一部失敗", "error": "失敗"}
RUN_STATE_LABELS = {"queued": "待ち", "running": "実行中", "done": "済み", "error": "失敗", "cancelled": "中止", "nothing": "やることがありませんでした"}
NOTHING_MESSAGE = "やることがありませんでした"
DOC_MODE = "doc"
MAX_MARKS = 50   # マークを選んだ実行で選べる数(スタジオの書き出しの1回の上限と同じ)
DOC_LABEL = "文字起こし → パック"
DEFAULT_TOP = 3
MAX_NEW = 10           # ① 探す から一度に入れられる配信の数(① 探す で選べる最大と同じ)
MAX_KEEP = 30          # 終わった記録を残す数
MAX_WAITING = 20       # 順番待ちの上限
BUSY_WAIT = 5.0        # スタジオの書き出しが別の書き出しで塞がっているときの待ち間隔
TX_KEYS = ("model", "language", "quality", "device", "vadMode", "boost", "autoDict", "wordSplit", "stripPunct", "autoGloss", "autoLearned", "glossary",
           "autoRedo", "redoLarge")   # autoRedo・redoLarge = 疑わしい所を自動で認識し直す(12 ③-2)


class Cancelled(Exception):
    pass


class StepError(Exception):
    pass


class ToolClient:
    """ツールの API を呼ぶ。endpoint(ツールID) -> (ポート, 場所 "/studio/" など) か None(動いていない)"""

    def __init__(self, endpoint, token="", timeout=60):
        self.endpoint, self.token, self.timeout = endpoint, token, timeout

    def call(self, tool, method, path, body=None):
        """-> (HTTP の状態, JSON)。つながらない・動いていないときは StepError"""
        ep = self.endpoint(tool)
        if not ep:
            raise StepError("%s が動いていません(入口の画面で状態を確かめてください)" % {"studio": "切り抜きスタジオ", "transcribe": "編集",
                                                                                     "cut2resolve": "cut2resolve"}.get(tool, tool))
        port, base = ep
        url = base.rstrip("/") + path
        headers = {"Host": "127.0.0.1:%d" % port}
        data = None
        if body is not None:
            data = json.dumps(body, ensure_ascii=False).encode("utf-8")
            headers["Content-Type"] = "application/json"
        if method != "GET" and self.token:
            headers["X-YTT-Token"] = self.token
        conn = http.client.HTTPConnection("127.0.0.1", port, timeout=self.timeout)
        try:
            conn.request(method, url, body=data, headers=headers)
            r = conn.getresponse()
            raw = r.read()
        except OSError as e:
            raise StepError("ツールにつながりませんでした(%s)" % (e.strerror or e.__class__.__name__))
        finally:
            conn.close()
        try:
            obj = json.loads(raw.decode("utf-8")) if raw else {}
        except ValueError:
            obj = {}
        return r.status, obj if isinstance(obj, dict) else {}

    def ok(self, tool, method, path, body=None):
        st, obj = self.call(tool, method, path, body)
        if st != 200:
            raise StepError(obj.get("message") or "エラー(HTTP %d)" % st)
        return obj


def _yt_id_ok(v):
    """YouTube の配信 ID(11文字。スタジオの common.VID_RE と同じ)"""
    return isinstance(v, str) and len(v) == 11 and all(c.isascii() and (c.isalnum() or c in "-_") for c in v)


def _doc_id_ok(v):
    return isinstance(v, str) and 1 <= len(v) <= 40 and all(c.isalnum() or c in "-_" for c in v)


class Run:
    def __init__(self, video_id, title, mode, top, doc_id=None, overwrite=False, streamer=None, marks=None, fresh=None, on_fail="next"):
        self.id = uuid.uuid4().hex[:10]
        self.video_id, self.title, self.mode, self.top = video_id, title, mode, top
        self.doc_id, self.overwrite = doc_id, bool(overwrite)   # overwrite = パックがあれば作り直す(文書単位も配信単位も。段4 S-12)
        self.on_fail = on_fail if on_fail in ("next", "stop") else "next"   # 切り抜きの1本が失敗したとき: next = 残りを続ける / stop = そこで止める
        self.nothing = False       # どの段もやることが無かった(「完了」と言わない。段4 S-4)
        self.docs = []             # この実行で文字起こし・パックした文書の id(終わったら「校正を始める」で開く。段4)
        self.streamer_from = None  # 配信者を自動で決めたときの出どころ(doc / video / channel = 覚えた名前・auto = チャンネル名から。段5)
        self.streamer = streamer   # 字幕の文字の色にする配信者(照らし合わせ済みの名前。手で入れたときだけ。docs/followup-2026-09-27.md の 4)
        self.marks = marks         # このマークだけ(スタジオのマークの行の「この後を」。None = 配信の全部。docs/followup-2026-09-27.md の 3)
        self.fresh = fresh         # ① 探す から: {"title", "channel"}(まだスタジオに無いかもしれない配信。解析のキューに入れるときに渡す)
        self.state = "queued"
        self.message = "順番待ち"
        self.error = ""
        self.created = time.time()
        self.finished = None
        self.cancel = False
        self.steps = [{"key": k, "label": STEP_LABELS[k], "state": "wait", "detail": ""} for k in MODE_STEPS[mode]]

    def step(self, key):
        return next(s for s in self.steps if s["key"] == key)

    def public(self):
        return {"id": self.id, "kind": "doc" if self.doc_id else "video", "docId": self.doc_id, "overwrite": self.overwrite,
                "videoId": self.video_id, "title": self.title, "mode": self.mode,
                "modeLabel": MODES.get(self.mode, DOC_LABEL) + ("(%d本)" % len(self.marks) if self.marks else ""), "top": self.top,
                "streamer": self.streamer, "streamerFrom": self.streamer_from, "marks": list(self.marks) if self.marks else None, "fromSearch": bool(self.fresh),
                "state": self.state, "stateLabel": RUN_STATE_LABELS["nothing" if self.nothing and self.state == "done" else self.state],
                "nothing": self.nothing, "onFail": self.on_fail, "docs": list(self.docs[:20]),
                "message": self.message, "error": self.error, "created": int(self.created * 1000),
                "finished": int(self.finished * 1000) if self.finished else None,
                "steps": [dict(s, stateLabel=STEP_STATE_LABELS.get(s["state"], s["state"])) for s in self.steps]}


class AutoRunner:
    def __init__(self, client, repo_root, env=None, poll=1.0, sleep=None, find_pack=None, prefs=None):
        self.client, self.root, self.env, self.poll = client, repo_root, env, poll
        self.prefs = prefs   # ホームの設定(home/prefs.py)。カットの無い文書のカットの方法 autorun.cut
        self.sleep = sleep or time.sleep
        if find_pack is None:
            import cases   # home/cases.py(パックの有無の見方を案件の画面とそろえる)
            find_pack = cases.find_pack
        self.find_pack = find_pack
        self.lock = threading.Lock()
        self.cv = threading.Condition(self.lock)
        self.runs = []
        self.thread = None
        self.closed = False

    # ------------------------------------------------------------ 受付
    def _streamer(self, name):
        """まとめて実行の画面で入れた配信者の名前 -> 照らし合わせた名前。None(指定なし)= 自動(パックのときに覚えた名前・チャンネル名から。段5)・
        ""(空で送った)= 色なし。見つからなければ始める前に断る(ValueError)"""
        if name is None:
            return None
        if isinstance(name, str) and not name.strip():
            return ""
        who, _hex = colors.resolve(name if isinstance(name, str) else "", env=self.env)
        return who

    def _auto_streamer(self, run, doc=None, v=None):
        """指定の無い実行の配信者を決める(1回だけ。段5): 覚えた名前(文書 → 配信 → チャンネル)→ チャンネル名から。決めた名前は進み具合に出す"""
        if run.streamer is not None:
            return
        import prefs as prefs_mod
        clip = (doc or {}).get("clip") or {}
        vid = run.video_id or ((clip.get("source") or {}).get("videoId") if isinstance(clip.get("source"), dict) else None)
        ch = (v or {}).get("channel") or (run.fresh or {}).get("channel")
        if vid and not ch:
            import cases
            ch = (cases.read_studio(cases.locations(self.root, self.env)["studio"]).get(vid) or {}).get("channel")
        r = prefs_mod.guess_streamer(self.prefs, (doc or {}).get("id") or run.doc_id, vid, ch or None,
                                     from_channel=lambda c: (colors.from_channel(c, env=self.env) or {}).get("name"))
        run.streamer = r["name"] or ""
        run.streamer_from = r["source"] if r["name"] else None

    @staticmethod
    def _marks_arg(marks):
        """スタジオのマークの行から: このマークだけ進める(-> 重ならない id の組 / None = 配信の全部)"""
        if marks in (None, []):
            return None
        if not isinstance(marks, list) or len(marks) > MAX_MARKS or not all(
                isinstance(m, str) and 1 <= len(m) <= 40 and all(c.isascii() and (c.isalnum() or c in "-_") for c in m) for m in marks):
            raise ValueError("マークの指定が正しくありません")
        return tuple(dict.fromkeys(marks))

    def _pref(self, key, default=None):
        """ホームの設定 autorun の値(home/prefs.py。読めなければ default)"""
        try:
            v = (self.prefs.get(["autorun"])["autorun"] or {}).get(key) if self.prefs else None
        except (OSError, ValueError, KeyError):
            v = None
        return default if v is None else v

    def start(self, video_id, mode, top=None, streamer=None, marks=None, overwrite=False):
        if not isinstance(video_id, str) or not (1 <= len(video_id) <= 64) or not all(c.isalnum() or c in "-_" for c in video_id):
            raise ValueError("配信の指定が正しくありません")
        if mode not in MODES:
            raise ValueError("実行の形が正しくありません")
        if top in (None, ""):
            top = DEFAULT_TOP
        if not isinstance(top, int) or isinstance(top, bool) or not (1 <= top <= 30):
            raise ValueError("採用する数は1〜30です")
        who = self._streamer(streamer)
        mk = self._marks_arg(marks)
        if mk and mode == "full":
            raise ValueError("マークを選んだまとめて実行は「採用後を全部」「文字起こしまで」だけです")
        with self.cv:
            active = [r for r in self.runs if r.state in ("queued", "running")]
            if any(r.video_id == video_id for r in active):
                raise ValueError("この配信はすでに実行中・順番待ちです")
            if len(active) >= MAX_WAITING:
                raise ValueError("順番待ちが多すぎます(%d本まで)" % MAX_WAITING)
            run = Run(video_id, "", mode, top, streamer=who, marks=mk, overwrite=overwrite, on_fail=self._pref("onFail", "next"))
            self.runs.append(run)
            self._trim()
            self._wake()
            return run.public()

    def start_new(self, items, top=None, streamer=None):
        """スタジオの ① 探す で選んだ配信を「解析から全部」で(docs/followup-2026-09-27.md の 5)。まだスタジオに無い配信でもよい。
        items = [{"id": YouTube の配信 ID, "title", "channel"}]。配信ごとに1つの実行。すでに実行中・順番待ちの配信は飛ばす。
        -> {"runs": [作った実行], "skipped": [{"id", "title", "reason"}]}"""
        if not isinstance(items, list) or not items or len(items) > MAX_NEW:
            raise ValueError("配信は 1〜%d 本で選んでください" % MAX_NEW)
        if top in (None, ""):
            top = DEFAULT_TOP
        if not isinstance(top, int) or isinstance(top, bool) or not (1 <= top <= 30):
            raise ValueError("採用する数は1〜30です")
        who = self._streamer(streamer)
        made, skipped, seen = [], [], set()
        with self.cv:
            active = [r for r in self.runs if r.state in ("queued", "running")]
            for it in items:
                it = it if isinstance(it, dict) else {}
                vid, title = it.get("id"), str(it.get("title") or "").strip()[:120]
                channel = str(it.get("channel") or "").strip()[:100]
                if not _yt_id_ok(vid):
                    skipped.append({"id": str(vid or "")[:40], "title": title, "reason": "配信の指定が正しくありません"})
                elif vid in seen or any(r.video_id == vid for r in active):
                    skipped.append({"id": vid, "title": title, "reason": "すでに実行中・順番待ちです"})
                elif len(active) >= MAX_WAITING:
                    skipped.append({"id": vid, "title": title, "reason": "順番待ちが多すぎます(%d本まで)" % MAX_WAITING})
                else:
                    seen.add(vid)
                    run = Run(vid, title or vid, "full", top, streamer=who, fresh={"title": title, "channel": channel}, on_fail=self._pref("onFail", "next"))
                    self.runs.append(run)
                    active.append(run)
                    made.append(run.public())
            if made:
                self._trim()
                self._wake()
        return {"runs": made, "skipped": skipped}

    def start_docs(self, ids, overwrite=False, streamer=None):
        """「編集」の履歴で選んだ文書をまとめて(⑦(b))。文書ごとに1つの実行(順番待ち・中止・状態は配信単位の実行と同じ)。
        同じ文書がもう実行中・順番待ちなら断る(二重の登録)。-> {"runs": [作った実行], "skipped": [{"id", "title", "reason"}]}"""
        if not isinstance(ids, list) or not ids or len(ids) > MAX_WAITING:
            raise ValueError("文書は 1〜%d 本で選んでください" % MAX_WAITING)
        who = self._streamer(streamer)
        docs = {d["id"]: d for d in txindex.load(txindex.folder(self.root, self.env))}
        made, skipped = [], []
        with self.cv:
            active = [r for r in self.runs if r.state in ("queued", "running")]
            for tid in dict.fromkeys(i for i in ids if isinstance(i, str)):
                d = docs.get(tid) if _doc_id_ok(tid) else None
                if not d:
                    skipped.append({"id": str(tid)[:40], "title": "", "reason": "文書が見つかりません"})
                elif any(r.doc_id == tid for r in active):
                    skipped.append({"id": tid, "title": d["title"], "reason": "すでに実行中・順番待ちです"})
                elif len(active) >= MAX_WAITING:
                    skipped.append({"id": tid, "title": d["title"], "reason": "順番待ちが多すぎます(%d本まで)" % MAX_WAITING})
                else:
                    run = Run(None, d["title"] or tid, DOC_MODE, None, doc_id=tid, overwrite=overwrite, streamer=who, on_fail=self._pref("onFail", "next"))
                    self.runs.append(run)
                    active.append(run)
                    made.append(run.public())
            if made:
                self._trim()
                self._wake()
        return {"runs": made, "skipped": skipped}

    # ------------------------------------------------------------ 見積もり(気が利く画面へ 段4)
    def estimate(self, video_id=None, mode=None, marks=None, top=None, doc_ids=None, overwrite=False):
        """実行と同じ規則で、段ごとの本数と飛ばす理由を返す(何も書き込まない)。実行は実行したときの状態で決めるので、ずれることがある。
        -> {"steps": [{"key", "label", "count" (None = 前の段の結果しだい), "note"}], "total": 分かっている本数の合計, "nothing": bool, "reason"}"""
        docs = txindex.load(txindex.folder(self.root, self.env))
        if doc_ids is not None:   # 文書単位(文字起こし → パック)
            if not isinstance(doc_ids, list) or not doc_ids or len(doc_ids) > MAX_WAITING:
                raise ValueError("文書は 1〜%d 本で選んでください" % MAX_WAITING)
            by = {d["id"]: d for d in docs}
            tx, pk, notes = 0, 0, []
            for tid in dict.fromkeys(i for i in doc_ids if isinstance(i, str)):
                d = by.get(tid) if _doc_id_ok(tid) else None
                if not d:
                    notes.append("見つからない文書があります")
                    continue
                if not d["count"]:
                    tx += 1
                    pk += 1
                elif overwrite or not self.find_pack(d.get("sourcePath") or ""):
                    pk += 1
            steps = [{"key": "transcribe", "label": STEP_LABELS["transcribe"], "count": tx, "note": "" if tx else "文字起こし済み"},
                     {"key": "pack", "label": STEP_LABELS["pack"], "count": pk, "note": "" if pk else "パック済み(「パックがあれば作り直す(上書き)」を選ぶと作り直します)"}]
            return self._estimate_out(steps, notes)
        if mode not in MODES:
            raise ValueError("実行の形が正しくありません")
        st, obj = self.client.call("studio", "GET", "/api/video?id=" + urllib.parse.quote(str(video_id or "")))
        v = (obj.get("video") or {}) if st == 200 and isinstance(obj, dict) else {}
        run = Run(video_id, "", mode, top or DEFAULT_TOP, marks=self._marks_arg(marks))
        mine = self._mine(run, v)
        adopted = [m for m in mine if m.get("status") == "adopted"]
        clips = self._clips(v, run)
        no_tx = [m for m in clips if not txindex.pick(docs, video_id, m.get("id"), m["path"])[0]]
        packable = [m for m in clips if m not in no_tx and (overwrite or not self.find_pack(m["path"]))]
        steps = []
        pending = False   # 前の段の結果しだい(解析・採用のあとで本数が決まる)
        for key in MODE_STEPS[mode]:
            label, count, note = STEP_LABELS[key], 0, ""
            if key == "analyze":
                count, note = (0, "解析済み") if v.get("analysis") else (1, "")
                pending = pending or count > 0
            elif key == "adopt":
                if any(m.get("status") in ("adopted", "exported") for m in mine):
                    note = "採用・書き出し済みのマークを使います"
                elif pending:
                    count, note = None, "解析のあとで、点数の高い %d 件" % (top or DEFAULT_TOP)
                else:
                    cands = [m for m in mine if not m.get("status")]
                    count = min(len(cands), top or DEFAULT_TOP)
                    note = "" if count else "採用できる候補がありません"
                pending = pending or count is None or bool(count)
            elif key == "export":
                count = None if pending and not adopted else len(adopted)
                note = "" if count else ("採用のあとで決まります" if count is None else "採用したマークがありません" if not clips else "書き出し済み %d 本" % len(clips))
                pending = pending or bool(count)
            elif key == "transcribe":
                count = None if pending else len(no_tx)
                note = "書き出しのあとで決まります" if count is None else ("" if count else ("%d 本とも文字起こし済み" % len(clips) if clips else "書き出した切り抜きがありません"))
                pending = pending or bool(count)
            elif key == "pack":
                count = None if pending else len(packable)
                note = "文字起こしのあとで決まります" if count is None else ("" if count else ("パック済み(「パックがあれば作り直す(上書き)」を選ぶと作り直します)" if clips else "文字起こしのある切り抜きがありません"))
            steps.append({"key": key, "label": label, "count": count, "note": note})
        return self._estimate_out(steps, [] if st == 200 else ["配信がスタジオに見つかりません"])

    @staticmethod
    def _estimate_out(steps, notes):
        known = [s["count"] for s in steps if s["count"] is not None]
        nothing = all(s["count"] == 0 for s in steps)
        reason = "・".join([s["note"] for s in steps if s["note"]] + notes) if nothing else ""
        return {"steps": steps, "total": sum(known), "nothing": nothing, "reason": reason, "notes": notes}

    def _wake(self):
        """順番待ちを動かす(呼ぶのは self.cv を持っている間)"""
        self.cv.notify_all()
        if self.thread is None or not self.thread.is_alive():
            self.thread = threading.Thread(target=self._loop, name="autorun", daemon=True)
            self.thread.start()

    def cancel(self, run_id):
        with self.cv:
            run = next((r for r in self.runs if r.id == run_id), None)
            if run is None:
                raise ValueError("その実行はありません")
            if run.state == "queued":
                run.state, run.message, run.finished = "cancelled", "中止しました", time.time()
            elif run.state == "running":
                run.cancel = True
                run.message = "中止しています…"
            return run.public()

    def snapshot_labels(self):
        return {"step": STEP_STATE_LABELS, "run": RUN_STATE_LABELS}

    def snapshot(self):
        with self.cv:
            return {"runs": [r.public() for r in reversed(self.runs)], "modes": MODES}

    def close(self):
        """入口の終了: 順番待ちを消し、実行中の分に中止を伝える(ツールの側のジョブもこの後の終了処理で止まる)"""
        with self.cv:
            self.closed = True
            for r in self.runs:
                if r.state == "queued":
                    r.state, r.message = "cancelled", "入口を終了しました"
                elif r.state == "running":
                    r.cancel = True
            self.cv.notify_all()

    def _trim(self):
        done = [r for r in self.runs if r.state not in ("queued", "running")]
        for r in done[:-MAX_KEEP] if len(done) > MAX_KEEP else []:
            self.runs.remove(r)

    def _loop(self):
        while True:
            with self.cv:
                while not self.closed and not any(r.state == "queued" for r in self.runs):
                    self.cv.wait(5)
                if self.closed:
                    return
                run = next(r for r in self.runs if r.state == "queued")
                run.state, run.message = "running", ""
            try:
                self._execute(run)
                run.state = "cancelled" if run.cancel else "done"
                run.message = "中止しました" if run.cancel else (run.message or "完了")
            except Cancelled:
                run.state, run.message = "cancelled", "中止しました"
            except StepError as e:
                run.state, run.error, run.message = "error", str(e), "止まりました"
            except Exception as e:   # 想定外でも、次の配信の処理は続ける
                run.state, run.error, run.message = "error", "内部エラー: %s %s" % (e.__class__.__name__, str(e)[:200]), "止まりました"
            finally:
                run.finished = time.time()
                for s in run.steps:
                    if s["state"] == "run":
                        s["state"] = "error" if run.state == "error" else "skip"
                with self.cv:
                    self._trim()

    # ------------------------------------------------------------ 実行
    def _check(self, run):
        if run.cancel or self.closed:
            raise Cancelled()

    def _wait(self, run, seconds=None):
        self._check(run)
        self.sleep(self.poll if seconds is None else seconds)
        self._check(run)

    def _video(self, run):
        st, obj = self.client.call("studio", "GET", "/api/video?id=" + run.video_id)
        if st == 404 and run.fresh:   # ① 探す から: 解析のキューに入れるまではスタジオに無い(受け取った題名で進める)
            return {"kind": "youtube", "title": run.title}
        if st != 200:
            raise StepError(obj.get("message") or "エラー(HTTP %d)" % st)
        v = obj.get("video") or {}
        run.title = str(v.get("title") or v.get("fileName") or run.video_id)[:120]
        return v

    def _execute(self, run):
        if run.doc_id:
            return self._execute_doc(run)
        v = self._video(run)
        for key in MODE_STEPS[run.mode]:
            self._check(run)
            st = run.step(key)
            st["state"] = "run"
            run.message = st["label"]
            result = getattr(self, "_step_" + key)(run, st, v)
            if st["state"] == "run":
                st["state"] = "done"
            v = self._video(run)
            if result == "stop":   # 続けても意味がない(採用するマークが無いなど)
                for s in run.steps:
                    if s["state"] == "wait":
                        s["state"], s["detail"] = "skip", s["detail"] or "前の段で止めました"
                break
        self._finish_message(run)

    def _finish_message(self, run):
        """どの段も飛ばした = やることが無かった(「完了」と言わない。段4 S-4)"""
        if all(s["state"] == "skip" for s in run.steps):
            run.nothing = True
            run.message = NOTHING_MESSAGE + (": " + run.message if run.message and run.message != "完了" else "")
        elif not run.message or run.message in [s["label"] for s in run.steps]:
            run.message = "完了"

    # 解析 -------------------------------------------------------
    def _step_analyze(self, run, st, v):
        if v.get("analysis"):
            st["state"], st["detail"] = "skip", "解析済み"
            return None
        item = {"kind": v.get("kind") or "youtube", "videoId": run.video_id}
        if run.fresh and item["kind"] == "youtube":   # ① 探す から: 題名・配信者はスタジオの一覧にそのまま出る(解析の前に分かっている分)
            item.update({k: run.fresh[k] for k in ("title", "channel") if run.fresh.get(k)})
        if item["kind"] == "file":
            import cases
            path = (cases.read_studio(cases.locations(self.root, self.env)["studio"]).get(run.video_id) or {}).get("path")
            if not path:
                raise StepError("元の動画ファイルの場所が分かりません")
            item = {"kind": "file", "path": path}
        # 解析の設定はスタジオの画面で保存したもの(/api/settings の settings.analyze。段階7-1)。無ければスタジオの既定値
        saved = (self.client.ok("studio", "GET", "/api/settings").get("settings") or {}).get("analyze")
        saved = saved if isinstance(saved, dict) else {}
        res = self.client.ok("studio", "POST", "/api/queue/add", {"items": [item], "settings": saved})
        added = res.get("added") or []
        qid = added[0]["qid"] if added else None
        if not qid:
            rej = (res.get("rejected") or [{}])[0].get("reason") or ""
            if "すでにキュー" not in rej:
                raise StepError("解析を始められませんでした: %s" % (rej or "理由不明"))
        st["detail"] = "解析中(%s)" % ("スタジオで保存した解析の設定" if saved else "解析の設定は既定値。スタジオの ② で設定を変えると次から使います")
        while True:
            self._wait(run)
            items = self.client.ok("studio", "GET", "/api/queue").get("items") or []
            it = next((i for i in items if (i.get("qid") == qid if qid else i.get("videoId") == run.video_id)), None)
            if it is None:
                raise StepError("解析のキューから消えました")
            st["detail"] = "%s %d%%" % (it.get("phase") or "", round((it.get("progress") or 0) * 100))
            if it.get("status") == "done":
                st["detail"] = "解析しました(候補 %s 件)" % it.get("marks", "?")
                return None
            if it.get("status") in ("error", "cancelled", "skipped"):
                raise StepError("解析が終わりませんでした: %s" % (it.get("error") or it.get("status")))

    # 採用 -------------------------------------------------------
    def _step_adopt(self, run, st, v):
        res = self.client.ok("studio", "POST", "/api/video/adopt-top", {"id": run.video_id, "top": run.top})
        ids = res.get("adopted") or []
        marks = (res.get("video") or {}).get("marks") or []
        if ids:
            st["detail"] = "点数の高い %d 件を採用しました" % len(ids)
            return None
        if any(m.get("status") in ("adopted", "exported") for m in marks):
            st["state"], st["detail"] = "skip", "採用・書き出し済みのマークがあるので、それを使います"
            return None
        st["state"], st["detail"] = "skip", "採用できる候補がありません"
        run.message = "採用できる候補がありませんでした"
        return "stop"

    # 書き出し ---------------------------------------------------
    def _export_body(self, run, ids):
        rv = (self.client.ok("studio", "GET", "/api/settings").get("settings") or {}).get("review") or {}
        n = lambda x, lo, hi, d: x if isinstance(x, (int, float)) and not isinstance(x, bool) and lo <= x <= hi else d
        loud = rv.get("exportLoudness", -14)
        return {"id": run.video_id, "markIds": ids, "precision": "fast" if rv.get("precision") == "fast" else "accurate",
                "maxHeight": rv.get("maxHeight") if rv.get("maxHeight") in (0, 720, 1080, 1440, 2160) else 1080,
                "volume": int(n(rv.get("exportVolume"), 1, 200, 75)), "loudness": loud if loud in (-11, -14, -16, -18) else None}

    def _mine(self, run, v):
        """この実行で扱うマーク(マークを選んだ実行ならそれだけ)"""
        return [m for m in v.get("marks") or [] if not run.marks or m.get("id") in run.marks]

    def _step_export(self, run, st, v):
        ids = [m["id"] for m in self._mine(run, v) if m.get("status") == "adopted"]
        if not ids:
            done = sum(1 for m in self._mine(run, v) if m.get("status") == "exported")
            st["state"], st["detail"] = "skip", ("書き出し済み %d 本(新しく採用したものはありません)" % done if done else "採用したマークがありません")
            return None if done else "stop"
        body = self._export_body(run, ids[:50])
        while True:
            status, res = self.client.call("studio", "POST", "/api/export", body)
            if status == 200:
                break
            if status == 409 and res.get("error") == "busy":
                st["detail"] = "別の書き出しが終わるのを待っています"
                self._wait(run, BUSY_WAIT)
                continue
            raise StepError("書き出しを始められませんでした: %s" % (res.get("message") or "HTTP %d" % status))
        jid = res.get("id")
        try:
            while True:
                self._wait(run)
                j = self.client.ok("studio", "GET", "/api/export?id=" + jid)
                items = j.get("items") or []
                done = sum(1 for i in items if i.get("status") == "done")
                st["detail"] = ("他のツールの重い処理を待っています" if j.get("waiting") else "%d / %d 本" % (done, len(items)))
                if j.get("state") != "running":
                    break
        except Cancelled:
            self.client.call("studio", "POST", "/api/export/cancel", {"id": jid})
            raise
        bad = [i for i in items if i.get("status") == "error"]
        st["detail"] = "%d 本を書き出しました" % done + ("(%d 本失敗)" % len(bad) if bad else "")
        if bad and (not done or run.on_fail == "stop"):
            raise StepError("書き出しに失敗しました(%d 本): %s" % (len(bad), bad[0].get("error") or ""))
        if bad:
            st["state"] = "warn"
        return None

    # 文字起こし -------------------------------------------------
    def _clips(self, v, run=None):
        return [m for m in (self._mine(run, v) if run else v.get("marks") or []) if m.get("status") == "exported" and isinstance(m.get("path"), str) and m["path"]
                and os.path.isfile(m["path"])]

    def _step_transcribe(self, run, st, v):
        clips = self._clips(v, run)
        if not clips:
            st["state"], st["detail"] = "skip", "書き出した切り抜きがありません"
            return "stop"
        docs = txindex.load(txindex.folder(self.root, self.env))
        todo = [m for m in clips if not txindex.pick(docs, run.video_id, m.get("id"), m["path"])[0]]
        if not todo:
            st["state"], st["detail"] = "skip", "%d 本とも文字起こし済み" % len(clips)
            return None
        opts = self.client.ok("transcribe", "GET", "/api/settings")
        opts = {k: opts[k] for k in TX_KEYS if k in opts and isinstance(opts[k], (str, bool, int, float))}
        jobs = []
        try:
            for m in todo:
                self._check(run)
                res = self.client.ok("transcribe", "POST", "/api/transcribe", dict(opts, sourcePath=m["path"]))
                jobs.append(res.get("id"))
            while True:
                self._wait(run)
                all_jobs = {j.get("id"): j for j in self.client.ok("transcribe", "GET", "/api/jobs").get("jobs") or []}
                mine = [all_jobs.get(j) or {"state": "error", "error": "文字起こしのジョブが見つかりません"} for j in jobs]
                fin = [j for j in mine if j.get("state") in ("done", "error", "cancelled")]
                cur = next((j for j in mine if j.get("state") not in ("done", "error", "cancelled", "queued")), None)
                st["detail"] = "%d / %d 本" % (len(fin), len(jobs)) + (" ・ %s %d%%" % (cur.get("phase") or "", round((cur.get("progress") or 0) * 100)) if cur else "")
                if len(fin) == len(jobs):
                    break
        except Cancelled:
            for j in jobs:
                self.client.call("transcribe", "POST", "/api/transcribe/cancel", {"id": j})
            raise
        ok = [j for j in mine if j.get("state") == "done"]
        bad = [j for j in mine if j.get("state") != "done"]
        run.docs += [j["tid"] for j in ok if j.get("tid") and j["tid"] not in run.docs]
        st["detail"] = "%d 本を文字起こししました" % len(ok) + ("(%d 本失敗)" % len(bad) if bad else "") + "。字幕の校正は文字起こしの画面で"
        if bad and (not ok or run.on_fail == "stop"):
            raise StepError("文字起こしに失敗しました(%d 本): %s" % (len(bad), bad[0].get("error") or bad[0].get("state")))
        if bad:
            st["state"] = "warn"
        return None

    # パック -----------------------------------------------------
    def _edit_keeps(self, doc):
        """「編集」のカット(残す区間の秒。接している区間 = 分割しただけの所は1つに)と rev。無い・読めなければ (None, 0)"""
        status, res = self.client.call("transcribe", "GET", "/api/edit?id=" + urllib.parse.quote(str(doc["id"])))
        e = res.get("edit") if status == 200 and isinstance(res, dict) else None
        clips = e.get("clips") if isinstance(e, dict) else None
        if not clips:
            return None, 0
        out = []
        for c in clips:
            a, b = float(c["in"]), float(c["out"])
            if out and a <= out[-1][1] + 1e-9:
                out[-1][1] = max(out[-1][1], b)
            else:
                out.append([a, b])
        return out, int(res.get("rev") or 0)

    def _pack_settings(self):
        """パックの作り方(編集の設定 = 3 パック のタブと同じ値。気が利く画面へ 段4 = 以前は fps・縦横・予備・話者の色を無視していた):
        行から作るときの端の広げ方(rowEdge。形が変なら既定で作って知らせる)・Text+ の置き先(packFps・packSize)・1段の文字数(縦横に合わせる)・
        話者の色・音量・予備(packBackup)・無音で削るときの値(cutSilence)。-> (rowEdge, output に足すもの, cutSilence, 知らせ)"""
        tx_settings = self.client.ok("transcribe", "GET", "/api/settings")
        notes = []
        row_edge = tx_settings.get("rowEdge")
        if row_edge is not None and not _row_edge_ok(row_edge):
            notes.append("「行から」の設定の形が正しくないので、既定の広げ方で作りました(「編集」の 2 カット の「行から ▾」で直せます)")
            row_edge = None
        size = tx_settings.get("packSize") if tx_settings.get("packSize") in ("1080x1920", "1920x1080") else "1080x1920"
        fps = str(tx_settings.get("packFps") or "30")
        sub = tx_settings.get("subtitle") if isinstance(tx_settings.get("subtitle"), dict) else {}
        wrap = (sub.get("wrapChars") or {}).get("horizontal" if size == "1920x1080" else "vertical") if isinstance(sub.get("wrapChars"), dict) else None
        wrap_out = {"textplusWrap": wrap} if isinstance(wrap, int) and not isinstance(wrap, bool) and 0 <= wrap <= 40 else {}
        wrap_out["textplusSize"] = size
        if re.fullmatch(r"\d{1,3}(\.\d{1,3})?", fps):
            wrap_out["textplusFps"] = fps
        if tx_settings.get("packBackup") is True:
            wrap_out["backup"] = True
        wrap_out["speakerColors"] = tx_settings.get("speakerColors") is not False   # 話者の名前がメンバーと合えばその色(編集の設定と同じ。以前は無視して常にオン)
        cs = tx_settings.get("cutSilence") if isinstance(tx_settings.get("cutSilence"), dict) else {}
        cut_silence = {k: cs[k] for k in ("noise", "min", "pad") if isinstance(cs.get(k), (int, float)) and not isinstance(cs.get(k), bool)}
        loud = tx_settings.get("packLoudness", -14)   # 聞こえ方の音量をそろえる目標(LUFS。編集の設定 = パックのタブと同じ値。既定 -14・0 = そろえない。2026-09-29)
        if loud in (-11, -14, -16, -18) and not isinstance(loud, bool):
            wrap_out["loudness"] = loud
        else:   # LUFS でそろえないときは音量(%)。元 = 100
            vol = tx_settings.get("packVolume", 100)
            if isinstance(vol, int) and not isinstance(vol, bool) and 1 <= vol <= 200 and vol != 100:
                wrap_out["volume"] = vol
        return row_edge, wrap_out, cut_silence, notes

    def _cut_method(self):
        """カットを決めていない文書のカットの方法(ホームの設定 autorun.cut。読めなければ今までどおり rows)"""
        try:
            m = (self.prefs.get(["autorun"])["autorun"] or {}).get("cut") if self.prefs else None
        except (OSError, ValueError, KeyError):
            m = None
        return m if m in ("rows", "none", "silence") else "rows"

    def _pack_one(self, run, st, doc, media, pack_opts, force=False, prefix=""):
        """1本のパックを cut2resolve で作る。「編集」でカットを決めてあればそのとおり(3 パック のタブのパックと同じ中身)、
        無ければ文字起こしの行だけを残す規則(preset transcript-rows)。-> ("made", カットのとおりか) か ("exists", False)(同じ名前のパックがあり force でない)"""
        row_edge, wrap_out, cut_silence = pack_opts[:3]
        keeps, rev = self._edit_keeps(doc)
        if keeps:
            captions = any(s.get("text", "").strip() and not s.get("cut") for s in doc.get("segments") or [])
            tr = self.client.ok("transcribe", "POST", "/api/export-file", {"id": doc["id"], "format": "transcript-v1"}) if captions else {}
            spec = dict({"video": media, "keeps": keeps}, **({"transcript": tr.get("path")} if captions else {}))
            body = {"spec": spec, "output": dict({"textplus": captions, "copyVideo": True}, **wrap_out)}
        else:   # カットを決めていない文書: カットの方法(ホームの設定。rows = 行から・none = カットしない・silence = 無音で削る)
            tr = self.client.ok("transcribe", "POST", "/api/export-file", {"id": doc["id"], "format": "transcript-v1"})
            method = self._cut_method()
            if method == "none":   # 動画全体(削る区間なし)。カット済の行の字幕も消さない
                spec = {"video": media, "transcript": tr.get("path"), "mode": "list", "listKind": "drop", "listText": "", "dropCutRows": False, "minLen": 0}
            elif method == "silence":   # 無音で削る(値は編集の設定 cutSilence。無ければ cut2resolve の既定)
                spec = {"video": media, "transcript": tr.get("path"), "mode": "silence", "silence": cut_silence}
            else:
                spec = {"video": media, "transcript": tr.get("path"), "preset": "transcript-rows"}
                if isinstance(row_edge, (bool, dict)):
                    spec["rowEdge"] = row_edge
            body = {"spec": spec, "output": dict({"textplus": True}, **wrap_out)}
        if force:
            body["output"]["force"] = True
        self._auto_streamer(run, doc)
        if run.streamer:   # 字幕の文字を配信者のメンバーカラーに(cut2resolve が同じ規則で照らし合わせる)
            body["output"]["streamer"] = run.streamer
        while True:
            status, res = self.client.call("cut2resolve", "POST", "/api/build", body)
            if not (status == 409 and res.get("error") == "busy"):
                break
            st["detail"] = prefix + "cut2resolve の別の処理が終わるのを待っています"
            self._wait(run, BUSY_WAIT)
        if status == 409 and res.get("error") == "exists":
            return "exists", False
        if status != 200:
            raise StepError("パックを作れませんでした: %s" % (res.get("message") or "HTTP %d" % status))
        jid = (res.get("job") or {}).get("id")
        try:
            while True:
                self._wait(run)
                j = self.client.ok("cut2resolve", "GET", "/api/job?id=" + jid)
                if j.get("state") != "running":
                    break
                if j.get("message"):
                    st["detail"] = prefix + j["message"]
        except Cancelled:
            self.client.call("cut2resolve", "POST", "/api/job/cancel", {"id": jid})
            raise
        if j.get("state") != "done":
            err = j.get("error")
            raise StepError("パックを作れませんでした: %s" % ((err.get("message") if isinstance(err, dict) else err) or j.get("state")))
        if keeps:   # 作った記録(packRev)を「編集」に残す(カット・字幕を直したら「作り直し」と知らせるため)。残せなくてもパックはできている
            r = j.get("result") or {}
            self.client.call("transcribe", "POST", "/api/edit/pack", {"id": doc["id"], "rev": rev, "docUpdatedAt": int(doc.get("updatedAt") or 0),
                                                                      "dir": r.get("outDir") or "", "files": [f.get("name") for f in r.get("files") or [] if isinstance(f, dict)]})
        return "made", bool(keeps)

    def _step_pack(self, run, st, v):
        clips = self._clips(v, run)
        docs = txindex.load(txindex.folder(self.root, self.env))
        todo, no_tx, made = [], 0, 0
        for m in clips:
            doc = txindex.pick(docs, run.video_id, m.get("id"), m["path"])[0]
            if not doc:
                no_tx += 1
            elif run.overwrite or not self.find_pack(m["path"]):
                todo.append((m, doc))
        if not todo:
            st["state"], st["detail"] = "skip", ("パック済み(「パックがあれば作り直す(上書き)」を選ぶと作り直します)" if clips and not no_tx else "文字起こしのある切り抜きがありません")
            return None
        skipped, failed, by_edit = [], [], 0
        opts = self._pack_settings()
        self._auto_streamer(run, todo[0][1] if todo else None, v)
        for i, (m, doc) in enumerate(todo, 1):
            self._check(run)
            prefix = "%d / %d 本 ・ " % (i - 1, len(todo))
            st["detail"] = prefix.rstrip(" ・ ")
            try:
                res, cut = self._pack_one(run, st, doc, m["path"], opts, force=run.overwrite, prefix=prefix)
            except StepError as e:
                if run.on_fail == "stop":
                    raise
                failed.append("%s(%s)" % (os.path.basename(m["path"]), str(e)[:120]))   # 次へ進む設定: 残りを続ける
                continue
            if res == "exists":
                skipped.append(os.path.basename(m["path"]))   # 同じ名前のパックがある: 上書きしない(人が作り直したものかもしれない)
                continue
            made += 1
            by_edit += 1 if cut else 0
            if doc["id"] not in run.docs:
                run.docs.append(doc["id"])
        if failed and not made:
            raise StepError("パックを作れませんでした: %s" % failed[0])
        st["detail"] = "%d 本のパックを作りました" % made + ("(うち %d 本は「編集」のカットのとおり)" % by_edit if by_edit else "") + \
            ("。前のパックを上書きしました" if run.overwrite else "") + "。字幕を校正したら「編集」のパックのタブで作り直してください"
        if skipped:
            st["detail"] += "。同じ名前のパックがあるので上書きしなかったもの: %s" % "・".join(skipped[:5])
        if failed:
            st["state"] = "warn"
            st["detail"] += "。失敗した %d 本: %s" % (len(failed), "・".join(failed[:3]))
        for n in opts[3]:
            st["detail"] += "。" + n
        if run.streamer_from:   # 自動で入れた配信者は進み具合に出す(コラボで相手の色になることがあるため。段5)
            st["detail"] += "。字幕の色: %s(%s)" % (run.streamer, "自動: チャンネル名から" if run.streamer_from == "auto" else "前回の名前")
        return None

    # 文書単位の実行(⑦(b)) -------------------------------------
    def _doc(self, run):
        d = next((x for x in txindex.load(txindex.folder(self.root, self.env)) if x["id"] == run.doc_id), None)
        if not d:
            raise StepError("文書が見つかりません(消した可能性があります)")
        run.title = d["title"] or run.title
        src = d.get("sourcePath") or ""
        if not src or not os.path.isfile(src):
            raise StepError("元の動画が見つかりません(移動・削除した可能性があります)")
        return d

    def _execute_doc(self, run):
        for key in MODE_STEPS[DOC_MODE]:
            self._check(run)
            st = run.step(key)
            st["state"] = "run"
            run.message = st["label"]
            result = getattr(self, "_doc_" + key)(run, st)
            if st["state"] == "run":
                st["state"] = "done"
            if result == "stop":
                for s in run.steps:
                    if s["state"] == "wait":
                        s["state"], s["detail"] = "skip", s["detail"] or "前の段で止めました"
                break
        self._finish_message(run)

    def _doc_transcribe(self, run, st):
        doc = self._doc(run)
        if doc["count"]:
            st["state"], st["detail"] = "skip", "文字起こし済み"
            return None
        opts = self.client.ok("transcribe", "GET", "/api/settings")
        opts = {k: opts[k] for k in TX_KEYS if k in opts and isinstance(opts[k], (str, bool, int, float))}
        jid = self.client.ok("transcribe", "POST", "/api/transcribe", dict(opts, sourcePath=doc["sourcePath"], intoDoc=doc["id"])).get("id")
        try:
            while True:
                self._wait(run)
                j = next((x for x in self.client.ok("transcribe", "GET", "/api/jobs").get("jobs") or [] if x.get("id") == jid),
                         {"state": "error", "error": "文字起こしのジョブが見つかりません"})
                if j.get("state") in ("done", "error", "cancelled"):
                    break
                st["detail"] = "%s %d%%" % (j.get("phase") or "", round((j.get("progress") or 0) * 100))
        except Cancelled:
            self.client.call("transcribe", "POST", "/api/transcribe/cancel", {"id": jid})
            raise
        if j.get("state") != "done":
            raise StepError("文字起こしに失敗しました: %s" % (j.get("error") or j.get("state")))
        st["detail"] = "文字起こししました。字幕の校正は「編集」で"
        return None

    def _doc_pack(self, run, st):
        doc = self._doc(run)
        if self.find_pack(doc["sourcePath"]) and not run.overwrite:
            st["state"], st["detail"] = "skip", "パック済み(「作り直す」を選ぶと上書きします)"
            return None
        if not any(s.get("text", "").strip() and not s.get("cut") for s in doc.get("segments") or []) and not self._edit_keeps(doc)[0]:
            st["state"], st["detail"] = "skip", "残す字幕の行もカットも無いので、パックを作れません(2 カット のタブで区間を決めると作れます)"
            return None
        opts = self._pack_settings()
        res, cut = self._pack_one(run, st, doc, doc["sourcePath"], opts, force=run.overwrite)
        if res == "exists":   # find_pack で見つからない名前違いのパック(以前の版で作ったもの)など
            st["state"], st["detail"] = "skip", "同じ名前のパックがあるので上書きしませんでした(「作り直す」を選ぶと上書きします)"
            return None
        st["detail"] = "パックを作りました" + ("(「編集」のカットのとおり)" if cut else "(文字起こしの行から)") + \
            ("。前のパックを上書きしました" if run.overwrite else "") + "".join("。" + n for n in opts[3])
        return None


def _row_edge_ok(v):
    """「行から」の設定の形(cut2resolve の pack.row_edge_from と同じ決まり: 真偽か {on?, after?, before?}(0〜2 秒))"""
    if isinstance(v, bool):
        return True
    if not isinstance(v, dict) or ("on" in v and not isinstance(v["on"], bool)):
        return False
    for k in ("after", "before"):
        x = v.get(k)
        if x not in (None, "") and (isinstance(x, bool) or not isinstance(x, (int, float)) or not 0 <= x <= 2.0):
            return False
    return True

