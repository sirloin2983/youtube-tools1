# -*- coding: utf-8 -*-
"""配信中の盛り上がりの検出(線 D の L2)と自動の採用(M11)の入口の側。計画は 資料の git:before-1028-cleanup:plan/line-d-detect.md(3 の「候補の API の約束」は線 2 = スタジオの画面との境目。変えない)。
計算はワーカー(src/pipeline/analyze/live_excite_worker.py。入口の子プロセス)。ここは起動・見張り・候補の API・人の採用と見送り・自動の採用・「調子」の行。
ライブ係 src/flow/livesession.py の LiveSession(入口の Live はそれを継ぐ)が持ち(live.detector)、見回り(tick。30 秒ごと)・API の振り分け・「調子」から呼ぶ(live.py を大きくしない。仮決め (br))。

設定(ホームの設定の節 live。src/app/prefs.py): detect {enabled(既定オン。ユーザー決定), sens: high|normal|low, perHour: 1〜30(既定 6), fill(既定オン = 配信の終わりの本数の埋め。EW の QUOTA)}・
autoAdopt {waitMin: 1〜60(既定 5)}(自動の採用はいつもオン。オフのスイッチは 10-19 に消した)。検出はリアルタイム切り抜き(live.enabled)もオンのときだけ動く。
束のある録画(親の bundles = live/bundles.json。RS7-2 G2b)は、録画を始めたときの束の解析の設定(analyze)・感度・枠(adopt.sens・perHour)を
config.json の bundles に、自動の採用の待ちは束の adopt.waitMin(決定 3-31 の仮 b1)。束の無い録画は上の設定とスタジオの解析の設定のまま。

ファイル(入口の作業データ live/excite/。書き手は 1 ファイルに 1 つ = 仮決め (bj)):
  config.json       ここが書く(変わったときだけ)。ワーカーが 30 秒ごとに読み直す: 録画元(合言葉つき)・感度・1 時間の本数・スタジオの解析の設定(長さ・前の割合・遅れ・重み・冒頭)・
                    ffmpeg と yt-dlp の場所
  <録画元>/<録画>/decisions.json   ここが書く: 人の採用・見送り・戻す、自動の採用 {"v":1, "n", "items": [{n, id, state: adopted|dismissed|restore, origin, markId, jobId, at}]}。
                    ワーカーが読んで候補の帳簿(PeakBook)に当てる。当てた番号は peaks.json の decN。まだ当たっていない決定は、ここが API の応答に重ねて返す
  auto_failures.json  ここが書く: 自動の採用を諦めた候補(「調子」の失敗に出す)
  peaks.json・state.json・series.jsonl・worker.json・skipped.jsonl はワーカーが書く(ここは読むだけ)
  ../peaks-kept/<録画元>__<録画>.json  ここが書く: 録画を消すとき(forget)に候補の区間の一覧を写した物(研究の材料。KEEP_DAYS で消す)

API(src/app/live.py の handle_get / _api_post から。書き込みは入口の合言葉が要る = 今の仕組みのまま):
  GET  /live/api/peaks?recorder=&recording=&since=<seq>
       → {ok, seq, enabled, recorder, recording, worker: {running, behindSec, chat, restarts, chatRestarts, memMB, lag, message, error},
          hour: {perHour, counts: {"<h>": n}}, autoAdopt: {waitMin},
          peaks: [peak…](since 省略) / changes: [{seq, id, state, peak}](since あり。変わった候補の今の形。まだワーカーが当てていない人の決定も入る),
          series?: {n, step, total, audio, chat}(600 点。since 省略のときだけ), reset?: true(since が古すぎる・新しすぎる = peaks に全部)}
       peak = {id, start, end, peak, score, parts, reasons, confirmedAt, hour, state: frame|bench|adopted|dismissed, endPending, origin, markId?, jobId?, seq, pending?}
  POST /live/api/peaks {op: adopt|dismiss|restore, recorder, recording, id, after?, streamer?}
       adopt → Live.adopt(origin manual。after・streamer は画面の帯の値をそのまま渡す = 検査は Live.adopt。無ければ設定 live.auto.after)の {job, video, mark, existing, origin} + {ok, peak}。markId は スタジオのマークの id
       dismiss / restore → {ok, peak}(採用した候補は 409 = スタジオでマークを消す)

自動の採用(M11。Detector.tick の最後。ワーカーが動いている間だけ): 録画中の録画の候補のうち、枠の中(frame)で終わり待ち(endPending)でなく、
入口が最初に見てから waitMin 分たったものを Live.adopt(origin auto・after auto)。採用した候補は帳簿が枠に数えたまま固定する(excite の仮決め (bl))。
スタジオにつながらない(502)・書き出しの途中など(409)は次の見回りでやり直し、1 候補 AUTO_TRIES 回で諦めて「調子」の失敗(kind detect。auto_failures.json)に出す。
配信の終わり(D-14): 録画が終わっても、ワーカーが帳簿を締めた(peaks.json の ended)あと END_GRACE_SEC の間は、待ち中だった候補(waitMin がまだ・
終わり待ちだった候補が締めで確定したもの)を同じ待ちで採用する(終わった瞬間に待ち中だった候補を取りこぼさない)。
締めで本数に届かず埋めた候補(印 fill。EW の QUOTA)も枠の候補なので同じ道(origin auto = 配信中の検出の続き。依頼の afterStream は見ない)で採用して届ける。
友人のライブの依頼の録画(10-30〜。スイッチ live_batch.BATCH_ON): waitMin 分の待ちでなく、BATCH_MIN 分ごとの区切りと配信の終わりにまとめて採用する
(_batch_tick。決まりは src/flow/live_batch.py の頭)。帳簿の 1 時間の本数は live_batch.POOL_PER_HOUR(requests_cfg)。
遅れて始まった頭(10-30。src/flow/live_head.py・スイッチ live_head.HEAD_ON): 頭を別に取って検出した候補(head.json。録画の頭からの秒 = 負・source "head")も採用する。
waitMin の録画は枠の候補と同じ道で、区切りの録画は頭が取れた次の見回りで頭の分(live_batch.share(合計, 取れた秒, 配信の長さの見込み))を印 kind head で選び、
配信の終わりの合計からその分を引く。採用は Live.adopt(hold "head")= 頭の動画から書き出す。取れた秒は録れなかった所(_fill_reserve・_fill_after)から外す。
安全弁(D-13。仮の数 = 使いながら直す): 1 つの録画の自動の採用は AUTO_MAX_PER_REC 本まで(decisions.json の adopted/auto を数える。
友人の依頼の録画・確認なしに届く自分の配信の自動の分にも効く)。
(「人が見ていない」ことを理由に自動の採用を休むことはしない = 採用は全部届ける。opt-manage Q1・2a-1・2a-2)
上限の数は親の hook auto_max(rc, rec)で変えられる(RS7-2 G1b。flow/livehost.py の LiveHost。持っていなくてもよい。友人の PC = 束の adopt.top = live_adopt.top_of)。
親が持たない・None(ユーザーの PC = Live)なら AUTO_MAX_PER_REC のまま。
"""
import json
import os
import shutil
import sys
import threading
import time

from ytt import fsio, marks as _marks, procs, schemas, tools
from . import spec as _spec   # 採用の数・待ちの既定は束の 1 か所(RS6 b-R1)
from . import chatreuse as _chatreuse   # 生のチャットを移す先(決定 3-117)
from . import live_failures
from . import live_batch as LB   # 友人のライブの依頼を区切りごとにまとめて届ける(10-30)
from . import live_export as LX
from . import livehost   # 親の口の型(RS7-2 G0)
from . import lengthhint as _lengthhint   # 長さの目安を使うときに数える(OPT-E2 7f-1)
from ytt import datadir as _datadir
from pipeline.analyze import excite
from pipeline.analyze import live_excite_worker as EW   # ファイルの形・定数・設定の検査はワーカーと 1 か所。numpy などは読まない

