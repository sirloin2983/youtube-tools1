"""src/friendapp/setup.py(初回の取得)のテスト。本物のネットには出ない(偽の取り方)。リポジトリ直下で: py -3.12 -m unittest tests/friendapp/test_setup.py"""
import hashlib
import io
import json
import os
import shutil
import sys
import tarfile
import threading
import time
import unittest
import zipfile
from collections import namedtuple
from unittest import mock

os.environ.setdefault("YTT_DATA_DIR", "inplace")
SRC = os.path.join(os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))), "src")
if SRC not in sys.path:
    sys.path.insert(0, SRC)
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))   # tests/(testkit)
import testkit  # noqa: E402
from friendapp import setup as S  # noqa: E402

Usage = namedtuple("Usage", "total used free")
BIG = Usage(10 ** 13, 0, 10 ** 13)


def sha(b):
    return hashlib.sha256(b).hexdigest()


def zbytes(entries):
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w") as z:
        for n, d in entries.items():
            z.writestr(n, d)
    return buf.getvalue()


def tbytes(entries):
    buf = io.BytesIO()
    with tarfile.open(fileobj=buf, mode="w:bz2") as t:
        for n, d in entries.items():
            info = tarfile.TarInfo(n)
            info.size = len(d)
            t.addfile(info, io.BytesIO(d))
    return buf.getvalue()


class FakeDownloader:
    """url -> 中身。part があればその続きから書く(Range の形)。fail = 何回失敗させるか・break_at = その回は途中で切る"""

    def __init__(self, files):
        self.files = dict(files)
        self.calls = []
        self.fail = {}
        self.wrong = {}

    def get(self, url, part, expect, progress, cancelled):
        self.calls.append(url)
        if not url.startswith("https://"):
            raise S.FetchError("https でない")
        if self.fail.get(url):
            self.fail[url] -= 1
            raise S.FetchError("つながりません")
        data = self.wrong.pop(url, None) or self.files[url]
        have = os.path.getsize(part) if os.path.isfile(part) else 0
        os.makedirs(os.path.dirname(part), exist_ok=True)
        with open(part, "ab") as f:
            for i in range(have, len(data), 4):
                if cancelled():
                    raise S.Cancelled()
                f.write(data[i:i + 4])
                progress(i + 4)


class HomeBase(unittest.TestCase):
    """一時の home(data・app/friendapp・fetch.json の置き場)と、取得表の書き出し"""

    def setUp(self):
        self.tmp = testkit.tempdir(self, "friendsetup-")
        hosts, S.FETCH_HOSTS = S.FETCH_HOSTS, S.FETCH_HOSTS + ("h",)   # 偽の取り先 https://h/
        self.addCleanup(setattr, S, "FETCH_HOSTS", hosts)
        self.home = os.path.join(self.tmp, "home")
        self.data = os.path.join(self.home, "data")
        self.friend = os.path.join(self.data, "app", "friendapp")
        os.makedirs(self.friend)
        self.fetch = os.path.join(self.home, "fetch.json")

    def write_fetch(self, items):
        testkit.write_json(self.fetch, {"schema": "youtube-tools-friend-fetch/v1", "version": "0.93.0", "items": items})


