# -*- coding: utf-8 -*-
"""app/cli(② + ① で動くコマンド。役割で組み直す RS6 b-S1)のテスト。  py -3.10 -m unittest src/app/tests/test_cli.py -v

- 引数・束の検査(形が違えば終了コード 2・API キーを書いた束は断る)
- lock があって入口が動いていれば入口に頼む(HTTP は差し替え)・入口が応答しない / 別の実行が使っている = 4・URL で入口が無い = 3
- 入口が無ければ動画ファイルを LocalTools で 1 本(疑似のエンジン。疑似の差し込みはテストの側)。2 回目は文字起こしを飛ばす
- 終わるとき(Ctrl+C でも)認識ワーカーを止めて lock を返す
- CLI の流れで ③ 人(human)を読まない(別のプロセスで sys.modules を見る)
作業データは必ず一時フォルダ(--data-dir)。flow/placement(並行して作っている段)はテストの側の偽物に差し替える
"""
import os
os.environ.setdefault("YTT_DATA_DIR", "inplace")   # 作業データは読み書きしない(一時フォルダだけ)
import io
import json
import shutil
import subprocess
import sys
import tempfile
import threading
import unittest
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from unittest import mock

SRC = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))   # tests -> app -> src
sys.path.insert(0, SRC)
from app import cli  # noqa: E402
from pipeline.transcribe import backend, roster, worker_client  # noqa: E402
from ytt import workdata  # noqa: E402
from eval.fake import fake_asr  # noqa: E402  (疑似の認識。CLI は eval を読まないので、テストの側で差し込む)

HAS_FFMPEG = bool(shutil.which("ffmpeg"))


def _make_video(path, sec=6):
    subprocess.run(["ffmpeg", "-v", "error", "-y", "-f", "lavfi", "-i", "testsrc=size=160x284:rate=30:duration=%d" % sec,
                    "-f", "lavfi", "-i", "sine=frequency=440:duration=%d" % sec, "-c:v", "libx264", "-pix_fmt", "yuv420p", "-c:a", "aac",
                    "-shortest", path], check=True, timeout=120)


class FakePlacement:
    """flow/placement の偽物(lock_info・acquire・release・LockBusy・write_result)"""

    class LockBusy(Exception):
        def __init__(self, info):
            super().__init__(info)
            self.info = info

    def __init__(self, info=None, busy=None, result_dir=None):
        self.info, self.busy, self.result_dir = info, busy, result_dir
        self.acquired, self.released, self.roots = [], [], []

    def lock_info(self, data_root=None):
        self.roots.append(data_root)
        return self.info

    def acquire(self, port=None, data_root=None):
        if self.busy:
            raise self.LockBusy(self.busy)
        h = ("handle", len(self.acquired))
        self.acquired.append(h)
        return h

    def release(self, handle):
        self.released.append(handle)

    def write_result(self, run):
        path = os.path.join(self.result_dir, run.id + ".json")
        with open(path, "w", encoding="utf-8") as f:
            json.dump(run.public(), f)
        return path


class FakeWorker:
    def __init__(self):
        self.closed = 0

    def close(self):
        self.closed += 1


