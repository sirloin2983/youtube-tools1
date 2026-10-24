"""「確かめる」の誰の声のカードの出どころ voice:solo(src/app/check/voice_solo.py)の単体テスト: ソロの見分け(コラボの題名・2 人の題名・
話者が 2 人・評価用・判別の記録のある文書は出ない)・行の選び方(覚える材料の決まり・1 本から 3 行まで・文書を回す)・量(覚えた秒と答えで減る)・
選択肢と予想・答えの反映の登録。一時フォルダの文書と同梱の名簿だけを使う(本物の声の登録簿は読まない)。

実行(リポジトリ直下から): py -3.12 -m unittest tests/app/check/test_voice_solo.py -v
"""
import os
import sys
import unittest
from unittest import mock

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import _checkkit as kit  # noqa: E402

from app.check import sources, voice_solo  # noqa: E402
from human.check import apply, voice as voice_mod  # noqa: E402
from pipeline.transcribe import roster  # noqa: E402
from ytt import schemas  # noqa: E402

MIKO = "さくらみこ"
NEED = 30.0 * voice_solo.MARGIN


def rows(n=5, **extra):
    """4 秒の行 n 本 + 覚える材料にならない行(短い・混ざり・BGM・字幕に出さない・長すぎる・ゲームの音)"""
    out = [{"id": "s%d" % i, "start": i * 10.0, "end": i * 10.0 + 4.0, "text": "話す %d" % i, "speaker": "S1"} for i in range(n)]
    out += [{"id": "x1", "start": 100.0, "end": 100.5, "text": "短い", "speaker": "S1"},
            {"id": "x2", "start": 110.0, "end": 114.0, "text": "混ざり", "speaker": "S1", "flag": schemas.MIXED_FLAG},
            {"id": "x3", "start": 120.0, "end": 124.0, "text": "BGM", "speaker": "S1", "tags": ["bgm"]},
            {"id": "x4", "start": 130.0, "end": 134.0, "text": "出さない", "speaker": "S1", "noSub": True},
            {"id": "x5", "start": 140.0, "end": 160.0, "text": "長い", "speaker": "S1"},
            {"id": "x6", "start": 170.0, "end": 174.0, "text": "ゲーム", "speaker": schemas.OTHER_SPK_ID}]
    for g in out:
        g.update(extra)
    return out


MEDIA = []   # 元の動画(setUp が一時フォルダに空のファイルを作る。元の動画が無い文書は出さない = 10-24)


def doc(title, updated=100, speakers=None, segs=None, **kw):
    return dict({"title": title, "updatedAt": updated, "speakers": speakers if speakers is not None else [{"id": "S1", "name": MIKO}],
                 "segments": segs if segs is not None else rows(), "sourcePath": MEDIA[0] if MEDIA else ""}, **kw)


class State:
    def __init__(self, answers=()):
        self.answers = list(answers)

    def effective(self):
        return self.answers


