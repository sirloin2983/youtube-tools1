# -*- coding: utf-8 -*-
"""友人の玄関の Dropbox の同期(F2-3。notes:plan/f1-friend-requirements.md の A-2・5 章・8b 章、docs/spec/friend.md の 2-14〜2-17・5-1)。

玄関の裏の糸で数分ごと(EVERY 秒)と、起動の直後・画面の操作のあと(kick)に 1 回ずつ回す。② = flow は Dropbox を知らない(ここが玄関の中で全部持つ)。
鍵は <home>/config.json(今の C# の送るアプリと同じ探し方・形 = friendapp/dropbox.py)。無ければ何もしない(画面に小さく知らせる)。
1 回の中身(1 つの失敗でほかを止めない。Dropbox の名前は全部検査してから使い、手元のパスには Dropbox の名前を入れない):
  1. ユーザーの PC に頼む(A-2): 受信箱のユーザーの PC の行の依頼の JSON(5-1 の形 = request_doc。url・video・live = F2-6)を直下 /<依頼 id>.request.json へ上げる。
     動画ファイルは先に動画を直下 /<依頼 id>__<元の名前> へ(進み具合 = upload_progress)。
     上げた依頼が直下から消えたら「受け付けられた」(行は「作っている」)。1 時間残っていれば画面に [この PC でやり直す](withdraw で直下から消す)
  2. 届け方(D-SEND 2-4): 送る欄の deliverBatch が前回上げた値と違えば /設定/届け方.json を置き換えて上げる(C# の UploadDeliverPrefs と同じ形)
  3. /出力/ の取り込み: 組(.group.json + まとめ動画 + 1 本ずつの zip)・1 本(zip + 同じ名前の .preview.mp4・.meta.json の origin)・.失敗.txt を
     受信箱の行へ(依頼 id の行か、無ければ新しい行)。まとめ動画は先に取って見られるように。zip は [受け取る] のときだけ取り(大きさと
     content_hash を確かめ)保存先へ展開(zip slip を断る)。組の全部を決めたら /出力/ の zip・まとめ動画・.group.json・.meta.json を消す
  4. 送り返し: <data>/app/outbox の zip と .verdict.json を /送り返し/ へ上げ、上がった物は outbox から消す(失敗は次の回・3 日上がらなければ消す = 6 章)
  5. 学習の束: /学習/latest.json が新しければ /学習/<版>/ を sha256 を確かめて <data>/learning/<版>/ へ・machine の learningDir を向ける・直近 3 版
     (C# の FetchLearning・ApplyLearning と同じ。束を作る側の PC = places.is_maker_data では取らない)
  6. 更新(F2-4 の起動役との約束): 起動役から動いているとき(YTT_FRIEND_LAUNCHER=1)だけ、/更新/latest.json が今の版より新しければ zip を取り
     SHA-256 を確かめ、src/ と python/ を <home>/app-<版>.tmp/ に展開 → src/friendapp/server.py と python/python.exe があれば <home>/app-<版>/ へ
"""
import datetime
import hashlib
import json
import os
import re
import shutil
import threading
import time
import zipfile

from flow import learning as _learning, machine as _machine
from ytt import fsio, version as _version

from . import dropbox as _dropbox, inbox as _inbox, places as _places

EVERY = 180                        # 見回りの間隔(秒。数分ごと)
OUT = "/出力"
RETURNS = "/送り返し"
LEARNING = "/学習"
UPDATES = "/更新"
DELIVER_PREFS = "/設定/届け方.json"
REQ_SUFFIX = ".request.json"
FAIL_SUFFIX, PREVIEW_SUFFIX, GROUP_SUFFIX, META_SUFFIX, ZIP_SUFFIX = ".失敗.txt", ".preview.mp4", ".group.json", ".meta.json", ".zip"
KINDS = (("failure", FAIL_SUFFIX), ("preview", PREVIEW_SUFFIX), ("group", GROUP_SUFFIX), ("meta", META_SUFFIX), ("pack", ZIP_SUFFIX))
RID_RE = re.compile(r"^\d{8}-\d{6}-[0-9a-f]{6}$")                     # 依頼 id(C# の RequestId・受付の REQ_ID_RE と同じ)
OUT_NAME_RE = re.compile(r"^(\d{8}-\d{6}-[0-9a-f]{6})__(.+)$")        # 出力の名前 <依頼 id>__<題>(C# の OutputFolder.NameRx)
VERSION_DIR_RE = re.compile(r"^\d{8}-\d{6}-[0-9a-f]{8}$")             # 学習の束の版(C# の SyncPaths.VersionDir)
RETURN_ZIP_RE = re.compile(r"^[0-9A-Za-z_-]{1,64}__[0-9A-Za-z_-]{1,64}\.zip$")                      # SyncPaths.ZipName
VERDICT_NAME_RE = re.compile(r'^[0-9A-Za-z_-]{1,64}__[^\\/:*?"<>|\x00-\x1f]{1,100}\.verdict\.json$')  # SyncPaths.VerdictName
APP_VERSION_RE = re.compile(r"^\d+\.\d+\.\d+$")
UPDATE_FILE_RE = re.compile(r"^RequestSender-\d+\.\d+\.\d+\.zip$")   # dev/build_friend_zip.py の名前(C# の Setup.UpdateFile)
SHA_RE = re.compile(r"^[0-9a-f]{64}$")
BAD_NAME = re.compile(r'[\\/:*?"<>|\x00-\x1f\x7f]')
RESERVED = re.compile(r"^(con|prn|aux|nul|com[0-9]|lpt[0-9])(\..*)?$", re.I)
SMALL_CAP = 64 * 1024              # .group.json・失敗の知らせ・latest.json(C# の GroupTextCap・FailureTextCap)
META_CAP = 16 * 1024
GROUP_WAIT = 600                   # 組の zip がそろわないとき、そろった分だけで取り込むまで待つ秒
SINGLE_WAIT = 1800                 # まとめ動画も印も無い zip を 1 本として取り込むまで待つ秒(組の一覧が後から来るかもしれない)
KEEP_LEARNING = 3
LEARN_PACK = "learning.json"
TOP_MAX = 10                       # 受付の 1 配信の本数の上限(human/friend/intake.TOP_MAX と同じ)
EXTRACT_MAX_FILES = 20000
EXTRACT_MAX_BYTES = 64 * 1024 ** 3
UPDATE_MAX_FILES = 60000
UPDATE_MAX_BYTES = 4 * 1024 ** 3
LAUNCHER_ENV = "YTT_FRIEND_LAUNCHER"
STATE_NAME = "sync.json"
VERSIONS_NAME = "app-versions.json"
NO_KEY = "Dropbox の鍵がありません(自動で届いた物・ユーザーの PC への依頼は使えません)"


