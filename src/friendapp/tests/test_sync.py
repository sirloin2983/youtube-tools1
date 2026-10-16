"""src/friendapp/sync.py のテスト(本物の Dropbox につながない = 偽の io。受信箱は本物の一時フォルダ)。
リポジトリ直下で: py -3.10 -m unittest src/friendapp/tests/test_sync.py"""
import hashlib
import io
import json
import os
import shutil
import sys
import tempfile
import time
import unittest
import zipfile

os.environ.setdefault("YTT_DATA_DIR", "inplace")
SRC = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
if SRC not in sys.path:
    sys.path.insert(0, SRC)
from friendapp import dropbox as D, inbox as I, sync as S  # noqa: E402

RID = "20261016-100000-abcdef"
AUTO = "20261016-110000-123456"
NOW = float(int(time.time()))
FORM = {"url": "https://www.youtube.com/watch?v=dQw4w9WgXcQ", "videoId": "dQw4w9WgXcQ", "ranges": [[10.0, 70.0], [100.0, 160.0]], "top": None,
        "streamer": "星見ルナ", "people": ["ゲスト"], "videoTracks": 2, "deliverBatch": 5, "useWeights": False, "weights": None,
        "title": "題", "channel": "ch", "pc": "user"}


class FakeIo:
    """Dropbox のアプリのフォルダの偽物(パスは小文字で引く)。fail = {パス: DropboxError}"""

    def __init__(self, clock):
        self.files = {}
        self.clock = clock
        self.fail = {}
        self.deleted = []
        self.n = 0

    def put(self, path, data, age=0.0):
        self.n += 1
        self.files[path.lower()] = {"path": path, "data": bytes(data), "rev": "rev%d" % self.n, "mtime": self.clock() - age}

    def data(self, path):
        f = self.files.get(path.lower())
        return f and f["data"]

    def _check(self, path):
        e = self.fail.get(path)
        if e:
            raise e

    def list_folder(self, folder):
        pre = folder.lower().rstrip("/") + "/"
        out = []
        for k, f in self.files.items():
            if k.startswith(pre) and "/" not in k[len(pre):]:
                t = time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime(f["mtime"]))
                out.append({".tag": "file", "name": f["path"].rsplit("/", 1)[1], "path_lower": k, "rev": f["rev"], "size": len(f["data"]),
                            "server_modified": t, "content_hash": D_hash(f["data"])})
        return out if out or any(k.startswith(pre) for k in self.files) else None

    def get_metadata(self, path):
        f = self.files.get(path.lower())
        return {"name": f["path"]} if f else None

    def read_small(self, path, cap=1024 * 1024):
        self._check(path)
        d = self.data(path)
        return None if d is None else (d[:cap], len(d) > cap)

    def download(self, path, part, rev=None, progress=None):
        self._check(path)
        d = self.data(path)
        if d is None:
            return False
        with open(part, "wb") as f:
            f.write(d)
        return True

    def upload(self, local, path, overwrite=False, progress=None):
        self._check(path)
        with open(local, "rb") as f:
            self.put(path, f.read())
        return path.rsplit("/", 1)[1]

    def upload_bytes(self, data, path, overwrite=False):
        self._check(path)
        self.put(path, data)
        return path.rsplit("/", 1)[1]

    def delete(self, path):
        self.deleted.append(path)
        return self.files.pop(path.lower(), None) is not None


def D_hash(data):
    """Dropbox の content_hash(4MB の塊 1 つ)"""
    return hashlib.sha256(hashlib.sha256(data).digest()).hexdigest() if data else hashlib.sha256(b"").hexdigest()


def zip_bytes(entries):
    b = io.BytesIO()
    with zipfile.ZipFile(b, "w") as z:
        for name, data in entries.items():
            z.writestr(name, data)
    return b.getvalue()


