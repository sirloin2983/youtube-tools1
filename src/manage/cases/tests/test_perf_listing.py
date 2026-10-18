#!/usr/bin/env python3
"""案件の一覧の速さの工夫(PERF O5・O15)が、ふつうの経路と同じ結果を返すことの突き合わせ。

    python -m unittest src/manage/cases/tests/test_perf_listing.py

- O5: txindex.pick に load の結果(Docs = 逆引きつき)を渡したときと、ふつうのリスト(全部を照らす)を渡したときで、
  選ぶ文書・紐づいた数・id の順(同じ id の別の文書・同率の更新日時・片方の経路だけの一致・付け替える前のパスも)が同じ。
  (cases.build の丸ごとの結び付けは test_cases の test_links_clips_transcripts_and_packs で確かめる)
- O15: txindex.doc_paths・docloc.iter_tids が、使える索引・壊れた索引・置き場の違いを同時に置いたときに決めた中身を返す
  (期待値は書き出した固定の値)
"""
import json
import os
os.environ.setdefault("YTT_DATA_DIR", "inplace")
import random
import shutil
import sys
import tempfile
import unittest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))))   # src
from manage.cases import txindex  # noqa: E402
from ytt import docloc, schemas, workdata  # noqa: E402


# ---------------------------------------------------------------- O5
VIDS = ["v1", "v2", "", None, 0, 1, True, ["v1"]]
MARKS = ["m1", "m2", "", None, 1, 1.0, {"a": 1}]


def rand_doc(rnd, paths, i):
    """_parse を通した文書(ときどき _parse を通らない生の形も)。id は少ない種類から(同じ id の別の文書を作る)"""
    clip = None
    if rnd.random() < 0.7:
        clip = {"source": {"videoId": rnd.choice(VIDS)} if rnd.random() < 0.9 else "x",
                "mark": {"id": rnd.choice(MARKS)} if rnd.random() < 0.9 else None}
    relinks = [{"why": rnd.choice([txindex.NORM_WHY, "other"]), "from": rnd.choice(paths)} for _ in range(rnd.randint(0, 2))]
    raw = {"id": "%012x" % rnd.randint(0, 6), "title": "t%d" % i, "sourcePath": rnd.choice(paths + [""]), "relinks": relinks,
           "clip": clip, "segments": [], "updatedAt": rnd.choice([0, 5, 5, 9, 9, 12])}
    d = txindex._parse(raw, "%012x" % i)
    if rnd.random() < 0.15:   # load を通らずに作った文書(_paths が無い)
        d = {k: v for k, v in d.items() if k != "_paths"}
    return d


class PickMatchesOldTest(unittest.TestCase):
    def setUp(self):
        base = tempfile.gettempdir()
        p = [os.path.join(base, "perf-o5", "clip%d.mp4" % k) for k in range(5)]
        self.paths = p + [p[0].upper(), p[1].replace(os.sep, "/")]   # 大文字小文字・区切りの違い(norm でそろう)

    def test_pick_same_as_scan(self):
        multi = 0
        for seed in range(300):
            rnd = random.Random(seed)
            plain = [rand_doc(rnd, self.paths, i) for i in range(rnd.randint(0, 30))]
            fast = txindex.Docs(plain)
            for _ in range(40):
                vid, mid, media = rnd.choice(VIDS), rnd.choice(MARKS), rnd.choice(self.paths + ["", None])
                want = txindex.pick(plain, vid, mid, media)
                got = txindex.pick(fast, vid, mid, media)
                self.assertIs(got[0], want[0], (seed, vid, mid, media))
                self.assertEqual(got[1:], want[1:], (seed, vid, mid, media))
                multi += want[1] >= 2
        self.assertGreater(multi, 100)   # 複数の文書が紐づく(同率・同じ id の別の文書を選ぶ)例を十分に含む

    def test_rebuilds_when_length_changes(self):
        rnd = random.Random(7)
        fast = txindex.Docs(rand_doc(rnd, self.paths, i) for i in range(10))
        txindex.pick(fast, "v1", "m1", self.paths[0])
        fast.append(dict(txindex._parse({"id": "aaaaaaaaaaaa", "sourcePath": self.paths[0], "segments": [], "updatedAt": 99}, "x")))
        self.assertEqual(txindex.pick(fast, "v1", "m1", self.paths[0]), txindex.pick(list(fast), "v1", "m1", self.paths[0]))
        self.assertEqual(txindex.pick(fast, "", "", self.paths[0])[0]["updatedAt"], 99)

