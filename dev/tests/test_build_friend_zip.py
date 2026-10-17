# -*- coding: utf-8 -*-
"""dev/build_friend_zip.py(友人の PC に配る zip を作る。F1 の F4a)のテスト。ネットは使わない(偽のキャッシュ・取る関数は差し替えて呼ばれたら落とす)。
展開した zip の src で入口(server.py --headless の形)と CLI が import で落ちないことも、この PC の Python で確かめる。
実行(リポジトリ直下): py -3.10 -m unittest dev/tests/test_build_friend_zip.py"""
import os
os.environ.setdefault("YTT_DATA_DIR", "inplace")   # サーバーは子プロセスで --help だけ。全テストの決まりに合わせる
import hashlib
import json
import shutil
import subprocess
import sys
import tempfile
import unittest
import zipfile

TESTS = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.dirname(TESTS))
import build_friend_zip as B  # noqa: E402
from pipeline.transcribe import diarize as D, tx_engines as E  # noqa: E402
from ytt import version as V  # noqa: E402

PTH = "python310.zip\r\n.\r\n\r\n# Uncomment to run site.main() automatically\r\n#import site\r\n"


def _sha(b):
    return hashlib.sha256(b).hexdigest()


def _no_fetch(*a, **k):
    raise AssertionError("ネットへ取りに行った: %r" % (a,))


def _zip(path, files):
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with zipfile.ZipFile(path, "w") as z:
        for n, b in files.items():
            z.writestr(n, b)


def _record(path):
    with open(path, "rb") as f:
        b = f.read()
    with open(path + ".sha256.json", "w", encoding="utf-8") as f:
        json.dump({"url": "https://example.invalid/", "size": len(b), "sha256": _sha(b)}, f)


def make_cache(root):
    """偽のキャッシュ: 埋め込み用 Python・wheel 3 つ(.data の置き場所の付け替えも)・道具 3 つ"""
    cache = os.path.join(root, "cache")
    emb = os.path.join(cache, "python", B.PY_EMBED["file"])
    _zip(emb, {"python.exe": b"MZfake", "python310._pth": PTH, "python310.zip": b"PK"})
    _record(emb)
    wdir = os.path.join(cache, "wheels")
    _zip(os.path.join(wdir, "numpy-2.2.6-cp310-cp310-win_amd64.whl"),
         {"numpy/__init__.py": "x = 1\n", "numpy-2.2.6.dist-info/METADATA": "Name: numpy\n"})
    _zip(os.path.join(wdir, "sherpa_onnx-1.13.8-cp310-cp310-win_amd64.whl"),
         {"sherpa_onnx/__init__.py": "", "sherpa_onnx-1.13.8.data/platlib/sherpa_onnx_core.pyd": b"MZ",
          "sherpa_onnx-1.13.8.data/scripts/sherpa-onnx.exe": b"MZ"})
    _zip(os.path.join(wdir, "streamlink-8.6.1-py3-none-any.whl"), {"streamlink/__init__.py": ""})
    reqs = B.wheel_pins()
    files = {}
    for n in sorted(os.listdir(wdir)):
        with open(os.path.join(wdir, n), "rb") as f:
            files[n] = _sha(f.read())
    with open(os.path.join(wdir, "wheels.lock.json"), "w", encoding="utf-8") as f:
        json.dump({"requirements": reqs, "files": files}, f)
    for t in B.TOOLS:
        p = os.path.join(cache, "tools", t["file"])
        os.makedirs(os.path.dirname(p), exist_ok=True)
        with open(p, "wb") as f:
            f.write(b"fake " + t["name"].encode())
        _record(p)
    return cache


def make_wcpp(root):
    d = os.path.join(root, "wcpp")
    os.makedirs(d)
    files = {}
    for n in (E.WCPP_EXE, "ggml.dll", "ggml-vulkan.dll"):
        b = ("fake " + n).encode()
        with open(os.path.join(d, n), "wb") as f:
            f.write(b)
        files[n] = _sha(b)
    with open(os.path.join(d, "extra-not-listed.txt"), "w") as f:
        f.write("not in build.json")
    with open(os.path.join(d, "build.json"), "w", encoding="utf-8") as f:
        json.dump({"version": E.WHISPER_CPP["version"], "commit": E.WHISPER_CPP["commit"], "backend": "vulkan", "files": files}, f)
    return d


