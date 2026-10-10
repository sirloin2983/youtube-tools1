# -*- coding: utf-8 -*-
"""② 管理の層 flow: ライブ係(役割で組み直す RS7-2 G2b。docs/design/rs7-survey-2026-10-10/plan_order_v3.md の 1 節 5・plan/f1-friend-pc.md)。

もとは入口の src/home/live.py の Live の中の app でない部分。録画元のクライアント(一覧・要求・状態)・録画を始める(begin・友人の依頼の begin_request)・
見回りの列(tick)・子プロセス(録画の部品の起動と後始末・検出のワーカー)・「調子」・採用の口(adopt)をここに置き、4 つの子(Detector・LiveTx・Reporter・
Exporter)と Archiver・Adopter の親になる(flow/livehost.py の LiveHost を満たす)。入口の Live は LiveSession を継いで、HTTP の受け口・中継・札・
スタジオ(studio_call・StudioMarks)・友人へ届ける・D-13・ホームの設定(prefs)だけを足す(app の殻)。画面なし(--headless)も同じ Live を使い、
use_headless でスタジオなしの採用(LocalMarks)・届けない・D-13 なし・上限は束の adopt.top・空き容量の下限にする。

受付 = submit(封筒, 束)(② の口 Queue.submit が kind live を回す = 入口が Queue.set_live_hook で登録する):
  封筒 kind live(flow/envelope.py)を受けて録画を始め、録画ごとに封筒 + 束を live/bundles.json に残す(BundleBook)。
  友人の依頼(封筒の requestId・入口の intake から ctx つき)と画面なしの依頼は requests.json の結びつき(human/friend/live_requests.Store)も今までどおり作る
  (= 依頼の録画の検出・自動の採用・after auto・配信後の追加は今の「友人の依頼の録画」の決まりのまま)。
  ユーザーの PC の自分の配信(スタジオの URL の欄 → 芯の begin)は今は束なし(plan_order_v3.md 6 節の時間の上限で切った。束を渡せば同じ芯で残る)。

live/bundles.json の形: {"<録画元>/<録画>": {"envelope": 封筒(検査済み。無い = 束だけ), "spec": 束(検査済み), "at": 受けた時刻(epoch 秒)}}
  一時ファイルから置き換える(fsio.atomic_write)。無い・読めない・形の違う行 = その録画は束なし(今までどおりの読み方)。BUNDLES_KEEP_DAYS で片付ける。
束から読む所(決定 3-31 の仮 b1・b2・b3 = 録画を始めたときの束に固定):
  検出(live_detect.Detector.config の bundles = 録画ごとの解析の設定・感度・枠)・自動の採用の待ち(Detector.adopt_for)・
  配信後の全自動の解析の設定(live_archive の settings_for)・書き出しの音量(live_export.Exporter._audio_cfg)・
  書き出したあとの設定(auto_cfg の cut・engine・model・pad。束の run.pinned にある物だけ)・まとめて実行へ渡す束(Exporter._handoff)。
  束の無い録画は今の読み方(スタジオの GET /api/settings・settings-ui.json・ホームの設定 live.auto)に落ちる。

import してよいのは標準ライブラリ・ytt・pipeline・同じ flow だけ(層の向き。友人の依頼の結びつき・片付け・案件は入口が hook で渡す)。
"""
import contextlib
import copy
import http.client
import json
import os
import subprocess
import sys
import threading
import time
import urllib.parse

from pipeline.ingest import rec_core   # 録画の状態の名前(ACTIVE)。録画の部品と同じ物
from ytt import datadir, fsio, layout, schemas, tools, version as _version
from . import envelope as _envelope
from . import live_adopt   # 採用 = マーク + 書き出し(M1。RS7-2 G1b)
from . import live_archive   # アーカイブで本番版に作り直す。P4
from . import live_detect   # 配信中の盛り上がりの検出と自動の採用。線 D の L2・M11
from . import live_export as LX   # マークと書き出し。P2
from . import live_failures   # 失敗の集約。M3・M7
from . import live_report   # 配信ごとの結果の記録。線 D の D-12
from . import live_tx   # 配信中の候補の文字起こし。線 D の D-11 案 b
from . import runlog, spec as _spec

DEFAULT_FOLDER = r"E:\Video\live-rec"     # src/pipeline/ingest/rec_core.py の DEFAULT_FOLDER と同じ(2026-10-04 ユーザー決定)
RECORDER_PORT = 8730                      # src/pipeline/ingest/recorder.py の DEFAULT_PORT と同じ
LOCAL = {"id": "local", "name": "この PC", "url": "http://127.0.0.1:%d" % RECORDER_PORT, "token": ""}
RELAY_TIMEOUT = 15.0
WATCH_SEC = 30.0
SPAWN_GAP = 30.0
QUALITIES = ("best", "1080p", "720p")     # src/pipeline/ingest/rec_core.py の QUALITIES と同じ名前(src/home/prefs.py の LIVE_QUALITIES)
DEFAULT_QUALITY = "1080p"
YT_HOSTS = ("youtube.com", "www.youtube.com", "m.youtube.com", "youtu.be")   # src/pipeline/ingest/rec_core.py の YT_HOSTS と同じ
URL_MAX = 500
LIVE_STATUSES = ("is_live", "is_upcoming", "was_live", "not_live", "post_live")   # yt-dlp の live_status
PROBE_TIMEOUT = 25.0     # yt-dlp で配信の状態を調べる時間切れ(秒)
CHANNEL_MAX = 100        # チャンネル名の長さ(スタジオの配信の channel と同じ)
STATUS_TIMEOUT = 1.5     # api/ytt/live の status: 録画元への問い合わせの時間切れ(全ツールのヘッダーが 10 秒ごとに呼ぶので短く)
STATUS_CACHE = 3.0       # 同じ結果を返す秒数
RECENT_SEC = 600         # 終わった録画を札に出す秒数(10 分)
STOP_TIMEOUT = 45.0      # 録画元の stop は録画のスレッドの終わりを 30 秒まで待つ
QUIT_TIMEOUT = 3.0       # 入口の終了: 録画の部品の quit の応答を待つ秒
QUIT_WAIT = 8.0          # quit を受けた録画の部品が終わるのを待つ秒(過ぎたら、この入口が起動したものだけ孫ごと止める)
KEPT_NOTE = "録画中なので録画の部品は残しました(録画は続きます。部品も終わらせるときは、スタジオで録画を止めてからもう一度「すべて終了」)"
OFF = {"enabled": False, "folder": "", "recorders": [], "quality": DEFAULT_QUALITY}   # 設定を読めないとき = オフ
BUNDLES_FILE = "bundles.json"   # 録画ごとの封筒 + 束(入口の作業データの live\)
BUNDLES_KEEP_DAYS = 7           # 束を残す日数(録画 12 時間 + 配信後の全自動 2 日 + 友人の依頼の結びつき 3 日に足りる)
BUNDLES_MAX = 200
BUNDLES_READ_MAX = 8 * 1024 * 1024
PAD_MAX = 5.0                   # 自動・アーカイブの採用の前後の余白の上限(秒。ホームの設定 live.auto.pad と同じ範囲)


def validate_url(url, allow_local=False):
    """スタジオの URL の欄から録画を始める URL(src/pipeline/ingest/rec_core.py の validate_url と同じ規則)。YouTube の https だけ。
    allow_local=True(テストの録画元 --source direct)は http(s)://127.0.0.1|localhost も。-> 整えた URL。だめなら LiveError"""
    if not isinstance(url, str):
        raise LX.LiveError("配信の URL を入れてください")
    url = url.strip()
    if not url or len(url) > URL_MAX or any(ord(c) < 33 for c in url):
        raise LX.LiveError("配信の URL が正しくありません")
    try:
        u = urllib.parse.urlsplit(url)
        port = u.port
    except ValueError:
        raise LX.LiveError("配信の URL が正しくありません")
    host = (u.hostname or "").lower()
    if allow_local and u.scheme in ("http", "https") and host in ("127.0.0.1", "localhost") and not u.username:
        return url
    if u.scheme != "https" or host not in YT_HOSTS or u.username or u.password or port not in (None, 443):
        raise LX.LiveError("YouTube の配信の URL(https://www.youtube.com/watch?v=… など)を入れてください")
    vid = LX.video_id_of(url)
    return "https://www.youtube.com/watch?v=" + vid if vid else url   # 動画の id が分かる形はそろえる(同じ配信を別の書き方で二重に録らない)


