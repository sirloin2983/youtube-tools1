# -*- coding: utf-8 -*-
"""友人の玄関の初回の取得(F2-5。notes:plan/f1-friend-requirements.md の 9-1・7-5・A-15・A-16。今の送るアプリの Setup.cs と同じ規則を Python で)。

表 = <アプリのフォルダ>/fetch.json(dev/build_friend_zip.py が書く。{schema, version, items: [行]})。1 行:
    name・file・url(https だけ)・sha256・base(data = ② の作業データの根 / app = アプリのフォルダ)・dest(/ 区切りの相対)・
    size(分からなければ null。そのときは maxBytes で守る)・unzip(null・zip・tar.bz2・tar.bz2-member)・top と parts(tar.bz2)・member(tar.bz2-member)
足りないか(起動のたびに見るので軽く。SHA-256 は取ったときに確かめた):
    unzip null = ファイルがあり大きさが合う / zip = 目印 .fetched-<file> の中身が sha256 と同じ(今の送るアプリと同じ目印 = 前に取った物は取り直さない)/
    tar.bz2 = top の下に parts が全部ある / tar.bz2-member = ファイルがあり 0 < 大きさ <= maxBytes
取り方: 1 つずつ・.part に続きから(Range)・大きさと SHA-256 を確かめる・違えば消して最初から(2 回まで)・zip と tar は名前を全部確かめてから展開
    (外へ出る名前・絶対パス・ドライブ名・リンクは断る = zip slip)・1 つ失敗しても次へ(失敗した物は次の回にまた足りない物として出る)・やめられる。
    書き換えるのは表に載った物の置き場所(dest の下)だけ(7-5)。接続先は表の https の URL だけ(http への転送は断る)。
    古い部品を写す oldcopy(A-16)のあとに見る = 写せた物は足りない物に入らない。
文字起こしのエンジン C(CUDA)にしているときは、公式の CUDA 版の whisper.cpp(pipeline/transcribe/tx_engines.WCPP_BINARIES)も足りない物に数える
    (表に無いので行を組む。取った zip を tx_engines.fetch_wcpp_binary に渡して展開する = 置き方は ① と同じ 1 か所)。
記録 <玄関>/setup.json(取った物と最後の回の結果。見るためだけ。足りないかの判断には使わない)。
"""
import hashlib
import json
import os
import re
import shutil
import tarfile
import threading
import time
import urllib.error
import urllib.request
import zipfile

from ytt import fsio as _fsio, version as _version

UNZIPS = (None, "zip", "tar.bz2", "tar.bz2-member", "wcpp")   # wcpp = CUDA 版の whisper.cpp(表には無い。cuda_item が組む)
SHA_RE = re.compile(r"^[0-9a-f]{64}\Z")
CHUNK = 256 * 1024
HASH_CHUNK = 1 << 20
RETRIES = 6
RETRY_WAIT = 2.0
TIMEOUT = 60
ROOM = 1024 ** 3            # 取るときに残す空き(展開の途中の物・ログなど)
RECORD = "setup.json"
TX_TOOL = "transcribe"      # 文字起こしの作業データの ID(fetch.json の dest の頭と同じ。dev/build_friend_zip.py の TX_TOOL)
CUDA_NAME = "whisper.cpp/cuda"
LABELS = (("whisper.cpp/", "文字起こしのモデル"), ("llama.cpp/", "文を整える部品"), ("llm/", "文を整えるモデル"), ("sensevoice/", "声の判別のモデル"),
          ("diar/", "話す人の判別のモデル"), ("ffmpeg", "動画の道具 ffmpeg"), ("yt-dlp", "配信を取る道具 yt-dlp"), ("deno", "配信を取る道具の部品 Deno"))


class FetchError(Exception):
    """取れなかった(文は画面にそのまま出す。やり直しても同じになる物 = 続けて取り直さない)"""


class Cancelled(Exception):
    """やめた"""


# ---------------------------------------------------------------- 表
def _good_file(name):
    return isinstance(name, str) and name not in ("", ".", "..") and not any(c in name for c in "/\\:")


def safe_relative(p, allow_empty=True):
    """/ 区切りの、根の中だけを指す相対パスか(絶対パス・ドライブ名・.. ・空の区切りは不可)"""
    if not isinstance(p, str):
        return False
    n = p.replace("\\", "/")
    if not n:
        return allow_empty
    if n.startswith("/") or ":" in n:
        return False
    return all(s not in ("", "..") for s in n.split("/"))