def make_app(root, key=True):
    build = os.path.join(root, "app-build")
    src = os.path.join(root, "app-src")
    os.makedirs(build)
    os.makedirs(src)
    for n, b in (("RequestSender.exe", b"MZapp"), ("members.json", b"[]"), ("version.txt", (V.VERSION + "\r\n").encode())):
        with open(os.path.join(build, n), "wb") as f:
            f.write(b)
    with open(os.path.join(src, "README.txt"), "w", encoding="utf-8") as f:
        f.write("readme\n")
    if key:
        with open(os.path.join(src, "config.json"), "w", encoding="utf-8") as f:
            f.write('{"fake": "FAKE-short"}')
    return build, src


def make_launcher(root, exe=True):
    d = os.path.join(root, "launcher-build")
    os.makedirs(d)
    if exe:
        for dll in B.LAUNCHER_DLLS:
            with open(os.path.join(d, dll), "wb") as f:
                f.write(b"dll")
        with open(os.path.join(d, "FriendApp.exe"), "wb") as f:
            f.write(b"MZlauncher")
    return d


class Base(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.mkdtemp(prefix="bfz-")
        self.addCleanup(shutil.rmtree, self.tmp, ignore_errors=True)
        self.cache = make_cache(self.tmp)
        self.wcpp = make_wcpp(self.tmp)
        self.app_build, self.app_src = make_app(self.tmp)
        self.launcher = make_launcher(self.tmp)
        self.out = os.path.join(self.tmp, "out")

    def build(self, **kw):
        kw.setdefault("fetcher", _no_fetch)
        kw.setdefault("downloader", _no_fetch)
        kw.setdefault("app_src", self.app_src)
        kw.setdefault("launcher_build", self.launcher)
        return B.build(self.out, self.cache, self.wcpp, self.app_build, **kw)


class BuildTest(Base):
    def test_update_zip_contents(self):
        got = self.build(notes="n")
        name = "RequestSender-%s.zip" % V.VERSION
        self.assertEqual(os.path.basename(got["zip"]), name)
        with open(os.path.join(self.out, "latest.json"), encoding="utf-8") as f:
            latest = json.load(f)
        self.assertEqual((latest["version"], latest["file"], latest["size"], latest["sha256"], latest["notes"]),
                         (V.VERSION, name, got["size"], got["sha256"], "n"))
        with zipfile.ZipFile(got["zip"]) as z:
            names = set(z.namelist())
            man = json.loads(z.read("manifest.json"))
            for n, sha in man["files"].items():   # manifest の SHA-256 が中身と一致する
                self.assertEqual(_sha(z.read(n)), sha, n)
            pth = z.read("python/python310._pth").decode()
        self.assertEqual(set(man["files"]) | {"manifest.json"}, names)
        self.assertEqual(man["version"], V.VERSION)
        self.assertFalse(man["withKey"])
        self.assertNotIn("config.json", names)   # 鍵は既定で入れない(f1g)
        self.assertNotIn("inbox.bat", names)   # 仮の入口は窓 FriendApp.exe に替わった
        for n in ("RequestSender.exe", "FriendApp.exe", "WebView2Loader.dll", "Microsoft.Web.WebView2.Core.dll", "Microsoft.Web.WebView2.WinForms.dll",
                  B.INSTALL_NAME, "members.json", "README.txt", "fetch.json",
                  "src/friendapp/server.py", "src/friendapp/streams.py", "src/friendapp/ui/friend.html", "src/friendapp/ui/host.js", "src/friendapp/ui/setup.html",
                  "src/friendapp/ui/guide.html", "src/app/server.py", "src/app/cli.py", "src/ytt/version.py",
                  "python/Lib/site-packages/numpy/__init__.py", "python/Lib/site-packages/sherpa_onnx_core.pyd"):
            self.assertIn(n, names)
        self.assertFalse(any("/tests/" in n or "__pycache__" in n or n.endswith(".pyc") for n in names))
        self.assertFalse(any(n.endswith("sherpa-onnx.exe") for n in names))   # wheel の scripts は捨てる
        wsub = "tools/" + os.path.basename(E.wcpp_bin_dir(""))
        self.assertIn(wsub + "/" + E.WCPP_EXE, names)
        self.assertIn(wsub + "/build.json", names)
        self.assertNotIn(wsub + "/extra-not-listed.txt", names)
        self.assertEqual(pth.split("\r\n")[-4:], ["Lib\\site-packages", "..\\src", "import site", ""])
        self.assertNotIn("#import site", pth)
        self.assertNotIn("ingest/data", " ".join(names))   # 追跡外の作業データは入らない

    def test_fetch_json_reads_the_tables(self):
        got = self.build()
        with zipfile.ZipFile(got["zip"]) as z:
            items = {i["name"]: i for i in json.loads(z.read("fetch.json"))["items"]}
        for name, s in E.WCPP_MODELS.items():
            i = items["whisper.cpp/" + name]
            self.assertEqual((i["url"], i["size"], i["sha256"], i["base"]), (s["url"], s["size"], s["sha256"], "data"))
            self.assertEqual(i["dest"], "transcribe/models/whispercpp")
        i = items["llama.cpp/" + E.LLAMA_CPP["version"]]
        self.assertEqual((i["sha256"], i["unzip"], i["dest"]), (E.LLAMA_CPP["sha256"], "zip", "transcribe/bin/llama.cpp-%s-vulkan" % E.LLAMA_CPP["version"]))
        for name, s in E.LLAMA_TEXT_MODELS.items():
            self.assertEqual(items["llm/" + name]["sha256"], s["model"]["sha256"])
        for name, s in E.SENSE_VOICE_MODELS.items():
            self.assertEqual((items["sensevoice/" + name]["sha256"], items["sensevoice/" + name]["top"]), (s["sha256"], s["dir"]))
        self.assertEqual(items["diar/segmentation"]["sha256"], D.DIAR_SEG["sha256"])
        self.assertEqual(items["diar/segmentation"]["member"], D.DIAR_SEG["member"])
        self.assertEqual(items["diar/" + D.DIAR_EMB_DEFAULT]["sha256"], D.DIAR_EMBS[D.DIAR_EMB_DEFAULT]["sha256"])
        self.assertEqual(items["diar/segmentation"]["dest"], "transcribe/models/diar")
        for t in B.TOOLS:   # 道具はキャッシュの記録の値
            with open(os.path.join(self.cache, "tools", t["file"] + ".sha256.json"), encoding="utf-8") as f:
                rec = json.load(f)
            self.assertEqual((items[t["name"]]["sha256"], items[t["name"]]["base"]), (rec["sha256"], "app"))
        for i in items.values():
            self.assertTrue(i["url"].startswith("https://"), i["name"])
            self.assertRegex(i["sha256"], r"^[0-9a-f]{64}$")

    def test_extracted_src_imports(self):
        """外した後も ② の headless(server.py)と CLI が import で落ちない(展開した src だけを読む)"""
        got = self.build()
        app = os.path.join(self.tmp, "friend", "RequestSender")
        with zipfile.ZipFile(got["zip"]) as z:
            z.extractall(app)
        data = os.path.join(self.tmp, "friend-data")
        os.makedirs(data)
        env = {k: v for k, v in os.environ.items() if not k.startswith("PYTHON")}
        env.update(YTT_DATA_DIR=data, PYTHONIOENCODING="utf-8")
        for script in ("server.py", "cli.py"):
            r = subprocess.run([sys.executable, "-E", "-s", "-B", os.path.join(app, "src", "app", script), "--help"], cwd=self.tmp, env=env,
                               capture_output=True, timeout=120, creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0))
            self.assertEqual(r.returncode, 0, r.stderr.decode("utf-8", "replace")[-2000:])
            if script == "server.py":
                self.assertIn("--headless", r.stdout.decode("utf-8", "replace"))

    def test_first_with_key(self):
        with self.assertRaises(B.BuildError):
            self.build(with_key=True)   # 更新の zip に鍵は入れない
        got = self.build(first=True, with_key=True)
        self.assertTrue(got["zip"].endswith("-first.zip"))
        self.assertFalse(os.path.exists(os.path.join(self.out, "latest.json")))
        with zipfile.ZipFile(got["zip"]) as z:
            self.assertIn("config.json", z.namelist())
            self.assertTrue(json.loads(z.read("manifest.json"))["withKey"])
        got = self.build(first=True)
        with zipfile.ZipFile(got["zip"]) as z:
            self.assertNotIn("config.json", z.namelist())

    def test_cli_rejects_key_without_first(self):
        with self.assertRaises(SystemExit) as cm:
            B.main(["--with-key", "--out", self.out])
        self.assertEqual(cm.exception.code, 2)

    def test_required_src_is_tracked(self):
        B.check_src()   # 新しいアプリの必須の物(REQUIRED_SRC)が git に入っている
        self.assertTrue(set(B.REQUIRED_SRC) <= set(B.src_files()))
        self.assertFalse(any("FriendInbox" in n for n in B.REQUIRED_SRC))

    def test_default_out_refuses_without_out(self):
        with self.assertRaisesRegex(B.BuildError, "--out"):
            B.default_out(False)   # Dropbox の 更新\ へは黙って置かない
        self.assertEqual(os.path.basename(B.default_out(True, False)), "dist")
        self.assertEqual(B.main([]), 1)
        with self.assertRaises(SystemExit) as cm:
            B.main(["--publish", "--out", self.out])
        self.assertEqual(cm.exception.code, 2)

    def test_launcher_rebuilt_when_missing_or_old(self):
        src = os.path.join(self.tmp, "launcher-src")
        os.makedirs(os.path.join(src, "src"))
        cs = os.path.join(src, "src", "A.cs")
        with open(cs, "w") as f:
            f.write("x")
        b = os.path.join(src, "build")
        calls = []

        def rebuild(launcher_src):
            calls.append(launcher_src)
            shutil.copytree(self.launcher, b, dirs_exist_ok=True)
        stage = tempfile.mkdtemp(dir=self.tmp)
        B.lay_launcher(stage, b, src, rebuild)           # 無い -> 作る
        self.assertEqual(calls, [src])
        os.utime(cs, (os.path.getmtime(b) + 100,) * 2)   # C# が新しい -> 作り直す
        B.lay_launcher(stage, b, src, rebuild)
        self.assertEqual(len(calls), 2)
        old = os.path.getmtime(cs) + 100
        os.utime(os.path.join(b, "FriendApp.exe"), (old, old))   # exe が新しい -> 流さない
        B.lay_launcher(stage, b, src, rebuild)
        self.assertEqual(len(calls), 2)
        for n in (B.LAUNCHER_EXE,) + B.LAUNCHER_DLLS:
            self.assertTrue(os.path.isfile(os.path.join(stage, n)))

    def test_launcher_exe_missing_stops(self):
        os.remove(os.path.join(self.launcher, "FriendApp.exe"))
        with self.assertRaisesRegex(B.BuildError, "launcher/build.bat"):
            self.build()

    def test_app_version_must_match(self):
        with open(os.path.join(self.app_build, "version.txt"), "w") as f:
            f.write("0.0.1")
        with self.assertRaisesRegex(B.BuildError, "build.bat"):
            self.build()

    def test_app_rebuilt_when_old(self):
        src = os.path.join(self.tmp, "app2")
        shutil.copytree(self.app_src, src)
        b = os.path.join(src, "build")
        shutil.rmtree(b, ignore_errors=True)
        shutil.copytree(self.app_build, b)
        with open(os.path.join(b, "version.txt"), "w") as f:
            f.write("0.0.1")
        calls = []

        def rebuild(app_src):
            calls.append(app_src)
            with open(os.path.join(b, "version.txt"), "w") as f:
                f.write(B._version.VERSION)
        stage = tempfile.mkdtemp(dir=self.tmp)
        B.lay_app(stage, b, False, app_src=src, rebuild=rebuild)
        self.assertEqual(calls, [src])
        self.assertTrue(os.path.isfile(os.path.join(stage, "RequestSender.exe")))

    def test_prune_keeps_two(self):
        os.makedirs(self.out)
        for v in ("0.9.0", "0.10.0", "0.8.5"):
            open(os.path.join(self.out, "RequestSender-%s.zip" % v), "wb").close()
        open(os.path.join(self.out, "other.zip"), "wb").close()
        B.prune(self.out)
        self.assertEqual(sorted(os.listdir(self.out)), ["RequestSender-0.10.0.zip", "RequestSender-0.9.0.zip", "other.zip"])


