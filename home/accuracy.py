"""精度の自動測定(マスタープラン Q3。docs/plan/q3-q4-design.md の (a))。

人が直した最終の記録に対して、機械の出力がどれだけ当たっているかを、手が空いたときに自動で測って「調子」に出す。
測る道具(dev/eval_asr.py・eval_marks.py・eval_speakers.py・eval_cut.py。無い道具は飛ばす)はそのまま使い、**子プロセス**で呼ぶ
(eval_asr.load_serve は serve.py を別名で読み環境変数を書き換えるので、入口の中では import できない。ほかの道具も形をそろえる)。

- 測るもの: 軽い測定だけ = 保存してある機械の出力と人の最終を比べる(認識し直さない。文字起こしは `eval_asr.py stored`)。作業データは読むだけ。
  結果は各道具が今どおり `<ツールの作業データ>\\evals\\<領域>\\` に保存する。入口は最新 2 回分の要約だけを記録 `app\\accuracy-state.json` に写す(直近と前回)
- いつ測るか: 夜の窓(設定 accuracy の nightFrom〜nightTo 時。既定 1〜6 時)に、1 日 1 回。画面の「今すぐ測る」はいつでも(窓・1 日 1 回・編集の静けさを待たない)
- 手が空いた判定: 入口の重い処理の順番(jobs.SLOTS)に動いている・待っているものが無い・「編集」のジョブが動いていない・まとめて実行が動いていない
  (この 3 つは busy() が返す理由。「今すぐ」でも待つ)、さらに自動のときは文字起こしの文書の最後の更新が 30 分以上前(last_edit())
- 子プロセス: sys.executable・優先度は通常より下・黒い画面なし・時間切れあり。環境変数(YTT_DATA_DIR など作業データの場所)はそのまま引き継ぐ。
  道具が失敗・時間切れ・結果を読めなくても入口は止まらない(その領域に理由を記録して、次の領域へ)
- 結果ファイルの整理: 自動の測定が作った分だけ、領域ごとに新しい 30 件を残して古いものを消す(人が手で流した結果は消さない)。
  自分が作った分の見分け方 = 入口が覚えた「自分が作ったファイルの一覧」(state の areas.<領域>.files)。marks・speakers・cut の道具には --label が無く、
  名前が手で流した分と同じ形(<日時>.json)なので、名前の印では見分けられない。asr だけは `_auto` の印でも見分けられる(一覧が失われても拾える)。
  消すのは各道具の evals/<領域>/ の中の、名前の形が厳しく合う普通のファイルだけ(シンボリックリンクはたどらない)
- 重い測定(認識し直しての比較)は入れない(heavy_enabled = False の箱と分岐だけ。docs/plan/q3-q4-design.md の (a) に入れるときの条件)
- 設定(home/prefs.py の節 accuracy): enabled(既定オン。読むだけで軽い)・nightFrom・nightTo
"""
import datetime
import json
import math
import os
import re
import subprocess
import sys
import threading
import time

STATE_FILE = "accuracy-state.json"
FIRST_WAIT = 120           # 起動してから最初に見るまで(秒。ツールの起動とぶつけない)
CHECK_EVERY = 300          # 夜の窓・手が空いたかを見る間隔(秒)
FORCE_CHECK_EVERY = 30     # 「今すぐ」で手が空くのを待っているときの間隔(秒)
QUIET_EDIT_SEC = 30 * 60   # 文字起こしの文書の最後の更新からこれだけ空いていれば「手が空いた」(自動のとき)
TOOL_TIMEOUT = 20 * 60     # 道具1つあたりの時間切れ(秒)
FEW_DOCS = 2               # これより少ない文書(配信)数のときは「まだ少ない」
MAX_RESULT_BYTES = 64 * 1024 * 1024
SAVED_MARK = "保存: "       # 道具が結果のファイルを書いたとき、最後に標準出力へ出す行の頭(dev/eval_*.py)
ERR_TAIL = 200
KEEP_FILES = 30            # 自動の測定が作った結果ファイルは、領域ごとに新しい分をこれだけ残して古いものを消す
# 消してよい名前の形(道具の save の形: <日時>.json。asr は --label auto の <日時>_auto.json)。これに合わないファイルは数えもしない・消さない
RESULT_NAME_RE = re.compile(r"^\d{8}-\d{6}(?:_auto)?\.json\Z")
STATE_LABELS = {"off": "オフ", "idle": "動いています", "waiting": "手が空くのを待っています", "running": "測っています…"}


