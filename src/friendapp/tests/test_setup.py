"""src/friendapp/setup.py(初回の取得。F2-5)のテスト。本物のネットには出ない(偽の取り方)。リポジトリ直下で: py -3.10 -m unittest src/friendapp/tests/test_setup.py"""
import hashlib
import io
import json
import os
import shutil
import sys
import tarfile
import tempfile
import threading
import unittest
import zipfile
from collections import namedtuple

os.environ.setdefault("YTT_DATA_DIR", "inplace")
SRC = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
if SRC not in sys.path:
    sys.path.insert(0, SRC)
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


class SetupTest(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.mkdtemp(prefix="friendsetup-")
        self.addCleanup(shutil.rmtree, self.tmp, True)
        self.home = os.path.join(self.tmp, "home")
        self.data = os.path.join(self.home, "data")
        self.friend = os.path.join(self.data, "app", "friendapp")
        os.makedirs(self.friend)
        self.fetch = os.path.join(self.home, "fetch.json")
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

    def write_fetch(self, items):
        with open(self.fetch, "w", encoding="utf-8") as f:
            json.dump({"schema": "youtube-tools-friend-fetch/v1", "version": "0.93.0", "items": items}, f)

    def make(self, **kw):
        kw.setdefault("downloader", self.dl)
        kw.setdefault("disk_usage", lambda p: BIG)
        kw.setdefault("cuda", lambda: None)
        st = S.Setup(self.fetch, self.data, self.home, self.friend, **kw)
        st.checked = True
        return st

    def run_setup(self, st, only=None):
        st.start(only)
        st.wait(10)
        return st.result

    # ---- 表
    def test_load_refuses_bad_rows(self):
        for bad in ({"url": "http://h/model.bin"}, {"dest": "../x"}, {"dest": "C:/x"}, {"file": "a/b"}, {"sha256": "zz"}, {"base": "other"},
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
        self.assertIn("https", st.view()["error"])
        self.assertIsNone(st.block_reason())

    def test_no_fetch_json_means_inactive(self):
        st = S.Setup(None, self.data, self.home, self.friend)
        st.checked = True
        self.assertEqual(st.missing(), [])
        self.assertIsNone(st.block_reason())
        self.assertEqual(st.view()["count"], 0)

    # ---- 取る
    def test_fetch_all_and_done(self):
        st = self.make()
        self.assertEqual(len(st.missing()), 4)
        self.assertIn("足りません", st.block_reason())
        v = st.view()
        self.assertTrue(v["canStart"])
        self.assertEqual(v["total"], sum(S.expect(S.parse_item(i)) for i in self.items))
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
            self.assertEqual(f.read(), sha(self.tool))   # 目印(今の送るアプリと同じ名前)
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

    def test_existing_marker_from_old_app_is_kept(self):
        """今の送るアプリが取って目印を置いた物は取り直さない・目印の sha256 が違えば足りない"""
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
        self.assertEqual(st.view()["result"]["failed"][0]["name"], "whisper.cpp/large-v3")

    def test_failure_does_not_stop_others(self):
        self.dl.fail["https://h/ffmpeg.zip"] = 1
        res = self.run_setup(self.make())
        self.assertEqual([f["name"] for f in res["failed"]], ["ffmpeg"])
        self.assertEqual(len(res["done"]), 3)

    def test_cancel_keeps_part(self):
        gate = threading.Event()
        started = threading.Event()

        class Slow(FakeDownloader):
            def get(self, url, part, expect, progress, cancelled):
                os.makedirs(os.path.dirname(part), exist_ok=True)
                with open(part, "ab") as f:
                    f.write(b"m")
                started.set()
                gate.wait(5)
                if cancelled():
                    raise S.Cancelled()
        st = self.make(downloader=Slow(self.files))
        st.start()
        started.wait(5)
        self.assertTrue(st.running())
        self.assertIn("取っています", st.block_reason())
        with self.assertRaises(ValueError):
            st.start()   # 2 つ目は断る
        st.cancel()
        gate.set()
        st.wait(5)
        self.assertTrue(st.result["cancelled"])
        self.assertTrue(os.path.isfile(os.path.join(self.data, "transcribe", "models", "whispercpp", "model.bin.part")))

    def test_space_short_refuses(self):
        st = self.make(disk_usage=lambda p: Usage(100, 99, 1))
        v = st.view()
        self.assertFalse(v["canStart"])
        self.assertIn("空きが足りません", v["reason"])
        with self.assertRaises(ValueError):
            st.start()
        self.assertEqual(self.dl.calls, [])

    def test_not_checked_waits(self):
        st = self.make()
        st.checked = False   # 古い部品を写している間は見せない・始めない・送るも止めない
        self.assertEqual(st.view(), {"active": False})
        self.assertIsNone(st.block_reason())
        with self.assertRaises(ValueError):
            st.start()

    def test_later_and_reopen(self):
        st = self.make()
        st.defer()
        self.assertTrue(st.view()["later"])
        st.reopen()
        self.assertFalse(st.view()["later"])

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
        self.tmp = tempfile.mkdtemp(prefix="friendhttp-")
        self.addCleanup(shutil.rmtree, self.tmp, True)
        self.part = os.path.join(self.tmp, "a", "x.part")

    def test_resume_with_range(self):
        os.makedirs(os.path.dirname(self.part))
        with open(self.part, "wb") as f:
            f.write(b"abc")
        op = FakeOpener(FakeResp(b"defg", 206))
        S.HttpDownloader(opener=op).get("https://h/x", self.part, 100, lambda n: None, lambda: False)
        self.assertEqual(op.reqs[0].get_header("Range"), "bytes=3-")
        with open(self.part, "rb") as f:
            self.assertEqual(f.read(), b"abcdefg")

    def test_server_ignores_range_restarts(self):
        os.makedirs(os.path.dirname(self.part))
        with open(self.part, "wb") as f:
            f.write(b"zzz")
        S.HttpDownloader(opener=FakeOpener(FakeResp(b"whole", 200))).get("https://h/x", self.part, 100, lambda n: None, lambda: False)
        with open(self.part, "rb") as f:
            self.assertEqual(f.read(), b"whole")

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


if __name__ == "__main__":
    unittest.main()