class SyncError(Exception):
    """同期の 1 つの段の問題(文はログと画面に出してよい日本語)"""


# ------------------------------------------------------------ 名前・中身の検査(Dropbox から来た物は鍵を知る人なら置ける)
def name_ok(name):
    """Dropbox の 1 つの名前として受け付けるか(区切り・使えない文字・制御文字・前後の空白・. と ~ で始まる・予約名を断る)"""
    return (isinstance(name, str) and 0 < len(name) <= 255 and not BAD_NAME.search(name) and name.strip() == name
            and not name.startswith((".", "~")) and not RESERVED.match(name))


def out_kind(name):
    """出力の名前 -> {"kind", "stem", "rid", "title"} か None(対象外)"""
    if not name_ok(name):
        return None
    for kind, suffix in KINDS:
        if name.lower().endswith(suffix.lower()) and len(name) > len(suffix):
            stem = name[:-len(suffix)]
            m = OUT_NAME_RE.match(stem)
            return {"kind": kind, "stem": stem, "rid": m.group(1) if m else "", "title": m.group(2) if m else stem}
    return None


def clean_text(s, limit=200):
    t = "".join(c for c in str(s or "") if c >= " " and c not in "\x7f  ").strip()
    return t[:limit] + "…" if len(t) > limit else t


def clean_origin(s):
    return s if s in ("request", "auto") else ""


def _plain(s, suffix):
    if not isinstance(s, str) or len(s) <= len(suffix) or not s.lower().endswith(suffix.lower()):
        return ""
    return s if name_ok(s) else ""


def _seconds(v):
    if isinstance(v, bool) or not isinstance(v, (int, float)) or v != v or v < 0 or v > 48 * 3600:
        return None
    return float(v)


def _json_bytes(data):
    try:
        return json.loads(data.decode("utf-8-sig"))
    except (UnicodeDecodeError, ValueError):
        return None


def parse_group(data):
    """.group.json の中身 -> {"title", "range", "preview", "origin", "packs": [{"n", "zip", "title", "seconds"}]} か None(形が違う・本が無い)。
    C# の GroupInfo.Parse と同じ検査(名前は区切りの無い物だけ・数は範囲に・題は制御文字を除いて短く)"""
    d = _json_bytes(data)
    if not isinstance(d, dict) or d.get("v") != 1:
        return None
    g = {"title": clean_text(d.get("title")), "range": clean_text(d.get("range")), "preview": _plain(d.get("preview"), PREVIEW_SUFFIX),
         "origin": clean_origin(d.get("origin")), "packs": []}
    if len(g["range"]) > 20:
        g["range"] = ""
    seen = set()
    for p in d.get("packs") if isinstance(d.get("packs"), list) else []:
        if not isinstance(p, dict):
            continue
        z = _plain(p.get("zip"), ZIP_SUFFIX)
        if not z or z.lower() in seen:
            continue
        seen.add(z.lower())
        n = p.get("n")
        g["packs"].append({"n": n if isinstance(n, int) and not isinstance(n, bool) and 1 <= n <= 1000 else len(g["packs"]) + 1,
                           "zip": z, "title": clean_text(p.get("title")), "seconds": _seconds(p.get("duration"))})
        if len(g["packs"]) >= 100:
            break
    if not g["packs"]:
        return None
    g["packs"].sort(key=lambda x: (x["n"], x["zip"]))
    return g


def parse_meta(data):
    """<zip>.meta.json -> 出どころ request|auto か ""(読めない = 依頼として扱う)"""
    d = _json_bytes(data)
    return clean_origin(d.get("origin")) if isinstance(d, dict) and d.get("v") == 1 else ""


def failure_text(data, truncated):
    """失敗の知らせの本文(BOM を除き、改行をそろえ、長ければ切る)"""
    s = data.decode("utf-8-sig", "replace").replace("\r\n", "\n").replace("\r", "\n").strip()
    s = s[:2000] + ("\n…(長いので途中まで)" if truncated or len(s) > 2000 else "")
    return s or "ユーザーの PC で失敗しました(理由は書かれていません)"