class ToolError(Exception):
    pass


# ---------------------------------------------------------------- 結果の要約(道具ごとの形 → 画面が読む共通の形)

def _num(x):
    return float(x) if isinstance(x, (int, float)) and not isinstance(x, bool) and math.isfinite(x) else None


def _int(x):
    return int(x) if isinstance(x, (int, float)) and not isinstance(x, bool) and math.isfinite(x) else 0


def _summary(label, value, docs, unit, better, low=False, rng=None, extra=None):
    """画面が読む共通の形。value は 0〜1 の割合(None = 測れなかった)・docs は数えた文書(配信)の数・extra は [{label, value, better}]"""
    return {"label": label, "value": _num(value), "range": rng, "docs": _int(docs), "unit": unit, "better": better,
            "lowData": bool(low), "few": _int(docs) < FEW_DOCS, "extra": extra or []}


def summarize_asr(res):
    s = res.get("summary") if isinstance(res.get("summary"), dict) else {}
    o = s.get("overall")
    if not isinstance(o, dict):
        raise ValueError("結果の形が想定と違います(summary.overall が無い)")
    ci = s.get("ci95")
    rng = [_num(ci[0]), _num(ci[1])] if isinstance(ci, list) and len(ci) == 2 and _num(ci[0]) is not None and _num(ci[1]) is not None else None
    out = _summary("CER", o.get("cer"), len(s.get("byDoc") or []), "文書", "lower", s.get("lowData"), rng)
    out["chars"] = _int(o.get("refChars"))
    out["proofedSec"] = _int(s.get("proofedSec"))
    return out


def summarize_marks(res):
    o = res.get("overall")
    if not isinstance(o, dict):
        raise ValueError("結果の形が想定と違います(overall が無い)")
    top10 = (o.get("top") or {}).get("top10") or {}
    miss = (o.get("misses") or {}).get("missRate")
    return _summary("上位10の採用率", top10.get("adoptRate"), o.get("judgedVideos"), "配信", "higher", (res.get("meta") or {}).get("few"),
                    extra=[{"label": "見逃し率", "value": _num(miss), "better": "lower"}])


def summarize_speakers(res):
    sub = ((res.get("subsets") or {}).get("all"))
    if not isinstance(sub, dict):
        raise ValueError("結果の形が想定と違います(subsets.all が無い)")
    voices = sub.get("voices") or {}
    count = res.get("speakerCount") or {}
    m = res.get("meta") or {}
    return _summary("行ごとの話者の正しさ", sub.get("rate"), m.get("docs"), "文書", "higher", m.get("fewNote"),
                    extra=[{"label": "声の照合", "value": _num(voices.get("rate")), "better": "higher"},
                           {"label": "話者の数が合う", "value": _num(count.get("exactRate")), "better": "higher"}])


def summarize_cut(res):
    """dev/eval_cut.py: たたき台のカットを人が直さなかった文書の割合(甘く出る = 人はたたき台につられる)と、端がそのままだった割合"""
    t = res.get("total")
    if not isinstance(t, dict):
        return summarize_generic(res)      # 道具が accuracy の鍵を足していれば、それを使う
    m = res.get("meta") or {}
    return _summary("たたき台を直さなかった文書", t.get("untouchedRate"), m.get("docs"), "文書", "higher", m.get("few"),
                    extra=[{"label": "端がそのまま", "value": _num((t.get("edges30") or {}).get("sameRate")), "better": "higher"}])


def summarize_generic(res):
    """道具が結果に `accuracy` の鍵(label・value・docs・unit・better・extra)を足してあれば、それをそのまま使う(カットなど、これから足す道具用)"""
    a = res.get("accuracy")
    if not isinstance(a, dict) or "value" not in a:
        raise ValueError("結果の形が想定と違います(accuracy の鍵が無い)")
    extra = [{"label": str(x.get("label"))[:40], "value": _num(x.get("value")), "better": "lower" if x.get("better") == "lower" else "higher"}
             for x in a.get("extra") or [] if isinstance(x, dict)][:6]
    return _summary(str(a.get("label") or "")[:40], a.get("value"), a.get("docs"), str(a.get("unit") or "文書")[:10],
                    "lower" if a.get("better") == "lower" else "higher", a.get("lowData"), extra=extra)


