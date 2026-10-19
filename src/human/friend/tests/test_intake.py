"""友人からの依頼の受付(src/human/friend/intake.py)の単体テスト。まとめて実行・ffprobe・yt-dlp は偽物。

実行(リポジトリ直下から): python -m unittest src/human/friend/tests/test_intake.py -v
(設定 prefs の intake の節の検査は入口の側 src/app/tests/test_intake_prefs.py)
"""
import json
import os
import subprocess
import sys
import threading
import time
import unittest
from unittest import mock

os.environ.setdefault("YTT_DATA_DIR", "inplace")
ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))))   # tests -> friend -> human -> src
HOME = os.path.join(ROOT, "app")   # 設定 prefs(入口 = app)を、本物の設定と組み合わせて使うため
for p in (HOME, ROOT):
    if p not in sys.path:
        sys.path.insert(0, p)

from human.friend import intake  # noqa: E402
from human.friend import live_requests  # noqa: E402
from app import prefs as prefs_mod  # noqa: E402
from ytt import fsio, jobs, normalize, tools  # noqa: E402
from ytt import testkit  # noqa: E402


class FakeRunner:
    """まとめて実行の代わり。受付(Intake)の欄を、submit_urls・submit_file に渡した形のまま覚える(下の Base が差し替える。
    欄 → 封筒 + 束の差分の変換そのものは TestSubmitOrders が本物の submit_urls・submit_file で確かめる)"""

    def __init__(self):
        self.requests, self.files = [], []
        self.fail = None

    def start_request(self, items, request_id=None, deliver_dir=None, speakers=None, video_tracks=None, cut=None, weights=None, streamer=None):
        if self.fail:
            raise ValueError(self.fail)
        self.requests.append((items, request_id))
        self.last = {"deliver": deliver_dir, "speakers": speakers, "tracks": video_tracks, "cut": cut, "weights": weights, "streamer": streamer}
        return {"runs": [{"id": "r%d" % len(self.requests) + it["id"][:3], "videoId": it["id"]} for it in items], "skipped": []}

    def start_file(self, path, title="", streamer=None, request_id=None, deliver_dir=None, speakers=None, video_tracks=None, cut=None):
        if self.fail:
            raise ValueError(self.fail)
        self.files.append({"path": path, "title": title, "streamer": streamer, "rid": request_id, "deliver": deliver_dir, "speakers": speakers,
                           "tracks": video_tracks, "cut": cut})
        return {"id": "f%d" % len(self.files)}


class Base(unittest.TestCase):
    def setUp(self):
        self.tmp = testkit.tempdir(self, "intake-")
        self.folder = os.path.join(self.tmp, "Dropbox", "切り抜き依頼")
        self.data = os.path.join(self.tmp, "app")
        os.makedirs(self.folder)
        self.prefs = prefs_mod.Prefs(os.path.join(self.data, "prefs.json"), fsio.atomic_write)
        self.prefs.patch("intake", {"enabled": True, "folder": self.folder})
        self.runner = FakeRunner()
        for name, meth in (("submit_urls", "start_request"), ("submit_file", "start_file")):   # 受付の欄を覚える(RV A1 で submit の 1 本に)
            p = mock.patch.object(intake, name, lambda runner, *a, _m=meth, **kw: getattr(runner, _m)(*a, **kw))
            p.start()
            self.addCleanup(p.stop)
        self.now = time.time() + 1000   # ファイルの更新時刻より十分あと(落ち着いた扱い)
        self.infos = {}
        self.probes = {}
        self.it = intake.Intake(self.prefs, lambda: self.runner, self.data, clock=lambda: self.now,
                                probe=lambda p: self.probes.get(os.path.basename(p), {"ok": True, "duration": 60.0, "reason": ""}),
                                info=lambda vid: self.infos.get(vid, {"duration": 3600.0, "live": "not_live", "title": "題名 " + vid, "channel": "ch"}))


    def put(self, name, data):
        p = os.path.join(self.folder, name)
        with open(p, "wb") as f:
            f.write(data if isinstance(data, bytes) else data.encode("utf-8"))
        return p

    def put_urls(self, lines, rid=None):
        """友人のアプリの URL の依頼(依頼の JSON の kind url)を置く。lines = ["URL [数]", …](数が無ければホームの既定)-> 依頼 id"""
        self._rid = getattr(self, "_rid", 0) + 1
        rid = rid or "20261002-120000-%06x" % self._rid
        items = []
        for line in lines:
            parts = line.split()
            items.append(dict({"url": parts[0]}, **({"top": int(parts[1])} if len(parts) > 1 else {})))
        self.put(rid + ".request.json", json.dumps({"v": 1, "kind": "url", "id": rid, "items": items}))
        return rid

    def scan2(self):
        """1回目で大きさを覚え、SETTLE 秒あとの2回目で処理する"""
        self.it.scan()
        self.now += intake.SETTLE + 1
        self.it.scan()

    def done(self, *parts):
        return os.path.join(self.folder, intake.DONE_DIR, self.it._today(), *parts)

    def failed(self, *parts):
        return os.path.join(self.folder, intake.FAIL_DIR, *parts)


class TestSubmitOrders(unittest.TestCase):
    """受付の欄 → ② の口 submit(封筒 + 束の差分。flow/order.py)。結果の形は {"runs", "skipped"}"""

    class Rec:
        def __init__(self, busy=()):
            self.got, self.busy = [], set(busy)

        def submit(self, env, spec=None):
            if env["input"].get("videoId") in self.busy:
                raise ValueError("同じ入力がすでに実行中・順番待ちです")
            self.got.append((env, spec))
            return {"id": env["id"], "videoId": env["input"].get("videoId")}

    def test_urls(self):
        rec = self.Rec(busy={"bbbbbbbbbbb"})
        out = intake.submit_urls(rec, [{"id": "aaaaaaaaaaa", "top": 3, "title": "配信", "channel": "ch", "ranges": [(10, 20)], "duration": 100.0},
                                       {"id": "bbbbbbbbbbb", "top": 2}, {"id": "bad", "top": 2}, {"id": "ccccccccccc", "top": 99}],
                                 request_id="20261016-120000-abc123", deliver_dir="D:/out", speakers={"count": 2, "names": ["A"]},
                                 video_tracks=2, cut="silence", weights={"wAudio": 1.5, "wChat": 0.5, "wComments": 2.0}, streamer="兎田ぺこら")
        self.assertEqual(sorted(out), ["runs", "skipped"])
        self.assertEqual([r["videoId"] for r in out["runs"]], ["aaaaaaaaaaa"])
        self.assertEqual([(s["id"], s["reason"]) for s in out["skipped"]],
                         [("bbbbbbbbbbb", "同じ入力がすでに実行中・順番待ちです"), ("bad", "配信の指定が正しくありません"), ("ccccccccccc", "配信の指定が正しくありません")])
        env, _spec = rec.got[0]   # 束の差分の中身(run・adopt・hints・pack・transcribe)は flow の test_order の test_fields_to_diff
        self.assertEqual((env["kind"], env["specVersion"], env["requestId"], env["deliver"]["dir"], env["input"]["duration"],
                          env["input"]["fresh"]), ("url", 2, "20261016-120000-abc123", "D:/out", 100.0, {"title": "配信", "channel": "ch"}))
        self.assertNotIn("batch", env["deliver"])

    def test_always_full_auto(self):
        """依頼はいつも ① 全自動 = パックまで(② 軽く確認 = 文字起こしまでは 10-19 に消した)。URL は送り直しで作り直す(repack)・動画は repack を付けない"""
        rec = self.Rec()
        intake.submit_urls(rec, [{"id": "aaaaaaaaaaa", "top": 1, "ranges": [[5, 1]]}, {"id": "ddddddddddd", "top": 1}])
        self.assertEqual(len(rec.got), 1, "形の違う区間の配信は断る")
        self.assertEqual(rec.got[0][1]["run"], {"upto": "pack", "repack": True})
        intake.submit_file(rec, "C:/x/依頼.mp4", title="依頼", streamer="さくらみこ", request_id="rid", deliver_dir="D:/out")
        env, spec = rec.got[-1]
        self.assertEqual((env["kind"], env["input"], env["requestId"], env["deliver"]["dir"]),
                         ("file", {"title": "依頼", "path": "C:/x/依頼.mp4", "normalize": True}, "rid", "D:/out"))
        self.assertEqual((spec["run"], spec["hints"]), ({"upto": "pack"}, {"streamer": "さくらみこ"}))
        intake.submit_file(rec, "C:/x/b.mp4")
        self.assertEqual((rec.got[-1][0]["input"]["title"], rec.got[-1][1]["run"]), ("b.mp4", {"upto": "pack"}))


