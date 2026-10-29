# -*- coding: utf-8 -*-
"""dev/build_friend_zip.py(友人の PC に配る zip を作る。F1 の F4a)のテスト。ネットは使わない(偽のキャッシュ・取る関数は差し替えて呼ばれたら落とす)。
展開した zip の src で友人のアプリ(friendapp/server.py)が import で落ちないことも、この PC の Python で確かめる。
実行(リポジトリ直下): py -3.12 -m unittest tests/dev/test_build_friend_zip.py"""
import os
os.environ.setdefault("YTT_DATA_DIR", "inplace")   # サーバーは子プロセスで --help だけ。全テストの決まりに合わせる
import hashlib
import json
import shutil
import subprocess
import sys
import tempfile
import unittest
from unittest import mock
import zipfile

TESTS = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.join(os.path.dirname(os.path.dirname(TESTS)), "dev"))
import build_friend_zip as B  # noqa: E402
from pipeline.transcribe import diarize as D, separate as SEP, tx_engines as E  # noqa: E402
from ytt import version as V  # noqa: E402
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))   # tests/(testkit)
import testkit  # noqa: E402

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


def _record(path, url):
    with open(path, "rb") as f:
        b = f.read()
    with open(path + ".sha256.json", "w", encoding="utf-8") as f:
        json.dump({"url": url, "size": len(b), "sha256": _sha(b)}, f)


def make_cache(root):
    """偽のキャッシュ: 埋め込み用 Python・wheel 3 つ(.data の置き場所の付け替えも)・道具 3 つ"""
    cache = os.path.join(root, "cache")
    emb = os.path.join(cache, "python", B.PY_EMBED["file"])
    _zip(emb, {"python.exe": b"MZfake", "python310._pth": PTH, "python310.zip": b"PK"})
    _record(emb, B.PY_EMBED["url"])
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
        json.dump({"requirements": reqs, "python": B.PY_TAG, "files": files}, f)
    for t in B.TOOLS:
        p = os.path.join(cache, "tools", t["file"])
        os.makedirs(os.path.dirname(p), exist_ok=True)
        with open(p, "wb") as f:
            f.write(b"fake " + t["name"].encode())
        _record(p, t["url"])
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


def make_inputs(root, key=True):
    """名簿(members.json)と鍵(config.json)の偽物。本物の名簿・鍵は読まない"""
    members = os.path.join(root, "members-src.json")
    with open(members, "w", encoding="utf-8") as f:
        f.write('{"members": []}')
    keyp = os.path.join(root, "key-src.json")
    if key:
        with open(keyp, "w", encoding="utf-8") as f:
            f.write('{"fake": "FAKE-short"}')
    return members, keyp


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


# 表の公式の大きさ・SHA-256(yt-dlp)は、偽の道具では合わないので外す(照らす所は CacheTest で別に確かめる)
FAKE_TOOLS = tuple({k: v for k, v in t.items() if k not in ("size", "sha256")} for t in B.TOOLS)


class Base(unittest.TestCase):
    def setUp(self):
        patcher = mock.patch.object(B, "TOOLS", FAKE_TOOLS)
        patcher.start()
        self.addCleanup(patcher.stop)
        self.tmp = testkit.tempdir(self, "bfz-")
        self.cache = make_cache(self.tmp)
        self.wcpp = make_wcpp(self.tmp)
        self.members, self.key = make_inputs(self.tmp)
        self.launcher = make_launcher(self.tmp)
        self.out = os.path.join(self.tmp, "out")

    def build(self, **kw):
        kw.setdefault("fetcher", _no_fetch)
        kw.setdefault("downloader", _no_fetch)
        kw.setdefault("members_src", self.members)
        kw.setdefault("key_src", self.key)
        kw.setdefault("launcher_build", self.launcher)
        return B.build(self.out, self.cache, self.wcpp, **kw)


