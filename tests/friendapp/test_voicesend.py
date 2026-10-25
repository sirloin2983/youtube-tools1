"""友人の PC から送る声の材料の通し(src/friendapp/voicesend.py → src/human/friend/voicein.py。10-24 夜)。
友人の PC がソロ配信の文書の行を切り出して送り返しの zip にし、ユーザーの PC の受付(returns.scan)が小さな文書と行の音にする。
歌の配信・歌の行は外す。本物の ffmpeg で 30 秒の音を作って通す(30 秒以下の工程は本物の通し 1 本)。
実行(リポジトリ直下から): py -3.12 -m unittest tests/friendapp/test_voicesend.py -v
"""
import json
import os
import shutil
import subprocess
import sys
import tempfile
import unittest
import zipfile
from unittest import mock

os.environ.setdefault("YTT_DATA_DIR", "inplace")
SRC = os.path.join(os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))), "src")
if SRC not in sys.path:
    sys.path.insert(0, SRC)

from friendapp import voicesend as VS  # noqa: E402
from human.check import voice as voice_mod  # noqa: E402
from human.friend import returns as R, voicein as VI  # noqa: E402
from human.proof import voiceclips, store  # noqa: E402
from pipeline.transcribe import roster  # noqa: E402
from ytt import tools, workdata  # noqa: E402

MIKO = "さくらみこ"
FF = tools.find_tool("ffmpeg")


def read_json(p):
    with open(p, encoding="utf-8") as f:
        return json.load(f)


def write_doc(data, tid, title, segs, src):
    os.makedirs(os.path.join(data, "transcripts"), exist_ok=True)
    p = os.path.join(data, "transcripts", tid + ".json")
    with open(p, "w", encoding="utf-8") as f:
        json.dump({"id": tid, "title": title, "sourcePath": src, "speakers": [{"id": "S1", "name": MIKO}], "segments": segs}, f, ensure_ascii=False)
    os.utime(p, (1000, 1000))


