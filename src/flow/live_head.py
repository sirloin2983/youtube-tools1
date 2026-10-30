# -*- coding: utf-8 -*-
"""遅れて始まったライブの頭を yt-dlp --live-from-start で別に取り、音だけで検出して、頭の場面を自動の採用の候補に入れる(10-30。スイッチ HEAD_ON)。

なぜ: 録画の部品(src/pipeline/ingest/rec_core.py)は streamlink で今の端から録るので、依頼や起動が遅れると配信の頭が録れない
(録画 25 本のうち録れなかった割合が 1 割以上の 8 本はほとんど頭の遅れ)。研究の 297 番(保管庫 plan/研究の待ちの列の結果-1030.md):
yt-dlp --live-from-start は cookies なしで頭から取れた(音だけなら 60 秒で 69 分ぶん)。--download-sections は併用できないので、時間で止める。

対象: 録画中の録画のうち、自動の採用が動く物(友人の依頼の録画・ホームの検出がオンの録画)で、録画の頭 − 配信の開始時刻(録画元の streamStart =
release_timestamp)が HEAD_MIN_SEC 以上・HEAD_MAX_SEC 以下の YouTube の配信。1 録画 1 回(head.json があれば取り直さない)・同じ配信は 1 回。

流れ(録画 1 本に 1 つのスレッド。今の録画・検出には触らない = 失敗しても head.json の state error と理由が残るだけ):
  1. 空き容量: 書き出しの作業の置き場(live/work)の空き − 見込み(秒 × EST_MBPS × 3)が live_export.DISK_LOW を切るなら取らない(skipped。
     頭は今までどおり配信の後にアーカイブから埋める = live_archive._after_fill)
  2. 取得: yt-dlp を映像(VIDEO_FMT)と音(AUDIO_FMT)で 1 つずつ(--live-from-start・--ignore-config・--no-cookies・--no-cookies-from-browser。
     cookies の環境変数も子に渡さない)。窓なし・優先度「低」・KillJob(入口が落ちても残らない)。POLL_SEC ごとに取れた長さを見積もり(続いた断片の数 × 最初の断片の長さ)、
     配信の開始からの見込みの頭(遅れ + SLACK_SEC)+ OVERLAP_SEC に届いた方から PID の木ごと止める(tools.kill_tree。名前では止めない)。GRAB_TIMEOUT で必ず止める
  3. つなぐ: 形式ごとに続いた断片をつなぎ(最後の書きかけかもしれない 1 つは捨てる)、映像と音を ffmpeg -c copy で head.mp4 に(-shortest)
  4. 時刻合わせ: 録画の最初の REF_SEC 秒の音(録画元から)を head.mp4 の後ろの窓と照合(live_archive の run_align・しきい値も同じ)→
     録画の頭が head.mp4 の何秒か(cover)。合わなければ error(頭は使わない)
  5. 検出: head.mp4 の音の 1 秒の RMS(ワーカーと同じ levels)→ excite.Online(チャットなし)→ excite.PeakBook(しきい値 × AUDIO_ONLY_SCALE = 音だけの録画と同じ)。
     山が録画の頭より前の候補だけ、録画の頭からの秒(負)にして head.json の peaks へ(id "h<番号>-<山の秒>"・印 source "head"・audioOnly)
  6. 使い道: live_detect が候補に混ぜて今の選び方(区切り live_batch・waitMin の自動の採用)で選び、採用は live_adopt の _adopt_before(hold "head")が
     マークの正本とジョブだけを作り、live_export が head.mp4 から切る(source)。取れた秒(cover)は録れなかった所(live_detect._fill_reserve・_fill_after)から外す

記録: <検出の録画のフォルダ>/head.json {state: grab|align|detect|done|error|skipped, reason, vid, delaySec, coverSec, startAt, endAt, path, grabSec, sec,
      minutes, peaks, at} と archive.json の head(同じ要約・peaks なし)。head.mp4 は録画が終わって KEEP_AFTER 秒たち、頭から書き出すジョブが
      動いていなければ消す(入口の作業データの live/work/head-<録画>/)。
"""
import glob
import json
import os
import re
import shutil
import subprocess
import threading
import time