class TestParse(unittest.TestCase):
    def test_youtube_id(self):
        ok = {"https://www.youtube.com/watch?v=abcdefghijk": "abcdefghijk",
              "https://www.youtube.com/watch?si=x&v=abcdefghijk&t=10s": "abcdefghijk",
              "youtu.be/abcdefghijk?si=zz": "abcdefghijk",
              "https://m.youtube.com/live/abcdefghijk?feature=share": "abcdefghijk",
              "https://youtube.com/shorts/abc-efg_ijk": "abc-efg_ijk"}
        for u, v in ok.items():
            self.assertEqual(intake.youtube_id(u), v, u)
        for u in ("https://evil.example/watch?v=abcdefghijk", "https://www.youtube.com.evil.example/watch?v=abcdefghijk",
                  "https://www.youtube.com/watch?v=short", "https://www.youtube.com/channel/abcdefghijk", "file:///C:/x", "",
                  "https://www.youtube.com/watch?vv=abcdefghijk", "abcdefghijk", "https://www.youtube.com/watchfoo?v=abcdefghijk"):
            self.assertIsNone(intake.youtube_id(u), u)   # 素の ID・/watch で始まるだけの道は受けない(yturl の strict)
        from ytt import yturl
        self.assertEqual(yturl.parse_video_id("abcdefghijk"), "abcdefghijk")   # strict でなければ素の ID も(ほかの入口の決まりは変えない)

    def test_parse_lines(self):
        ok, bad = intake.parse_lines("# メモ\n\nhttps://youtu.be/abcdefghijk 5\nhttps://youtu.be/bbbbbbbbbbb\nhttps://x.example/ 3\n"
                                     "https://youtu.be/ccccccccccc 11\nhttps://youtu.be/ddddddddddd 2 # ここがほしい\nhttps://youtu.be/eeeeeeeeeee よろしく\n", 3)
        self.assertEqual([(o["id"], o["top"]) for o in ok], [("abcdefghijk", 5), ("bbbbbbbbbbb", 3), ("ddddddddddd", 2)])
        self.assertEqual(len(bad), 3)
        # 文字コード(cp932・BOM)の読み(依頼の JSON)
        self.assertEqual(intake.decode_text("あ".encode("cp932")), "あ")
        self.assertEqual(intake.decode_text("\ufeffあ".encode("utf-8")), "あ")


class TestState(Base):
    def test_off_and_missing_folder(self):
        self.prefs.patch("intake", {"enabled": False})
        self.it.scan()
        self.assertEqual(self.it.snapshot()["state"], "off")
        self.prefs.patch("intake", {"enabled": True, "folder": os.path.join(self.tmp, "nai")})
        self.it.scan()
        snap = self.it.snapshot()
        self.assertEqual(snap["state"], "error")
        self.assertIn("見つかりません", snap["message"])
        self.prefs.patch("intake", {"folder": self.folder})
        self.it.scan()
        self.assertEqual(self.it.snapshot()["stateLabel"], "見張り中")


class TestSend(Base):
    """D-SEND: 下のフォルダを読まない・依頼済みの配信の引き方(2-9)・見回りの終わりの送り直し(2-6)"""

    def test_settings_folder_is_not_a_request(self):
        """受付のフォルダの下のフォルダ(設定 など)の JSON は依頼として読まない(下のフォルダは見ない)"""
        os.makedirs(os.path.join(self.folder, "設定"))
        with open(os.path.join(self.folder, "設定", "x.json"), "w", encoding="utf-8") as f:
            f.write('{"v":1}')
        self.scan2()
        self.assertEqual((self.runner.requests, self.runner.files, self.it.snapshot()["requests"]), ([], [], []))

    def test_requested_at(self):
        self.put_urls(["https://youtu.be/abcdefghijk 5"])
        self.scan2()
        self.assertEqual(self.it.requested_at("abcdefghijk"), int(self.now))
        for bad in ("bbbbbbbbbbb", "", None, 3):
            self.assertIsNone(self.it.requested_at(bad), bad)

    def test_flush_at_end_of_scan(self):
        """見回りの終わりに flush(受付がオフでも・依頼の処理で例外が出ても)。受付のフォルダが無ければ呼ばない。flush の失敗はログだけ"""
        calls, logs = [], []
        self.it.flush, self.it.log = lambda: calls.append(1), logs.append
        self.it.scan()
        self.assertEqual(len(calls), 1)
        self.prefs.patch("intake", {"enabled": False})
        self.it.scan()
        self.assertEqual(len(calls), 2, "オフでも送り直す(自動で送るのは受付のフォルダがあれば効く = 2-10)")
        self.prefs.patch("intake", {"enabled": True, "folder": os.path.join(self.tmp, "nai")})
        self.it.scan()
        self.assertEqual(len(calls), 2, "フォルダが無ければ呼ばない(Dropbox でない所に作らない)")
        self.prefs.patch("intake", {"folder": self.folder})

        def boom():
            raise OSError("x")
        self.it.flush = boom
        self.it.scan()
        self.assertTrue(any("送り直し" in m for m in logs), logs)


class TestUrlRequest(Base):
    """友人のアプリの URL の依頼(依頼の JSON の kind url)を受付全体で見る。手で置いたファイル(動画・.txt・.url など)は受け付けない(10-19)"""

    def test_url_request(self):
        rid = self.put_urls(["https://youtu.be/abcdefghijk 5", "https://example.com/x"])
        self.it.scan()
        self.assertEqual(self.runner.requests, [], "落ち着く前は処理しない")
        self.now += intake.SETTLE + 1
        self.it.scan()
        (items, got), = self.runner.requests
        self.assertEqual([(i["id"], i["top"], i["title"]) for i in items], [("abcdefghijk", 5, "題名 abcdefghijk")])
        self.assertEqual(got, rid)
        self.assertTrue(os.path.isfile(self.done(rid + ".request.json")))
        self.assertTrue(os.path.isfile(self.done(rid + ".request.理由.txt")))   # 飛ばした行の理由
        snap = self.it.snapshot()
        self.assertEqual((snap["today"], snap["requests"][0]["state"], snap["requests"][0]["kind"], snap["requests"][0]["flowLabel"]),
                         (1, "accepted", "url", "① 全自動"))
        # 同じ配信をもう一度: 断らない(ユーザー。解析・切り抜き・文字起こしは、まとめて実行が使い回す)
        rid2 = self.put_urls(["https://www.youtube.com/watch?v=abcdefghijk"])
        self.scan2()
        self.assertEqual(len(self.runner.requests), 2)
        self.assertTrue(os.path.isfile(self.done(rid2 + ".request.json")))
        # 1つの依頼の中で同じ配信を2回書いたら、1回だけ
        self.put_urls(["https://youtu.be/ccccccccccc", "https://www.youtube.com/watch?v=ccccccccccc 2"])
        self.scan2()
        self.assertEqual([i["id"] for i in self.runner.requests[2][0]], ["ccccccccccc"])

    def test_manual_files_are_rejected(self):
        """依頼の JSON の無いファイル(手で置いた動画・URL の .txt・.url)は受け付けない: 失敗\\ へ移して理由を添える・まとめて実行へは入れない・
        出力\\ には置かない(依頼 id が無い = 友人のアプリに知らせる先が無い)。記録の行に「① 全自動」は出さない"""
        for n, data in (("【さくらみこ】にぇ.mp4", b"video"), ("依頼.txt", "https://youtu.be/abcdefghijk 5\n"),
                        ("again.url", "[InternetShortcut]\nURL=https://www.youtube.com/watch?v=abcdefghijk\n")):
            self.put(n, data)
        self.scan2()
        self.assertEqual((self.runner.requests, self.runner.files), ([], []))
        for n in ("【さくらみこ】にぇ.mp4", "依頼.txt", "again.url"):
            self.assertTrue(os.path.isfile(self.failed(n)), n)
        with open(self.failed("依頼.理由.txt"), encoding="utf-8-sig") as f:
            self.assertIn("友人のアプリから送ってください", f.read())
        recs = self.it.snapshot()["requests"]
        self.assertEqual(sorted((r["source"], r["state"], r["flowLabel"], r["reason"]) for r in recs),
                         [("manual", "rejected", "", intake.MANUAL_REASON)] * 3)
        self.assertFalse(os.path.exists(os.path.join(self.folder, intake.OUT_DIR)))
        self.assertNotIn("abcdefghijk", self.it.st["videos"])

    def test_long_and_live(self):
        self.infos = {"aaaaaaaaaaa": {"duration": 9 * 3600.0, "live": "was_live", "title": "", "channel": ""},
                      "bbbbbbbbbbb": {"duration": None, "live": "is_live", "title": "", "channel": ""}}
        rid = self.put_urls(["https://youtu.be/aaaaaaaaaaa", "https://youtu.be/bbbbbbbbbbb"])
        self.scan2()
        self.assertEqual(self.runner.requests, [])
        r = self.it.snapshot()["requests"][0]
        self.assertEqual(r["state"], "rejected")
        self.assertIn("長すぎます", r["items"][0]["reason"])
        self.assertIn("配信中", r["items"][1]["reason"])
        self.assertEqual(r["title"], rid + ".request.json", "題名が分からなければファイル名")

    def test_rejected_shows_stream_title(self):
        """断った配信も、題名が分かれば URL ではなく題名で出す(一覧で読めるように)"""
        self.infos = {"bbbbbbbbbbb": {"duration": None, "live": "is_live", "title": "【雑談】配信中の題名", "channel": ""}}
        self.put_urls(["https://youtu.be/bbbbbbbbbbb 2"])
        self.scan2()
        r = self.it.snapshot()["requests"][0]
        self.assertEqual(r["title"], "【雑談】配信中の題名")
        self.assertEqual(r["items"][0]["label"], "【雑談】配信中の題名(2 個)")

    def test_no_daily_limit(self):
        """1 日の件数の上限は無い: 同じ日に何件でも受け付け、フォルダに残さない。今日の件数は数えるだけ"""
        for i in range(7):
            self.put_urls(["https://youtu.be/%s" % (chr(ord("a") + i) * 11)])
        self.scan2()
        self.assertEqual(len(self.runner.requests), 7)
        self.assertEqual([n for n in os.listdir(self.folder) if n.endswith(".json")], [], "フォルダに残さない(翌日に回さない)")
        snap = self.it.snapshot()
        self.assertEqual((snap["today"], snap["message"]), (7, ""))
        self.assertNotIn("dailyMax", snap)
        self.assertNotIn("held", snap)

    def test_unknown_type(self):
        self.put("写真.png", b"x")
        self.scan2()
        self.assertTrue(os.path.isfile(self.failed("写真.png")))
        self.assertEqual(self.runner.requests + self.runner.files, [])
        self.assertEqual(self.it.snapshot()["requests"][0]["reason"], intake.MANUAL_REASON)

    def test_os_files_are_ignored(self):
        """desktop.ini・Thumbs.db・隠しファイルは依頼ではない(断って移すと、また作られて「断った」が毎回増えた)"""
        for n in ("desktop.ini", "Thumbs.db", "hidden.mp4"):
            self.put(n, b"x")
        if os.name == "nt":
            import ctypes
            ctypes.windll.kernel32.SetFileAttributesW(os.path.join(self.folder, "hidden.mp4"), 0x2)
        else:
            os.rename(os.path.join(self.folder, "hidden.mp4"), os.path.join(self.folder, ".hidden.mp4"))
        self.scan2()
        self.assertEqual(self.it.snapshot()["requests"], [])
        self.assertFalse(os.path.exists(self.failed()))
        self.assertTrue(os.path.isfile(os.path.join(self.folder, "desktop.ini")), "OS のファイルは動かさない")
        # 前の版で断った記録は、読み直すときに消す
        self.it.st["requests"] = [{"title": "desktop.ini", "state": "rejected"}, {"title": "a.mp4", "state": "accepted"}]
        self.it._save_state()
        again = intake.Intake(self.prefs, lambda: self.runner, self.data, clock=lambda: self.now)
        self.assertEqual([r["title"] for r in again.snapshot()["requests"]], ["a.mp4"])

    def test_runner_refuses(self):
        self.runner.fail = "順番待ちが多すぎます(20本まで)"
        self.put_urls(["https://youtu.be/aaaaaaaaaaa"])
        self.scan2()
        r = self.it.snapshot()["requests"][0]
        self.assertEqual(r["state"], "rejected")
        self.assertIn("順番待ち", r["reason"])


