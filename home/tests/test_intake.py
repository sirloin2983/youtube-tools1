"""友人からの依頼の受付(home/intake.py)の単体テスト。まとめて実行・ffprobe・yt-dlp は偽物。

実行(リポジトリ直下から): python -m unittest home/tests/test_intake.py -v
"""
import json
import os
import shutil
import sys
import tempfile
import time
import unittest

os.environ.setdefault("YTT_DATA_DIR", "inplace")
HOME = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
ROOT = os.path.dirname(HOME)
for p in (HOME, ROOT):
    if p not in sys.path:
        sys.path.insert(0, p)

import intake  # noqa: E402
import prefs as prefs_mod  # noqa: E402
from ytt_core import fsio  # noqa: E402


class FakeRunner:
    def __init__(self):
        self.requests, self.files = [], []
        self.fail = None

    def start_request(self, items, request_id=None, flow="check", deliver_dir=None, speakers=None, video_tracks=None):
        if self.fail:
            raise ValueError(self.fail)
        self.requests.append((items, request_id))
        self.last = {"flow": flow, "deliver": deliver_dir, "speakers": speakers, "tracks": video_tracks}
        return {"runs": [{"id": "r%d" % len(self.requests) + it["id"][:3], "videoId": it["id"]} for it in items], "skipped": []}

    def start_file(self, path, title="", streamer=None, request_id=None, flow="check", deliver_dir=None, speakers=None, video_tracks=None):
        if self.fail:
            raise ValueError(self.fail)
        self.files.append({"path": path, "title": title, "streamer": streamer, "rid": request_id, "flow": flow, "deliver": deliver_dir, "speakers": speakers,
                           "tracks": video_tracks})
        return {"id": "f%d" % len(self.files)}


class Base(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.mkdtemp(prefix="intake-")
        self.folder = os.path.join(self.tmp, "Dropbox", "切り抜き依頼")
        self.data = os.path.join(self.tmp, "app")
        os.makedirs(self.folder)
        self.prefs = prefs_mod.Prefs(os.path.join(self.data, "prefs.json"), fsio.atomic_write)
        self.prefs.patch("intake", {"enabled": True, "folder": self.folder})
        self.runner = FakeRunner()
        self.now = time.time() + 1000   # ファイルの更新時刻より十分あと(落ち着いた扱い)
        self.infos = {}
        self.probes = {}
        self.it = intake.Intake(self.prefs, lambda: self.runner, self.data, clock=lambda: self.now,
                                probe=lambda p: self.probes.get(os.path.basename(p), {"ok": True, "duration": 60.0, "reason": ""}),
                                info=lambda vid: self.infos.get(vid, {"duration": 3600.0, "live": "not_live", "title": "題名 " + vid, "channel": "ch"}))

    def tearDown(self):
        shutil.rmtree(self.tmp, ignore_errors=True)

    def put(self, name, data):
        p = os.path.join(self.folder, name)
        with open(p, "wb") as f:
            f.write(data if isinstance(data, bytes) else data.encode("utf-8"))
        return p

    def scan2(self):
        """1回目で大きさを覚え、SETTLE 秒あとの2回目で処理する"""
        self.it.scan()
        self.now += intake.SETTLE + 1
        self.it.scan()

    def done(self, *parts):
        return os.path.join(self.folder, intake.DONE_DIR, self.it._today(), *parts)

    def failed(self, *parts):
        return os.path.join(self.folder, intake.FAIL_DIR, *parts)


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
                  "https://www.youtube.com/watch?vv=abcdefghijk"):
            self.assertIsNone(intake.youtube_id(u), u)

    def test_parse_lines(self):
        ok, bad = intake.parse_lines("# メモ\n\nhttps://youtu.be/abcdefghijk 5\nhttps://youtu.be/bbbbbbbbbbb\nhttps://x.example/ 3\n"
                                     "https://youtu.be/ccccccccccc 11\nhttps://youtu.be/ddddddddddd 2 # ここがほしい\nhttps://youtu.be/eeeeeeeeeee よろしく\n", 3)
        self.assertEqual([(o["id"], o["top"]) for o in ok], [("abcdefghijk", 5), ("bbbbbbbbbbb", 3), ("ddddddddddd", 2)])
        self.assertEqual(len(bad), 3)

    def test_decode_and_url_file(self):
        self.assertEqual(intake.decode_text("あ".encode("cp932")), "あ")
        self.assertEqual(intake.decode_text("\ufeffあ".encode("utf-8")), "あ")
        self.assertEqual(intake.parse_url_file("[InternetShortcut]\r\nURL=https://youtu.be/abcdefghijk\r\n"), "https://youtu.be/abcdefghijk")


