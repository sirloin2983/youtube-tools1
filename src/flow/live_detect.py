# -*- coding: utf-8 -*-
"""配信中の盛り上がりの検出(線 D の L2)と自動の採用(M11)の入口の側。計画は plan/line-d-detect.md(3 の「候補の API の約束」は線 2 = スタジオの画面との境目。変えない)。
計算はワーカー(src/pipeline/analyze/live_excite_worker.py。入口の子プロセス)。ここは起動・見張り・候補の API・人の採用と見送り・自動の採用・「調子」の行。
src/home/live.py の Live が持ち(live.detector)、見回り(Live.tick。30 秒ごと)・API の振り分け・「調子」から呼ぶ(live.py を大きくしない。仮決め (br))。

設定(ホームの設定の節 live。src/home/prefs.py): detect {enabled(既定オン。10-08 ユーザー決定), sens: high|normal|low, perHour: 1〜30(既定 6)}・
autoAdopt {enabled(既定オン), waitMin: 1〜60(既定 5)}。検出はリアルタイム切り抜き(live.enabled)もオンのときだけ動く。

ファイル(入口の作業データ live/excite/。書き手は 1 ファイルに 1 つ = 仮決め (bj)):
  config.json       ここが書く(変わったときだけ)。ワーカーが 30 秒ごとに読み直す: 録画元(合言葉つき)・感度・1 時間の本数・スタジオの解析の設定(長さ・前の割合・遅れ・重み・冒頭)・
                    ffmpeg と yt-dlp の場所
  <録画元>/<録画>/decisions.json   ここが書く: 人の採用・見送り・戻す、自動の採用 {"v":1, "n", "items": [{n, id, state: adopted|dismissed|restore, origin, markId, jobId, at}]}。
                    ワーカーが読んで候補の帳簿(PeakBook)に当てる。当てた番号は peaks.json の decN。まだ当たっていない決定は、ここが API の応答に重ねて返す
  auto_failures.json  ここが書く: 自動の採用を諦めた候補(「調子」の失敗に出す)
  peaks.json・state.json・series.jsonl・worker.json・skipped.jsonl はワーカーが書く(ここは読むだけ)

API(src/home/live.py の handle_get / _api_post から。書き込みは入口の合言葉が要る = 今の仕組みのまま):
  GET  /live/api/peaks?recorder=&recording=&since=<seq>
       → {ok, seq, enabled, recorder, recording, worker: {running, behindSec, chat, restarts, chatRestarts, memMB, lag, message, error},
          hour: {perHour, counts: {"<h>": n}}, autoAdopt: {enabled, waitMin},
          peaks: [peak…](since 省略) / changes: [{seq, id, state, peak}](since あり。変わった候補の今の形。まだワーカーが当てていない人の決定も入る),
          series?: {n, step, total, audio, chat}(600 点。since 省略のときだけ), reset?: true(since が古すぎる・新しすぎる = peaks に全部)}
       peak = {id, start, end, peak, score, parts, reasons, confirmedAt, hour, state: frame|bench|adopted|dismissed, endPending, origin, markId?, jobId?, seq, pending?}
  POST /live/api/peaks {op: adopt|dismiss|restore, recorder, recording, id, after?, streamer?}
       adopt → Live.adopt(origin manual。after・streamer は画面の帯の値をそのまま渡す = 検査は Live.adopt。無ければ設定 live.auto.after)の {job, video, mark, existing, origin} + {ok, peak}。markId は スタジオのマークの id
       dismiss / restore → {ok, peak}(採用した候補は 409 = スタジオでマークを消す)

自動の採用(M11。Detector.tick の最後。ワーカーが動いている間だけ): 録画中の録画の候補のうち、枠の中(frame)で終わり待ち(endPending)でなく、
入口が最初に見てから waitMin 分たったものを Live.adopt(origin auto・after auto)。採用した候補は帳簿が枠に数えたまま固定する(excite の仮決め (bl))。
スタジオにつながらない(502)・書き出しの途中など(409)は次の見回りでやり直し、1 候補 AUTO_TRIES 回で諦めて「調子」の失敗(kind detect。auto_failures.json)に出す。
配信の終わり(D-14。10-08 決定): 録画が終わっても、ワーカーが帳簿を締めた(peaks.json の ended)あと END_GRACE_SEC の間は、待ち中だった候補(waitMin がまだ・
終わり待ちだった候補が締めで確定したもの)を同じ待ちで採用する(終わった瞬間に待ち中だった候補を取りこぼさない)。
安全弁(D-13。10-08 決定。仮の数 = 使いながら直す): 1 つの録画の自動の採用は AUTO_MAX_PER_REC 本まで(decisions.json の adopted/auto を数える。
友人の依頼の録画・live.autoDeliver で確認なしに届く分にも効く)。ホームの「自動の切り抜き: 未確認」(src/manage/cases/cases.py の auto.unconfirmed。Live.unconfirmed)が
UNCONFIRMED_PAUSE 本以上なら、依頼の無い録画の自動の採用を休む(人が見ていないのに増やさない。友人の依頼の録画は届けるのでそのまま)。休んでいる間は「調子」の
detect の行(autoAdopt.paused)に理由を出す。
"""
import json
import os
import shutil
import signal
import subprocess
import sys
import threading
import time

from ytt import fsio, schemas, tools
from . import spec as _spec   # 採用の数・待ちの既定は束の 1 か所(RS6 b-R1)
from . import live_failures
from . import live_export as LX
from . import livehost   # 親の口の型(RS7-2 G0)
from pipeline.analyze import excite
from pipeline.analyze import live_excite_worker as EW   # ファイルの形・定数・設定の検査はワーカーと 1 か所。numpy などは読まない