class TestVideo(Base):
    def send_video(self, rid, names, **extra):
        """友人のアプリの動画の依頼(<依頼 id>__<名前> の動画 + 依頼の JSON)を置いて流す"""
        for n in names:
            self.put("%s__%s" % (rid, n), ("clip-" + n).encode("utf-8"))
        self.put(rid + ".request.json", json.dumps(dict({"v": 1, "kind": "video", "id": rid, "files": ["%s__%s" % (rid, n) for n in names]}, **extra),
                                                   ensure_ascii=False))
        self.scan2()

    def test_flow_label_only_when_known(self):
        """行の「① 全自動」は流れが分かる依頼だけ(友人の依頼は断っても ①・形の読めない依頼・手で置いたファイル・知らないファイルは出さない。9a-3)"""
        self.put("手で置いた.mp4", b"m")
        self.put("写真.png", b"x")
        rid = "20261001-120000-abc130"
        self.put(rid + ".request.json", "{broken")
        rid2 = "20261001-120000-abc131"
        self.put(rid2 + ".request.json", json.dumps({"v": 1, "kind": "video", "id": rid2, "files": []}))
        self.scan2()
        labels = {r["title"]: r["flowLabel"] for r in self.it.snapshot()["requests"]}
        self.assertEqual(labels, {"手で置いた.mp4": "", "写真.png": "", rid + ".request.json": "", rid2 + ".request.json": "① 全自動"})

    def test_unknown_streamer_goes_without_color(self):
        self.send_video("20261001-120000-abc150", ["x.mp4"], streamer="だれでもない人")
        self.assertIsNone(self.runner.files[0]["streamer"])
        self.assertTrue(any("色なし" in i["reason"] for i in self.it.snapshot()["requests"][0]["items"]))

    def test_probe_rejects(self):
        rid = "20261001-120000-abc151"
        self.probes[rid + "__bad.mp4"] = {"ok": False, "duration": None, "reason": "音声のある動画として読めませんでした"}
        self.probes[rid + "__long.mp4"] = {"ok": True, "duration": 10 * 3600.0, "reason": ""}
        self.send_video(rid, ["bad.mp4", "long.mp4"])
        self.assertEqual(self.runner.files, [])
        self.assertTrue(os.path.isfile(self.failed(rid + "__bad.mp4")) and os.path.isfile(self.failed(rid + "__long.mp4")))
        reasons = [i["reason"] for i in self.it.snapshot()["requests"][0]["items"]]
        self.assertTrue(any("読めませんでした" in r for r in reasons) and any("長すぎます" in r for r in reasons), reasons)

    def test_app_request_video(self):
        rid = "20261001-120000-abc123"
        self.put(rid + "__にぇの叫び.mp4", b"clip")
        self.it.scan()
        self.now += intake.SETTLE + 1
        self.it.scan()
        self.assertEqual(self.runner.files, [], "JSON が届くまで待つ")
        self.put(rid + ".request.json", json.dumps({"v": 1, "kind": "video", "id": rid, "files": [rid + "__にぇの叫び.mp4"],
                                                     "streamer": "さくらみこ", "sentAt": ""}, ensure_ascii=False))
        self.scan2()
        f, = self.runner.files
        self.assertEqual((f["title"], f["streamer"], f["rid"]), ("にぇの叫び", "さくらみこ", rid))   # flow の無い 1.0.0 のアプリ = ① (RS5-F)
        self.assertEqual(self.it.snapshot()["requests"][0]["flowLabel"], "① 全自動")
        r = self.it.snapshot()["requests"][0]
        self.assertEqual((r["source"], r["state"]), ("app", "accepted"))
        self.assertNotIn("memo", r)
        self.assertTrue(os.path.isfile(self.done(rid + ".request.json")))
        self.assertTrue(os.path.isfile(self.done(rid + "__にぇの叫び.mp4")))

    def test_same_video_is_accepted_again(self):
        """前に受け付けた動画と同じ中身でも断らない(送り直し。ユーザー)"""
        for i, rid in enumerate(("20261001-120000-abc140", "20261001-120000-abc141")):
            self.put(rid + "__同じ.mp4", b"same clip")
            self.put(rid + ".request.json", json.dumps({"v": 1, "kind": "video", "id": rid, "files": [rid + "__同じ.mp4"], "flow": "auto",
                                                         "videoTracks": i + 1}))
            self.scan2()
        self.assertEqual([(f["rid"], f["tracks"]) for f in self.runner.files],
                         [("20261001-120000-abc140", 1), ("20261001-120000-abc141", 2)])
        self.assertEqual([r["state"] for r in self.it.snapshot()["requests"]], ["accepted", "accepted"])
        self.assertEqual(len({f["path"] for f in self.runner.files}), 2, "作業データには別のコピーとして入る")

    def test_app_request_missing_video_times_out(self):
        rid = "20261001-120000-abc124"
        self.put(rid + ".request.json", json.dumps({"v": 1, "kind": "video", "id": rid, "files": [rid + "__x.mp4"]}))
        self.scan2()
        self.assertTrue(os.path.isfile(os.path.join(self.folder, rid + ".request.json")), "動画を待つ")
        self.now += intake.WAIT_FILES + 10
        self.it.scan()
        self.assertTrue(os.path.isfile(self.failed(rid + ".request.json")))

    def test_app_request_rejects_path_tricks(self):
        rid = "20261001-120000-abc125"
        self.put(rid + ".request.json", json.dumps({"v": 1, "kind": "video", "id": rid, "files": ["..\\..\\secret.mp4", "C:\\x.mp4"]}))
        self.scan2()
        self.assertEqual(self.runner.files, [])
        self.assertTrue(os.path.isfile(self.failed(rid + ".request.json")))

    def test_rejected_app_request_tells_friend(self):
        """段9 9-4: 友人のアプリの依頼を受け付けなかったら、出力\\<依頼 id>__<題>.失敗.txt に理由(アプリの「受け取る」に出る)。
        手で置いたファイル(依頼 id が無い)は 出力 に置かない"""
        rid = "20261001-120000-abc131"
        self.put(rid + ".request.json", json.dumps({"v": 1, "kind": "video", "id": rid, "files": []}))
        self.put("手で置いた.txt", "https://example.com/not-youtube")
        self.scan2()
        out = os.path.join(self.folder, intake.OUT_DIR)
        names = os.listdir(out)
        self.assertEqual(len(names), 1)
        self.assertTrue(names[0].startswith(rid + "__") and names[0].endswith(".失敗.txt"))
        with open(os.path.join(out, names[0]), encoding="utf-8-sig") as f:
            text = f.read()
        self.assertIn("受け付けられませんでした", text)
        self.assertIn("動画の名前が書かれていません", text)

    def test_flow_from_app(self):
        """友人が選んだ形(① auto / ② check / ③ manual)と、① のパックの届け先(見張るフォルダの 出力\\)をまとめて実行へ渡す"""
        rid = "20261001-120000-abc127"
        self.put(rid + "__clip.mp4", b"clip-auto")
        self.put(rid + ".request.json", json.dumps({"v": 1, "kind": "video", "id": rid, "files": [rid + "__clip.mp4"], "flow": "auto"}))
        rid2 = "20261001-120000-abc128"
        self.put(rid2 + ".request.json", json.dumps({"v": 1, "kind": "url", "id": rid2, "flow": "manual",
                                                      "items": [{"url": "https://youtu.be/abcdefghijk", "top": 3}]}))
        rid3 = "20261001-120000-abc129"
        self.put(rid3 + ".request.json", json.dumps({"v": 1, "kind": "url", "id": rid3, "flow": "rm -rf",
                                                      "items": [{"url": "https://youtu.be/bbbbbbbbbbb", "top": 3}]}))
        self.scan2()
        f, = self.runner.files
        self.assertEqual(f["deliver"], os.path.join(self.folder, intake.OUT_DIR))
        self.assertEqual(len(self.runner.requests), 2)
        labels = {r["title"]: r["flowLabel"] for r in self.it.snapshot()["requests"]}
        self.assertEqual(sorted(labels.values()), ["① 全自動"] * 3)   # ③ manual も知らない形も ① (断らない)
        origs = {r["title"]: r.get("flowOrig") for r in self.it.snapshot()["requests"]}
        self.assertEqual(sorted(str(v) for v in origs.values()), ["None", "None", "manual"])   # 元の値は記録に残す(① と知らない形は残さない)

    def test_app_request_url(self):
        rid = "20261001-120000-abc126"
        self.put(rid + ".request.json", json.dumps({"v": 1, "kind": "url", "id": rid, "items": [{"url": "https://youtu.be/abcdefghijk", "top": 7}]}))
        self.scan2()
        (items, got), = self.runner.requests
        self.assertEqual((items[0]["id"], items[0]["top"], got), ("abcdefghijk", 7, rid))
        self.assertIsNone(self.runner.last["speakers"])

    def test_speakers_passed(self):
        """話す人(1.3.0 のアプリ): 人数と名前をまとめて実行へ。形が違えば話者分離しない"""
        self.assertEqual(intake.parse_speakers({"count": 2, "names": [" 兎田ぺこら ", "", "兎田ぺこら", "宝鐘マリン", "x"]}),
                         {"count": 2, "names": ["兎田ぺこら", "宝鐘マリン"], "styles": {}})   # 古い形(people なし)= styles は空
        for bad in (None, {"count": 0}, {"count": 11}, {"count": "2"}, {"count": True}):
            self.assertIsNone(intake.parse_speakers(bad))
        rid = "20261001-120000-abc130"
        self.put(rid + ".request.json", json.dumps({"v": 1, "kind": "url", "id": rid, "speakers": {"count": 1, "names": ["さくらみこ"]},
                                                     "items": [{"url": "https://youtu.be/abcdefghijk", "top": 2}]}, ensure_ascii=False))
        self.scan2()
        self.assertEqual(self.runner.last["speakers"], {"count": 1, "names": ["さくらみこ"], "styles": {}})
        self.assertEqual(self.it.snapshot()["requests"][0]["speakersLabel"], "配信者: 1人(さくらみこ)")

    def test_parse_speakers_people_style(self):
        """2.1.0 のアプリ: people[].style.color(16 進 6 桁)を styles に。# つき・小文字も受け、# つきの形にそろえる。
        形の違う値・names に無い名前・知らない鍵はその項目だけ黙って捨てる(外から来る文字なので、画面・Lua に入る前に 6 桁だけにする)"""
        ps = intake.parse_speakers
        got = ps({"count": 3, "names": ["A", "B", "C"],
                  "people": [{"name": "A", "style": {"color": "FF00AA"}}, {"name": " B ", "style": {"color": "#00ff7f"}}, {"name": "C"}]})
        self.assertEqual(got, {"count": 3, "names": ["A", "B", "C"], "styles": {"A": {"color": "#FF00AA"}, "B": {"color": "#00FF7F"}}})
        for bad in ("FF00A", "FF00AAA", "GG00AA", "#", "", " ", "FF00AA\nx", "0xFF00AA", "FF 00AA", 123456, 0xFF00AA, None, True, ["FF00AA"], {"c": 1}, "ＦＦ００ＡＡ"):
            self.assertEqual(ps({"count": 1, "names": ["A"], "people": [{"name": "A", "style": {"color": bad}}]})["styles"], {}, repr(bad))
        # 知らない鍵は捨てて、色は残す
        got = ps({"count": 1, "names": ["A"], "people": [{"name": "A", "style": {"color": "112233", "font": "Arial", "size": 40, "outline": {"x": 1}}}]})
        self.assertEqual(got["styles"], {"A": {"color": "#112233"}})
        # names に無い名前・count で切った後の名前・同じ名前は先のもの・形の違う people
        got = ps({"count": 1, "names": ["A", "B"], "people": [{"name": "B", "style": {"color": "111111"}}, {"name": "Z", "style": {"color": "222222"}},
                                                                {"name": "A", "style": {"color": "333333"}}, {"name": "A", "style": {"color": "444444"}}]})
        self.assertEqual((got["names"], got["styles"]), (["A"], {"A": {"color": "#333333"}}))
        for people in (None, "x", 3, {"name": "A"}, ["A"], [None, 5, {"name": 3, "style": {"color": "111111"}}, {"name": "A", "style": "red"}, {"name": "A", "style": []},
                                                              {"name": "A\x00", "style": {"color": "111111"}}, {"style": {"color": "111111"}}]):
            self.assertEqual(ps({"count": 1, "names": ["A"], "people": people})["styles"], {}, repr(people))
        self.assertEqual(ps({"count": 1, "names": ["A"]})["styles"], {})   # 古いアプリ: people なし

    def test_url_request_streamer(self):
        """URL の依頼の streamer(2.1.0 のアプリ): メンバーと合えばまとめて実行へ。合わなければ自動(None)+ 知らせ。無ければ今までどおり(None)"""
        def send(rid, extra):
            d = {"v": 1, "kind": "url", "id": rid, "items": [{"url": "https://youtu.be/abcdefghijk", "top": 2}]}
            d.update(extra)
            self.put(rid + ".request.json", json.dumps(d, ensure_ascii=False))
            self.scan2()
            return self.it.snapshot()["requests"][0]
        rec = send("20261001-120000-abc141", {"streamer": "さくらみこ"})
        self.assertEqual((self.runner.last["streamer"], rec["streamer"], rec["state"]), ("さくらみこ", "さくらみこ", "accepted"))
        self.assertFalse([i for i in rec["items"] if i["label"] == "配信者"])
        rec = send("20261001-120000-abc142", {"streamer": "だれでもない人"})
        self.assertEqual((self.runner.last["streamer"], rec["streamer"], rec["state"]), (None, "", "accepted"))
        self.assertTrue(any(i["label"] == "配信者" and "色なし" in i["reason"] and i["state"] == "accepted" for i in rec["items"]))
        self.assertEqual(rec["title"], "題名 abcdefghijk")   # 知らせの行が題名を奪わない
        rec = send("20261001-120000-abc143", {"streamer": ""})
        self.assertEqual((self.runner.last["streamer"], rec["streamer"]), (None, ""))
        self.assertFalse([i for i in rec["items"] if i["label"] == "配信者"])
        rec = send("20261001-120000-abc144", {})   # 古いアプリ: streamer なし
        self.assertEqual((self.runner.last["streamer"], rec["streamer"]), (None, ""))
        self.assertFalse([i for i in rec["items"] if i["label"] == "配信者"])
        rec = send("20261001-120000-abc145", {"streamer": 5})   # 文字列でない = 合わない名前として扱う(自動)
        self.assertIsNone(self.runner.last["streamer"])

    def test_video_tracks_passed_only_for_auto(self):
        """映像トラックの数(1.4.0 のアプリ。① 全自動のときだけ): 1〜5 をまとめて実行へ。無い・形が違えば 1。②③ は渡さない"""
        for v, want in ((3, 3), (5, 5), (1, 1), (6, 1), (0, 1), ("3", 1), (True, 1), (None, 1)):
            self.assertEqual(intake.parse_video_tracks(v), want, v)
        rid = "20261001-120000-abc131"
        self.put(rid + ".request.json", json.dumps({"v": 1, "kind": "url", "id": rid, "flow": "auto", "videoTracks": 3,
                                                     "items": [{"url": "https://youtu.be/abcdefghijk", "top": 2}]}))
        self.scan2()
        self.assertEqual(self.runner.last["tracks"], 3)
        self.assertEqual(self.it.snapshot()["requests"][0]["tracksLabel"], "映像トラック: 3本")
        rid = "20261001-120000-abc132"                                   # 古いアプリの ② も ① として扱う = トラックも渡す
        self.put(rid + ".request.json", json.dumps({"v": 1, "kind": "url", "id": rid, "flow": "check", "videoTracks": 3,
                                                     "items": [{"url": "https://youtu.be/bbbbbbbbbbb", "top": 2}]}))
        self.scan2()
        self.assertEqual(self.runner.last["tracks"], 3)
        self.assertEqual(self.it.snapshot()["requests"][0]["flowOrig"], "check")

    def test_ranges_cut_weights_from_app(self):
        """2.0.0 のアプリ: 時刻で指定した区間(配信ごと)・カット(① だけ)・解析の重みを、形を確かめてまとめて実行へ"""
        self.assertEqual(intake.parse_ranges(None), ([], []))
        ok, bad = intake.parse_ranges([{"start": 10, "end": 20}, {"start": 5, "end": 5}, {"start": 0, "end": 360001}, {"start": "1", "end": 2}, "x",
                                       {"start": True, "end": 2}, {"start": 10, "end": 20}, {"start": 0, "end": 3 * 3600}])
        self.assertEqual((ok, len(bad)), ([(10, 20), (0.0, 10800.0)], 5))   # 区間 1 つの長さは上限なし(C-2-7・C-5-5)
        self.assertEqual(len(intake.parse_ranges([{"start": i * 10, "end": i * 10 + 5} for i in range(12)])[0]), 10)
        ok, bad = intake.parse_ranges([{"start": 0.01, "end": 0.04}, {"start": 1.26, "end": 2}])   # 丸めたあと長さ 0 は断る(9b-2)・丸めた値で渡す
        self.assertEqual((ok, len(bad)), ([(1.3, 2.0)], 1))
        self.assertIn("短すぎます", bad[0])
        self.assertEqual([intake.parse_cut(x) for x in ("none", "silence", "rows", None, 1)], ["none", "silence", None, None, None])
        self.assertEqual(intake.parse_weights({"audio": 1.5, "chat": 0, "comments": 3}), {"wAudio": 1.5, "wChat": 0.0, "wComments": 3.0})
        for badw in (None, {}, {"audio": 1, "chat": 1}, {"audio": 4, "chat": 1, "comments": 1}, {"audio": "1", "chat": 1, "comments": 1}, {"audio": True, "chat": 1, "comments": 1}):
            self.assertIsNone(intake.parse_weights(badw), badw)

        self.infos["abcdefghijk"] = {"duration": 7200.0, "live": "not_live", "title": "長い配信", "channel": "ch"}
        self.infos["bbbbbbbbbbb"] = {"duration": 600.0, "live": "not_live", "title": "短い配信", "channel": "ch"}
        rid = "20261002-120000-abc201"
        self.put(rid + ".request.json", json.dumps({"v": 1, "kind": "url", "id": rid, "flow": "auto", "videoTracks": 2, "cut": "silence",
                                                     "weights": {"audio": 1.5, "chat": 1.0, "comments": 0.7},
                                                     "items": [{"url": "https://youtu.be/abcdefghijk", "top": 1, "ranges": [{"start": 5025, "end": 5110}, {"start": 60, "end": 90}]},
                                                               {"url": "https://youtu.be/bbbbbbbbbbb", "top": 3, "ranges": [{"start": 590, "end": 650}, {"start": 700, "end": 720}, {"start": 9, "end": 3}]},
                                                               {"url": "https://youtu.be/ccccccccccc", "top": 2}]}))
        self.scan2()
        (items, _rid), = self.runner.requests
        by = {i["id"]: i for i in items}
        self.assertEqual((by["abcdefghijk"]["top"], by["abcdefghijk"]["ranges"]), (2, [(5025, 5110), (60, 90)]))   # 切り抜く数は区間の数より小さくしない
        self.assertEqual((by["bbbbbbbbbbb"]["top"], by["bbbbbbbbbbb"]["ranges"], by["bbbbbbbbbbb"]["duration"]), (2, [(590, 600.0)], 600.0))   # 配信の長さで切る・長さより後の区間の分は自動で埋めない
        self.assertEqual((by["ccccccccccc"]["top"], by["ccccccccccc"]["ranges"]), (2, []))
        self.assertEqual((self.runner.last["cut"], self.runner.last["weights"], self.runner.last["tracks"]), ("silence", {"wAudio": 1.5, "wChat": 1.0, "wComments": 0.7}, 2))
        rec = self.it.snapshot()["requests"][0]
        self.assertEqual((rec["rangesLabel"], rec["cutLabel"], rec["weightsLabel"]),
                         ("区間: 1:23:45〜1:25:10・0:01:00〜0:01:30・0:09:50〜0:10:00", "カット: 無音で削る", "重み: 音声 1.5・チャット 1.0・コメント 0.7"))
        reasons = [i["reason"] for i in rec["items"] if i["state"] == "rejected"]
        self.assertEqual(len(reasons), 2, reasons)
        self.assertTrue(any("より後です" in r for r in reasons) and any("終了が開始より前" in r for r in reasons), reasons)
        # 断った区間は、友人のアプリの「受け取る」に理由が届く(ほかは進める)
        note = [n for n in os.listdir(os.path.join(self.folder, "出力")) if n.startswith(rid)]
        self.assertEqual(len(note), 1)

        # 古いアプリの ② ③ も ① として扱う: 区間もカットも渡す / 動画の ①: カットを渡す
        rid = "20261002-120000-abc202"
        self.put(rid + ".request.json", json.dumps({"v": 1, "kind": "url", "id": rid, "flow": "check", "cut": "silence",
                                                     "items": [{"url": "https://youtu.be/ddddddddddd", "top": 3, "ranges": [{"start": 1, "end": 9}]}]}))
        self.scan2()
        self.assertEqual((self.runner.requests[-1][0][0]["ranges"], self.runner.last["cut"], self.runner.last["weights"]), ([(1, 9)], "silence", None))
        self.assertEqual(self.it.snapshot()["requests"][0]["cutLabel"], "カット: 無音で削る")
        rid = "20261002-120000-abc203"
        self.put(rid + ".request.json", json.dumps({"v": 1, "kind": "url", "id": rid, "flow": "manual",
                                                     "items": [{"url": "https://youtu.be/eeeeeeeeeee", "top": 3, "ranges": [{"start": 1, "end": 9}]}]}))
        self.scan2()
        self.assertEqual((self.runner.requests[-1][0][0]["ranges"], self.runner.requests[-1][0][0]["top"]), ([(1, 9)], 3))
        rid = "20261002-120000-abc204"
        self.put(rid + "__a.mp4", b"v")
        self.put(rid + ".request.json", json.dumps({"v": 1, "kind": "video", "id": rid, "flow": "auto", "files": [rid + "__a.mp4"], "cut": "silence"}))
        self.scan2()
        self.assertEqual(self.runner.files[-1]["cut"], "silence")
        self.assertEqual(self.it.snapshot()["requests"][0]["cutLabel"], "カット: 無音で削る")

    def test_all_ranges_out_of_stream_rejects(self):
        """指定した区間が全部、配信の長さより後(自動の分も無い)なら、その配信は流さない"""
        self.infos["abcdefghijk"] = {"duration": 100.0, "live": "not_live", "title": "短い", "channel": ""}
        rid = "20261002-120000-abc205"
        self.put(rid + ".request.json", json.dumps({"v": 1, "kind": "url", "id": rid, "flow": "check",
                                                     "items": [{"url": "https://youtu.be/abcdefghijk", "top": 1, "ranges": [{"start": 200, "end": 260}]}]}))
        self.scan2()
        self.assertEqual(self.runner.requests, [])
        self.assertEqual(self.it.snapshot()["requests"][0]["state"], "rejected")

    def test_state_persists(self):
        self.put_urls(["https://youtu.be/aaaaaaaaaaa"])
        self.scan2()
        again = intake.Intake(self.prefs, lambda: self.runner, self.data, clock=lambda: self.now, info=lambda v: None)
        self.assertEqual(again.snapshot()["today"], 1)
        self.assertIn("aaaaaaaaaaa", again.st["videos"])