from pipeline.analyze import live_excite_worker as EW
from ytt import fsio, schemas, tools
from . import live_export as LX

HEAD_ON = True               # スイッチ: False = 頭を取らない(前の形 = 頭は配信の後にアーカイブから埋めるだけ)
HEAD_MIN_SEC = 60.0          # 録画の頭 − 配信の開始時刻 がこれ以上のときだけ
HEAD_MAX_SEC = 4 * 3600.0    # これより長い頭は取らない(取る時間と容量。研究: 12 時間を超えると取れない)
SLACK_SEC = 240.0            # 配信の開始時刻(release_timestamp)と本当の 0 秒のずれの見込み(−220 秒の例があった)
OVERLAP_SEC = 90.0           # 録画の頭のあとも取る秒(照合の重ね)
REF_SEC = 60.0               # 照合に使う録画の頭の音の秒
POLL_SEC = 10.0              # 取れた長さを測る間隔
GRAB_TIMEOUT = 40 * 60.0     # 取得の上限(秒)
EST_MBPS = 6.0               # 空き容量の見込みに使う映像 + 音の速さ(Mbps。1080p)
KEEP_AFTER = 2 * 3600.0      # 録画が終わってから head.mp4 を残す秒(頭から書き出すジョブが動いていれば残す)
VIDEO_FMT = "bv*[height<=1080][vcodec^=avc1]/bv*[height<=1080]/bv*"
AUDIO_FMT = "ba[ext=m4a]/ba"
STATE_FILE = "head.json"
WORK_PREFIX = "head-"
COOKIE_ENVS = (tools.COOKIES_ENV,)   # 子に渡さない環境変数(cookies は使わない・読まない)
STATES_END = ("done", "error", "skipped")
FRAG_RE = re.compile(r"-Frag(\d+)\Z")


def grab_cmd(yd, url, fmt, out):
    """yt-dlp の頭からの取得のコマンド(cookies を使わない。URL は -- の後)"""
    return [yd, "--ignore-config", "--no-cookies", "--no-cookies-from-browser", "--live-from-start", "--no-part", "--newline",
            "--no-playlist", "-N", "4", "-f", fmt, "-o", out + ".%(ext)s", "--", url]


def child_env(env=None):
    """子に渡す環境変数(cookies の指定を外す)"""
    env = dict(os.environ if env is None else env)
    for k in COOKIE_ENVS:
        env.pop(k, None)
    return env


def main_file(prefix):
    """yt-dlp が順につないでいる本体(<prefix>.<拡張子>。中身があるときだけ)か None。
    本物の yt-dlp(2026 年の版・--live-from-start)は止めるまで本体を 0 バイトのまま断片 <本体>-Frag<n> を残す(10-30 に本物で確かめた)"""
    mains = [p for p in glob.glob(glob.escape(prefix) + ".*") if not FRAG_RE.search(p) and not p.endswith((".part", ".ytdl", ".join", ".log", ".json"))]
    mains = [p for p in mains if os.path.getsize(p) > 0]
    return max(mains, key=os.path.getsize) if mains else None


def frags(prefix):
    """番号の続いた断片の一覧(いちばん小さい番号から、抜けの手前まで)"""
    got = {}
    for p in glob.glob(glob.escape(prefix) + "*-Frag*"):
        m = FRAG_RE.search(p)
        if m:
            got[int(m.group(1))] = p
    out = []
    n = min(got) if got else 0
    while n in got:
        out.append(got[n])
        n += 1
    return out


def joined(prefix):
    """取れた物のファイル: 本体(main_file)があればそれ。無ければ番号の続いた断片をつないだ <prefix>.join(止めたあとに 1 回だけ)"""
    m = main_file(prefix)
    if m:
        return m
    fs = frags(prefix)[:-1] or frags(prefix)   # 止めた時の最後の断片は書きかけかもしれない
    if not fs:
        return None
    out = prefix + ".join"
    with open(out, "wb") as w:
        for f in fs:
            with open(f, "rb") as r:
                shutil.copyfileobj(r, w)
    return out