class BuildTest(Base):
    @classmethod
    def setUpClass(cls):
        """既定の更新の zip(notes="n")を 1 回だけ作る。中を読むだけのテストはこれを使う(1 回 4〜5 秒かかるので)"""
        cls.shared_tmp = tempfile.mkdtemp(prefix="bfz-shared-")
        with mock.patch.object(B, "TOOLS", FAKE_TOOLS):
            cls.shared_cache = make_cache(cls.shared_tmp)
            members, key = make_inputs(cls.shared_tmp)
            cls.shared_out = os.path.join(cls.shared_tmp, "out")
            cls.shared = B.build(cls.shared_out, cls.shared_cache, make_wcpp(cls.shared_tmp), fetcher=_no_fetch, downloader=_no_fetch,
                                 members_src=members, key_src=key, launcher_build=make_launcher(cls.shared_tmp), notes="n")

    @classmethod
    def tearDownClass(cls):
        shutil.rmtree(cls.shared_tmp, ignore_errors=True)

    def test_update_zip_contents(self):
        got = self.shared   # = self.build(notes="n")
        name = "FriendApp-%s.zip" % V.VERSION
        self.assertEqual(os.path.basename(got["zip"]), name)
        with open(os.path.join(self.shared_out, "latest.json"), encoding="utf-8") as f:
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
        self.assertNotIn("handoff", man)
        for n in ("README.txt", "friend-defaults.json", "guide.html"):
            self.assertNotIn(n, names)                 # 直下に置くのは決めた物だけ
        self.assertNotIn("config.json", names)   # 鍵は既定で入れない(f1g)
        self.assertNotIn("inbox.bat", names)   # 仮の入口は窓 FriendApp.exe に替わった
        for n in ("FriendApp.exe", "WebView2Loader.dll", "Microsoft.Web.WebView2.Core.dll", "Microsoft.Web.WebView2.WinForms.dll",
                  B.INSTALL_NAME, "members.json", "fetch.json",
                  "src/friendapp/server.py", "src/friendapp/streams.py", "src/friendapp/ui/friend.html", "src/friendapp/ui/host.js", "src/friendapp/ui/setup.html",
                  "src/friendapp/ui/guide.html", "src/flow/run.py", "src/pipeline/transcribe/diarize.py", "src/ytt/version.py",
                  "python/Lib/site-packages/numpy/__init__.py", "python/Lib/site-packages/sherpa_onnx_core.pyd"):
            self.assertIn(n, names)
        self.assertFalse(any("/tests/" in n or "__pycache__" in n or n.endswith(".pyc") for n in names))
        layers = {n.split("/")[1] for n in names if n.startswith("src/")}
        self.assertEqual(layers, set(B.FRIEND_LAYERS))   # 友人のアプリが読む層だけ(入口 app・編集・人・管理・評価・スタジオ・cut2resolve は入らない)
        self.assertIn("src/pipeline/transcribe/hololive-roster.json", names)   # 名簿は ① の層と一緒に入る(友人のアプリが作業データへ写す)
        self.assertFalse(any(n.endswith("sherpa-onnx.exe") for n in names))   # wheel の scripts は捨てる
        wsub = "tools/" + os.path.basename(E.wcpp_bin_dir(""))
        self.assertIn(wsub + "/" + E.WCPP_EXE, names)
        self.assertIn(wsub + "/build.json", names)
        self.assertNotIn(wsub + "/extra-not-listed.txt", names)
        self.assertEqual(pth.split("\r\n")[-4:], ["Lib\\site-packages", "..\\src", "import site", ""])
        self.assertNotIn("#import site", pth)
        self.assertNotIn("ingest/data", " ".join(names))   # 追跡外の作業データは入らない

    def test_light_zip_has_no_python_or_tools_and_same_manifest(self):
        got = self.shared
        lname = "FriendApp-%s-light.zip" % V.VERSION
        self.assertEqual(os.path.basename(got["light"]["zip"]), lname)
        with open(os.path.join(self.shared_out, "latest.json"), encoding="utf-8") as f:
            latest = json.load(f)
        self.assertEqual(latest["light"], {"file": lname, "size": got["light"]["size"], "sha256": got["light"]["sha256"]})
        self.assertEqual(latest["file"], "FriendApp-%s.zip" % V.VERSION)   # file は全部入りのまま
        self.assertEqual(B.sha256_file(got["light"]["zip"]), got["light"]["sha256"])
        with zipfile.ZipFile(got["zip"]) as zf, zipfile.ZipFile(got["light"]["zip"]) as zl:
            full, light = set(zf.namelist()), set(zl.namelist())
            mf, ml = json.loads(zf.read("manifest.json")), json.loads(zl.read("manifest.json"))
            self.assertEqual(light, {n for n in full if not n.startswith(B.LIGHT_SKIP)})
            self.assertTrue({"FriendApp.exe", "WebView2Loader.dll", "fetch.json", "members.json", "manifest.json", "src/friendapp/server.py"} <= light)
            for n in light - {"manifest.json"}:
                self.assertEqual(zl.read(n), zf.read(n), n)
        self.assertEqual(ml["files"], mf["files"])   # python/・tools/ のハッシュも含む
        self.assertTrue(ml["light"])
        self.assertNotIn("light", mf)
        self.assertLess(got["light"]["size"], got["size"])

    def test_fetch_json_reads_the_tables(self):
        got = self.shared   # 既定の build()(notes は fetch.json に入らない)
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
        for name, s in SEP.SEP_MODELS.items():   # 声の分離(10-22)
            self.assertEqual((items["sep/" + name]["sha256"], items["sep/" + name]["dest"]), (s["sha256"], "transcribe/models/sep"))
        self.assertEqual(items["diar/segmentation"]["sha256"], D.DIAR_SEG["sha256"])
        self.assertEqual(items["diar/segmentation"]["member"], D.DIAR_SEG["member"])
        self.assertEqual(items["diar/" + D.DIAR_EMB_DEFAULT]["sha256"], D.DIAR_EMBS[D.DIAR_EMB_DEFAULT]["sha256"])
        self.assertEqual(items["diar/" + D.VOICE_EMB]["sha256"], D.DIAR_EMBS[D.VOICE_EMB]["sha256"])   # 声の名前付けのモデル(10-22)
        self.assertEqual(items["diar/segmentation"]["dest"], "transcribe/models/diar")
        for t in B.TOOLS:   # 道具はキャッシュの記録の値
            with open(os.path.join(self.shared_cache, "tools", t["file"] + ".sha256.json"), encoding="utf-8") as f:
                rec = json.load(f)
            self.assertEqual((items[t["name"]]["sha256"], items[t["name"]]["base"]), (rec["sha256"], "app"))
        from friendapp import setup as FS
        for i in items.values():
            self.assertTrue(i["url"].startswith("https://"), i["name"])
            self.assertRegex(i["sha256"], r"^[0-9a-f]{64}$")
            self.assertIsNone(FS.problem(FS.parse_item(i)), i["name"])   # 友人の PC が取る(取り先が FETCH_HOSTS の中)

    def test_extracted_src_imports(self):
        """展開した src だけで友人のアプリの入口(friendapp/server.py)が import で落ちない"""
        got = self.shared
        app = os.path.join(self.tmp, "friend", "FriendApp")
        with zipfile.ZipFile(got["zip"]) as z:
            z.extractall(app)
        data = os.path.join(self.tmp, "friend-data")
        os.makedirs(data)
        env = {k: v for k, v in os.environ.items() if not k.startswith("PYTHON")}
        env.update(YTT_DATA_DIR=data, PYTHONIOENCODING="utf-8")
        r = subprocess.run([sys.executable, "-E", "-s", "-B", os.path.join(app, "src", "friendapp", "server.py"), "--help"], cwd=self.tmp, env=env,
                           capture_output=True, timeout=120, creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0))
        self.assertEqual(r.returncode, 0, r.stderr.decode("utf-8", "replace")[-2000:])

    def test_first_with_key(self):
        with self.assertRaises(B.BuildError):
            self.build(with_key=True)   # 更新の zip に鍵は入れない
        got = self.build(first=True, with_key=True)
        self.assertTrue(got["zip"].endswith("-first.zip"))
        self.assertFalse(os.path.exists(os.path.join(self.out, "latest.json")))
        self.assertIsNone(got["light"])   # --first は全部入りだけ
        self.assertEqual(os.path.basename(got["zip"]), "FriendApp-%s-first.zip" % V.VERSION)
        with zipfile.ZipFile(got["zip"]) as z:
            self.assertIn("config.json", z.namelist())
            self.assertEqual(z.read("config.json"), b'{"fake": "FAKE-short"}')
            self.assertTrue(json.loads(z.read("manifest.json"))["withKey"])
        got = self.build(first=True)
        with zipfile.ZipFile(got["zip"]) as z:
            self.assertNotIn("config.json", z.namelist())

    def test_members_copied_from_source(self):
        got = self.shared   # 名簿の写し元は make_inputs の同じ中身
        with zipfile.ZipFile(got["zip"]) as z:
            self.assertEqual(z.read("members.json"), b'{"members": []}')
        os.remove(self.members)
        with self.assertRaisesRegex(B.BuildError, "members.json|members-src"):
            self.build()

    def test_with_key_without_key_file_stops(self):
        os.remove(self.key)
        with self.assertRaisesRegex(B.BuildError, "dropbox_auth"):
            self.build(first=True, with_key=True)

    def test_cli_rejects_key_without_first(self):
        with self.assertRaises(SystemExit) as cm:
            B.main(["--with-key", "--out", self.out])
        self.assertEqual(cm.exception.code, 2)

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

    def test_prune_keeps_three_full_and_ten_light(self):
        os.makedirs(self.out)
        full = ["0.9.0", "0.10.0", "0.8.5", "0.8.4", "0.7.0"]
        light = ["0.%d.0" % n for n in range(1, 14)]
        for v in full:
            open(os.path.join(self.out, "FriendApp-%s.zip" % v), "wb").close()
        for v in light:
            open(os.path.join(self.out, "FriendApp-%s-light.zip" % v), "wb").close()
        open(os.path.join(self.out, "FriendApp-0.1.0-first.zip"), "wb").close()
        open(os.path.join(self.out, "other.zip"), "wb").close()
        gone = B.prune(self.out)
        left = sorted(os.listdir(self.out))
        self.assertEqual([n for n in left if not n.endswith("-light.zip")], ["FriendApp-0.1.0-first.zip", "FriendApp-0.10.0.zip", "FriendApp-0.8.5.zip", "FriendApp-0.9.0.zip", "other.zip"])
        self.assertEqual(len([n for n in left if n.endswith("-light.zip")]), B.KEEP_LIGHT)
        self.assertNotIn("FriendApp-0.1.0-light.zip", left)   # 軽いのは新しい順に 10 版(0.4.0 以降)
        self.assertIn("FriendApp-0.4.0-light.zip", left)
        self.assertEqual(len(gone), 2 + 3)

    def test_versions_json_rows_newest_first_and_nulled_when_zip_pruned(self):
        os.makedirs(self.out)

        def add(v, size):
            for n in ("FriendApp-%s.zip" % v, "FriendApp-%s-light.zip" % v):
                with open(os.path.join(self.out, n), "wb") as f:
                    f.write(b"x" * size)
            row = {"version": v, "builtAt": "2026-10-21T00:00:00", "notes": "n", "file": "FriendApp-%s.zip" % v, "size": size, "sha256": "a" * 64,
                   "light": {"file": "FriendApp-%s-light.zip" % v, "size": size, "sha256": "b" * 64}, "runtime": "c" * 64}
            B.update_versions(self.out, row)
            B.prune(self.out)

        for n in range(1, 6):
            add("0.99.%d" % (60 + n), n)
        with open(os.path.join(self.out, "versions.json"), encoding="utf-8") as f:
            doc = json.load(f)
        self.assertEqual(doc["v"], 1)
        self.assertEqual([r["version"] for r in doc["versions"]], ["0.99.65", "0.99.64", "0.99.63", "0.99.62", "0.99.61"])
        have = [r["file"] is not None for r in doc["versions"]]
        self.assertEqual(have, [True, True, True, False, False])   # 全部入りは 3 版
        self.assertTrue(all(r["light"] is not None for r in doc["versions"]))   # 軽いのは 10 版
        self.assertEqual(doc["versions"][3]["sha256"], "a" * 64)   # 行は残る
        for n in range(6, 30):
            add("0.99.%d" % (60 + n), 1)
        with open(os.path.join(self.out, "versions.json"), encoding="utf-8") as f:
            doc = json.load(f)
        self.assertEqual(len(doc["versions"]), B.KEEP_ROWS)
        self.assertEqual(doc["versions"][0]["version"], "0.99.89")
        self.assertIsNone(doc["versions"][-1]["light"])
        with open(os.path.join(self.out, "versions.json"), "w", encoding="utf-8") as f:
            f.write("{broken")
        B.update_versions(self.out, doc["versions"][0])   # 壊れた台帳は作り直す
        with open(os.path.join(self.out, "versions.json"), encoding="utf-8") as f:
            self.assertEqual(len(json.load(f)["versions"]), 1)

    def test_withdraw_moves_zips_and_rolls_latest_back(self):
        """配った版の取り下げ: zip は手元へ移す(消さない)・台帳から消す・latest.json は前の良い版へ"""
        os.makedirs(self.out)
        for v in ("0.99.91", "0.99.92"):
            for n in ("FriendApp-%s.zip" % v, "FriendApp-%s-light.zip" % v):
                with open(os.path.join(self.out, n), "wb") as f:
                    f.write(b"x")
            row = {"version": v, "builtAt": "", "notes": "", "file": "FriendApp-%s.zip" % v, "size": 1, "sha256": "a" * 64,
                   "light": {"file": "FriendApp-%s-light.zip" % v, "size": 1, "sha256": "b" * 64}, "runtime": "c" * 64}
            B.update_versions(self.out, row)
            testkit.write_json(os.path.join(self.out, "latest.json"), {"version": v, "file": row["file"], "size": 1, "sha256": "a" * 64, "notes": "", "light": row["light"]})
        keep = os.path.join(self.tmp, "withdrawn")
        self.assertEqual(B.withdraw(self.out, "0.99.92", keep), "0.99.91")
        self.assertEqual(sorted(os.listdir(keep)), ["FriendApp-0.99.92-light.zip", "FriendApp-0.99.92.zip"])
        self.assertFalse(any("0.99.92" in n for n in os.listdir(self.out)))
        with open(os.path.join(self.out, "versions.json"), encoding="utf-8") as f:
            self.assertEqual([r["version"] for r in json.load(f)["versions"]], ["0.99.91"])
        with open(os.path.join(self.out, "latest.json"), encoding="utf-8") as f:
            latest = json.load(f)
        self.assertEqual((latest["version"], latest["file"], latest["light"]["file"]), ("0.99.91", "FriendApp-0.99.91.zip", "FriendApp-0.99.91-light.zip"))
        self.assertIn("cancel", latest)   # 取り消した版を友人のアプリが捨てる印(問題 5)

    def test_wheel_python_mismatch_stops(self):
        """埋め込みの Python(python310._pth)と違う cpXY の wheel では作らない(0.99.92 = 3.10 と cp312)"""
        bad = os.path.join(self.tmp, "x-1.0-cp312-cp312-win_amd64.whl")
        _zip(bad, {"x/__init__.py": ""})
        with self.assertRaises(B.BuildError):
            B.lay_python(os.path.join(self.tmp, "stage-bad"), os.path.join(self.cache, "python", B.PY_EMBED["file"]), [bad])

    def test_runtime_mark_follows_python_files_only(self):
        a = {"python/python.exe": "1" * 64, "python/x.pyd": "2" * 64, "src/a.py": "3" * 64}
        self.assertEqual(B.runtime_mark(a), B.runtime_mark(dict(a, **{"src/a.py": "4" * 64})))
        self.assertNotEqual(B.runtime_mark(a), B.runtime_mark(dict(a, **{"python/x.pyd": "5" * 64})))

    def test_build_writes_versions_row(self):
        with open(os.path.join(self.shared_out, "versions.json"), encoding="utf-8") as f:
            rows = json.load(f)["versions"]
        self.assertEqual(rows[0]["version"], V.VERSION)
        self.assertEqual(rows[0]["file"], "FriendApp-%s.zip" % V.VERSION)
        self.assertEqual(rows[0]["light"]["file"], "FriendApp-%s-light.zip" % V.VERSION)
        self.assertEqual(len(rows[0]["runtime"]), 64)
        with open(os.path.join(self.shared_out, "latest.json"), encoding="utf-8") as f:
            self.assertEqual(sorted(json.load(f)), ["file", "light", "notes", "sha256", "size", "version"])   # 友人が読む latest.json に欄を足さない