def _int_or(v, dflt):
    return v if isinstance(v, int) and not isinstance(v, bool) else dflt


def problem(it):
    """表の 1 行の形の問題(文)か None(Setup.cs の Problem と同じ)"""
    if not it["name"]:
        return "name がありません"
    if not _good_file(it["file"]):
        return "file の名前が不正です"
    if not it["url"].startswith("https://"):
        return "url が https ではありません"
    if not SHA_RE.match(it["sha256"]):
        return "sha256 の形が違います"
    if it["base"] not in ("data", "app"):
        return "base は data か app"
    if not safe_relative(it["dest"]):
        return "dest が不正です"
    if it["size"] <= 0 and it["maxBytes"] <= 0:
        return "size も maxBytes もありません"
    if it["unzip"] not in UNZIPS:
        return "unzip を知りません: %s" % it["unzip"]
    if it["unzip"] == "tar.bz2" and not (it["top"] and safe_relative(it["top"]) and it["parts"] and all(safe_relative(p, False) for p in it["parts"])):
        return "top・parts が不正です"
    if it["unzip"] == "tar.bz2-member" and not (it["member"] and it["maxBytes"] > 0):
        return "member・maxBytes がありません"
    if not _good_file(archive_name(it)):
        return "url の名前が不正です"
    return None


def parse_item(o):
    s = lambda k: o.get(k) if isinstance(o.get(k), str) else ""   # noqa: E731
    parts = o.get("parts")
    it = {"name": s("name"), "file": s("file"), "url": s("url"), "sha256": s("sha256").lower(), "base": s("base"), "dest": s("dest"),
          "unzip": o.get("unzip") if isinstance(o.get("unzip"), str) else None, "top": s("top"), "member": s("member"),
          "size": _int_or(o.get("size"), -1), "maxBytes": _int_or(o.get("maxBytes"), 0),
          "parts": [p for p in parts if isinstance(p, str)] if isinstance(parts, list) else []}
    return it


def load(fetch_path):
    """fetch.json -> (版, [行])。無ければ (None, [])。形が壊れていれば FetchError(作る側の不具合。危ない行は 1 つでもあれば使わない = Setup.cs と同じ)"""
    if not fetch_path or not os.path.isfile(fetch_path):
        return None, []
    try:
        with open(fetch_path, "r", encoding="utf-8") as f:
            d = json.load(f)
    except (OSError, ValueError) as e:
        raise FetchError("fetch.json を読めません(%s)" % e.__class__.__name__)
    rows = d.get("items") if isinstance(d, dict) else None
    if not isinstance(rows, list):
        raise FetchError("fetch.json の形が違います(items がありません)")
    out = []
    for o in rows:
        if not isinstance(o, dict):
            raise FetchError("fetch.json の形が違います(行が表ではありません)")
        it = parse_item(o)
        bad = problem(it) if it["unzip"] != "wcpp" else "unzip を知りません: wcpp"
        if bad:
            raise FetchError("fetch.json の %s: %s" % (it["name"] or "?", bad))
        out.append(it)
    return str(d.get("version") or ""), out


def archive_name(it):
    """取るファイルの名前(tar.bz2-member は file が取り出したあとの名前なので、URL の最後の名前)"""
    if it["unzip"] == "tar.bz2-member":
        n = it["url"].rsplit("/", 1)[-1]
        return re.split(r"[?#]", n, 1)[0]
    return it["file"]


def expect(it):
    """大きさの見込み(上限)。進み具合の分母・これを超えたら止める"""
    return it["size"] if it["size"] > 0 else it["maxBytes"]


def folder(it, data_root, home):
    return os.path.join(home if it["base"] == "app" else data_root, *[p for p in it["dest"].split("/") if p])


def marker(it, fold):
    return os.path.join(fold, ".fetched-" + it["file"])


def label(name):
    """画面に出す名前(分からなければ表の name のまま)"""
    for head, text in LABELS:
        if name.startswith(head):
            rest = name[len(head):].strip("/")
            return "%s(%s)" % (text, rest) if rest and head.endswith("/") else text
    return name