# 領域: script = dev/ の道具・args = 呼び方・tool/sub = 結果の置き場所(<ツールの作業データ>\evals\<sub>)・summarize = 結果 → 要約
AREAS = (
    {"id": "asr", "label": "文字起こし", "script": "eval_asr.py", "args": ("stored", "--label", "auto"), "tool": "transcribe", "sub": "asr", "summarize": summarize_asr},
    {"id": "marks", "label": "盛り上がり", "script": "eval_marks.py", "args": ("--json",), "tool": "studio", "sub": "marks", "summarize": summarize_marks},
    {"id": "speakers", "label": "話者", "script": "eval_speakers.py", "args": ("--json",), "tool": "transcribe", "sub": "speakers", "summarize": summarize_speakers},
    {"id": "cut", "label": "カット", "script": "eval_cut.py", "args": ("--json",), "tool": "transcribe", "sub": "cut", "summarize": summarize_cut},   # dev/eval_cut.py(無ければ飛ばす)
)


def in_window(now, cfg):
    """now(エポック秒。PC の時刻)が夜の窓か。nightFrom > nightTo なら日をまたぐ(22 → 6 など)"""
    h = datetime.datetime.fromtimestamp(now).hour
    a, b = int(cfg.get("nightFrom", 1)), int(cfg.get("nightTo", 6))
    return a <= h < b if a < b else (h >= a or h < b)


def day_of(now):
    return datetime.date.fromtimestamp(now).isoformat()


def _python():
    """子プロセスの python。pythonw.exe(黒い画面なしの起動)のときは、標準出力を持つ python.exe を探す"""
    exe = sys.executable
    if os.path.basename(exe).lower() == "pythonw.exe":
        alt = os.path.join(os.path.dirname(exe), "python.exe")
        if os.path.isfile(alt):
            return alt
    return exe