CODE_DIR = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "pipeline", "analyze")   # 子プロセスの道具は ① の置き場(pipeline/analyze)
WORKER = os.path.join(CODE_DIR, "live_excite_worker.py")
STALE_SEC = 120.0          # 心拍(worker.json)がこれだけ止まったら起動し直す
SETTINGS_EVERY = 300.0     # スタジオの解析の設定を読み直す間隔
RESTART_WARN = 3           # 起動し直しがこれを超えたら「調子」に失敗として出す
AUTO_TRIES = 5             # 自動の採用を 1 候補で試す回数
LOG_MAX = 2 * 1024 * 1024  # logs/excite.log がこれを超えていたら、ワーカーを起動するときに .old.log へ回す
OPS = ("adopt", "dismiss", "restore")
DECISIONS_MAX = 5000
PEAKS_MAX = 16 * 1024 * 1024
DETECT_DEFAULT = {"enabled": True, "sens": "normal", "perHour": _spec.DEFAULTS["adopt"]["perHour"]}
ADOPT_DEFAULT = {"enabled": True, "waitMin": _spec.DEFAULTS["adopt"]["waitMin"]}
CHAT_ORDER = ("none", "restarting", "ok", "off")   # 「調子」に出すチャットの状態(悪い順)


def _dump(obj):
    """入口が書く JSON(config.json・decisions.json・auto_failures.json)のバイト列"""
    return json.dumps(obj, ensure_ascii=False, indent=1).encode("utf-8")


def start_logged(cmd, log_path, cwd, flags, rotate=None):
    """入口が起こす常駐の子プロセス(録画の部品・検出のワーカー)を、標準出力と標準エラーをログに足す形で起動する -> Popen。
    見出しの行(起動の時刻)・PYTHONIOENCODING(無ければ)・PYTHONUNBUFFERED を付ける。rotate(バイト数)を渡すと、超えていたら起動の前に .old.log へ回す。
    flags: creationflags か、その候補の並び(先頭から試し、起動できなければ次。最後もだめなら OSError)"""
    env = dict(os.environ)
    env.setdefault("PYTHONIOENCODING", "utf-8:backslashreplace")
    env["PYTHONUNBUFFERED"] = "1"
    if rotate is not None:
        fsio.rotate(log_path, rotate)
    tries = list(flags) if isinstance(flags, (list, tuple)) else [flags]
    with open(log_path, "ab") as logf:
        logf.write(("\n==== %s ホームから起動 ====\n" % time.strftime("%Y-%m-%d %H:%M:%S")).encode("utf-8"))
        logf.flush()
        for i, f in enumerate(tries):
            try:
                return subprocess.Popen(cmd, cwd=cwd, env=env, stdin=subprocess.DEVNULL, stdout=logf, stderr=subprocess.STDOUT, creationflags=f)
            except OSError:
                if i == len(tries) - 1:
                    raise


def clean_spec(an):
    """スタジオの解析の設定(settings-ui.json の analyze)→ ワーカーの spec(範囲外は丸め、読めなければ既定。仮決め (bn))"""
    an = an if isinstance(an, dict) else {}
    out = dict(EW.SPEC_DEFAULT)
    for k, (lo, hi) in EW.SPEC_RANGES.items():
        v = an.get(k)
        if isinstance(v, (int, float)) and not isinstance(v, bool) and v == v:
            out[k] = float(min(hi, max(lo, v)))
    out["lagAuto"] = an.get("lagAuto") is not False
    return out


def overlay(pk, item):
    """候補に、まだワーカーが当てていない決定を重ねる(画面には決めたとおりに見せる)"""
    p = dict(pk)
    st = item.get("state")
    if st == "adopted":
        p.update(state="adopted", origin=item.get("origin") or "manual")
        for k in ("markId", "jobId"):
            if item.get(k):
                p[k] = item[k]
    elif st == "dismissed":
        p.update(state="dismissed", origin=None)
    elif st == "restore":
        p.update(state="bench", origin=None)   # 枠か控えかはワーカーが決める
    p["pending"] = True
    return p
SEEN_KEEP_SEC = 3600       # M11 の「最初に見た時刻」(_seen)を、見回りで見かけなくなってから残す秒(繋ぎ直しで同じ候補が戻る分は残す)
END_GRACE_SEC = 6 * 3600   # D-14: 録画が終わってからこの秒数の間は、締めで確定した候補も待ち中の候補も採用する(それより古い録画の候補はまとめて採用しない)
AUTO_MAX_PER_REC = 10      # D-13(仮の数): 1 つの録画で自動で採用する本数の上限(人のマーク・配信後の解析 archive は数えない)
UNCONFIRMED_PAUSE = 20     # D-13(仮の数): ホームの「自動の切り抜き: 未確認」がこれ以上なら、依頼の無い録画の自動の採用を休む
UNCONFIRMED_EVERY = 120.0  # 未確認の数を聞き直す間隔(案件の一覧を組み立て直すので、見回りのたびには聞かない)