@unittest.skipUnless(tools.find_tool("ffmpeg") and tools.find_tool("ffprobe"), "ffmpeg / ffprobe が無い")
class TestRequestFolder(Base):
    """友人の依頼は 1 依頼 1 フォルダ。書き出し先が設定されていて固定ディスクなら <書き出し先>/依頼/<日付>_<題>_<id6>/ に置いて案件にする。
    そうでなければ app/intake/<日付>/<依頼 id>/"""

    def send(self, rid, names):
        for n in names:
            self.put("%s__%s" % (rid, n), ("clip-" + n).encode("utf-8"))
        self.put(rid + ".request.json", json.dumps({"v": 1, "kind": "video", "id": rid, "files": ["%s__%s" % (rid, n) for n in names], "flow": "auto"}))
        self.scan2()

    def with_out(self, out):
        for p in (mock.patch.object(intake.placement, "configured_out_dir", return_value=out),
                  mock.patch.object(intake.placement._fsio, "is_fixed_drive", return_value=True)):
            p.start()
            self.addCleanup(p.stop)

    def test_into_request_folder_with_case(self):
        from flow import placement
        out = os.path.join(self.tmp, "出力")
        self.with_out(out)
        rid = "20261001-120000-abc123"
        self.send(rid, ["一本目.mp4", "二本目.mp4"])
        a, b = (f["path"] for f in self.runner.files)
        want = os.path.join(out, "依頼", "%s_一本目_abc123" % self.it._today())
        self.assertEqual((os.path.dirname(a), os.path.dirname(b)), (want, want), "同じ依頼の動画は 1 つのフォルダ")
        self.assertIsNotNone(placement.read_case(want), "案件の身分証がある = 文書が 作業用 に置ける")
        self.assertEqual(placement.doc_home(a, out), os.path.normpath(os.path.join(want, "作業用")))
        self.assertFalse(os.path.exists(os.path.join(self.data, "intake")))
        # 別の依頼 = 別のフォルダ(同じ日・同じ題でも id6 が違う)
        self.send("20261001-120100-def456", ["一本目.mp4"])
        self.assertNotEqual(os.path.dirname(self.runner.files[2]["path"]), want)

    def test_restart_keeps_same_request_folder(self):
        """入口を起こし直して覚えが空でも、同じ依頼の 2 本目は 1 本目のフォルダへ(書き出し先が設定済み・未設定のどちらも)"""
        # 書き出し先が未設定の口(アプリの受付)
        rid3 = "20261001-120000-abc131"
        self.send(rid3, ["一本目.mp4"])
        self.it._req_dirs.clear()
        self.send(rid3, ["二本目.mp4"])
        self.assertEqual(os.path.dirname(self.runner.files[0]["path"]), os.path.dirname(self.runner.files[1]["path"]))
        # 書き出し先が設定済み
        out = os.path.join(self.tmp, "出力")
        self.with_out(out)
        rid = "20261001-120000-abc130"
        self.send(rid, ["一本目.mp4"])
        self.it._req_dirs.clear()
        self.send("20261001-120000-abd130", ["他.mp4"])   # id6 の違う別の依頼
        self.it._req_dirs.clear()
        self.send(rid, ["二本目.mp4"])
        a, b, c = (f["path"] for f in self.runner.files[2:])
        self.assertEqual(os.path.dirname(a), os.path.dirname(c))
        self.assertNotEqual(os.path.dirname(a), os.path.dirname(b))

    def test_long_and_bad_title_is_trimmed(self):
        out = os.path.join(self.tmp, "出力")
        self.with_out(out)
        self.send("20261001-120000-abc125", ['【配信者】' + "あ" * 80 + '.mp4'])
        d = os.path.dirname(self.runner.files[0]["path"])
        name = os.path.basename(d)
        self.assertTrue(name.endswith("_abc125") and not any(c in name for c in ':*?"<>|'), name)
        self.assertIn("【配信者】", name)
        self.assertLessEqual(len(name), 10 + 1 + 40 + 1 + 6)
        self.assertLessEqual(len(self.runner.files[0]["path"]), 240)

    def test_fallback_to_app_intake(self):
        """書き出し先が未設定(既定)・固定ディスクでない → app/intake/<日付>/<依頼 id>/"""
        rid = "20261001-120000-abc126"
        self.send(rid, ["x.mp4"])
        self.assertEqual(os.path.dirname(self.runner.files[0]["path"]), os.path.join(self.data, "intake", self.it._today(), rid))
        with mock.patch.object(intake.placement, "configured_out_dir", return_value=os.path.join(self.tmp, "外付け")), \
                mock.patch.object(intake.placement._fsio, "is_fixed_drive", return_value=False):
            self.send("20261001-120000-abc127", ["y.mp4"])
        self.assertEqual(os.path.dirname(self.runner.files[1]["path"]), os.path.join(self.data, "intake", self.it._today(), "20261001-120000-abc127"))