def is_done(it, data_root, home):
    """取り終えているか(上の説明。読めなければ足りない)"""
    fold = folder(it, data_root, home)
    try:
        if it["unzip"] is None:
            p = os.path.join(fold, it["file"])
            if not os.path.isfile(p):
                return False
            n = os.path.getsize(p)
            return n == it["size"] if it["size"] > 0 else 0 < n <= it["maxBytes"]
        if it["unzip"] == "zip":
            with open(marker(it, fold), "r", encoding="utf-8") as f:
                return f.read().strip().lower() == it["sha256"]
        if it["unzip"] == "tar.bz2":
            return bool(it["parts"]) and all(os.path.isfile(os.path.join(fold, *it["top"].split("/"), *p.split("/"))) for p in it["parts"])
        if it["unzip"] == "tar.bz2-member":
            p = os.path.join(fold, it["file"])
            return os.path.isfile(p) and 0 < os.path.getsize(p) <= it["maxBytes"]
        if it["unzip"] == "wcpp":
            return _wcpp_ready(data_root)
    except OSError:
        return False
    return False


# ---------------------------------------------------------------- CUDA 版の whisper.cpp(エンジン C)
def cuda_item():
    """エンジン C の部品の行(① の表 tx_engines.WCPP_BINARIES の cuda。置き場所は <作業データ>/transcribe/bin/)か None(表に無い・確かめていない)"""
    from pipeline.transcribe import tx_engines as _tx   # 読むのは C を選んだときだけ
    if not _tx.wcpp_binary_ok("cuda"):
        return None
    s = _tx.WCPP_BINARIES["cuda"]
    return {"name": CUDA_NAME, "file": s["file"], "url": s["url"], "sha256": s["sha256"].lower(), "base": "data", "dest": TX_TOOL + "/bin",
            "unzip": "wcpp", "top": "", "member": "", "size": s["size"], "maxBytes": 0, "parts": []}


def _wcpp_ready(data_root):
    from pipeline.transcribe import tx_engines as _tx
    from ytt import txbase as _txbase
    tx = os.path.join(data_root, TX_TOOL)
    m = _fsio.read_json_or(os.path.join(_txbase.wcpp_bin_dir(tx, "cuda"), "build.json"), None, kind=dict)   # ① の WhisperCpp.ready と同じ見方
    return os.path.isfile(_txbase.wcpp_exe(tx, "cuda")) and bool(m) and m.get("commit") == _tx.WHISPER_CPP["commit"]


def install_wcpp(it, archive, data_root):
    """取って確かめた CUDA 版の zip を ① の置き方で展開する(tx_engines.fetch_wcpp_binary。zip が同じ大きさと SHA-256 ならネットへ出ない)"""
    from pipeline.transcribe import tx_engines as _tx
    try:
        _tx.fetch_wcpp_binary("cuda", os.path.join(data_root, TX_TOOL))
    except _tx.EngineError as e:
        raise FetchError(str(getattr(e, "message", "") or e))


# ---------------------------------------------------------------- 取る道具
class _HttpsOnly(urllib.request.HTTPRedirectHandler):
    """https でない転送先へは行かない"""

    def redirect_request(self, req, fp, code, msg, headers, newurl):
        if not str(newurl).lower().startswith("https://"):
            raise FetchError("転送先が https ではないので取りません")
        return super().redirect_request(req, fp, code, msg, headers, newurl)