class SyncTest(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.mkdtemp(prefix="friendsync-")
        self.addCleanup(shutil.rmtree, self.tmp, True)
        self.t = [NOW]
        self.places = {"home": os.path.join(self.tmp, "home"), "data": os.path.join(self.tmp, "data"),
                       "friend": os.path.join(self.tmp, "data", "app", "friendapp"), "outbox": os.path.join(self.tmp, "data", "app", "outbox"),
                       "cases": os.path.join(self.tmp, "作業"), "save": lambda: os.path.join(self.tmp, "save")}
        for k in ("home", "friend", "cases"):
            os.makedirs(self.places[k], exist_ok=True)
        self.box = I.Inbox(os.path.join(self.places["friend"], "inbox.json"), self.places["outbox"], self.places["save"],
                           lambda: self.places["cases"], clock=self.clock)
        self.io = FakeIo(self.clock)
        self.form = {"deliverBatch": 5}
        self.applied = []
        self.env = {}
        self.sync = S.Sync(self.places, self.box, lambda: self.form, client_factory=lambda cfg, cancelled: self.io, clock=self.clock,
                           env=self.env, apply_learning=lambda ld: self.applied.append(ld) or True, version="0.90.0")

    def clock(self):
        return self.t[0]

    def key(self):
        with open(os.path.join(self.places["home"], "config.json"), "w", encoding="utf-8") as f:
            json.dump({"appKey": "k", "refreshToken": "r"}, f)

    def verdict(self, rid, name):
        with open(os.path.join(self.places["outbox"], "%s__%s.verdict.json" % (rid, name)), encoding="utf-8") as f:
            return json.load(f)

    def run_sync(self):
        got = self.sync.run_once()
        self.assertIsNotNone(got)
        return got

    # ------------------------------------------------------------ 鍵
    def test_no_key_does_nothing(self):
        self.assertIsNone(self.sync.run_once())
        st = self.sync.status()
        self.assertFalse(st["key"])
        self.assertIn("Dropbox の鍵がありません", st["message"])
        self.assertEqual(self.io.files, {})

    # ------------------------------------------------------------ ユーザーの PC に頼む(A-2)
    def test_request_upload_accept_and_wait(self):
        self.key()
        self.box.add(RID, FORM, {"title": "題"}, pc="user")
        self.assertEqual(self.run_sync(), [])
        doc = json.loads(self.io.data("/%s.request.json" % RID).decode("utf-8"))
        self.assertEqual(list(doc), ["v", "kind", "id", "flow", "items", "streamer", "speakers", "videoTracks", "cut", "deliverBatch", "sentAt"])
        self.assertEqual(doc["items"], [{"url": FORM["url"], "top": 2, "ranges": [{"start": 10.0, "end": 70.0}, {"start": 100.0, "end": 160.0}]}])
        self.assertEqual(doc["speakers"]["names"], ["星見ルナ", "ゲスト"])
        self.assertEqual((doc["id"], doc["deliverBatch"], doc["videoTracks"], doc["cut"]), (RID, 5, 2, "none"))
        self.assertEqual(self.box.row(RID)["remote"]["state"], "uploaded")
        v = self.box.view()[0]
        self.assertFalse(v["canLocal"])
        self.t[0] += 3700   # 1 時間読まれない = [この PC でやり直す]
        v = self.box.view()[0]
        self.assertTrue(v["canLocal"])
        self.assertEqual(v["waitHours"], 1)
        self.run_sync()   # まだ直下にある = 待ちのまま
        self.assertEqual(self.box.row(RID)["state"], "sent")
        del self.io.files[("/%s.request.json" % RID).lower()]   # ユーザーの PC が受付済みへ移した
        self.run_sync()
        r = self.box.row(RID)
        self.assertEqual((r["state"], r["remote"]["state"]), ("making", "accepted"))
        self.assertNotIn("canLocal", self.box.view()[0])

    def test_withdraw(self):
        self.key()
        self.box.add(RID, FORM, {"title": "題"}, pc="user")
        self.assertTrue(self.sync.withdraw(RID))   # まだ上げていない
        self.run_sync()
        self.assertTrue(self.sync.withdraw(RID))
        self.assertIsNone(self.io.data("/%s.request.json" % RID))
        self.box.remote_mark(RID, "accepted")
        self.assertFalse(self.sync.withdraw(RID))

    def test_deliver_prefs_only_when_changed(self):
        self.key()
        self.run_sync()
        doc = json.loads(self.io.data(S.DELIVER_PREFS))
        self.assertEqual((doc["v"], doc["deliverBatch"]), (1, 5))
        self.io.files.clear()
        self.run_sync()
        self.assertIsNone(self.io.data(S.DELIVER_PREFS))
        self.form["deliverBatch"] = 1
        self.run_sync()
        self.assertEqual(json.loads(self.io.data(S.DELIVER_PREFS))["deliverBatch"], 1)

    # ------------------------------------------------------------ /出力/ の取り込み
    def put_group(self, rid, origin="auto", n=2, pack_data=None):
        zips = []
        for i in range(1, n + 1):
            name = "%s__見どころ %d.zip" % (rid, i)
            self.io.put("/出力/" + name, pack_data or zip_bytes({"見どころ %d_pack/clip.mp4" % i: b"v" * 10, "見どころ %d_pack/a.lua" % i: b"x"}))
            zips.append(name)
        pv = "%s__朝活 1-%d.preview.mp4" % (rid, n)
        self.io.put("/出力/" + pv, b"MP4")
        g = {"v": 1, "title": "朝活", "range": "1-%d" % n, "preview": pv, "origin": origin,
             "packs": [{"n": i + 1, "zip": z, "title": "見どころ %d" % (i + 1), "previewStart": 0, "duration": 30.5} for i, z in enumerate(zips)]}
        self.io.put("/出力/%s__朝活 1-%d.group.json" % (rid, n), json.dumps(g).encode("utf-8"))
        return zips

    def test_group_import_preview_reject_keep_cleanup_and_returns(self):
        self.key()
        zips = self.put_group(AUTO)
        self.run_sync()
        r = self.box.row(AUTO)
        self.assertEqual((r["origin"], r["pc"], r["state"]), ("auto", "auto", "arrived"))
        self.assertEqual([p["remote"]["zip"] for p in r["packs"]], zips)
        self.assertTrue(r["groups"][0]["preview"] and os.path.isfile(r["groups"][0]["preview"]))
        self.assertIs(self.box.view()[0]["groups"][0]["preview"], True)   # 画面には手元のパスを出さない
        self.run_sync()   # 2 回目は取り込み直さない
        self.assertEqual(len(self.box.row(AUTO)["packs"]), 2)
        names = [p["name"] for p in r["packs"]]
        got = self.box.decide(AUTO, [names[0]], "reject")   # 要らない = 取らない
        self.assertEqual(got["done"], [names[0]])
        got = self.box.decide(AUTO, [names[1]], "keep")
        self.assertEqual((got["done"], got["pending"]), ([], [names[1]]))
        v = self.verdict(AUTO, names[0])
        self.assertEqual((v["verdict"], v["zip"], v["origin"], v["requestId"]), ("reject", zips[0], "auto", AUTO))
        self.run_sync()
        r = self.box.row(AUTO)
        self.assertEqual(r["state"], "done")
        saved = r["packs"][1]["savedTo"]
        self.assertEqual(os.path.basename(saved), "見どころ 2_pack")
        self.assertTrue(os.path.isfile(os.path.join(saved, "clip.mp4")))
        self.assertTrue(r["groups"][0]["remote"]["cleaned"])
        self.assertEqual([k for k in self.io.files if k.startswith("/出力/")], [])   # zip・まとめ動画・組の一覧を消した
        sent = sorted(k for k in self.io.files if k.startswith("/送り返し/"))
        self.assertEqual(len(sent), 2)
        self.assertEqual(os.listdir(self.places["outbox"]), [])   # 上げたら消す
        self.assertFalse(os.path.exists(r["groups"][0]["preview"]))

    def test_partial_group_waits_then_imports(self):
        self.key()
        zips = self.put_group(AUTO, n=3)
        del self.io.files[("/出力/" + zips[2]).lower()]
        self.run_sync()
        self.assertIsNone(self.box.row(AUTO))
        self.t[0] += S.GROUP_WAIT + 1
        self.run_sync()
        self.assertEqual(len(self.box.row(AUTO)["packs"]), 2)

    def test_single_to_requested_row_and_meta_origin(self):
        self.key()
        self.box.add(RID, FORM, {"title": "題"}, pc="user")
        self.run_sync()
        self.io.put("/出力/%s__見どころ.zip" % RID, zip_bytes({"見どころ_pack/a.mp4": b"v"}))
        self.io.put("/出力/%s__見どころ.preview.mp4" % RID, b"MP4")
        self.run_sync()
        r = self.box.row(RID)
        self.assertEqual((r["state"], r["pc"], r["origin"], len(r["packs"]), r["remote"]["state"]), ("arrived", "user", "request", 1, "done"))
        self.assertTrue(r["groups"][0]["preview"])
        self.io.put("/出力/%s__自動.meta.json" % AUTO, json.dumps({"v": 1, "origin": "auto", "sentAt": "x"}).encode())
        self.io.put("/出力/%s__自動.zip" % AUTO, zip_bytes({"自動_pack/a.mp4": b"v"}))
        self.run_sync()
        a = self.box.row(AUTO)
        self.assertEqual((a["origin"], a["packs"][0]["remote"]["meta"]), ("auto", "%s__自動.meta.json" % AUTO))

    def test_lone_zip_waits_for_group_list(self):
        self.key()
        self.io.put("/出力/%s__見どころ 1.zip" % AUTO, b"z")
        self.run_sync()
        self.assertIsNone(self.box.row(AUTO))
        self.t[0] += S.SINGLE_WAIT + 1
        self.run_sync()
        self.assertEqual(len(self.box.row(AUTO)["packs"]), 1)

    def test_failure_text(self):
        self.key()
        self.box.add(RID, FORM, {"title": "題"}, pc="user")
        self.run_sync()
        self.io.put("/出力/%s__題.失敗.txt" % RID, "\ufeff配信を取れませんでした\r\n非公開です".encode("utf-8"))
        self.run_sync()
        r = self.box.row(RID)
        self.assertEqual(r["state"], "failed")
        self.assertEqual(r["error"], "配信を取れませんでした\n非公開です")
        self.assertIsNone(self.io.data("/出力/%s__題.失敗.txt" % RID))
        self.io.put("/出力/%s__x.失敗.txt" % AUTO, b"no row")
        self.run_sync()
        self.assertEqual(self.box.row(AUTO)["state"], "failed")

    def test_bad_names_are_ignored(self):
        self.key()
        for n in ("../%s__x.zip" % AUTO, ".%s__x.zip" % AUTO, "%s__a:b.zip" % AUTO, "readme.txt", "CON.zip"):
            self.io.files[("/出力/" + n).lower()] = {"path": "/出力/" + n, "data": b"z", "rev": "r", "mtime": 0}
        self.run_sync()
        self.assertEqual(self.box.rows, [])

    def test_keep_refuses_zip_slip_and_broken(self):
        self.key()
        self.put_group(AUTO, n=1, pack_data=zip_bytes({"../evil.txt": b"x"}))
        self.run_sync()
        name = self.box.row(AUTO)["packs"][0]["name"]
        self.box.decide(AUTO, [name], "keep")
        self.run_sync()
        p = self.box.row(AUTO)["packs"][0]
        self.assertIsNone(p["verdict"])
        self.assertIn("展開できませんでした", p["error"])
        self.assertFalse(os.path.exists(os.path.join(self.tmp, "evil.txt")))
        self.assertEqual(os.listdir(os.path.join(self.tmp, "save")), [])
        f = self.io.files[("/出力/" + p["remote"]["zip"]).lower()]
        f["data"] = b"changed"   # 一覧の hash と違う = 壊れていた
        with self.box.lock:
            self.box.row(AUTO)["packs"][0]["remote"]["hash"] = "0" * 64
        self.box.decide(AUTO, [name], "keep")
        self.run_sync()
        self.assertIn("壊れていました", self.box.row(AUTO)["packs"][0]["error"])

    def test_keep_retries_when_offline(self):
        self.key()
        zips = self.put_group(AUTO, n=1)
        self.run_sync()
        name = self.box.row(AUTO)["packs"][0]["name"]
        self.box.decide(AUTO, [name], "keep")
        self.io.fail["/出力/" + zips[0]] = D.DropboxError("つながりません", 0)
        probs = self.run_sync()
        self.assertTrue(any(p.startswith("受け取る") for p in probs))
        self.assertEqual(self.box.row(AUTO)["packs"][0]["want"], "keep")   # 押したまま次の回へ
        del self.io.fail["/出力/" + zips[0]]
        self.run_sync()
        self.assertEqual(self.box.row(AUTO)["packs"][0]["verdict"], "keep")

    def test_three_days_auto_reject_without_download(self):
        self.key()
        self.put_group(AUTO, n=2)
        self.run_sync()
        names = [p["name"] for p in self.box.row(AUTO)["packs"]]
        self.box.decide(AUTO, [names[0]], "keep")   # 受け取っている途中の物は自動で要らないにしない
        self.t[0] += 3 * 86400 + 1
        self.assertEqual(self.box.sweep(), 1)
        p = self.box.row(AUTO)["packs"]
        self.assertEqual((p[0]["want"], p[1]["verdict"], p[1]["by"]), ("keep", "reject", "auto"))
        v = self.verdict(AUTO, names[1])
        self.assertEqual(v["by"], "auto")

    # ------------------------------------------------------------ 送り返し
    def test_returns_upload_and_keep_on_failure(self):
        self.key()
        os.makedirs(self.places["outbox"])
        ok = "%s__run1.zip" % RID
        for n in (ok, "%s__p.verdict.json" % RID, "bad name.zip", "x.txt"):
            with open(os.path.join(self.places["outbox"], n), "wb") as f:
                f.write(b"1")
        self.io.fail["/送り返し/%s__p.verdict.json" % RID] = D.DropboxError("つながりません", 0)
        probs = self.run_sync()
        self.assertTrue(any(p.startswith("送り返し") for p in probs))
        self.assertEqual(self.io.data("/送り返し/" + ok), b"1")
        self.assertEqual(sorted(os.listdir(self.places["outbox"])), sorted(["%s__p.verdict.json" % RID, "bad name.zip", "x.txt"]))
        self.t[0] += 3 * 86400 + 10   # 3 日上がらなければ消す
        os.utime(os.path.join(self.places["outbox"], "%s__p.verdict.json" % RID), (NOW - 10, NOW - 10))
        self.run_sync()
        self.assertNotIn("%s__p.verdict.json" % RID, os.listdir(self.places["outbox"]))

    # ------------------------------------------------------------ 学習の束
    def put_learning(self, ver, files, bad=False):
        self.io.put("/学習/latest.json", json.dumps({"version": ver}).encode())
        entries = []
        for rel, data in files.items():
            self.io.put("/学習/%s/%s" % (ver, rel), data)
            entries.append({"path": rel, "size": len(data), "sha256": hashlib.sha256(b"other" if bad else data).hexdigest()})
        self.io.put("/学習/%s/learning.json" % ver, json.dumps({"version": ver, "files": entries}).encode())

    def test_learning_fetch_apply_and_prune(self):
        self.key()
        root = os.path.join(self.places["data"], "learning")
        for i in range(3):
            os.makedirs(os.path.join(root, "20261001-00000%d-aaaaaaaa" % i))
        ver = "20261016-120000-0123abcd"
        self.put_learning(ver, {"learned-rules.json": b"{}", "voices/a.npy": b"v"})
        self.assertEqual(self.run_sync(), [])
        self.assertTrue(os.path.isfile(os.path.join(root, ver, "voices", "a.npy")))
        self.assertEqual(self.applied, [os.path.join(root, ver)])
        self.assertEqual(sorted(n for n in os.listdir(root) if S.VERSION_DIR_RE.match(n)),
                         ["20261001-000001-aaaaaaaa", "20261001-000002-aaaaaaaa", ver])
        self.run_sync()
        self.assertEqual(len(self.applied), 1)   # 向け済み

    def test_learning_bad_hash_and_unsafe_name(self):
        self.key()
        root = os.path.join(self.places["data"], "learning")
        ver = "20261016-120000-0123abcd"
        self.put_learning(ver, {"a.json": b"{}"}, bad=True)
        probs = self.run_sync()
        self.assertTrue(any("hash" in p for p in probs))
        self.assertFalse(os.path.exists(os.path.join(root, ver)))
        self.put_learning(ver, {"../x.json": b"{}"})
        probs = self.run_sync()
        self.assertTrue(any("安全" in p for p in probs))
        self.assertEqual(self.applied, [])

    def test_learning_skipped_on_maker_pc(self):
        self.key()
        os.makedirs(os.path.join(self.places["data"], "app"), exist_ok=True)
        with open(os.path.join(self.places["data"], "app", "prefs.json"), "w", encoding="utf-8") as f:
            json.dump({"intake": {"folder": "D:/Dropbox"}}, f)
        self.put_learning("20261016-120000-0123abcd", {"a.json": b"{}"})
        self.run_sync()
        self.assertEqual(self.applied, [])

    # ------------------------------------------------------------ 更新
    def put_update(self, ver, entries, sha=None):
        data = zip_bytes(entries)
        name = "RequestSender-%s.zip" % ver
        self.io.put("/更新/" + name, data)
        self.io.put("/更新/latest.json", json.dumps({"version": ver, "file": name, "size": len(data),
                                                      "sha256": sha or hashlib.sha256(data).hexdigest(), "notes": ""}).encode())

    def update_entries(self, **extra):
        e = {"src/friendapp/server.py": b"# server", "python/python.exe": b"MZ", "RequestSender.exe": b"MZ", "src/ytt/version.py": b"v"}
        e["manifest.json"] = json.dumps({"files": {k: hashlib.sha256(v).hexdigest() for k, v in e.items()}}).encode()
        e.update(extra)
        return e

    def test_update_installs_new_version_folder(self):
        self.key()
        self.put_update("0.91.0", self.update_entries())
        self.run_sync()
        self.assertFalse(os.path.exists(os.path.join(self.places["home"], "app-0.91.0")))   # 起動役からでなければ入れない
        self.env[S.LAUNCHER_ENV] = "1"
        self.assertEqual(self.run_sync(), [])
        app = os.path.join(self.places["home"], "app-0.91.0")
        self.assertTrue(os.path.isfile(os.path.join(app, "src", "friendapp", "server.py")))
        self.assertFalse(os.path.exists(os.path.join(app, "RequestSender.exe")))   # src と python だけ
        self.assertEqual(self.sync.status()["updated"], "0.91.0")
        self.assertEqual([n for n in os.listdir(self.places["home"]) if n.endswith((".tmp", ".part"))], [])

    def test_update_refuses_bad_zip_old_version_and_bad_list(self):
        self.key()
        self.env[S.LAUNCHER_ENV] = "1"
        self.put_update("0.89.0", self.update_entries())
        self.run_sync()
        self.assertFalse(os.path.exists(os.path.join(self.places["home"], "app-0.89.0")))
        e = self.update_entries()
        del e["python/python.exe"]
        self.put_update("0.91.0", e)
        probs = self.run_sync()
        self.assertTrue(any("python.exe" in p for p in probs))
        self.put_update("0.91.0", self.update_entries(**{"src/../../evil.py": b"x"}))
        probs = self.run_sync()
        self.assertTrue(probs)
        self.put_update("0.91.0", self.update_entries(), sha="0" * 64)
        probs = self.run_sync()
        self.assertTrue(any("SHA-256" in p for p in probs))
        with open(os.path.join(self.places["home"], S.VERSIONS_NAME), "w", encoding="utf-8") as f:
            json.dump({"v": 1, "bad": ["0.91.0"]}, f)
        self.put_update("0.91.0", self.update_entries())
        self.assertEqual(self.run_sync(), [])
        self.assertEqual([n for n in os.listdir(self.places["home"]) if n.startswith("app-0")], [])
        self.assertFalse(os.path.exists(os.path.join(self.tmp, "evil.py")))

    # ------------------------------------------------------------ 部品
    def test_request_doc_weights_and_top(self):
        f = dict(FORM, ranges=[], top=7, people=[], streamer="", weights={"wAudio": 1, "wChat": 2, "wComments": 0})
        d = S.request_doc("url", RID, f, NOW)
        self.assertEqual(d["items"], [{"url": FORM["url"], "top": 7}])
        self.assertEqual(d["weights"], {"audio": 1.0, "chat": 2.0, "comments": 0.0})
        self.assertNotIn("streamer", d)
        self.assertNotIn("speakers", d)
        with self.assertRaises(ValueError):
            S.request_doc("video", RID, f, NOW)

    def test_parse_group_checks_names(self):
        g = S.parse_group(json.dumps({"v": 1, "title": "t\x00", "preview": "../a.preview.mp4", "origin": "x",
                                      "packs": [{"zip": "a/b.zip"}, {"zip": "ok.zip", "n": 3, "duration": -1}, {"zip": "ok.zip"}]}).encode())
        self.assertEqual((g["title"], g["preview"], g["origin"]), ("t", "", ""))
        self.assertEqual([(p["zip"], p["n"], p["seconds"]) for p in g["packs"]], [("ok.zip", 3, None)])
        self.assertIsNone(S.parse_group(b"{broken"))
        self.assertIsNone(S.parse_group(json.dumps({"v": 2, "packs": [{"zip": "a.zip"}]}).encode()))


if __name__ == "__main__":
    unittest.main()