class TestVideoNoSlots(Base):
    """届いた動画の確かめ(本物の ffprobe)と、受付が重い処理の枠を待たないこと(opt-human 9a-1)。lavfi の短い動画を「届いた動画」にする。
    30fps にそろえるのはまとめて実行の段 normalize(テストは src/flow/tests/test_run.py の TestStepNormalize)"""

    def setUp(self):
        super().setUp()
        self.logs = []
        self.it = intake.Intake(self.prefs, lambda: self.runner, self.data, clock=lambda: self.now, log=self.logs.append,
                                probe=lambda p: {"ok": True, "duration": 2.0, "reason": ""}, info=lambda v: None)

    def make(self, name, fps, ext=".mp4", vcodec="libx264"):
        path = os.path.join(self.folder, name + ext)
        subprocess.run([tools.find_tool("ffmpeg"), "-v", "error", "-y", "-f", "lavfi", "-i", "testsrc=size=160x120:rate=%s:duration=2" % fps,
                        "-f", "lavfi", "-i", "sine=frequency=440:duration=2", "-c:v", vcodec, "-pix_fmt", "yuv420p", "-c:a", "aac", "-shortest", path],
                       check=True, stdin=subprocess.DEVNULL, creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0))
        return path

    def test_probe_video_needs_audio(self):
        """届いた動画の確かめ(probe_video。中は normalize.probe = 30fps の判定と同じ ffprobe の呼び方):
        音声があれば ok と長さ・映像だけ・壊れた・無いファイルは「音声のある動画として読めませんでした」"""
        ok = intake.probe_video(self.make("音あり", 30))
        self.assertEqual((ok["ok"], ok["reason"]), (True, ""))
        self.assertAlmostEqual(ok["duration"], 2.0, delta=0.1)
        silent = os.path.join(self.folder, "映像だけ.mp4")
        subprocess.run([tools.find_tool("ffmpeg"), "-v", "error", "-y", "-f", "lavfi", "-i", "testsrc=size=160x120:rate=30:duration=1", "-c:v", "libx264", silent],
                       check=True, stdin=subprocess.DEVNULL, creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0))
        bad = os.path.join(self.folder, "壊れた.mp4")
        with open(bad, "wb") as f:
            f.write(os.urandom(3000))
        for p in (silent, bad, os.path.join(self.folder, "無い.mp4")):
            self.assertEqual(intake.probe_video(p), {"ok": False, "duration": None, "reason": "音声のある動画として読めませんでした"}, p)

    def test_scan_does_not_wait_for_heavy_slots(self):
        """重い処理の枠を上限まで埋めた状態で 30fps でない動画を置いても、scan はすぐ返り、別の見回りが錠を取れる(9a-1 の再現。
        scan が錠を持ったまま SLOTS.slot で待つと、枠が空くまでライブ配信の依頼・「要らない」・送り返しの見回りも止まる)。
        受付は写して start_file に渡すだけ(写しは 60fps のまま。友人の元のファイルは受付済みへ移るだけ)"""
        rid = "20261001-120000-abc160"
        src = self.make(rid + "__【さくらみこ】にぇ", 60)
        self.put(rid + ".request.json", json.dumps({"v": 1, "kind": "video", "id": rid, "files": [os.path.basename(src)], "streamer": "さくらみこ"},
                                                   ensure_ascii=False))
        with open(src, "rb") as f:
            original = f.read()
        slots = jobs.HeavySlots(limit=1, reserved={})
        token = slots.acquire("test", "枠を埋める")
        try:
            with mock.patch.object(jobs, "SLOTS", slots):
                self.it.scan()
                self.now += intake.SETTLE + 1
                t = threading.Thread(target=self.it.scan, daemon=True)
                t.start()
                t.join(30)
                self.assertFalse(t.is_alive(), "scan が重い処理の枠を待って止まった")
                self.assertTrue(self.it.lock.acquire(timeout=1), "別の見回り(次の回・画面の snapshot)が錠を取れる")
                self.it.lock.release()
                self.assertEqual(slots.snapshot()["waiting"], [], "受付は枠を待たない")
        finally:
            slots.release(token)
        p = self.runner.files[0]["path"]
        with open(p, "rb") as f:
            self.assertEqual(f.read(), original, "受付は写すだけ(30fps は実行の段 normalize)")
        self.assertTrue(p.startswith(os.path.join(self.data, "intake")))
        self.assertEqual(normalize.probe(self.done(os.path.basename(src)))["r_frame_rate"], "60/1")
        rec = self.it.snapshot()["requests"][0]
        self.assertEqual((rec["state"], rec["items"][0]["reason"]), ("accepted", ""))
        self.assertEqual(self.it.message, "")