class TestPrefs(unittest.TestCase):
    def test_intake_prefs(self):
        tmp = tempfile.mkdtemp()
        try:
            p = prefs_mod.Prefs(os.path.join(tmp, "prefs.json"), fsio.atomic_write)
            self.assertEqual(p.get(["intake"])["intake"], prefs_mod.DEFAULTS["intake"])
            v = p.patch("intake", {"enabled": True, "top": 5, "maxHours": 2.5})
            self.assertEqual((v["enabled"], v["top"], v["maxHours"], v["dailyMax"], v["interval"]), (True, 5, 2.5, 5, 30))
            self.assertEqual(p.patch("intake", {"interval": 120})["interval"], 120)   # 見る間隔(段9 9-4)
            for bad in ({"top": 11}, {"top": 2.5}, {"dailyMax": 0}, {"maxGB": True}, {"folder": 3}, {"folder": "\\\\server\\share"},
                        {"interval": 5}, {"interval": 601}, {"interval": 30.5},
                        {"folder": "//server/share"}, {"folder": "relative\\dir"}):
                with self.assertRaises(prefs_mod.PrefsError, msg=str(bad)):
                    p.patch("intake", bad)
            if os.name == "nt":
                self.assertEqual(p.patch("intake", {"folder": ' "C:\\Users\\x\\Dropbox" '})["folder"], "C:\\Users\\x\\Dropbox")
        finally:
            shutil.rmtree(tmp, ignore_errors=True)


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