class CacheTest(Base):

    def test_official_hash_mismatch_stops(self):
        item = dict(FAKE_TOOLS[1], size=len(b"fake yt-dlp"), sha256="0" * 64)
        with self.assertRaisesRegex(B.BuildError, "公式の SHA-256 と違います"):
            B.cached(self.cache, "tools", item, False)
        item["sha256"] = _sha(b"fake yt-dlp")
        self.assertEqual(B.cached(self.cache, "tools", item, False)[1]["sha256"], item["sha256"])

    def test_new_version_url_refetches(self):
        item = dict(FAKE_TOOLS[1], url="https://example.invalid/2099.01.01/yt-dlp.exe")
        with self.assertRaisesRegex(B.BuildError, "別の版"):
            B.cached(self.cache, "tools", item, False)
        calls = []

        def fetcher(url, dest):
            calls.append(url)
            with open(dest, "wb") as f:
                f.write(b"new")

        path, got = B.cached(self.cache, "tools", item, True, fetcher=fetcher)
        self.assertEqual((calls, got["sha256"]), ([item["url"]], _sha(b"new")))

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
            raise B.BuildError("取りに行く所で止める")

        with self.assertRaises(B.BuildError):
            self.build(downloader=downloader)
        self.assertEqual(seen, [B.wheel_pins()])

    def test_old_certifi_stops_build(self):
        """古い認証局の一覧(certifi が CERTIFI_MIN より前)の wheel では作らない・新しい版と certifi の無い組は通る"""
        with self.assertRaisesRegex(B.BuildError, "certifi 2026.7.22"):
            B.check_certifi(["x/certifi-2026.7.22-py3-none-any.whl", "x/numpy-2.2.6-cp312-cp312-win_amd64.whl"])
        B.check_certifi(["x/certifi-2026.10.19-py3-none-any.whl"])
        B.check_certifi(["x/numpy-2.2.6-cp312-cp312-win_amd64.whl"])

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
        self.stage = testkit.tempdir(self, "bfz-audit-")
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

    def test_finds_gone_tool_names(self):
        """前の友人のアプリの名前(dev/spec_check.GONE)が配る文に残っていたら止める"""
        self.put("FriendApp-はじめに.txt", "前の Request" + "Sender から移る\n")
        self.put("src/friendapp/ui/a.js", "// 送る" + "アプリと同じ\n")
        self.put("src/friendapp/ui/b.js", "// 今の形\n")
        bad = B.audit(self.stage, False, home="C:\\Users\\alice", user="alice")
        self.assertEqual(sorted(bad), ["消した道具の名前: FriendApp-はじめに.txt", "消した道具の名前: src/friendapp/ui/a.js"])