class HttpDownloader:
    """url を part へ(あればその続きから = Range)。expect を超えたら FetchError。通信の失敗は RETRIES 回まで待ってやり直す"""

    def __init__(self, log=None, wait=RETRY_WAIT, opener=None):
        self.log = log or (lambda msg: None)
        self.wait = wait
        self.opener = opener or urllib.request.build_opener(_HttpsOnly)

    def get(self, url, part, expect_bytes, progress, cancelled):
        if not str(url).startswith("https://"):
            raise FetchError("取得先が https ではありません")
        os.makedirs(os.path.dirname(part), exist_ok=True)
        attempt = 0
        while True:
            attempt += 1
            try:
                return self._once(url, part, expect_bytes, progress, cancelled)
            except (FetchError, Cancelled):
                raise
            except (OSError, ValueError) as e:   # urllib の失敗(HTTPError・URLError・切れた)
                if attempt >= RETRIES:
                    raise FetchError("通信が続きませんでした(%s)" % (str(e)[:160] or e.__class__.__name__))
                self.log("取得のやり直し %d: %s" % (attempt, str(e)[:160]))
                end = time.monotonic() + self.wait
                while time.monotonic() < end:
                    if cancelled():
                        raise Cancelled()
                    time.sleep(0.1)

    def _once(self, url, part, expect_bytes, progress, cancelled):
        have = os.path.getsize(part) if os.path.isfile(part) else 0
        if have > expect_bytes:
            _fsio.unlink_quiet(part)
            have = 0
        req = urllib.request.Request(url, headers={"User-Agent": "ytt-friend/%s" % _version.VERSION})
        if have > 0:
            req.add_header("Range", "bytes=%d-" % have)
        try:
            resp = self.opener.open(req, timeout=TIMEOUT)
        except urllib.error.HTTPError as e:
            if e.code == 416:   # 続きが取れない = 最初から
                _fsio.unlink_quiet(part)
                raise OSError("続きが取れなかったので最初から取り直します")
            raise
        with resp:
            resume = have > 0 and getattr(resp, "status", 200) == 206
            done = have if resume else 0
            with open(part, "ab" if resume else "wb") as f:
                progress(done)
                while True:
                    if cancelled():
                        raise Cancelled()
                    b = resp.read(CHUNK)
                    if not b:
                        break
                    done += len(b)
                    if done > expect_bytes:
                        f.close()
                        _fsio.unlink_quiet(part)
                        raise FetchError("想定より大きいファイルなので止めました")
                    f.write(b)
                    progress(done)


def sha256_file(path):
    h = hashlib.sha256()
    with open(path, "rb") as f:
        for b in iter(lambda: f.read(HASH_CHUNK), b""):
            h.update(b)
    return h.hexdigest()


def verify(it, path):
    """大きさ(分かっていれば一致・無ければ上限以下)と SHA-256 -> 違う理由か None"""
    n = os.path.getsize(path)
    if (n != it["size"]) if it["size"] > 0 else (n == 0 or n > it["maxBytes"]):
        return "大きさが違います"
    if sha256_file(path) != it["sha256"]:
        return "SHA-256 が合いません"
    return None


def _safe_name(n):
    n = n.replace("\\", "/")
    return not (n.startswith("/") or ":" in n or ".." in n.split("/"))


def unzip_safe(zip_path, dest):
    """zip を dest に展開(名前を全部確かめてから書く。外へ出る名前・絶対パス・ドライブ名は FetchError = zip slip。同じ名前は上書き)"""
    with zipfile.ZipFile(zip_path) as z:
        plan = []
        for info in z.infolist():
            n = info.filename.replace("\\", "/")
            if not n:
                continue
            full = os.path.join(dest, *[p for p in n.split("/") if p])
            if not _safe_name(n) or not _fsio.is_inside(full, dest):
                raise FetchError("zip の中の名前が危ないので使いません: %s" % n[:80])
            if (info.external_attr >> 16) & 0o170000 == 0o120000:
                raise FetchError("zip の中にリンクがあるので使いません: %s" % n[:80])
            plan.append((info, full, n.endswith("/")))
        for info, full, is_dir in plan:
            if is_dir:
                os.makedirs(full, exist_ok=True)
                continue
            os.makedirs(os.path.dirname(full), exist_ok=True)
            with z.open(info) as src, open(full, "wb") as dst:
                shutil.copyfileobj(src, dst, HASH_CHUNK)


def untar_all(archive, dest, top):
    """tar.bz2 を dest に展開(全部の名前が top の下・ファイルとフォルダだけ・外へ出ない。違えば何も書かずに FetchError)"""
    with tarfile.open(archive, "r:bz2") as t:
        ms = t.getmembers()
        plan = []
        for m in ms:
            n = m.name[2:] if m.name.startswith("./") else m.name
            full = os.path.join(dest, *[p for p in n.replace("\\", "/").split("/") if p])
            if not _safe_name(n) or not (m.isfile() or m.isdir()) or not (n == top or n.startswith(top + "/")) or not _fsio.is_inside(full, dest):
                raise FetchError("tar の中に想定外の物があるので使いません: %s" % m.name[:80])
            plan.append((m, full))
        for m, full in plan:
            if m.isdir():
                os.makedirs(full, exist_ok=True)
                continue
            os.makedirs(os.path.dirname(full), exist_ok=True)
            with t.extractfile(m) as src, open(full, "wb") as dst:
                shutil.copyfileobj(src, dst, HASH_CHUNK)