class TestReturns(Base):
    """友人の送り返し(同期フォルダの 送り返し\\。F1 の F2): 見回りのたびに returns.scan が app/friend-returns へ並べる。依頼の一覧には出さない"""

    def test_scan_files_returns(self):
        import json
        import zipfile
        inbox = os.path.join(self.folder, "送り返し")
        os.makedirs(inbox)
        zp = os.path.join(inbox, "20261011-120000-abcdef__r1.zip")
        with zipfile.ZipFile(zp, "w") as z:
            z.writestr("manifest.json", json.dumps({"schema": "youtube-tools-outbox/v1"}))
            z.writestr("run.json", "{}")
        os.utime(zp, (self.now - 600, self.now - 600))
        self.it.clock = lambda: self.now
        self.it.scan()
        self.assertTrue(os.path.isfile(os.path.join(self.data, "friend-returns", time.strftime("%Y-%m", time.localtime(self.now)),
                                                    "20261011-120000-abcdef", "r1", "run.json")))
        self.assertTrue(os.path.isfile(os.path.join(inbox, "受付済み", self.it._today(), "20261011-120000-abcdef__r1.zip")))
        self.assertEqual(self.it.st["requests"], [])


class TestLiveSettings(unittest.TestCase):
    """ライブ配信の依頼の設定(依頼の JSON の live。src/human/friend/live_requests.py の clean_settings・settings_label)。範囲の外・形の違う値は既定"""

    def test_clean_settings_bounds(self):
        cs, dflt = live_requests.clean_settings, live_requests.SETTINGS_DEFAULT
        for v in (None, "x", [1], 5, {}):
            self.assertEqual(cs(v), dflt, repr(v))
        self.assertIsNot(cs(None), dflt, "既定の写しを返す(書き換えても既定は変わらない)")
        self.assertEqual(cs({"sens": "low", "perHour": 1, "length": 10, "waitMin": 1, "pad": 0, "afterStream": False}),
                         {"sens": "low", "perHour": 1, "length": 10, "waitMin": 1, "pad": 0.0, "afterStream": False})   # 下の端
        self.assertEqual(cs({"sens": "high", "perHour": 30, "length": 180, "waitMin": 60, "pad": 5, "afterStream": True}),
                         {"sens": "high", "perHour": 30, "length": 180, "waitMin": 60, "pad": 5.0, "afterStream": True})   # 上の端(長さは A-5b の仮 180)
        for k, bad in (("perHour", 0), ("perHour", 31), ("length", 9), ("length", 181), ("waitMin", 0), ("waitMin", 61), ("pad", -0.1), ("pad", 5.1),
                       ("perHour", True), ("perHour", "6"), ("perHour", None), ("pad", None), ("pad", "1"), ("pad", float("nan")), ("length", float("inf")),
                       ("sens", "HIGH"), ("sens", None), ("sens", 1), ("afterStream", "false"), ("afterStream", 0), ("afterStream", None)):
            self.assertEqual(cs({k: bad})[k], dflt[k], (k, bad))
        got = cs({"perHour": 6.6, "length": 44.4, "waitMin": 2.6, "pad": 1, "unknown": 1})
        self.assertEqual(got, dict(dflt, perHour=7, length=44, waitMin=3, pad=1.0), "小数は丸める・余白は小数・知らない鍵は捨てる")
        self.assertTrue(isinstance(got["perHour"], int) and isinstance(got["pad"], float))

    def test_length_mode(self):
        auto = live_requests.clean_settings({"lengthMode": "auto"})   # 友人の受信箱のアプリの長さ「自動(場面ごと)」(C-2-11)
        self.assertEqual(auto, dict(live_requests.SETTINGS_DEFAULT, lengthMode="auto"))
        for mode in ("fixed", "AUTO", None, 1):   # auto 以外・無い(前の形の依頼)= 固定の長さ
            self.assertEqual(live_requests.clean_settings({"lengthMode": mode}), live_requests.SETTINGS_DEFAULT, mode)