def _clean(s, n):
    """yt-dlp の出した値 → 画面へ返す文字(制御文字を落とす・NA は空・長さを切る)"""
    s = "".join(c for c in str(s or "") if ord(c) >= 32 and ord(c) != 127).strip()
    return "" if s == "NA" else s[:n].strip()


def probe_live(url, timeout=PROBE_TIMEOUT):
    """yt-dlp で配信の状態・チャンネル名・題を調べる(ダウンロードしない・シェルを通さない・窓を出さない)。
    -> {"status": LIVE_STATUSES のどれか か "unknown", "title": 題, "channel": チャンネル名(無ければ投稿者。分からなければ ""), "message": 調べられなかった理由}"""
    yd = tools.find_tool("yt-dlp")
    if not yd:
        return {"status": "unknown", "title": "", "channel": "", "message": "yt-dlp が見つからないので、配信中か調べられませんでした"}
    try:   # 題は最後(題にタブが入っても崩れない)。%(channel,uploader)s = チャンネル名が無ければ投稿者(yt-dlp の書式の「代わり」)
        r = tools.run(tools.ytdlp_print_cmd(yd, url, "%(live_status)s\t%(channel,uploader)s\t%(title)s"), timeout=timeout, err_tail=40)
    except OSError as e:
        return {"status": "unknown", "title": "", "channel": "", "message": "yt-dlp を起動できませんでした: %s" % (e.strerror or e.__class__.__name__)}
    if r.why == "timeout":
        return {"status": "unknown", "title": "", "channel": "", "message": "配信の状態を %d 秒で調べられませんでした" % int(timeout)}
    lines = r.out.decode("utf-8", "replace").strip().splitlines()
    parts = (lines[-1] if lines else "").split("\t", 2)
    st = parts[0].strip()
    channel = _clean(parts[1], CHANNEL_MAX) if len(parts) > 2 else ""
    title = _clean(parts[-1], LX.TITLE_MAX) if len(parts) > 1 else ""
    if st in LIVE_STATUSES:
        return {"status": st, "title": title, "channel": channel, "message": ""}
    err = r.err.decode("utf-8", "replace")
    if "will begin" in err or "Premieres in" in err:   # 古い yt-dlp は配信の前をエラーで返す
        return {"status": "is_upcoming", "title": title, "channel": channel, "message": ""}
    last = (err.strip().splitlines() or [""])[-1][:160]
    return {"status": "unknown", "title": "", "channel": "", "message": "配信の状態を調べられませんでした" + ("(%s)" % last if last else "")}


def rec_view(r, channel=None):
    """録画元の録画の要約 → 画面へ返す形。channel = begin で yt-dlp から取ったチャンネル名(begin だけが付ける。分からなければ "")"""
    out = {"id": r.get("id"), "url": r.get("url") or "", "title": r.get("title") or "", "state": r.get("state") or ""}
    if channel is not None:
        out["channel"] = channel
    return out


def _same_stream(a_url, b_url, b_id=""):
    """同じ配信か(URL が同じ・YouTube の動画の id が同じ)"""
    if a_url and a_url == b_url:
        return True
    v = LX.video_id_of(a_url)
    return bool(v) and v == LX.video_id_of(b_url or "", b_id or "")


def recorder_data_dir(root):
    """録画の部品の作業データ(token.txt)。src/pipeline/ingest/recorder.py の data_dir() と同じ規則"""
    return datadir.locate("recorder", legacy_dir=os.path.join(root, layout.RECORDER_DIR, "data"))


def _read_token(path):
    try:
        with open(path, "r", encoding="ascii") as f:
            return f.read().strip()[:200]
    except (OSError, UnicodeError):
        return ""


def is_local_url(url):
    try:
        return (urllib.parse.urlsplit(url).hostname or "") in ("127.0.0.1", "localhost")
    except ValueError:
        return False


# ---------- 束と封筒(RS7-2 G2b) ----------
def stream_url(env):
    """封筒 kind live(検査済み)-> 録画する配信の URL(url が無ければ動画の id から)"""
    inp = env["input"]
    return inp.get("url") or "https://www.youtube.com/watch?v=" + inp["videoId"]


def live_envelope(url, title="", request_id=None, deliver_dir=None, batch=None, streamer=None, note="", eid=None):
    """録画を始める依頼の封筒(kind live。検査済み)。YouTube の動画の URL でなければ ValueError(手元のテストの録画元など = 束なしで録る)。
    eid = 封筒の id(英数字と - _ の 64 字まで。合わない・無ければ新しく作る)"""
    eid = eid if isinstance(eid, str) and _envelope.ID_RE.match(eid) else "lv-" + os.urandom(6).hex()
    return _envelope.check({"id": eid, "kind": "live", "input": {"url": url, "title": str(title or "")[:_envelope.TITLE_MAX]},
                            "requestId": str(request_id)[:120] if request_id else None,
                            "deliver": {"dir": str(deliver_dir)[:_envelope.PATH_MAX] if deliver_dir else None,
                                        "batch": batch if _envelope.batch_ok(batch) else None},
                            "note": str(note or "")[:_envelope.NOTE_MAX], "legacy": {"streamer": str(streamer)[:_envelope.TITLE_MAX] if streamer else None}})


def cfg_bundle(base, cfg):
    """録画を始めるときの束(入口の友人の依頼の土台): base(画面の設定から組んだ束 = 入口の AutoRunner.build_spec)に、ライブの設定 cfg(ホームの設定 live)の
    検出の感度・枠(detect)・自動の採用の待ち(autoAdopt.waitMin)・余白(auto.pad)と、書き出したあとのエンジン・モデル・カット(auto。決めてあれば run.pinned に)を重ねる
    (決定 3-31 の仮 b1・b3)。合わない値は base のまま"""
    b = copy.deepcopy(_spec.validate(_spec.merge(base)))
    cfg = cfg if isinstance(cfg, dict) else {}
    det = cfg.get("detect") if isinstance(cfg.get("detect"), dict) else {}
    aa = cfg.get("autoAdopt") if isinstance(cfg.get("autoAdopt"), dict) else {}
    auto = cfg.get("auto") if isinstance(cfg.get("auto"), dict) else {}
    for key, v in (("sens", det.get("sens")), ("perHour", det.get("perHour")), ("waitMin", aa.get("waitMin")), ("pad", auto.get("pad"))):
        if v is not None and _spec.key_ok("adopt", key, v) and (key != "pad" or v <= PAD_MAX):
            b["adopt"][key] = v
    pins = list(b["run"]["pinned"])
    for sec, key, v in (("transcribe", "engine", auto.get("engine")), ("transcribe", "model", auto.get("model")), ("pack", "cut", auto.get("cut"))):
        if v and _spec.key_ok(sec, key, v) and (key != "cut" or v in _spec.CUTS):
            b[sec][key] = _spec.read_legacy_tx(key, v) if sec == "transcribe" else v   # 旧い名前は key_ok と同じく今の値に読む(0.58.0)
            pins.append(key)
    b["run"]["pinned"] = list(dict.fromkeys(pins))
    return _spec.validate(b)


def request_bundle(ctx, base=None, top=None):
    """友人のライブ配信の依頼の欄 ctx(human/friend/intake.py の _handle_live_request の形)-> 束: base に依頼の設定(感度・枠・待ち・余白・配信後の追加)・
    カット・映像トラック・話す人(run.pinned に)と、自動の採用の上限 top(友人の依頼の欄の既定 10 を呼ぶ側が明示する)を重ねる。
    長さ(settings.length)は束の analyze に入れない(検出は依頼の長さで測る = requests.json のまま。配信後の解析はスタジオの設定のまま)"""
    b = copy.deepcopy(_spec.validate(_spec.merge(base)))
    s = ctx.get("settings") if isinstance(ctx.get("settings"), dict) else {}
    for key in ("sens", "perHour", "waitMin", "pad", "afterStream"):
        if key in s and _spec.key_ok("adopt", key, s[key]):
            b["adopt"][key] = s[key]
    if top is not None and _spec.key_ok("adopt", "top", top):
        b["adopt"]["top"] = top
    pins = list(b["run"]["pinned"])
    if ctx.get("cut") in _spec.CUTS:
        b["pack"]["cut"] = ctx["cut"]
        pins.append("cut")
    if ctx.get("videoTracks") and _spec.key_ok("pack", "videoTracks", ctx["videoTracks"]):
        b["pack"]["videoTracks"] = ctx["videoTracks"]
        pins.append("videoTracks")
    sp = ctx.get("speakers") if isinstance(ctx.get("speakers"), dict) else None
    if sp and _spec.key_ok("transcribe", "diarize", sp.get("count")):
        b["transcribe"]["diarize"] = sp["count"]
        from . import run as _run   # 呼ぶときに読む(run は文字起こしの部品まで読む)
        people = _run._people_of(sp)   # 欄 → 束の写し方は flow/run.py の Run の欄と同じ
        if people:
            b["hints"]["people"] = people
    b["run"]["pinned"] = list(dict.fromkeys(pins))
    return _spec.validate(b)