def untar_member(archive, member, out_file, max_bytes):
    """tar.bz2 の 1 つ(ファイル・max_bytes 以下)だけを out_file に"""
    with tarfile.open(archive, "r:bz2") as t:
        try:
            m = t.getmember(member)
        except KeyError:
            raise FetchError("tar の中に %s がありません" % member[:80])
        if not m.isfile() or m.size > max_bytes:
            raise FetchError("tar の中の %s が想定と違います" % member[:80])
        os.makedirs(os.path.dirname(out_file), exist_ok=True)
        part = out_file + ".part"
        try:
            with t.extractfile(m) as src, open(part, "wb") as dst:
                shutil.copyfileobj(src, dst, HASH_CHUNK)
            os.replace(part, out_file)
        except BaseException:
            _fsio.unlink_quiet(part)
            raise


# ---------------------------------------------------------------- 1 回の取得
class Fetcher:
    """items を 1 つずつ取る(Setup.cs の Fetcher と同じ)。downloader = HttpDownloader(テストは偽物)・wcpp = CUDA 版の展開(テストは偽物)"""

    def __init__(self, data_root, home, downloader=None, log=None, progress=None, cancelled=None, wcpp=install_wcpp):
        self.data_root, self.home = data_root, home
        self.log = log or (lambda msg: None)
        self.http = downloader or HttpDownloader(log=self.log)
        self.progress = progress or (lambda p: None)
        self.cancelled = cancelled or (lambda: False)
        self.wcpp = wcpp

    def run(self, items):
        """-> {"done": [名前], "failed": [{"name", "message"}], "cancelled": 真偽}"""
        res = {"done": [], "failed": [], "cancelled": False}
        total = sum(expect(i) for i in items)
        before = 0
        for idx, it in enumerate(items):
            pr = {"index": idx + 1, "count": len(items), "name": it["name"], "label": label(it["name"]), "phase": "",
                  "itemDone": 0, "itemTotal": expect(it), "done": before, "total": total}

            def report(done, phase, pr=pr, it=it, before=before):
                pr.update(itemDone=done, phase=phase, done=before + min(done, expect(it)))
                self.progress(dict(pr))
            try:
                self.fetch_one(it, report)
                res["done"].append(it["name"])
            except Cancelled:
                res["cancelled"] = True
                return res
            except (FetchError, OSError, zipfile.BadZipFile, tarfile.TarError, EOFError) as e:
                msg = str(e)[:200] or e.__class__.__name__
                self.log("取れませんでした %s: %s" % (it["name"], msg))
                res["failed"].append({"name": it["name"], "label": label(it["name"]), "message": msg})
            report(expect(it), "済み")
            before += expect(it)
        return res

    def fetch_one(self, it, report):
        fold = folder(it, self.data_root, self.home)
        os.makedirs(fold, exist_ok=True)
        archive = os.path.join(fold, archive_name(it))
        part = archive + ".part"
        if os.path.isfile(archive) and verify(it, archive):
            self.log("中身が違うので取り直します: %s" % archive_name(it))
            os.remove(archive)
        if not os.path.isfile(archive):
            for attempt in (1, 2):
                self.http.get(it["url"], part, expect(it), lambda n: report(n, "取っています"), self.cancelled)
                report(expect(it), "確かめています")
                why = verify(it, part)
                if not why:
                    break
                _fsio.unlink_quiet(part)   # 違う物は続きから取らず、最初から
                if attempt == 2:
                    raise FetchError("%s の中身が想定と違います(%s)" % (label(it["name"]), why))
            os.replace(part, archive)
        if it["unzip"] is None:
            return
        report(expect(it), "展開しています")
        if self.cancelled():
            raise Cancelled()
        if it["unzip"] == "zip":
            unzip_safe(archive, fold)
            with open(marker(it, fold), "w", encoding="utf-8") as f:
                f.write(it["sha256"])
        elif it["unzip"] == "tar.bz2":
            untar_all(archive, fold, it["top"])
            if not is_done(it, self.data_root, self.home):
                raise FetchError("%s のファイルがそろいませんでした" % label(it["name"]))
        elif it["unzip"] == "tar.bz2-member":
            untar_member(archive, it["member"], os.path.join(fold, it["file"]), it["maxBytes"])
        elif it["unzip"] == "wcpp":
            self.wcpp(it, archive, self.data_root)
        _fsio.unlink_quiet(archive)


# ---------------------------------------------------------------- 空き容量
def _free(path, disk_usage):
    p = os.path.abspath(path)
    while not os.path.exists(p):
        up = os.path.dirname(p)
        if up == p:
            break
        p = up
    try:
        return disk_usage(p).free
    except OSError:
        return None


