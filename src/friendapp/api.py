# -*- coding: utf-8 -*-
"""友人の玄関の口の中身(F2-2。HTTP の形は server.py。ここは欄の検査・② への受付・受信箱の決め方・前回の値)。

送る欄(notes:plan/f1-friend-requirements.md の A-3〜A-10):
    url            配信の URL 1 本(A-4。YouTube の配信・動画。動画ファイルとライブは F2-6)
    ranges         区間 [[開始, 終了], …](秒。任意)。区間があれば本数は区間の数(自動の見どころで埋めない = A-3)
    top            本数(区間が無いときだけ。1〜30。前回の値)
    streamer       配信者(自動の推し・名簿・打った名前。"" = 色なし。依頼ごと = 覚えない = A-7)
    people         コラボで足した人の名前(字幕の色だけ。話者分離は友人の PC の ② にまだ無いので人数は束に入れない = 仮・AI)
    videoTracks    映像トラックの数 1〜5(「詳しく」・前回の値 = A-6)
    deliverBatch   届け方 1 か 5(「詳しく」・初めは 5・前回の値 = A-9)
    weights        解析の重み {wAudio, wChat, wComments} 0〜3 か null(「詳しく」・区間のある依頼では使わない = A-10)
    pc             処理する PC "this"(この PC の ②)/ "user"(ユーザーの PC に Dropbox で頼む。「詳しく」・前回の値・初めは this = A-2。F2-3)
カット(A-8)は束の既定のまま(しない)。前回の値は <玄関>/form.json。
ユーザーの PC に頼む行は、同期(friendapp/sync.py。api.sync)が依頼の JSON を Dropbox の直下へ上げる。受付が 1 時間読まなければ [この PC でやり直す](local)。
"""
import json
import os
import threading
import time
import urllib.error
import urllib.parse
import urllib.request

from flow import deliver as _deliver, order as _order, spec as _spec
from ytt import colors as _colors, fsio as _fsio, yturl as _yturl

FORM_NAME = "form.json"
FORM_DEFAULTS = {"top": 10, "videoTracks": 1, "deliverBatch": 5, "useWeights": False, "weights": {"wAudio": 1, "wChat": 1, "wComments": 1},
                 "pc": "this"}
BATCHES = (1, 5)
PCS = ("this", "user")
PEOPLE_MAX = 6
OEMBED = "https://www.youtube.com/oembed?format=json&url="
PEEK_TIMEOUT = 8


class FormError(ValueError):
    """送る欄が違う(文は画面にそのまま出す)"""


def _int_in(v, lo, hi):
    return isinstance(v, int) and not isinstance(v, bool) and lo <= v <= hi


def oembed(vid, timeout=PEEK_TIMEOUT):
    """oEmbed(公開・キー不要)で題とチャンネル名 -> {"title", "channel"}(取れなければ空。接続先は固定・id は検査済み)"""
    target = OEMBED + urllib.parse.quote(_yturl.watch_url(vid), safe="")
    try:
        with urllib.request.urlopen(urllib.request.Request(target, headers={"Accept": "application/json"}), timeout=timeout) as r:
            d = json.loads(r.read(200000).decode("utf-8", "replace"))
    except (urllib.error.URLError, TimeoutError, OSError, ValueError):
        return {"title": "", "channel": ""}
    return {"title": str(d.get("title") or "")[:120], "channel": str(d.get("author_name") or "")[:100]}