# ---------------------------------------------------------------- O15
class DocPathsTest(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.mkdtemp(prefix="perf-o15-")
        self.addCleanup(shutil.rmtree, self.tmp, True)
        saved = {n: getattr(workdata, n) for n in ("DATA_DIR", "TX_DIR", "TMP_DIR", "SETTINGS", "FEEDBACK")}
        self.addCleanup(lambda: [setattr(workdata, n, v) for n, v in saved.items()])
        workdata.set_data_dir(os.path.join(self.tmp, "data"))
        self.tx = workdata.TX_DIR
        os.makedirs(self.tx)
        docloc._warned.clear()

    def _write(self, path, d):
        os.makedirs(os.path.dirname(path), exist_ok=True)
        with open(path, "w", encoding="utf-8") as f:
            f.write(d if isinstance(d, str) else json.dumps(d))

    def _loc(self, tid, folder, **over):
        self._write(os.path.join(self.tx, tid + docloc.LOC_SUFFIX), dict({"version": 1, "id": tid, "dir": folder}, **over))

    def test_mixed_indexes(self):
        work = os.path.join(self.tmp, "out", "題名", schemas.WORK_DIR)
        wrong = os.path.join(self.tmp, "out", "題名", "ほか")
        t = ["%012x" % k for k in range(12)]
        self._write(os.path.join(self.tx, t[0] + ".json"), {})                       # 索引なし
        self._write(os.path.join(work, t[1] + ".json"), {})
        self._loc(t[1], work)                                                       # 使える索引
        self._write(os.path.join(self.tx, t[2] + ".json"), {})
        self._write(os.path.join(work, t[2] + ".json"), {})
        self._loc(t[2], work)                                                       # 使える索引 + 根にも古い文書
        self._loc(t[3], work)                                                       # 置いた先に文書が無い
        self._write(os.path.join(self.tx, t[4] + ".json"), {})
        self._loc(t[4], work)                                                       # 同上 + 根に文書
        self._write(os.path.join(self.tx, t[5] + docloc.LOC_SUFFIX), "{壊れ")     # 壊れた索引
        self._write(os.path.join(self.tx, t[6] + ".json"), {})
        self._write(os.path.join(self.tx, t[6] + docloc.LOC_SUFFIX), "[]")          # 形の違う索引 + 根に文書
        self._write(os.path.join(wrong, t[7] + ".json"), {})
        self._loc(t[7], wrong)                                                      # 名前が 作業用 でない
        self._loc(t[8], "\\\\server\\share\\" + schemas.WORK_DIR)                   # ネットワーク上
        self._write(os.path.join(work, t[9] + ".json"), {})
        self._loc(t[9], work, id=t[10])                                             # id が違う
        self._loc(t[11], "relative/" + schemas.WORK_DIR)                            # 絶対パスでない
        self._write(os.path.join(self.tx, "readme.json"), {})                       # 文書でない名前
        self._write(os.path.join(self.tx, "XYZ.loc.json"), {})
        want_tids = [t[k] for k in (0, 1, 2, 4, 6)]   # 置いた先に文書が無い t3 は数えない・根に文書がある t4・t6 は根の物
        with self.assertLogs("tx", "WARNING"):   # 使えない索引の 1 行(同じ物は 1 回だけ)
            for data_dir in (None, os.path.dirname(self.tx)):
                self.assertEqual(docloc.iter_tids(data_dir), want_tids)
            got = txindex.doc_paths(self.tx)
        want = {n: os.path.join(self.tx, n) for n in os.listdir(self.tx)}
        for k in (1, 2):   # 使える索引は置き場(t2 は根にも古い文書があるが置き場が先)
            want[t[k] + ".json"] = os.path.join(os.path.normpath(work), t[k] + ".json")
        self.assertEqual(got, want)
        other = os.path.join(self.tmp, "other")   # 文書の根でないフォルダは索引を見ない
        os.makedirs(other)
        self._write(os.path.join(other, t[0] + ".json"), {})
        self.assertEqual(txindex.doc_paths(other), {t[0] + ".json": os.path.join(other, t[0] + ".json")})


if __name__ == "__main__":
    unittest.main()
