# -*- coding: utf-8 -*-
"""flow/runqueue.py(② の待ち行列と実行の糸。RS7-1 S5)のテスト。  py -3.10 -m unittest src/flow/tests/test_runqueue.py -v
home(入口の AutoRunner・案件・ホームの設定)を読まずに、素の Queue だけで submit → status → 完了・待ちの記録の保存と復元・中止を見る。
受付と hook を埋めた形(AutoRunner)の細かい動きは src/home/tests/test_autorun.py。
"""
import os
os.environ.setdefault("YTT_DATA_DIR", "inplace")   # 作業データは読み書きしない(記録は一時フォルダ)
import json
import shutil
import subprocess
import sys
import tempfile
import threading
import time
import unittest

SRC = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))   # tests -> flow -> src
sys.path.insert(0, SRC)
from flow import board as B, runqueue as Q, run as R, spec as SP, tools as T  # noqa: E402
from ytt import fsio  # noqa: E402

WAIT = 10.0


class Tools(T.HttpTools):
    """文字起こしだけの道具の真似(client なし)。gate が閉じている間はジョブが終わらない"""

    def __init__(self):
        super().__init__(None)
        self.started = []            # (動画, 束の transcribe.model, 束の post.llmModel)
        self.gate = threading.Event()
        self.gate.set()
        self.cancelled = []

    def docs(self):
        return []

    def transcribe_start(self, req, bundle=None):
        self.started.append((req["sourcePath"], bundle["transcribe"]["model"], bundle["post"]["llmModel"]))
        return "j%d" % len(self.started)

    def jobs(self):
        state = "done" if self.gate.is_set() else "running"
        return [{"id": "j%d" % i, "state": state, "tid": "t%d" % i, "progress": 0.5} for i in range(1, len(self.started) + 1)]

    def transcribe_cancel(self, jid):
        self.cancelled.append(jid)


def _until(cond, what):
    end = time.time() + WAIT
    while time.time() < end:
        if cond():
            return
        time.sleep(0.01)
    raise AssertionError("待っても %s になりませんでした" % what)