class VoiceSoloTest(unittest.TestCase):
    def setUp(self):
        self.tmp = kit.tempdir(self, "ytt-check-solo-")
        self.tx = os.path.join(self.tmp, "transcribe", "transcripts")
        media = os.path.join(self.tmp, "clip.mp4")
        open(media, "wb").close()
        MEDIA[:] = [media]
        self.addCleanup(MEDIA.clear)
        self.ctx = kit.Ctx(os.path.join(self.tmp, "app"), kit.ROOT, env={"YTT_DATA_DIR": self.tmp}, eval_dirs=[])
        self.reg = {}
        for p in (mock.patch.object(roster, "ROSTER", roster.BUNDLED), mock.patch.object(voice_mod, "registry", lambda emb, cache=None: self.reg),
                  mock.patch.object(voice_mod, "_relearn_sec", lambda: 30.0)):
            p.start()
            self.addCleanup(p.stop)
        for i in range(6):   # ソロ 6 本
            self.put("a0000000000%d" % i, doc("【マイクラ】%s の建築 %d" % (MIKO, i), updated=200 - i))

    def put(self, tid, d, diar=None):
        kit.write(os.path.join(self.tx, tid + ".json"), d)
        if diar is not None:
            kit.write(os.path.join(self.tx, tid + ".diar.json"), {"schema": sources.DIAR_SCHEMA, "latest": diar, "history": []})

    def cards(self, answers=()):
        return voice_solo.voice_solo(sources.View(self.ctx, State(answers)))

    def test_solo_rows_spread_and_amount(self):
        cards = self.cards()
        self.assertTrue(cards)
        self.assertEqual({c["guess"]["name"] for c in cards}, {MIKO})
        self.assertEqual({c["target"]["row"] for c in cards} & {"x1", "x2", "x3", "x4", "x5", "x6"}, set())   # 覚える材料の決まりの外の行は出ない
        docs = [c["target"]["docId"] for c in cards]
        self.assertEqual(len(set(docs[:6])), 6)                                  # 先に文書を 1 行ずつ回す(いろいろな配信から)
        self.assertTrue(all(docs.count(t) <= voice_solo.PER_DOC for t in docs))
        sec = sum(c["media"]["end"] - c["media"]["start"] for c in cards)
        self.assertGreaterEqual(sec, NEED)                                       # 覚え直す秒 × 余裕に届くまで
        self.assertLess(sec - 4.0, NEED)                                         # 届いたら止める
        c = cards[0]
        self.assertEqual((c["kind"], c["source"], c["note"]), ("voice", "solo", "solo"))
        self.assertEqual(c["guess"], {"id": "S1", "name": MIKO})                  # 文書にその名前の話者がいればその id
        self.assertEqual([o["id"] for o in c["options"]][-2:], [voice_mod.OTHER, voice_mod.MIXED])
        self.assertLess(c["_order"][0], 0)                                       # voice:diar より先に並ぶ

    def test_not_solo_is_skipped(self):
        bad = {"b00000000001": doc("【コラボ】%s とあそぶ" % MIKO),                       # コラボの印
               "b00000000002": doc("%s×星街すいせい" % MIKO),                            # 名簿の 2 人
               "b00000000003": doc("%s の雑談" % MIKO, segs=rows() + [{"id": "y", "start": 200.0, "end": 204.0, "text": "a", "speaker": "S2"}],
                                   speakers=[{"id": "S1", "name": MIKO}, {"id": "S2", "name": "話者2"}]),   # 行の話者が 2 人
               "b00000000004": doc("%s の雑談" % MIKO, speakers=[{"id": "S1", "name": "星街すいせい"}]),   # 名簿のほかの人の話者
               "b00000000005": doc("%s の雑談" % MIKO, evalSet=True)}                     # 評価用
        for tid, d in bad.items():
            self.put(tid, d)
        self.put("b00000000006", doc("%s の雑談" % MIKO), diar={"rows": {"s0": {"speaker": "S1"}}})   # 判別の記録がある = voice:diar が出す
        self.reg = {MIKO: {"sec": 0}}
        got = {c["target"]["docId"] for c in voice_solo.voice_solo(sources.View(self.ctx, State()))}
        self.assertEqual(got & set(bad) | (got & {"b00000000006"}), set())

    def test_learned_and_answered_reduce(self):
        self.reg = {MIKO: {"sec": NEED, "learnedFrom": [{"doc": "a0000000000%d" % i, "rows": []} for i in range(5)]}}
        cards = self.cards()
        self.assertEqual(len(cards), voice_solo.LEARNED_CARDS)                   # 覚えた人も止めない(10-24 夜)= 少しだけ
        self.assertIn("a00000000005", {c["target"]["docId"] for c in cards})     # まだ材料に入っていない配信が先(並びの順なら a0〜a2)
        self.reg[MIKO]["sec"] = NEED * 6
        with mock.patch.object(voice_solo.random, "random", lambda: 0.9):
            self.assertEqual(len(self.cards()), 0)                               # 材料が多いほど少ない(3 × 1/6 = 0.5 枚 = くじ)
        with mock.patch.object(voice_solo.random, "random", lambda: 0.1):
            self.assertEqual(len(self.cards()), 1)
        self.reg = {MIKO: {"sec": NEED - 8.0, "learnedFrom": [{"doc": "a00000000000", "rows": ["s0"]}]}}
        cards = self.cards()
        self.assertEqual(len(cards), 2)                                          # 残り 8 秒 = 4 秒の行 2 本
        self.assertNotIn(("a00000000000", "s0"), {(c["target"]["docId"], c["target"]["row"]) for c in cards})
        first = cards[0]
        ans = {"kind": "voice", "applied": {"doc": first["target"]["docId"], "row": first["target"]["row"], "learn": {"name": MIKO, "sec": 4.0}}}
        self.assertEqual(len(self.cards([ans])), 1)                              # 名前で答えた行の秒を数える(答えた行は出さない)
        ans["applied"]["learn"] = None                                           # 混ざり・その他で答えた行は数えない = 次の行が出る
        self.assertEqual(len(self.cards([ans])), 2)

    def test_name_option_when_doc_has_no_speaker(self):
        self.put("c00000000001", doc("%s の朝雑談" % MIKO, updated=300, speakers=[], segs=rows(speaker="")))   # 歌枠は外す(10-24 夜)ので雑談に
        c = next(c for c in self.cards() if c["target"]["docId"] == "c00000000001")
        self.assertEqual(c["guess"], {"id": voice_mod.NAME_PREFIX + MIKO, "name": MIKO})   # 答えると文書に話者を足す(voice:diar と同じ name: の形)

    def test_answers_are_applied_like_diar(self):
        self.assertIn(("voice", "solo"), apply._REG)
        self.assertIs(apply._REG[("voice", "solo")].apply, apply._REG[("voice", "diar")].apply)

    def test_missing_media_is_skipped(self):
        """元の動画が無い文書は聞けないので出さない(10-24)"""
        self.put("f00000000001", doc("%s の雑談" % MIKO, updated=999, sourcePath=os.path.join(self.tmp, "gone.mp4")))
        self.assertNotIn("f00000000001", {c["target"]["docId"] for c in self.cards()})

    def test_kept_clip_plays_without_media(self):
        """切り出して残した行の音があれば、元の動画が片付いた文書の行もカードになり、その音で流す(10-24 夜)。clip_targets は動画のある文書の
        まだ切り出していない行だけを返す"""
        from human.proof import voiceclips
        from ytt import workdata
        gone = doc("兎田ぺこら の雑談", updated=999, speakers=[{"id": "S1", "name": "兎田ぺこら"}], sourcePath=os.path.join(self.tmp, "gone.mp4"))   # 別の人(枠が空いている)
        self.put("f00000000002", gone)
        clip_dir = os.path.join(self.tmp, "data", voiceclips.DIR, "f00000000002")
        os.makedirs(clip_dir)
        row = gone["segments"][0]   # s0(覚える材料になる行)
        open(os.path.join(clip_dir, row["id"] + ".wav"), "wb").close()
        kit.write(os.path.join(clip_dir, voiceclips.INDEX), {row["id"]: {"a": row["start"] - 1.0, "b": row["end"] + 1.0}})
        with mock.patch.object(workdata, "DATA_DIR", os.path.join(self.tmp, "data")):
            got = [c for c in self.cards() if c["target"]["docId"] == "f00000000002"]
            self.assertEqual([c["target"]["row"] for c in got], [row["id"]])   # 音のある行だけ
            self.assertTrue(got[0]["media"]["url"].startswith("api/check/voiceclip?doc=f00000000002&row="))
            self.assertLess(got[0]["media"]["start"], 1.5)   # 切り出した音の中の秒
            have = os.path.join(self.tmp, "data", voiceclips.DIR, "a00000000000")   # 動画のある文書に音があっても映像つきで流す(10-25 直し)
            os.makedirs(have)
            open(os.path.join(have, "s0.wav"), "wb").close()
            kit.write(os.path.join(have, voiceclips.INDEX), {"s0": {"a": -1.0, "b": 5.0}})
            vid = [c for c in self.cards() if c["target"]["docId"] == "a00000000000"]
            self.assertTrue(vid and all(c["media"]["url"].startswith("transcribe/media?id=") for c in vid))
            targets = voice_solo.clip_targets(sources.View(self.ctx, State()))
            self.assertNotIn("f00000000002", {t for t, _d, _r in targets})   # 動画が無い文書は切り出せない
            self.assertTrue(targets and all(r for _t, _d, r in targets))

    def test_songs_are_skipped(self):
        """歌は声を覚える材料にしない(10-24 夜): 題名に歌の印がある配信の文書と、音符のある行。外した数は LAST_SKIPS"""
        self.put("b00000000001", doc("【歌枠】%s のアニソン" % MIKO, updated=999))
        segs = rows()
        segs[0]["text"] = "♪ ラララ"
        self.put("b00000000002", doc("兎田ぺこら の雑談", updated=998, speakers=[{"id": "S1", "name": "兎田ぺこら"}], segs=segs))
        got = self.cards()
        self.assertNotIn("b00000000001", {c["target"]["docId"] for c in got})
        self.assertNotIn(("b00000000002", segs[0]["id"]), {(c["target"]["docId"], c["target"]["row"]) for c in got})
        self.assertIn("b00000000002", {c["target"]["docId"] for c in got})   # 歌でない行は出る
        self.assertEqual((voice_solo.LAST_SKIPS["songDocs"], voice_solo.LAST_SKIPS["songRows"] >= 1), (1, True))
        self.assertTrue(voice_solo.song_title(["Singing stream!"]) and not voice_solo.song_title(["雑談"]))

    def test_group_streams_are_not_solo(self):
        """題名の【】がグループの名前(メンバーの名前なし)・「みんなで」は外す。所属の札【名前/グループ】は外さない(10-24)"""
        self.put("d00000000001", doc("【アソビ★まわり隊!】クイズ!【%s/ホロライブ】" % MIKO))
        self.put("d00000000002", doc("【ゲーム】みんなで遊ぼ!【%s】" % MIKO))
        self.put("d00000000003", doc("【雑談】おしゃべり【%s/ホロライブ/アソビ★まわり隊!】" % MIKO, updated=900))
        got = {c["target"]["docId"] for c in self.cards()}
        self.assertNotIn("d00000000001", got)
        self.assertNotIn("d00000000002", got)
        self.assertIn("d00000000003", got)

    def test_diar_cards_off_by_default(self):
        """判別の記録から作る声のカードは既定で出さない(ソロ配信限定)。環境変数でオン"""
        self.put("e00000000001", doc("%s の雑談" % MIKO), diar={"rows": {"s0": {"speaker": "S1", "ratio": 0.9}}})
        with mock.patch.dict(os.environ, {}, clear=False):
            os.environ.pop("YTT_CHECK_VOICE_DIAR", None)
            self.assertEqual(sources.voice_diar(sources.View(self.ctx, State())), [])
        with mock.patch.dict(os.environ, {"YTT_CHECK_VOICE_DIAR": "1"}):
            self.assertTrue(sources.voice_diar(sources.View(self.ctx, State())))

    def test_no_roster_no_cards(self):
        with mock.patch.object(roster, "ROSTER", None):
            self.assertEqual(self.cards(), [])


if __name__ == "__main__":
    unittest.main()