def request_settings(bundle):
    """束 -> 友人の依頼の結びつきの設定 {sens, perHour, length, waitMin, pad, afterStream}(human/friend/live_requests.Store が範囲を検査する)"""
    a = bundle["adopt"]
    return {"sens": a["sens"], "perHour": a["perHour"], "length": int(round(bundle["analyze"]["length"])), "waitMin": a["waitMin"],
            "pad": float(a["pad"]), "afterStream": a["afterStream"]}


def speakers_of(bundle):
    """束の transcribe.diarize と hints.people -> 話す人 {"count", "names", "styles"} か None(flow/run.py の Run.from_envelope と同じ形)"""
    dz = bundle["transcribe"]["diarize"]
    if not dz:
        return None
    people = _spec.hint_people(bundle)["people"]
    return {"count": dz, "names": [p["name"] for p in people], "styles": {p["name"]: {"color": p["color"]} for p in people if p.get("color")}}


def bundle_ctx(env, bundle, url):
    """封筒 + 束 -> 友人の依頼の結びつきの欄(requests.json に残す形。画面なしの依頼・requestId のある封筒)"""
    pins, pk = bundle["run"]["pinned"], bundle["pack"]
    return {"rid": env["requestId"] or env["id"], "deliverDir": env["deliver"]["dir"] or "", "url": url, "title": env["input"]["title"] or "",
            "streamer": env["legacy"]["streamer"] or "", "speakers": speakers_of(bundle),
            "videoTracks": pk["videoTracks"] if "videoTracks" in pins else None,
            "cut": pk["cut"] if "cut" in pins and pk["cut"] in _spec.CUTS else None,
            "memo": env["note"], "settings": request_settings(bundle), "deliverBatch": env["deliver"]["batch"]}


class BundleBook:
    """録画ごとの封筒 + 束(live/bundles.json)。メモリに持ち、変えたときだけ書く。入口の複数のスレッド(受付・見回り・API)から使うので中は lock。
    path() -> ファイルの場所(呼ぶたびに読む = テストが親の store_dir を差し替えても効く)"""

    def __init__(self, path, clock=time.time, log=None):
        self.path, self.clock, self.log = path, clock, log or (lambda m: None)
        self.lock = threading.Lock()
        self._items = None
        self._at = None   # 読んだファイルの場所

    @staticmethod
    def key(rc, rec):
        return "%s/%s" % (rc, rec)

    def _load(self):
        p = self.path()
        if self._items is not None and self._at == p:
            return self._items
        d = fsio.read_json_or(p, None, BUNDLES_READ_MAX, kind=dict) or {}
        items, bad = {}, 0
        for k, v in d.items():
            rc, _sep, rec = k.partition("/") if isinstance(k, str) else ("", "", "")
            try:
                spec = _spec.validate(_spec.merge(v.get("spec")))
            except (AttributeError, TypeError, ValueError):
                bad += 1
                continue
            if not schemas.ids_ok(rc, rec):
                bad += 1
                continue
            env = v.get("envelope")
            try:
                env = _envelope.check(env) if env is not None else None
            except (TypeError, ValueError):
                env = None   # 封筒は記録だけ(束が読めれば使う)
            items[k] = {"envelope": env, "spec": spec, "at": v["at"] if schemas.is_num(v.get("at")) else 0}
        if bad:
            self.log("リアルタイム切り抜き: 録画の束 %d 件を読めなかったので、その録画は束なし(今までの設定の読み方)で続けます" % bad)
        self._items, self._at = items, p
        return items

    def _save(self):
        try:
            fsio.atomic_write(self._at, json.dumps(self._items, ensure_ascii=False).encode("utf-8"))
        except OSError as e:
            self.log("リアルタイム切り抜き: 録画の束を書けませんでした(%s)" % tools.why(e))

    def get(self, rc, rec):
        """{"envelope", "spec", "at"} の写しか None"""
        with self.lock:
            v = self._load().get(self.key(rc, rec))
            return copy.deepcopy(v) if v else None

    def spec(self, rc, rec):
        """その録画の束(写し)か None"""
        if not isinstance(rc, str) or not isinstance(rec, str):
            return None
        v = self.get(rc, rec)
        return v["spec"] if v else None

    def specs(self):
        """{"<録画元>/<録画>": 束}(写し)"""
        with self.lock:
            return {k: copy.deepcopy(v["spec"]) for k, v in self._load().items()}

    def put(self, rc, rec, envelope, spec, replace=True):
        """録画に封筒 + 束を残す(replace=False なら、もうあれば残さない = 録画を始めたときの束のまま)。-> 残したか"""
        if not schemas.ids_ok(rc, rec):
            return False
        spec = _spec.validate(_spec.merge(spec))
        with self.lock:
            items = self._load()
            k = self.key(rc, rec)
            if k in items and not replace:
                return False
            items[k] = {"envelope": copy.deepcopy(envelope), "spec": copy.deepcopy(spec), "at": round(self.clock(), 3)}
            while len(items) > BUNDLES_MAX:
                items.pop(min(items, key=lambda x: items[x].get("at") or 0))
            self._save()
        return True

    def prune(self, keep_days=BUNDLES_KEEP_DAYS):
        """古い束を消す -> 消した数"""
        now = self.clock()
        with self.lock:
            items = self._load()
            old = [k for k, v in items.items() if now - (v.get("at") or 0) > keep_days * 86400]
            for k in old:
                items.pop(k, None)
            if old:
                self._save()
        return len(old)


class MemoryRequests:
    """友人の依頼の結びつきの置き場の代わり(メモリだけ。入口は human/friend/live_requests.Store を渡す。flow/livehost.py の RequestBook)"""

    def __init__(self):
        self.items = {}

    def get(self, rc, rec):
        v = self.items.get("%s/%s" % (rc, rec))
        return copy.deepcopy(v) if v else None

    def all(self):
        return copy.deepcopy(self.items)

    def put(self, rc, rec, ctx):
        item = dict(copy.deepcopy(ctx), createdAt=time.time())
        self.items["%s/%s" % (rc, rec)] = item
        return dict(item)

    def prune(self):
        return 0