class SetupTest(HomeBase):
    def setUp(self):
        super().setUp()
        self.model = b"model-bytes-" * 10
        self.tool = zbytes({"ffmpeg-1/bin/ffmpeg.exe": b"exe", "ffmpeg-1/README.txt": b"r"})
        self.sv = tbytes({"sv/model.onnx": b"onnx", "sv/tokens.txt": b"tok"})
        self.diar = tbytes({"seg/model.onnx": b"seg-onnx", "seg/other.txt": b"x"})
        self.files = {"https://h/model.bin": self.model, "https://h/ffmpeg.zip": self.tool, "https://h/sv.tar.bz2": self.sv,
                      "https://h/seg.tar.bz2?dl=1": self.diar}
        self.items = [
            {"name": "whisper.cpp/large-v3", "file": "model.bin", "url": "https://h/model.bin", "size": len(self.model), "sha256": sha(self.model),
             "base": "data", "dest": "transcribe/models/whispercpp", "unzip": None},
            {"name": "ffmpeg", "file": "ffmpeg.zip", "url": "https://h/ffmpeg.zip", "size": len(self.tool), "sha256": sha(self.tool),
             "base": "app", "dest": "tools/ffmpeg", "unzip": "zip"},
            {"name": "sensevoice/x", "file": "sv.tar.bz2", "url": "https://h/sv.tar.bz2", "size": len(self.sv), "sha256": sha(self.sv),
             "base": "data", "dest": "transcribe/models/sv", "unzip": "tar.bz2", "top": "sv", "parts": ["model.onnx", "tokens.txt"]},
            {"name": "diar/segmentation", "file": "seg.onnx", "url": "https://h/seg.tar.bz2?dl=1", "size": None, "maxBytes": 10 ** 6,
             "sha256": sha(self.diar), "base": "data", "dest": "transcribe/models/diar", "unzip": "tar.bz2-member", "member": "seg/model.onnx"},
        ]
        self.write_fetch(self.items)
        self.dl = FakeDownloader(self.files)

    def write_tmp(self, data):
        p = os.path.join(self.tmp, "blob.tar.bz2")
        with open(p, "wb") as f:
            f.write(data)
        return p

    def make(self, **kw):
        kw.setdefault("downloader", self.dl)
        kw.setdefault("disk_usage", lambda p: BIG)
        kw.setdefault("cuda", lambda: None)
        return S.Setup(self.fetch, self.data, self.home, self.friend, **kw)

    def start_job(self, st, only=None):
        """取る段だけを裏の糸で始める(準備の流れ start を通さない)"""
        st.thread = threading.Thread(target=st._job, args=(st.missing(only),), daemon=True)
        st.thread.start()

    def run_setup(self, st, only=None):
        self.start_job(st, only)
        st.wait(10)
        return st.result

    # ---- 表
    def test_load_refuses_bad_rows(self):
        for bad in ({"url": "http://h/model.bin"}, {"url": "https://evil.example/model.bin"}, {"url": "https://github.com.evil.example/x.bin"}, {"dest": "../x"}, {"dest": "C:/x"}, {"file": "a/b"}, {"sha256": "zz"}, {"base": "other"},
                    {"unzip": "rar"}, {"unzip": "wcpp"}, {"size": None, "maxBytes": None}):
            row = dict(self.items[0], **bad)
            self.write_fetch([row])
            with self.assertRaises(S.FetchError, msg=str(bad)):
                S.load(self.fetch)
        self.assertEqual(S.load(os.path.join(self.tmp, "none.json")), (None, []))

    def test_bad_table_means_nothing_to_fetch(self):
        self.write_fetch([dict(self.items[0], url="http://h/model.bin")])
        st = self.make()
        self.assertEqual(st.missing(), [])
        self.assertIn("https", st.error)
        self.assertIsNone(st.block_reason())

    def test_no_fetch_json_means_inactive(self):
        st = S.Setup(None, self.data, self.home, self.friend)
        self.assertEqual(st.missing(), [])
        self.assertIsNone(st.block_reason())

    # ---- 取る
    def test_fetch_all_and_done(self):
        st = self.make()
        self.assertEqual(len(st.missing()), 4)
        self.assertIn("足りません", st.block_reason())
        self.assertEqual(sum(S.expect(i) for i in st.missing()), sum(S.expect(S.parse_item(i)) for i in self.items))
        res = self.run_setup(st)
        self.assertTrue(res["ok"], res)
        self.assertEqual(st.missing(), [])
        self.assertIsNone(st.block_reason())
        with open(os.path.join(self.data, "transcribe", "models", "whispercpp", "model.bin"), "rb") as f:
            self.assertEqual(f.read(), self.model)
        tools = os.path.join(self.home, "tools", "ffmpeg")
        self.assertTrue(os.path.isfile(os.path.join(tools, "ffmpeg-1", "bin", "ffmpeg.exe")))
        self.assertFalse(os.path.exists(os.path.join(tools, "ffmpeg.zip")))   # 展開したら zip は消す
        with open(os.path.join(tools, ".fetched-ffmpeg.zip"), encoding="utf-8") as f:
            self.assertEqual(f.read(), sha(self.tool))   # 目印(取り直さないための印)
        self.assertTrue(os.path.isfile(os.path.join(self.data, "transcribe", "models", "sv", "sv", "tokens.txt")))
        with open(os.path.join(self.data, "transcribe", "models", "diar", "seg.onnx"), "rb") as f:
            self.assertEqual(f.read(), b"seg-onnx")
        self.assertFalse(os.path.exists(os.path.join(self.data, "transcribe", "models", "diar", "seg.tar.bz2")))
        with open(os.path.join(self.friend, S.RECORD), encoding="utf-8") as f:
            rec = json.load(f)
        self.assertTrue(rec["last"]["ok"])
        self.assertIn("ffmpeg", rec["items"])
        # 2 回目は取らない
        n = len(self.dl.calls)
        self.assertEqual(self.make().missing(), [])
        self.assertEqual(len(self.dl.calls), n)

    def test_existing_marker_is_kept(self):
        """前に取って目印を置いた物は取り直さない・目印の sha256 が違えば足りない"""
        tools = os.path.join(self.home, "tools", "ffmpeg")
        os.makedirs(tools)
        with open(os.path.join(tools, ".fetched-ffmpeg.zip"), "w", encoding="utf-8") as f:
            f.write(sha(self.tool))
        names = [i["name"] for i in self.make().missing()]
        self.assertNotIn("ffmpeg", names)
        with open(os.path.join(tools, ".fetched-ffmpeg.zip"), "w", encoding="utf-8") as f:
            f.write("0" * 64)
        self.assertIn("ffmpeg", [i["name"] for i in self.make().missing()])

    def test_wrong_size_file_is_missing(self):
        p = os.path.join(self.data, "transcribe", "models", "whispercpp", "model.bin")
        os.makedirs(os.path.dirname(p))
        with open(p, "wb") as f:
            f.write(b"short")
        self.assertIn("whisper.cpp/large-v3", [i["name"] for i in self.make().missing()])

    def test_resume_from_part(self):
        fold = os.path.join(self.data, "transcribe", "models", "whispercpp")
        os.makedirs(fold)
        with open(os.path.join(fold, "model.bin.part"), "wb") as f:
            f.write(self.model[:30])
        res = self.run_setup(self.make(), only={"whisper.cpp/large-v3"})
        self.assertTrue(res["ok"])
        with open(os.path.join(fold, "model.bin"), "rb") as f:
            self.assertEqual(f.read(), self.model)

    def test_sha_mismatch_refetches_once_then_fails(self):
        url = "https://h/model.bin"
        self.dl.wrong[url] = b"x" * len(self.model)   # 1 回目は中身が違う → 消して最初から
        res = self.run_setup(self.make(), only={"whisper.cpp/large-v3"})
        self.assertTrue(res["ok"])
        self.assertEqual(self.dl.calls.count(url), 2)
        # 2 回とも違えば失敗(ほかの物は進む)
        shutil.rmtree(os.path.join(self.data, "transcribe", "models", "whispercpp"))
        files = dict(self.files)
        files[url] = b"y" * len(self.model)
        self.dl = FakeDownloader(files)
        st = self.make()
        res = self.run_setup(st)
        self.assertFalse(res["ok"])
        self.assertEqual([f["name"] for f in res["failed"]], ["whisper.cpp/large-v3"])
        self.assertIn("SHA-256", res["failed"][0]["message"])
        self.assertEqual([i["name"] for i in st.missing()], ["whisper.cpp/large-v3"])   # 失敗した物だけ次の回
        self.assertFalse(os.path.exists(os.path.join(self.data, "transcribe", "models", "whispercpp", "model.bin.part")))

    def test_failure_does_not_stop_others(self):
        self.dl.fail["https://h/ffmpeg.zip"] = 1
        res = self.run_setup(self.make())
        self.assertEqual([f["name"] for f in res["failed"]], ["ffmpeg"])
        self.assertEqual(len(res["done"]), 3)

    def test_cancel_keeps_part(self):
        gate = threading.Event()
        started = threading.Event()
        lock, began = threading.Lock(), []

        class Slow(FakeDownloader):
            def get(self, url, part, expect, progress, cancelled):
                os.makedirs(os.path.dirname(part), exist_ok=True)
                with open(part, "ab") as f:
                    f.write(b"m")
                with lock:
                    began.append(part)
                    if len(began) >= S.PARALLEL:   # 同時に始める物が全部書いてから取り消す(10-23: 1 本目で取り消すと、負荷で残りが書く前に止まり 2 != 3 で揺れた)
                        started.set()
                gate.wait(60)
                if cancelled():
                    raise S.Cancelled()
        st = self.make(downloader=Slow(self.files))
        self.start_job(st)
        self.assertTrue(started.wait(60), began)
        self.assertTrue(st.running())
        self.assertIn("取っています", st.block_reason())
        st.cancel()
        gate.set()
        st.wait(60)
        self.assertTrue(st.result["cancelled"])
        parts = [n for _, _, fs in os.walk(self.home) for n in fs if n.endswith(".part")]
        self.assertEqual(len(parts), S.PARALLEL, parts)   # 同時に始めた物の途中は残す・残りは始めない

    def test_after_called_with_result(self):
        got = []
        self.run_setup(self.make(after=got.append))
        self.assertEqual(len(got), 1)
        self.assertTrue(got[0]["ok"])

    # ---- 展開の守り(zip slip)
    def test_zip_slip_refused(self):
        for name in ("../evil.txt", "/abs.txt", "C:/x.txt", "a/../../evil.txt"):
            bad = zbytes({name: b"bad"})
            item = dict(self.items[1], size=len(bad), sha256=sha(bad), url="https://h/bad.zip", file="bad.zip")
            self.write_fetch([item])
            dl = FakeDownloader({"https://h/bad.zip": bad})
            res = self.run_setup(self.make(downloader=dl))
            self.assertFalse(res["ok"], name)
            self.assertIn("危ない", res["failed"][0]["message"])
            self.assertFalse(os.path.exists(os.path.join(self.home, "tools", "evil.txt")))
            self.assertFalse(os.path.exists(os.path.join(self.home, "evil.txt")))

    def test_tar_outside_top_refused(self):
        bad = tbytes({"sv/model.onnx": b"o", "other/evil.txt": b"e"})
        item = dict(self.items[2], size=len(bad), sha256=sha(bad), url="https://h/bad.tar.bz2", file="bad.tar.bz2")
        self.write_fetch([item])
        res = self.run_setup(self.make(downloader=FakeDownloader({"https://h/bad.tar.bz2": bad})))
        self.assertFalse(res["ok"])
        self.assertFalse(os.path.exists(os.path.join(self.data, "transcribe", "models", "sv", "other")))
        self.assertFalse(os.path.exists(os.path.join(self.data, "transcribe", "models", "sv", "sv", "model.onnx")))   # 何も書かない

    def test_tar_member_only_that_member(self):
        self.write_fetch([self.items[3]])
        self.assertTrue(self.run_setup(self.make())["ok"])
        self.assertEqual(sorted(os.listdir(os.path.join(self.data, "transcribe", "models", "diar"))), ["seg.onnx"])
        with self.assertRaises(S.FetchError):   # 上限より大きい中身は断る
            S.untar_member(self.write_tmp(self.diar), "seg/model.onnx", os.path.join(self.tmp, "o.onnx"), 3)
        self.assertEqual(S.label("diar/segmentation"), "話す人の判別のモデル(segmentation)")

    # ---- エンジン C(CUDA 版の whisper.cpp)
    def test_cuda_item_only_when_device_cuda(self):
        blob = zbytes({"Release/whisper-cli.exe": b"cli"})
        cuda = {"name": S.CUDA_NAME, "file": "cuda.zip", "url": "https://h/cuda.zip", "sha256": sha(blob), "base": "data",
                "dest": "transcribe/bin", "unzip": "wcpp", "top": "", "member": "", "size": len(blob), "maxBytes": 0, "parts": []}
        self.dl.files["https://h/cuda.zip"] = blob
        installed = []
        dev = {"v": "vulkan"}

        def wcpp(it, archive, data_root):
            installed.append(os.path.basename(archive))
            with open(os.path.join(self.tmp, "cuda-ready"), "w") as f:
                f.write("1")
        st = self.make(device=lambda: dev["v"], cuda=lambda: cuda, wcpp=wcpp)
        self.assertNotIn(S.CUDA_NAME, [i["name"] for i in st.missing()])
        dev["v"] = "cuda"
        orig = S._wcpp_ready
        S._wcpp_ready = lambda root: os.path.isfile(os.path.join(self.tmp, "cuda-ready"))
        self.addCleanup(setattr, S, "_wcpp_ready", orig)
        self.assertIn(S.CUDA_NAME, [i["name"] for i in st.missing()])
        res = self.run_setup(st, only={S.CUDA_NAME})
        self.assertTrue(res["ok"], res)
        self.assertEqual(installed, ["cuda.zip"])
        self.assertNotIn(S.CUDA_NAME, [i["name"] for i in st.missing()])

    def test_real_cuda_item_shape(self):
        it = S.cuda_item()
        if it is None:
            self.skipTest("CUDA 版の取得先を確かめていない")
        self.assertIsNone(S.problem(dict(it, unzip="zip")))   # 形は表の行と同じ検査に通る
        self.assertTrue(it["url"].startswith("https://"))