def head_peaks(full, band, spec, det, upto):
    """頭の音(1 秒ずつの全帯域・2kHz 超の dB)-> 山が upto 秒(頭のファイルの秒 = 録画の頭)より前の候補の一覧(頭のファイルの秒)。
    計算はワーカーの音だけの録画と同じ(excite.Online(チャットなし)→ excite.PeakBook・しきい値 × AUDIO_ONLY_SCALE)"""
    ex = EW.excite
    spec = dict(EW.SPEC_DEFAULT, **(spec or {}))
    det = EW.clean_detect(det)
    on = ex.Online(use_chat=False, back=ex.ONLINE_BACK, fwd=ex.ONLINE_FWD, window=ex.ONLINE_WINDOW, lag=spec["lag"],
                   w_audio=spec["wAudio"], w_chat=spec["wChat"], head=spec["headSec"])
    book = ex.PeakBook(spec["length"], spec["preRatio"], det["sens"], det["perHour"], shape=EW.shape_of(spec), fallback=EW.fallback_of(),
                       join=ex.JOIN_ON, rerank=False)
    book.thr = book.thr * EW.AUDIO_ONLY_SCALE
    book.tag = {"audioOnly": True}
    level = {}
    for t in range(min(len(full), len(band))):
        level[t] = full[t]
        for s, total, parts in on.push(full[t], band[t]):
            book.push(s, total, {"audio": parts["audio"], "chat": 0.0}, level.pop(s, -90.0))
    book.finish()
    out = []
    for pid in book.order:
        pk = book.peaks.get(pid)
        if pk and pk.get("state") == "frame" and schemas.is_num(pk.get("peak")) and pk["peak"] < upto:
            out.append(pk)
    return out