def server_time(s):
    """Dropbox の server_modified("2026-10-01T03:00:00Z")-> 秒(読めなければ 0)"""
    try:
        return datetime.datetime.fromisoformat(str(s).replace("Z", "+00:00")).timestamp()
    except ValueError:
        return 0.0


def safe_rel(rel):
    """束・zip の中の相対パスとして安全か(.. ・絶対・ドライブ・バックスラッシュ・使えない文字を断る。C# の Sync.SafeRel より厳しめ)"""
    if not isinstance(rel, str) or not rel or len(rel) > 400 or "\\" in rel or ":" in rel or rel.startswith("/"):
        return False
    return all(p and p not in (".", "..") and not BAD_NAME.search(p) and not RESERVED.match(p) for p in rel.split("/"))


def safe_join(root, rel):
    """root の中の場所(外へ出る名前は ValueError)"""
    if not safe_rel(rel):
        raise ValueError("zip の中に使えない名前があります: %s" % rel[:120])
    full = os.path.abspath(os.path.join(root, *rel.split("/")))
    if not fsio.is_inside(full, root, strict=True):
        raise ValueError("zip の中に外へ出る名前があります: %s" % rel[:120])
    return full


def local_name(s, limit=100):
    """手元のフォルダの名前(使えない文字は _・終わりの . と空白を除く・予約名は前に _)"""
    n = BAD_NAME.sub("_", str(s or "")).strip().rstrip(". ")[:limit].rstrip(". ")
    return "_" + n if not n or RESERVED.match(n) else n


def sha256_file(path):
    h = hashlib.sha256()
    with open(path, "rb") as f:
        for block in iter(lambda: f.read(1 << 20), b""):
            h.update(block)
    return h.hexdigest()


def version_tuple(v):
    return tuple(int(x) for x in v.split(".")) if isinstance(v, str) and APP_VERSION_RE.match(v) else (0,)


def _copy_member(z, info, path):
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with z.open(info) as src, open(path, "xb") as dst:
        shutil.copyfileobj(src, dst, 1 << 20)


def extract_pack(zip_path, dest_dir, fallback_name):
    """受け取った zip を dest_dir に展開する -> 置いたフォルダ(C# の Receiving.Extract と同じ形)。
    中身が 1 つのフォルダ(<題>_pack)ならそれを直下に・違えば fallback_name のフォルダに入れる。<名前>.extracting に書いてから名前を変える。
    中の名前が外へ出る物・使えない文字・多すぎる・大きすぎる物は ValueError(zip slip を断る)"""
    with zipfile.ZipFile(zip_path) as z:
        infos = z.infolist()
        if len(infos) > EXTRACT_MAX_FILES or sum(i.file_size for i in infos) > EXTRACT_MAX_BYTES:
            raise ValueError("zip の中身が多すぎます")
        names = [i.filename.replace("\\", "/") for i in infos]
        for n in names:
            if n.strip("/") and not safe_rel(n.rstrip("/")):   # 先頭のフォルダを外す前に、全部の名前を確かめる(.. ・絶対・ドライブを断る)
                raise ValueError("zip の中に使えない名前があります: %s" % n[:120])
        tops = {n.split("/", 1)[0] for n in names if n.strip("/")}
        top = next(iter(tops)) if len(tops) == 1 and all("/" in n.strip("/") or n.endswith("/") for n in names if n.strip("/")) else None
        target = _inbox.unique_dest(dest_dir, local_name(top or fallback_name))
        temp = target + ".extracting"
        shutil.rmtree(temp, ignore_errors=True)
        os.makedirs(temp)
        try:
            for info, n in zip(infos, names):
                rel = n[len(top) + 1:] if top else n
                rel = rel.strip("/")
                if not rel:
                    continue
                path = safe_join(temp, rel)
                if info.is_dir():
                    os.makedirs(path, exist_ok=True)
                else:
                    _copy_member(z, info, path)
            os.replace(temp, target)
        except BaseException:
            shutil.rmtree(temp, ignore_errors=True)
            raise
    return target


def install_update(zip_path, home, version):
    """更新の zip の src/ と python/ を <home>/app-<版>.tmp/ に展開し、manifest.json があれば SHA-256 を確かめ、
    src/friendapp/server.py と python/python.exe があれば <home>/app-<版>/ へ名前を変える -> 置いたフォルダ。だめなら ValueError(途中の物は消す)"""
    final = os.path.join(home, "app-" + version)
    tmp = final + ".tmp"
    shutil.rmtree(tmp, ignore_errors=True)
    os.makedirs(tmp)
    try:
        with zipfile.ZipFile(zip_path) as z:
            infos = z.infolist()
            if len(infos) > UPDATE_MAX_FILES or sum(i.file_size for i in infos) > UPDATE_MAX_BYTES:
                raise ValueError("更新の zip の中身が多すぎます")
            manifest = None
            for info in infos:
                n = info.filename.replace("\\", "/")
                if n == "manifest.json":
                    manifest = _json_bytes(z.read(info))
                    continue
                if not n.startswith(("src/", "python/")) or n.endswith("/"):
                    continue
                _copy_member(z, info, safe_join(tmp, n))
        files = manifest.get("files") if isinstance(manifest, dict) and isinstance(manifest.get("files"), dict) else {}
        for rel, want in files.items():
            if not str(rel).startswith(("src/", "python/")):
                continue
            p = safe_join(tmp, rel)
            if not isinstance(want, str) or not os.path.isfile(p) or sha256_file(p) != want.lower():
                raise ValueError("更新の zip の中身が manifest.json と違います: %s" % str(rel)[:120])
        for need in (("src", "friendapp", "server.py"), ("python", "python.exe")):
            if not os.path.isfile(os.path.join(tmp, *need)):
                raise ValueError("更新の zip に %s がありません" % "/".join(need))
        os.replace(tmp, final)
    except BaseException:
        shutil.rmtree(tmp, ignore_errors=True)
        raise
    return final