class FakeResp:
    def __init__(self, data, status=200):
        self.data, self.status, self.pos = data, status, 0

    def read(self, n):
        b = self.data[self.pos:self.pos + n]
        self.pos += len(b)
        return b

    def __enter__(self):
        return self

    def __exit__(self, *a):
        return False


class FakeOpener:
    def __init__(self, resp):
        self.resp, self.reqs = resp, []

    def open(self, req, timeout=None):
        self.reqs.append(req)
        r = self.resp(req) if callable(self.resp) else self.resp
        if isinstance(r, Exception):
            raise r
        return r


class HttpDownloaderTest(unittest.TestCase):
    def setUp(self):
        self.tmp = testkit.tempdir(self, "friendhttp-")
        self.part = os.path.join(self.tmp, "a", "x.part")

    def test_resume_with_range_or_restart_when_server_ignores_it(self):
        for have, resp, status, want in ((b"abc", b"defg", 206, b"abcdefg"), (b"zzz", b"whole", 200, b"whole")):
            with self.subTest(status=status):
                os.makedirs(os.path.dirname(self.part), exist_ok=True)
                with open(self.part, "wb") as f:
                    f.write(have)
                op = FakeOpener(FakeResp(resp, status))
                S.HttpDownloader(opener=op).get("https://h/x", self.part, 100, lambda n: None, lambda: False)
                self.assertEqual(op.reqs[0].get_header("Range"), "bytes=%d-" % len(have))
                with open(self.part, "rb") as f:
                    self.assertEqual(f.read(), want)

    def test_too_big_stops(self):
        with self.assertRaises(S.FetchError):
            S.HttpDownloader(opener=FakeOpener(FakeResp(b"x" * 600000))).get("https://h/x", self.part, 1000, lambda n: None, lambda: False)
        self.assertFalse(os.path.exists(self.part))

    def test_http_url_refused(self):
        with self.assertRaises(S.FetchError):
            S.HttpDownloader(opener=FakeOpener(FakeResp(b""))).get("http://h/x", self.part, 10, lambda n: None, lambda: False)

    def test_redirect_to_http_refused(self):
        import urllib.request
        h = S._HttpsOnly()
        req = urllib.request.Request("https://h/x")
        with self.assertRaises(S.FetchError):
            h.redirect_request(req, None, 302, "Found", {}, "http://evil/x")
        self.assertIsNotNone(h.redirect_request(req, None, 302, "Found", {}, "https://cdn/x"))

    def test_retries_then_fails(self):
        op = FakeOpener(OSError("切れた"))
        with self.assertRaises(S.FetchError):
            S.HttpDownloader(opener=op, wait=0).get("https://h/x", self.part, 10, lambda n: None, lambda: False)
        self.assertEqual(len(op.reqs), S.RETRIES)

    def test_cancel(self):
        with self.assertRaises(S.Cancelled):
            S.HttpDownloader(opener=FakeOpener(FakeResp(b"abc"))).get("https://h/x", self.part, 10, lambda n: None, lambda: True)


