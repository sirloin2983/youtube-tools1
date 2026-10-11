# -*- coding: utf-8 -*-
"""配信中の候補の文字起こし(D-11 案 b)の設定との一致のテスト。入口 home の prefs と ② flow/live_tx・編集の tx_engines の値がそろっていること。

    py -3.10 -m unittest src/home/tests/test_live_tx_prefs.py

  - 値の一致: WCPP_VERSION・WCPP_EXE・WCPP_MODEL_FILES・置き場所が編集の tx_engines と同じ・prefs.LIVE_TX_MODELS が同じ名前
  - 入口のプロセスで tx_engines・numpy を import しない(live_tx を読んでも)
本体の試験は src/flow/tests/test_live_tx.py と src/pipeline/transcribe/tests/test_live_tx_worker.py。
"""
import os
import subprocess
import sys
import tempfile
import unittest

os.environ.setdefault("YTT_DATA_DIR", "inplace")   # テストは作業データを本物の置き場所(AppData など)に書かない(ytt.datadir)

TESTS = os.path.dirname(os.path.abspath(__file__))
HERE = os.path.dirname(TESTS)
SRC = os.path.dirname(HERE)
sys.path.insert(0, HERE)
if SRC not in sys.path:   # 共通部品 ytt(server.py と同じ)
    sys.path.append(SRC)
from flow import live_tx as TX  # noqa: E402
import prefs as P  # noqa: E402


def tx_engines():
    """編集の認識エンジンの口(値を比べるため。テストのプロセスだけで読む)"""
    from pipeline.transcribe import tx_engines as te
    return te


class ConstantsTest(unittest.TestCase):
    def test_same_values_as_editor(self):
        """入口は編集の部品を import しないので値を持っている。編集の tx_engines・ホームの設定と同じであること"""
        te = tx_engines()
        self.assertEqual(TX.WCPP_VERSION, te.WHISPER_CPP["version"])
        self.assertEqual(TX.WCPP_EXE, te.WCPP_EXE)
        self.assertEqual(TX.WCPP_MODEL_FILES, {k: v["file"] for k, v in te.WCPP_MODELS.items()})
        self.assertEqual(P.LIVE_TX_MODELS, tuple(te.WCPP_MODELS))
        self.assertEqual((P.DEFAULTS["live"]["liveTx"]["model"], TX.DEFAULT_MODEL), ("large-v3", "large-v3"))
        d = os.path.join(tempfile.gettempdir(), "ytt-livetx-x", "editor")

        class FakeLive:
            root = None

            def cfg(self):
                return {"liveTx": {"model": "large-v3"}}
        tx = TX.LiveTx(FakeLive())
        tx.data_dir = lambda: d
        p = tx.paths()
        self.assertEqual((os.path.dirname(p["exe"]), os.path.basename(p["exe"])), (te.wcpp_bin_dir(d), te.WCPP_EXE))
        self.assertEqual(p["model"], os.path.join(te.wcpp_model_dir(d), te.WCPP_MODELS["large-v3"]["file"]))

    def test_portal_does_not_import_editor_engines(self):
        """入口のプロセスで tx_engines・numpy を import しない(認識は子プロセス live_tx_worker.py の中だけ)"""
        code = ("import sys; sys.path[:0] = [%r, %r]; import live; import flow.live_tx, flow.live_detect; "
                "print(sorted(m for m in ('tx_engines', 'pipeline.transcribe.tx_engines', 'numpy', 'faster_whisper') if m in sys.modules))") % (HERE, SRC)
        p = subprocess.run([sys.executable, "-c", code], capture_output=True, timeout=60, env=dict(os.environ, YTT_DATA_DIR="inplace"))


if __name__ == "__main__":
    unittest.main()