def _iso(t):
    return datetime.datetime.fromtimestamp(t).astimezone().isoformat(timespec="seconds")


LIVE_KEYS = ("sens", "perHour", "length", "waitMin", "pad", "afterStream")   # 依頼の JSON の live の鍵の順(C# の LiveSettings.JsonPart と同じ)


def request_doc(kind, rid, form, sent_at, files=None):
    """ユーザーの PC に頼む依頼の JSON(5-1。C# の送るアプリの RequestJson と同じ鍵と順 = 依頼の JSON を組むのはここ 1 か所)。
    kind = url(RequestJson.Url)/ video(RequestJson.Video。files = Dropbox の直下に上げた動画の名前)/ live(RequestJson.Live。2-15)。
    form = api.check_form の整えた欄。区間があれば本数は区間の数(A-3)・カットは しない(A-8)・重みは指定したときだけ(URL だけ)"""
    if kind not in ("url", "video", "live"):
        raise ValueError("依頼の種類が正しくありません")
    if kind == "video" and not files:
        raise ValueError("上げた動画の名前がありません")
    names = list(dict.fromkeys(n for n in [form.get("streamer") or ""] + list(form.get("people") or []) if n))
    d = {"v": 1, "kind": kind, "id": rid, "flow": "auto"}
    if kind == "url":
        ranges = form.get("ranges") or []
        top = len(ranges) if ranges else (form.get("top") or 10)
        item = {"url": form["url"], "top": max(1, min(TOP_MAX, int(top)))}
        if ranges:
            item["ranges"] = [{"start": s, "end": e} for s, e in ranges]
        d["items"] = [item]
        if form.get("streamer"):
            d["streamer"] = form["streamer"]
    elif kind == "video":
        d["files"] = [str(n) for n in files]
        d["streamer"] = form.get("streamer") or ""
    else:
        d["url"] = "https://www.youtube.com/watch?v=" + form["videoId"] if form.get("videoId") else form["url"]   # 正規化した URL(C# と同じ)
        d["streamer"] = form.get("streamer") or ""
    if names:
        d["speakers"] = {"count": len(names), "names": names, "people": [{"name": n} for n in names]}
    d["videoTracks"] = form.get("videoTracks") or 1
    d["cut"] = "none"
    w = form.get("weights")
    if w and kind == "url":
        d["weights"] = {"audio": float(w["wAudio"]), "chat": float(w["wChat"]), "comments": float(w["wComments"])}
    if kind == "live":
        s = form.get("live") or {}
        d["live"] = {k: s[k] for k in LIVE_KEYS if k in s}
    d["deliverBatch"] = form.get("deliverBatch") or 5
    d["sentAt"] = _iso(sent_at)
    return d


def upload_name(rid, name):
    """ユーザーの PC へ上げる動画の Dropbox の名前 <依頼 id>__<元の名前>(使えない文字は _。受付の APP_FILE_RE の形)"""
    stem, ext = os.path.splitext(local_name(name, 150))
    return "%s__%s%s" % (rid, stem or "video", ext if ext and not BAD_NAME.search(ext) else "")