def space(items, data_root, home, disk_usage=shutil.disk_usage):
    """置き場所ごとの要る量と空き -> [{"path", "need", "free", "ok"}]。同じドライブなら合わせて比べる。
    要る量 = 取る物の合計 + 展開する物は同じだけもう 1 つ(展開が済むまで zip と中身が並ぶ。多めに見る)+ ROOM"""
    by_base = {}
    for it in items:
        base = home if it["base"] == "app" else data_root
        n = expect(it) * (2 if it["unzip"] else 1)
        by_base[base] = by_base.get(base, 0) + n
    drives = {}
    for base, n in by_base.items():
        d = os.path.splitdrive(os.path.abspath(base))[0].lower() or os.path.abspath(base)
        drives[d] = drives.get(d, 0) + n
    out = []
    for base, n in by_base.items():
        d = os.path.splitdrive(os.path.abspath(base))[0].lower() or os.path.abspath(base)
        free = _free(base, disk_usage)
        out.append({"path": base, "need": n + ROOM, "free": free, "ok": free is None or free >= drives[d] + ROOM})
    return out


# ---------------------------------------------------------------- 玄関の係
class Setup:
    """初回の取得の係(玄関に 1 つ)。fetch_path = <home>/fetch.json(無ければ何もしない = 開発の PC)。
    device() = 今の文字起こしの機器(cuda なら CUDA 版の whisper.cpp も数える)。checked = oldcopy が済んで見てよい(玄関の prepare が真にする)。
    after(結果) = 取り終えたとき(玄関が道具の場所を教え直す)"""

    def __init__(self, fetch_path, data_root, home, record_dir, device=lambda: "vulkan", log=None, downloader=None,
                 disk_usage=shutil.disk_usage, wcpp=install_wcpp, cuda=cuda_item, after=None):
        self.fetch_path, self.data_root, self.home, self.record_dir = fetch_path, data_root, home, record_dir
        self.device, self.log, self.downloader = device, log or (lambda msg: None), downloader
        self.disk_usage, self.wcpp, self.cuda, self.after = disk_usage, wcpp, cuda, after
        self.checked = False
        self.later = False          # [あとで](起動ごと。次に開くとまた確認を出す)
        self.error = None           # fetch.json が壊れている(作る側の不具合。ログと画面に)
        self.lock = threading.Lock()
        self.thread = None
        self.cancel_ev = threading.Event()
        self.progress = None
        self.result = None

    # ---- 足りない物
    def items(self):
        """表の行(+ エンジン C のとき CUDA 版)。fetch.json が無ければ空(開発の PC = 取る物は無い)"""
        if not self.fetch_path or not os.path.isfile(self.fetch_path):
            return []
        try:
            _ver, rows = load(self.fetch_path)
            self.error = None
        except FetchError as e:
            if self.error != str(e):
                self.log("初回の取得の表を使えません: %s" % e)
            self.error = str(e)
            return []
        try:
            if self.device() == "cuda":
                c = self.cuda()
                if c:
                    rows.append(c)
        except Exception as e:   # noqa: BLE001  (C の部品の表を読めなくても、ほかの部品は取れる)
            self.log("エンジン C の部品の表を読めません: %s" % e.__class__.__name__)
        return rows

    def missing(self, only=None):
        rows = [i for i in self.items() if not is_done(i, self.data_root, self.home)]
        return [i for i in rows if i["name"] in only] if only else rows

    def running(self):
        t = self.thread
        return t is not None and t.is_alive()

    def block_reason(self):
        """[送る](この PC)を押せない理由か None"""
        if not self.checked:
            return None
        if self.running():
            return "処理の部品を取っています。取り終えると送れます(進み具合は上の「初回の準備」)"
        if self.missing():
            return "処理の部品が足りません。上の帯の [取ってくる] から取ってください"
        return None

    def view(self):
        """画面へ: {active, missing: [{name, label, size}], count, total, places, canStart, reason, running, progress, result, later, error}"""
        if not self.checked:
            return {"active": False}
        miss = self.missing()
        sp = space(miss, self.data_root, self.home, self.disk_usage) if miss else []
        short = [s for s in sp if not s["ok"]]
        reason = ""
        if short:
            s = short[0]
            reason = "%s の空きが足りません(空き %s・要る %s)。空きを増やしてから始めてください" % (s["path"], gb(s["free"]), gb(s["need"]))
        running = self.running()
        return {"active": True, "count": len(miss), "total": sum(expect(i) for i in miss),
                "missing": [{"name": i["name"], "label": label(i["name"]), "size": expect(i)} for i in miss],
                "places": [{"path": s["path"], "need": s["need"], "free": s["free"], "ok": s["ok"]} for s in sp],
                "canStart": bool(miss) and not short and not running, "reason": reason, "running": running,
                "progress": dict(self.progress) if running and self.progress else None, "result": self.result, "later": self.later,
                "error": self.error}

    # ---- 操作
    def start(self, only=None):
        """足りない物を裏の糸で取り始める(only = 名前の組 = その物だけ)。始められなければ ValueError(理由)"""
        with self.lock:
            if not self.checked:
                raise ValueError("前のアプリの部品を写しています。終わってから始めてください")
            if self.running():
                raise ValueError("もう取っています")
            miss = self.missing(only)
            if not miss:
                raise ValueError("足りない部品はありません")
            short = [s for s in space(miss, self.data_root, self.home, self.disk_usage) if not s["ok"]]
            if short:
                raise ValueError("%s の空きが足りません(空き %s・要る %s)" % (short[0]["path"], gb(short[0]["free"]), gb(short[0]["need"])))
            self.cancel_ev.clear()
            self.later = False
            self.result = None
            self.progress = {"index": 0, "count": len(miss), "name": "", "label": "", "phase": "始めています", "itemDone": 0,
                             "itemTotal": 0, "done": 0, "total": sum(expect(i) for i in miss)}
            self.thread = threading.Thread(target=self._job, args=(miss,), name="friend-setup", daemon=True)
            self.thread.start()
        return self.view()

    def cancel(self):
        self.cancel_ev.set()

    def defer(self):
        self.later = True

    def reopen(self):
        self.later = False

    def wait(self, timeout=None):
        t = self.thread
        if t is not None:
            t.join(timeout)

    def _job(self, items):
        self.log("初回の取得を始めます: %d 個(%s)" % (len(items), gb(sum(expect(i) for i in items))))
        f = Fetcher(self.data_root, self.home, downloader=self.downloader, log=self.log, progress=self._on_progress,
                    cancelled=self.cancel_ev.is_set, wcpp=self.wcpp)
        try:
            res = f.run(items)
        except Exception as e:   # noqa: BLE001  (思わぬ失敗でも画面に理由を出す)
            self.log("初回の取得が止まりました: %s %s" % (e.__class__.__name__, str(e)[:200]))
            res = {"done": [], "failed": [{"name": "取得", "label": "取得", "message": e.__class__.__name__}], "cancelled": False}
        res["ok"] = not res["failed"] and not res["cancelled"]
        res["at"] = int(time.time() * 1000)
        self.result = res
        self.log("初回の取得: 取れた %d 個・取れなかった %d 個%s" % (len(res["done"]), len(res["failed"]), "・やめた" if res["cancelled"] else ""))
        self._record(items, res)
        if res["done"] and self.after is not None:
            try:
                self.after(res)
            except Exception as e:   # noqa: BLE001
                self.log("取り終えたあとの準備に失敗しました: %s" % e.__class__.__name__)

    def _on_progress(self, p):
        self.progress = p

    def _record(self, items, res):
        """記録(見るためだけ): 取れた物の名前・sha256・置き場所と、最後の回の結果"""
        path = os.path.join(self.record_dir, RECORD)
        d = _fsio.read_json_or(path, {}, kind=dict)
        got = d.get("items") if isinstance(d.get("items"), dict) else {}
        for it in items:
            if it["name"] in res["done"]:
                got[it["name"]] = {"sha256": it["sha256"], "folder": folder(it, self.data_root, self.home), "at": res["at"]}
        try:
            _fsio.write_json(path, {"v": 1, "items": got, "last": {k: res[k] for k in ("at", "ok", "done", "failed", "cancelled")}}, indent=1)
        except OSError as e:
            self.log("初回の取得の記録を書けませんでした: %s" % e.__class__.__name__)


def gb(n):
    if n is None:
        return "不明"
    return "%.1f GB" % (n / 1e9) if n >= 1e9 else "%d MB" % max(1, round(n / 1e6))   # 画面(friend.js の sizeText)と同じ数え方