class HeadGrabber:
    """録画ごとの頭の取得(上の流れ)。親 = ライブ係(flow/livesession.LiveSession)。tick は見回りから・stop は入口の終了から"""

    def __init__(self, host, clock=time.time, launcher=None, probe=None, poll=POLL_SEC):
        self.host = host
        self.clock = clock
        self.spawn = launcher is not None or None   # None = 親の spawn_ok に従う(テストのライブ係は子プロセスを起こさない)
        self.launcher = launcher or self._popen
        self.probe = probe or self._duration
        self.poll = poll
        self.lock = threading.Lock()
        self.threads = {}     # (録画元, 録画) -> スレッド
        self.procs = {}       # (録画元, 録画) -> [Popen](止めるときに木ごと)
        self.vids = set()     # この入口で取った・取っている配信(同じ配信を 2 つの録画元で録っていても 1 回)
        self._halt = threading.Event()
        self._job = None

    # ---- 置き場所と記録
    def folder(self, rc, rec):
        return self.host.detector.folder(rc, rec)

    def work(self, rec):
        return os.path.join(self.host.exporter.work, WORK_PREFIX + rec)

    def load(self, rc, rec):
        return fsio.read_json_or(os.path.join(self.folder(rc, rec), STATE_FILE), None, 4 * 1024 * 1024, kind=dict)

    def _save(self, rc, rec, doc):
        doc = dict(doc, v=1, at=LX.now_iso())
        folder = self.folder(rc, rec)
        os.makedirs(folder, exist_ok=True)
        fsio.atomic_write(os.path.join(folder, STATE_FILE), json.dumps(doc, ensure_ascii=False).encode("utf-8"))
        if doc.get("state") in STATES_END:   # 記録(archive.json の head。候補の一覧は入れない)
            try:
                self.host.archiver._info_put(rc, rec, head={k: v for k, v in doc.items() if k not in ("peaks", "path")})
            except Exception as e:   # noqa: BLE001  (記録を書けなくても頭は使える)
                self.host.note("頭の取得: archive.json に書けませんでした: %r" % (e,))
        return doc

    # ---- 使う側(live_detect・live_export)
    def source(self, rc, rec):
        """頭の動画 {path, start, end}(絶対時刻の epoch)か None(取れていない・消した)"""
        d = self.load(rc, rec) or {}
        p = d.get("path")
        if d.get("state") != "done" or not isinstance(p, str) or not os.path.isfile(p):
            return None
        s, e = LX.iso_epoch(d.get("startAt")), LX.iso_epoch(d.get("endAt"))
        return {"path": p, "start": s, "end": e} if s is not None and e is not None else None

    def peaks(self, rc, rec):
        """頭の候補(録画の頭からの秒・負)。取れていなければ []"""
        if not HEAD_ON:
            return []
        d = self.load(rc, rec) or {}
        if d.get("state") != "done":
            return []
        return [dict(p) for p in d.get("peaks") or [] if isinstance(p, dict) and isinstance(p.get("id"), str)]

    def cover(self, rc, rec):
        """取れて使える頭の秒(録画の頭より前。録れなかった所から外す)。取れていなければ 0"""
        d = self.load(rc, rec) or {}
        return float(d["coverSec"]) if d.get("state") == "done" and schemas.is_num(d.get("coverSec")) else 0.0

    # ---- 見回り
    def tick(self, now=None):
        """録画中の録画で、頭を取る物にスレッドを始める・終わった録画の頭の動画を片付ける -> 始めた数"""
        if not HEAD_ON or self._halt.is_set() or not (self.spawn or (self.spawn is None and getattr(self.host, "spawn_ok", True))):
            return 0
        now = self.clock() if now is None else now
        det = self.host.detector
        home = det.detect_cfg().get("enabled") is True
        started = 0
        for r in self.host.list_recordings():
            rc, rec = r["recorder"], r["id"]
            if not r.get("active"):
                self._clean(rc, rec, r, now)
                continue
            key = (rc, rec)
            if key in self.threads or not isinstance(r.get("firstPdt"), (int, float)):
                continue
            if self.host.requests.get(rc, rec) is None and not home:   # 自動の採用が動かない録画は取らない
                continue
            ss = r.get("streamStart")
            delay = r["firstPdt"] - ss if isinstance(ss, (int, float)) else None
            vid = LX.video_id_of(r.get("url"), rec) if r.get("url") else None
            if delay is None or not HEAD_MIN_SEC <= delay <= HEAD_MAX_SEC or not vid or vid in self.vids:
                continue
            if (self.load(rc, rec) or {}).get("state") is not None:   # 1 録画 1 回(入口を起き直したら、途中だった物は取り直さない)
                continue
            self.vids.add(vid)
            th = threading.Thread(target=self._run, args=(rc, rec, r, vid, delay), name="live-head-" + rec, daemon=True)
            self.threads[key] = th
            th.start()
            started += 1
        return started

    def _clean(self, rc, rec, r, now):
        """終わった録画の頭の動画を消す(KEEP_AFTER 秒たち、頭から書き出すジョブが動いていないとき)"""
        if (rc, rec) in self.threads:
            return
        wd = self.work(rec)
        if not os.path.isdir(wd):
            return
        ended = r.get("endedAt") or r.get("lastPdt")
        if not isinstance(ended, (int, float)) or now - ended < KEEP_AFTER:
            return
        if any(j.get("from") == "head" and j.get("state") in LX.ACTIVE for j in self.host.exporter.snapshot(rc, rec)):
            return
        shutil.rmtree(wd, ignore_errors=True)

    def stop(self):
        """入口の終了: 動いている取得を木ごと止める(途中の物は error のまま。次の起動で取り直さない)"""
        self._halt.set()
        with self.lock:
            procs = [p for ps in self.procs.values() for p in ps]
        for p in procs:
            tools.kill_tree(p, wait=5)

    # ---- 1 本
    def _run(self, rc, rec, r, vid, delay):
        key = (rc, rec)
        doc = {"state": "grab", "vid": vid, "delaySec": round(delay, 1), "reason": ""}
        wd = self.work(rec)
        t0 = self.clock()
        try:
            self._save(rc, rec, doc)
            target = delay + SLACK_SEC + OVERLAP_SEC
            need = target * EST_MBPS * 1e6 / 8 * 3   # 断片 + つないだ物 + 1 本にした物
            free = self._free(self.host.exporter.work)
            if free is not None and free - need < LX.DISK_LOW:
                self._save(rc, rec, dict(doc, state="skipped", reason="空きが足りないので頭を取りませんでした(空き %.1f GB・見込み %.1f GB)" % (free / LX.GB, need / LX.GB)))
                return
            shutil.rmtree(wd, ignore_errors=True)
            os.makedirs(wd, exist_ok=True)
            got = self._grab(key, r["url"], wd, target)
            doc["grabSec"] = round(self.clock() - t0, 1)
            if isinstance(got, str):
                raise HeadError(got)
            doc.update(state="align")
            self._save(rc, rec, doc)
            path = os.path.join(wd, "head.mp4")
            self._mux(got, path)
            dur = self.probe(path)
            if not dur or dur < OVERLAP_SEC:
                raise HeadError("頭の動画をつなげませんでした")
            cover, first = self._align(rc, rec, path, dur, delay, wd)
            doc.update(state="detect", coverSec=round(cover, 2), startAt=LX.epoch_iso(first - cover), endAt=LX.epoch_iso(first - cover + dur),
                       path=path, minutes=round(cover / 60.0, 1))
            self._save(rc, rec, doc)
            pks = self._detect(rc, rec, path, cover, wd)
            self._save(rc, rec, dict(doc, state="done", peaks=pks, sec=round(self.clock() - t0, 1)))
            self.host.log("頭の取得: 録画 %s の頭 %.1f 分を取り、候補 %d 本を見つけました(%.0f 秒)" % (rec, cover / 60.0, len(pks), self.clock() - t0))
        except HeadError as e:
            shutil.rmtree(wd, ignore_errors=True)
            self._save(rc, rec, dict(doc, state="error", reason=str(e), sec=round(self.clock() - t0, 1)))
            self.host.log("頭の取得: 録画 %s の頭は使いません(%s)" % (rec, e))
        except Exception as e:   # noqa: BLE001  (思わぬ不具合でも、今の録画と検出には何も起きない)
            shutil.rmtree(wd, ignore_errors=True)
            try:
                self._save(rc, rec, dict(doc, state="error", reason="内部エラー: %s" % e.__class__.__name__, sec=round(self.clock() - t0, 1)))
            except Exception:   # noqa: BLE001
                pass
            self.host.log("頭の取得: 録画 %s でエラー %r" % (rec, e))
        finally:
            with self.lock:
                for p in self.procs.pop(key, []):
                    tools.kill_tree(p, wait=5)
            self.threads.pop(key, None)

    def _free(self, path):
        try:
            os.makedirs(path, exist_ok=True)
            return (getattr(self.host, "disk_usage", None) or fsio.disk_space)(path)[0]
        except Exception:   # noqa: BLE001  (測れなければ見ない)
            return None

    def _popen(self, cmd, log_path):
        if self._job is None:
            self._job = tools.KillJob()
        with open(log_path, "ab") as log:
            p = subprocess.Popen(cmd, stdin=subprocess.DEVNULL, stdout=log, stderr=subprocess.STDOUT, env=child_env(),
                                 creationflags=tools.no_window_flags(new_group=True, priority="low"), start_new_session=os.name != "nt")
        self._job.add(p)
        return p

    def _grab(self, key, url, wd, target):
        """映像と音を頭から target 秒まで取る -> {"v": ファイル, "a": ファイル} か失敗の理由(文)"""
        yd = self.host.detector.ytdlp()
        if not yd:
            return "yt-dlp が見つかりません"
        parts = {}
        for k, fmt in (("v", VIDEO_FMT), ("a", AUDIO_FMT)):
            prefix = os.path.join(wd, k)
            p = self.launcher(grab_cmd(yd, url, fmt, prefix), prefix + ".log")
            parts[k] = {"prefix": prefix, "proc": p, "dur": 0.0, "done": False}
            with self.lock:
                self.procs.setdefault(key, []).append(p)
        end = self.clock() + GRAB_TIMEOUT
        while not all(x["done"] for x in parts.values()):
            if self._halt.is_set():
                return "入口を終えたので止めました"
            for x in parts.values():
                if x["done"]:
                    continue
                x["dur"] = self._est(x)
                if x["dur"] >= target or x["proc"].poll() is not None or self.clock() >= end:
                    tools.kill_tree(x["proc"], wait=5)
                    x["done"] = True
            if not all(x["done"] for x in parts.values()):
                self._halt.wait(self.poll)
        files = {k: joined(x["prefix"]) for k, x in parts.items()}
        short = min((self.probe(f) or 0.0) if f else 0.0 for f in files.values())
        if not all(files.values()) or short < OVERLAP_SEC:
            tail = self._tail(parts["a"]["prefix"] + ".log") or self._tail(parts["v"]["prefix"] + ".log")
            return "頭を取れませんでした" + ("(%s)" % tail if tail else "")
        return files

    def _est(self, x):
        """取れた長さの見積もり(秒): 本体があれば ffprobe、無ければ続いた断片の数 × 最初の断片の長さ(断片を測るたびにつながない)"""
        m = main_file(x["prefix"])
        if m:
            return self.probe(m) or 0.0
        fs = frags(x["prefix"])
        if len(fs) < 2:
            return 0.0
        if not x.get("fragSec"):
            x["fragSec"] = self.probe(fs[0])
        return (len(fs) - 1) * (x.get("fragSec") or 0.0)

    @staticmethod
    def _tail(path):
        try:
            with open(path, "rb") as f:
                lines = [x.strip() for x in f.read()[-4000:].decode("utf-8", "replace").splitlines() if x.strip()]
        except OSError:
            return ""
        errs = [x for x in lines if "ERROR" in x] or lines
        return errs[-1][:200] if errs else ""

    def _ff(self):
        ff = self.host.detector.ffmpeg()
        if not ff:
            raise HeadError("ffmpeg が見つかりません")
        return ff

    def _duration(self, path):
        """ffprobe で長さ(秒)か None"""
        fp = tools.find_tool("ffprobe")
        if not fp or not path:
            return None
        try:
            d = tools.ffprobe_json(fp, ["-show_entries", "format=duration", path], timeout=60)
            v = float((d.get("format") or {}).get("duration"))
            return v if v == v and v > 0 else None
        except Exception:   # noqa: BLE001
            return None

    def _mux(self, files, out):
        """映像と音を 1 本の mp4 に(写すだけ)"""
        cmd = [self._ff(), "-nostdin", "-y", "-v", "error", "-i", files["v"], "-i", files["a"], "-map", "0:v:0", "-map", "1:a:0", "-c", "copy",
               "-shortest", out]
        r = tools.run(cmd, timeout=1800, flags=tools.no_window_flags(priority="low"), err_tail=5)
        if r.code != 0 or not os.path.isfile(out):
            raise HeadError("頭の映像と音をつなげませんでした(%s)" % " / ".join(r.err_lines(2)))
        for f in glob.glob(os.path.join(os.path.dirname(out), "[va].*")):   # つないだら元は消す(容量)
            if not f.endswith(".log"):
                fsio.unlink_quiet(f)

    def _align(self, rc, rec, path, dur, delay, wd):
        """録画の最初の REF_SEC 秒の音を head.mp4 の後ろの窓と照合 -> (録画の頭が head.mp4 の何秒か, 録画の頭の絶対時刻)"""
        from . import live_archive as LA   # 照合のしきい値は 1 か所
        ex, ar = self.host.exporter, self.host.archiver
        rco = self.host.find(rc)
        st = self.host.recording_state(rc, rec)
        if rco is None or st is None:
            raise HeadError("録画元につながらないので、頭の時刻を合わせられません")
        rows = [x for x in self.host.list_recordings() if x["recorder"] == rc and x["id"] == rec]
        first = rows[0]["firstPdt"] if rows else None
        if not isinstance(first, (int, float)):
            raise HeadError("録画の頭の時刻が分かりません")
        code, d = ex._query(rc, rec, first, first + REF_SEC)
        segs = [x for x in (d or {}).get("segments") or [] if LX.SEG_URI_RE.match(str(x.get("uri") or ""))] if code == 200 else []
        if not segs:
            raise HeadError("録画の頭の音を取れないので、頭の時刻を合わせられません")
        segs = [x for x in segs if x.get("session") == segs[0].get("session")]
        job = {"id": "head-" + rec}
        files = ex._fetch(job, rco, rec, segs, os.path.join(wd, "ref"))
        s0 = LX.iso_epoch(segs[0].get("pdt"))
        have = sum(float(x.get("dur") or 0) for x in segs)
        ref = ar._wav(files[0][0], os.path.join(wd, "ref.wav"), 0.0, min(REF_SEC, have))
        w0 = max(0.0, dur - (SLACK_SEC * 2 + OVERLAP_SEC + REF_SEC))
        win = ar._wav(path, os.path.join(wd, "win.wav"), w0, dur - w0)
        res = ar.align(ref, win) or {}
        shutil.rmtree(os.path.join(wd, "ref"), ignore_errors=True)
        for f in (ref, win):
            fsio.unlink_quiet(f)
        if not (res.get("ok") and (res.get("score") or 0) >= LA.MIN_SCORE and (res.get("ratio") or 0) >= LA.MIN_RATIO):
            raise HeadError("頭の音と録画の音が合いませんでした(%s)" % (res.get("reason") if not res.get("ok") else
                                                                "確かさ %.2f・%.1f 倍" % (res.get("score") or 0, res.get("ratio") or 0)))
        cover = w0 + float(res["offset"])
        if not 0 < cover <= dur - 5.0:
            raise HeadError("頭の動画が録画の頭まで届いていませんでした")
        return cover, s0 if s0 is not None else first

    def _detect(self, rc, rec, path, cover, wd):
        """head.mp4 の音を測って候補を出す -> 候補の一覧(録画の頭からの秒・負)"""
        spec, det = self._spec(rc, rec)
        mdir = os.path.join(wd, "levels")
        os.makedirs(mdir, exist_ok=True)
        try:
            full, band = EW.measure_levels(self._ff(), path, mdir, timeout=1800)
        except Exception as e:   # noqa: BLE001
            raise HeadError("頭の音を測れませんでした: %s" % e)
        finally:
            shutil.rmtree(mdir, ignore_errors=True)
        out = []
        for n, pk in enumerate(head_peaks(full, band, spec, det, cover)):
            s, e = float(pk["start"]) - cover, float(pk["end"]) - cover
            out.append({"id": "h%d-%d" % (n, int(pk["peak"])), "start": round(s, 2), "end": round(e, 2), "peak": round(float(pk["peak"]) - cover, 2),
                        "score": pk.get("score"), "parts": pk.get("parts"), "reasons": pk.get("reasons") or [], "confirmedAt": 0.0, "hour": 0,
                        "state": "frame", "endPending": False, "origin": None, "seq": 0, "source": "head", "audioOnly": True,
                        **({"pieces": pk["pieces"]} if pk.get("pieces") else {})})
        return out

    def _spec(self, rc, rec):
        """その録画のワーカーの解析の設定(state.json の spec)と感度・枠(友人の依頼 > ホームの設定)"""
        det = self.host.detector
        st = fsio.read_json_or(os.path.join(self.folder(rc, rec), "state.json"), None, 64 * 1024 * 1024, kind=dict) or {}
        spec = st.get("spec") if isinstance(st.get("spec"), dict) else det.spec()
        req = det.requests_cfg().get("%s/%s" % (rc, rec))
        return spec, req if req else det.detect_cfg()


class HeadError(Exception):
    pass