class Detector:
    def __init__(self, host: "livehost.DetectHost", python=None, spawn=True, worker=WORKER, stale_sec=STALE_SEC, clock=time.time):
        """host: 親(flow/livehost.py の DetectHost。今は src/home/live.py の Live。設定・録画元・adopt・list_recordings・studio_call・store_dir・logs_dir)。
        テストは spawn=False(ワーカーを起動しない)か、worker に偽のワーカーを渡す・stale_sec を縮める"""
        self.host = host
        self.python = python or sys.executable
        self.spawn_ok, self.worker, self.stale_sec, self.clock = spawn, worker, stale_sec, clock
        self.ffmpeg = lambda: tools.find_tool("ffmpeg", "YTT_FFMPEG")
        self.ytdlp = lambda: tools.find_tool("yt-dlp", "YTT_YTDLP")
        self.chat_limit, self.chat_stall = EW.CHAT_LIMIT, EW.CHAT_STALL
        self.proc = None
        self.started_at = None
        self.restarts = 0
        self.last_exit = None
        self.lock = threading.RLock()     # decisions.json・auto_failures.json の書き込み(API の要求と見回りが同時に来る)
        self._tick_lock = threading.Lock()   # tick(見回りと友人の依頼の wake)を 1 つずつ
        self._spec, self._spec_at = None, -1e18
        self._written = None
        self._tries = {}                   # (録画元, 録画, 候補) -> 自動の採用を試した数
        self._seen = {}                    # (録画元, 録画, 候補) -> 入口が最初に見た時刻(M11 の waitMin の起点)。見かけなくなって SEEN_KEEP_SEC たったら消す
        self._seen_at = {}                 # (録画元, 録画, 候補) -> 見回りで最後に見た時刻(_seen を消す判断)
        self._fails = None                 # 自動の採用を諦めた候補(auto_failures.json)
        self._series = fsio.StampCache()   # series.jsonl の読み取りの覚え(更新日時と大きさが変わったときだけ読み直す)
        self._unconf, self._unconf_at, self._unconf_err = 0, -1e18, False   # D-13: 未確認の自動の切り抜きの数(UNCONFIRMED_EVERY 秒ごとに聞く)
        self._paused_said = ""             # D-13: 休む理由を記録に出したか(変わったときだけ出す)
        self._capped_said = set()          # D-13: 上限に達した録画(記録に 1 回だけ出す)

    # ---- 設定
    @property
    def dir(self):
        return os.path.join(self.host.store_dir, "excite")

    def _sub(self, name, defaults):
        v = self.host.cfg().get(name)
        return dict(defaults, **v) if isinstance(v, dict) else dict(defaults)

    def detect_cfg(self):
        return self._sub("detect", DETECT_DEFAULT)

    def adopt_cfg(self):
        a = self._sub("autoAdopt", ADOPT_DEFAULT)
        return {"enabled": a.get("enabled") is True, "waitMin": a.get("waitMin") if isinstance(a.get("waitMin"), int) else ADOPT_DEFAULT["waitMin"]}

    def enabled(self):
        """検出を動かすか: リアルタイム切り抜きがオンで、検出のスイッチがオンか、友人のライブ配信の依頼の録画がある(2-15: 友人の録画は常に動かす)"""
        return self.host.enabled() and (self.detect_cfg().get("enabled") is True or bool(self.requests_cfg()))

    def requests_cfg(self):
        """友人のライブ配信の依頼の録画ごとの設定(config.json の requests。ワーカーはこの録画を、ホームの検出がオフでも測り、感度・枠・長さをこの値で)"""
        # settings は live_requests.Store が検査済み(無い鍵・範囲の外は既定 = live_requests.SETTINGS_DEFAULT。読み直した項目も)
        return {k: {x: v["settings"][x] for x in ("sens", "perHour", "length")} for k, v in self.host.requests.all().items()}

    def adopt_for(self, req):
        """録画ごとの自動の採用 {"enabled", "waitMin"}: 友人の依頼の録画(req = live.requests.get の項目)は常にオンで待ちは依頼の waitMin(2-15)、
        ほかはホームの設定(adopt_cfg)"""
        if req is None:
            return self.adopt_cfg()
        return {"enabled": True, "waitMin": req["settings"]["waitMin"]}   # Store が検査済み(1〜60 の整数)

    def wake(self):
        """友人の依頼で録画を始めた直後: 次の見回りを待たずに config.json を書いてワーカーを起こす"""
        try:
            self.tick()
        except Exception as e:   # noqa: BLE001  (起こせなくても見回りが拾う)
            self.host.note("盛り上がりの検出: 友人の依頼で起こせませんでした: %r" % (e,))

    def spec(self):
        """スタジオの解析の設定(長さ・前の割合・遅れ・重み・冒頭)。SETTINGS_EVERY ごとにスタジオに聞く。つながらなければ前の値か既定"""
        now = self.clock()
        if self._spec is None or now - self._spec_at > SETTINGS_EVERY:
            self._spec_at = now
            try:
                code, d = self.host.studio_call("GET", "/api/settings")
            except Exception:
                code, d = None, None
            if code == 200 and isinstance(d, dict):
                self._spec = clean_spec((d.get("settings") or {}).get("analyze") if isinstance(d.get("settings"), dict) else None)
            elif self._spec is None:
                self._spec = clean_spec(None)
        return self._spec

    def config(self):
        return {"v": 1, "dir": self.dir, "recorders": [{"id": r["id"], "url": r.get("url") or "", "token": r.get("token") or ""} for r in self.host.recorders()],
                "detect": EW.clean_detect(self.detect_cfg()), "spec": self.spec(), "ffmpeg": self.ffmpeg(), "ytdlp": self.ytdlp(),
                "chatLimitBytes": self.chat_limit, "chatStallSec": self.chat_stall, "lengthHint": self._length_hint(),
                "detectAll": self.detect_cfg().get("enabled") is True, "requests": self.requests_cfg()}   # 友人の依頼の録画(2-15)

    def _length_hint(self):
        """M10: 人が選んだ区間の長さの目安(夜の自動測定 src/eval/tools/eval_marks.py --json の結果。enough のときだけワーカーが使う)。読めなければ None"""
        try:
            return EW.length_hint(self.host.root)
        except Exception as e:
            self.host.note("盛り上がりの検出: 長さの目安を読めませんでした: %r" % (e,))
            return None

    def write_config(self):
        """config.json(変わったときだけ書く。ワーカーは更新の時刻を見て読み直す)"""
        data = _dump(self.config())
        path = os.path.join(self.dir, "config.json")
        if data == self._written and os.path.isfile(path):
            return False
        fsio.atomic_write(path, data)
        self._written = data
        return True

    # ---- 見回り(Live.tick から 30 秒ごと)
    def tick(self):
        """オン: config.json → ワーカーを起動・見張る → 自動の採用。オフ: ワーカーを止める。-> "off"|"running"|"spawned"|"failed"|"nospawn"。
        入口の見回り(Live.tick)と友人の依頼の受付(wake)の 2 つのスレッドから来るので 1 つずつ(同時にワーカーを 2 つ起動して、片方の手綱を失わないため)"""
        with self._tick_lock:
            if not self.enabled():
                self.stop()
                return "off"
            self.write_config()
            state = self._ensure() if self.spawn_ok else "nospawn"
            try:
                self.auto_tick()
            except Exception as e:   # 自動の採用の不具合でも、見張りは続ける
                self.host.note("リアルタイム切り抜き: 自動の採用でエラー: %r" % (e,))
            return state

    def heartbeat(self):
        """worker.json(ワーカーの心拍)。無い・読めなければ None"""
        return fsio.read_json_or(os.path.join(self.dir, "worker.json"), None, 1024 * 1024, kind=dict)

    def _hb_age(self, hb):
        at = LX.iso_epoch((hb or {}).get("at"))
        return None if at is None else self.clock() - at

    def running(self, hb=None):
        """ワーカーが動いているか。この入口が起動したワーカー: 終わっていない かつ 心拍(その pid の。まだ無ければ起動の時刻)が stale_sec 以内。
        前の入口が残したワーカー: 心拍が stale_sec 以内で「止まりました」でない"""
        hb = self.heartbeat() if hb is None else hb
        age = self._hb_age(hb)
        p = self.proc
        if p is None:
            return age is not None and age <= self.stale_sec and (hb or {}).get("message") != "止まりました"
        if p.poll() is not None:
            return False
        if hb and hb.get("pid") == p.pid:
            return age is None or age <= self.stale_sec
        return self.clock() - (self.started_at or 0) <= self.stale_sec

    def _ensure(self):
        p = self.proc
        if p is not None and p.poll() is None:
            hb = self.heartbeat()
            age = self._hb_age(hb) if hb and hb.get("pid") == p.pid else None
            ref = age if age is not None else self.clock() - (self.started_at or self.clock())
            if ref <= self.stale_sec:
                return "running"
            self.host.log("盛り上がりの検出: ワーカーの心拍が %d 秒止まったので、起動し直します" % int(ref))
            self._kill(p)
            self.restarts += 1
        elif p is not None:
            self.proc, self.last_exit = None, p.returncode
            if p.returncode != EW.EXIT_LOCKED:   # ほかのワーカー(前の入口が残したもの)が終わるのを待つときは数えない
                self.restarts += 1
            self.host.log("盛り上がりの検出: ワーカーが終わりました(終了コード %s)。起動し直します" % p.returncode)
        return "spawned" if self._spawn() else "failed"

    def _spawn(self):
        if getattr(self.host, "_halt", None) is not None and self.host._halt.is_set():   # 入口の終了の途中
            return False
        os.makedirs(self.dir, exist_ok=True)
        os.makedirs(self.host.logs_dir, exist_ok=True)
        cmd = [self.python, "-u", self.worker, "--config", os.path.join(self.dir, "config.json"), "--parent", str(os.getpid())]
        try:   # 通常より下の優先度・別のプロセスグループ(_kill の CTRL_BREAK がワーカーだけに届く)
            self.proc = start_logged(cmd, os.path.join(self.host.logs_dir, "excite.log"), CODE_DIR,
                                     tools.no_window_flags(new_group=True, priority="low"), rotate=LOG_MAX)
        except OSError as e:
            self.host.note("盛り上がりの検出: ワーカーを起動できませんでした: %s" % tools.why(e))
            return False
        self.started_at = self.clock()
        self.host.log("盛り上がりの検出: ワーカーを起動しました(pid %d)" % self.proc.pid)
        return True

    @staticmethod
    def _kill(p):
        """まず穏やかに(Windows は CTRL_BREAK = ワーカーの SIGBREAK の handler が状態を保存して心拍に「止まりました」を書く)、終わらなければ terminate・kill"""
        try:
            if os.name == "nt":
                p.send_signal(signal.CTRL_BREAK_EVENT)   # CREATE_NEW_PROCESS_GROUP で起動しているので、ワーカーだけに届く
            else:
                p.terminate()
            p.wait(8)
            return
        except Exception:
            pass
        try:
            p.terminate()   # Windows は TerminateProcess(ワーカーの子 = ffmpeg・yt-dlp はワーカーのジョブと一緒に消える)
            p.wait(5)
        except Exception:
            tools.kill_quiet(p)

    def stop(self):
        """止める(オフにした・入口の終了)。状態は 60 秒ごとに保存しているので、次に起動したら続きから"""
        p, self.proc = self.proc, None
        if p is not None and p.poll() is None:
            self._kill(p)
            self.host.log("盛り上がりの検出: ワーカーを止めました")

    # ---- 候補を読む
    def folder(self, rc, rec):
        return os.path.join(self.dir, rc, rec)

    def forget(self, rc, rec):
        """録画を消したとき(src/manage/keep/live_cleanup.py): その録画の検出の記録(state.json・series.jsonl・peaks.json・decisions.json)も消す"""
        if schemas.ids_ok(rc, rec):
            shutil.rmtree(self.folder(rc, rec), ignore_errors=True)

    def _decisions(self, folder):
        d = fsio.read_json_or(os.path.join(folder, "decisions.json"), None, 8 * 1024 * 1024, kind=dict)
        if d is None or not isinstance(d.get("items"), list):
            return {"v": 1, "n": 0, "items": []}
        return {"v": 1, "n": int(d.get("n") or 0), "items": [x for x in d["items"] if isinstance(x, dict) and isinstance(x.get("n"), int)]}

    def view(self, rc, rec):
        """peaks.json(ワーカー)+ まだ当たっていない決定(decisions.json)-> (peaks.json の中身か None, 候補の一覧, {id: 重ねた決定})"""
        folder = self.folder(rc, rec)
        doc = fsio.read_json_or(os.path.join(folder, "peaks.json"), None, PEAKS_MAX, kind=dict)
        dec_n = int((doc or {}).get("decN") or 0)
        pending = {}
        for it in sorted(self._decisions(folder)["items"], key=lambda x: x["n"]):
            if it["n"] > dec_n and isinstance(it.get("id"), str):
                pending[it["id"]] = it
        peaks = [overlay(p, pending[p.get("id")]) if p.get("id") in pending else p for p in (doc or {}).get("peaks") or [] if isinstance(p, dict)]
        return doc, peaks, pending

    def series(self, rc, rec):
        """series.jsonl(1 分 1 行)→ 600 点 {n, step, total, audio, chat}(スタジオのアーカイブの解析の series と同じ形)。無ければ None"""
        return self._series.get(os.path.join(self.folder(rc, rec), "series.jsonl"), self._load_series)

    @staticmethod
    def _load_series(p):
        """series.jsonl を読んで 600 点にする(series の読み直し)。読めなければ None"""
        rows = {}
        try:
            with open(p, "r", encoding="utf-8", errors="replace") as f:
                for line in f:
                    try:
                        d = json.loads(line)
                    except ValueError:
                        continue
                    if isinstance(d, dict) and isinstance(d.get("t0"), int) and isinstance(d.get("total"), list):
                        rows[d["t0"]] = d   # 同じ分が 2 回あれば後(起動し直しで書き直した)
        except OSError:
            return None
        n = max((t0 + len(d["total"]) for t0, d in rows.items()), default=0)
        cols = {k: [0.0] * n for k in ("total", "audio", "chat")}
        for t0, d in rows.items():
            for k in cols:
                for i, v in enumerate(d.get(k) or []):
                    if 0 <= t0 + i < n and isinstance(v, (int, float)):
                        cols[k][t0 + i] = float(v)
        return {"n": n, "step": max(1.0, n / 600.0), **{k: excite.downsample(v) for k, v in cols.items()}} if n else None

    def worker_view(self, doc):
        hb = self.heartbeat() or {}
        return {"running": self.running(hb), "behindSec": (doc or {}).get("behindSec", hb.get("behindSec")),
                "chat": (doc or {}).get("chat") or "off", "restarts": self.restarts, "chatRestarts": hb.get("chatRestarts") or 0,
                "memMB": hb.get("memMB"), "lag": (doc or {}).get("lag"), "message": (doc or {}).get("message") or hb.get("message") or "",
                "error": hb.get("error") or ""}

    def api_get(self, q):
        """GET /live/api/peaks(q = parse_qs の結果)-> JSON(だめなら LiveError)"""
        rc, rec, since = (q.get("recorder") or [""])[0], (q.get("recording") or [""])[0], (q.get("since") or [None])[0]
        self.host._ids(rc, rec)   # 録画元と録画の id の検査(文・番号は Live の API と同じ)
        if since is not None:
            try:
                since = int(since)
            except ValueError:
                raise LX.LiveError("since は数で指定してください")
        doc, peaks, pending = self.view(rc, rec)
        tx = self.host.livetx.view(rc, rec)   # 配信中の文字起こし(D-11 案 b): 文字の付いた候補
        for p in peaks:
            t = tx.get(p.get("id"))
            if t:
                p["text"], p["textAt"] = t.get("text"), t.get("at")
        det = self.detect_cfg()
        req = self.host.requests.get(rc, rec)   # 友人のライブ配信の依頼の録画は、ホームの検出・自動採用がオフでも依頼の設定で動く(2-15)
        seq = int((doc or {}).get("seq") or 0)
        out = {"ok": True, "enabled": self.enabled() and (det.get("enabled") is True or req is not None), "recorder": rc, "recording": rec, "seq": seq,
               "worker": self.worker_view(doc),
               "hour": {"perHour": (doc or {}).get("perHour") or det.get("perHour") or DETECT_DEFAULT["perHour"], "counts": (doc or {}).get("counts") or {}},
               "autoAdopt": self.adopt_for(req), "changes": [], "tx": self.host.livetx.status()}
        chs = [c for c in (doc or {}).get("changes") or [] if isinstance(c, dict) and isinstance(c.get("seq"), int)]
        if since is None or since > seq or (chs and since < chs[0]["seq"] - 1):
            out["peaks"] = peaks
            if since is None:
                ser = self.series(rc, rec)
                if ser is not None:
                    out["series"] = ser
            else:
                out["reset"] = True   # 前に受け取った番号が古すぎる・新しすぎる(ワーカーが続きから戻った): 全部を取り直す
            return out
        by_id = {p.get("id"): p for p in peaks}
        last = {}
        for c in chs:
            if c["seq"] > since:
                last[c.get("id")] = c["seq"]
        for pid in pending:   # まだワーカーが当てていない決定も「変わった」として返す(ほかの窓にもすぐ出す)
            last.setdefault(pid, seq)
        for pid in self.host.livetx.recent_ids(rc, rec):   # 最近文字が付いた候補も(行に文字を出す)
            last.setdefault(pid, seq)
        out["changes"] = [{"seq": s, "id": pid, "state": by_id[pid].get("state"), "peak": by_id[pid]}
                          for pid, s in sorted(last.items(), key=lambda x: x[1]) if pid in by_id]
        return out

    # ---- 決める
    def decide(self, rc, rec, pid, state, origin=None, mark_id=None, job_id=None):
        """decisions.json に 1 件足す(ワーカーが読んで帳簿に当てる)-> 足した決定"""
        folder = self.folder(rc, rec)
        with self.lock:
            d = self._decisions(folder)
            n = d["n"] + 1
            item = {"n": n, "id": pid, "state": state, "origin": origin, "markId": mark_id, "jobId": job_id, "at": LX.now_iso()}
            d["n"] = n
            d["items"] = (d["items"] + [item])[-DECISIONS_MAX:]
            os.makedirs(folder, exist_ok=True)
            fsio.atomic_write(os.path.join(folder, "decisions.json"), _dump(d))
        return item

    def api_post(self, body):
        """POST /live/api/peaks -> JSON(だめなら LiveError)"""
        op = body.get("op")
        if op not in OPS:
            raise LX.LiveError("op は adopt・dismiss・restore のどれかです")
        rc, rec, pid = body.get("recorder"), body.get("recording"), body.get("id")
        self.host._ids(rc, rec)
        if not isinstance(pid, str) or not EW.PEAK_ID_RE.match(pid):
            raise LX.LiveError("候補の id が正しくありません")
        _doc, peaks, _pending = self.view(rc, rec)
        pk = next((p for p in peaks if p.get("id") == pid), None)
        if pk is None:
            raise LX.LiveError("その候補はありません", 404)
        if op == "adopt":   # 画面の帯の「書き出したあと」(after)と配信者(streamer)はそのまま M1 へ(検査は Live.adopt。無ければ設定 live.auto.after)
            return self.adopt(rc, rec, pk, "manual", after=body.get("after"), streamer=body.get("streamer"))
        if pk.get("state") == "adopted":
            raise LX.LiveError("採用した候補は見送り・戻すができません(要らなければ、スタジオでマークを消してください)", 409)
        if (op == "dismiss" and pk.get("state") == "dismissed") or (op == "restore" and pk.get("state") in ("frame", "bench")):
            return {"ok": True, "peak": pk}   # もうその状態(二重に押した)
        item = self.decide(rc, rec, pid, "dismissed" if op == "dismiss" else "restore")
        return {"ok": True, "peak": overlay(pk, item)}

    def adopt(self, rc, rec, pk, origin, after=None, streamer=None):
        """候補を M1 の採用(Live.adopt)に通して、決定を残す -> API の応答の形"""
        body = {"recorder": rc, "recording": rec, "start": pk["start"], "end": pk["end"], "label": "", "origin": origin}
        if schemas.is_num(pk.get("score")):
            body["score"] = pk["score"]   # 候補の点数を切り抜きの記録(.clip.json の source.live.score)に残す(M9 の一覧が出す)
        if after is not None:
            body["after"] = after
        if streamer is not None:
            body["streamer"] = streamer
        text = self.host.livetx.text_for(rc, rec, pk.get("id"))   # 配信中の文字起こしの文字があれば採用の記録に(D-11 案 b)
        if text:
            body["text"] = text
        res = self.host.adopt(body)
        job = res.get("job") or {}
        item = {"state": "adopted", "origin": pk.get("origin") or origin, "markId": pk.get("markId"), "jobId": pk.get("jobId")}
        if pk.get("state") != "adopted" or pk.get("markId") != res.get("mark"):
            item = self.decide(rc, rec, pk["id"], "adopted", origin=origin, mark_id=res.get("mark"), job_id=job.get("id"))
        return {"ok": True, "peak": overlay(pk, item), "job": res.get("job"), "video": res.get("video"), "mark": res.get("mark"),
                "existing": bool(res.get("existing")), "origin": res.get("origin")}

    # ---- 自動の採用(M11)
    def _load_fails(self):
        """自動の採用を諦めた候補(auto_failures.json。最初の 1 回だけ読み、あとは覚えた一覧に足して書く)"""
        if self._fails is None:
            d = fsio.read_json_or(os.path.join(self.dir, "auto_failures.json"), None, 1024 * 1024, kind=dict) or {}
            self._fails = [x for x in d.get("items") or [] if isinstance(x, dict)]
        return self._fails

    def _give_up(self, rc, rec, pk, why):
        with self.lock:
            fails = self._load_fails()
            fails.append({"recorder": rc, "recording": rec, "id": pk.get("id"), "start": pk.get("start"), "end": pk.get("end"),
                          "message": str(why)[:300], "at": LX.now_iso()})
            del fails[:-200]
            try:
                fsio.atomic_write(os.path.join(self.dir, "auto_failures.json"), _dump({"v": 1, "items": fails}))
            except OSError:
                pass
        self.host.log("盛り上がりの検出: 候補 %s(%s)を自動で採用できなかったので諦めました: %s" % (pk.get("id"), rec, why))

    def unconfirmed(self):
        """ホームの「自動の切り抜き: 未確認」の数(D-13 の休む判断。Live.unconfirmed = 入口が cases の数を渡す。UNCONFIRMED_EVERY 秒は前の値)。
        数えられなければ 0(休まない = 数えられない不具合で自動を止めない。記録には 1 回だけ出す)"""
        now = self.clock()
        if now - self._unconf_at < UNCONFIRMED_EVERY:
            return self._unconf
        fn = getattr(self.host, "unconfirmed", None)
        n = 0
        try:
            if fn is not None:
                v = fn()
                n = int(v) if isinstance(v, (int, float)) and not isinstance(v, bool) else 0
            self._unconf_err = False
        except Exception as e:   # noqa: BLE001
            if not self._unconf_err:
                self.host.note("リアルタイム切り抜き: 未確認の自動の切り抜きの数を読めませんでした(安全弁は効きません): %r" % (e,))
            self._unconf_err = True
        self._unconf, self._unconf_at = max(0, n), now
        return self._unconf

    def auto_count(self, rc, rec):
        """その録画で自動(origin auto)で採用した数(decisions.json。D-13 の上限の分母)"""
        return sum(1 for x in self._decisions(self.folder(rc, rec))["items"] if x.get("state") == "adopted" and x.get("origin") == "auto")

    def paused_why(self):
        """D-13: 依頼の無い録画の自動の採用を休む理由("" = 休まない)"""
        n = self.unconfirmed()
        if n >= UNCONFIRMED_PAUSE:
            return "未確認の自動の切り抜きが %d 本あるので、自動の採用を休んでいます(ホームで %d 本未満になるまで見るか要らないにしてください)" % (n, UNCONFIRMED_PAUSE)
        return ""

    def _target_recordings(self, now):
        """自動の採用の対象の録画 -> [(録画, 終わったか)]: 録画中(firstPdt・lastPdt あり)と、終わって END_GRACE_SEC 以内でワーカーが帳簿を締めたもの(D-14)"""
        out = []
        for r in self.host.list_recordings():
            if not isinstance(r.get("firstPdt"), (int, float)):
                continue
            if r.get("active"):
                if isinstance(r.get("lastPdt"), (int, float)):
                    out.append((r, False))
                continue
            ended = r.get("endedAt") if isinstance(r.get("endedAt"), (int, float)) else r.get("lastPdt")
            if isinstance(ended, (int, float)) and 0 <= now - ended <= END_GRACE_SEC:
                out.append((r, True))
        return out

    def auto_tick(self):
        """M11: 録画中の録画の候補のうち、枠の中で入口が最初に見てから waitMin 分たったものを自動で採用する -> 採用した数。
        D-14: 録画が終わって END_GRACE_SEC 以内でワーカーが締めた録画の、待ち中だった候補も同じ待ちで採用する。
        D-13: 1 録画 AUTO_MAX_PER_REC 本まで・未確認 UNCONFIRMED_PAUSE 本で依頼の無い録画は休む"""
        a = self.adopt_cfg()
        now = self.clock()
        for key in [k for k, t in self._seen_at.items() if now - t > SEEN_KEEP_SEC]:   # 採用した・録画が終わった候補の分は残さない(録画のたびに増え続けない)
            self._seen.pop(key, None)
            self._seen_at.pop(key, None)
        if not self.enabled() or not self.running():   # ワーカーが止まっている間は採用しない(古い候補をまとめて採用しないため)
            return 0
        # 依頼の無い録画は、ホームの検出と自動採用の両方がオンのときだけ(友人の依頼だけで検出が動いている間に、止めた録画の古い候補を採用しない)
        home = a["enabled"] and self.detect_cfg().get("enabled") is True
        if not home and not self.requests_cfg():   # 採用する録画が無い(録画元に聞かない)
            return 0
        paused = self.paused_why() if home else ""
        if paused and paused != self._paused_said:
            self.host.log("盛り上がりの検出: " + paused)
        self._paused_said = paused
        done = 0
        given = {(x.get("recorder"), x.get("recording"), x.get("id")) for x in self._load_fails()}
        for r, ended in self._target_recordings(now):
            rc, rec = r["recorder"], r["id"]
            req = self.host.requests.get(rc, rec)   # 友人のライブ配信の依頼の録画は、自動採用のスイッチがオフでも採用する(待ちは依頼の設定。2-15)
            if req is None and (not home or paused):
                continue
            wait_min = self.adopt_for(req)["waitMin"]
            doc, peaks, _pending = self.view(rc, rec)
            if ended and not (doc or {}).get("ended"):   # 終わった録画は、ワーカーが帳簿を締めてから(終わり待ちの候補が確定する)
                continue
            used = self.auto_count(rc, rec)
            for pk in peaks:
                key = (rc, rec, pk.get("id"))
                if pk.get("state") != "frame" or pk.get("endPending") or key in given or not isinstance(pk.get("confirmedAt"), (int, float)):
                    continue   # 終わり待ち(区間の終わりがまだ録れていない)は、合わせ直されてから
                # 待ちは入口が候補を最初に見た時刻から数える(画面に出てから人が見られる時間を waitMin 分とる。
                # 録画の秒(confirmedAt)で比べると、ワーカーの遅れの分だけ人が見られる時間が短くなる)
                first = self._seen.setdefault(key, now)
                self._seen_at[key] = now
                if now - first < wait_min * 60:
                    continue
                if used >= AUTO_MAX_PER_REC:   # D-13: この録画はもう上限(候補は帯に残る = 人が採用できる)
                    if rec not in self._capped_said:
                        self._capped_said.add(rec)
                        self.host.log("盛り上がりの検出: 録画 %s の自動の採用は上限の %d 本に達したので、残りの候補は人の採用に任せます" % (rec, AUTO_MAX_PER_REC))
                    break
                try:
                    self.adopt(rc, rec, pk, "auto", after="auto")
                    self._tries.pop(key, None)
                    done += 1
                    used += 1
                except LX.LiveError as e:
                    n = self._tries.get(key, 0) + 1
                    self._tries[key] = n
                    if e.code not in (502, 409) or n >= AUTO_TRIES:
                        self._tries.pop(key, None)
                        self._give_up(rc, rec, pk, "%s(%d 回試しました)" % (e, n))
                        given.add(key)
        return done

    # ---- 配信が終わったあと(0-10-6。L5 の材料。人の手は要らない)
    def compare(self, rc, rec, a, marks):
        """配信後の全自動(M7。src/flow/live_archive.py)がアーカイブの解析の結果を読んだとき: アーカイブの候補(自動のマーク)のうち、配信中にも
        候補(見送り以外)が出ていた割合と時刻の差を live_feedback.jsonl に 1 行({"event": "detect_compare"})。配信中の候補が無い録画は何もしない。
        a: afterStream の記録(t0・offset・first・last)。アーカイブの秒 s → 録画の頭からの秒 = t0 + s − offset − first(pick_candidates と同じ向き)-> 書いた行か None"""
        doc, peaks, _p = self.view(rc, rec)
        if doc is None or not all(isinstance(a.get(k), (int, float)) for k in ("t0", "offset", "first", "last")):
            return None
        def num(x):
            return isinstance(x, (int, float))

        def rel(s):   # アーカイブの秒 → 録画の頭からの秒
            return a["t0"] + s - a["offset"] - a["first"]

        def center(p):   # 配信中の候補の山の秒(無ければ区間のまん中)
            return p["peak"] if num(p.get("peak")) else (p["start"] + p["end"]) / 2.0

        span = a["last"] - a["first"]
        live = [p for p in peaks if p.get("state") != "dismissed" and num(p.get("start")) and num(p.get("end"))]
        arch = []   # [(開始, 終わり, 山)](録画の頭からの秒)
        for m in marks or []:
            if not isinstance(m, dict) or m.get("src") != "auto" or not num(m.get("start")) or not num(m.get("end")):
                continue
            s0, s1 = rel(m["start"]), rel(m["end"])
            if s1 > 0 and s0 < span:
                arch.append((s0, s1, rel(m["peak"]) if num(m.get("peak")) else (s0 + s1) / 2.0))
        hits, diffs = 0, []
        for s0, s1, at in arch:
            near = [p for p in live if p["start"] < s1 and s0 < p["end"]]
            if near:
                hits += 1
                diffs.append(round(center(min(near, key=lambda p: abs(center(p) - at))) - at, 1))
        unmatched = sum(1 for p in live if p.get("state") in ("frame", "adopted") and not any(p["start"] < s1 and s0 < p["end"] for s0, s1, _at in arch))
        ds = sorted(abs(x) for x in diffs)
        row = {"event": "detect_compare", "recorder": rc, "recording": rec, "archive": len(arch), "hit": hits,
               "ratio": round(hits / len(arch), 3) if arch else None, "medianAbsDiff": ds[len(ds) // 2] if ds else None, "diffs": diffs[:200],
               "liveFrame": sum(1 for p in live if p.get("state") in ("frame", "adopted")), "liveBench": sum(1 for p in live if p.get("state") == "bench"),
               "liveUnmatched": unmatched, "lag": doc.get("lag"), "chat": doc.get("chat"), "gaps": doc.get("gaps"), "offset": a.get("offset")}
        self.host.exporter.feedback(row)
        return row

    # ---- 「調子」
    def health(self):
        """Live.health の detect(検出がオフなら None)"""
        if not self.enabled():
            return None
        hb = self.heartbeat() or {}
        recs, chats = [], []
        for x in hb.get("recordings") or []:
            if not isinstance(x, dict) or not schemas.ids_ok(x.get("recorder"), x.get("id")):   # worker.json の id はパスに使う前に形を見る
                continue
            doc, peaks, _p = self.view(x["recorder"], x["id"])
            ch = (doc or {}).get("chat") or "off"
            chats.append(ch)
            auto_n = self.auto_count(x["recorder"], x["id"])
            recs.append({"recorder": x["recorder"], "id": x["id"], "peaks": sum(1 for p in peaks if p.get("state") in ("frame", "adopted")),
                         "lag": (doc or {}).get("lag"), "chat": ch, "behindSec": (doc or {}).get("behindSec"),
                         "auto": auto_n, "autoCapped": auto_n >= AUTO_MAX_PER_REC})   # D-13: 自動で採用した数と上限に達したか
        chat = next((c for c in CHAT_ORDER if c in chats), "off")
        paused = self._paused_said   # D-13: 休んでいる理由(auto_tick が決める。見回りの間の値 = ここで案件を数え直さない)
        return {"running": self.running(hb), "pid": hb.get("pid"), "behindSec": hb.get("behindSec"), "memMB": hb.get("memMB"),
                "restarts": self.restarts, "chat": chat, "chatRestarts": hb.get("chatRestarts") or 0, "recordings": recs,
                "message": hb.get("message") or ("ワーカーを起動しています" if self.proc is not None else "ワーカーは動いていません"),
                "error": hb.get("error") or "",
                "autoAdopt": dict(self.adopt_cfg(), maxPerRecording=AUTO_MAX_PER_REC, pauseUnconfirmed=UNCONFIRMED_PAUSE, paused=paused)}

    def failures(self, now=None):
        """「調子」の失敗(kind detect。文は src/flow/live_failures.py の detect_failure)"""
        if not self.host.enabled():
            return []
        now = time.time() if now is None else now
        out = []
        hb = self.heartbeat() or {}
        if self.enabled() and hb.get("error"):
            out.append(live_failures.detect_failure("worker", hb["error"], at=hb.get("at") or ""))
        if self.enabled() and self.restarts > RESTART_WARN:
            out.append(live_failures.detect_failure("restarts", "%d 回" % self.restarts, at=LX.now_iso()))
        for x in self._load_fails():
            t = LX.iso_epoch(x.get("at"))
            if t is not None and now - t > live_failures.WINDOW_SEC:
                continue
            out.append(live_failures.detect_failure("adopt", x.get("message"), recorder=x.get("recorder") or "", recording=x.get("recording") or "",
                                                    at=x.get("at") or "", span=(x.get("start"), x.get("end"))))
        return out
