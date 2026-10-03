"""友人からの依頼の受付(home/intake.py)の単体テスト。まとめて実行・ffprobe・yt-dlp は偽物。

実行(リポジトリ直下から): python -m unittest home/tests/test_intake.py -v
"""
import json
import os
import shutil
import subprocess
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
from ytt_core import fsio, normalize, tools  # noqa: E402

OK_30FPS = {"has_video": True, "has_audio": True, "vcodec": "h264", "bit_depth": 8, "pix_fmt": "yuv420p", "r_frame_rate": "30/1",
            "avg_fps": 30.0, "acodec": "aac"}   # normalize.probe の結果の形(作り直しが要らない動画)


class FakeRunner:
    def __init__(self):
        self.requests, self.files = [], []
        self.fail = None

    def start_request(self, items, request_id=None, flow="check", deliver_dir=None, speakers=None, video_tracks=None, cut=None, weights=None):
        if self.fail:
            raise ValueError(self.fail)
        self.requests.append((items, request_id))
        self.last = {"flow": flow, "deliver": deliver_dir, "speakers": speakers, "tracks": video_tracks, "cut": cut, "weights": weights}
        return {"runs": [{"id": "r%d" % len(self.requests) + it["id"][:3], "videoId": it["id"]} for it in items], "skipped": []}

    def start_file(self, path, title="", streamer=None, request_id=None, flow="check", deliver_dir=None, speakers=None, video_tracks=None, cut=None):
        if self.fail:
            raise ValueError(self.fail)
        self.files.append({"path": path, "title": title, "streamer": streamer, "rid": request_id, "flow": flow, "deliver": deliver_dir, "speakers": speakers,
                           "tracks": video_tracks, "cut": cut})
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
                                info=lambda vid: self.infos.get(vid, {"duration": 3600.0, "live": "not_live", "title": "題名 " + vid, "channel": "ch"}),
                                norm_probe=lambda p: dict(OK_30FPS), norm_run=self.norm_run)   # 既定は 30fps 済み(作り直さない)。作り直しのテストは TestNormalize
        self.norm_calls = []

    def tearDown(self):
        shutil.rmtree(self.tmp, ignore_errors=True)

    def norm_run(self, src, dst, **kw):
        self.norm_calls.append((src, dst))
        raise AssertionError("30fps 済みの動画を作り直そうとした")

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
        # 同じ配信をもう一度: 断らない(2026-10-02 ユーザー。解析・切り抜き・文字起こしは、まとめて実行が使い回す)
        self.put("again.url", "[InternetShortcut]\nURL=https://www.youtube.com/watch?v=abcdefghijk\n")
        self.scan2()
        self.assertEqual(len(self.runner.requests), 2)
        self.assertTrue(os.path.isfile(self.done("again.url")))
        # 1つの依頼の中で同じ配信を2回書いたら、1回だけ
        self.put("twice.txt", "https://youtu.be/ccccccccccc\nhttps://www.youtube.com/watch?v=ccccccccccc 2\n")
        self.scan2()
        self.assertEqual([i["id"] for i in self.runner.requests[2][0]], ["ccccccccccc"])

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
        self.assertEqual(r["title"], "x.txt", "題名が分からなければファイル名")

    def test_rejected_shows_stream_title(self):
        """断った配信も、題名が分かれば URL ではなく題名で出す(2026-10-04。一覧で読めるように)"""
        self.infos = {"bbbbbbbbbbb": {"duration": None, "live": "is_live", "title": "【雑談】配信中の題名", "channel": ""}}
        self.put("y.txt", "https://youtu.be/bbbbbbbbbbb 2\n")
        self.scan2()
        r = self.it.snapshot()["requests"][0]
        self.assertEqual(r["title"], "【雑談】配信中の題名")
        self.assertEqual(r["items"][0]["label"], "【雑談】配信中の題名(2 個)")

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

    def test_ranges_cut_weights_from_app(self):
        """2.0.0 のアプリ: 時刻で指定した区間(配信ごと)・カット(① だけ)・解析の重みを、形を確かめてまとめて実行へ"""
        self.assertEqual(intake.parse_ranges(None), ([], []))
        ok, bad = intake.parse_ranges([{"start": 10, "end": 20}, {"start": 5, "end": 5}, {"start": 0, "end": 3601}, {"start": "1", "end": 2}, "x",
                                       {"start": True, "end": 2}, {"start": 10, "end": 20}])
        self.assertEqual((ok, len(bad)), ([(10, 20)], 5))
        self.assertEqual(len(intake.parse_ranges([{"start": i * 10, "end": i * 10 + 5} for i in range(12)])[0]), 10)
        self.assertEqual([intake.parse_cut(x) for x in ("none", "silence", "rows", None, 1)], ["none", "silence", None, None, None])
        self.assertEqual(intake.parse_weights({"audio": 1.5, "chat": 0, "comments": 3}), {"wAudio": 1.5, "wChat": 0.0, "wComments": 3.0})
        for badw in (None, {}, {"audio": 1, "chat": 1}, {"audio": 4, "chat": 1, "comments": 1}, {"audio": "1", "chat": 1, "comments": 1}, {"audio": True, "chat": 1, "comments": 1}):
            self.assertIsNone(intake.parse_weights(badw), badw)

        self.prefs.patch("intake", {"dailyMax": 50})
        self.infos["abcdefghijk"] = {"duration": 7200.0, "live": "not_live", "title": "長い配信", "channel": "ch"}
        self.infos["bbbbbbbbbbb"] = {"duration": 600.0, "live": "not_live", "title": "短い配信", "channel": "ch"}
        rid = "20261002-120000-abc201"
        self.put(rid + ".request.json", json.dumps({"v": 1, "kind": "url", "id": rid, "flow": "auto", "videoTracks": 2, "cut": "silence",
                                                     "weights": {"audio": 1.5, "chat": 1.0, "comments": 0.7}, "memo": "",
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
                         ("区間: 1:23:45〜1:25:10・0:01:00〜0:01:30・0:09:50〜0:10:00", "カット: 無音を削る", "重み: 音声 1.5・チャット 1.0・コメント 0.7"))
        reasons = [i["reason"] for i in rec["items"] if i["state"] == "rejected"]
        self.assertEqual(len(reasons), 2, reasons)
        self.assertTrue(any("より後です" in r for r in reasons) and any("終了が開始より前" in r for r in reasons), reasons)
        # 断った区間は、友人のアプリの「受け取る」に理由が届く(ほかは進める)
        note = [n for n in os.listdir(os.path.join(self.folder, "出力")) if n.startswith(rid)]
        self.assertEqual(len(note), 1)

        # ②: 区間は渡す・カットは渡さない / ③: 区間も渡さない / 動画の ①: カットを渡す
        rid = "20261002-120000-abc202"
        self.put(rid + ".request.json", json.dumps({"v": 1, "kind": "url", "id": rid, "flow": "check", "cut": "silence",
                                                     "items": [{"url": "https://youtu.be/ddddddddddd", "top": 3, "ranges": [{"start": 1, "end": 9}]}]}))
        self.scan2()
        self.assertEqual((self.runner.requests[-1][0][0]["ranges"], self.runner.last["cut"], self.runner.last["weights"]), ([(1, 9)], None, None))
        self.assertEqual(self.it.snapshot()["requests"][0]["cutLabel"], "")
        rid = "20261002-120000-abc203"
        self.put(rid + ".request.json", json.dumps({"v": 1, "kind": "url", "id": rid, "flow": "manual",
                                                     "items": [{"url": "https://youtu.be/eeeeeeeeeee", "top": 3, "ranges": [{"start": 1, "end": 9}]}]}))
        self.scan2()
        self.assertEqual((self.runner.requests[-1][0][0]["ranges"], self.runner.requests[-1][0][0]["top"]), ([], 3))
        rid = "20261002-120000-abc204"
        self.put(rid + "__a.mp4", b"v")
        self.put(rid + ".request.json", json.dumps({"v": 1, "kind": "video", "id": rid, "flow": "auto", "files": [rid + "__a.mp4"], "cut": "silence"}))
        self.scan2()
        self.assertEqual(self.runner.files[-1]["cut"], "silence")
        self.assertEqual(self.it.snapshot()["requests"][0]["cutLabel"], "カット: 無音を削る")

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
        self.put("a.txt", "https://youtu.be/aaaaaaaaaaa\n")
        self.scan2()
        again = intake.Intake(self.prefs, lambda: self.runner, self.data, clock=lambda: self.now, info=lambda v: None)
        self.assertEqual(again.snapshot()["today"], 1)
        self.assertIn("aaaaaaaaaaa", again.st["videos"])


@unittest.skipUnless(tools.find_tool("ffmpeg") and tools.find_tool("ffprobe"), "ffmpeg / ffprobe が無い")
class TestNormalize(Base):
    """友人の動画を 30fps にそろえる(Q1。2026-10-04)。本物の ffmpeg で、lavfi の短い動画を「届いた動画」にする"""

    def setUp(self):
        super().setUp()
        self.logs = []
        self.it = intake.Intake(self.prefs, lambda: self.runner, self.data, clock=lambda: self.now, log=self.logs.append,
                                probe=lambda p: {"ok": True, "duration": 2.0, "reason": ""}, info=lambda v: None)   # norm_probe・norm_run は本物

    def make(self, name, fps, ext=".mp4", vcodec="libx264"):
        path = os.path.join(self.folder, name + ext)
        subprocess.run([tools.find_tool("ffmpeg"), "-v", "error", "-y", "-f", "lavfi", "-i", "testsrc=size=160x120:rate=%s:duration=2" % fps,
                        "-f", "lavfi", "-i", "sine=frequency=440:duration=2", "-c:v", vcodec, "-pix_fmt", "yuv420p", "-c:a", "aac", "-shortest", path],
                       check=True, stdin=subprocess.DEVNULL, creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0))
        return path

    def copied(self):
        f, = self.runner.files
        return f["path"]

    def test_60fps_copy_is_replaced_with_30fps(self):
        src = self.make("【さくらみこ】にぇ", 60)
        before = os.path.getsize(src)
        self.scan2()
        p = self.copied()
        info = normalize.probe(p)
        self.assertEqual(info["r_frame_rate"], "30/1")
        self.assertEqual((info["vcodec"], info["acodec"]), ("h264", "aac"))
        self.assertTrue(p.startswith(os.path.join(self.data, "intake")))
        self.assertEqual([n for n in os.listdir(os.path.dirname(p)) if normalize.PART in n or n.endswith(".copying")], [], "途中のファイルは残さない")
        # 友人の元のファイルは受付済みへ移るだけで、作り直さない(60fps のまま)
        moved = self.done("【さくらみこ】にぇ.mp4")
        self.assertEqual(os.path.getsize(moved), before)
        self.assertEqual(normalize.probe(moved)["r_frame_rate"], "60/1")
        self.assertEqual(self.it.snapshot()["requests"][0]["state"], "accepted")
        self.assertEqual(self.it.message, "")

    def test_30fps_h264_aac_is_not_reencoded(self):
        src = self.make("そのまま", 30)
        with open(src, "rb") as f:
            original = f.read()
        self.scan2()
        with open(self.copied(), "rb") as f:
            self.assertEqual(f.read(), original, "30fps の H.264 + AAC はコピーのまま")

    def test_mov_becomes_mp4_and_old_copy_removed(self):
        self.make("めっきー", 60, ".mov")
        self.scan2()
        p = self.copied()
        self.assertTrue(p.endswith(".mp4"))
        self.assertEqual(normalize.probe(p)["r_frame_rate"], "30/1")
        self.assertEqual([n for n in os.listdir(os.path.dirname(p)) if n.endswith(".mov")], [])

    def test_failure_does_not_stop_request(self):
        def boom(src, dst, **kw):
            raise normalize.NormalizeError("作り直しに失敗しました: テスト")
        self.it.norm_run = boom
        src = self.make("失敗", 60)
        with open(src, "rb") as f:
            original = f.read()
        self.scan2()
        with open(self.copied(), "rb") as f:
            self.assertEqual(f.read(), original, "写しのまま続ける")
        r = self.it.snapshot()["requests"][0]
        self.assertEqual(r["state"], "accepted")
        self.assertIn("30fps にそろえられませんでした", r["items"][0]["reason"])
        self.assertTrue(any("30fps にできませんでした" in m for m in self.logs))
        with open(self.done("失敗.理由.txt"), encoding="utf-8-sig") as f:
            self.assertIn("30fps にそろえられませんでした", f.read())   # 友人の Dropbox の受付済みにも理由が残る

    def test_unexpected_error_also_continues(self):
        def boom(src, dst, **kw):
            raise RuntimeError("想定外")
        self.it.norm_run = boom
        self.make("想定外", 60)
        self.scan2()
        self.assertEqual(len(self.runner.files), 1)
        self.assertEqual(self.it.snapshot()["requests"][0]["state"], "accepted")


if __name__ == "__main__":
    unittest.main()
