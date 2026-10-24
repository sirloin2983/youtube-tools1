"""src/friendapp/sync.py のテスト(本物の Dropbox につながない = 偽の io。受信箱は本物の一時フォルダ)。
リポジトリ直下で: py -3.12 -m unittest tests/friendapp/test_sync.py"""
import datetime
import glob
import hashlib
import io
import json
import os
import shutil
import sys
import time
import types
import unittest
import zipfile
from unittest import mock

os.environ.setdefault("YTT_DATA_DIR", "inplace")
SRC = os.path.join(os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))), "src")
if SRC not in sys.path:
    sys.path.insert(0, SRC)
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))   # tests/(testkit)
import testkit  # noqa: E402
from friendapp import dropbox as D, inbox as I, sync as S  # noqa: E402

RID = "20261016-100000-abcdef"
AUTO = "20261016-110000-123456"
NOW = float(int(time.time()))
FORM = {"url": "https://www.youtube.com/watch?v=dQw4w9WgXcQ", "videoId": "dQw4w9WgXcQ", "ranges": [[10.0, 70.0], [100.0, 160.0]], "top": None,
        "streamer": "星見ルナ", "people": ["ゲスト"], "videoTracks": 2, "useWeights": False, "weights": None,
        "title": "題", "channel": "ch", "pc": "user"}