CODE_DIR = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "pipeline", "analyze")   # 子プロセスの道具は ① の置き場(pipeline/analyze)
WORKER = os.path.join(CODE_DIR, "live_excite_worker.py")
STOP_WAIT = 8.0            # 止める合図のあと、ワーカーが自分で終わるのを待つ秒(周期 6 秒 + 保存)
STALE_SEC = 120.0          # 心拍(worker.json)がこれだけ止まったら起動し直す
LENGTH_HINT_ENV = "YTT_LIVE_LENGTH"   # off = 長さの目安を使わない(スタジオの解析の設定の長さのまま)
SETTINGS_EVERY = 60.0      # スタジオの解析の設定を読み直す間隔(10-20 に 300 → 60。設定を変えてから効くまで。入口の中の問い合わせ 1 回)
# 見回り(30 秒)の間も ADOPT_SEC ごとに自動の採用だけを見る(10-21。スイッチ ADOPT_FAST は 10-30 の片付けで外した)
ADOPT_SEC = 5.0
RESTART_WARN = 3           # 起動し直しがこれを超えたら「調子」に失敗として出す
AUTO_TRIES = 5             # 自動の採用を 1 候補で試す回数
LOG_MAX = 2 * 1024 * 1024  # logs/excite.log がこれを超えていたら、ワーカーを起動するときに .old.log へ回す
OPS = ("adopt", "dismiss", "restore")
DECISIONS_MAX = 5000
PEAKS_MAX = 16 * 1024 * 1024
# 録画を消す前に、候補の区間の一覧(数字だけ。音・映像は無し)を live/peaks-kept/<録画元>__<録画>.json へ写す(10-30 まとめ役。
# 研究で「採用しなかった候補 = 控え・見送りに正解があったか」を数える材料。peaks.json はフォルダごと消える)。写せなくても消すのは止めない
KEEP_ON = True             # False = 前の形(写さずに消す)
KEEP_DIR = "peaks-kept"
KEEP_DAYS = 30             # 写しを残す日数(研究で使うので片付けの 3 日より長め。写すたびに、これより古い写しを消す)
DETECT_DEFAULT = {"enabled": True, "sens": "normal", "perHour": _spec.DEFAULTS["adopt"]["perHour"], "fill": True}   # fill = 配信の終わりの本数の埋め(EW の QUOTA)
ADOPT_DEFAULT = {"waitMin": _spec.DEFAULTS["adopt"]["waitMin"]}
CHAT_ORDER = ("none", "restarting", "ok", "off")   # 「調子」に出すチャットの状態(悪い順)


def _dump(obj):
    """入口が書く JSON(config.json・decisions.json・auto_failures.json)のバイト列"""
    return json.dumps(obj, ensure_ascii=False, indent=1).encode("utf-8")


def clean_spec(an):
    """スタジオの解析の設定(settings-ui.json の analyze)→ ワーカーの spec(範囲外は丸め、読めなければ既定。仮決め (bn))"""
    an = an if isinstance(an, dict) else {}
    out = dict(EW.SPEC_DEFAULT)
    for k, (lo, hi) in EW.SPEC_RANGES.items():
        v = an.get(k)
        if isinstance(v, (int, float)) and not isinstance(v, bool) and v == v:
            out[k] = float(min(hi, max(lo, v)))
    out["lagAuto"] = an.get("lagAuto") is not False
    if an.get("shape") in EW.excite.SHAPES:   # 区間の形(LD-2b。無ければワーカーがスイッチ excite.SHAPE_DEFAULT)
        out["shape"] = an["shape"]
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
SEEN_FILE = "seen.json"    # _seen を入口の起き直しの間も残す(live/excite/seen.json。起動時に読み戻す)
SEEN_KEEP_SEC = 3600       # M11 の「最初に見た時刻」(_seen)を、見回りで見かけなくなってから残す秒(繋ぎ直しで同じ候補が戻る分は残す)
END_GRACE_SEC = 6 * 3600   # D-14: 録画が終わってからこの秒数の間は、締めで確定した候補も待ち中の候補も採用する(それより古い録画の候補はまとめて採用しない)
AUTO_MAX_PER_REC = 10      # D-13(仮の数): 1 つの録画で自動で採用する本数の上限(人のマーク・配信後の解析 archive は数えない)


def merge_spans(spans):
    """[(から, まで)] を時刻の順に並べて、重なり・接するものを 1 つにまとめる(EV-1 の穴)"""
    out = []
    for x, y in sorted(spans):
        if out and x <= out[-1][1]:
            out[-1] = (out[-1][0], max(out[-1][1], y))
        else:
            out.append((x, y))
    return out


def measured_holes(doc, first, span):
    """peaks.json(doc)から、配信中の検出が測っていない所 [(から, まで)](録画の頭からの秒。EV-1):
    検出の頭(doc の first)が録画の頭より後ならその間・measuredSec が録画の長さより短ければその後ろ・遅れて飛ばした区間(skipped の from〜to。検出の頭からの秒)。
    読めない欄は飛ばす(穴にしない)"""
    def num(x):
        return isinstance(x, (int, float)) and not isinstance(x, bool)
    d0 = LX.iso_epoch(doc.get("first")) if isinstance(doc.get("first"), str) else (doc.get("first") if num(doc.get("first")) else None)
    d0 = (d0 - first) if d0 is not None else 0.0
    out = []
    if d0 > 1.0:
        out.append((0.0, min(span, d0)))
    m = doc.get("measuredSec")
    if num(m) and d0 + m < span - 1.0:
        out.append((max(0.0, d0 + m), span))
    for sk in doc.get("skipped") or []:
        if isinstance(sk, dict) and num(sk.get("from")) and num(sk.get("to")) and sk["to"] > sk["from"]:
            out.append((max(0.0, d0 + sk["from"]), min(span, d0 + sk["to"])))
    return [(x, y) for x, y in out if y > x]