@unittest.skipUnless(FF, "ffmpeg が無い")
class VoiceSendTest(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.mkdtemp(prefix="ytt-voicesend-")
        self.addCleanup(shutil.rmtree, self.tmp, True)
        self.src = os.path.join(self.tmp, "a.wav")
        subprocess.run([FF, "-hide_banner", "-nostdin", "-y", "-v", "error", "-f", "lavfi", "-i", "sine=frequency=300:sample_rate=48000:duration=30",
                        "-c:a", "pcm_s16le", self.src], check=True, creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0))
        self.friend = os.path.join(self.tmp, "friend")   # 友人の PC の ② の作業データ
        segs = [{"id": "s%d" % i, "start": i * 5.0 + 1, "end": i * 5.0 + 5, "text": "話す %d" % i, "speaker": "S1"} for i in range(5)]
        segs.append({"id": "m1", "start": 26.0, "end": 29.0, "text": "♪ うた", "speaker": "S1"})
        write_doc(self.friend, "aaaaaaaaaaaa", "【雑談】さくらみこ のんびり話す", segs, self.src)
        write_doc(self.friend, "bbbbbbbbbbbb", "【歌枠】さくらみこ 歌う", segs, self.src)
        self.reg = {}
        for p in (mock.patch.object(roster, "ROSTER", roster.BUNDLED), mock.patch.object(voice_mod, "registry", lambda emb, cache=None: self.reg),
                  mock.patch.object(voice_mod, "_relearn_sec", lambda: 30.0)):
            p.start()
            self.addCleanup(p.stop)

    def test_friend_to_user(self):
        outbox, sent = os.path.join(self.tmp, "outbox"), os.path.join(self.tmp, "voice-sent.json")
        logs = []
        self.assertEqual(VS.build(outbox, sent, now=10 ** 6, log=logs.append, data_dir=self.friend), 1)
        self.assertEqual(os.listdir(outbox), ["voice__aaaaaaaaaaaa.voice.zip"])   # 歌枠の配信は外す
        self.assertIn("歌の配信で外した 1 本", logs[-1])
        with zipfile.ZipFile(os.path.join(outbox, "voice__aaaaaaaaaaaa.voice.zip")) as z:
            meta = json.loads(z.read("meta.json"))
            self.assertEqual(len(meta["rows"]), VS.PER_DOC)
            self.assertNotIn("m1", meta["rows"])   # 歌の行は外す
            self.assertEqual((meta["streamer"], meta["doc"]), (MIKO, "aaaaaaaaaaaa"))
        self.assertEqual(VS.build(outbox, sent, now=10 ** 6, data_dir=self.friend), 0)   # 送った文書は 2 回作らない

        # ユーザーの PC: 同期フォルダの 送り返し\ に届いた
        user = os.path.join(self.tmp, "user")
        old = (workdata.DATA_DIR, workdata.TX_DIR)
        workdata.set_data_dir(user)
        self.addCleanup(lambda: (setattr(workdata, "DATA_DIR", old[0]), setattr(workdata, "TX_DIR", old[1])))
        sync = os.path.join(self.tmp, "sync")
        os.makedirs(os.path.join(sync, R.IN_DIR))
        z = os.path.join(sync, R.IN_DIR, "voice__aaaaaaaaaaaa.voice.zip")
        shutil.copy(os.path.join(outbox, "voice__aaaaaaaaaaaa.voice.zip"), z)
        os.utime(z, (1000, 1000))
        got = R.scan(sync, os.path.join(self.tmp, "app"), clock=lambda: 10 ** 6)
        self.assertEqual([(r["kind"], r["state"]) for r in got], [("voice", "accepted")])
        doc = read_json(store.tx_path("aaaaaaaaaaaa"))
        self.assertEqual((doc["origin"], doc["sourcePath"], doc["speakers"][0]["name"], len(doc["segments"])), (VI.ORIGIN, "", MIKO, 3))
        g = doc["segments"][0]
        self.assertIsNotNone(voiceclips.media("aaaaaaaaaaaa", g["id"], g["start"], g["end"]))   # 送られた音でカードを流せる
        self.assertFalse(os.path.exists(z))   # 受付済みへ

        # 同じ配信の同じ所が別の文書の印で届いた(友人の PC が同じ配信を 2 本の文書にした)= 受け取らない
        self.reg = {MIKO: {"sec": 60.0}}
        shutil.copy(os.path.join(outbox, "voice__aaaaaaaaaaaa.voice.zip"), os.path.join(sync, R.IN_DIR, "x__cccccccccccc.voice.zip"))
        os.utime(os.path.join(sync, R.IN_DIR, "x__cccccccccccc.voice.zip"), (1000, 1000))
        got = R.scan(sync, os.path.join(self.tmp, "app"), clock=lambda: 10 ** 6)
        self.assertEqual([r["state"] for r in got], ["accepted"])
        self.assertIn("同じ配信の同じ所 3", got[0]["reason"])                  # 同じ配信(題名)の同じ所 = 同じ声を 2 回覚えない(10-25)
        self.assertFalse(os.path.exists(store.tx_path("cccccccccccc")))

    def test_bad_zip_refused(self):
        user = os.path.join(self.tmp, "user")
        old = (workdata.DATA_DIR, workdata.TX_DIR)
        workdata.set_data_dir(user)
        self.addCleanup(lambda: (setattr(workdata, "DATA_DIR", old[0]), setattr(workdata, "TX_DIR", old[1])))
        p = os.path.join(self.tmp, "x__dddddddddddd.voice.zip")
        with zipfile.ZipFile(p, "w") as z:
            z.writestr("meta.json", json.dumps({"format": VS.FORMAT, "streamer": MIKO, "rows": {}}))
            z.writestr("../evil.wav", b"x")
        self.assertEqual(VI.take("x__dddddddddddd.voice.zip", p, lambda m: None)[0], "rejected")


if __name__ == "__main__":
    unittest.main()
