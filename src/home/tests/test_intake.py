"""友人からの依頼の受付(src/human/friend/intake.py)の単体テスト。まとめて実行・ffprobe・yt-dlp は偽物。

実行(リポジトリ直下から): python -m unittest src/home/tests/test_intake.py -v
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

from human.friend import intake  # noqa: E402
from human.friend import live_requests  # noqa: E402
import prefs as prefs_mod  # noqa: E402
from ytt_core import fsio, normalize, tools  # noqa: E402

OK_30FPS = {"has_video": True, "has_audio": True, "vcodec": "h264", "bit_depth": 8, "pix_fmt": "yuv420p", "r_frame_rate": "30/1",
            "avg_fps": 30.0, "acodec": "aac"}   # normalize.probe の結果の形(作り直しが要らない動画)


class FakeRunner:
    def __init__(self):
        self.requests, self.files = [], []
        self.fail = None

    def start_request(self, items, request_id=None, flow="check", deliver_dir=None, speakers=None, video_tracks=None, cut=None, weights=None, streamer=None,
                      deliver_batch=None):
        if self.fail:
            raise ValueError(self.fail)
        self.requests.append((items, request_id))
        self.last = {"flow": flow, "deliver": deliver_dir, "speakers": speakers, "tracks": video_tracks, "cut": cut, "weights": weights, "streamer": streamer,
                     "batch": deliver_batch}
        return {"runs": [{"id": "r%d" % len(self.requests) + it["id"][:3], "videoId": it["id"]} for it in items], "skipped": []}

    def start_file(self, path, title="", streamer=None, request_id=None, flow="check", deliver_dir=None, speakers=None, video_tracks=None, cut=None,
                   deliver_batch=None):
        if self.fail:
            raise ValueError(self.fail)
        self.files.append({"path": path, "title": title, "streamer": streamer, "rid": request_id, "flow": flow, "deliver": deliver_dir, "speakers": speakers,
                           "tracks": video_tracks, "cut": cut, "batch": deliver_batch})
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
    def test_cfg_falls_back_to_given_defaults(self):
        """設定が読めないときの既定は入口が渡す(intake は prefs を読み込まない。RS3-0B)"""
        class Broken:
            def get(self, sections):
                raise OSError("読めない")
        tmp = tempfile.mkdtemp(prefix="intake-")
        self.addCleanup(shutil.rmtree, tmp, True)
        d = prefs_mod.DEFAULTS["intake"]
        it = intake.Intake(Broken(), lambda: None, tmp, defaults=d)
        self.assertEqual(it._cfg(), d)
        self.assertIsNot(it._cfg(), d)    # 呼ぶ側が書き換えても既定は変わらない
        self.assertEqual(intake.Intake(Broken(), lambda: None, tmp)._cfg(), {})   # 渡さなければ空 = オフ扱い

    def test_intake_prefs(self):
        tmp = tempfile.mkdtemp()
        try:
            p = prefs_mod.Prefs(os.path.join(tmp, "prefs.json"), fsio.atomic_write)
            self.assertEqual(p.get(["intake"])["intake"], prefs_mod.DEFAULTS["intake"])
            v = p.patch("intake", {"enabled": True, "top": 5, "maxHours": 2.5})
            self.assertEqual((v["enabled"], v["top"], v["maxHours"], v["interval"]), (True, 5, 2.5, 30))
            self.assertNotIn("dailyMax", v)   # 1 日の上限は無い。古いアプリ・古い prefs.json の dailyMax は読み飛ばす
            self.assertNotIn("dailyMax", p.patch("intake", {"dailyMax": 3}))
            self.assertEqual(p.patch("intake", {"interval": 120})["interval"], 120)   # 見る間隔(段9 9-4)
            for bad in ({"top": 11}, {"top": 2.5}, {"maxGB": True}, {"folder": 3}, {"folder": "\\\\server\\share"},
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

    def test_no_daily_limit(self):
        """1 日の件数の上限は無い: 同じ日に何件でも受け付け、フォルダに残さない。今日の件数は数えるだけ"""
        for i in range(7):
            self.put("%d.txt" % i, "https://youtu.be/%s\n" % (chr(ord("a") + i) * 11))
        self.scan2()
        self.assertEqual(len(self.runner.requests), 7)
        self.assertEqual([n for n in os.listdir(self.folder) if n.endswith(".txt")], [], "フォルダに残さない(翌日に回さない)")
        snap = self.it.snapshot()
        self.assertEqual((snap["today"], snap["message"]), (7, ""))
        self.assertNotIn("dailyMax", snap)
        self.assertNotIn("held", snap)

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

    def test_speakers_label_with_styles(self):
        """依頼の記録の「配信者: n人(…)」: 色を指定した人がいれば人数を足す(受付の画面 portal.js は speakersLabel をそのまま出す)"""
        rid = "20261001-120000-abc140"
        self.put(rid + ".request.json", json.dumps({"v": 1, "kind": "url", "id": rid, "streamer": "さくらみこ",
                                                     "speakers": {"count": 2, "names": ["A", "B"], "people": [{"name": "A", "style": {"color": "FF00AA"}}, {"name": "B"}]},
                                                     "items": [{"url": "https://youtu.be/abcdefghijk", "top": 2}]}, ensure_ascii=False))
        self.scan2()
        self.assertEqual(self.runner.last["speakers"], {"count": 2, "names": ["A", "B"], "styles": {"A": {"color": "#FF00AA"}}})
        self.assertEqual(self.it.snapshot()["requests"][0]["speakersLabel"], "配信者: 2人(A・B)・色の指定 1人")

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
                         ("区間: 1:23:45〜1:25:10・0:01:00〜0:01:30・0:09:50〜0:10:00", "カット: 無音で削る", "重み: 音声 1.5・チャット 1.0・コメント 0.7"))
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

    def test_probe_video_needs_audio(self):
        """届いた動画の確かめ(probe_video。中は normalize.probe = 30fps の判定と同じ ffprobe の呼び方。2026-10-09 に寄せた):
        音声があれば ok と長さ・映像だけ・壊れた・無いファイルは「音声のある動画として読めませんでした」(寄せる前と同じ結果を確かめた)"""
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


class TestFeedback(Base):
    """友人のアプリの「要らない」(<zip の名前>.feedback.json。アプリ 2.6.0): 読んで feedback= に渡し、一覧に kind "feedback" で残して 受付済み へ"""

    def test_reject_is_applied_and_filed(self):
        got = []
        self.it.feedback = lambda fb: (got.append(fb), {"ok": True, "summary": "2 本をごみ箱フォルダへ(スタジオのマークを不採用 2 本)"})[1]
        self.put("20261002-120000-0a1b2c__配信A 1-2.feedback.json",
                 '{"v":1,"kind":"feedback","verdict":"reject","zip":"20261002-120000-0a1b2c__配信A 1-2.zip","requestId":"20261002-120000-0a1b2c",'
                 '"title":"配信A 1-2","sentAt":"2026-10-08T01:02:03+09:00"}')
        self.scan2()
        self.assertEqual([f["zip"] for f in got], ["20261002-120000-0a1b2c__配信A 1-2.zip"])
        rec = self.it.st["requests"][0]
        self.assertEqual((rec["kind"], rec["source"], rec["state"], rec["title"]), ("feedback", "app", "accepted", "要らない: 配信A 1-2"))
        self.assertEqual((rec["items"][0]["label"], rec["items"][0]["reason"]), ("20261002-120000-0a1b2c__配信A 1-2.zip", "2 本をごみ箱フォルダへ(スタジオのマークを不採用 2 本)"))
        self.assertTrue(os.path.exists(self.done("20261002-120000-0a1b2c__配信A 1-2.feedback.json")), "受付済み へ")
        self.assertEqual((self.runner.files, self.runner.requests), ([], []), "依頼としては扱わない")

    def test_unreadable_or_unapplied_goes_to_failed(self):
        self.it.feedback = lambda fb: {"ok": False, "reason": "届けた記録に見つかりません: x.zip"}
        self.put("x.feedback.json", '{"v":1,"kind":"feedback","verdict":"reject","zip":"x.zip"}')
        self.put("y.feedback.json", "{broken")
        self.scan2()
        recs = {r["title"]: r for r in self.it.st["requests"]}
        self.assertEqual(recs["要らない: x.zip"]["state"], "rejected")
        self.assertIn("届けた記録に", recs["要らない: x.zip"]["reason"])
        self.assertIn("読めませんでした", recs["y.feedback.json"]["reason"])
        self.assertTrue(os.path.exists(self.failed("x.feedback.json")) and os.path.exists(self.failed("y.feedback.json")), os.listdir(self.folder))
        self.assertFalse(os.path.isdir(os.path.join(self.folder, intake.OUT_DIR)), "友人には知らせない(もう消したあと)")

    def test_without_handler_is_refused(self):
        self.put("x.feedback.json", '{"v":1,"kind":"feedback","verdict":"reject","zip":"x.zip"}')
        self.scan2()
        rec = self.it.st["requests"][0]
        self.assertEqual((rec["kind"], rec["state"]), ("feedback", "rejected"))
        self.assertIn("部品", rec["reason"])


class TestDeliverBatch(Base):
    """依頼ごとの届け方(docs/spec/friend-intake.md の 2-16。2.8.0 のアプリの deliverBatch 1〜10): url・video の依頼はまとめて実行へ渡す。
    無い・範囲の外・手で置いた依頼は None(= ホームの設定 intake.deliverBatch のまま)"""

    def test_parse_deliver_batch(self):
        for v, want in ((1, 1), (5, 5), (10, 10), (0, None), (11, None), (-1, None), (5.0, None), (True, None), (False, None), ("3", None), (None, None),
                        ([2], None)):
            self.assertEqual(intake.parse_deliver_batch(v), want, repr(v))

    def test_url_and_video_requests_pass_batch(self):
        for i, (v, want) in enumerate(((5, 5), (1, 1), (10, 10), (11, None), (0, None), ("5", None), (None, None))):
            rid = "20261008-120000-abc1%02d" % i
            d = {"v": 1, "kind": "url", "id": rid, "flow": "auto", "items": [{"url": "https://youtu.be/abcdefghijk", "top": 2}]}
            if v is not None:
                d["deliverBatch"] = v
            self.put(rid + ".request.json", json.dumps(d))
            self.scan2()
            self.assertEqual((self.runner.requests[-1][1], self.runner.last["batch"]), (rid, want), repr(v))
        self.assertEqual(len(self.runner.requests), 7)
        rid = "20261008-120000-abc1a0"
        self.put(rid + "__clip.mp4", b"clip-batch")
        self.put(rid + ".request.json", json.dumps({"v": 1, "kind": "video", "id": rid, "files": [rid + "__clip.mp4"], "flow": "auto", "deliverBatch": 3}))
        self.scan2()
        self.assertEqual((self.runner.files[-1]["rid"], self.runner.files[-1]["batch"]), (rid, 3))
        # 手で置いた動画・テキスト(依頼の JSON が無い)はホームの設定のまま
        self.put("手で.mp4", b"manual-batch")
        self.put("手で.txt", "https://youtu.be/bbbbbbbbbbb 2\n")
        self.scan2()
        self.assertEqual((self.runner.files[-1]["path"].endswith(".mp4"), self.runner.files[-1]["rid"], self.runner.files[-1]["batch"]), (True, None, None))
        self.assertEqual((self.runner.requests[-1][1], self.runner.last["batch"]), (None, None))


class TestLiveSettings(unittest.TestCase):
    """ライブ配信の依頼の設定(依頼の JSON の live。src/home/live_requests.py の clean_settings・settings_label)。範囲の外・形の違う値は既定"""

    def test_clean_settings_bounds(self):
        cs, dflt = live_requests.clean_settings, live_requests.SETTINGS_DEFAULT
        for v in (None, "x", [1], 5, {}):
            self.assertEqual(cs(v), dflt, repr(v))
        self.assertIsNot(cs(None), dflt, "既定の写しを返す(書き換えても既定は変わらない)")
        self.assertEqual(cs({"sens": "low", "perHour": 1, "length": 10, "waitMin": 1, "pad": 0, "afterStream": False}),
                         {"sens": "low", "perHour": 1, "length": 10, "waitMin": 1, "pad": 0.0, "afterStream": False})   # 下の端
        self.assertEqual(cs({"sens": "high", "perHour": 30, "length": 120, "waitMin": 60, "pad": 5, "afterStream": True}),
                         {"sens": "high", "perHour": 30, "length": 120, "waitMin": 60, "pad": 5.0, "afterStream": True})   # 上の端
        for k, bad in (("perHour", 0), ("perHour", 31), ("length", 9), ("length", 121), ("waitMin", 0), ("waitMin", 61), ("pad", -0.1), ("pad", 5.1),
                       ("perHour", True), ("perHour", "6"), ("perHour", None), ("pad", None), ("pad", "1"), ("pad", float("nan")), ("length", float("inf")),
                       ("sens", "HIGH"), ("sens", None), ("sens", 1), ("afterStream", "false"), ("afterStream", 0), ("afterStream", None)):
            self.assertEqual(cs({k: bad})[k], dflt[k], (k, bad))
        got = cs({"perHour": 6.6, "length": 44.4, "waitMin": 2.6, "pad": 1, "unknown": 1})
        self.assertEqual(got, dict(dflt, perHour=7, length=44, waitMin=3, pad=1.0), "小数は丸める・余白は小数・知らない鍵は捨てる")
        self.assertTrue(isinstance(got["perHour"], int) and isinstance(got["pad"], float))

    def test_settings_label(self):
        self.assertEqual(live_requests.settings_label(live_requests.SETTINGS_DEFAULT),
                         "ライブの設定: 感度 普通・1 時間 6 本・長さ 45 秒・待ち 5 分・余白 2 秒・配信後の追加 あり")
        self.assertEqual(live_requests.settings_label({"sens": "high", "perHour": 12, "length": 60, "waitMin": 3, "pad": 1.5, "afterStream": False}),
                         "ライブの設定: 感度 高・1 時間 12 本・長さ 60 秒・待ち 3 分・余白 1.5 秒・配信後の追加 なし")


class TestLiveRequest(Base):
    """ライブ配信の依頼(docs/spec/friend-intake.md の 2-15。2.8.0 のアプリの kind live): 配信中・配信前なら live_begin(= Live.begin_request)で録画を始めて結びつける。
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
             "memo": "歌のところ", "speakers": {"count": 1, "names": ["さくらみこ"]}, "videoTracks": 3, "cut": "silence",
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

    def test_live_request_keeps_deliver_batch(self):
        """10-09 ユーザー決定(decisions 3-20): ライブ配信の依頼も届け方(2.9.0 のアプリの deliverBatch)を結びつきに残し、受付の記録の文も合わせる"""
        self.infos[self.VID] = {"duration": None, "live": "is_live", "title": "配信中", "channel": "Miko Ch."}
        rec = self.send("20261008-200000-abc302", deliverBatch=3)
        (_url, ctx), = self.begun
        self.assertEqual(ctx["deliverBatch"], 3)
        self.assertIn("3 本ごとに組で届けます", rec["items"][0]["reason"])

    def test_live_now_begins_recording_and_links(self):
        self.infos[self.VID] = {"duration": None, "live": "is_live", "title": "【歌枠】配信中", "channel": "Miko Ch."}
        rid = "20261008-200000-abc301"
        rec = self.send(rid, live={"sens": "high", "perHour": 31, "length": 60, "waitMin": 0, "pad": 1.5, "afterStream": False})
        (url, ctx), = self.begun
        self.assertEqual(url, "https://www.youtube.com/watch?v=abcdefghijk")   # 書き方の違う URL(/live/…?si=)はそろえる
        want = {"sens": "high", "perHour": 6, "length": 60, "waitMin": 5, "pad": 1.5, "afterStream": False}   # 範囲の外(31・0)は既定
        self.assertEqual(ctx, {"rid": rid, "deliverDir": os.path.join(self.folder, intake.OUT_DIR), "url": url, "title": "【歌枠】配信中",
                               "streamer": "さくらみこ", "speakers": self.SPEAKERS, "videoTracks": 3, "cut": "silence", "memo": "歌のところ", "settings": want,
                               "deliverBatch": None})   # 届け方の指定が無い依頼(2.8.x のアプリ)= ホームの設定
        self.assertEqual((self.runner.requests, self.runner.files), ([], []), "録画の依頼はまとめて実行へ入れない(切り抜きごとに入口が入れる)")
        self.assertEqual((rec["kind"], rec["state"], rec["source"], rec["title"], rec["flowLabel"], rec["streamer"], rec["memo"]),
                         ("live", "accepted", "app", "【歌枠】配信中", "① 全自動", "さくらみこ", "歌のところ"))
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
        """終わった配信(not_live・was_live)は kind url の ① 全自動と同じ: 切り抜く数はホームの既定・届け方は依頼の指定(2.9.0。10-09 ユーザー決定)・知らせの行「ライブ配信」"""
        for i, (live, title) in enumerate((("not_live", "終わった配信"), ("was_live", "アーカイブ"))):
            self.infos[self.VID] = {"duration": 3600.0, "live": live, "title": title, "channel": "ch"}
            rid = "20261008-200000-abc31%d" % i
            rec = self.send(rid, deliverBatch=5)   # 届け方の指定(5 本ごと)をそのまま
            self.assertEqual(self.begun, [], "録画は始めない")
            items, got = self.runner.requests[-1]
            self.assertEqual(([(x["id"], x["top"], x["ranges"]) for x in items], got), ([(self.VID, 4, [])], rid))
            self.assertEqual(self.runner.last, {"flow": "auto", "deliver": os.path.join(self.folder, intake.OUT_DIR), "speakers": self.SPEAKERS, "tracks": 3,
                                                "cut": "silence", "weights": None, "streamer": "さくらみこ", "batch": 5})
            self.assertEqual((rec["kind"], rec["state"], rec["title"], rec["flowLabel"]), ("url", "accepted", title, "① 全自動"))
            note = [x for x in rec["items"] if x["label"] == "ライブ配信"]
            self.assertEqual([(x["state"], "配信は終わっていた" in x["reason"]) for x in note], [("accepted", True)])
            self.assertTrue(os.path.isfile(self.done(rid + ".request.json")))
        self.assertEqual(len(self.runner.requests), 2)
        self.assertFalse(os.path.exists(os.path.join(self.folder, intake.OUT_DIR)))
        # 配信の状態が分からない(yt-dlp が答えない)は、まず録画を試す(10-09。① 全自動へ落とすのは録画も始められなかったときだけ = test_unknown_status_*)
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
        """状態を確かめられなかった(yt-dlp が失敗・無い = info が None)→ 録画を試す(Live.begin が自分でもう一度調べる)。始まれば配信中・配信前と同じ受け付け。
        10-08 に配信前の依頼 2 件が「確かめられない → アーカイブから ①」に落ちて解析が失敗した(10-09)"""
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
    ほかの失敗は None(10-09。10-08 に配信前の依頼で None になっていた)"""

    def run_info(self, returncode, stdout, stderr=""):
        from unittest import mock
        calls = []

        def fake_run(args, **kw):
            calls.append(list(args))
            return subprocess.CompletedProcess(args, returncode, stdout.encode("utf-8"), stderr.encode("utf-8"))

        with mock.patch.dict(os.environ, {"STUDIO_FAKE": "0"}), mock.patch.object(intake.tools, "find_tool", lambda name: "C:/x/yt-dlp.exe"), \
                mock.patch.object(intake.subprocess, "run", fake_run):
            out = intake.youtube_info("abcdefghijk")
        return out, calls

    def test_upcoming_is_reported_not_none(self):
        out, calls = self.run_info(0, "NA\tis_upcoming\tMiko Ch.\t🌸FreeChat\n")
        self.assertEqual(out, {"duration": None, "live": "is_upcoming", "channel": "Miko Ch.", "title": "🌸FreeChat"})
        self.assertEqual(len(calls), 1)
        self.assertIn("--ignore-no-formats-error", calls[0])
        self.assertEqual(calls[0][-1], "https://www.youtube.com/watch?v=abcdefghijk")

    def test_old_ytdlp_error_text_means_upcoming(self):
        out, _calls = self.run_info(1, "", "ERROR: [youtube] abcdefghijk: This live event will begin in 3 minutes.\n")
        self.assertEqual(out, {"duration": None, "live": "is_upcoming", "channel": "", "title": ""})
        out, _calls = self.run_info(1, "", "ERROR: [youtube] abcdefghijk: Premieres in 2 hours\n")
        self.assertEqual(out["live"], "is_upcoming")

    def test_other_failures_are_none(self):
        self.assertIsNone(self.run_info(1, "", "ERROR: [youtube] abcdefghijk: Video unavailable\n")[0])
        self.assertIsNone(self.run_info(0, "garbage\n")[0])
        out, _calls = self.run_info(0, "3600\twas_live\tch\t題\n")
        self.assertEqual(out, {"duration": 3600.0, "live": "was_live", "channel": "ch", "title": "題"})


if __name__ == "__main__":
    unittest.main()