class TestText(Base):
    def test_txt_urls(self):
        self.put("依頼.txt", "https://youtu.be/abcdefghijk 5\nhttps://example.com/x\n")
        self.it.scan()
        self.assertEqual(self.runner.requests, [], "落ち着く前は処理しない")
        self.now += intake.SETTLE + 1
        self.it.scan()
        (items, rid), = self.runner.requests
        self.assertEqual([(i["id"], i["top"], i["title"]) for i in items], [("abcdefghijk", 5, "題名 abcdefghijk")])
        self.assertIsNone(rid)
        self.assertTrue(os.path.isfile(self.done("依頼.txt")))
        self.assertTrue(os.path.isfile(self.done("依頼.理由.txt")))   # 飛ばした行の理由
        snap = self.it.snapshot()
        self.assertEqual((snap["today"], snap["requests"][0]["state"], snap["requests"][0]["kind"]), (1, "accepted", "url"))
        # 同じ配信をもう一度: 断る
        self.put("again.url", "[InternetShortcut]\nURL=https://www.youtube.com/watch?v=abcdefghijk\n")
        self.scan2()
        self.assertEqual(len(self.runner.requests), 1)
        self.assertTrue(os.path.isfile(self.failed("again.url")))
        with open(self.failed("again.理由.txt"), encoding="utf-8-sig") as f:
            self.assertIn("前に受け付けた配信", f.read())

    def test_long_and_live(self):
        self.infos = {"aaaaaaaaaaa": {"duration": 9 * 3600.0, "live": "was_live", "title": "", "channel": ""},
                      "bbbbbbbbbbb": {"duration": None, "live": "is_live", "title": "", "channel": ""}}
        self.put("x.txt", "https://youtu.be/aaaaaaaaaaa\nhttps://youtu.be/bbbbbbbbbbb\n")
        self.scan2()
        self.assertEqual(self.runner.requests, [])
        r = self.it.snapshot()["requests"][0]
        self.assertEqual(r["state"], "rejected")
        self.assertIn("長すぎます", r["items"][0]["reason"])
        self.assertIn("配信中", r["items"][1]["reason"])

    def test_daily_limit_holds(self):
        self.prefs.patch("intake", {"dailyMax": 1})
        self.put("a.txt", "https://youtu.be/aaaaaaaaaaa\n")
        self.scan2()
        self.put("b.txt", "https://youtu.be/bbbbbbbbbbb\n")
        self.scan2()
        self.assertEqual(len(self.runner.requests), 1)
        self.assertTrue(os.path.isfile(os.path.join(self.folder, "b.txt")), "上限を超えた分はフォルダに残す")
        self.assertIn("明日に回します", self.it.snapshot()["message"])
        self.now += 86400   # 次の日
        self.it.scan()
        self.assertEqual(len(self.runner.requests), 2)

    def test_unknown_type(self):
        self.put("写真.png", b"x")
        self.scan2()
        self.assertTrue(os.path.isfile(self.failed("写真.png")))
        self.assertEqual(self.runner.requests + self.runner.files, [])

    def test_os_files_are_ignored(self):
        """desktop.ini・Thumbs.db・隠しファイルは依頼ではない(断って移すと、また作られて「断った」が毎回増えた。0.15.1)"""
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
        self.put("a.txt", "https://youtu.be/aaaaaaaaaaa\n")
        self.scan2()
        r = self.it.snapshot()["requests"][0]
        self.assertEqual(r["state"], "rejected")
        self.assertIn("順番待ち", r["reason"])