class TestLiveRequest(Base):
    """ライブ配信の依頼(notes:docs/spec/friend.md の 2-15。kind live): 配信中・配信前なら live_begin(= Live.begin_request)で録画を始めて結びつける。
    終わっていれば kind url の ① 全自動(切り抜く数はホームの既定・1 本ずつ届ける)。終わった直後(post_live)・live_begin が無い・だめなら断る(出力 に .失敗.txt)"""
    VID = "abcdefghijk"
    SPEAKERS = {"count": 1, "names": ["さくらみこ"], "styles": {}}

    def setUp(self):
        super().setUp()
        self.prefs.patch("intake", {"top": 4})   # ホームの既定の切り抜く数(終わった配信の ① 全自動で使う)
        self.begun = []
        self.begin_out = {"recorder": "local", "recording": "20261008-200000-abcdefghijk", "existing": False}
        self.it.live_begin = self.fake_begin
        self.info_calls = []
        info = self.it.info
        self.it.info = lambda vid: (self.info_calls.append(vid), info(vid))[1]

    def fake_begin(self, url, ctx):
        self.begun.append((url, json.loads(json.dumps(ctx))))
        if isinstance(self.begin_out, Exception):
            raise self.begin_out
        return self.begin_out

    def send(self, rid, **extra):
        d = {"v": 1, "kind": "live", "id": rid, "flow": "auto", "url": "https://www.youtube.com/live/abcdefghijk?si=xyz", "streamer": "さくらみこ",
             "speakers": {"count": 1, "names": ["さくらみこ"]}, "videoTracks": 3, "cut": "silence",
             "live": {"sens": "high", "perHour": 12, "length": 60, "waitMin": 3, "pad": 1.5, "afterStream": False}, "sentAt": "2026-10-08T20:00:00+09:00"}
        d.update(extra)
        self.put(rid + ".request.json", json.dumps(d, ensure_ascii=False))
        self.scan2()
        return self.it.snapshot()["requests"][0]

    def out_notes(self, rid):
        """出力\\<依頼 id>__….失敗.txt の (名前の一覧, 中身の一覧)"""
        out = os.path.join(self.folder, intake.OUT_DIR)
        names = sorted(n for n in os.listdir(out) if n.startswith(rid + "__")) if os.path.isdir(out) else []
        texts = []
        for n in names:
            with open(os.path.join(out, n), encoding="utf-8-sig") as f:
                texts.append(f.read())
        return names, texts

    def test_live_request_options_reach_link(self):
        """ライブ配信の依頼の受付の記録の文(1 本ずつ届ける)。友人の受信箱のアプリの長さ「自動(場面ごと)」(live.lengthMode auto。C-2-11)も
        結びつきの settings に残す(検出が場面ごとに切る)"""
        self.infos[self.VID] = {"duration": None, "live": "is_live", "title": "配信中", "channel": "Miko Ch."}
        rec = self.send("20261008-200000-abc302")
        (_url, ctx), = self.begun
        self.assertIn("1 本ずつ届けます", rec["items"][0]["reason"])
        self.begun.clear()
        rec = self.send("20261017-200000-abc303", live={"sens": "high", "perHour": 12, "length": 60, "waitMin": 3, "pad": 1.5, "afterStream": False,
                                                         "lengthMode": "auto"})
        (_url, ctx), = self.begun
        self.assertEqual(ctx["settings"]["lengthMode"], "auto")
        self.assertIn("長さ 自動(場面ごと)", rec["items"][1]["reason"])

    def test_live_now_begins_recording_and_links(self):
        self.infos[self.VID] = {"duration": None, "live": "is_live", "title": "【歌枠】配信中", "channel": "Miko Ch."}
        rid = "20261008-200000-abc301"
        rec = self.send(rid, live={"sens": "high", "perHour": 31, "length": 60, "waitMin": 0, "pad": 1.5, "afterStream": False})
        (url, ctx), = self.begun
        self.assertEqual(url, "https://www.youtube.com/watch?v=abcdefghijk")   # 書き方の違う URL(/live/…?si=)はそろえる
        want = {"sens": "high", "perHour": 6, "length": 60, "waitMin": 5, "pad": 1.5, "afterStream": False}   # 範囲の外(31・0)は既定
        self.assertEqual(ctx, {"rid": rid, "deliverDir": os.path.join(self.folder, intake.OUT_DIR), "url": url, "title": "【歌枠】配信中",
                               "streamer": "さくらみこ", "speakers": self.SPEAKERS, "videoTracks": 3, "cut": "silence", "settings": want})
        self.assertEqual((self.runner.requests, self.runner.files), ([], []), "録画の依頼はまとめて実行へ入れない(切り抜きごとに入口が入れる)")
        self.assertEqual((rec["kind"], rec["state"], rec["source"], rec["title"], rec["flowLabel"], rec["streamer"]),
                         ("live", "accepted", "app", "【歌枠】配信中", "① 全自動", "さくらみこ"))
        self.assertEqual((rec["tracksLabel"], rec["cutLabel"], rec["speakersLabel"]), ("映像トラック: 3本", "カット: 無音で削る", "配信者: 1人(さくらみこ)"))
        self.assertEqual((rec["items"][0]["label"], rec["items"][0]["state"]), ("【歌枠】配信中(ライブ配信)", "accepted"))
        self.assertIn("録画を始めました", rec["items"][0]["reason"])
        self.assertEqual(rec["items"][1], {"label": "ライブ配信", "state": "accepted", "reason": live_requests.settings_label(want)})
        self.assertEqual(len(rec["items"]), 2, "配信者が合えば知らせの行は無い")
        self.assertTrue(os.path.isfile(self.done(rid + ".request.json")), "受付済み へ")
        self.assertFalse(os.path.exists(os.path.join(self.folder, intake.OUT_DIR)), "断った物が無ければ 出力 に何も置かない")
        self.assertIn(self.VID, self.it.st["videos"])
        self.assertEqual(self.it.snapshot()["today"], 1)
        self.assertEqual(self.info_calls, [self.VID])

    def test_upcoming_also_begins_and_flow_is_always_auto(self):
        """配信前(is_upcoming)も録画を始める。flow は auto 固定(ほかの値でも ① = 映像トラック・カットを渡す)。録画中だった(existing)も受け付ける"""
        self.infos[self.VID] = {"duration": None, "live": "is_upcoming", "title": "", "channel": ""}
        self.begin_out = dict(self.begin_out, existing=True)
        rid = "20261008-200000-abc302"
        rec = self.send(rid, flow="manual", streamer="だれでもない人", live="x")
        (url, ctx), = self.begun
        self.assertEqual((ctx["title"], ctx["streamer"], ctx["videoTracks"], ctx["cut"], ctx["settings"]),
                         ("https://www.youtube.com/watch?v=abcdefghijk", "", 3, "silence", live_requests.SETTINGS_DEFAULT))   # 題が無ければ URL・合わない配信者は ""
        self.assertEqual((rec["kind"], rec["state"], rec["flowLabel"], rec["streamer"]), ("live", "accepted", "① 全自動", ""))
        self.assertIn("前から録画中", rec["items"][0]["reason"])
        self.assertTrue(any(i["label"] == "配信者" and i["state"] == "accepted" and "色なし" in i["reason"] for i in rec["items"]))
        self.assertTrue(os.path.isfile(self.done(rid + ".request.json")))

    def test_ended_stream_goes_as_auto_url_request(self):
        """終わった配信(not_live・was_live)は kind url の ① 全自動と同じ: 切り抜く数はホームの既定・知らせの行「ライブ配信」"""
        for i, (live, title) in enumerate((("not_live", "終わった配信"), ("was_live", "アーカイブ"))):
            self.infos[self.VID] = {"duration": 3600.0, "live": live, "title": title, "channel": "ch"}
            rid = "20261008-200000-abc31%d" % i
            rec = self.send(rid)
            self.assertEqual(self.begun, [], "録画は始めない")
            items, got = self.runner.requests[-1]
            self.assertEqual(([(x["id"], x["top"], x["ranges"]) for x in items], got), ([(self.VID, 4, [])], rid))
            self.assertEqual(self.runner.last, {"deliver":os.path.join(self.folder, intake.OUT_DIR), "speakers": self.SPEAKERS, "tracks": 3,
                                                "cut": "silence", "weights": None, "streamer": "さくらみこ"})
            self.assertEqual((rec["kind"], rec["state"], rec["title"], rec["flowLabel"]), ("url", "accepted", title, "① 全自動"))
            note = [x for x in rec["items"] if x["label"] == "ライブ配信"]
            self.assertEqual([(x["state"], "配信は終わっていた" in x["reason"]) for x in note], [("accepted", True)])
            self.assertTrue(os.path.isfile(self.done(rid + ".request.json")))
        self.assertEqual(len(self.runner.requests), 2)
        self.assertFalse(os.path.exists(os.path.join(self.folder, intake.OUT_DIR)))
        # 配信の状態が分からない(yt-dlp が答えない)は、まず録画を試す(① 全自動へ落とすのは録画も始められなかったときだけ = test_unknown_status_*)
        self.it.info = lambda vid: None
        rec = self.send("20261008-200000-abc312")
        self.assertEqual((len(self.runner.requests), rec["kind"], rec["state"], len(self.begun)), (2, "live", "accepted", 1))
        self.assertIn("録画を始めました", rec["items"][0]["reason"])

    def test_post_live_is_rejected_with_reason(self):
        """終わった直後(post_live = YouTube がアーカイブを用意している)は録画もアーカイブの切り抜きもまだできない: 断る(kind url と同じ)。理由はライブ配信の言い方で"""
        self.infos[self.VID] = {"duration": None, "live": "post_live", "title": "終わったばかり", "channel": ""}
        rid = "20261008-200000-abc320"
        rec = self.send(rid)
        self.assertEqual((self.begun, self.runner.requests), ([], []))
        self.assertEqual((rec["kind"], rec["state"], rec["title"]), ("live", "rejected", "終わったばかり"))
        self.assertIn("アーカイブがまだ見られません", rec["reason"])
        self.assertFalse([x for x in rec["items"] if x["state"] == "accepted"], "「切り抜きます」の知らせを出さない")
        self.assertTrue(os.path.isfile(self.failed(rid + ".request.json")))
        names, texts = self.out_notes(rid)
        self.assertEqual(names, [rid + "__終わったばかり.失敗.txt"])
        self.assertIn("アーカイブがまだ見られません", texts[0])

    def test_without_live_begin_is_refused(self):
        """live_begin が無い(この PC でリアルタイム切り抜きが使えない)→ 断る。設定の行(知らせ)は受け付けた数に入れない = 依頼の全部を断った"""
        self.it.live_begin = None
        self.infos[self.VID] = {"duration": None, "live": "is_live", "title": "配信中", "channel": ""}
        rid = "20261008-200000-abc330"
        rec = self.send(rid)
        self.assertEqual((rec["kind"], rec["state"]), ("live", "rejected"))
        self.assertIn("リアルタイム切り抜きが使えません", rec["reason"])
        self.assertTrue(any(x["label"] == "ライブ配信" for x in rec["items"]), "設定の行は一覧に残す")
        self.assertTrue(os.path.isfile(self.failed(rid + ".request.json")))
        names, texts = self.out_notes(rid)
        self.assertEqual(names, [rid + "__配信中.失敗.txt"])
        self.assertTrue(texts[0].startswith("依頼を受け付けられませんでした。"), texts[0])
        self.assertIn("リアルタイム切り抜きが使えません", texts[0])
        self.assertNotIn("ライブの設定", texts[0], "知らせの行は 失敗.txt に書かない")
        self.assertNotIn(self.VID, self.it.st["videos"])
        self.assertEqual(self.it.snapshot()["today"], 0)
        self.assertEqual((self.runner.requests, self.runner.files), ([], []))

    def test_begin_error_is_refused_with_reason(self):
        """live_begin がだめ(オフ・録画元が動いていない・streamlink が無いなど)→ 断って、理由を友人へ。Live.begin の理由の頭「録画を始められませんでした」は二重にしない"""
        self.infos[self.VID] = {"duration": None, "live": "is_live", "title": "配信中", "channel": ""}
        self.begin_out = ValueError("リアルタイム切り抜きがオフです")
        rid = "20261008-200000-abc340"
        rec = self.send(rid)
        self.assertEqual(len(self.begun), 1)
        self.assertEqual((rec["kind"], rec["state"], rec["reason"]), ("live", "rejected", "録画を始められませんでした: リアルタイム切り抜きがオフです"))
        self.assertIn("録画を始められませんでした: リアルタイム切り抜きがオフです", self.out_notes(rid)[1][0])
        self.assertTrue(os.path.isfile(self.failed(rid + ".request.json")))
        self.begin_out = RuntimeError("録画を始められませんでした: streamlink が入っていません")
        rec = self.send("20261008-200000-abc341")
        self.assertEqual(rec["reason"], "録画を始められませんでした: streamlink が入っていません")
        self.assertNotIn(self.VID, self.it.st["videos"])
        self.assertEqual(self.runner.requests, [])

    def test_not_youtube_url_is_refused(self):
        for i, url in enumerate(("https://evil.example/watch?v=abcdefghijk", "https://www.youtube.com/channel/abcdefghijk", "", None, 5)):
            rid = "20261008-200000-abc35%d" % i
            rec = self.send(rid, url=url)
            self.assertEqual((rec["kind"], rec["state"]), ("live", "rejected"), url)
            self.assertIn("YouTube の配信の URL ではありません", rec["reason"])
            self.assertTrue(os.path.isfile(self.failed(rid + ".request.json")), url)
            self.assertEqual(len(self.out_notes(rid)[0]), 1, url)
        self.assertEqual((self.begun, self.info_calls, self.runner.requests), ([], [], []), "yt-dlp も録画元も呼ばない")

    def test_unknown_status_tries_recording_before_archive(self):
        """状態を確かめられなかった(yt-dlp が失敗・無い = info が None)→ 録画を試す(Live.begin が自分でもう一度調べる)。始まれば配信中・配信前と同じ受け付け"""
        self.infos[self.VID] = None
        rid = "20261008-200000-abc360"
        rec = self.send(rid)
        (url, ctx), = self.begun
        self.assertEqual((url, ctx["rid"], ctx["title"]), ("https://www.youtube.com/watch?v=abcdefghijk", rid, url), "題が分からなければ URL")
        self.assertEqual((rec["kind"], rec["state"]), ("live", "accepted"))
        self.assertIn("録画を始めました", rec["items"][0]["reason"])
        self.assertEqual(self.runner.requests, [], "アーカイブの ① には流さない")
        self.assertIn(self.VID, self.it.st["videos"])

    def test_unknown_status_falls_back_to_archive_when_recording_fails(self):
        """状態を確かめられず、録画も始められない(終わっていた・録画元が動いていないなど)→ 今までどおりアーカイブから ① 全自動(理由を知らせの行に)。
        live_begin が無い PC も同じ(録画は試さない)"""
        self.infos[self.VID] = None
        self.begin_out = ValueError("配信中・配信前の配信ではありません(unknown)")
        rid = "20261008-200000-abc361"
        rec = self.send(rid)
        self.assertEqual(len(self.begun), 1, "先に録画を試す")
        items, got = self.runner.requests[-1]
        self.assertEqual(([(x["id"], x["top"]) for x in items], got), ([(self.VID, 4)], rid))
        self.assertEqual((rec["kind"], rec["state"], rec["flowLabel"]), ("url", "accepted", "① 全自動"))
        note = next(i for i in rec["items"] if i["label"] == "ライブ配信")
        self.assertIn("録画も始められなかったので(配信中・配信前の配信ではありません(unknown))、アーカイブから ① 全自動", note["reason"])
        self.assertEqual(len(self.out_notes(rid)[0]), 0, "断っていない = .失敗.txt は置かない")
        self.it.live_begin = None
        rec = self.send("20261008-200000-abc362")
        self.assertEqual(len(self.begun), 1, "live_begin が無ければ試さない")
        self.assertEqual((rec["kind"], rec["state"]), ("url", "accepted"))
        self.assertIn("配信の状態を確かめられなかったので、アーカイブから ① 全自動", next(i for i in rec["items"] if i["label"] == "ライブ配信")["reason"])