class Api:
    """玄関の口(server.py の Handler が呼ぶ)。engine = friendapp.engine.Engine(準備中は None)"""

    def __init__(self, places, inbox, engine_fn, fetch=oembed, clock=time.time):
        self.places, self.inbox, self.engine_fn = places, inbox, engine_fn
        self.fetch, self.clock = fetch, clock
        self.form_path = os.path.join(places["friend"], FORM_NAME)
        self._peek = {}
        self._lock = threading.Lock()
        self.sync = None   # Dropbox の同期(friendapp/sync.Sync。玄関が入れる。無ければユーザーの PC には頼めない)

    # ------------------------------------------------------------ 前回の値
    def form(self):
        d = _fsio.read_json_or(self.form_path, {}, kind=dict)
        out = json.loads(json.dumps(FORM_DEFAULTS))
        if _int_in(d.get("top"), 1, 30):
            out["top"] = d["top"]
        if _int_in(d.get("videoTracks"), 1, 5):
            out["videoTracks"] = d["videoTracks"]
        if d.get("deliverBatch") in BATCHES:
            out["deliverBatch"] = d["deliverBatch"]
        if isinstance(d.get("useWeights"), bool):
            out["useWeights"] = d["useWeights"]
        if d.get("pc") in PCS:
            out["pc"] = d["pc"]
        w = d.get("weights")
        if isinstance(w, dict) and all(_int_in(w.get(k), 0, 3) for k in _spec.WEIGHT_KEYS):
            out["weights"] = {k: w[k] for k in _spec.WEIGHT_KEYS}
        return out

    def _remember(self, f):
        cur = self.form()
        for k in ("videoTracks", "deliverBatch", "useWeights", "pc"):
            cur[k] = f[k]
        if f.get("top") is not None:
            cur["top"] = f["top"]
        if f.get("weights"):
            cur["weights"] = f["weights"]
        _fsio.write_json(self.form_path, cur, indent=None)

    # ------------------------------------------------------------ 送る
    def peek(self, url):
        """URL を貼ったとき: 配信の id・題・チャンネル名と配信者の推し(A-7)-> {"videoId", "title", "channel", "streamer", "hex"}"""
        vid = _yturl.parse_video_id(url)
        if not vid:
            raise FormError("YouTube の配信の URL を貼ってください")
        with self._lock:
            got = self._peek.get(vid)
        if got is None:
            meta = self.fetch(vid)
            hit = _colors.from_channel(meta["channel"]) if meta["channel"] else None
            got = {"videoId": vid, "title": meta["title"], "channel": meta["channel"], "streamer": hit["name"] if hit else "",
                   "hex": hit["hex"] if hit else None}
            with self._lock:
                self._peek[vid] = got
        return dict(got)

    def check_form(self, body):
        """送る欄 -> 整えた欄(上の説明)。違えば FormError"""
        vid = _yturl.parse_video_id(body.get("url"))
        if not vid:
            raise FormError("YouTube の配信の URL を貼ってください")
        try:
            ranges = _spec.clean_ranges(body.get("ranges"))
        except ValueError as e:
            raise FormError(str(e))
        top = None if ranges else body.get("top")
        if not ranges and not _int_in(top, 1, 30):
            raise FormError("本数は 1〜30 にしてください")
        streamer = body.get("streamer")
        streamer = streamer.strip()[:_colors.NAME_MAX] if isinstance(streamer, str) else ""
        people = [p.strip()[:_order.PEOPLE_NAME_MAX] for p in body.get("people") or [] if isinstance(p, str) and p.strip()][:PEOPLE_MAX]
        vt = body.get("videoTracks", 1)
        if not _int_in(vt, 1, 5):
            raise FormError("映像トラックの数は 1〜5 にしてください")
        batch = body.get("deliverBatch", 5)
        if batch not in BATCHES:
            raise FormError("届け方が正しくありません")
        use_w = body.get("useWeights") is True and not ranges
        w = body.get("weights") if use_w else None
        if use_w and not (isinstance(w, dict) and all(_int_in(w.get(k), 0, 3) for k in _spec.WEIGHT_KEYS)):
            raise FormError("重みは 0〜3 にしてください")
        pc = body.get("pc", "this")
        if pc not in PCS:
            raise FormError("処理する PC が正しくありません")
        return {"url": str(body.get("url"))[:300], "videoId": vid, "ranges": ranges, "top": top, "streamer": streamer, "people": people,
                "videoTracks": vt, "deliverBatch": batch, "useWeights": body.get("useWeights") is True,
                "weights": {k: w[k] for k in _spec.WEIGHT_KEYS} if w else None,
                "title": str(body.get("title") or "")[:120], "channel": str(body.get("channel") or "")[:100], "pc": pc}

    def order(self, f, rid):
        """整えた欄 -> (封筒, 束の差分)(flow/order.py の 1 か所 + 人の名前)"""
        env, diff = _order.order("url", video_id=f["videoId"], title=f["title"] or f["videoId"], fresh={"title": f["title"], "channel": f["channel"]},
                                 upto="pack", top=len(f["ranges"]) if f["ranges"] else f["top"], ranges=f["ranges"] or None,
                                 weights=f["weights"], video_tracks=f["videoTracks"], streamer=f["streamer"], repack=True, request_id=rid)
        names = ([f["streamer"]] if f["streamer"] else []) + [p for p in f["people"] if p != f["streamer"]]
        people = [{"name": n} for n in dict.fromkeys(names)]
        if len(people) > 1 and _spec.key_ok("hints", "people", people):
            diff.setdefault("hints", {})["people"] = people
        return env, diff

    def _need_key(self):
        if self.sync is None or not self.sync.has_key():
            raise FormError("Dropbox の鍵が無いので、ユーザーの PC には頼めません(「詳しく」の処理する PC を「この PC」にしてください)")

    def send(self, body):
        """[送る] -> 受信箱の行(送った)。② が断れば FormError(理由)。処理する PC がユーザーの PC なら同期が Dropbox へ上げる(② は使わない)"""
        f = self.check_form(body)
        source = {"url": f["url"], "videoId": f["videoId"], "title": f["title"], "channel": f["channel"]}
        if f["pc"] == "user":
            self._need_key()
            row = self.inbox.add(_deliver.request_id(self.clock()), f, source, pc="user")
            self._remember(f)
            self.sync.kick()
            return row
        eng = self.engine_fn()
        if eng is None:
            raise FormError("準備中です。少し待ってから、もう一度押してください")
        rid = _deliver.request_id(self.clock())
        env, diff = self.order(f, rid)
        row = self.inbox.add(rid, f, source, run_id=env["id"])
        try:
            eng.queue.submit(env, diff)
        except ValueError as e:
            with self.inbox.lock:
                self.inbox.rows.remove(self.inbox.row(rid))
                self.inbox._save()
            raise FormError(str(e))
        self._remember(f)
        return row

    def retry(self, rid):
        """失敗の行の [もう一度送る](同じ欄で。済んだ段は ② が飛ばす)"""
        eng = self.engine_fn()
        r = self.inbox.row(rid)
        if r is None or r["state"] != "failed" or not r.get("form"):
            raise FormError("もう一度送れる行ではありません")
        if r.get("pc") == "user":   # ユーザーの PC に頼んだ行は、同じ id の依頼を上げ直す
            self._need_key()
            row = self.inbox.resent(rid, None)
            self.sync.kick()
            return row
        if eng is None:
            raise FormError("もう一度送れる行ではありません")
        env, diff = self.order(r["form"], rid)
        eng.queue.submit(env, diff)
        return self.inbox.resent(rid, env["id"])

    def local(self, rid):
        """[この PC でやり直す](A-2): ユーザーの PC の受付が 1 時間読まない依頼を、直下から消してから同じ欄でこの PC の ② へ"""
        eng = self.engine_fn()
        r = self.inbox.row(rid)
        if r is None or r.get("pc") != "user" or not r.get("form"):
            raise FormError("この PC でやり直せる行ではありません")
        if eng is None:
            raise FormError("準備中です。少し待ってから、もう一度押してください")
        if self.sync is None:
            raise FormError("Dropbox の鍵が無いので、ユーザーの PC への依頼を取り消せません")
        try:
            gone = self.sync.withdraw(rid)
        except Exception as e:   # 鍵が無い・つながらない = 二重に作らないよう、取り消せるまでやり直さない
            raise FormError("ユーザーの PC への依頼を取り消せませんでした(%s)。少し待ってから、もう一度押してください" % e)
        if not gone:
            raise FormError("ユーザーの PC がちょうど受け付けました。このまま届くのを待ってください")
        env, diff = self.order(r["form"], rid)
        row = self.inbox.to_local(rid, env["id"])
        try:
            eng.queue.submit(env, diff)
        except ValueError as e:
            self.inbox.finished(env["id"], "error", str(e), [], None)
            raise FormError(str(e))
        return row

    def cancel(self, rid):
        """送った・作っている行を止める(② の取り消し。行は「失敗(止めました)」になる)"""
        eng = self.engine_fn()
        r = self.inbox.row(rid)
        if r is not None and r.get("pc") == "user":
            raise FormError("ユーザーの PC に頼んだ依頼は、ここから止められません")
        if eng is None or r is None or r["state"] not in ("sent", "making"):
            raise FormError("止められる行ではありません")
        return eng.queue.cancel(r["runId"])

    # ------------------------------------------------------------ 受信箱
    def view(self):
        eng = self.engine_fn()
        st, flow = (eng.status_map() if eng else ({}, None))
        rows = self.inbox.view(status_of=lambda run_id: _public_run(st.get(run_id)))
        for r in rows:
            run = r.get("run")
            if r["state"] == "sent" and run and run.get("state") == "running":
                r["state"] = "making"
        return {"rows": rows, "form": self.form(), "saveDir": self.places["save"](), "blocked": (flow or {}).get("blocked"),
                "ready": eng is not None}


def _public_run(r):
    if not r:
        return None
    return {k: r.get(k) for k in ("state", "stateLabel", "message", "step", "steps", "startedAt")}