class TestVideo(Base):
    def test_manual_video_with_name(self):
        self.put("【さくらみこ】にぇ.mp4", b"video-bytes-1")
        self.scan2()
        f, = self.runner.files
        self.assertTrue(f["path"].startswith(os.path.join(self.data, "intake")))
        self.assertTrue(os.path.isfile(f["path"]))
        self.assertEqual(f["streamer"], "さくらみこ")
        self.assertTrue(os.path.isfile(self.done("【さくらみこ】にぇ.mp4")))
        # 同じ中身をもう一度: 断らない(送り直し。2026-10-02 ユーザー)
        self.put("copy.mp4", b"video-bytes-1")
        self.scan2()
        self.assertEqual(len(self.runner.files), 2)
        self.assertEqual(self.it.snapshot()["requests"][0]["state"], "accepted")

    def test_unknown_streamer_goes_without_color(self):
        self.put("【だれでもない人】x.mp4", b"v2")
        self.scan2()
        self.assertIsNone(self.runner.files[0]["streamer"])
        self.assertTrue(any("色なし" in i["reason"] for i in self.it.snapshot()["requests"][0]["items"]))

    def test_probe_rejects(self):
        self.probes["bad.mp4"] = {"ok": False, "duration": None, "reason": "音声のある動画として読めませんでした"}
        self.probes["long.mp4"] = {"ok": True, "duration": 10 * 3600.0, "reason": ""}
        self.put("bad.mp4", b"a")
        self.put("long.mp4", b"b")
        self.scan2()
        self.assertEqual(self.runner.files, [])
        self.assertTrue(os.path.isfile(self.failed("bad.mp4")) and os.path.isfile(self.failed("long.mp4")))

    def test_app_request_video(self):
        rid = "20261001-120000-abc123"
        self.put(rid + "__にぇの叫び.mp4", b"clip")
        self.it.scan()
        self.now += intake.SETTLE + 1
        self.it.scan()
        self.assertEqual(self.runner.files, [], "JSON が届くまで待つ")
        self.put(rid + ".request.json", json.dumps({"v": 1, "kind": "video", "id": rid, "files": [rid + "__にぇの叫び.mp4"],
                                                     "streamer": "さくらみこ", "memo": "最後のところ", "sentAt": ""}, ensure_ascii=False))
        self.scan2()
        f, = self.runner.files
        self.assertEqual((f["title"], f["streamer"], f["rid"], f["flow"]), ("にぇの叫び", "さくらみこ", rid, "check"))   # flow の無い 1.0.0 のアプリ = ②
        r = self.it.snapshot()["requests"][0]
        self.assertEqual((r["source"], r["memo"], r["state"]), ("app", "最後のところ", "accepted"))
        self.assertTrue(os.path.isfile(self.done(rid + ".request.json")))
        self.assertTrue(os.path.isfile(self.done(rid + "__にぇの叫び.mp4")))

    def test_same_video_is_accepted_again(self):
        """前に受け付けた動画と同じ中身でも断らない(送り直し。2026-10-02 ユーザー)"""
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
        """友人が選んだ形(① auto / ② check / ③ manual)と、① のパックの届け先(見張るフォルダの 出力\\)をまとめて実行へ渡す(2026-10-01)"""
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
        self.assertEqual((f["flow"], f["deliver"]), ("auto", os.path.join(self.folder, intake.OUT_DIR)))
        self.assertEqual(len(self.runner.requests), 2)
        labels = {r["title"]: r["flowLabel"] for r in self.it.snapshot()["requests"]}
        self.assertEqual(labels["clip.mp4"], "① 全自動")
        self.assertEqual(sorted(labels.values()), ["① 全自動", "② 軽く確認", "③ 全部人が行う"])   # 知らない形は ②

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
                         {"count": 2, "names": ["兎田ぺこら", "宝鐘マリン"]})
        for bad in (None, {"count": 0}, {"count": 11}, {"count": "2"}, {"count": True}):
            self.assertIsNone(intake.parse_speakers(bad))
        rid = "20261001-120000-abc130"
        self.put(rid + ".request.json", json.dumps({"v": 1, "kind": "url", "id": rid, "speakers": {"count": 1, "names": ["さくらみこ"]},
                                                     "items": [{"url": "https://youtu.be/abcdefghijk", "top": 2}]}, ensure_ascii=False))
        self.scan2()
        self.assertEqual(self.runner.last["speakers"], {"count": 1, "names": ["さくらみこ"]})
        self.assertEqual(self.it.snapshot()["requests"][0]["speakersLabel"], "話す人: 1人(さくらみこ)")

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
        rid = "20261001-120000-abc132"
        self.put(rid + ".request.json", json.dumps({"v": 1, "kind": "url", "id": rid, "flow": "check", "videoTracks": 3,
                                                     "items": [{"url": "https://youtu.be/bbbbbbbbbbb", "top": 2}]}))
        self.scan2()
        self.assertIsNone(self.runner.last["tracks"])
        self.assertEqual(self.it.snapshot()["requests"][0]["tracksLabel"], "")
        rid = "20261001-120000-abc133"                                   # ① で指定が無い(1.3.0 までのアプリ)= 1
        self.put(rid + ".request.json", json.dumps({"v": 1, "kind": "url", "id": rid, "flow": "auto",
                                                     "items": [{"url": "https://youtu.be/ccccccccccc", "top": 2}]}))
        self.scan2()
        self.assertEqual(self.runner.last["tracks"], 1)
        self.assertEqual(self.it.snapshot()["requests"][0]["tracksLabel"], "映像トラック: 1本")

    def test_state_persists(self):
        self.put("a.txt", "https://youtu.be/aaaaaaaaaaa\n")
        self.scan2()
        again = intake.Intake(self.prefs, lambda: self.runner, self.data, clock=lambda: self.now, info=lambda v: None)
        self.assertEqual(again.snapshot()["today"], 1)
        self.assertIn("aaaaaaaaaaa", again.st["videos"])


if __name__ == "__main__":
    unittest.main()