class TestYoutubeInfo(unittest.TestCase):
    """youtube_info(yt-dlp の問い合わせ): 配信の前は --ignore-no-formats-error で is_upcoming を出させる。古い yt-dlp のエラー文(will begin)も is_upcoming。
    ほかの失敗は None"""

    def run_info(self, returncode, stdout, stderr=""):
        from unittest import mock
        calls = []

        def fake_run(args, **kw):
            calls.append(list(args))
            return intake.tools.RunResult(returncode, stdout.encode("utf-8"), stderr.encode("utf-8"), None)

        with mock.patch.dict(os.environ, {"STUDIO_FAKE": "0"}), mock.patch.object(intake.tools, "find_tool", lambda name: "C:/x/yt-dlp.exe"), \
                mock.patch.object(intake.tools, "run", fake_run):
            out = intake.youtube_info("abcdefghijk")
        return out, calls

    def test_upcoming_is_reported_not_none(self):
        out, calls = self.run_info(0, "NA\tis_upcoming\tMiko Ch.\t🌸FreeChat\n")
        self.assertEqual(out, {"duration": None, "live": "is_upcoming", "channel": "Miko Ch.", "title": "🌸FreeChat"})
        self.assertEqual(len(calls), 1)
        self.assertIn("--ignore-no-formats-error", calls[0])
        self.assertEqual(calls[0][-1], "https://www.youtube.com/watch?v=abcdefghijk")

    def test_error_text_and_failures(self):
        """古い yt-dlp のエラー文(will begin・Premieres)は is_upcoming・ほかの失敗は None・正常な出力は読む"""
        upcoming = {"duration": None, "live": "is_upcoming", "channel": "", "title": ""}
        for rc, stdout, stderr, want in (
                (1, "", "ERROR: [youtube] abcdefghijk: This live event will begin in 3 minutes.\n", upcoming),
                (1, "", "ERROR: [youtube] abcdefghijk: Premieres in 2 hours\n", upcoming),
                (1, "", "ERROR: [youtube] abcdefghijk: Video unavailable\n", None),
                (0, "garbage\n", "", None),
                (0, "3600\twas_live\tch\t題\n", "", {"duration": 3600.0, "live": "was_live", "channel": "ch", "title": "題"})):
            with self.subTest(rc=rc, stdout=stdout, stderr=stderr):
                self.assertEqual(self.run_info(rc, stdout, stderr)[0], want)

    def test_uses_shared_ytdlp_command(self):
        """呼び方は ytt/tools.ytdlp_print_cmd(flow/livesession.probe_live と同じ)・時間切れは None"""
        from unittest import mock
        _out, calls = self.run_info(0, "NA\tis_live\tc\tt\n")
        self.assertEqual(calls[0], intake.tools.ytdlp_print_cmd("C:/x/yt-dlp.exe", "https://www.youtube.com/watch?v=abcdefghijk",
                                                                "%(duration)s\t%(live_status)s\t%(channel)s\t%(title)s"))
        with mock.patch.dict(os.environ, {"STUDIO_FAKE": "0"}), mock.patch.object(intake.tools, "find_tool", lambda name: "C:/x/yt-dlp.exe"), \
                mock.patch.object(intake.tools, "run", lambda args, **kw: intake.tools.RunResult(None, b"", b"", "timeout")):
            self.assertIsNone(intake.youtube_info("abcdefghijk"))


if __name__ == "__main__":
    unittest.main()