class Base(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.mkdtemp()
        self.addCleanup(shutil.rmtree, self.tmp, True)
        self.logs = os.path.join(self.tmp, "logs")
        os.makedirs(self.logs)
        self.media = []
        for i in range(3):
            p = os.path.join(self.tmp, "clip%d.mp4" % i)
            with open(p, "wb") as f:
                f.write(b"x")
            self.media.append(p)
        self.env = {"YTT_MACHINE_FILE": os.path.join(self.tmp, "nai", "machine.json")}   # この PC の設定は無い(既定)

    def queue(self, tools=None, env=None):
        q = Q.Queue(None, env=env or self.env, poll=0.01, tools=tools or Tools(), log_dir=self.logs)
        self.addCleanup(q.close)
        return q

    @staticmethod
    def env_of(path, eid="0123456789"):
        return {"id": eid, "kind": "file", "input": {"path": path, "title": "切り抜き"}, "legacy": {"mode": "file"}}   # 文字起こしだけ

    def active_file(self):
        with open(os.path.join(self.logs, Q.ACTIVE_FILE), encoding="utf-8") as f:
            return json.load(f)


class TestImport(unittest.TestCase):
    def test_imports_without_home(self):
        """home・human・manage を読まずに読める = 層の向き(画面なし・③ なしの ②)"""
        code = ("import sys; sys.path.insert(0, %r); import flow.runqueue as q; "
                "bad = [m for m in ('autorun', 'cases', 'prefs', 'deliver', 'delivery', 'friend_feedback', 'manage', 'human', 'home') "
                "if m in sys.modules]; print(bad); sys.exit(1 if bad else 0)") % SRC
        p = subprocess.run([sys.executable, "-c", code], capture_output=True, text=True, timeout=60)
        self.assertEqual(p.returncode, 0, p.stdout + p.stderr)


class TestSubmitLive(Base):
    def live_env(self):
        return {"id": "live000001", "kind": "live", "input": {"videoId": "abcdefghijk", "title": "配信"}}

    def test_without_hook(self):
        q = self.queue()
        with self.assertRaisesRegex(ValueError, "ライブの依頼を受ける係"):
            q.submit(self.live_env())
        self.assertEqual(q.status()["runs"], [])

    def test_to_hook(self):
        """kind live は Run を作らず hook へ(検査済みの封筒と束)。hook の返り値がそのまま返る。形の違いは hook の前に断る"""
        q = self.queue()
        seen = []
        q.set_live_hook(lambda env, spec: seen.append((env, spec)) or {"id": env["id"], "state": "recording"})
        out = q.submit(self.live_env(), {"adopt": {"sens": "low", "afterStream": False}})
        self.assertEqual(out, {"id": "live000001", "state": "recording"})
        env, spec = seen[0]
        self.assertEqual((env["kind"], env["input"]["videoId"]), ("live", "abcdefghijk"))
        self.assertEqual((spec["adopt"]["sens"], spec["adopt"]["afterStream"], spec["adopt"]["top"]), ("low", False, SP.DEFAULT_TOP))
        self.assertEqual(q.status()["runs"], [])
        for bad_env, bad_spec in (({"id": "x", "kind": "live", "input": {}}, None), (self.live_env(), {"adopt": {"sens": "x"}})):
            with self.assertRaises(ValueError):
                q.submit(bad_env, bad_spec)
        self.assertEqual(len(seen), 1)


class TestSubmit(Base):
    def test_submit_status_done(self):
        """封筒 + 束を積む → 糸が束のとおりに進める → status で 0 本に戻る・記録と history に 1 行"""
        tools = Tools()
        q = self.queue(tools, env=dict(self.env, YTT_MACHINE_LLM_MODEL="qwen3-4b"))
        pub = q.submit(self.env_of(self.media[0]), {"transcribe": {"model": "large-v3"}})
        self.assertEqual((pub["id"], pub["kind"], pub["sourcePath"]), ("0123456789", "file", self.media[0]))
        _until(lambda: q.status()["idle"], "待ち・実行中が 0")
        st = q.status()
        self.assertEqual((st["queued"], st["running"], st["done"], st["closed"]), (0, 0, 1, False))
        one = st["runs"][0]
        self.assertEqual((one["id"], one["kind"], one["state"], one["step"]), ("0123456789", "file", "done", None))
        self.assertEqual([s["key"] for s in one["steps"]], ["transcribe"])
        self.assertIsInstance(one["startedAt"], int)
        self.assertTrue(all(isinstance(s.get("finishedAt"), int) for s in one["steps"] if s["state"] != "wait"))
        # 受けた束 + この PC の設定(machine の llmModel)のまま流れた(build_spec は呼ばない)
        self.assertEqual(tools.started, [(self.media[0], "large-v3", "qwen3-4b")])
        hist = q.history()
        self.assertEqual((hist["total"], hist["runs"][0]["id"], hist["runs"][0]["state"]), (1, "0123456789", "done"))
        self.assertEqual(self.active_file()["runs"], [])   # 終わった実行は待ちの記録から外れる

    def test_submit_rejects(self):
        """封筒の形が違う・同じ入力が待ち・実行中・同じ id は理由つきの ValueError(積まない)"""
        tools = Tools()
        tools.gate.clear()
        q = self.queue(tools)
        with self.assertRaises(ValueError):
            q.submit({"id": "x", "kind": "nai", "input": {}})
        with self.assertRaises(ValueError):
            q.submit(self.env_of(self.media[0]), {"transcribe": {"engine": "nai"}})
        q.submit(self.env_of(self.media[0]))
        with self.assertRaisesRegex(ValueError, "すでに実行中・順番待ち"):
            q.submit(self.env_of(self.media[0], "abcdef0123"))
        with self.assertRaisesRegex(ValueError, "もう待ち・実行中"):
            q.submit(self.env_of(self.media[1]))
        self.assertEqual(len(q.status()["runs"]), 1)
        tools.gate.set()
        _until(lambda: q.status()["idle"], "待ち・実行中が 0")

    def test_submit_file_must_be_media(self):
        """動画ファイルの封筒は、実在する絶対パスで拡張子が動画・音声の物だけ(RS7-1 S4)"""
        q = self.queue()
        txt = os.path.join(self.tmp, "memo.txt")
        with open(txt, "wb") as f:
            f.write(b"x")
        for path, why in ((os.path.join(self.tmp, "nai.mp4"), "見つかりません"), ("clip0.mp4", "見つかりません"), (txt, "動画・音声")):
            with self.assertRaisesRegex(ValueError, why, msg=path):
                q.submit(self.env_of(path))
        self.assertEqual(q.status()["runs"], [])

    def test_people_head_is_streamer(self):
        """封筒に配信者が無ければ、束の hints.people の先頭を照らし合わせた名前(合わなければ決めない = 実行中に)。封筒にあれば封筒(RS7-1 S4)"""
        tools = Tools()
        tools.gate.clear()
        q = self.queue(tools)
        spec = {"hints": {"people": [{"name": "ぺこら"}, {"name": "ゲスト"}]}}
        q.submit(self.env_of(self.media[0]), spec)
        q.submit(self.env_of(self.media[1], "abcdef0123"), {"hints": {"people": [{"name": "だれでもない人"}]}})
        q.submit(dict(self.env_of(self.media[2], "fedcba9876"), legacy={"mode": "file", "streamer": ""}), spec)
        by = {r.id: r.streamer for r in q.runs}
        self.assertEqual(by, {"0123456789": "兎田ぺこら", "abcdef0123": None, "fedcba9876": ""})
        tools.gate.set()
        _until(lambda: q.status()["idle"], "待ち・実行中が 0")

    def test_accept_uses_accept_hook(self):
        """accept=True(ライブの書き出しの受け渡し。RS7-2 G2b)は束の hints.people の先頭を見ず、受付と同じ hook の _accept で決める(以前の start_file と同じ)"""
        tools = Tools()
        tools.gate.clear()
        q = self.queue(tools)
        seen = []
        q._accept = lambda run, convert=False: seen.append((run.id, run.spec is not None, convert))
        q.submit(self.env_of(self.media[0]), {"hints": {"people": [{"name": "ぺこら"}]}}, accept=True)
        self.assertEqual(seen, [("0123456789", True, False)])
        self.assertIsNone(q.runs[0].streamer)
        tools.gate.set()
        _until(lambda: q.status()["idle"], "待ち・実行中が 0")

    def test_without_spec_uses_build_spec_hook(self):
        """束を持たない実行(画面の欄から作った Run)は hook の build_spec(既定 = 束の既定 + この PC の設定)"""
        tools = Tools()
        q = self.queue(tools)
        with q.cv:
            out = q._push(R.Run(None, "t", "file", None, source_path=self.media[0]))
        _until(lambda: q.status()["idle"], "待ち・実行中が 0")
        self.assertEqual(tools.started, [(self.media[0], SP.DEFAULTS["transcribe"]["model"], SP.DEFAULTS["post"]["llmModel"])])
        self.assertEqual(q.status()["runs"][0]["id"], out["id"])


class TestRestore(Base):
    def test_close_keeps_and_next_queue_resumes(self):
        """終了(close)で止まった実行は待ちの記録(封筒 + 束)に残り、次の Queue が同じ id のまま、受けたときの束で続ける"""
        tools = Tools()
        tools.gate.clear()
        q = self.queue(tools)
        q.submit(self.env_of(self.media[0]), {"transcribe": {"model": "large-v3"}})
        q.submit(self.env_of(self.media[1], "abcdef0123"))
        _until(lambda: q.status()["running"] == 1 and tools.started, "実行中")
        st = q.status()
        self.assertEqual((st["queued"], st["running"], st["idle"], st["runs"][0]["step"]), (1, 1, False, "transcribe"))
        q.close()
        _until(lambda: not q.thread.is_alive(), "糸が止まる")
        saved = self.active_file()["runs"]
        self.assertEqual([r["id"] for r in saved], ["0123456789", "abcdef0123"])
        self.assertEqual(saved[0]["envelope"]["kind"], "file")
        self.assertEqual(saved[0]["spec"]["transcribe"]["model"], "large-v3")
        self.assertEqual(q.history()["total"], 0)   # 終了で止まった実行は「中止」と書かない

        tools2 = Tools()
        q2 = self.queue(tools2)
        _until(lambda: q2.status()["idle"], "戻した 2 本が済む")
        self.assertEqual([(r["id"], r["state"]) for r in q2.status()["runs"]], [("0123456789", "done"), ("abcdef0123", "done")])
        self.assertEqual([m for _p, m, _l in tools2.started], ["large-v3", SP.DEFAULTS["transcribe"]["model"]])

    def test_old_form_and_too_old(self):
        """古い形(欄だけ・束なし)の待ちの記録も戻す。RESTORE_MAX_AGE より前の物は戻さず記録に「中止」"""
        now = time.time()
        old = {"id": "0123456789", "mode": "file", "title": "古い形", "sourcePath": self.media[0], "created": now - 60,
               "steps": [{"key": "transcribe", "state": "wait", "detail": ""}]}
        stale = dict(old, id="abcdef0123", sourcePath=self.media[1], created=now - Q.RESTORE_MAX_AGE - 60)
        with open(os.path.join(self.logs, Q.ACTIVE_FILE), "w", encoding="utf-8") as f:
            json.dump({"v": Q.ACTIVE_VERSION, "runs": [{"id": "../x", "mode": "file"}, old, {"id": "abcdefabcd", "mode": "nope"}, stale, "壊れた"]}, f)   # 壊れた行・形の違う id・知らない mode は読み飛ばす(入口の試験から移した)
        tools = Tools()
        q = self.queue(tools)
        _until(lambda: q.status()["idle"], "戻した 1 本が済む")
        self.assertEqual([(r["id"], r["state"]) for r in q.status()["runs"]], [("0123456789", "done")])
        self.assertEqual([p for p, _m, _l in tools.started], [self.media[0]])
        states = {r["id"]: r["state"] for r in q.history()["runs"]}
        self.assertEqual(states, {"0123456789": "done", "abcdef0123": "cancelled"})

    def test_old_version_is_dropped(self):
        """版 1(RS7-1 S4 より前)・知らない版の待ちの記録は読まずに捨てる(知らせを 1 行。次に書くときは今の版の空)"""
        self.assertEqual(Q.ACTIVE_VERSION, 2)
        old = {"id": "0123456789", "mode": "file", "title": "版 1", "sourcePath": self.media[0], "created": time.time() - 60,
               "steps": [{"key": "transcribe", "state": "wait", "detail": ""}]}
        for ver in (1, 99):
            with open(os.path.join(self.logs, Q.ACTIVE_FILE), "w", encoding="utf-8") as f:
                json.dump({"v": ver, "runs": [old]}, f)
            logs, tools = [], Tools()
            q = Q.Queue(None, env=self.env, poll=0.01, tools=tools, log_dir=self.logs, log=logs.append)
            self.addCleanup(q.close)
            self.assertEqual(q.runs, [], ver)
            self.assertTrue(any("古い形(版 %d)" % ver in m for m in logs), logs)
            self.assertEqual(self.active_file(), {"v": Q.ACTIVE_VERSION, "runs": []})
            self.assertEqual(tools.started, [])


class TestCancel(Base):
    def test_cancel_queued_and_running(self):
        """待ちの中止はすぐ「中止」・実行中の中止は段が止まってから。どちらも待ちの記録から外れ、記録に残る"""
        tools = Tools()
        tools.gate.clear()
        q = self.queue(tools)
        q.submit(self.env_of(self.media[0]))
        q.submit(self.env_of(self.media[1], "abcdef0123"))
        _until(lambda: q.status()["running"] == 1, "実行中")
        self.assertEqual(q.cancel("abcdef0123")["state"], "cancelled")
        self.assertEqual([r["id"] for r in self.active_file()["runs"]], ["0123456789"])
        q.cancel("0123456789")
        _until(lambda: q.status()["idle"], "待ち・実行中が 0")
        self.assertEqual([r["state"] for r in q.status()["runs"]], ["cancelled", "cancelled"])
        self.assertEqual(self.active_file()["runs"], [])
        self.assertEqual(sorted(r["id"] for r in q.history()["runs"]), ["0123456789", "abcdef0123"])
        self.assertEqual(tools.cancelled, ["j1"])   # 実行中の段の仕事も取り消す
        with self.assertRaises(ValueError):
            q.cancel("ffffffffff")


class TestBoard(Base):
    """RS8 の ② の口 S3: attach_board で Run が掲示板(flow/board.py)に載る(引く形・頭 run)。取り消し・やり直しも掲示板の id で"""

    def board(self, q):
        b = B.Board()
        q.attach_board(b)
        return b

    @staticmethod
    def job_of(b, jid):
        return next(j for j in b.snapshot()["jobs"] if j["id"] == jid)

    def test_run_on_board(self):
        """待ち・実行中(器のジョブに親の印)→ 済み(progress 1・案件の根は結果の束から)。history の case で絞れる"""
        tools = Tools()
        tools.gate.clear()
        q = self.queue(tools)
        b = self.board(q)
        q.submit(self.env_of(self.media[0]))
        _until(lambda: q.runs[0].owned, "編集のジョブを待つ")
        j = self.job_of(b, "run:0123456789")
        self.assertEqual((j["kind"], j["state"], j["target"], j["canCancel"], j["canRetry"]),
                         ("run", "running", {"path": self.media[0]}, True, False))
        self.assertEqual([s["key"] for s in j["steps"]], ["transcribe"])
        self.assertIn(R.STEP_LABELS["transcribe"], j["phase"])
        self.assertEqual(b.upsert({"id": "tx:j1", "kind": "transcribe", "state": "running"})["parent"], "run:0123456789")   # 親子の印
        tools.gate.set()
        _until(lambda: q.status()["idle"], "待ち・実行中が 0")
        j = self.job_of(b, "run:0123456789")
        self.assertEqual((j["state"], j["progress"], j["canCancel"], j["canRetry"], j["finishedAt"] is not None), ("done", 1.0, False, False, True))
        run = q.runs[0]
        self.assertTrue(run.result_path, "動画のあるフォルダ = 案件の根に結果の束")
        self.assertEqual(j["case"], fsio.norm_path(self.tmp))
        self.assertEqual(b.cases()[fsio.norm_path(self.tmp)]["lastState"], "done")
        self.assertEqual([r["id"] for r in q.history(case=self.tmp)["runs"]], ["0123456789"])
        self.assertEqual(q.history(case=os.path.join(self.tmp, "nai"))["total"], 0)
        self.assertEqual(q.history(case="相対")["total"], 0)

    def test_cancel_and_retry(self):
        """掲示板の cancel は Queue.cancel・retry は同じ封筒(新しい id)+ 同じ束をもう一度 submit。できない物は Refused・無い id は NotFound"""
        tools = Tools()
        tools.gate.clear()
        q = self.queue(tools)
        b = self.board(q)
        q.submit(self.env_of(self.media[0]), {"transcribe": {"model": "large-v3"}})
        _until(lambda: q.status()["running"] == 1, "実行中")
        with self.assertRaises(B.Refused):   # 実行中はやり直せない
            b.retry("run:0123456789")
        out = b.cancel("run:0123456789")
        self.assertEqual((out["id"], out["canCancel"]), ("run:0123456789", False))   # 止める印 = もう止められない
        _until(lambda: q.status()["idle"], "待ち・実行中が 0")
        old = self.job_of(b, "run:0123456789")
        self.assertEqual((old["state"], old["canRetry"]), ("cancelled", True))
        new = b.retry("run:0123456789")
        self.assertNotEqual(new["id"], "run:0123456789")
        self.assertEqual((new["kind"], new["state"] in ("queued", "running"), new["target"]), ("run", True, {"path": self.media[0]}))
        again = next(r for r in q.runs if "run:" + r.id == new["id"])
        self.assertEqual(again.spec["transcribe"]["model"], "large-v3")   # 同じ束
        with self.assertRaisesRegex(B.Refused, "すでに実行中"):   # 同じ入力が待ち・実行中
            b.retry("run:0123456789")
        tools.gate.set()
        _until(lambda: q.status()["idle"], "待ち・実行中が 0")
        with self.assertRaises(B.Refused):   # 済んだ物は止められない・やり直せない
            b.cancel(new["id"])
        with self.assertRaises(B.Refused):
            b.retry(new["id"])
        with self.assertRaises(B.NotFound):
            b.cancel("run:ffffffffff")
        self.assertIsNone(q.board_cancel("0123456789"))
        with self.assertRaises(LookupError):
            q.board_retry("ffffffffff")

    def test_board_job_shape(self):
        """board_job は掲示板の形のまま(normalize を通る)。失敗は error・案件の根は結果の束のパスの形だけで決める"""
        run = R.Run("vid", "配信", "full", 3)
        run.state, run.error = "error", "止まりました"
        j = B.normalize(Q.board_job(run))
        self.assertEqual((j["state"], j["error"]["text"], j["canRetry"], j["target"]), ("error", "止まりました", True, {"videoId": "vid"}))
        self.assertFalse(B.normalize(Q.board_job(run, closed=True))["canRetry"])   # 終了の途中はやり直さない
        root = os.path.join(self.tmp, "案件")
        self.assertEqual(Q.result_case(os.path.join(root, "作業用", "runs", "0123456789.json")), root)
        for bad in (None, "x.json", os.path.join(root, "runs", "0123456789.json"), os.path.join(root, "作業用", "x", "0123456789.json")):
            self.assertIsNone(Q.result_case(bad), bad)


class TestStatusLive(Base):
    """RS7-2 G5a: status() の live 欄(録画・検出の数は外から足す hook)。idle は待ち・実行中が 0 かつ live の数がどれも 0 のときだけ真"""

    def test_without_hook_live_is_zero(self):
        st = self.queue().status()
        self.assertEqual((st["live"], st["idle"]), ({"recording": 0, "detecting": 0}, True))
        self.assertEqual(set(st) - {"live"}, {"queued", "running", "done", "idle", "closed", "runs"})   # 今までの欄はそのまま

    def test_recording_or_detecting_makes_not_idle(self):
        q = self.queue()
        now = {"recording": 1, "detecting": 0}
        q.set_status_hook(lambda: dict(now))
        st = q.status()
        self.assertEqual((st["live"], st["idle"], st["queued"], st["running"]), ({"recording": 1, "detecting": 0}, False, 0, 0))
        now.update(recording=0, detecting=2)
        self.assertFalse(q.status()["idle"])
        now.update(detecting=0, exporting=1)   # 足した数の欄も idle に効く
        st = q.status()
        self.assertEqual((st["live"]["exporting"], st["idle"]), (1, False))
        now.update(exporting=0)
        self.assertTrue(q.status()["idle"])
        q.set_status_hook(None)
        self.assertEqual(q.status()["live"], {"recording": 0, "detecting": 0})

    def test_running_run_and_idle_live_is_not_idle(self):
        tools = Tools()
        tools.gate.clear()
        q = self.queue(tools)
        q.set_status_hook(lambda: {"recording": 0, "detecting": 0})
        q.submit(self.env_of(self.media[0]))
        _until(lambda: q.status()["running"] == 1, "実行中")
        self.assertFalse(q.status()["idle"])
        tools.gate.set()
        _until(lambda: q.status()["idle"], "待ち・実行中が 0")

    def test_hook_failure_is_not_idle(self):
        """hook が失敗した・おかしな値 = 閉じない側(idle は偽)。おかしな値の欄は捨てる"""
        q = self.queue()

        def boom():
            raise OSError("録画元につながらない")
        q.set_status_hook(boom)
        st = q.status()
        self.assertEqual((st["live"]["recording"], st["live"]["detecting"], st["idle"]), (None, None, False))
        self.assertIn("OSError", st["live"]["error"])
        q.set_status_hook(lambda: {"recording": True, "detecting": -1, "note": "x", "exporting": 0})
        st = q.status()
        self.assertEqual((st["live"], st["idle"]), ({"recording": 0, "detecting": 0, "exporting": 0}, True))
        q.set_status_hook(lambda: {"recording": None})   # 数が分からない = 閉じない側
        self.assertFalse(q.status()["idle"])


if __name__ == "__main__":
    unittest.main()
