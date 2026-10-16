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
F2-6(送る欄を広げる):
    source         "url"(配信の URL)/ "file"(動画ファイル。fileId = [ファイルを選ぶ] で玄関が覚えた id。画面からパスは受けない)
    kind           URL のとき "live" なら ライブ(peek_live が配信中・配信前と答えた)。区間は使わない・本数は 1 録画の自動の採用の上限
    live           ライブの 6 つの設定 {sens, perHour, length, waitMin, pad, afterStream}(前回の値 = form.json の live。検査は friendapp/live.check_settings)
    動画ファイル: 題 = ファイル名・配信者の推しは名前の頭の【名前】から(A-7 の仮)・区間・本数・重みは使わない(② の動画ファイルの実行は 1 本 = 1 パック)。
    この PC では一時保管の <作業>/依頼/<日付>_<題>_<id6>/ へ写してから ② へ(7-2。元の動画は読むだけ)・ユーザーの PC へは同期が動画を上げてから依頼の JSON
カット(A-8)は束の既定のまま(しない)。前回の値は <玄関>/form.json。
ユーザーの PC に頼む行は、同期(friendapp/sync.py。api.sync)が依頼の JSON を Dropbox の直下へ上げる。受付が 1 時間読まなければ [この PC でやり直す](local)。
"""
import datetime
import json
import os
import re
import shutil
import threading
import time
import urllib.error
import urllib.parse
import urllib.request
import uuid

from flow import deliver as _deliver, order as _order, placement as _placement, spec as _spec
from ytt import colors as _colors, fsio as _fsio, tools as _tools, yturl as _yturl

from . import inbox as _inbox, live as _live

FORM_NAME = "form.json"
FORM_DEFAULTS = {"top": 10, "videoTracks": 1, "deliverBatch": 5, "useWeights": False, "weights": {"wAudio": 1, "wChat": 1, "wComments": 1},
                 "pc": "this", "live": dict(_live.SETTINGS_DEFAULT)}
BATCHES = (1, 5)
PCS = ("this", "user")
PEOPLE_MAX = 6
OEMBED = "https://www.youtube.com/oembed?format=json&url="
PEEK_TIMEOUT = 8
LIVE_PEEK_CACHE = 60                # 配信中か調べた結果を覚える秒(配信前 → 配信中と変わるので短く)
LIVE_STATES = ("is_live", "is_upcoming")
FILES_MAX = 20                      # 覚えておく選んだファイルの数
VIDEO_TYPES = tuple(k for k, v in _tools.MEDIA_TYPES.items() if v.startswith("video/"))
NAME_PREFIX_RE = re.compile(r"^【([^】]{1,60})】")   # 動画の名前の頭の【配信者】(手で送るときの読み方 = A-7 の仮)
COPY_CHUNK = 8 * 1024 * 1024
COPY_ROOM = 512 * 1024 * 1024       # 写すときに残す空き


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


def probe_live(url):
    """配信中・配信前か(② の flow/livesession.probe_live = yt-dlp の live_status。読むのは呼んだときだけ = 画面を先に出す)"""
    from flow import livesession
    return livesession.probe_live(url)


def guess_streamer(name, entries=None):
    """動画の名前の頭の【名前】-> 名簿の 1 人 {"name", "hex"} か None(A-7 の仮: 手で送るときの読み方を流用。合わなければ推さない)"""
    m = NAME_PREFIX_RE.match(str(name or "").strip())
    if not m:
        return None
    hit = _colors.lookup(m.group(1).strip(), entries)["match"]
    return {"name": hit["name"], "hex": hit["hex"]} if hit else None


class Api:
    """玄関の口(server.py の Handler が呼ぶ)。engine = friendapp.engine.Engine(準備中は None)。
    fetch = oEmbed・probe = 配信中か調べる(テストは偽物)"""

    def __init__(self, places, inbox, engine_fn, fetch=oembed, clock=time.time, probe=probe_live):
        self.places, self.inbox, self.engine_fn = places, inbox, engine_fn
        self.fetch, self.clock, self.probe = fetch, clock, probe
        self.form_path = os.path.join(places["friend"], FORM_NAME)
        self._peek = {}
        self._live_peek = {}
        self._files = {}                 # [ファイルを選ぶ] で選んだ動画 {id: {path, name, size}}(パスは画面に出さない)
        self._copies = {}                # 写している動画 {依頼 id: [写した, 全部]}
        self._lock = threading.Lock()
        self.stopping = lambda: False    # 玄関が終わる途中か(写すのを止める。玄関が入れる)
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
        out["live"] = _live.clean_settings(d.get("live"))   # ライブの 6 つの設定(A-5。前回の値)
        return out

    def _remember(self, f):
        cur = self.form()
        for k in ("videoTracks", "deliverBatch", "pc"):
            cur[k] = f[k]
        if f["kind"] == "url":   # 重みは URL の欄だけ(動画ファイル・ライブでは出さない)
            cur["useWeights"] = f["useWeights"]
        if f.get("top") is not None:
            cur["top"] = f["top"]
        if f.get("weights"):
            cur["weights"] = f["weights"]
        if f.get("live"):
            cur["live"] = f["live"]
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

    def peek_live(self, url):
        """URL を貼ったとき: 配信中・配信前か(A-5。yt-dlp の live_status = ② の probe_live。数秒かかる)-> {"videoId", "status", "live", "message"}。
        live = 配信中・配信前(送る欄の下に 6 つの設定を出す)。post_live = 終わった直後(アーカイブがまだ見られない = 送れない)"""
        vid = _yturl.parse_video_id(url)
        if not vid:
            raise FormError("YouTube の配信の URL を貼ってください")
        now = self.clock()
        with self._lock:
            hit = self._live_peek.get(vid)
        if hit is None or now - hit[0] > LIVE_PEEK_CACHE:
            try:
                info = self.probe(_yturl.watch_url(vid)) or {}
            except Exception as e:   # 調べる部品の不具合でも送る欄は使える(普通の URL として)
                info = {"status": "unknown", "message": "配信中か調べられませんでした(%s)" % e.__class__.__name__}
            st = info.get("status") if isinstance(info.get("status"), str) else "unknown"
            msg = str(info.get("message") or "")[:200]
            if st == "post_live":
                msg = "配信が終わったばかりで、アーカイブがまだ見られません。見られるようになってから送ってください"
            hit = (now, {"videoId": vid, "status": st, "live": st in LIVE_STATES, "message": msg})
            with self._lock:
                self._live_peek[vid] = hit
        return dict(hit[1])

    def remember_file(self, path):
        """[ファイルを選ぶ] で選んだ動画を覚える -> {"id", "name", "size", "title", "streamer", "hex"}(パスは返さない)。動画でなければ FormError"""
        if not isinstance(path, str) or not os.path.isabs(path) or not os.path.isfile(path):
            raise FormError("動画ファイルが見つかりません")
        name = os.path.basename(path)
        if os.path.splitext(name)[1].lower() not in VIDEO_TYPES:
            raise FormError("動画ファイル(%s)を選んでください" % " ".join(sorted(VIDEO_TYPES)))
        size = os.path.getsize(path)
        fid = uuid.uuid4().hex[:12]
        with self._lock:
            self._files[fid] = {"path": path, "name": name[:200], "size": size}
            while len(self._files) > FILES_MAX:
                self._files.pop(next(iter(self._files)))
        who = guess_streamer(name)
        return {"id": fid, "name": name[:200], "size": size, "title": os.path.splitext(name)[0][:120],
                "streamer": who["name"] if who else "", "hex": who["hex"] if who else None}

    def check_form(self, body):
        """送る欄 -> 整えた欄(上の説明)。違えば FormError"""
        source = body.get("source", "url")
        if source not in ("url", "file"):
            raise FormError("送る物が正しくありません")
        vid, picked, live = None, None, None
        if source == "file":
            with self._lock:
                picked = self._files.get(str(body.get("fileId") or ""))
            if picked is None or not os.path.isfile(picked["path"]):
                raise FormError("動画ファイルを選び直してください([ファイルを選ぶ])")
            kind = "file"
        else:
            vid = _yturl.parse_video_id(body.get("url"))
            if not vid:
                raise FormError("YouTube の配信の URL を貼ってください")
            kind = "live" if body.get("kind") == "live" else "url"
        try:
            ranges = _spec.clean_ranges(body.get("ranges")) if kind == "url" else []   # 区間は URL だけ(ライブ・動画ファイルは使わない)
        except ValueError as e:
            raise FormError(str(e))
        top = None if ranges or kind == "file" else body.get("top")
        if kind != "file" and not ranges and not _int_in(top, 1, 30):
            raise FormError("本数は 1〜30 にしてください")
        if kind == "live":
            try:
                live = _live.check_settings(body.get("live"))
            except ValueError as e:
                raise FormError(str(e))
        streamer = body.get("streamer")
        streamer = streamer.strip()[:_colors.NAME_MAX] if isinstance(streamer, str) else ""
        people = [p.strip()[:_order.PEOPLE_NAME_MAX] for p in body.get("people") or [] if isinstance(p, str) and p.strip()][:PEOPLE_MAX]
        vt = body.get("videoTracks", 1)
        if not _int_in(vt, 1, 5):
            raise FormError("映像トラックの数は 1〜5 にしてください")
        batch = body.get("deliverBatch", 5)
        if batch not in BATCHES:
            raise FormError("届け方が正しくありません")
        use_w = body.get("useWeights") is True and not ranges and kind == "url"
        w = body.get("weights") if use_w else None
        if use_w and not (isinstance(w, dict) and all(_int_in(w.get(k), 0, 3) for k in _spec.WEIGHT_KEYS)):
            raise FormError("重みは 0〜3 にしてください")
        pc = body.get("pc", "this")
        if pc not in PCS:
            raise FormError("処理する PC が正しくありません")
        f = {"kind": kind, "url": str(body.get("url"))[:300] if vid else "", "videoId": vid, "ranges": ranges, "top": top, "streamer": streamer,
             "people": people, "videoTracks": vt, "deliverBatch": batch, "useWeights": use_w,
             "weights": {k: w[k] for k in _spec.WEIGHT_KEYS} if w else None,
             "title": str(body.get("title") or "")[:120], "channel": str(body.get("channel") or "")[:100], "pc": pc}
        if live:
            f["live"] = live
        if picked:
            f.update(file=dict(picked), title=os.path.splitext(picked["name"])[0][:120], channel="")
        return f

    def _people(self, f):
        names = ([f["streamer"]] if f["streamer"] else []) + [p for p in f["people"] if p != f["streamer"]]
        people = [{"name": n} for n in dict.fromkeys(names)]
        return people if len(people) > 1 and _spec.key_ok("hints", "people", people) else None

    def order(self, f, rid):
        """整えた欄 -> (封筒, 束の差分)(flow/order.py の 1 か所 + 人の名前)。kind ごと(url・file・live)"""
        kind = f.get("kind") or "url"
        if kind == "live":   # ライブ: 封筒 kind live + 依頼の束(感度・枠・待ち・余白・配信後の追加・上限 = 本数。長さは束に入れない = engine が行の欄から)
            from flow import livesession   # 読むのは送るときだけ(画面を先に出す)
            env, _diff = _order.order("live", video_id=f["videoId"], title=f["title"] or f["videoId"], request_id=rid, batch=f["deliverBatch"])
            ctx = {"settings": f["live"], "videoTracks": f["videoTracks"], "streamer": f["streamer"]}
            bundle = livesession.request_bundle(ctx, None, top=f["top"])
            people = self._people(f)
            if people:   # 名前と色だけ(人数は入れない = 話者分離は友人の PC の ② にまだ無い。URL の欄と同じ)。切り抜きの実行は録画の束を土台にする
                bundle["hints"]["people"] = people
            return env, bundle
        if kind == "file":   # 動画ファイル: 一時保管の写し(form.file.copy)を 30fps にそろえてから(写しだけ置き換える)パックまで
            env, diff = _order.order("file", path=f["file"].get("copy") or f["file"]["path"], title=f["title"] or f["file"]["name"], normalize=True,
                                     upto="pack", video_tracks=f["videoTracks"], streamer=f["streamer"], repack=True, request_id=rid)
        else:
            env, diff = _order.order("url", video_id=f["videoId"], title=f["title"] or f["videoId"], fresh={"title": f["title"], "channel": f["channel"]},
                                     upto="pack", top=len(f["ranges"]) if f["ranges"] else f["top"], ranges=f["ranges"] or None,
                                     weights=f["weights"], video_tracks=f["videoTracks"], streamer=f["streamer"], repack=True, request_id=rid)
        people = self._people(f)
        if people:
            diff.setdefault("hints", {})["people"] = people
        return env, diff

    def _need_key(self):
        if self.sync is None or not self.sync.has_key():
            raise FormError("Dropbox の鍵が無いので、ユーザーの PC には頼めません(「詳しく」の処理する PC を「この PC」にしてください)")

    @staticmethod
    def _source(f):
        if f["kind"] == "file":
            return {"url": "", "videoId": "", "title": f["title"], "channel": "", "fileName": f["file"]["name"], "fileSize": f["file"]["size"]}
        return {"url": f["url"], "videoId": f["videoId"], "title": f["title"], "channel": f["channel"]}

    def send(self, body):
        """[送る] -> 受信箱の行(送った)。② が断れば FormError(理由)。処理する PC がユーザーの PC なら同期が Dropbox へ上げる(② は使わない)"""
        f = self.check_form(body)
        if f["pc"] == "user":
            self._need_key()
            row = self.inbox.add(_deliver.request_id(self.clock()), f, self._source(f), pc="user", kind=f["kind"])
            self._remember(f)
            self.sync.kick()
            return row
        eng = self.engine_fn()
        if eng is None:
            raise FormError("準備中です。少し待ってから、もう一度押してください")
        rid = _deliver.request_id(self.clock())
        row = self.inbox.add(rid, f, self._source(f), kind=f["kind"])
        try:
            row = self._submit_this(eng, row)
        except FormError:
            self.inbox.drop(rid)
            raise
        self._remember(f)
        return row

    def _submit_this(self, eng, row):
        """この PC の ② へ(kind ごと)-> 行。断られたら FormError(行は呼ぶ側が始末する)"""
        f, rid = row["form"], row["id"]
        if f.get("kind") == "file":   # 写すのは裏の糸(大きな動画でも画面を待たせない)。写し終えたら ② へ
            self._start_copy(rid)
            return self.inbox.row(rid)
        env, diff = self.order(f, rid)
        if f.get("kind") == "live":
            if getattr(eng, "live", None) is None:
                raise FormError("この PC ではライブを録画できません(録画の部品がありません)")
            try:
                out = eng.queue.submit(env, diff) or {}
            except ValueError as e:   # 配信中でなかった・録画を始められない・空き容量 など(LiveError も ValueError)
                raise FormError(str(e))
            return self.inbox.live_started(rid, out.get("recorder"), out.get("recording"), out.get("existing"))
        self.inbox.set_run(rid, env["id"])
        try:
            eng.queue.submit(env, diff)
        except ValueError as e:
            raise FormError(str(e))
        return self.inbox.row(rid)

    # ------------------------------------------------------------ 動画ファイルを写す(この PC。7-2)
    def copying(self):
        with self._lock:
            return bool(self._copies)

    def copy_progress(self, rid):
        with self._lock:
            c = self._copies.get(rid)
            return {"done": c[0], "total": c[1]} if c else None

    def _start_copy(self, rid):
        with self._lock:
            if rid in self._copies:
                return
            self._copies[rid] = [0, 0]
        threading.Thread(target=self._copy_job, args=(rid,), name="friend-copy", daemon=True).start()

    def _copy_job(self, rid):
        try:
            self._copy_and_submit(rid)
        except FormError as e:
            self.inbox.fail(rid, str(e))
        except Exception as e:   # noqa: BLE001  (写せない・② が断った = 行を失敗に。[もう一度送る] で写し直す)
            self.inbox.fail(rid, "動画を送れませんでした(%s)" % (str(e)[:160] or e.__class__.__name__))
        finally:
            with self._lock:
                self._copies.pop(rid, None)

    def _copy_and_submit(self, rid):
        r = self.inbox.row(rid)
        if r is None:
            return
        f = json.loads(json.dumps(r["form"]))
        fi = f["file"]
        dest = fi.get("copy")
        if not (dest and os.path.isfile(dest) and os.path.getsize(dest) > 0):
            dest = self._copy_video(rid, f["title"], fi["path"])
        fi["copy"] = dest
        _placement.ensure_case({"kind": "file", "path": dest}, channel=f.get("streamer") or "", root=os.path.dirname(dest), request_id=rid)
        if self.stopping():
            return   # 終わる途中 = 行は「送った」のまま(次に開いたとき失敗の行 = [もう一度送る] で写しを使う)
        eng = self.engine_fn()
        if eng is None:
            raise FormError("処理の部品が止まっています。アプリを開き直してから [もう一度送る] を押してください")
        env, diff = self.order(f, rid)
        self.inbox.set_run(rid, env["id"], copy=dest)
        try:
            eng.queue.submit(env, diff)
        except ValueError as e:
            raise FormError(str(e))

    def _copy_video(self, rid, title, src):
        """元の動画を一時保管の <作業>/依頼/<日付>_<題>_<id6>/ へ写す(元は読むだけ)-> 写しのパス"""
        if not os.path.isfile(src):
            raise FormError("動画ファイルが見つかりません(移動・削除した可能性があります)。選び直して送ってください")
        cases = self.places["cases"]
        day = datetime.date.fromtimestamp(self.clock()).isoformat()
        folder = _placement.find_request_dir(rid, cases) or _placement.request_root(day, title, rid, out_dir=cases) or os.path.join(cases, "依頼", rid)
        os.makedirs(folder, exist_ok=True)
        size = os.path.getsize(src)
        try:
            free = shutil.disk_usage(folder).free
        except OSError:
            free = None
        if free is not None and free < size + COPY_ROOM:
            raise FormError("一時保管の空きが足りません(あと %d MB ほど空けてから [もう一度送る])" % ((size + COPY_ROOM - free) // (1024 * 1024) + 1))
        stem, ext = os.path.splitext(_inbox.BAD_NAME.sub("_", os.path.basename(src)))
        dest = os.path.join(folder, stem + ext)
        while os.path.exists(dest):
            dest = os.path.join(folder, "%s-%s%s" % (stem, uuid.uuid4().hex[:4], ext))
        tmp = dest + ".copying"
        with self._lock:
            self._copies[rid] = [0, size]
        try:
            with open(src, "rb") as a, open(tmp, "wb") as b:
                done = 0
                while True:
                    if self.stopping():
                        raise FormError("アプリを閉じたので写すのを止めました。[もう一度送る] で写し直します")
                    buf = a.read(COPY_CHUNK)
                    if not buf:
                        break
                    b.write(buf)
                    done += len(buf)
                    with self._lock:
                        self._copies[rid] = [done, size]
            os.replace(tmp, dest)
        except BaseException:
            _fsio.unlink_quiet(tmp)
            raise
        return dest

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
        self.inbox.resent(rid, None)
        try:
            return self._submit_this(eng, self.inbox.row(rid))
        except FormError as e:
            self.inbox.fail(rid, str(e))
            raise

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
        row = self.inbox.to_local(rid, None)
        try:
            return self._submit_this(eng, row)
        except FormError as e:
            self.inbox.fail(rid, str(e))
            raise

    def cancel(self, rid):
        """送った・作っている行を止める(② の取り消し。行は「失敗(止めました)」になる)。録画中のライブの行は録画を止める(そのあとの切り抜きは続く)"""
        eng = self.engine_fn()
        r = self.inbox.row(rid)
        if r is not None and r.get("pc") == "user":
            raise FormError("ユーザーの PC に頼んだ依頼は、ここから止められません")
        if eng is not None and r is not None and r["state"] == "recording":
            lv = r.get("live") or {}
            if getattr(eng, "live", None) is None:
                raise FormError("録画を止められませんでした(録画の部品がありません)")
            try:
                eng.live.stop_recording(lv.get("recorder"), lv.get("recording"))
            except ValueError as e:
                raise FormError(str(e))
            return {"id": rid, "state": "stopped"}
        if eng is None or r is None or r["state"] not in ("sent", "making") or not r.get("runId"):
            raise FormError("止められる行ではありません")
        return eng.queue.cancel(r["runId"])

    # ------------------------------------------------------------ 受信箱
    def view(self):
        eng = self.engine_fn()
        st, flow = (eng.status_map() if eng else ({}, None))
        rows = self.inbox.view(status_of=lambda run_id: _public_run(st.get(run_id)))
        sync = self.sync
        for r in rows:
            run = r.get("run")
            if r["state"] == "sent" and run and run.get("state") == "running":
                r["state"] = "making"
            if r["state"] == "sent" and r.get("kind") == "file":   # 動画を写している(この PC)・Dropbox へ上げている(ユーザーの PC)の進み具合
                prog = self.copy_progress(r["id"]) if r.get("pc") != "user" else (sync.upload_progress(r["id"]) if sync is not None else None)
                if prog:
                    r["progress"] = prog
        return {"rows": rows, "form": self.form(), "saveDir": self.places["save"](), "blocked": (flow or {}).get("blocked"),
                "ready": eng is not None}


def _public_run(r):
    if not r:
        return None
    return {k: r.get(k) for k in ("state", "stateLabel", "message", "step", "steps", "startedAt")}