# ================================================================ 準備だけの画面の流れ(begin・view・done・awake)
class FlowTest(HomeBase):
    """本物のネット・本物の道具・本物の文字起こしは動かさない(偽の取り方・偽の run・偽の whisper)"""

    def setUp(self):
        super().setUp()
        self.model = b"model-bytes" * 5
        self.ffz = zbytes({"ffmpeg-9/bin/ffmpeg.exe": b"ff-exe", "ffmpeg-9/bin/ffprobe.exe": b"fp-exe", "ffmpeg-9/LICENSE": b"l"})
        self.ytd = b"ytdlp-exe"
        self.dnz = zbytes({"deno.exe": b"deno-exe"})
        self.files = {"https://h/model.bin": self.model, "https://h/ff.zip": self.ffz, "https://h/yt-dlp.exe": self.ytd, "https://h/deno.zip": self.dnz}
        self.items = [
            {"name": "whisper.cpp/large-v3", "file": "model.bin", "url": "https://h/model.bin", "size": len(self.model), "sha256": sha(self.model),
             "base": "data", "dest": "transcribe/models/whispercpp", "unzip": None},
            {"name": "ffmpeg", "file": "ff.zip", "url": "https://h/ff.zip", "size": len(self.ffz), "sha256": sha(self.ffz),
             "base": "app", "dest": "tools/ffmpeg", "unzip": "zip"},
            {"name": "yt-dlp", "file": "yt-dlp.exe", "url": "https://h/yt-dlp.exe", "size": len(self.ytd), "sha256": sha(self.ytd),
             "base": "app", "dest": "tools/yt-dlp", "unzip": None},
            {"name": "deno", "file": "deno.zip", "url": "https://h/deno.zip", "size": len(self.dnz), "sha256": sha(self.dnz),
             "base": "app", "dest": "tools/deno", "unzip": "zip"},
        ]
        self.write_fetch(self.items)
        self.dl = FakeDownloader(self.files)
        self.cmds = []                 # 偽の run が受けた命令
        self.bad_tool = None           # この名前を含む道具は終了コード 1
        self.whispered = []            # 偽の whisper が受けた機器
        self.whisper_ok = {"vulkan": True, "cuda": True}
        self.device = ["vulkan"]
        self.devices_set = []

    def hold_downloads(self):
        """取り方を gate が開くまで止める -> gate"""
        gate = threading.Event()
        orig = self.dl.get

        def slow(url, part, expect, progress, cancelled):
            gate.wait(5)
            return orig(url, part, expect, progress, cancelled)
        self.dl.get = slow
        return gate

    def fake_run(self, cmd, timeout):
        self.cmds.append(list(cmd))
        if "lavfi" in cmd:
            with open(cmd[-1], "wb") as f:
                f.write(b"RIFF....WAVE")
            return 0, "", None
        if self.bad_tool and self.bad_tool in os.path.basename(cmd[0]):
            return 1, "broken", None
        return 0, "tool version 1.2.3", None

    def whisper(self, device, data_root, wav):
        self.whispered.append(device)
        if not self.whisper_ok[device]:
            raise RuntimeError("Vulkan の機器がありません" if device == "vulkan" else "CUDA が動きません")

    def set_device(self, d):
        self.devices_set.append(d)
        self.device[0] = d

    def make(self, **kw):
        kw.setdefault("downloader", self.dl)
        kw.setdefault("disk_usage", lambda p: BIG)
        kw.setdefault("cuda", lambda: None)
        kw.setdefault("env", {})
        kw.setdefault("run", self.fake_run)
        kw.setdefault("whisper", self.whisper)
        kw.setdefault("set_device", self.set_device)
        kw.setdefault("device", lambda: self.device[0])
        return S.Setup(self.fetch, self.data, self.home, self.friend, **kw)

    def go(self, st):
        st.start()
        st.wait(10)
        return st.view()

    def cuda_item(self):
        blob = b"cuda-zip"
        self.files["https://h/c.zip"] = blob
        self.dl.files["https://h/c.zip"] = blob
        return {"name": S.CUDA_NAME, "file": "c.zip", "url": "https://h/c.zip", "sha256": sha(blob), "base": "data", "dest": "transcribe/bin",
                "unzip": "wcpp", "top": "", "member": "", "size": len(blob), "maxBytes": 0, "parts": []}

    def tool(self, *parts):
        return os.path.join(self.home, "tools", *parts)

    # ---- 全部通る
    def test_full_flow_places_checks_and_records(self):
        st = self.make()
        self.assertFalse(st.done)
        v = self.go(st)
        self.assertEqual((v["state"], v["percent"], v["error"]), ("done", 100, None))
        self.assertTrue(st.done)
        self.assertFalse(st.awake())
        # 浅く置いた(1 段下)・深い所は消えた
        for rel in (("ffmpeg", "ffmpeg.exe"), ("ffmpeg", "ffprobe.exe"), ("yt-dlp", "yt-dlp.exe"), ("deno", "deno.exe")):
            self.assertTrue(os.path.isfile(self.tool(*rel)), rel)
        self.assertFalse(os.path.exists(self.tool("ffmpeg", "ffmpeg-9")))
        self.assertEqual(st.env["YTT_FFMPEG"], self.tool("ffmpeg", "ffmpeg.exe"))
        self.assertEqual(st.env["YTT_DENO"], self.tool("deno", "deno.exe"))
        # 4 つの道具を 1 回ずつ + 短い音 + 文字起こし 1 回
        versions = [c[1] for c in self.cmds if len(c) == 2]
        self.assertEqual(sorted(versions), ["--version", "--version", "-version", "-version"])
        self.assertEqual(self.whispered, ["vulkan"])
        labels = [d["label"] for d in v["detail"]]
        self.assertIn("文字起こし(whisper.cpp)", labels)
        self.assertTrue(all(d["state"] == "done" for d in v["detail"]), v["detail"])
        with open(os.path.join(self.friend, "setup.json"), encoding="utf-8") as f:
            rec = json.load(f)
        self.assertEqual(rec["checked"]["device"], "vulkan")
        self.assertIn("ffmpeg", rec["items"])

    def test_second_start_does_not_check_again(self):
        self.go(self.make())
        self.cmds.clear()
        self.whispered.clear()
        self.dl.calls.clear()
        v = self.go(self.make())
        self.assertEqual(v["state"], "done")
        self.assertEqual((self.cmds, self.whispered, self.dl.calls), ([], [], []))

    def test_changed_tool_is_checked_again(self):
        self.go(self.make())
        self.cmds.clear()
        with open(self.tool("ffmpeg", "ffmpeg.exe"), "wb") as f:
            f.write(b"a-different-and-longer-ffmpeg")
        v = self.go(self.make())
        self.assertEqual(v["state"], "done")
        self.assertTrue(self.cmds)
        self.assertEqual(self.whispered, ["vulkan", "vulkan"])

    def test_no_fetch_json_is_done_at_once(self):
        os.remove(self.fetch)
        st = self.make()
        st.start()
        self.assertTrue(st.done)
        self.assertEqual(self.cmds, [])

    # ---- 失敗と続き
    def test_tool_failure_names_the_tool(self):
        self.bad_tool = "yt-dlp"
        st = self.make()
        v = self.go(st)
        self.assertEqual(v["state"], "failed")
        self.assertNotIn("yt-dlp", v["error"])   # 失敗の文に部品の名前は出さない(名前は詳しくの中)
        self.assertFalse(st.done)
        bad = [d for d in v["detail"] if d["state"] == "failed"]
        self.assertEqual([d["label"] for d in bad], ["配信を取る道具 yt-dlp"])
        self.assertIn("終了コード 1", bad[0]["text"])
        self.assertIsNotNone(st.block_reason())
        self.bad_tool = None
        self.dl.calls.clear()
        self.assertEqual(self.go(st)["state"], "done")   # [もう一度] = 取る物は残っていない・確かめ直す
        self.assertEqual(self.dl.calls, [])

    def test_download_failure_then_retry_continues(self):
        self.dl.fail["https://h/deno.zip"] = 99
        st = self.make()
        v = self.go(st)
        self.assertEqual(v["state"], "failed")
        self.assertIn("ネット", v["error"])
        self.assertNotIn("Deno", v["error"])   # 失敗の文に部品の名前は出さない
        self.assertIn("Deno", " ".join(d["label"] for d in v["detail"] if d["state"] == "failed"))
        self.assertEqual([d["state"] for d in v["detail"]], ["done", "done", "done", "failed"])
        self.dl.fail.clear()
        self.dl.calls.clear()
        v = self.go(st)
        self.assertEqual(v["state"], "done")
        self.assertEqual(self.dl.calls, ["https://h/deno.zip"])   # 取れた物は取り直さない

    def test_space_short_does_not_start(self):
        st = self.make(disk_usage=lambda p: Usage(100, 99, 1))
        v = self.go(st)
        self.assertEqual(v["state"], "need-space")
        self.assertIn("空きが足りません", v["message"])
        self.assertEqual(self.dl.calls, [])
        self.assertFalse(st.done)

    def test_cancel_stops_with_failed(self):
        gate = self.hold_downloads()
        st = self.make()
        st.start()
        self.assertTrue(st.awake())
        self.assertEqual(st.view()["state"], "fetching")
        st.cancel()
        gate.set()
        st.wait(10)
        self.assertEqual(st.view()["state"], "failed")
        self.assertFalse(st.awake())

    # ---- C への自動の切り替え
    def test_whisper_fails_on_a_then_c_works(self):
        self.whisper_ok["vulkan"] = False
        st = self.make(cuda=self.cuda_item, wcpp=lambda it, archive, root: None)
        with mock.patch.object(S, "_wcpp_ready", lambda root: False):
            v = self.go(st)
        self.assertEqual(v["state"], "done", v)
        self.assertEqual(self.whispered, ["vulkan", "cuda"])
        self.assertEqual(self.devices_set, ["cuda"])
        self.assertEqual(self.device[0], "cuda")
        names = {d["label"]: d for d in v["detail"]}
        self.assertEqual(names["文字起こし(whisper.cpp)"]["state"], "failed")      # A の失敗は詳しくに残る
        self.assertEqual(names["文字起こし(whisper.cpp) C"]["state"], "done")
        self.assertIn("https://h/c.zip", self.dl.calls)
        with open(os.path.join(self.friend, "setup.json"), encoding="utf-8") as f:
            self.assertEqual(json.load(f)["checked"]["device"], "cuda")

    def test_whisper_fails_on_both_goes_back_to_a(self):
        self.whisper_ok = {"vulkan": False, "cuda": False}
        st = self.make(cuda=self.cuda_item, wcpp=lambda it, archive, root: None)
        with mock.patch.object(S, "_wcpp_ready", lambda root: False):
            v = self.go(st)
        self.assertEqual(v["state"], "failed")
        self.assertIn("文字起こしが動きません", v["error"])
        self.assertEqual(self.devices_set, ["cuda", "vulkan"])
        self.assertEqual(self.device[0], "vulkan")
        texts = " ".join(d["text"] for d in v["detail"] if d["state"] == "failed")
        self.assertIn("CUDA が動きません", texts)
        self.assertIn("Vulkan の機器がありません", texts)
        self.assertFalse(st.done)

    def test_whisper_fails_and_no_cuda_part_known(self):
        self.whisper_ok["vulkan"] = False
        v = self.go(self.make())   # cuda = None(表に無い)
        self.assertEqual(v["state"], "failed")
        self.assertEqual(self.devices_set, [])

    def test_whisper_not_tried_when_ffmpeg_broken(self):
        self.bad_tool = "ffmpeg"
        v = self.go(self.make())
        self.assertEqual(v["state"], "failed")
        self.assertEqual(self.whispered, [])

    def test_device_c_failure_does_not_switch(self):
        self.device[0] = "cuda"
        self.whisper_ok["cuda"] = False
        v = self.go(self.make(cuda=lambda: None))
        self.assertEqual(v["state"], "failed")
        self.assertEqual(self.devices_set, [])

    # ---- エンジンの自動の選び(10-23)
    NV = {"name": "NVIDIA GeForce RTX 3060", "vramGB": 12.0, "vendor": "nvidia"}
    AMD = {"name": "AMD Radeon RX 6600", "vramGB": 8.0, "vendor": "amd"}

    def test_auto_nvidia_without_c_fetches_and_uses_c(self):
        """NVIDIA で C の部品が無い = A で確かめたあと C の部品を取って確かめ、C にする"""
        notes = []
        st = self.make(cuda=self.cuda_item, wcpp=lambda it, archive, root: None, gpu=lambda: self.NV)
        st.on_fail = lambda msg, detail: notes.append(msg)
        with mock.patch.object(S, "_wcpp_ready", lambda root: False):
            v = self.go(st)
        self.assertEqual(v["state"], "done", v)
        self.assertEqual((self.whispered, self.devices_set, self.device[0]), (["vulkan", "cuda"], ["cuda"], "cuda"))
        self.assertIn("https://h/c.zip", self.dl.calls)
        self.assertEqual(notes, [])
        # 2 回目の起動(部品あり・確かめ済み)= C のまま・確かめ直さない
        self.whispered.clear()
        with mock.patch.object(S, "_wcpp_ready", lambda root: True):
            v = self.go(self.make(cuda=self.cuda_item, gpu=lambda: self.NV))
        self.assertEqual((v["state"], self.whispered, self.device[0]), ("done", [], "cuda"))

    def test_auto_nvidia_c_fails_stays_a_and_notes(self):
        """C の部品を取っても動かない = A のまま済み・診断に 1 つ・この版では取り直さない"""
        self.whisper_ok["cuda"] = False
        notes = []
        st = self.make(cuda=self.cuda_item, wcpp=lambda it, archive, root: None, gpu=lambda: self.NV)
        st.on_fail = lambda msg, detail: notes.append((msg, detail))
        with mock.patch.object(S, "_wcpp_ready", lambda root: False):
            v = self.go(st)
        self.assertEqual(v["state"], "done", v)
        self.assertEqual((self.devices_set, self.device[0]), (["cuda", "vulkan"], "vulkan"))
        self.assertEqual(len(notes), 1)
        self.assertIn("A のまま", notes[0][0])
        self.assertIn("CUDA が動きません", notes[0][1])
        self.assertTrue(st.cuda_failed())
        self.whispered.clear()
        with mock.patch.object(S, "_wcpp_ready", lambda root: True):   # 部品は置いてあっても、この版では選ばない
            v = self.go(self.make(cuda=self.cuda_item, gpu=lambda: self.NV))
        self.assertEqual((v["state"], self.device[0], self.whispered), ("done", "vulkan", []))

    def test_auto_non_nvidia_goes_back_to_a(self):
        self.device[0] = "cuda"
        with mock.patch.object(S, "_wcpp_ready", lambda root: True):
            v = self.go(self.make(gpu=lambda: self.AMD))
        self.assertEqual((v["state"], self.devices_set, self.whispered), ("done", ["vulkan"], ["vulkan"]))

    def test_auto_nvidia_with_c_ready_uses_c_and_env_forces_a(self):
        with mock.patch.object(S, "_wcpp_ready", lambda root: True):
            v = self.go(self.make(cuda=self.cuda_item, gpu=lambda: self.NV))
            self.assertEqual((v["state"], self.device[0], self.whispered), ("done", "cuda", ["cuda"]))
            v = self.go(self.make(cuda=self.cuda_item, gpu=lambda: self.NV, env={S.ENGINE_ENV: "A"}))   # 逃げ道
        self.assertEqual((v["state"], self.device[0]), ("done", "vulkan"))

    def test_auto_unknown_gpu_keeps_device(self):
        def boom():
            raise OSError("nvidia-smi")
        self.device[0] = "cuda"
        with mock.patch.object(S, "_wcpp_ready", lambda root: True):
            v = self.go(self.make(cuda=self.cuda_item, gpu=boom))
        self.assertEqual((v["state"], self.devices_set, self.device[0]), ("done", [], "cuda"))

    # ---- 見た目の形
    def test_view_shape_while_fetching(self):
        gate = self.hold_downloads()
        st = self.make()
        st.start()
        for _ in range(100):
            if st.view()["totalBytes"]:
                break
            time.sleep(0.02)
        v = st.view()
        self.assertEqual(set(v), {"state", "percent", "remainSec", "totalBytes", "doneBytes", "message", "detail", "error"})
        self.assertEqual(v["state"], "fetching")
        self.assertIsNone(v["remainSec"])
        self.assertEqual(v["totalBytes"], sum(S.expect(i) for i in self.items))
        self.assertTrue(v["message"])
        self.assertEqual(len(v["detail"]), 4)
        gate.set()
        st.wait(10)
        self.assertTrue(st.done)
        self.assertIsNone(st.block_reason())


if __name__ == "__main__":
    unittest.main()