class FakeIo:
    """Dropbox のアプリのフォルダの偽物(パスは小文字で引く)。fail = {パス: DropboxError}"""

    def __init__(self, clock):
        self.files = {}
        self.clock = clock
        self.fail = {}
        self.deleted = []
        self.downloads = []
        self.reads = []
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
        self.reads.append(path)
        self._check(path)
        d = self.data(path)
        return None if d is None else (d[:cap], len(d) > cap)

    def download(self, path, part, rev=None, progress=None):
        self._check(path)
        self.downloads.append(path)
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
        self.tmp = testkit.tempdir(self, "friendsync-")
        self.t = [NOW]
        self.places = {"home": os.path.join(self.tmp, "home"), "data": os.path.join(self.tmp, "data"),
                       "friend": os.path.join(self.tmp, "data", "app", "friendapp"), "outbox": os.path.join(self.tmp, "data", "app", "outbox"),
                       "cases": os.path.join(self.tmp, "作業"), "save": lambda: os.path.join(self.tmp, "save")}
        for k in ("home", "friend", "cases"):
            os.makedirs(self.places[k], exist_ok=True)
        self.box = I.Inbox(os.path.join(self.places["friend"], "inbox.json"), self.places["outbox"], self.places["save"],
                           lambda: self.places["cases"], clock=self.clock)
        self.io = FakeIo(self.clock)
        self.applied = []
        self.env = {}
        self.sync = S.Sync(self.places, self.box, client_factory=lambda cfg, cancelled: self.io, clock=self.clock,
                           env=self.env, apply_learning=lambda ld: self.applied.append(ld) or True, version="0.90.0", runtime_dirs=[])

    def clock(self):
        return self.t[0]

    def key(self):
        testkit.write_json(os.path.join(self.places["home"], "config.json"), {"appKey": "k", "refreshToken": "r"})

    def verdict(self, rid, name, nth=-1):
        """判断の記録(<依頼 id>__<パック名>~<13 桁>.verdict.json。送り返しへ上げるまでの outbox)"""
        files = sorted(glob.glob(os.path.join(self.places["outbox"], "%s__%s~*.verdict.json" % (rid, glob.escape(name)))))
        self.assertTrue(files, name)
        with open(files[nth], encoding="utf-8") as f:
            return json.load(f)

    def uploaded(self, rid, name, nth=-1):
        """送り返しへ上げ終えた判断の記録(Dropbox の /送り返し/ の偽物の中)"""
        pre = ("/送り返し/%s__%s~" % (rid, name)).lower()
        keys = sorted(k for k in self.io.files if k.startswith(pre) and k.endswith(".verdict.json"))
        self.assertTrue(keys, name)
        return json.loads(self.io.files[keys[nth]]["data"].decode("utf-8"))

    def iso_day(self):
        return datetime.datetime.fromtimestamp(NOW).strftime("%Y-%m-%d")

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

    # ------------------------------------------------------------ 変化を長く待つ糸(WATCH)
    def test_watch_kicks_on_change_takes_new_cursor_and_backs_off(self):
        self.key()
        calls, waits = [], []
        sync = self.sync
        plan = [{"changes": False, "backoff": None}, {"changes": True, "backoff": 7}, D.DropboxError("切れた", 0), {"changes": True, "backoff": None}]

        def latest_cursor(path=""):
            calls.append(("cursor", path))
            return "c%d" % len(calls)

        def longpoll(cursor, timeout):
            calls.append(("poll", cursor, timeout))
            got = plan.pop(0)
            if not plan:
                sync.stop()
            if isinstance(got, Exception):
                raise got
            return got
        self.io.latest_cursor, self.io.longpoll = latest_cursor, longpoll
        kicks = []
        with mock.patch.object(sync, "kick", lambda: kicks.append(1)), \
                mock.patch.object(sync._stop, "wait", lambda s: waits.append(s)):
            sync.watch(timeout=30, gap=2, retry=99)
        self.assertEqual([c[0] for c in calls], ["cursor", "poll", "poll", "cursor", "poll", "cursor", "poll", "cursor"])
        self.assertEqual(calls[2][1], "c1")              # 変化が無ければ同じ位置で待ち続ける
        self.assertEqual(calls[4][1], "c4")              # 変化のあとは取り直した位置で
        self.assertEqual(len(kicks), 2)
        self.assertEqual(waits, [2, 7, 12, 2])           # ふだんは gap・backoff はその秒・1 回目の失敗は gap x 6

    def test_watch_without_longpoll_waits_like_before(self):
        self.key()
        waits = []
        with mock.patch.object(self.sync._stop, "wait", lambda s: waits.append(s) or self.sync.stop()):
            self.sync.watch(retry=99)   # 偽の口に longpoll が無い = 数分ごとの見回りだけ
        self.assertEqual(waits, [99])

    # ------------------------------------------------------------ ユーザーの PC に頼む(A-2)
    def test_request_upload_accept_and_wait(self):
        self.key()
        self.box.add(RID, FORM, {"title": "題"}, pc="user")
        self.assertEqual(self.run_sync(), [])
        doc = json.loads(self.io.data("/%s.request.json" % RID).decode("utf-8"))
        self.assertEqual(list(doc), ["v", "kind", "id", "flow", "items", "streamer", "speakers", "videoTracks", "cut", "sentAt"])
        self.assertEqual(doc["items"], [{"url": FORM["url"], "top": 2, "ranges": [{"start": 10.0, "end": 70.0}, {"start": 100.0, "end": 160.0}]}])
        self.assertEqual(doc["speakers"]["names"], ["星見ルナ", "ゲスト"])
        self.assertEqual((doc["id"], doc["videoTracks"], doc["cut"]), (RID, 2, "none"))
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

    def test_request_video_uploads_video_then_json(self):
        """動画ファイルは先に動画を直下 <依頼 id>__<元の名前> へ・[この PC でやり直す] は動画も消す"""
        self.key()
        clip = os.path.join(self.tmp, "【星見ルナ】歌ってみた.mp4")
        self.assertEqual(S.upload_name(RID, 'a<b>:"c".mp4'), RID + "__a_b___c_.mp4")   # Dropbox に使えない文字は _
        with open(clip, "wb") as f:
            f.write(b"v" * 100)
        f = dict(FORM, kind="file", ranges=[], top=None, file={"path": clip, "name": os.path.basename(clip), "size": 100})
        self.box.add(RID, f, {"title": "歌"}, pc="user", kind="file")
        self.assertEqual(self.run_sync(), [])
        name = S.upload_name(RID, os.path.basename(clip))
        self.assertTrue(name.startswith(RID + "__【星見ルナ】歌") and name.endswith(".mp4"))
        self.assertEqual(self.io.data("/" + name), b"v" * 100)
        doc = json.loads(self.io.data("/%s.request.json" % RID).decode("utf-8"))
        self.assertEqual(list(doc), ["v", "kind", "id", "flow", "files", "streamer", "speakers", "videoTracks", "cut", "sentAt"])
        self.assertEqual((doc["kind"], doc["files"], doc["streamer"]), ("video", [name], "星見ルナ"))
        self.assertTrue(self.sync.withdraw(RID))
        self.assertIsNone(self.io.data("/" + name))
        self.assertIsNone(self.io.data("/%s.request.json" % RID))

    def test_request_video_missing_fails_row(self):
        self.key()
        f = dict(FORM, kind="file", file={"path": os.path.join(self.tmp, "nope.mp4"), "name": "nope.mp4", "size": 1})
        self.box.add(RID, f, {"title": "x"}, pc="user", kind="file")
        self.run_sync()
        r = self.box.row(RID)
        self.assertEqual(r["state"], "failed")
        self.assertIn("見つかりません", r["error"])
        self.assertIsNone(self.io.data("/%s.request.json" % RID))

    def test_request_live_doc(self):
        """ライブの依頼の鍵と順(live の後に sentAt)"""
        self.key()
        live = {"sens": "low", "perHour": 8, "length": 150, "waitMin": 10, "pad": 5.0, "afterStream": False}
        self.box.add(RID, dict(FORM, kind="live", ranges=[], top=7, url="https://youtu.be/dQw4w9WgXcQ", live=live), {"title": "x"}, pc="user", kind="live")
        self.run_sync()
        doc = json.loads(self.io.data("/%s.request.json" % RID).decode("utf-8"))
        self.assertEqual(list(doc), ["v", "kind", "id", "flow", "url", "streamer", "speakers", "videoTracks", "cut", "live", "sentAt"])
        self.assertEqual((doc["url"], doc["live"], list(doc["live"])), ("https://www.youtube.com/watch?v=dQw4w9WgXcQ", live, [k for k in S.LIVE_KEYS if k in live]))   # 鍵の順は LIVE_KEYS(無い鍵 = 前の形の lengthMode は入れない)

    # ------------------------------------------------------------ /出力/ の取り込み
    def put_packs(self, rid, origin="auto", n=2, pack_data=None):
        """作る側と同じ形で 1 本ずつ置く(確認用の動画 → .meta.json → zip)"""
        zips = []
        for i in range(1, n + 1):
            stem = "%s__見どころ %d" % (rid, i)
            self.io.put("/出力/%s.preview.mp4" % stem, b"MP4")
            self.io.put("/出力/%s.meta.json" % stem, json.dumps({"v": 1, "origin": origin, "streamTitle": "朝活", "seconds": 30.5}).encode("utf-8"))
            self.io.put("/出力/%s.zip" % stem, pack_data or zip_bytes({"見どころ %d_pack/clip.mp4" % i: b"v" * 10, "見どころ %d_pack/a.lua" % i: b"x"}))
            zips.append(stem + ".zip")
        return zips

    def test_packs_import_preview_skip_keep_cleanup_and_returns(self):
        self.key()
        zips = self.put_packs(AUTO)
        self.run_sync()
        r = self.box.row(AUTO)
        self.assertEqual((r["origin"], r["pc"], r["state"]), ("auto", "auto", "arrived"))
        self.assertEqual([p["remote"]["zip"] for p in r["packs"]], zips)
        self.assertEqual([len(g["names"]) for g in r["groups"]], [1, 1])   # 1 本ずつの枠
        self.assertEqual(r["packs"][0]["seconds"], 30.5)
        self.assertTrue(all(g["preview"] and os.path.isfile(g["preview"]) for g in r["groups"]))
        self.assertIs(self.box.view()[0]["groups"][0]["preview"], True)   # 画面には手元のパスを出さない
        self.run_sync()   # 2 回目は取り込み直さない
        self.assertEqual(len(self.box.row(AUTO)["packs"]), 2)
        names = [p["name"] for p in r["packs"]]
        got = self.box.decide(AUTO, [names[0]], "skip")   # 見送る = 取らない
        self.assertEqual(got["done"], [names[0]])
        got = self.box.decide(AUTO, [names[1]], "keep")
        self.assertEqual((got["done"], got["pending"]), ([], [names[1]]))
        v = self.verdict(AUTO, names[0])
        self.assertEqual((v["v"], v["judge"], v["zip"], v["origin"]), (2, "unknown", zips[0], "auto"))
        self.run_sync()
        r = self.box.row(AUTO)
        self.assertEqual(r["state"], "done")
        saved = r["packs"][1]["savedTo"]
        # 保存先 = <保存先>/<日付>_<配信の題>_#番号(平らに。配信者・配信の日付が無い = 届いた日。番号は 2 本目)
        self.assertEqual(saved, os.path.join(self.tmp, "save", "%s_朝活_#2" % self.iso_day()))
        self.assertTrue(os.path.isfile(os.path.join(saved, "clip.mp4")))
        self.assertEqual(self.uploaded(AUTO, names[1])["judge"], "good")
        # 見送った物は戻せる 3 日の間は Dropbox の出力に残す(受け取った物は先に消す)
        self.assertFalse(r["groups"][0]["remote"]["cleaned"])
        self.assertTrue(r["groups"][1]["remote"]["cleaned"])
        self.assertEqual(sorted(k for k in self.io.files if k.startswith("/出力/")),
                         sorted(("/出力/%s__見どころ 1%s" % (AUTO, s)).lower() for s in (".zip", ".preview.mp4", ".meta.json")))
        self.assertEqual(len([k for k in self.io.files if k.startswith("/送り返し/")]), 2)
        self.assertEqual(os.listdir(self.places["outbox"]), [])   # 上げたら消す
        self.assertFalse(os.path.exists(r["groups"][1]["preview"]))   # 受け取った物の確認用の動画は消す
        self.t[0] += 3 * 86400 + 1
        self.run_sync()
        self.assertTrue(self.box.row(AUTO)["groups"][0]["remote"]["cleaned"])
        self.assertEqual([k for k in self.io.files if k.startswith("/出力/")], [])   # zip・確認用の動画・.meta.json を消した

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

    def test_zip_without_meta_waits_then_imports(self):
        """.meta.json も確認用の動画も無い zip は一覧の遅れの分だけ待ってから、出どころ「依頼」として取り込む"""
        self.key()
        self.io.put("/出力/%s__見どころ 1.zip" % AUTO, b"z")
        self.run_sync()
        self.assertIsNone(self.box.row(AUTO))
        self.t[0] += S.NO_META_WAIT + 1
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

    def test_failure_text_delete_retried_after_network_error(self):
        """失敗の知らせを取り込んだあと、Dropbox から消すのが通信で失敗した: 次の回に消し直す(覚えたまま残さない。10-23 の見回り)"""
        self.key()
        self.box.add(RID, FORM, {"title": "題"}, pc="user")
        self.run_sync()
        name = "/出力/%s__題.失敗.txt" % RID
        self.io.put(name, "取れませんでした".encode("utf-8"))
        real = self.io.delete

        def broken(path):
            if path == name:
                raise D.DropboxError("通信が切れました(ConnectionResetError)", 0)
            return real(path)
        self.io.delete = broken
        self.run_sync()
        self.assertEqual(self.box.row(RID)["state"], "failed")
        self.assertIsNotNone(self.io.data(name))   # 消せなかった
        self.io.delete = real
        self.run_sync()
        self.assertIsNone(self.io.data(name))      # 次の回に消した
        self.assertEqual(self.box.row(RID).get("remoteFails") or [], [])

    def test_bad_names_are_ignored(self):
        self.key()
        for n in ("../%s__x.zip" % AUTO, ".%s__x.zip" % AUTO, "%s__a:b.zip" % AUTO, "readme.txt", "CON.zip"):
            self.io.files[("/出力/" + n).lower()] = {"path": "/出力/" + n, "data": b"z", "rev": "r", "mtime": 0}
        self.run_sync()
        self.assertEqual(self.box.rows, [])

    def test_keep_refuses_zip_slip_and_broken(self):
        self.key()
        self.put_packs(AUTO, n=1, pack_data=zip_bytes({"../evil.txt": b"x"}))
        self.run_sync()
        name = self.box.row(AUTO)["packs"][0]["name"]
        self.box.decide(AUTO, [name], "keep")
        self.run_sync()
        p = self.box.row(AUTO)["packs"][0]
        self.assertIsNone(p["verdict"])
        self.assertIn("展開できませんでした", p["error"])
        self.assertFalse(os.path.exists(os.path.join(self.tmp, "evil.txt")))
        self.assertEqual([n for _d, _s, fs in os.walk(os.path.join(self.tmp, "save")) for n in fs], [])   # 何も置かない(空のフォルダだけ)
        f = self.io.files[("/出力/" + p["remote"]["zip"]).lower()]
        f["data"] = b"changed"   # 一覧の hash と違う = 壊れていた
        with self.box.lock:
            self.box.row(AUTO)["packs"][0]["remote"]["hash"] = "0" * 64
        self.box.decide(AUTO, [name], "keep")
        self.run_sync()
        self.assertIn("壊れていました", self.box.row(AUTO)["packs"][0]["error"])

    def test_keep_retries_when_offline(self):
        self.key()
        zips = self.put_packs(AUTO, n=1)
        self.run_sync()
        name = self.box.row(AUTO)["packs"][0]["name"]
        self.box.decide(AUTO, [name], "keep")
        self.io.fail["/出力/" + zips[0]] = D.DropboxError("つながりません", 0)
        probs = self.run_sync()
        self.assertTrue(any(p.startswith("受け取る") for p in probs))
        self.assertEqual(self.box.row(AUTO)["packs"][0]["want"], "keep")   # 押したまま次の回へ
        self.assertEqual(self.sync.status()["message"], "")   # 一時の切れは帯に出さない
        self.t[0] += S.PROBLEM_SHOW
        self.run_sync()
        self.assertIn("10 分以上", self.sync.status()["message"])   # 続く問題は帯に出す
        del self.io.fail["/出力/" + zips[0]]
        self.run_sync()
        self.assertEqual(self.box.row(AUTO)["packs"][0]["verdict"], "keep")
        self.assertEqual(self.sync.status()["message"], "")

    def test_keep_unwritable_save_folder_gives_reason(self):
        """保存先を作れない(抜いた USB など)= その行に理由を出して押す前に戻す(「受け取っています」のまま止めない)"""
        self.key()
        self.put_packs(AUTO, n=1)
        self.run_sync()
        name = self.box.row(AUTO)["packs"][0]["name"]
        with open(os.path.join(self.tmp, "save"), "w") as f:   # 保存先の場所にファイル = フォルダを作れない
            f.write("x")
        self.box.decide(AUTO, [name], "keep")
        self.run_sync()
        p = self.box.row(AUTO)["packs"][0]
        self.assertIsNone(p["verdict"])
        self.assertIn("保存先のフォルダを作れません", p["error"])
        os.remove(os.path.join(self.tmp, "save"))
        self.box.decide(AUTO, [name], "keep")
        self.run_sync()
        self.assertEqual(self.box.row(AUTO)["packs"][0]["verdict"], "keep")

    def test_three_days_auto_skip_without_download(self):
        self.key()
        self.put_packs(AUTO, n=2)
        self.run_sync()
        names = [p["name"] for p in self.box.row(AUTO)["packs"]]
        self.box.decide(AUTO, [names[0]], "keep")   # 受け取っている途中の物は自動で見送らない
        self.t[0] += 3 * 86400 + 1
        self.assertEqual(self.box.sweep(), 1)
        p = self.box.row(AUTO)["packs"]
        self.assertEqual((p[0]["want"], p[1]["verdict"], p[1]["by"]), ("keep", "skip", "auto"))
        v = self.verdict(AUTO, names[1])
        self.assertEqual((v["by"], v["judge"]), ("auto", "unknown"))

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

    def test_returns_upload_new_verdict_and_notice_names(self):
        """F3: 判断の記録は ~<13 桁> つき・知らせは __notice-<13 桁>.notice.json。形の違う名前は上げない"""
        self.key()
        os.makedirs(self.places["outbox"])
        good = ["%s__p~1790000000000.verdict.json" % RID, "%s__p.verdict.json" % RID, "%s__notice-1790000000000.notice.json" % RID,
                "unknown__notice-1790000000000.notice.json"]
        bad = ["%s__notice-123.notice.json" % RID, "%s__notice-1790000000000.notice.json.tmp" % RID, "x__y.notice.json"]
        for n in good + bad:
            with open(os.path.join(self.places["outbox"], n), "wb") as f:
                f.write(b"1")
        self.assertEqual(self.run_sync(), [])
        self.assertEqual(sorted(k for k in self.io.files if k.startswith("/送り返し/")), sorted(("/送り返し/" + n).lower() for n in good))
        self.assertEqual(sorted(os.listdir(self.places["outbox"])), sorted(bad))
        for n in good:
            self.assertEqual(self.io.data("/送り返し/" + n), b"1")

    def test_parse_meta_info(self):
        d = S.parse_meta_info(json.dumps({"v": 1, "origin": "request", "videoId": "dQw4w9WgXcQ", "markId": "m1", "streamTitle": "枠の題", "streamer": "星見ルナ",
                                          "seconds": 31.5, "title": "パックの題"}).encode())
        self.assertEqual(d, {"videoId": "dQw4w9WgXcQ", "markId": "m1", "streamTitle": "枠の題", "streamer": "星見ルナ", "seconds": 31.5})
        d = S.parse_meta_info(json.dumps({"v": 1, "headline": "「うわ最悪だね」", "headlineWhy": "チャットが急増", "overlapNote": "前に届けた…"}).encode())
        self.assertEqual(d, {"overlapNote": "前に届けた…"})   # かぶり(新機能 E)。古い .meta.json の機械の見出し(10-24 に無くした)は読まない
        d = S.parse_meta_info(json.dumps({"v": 1, "videoId": "short", "markId": "", "streamTitle": "", "seconds": 0}).encode())
        self.assertEqual(d, {})   # 分からない欄は入れない
        for raw in (json.dumps({"v": 1, "seconds": 86400}), json.dumps({"v": 1, "seconds": True}), json.dumps({"v": 2, "videoId": "dQw4w9WgXcQ"}), "{broken"):
            with self.subTest(raw=raw):
                self.assertEqual(S.parse_meta_info(raw.encode()), {})

    def test_single_pack_meta_fills_stream_info_and_keep_place(self):
        """.meta.json の配信の欄がパックの info に入り、受け取るの保存先の直下の <日付>_<配信者>_<題>_#番号 になる。判断の記録にも videoId・markId"""
        self.key()
        meta = {"v": 1, "kind": "clip", "origin": "request", "videoId": "dQw4w9WgXcQ", "markId": "mk1", "streamTitle": "耐久/配信:前編", "streamer": "星見ルナ",
                "seconds": 42.0, "title": "見どころ"}
        for i in (1, 2):
            self.io.put("/出力/%s__見どころ%d.zip" % (RID, i), zip_bytes({"見どころ%d_pack/a.mp4" % i: b"v"}))
            self.io.put("/出力/%s__見どころ%d.preview.mp4" % (RID, i), b"MP4")
            self.io.put("/出力/%s__見どころ%d.meta.json" % (RID, i), json.dumps(dict(meta, title="見どころ%d" % i)).encode())
        self.run_sync()
        r = self.box.row(RID)
        self.assertEqual(len(r["packs"]), 2)
        p0 = r["packs"][0]
        self.assertEqual(p0["info"], {"videoId": "dQw4w9WgXcQ", "markId": "mk1", "streamTitle": "耐久/配信:前編", "streamer": "星見ルナ"})
        self.assertEqual((p0["seconds"], p0["key"], [p["num"] for p in r["packs"]]), (42.0, "v:dQw4w9WgXcQ", [1, 2]))
        self.assertEqual(self.box.receive_view()["sections"][0]["title"], "耐久/配信:前編")
        self.assertEqual(self.box.receive_view()["sections"][0]["streamer"], "星見ルナ")
        names = [p["name"] for p in r["packs"]]
        self.box.decide(RID, names, "keep")
        self.run_sync()
        r = self.box.row(RID)
        folder = os.path.join(self.tmp, "save", "%s_星見ルナ_耐久_配信_前編" % self.iso_day())   # 使えない文字は _
        self.assertEqual([p["savedTo"] for p in r["packs"]], [folder + "_#1", folder + "_#2"])
        self.assertTrue(os.path.isfile(os.path.join(folder + "_#2", "a.mp4")))
        self.assertEqual(r["state"], "done")
        v = self.uploaded(RID, names[0])
        self.assertEqual((v["judge"], v["videoId"], v["markId"], v["zip"]), ("good", "dQw4w9WgXcQ", "mk1", "%s__見どころ1.zip" % RID))

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
        testkit.write_json(os.path.join(self.places["data"], "app", "prefs.json"), {"intake": {"folder": "D:/Dropbox"}})
        self.put_learning("20261016-120000-0123abcd", {"a.json": b"{}"})
        self.run_sync()
        self.assertEqual(self.applied, [])

    # ------------------------------------------------------------ 更新
    def put_update(self, ver, entries, sha=None, name=None):
        data = zip_bytes(entries)
        name = name or "FriendApp-%s.zip" % ver
        self.io.put("/更新/" + name, data)
        self.io.put("/更新/latest.json", json.dumps({"version": ver, "file": name, "size": len(data),
                                                      "sha256": sha or hashlib.sha256(data).hexdigest(), "notes": ""}).encode())

    def update_entries(self, **extra):
        e = {"src/friendapp/server.py": b"# server", "python/python.exe": b"MZ", "other.exe": b"MZ", "src/ytt/version.py": b"v"}
        e["manifest.json"] = json.dumps({"files": {k: hashlib.sha256(v).hexdigest() for k, v in e.items()}}).encode()
        e.update(extra)
        return e

    def test_update_notes_latest_marks_and_skips_cancelled(self):
        """latest.json の important・fixes・cancel を覚える(形の違う欄は捨てる)・cancel に入った版は取らない"""
        self.key()
        self.env[S.LAUNCHER_ENV] = "1"
        self.put_update("0.91.0", self.update_entries())
        doc = json.loads(self.io.data("/更新/latest.json"))
        doc.update(important=True, fixes={"requests": ["20261025-010203-abcdef", "../x"], "kinds": [1, 9, True]}, cancel=["0.91.0", "x"],
                   notes=[{"v": "0.91.0", "at": 5, "items": ["直した\x00こと", 3, ""]}, {"v": "x", "items": ["捨てる"]}])
        self.io.put("/更新/latest.json", json.dumps(doc).encode())
        self.assertEqual(self.run_sync(), [])
        self.assertEqual(self.sync.state["latest"], {"version": "0.91.0", "important": True, "cancel": ["0.91.0"],
                                                     "fixes": {"requests": ["20261025-010203-abcdef"], "kinds": [1]},
                                                     "notes": [{"v": "0.91.0", "at": 5, "items": ["直したこと"]}]})
        self.assertFalse(os.path.exists(os.path.join(self.places["home"], "app-0.91.0")))   # 取り消された版は取らない

    def test_update_gone_only_when_folder_readable(self):
        """latest.json が外された(/更新/ は読めて latest.json だけ無い)ときだけ gone。フォルダごと見えない・読めないのは取り違えない"""
        self.key()
        self.env[S.LAUNCHER_ENV] = "1"
        self.run_sync()
        self.assertNotIn("latest", self.sync.state)   # /更新/ が無い
        self.io.fail["/更新/latest.json"] = S._dropbox.DropboxError("つながりません", 0)
        self.io.put("/更新/FriendApp-0.90.0.zip", b"z")
        self.run_sync()
        self.assertNotIn("latest", self.sync.state)   # 読めなかった
        del self.io.fail["/更新/latest.json"]
        self.run_sync()
        self.assertEqual(self.sync.state["latest"], {"gone": True})

    def test_returns_upload_beat_and_fail_to_diag(self):
        """心拍 .beat.json と失敗の知らせ .fail.json も /診断/ へ。/診断/ の心拍は 1 日・失敗の知らせは 3 日で消す"""
        self.key()
        os.makedirs(self.places["outbox"], exist_ok=True)
        at = int(NOW * 1000)
        for n in ("app__beat-%013d.beat.json" % at, "launcher__fail-%013d.fail.json" % at):
            with open(os.path.join(self.places["outbox"], n), "w") as f:
                f.write("{}")
        self.run_sync()
        self.assertIsNotNone(self.io.data("/診断/app__beat-%013d.beat.json" % at))
        self.assertIsNotNone(self.io.data("/診断/launcher__fail-%013d.fail.json" % at))
        old = at - 2 * 86400 * 1000
        self.assertEqual(S._diag.prune_names(["app__beat-%013d.beat.json" % old, "launcher__fail-%013d.fail.json" % old], at),
                         ["app__beat-%013d.beat.json" % old])

    def test_update_installs_new_version_folder(self):
        self.key()
        self.put_update("0.91.0", self.update_entries())
        self.run_sync()
        self.assertFalse(os.path.exists(os.path.join(self.places["home"], "app-0.91.0")))   # 起動役からでなければ入れない
        self.env[S.LAUNCHER_ENV] = "1"
        self.assertEqual(self.run_sync(), [])
        app = os.path.join(self.places["home"], "app-0.91.0")
        self.assertTrue(os.path.isfile(os.path.join(app, "src", "friendapp", "server.py")))
        self.assertFalse(os.path.exists(os.path.join(app, "other.exe")))   # src・python と決まった直下の物だけ
        self.assertEqual(self.sync.status()["updated"], "0.91.0")
        self.assertEqual([n for n in os.listdir(self.places["home"]) if n.endswith((".tmp", ".part"))], [])

    def test_update_takes_launcher_files_and_refuses_other_names(self):
        """exe と DLL・fetch.json は app-<版>/ へ(入れ替えは [更新する] で exe が)・FriendApp-<版>.zip のほかの名前は断る"""
        self.key()
        self.env[S.LAUNCHER_ENV] = "1"
        extra = {"FriendApp.exe": b"MZexe", "WebView2Loader.dll": b"MZdll", "fetch.json": b"{}", "notes.txt": b"x"}
        self.put_update("0.92.0", self.update_entries(**extra))
        self.assertEqual(self.run_sync(), [])
        app = os.path.join(self.places["home"], "app-0.92.0")
        for n in ("FriendApp.exe", "WebView2Loader.dll", "fetch.json"):
            self.assertTrue(os.path.isfile(os.path.join(app, n)), n)
        self.assertFalse(os.path.exists(os.path.join(app, "notes.txt")))   # 決まった名前だけ
        for bad in ("Other-0.93.0.zip", "FriendApp-0.93.zip"):
            self.put_update("0.93.0", self.update_entries(), name=bad)
            self.assertTrue(any("latest.json" in p for p in self.run_sync()), bad)

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
        self.assertEqual(self.run_sync(), [])   # 同じ zip はしばらく取り直さない
        self.t[0] += S.UPDATE_RETRY_SEC
        self.assertTrue(any("python.exe" in p for p in self.run_sync()))
        self.put_update("0.91.0", self.update_entries(**{"src/../../evil.py": b"x"}))
        probs = self.run_sync()
        self.assertTrue(probs)
        self.put_update("0.91.0", self.update_entries(), sha="0" * 64)
        probs = self.run_sync()
        self.assertTrue(any("SHA-256" in p for p in probs))
        testkit.write_json(os.path.join(self.places["home"], S.VERSIONS_NAME), {"v": 1, "bad": ["0.91.0"]})
        self.put_update("0.91.0", self.update_entries())
        self.assertEqual(self.run_sync(), [])
        self.assertEqual([n for n in os.listdir(self.places["home"]) if n.startswith("app-0")], [])
        self.assertFalse(os.path.exists(os.path.join(self.tmp, "evil.py")))

    # ------------------------------------------------------------ 軽い更新(python/ は今の python から写す)
    RUNTIME = {"python.exe": b"MZpy", "python310._pth": b"..\\src\n", "Lib/site-packages/numpy/__init__.py": b"x = 1\n"}

    def runtime(self, **change):
        """今動いている Python のフォルダの偽物(change で 1 つ書き換える = python が変わった)"""
        d = os.path.join(self.tmp, "runtime")
        for rel, data in dict(self.RUNTIME, **change).items():
            path = os.path.join(d, *rel.split("/"))
            os.makedirs(os.path.dirname(path), exist_ok=True)
            with open(path, "wb") as f:
                f.write(data)
        self.sync.runtime_dirs = [d]
        return d

    def put_light(self, ver, light_extra=None, with_full=True):
        """全部入り(python/ つき)と軽い zip(python/ なし・manifest は同じ files + light)と light 付きの latest.json"""
        src = {"src/friendapp/server.py": b"# server", "src/ytt/version.py": b"v", "fetch.json": b"{}"}
        py = {"python/" + rel: data for rel, data in self.RUNTIME.items()}
        files = {k: hashlib.sha256(v).hexdigest() for k, v in dict(src, **py).items()}
        full = zip_bytes(dict(src, **py, **{"manifest.json": json.dumps({"files": files}).encode()}))
        light = zip_bytes(dict(src, **{"manifest.json": json.dumps({"files": files, "light": True}).encode()}))
        name, lname = "FriendApp-%s.zip" % ver, "FriendApp-%s-light.zip" % ver
        self.io.put("/更新/" + name, full)
        self.io.put("/更新/" + lname, light)
        entry = {"file": lname, "size": len(light), "sha256": hashlib.sha256(light).hexdigest()}
        entry.update(light_extra or {})
        doc = {"version": ver, "file": name, "size": len(full), "sha256": hashlib.sha256(full).hexdigest(), "notes": "", "light": entry}
        self.io.put("/更新/latest.json", json.dumps(doc).encode())
        return name, lname

    def test_heavy_zip_waits_for_recording_but_light_does_not(self):
        """録画中: 軽い zip は取る・全部入りは録画が終わってから(update_wait = recording)"""
        self.key()
        self.env[S.LAUNCHER_ENV] = "1"
        live = types.SimpleNamespace(active_count=lambda: 1)
        self.sync.engine_fn = lambda: types.SimpleNamespace(live=live)
        self.put_update("0.91.0", self.update_entries())   # 軽い zip の無い版
        self.assertEqual(self.run_sync(), [])
        self.assertEqual((self.sync.update_wait, [p for p in self.io.downloads if "FriendApp-" in p]), ("recording", []))
        live.active_count = lambda: 0
        self.run_sync()
        self.assertTrue(os.path.isdir(os.path.join(self.places["home"], "app-0.91.0")))
        self.assertIsNone(self.sync.update_wait)
        live.active_count = lambda: 1
        self.runtime()
        _name, lname = self.put_light("0.95.0")
        self.assertEqual(self.run_sync(), [])
        self.assertEqual([p for p in self.io.downloads if "0.95.0" in p], ["/更新/" + lname])   # 軽い zip は録画中でも取る

    def test_light_update_copies_python_from_runtime(self):
        self.key()
        self.env[S.LAUNCHER_ENV] = "1"
        self.runtime()
        name, lname = self.put_light("0.95.0")
        self.assertEqual(self.run_sync(), [])
        app = os.path.join(self.places["home"], "app-0.95.0")
        self.assertEqual([p for p in self.io.downloads if "FriendApp-" in p], ["/更新/" + lname])   # 取ったのは軽い zip だけ
        with open(os.path.join(app, "python", "Lib", "site-packages", "numpy", "__init__.py"), "rb") as f:
            self.assertEqual(f.read(), b"x = 1\n")
        self.assertTrue(os.path.isfile(os.path.join(app, "python", "python.exe")))
        self.assertTrue(os.path.isfile(os.path.join(app, "src", "friendapp", "server.py")))
        self.assertEqual(self.sync.status()["updated"], "0.95.0")
        self.assertEqual([n for n in os.listdir(self.places["home"]) if n.endswith((".tmp", ".part"))], [])

    def test_light_update_falls_back_to_full_when_python_differs(self):
        self.key()
        self.env[S.LAUNCHER_ENV] = "1"
        for missing in (False, True):   # 1 つ違う・1 つ無い
            rt = self.runtime(**({} if missing else {"python.exe": b"MZother"}))
            if missing:
                os.remove(os.path.join(rt, "Lib", "site-packages", "numpy", "__init__.py"))
            name, lname = self.put_light("0.95.0")
            self.io.downloads.clear()
            self.assertEqual(self.run_sync(), [])
            self.assertEqual([p for p in self.io.downloads if "FriendApp-" in p], ["/更新/" + lname, "/更新/" + name])   # 同じ回で全部入りを取り直す
            app = os.path.join(self.places["home"], "app-0.95.0")
            self.assertTrue(os.path.isfile(os.path.join(app, "python", "python.exe")))
            self.assertEqual([n for n in os.listdir(self.places["home"]) if n.endswith((".tmp", ".part"))], [])
            shutil.rmtree(app)

    def test_malformed_light_entry_takes_full(self):
        self.key()
        self.env[S.LAUNCHER_ENV] = "1"
        self.runtime()
        for extra in ({"file": "evil.zip"}, {"sha256": "zz"}, {"file": "FriendApp-0.1.0-light.zip"}):
            name, lname = self.put_light("0.95.0", extra)
            self.io.downloads.clear()
            self.assertEqual(self.run_sync(), [])
            self.assertEqual([p for p in self.io.downloads if "FriendApp-" in p], ["/更新/" + name], extra)
            shutil.rmtree(os.path.join(self.places["home"], "app-0.95.0"))

    def test_light_update_needs_free_space(self):
        self.key()
        self.env[S.LAUNCHER_ENV] = "1"
        self.runtime()
        name, lname = self.put_light("0.95.0")
        with mock.patch.object(S, "free_ok", side_effect=lambda folder, need: need >= S.UPDATE_NEED):   # 取る前の空きはある・写す分の空きが無い = 軽い更新はせず、同じ回で全部入りを取る
            self.assertEqual(self.run_sync(), [])
        self.assertEqual([p for p in self.io.downloads if "FriendApp-" in p], ["/更新/" + lname, "/更新/" + name])

    def test_update_waits_for_free_space_before_downloading(self):
        self.key()
        self.env[S.LAUNCHER_ENV] = "1"
        self.runtime()
        seen = []

        class FakeDiag:
            def once(self, key, every, kind, **kw):
                seen.append((key, kind, kw.get("stage")))

            def write(self, kind, **kw):
                pass

        self.sync.diag = FakeDiag()
        self.put_light("0.95.0")
        needs = []
        with mock.patch.object(S, "free_ok", side_effect=lambda folder, need: needs.append(need) or False):
            self.assertEqual(self.run_sync(), [])
        self.assertEqual([p for p in self.io.downloads if "FriendApp-" in p], [])   # 取らない = .part も作らない
        self.assertEqual([n for n in os.listdir(self.places["home"]) if n.endswith((".tmp", ".part"))], [])
        self.assertEqual(seen, [("update:space", "update", "space")])
        self.assertGreater(needs[0], S.UPDATE_NEED)   # 作業データが同じドライブ = diskMinGB を足す
        self.assertIsNone(self.sync.status().get("updated"))
        self.assertEqual(self.run_sync(), [])   # 空いたら次の回で取る
        self.assertTrue([p for p in self.io.downloads if "FriendApp-" in p])
        self.assertEqual(self.sync.status()["updated"], "0.95.0")

    def test_friend_never_reads_versions_json(self):
        """更新/versions.json は作る側の台帳。友人のアプリは読まない(latest.json の欄も増やさない)"""
        self.key()
        self.env[S.LAUNCHER_ENV] = "1"
        self.runtime()
        self.put_light("0.95.0")
        self.io.put("/更新/versions.json", b'{"v":1,"versions":[]}')
        self.assertEqual(self.run_sync(), [])
        self.assertNotIn("/更新/versions.json", self.io.reads + self.io.downloads)
        self.assertEqual(sorted(json.loads(self.io.data("/更新/latest.json"))), ["file", "light", "notes", "sha256", "size", "version"])

    # ------------------------------------------------------------ 部品
    def test_request_doc_top(self):
        f = dict(FORM, ranges=[], top=7, people=[], streamer="", weights={"wAudio": 1, "wChat": 2, "wComments": 0})   # 前の版の行に残った重みは送らない(10-23)
        d = S.request_doc("url", RID, f, NOW)
        self.assertEqual(d["items"], [{"url": FORM["url"], "top": 7}])
        self.assertNotIn("weights", d)
        self.assertNotIn("streamer", d)
        self.assertNotIn("speakers", d)
        with self.assertRaises(ValueError):
            S.request_doc("video", RID, f, NOW)


if __name__ == "__main__":
    unittest.main()