class CacheTest(Base):
    def test_tampered_cache_stops(self):
        with open(os.path.join(self.cache, "python", B.PY_EMBED["file"]), "ab") as f:
            f.write(b"x")
        with self.assertRaisesRegex(B.BuildError, "記録と違います"):
            self.build()

    def test_no_fetch_and_fetch(self):
        os.remove(os.path.join(self.cache, "tools", B.TOOLS[1]["file"]))
        with self.assertRaisesRegex(B.BuildError, "no-fetch"):
            self.build(fetch=False)
        calls = []

        def fetcher(url, dest):
            calls.append(url)
            with open(dest, "wb") as f:
                f.write(b"downloaded")

        got = self.build(fetcher=fetcher)
        self.assertEqual(calls, [B.TOOLS[1]["url"]])
        with zipfile.ZipFile(got["zip"]) as z:
            items = {i["name"]: i for i in json.loads(z.read("fetch.json"))["items"]}
        self.assertEqual(items[B.TOOLS[1]["name"]]["sha256"], _sha(b"downloaded"))

    def test_wheels_refetch_when_requirements_change(self):
        lock = os.path.join(self.cache, "wheels", "wheels.lock.json")
        with open(lock, encoding="utf-8") as f:
            rec = json.load(f)
        rec["requirements"] = ["numpy==0.0.1"]
        with open(lock, "w", encoding="utf-8") as f:
            json.dump(rec, f)
        seen = []

        def downloader(reqs, folder):
            seen.append(list(reqs))
            _zip(os.path.join(folder, "numpy-2.2.6-cp310-cp310-win_amd64.whl"), {"numpy/__init__.py": ""})

        self.build(downloader=downloader)
        self.assertEqual(seen, [B.wheel_pins()])

    def test_wcpp_mismatch(self):
        with open(os.path.join(self.wcpp, "ggml.dll"), "ab") as f:
            f.write(b"x")
        with self.assertRaisesRegex(B.BuildError, "ggml.dll"):
            self.build()

    def test_unsafe_zip_name(self):
        bad = os.path.join(self.tmp, "bad.zip")
        _zip(bad, {"../evil.txt": "x"})
        with self.assertRaises(B.BuildError):
            B.unzip_into(bad, os.path.join(self.tmp, "x"))