class UpdateMarkTest(unittest.TestCase):
    def test_mark(self):
        """「重要」の印と直す対象(友人のアプリの更新の決め): 付けなければ欄を書かない・形が違えば断る"""
        self.assertEqual(B.update_mark(), {})
        self.assertEqual(B.update_mark(True, ["20261025-010203-abcdef"], [2, 1, 2]),
                         {"important": True, "fixes": {"requests": ["20261025-010203-abcdef"], "kinds": [1, 2]}})
        for bad in (["x"], None), (None, [8]):
            with self.assertRaises(B.BuildError):
                B.update_mark(False, *bad)

    def test_rollback_marker(self):
        """戻す印(問題 4): 診断/戻して/ に {v, id, at, to, why}。prev は to = None・形の違う版は断る"""
        d = tempfile.mkdtemp()
        try:
            p = B.rollback(d, None, "起動しない", now=1792900000.0)
            self.assertEqual(os.path.dirname(p), os.path.join(d, "診断", "戻して"))
            with open(p, encoding="utf-8") as f:
                got = json.load(f)
            self.assertEqual((got["v"], got["to"], got["why"], got["id"] + ".rollback.json"), (1, None, "起動しない", os.path.basename(p)))
            self.assertEqual(json.load(open(B.rollback(d, "0.99.240", now=1792900001.0), encoding="utf-8"))["to"], "0.99.240")
            with self.assertRaises(B.BuildError):
                B.rollback(d, "latest")
        finally:
            shutil.rmtree(d, ignore_errors=True)

    def test_queue_and_publish_exceptions(self):
        """ふだんは --queue で積むだけ・--publish は配る回(--from-queue)か種類 4・2 の --important だけ(まとめて配る決め)"""
        from human.friend import pubqueue
        d = tempfile.mkdtemp()
        try:
            with mock.patch.object(B.datadir, "locate", return_value=d):
                self.assertEqual(B.main(["--queue", "--note", "直した"]), 0)
                self.assertEqual([x["note"] for x in pubqueue.items(d)], ["直した"])
                for argv in (["--queue"], ["--publish"], ["--publish", "--important", "--fix-kind", "1"], ["--from-queue"]):
                    with self.assertRaises(SystemExit):
                        B.main(argv)
        finally:
            shutil.rmtree(d, ignore_errors=True)

    def test_history_in_latest(self):
        """配った後の latest.json に最近の更新(changes のある版・新しい順)と python/ の印"""
        d = tempfile.mkdtemp()
        try:
            with open(os.path.join(d, "latest.json"), "w", encoding="utf-8") as f:
                json.dump({"version": "0.99.3", "file": "x.zip"}, f)
            with open(os.path.join(d, B.VERSIONS_NAME), "w", encoding="utf-8") as f:
                json.dump({"versions": [{"version": "0.99.3", "publishedAt": 3, "changes": ["録画が止まるのを直しました"], "runtime": "r3"},
                                        {"version": "0.99.2", "publishedAt": 2}, {"version": "0.99.1", "publishedAt": 1, "changes": ["a", "b"]}]}, f)
            got = B.add_history(d)
            self.assertEqual(got["history"], [{"v": "0.99.3", "at": 3, "items": ["録画が止まるのを直しました"]}, {"v": "0.99.1", "at": 1, "items": ["a", "b"]}])
            self.assertEqual(got["runtime"], "r3")
        finally:
            shutil.rmtree(d, ignore_errors=True)

if __name__ == "__main__":
    unittest.main()