class Accuracy:
    def __init__(self, prefs, data_dir, repo_root, busy=None, last_edit=None, log=None, clock=None, commands=None, evals_dir=None,
                 timeout=TOOL_TIMEOUT, first_wait=FIRST_WAIT, check_every=CHECK_EVERY, heavy_enabled=False, keep=KEEP_FILES):
        """prefs: home/prefs.py の Prefs(節 accuracy)。data_dir: ホームの作業データ(app。記録を置く)。repo_root: リポジトリ(dev/ の道具の場所・作業データの場所)。
        busy() -> 手が空いていない理由の文(空・None = 空いている)。last_edit() -> 文字起こしの文書の最後の更新(エポック秒・None = 不明)。
        commands(area) -> 子プロセスの引数の一覧(None = その道具が無い)・evals_dir(area) -> 結果の置き場所: テストで偽の道具に差し替える"""
        self.prefs, self.data_dir, self.repo_root = prefs, data_dir, repo_root
        self.busy = busy or (lambda: None)
        self.last_edit = last_edit or (lambda: None)
        self.log = log or (lambda msg: None)
        self.clock = clock or time.time
        self.commands = commands or self._default_commands
        self.evals_dir = evals_dir or self._default_evals_dir
        self.timeout = timeout
        self.keep = keep
        self.first_wait, self.check_every = first_wait, check_every
        self.heavy_enabled = heavy_enabled     # 重い測定(認識し直し)。今回は入れない(false 固定)
        self.state_path = os.path.join(data_dir, STATE_FILE)
        self.lock = threading.Lock()           # 測る処理を1つずつ
        self.wake = threading.Event()
        self.force = False                     # 「今すぐ」(手が空くまで残る)
        self.closed = False
        self.thread = None
        self.state = "idle"
        self.message = ""
        self.last = self._load_state()

    # ---- 記録
    def _load_state(self):
        try:
            with open(self.state_path, "rb") as f:
                d = json.loads(f.read(1024 * 1024).decode("utf-8-sig"))
        except (OSError, ValueError):
            d = None
        d = d if isinstance(d, dict) else {}
        if not isinstance(d.get("areas"), dict):
            d["areas"] = {}
        return d

    def _save_state(self):
        try:
            os.makedirs(self.data_dir, exist_ok=True)
            tmp = self.state_path + ".tmp"
            with open(tmp, "wb") as f:
                f.write(json.dumps(self.last, ensure_ascii=False).encode("utf-8"))
            os.replace(tmp, self.state_path)
        except OSError as e:
            self.log("精度の測定: 記録を書けませんでした(%s)" % (e.strerror or e.__class__.__name__))

    def _cfg(self):
        import prefs as prefs_mod
        try:
            return dict(self.prefs.get(["accuracy"])["accuracy"])
        except (OSError, ValueError, KeyError):
            return dict(prefs_mod.DEFAULTS["accuracy"])

    # ---- 道具の呼び方
    def _default_commands(self, area):
        script = os.path.join(self.repo_root, "dev", area["script"])
        return [_python(), script] + list(area["args"]) if os.path.isfile(script) else None

    def _default_evals_dir(self, area):
        from ytt_core import datadir
        try:
            return os.path.join(datadir.resolve(area["tool"], self.repo_root), "evals", area["sub"])
        except Exception:
            return None

    def _run(self, argv):
        """子プロセスで道具を動かす -> 標準出力。失敗・時間切れは ToolError(理由の文)"""
        env = dict(os.environ, PYTHONIOENCODING="utf-8", PYTHONUTF8="1")   # 作業データの場所(YTT_DATA_DIR など)はそのまま引き継ぐ
        kw = {}
        if os.name == "nt":
            kw["creationflags"] = getattr(subprocess, "BELOW_NORMAL_PRIORITY_CLASS", 0x4000) | getattr(subprocess, "CREATE_NO_WINDOW", 0x08000000)
        else:
            kw["preexec_fn"] = lambda: os.nice(10)
        try:
            p = subprocess.Popen(argv, cwd=self.repo_root, env=env, stdin=subprocess.DEVNULL, stdout=subprocess.PIPE, stderr=subprocess.PIPE, **kw)
        except OSError as e:
            raise ToolError("道具を起動できませんでした(%s)" % (e.strerror or e.__class__.__name__))
        deadline = time.monotonic() + self.timeout
        while True:
            try:
                out, err = p.communicate(timeout=1.0)
                break
            except subprocess.TimeoutExpired:
                if self.closed or time.monotonic() > deadline:
                    p.kill()
                    p.communicate()
                    raise ToolError("入口を終了します" if self.closed else "時間切れ(%d 分)で止めました" % max(1, int(self.timeout // 60)))
        if p.returncode != 0:
            lines = [x.strip() for x in err.decode("utf-8", "replace").splitlines() if x.strip()]
            raise ToolError("道具が失敗しました(終了コード %d)%s" % (p.returncode, ": " + lines[-1][:ERR_TAIL] if lines else ""))
        return out.decode("utf-8", "replace")

    def _result_path(self, out, edir, t0):
        """道具が結果を書いたファイル。標準出力の「保存: <パス>」を優先し、無ければ置き場所の中で今回の測定のあとに書かれた最新のファイル。
        置き場所の外のファイルは読まない"""
        cand = None
        for line in reversed(out.splitlines()):
            if line.startswith(SAVED_MARK):
                cand = line[len(SAVED_MARK):].strip()
                break
        if cand is None and edir and os.path.isdir(edir):
            best = None
            for name in os.listdir(edir):
                p = os.path.join(edir, name)
                if name.endswith(".json") and os.path.isfile(p) and os.path.getmtime(p) >= t0 - 2 and (best is None or os.path.getmtime(p) > os.path.getmtime(best)):
                    best = p
            cand = best
        if not cand or not os.path.isfile(cand):
            raise ToolError("結果のファイルが見つかりません")
        if edir:
            e, c = os.path.normcase(os.path.realpath(edir)), os.path.normcase(os.path.realpath(cand))
            if not c.startswith(e.rstrip("\\/") + os.sep):
                raise ToolError("結果のファイルが想定の場所の外にあります")
        return cand

    def _prune(self, area, entry):
        """自動の測定が作った結果ファイルを、新しい self.keep 件だけ残して消す。entry["files"](自分が作った分の一覧)を更新する。
        対象 = 一覧にある名前 + (asr だけ)置き場所の中の `_auto` 付きの名前。名前は RESULT_NAME_RE に厳しく合うものだけ・
        置き場所の中の普通のファイルだけ(シンボリックリンク・フォルダは消さない)。名前は先頭が日時なので、並べ替えれば古い順"""
        edir = self.evals_dir(area)
        names = {n for n in entry.get("files") or [] if isinstance(n, str) and RESULT_NAME_RE.match(n)}
        if not edir or not os.path.isdir(edir):
            entry["files"] = sorted(names)
            return
        if area["id"] == "asr":
            try:
                names |= {n for n in os.listdir(edir) if RESULT_NAME_RE.match(n) and n.endswith("_auto.json")}
            except OSError:
                pass
        ordered = sorted(names)
        keep = ordered[-self.keep:] if self.keep > 0 else []
        real = os.path.normcase(os.path.realpath(edir))
        for n in ordered[:len(ordered) - len(keep)]:
            p = os.path.join(edir, n)
            try:
                if os.path.islink(p) or not os.path.isfile(p) or os.path.normcase(os.path.realpath(os.path.dirname(p))) != real:
                    continue
                os.remove(p)
            except OSError:
                continue
        entry["files"] = keep

    def _measure_area(self, area, t0):
        """1 つの領域を測る。-> 記録に入れる {"at", "file", "summary"}。None = 道具が無い。失敗は ToolError"""
        argv = self.commands(area)
        if not argv:
            return None
        out = self._run(argv)
        path = self._result_path(out, self.evals_dir(area), t0)
        try:
            if os.path.getsize(path) > MAX_RESULT_BYTES:
                raise ToolError("結果のファイルが大きすぎます")
            with open(path, "rb") as f:
                res = json.loads(f.read().decode("utf-8-sig"))
            if not isinstance(res, dict):
                raise ValueError("JSON の形が違います")
            summary = area["summarize"](res)
        except (OSError, ValueError) as e:
            raise ToolError("結果を読めませんでした(%s)" % str(e)[:ERR_TAIL])
        return {"at": int(self.clock() * 1000), "file": os.path.basename(path), "summary": summary}

    # ---- 見張り
    def start(self):
        if self.thread is None:
            self.thread = threading.Thread(target=self._loop, name="accuracy", daemon=True)
            self.thread.start()

    def close(self):
        self.closed = True
        self.wake.set()

    def run_now(self):
        """「今すぐ測る」。手が空くまで待って(窓・1 日 1 回は待たない)裏で測る。オフのときは False"""
        if not self._cfg().get("enabled"):
            return False
        self.force = True
        self.wake.set()
        return True

    def _loop(self):
        self.wake.wait(self.first_wait)
        while not self.closed:
            self.wake.clear()
            try:
                self.tick()
            except Exception as e:   # 想定外でも止めない(次の回でやり直す)
                self.state, self.message = "idle", "内部エラー: %s %s" % (e.__class__.__name__, str(e)[:200])
                self.log("精度の測定: " + self.message)
            self.wake.wait(FORCE_CHECK_EVERY if self.force else self.check_every)

    def waiting_reason(self, force):
        """手が空いていない理由(空 = 空いている)。busy() = 重い処理・編集のジョブ・まとめて実行(「今すぐ」でも待つ)。
        自動のときは、文字起こしの文書の最後の更新から QUIET_EDIT_SEC 空くのも待つ(今まさに校正している最中に測らない)"""
        try:
            why = self.busy()
        except Exception:
            why = None
        if why:
            return "動いている処理が終わるのを待っています(%s)" % why
        if not force:
            try:
                le = self.last_edit()
            except Exception:
                le = None
            if isinstance(le, (int, float)) and self.clock() - le < QUIET_EDIT_SEC:
                return "文書の編集が止まるのを待っています(あと %d 分)" % max(1, int((QUIET_EDIT_SEC - (self.clock() - le)) // 60) + 1)
        return ""

    def tick(self):
        """夜の窓で今日まだなら(または「今すぐ」なら)、手が空いているときに測る。-> 測ったときは {領域の id: "ok" / 理由 / None}"""
        cfg = self._cfg()
        now = self.clock()
        if not cfg.get("enabled"):
            self.force = False
            self.state, self.message = "off", ""
            return None
        force = self.force
        today = day_of(now)
        if not force and not (self.last.get("day") != today and in_window(now, cfg)):
            self.state, self.message = "idle", ""
            return None
        why = self.waiting_reason(force)
        if why:
            self.state, self.message = "waiting", why
            return None
        with self.lock:
            self.force = False
            return self._measure(today)

    def _measure(self, today):
        self.state, self.message = "running", ""
        t0 = self.clock()
        result, done = {}, True
        for area in AREAS:
            if self.closed:
                done = False
                break
            entry = dict(self.last["areas"].get(area["id"]) or {})
            try:
                got = self._measure_area(area, t0)
            except ToolError as e:   # 1 つの道具の失敗で止めない(その領域に理由を残して次へ)
                entry.update(error=str(e), errorAt=int(self.clock() * 1000))
                result[area["id"]] = str(e)
                self.log("精度の測定: %s: %s" % (area["label"], e))
            except Exception as e:
                entry.update(error="内部エラー: %s %s" % (e.__class__.__name__, str(e)[:ERR_TAIL]), errorAt=int(self.clock() * 1000))
                result[area["id"]] = entry["error"]
                self.log("精度の測定: %s: %s" % (area["label"], entry["error"]))
            else:
                if got is None:
                    result[area["id"]] = None
                else:
                    cur = entry.get("latest")
                    if isinstance(cur, dict) and cur.get("file") != got["file"]:
                        entry["prev"] = cur          # 直近 → 前回
                    entry["latest"] = got
                    if RESULT_NAME_RE.match(got["file"]):
                        entry["files"] = list(entry.get("files") or []) + [got["file"]]   # 自分が作った分の一覧(整理の対象)
                    try:
                        self._prune(area, entry)
                    except Exception as e:   # 整理に失敗しても測定は成功(次の回でやり直す)
                        self.log("精度の測定: %s: 古い結果ファイルを整理できませんでした(%s)" % (area["label"], e.__class__.__name__))
                    entry.pop("error", None)
                    entry.pop("errorAt", None)
                    result[area["id"]] = "ok"
            if result[area["id"]] is not None or entry:
                self.last["areas"][area["id"]] = entry
        if self.heavy_enabled and not self.closed:
            self._heavy()
        now = self.clock()
        self.last.update(ran=now, seconds=round(now - t0, 1))
        if done:
            self.last["day"] = day_of(t0)       # 1 日 1 回(途中で終了したときは記録しない = 次の起動でやり直す)
        self._save_state()
        self.state, self.message = "idle", ""
        self.log("精度の測定: 終わりました(%s)" % "・".join("%s %s" % (a["label"], "ok" if result.get(a["id"]) == "ok" else "なし" if result.get(a["id"]) is None else "失敗") for a in AREAS))
        return result

    def _heavy(self):
        """重い測定(認識し直しての比較)。今回は入れない(heavy_enabled は false のまま)。
        入れるときの条件(docs/plan/q3-q4-design.md の (a)): 入口が SLOTS を 1 つ持って子プロセス・前回から評価用の校正済みの秒が +5 分・whisper.cpp が使える"""
        return None

    def snapshot(self):
        cfg = self._cfg()
        areas = []
        for a in AREAS:
            e = self.last["areas"].get(a["id"]) or {}
            try:
                available = bool(self.commands(a))
            except Exception:
                available = False
            areas.append({"id": a["id"], "label": a["label"], "available": available, "latest": e.get("latest"), "prev": e.get("prev"),
                          "error": e.get("error") or "", "errorAt": e.get("errorAt")})
        ran = self.last.get("ran")
        state = "off" if not cfg.get("enabled") else self.state
        return dict(cfg, state=state, stateLabel=STATE_LABELS[state], message=self.message if state != "off" else "", heavyEnabled=self.heavy_enabled,
                    forced=bool(self.force), lastRun=int(ran * 1000) if isinstance(ran, (int, float)) else None, areas=areas)