class Base(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.mkdtemp(prefix="ytt_cli_")
        self.addCleanup(shutil.rmtree, self.tmp, True)
        self.data = os.path.join(self.tmp, "data")
        # main は環境変数・作業データの場所・名簿の場所を入れ替える = テストの終わりに戻す
        p = mock.patch.dict(os.environ, {"YTT_RUNTIME_DIR": os.path.join(self.tmp, "runtime"), "TRANSCRIBE_FAKE_DELAY": "0"})
        p.start()
        self.addCleanup(p.stop)
        for name in ("ROOT", "DATA_DIR", "TX_DIR", "TMP_DIR", "EVAL_BASE", "SETTINGS", "FEEDBACK", "MARKER_DATA", "STUDIO_DATA"):
            p = mock.patch.object(workdata, name, getattr(workdata, name))
            p.start()
            self.addCleanup(p.stop)
        p = mock.patch.object(roster, "ROSTER", roster.ROSTER)
        p.start()
        self.addCleanup(p.stop)
        self.worker = FakeWorker()
        p = mock.patch.object(worker_client, "WORKER", self.worker)
        p.start()
        self.addCleanup(p.stop)
        p = mock.patch.object(cli.time, "sleep", lambda s: None)
        p.start()
        self.addCleanup(p.stop)
        self.pl = FakePlacement(result_dir=self.tmp)
        p = mock.patch.object(cli, "_placement", lambda: self.pl)
        p.start()
        self.addCleanup(p.stop)

    def main(self, *argv):
        out, err = io.StringIO(), io.StringIO()
        code = cli.main(list(argv) + ["--data-dir", self.data], stdout=out, stderr=err)
        text = out.getvalue()
        return code, (json.loads(text) if text.strip() else None), err.getvalue()

    def dummy(self, name="clip.mp4"):
        path = os.path.join(self.tmp, name)
        with open(path, "wb") as f:
            f.write(b"\0")
        return path

    def spec(self, obj):
        self.n_spec = getattr(self, "n_spec", 0) + 1
        path = os.path.join(self.tmp, "spec%d.json" % self.n_spec)
        with open(path, "w", encoding="utf-8") as f:
            json.dump(obj, f)
        return path


class TestArgs(Base):
    def test_classify(self):
        self.assertEqual(cli.classify_input(self.dummy()), ("file", os.path.join(self.tmp, "clip.mp4")))
        self.assertEqual(cli.classify_input("https://www.youtube.com/watch?v=abcdefghijk"), ("url", "abcdefghijk"))
        self.assertEqual(cli.classify_input("https://youtu.be/abcdefghijk"), ("url", "abcdefghijk"))
        for bad in (self.dummy("memo.txt"), os.path.join(self.tmp, "none.mp4"), "https://example.com/x"):
            with self.assertRaises(cli.UsageError):
                cli.classify_input(bad)

    def test_usage_errors_exit_2(self):
        video = self.dummy()
        cases = [([os.path.join(self.tmp, "none.mp4")], "見つかりません"),
                 ([video, "--spec", os.path.join(self.tmp, "no.json")], "読めません"),
                 ([video, "--spec", self.spec({"pack": {"sise": "1080x1920"}})], "知らない項目"),
                 ([video, "--spec", self.spec({"pack": {"volume": 999}})], "pack.volume"),
                 (["https://youtu.be/abcdefghijk", "--from", "pack"], "analyze か export")]
        for argv, word in cases:
            code, res, err = self.main(*argv)
            self.assertEqual((code, res), (2, None), argv)
            self.assertIn(word, err, argv)
        self.assertEqual(self.pl.roots, [], "形が違えば lock も見ない")
        with self.assertRaises(SystemExit) as cm:
            cli.parse_args([video, "--from", "deliver"])
        self.assertEqual(cm.exception.code, 2)

    def test_api_key_refused(self):
        for given in ({"post": {"apiKey": "AIza-xxx"}}, {"youtubeApiKey": "x"}, {"hints": {"people": [{"name": "a", "token": "t"}]}}):
            code, res, err = self.main(self.dummy(), "--spec", self.spec(given))
            self.assertEqual(code, 2, given)
            self.assertIn("YOUTUBE_API_KEY", err)

    def test_load_spec_overlays_run(self):
        b = cli.load_spec(self.spec({"pack": {"volume": 50}}), "pack", True)
        self.assertEqual((b["pack"]["volume"], b["run"]["from"], b["run"]["force"]), (50, "pack", True))
        self.assertEqual(cli.load_spec(None)["run"], {"from": None, "force": False, "repack": False, "pinned": []})   # repack・pinned は RS7-1 S3


class TestLearningPlaces(Base):
    """RS7-1 F-k: CLI の学習データ・スタジオの文脈は作業データの根から読む(リポジトリの中の src/studio は読まない)"""

    def test_studio_data_under_data_root(self):
        with mock.patch.dict(os.environ):
            os.environ.pop("TRANSCRIBE_STUDIO_DATA", None)
            cli.use_data_dir(self.data)
            self.assertEqual(workdata.STUDIO_DATA, os.path.join(os.path.abspath(self.data), "studio", "data.json"))
            self.assertIsNone(cli.learning_dir())     # 既定(作業データの根)= 今の置き場所のまま
            self.assertEqual(workdata.SETTINGS, os.path.join(workdata.DATA_DIR, "settings.json"))

    def test_learning_dir_from_machine(self):
        other = os.path.join(self.tmp, "learn")
        with mock.patch.dict(os.environ, {"YTT_MACHINE_LEARNING_DIR": other}):
            cli.use_data_dir(self.data)
            ld = cli.learning_dir()
            self.assertEqual(ld, os.path.join(os.path.abspath(other), "transcribe"))
            self.assertEqual((workdata.SETTINGS, workdata.FEEDBACK), (os.path.join(ld, "settings.json"), os.path.join(ld, "learn-feedback.json")))
            self.assertEqual(workdata.TX_DIR, os.path.join(os.path.abspath(self.data), "transcribe", "transcripts"))   # 出力の文書はそのまま作業データへ

    def test_learning_reader_skips_without_docs(self):
        """学習のもとの文書が無ければ ③ を読まずに「学習なし」(友人の PC の ② + ① だけの形)"""
        empty = os.path.join(self.tmp, "ld")
        os.makedirs(os.path.join(empty, "transcripts"))
        lr = cli.Learning(empty)
        self.assertEqual((lr.glossary(["あ"]), lr.learned()), ([], None))
        self.assertEqual(cli.Learning(os.path.join(self.tmp, "none")).glossary([]), [])


class FakePortal:
    """入口の HTTP の偽物: 頼まれたことを並べ、GET /api/autorun は 1 回目は実行中・2 回目から済み。
    old = submit の無い古い入口(POST /api/flow/submit が 404)。refuse = submit を 400 で断る理由"""

    def __init__(self, final="done", interrupt=False, old=False, refuse=None):
        self.port, self.calls, self.polls, self.final, self.interrupt = 8700, [], 0, final, interrupt
        self.old, self.refuse = old, refuse

    def call(self, method, path, body=None):
        self.calls.append((method, path, body))
        if path == "/api/flow/submit":
            if self.old:
                return 404, {"error": "not_found", "message": "その操作はありません"}
            if self.refuse:
                return 400, {"error": "bad_request", "message": self.refuse}
            return 200, {"run": {"id": "r1"}}
        if path == "/api/autorun":
            self.polls += 1
            if self.interrupt:
                raise KeyboardInterrupt()
            state = "running" if self.polls == 1 else self.final
            step = {"key": "pack", "label": "パック", "state": "run" if state == "running" else "done", "detail": ""}
            return 200, {"runs": [{"id": "other", "state": "running"}, {"id": "r1", "state": state, "steps": [step], "docs": ["0123456789ab"]}]}
        return 200, {}

    def ok(self, method, path, body=None):
        return self.call(method, path, body)[1]

    def posts(self):
        return [(p, b) for m, p, b in self.calls if m == "POST"]


class TestPortal(Base):
    def use_portal(self, portal, info=None):
        self.pl.info = info or {"pid": 4321, "port": 8700, "at": 0}
        p = mock.patch.object(cli, "portal_at", lambda port: portal if port == 8700 else None)
        p.start()
        self.addCleanup(p.stop)

    def submitted(self, portal):
        """入口に submit した 1 回 -> (封筒, 束)。submit のほかに頼んだ物は無い(取り消しは除く)"""
        posts = [(p, b) for p, b in portal.posts() if p != "/api/autorun/cancel"]
        self.assertEqual([p for p, _b in posts], ["/api/flow/submit"])
        body = posts[0][1]
        from flow import envelope as E, spec as SP
        E.check(body["envelope"])   # ② の封筒の形
        SP.validate(body["spec"])   # 束は丸ごと(検査を通る形)
        return body["envelope"], body["spec"]

    def test_url_submit(self):
        """RS7-1 S4: URL は封筒 + 束の submit 1 回(解析から = full・まだスタジオに無い配信の印 fresh)。--spec・--force も入口で効く"""
        portal = FakePortal()
        self.use_portal(portal)
        code, res, err = self.main("https://www.youtube.com/watch?v=abcdefghijk", "--spec", self.spec({"adopt": {"top": 2}}), "--title", "題", "--force")
        self.assertEqual(code, 0, err)
        env, spec = self.submitted(portal)
        self.assertEqual((env["kind"], env["input"], env["legacy"]),
                         ("url", {"videoId": "abcdefghijk", "title": "題", "fresh": {"title": "題", "channel": ""}}, {"mode": "full"}))
        self.assertRegex(env["id"], r"^[0-9a-f]{10}$")
        self.assertEqual((spec["adopt"]["top"], spec["run"]["force"]), (2, True))
        self.assertEqual((res["via"], res["state"], res["id"]), ("portal", "done", "r1"))
        self.assertEqual(self.pl.acquired, [], "入口が動いていれば lock は取らない")
        self.assertIn("[パック]", err)
        self.assertEqual(self.worker.closed, 0)

    def test_url_from_export_submit_and_failure(self):
        portal = FakePortal(final="error")
        self.use_portal(portal)
        code, res, err = self.main("abcdefghijk", "--from", "export", "--force")
        self.assertEqual(code, 1)
        env, spec = self.submitted(portal)
        self.assertEqual((env["input"], env["legacy"], spec["run"]["from"], spec["run"]["force"]),
                         ({"videoId": "abcdefghijk", "title": ""}, {"mode": "adopted"}, "export", True))

    def test_file_submit(self):
        """動画ファイルは kind file の submit 1 回(文字起こし → パック。--from pack・--force は束の run で入口に渡る)"""
        portal = FakePortal()
        self.use_portal(portal)
        video = self.dummy()
        code, res, err = self.main(video, "--spec", self.spec({"transcribe": {"model": "large-v3"}}), "--from", "pack", "--force")
        self.assertEqual(code, 0, err)
        env, spec = self.submitted(portal)
        self.assertEqual((env["kind"], env["input"]["path"], env["legacy"]["mode"]), ("file", video, "file_auto"))
        self.assertEqual((spec["transcribe"]["model"], spec["run"]["from"], spec["run"]["force"]), ("large-v3", "pack", True))

    def test_submit_refused(self):
        portal = FakePortal(refuse="同じ入力がすでに実行中・順番待ちです")
        self.use_portal(portal)
        code, res, err = self.main(self.dummy())
        self.assertEqual((code, res["state"]), (1, "error"))
        self.assertIn("すでに実行中", err)

    def test_old_portal_fails(self):
        """submit の無い古い入口(404)には頼まない = 起動し直しを促して終了コード 1(2 段で頼む今までの形は消した)"""
        for target in ("https://www.youtube.com/watch?v=abcdefghijk", self.dummy()):
            portal = FakePortal(old=True)
            self.use_portal(portal)
            code, res, err = self.main(target)
            self.assertEqual((code, res["state"]), (1, "error"), target)
            self.assertIn("start.bat", res["error"])
            self.assertEqual([p for p, _b in portal.posts()], ["/api/flow/submit"])
            self.assertEqual((self.pl.acquired, portal.polls), ([], 0))

    def test_ctrl_c_cancels_portal_run(self):
        portal = FakePortal(interrupt=True)
        self.use_portal(portal)
        code, res, err = self.main("abcdefghijk")
        self.assertEqual(code, 130)
        self.assertEqual(portal.posts()[-1], ("/api/autorun/cancel", {"runId": "r1"}))
        self.assertEqual(res["state"], "cancelled")

    def test_lock_without_portal(self):
        """lock に port があるのに入口が応答しない・port の無い lock(別の CLI)= 4。動画ファイルでも自分では動かさない"""
        self.use_portal(FakePortal(), {"pid": 1, "port": 8799})
        code, res, err = self.main(self.dummy())
        self.assertEqual((code, res["state"]), (4, "error"))
        self.assertIn("応答しません", err)
        self.pl.info = {"pid": 77, "port": None}
        code, res, err = self.main(self.dummy())
        self.assertEqual(code, 4)
        self.assertIn("pid 77", err)
        self.assertEqual(self.pl.acquired, [])

    def test_url_without_portal_exit_3(self):
        code, res, err = self.main("https://youtu.be/abcdefghijk")
        self.assertEqual(code, 3)
        self.assertIn("start.bat", res["error"])
        self.assertEqual(self.pl.acquired, [])


class _Handler(BaseHTTPRequestHandler):
    seen = []

    def log_message(self, *a):
        pass

    def _send(self, code, body, ctype="application/json"):
        self.send_response(code)
        self.send_header("Content-Type", ctype)
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def do_GET(self):
        self.seen.append(("GET", self.path, self.headers.get("X-YTT-Token"), self.headers.get("Host")))
        if self.path == "/":
            return self._send(200, b'<html><head><meta name="ytt-token" content="tok_123"></head></html>', "text/html")
        return self._send(200, b'{"runs": []}')

    def do_POST(self):
        n = int(self.headers.get("Content-Length") or 0)
        body = json.loads(self.rfile.read(n).decode("utf-8"))
        self.seen.append(("POST", self.path, self.headers.get("X-YTT-Token"), body))
        if self.headers.get("X-YTT-Token") != "tok_123":
            return self._send(403, b'{"message": "bad token"}')
        return self._send(200, b'{"runs": [{"id": "r9"}]}')


class TestPortalHttp(unittest.TestCase):
    def test_token_from_page(self):
        srv = ThreadingHTTPServer(("127.0.0.1", 0), _Handler)
        threading.Thread(target=srv.serve_forever, daemon=True).start()
        self.addCleanup(srv.server_close)
        self.addCleanup(srv.shutdown)
        p = cli.Portal(srv.server_address[1], timeout=5)
        self.assertEqual(p.ok("GET", "/api/autorun"), {"runs": []})
        self.assertEqual(p.ok("POST", "/api/flow/submit", {"items": []}), {"runs": [{"id": "r9"}]})
        get_api = [s for s in _Handler.seen if s[:2] == ("GET", "/api/autorun")][0]
        self.assertIsNone(get_api[2], "GET には合言葉を付けない")
        self.assertEqual(get_api[3], "127.0.0.1:%d" % srv.server_address[1])
        self.assertEqual(_Handler.seen[-1], ("POST", "/api/flow/submit", "tok_123", {"items": []}))
        with self.assertRaises(cli.PortalError):
            cli.Portal(1, timeout=1).ok("GET", "/api/autorun")   # つながらない


class TestLocalLifecycle(Base):
    """入口なし: lock を取る・終わったら(Ctrl+C・失敗でも)ワーカーを止めて lock を返す"""

    def test_interrupt_cleans_up(self):
        with mock.patch.object(cli._run, "run", side_effect=KeyboardInterrupt):
            code, res, err = self.main(self.dummy())
        self.assertEqual((code, res["state"], res["via"]), (130, "cancelled", "local"))
        self.assertEqual((len(self.pl.acquired), self.pl.released, self.worker.closed), (1, self.pl.acquired, 1))

    def test_step_error_cleans_up(self):
        with mock.patch.object(cli._run, "run", side_effect=cli._run.StepError("だめ")):
            code, res, err = self.main(self.dummy())
        self.assertEqual((code, res["state"], res["error"]), (1, "error", "だめ"))
        self.assertTrue(os.path.isfile(res["resultFile"]))
        self.assertEqual((self.pl.released, self.worker.closed), (self.pl.acquired, 1))

    def test_lock_busy(self):
        self.pl.busy = {"pid": 99}
        code, res, err = self.main(self.dummy())
        self.assertEqual(code, 4)
        self.assertEqual(self.worker.closed, 0)

    def test_from_pack_without_doc(self):
        code, res, err = self.main(self.dummy(), "--from", "pack")
        self.assertEqual(code, 1)
        self.assertIn("文書がありません", res["error"])
        self.assertEqual((self.pl.released, self.worker.closed), (self.pl.acquired, 1))


@unittest.skipUnless(HAS_FFMPEG, "ffmpeg が無い")
class TestLocalRun(Base):
    def setUp(self):
        super().setUp()
        saved = backend._selector[0]
        backend.set_selector(lambda: fake_asr.FAKE)
        self.addCleanup(backend.set_selector, saved)
        self.video = os.path.join(self.tmp, "clip", "切り抜き.mp4")
        os.makedirs(os.path.dirname(self.video))
        _make_video(self.video)

    def test_file_to_pack(self):
        spec = self.spec({"post": {"autoLlm": False}, "pack": {"volume": 100}})
        out = os.path.join(self.tmp, "result.json")
        code, res, err = self.main(self.video, "--spec", spec, "--out", out)
        self.assertEqual(code, 0, err)
        self.assertEqual([(s["key"], s["state"]) for s in res["steps"]], [("transcribe", "done"), ("pack", "done")], res["steps"])
        self.assertEqual((res["via"], res["state"]), ("local", "done"))
        self.assertEqual(res["dataRoot"], os.path.abspath(self.data))
        tx_dir = os.path.join(self.data, "transcribe", "transcripts")
        self.assertEqual(res["artifacts"]["docs"], [os.path.join(tx_dir, res["docId"] + ".json")])
        self.assertEqual(len(res["artifacts"]["packs"]), 1)
        self.assertTrue(any(k.endswith(".transcribe.key.json") for k in res["artifacts"]["keys"]), res["artifacts"])
        self.assertTrue(os.path.isfile(res["resultFile"]))
        with open(out, encoding="utf-8") as f:
            self.assertEqual(json.load(f)["id"], res["id"])
        self.assertIn("[文字起こし]", err)
        self.assertEqual((self.pl.released, self.worker.closed), (self.pl.acquired, 1))
        # 2 回目: 文字起こし済み(文書を見つける)= 飛ばす・同じ名前のパックがある = 上書きしない
        code, res2, err = self.main(self.video, "--spec", spec)
        self.assertEqual(code, 0, err)
        self.assertEqual([(s["key"], s["state"]) for s in res2["steps"]], [("transcribe", "skip"), ("pack", "skip")], res2["steps"])
        self.assertEqual(res2["docId"], res["docId"])
        # --from pack --force: その文書でパックだけを作り直す
        code, res3, err = self.main(self.video, "--spec", spec, "--from", "pack", "--force")
        self.assertEqual(code, 0, err)
        self.assertEqual([(s["key"], s["state"]) for s in res3["steps"]], [("transcribe", "skip"), ("pack", "done")], res3["steps"])


DRIVER = r"""
import json, os, sys, types
src, video, data = sys.argv[1:4]
sys.path.insert(0, src)
from pipeline.transcribe import backend
from eval.fake import fake_asr
backend.set_selector(lambda: fake_asr.FAKE)
before = sorted(k for k in sys.modules if k.split(".")[0] == "human")
from app import cli
code = cli.main([video, "--data-dir", data], stdout=open(os.devnull, "w", encoding="utf-8"))
print(json.dumps({"code": code, "before": before, "human": sorted(k for k in sys.modules if k.split(".")[0] == "human")}))
"""


@unittest.skipUnless(HAS_FFMPEG, "ffmpeg が無い")
class TestNoHumanLayer(unittest.TestCase):
    def test_local_run_does_not_import_human(self):
        """友人に渡す ② + ① だけで動く: 入口なしの 1 本の間に ③ 人(human)の部品を 1 つも読まない(別のプロセスで見る)"""
        tmp = tempfile.mkdtemp(prefix="ytt_cli_iso_")
        self.addCleanup(shutil.rmtree, tmp, True)
        video = os.path.join(tmp, "v.mp4")
        _make_video(video, 3)
        env = dict(os.environ, TRANSCRIBE_FAKE_DELAY="0", YTT_RUNTIME_DIR=os.path.join(tmp, "runtime"))
        p = subprocess.run([sys.executable, "-c", DRIVER, SRC, video, os.path.join(tmp, "data")], capture_output=True, env=env, timeout=300)
        self.assertEqual(p.returncode, 0, p.stderr.decode("utf-8", "replace"))
        res = json.loads(p.stdout.decode("utf-8").strip().splitlines()[-1])
        self.assertEqual((res["code"], res["before"], res["human"]), (0, [], []), p.stderr.decode("utf-8", "replace")[-2000:])


if __name__ == "__main__":
    unittest.main()