class Sync:
    """同期の係(玄関に 1 つ)。places = friendapp/places.setup の値 + save・inbox = 受信箱・form_fn() = 送る欄の前回の値・engine_fn() = ② か None。
    client_factory(config, cancelled) -> Dropbox の口(dropbox.Client と同じ名前の関数を持つ物。テストは偽物)"""

    def __init__(self, places, inbox, form_fn, engine_fn=None, client_factory=None, clock=time.time, log=None, env=None,
                 apply_learning=None, version=None, every=EVERY):
        self.places, self.inbox, self.form_fn = places, inbox, form_fn
        self.engine_fn = engine_fn or (lambda: None)
        self.client_factory = client_factory or (lambda cfg, cancelled: _dropbox.Client(cfg, log=self.log, cancelled=cancelled))
        self.clock, self.log = clock, log or (lambda msg: None)
        self.env = os.environ if env is None else env
        self.apply_learning = apply_learning or self._apply_learning
        self.version = version or _version.VERSION
        self.every = every
        self.state_path = os.path.join(places["friend"], STATE_NAME)
        self.state = fsio.read_json_or(self.state_path, {}, kind=dict)
        self.req_lock = threading.Lock()        # 依頼を上げる・直下から消す(この PC でやり直す)を重ねない
        self._run_lock = threading.Lock()
        self._wake, self._stop = threading.Event(), threading.Event()
        self._client, self._client_cfg = None, None
        self._key_cache = (None, False)
        self._groups = {}
        self.last = {"at": None, "problem": ""}
        self.receiving = 0
        self.uploads = {}                       # 上げている動画 {依頼 id: [上げた, 全部]}(F2-6)

    # ------------------------------------------------------------ 鍵と口
    def config(self):
        return _dropbox.load_config(self.places["home"])

    def has_key(self):
        """鍵があるか(config.json の更新時刻で覚える = 画面の問い合わせごとに読み直さない)"""
        try:
            mt = os.path.getmtime(_dropbox.config_path(self.places["home"]))
        except OSError:
            return False
        if self._key_cache[0] != mt:
            self._key_cache = (mt, self.config() is not None)
        return self._key_cache[1]

    def io(self):
        """Dropbox の口か None(鍵が無い)。同じ鍵なら同じ口(access token を使い回す)"""
        cfg = self.config()
        if cfg is None:
            return None
        if self._client is None or self._client_cfg != cfg:
            self._client, self._client_cfg = self.client_factory(cfg, self._stop.is_set), cfg
        return self._client

    def _save_state(self):
        fsio.write_json(self.state_path, self.state, indent=None)

    # ------------------------------------------------------------ 糸
    def loop(self):
        """裏の糸の本体(起動の直後に 1 回・そのあと every 秒ごとか kick で)"""
        while not self._stop.is_set():
            try:
                self.run_once()
            except _dropbox.Cancelled:
                return
            except Exception as e:   # 同期で玄関を止めない
                self.log("同期: 止まりました %s %s" % (e.__class__.__name__, str(e)[:200]))
            self._wake.wait(self.every)
            self._wake.clear()

    def kick(self):
        self._wake.set()

    def stop(self):
        self._stop.set()
        self._wake.set()

    def busy(self):
        return self.receiving > 0 or bool(self.uploads)

    def status(self):
        """画面へ: {"key": 鍵があるか, "message": 鍵が無いときの文, "at": 最後に回したミリ秒, "problem": 最後の問題, "updated": 入れた新しい版}"""
        up = self.state.get("updated")
        key = self.has_key()
        return {"key": key, "message": "" if key else NO_KEY, "at": self.last["at"], "problem": self.last["problem"],
                "updated": up if version_tuple(up) > version_tuple(self.version) else None}

    def run_once(self):
        """1 回分(鍵が無ければ何もしない)-> 問題の一覧(空 = 全部済んだ)か None(鍵が無い・ほかの回が動いている)"""
        if not self._run_lock.acquire(blocking=False):
            return None
        try:
            io = self.io()
            if io is None:
                return None
            problems = []
            for label, step in (("ユーザーの PC への依頼", self._requests), ("届け方", self._deliver_prefs), ("届いた物", self._intake),
                                ("まとめ動画", self._previews), ("受け取る", self._receive), ("片付け", self._cleanup),
                                ("送り返し", self._returns), ("学習", self._learning), ("更新", self._update)):
                if self._stop.is_set():
                    break
                try:
                    step(io)
                except _dropbox.Cancelled:
                    raise
                except (_dropbox.DropboxError, SyncError, OSError, ValueError, zipfile.BadZipFile) as e:
                    problems.append("%s: %s" % (label, e))
                    self.log("同期の %s: %s %s" % (label, e.__class__.__name__, str(e)[:200]))
            self.last = {"at": int(self.clock() * 1000), "problem": problems[0] if problems else ""}
            return problems
        finally:
            self._run_lock.release()

    # ------------------------------------------------------------ 1. ユーザーの PC に頼む(A-2)
    @staticmethod
    def request_path(rid):
        return "/%s%s" % (rid, REQ_SUFFIX)

    def _requests(self, io):
        for r in self.inbox.remote_rows("pending"):
            with self.req_lock:
                cur = self.inbox.row(r["id"])
                if cur is None or cur.get("pc") != "user" or (cur.get("remote") or {}).get("state") != "pending" or not cur.get("form"):
                    continue
                kind = cur.get("kind") or "url"
                files = None
                if kind == "file":   # 動画ファイル: 先に動画を直下へ <依頼 id>__<元の名前>(大きな動画は 8MB ずつ・進み具合を行に)・最後に依頼の JSON(C# と同じ順)
                    files = self._upload_video(io, cur)
                    if files is None:
                        continue
                doc = request_doc("video" if kind == "file" else kind, r["id"], cur["form"], self.clock(), files=files)
                io.upload_bytes(json.dumps(doc, ensure_ascii=False).encode("utf-8"), self.request_path(r["id"]), overwrite=True)
                self.inbox.remote_mark(r["id"], "uploaded")
                self.log("ユーザーの PC への依頼を上げました: %s" % r["id"])
        for r in self.inbox.remote_rows("uploaded"):
            if io.get_metadata(self.request_path(r["id"])) is None:
                self.inbox.remote_mark(r["id"], "accepted")
                self.log("ユーザーの PC が依頼を受け付けました: %s" % r["id"])

    def _upload_video(self, io, row):
        """ユーザーの PC に頼む動画ファイルを直下へ上げる -> [置かれた名前] か None(動画が無い = 行を失敗に)。
        前の回に上げ終えた同じ大きさの物が直下にあれば上げ直さない。通信の問題は DropboxError(次の回にもう一度)"""
        rid, fi = row["id"], (row["form"].get("file") or {})
        path = fi.get("path")
        if not isinstance(path, str) or not os.path.isfile(path):
            self.inbox.fail(rid, "送る動画ファイルが見つかりません(移動・削除した可能性があります)。選び直して送ってください")
            return None
        size = os.path.getsize(path)
        name = upload_name(rid, fi.get("name") or os.path.basename(path))
        have = io.get_metadata("/" + name)
        if isinstance(have, dict) and have.get("size") == size:
            return [have.get("name") or name]
        self.uploads[rid] = [0, size]
        try:
            placed = io.upload(path, "/" + name, overwrite=True, progress=lambda done: self.uploads.__setitem__(rid, [done, size]))
        finally:
            self.uploads.pop(rid, None)
        self.log("ユーザーの PC へ動画を上げました: %s(%d MB)" % (rid, size // (1024 * 1024)))
        return [placed or name]

    def upload_progress(self, rid):
        """動画を Dropbox へ上げている進み具合 {"done", "total"} か None"""
        got = self.uploads.get(rid)
        return {"done": got[0], "total": got[1]} if got else None

    def withdraw(self, rid):
        """[この PC でやり直す]: 直下の依頼を消す -> True(消した・まだ上げていない)/ False(もう無い = ユーザーの PC が受け付けた)。
        鍵が無い・つながらないときは SyncError・DropboxError(呼ぶ側が断る)"""
        with self.req_lock:
            r = self.inbox.row(rid)
            rem = (r or {}).get("remote") or {}
            if r is None or r.get("pc") != "user":
                raise KeyError(rid)
            if rem.get("state") not in ("pending", "uploaded"):
                return False
            video = r.get("kind") == "file"
            if rem.get("state") == "pending" and not video:
                return True
            io = self.io()
            if io is None:
                raise SyncError(NO_KEY)
            gone = True if rem.get("state") == "pending" else io.delete(self.request_path(rid))
            if gone and video:   # 上げた動画も消す(依頼の JSON の無い動画を、受付が手で置いた動画として流さないように)
                fi = (r.get("form") or {}).get("file") or {}
                io.delete("/" + upload_name(rid, fi.get("name") or "video"))
            return gone

    # ------------------------------------------------------------ 2. 届け方(D-SEND 2-4)
    def _deliver_prefs(self, io):
        batch = (self.form_fn() or {}).get("deliverBatch")
        if not (isinstance(batch, int) and 1 <= batch <= 10) or batch == self.state.get("deliverBatchUploaded"):
            return
        doc = {"v": 1, "deliverBatch": batch, "at": _iso(self.clock())}
        io.upload_bytes(json.dumps(doc, ensure_ascii=False).encode("utf-8"), DELIVER_PREFS, overwrite=True)
        self.state["deliverBatchUploaded"] = batch
        self._save_state()
        self.log("届け方を上げました: %d" % batch)

    # ------------------------------------------------------------ 3. /出力/ の取り込み
    @staticmethod
    def out_path(name):
        return "%s/%s" % (OUT, name)

    def _read(self, io, name, cap):
        got = io.read_small(self.out_path(name), cap)
        return got if got is not None else None

    def _group(self, io, name, rev):
        key = (name, rev)
        if key not in self._groups:
            got = self._read(io, name, SMALL_CAP)
            self._groups[key] = parse_group(got[0]) if got and not got[1] else None
            if self._groups[key] is None:
                self.log("同期: 組の一覧を読めませんでした(形が違う・大きすぎる): %s" % name)
        return self._groups[key]

    def _intake(self, io):
        entries = io.list_folder(OUT)
        if entries is None:
            return
        files = {}
        for e in entries:
            k = out_kind(e.get("name")) if e.get(".tag") == "file" else None
            if k is not None:
                files[e["name"]] = dict(k, entry=e, size=e.get("size") if isinstance(e.get("size"), int) else 0)
        known = self.inbox.known_remote()
        now = self.clock()
        live_groups = {(f, f_["entry"].get("rev")) for f, f_ in files.items() if f_["kind"] == "group"}
        self._groups = {k: v for k, v in self._groups.items() if k in live_groups}
        in_groups = set()
        for name, f in sorted(files.items()):
            if f["kind"] != "group":
                continue
            info = self._group(io, name, f["entry"].get("rev"))
            if info is None:
                continue
            in_groups.update(p["zip"] for p in info["packs"])
            if name in known or not f["rid"]:
                continue
            members = [p for p in info["packs"] if p["zip"] in files and files[p["zip"]]["kind"] == "pack"]
            fresh = [p for p in members if p["zip"] not in known]
            if not fresh or (len(members) < len(info["packs"]) and now - server_time(f["entry"].get("server_modified")) < GROUP_WAIT):
                continue
            pv = info["preview"] if info["preview"] in files else None
            spec = {"group": name, "preview": pv, "previewSize": files[pv]["size"] if pv else None,
                    "packs": [self._pack_item(files[p["zip"]], p["title"], p["seconds"]) for p in fresh]}
            self.inbox.import_remote(f["rid"], info["origin"] or "request", info["title"] or f["title"], [spec])
            known.update(p["zip"] for p in fresh)
            self.log("届いた組を受信箱に入れました: %s(%d 本)" % (name, len(fresh)))
        for name, f in sorted(files.items()):
            if f["kind"] != "pack" or name in known or name in in_groups or not f["rid"]:
                continue
            pv, meta = f["stem"] + PREVIEW_SUFFIX, f["stem"] + META_SUFFIX
            pv, meta = (pv if pv in files else None), (meta if meta in files else None)
            if not pv and not meta and now - server_time(f["entry"].get("server_modified")) < SINGLE_WAIT:
                continue
            got = self._read(io, meta, META_CAP) if meta else None
            origin = (parse_meta(got[0]) if got and not got[1] else "") or "request"
            item = self._pack_item(f, f["title"], None)
            item["meta"] = meta
            self.inbox.import_remote(f["rid"], origin, f["title"], [{"group": None, "preview": pv, "previewSize": files[pv]["size"] if pv else None,
                                                                     "packs": [item]}])
            self.log("届いたパックを受信箱に入れました: %s" % name)
        for name, f in sorted(files.items()):
            if f["kind"] != "failure" or name in known or not f["rid"]:
                continue
            got = self._read(io, name, SMALL_CAP)
            if got is None:
                continue
            self.inbox.remote_failure(f["rid"], f["title"], failure_text(*got), name)
            if io.delete(self.out_path(name)) is not None:
                self.inbox.remote_fail_cleared(f["rid"], name)
            self.log("ユーザーの PC の失敗の知らせを受信箱に入れました: %s" % name)

    @staticmethod
    def _pack_item(f, title, seconds):
        e = f["entry"]
        return {"zip": e["name"], "title": title or f["title"], "seconds": seconds, "size": f["size"], "rev": e.get("rev"),
                "hash": e.get("content_hash"), "meta": None}

    def _previews(self, io):
        folder = os.path.join(self.places["friend"], "previews")
        for rid, n, name, size in self.inbox.preview_queue():
            if not name_ok(name):
                self.inbox.set_preview(rid, n, None)
                continue
            os.makedirs(folder, exist_ok=True)
            dest = os.path.join(folder, "%s-r%d.mp4" % (rid, n))   # 手元の名前に Dropbox の名前を入れない
            if not (os.path.isfile(dest) and size and os.path.getsize(dest) == size):
                part = dest + ".part"
                if not io.download(self.out_path(name), part):
                    self.inbox.set_preview(rid, n, None)
                    continue
                os.replace(part, dest)
            self.inbox.set_preview(rid, n, dest)

    def _free_ok(self, folder, need):
        try:
            return shutil.disk_usage(fsio.existing_parent(folder) or folder).free >= need + 64 * 1024 * 1024
        except (OSError, ValueError):
            return True   # 測れない場所は測らない(C# と同じ)

    def _receive(self, io):
        """[受け取る] を押した Dropbox のパック: 取る → 大きさと content_hash → 保存先へ展開 → 受け取ったに決める。
        通信の問題は押したまま次の回へ(止める)・そのパックだけの問題は理由を出して押す前に戻す"""
        folder = os.path.join(self.places["friend"], "incoming")
        for i, (rid, name, rem) in enumerate(self.inbox.receive_queue()):
            zname, size = rem.get("zip"), rem.get("size") or 0
            if not name_ok(zname):
                self.inbox.remote_keep_failed(rid, name, "名前が正しくないので受け取れません")
                continue
            save = self.places["save"]()
            os.makedirs(save, exist_ok=True)
            if not self._free_ok(save, size * 2):
                self.inbox.remote_keep_failed(rid, name, "保存先の空きが足りません(あと %d MB ほど空けてから、もう一度 [受け取る])" % (size * 2 // (1024 * 1024) + 64))
                continue
            os.makedirs(folder, exist_ok=True)
            part = os.path.join(folder, "%s-%d.zip" % (rid, i))
            self.receiving += 1
            try:
                if not io.download(self.out_path(zname), part, rev=rem.get("rev")):
                    self.inbox.remote_keep_failed(rid, name, "Dropbox にもうありません(ユーザーの PC が消しました)。[要らない] で片付けてください")
                    continue
                got = os.path.getsize(part)
                if (size and got != size) or (rem.get("hash") and _dropbox.content_hash(part) != rem["hash"]):
                    self.inbox.remote_keep_failed(rid, name, "受け取った物が壊れていました。もう一度 [受け取る] を押してください")
                    continue
                try:
                    placed = extract_pack(part, save, _inbox.pack_title(name))
                except (ValueError, zipfile.BadZipFile, OSError) as e:
                    self.inbox.remote_keep_failed(rid, name, "展開できませんでした(%s)" % (str(e)[:120] if isinstance(e, ValueError) else e.__class__.__name__))
                    continue
                self.inbox.remote_kept(rid, name, placed)
                self.log("受け取りました: %s" % zname)
            except _dropbox.DropboxError as e:
                if e.retryable:
                    raise   # つながらない = 押したまま次の回で続ける
                self.inbox.remote_keep_failed(rid, name, str(e))
            finally:
                self.receiving -= 1
                fsio.unlink_quiet(part)

    def _cleanup(self, io):
        for rid, n, names in self.inbox.cleanup_queue():
            for nm in names:
                if name_ok(nm):
                    io.delete(self.out_path(nm))
            self.inbox.remote_cleaned(rid, n)
            self.log("Dropbox の出力から決めた組を消しました: %s の %d 組目" % (rid, n))

    # ------------------------------------------------------------ 4. 送り返し
    def _returns(self, io):
        box = self.places["outbox"]
        if not os.path.isdir(box):
            return
        failed = []
        for name in sorted(os.listdir(box)):
            p = os.path.join(box, name)
            if not os.path.isfile(p) or not (RETURN_ZIP_RE.match(name) or VERDICT_NAME_RE.match(name)):
                continue
            try:
                io.upload(p, "%s/%s" % (RETURNS, name))
                fsio.unlink_quiet(p)
                self.log("送り返しを上げました: %s" % name)
            except _dropbox.DropboxError as e:
                if self.clock() - os.path.getmtime(p) >= _inbox.KEEP_DAYS * _inbox.DAY:   # 3 日上がらなければ消す(6 章)
                    fsio.unlink_quiet(p)
                    self.log("送り返しを 3 日上げられなかったので消しました: %s" % name)
                failed.append("%s(%s)" % (name, e))
        if failed:
            raise SyncError("上げられなかった物 %d 件(次の回でもう一度)" % len(failed))

    # ------------------------------------------------------------ 5. 学習の束
    def learn_root(self):
        return os.path.join(self.places["data"], "learning")

    def _learning(self, io):
        if _places.is_maker_data(self.places["data"]):   # 自分の束を自分の ② に向けない(二重の守りの片方。C# の Sync.MakerPc と同じ)
            return
        root = self.learn_root()
        v = fetch_learning(io, root, self.log)
        if v is None:
            return
        rec = os.path.join(root, "current.json")
        cur = fsio.read_json_or(rec, {}, kind=dict)
        if cur.get("version") == v and cur.get("applied") is True:
            return
        ok = bool(self.apply_learning(os.path.join(root, v)))
        fsio.write_json(rec, {"version": v, "applied": ok})
        self.log("学習の束 %s を向けました" % v)

    def _apply_learning(self, ld):
        _machine.save({"learningDir": ld})
        _learning.apply_places(_learning.learning_dir())
        eng = self.engine_fn()
        if eng is not None and hasattr(eng, "reload_learning"):
            eng.reload_learning()
        return True

    # ------------------------------------------------------------ 6. 更新(F2-4 の起動役との約束)
    def _update(self, io):
        if (self.env.get(LAUNCHER_ENV) or "").strip() != "1":
            return
        got = io.read_small(UPDATES + "/latest.json", SMALL_CAP)
        d = _json_bytes(got[0]) if got and not got[1] else None
        if not isinstance(d, dict):
            return
        ver, name, sha = d.get("version"), d.get("file"), str(d.get("sha256") or "").lower()
        if not (isinstance(ver, str) and APP_VERSION_RE.match(ver)) or version_tuple(ver) <= version_tuple(self.version):
            return
        if not (isinstance(name, str) and UPDATE_FILE_RE.match(name)) or not SHA_RE.match(sha):
            raise SyncError("更新の latest.json の形が違います")
        home = self.places["home"]
        bad = fsio.read_json_or(os.path.join(home, VERSIONS_NAME), {}, kind=dict).get("bad") or []
        if os.path.isdir(os.path.join(home, "app-" + ver)) or ver in bad:
            return
        part = os.path.join(home, "app-%s.zip.part" % ver)
        try:
            if not io.download("%s/%s" % (UPDATES, name), part):
                return
            size = d.get("size")
            if (isinstance(size, int) and size > 0 and os.path.getsize(part) != size) or sha256_file(part) != sha:
                raise SyncError("取った更新の zip が想定と違います(大きさか SHA-256 が合いません)")
            install_update(part, home, ver)
        finally:
            fsio.unlink_quiet(part)
        self.state["updated"] = ver
        self._save_state()
        self.log("新しい版 %s を入れました(次に開いたときから)" % ver)


def fetch_learning(io, root, log):
    """学習の束(C# の Sync.FetchLearning と同じ)-> 最新の版(取った・既にあった)か None(Dropbox に無い)。取れなければ SyncError"""
    got = io.read_small(LEARNING + "/latest.json", SMALL_CAP)
    if got is None:
        return None
    d = _json_bytes(got[0])
    v = d.get("version") if isinstance(d, dict) else None
    if not (isinstance(v, str) and VERSION_DIR_RE.match(v)):
        raise SyncError("学習の latest.json の版の形が違います")
    final = os.path.join(root, v)
    if os.path.isfile(os.path.join(final, LEARN_PACK)):   # learning.json は最後に置く = あれば完成
        return v
    tmp = final + ".part"
    shutil.rmtree(tmp, ignore_errors=True)
    os.makedirs(tmp)
    try:
        pack_local = os.path.join(tmp, LEARN_PACK)
        if not io.download("%s/%s/%s" % (LEARNING, v, LEARN_PACK), pack_local):
            raise SyncError("学習の束 %s の learning.json が Dropbox にありません(同期の途中かもしれません)" % v)
        pack = fsio.read_json_or(pack_local, {}, kind=dict)
        for f in pack.get("files") if isinstance(pack.get("files"), list) else []:
            rel = f.get("path") if isinstance(f, dict) else None
            sha = str((f or {}).get("sha256") or "").lower() if isinstance(f, dict) else ""
            if not safe_rel(rel):
                raise SyncError("学習の束のファイル名が安全ではありません")
            local = safe_join(tmp, rel)
            os.makedirs(os.path.dirname(local), exist_ok=True)
            if not io.download("%s/%s/%s" % (LEARNING, v, rel), local):
                raise SyncError("学習の束のファイルが Dropbox にありません: %s" % rel)
            size = f.get("size")
            if (isinstance(size, int) and size >= 0 and os.path.getsize(local) != size) or sha256_file(local) != sha:
                raise SyncError("学習の束のファイルが壊れています(hash が合いません): %s" % rel)
        os.replace(tmp, final)
    except BaseException:
        shutil.rmtree(tmp, ignore_errors=True)
        raise
    log("学習の束 %s を取りました" % v)
    for old in sorted((n for n in os.listdir(root) if VERSION_DIR_RE.match(n) and os.path.isdir(os.path.join(root, n))), reverse=True)[KEEP_LEARNING:]:
        shutil.rmtree(os.path.join(root, old), ignore_errors=True)
    return v
