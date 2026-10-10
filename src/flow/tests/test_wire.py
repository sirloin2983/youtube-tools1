# -*- coding: utf-8 -*-
"""flow/wire(② 文字起こしの配線。役割で組み直す RS6 a-5b)の最小のテスト。編集の serve を読まず、③⑤ の物なしで install を呼ぶ。

    py -3.10 -m unittest src/flow/tests/test_wire.py -v

- ③ なし(引数なし)で呼べる・二度呼んでも壊れない
- bodies に渡した種類だけ登録する(優先度・同時に入れない組・文書の id・やり直しは flow/wire の表どおり)・知らない種類は KeyError
- 本物と疑似の選び方(backend_name() が "fake" のときだけ疑似)・辞書の版の材料の口・疑似の認識ワーカーの部品の名前
"""
import os
os.environ.setdefault("YTT_DATA_DIR", "inplace")   # 作業データは読み書きしない。ほかのテストとそろえる
import sys
import unittest
from unittest import mock

SRC = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))   # tests -> flow -> src
sys.path.insert(0, SRC)
from flow import jobs, wire  # noqa: E402
from pipeline.transcribe import backend, records, recognize, roster, worker_client  # noqa: E402


class TestInstall(unittest.TestCase):
    def setUp(self):
        # 全体の表・口を、このテストが終わったら元に戻す
        for obj, name in ((jobs, "JOB_RUNNERS"), (jobs, "JOB_PRIORITY"), (jobs, "EXCLUSIVE"), (jobs, "_conf"), (backend, "_selector"),
                          (records, "_dict_inputs"), (recognize, "_head_stripper")):
            saved = getattr(obj, name)
            copy = saved.copy()
            self.addCleanup(lambda saved=saved, copy=copy: (saved.clear(), saved.update(copy)) if isinstance(saved, dict) else saved.__setitem__(slice(None), copy))
        for obj, name in ((jobs, "TID_KINDS"), (jobs, "RETRY_KINDS"), (worker_client, "WORKER_LOG"), (worker_client, "FAKES_MODULE"), (roster, "ROSTER")):
            p = mock.patch.object(obj, name, os.path.join(os.devnull, "none.json") if name == "ROSTER" else (set(jobs.TID_KINDS) if name == "TID_KINDS" else getattr(obj, name)))   # 名簿は無いものとして・TID_KINDS は写しに足す
            p.start()
            self.addCleanup(p.stop)

    def test_without_human_layer_and_twice(self):
        backend._selector[0] = lambda: backend.REAL   # 同じプロセスで先に読んだ serve の選び方を持ち越さない(後片付けで元に戻る)
        wire.install()
        wire.install()
        self.assertTrue(callable(backend.select) and backend.select() is backend.REAL)
        self.assertEqual(records.dict_version({"glossary": ["x"]}).get("glossary") is not None, True)

    def test_registers_only_given_kinds(self):
        jobs.JOB_RUNNERS.clear()   # 同じプロセスで先に読んだ serve の登録を持ち越さない(後片付けで元に戻る)
        wire.install(bodies={"diarize": lambda job: "d", "alt": lambda job: "a"})
        self.assertEqual(jobs.JOB_RUNNERS["diarize"](None), "d")
        self.assertEqual((jobs.JOB_PRIORITY["diarize"], jobs.JOB_PRIORITY["alt"]), (0, 2))
        self.assertEqual(jobs.EXCLUSIVE["diarize"], wire.DOC_LOCK)
        self.assertIn("diarize", jobs.TID_KINDS)
        wire.install(bodies={"transcribe": lambda job: "t"})
        self.assertIn("transcribe", jobs.RETRY_KINDS)
        self.assertNotIn("redo", jobs.JOB_RUNNERS)
        with self.assertRaises(KeyError):
            wire.install(bodies={"nope": lambda job: None})

    def test_backend_selector_decides_each_call(self):
        fake = backend.Backend()
        name = ["real"]
        wire.install(backend_name=lambda: name[0], fake_backend=fake)
        self.assertIs(backend.select(), backend.REAL)
        name[0] = "fake"
        self.assertIs(backend.select(), fake)

    def test_dict_learned_and_fake_worker_module(self):
        wire.install(dict_learned=lambda: "L", fake_worker_module="x.y")
        self.assertEqual(records.dict_version({"autoLearned": True})["learned"], records.short_hash("L"))
        self.assertEqual(worker_client.FAKES_MODULE, "x.y")


if __name__ == "__main__":
    unittest.main()