class Detector:
    def __init__(self, host: "livehost.LiveHost", python=None, spawn=True, worker=WORKER, stale_sec=STALE_SEC, clock=time.time):
        """host: 親(flow/livehost.py の LiveHost。flow/livesession.py の LiveSession。設定・録画元・adopt・list_recordings・studio_call・store_dir・logs_dir)。
        テストは spawn=False(ワーカーを起動しない)か、worker に偽のワーカーを渡す・stale_sec を縮める"""
        self.host = host
        self.python = python or sys.executable
        self.spawn_ok, self.worker, self.stale_sec, self.clock = spawn, worker, stale_sec, clock
        self.ffmpeg = lambda: tools.find_tool("ffmpeg")
        self.ytdlp = lambda: tools.find_tool("yt-dlp")
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
        self._seen_loaded = False          # seen.json を読み戻したか(最初の auto_tick で 1 回)
        self._seen_dirty = False           # _seen を消した(seen.json を書き直す)
        self.adopted = None                # 前の入口が残したワーカーを引き継いだときの pid(この入口は Popen を持たない)
        self.retired = None                # 受け持ちが無いので止めて、この入口の版で起こし直した前のワーカーの pid(起き直しの確かめで違いにしない)
        self._fails = None                 # 自動の採用を諦めた候補(auto_failures.json)
        self._series = fsio.StampCache()   # series.jsonl の読み取りの覚え(更新日時と大きさが変わったときだけ読み直す)
        self._capped_said = set()          # D-13: 上限に達した録画(記録に 1 回だけ出す)
        self._hint = _lengthhint.Tracker(LENGTH_HINT_ENV, "盛り上がりの検出", lambda s: self.host.note(s))   # 長さの目安(切り替わったら記録に 1 行)

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
        """自動の採用の待つ分 {"waitMin"}(ホームの設定 live.autoAdopt。自動の採用はいつもオン = 保存してある enabled は読まない)"""
        a = self._sub("autoAdopt", ADOPT_DEFAULT)
        return {"waitMin": a.get("waitMin") if isinstance(a.get("waitMin"), int) else ADOPT_DEFAULT["waitMin"]}

    def enabled(self):
        """検出を動かすか: リアルタイム切り抜きがオンで、検出のスイッチがオンか、友人のライブ配信の依頼の録画がある(2-15: 友人の録画は常に動かす)"""
        return self.host.enabled() and (self.detect_cfg().get("enabled") is True or bool(self.requests_cfg()))

    def requests_cfg(self):
        """友人のライブ配信の依頼の録画ごとの設定(config.json の requests。ワーカーはこの録画を、ホームの検出がオフでも測り、感度・枠・長さをこの値で)"""
        # settings は live_rules.RequestBook が検査済み(無い鍵・範囲の外は既定 = live_requests.SETTINGS_DEFAULT。読み直した項目も)
        # lengthMode auto(長さ「自動(場面ごと)」。C-2-11)だけ渡す = 無ければ固定の長さ(前の形の依頼)
        # 区切りごとにまとめて届ける形(live_batch.on)は、帳簿の 1 時間の本数を候補の元の本数(POOL_PER_HOUR)にする(配信の終わりに選ぶ分を残す)
        return {k: dict({x: v["settings"][x] for x in ("sens", "perHour", "length")}, **({"lengthMode": "auto"} if v["settings"].get("lengthMode") == "auto" else {}),
                        **({"perHour": LB.POOL_PER_HOUR} if LB.on(v) else {}))
                for k, v in self.host.requests.all().items()}

    def adopt_for(self, req, rc=None, rec=None):
        """録画ごとの自動の採用の待ち {"waitMin"}: 友人の依頼の録画(req = live.requests.get の項目)は依頼の waitMin(2-15)、
        ほかはホームの設定(adopt_cfg)。録画(rc・rec)に束があれば待ちは束の adopt.waitMin(録画を始めたときの値。RS7-2 G2b)"""
        if req is None:
            a = self.adopt_cfg()
            b = self._bundle(rc, rec)
            return dict(a, waitMin=b["adopt"]["waitMin"]) if b is not None else a
        return {"waitMin": req["settings"]["waitMin"]}   # Store が検査済み(1〜60 の整数)

    def wake(self):
        """友人の依頼で録画を始めた直後: 次の見回りを待たずに config.json を書いてワーカーを起こす"""
        try:
            self.tick()
        except Exception as e:   # noqa: BLE001  (起こせなくても見回りが拾う)
            self.host.note("盛り上がりの検出: 友人の依頼で起こせませんでした: %r" % (e,))

    def _bundles(self):
        """親の録画ごとの束 {"<録画元>/<録画>": 束}(flow/livesession.py の BundleBook。RS7-2 G2b)。親が持たない・読めなければ {}"""
        bk = getattr(self.host, "bundles", None)
        try:
            out = bk.specs() if bk is not None else {}
        except Exception:   # noqa: BLE001  (束を読めなければ束なしと同じ = スタジオの設定・ホームの設定)
            out = {}
        return out if isinstance(out, dict) else {}

    def _bundle(self, rc, rec):
        """その録画の束か None"""
        bk = getattr(self.host, "bundles", None)
        try:
            b = bk.spec(rc, rec) if bk is not None and rc and rec else None
        except Exception:   # noqa: BLE001
            b = None
        return b if isinstance(b, dict) else None

    def bundles_cfg(self):
        """config.json の bundles: 束のある録画ごとの解析の設定(spec)・感度・枠(録画を始めたときの束 = 決定 3-31 の仮 b1。ワーカーは友人の依頼の設定 > 束 > ホームの設定の順)"""
        return {k: {"spec": clean_spec(b.get("analyze")), "sens": b["adopt"]["sens"], "perHour": b["adopt"]["perHour"]}
                for k, b in self._bundles().items() if isinstance(b, dict) and isinstance(b.get("adopt"), dict)}

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
        bc = self.bundles_cfg()
        return {"v": 1, "dir": self.dir, "recorders": [{"id": r["id"], "url": r.get("url") or "", "token": r.get("token") or ""} for r in self.host.recorders()],
                "detect": EW.clean_detect(self.detect_cfg()), "spec": self.spec(), "ffmpeg": self.ffmpeg(), "ytdlp": self.ytdlp(),
                "chatLimitBytes": self.chat_limit, "chatStallSec": self.chat_stall, "lengthHint": self._length_hint(),
                "detectAll": self.detect_cfg().get("enabled") is True, "requests": self.requests_cfg(),   # 友人の依頼の録画(2-15)
                "quotaFill": self.detect_cfg().get("fill") is not False,   # 配信の終わりの本数の埋め(EW の QUOTA。友人の PC は設定が無い = オン)
                **({"bundles": bc} if bc else {}),   # 束のある録画(RS7-2 G2b。無ければ書かない = 今までの config.json のまま)
                **({"chatKeepDir": keep} if (keep := _chatreuse.keep_dir(self.host.store_dir)) else {})}   # 生のチャットを移す先(決定 3-117。② が決める)

    def _length_hint(self):
        """M10: 人が選んだ区間の長さの目安(② flow/lengthhint がその場で数える = 友人が依頼で指定した区間。enough のときだけワーカーが使う)。
        止めてある(環境変数 YTT_LIVE_LENGTH=off)・数えられなければ None。使う ⇄ 使わない・長さが変わったら記録と調子に 1 行(7f-2)"""
        h = self._hint.read(_datadir.resolve("studio", self.host.root), _datadir.resolve("app", self.host.root))
        if h is None:
            return None
        return {"length": h["length"], "preRatio": h["preRatio"], "samples": h["samples"], "videos": h["videos"], "enough": h["enough"], "file": "flow/lengthhint"}

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

    def adopt_tick(self):
        """見回りの間の自動の採用だけ(ADOPT_SEC ごと。ワーカーの起動・設定は tick の 30 秒ごとのまま)。
        候補を入口が最初に見る時刻と、waitMin 分たってから採用する時刻の遅れを 30 秒 → 数秒に。決まり(waitMin・上限)は同じ -> 採用した数"""
        if (self.proc is None and self.adopted is None) or not ((self.heartbeat() or {}).get("recordings")):   # この入口のワーカーが録画を測っている間だけ(録画元に聞かない)
            return 0
        if not self._tick_lock.acquire(blocking=False):   # tick と重ねない
            return 0
        try:
            return self.auto_tick()
        finally:
            self._tick_lock.release()

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

    def adoptable(self, hb=None, leaving=False):
        """前の入口が残したワーカーを引き継げるか: 心拍が stale_sec 以内・「止まりました」でない・その pid が生きている・
        親(心拍の parent)が生きていない(親の無い古い心拍も可。引き継いだ後はこの入口)-> pid か None。
        leaving: この入口がこれから終わる(handover_ok)= 親がこの入口でもよい"""
        hb = self.heartbeat() if hb is None else hb
        pid = (hb or {}).get("pid")
        age = self._hb_age(hb)
        if age is None or age > self.stale_sec or hb.get("message") == "止まりました" or pid == os.getpid() or not procs.pid_alive(pid):
            return None
        par = hb.get("parent")
        if pid == self.adopted or (leaving and par == os.getpid()):
            return pid
        return None if par == os.getpid() or procs.pid_alive(par) else pid

    def _adopt(self):
        """Popen を持たない間: 前の入口のワーカーが録画を測っていれば引き継ぐ(起こし直すと自動の採用の待ち・チャットの取得が途切れる)。
        受け持ちが無ければ止めて、この入口の版で起こす。-> "adopted" か None(起こしてよい)"""
        hb = self.heartbeat()
        pid = self.adoptable(hb)
        if pid is None:
            self.adopted = None
            return None
        if not hb.get("recordings"):
            self._stop_pid(pid)
            self.adopted, self.retired = None, pid
            return None
        if self.adopted != pid:
            fsio.atomic_write(os.path.join(self.dir, EW.PARENT_NAME), json.dumps({"pid": os.getpid()}).encode("utf-8"))   # ワーカーの新しい親
            self.adopted = pid
            self.host.log("盛り上がりの検出: 前のホームのワーカー(pid %d)を引き継ぎました" % pid)
        return "adopted"

    def _stop_pid(self, pid):
        """Popen を持たないワーカーを止める合図(EW.STOP_NAME)を書き、STOP_WAIT 秒まで終わりを待つ"""
        try:
            fsio.atomic_write(os.path.join(self.dir, EW.STOP_NAME), b"stop")
        except OSError:
            return
        end = time.monotonic() + STOP_WAIT
        while procs.pid_alive(pid) and time.monotonic() < end:
            time.sleep(0.2)
        self.host.log("盛り上がりの検出: 前のホームのワーカー(pid %d)を止めました" % pid)

    def _ensure(self):
        p = self.proc
        if p is None and self._adopt():
            return "adopted"
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
            self.proc = tools.start_logged(cmd, os.path.join(self.host.logs_dir, "excite.log"), CODE_DIR,
                                     tools.no_window_flags(new_group=True, priority="low"), rotate=LOG_MAX)
        except OSError as e:
            self.host.note("盛り上がりの検出: ワーカーを起動できませんでした: %s" % tools.why(e))
            return False
        self.started_at = self.clock()
        self.host.log("盛り上がりの検出: ワーカーを起動しました(pid %d)" % self.proc.pid)
        return True

    def _kill(self, p):
        """まず穏やかに(止める合図のファイル EW.STOP_NAME = ワーカーが周期の合間に見て、状態を保存し心拍に「止まりました」を書いて終わる。
        窓なしで起こした子には CTRL_BREAK が届かない)、STOP_WAIT 秒で終わらなければ terminate・kill"""
        try:
            fsio.atomic_write(os.path.join(self.dir, EW.STOP_NAME), b"stop")
            p.wait(STOP_WAIT)
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
        pid, self.adopted = self.adopted, None
        if pid is not None and procs.pid_alive(pid):
            self._stop_pid(pid)

    # ---- 候補を読む
    def folder(self, rc, rec):
        return os.path.join(self.dir, rc, rec)

    def forget(self, rc, rec, row=None):
        """録画を消したとき(src/manage/keep/live_cleanup.py): その録画の検出の記録(state.json・series.jsonl・peaks.json・decisions.json)も消す。
        消す前に候補の区間の一覧を写す(KEEP_ON。row = 録画元の一覧の 1 行 = url・firstPdt・streamStart。無ければ配信の記録 reports から)"""
        if schemas.ids_ok(rc, rec):
            if KEEP_ON:
                self.keep_peaks(rc, rec, row)
            shutil.rmtree(self.folder(rc, rec), ignore_errors=True)

    @property
    def keep_dir(self):
        return os.path.join(self.host.store_dir, KEEP_DIR)

    def keep_peaks(self, rc, rec, row=None, now=None):
        """候補の区間の一覧を keep_dir へ写す -> 写したパスか None(候補が無い・書けない)。
        1 行 = {id, state(frame|bench|adopted|dismissed), origin, start, end, peak(録画の頭からの秒), streamStart・streamEnd(配信の開始からの秒。分かるときだけ),
        score, provisional, expired, fill, pieces}"""
        try:
            doc, peaks, _pending = self.view(rc, rec)
            if not peaks:
                return None
            row = row if isinstance(row, dict) else {}
            rep = fsio.read_json_or(os.path.join(self.host.store_dir, "reports", "%s__%s.json" % (rc, rec)), None, 4 * 1024 * 1024, kind=dict) or {}
            info = rep.get("info") if isinstance(rep.get("info"), dict) else {}

            def at(v):
                return float(v) if isinstance(v, (int, float)) and not isinstance(v, bool) else LX.iso_epoch(v)
            url = row.get("url") or info.get("url") or ""
            first = at(row.get("firstPdt")) or at((doc or {}).get("first")) or at(info.get("firstPdt"))
            ss = at(row.get("streamStart"))
            off = round(first - ss, 1) if first is not None and ss is not None and ss <= first else None   # 録画の頭 = 配信の開始から off 秒
            items = []
            for p in peaks:
                s, e = p.get("start"), p.get("end")
                if not all(isinstance(x, (int, float)) and not isinstance(x, bool) for x in (s, e)):
                    continue
                it = {"id": p.get("id"), "state": p.get("state"), "origin": p.get("origin"), "start": s, "end": e, "peak": p.get("peak"), "score": p.get("score")}
                if off is not None:
                    it["streamStart"], it["streamEnd"] = round(s + off, 1), round(e + off, 1)
                for k in ("provisional", "expired", "fill"):
                    if p.get(k):
                        it[k] = True
                if p.get("pieces"):
                    it["pieces"] = p.get("pieces")
                items.append(it)
            out = {"v": 1, "recorder": rc, "recording": rec, "videoId": LX.video_id_of(url, rec) or None, "url": url,
                   "title": row.get("title") or info.get("title") or "", "firstPdt": LX.epoch_iso(first) if first is not None else None,
                   "streamStart": LX.epoch_iso(ss) if ss is not None else None, "streamOffset": off, "keptAt": LX.now_iso(),
                   "detect": {k: (doc or {}).get(k) for k in ("perHour", "thr", "shape", "ended", "measuredSec", "lateFrom", "audioOnly")},
                   "peaks": items}
            os.makedirs(self.keep_dir, exist_ok=True)
            path = os.path.join(self.keep_dir, "%s__%s.json" % (rc, rec))
            fsio.write_json(path, out, indent=1)
        except Exception as e:   # noqa: BLE001  (写せなくても録画の後始末は止めない)
            self.host.note("リアルタイム切り抜き: 候補の区間を写せませんでした(%s): %r" % (rec, e))
            return None
        self._trim_kept(now)
        return path

    def _trim_kept(self, now=None):
        """KEEP_DAYS より古い写しを消す(更新日時で)"""
        limit = (now if now is not None else time.time()) - KEEP_DAYS * 86400
        try:
            names = [n for n in os.listdir(self.keep_dir) if n.endswith(".json")]
        except OSError:
            return
        for n in names:
            p = os.path.join(self.keep_dir, n)
            try:
                if os.path.getmtime(p) < limit:
                    os.remove(p)
            except OSError:
                pass

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
        """series.jsonl を読んで 600 点にする(series の読み直し。読み方はワーカーと 1 か所 = EW.read_series)。読めなければ None"""
        cols = EW.read_series(p)
        if cols is None:
            return None
        n = cols["n"]
        return {"n": n, "step": max(1.0, n / 600.0), **{k: excite.downsample(cols[k]) for k in ("total", "audio", "chat")}}

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
        req = self.host.requests.get(rc, rec)   # 友人のライブ配信の依頼の録画は、ホームの検出がオフでも依頼の設定で動く(2-15)
        seq = int((doc or {}).get("seq") or 0)
        out = {"ok": True, "enabled": self.enabled() and (det.get("enabled") is True or req is not None), "recorder": rc, "recording": rec, "seq": seq,
               "worker": self.worker_view(doc),
               "hour": {"perHour": (doc or {}).get("perHour") or det.get("perHour") or DETECT_DEFAULT["perHour"], "counts": (doc or {}).get("counts") or {}},
               "autoAdopt": self.adopt_for(req, rc, rec), "changes": [], "tx": self.host.livetx.status()}
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
    def decide(self, rc, rec, pid, state, origin=None, mark_id=None, job_id=None, batch=None):
        """decisions.json に 1 件足す(ワーカーが読んで帳簿に当てる)-> 足した決定。batch = 区切りの印(区切りごとにまとめて届ける形の採用だけ)"""
        folder = self.folder(rc, rec)
        with self.lock:
            d = self._decisions(folder)
            n = d["n"] + 1
            item = {"n": n, "id": pid, "state": state, "origin": origin, "markId": mark_id, "jobId": job_id, "at": LX.now_iso(),
                    **({"batch": batch} if batch is not None else {})}
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

    def adopt(self, rc, rec, pk, origin, after=None, streamer=None, batch=None):
        """候補を M1 の採用(Live.adopt)に通して、決定を残す -> API の応答の形。batch = 区切りの印(live_batch.mark。ジョブ・.clip.json・決定に残す)"""
        body = {"recorder": rc, "recording": rec, "start": pk["start"], "end": pk["end"], "label": "", "origin": origin}
        if batch is not None:
            body["batch"] = batch
        if schemas.is_num(pk.get("score")):
            body["score"] = pk["score"]   # 候補の点数を切り抜きの記録(.clip.json の source.live.score)に残す(M9 の一覧が出す)
        if after is not None:
            body["after"] = after
        if streamer is not None:
            body["streamer"] = streamer
        text = self.host.livetx.text_for(rc, rec, pk.get("id"))   # 配信中の文字起こしの文字があれば採用の記録に(D-11 案 b)
        if text:
            body["text"] = text
        res = self.host.adopt(body, "head") if pk.get("source") == "head" else self.host.adopt(body)   # 頭の候補(10-30)は頭の動画から書き出す
        job = res.get("job") or {}
        item = {"state": "adopted", "origin": pk.get("origin") or origin, "markId": pk.get("markId"), "jobId": pk.get("jobId")}
        if pk.get("state") != "adopted" or pk.get("markId") != res.get("mark"):
            item = self.decide(rc, rec, pk["id"], "adopted", origin=origin, mark_id=res.get("mark"), job_id=job.get("id"), batch=batch)
        return {"ok": True, "peak": overlay(pk, item), "job": res.get("job"), "video": res.get("video"), "mark": res.get("mark"),
                "existing": bool(res.get("existing")), "origin": res.get("origin")}

    # ---- 自動の採用(M11)
    def _load_fails(self):
        """自動の採用を諦めた候補(auto_failures.json。最初の 1 回だけ読み、あとは覚えた一覧に足して書く)"""
        if self._fails is None:
            d = fsio.read_json_or(os.path.join(self.dir, "auto_failures.json"), None, 1024 * 1024, kind=dict) or {}
            self._fails = [x for x in d.get("items") or [] if isinstance(x, dict)]
        return self._fails

    def given_up(self, rc, rec):
        """その録画で自動の採用を諦めた候補(auto_failures.json の写し。古い順)"""
        with self.lock:
            return [dict(x) for x in self._load_fails() if x.get("recorder") == rc and x.get("recording") == rec]

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

    def auto_max(self, rc, rec):
        """D-13: その録画の自動の採用の上限(本数)。親の auto_max(rc, rec)(友人の PC = 束の adopt.top)があればその値、無い・None・形が違えば AUTO_MAX_PER_REC。
        区切りごとに届ける録画(live_batch.on)は BATCH_LIVE + BATCH_END 本より小さくしない(10-30 不具合: 友人の PC の上限は束の既定 3 で、4 + 2 が 3 本で止まった)"""
        cap = self._auto_max(rc, rec)
        return max(cap, LB.max_total()) if LB.on(self.host.requests.get(rc, rec)) else cap

    def _auto_max(self, rc, rec):
        fn = getattr(self.host, "auto_max", None)
        if fn is None:
            return AUTO_MAX_PER_REC
        try:
            v = fn(rc, rec)
        except Exception as e:   # noqa: BLE001  (上限を読めない不具合で自動の採用を止めない = 今の上限で続ける)
            self.host.note("盛り上がりの検出: 自動の採用の上限を読めませんでした(%s 本で続けます): %r" % (AUTO_MAX_PER_REC, e))
            return AUTO_MAX_PER_REC
        return v if isinstance(v, int) and not isinstance(v, bool) and v >= 0 else AUTO_MAX_PER_REC

    def auto_count(self, rc, rec, peaks=None):
        """その録画で自動(origin auto)で採用した数(decisions.json。D-13 の上限の分母)。つないだ候補は元の本数(peaks.json の pieces。
        10-28 ユーザー「つないだ物は元の本数で数える」)。peaks = view の候補の一覧(無ければ読む)"""
        if peaks is None:
            peaks = self.view(rc, rec)[1]
        n_of = {p.get("id"): _marks.pieces_of(p) for p in peaks}
        return sum(n_of.get(x.get("id"), 1) for x in self._decisions(self.folder(rc, rec))["items"] if x.get("state") == "adopted" and x.get("origin") == "auto")

    def adopt_waiting(self, rc, rec):
        """録画の、自動の採用を待っている枠の候補 -> {"count", "dueAt"(いちばん早く採用する時刻 epoch。まだ見ていなければ None)}・
        上限に達した = {"capped": 上限の本数} か None(待ちが無い)。読むだけ(友人のアプリの録画中の行に「候補 2 件・約 4 分後に切り抜きます」を出す)"""
        cap = self.auto_max(rc, rec)
        if self.auto_count(rc, rec) >= cap:
            return {"capped": cap}
        doc, peaks, _pending = self.view(rc, rec)
        if LB.on(self.host.requests.get(rc, rec)):
            return self._batch_waiting(rc, rec, doc, peaks)
        given = {x.get("id") for x in self.given_up(rc, rec)}
        left = [pk for pk in peaks if pk.get("state") == "frame" and not pk.get("provisional") and pk.get("id") not in given
                and isinstance(pk.get("confirmedAt"), (int, float))]
        if not left:
            return None
        wait = self.adopt_for(self.host.requests.get(rc, rec), rc, rec)["waitMin"] * 60
        due = [self._seen[(rc, rec, pk.get("id"))] + wait for pk in left if (rc, rec, pk.get("id")) in self._seen]
        return {"count": len(left), "dueAt": min(due) if due else None}

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
        D-13: 1 録画 auto_max 本まで(既定 AUTO_MAX_PER_REC)。自動の採用はいつもオン(オフのスイッチは 10-19 に消した)"""
        now = self.clock()
        self._load_seen(now)
        n_seen = len(self._seen)
        try:
            return self._auto_tick(now)
        finally:
            if len(self._seen) != n_seen or self._seen_dirty:
                self._save_seen()

    def _load_seen(self, now):
        """seen.json を 1 回だけ読み戻す(入口を起き直しても waitMin の起点が延びない)。最後に見た時刻は今にする(1 時間見かけなければ消える)"""
        if self._seen_loaded:
            return
        self._seen_loaded = True
        self._seen_dirty = False
        d = fsio.read_json_or(os.path.join(self.dir, SEEN_FILE), {}, 1024 * 1024, kind=dict)
        for x in d.get("seen") or []:
            if isinstance(x, list) and len(x) == 4 and all(isinstance(v, str) for v in x[:3]) and schemas.is_num(x[3]):
                key = (x[0], x[1], x[2])
                self._seen.setdefault(key, float(x[3]))
                self._seen_at.setdefault(key, now)

    def _save_seen(self):
        self._seen_dirty = False
        try:
            os.makedirs(self.dir, exist_ok=True)
            fsio.atomic_write(os.path.join(self.dir, SEEN_FILE), _dump({"v": 1, "seen": [[k[0], k[1], k[2], t] for k, t in self._seen.items()]}))
        except OSError as e:
            self.host.note("盛り上がりの検出: %s を書けませんでした: %s" % (SEEN_FILE, tools.why(e)))

    def _auto_tick(self, now):
        for key in [k for k, t in self._seen_at.items() if now - t > SEEN_KEEP_SEC]:   # 採用した・録画が終わった候補の分は残さない(録画のたびに増え続けない)
            self._seen.pop(key, None)
            self._seen_at.pop(key, None)
            self._seen_dirty = True
        if not self.enabled() or not self.running():   # ワーカーが止まっている間は採用しない(古い候補をまとめて採用しないため)
            return 0
        # 依頼の無い録画は、ホームの検出がオンのときだけ(友人の依頼だけで検出が動いている間に、止めた録画の古い候補を採用しない)
        home = self.detect_cfg().get("enabled") is True
        if not home and not self.requests_cfg():   # 採用する録画が無い(録画元に聞かない)
            return 0
        done = 0
        given = {(x.get("recorder"), x.get("recording"), x.get("id")) for x in self._load_fails()}
        for r, ended in self._target_recordings(now):
            rc, rec = r["recorder"], r["id"]
            req = self.host.requests.get(rc, rec)   # 友人のライブ配信の依頼の録画は、ホームの検出がオフでも採用する(待ちは依頼の設定。2-15)
            if req is None and not home:
                continue
            wait_min = self.adopt_for(req, rc, rec)["waitMin"]
            doc, peaks, _pending = self.view(rc, rec)
            if ended and not (doc or {}).get("ended"):   # 終わった録画は、ワーカーが帳簿を締めてから(終わり待ちの候補が確定する)
                continue
            if LB.on(req):   # 友人のライブの依頼: 区切りごとにまとめて(10-30。waitMin の待ちは使わない)
                done += self._batch_tick(rc, rec, doc, peaks, given, r)
                continue
            used, cap = self.auto_count(rc, rec, peaks), self.auto_max(rc, rec)
            for pk in peaks + self._head_peaks(rc, rec):   # 遅れて始まった頭の候補も同じ待ちで(10-30)
                key = (rc, rec, pk.get("id"))
                if pk.get("state") != "frame" or pk.get("endPending") or key in given or not isinstance(pk.get("confirmedAt"), (int, float)):
                    continue   # 終わり待ち(区間の終わりがまだ録れていない)は、合わせ直されてから
                # 待ちは入口が候補を最初に見た時刻から数える(画面に出てから人が見られる時間を waitMin 分とる。
                # 録画の秒(confirmedAt)で比べると、ワーカーの遅れの分だけ人が見られる時間が短くなる)
                first = self._seen.setdefault(key, now)
                self._seen_at[key] = now
                if now - first < wait_min * 60:
                    continue
                if used >= cap:   # D-13: この録画はもう上限(候補は帯に残る = 人が採用できる)
                    if rec not in self._capped_said:
                        self._capped_said.add(rec)
                        self.host.log("盛り上がりの検出: 録画 %s の自動の採用は上限の %d 本に達したので、残りの候補は人の採用に任せます" % (rec, cap))
                    break
                if used + _marks.pieces_of(pk) > cap:   # つないだ候補(元の本数)が残りに入らない: 人の採用に任せて次の候補へ
                    continue
                try:
                    self.adopt(rc, rec, pk, "auto", after="auto")
                    self._tries.pop(key, None)
                    done += 1
                    used += _marks.pieces_of(pk)
                except LX.LiveError as e:
                    n = self._tries.get(key, 0) + 1
                    self._tries[key] = n
                    if e.code not in (502, 409) or n >= AUTO_TRIES:
                        self._tries.pop(key, None)
                        self._give_up(rc, rec, pk, "%s(%d 回試しました)" % (e, n))
                        given.add(key)
        return done

    # ---- 区切りごとにまとめて届ける(友人のライブの依頼。10-30。決まりは flow/live_batch.py)
    def _batch_tick(self, rc, rec, doc, peaks, given, r=None):
        """区切り(BATCH_MIN 分ごと)を過ぎた・帳簿を締めた録画の候補を選んで採用の待ちに積み、待ちを採用する -> 採用した数。
        r = 録画元の一覧の 1 行(firstPdt・lastPdt。配信の終わりの合計 = live_batch.total に使う)"""
        if doc is None:
            return 0
        folder = self.folder(rc, rec)
        st = LB.load(folder)
        dirty = False
        busy = {x["id"] for x in st["queue"]}
        heads = self._head_peaks(rc, rec)
        by_id = {p.get("id"): p for p in peaks + heads}
        used, cap = self.auto_count(rc, rec, peaks), self.auto_max(rc, rec)
        queued = sum(_marks.pieces_of(by_id.get(x["id"]) or {}) for x in st["queue"])
        live_done = sum(_marks.pieces_of(by_id.get(x.get("id")) or {}) for x in self._decisions(folder)["items"]
                        if x.get("state") == "adopted" and x.get("origin") == "auto" and (x.get("batch") or {}).get("kind") == "live")
        live_done += sum(_marks.pieces_of(by_id.get(x["id"]) or {}) for x in st["queue"] if x["batch"]["kind"] == "live")
        long_end = LB.LONG_ON and schemas.is_num(doc.get("measuredSec")) and doc["measuredSec"] > LB.LONG_AFTER
        if heads and st.get("head") is None and not st["end"]:   # 遅れて始まった頭が取れた(10-30): 頭の分を選ぶ
            dirty = self._batch_head(rc, rec, doc, st, heads, given, cap - used - queued) or dirty
        if doc.get("ended") and not st["end"]:
            n_all = self._batch_total(rc, rec, r, st)   # 合計(配信の長さで。live_batch.SCALE_ON)
            n_all -= len((st.get("head") or {}).get("ids") or [])   # 頭の分はもう選んだ(10-30)
            n_all -= self._fill_reserve(rc, rec, r, st, n_all, live_done)   # 録れなかった所の分を空ける(live_batch.FILL_ON)
        if doc.get("ended") and long_end:
            if not st["end"]:   # 長い配信の終わり(研究の 270 番 = 最後の区切り): 前の区切りより後に区間の決まった候補から合計までの残りを
                seen = set(st["seen"])
                room = min(n_all - live_done, cap - used - queued)
                fresh = [p for p in peaks if p.get("id") not in busy and (rc, rec, p.get("id")) not in given]
                taken = [by_id[x["id"]] for x in st["queue"] if x["id"] in by_id]
                adopted = [p for p in peaks if LB.settled(p) and p.get("state") == "adopted"]
                picks = LB.take(LB.ranked([p for p in fresh if LB.settled(p) and p["id"] not in seen]), room, adopted + taken)
                # 足りない分は候補の元の全部から(最終の候補の点の順・採用済み・選んだ物と重ならない物。10-30: 3 時間を少し過ぎて終わると、
                # 前の区切りより後に候補が無く 6 本に届かなかった)
                left = room - sum(_marks.pieces_of(p) for p in picks)
                if left > 0:
                    got = {p["id"] for p in picks}
                    picks += LB.take(LB.ranked([p for p in fresh if LB.settled(p) and p["id"] not in got]), left, adopted + taken + picks)
                for pk, cut in self._batch_trim(rc, rec, folder, by_id, st, picks, "live"):
                    st["queue"].append({"id": pk["id"], "batch": dict(LB.mark("live", st["round"] + 1, long=True), **cut)})
                st["end"], dirty = True, True
        elif doc.get("ended"):
            if not st["end"]:   # 配信の終わり: 候補の元の全部から、届けた・待ちの候補と重ならない残りを
                room = min(n_all - live_done, cap - used - queued)
                taken = [by_id[x["id"]] for x in st["queue"] if x["id"] in by_id]
                pool = [p for p in peaks if p.get("id") not in busy and (rc, rec, p.get("id")) not in given]
                picks = LB.take(LB.ranked([p for p in pool if LB.settled(p)]), room, [p for p in pool if LB.settled(p) and p.get("state") == "adopted"] + taken)
                for pk, cut in self._batch_trim(rc, rec, folder, by_id, st, picks, "end"):
                    st["queue"].append({"id": pk["id"], "batch": dict(LB.mark("end", None), **cut)})
                st["end"], dirty = True, True
        else:
            k = LB.round_of(doc.get("measuredSec"))   # 3 時間を過ぎたら 60 分ごと(live_batch.LONG_ON)
            if k > st["round"]:   # 区切りを過ぎた(続けて過ぎていれば 1 回にまとめる)
                seen = set(st["seen"])
                room = min(LB.quota(k) - live_done, cap - used - queued)
                fresh = [p for p in peaks if p.get("id") not in busy and (rc, rec, p.get("id")) not in given]
                for pk in LB.pick_live(fresh, seen, room):
                    st["queue"].append({"id": pk["id"], "batch": LB.mark("live", k, long=LB.is_long(k))})
                st["seen"] = sorted(seen | {p["id"] for p in peaks if LB.settled(p)})
                st["round"], dirty = k, True
        done = 0
        left = []
        for x in st["queue"]:
            pk = by_id.get(x["id"])
            key = (rc, rec, x["id"])
            if pk is None or pk.get("state") in ("adopted", "dismissed") or key in given:   # もう採用した・人が見送った・諦めた
                dirty = True
                continue
            try:
                sp, cut = LB.shrink(pk, x["batch"]["kind"])   # 終わりを笑いの収まりまで(live_batch.SHRINK_ON)
                self.adopt(rc, rec, sp, "auto", after="auto", batch=dict(x["batch"], **({"cut": cut} if cut > 0 else {})))
                self._tries.pop(key, None)
                done += 1
                dirty = True
            except LX.LiveError as e:
                n = self._tries.get(key, 0) + 1
                self._tries[key] = n
                if e.code not in (502, 409) or n >= AUTO_TRIES:
                    self._tries.pop(key, None)
                    self._give_up(rc, rec, pk, "%s(%d 回試しました)" % (e, n))
                    given.add(key)
                    dirty = True
                else:
                    left.append(x)   # 次の見回りでやり直す
        st["queue"] = left
        if dirty:
            try:
                LB.save(folder, st, _dump)
            except OSError as e:
                self.host.note("盛り上がりの検出: %s を書けませんでした: %s" % (LB.STATE_FILE, tools.why(e)))
        return done

    def _batch_head(self, rc, rec, doc, st, heads, given, room):
        """頭の分(10-30): 取れた頭の秒の割合で本数(live_batch.share。配信の長さの見込み = 頭 + 測った秒か EXPECT_SEC の長い方)を決め、
        点数の高い順に重ならない物を待ちに積む(印 kind head)。batch.json の head {n, cover, ids} に残す(配信の終わりの合計から引く)-> 書いたか"""
        hg = getattr(self.host, "head", None)
        cover = hg.cover(rc, rec) if hg is not None else 0.0
        if cover <= 0:
            return False
        length = cover + max(float(doc.get("measuredSec") or 0.0), LB.EXPECT_SEC)
        n = LB.share(LB.total(length), cover, length)
        pool = [p for p in heads if LB.settled(p) and p.get("state") != "adopted" and (rc, rec, p["id"]) not in given]
        picks = LB.take(LB.ranked(pool), max(0, min(n, room)), [])
        for pk in picks:
            st["queue"].append({"id": pk["id"], "batch": {"kind": "head"}})
        st["head"] = {"n": n, "cover": round(cover, 1), "ids": [p["id"] for p in picks]}
        self.host.log("盛り上がりの検出: 録画 %s は頭の %.1f 分が取れたので、頭の分を %d 本選びました(見込み %d 本)" % (rec, cover / 60.0, len(picks), n))
        return True

    def _head_peaks(self, rc, rec):
        """遅れて始まった頭の候補(live_head。録画の頭からの秒 = 負)に、この録画の決定(decisions.json の最後の物)を重ねた一覧。
        ワーカーの帳簿に無い候補なので、decN に関係なく重ねる"""
        hg = getattr(self.host, "head", None)
        pks = hg.peaks(rc, rec) if hg is not None else []
        if not pks:
            return []
        last = {}
        for it in sorted(self._decisions(self.folder(rc, rec))["items"], key=lambda x: x["n"]):
            last[it.get("id")] = it
        return [overlay(p, last[p["id"]]) if p["id"] in last else p for p in pks]

    def _batch_trim(self, rc, rec, folder, by_id, st, picks, kind):
        """配信の終わりに選んだ候補を、確かめる時間の見込みが live_batch.TRIM_LIM 分以下になるまで後ろから外す -> [(候補, 印に足す欄)]。
        届けた分 = 区切りの形で自動で採用した候補(縮めた秒 cut を引く)+ 採用を待つ候補(縮めた後)"""
        done = []
        for x in self._decisions(folder)["items"]:
            pk = by_id.get(x.get("id"))
            b = x.get("batch") if isinstance(x.get("batch"), dict) else {}
            if pk is not None and x.get("state") == "adopted" and x.get("origin") == "auto" and b.get("kind") in ("live", "end"):
                done.append((pk["start"], pk["end"] - (b["cut"] if schemas.is_num(b.get("cut")) else 0.0)))
        for x in st["queue"]:
            if x["id"] in by_id:
                sp = LB.shrink(by_id[x["id"]], x["batch"]["kind"])[0]
                done.append((sp["start"], sp["end"]))
        rows = []
        for pk in picks:
            sp = LB.shrink(pk, kind)[0]
            rows.append((pk, (sp["start"], sp["end"])))
        lim = LB.trim_lim(LB.total(st.get("length")))   # 合計を増やした分だけ広げる(live_batch.SCALE_ON)
        kept, dropped, mins = LB.trim(done, rows, lim)
        if dropped:
            st["trim"] = {"dropped": dropped, "checkMin": mins, "limMin": round(lim, 2)}
            self.host.log("盛り上がりの検出: 録画 %s は確かめる時間の見込みが %g 分を超えるので、配信の終わりの分を %d 本減らしました(残した後 %s 分)"
                          % (rec, round(lim, 2), dropped, mins))
        return [(pk, {"trim": dropped} if dropped else {}) for pk, _sp in kept]

    def _batch_total(self, rc, rec, r, st):
        """配信の終わりの合計(live_batch.total)。配信の長さ = 録画の長さ(lastPdt − firstPdt)+ 遅れて始まった頭(配信の開始時刻 → 録画の頭)。
        録画の長さが分からなければ BATCH_LIVE + BATCH_END。長さは batch.json の length に残す(12 分の上限も同じ値)"""
        r = r or {}
        a, b = r.get("firstPdt"), r.get("lastPdt")
        head = self._head_sec(rc, rec, a) if schemas.is_num(a) else 0.0
        length = (b - a) + head if schemas.is_num(a) and schemas.is_num(b) and b > a else None
        st["length"] = round(length, 1) if length is not None else None
        st["headSec"] = round(head, 1)
        return LB.total(length)

    def _fill_reserve(self, rc, rec, r, st, n_all, live_done):
        """配信の終わりに分かる録れなかった所(遅れて始まった頭 + 録画の欠け)の本数(live_batch.fill_count)を数え、配信の終わりの分から空ける数 -> 空ける数。
        batch.json の fill に残す(空けられない分 = n − reserved は配信の後に枠の外で届く)"""
        if not LB.FILL_ON:
            return 0
        r = r or {}
        a, b = r.get("firstPdt"), r.get("lastPdt")
        gaps = LX.rec_gaps(self.host.exporter._query, rc, rec, a, b) if schemas.is_num(a) and schemas.is_num(b) else None
        length, head = st.get("length"), st.get("headSec") or 0.0
        cover = min(head, float((st.get("head") or {}).get("cover") or 0.0))   # 別に取れた頭(10-30。live_head)は録れなかった所に入れない
        lost = head - cover + sum(y - x for x, y in merge_spans(gaps or []))
        n = LB.fill_count(n_all, lost, length)
        reserved = min(n, max(0, n_all - live_done))
        st["fill"] = {"n": n, "reserved": reserved, "f": round(lost / length, 4) if length else None, "lostSec": round(lost, 1),
                      "headSec": round(head, 1), "headCover": round(cover, 1), "length": length, "gapsKnown": gaps is not None}
        if n:
            self.host.log("盛り上がりの検出: 録画 %s は録れなかった所が %d 秒あるので、配信の終わりの分を %d 本空けて、アーカイブから %d 本埋めます"
                          % (rec, int(lost), reserved, n))
        return reserved

    def _head_sec(self, rc, rec, first):
        """遅れて始まった頭の秒(配信の開始時刻 streamStart → 録画の頭 first。録画元の /live/list から。分からなければ 0)"""
        rcd = self.host.find(rc)
        rows = LX.rec_list(self.host.call, rcd) if rcd is not None else None
        row = next((x for x in rows or [] if x.get("id") == rec), None)
        ss = LX.iso_epoch((row or {}).get("streamStart"))
        return max(0.0, first - ss) if ss is not None and schemas.is_num(first) else 0.0

    def _batch_waiting(self, rc, rec, doc, peaks):
        """区切りごとにまとめて届ける録画の adopt_waiting: 次の区切りで選ぶ候補の数と、次の区切りの時刻(録画の頭 + 区切りの秒 + ワーカーの遅れ)"""
        if doc is None or doc.get("ended"):
            return None
        st = LB.load(self.folder(rc, rec))
        seen = set(st["seen"])
        left = [p for p in peaks if LB.settled(p) and p["id"] not in seen and p.get("state") != "adopted"]
        if not left:
            return None
        first = LX.iso_epoch(doc.get("first"))
        due = first + LB.round_at(st["round"] + 1) + float(doc.get("behindSec") or 0.0) if first is not None else None
        return {"count": len(left), "dueAt": due, "batch": True}   # batch = 次の区切りで、この候補から選ぶ(全部は切り抜かない)

    # ---- 配信が終わったあと(0-10-6。L5 の材料。人の手は要らない)
    def compare(self, rc, rec, a, marks, holes=None):
        """配信後の全自動(M7。src/flow/live_archive.py。測るだけの録画も = EV-1)がアーカイブの解析の結果を読んだとき: アーカイブの候補(自動のマーク)のうち、
        配信中にも候補(見送り以外)が出ていた割合と時刻の差を live_feedback.jsonl に 1 行({"event": "detect_compare"})。配信中の候補が無い録画は何もしない。
        a: afterStream の記録(t0・offset・first・last)。アーカイブの秒 s → 録画の頭からの秒 = t0 + s − offset − first(pick_candidates と同じ向き)。
        EV-1: 配信中に測れなかった所(holes)にあるアーカイブの候補は「拾えなかった」に数えない(分母から外して excluded に数える):
          holes(呼ぶ側から。録画の頭からの秒 [(から, まで)]。None = 分からない)= 録画の欠け(つなぎ直しの間・止めていた間。録画元の /segments の gaps)
          + 検出が測っていない所(peaks.json の first より前・measuredSec より後・遅れて飛ばした skipped。飛ばした所は測り直しても候補は作り直さない)。
          候補の区間の半分以上が穴か、山(peak・無ければまん中)が穴の中なら外す。-> 書いた行か None"""
        doc, peaks, _p = self.view(rc, rec)
        if doc is None or not all(isinstance(a.get(k), (int, float)) for k in ("t0", "offset", "first", "last")):
            return None
        def num(x):
            return isinstance(x, (int, float)) and not isinstance(x, bool)

        def rel(s):   # アーカイブの秒 → 録画の頭からの秒
            return a["t0"] + s - a["offset"] - a["first"]

        def center(p):   # 配信中の候補の山の秒(無ければ区間のまん中)
            return p["peak"] if num(p.get("peak")) else (p["start"] + p["end"]) / 2.0

        span = a["last"] - a["first"]
        gaps = sorted((float(x), float(y)) for x, y in holes or [] if num(x) and num(y) and y > x)
        not_measured = measured_holes(doc, a["first"], span)
        hs = merge_spans(gaps + not_measured)

        def in_hole(s0, s1, at):
            cut = sum(max(0.0, min(s1, y) - max(s0, x)) for x, y in hs)
            return cut >= (s1 - s0) * 0.5 or any(x <= at < y for x, y in hs)

        live = [p for p in peaks if p.get("state") != "dismissed" and num(p.get("start")) and num(p.get("end"))]
        arch, excluded = [], 0   # [(開始, 終わり, 山)](録画の頭からの秒)
        for m in marks or []:
            if not isinstance(m, dict) or m.get("src") != "auto" or not num(m.get("start")) or not num(m.get("end")):
                continue
            s0, s1 = rel(m["start"]), rel(m["end"])
            if s1 > 0 and s0 < span:
                at = rel(m["peak"]) if num(m.get("peak")) else (s0 + s1) / 2.0
                if in_hole(s0, s1, at):
                    excluded += 1
                    continue
                arch.append((s0, s1, at))
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
               "liveUnmatched": unmatched, "liveAudioOnly": sum(1 for p in live if p.get("audioOnly")),   # 音だけで下げたしきい値で出た候補(数えるときに分けられる)
               "lag": doc.get("lag"), "chat": doc.get("chat"), "gaps": doc.get("gaps"), "offset": a.get("offset"),
               "excluded": excluded, "holesSec": round(sum(y - x for x, y in hs), 1), "holes": [[round(x, 1), round(y, 1)] for x, y in hs[:50]],
               "gapsKnown": holes is not None, "mode": a.get("mode") or "after"}
        fill = self._fill_after(rc, rec, a, hs, span)
        if fill is not None:
            row["fill"] = fill
        self.host.exporter.feedback(row)
        return row

    def _fill_after(self, rc, rec, a, hs, span):
        """配信の後の録れなかった所の分(live_batch.FILL_ON・区切りの形の録画だけ): 録画の欠け + 検出の穴(hs。録画の頭からの秒)で数え直し、
        配信の終わりに数えた本数(batch.json の fill.n)と多い方 -> {n, f, nEnd, reserved, lostSec, headSec, fAll, length, holes} か None。
        遅れて始まった頭(配信の開始 t0 − offset 〜 録画の頭)も録れなかった秒と穴([−頭の秒, 0])に入れる"""
        if not LB.FILL_ON or not LB.on(self.host.requests.get(rc, rec)):
            return None
        st = LB.load(self.folder(rc, rec))
        head = max(0.0, a["first"] - (a["t0"] - a["offset"]))
        length = span + head
        cover = float((st.get("fill") or {}).get("headCover") or 0.0)   # 配信の終わりまでに別に取れて使った頭(10-30。live_head)は穴にしない
        if head - cover > 1.0:
            hs = [(-head, -cover)] + list(hs)
        lost = sum(y - x for x, y in hs)
        end = st.get("fill") or {}
        n_end = end.get("n") if isinstance(end.get("n"), int) else 0
        n = max(n_end, LB.fill_count(LB.total(length), lost, length))
        return {"n": n, "f": round(lost / length, 4) if length > 0 else None, "nEnd": n_end, "reserved": end.get("reserved") or 0,
                "lostSec": round(lost, 1), "headSec": round(head, 1),
                "length": round(length, 1), "holes": [[round(x, 1), round(y, 1)] for x, y in hs[:50]]}

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
                         "auto": auto_n, "autoCapped": auto_n >= self.auto_max(x["recorder"], x["id"])})   # D-13: 自動で採用した数と上限に達したか
        chat = next((c for c in CHAT_ORDER if c in chats), "off")
        return {"running": self.running(hb), "pid": hb.get("pid"), "behindSec": hb.get("behindSec"), "memMB": hb.get("memMB"),
                "restarts": self.restarts, "chat": chat, "chatRestarts": hb.get("chatRestarts") or 0, "recordings": recs,
                "message": hb.get("message") or ("ワーカーを起動しています" if self.proc is not None else "ワーカーは動いていません"),
                "error": hb.get("error") or "",
                "autoAdopt": dict(self.adopt_cfg(), maxPerRecording=AUTO_MAX_PER_REC)}

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