class AuditTest(unittest.TestCase):
    def setUp(self):
        self.stage = tempfile.mkdtemp(prefix="bfz-audit-")
        self.addCleanup(shutil.rmtree, self.stage, ignore_errors=True)
        os.makedirs(os.path.join(self.stage, "src", "ytt"))
        os.makedirs(os.path.join(self.stage, "python"))

    def put(self, rel, text):
        p = os.path.join(self.stage, *rel.split("/"))
        os.makedirs(os.path.dirname(p), exist_ok=True)
        with open(p, "w", encoding="utf-8") as f:
            f.write(text)

    def test_clean(self):
        self.put("src/ytt/a.py", "x = 'C:/Users/<ユーザー名>/x'\n")
        self.put("python/settings.json", "{}")   # python/ は公式の配布物 = 見ない
        self.assertEqual(B.audit(self.stage, False, home="C:\\Users\\alice", user="alice"), [])

    def test_finds_key_names_and_paths(self):
        self.put("config.json", "{}")
        self.put("src/ytt/transcripts/x.json", "{}")
        self.put("src/ytt/b.py", "p = r'C:\\Users\\alice\\AppData'\n")
        self.put("src/ytt/c.json", '{"p": "C:\\\\Users\\\\alice\\\\x"}')
        bad = B.audit(self.stage, False, home="C:\\Users\\alice", user="alice")
        self.assertEqual(sorted(bad), sorted(["個人データ・鍵の名前: config.json", "個人データ・鍵の名前: src/ytt/transcripts/x.json",
                                              "個人のパス: src/ytt/b.py", "個人のパス: src/ytt/c.json"]))
        self.assertNotIn("個人データ・鍵の名前: config.json", B.audit(self.stage, True, home="C:\\Users\\alice", user="alice"))

    def test_real_src_is_clean(self):
        """本物の src(git の管理分・tests なし)に個人データの名前・この PC の家のパスが無い"""
        B.lay_src(self.stage)
        self.assertEqual(B.audit(self.stage, False), [])


class PinsTest(unittest.TestCase):
    def test_pins_from_requirements(self):
        pins = B.wheel_pins()
        self.assertEqual([p.split("==")[0] for p in pins], list(B.WHEEL_NAMES))
        self.assertTrue(all("==" in p for p in pins))


if __name__ == "__main__":
    unittest.main()