class LiveSession:
    def __init__(self, root, logs_dir, requests=None, cfg=None, log=None, python=None, data_dir=None, watch_sec=WATCH_SEC, spawn=True,
                 store_dir=None, out_dir=None, runner=None, audio=None, archive_opts=None, cleanup_opts=None, marks=None, deliver_for=None):
        """root: src/(ツールの 1 つ上)。logs_dir: 入口の作業データの logs。requests: 友人の依頼の結びつき(livehost.RequestBook。入口は live_requests.Store。
        無ければメモリだけ)。cfg() -> ライブの設定 {enabled, folder, recorders, quality, auto, detect, autoAdopt, …}(入口はホームの設定の節 live。
        無い・読めなければオフ)。data_dir: 手元の録画の部品の作業データ(テスト用。既定 recorder_data_dir)。
        store_dir: マークと書き出しの記録(既定 入口の作業データの live)。out_dir(): 書き出し先(既定 スタジオの書き出し先)。
        runner(): まとめて実行(flow/runqueue.py の Queue。書き出した切り抜きを submit する)か None。
        audio(): 束の無い録画の書き出しの音量 {"volume", "loudness"}(None = 変えない)。
        archive_opts・cleanup_opts: Archiver・片付けへ渡す引数(テスト用)。marks: マークの置き場(既定 LocalMarks = スタジオなし)。
        deliver_for: 友人の依頼の無い録画を確認なしで届けるか(app の hook。flow/live_adopt.py の Adopter)"""
        self.root, self.logs_dir = root, logs_dir
        self._cfg_fn = cfg
        self.store_dir = store_dir or os.path.join(os.path.dirname(logs_dir), "live")
        self.out_dir = out_dir or (lambda: datadir.studio_out_dir(self.root))
        self.audio = audio
        self.runner = runner or (lambda: None)
        self._exporter = None
        self._archiver = None
        self.archive_opts = dict(archive_opts or {})
        self._cleaner = None
        self.cleanup_opts = dict(cleanup_opts or {})
        self._ex_lock = threading.Lock()
        self.log = log or (lambda m: None)
        self.python = python or sys.executable
        self.data_dir = data_dir or recorder_data_dir(root)
        self.watch_sec, self.spawn_ok = watch_sec, spawn
        self.wake = threading.Event()
        self._halt = threading.Event()
        self._thread = None
        self._last_spawn = 0.0
        self.proc = None
        self.probe = probe_live           # 配信の状態を調べる(begin。テストは偽物に差し替える = 本物の YouTube へ繋がない)
        self.allow_local_urls = False     # begin で手元の URL も通す(テストの録画元 --source direct だけ。画面からは変えられない)
        self._recent = None               # api/ytt/live の status の結果 (時刻, 一覧)
        self._recent_lock = threading.Lock()
        self._stop_lock = threading.Lock()
        self._stopped = None              # 入口の終了で録画の部品を止めた結果(stop_recorder。2 回目からはこれを返す)
        self.always_on = False            # 設定に関わらずオン(画面なし = 送るアプリの依頼で動く。use_headless)
        self.request_all = False          # どの封筒も友人の依頼の結びつきを作る(画面なし = 依頼の決まりで検出・採用・パックまで)
        self.disk_min_gb = None           # 空き容量の下限(GB。下回ったら新しい録画を始めない。画面なし = machine.json の diskMinGB。None = 見ない)
        self.disk_usage = fsio.disk_space     # (空き, 全体)(テストは偽の小さな空きにする)
        # 子(Detector・LiveTx・Reporter・Exporter)は self を親 host として受ける = flow/livehost.py の LiveHost(RS7-2 G0)
        self.detector = live_detect.Detector(self, python=self.python, spawn=spawn)   # 配信中の盛り上がりの検出(L2)と自動の採用(M11)
        self.requests = requests if requests is not None else MemoryRequests()   # 友人のライブ配信の依頼と録画の結びつき(2-15)
        self.bundles = BundleBook(lambda: os.path.join(self.store_dir, BUNDLES_FILE), log=self.log)   # 録画ごとの封筒 + 束(RS7-2 G2b)
        self.livetx = live_tx.LiveTx(self, log=self.log, python=self.python)   # 配信中の候補の文字起こし(D-11 案 b。whisper.cpp の GPU)
        self.reporter = live_report.Reporter(self)   # 配信ごとの結果の記録(D-12。live/reports/)
        self.unconfirmed = None            # () -> 「自動の切り抜き: 未確認」の数(D-13 の休む判断。入口が渡す。None = 休まない)
        self.auto_max = None               # (録画元, 録画) -> 1 録画の自動の採用の上限(D-13)。None = live_detect.AUTO_MAX_PER_REC
        # 採用(M1)のマークの置き場(既定 = マークの正本 LocalMarks。入口はスタジオ = StudioMarks)
        self.marks = marks if marks is not None else live_adopt.LocalMarks(lambda: self.exporter)
        self.adopter = live_adopt.Adopter(self, deliver_for=deliver_for)   # 採用の本体(RS7-2 G1b)
        self._scope = threading.local()    # cfg_scope の中で読んだ設定(スレッドごと)
        self._tokens = fsio.StampCache()   # 手元の録画元の合言葉(token.txt。変わったときだけ読み直す)

    # --- 設定 ---
    def cfg(self):
        """ライブの設定(読めなければオフ)。要求・見回りの中(cfg_scope)では、頭で 1 回読んだ値"""
        hit = getattr(self._scope, "cfg", None)
        return hit if hit is not None else self._read_cfg()

    def _load_cfg(self):
        """ライブの設定の出どころ(入口の Live はホームの設定の節 live を読む)"""
        return self._cfg_fn() if self._cfg_fn is not None else dict(OFF)

    def _read_cfg(self):
        try:
            c = self._load_cfg()
        except Exception:
            c = None
        c = c if isinstance(c, dict) else dict(OFF)
        return dict(c, enabled=True) if self.always_on else c

    @contextlib.contextmanager
    def cfg_scope(self):
        """1 つの要求・見回りの間は、設定を頭で 1 回だけ読む(スタジオが 3 秒ごとに呼ぶ GET /live/api/peaks 1 回で約 11 回読み直していた)。
        時間では覚えない(終われば捨てる = 設定を変えた直後の要求・見回りは新しい値)。入れ子なら外側の値のまま。スレッドごと(ほかの要求・裏の処理は自分で読む)"""
        if getattr(self._scope, "cfg", None) is not None:
            yield
            return
        self._scope.cfg = self._read_cfg()
        try:
            yield
        finally:
            self._scope.cfg = None

    def enabled(self):
        return self.cfg().get("enabled") is True

    def recorders(self, cfg=None):
        """録画元の一覧(合言葉つき。画面には出さない)。空 = 手元の1つ"""
        cfg = cfg or self.cfg()
        out = []
        for r in (cfg.get("recorders") or [dict(LOCAL)]):
            r = dict(r)
            if not r.get("token") and is_local_url(r.get("url") or ""):
                r["token"] = self.local_token()
            out.append(r)
        return out

    def find(self, rid):
        return next((r for r in self.recorders() if r.get("id") == rid), None)

    def bundle(self, rc, rec):
        """その録画の束(録画を始めたときに受けた物。RS7-2 G2b)か None(束の無い録画 = 今までの設定の読み方)"""
        return self.bundles.spec(rc, rec)

    def bundle_top(self, rc, rec):
        """1 録画の自動の採用の上限 = その録画の束の adopt.top(友人の PC の auto_max。束の無い録画は None = live_detect.AUTO_MAX_PER_REC)"""
        b = self.bundle(rc, rec)
        return live_adopt.top_of(b) if b is not None else None

    def auto_cfg(self, rc=None, rec=None):
        """書き出したあとの自動の流れ(M2)-> {after, cut, engine, model, pad}。pad = 自動・アーカイブの採用の前後の余白(秒。M8)。
        ライブの設定 auto(読めなければ既定)。rc・rec の録画に束があれば、cut・engine・model は束が決めた物(run.pinned にある物。無ければ "")・pad は束の adopt.pad
        (録画を始めたときに固定 = 決定 3-31 の仮 b1・b3)。after は束に無い(ライブの設定のまま)"""
        a = self.cfg().get("auto")
        a = a if isinstance(a, dict) else {}
        pad = a.get("pad")
        out = {"after": a.get("after") if a.get("after") in LX.AFTERS else "check",
               "cut": a.get("cut") or "", "engine": a.get("engine") or "", "model": a.get("model") or "",
               "pad": float(pad) if schemas.is_num(pad) and 0 <= pad <= PAD_MAX else float(_spec.DEFAULTS["adopt"]["pad"])}
        b = self.bundle(rc, rec) if rc and rec else None
        if b is not None:
            pins = b["run"]["pinned"]
            out.update(cut=b["pack"]["cut"] if "cut" in pins else "", engine=b["transcribe"]["engine"] if "engine" in pins else "",
                       model=b["transcribe"]["model"] if "model" in pins else "")
            if 0 <= b["adopt"]["pad"] <= PAD_MAX:
                out["pad"] = float(b["adopt"]["pad"])
        return out

    @property
    def exporter(self):
        """マークと書き出し(src/flow/live_export.py)。オンにして初めて使うときに作る(オフの間は作業データに何も作らない)"""
        with self._ex_lock:
            if self._exporter is None:
                self._exporter = LX.Exporter(self, self.store_dir, lambda: self.out_dir(), runner=lambda: self.runner(), log=self.log,
                                             audio=lambda: self.audio() if self.audio is not None else None,
                                             runs_log=os.path.join(self.logs_dir, runlog.RUNS_LOG),   # 失敗の集約(M3)が読む まとめて実行の記録
                                             exported=lambda job, media, archived=False: self.marks.exported(job, media, archived))   # マークを「書き出し済み」に
            return self._exporter

    @property
    def archiver(self):
        """アーカイブで本番版に作り直す(src/flow/live_archive.py。P4)。書き出しのジョブを単位にするので、書き出しと同じく初めて使うときに作る"""
        ex = self.exporter
        with self._ex_lock:
            if self._archiver is None:
                kw = dict({"studio": self.studio_call, "enabled": self.enabled, "auto": lambda: self.cfg().get("autoArchive") is not False,
                           "recording_state": self.recording_state, "python": self.python, "log": self.log,
                           "after": self._cleaner_check,   # 1本終えたら: 全部入れ替わった録画を消す
                           "after_stream": lambda: self.cfg().get("autoAfterStream") is True,   # 配信後の全自動(M7)
                           "per_hour": lambda: self.cfg().get("afterStreamPerHour") or _spec.DEFAULTS["adopt"]["perHour"],
                           "recordings": self.list_recordings, "adopt": self.adopt, "request": self.requests.get,   # 友人の依頼の録画は afterStream の設定で(2-15)
                           "compare": self.detector.compare,   # 配信中の候補とアーカイブの候補を比べる(0-10-6)
                           "settings_for": lambda rc, rec: (self.bundle(rc, rec) or {}).get("analyze"),   # 配信後の解析の設定はその録画の束から(RS7-2 G2b)
                           "pack_info": self._pack_info},   # パックの有無の規則は入口が渡す(live_archive は読まない)
                          **self.archive_opts)
                self._archiver = live_archive.Archiver(ex, **kw)
            return self._archiver

    @property
    def cleaner(self):
        """録画を自動で消す(入口が _make_cleaner で作る = manage/keep/live_cleanup.py。P4。設定 live.autoDelete)。作れなければ None"""
        with self._ex_lock:
            if self._cleaner is None:
                self._cleaner = self._make_cleaner()
            return self._cleaner

    def _make_cleaner(self):
        """録画を消す部品(入口が埋める)。既定は無し = 消さない"""
        return None

    def _cleaner_check(self, rc, rec):
        c = self.cleaner
        return c.check(rc, rec) if c is not None else None

    def _pack_info(self, path):
        """その動画の Resolve パックの情報か None(入口が txindex.pack_info で埋める)"""
        return None

    def auto_delete(self):
        """録画を自動で消してよいか(リアルタイム切り抜きがオンで、設定 live.autoDelete がオン。既定オン)"""
        cfg = self.cfg()
        return cfg.get("enabled") is True and cfg.get("autoDelete") is True   # 消すのは戻せないので、明示的に true のときだけ(既定の値は src/home/prefs.py の DEFAULTS)

    def studio_call(self, method, path, body=None):
        """取り込んだスタジオの API -> (HTTP の番号, JSON)。ここ(スタジオなし)は (None, {"message"})。入口の Live が埋める"""
        return None, {"message": "切り抜きスタジオがありません"}

    def list_recordings(self):
        """録画元ごとの録画の一覧(配信後の全自動 M7 の見回り)-> [{recorder, id, url, title, active, endedAt, firstPdt, lastPdt}](時刻は epoch か None)。
        つながらない録画元は飛ばす"""
        out = []
        for rc in self.recorders():
            for r in LX.rec_list(self.call, rc) or []:
                out.append({"recorder": rc["id"], "id": r["id"], "url": str(r.get("url") or "")[:URL_MAX], "title": str(r.get("title") or "")[:LX.TITLE_MAX],
                            "active": r.get("active") is True or r.get("state") in rec_core.ACTIVE,
                            "endedAt": LX.iso_epoch(r.get("endedAt")), "firstPdt": LX.iso_epoch(r.get("firstPdt")),
                            "lastPdt": LX.iso_epoch(r.get("lastPdt"))})
        return out

    def recording_state(self, rc_id, rec):
        """録画元での録画の状態 {"active", "endedAt"(epoch か None)}。つながらない・見つからないときは None(P4 の自動: 録画が終わったか)"""
        rc = self.find(rc_id)
        for r in (LX.rec_list(self.call, rc) or []) if rc is not None else []:
            if r.get("id") == rec:
                return {"active": r.get("active") is True,
                        "endedAt": LX.iso_epoch(r.get("endedAt")) or LX.iso_epoch(r.get("lastPdt"))}
        return None

    def local_token(self):
        """手元の録画元の合言葉(録画の部品の作業データの token.txt。更新日時と大きさが変わったときだけ読み直す。無ければ "")"""
        return self._tokens.get(os.path.join(self.data_dir, "token.txt"), _read_token) or ""

    def expected_version(self):
        return _version.on_disk(self.root)   # 全体の版(ytt/version.py をディスクから読み直した値)

    # --- 録画元への要求 ---
    def request(self, rc, method, path, body=None, timeout=RELAY_TIMEOUT):
        """-> (HTTPConnection, HTTPResponse)。呼んだ側が読んで conn.close() する。つながらなければ OSError"""
        u = urllib.parse.urlsplit(rc.get("url") or "")
        if u.scheme != "http" or not u.hostname or not u.port:
            raise OSError("録画元の URL が正しくありません")
        conn = http.client.HTTPConnection(u.hostname, u.port, timeout=timeout)
        headers = {"Host": u.netloc, "Authorization": "Bearer " + (rc.get("token") or ""), "Accept": "*/*"}
        data = None
        if body is not None:
            data = json.dumps(body, ensure_ascii=False).encode("utf-8")
            headers["Content-Type"] = "application/json"
        try:
            conn.request(method, path, body=data, headers=headers)
            return conn, conn.getresponse()
        except (OSError, http.client.HTTPException) as e:
            conn.close()
            raise OSError(str(e) or e.__class__.__name__)

    def call(self, rc, method, path, body=None, timeout=3.0):
        """JSON の API を呼ぶ -> (HTTP の番号, JSON)。つながらなければ (None, None)"""
        try:
            conn, r = self.request(rc, method, path, body, timeout)
        except OSError:
            return None, None
        try:
            raw = r.read(4 * 1024 * 1024)
            try:
                return r.status, json.loads(raw.decode("utf-8", "replace"))
            except ValueError:
                return r.status, None
        except (OSError, http.client.HTTPException):
            return None, None
        finally:
            conn.close()

    def ping(self, rc, timeout=1.5):
        code, d = self.call(rc, "GET", "/api/ping", timeout=timeout)
        return d if code == 200 and isinstance(d, dict) and d.get("app") == "ytt-recorder" else None

    def _ids(self, rc_id, rec):
        """録画元と録画の id を確かめる -> 録画元(合言葉つき)。だめなら LiveError"""
        if not schemas.ids_ok(rc_id, rec):
            raise LX.LiveError("録画元か録画の指定が正しくありません")
        rc = self.find(rc_id)
        if rc is None:
            raise LX.LiveError("その録画元はありません", 404)
        return rc

    def _down(self, rc):
        return LX.LiveError("録画元「%s」につながりません。録画の部品が起動するまで少し待ってください(%s)" % (rc.get("name"), rc.get("url")), 502)

    def _find_active(self, rc, url):
        """録画元で同じ配信を録画中の録画(要約)か None"""
        return next((r for r in LX.rec_list(self.call, rc) or [] if r.get("active") and _same_stream(url, r.get("url"), r.get("id"))), None)

    # --- 受付(録画を始める) ---
    def submit(self, envelope, bundle, ctx=None):
        """② の口(Queue.submit が kind live を回す。RS7-2 G2b): 封筒 kind live + 束を受けて録画を始め、録画に封筒 + 束を残す(live/bundles.json)。
        友人の依頼(封筒の requestId か ctx = 入口の intake の欄)と画面なし(request_all)は友人の依頼の結びつき(requests.json)も作る(begin_request)。
        画面なしで空き容量が下限(disk_min_gb)より少なければ録画を始めない。
        -> {"id": 封筒の id, "live", "recorder", "recording": 録画の id, "existing", "title"?} か 配信中でなければ {"id", "live": False, "status", "message"?}。
        形が違う・録画を始められなければ LiveError(ValueError)"""
        env = _envelope.check(envelope)
        if env["kind"] != "live":
            raise LX.LiveError("ライブの依頼(封筒の kind live)ではありません")
        b = _spec.validate(_spec.merge(bundle))
        url = validate_url(stream_url(env), self.allow_local_urls)
        if not self.enabled():
            raise LX.LiveError("リアルタイム切り抜きがオフです", 409)
        rc_id = env["input"].get("recorder")
        self._disk_guard(self._pick_recorder(rc_id))
        if ctx is not None or env["requestId"] or self.request_all:
            out = self.begin_request(url, ctx if ctx is not None else bundle_ctx(env, b, url), envelope=env, bundle=b, recorder=rc_id)
            return dict(out, id=env["id"], live=True)
        v = self.begin(url, envelope=env, bundle=b, recorder=rc_id)
        if not v.get("live"):
            return dict(v, id=env["id"])
        r = v["recording"]
        return {"id": env["id"], "live": True, "recorder": v["recorder"], "recording": r.get("id"), "existing": v["existing"], "title": r.get("title") or ""}

    def _pick_recorder(self, rc_id=None):
        """録画を始める録画元(rc_id が無ければ既定 = 一覧の先頭)。だめなら LiveError"""
        rcs = self.recorders()
        if not rcs:
            raise LX.LiveError("録画元がありません", 409)
        if rc_id is None:
            return rcs[0]   # 既定の録画元 = 一覧の先頭(2台(P5)で二重録画するときは、ここで全部に頼む)
        rc = next((r for r in rcs if r.get("id") == rc_id), None)
        if rc is None:
            raise LX.LiveError("その録画元はありません", 404)
        return rc

    def _disk_guard(self, rc):
        """空き容量の下限(disk_min_gb。画面なし = machine.json の diskMinGB。plan/f1-friend-pc.md 決めたこと 7)を下回っていたら LiveError(409)。
        見る所: 書き出し先・パック・live\\work(Exporter.disk の行)と録画元の録画の置き場所(GET /live/list の freeBytes)"""
        gb = self.disk_min_gb
        if not schemas.is_num(gb) or gb <= 0:
            return
        need, low = gb * LX.GB, []
        for label, path in self.exporter.disk_paths():
            probe = fsio.existing_parent(path)   # まだ無いフォルダは、ある所まで上へ(Exporter.disk と同じ)
            try:
                free = int(self.disk_usage(probe)[0])
            except (OSError, ValueError, TypeError):
                continue
            if free < need:
                low.append((label, free))
        code, d = self.call(rc, "GET", "/live/list", timeout=3.0)
        if code == 200 and isinstance(d, dict) and schemas.is_num(d.get("freeBytes")) and d["freeBytes"] < need:
            low.append(("録画の置き場所", d["freeBytes"]))
        if low:
            raise LX.LiveError("空き容量が下限の %g GB より少ないので、新しい録画を始めません(%s)" % (
                gb, "・".join("%s の空き %.1f GB" % (label, free / LX.GB) for label, free in low)), 409)

    def begin(self, url, envelope=None, bundle=None, recorder=None, replace=False):
        """録画を始める芯(スタジオの URL の欄 POST /live/api/begin・submit・begin_request)。配信中・配信前なら録画を始める(同じ配信を録画中ならそれを返す)。
        bundle(と封筒)があれば、その録画の束として残す(replace = 録画中の録画でも置き換える = 友人の依頼。False = 始めたときの束のまま)。-> 返す JSON"""
        url = validate_url(url, self.allow_local_urls)
        try:
            info = self.probe(url) or {}
        except Exception as e:   # 調べる部品の不具合でも、画面は今までどおりの解析へ進める
            self.log("リアルタイム切り抜き: 配信の状態を調べられませんでした %r" % (e,))
            info = {}
        status = info.get("status") if info.get("status") in LIVE_STATUSES else "unknown"
        if status not in ("is_live", "is_upcoming"):
            out = {"live": False, "status": status}
            if info.get("message"):
                out["message"] = str(info["message"])[:300]
            return out
        rc = self._pick_recorder(recorder)
        ch = _clean(info.get("channel"), CHANNEL_MAX) if isinstance(info.get("channel"), str) else ""   # 録画中だった(existing)ときも付ける

        def view(r, existing):
            if bundle is not None:
                self.bundles.put(rc["id"], r.get("id"), envelope, bundle, replace=replace or not existing)
            return {"live": True, "recorder": rc["id"], "recording": rec_view(r, ch), "existing": existing}
        found = self._find_active(rc, url)
        if found:
            return view(found, True)
        q = self.cfg().get("quality")
        title = info.get("title") if isinstance(info.get("title"), str) else ""
        code, d = self.call(rc, "POST", "/live/start", {"url": url, "quality": q if q in QUALITIES else DEFAULT_QUALITY, "title": title[:LX.TITLE_MAX]},
                            timeout=15.0)
        if code == 200 and isinstance(d, dict) and isinstance(d.get("recording"), dict):
            self._recent = None   # ヘッダーの札にすぐ出す
            self.log("リアルタイム切り抜き: 録画を始めました %s(%s)" % (d["recording"].get("id"), url))
            return view(d["recording"], False)
        if code == 409:   # 「その配信はもう録画しています」(ほかは streamlink が無い・置き場所が無いなど)
            found = self._find_active(rc, url)
            if found:
                return view(found, True)
        if code is None:
            raise self._down(rc)
        msg = (d or {}).get("message") if isinstance(d, dict) else ""
        raise LX.LiveError("録画を始められませんでした: %s" % (msg or "HTTP %s" % code), code if code in (400, 409) else 502)

    def _request_limit(self):
        """友人のライブ配信の依頼を同時に録画する本数の上限(入口は live_requests.MAX_ACTIVE。None = 上限なし = 友人の PC)"""
        return None

    def _request_label(self, item):
        """友人の依頼の設定の 1 行(記録に出す。入口は live_requests.settings_label)"""
        return ""

    def begin_request(self, url, ctx, envelope=None, bundle=None, recorder=None):
        """友人のライブ配信の依頼(docs/spec/friend-intake.md の 2-15。submit から・入口の intake の live_begin から): 録画を始めて(begin)、その録画を依頼に結びつける。
        ctx = {rid, deliverDir, url, title, streamer, speakers, videoTracks, cut, memo, settings, deliverBatch}。封筒 + 束があれば録画の束として残す(置き換える)。
        -> {"recorder", "recording", "existing"}。だめなら LiveError"""
        if not self.enabled():
            raise LX.LiveError("リアルタイム切り抜きがオフです", 409)
        limit = self._request_limit()
        busy = self.active_requests(url) if limit is not None else []   # 同時の上限(同じ配信なら今の録画に結びつける = existing)
        if limit is not None and len(busy) >= limit:
            raise LX.LiveError("友人のライブ配信の依頼は同時に %d 本までです(「%s」を録画中。終わってからもう一度送ってください)"
                               % (limit, "」「".join((r.get("title") or r.get("url") or r["id"])[:60] for r in busy)), 409)
        out = self.begin(url, envelope=envelope, bundle=bundle, recorder=recorder, replace=True)
        if not out.get("live"):
            raise LX.LiveError("配信中・配信前の配信ではありません(%s)" % (out.get("status") or "unknown"), 409)
        rc, rec = out["recorder"], out["recording"]["id"]
        item = self.requests.put(rc, rec, ctx)
        label = self._request_label(item)
        self.log("リアルタイム切り抜き: 友人の依頼 %s を録画 %s に結びつけました%s" % (item["rid"], rec, "(%s)" % label if label else ""))
        self.detector.wake()   # 検出がオフでも、この録画はすぐ測り始める
        return {"recorder": rc, "recording": rec, "existing": bool(out.get("existing"))}

    def active_requests(self, url):
        """友人のライブ配信の依頼に結びついた録画で、まだ録画中のもの(url と同じ配信は除く)-> 録画元の一覧の行のリスト(同時の上限の分子)"""
        items = self.requests.all()
        if not items:
            return []
        return [r for r in self.list_recordings()
                if r.get("active") and "%s/%s" % (r["recorder"], r["id"]) in items and not _same_stream(url, r.get("url") or "", r["id"])]

    def _request_for(self, rc_id, rec, origin, after, streamer):
        """録画が友人のライブ配信の依頼に結びついていれば (依頼, after=auto, 配信者)・無ければ自分の配信を届けるか(deliver_for)。
        本体は flow/live_adopt.py の Adopter.request_for(RS7-2 G1b)"""
        return self.adopter.request_for(rc_id, rec, origin, after, streamer)

    def _rec_status(self, rc, rc_id, rec):
        """録画元の録画の状態(書き出しの基準 firstPdt・URL・題)。-> (状態の JSON, 最初のセグメントの受信時刻 epoch)。だめなら LiveError"""
        code, d = self.call(rc, "GET", "/live/%s/status?since=999999999" % rec, timeout=5.0)   # since: セグメントの一覧は要らない
        if code is None:
            raise self._down(rc)
        if code == 404:
            if any(j.get("recordingDeleted") for j in self.exporter.snapshot(rc_id, rec)):   # 本番版に入れ替えて、録画を自動で消した(P4)
                raise LX.LiveError("録画は消しました(本番版に入れ替え済み)。区間を変えた切り抜きは、録画が無いので作れません", 404)
            raise LX.LiveError("その録画はありません(録画元で消されたか、置き場所を変えたかもしれません)", 404)
        if code != 200 or not isinstance(d, dict):
            raise LX.LiveError("録画元から思わぬ応答がありました(HTTP %s)" % code, 502)
        first = LX.iso_epoch(d.get("firstPdt"))   # 秒の 0 = 最初のセグメントの受信時刻(live_export.Exporter._base と同じ基準)
        if first is None:
            raise LX.LiveError("録画がまだ始まっていません(録画のデータが最初に届いてから書き出せます)", 409)
        return d, first

    # --- M1: サーバー側の「マーク + 書き出し」(画面を閉じていても。自動の採用 M7・M11 もここを通る) ---
    def adopt(self, body, hold=None):
        """POST /live/api/adopt(M1)。-> {job, video, mark, origin, existing}。本体は flow/live_adopt.py の Adopter.adopt(RS7-2 G1b。マークの置き場は self.marks)。
        hold: "archive" = 書き出したあと、本番版に入れ替えてから まとめて実行へ渡す(配信後の全自動 M7 が入口の中から渡す。API の本文からは渡せない)"""
        return self.adopter.adopt(body, hold)

    def recent(self):
        """録画中 + 終わって RECENT_SEC 秒以内の録画(録画元ごと)。STATUS_CACHE 秒は前の結果を返す(ロックの中で問い合わせる = 同時に来ても1回)"""
        with self._recent_lock:
            if self._recent is not None and time.time() - self._recent[0] < STATUS_CACHE:
                return self._recent[1]
            out, now = [], time.time()
            for rc in self.recorders():
                for r in LX.rec_list(self.call, rc, STATUS_TIMEOUT) or []:
                    ended = LX.iso_epoch(r.get("endedAt"))
                    if not r.get("active") and (ended is None or now - ended > RECENT_SEC):
                        continue
                    secs = r.get("seconds")
                    a, b = LX.iso_epoch(r.get("firstPdt")), LX.iso_epoch(r.get("lastPdt"))
                    if a is not None and b is not None and schemas.is_num(secs):
                        secs = round(max(secs, b - a), 3)   # スタジオの録画の長さと同じ(受信時刻の幅。繋ぎ直しの欠けの間も時間は進む)
                    out.append({"recorder": rc["id"], "id": r["id"], "title": str(r.get("title") or "")[:LX.TITLE_MAX],
                                "state": str(r.get("state") or ""), "active": r.get("active") is True,
                                "seconds": secs if schemas.is_num(secs) else 0,
                                "endedAt": r.get("endedAt") if ended is not None else None, "url": str(r.get("url") or "")[:URL_MAX]})
            self._recent = (time.time(), out)
            return out

    def note(self, msg):
        """同じ知らせを見回りのたびに記録しない"""
        if msg != getattr(self, "_last_note", None):
            self._last_note = msg
            self.log(msg)

    # --- 見回り(手元の録画の部品を起こす) ---
    def start(self):
        if self._thread is None:
            self._thread = threading.Thread(target=self._watch, daemon=True, name="live-watch")
            self._thread.start()

    def close(self):
        """入口の終了: 見回りを止め、録画中でなければ録画の部品も止める(stop_recorder。録画中なら残す = 録画は続く。計画の 0-3 と 2026-10-07 ユーザー指示)"""
        self._halt.set()
        self.wake.set()
        self.detector.stop()   # 盛り上がりの検出のワーカー(状態は 1 分ごとに保存済み。次の起動で続きから)
        self.livetx.close()    # 配信中の文字起こしの子プロセス(途中の候補は次の見回りでやり直す)
        if self._archiver is not None:   # 本番版への作り直しの途中なら止める(順番待ちに戻り、次の起動で続ける)
            self._archiver.close()
        if self._exporter is not None:   # 書き出しの途中なら ffmpeg を止める(ジョブは「録画待ち」に戻り、次の起動でやり直す)
            self._exporter.close()
        try:
            self.stop_recorder()
        except Exception as e:   # 後始末の途中の不具合で入口の終了を止めない
            self.log("録画の部品を止める途中でエラー: %r" % (e,))

    # --- 入口の終了で録画の部品も止める(入口 0.38.1) ---
    def _own_proc(self):
        """この入口が起動して、まだ動いている録画の部品のプロセス(無ければ None)"""
        p = self.proc
        return p if p is not None and p.poll() is None else None

    def _stop_target(self):
        """入口の終了で止める手元の録画元。リアルタイム切り抜きがオンか、この入口が起動した録画の部品が動いているときだけ(オフで人が別に起動したものは触らない)"""
        if self._own_proc() is None and not self.enabled():
            return None
        return next((r for r in self.recorders() if is_local_url(r.get("url") or "")), None)

    def local_recording(self, timeout=1.5):
        """入口の終了で止める手元の録画元が録画中か: True / False(録画していない・止める相手が無い)/ None(つながらない)。「すべて終了」の応答の知らせに使う"""
        rc = self._stop_target()
        if rc is None:
            return False
        code, d = self.call(rc, "GET", "/live/list", timeout=timeout)
        if code != 200 or not isinstance(d, dict):
            return None
        return bool(d.get("active")) or any(isinstance(r, dict) and r.get("active") is True for r in d.get("recordings") or [])

    def stop_recorder(self):
        """入口の終了で手元の録画の部品を止める。-> "none"(止める相手が無い・動いていない)|"quit"(静かに終わった)|
        "killed"(応答が無い・終わらないので孫ごと止めた)|"kept"(録画中なので残した)|"failed"(断られた。残した)。2 回目からは前の結果"""
        with self._stop_lock:
            if self._stopped is None:
                self._stopped = self._stop_recorder()
            return self._stopped

    def _stop_recorder(self):
        rc, own = self._stop_target(), self._own_proc()
        if rc is None:
            return "none"
        code, d = self.call(rc, "POST", "/live/quit", {}, timeout=QUIT_TIMEOUT)
        if code == 409:   # 録画中(録画の部品が断る)= 止めない
            self.log("録画の部品: " + KEPT_NOTE)
            return "kept"
        if code == 200:
            end = time.time() + QUIT_WAIT
            while time.time() < end:   # この入口が起動したものはプロセスの終わり、それ以外は待ち受けの終わりを待つ
                if (own.poll() is not None) if own is not None else not self.ping(rc, 0.5):
                    self.log("録画の部品を終わらせました(ホームの終了)")
                    return "quit"
                time.sleep(0.2)
            if own is not None:
                tools.kill_tree(own, wait=5.0)
                self.log("録画の部品が %d 秒で終わらないので、止めました(ホームの終了)" % int(QUIT_WAIT))
                return "killed"
            self.log("録画の部品に終わるよう伝えました(終わるのを待ちきれませんでした)")
            return "quit"
        if code is None:   # 応答が無い: この入口が起動したものなら孫ごと止める。それ以外は動いていない
            if own is not None:
                tools.kill_tree(own, wait=5.0)
                self.log("録画の部品が応答しないので、止めました(ホームの終了)")
                return "killed"
            return "none"
        msg = (d or {}).get("message") if isinstance(d, dict) else ""
        self.log("録画の部品を止められませんでした(HTTP %s%s)。録画の部品は残しています" % (code, ": " + msg if msg else ""))
        return "failed"

    def _watch(self):
        while not self._halt.is_set():
            try:
                self.tick()
            except Exception as e:   # 見回りは止めない
                self.log("録画の部品の見回りでエラー: %r" % (e,))
            self.wake.wait(self.watch_sec)
            self.wake.clear()

    def _guard(self, what, fn, default=None):
        """見回り・「調子」の 1 つを動かす(不具合でもほかは続ける。記録は「リアルタイム切り抜き: <what>: <例外>」を同じ文なら 1 回だけ)-> fn() か default"""
        try:
            return fn()
        except Exception as e:
            self.note("リアルタイム切り抜き: %s: %r" % (what, e))
            return default

    def tick(self):
        """オンなら: 手元の録画元が動いていなければ起動する・古い版なら(録画中でなければ)起動し直す・置き場所の設定が違えば伝える。
        -> "off"|"running"|"spawned"|"waiting"|"failed\""""
        with self.cfg_scope():   # 1 回の見回りの中では同じ設定(C)
            return self._tick()

    def _request_watch(self):
        """友人の依頼の結びつきの片付けのあとに入れる見回り(入口は D-13 の 6 時間の上限)-> [(what, fn)]"""
        return []

    def _app_watch(self):
        """配信の記録のあとに入れる見回り(入口は届け方の組の溜め・見ていない自動の切り抜きの片付け)-> [(what, fn)]"""
        return []

    def _watch_steps(self):
        """1 回の見回りで動かす物の列 [(記録の文, fn)](不具合でもほかは続ける = _guard)"""
        return ([("盛り上がりの検出の見回りでエラー", self.detector.tick),   # L2・M11: オンならワーカーを見張り・自動の採用、オフなら止める
                 ("配信中の文字起こしの見回りでエラー", self.livetx.tick),   # D-11 案 b: 確定した候補を列に入れる(準備が無ければ何もしない)
                 ("友人の依頼の結びつきの片付けでエラー", self.requests.prune)]   # 2-15: 古い結びつきを消す(消すものがあるときだけ書く)
                + self._request_watch()
                + [("録画の束の片付けでエラー", self.bundles.prune),   # RS7-2 G2b: 古い録画の束を消す
                   ("配信の記録の見回りでエラー", self.reporter.tick)]   # D-12: 配信ごとの結果の記録(録画中は 1 分ごと・終わったら最後に 1 回)
                + self._app_watch())

    def _tick(self):
        for what, fn in self._watch_steps():
            self._guard(what, fn)
        cfg = self.cfg()
        if cfg.get("enabled") is not True:
            return "off"
        if os.path.isfile(os.path.join(self.store_dir, "exports.json")) or cfg.get("autoAfterStream") is True or self.requests.all():   # 友人の依頼の録画(2-15)は M7 がオフでも
            if self.exporter.pending():   # 入口を起動し直した: 途中の書き出しを続ける(空き待ちの受け渡しも。M4)
                self.exporter.start()
            self.archiver.start()   # 本番版への作り直し(P4): 途中のものを続ける・自動の見回り(設定 live.autoArchive)・配信後の全自動(M7)
        if self.auto_delete():   # 録画を自動で消す(P4。設定 live.autoDelete。中で間隔を見る = 10 分ごと。不具合でも録画の部品の見回りは続ける)
            self._guard("録画を消す見回りでエラー", lambda: self.cleaner is not None and self.cleaner.tick())
        local = next((r for r in self.recorders(cfg) if is_local_url(r.get("url") or "")), None)
        if local is None:
            return "off"
        info = self.ping(local)
        if info:
            exp = self.expected_version()
            if exp and info.get("version") != exp:   # コードを直した(版が上がった): 録画中でなければ終わってもらって、新しい版で起こし直す
                code, _d = self.call(local, "POST", "/live/quit", {})
                if code == 200:
                    self.note("録画の部品が古い版(v%s)なので、v%s で起動し直します" % (info.get("version"), exp))
                    end = time.time() + 15
                    while time.time() < end and self.ping(local, 0.5):
                        time.sleep(0.3)
                    self._last_spawn = 0.0
                    return "spawned" if self.spawn_ok and self.spawn(local, cfg.get("folder") or "") else "waiting"
                self.note("録画の部品が古い版(v%s)ですが、録画中なので録画が終わってから起動し直します" % info.get("version"))
            folder = cfg.get("folder") or ""
            if folder:
                code, d = self.call(local, "GET", "/live/config")
                if code == 200 and isinstance(d, dict) and os.path.normcase(d.get("folder") or "") != os.path.normcase(os.path.normpath(folder)):
                    code, d = self.call(local, "POST", "/live/config", {"folder": folder})
                    self.note("録画の置き場所を %s にしました" % folder if code == 200 else
                              "録画の置き場所を変えられませんでした: %s" % ((d or {}).get("message") or code))
            return "running"
        if not self.spawn_ok:
            return "waiting"
        if time.time() - self._last_spawn < SPAWN_GAP:   # 起動したばかり(待ち受けの準備中)
            return "waiting"
        return "spawned" if self.spawn(local, cfg.get("folder") or "") else "failed"

    def spawn(self, rc, folder=""):
        """手元の録画の部品を、入口と切り離して起動する(入口と同じ Python = start.bat と同じ選び方で選ばれたもの)"""
        if self._halt.is_set():   # 入口の終了の途中(止めたあとに見回りが起こし直さない)
            return False
        self._last_spawn = time.time()
        script = os.path.join(self.root, layout.RECORDER_SCRIPT)
        if not os.path.isfile(script):
            self.log("録画の部品が見つかりません: %s" % script)
            return False
        port = urllib.parse.urlsplit(rc["url"]).port or RECORDER_PORT
        cmd = [self.python, "-u", script, "--port", str(port), "--quiet", "--data-dir", self.data_dir]
        if folder:
            cmd += ["--folder", folder]
        # 別のプロセスグループ(入口への Ctrl+Break が届かない)・隠れた黒い画面(入口の黒い画面を閉じても止まらない)・通常より上の優先度
        flags = tools.no_window_flags(new_group=True, priority="high")
        os.makedirs(self.logs_dir, exist_ok=True)
        try:   # 入口がジョブ(閉じると子も消える)の中で動いていても、録画の部品は外へ出す。出られないジョブならそのまま
            self.proc = tools.start_logged(cmd, os.path.join(self.logs_dir, "recorder.log"), os.path.dirname(script),
                                                 [flags | getattr(subprocess, "CREATE_BREAKAWAY_FROM_JOB", 0), flags])
        except OSError as e:
            self.log("録画の部品を起動できませんでした: %s" % tools.why(e))
            return False
        self.log("録画の部品を起動しました(%s。置き場所 %s)" % (rc["url"], folder or "前回の設定か既定 " + DEFAULT_FOLDER))
        return True

    # --- 「調子」 ---
    def health(self):
        """オフなら None(「調子」に出さない)。オンなら録画元ごとの状態と空き容量"""
        with self.cfg_scope():   # 1 回の「調子」の中では同じ設定(C)
            return self._health()

    def _health(self):
        cfg = self.cfg()
        if cfg.get("enabled") is not True:
            return None
        expected = self.expected_version()
        out = []
        for rc in self.recorders(cfg):
            row = {"id": rc["id"], "name": rc["name"], "url": rc["url"], "ok": False, "version": "", "expected": expected if is_local_url(rc["url"]) else "",
                   "folder": None, "folderOk": None, "folderMessage": "", "freeBytes": None, "totalBytes": None, "streamlink": None,
                   "active": 0, "recordings": [], "message": ""}
            code, d = self.call(rc, "GET", "/live/list", timeout=2.0)
            if code == 200 and isinstance(d, dict):
                row.update(ok=True, version=str(d.get("version") or ""), folder=d.get("folder"), folderOk=d.get("folderOk"),
                           folderMessage=d.get("folderMessage") or "", freeBytes=d.get("freeBytes"), totalBytes=d.get("totalBytes"),
                           streamlink=d.get("streamlink"), active=d.get("active") or 0,
                           recordings=[{k: x.get(k) for k in ("id", "title", "state", "message", "segments", "lastPdt")}
                                       for x in (d.get("recordings") or []) if x.get("active")][:5])
            elif code is None:
                row["message"] = "つながりません(録画の部品が起動していません)"
            else:
                row["message"] = ((d or {}).get("message") if isinstance(d, dict) else "") or "応答が正しくありません(HTTP %s)" % code
            out.append(row)
        failures = []   # 新しい順に MAX_LIST まで(文は LIVE の帯と同じ = live_failures)
        if os.path.isfile(os.path.join(self.store_dir, "exports.json")):   # 書き出し・まとめて実行へ渡す・文字起こし・パック(M3。failure_of)
            failures += self._guard("失敗の一覧を作れませんでした", self.exporter.failures, [])
        if self._archiver is not None:   # 配信後の全自動(M7)が止まった録画(after_stream_failure)
            failures += self._guard("配信後の自動の失敗を読めませんでした", self._archiver.after_failures, [])
        failures += self._guard("盛り上がりの検出の失敗を読めませんでした", self.detector.failures, [])   # L2・M11
        if self._cleaner is not None:   # D-14: 本番版に置き換わらないまま残っている録画の知らせ(keep_failure)
            failures += self._guard("残っている録画の一覧を作れませんでした", self._cleaner.kept_failures, [])
        failures = sorted(failures, key=lambda x: x.get("at") or "", reverse=True)[:live_failures.MAX_LIST]
        disk = self._guard("空き容量を調べられませんでした", self.exporter.disk)   # 書き出し先・パック・live\work の空き(M4)
        try:   # 配信中の検出(L2。worker.json・peaks.json を読む。オフなら None)
            detect = self.detector.health()
        except Exception as e:
            self.note("リアルタイム切り抜き: 検出の状態を読めませんでした: %r" % (e,))
            detect = {"running": False, "error": "状態を読めませんでした", "restarts": self.detector.restarts}
        return {"recorders": out, "failures": failures, "disk": disk, "detect": detect}
