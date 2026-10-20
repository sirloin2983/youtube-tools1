# -*- coding: utf-8 -*-
"""flow/runqueue.py(② の待ち行列と実行の糸。RS7-1 S5)のテスト。  py -3.12 -m unittest tests/flow/test_runqueue.py -v
home(入口の AutoRunner・案件・ホームの設定)を読まずに、素の Queue だけで submit → status → 完了・待ちの記録の保存と復元・中止を見る。
受付と hook を埋めた形(AutoRunner)の細かい動きは tests/app/test_autorun.py。
"""
import os
os.environ.setdefault("YTT_DATA_DIR", "inplace")   # 作業データは読み書きしない(記録は一時フォルダ)
import json
import sys
import threading
import time
import types
import unittest
from unittest import mock

SRC = os.path.join(os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))), "src")   # tests -> flow -> src
sys.path.insert(0, SRC)
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))   # tests/(testkit)
import testkit  # noqa: E402
from flow import board as B, runqueue as Q, run as R, spec as SP, tools as T  # noqa: E402
from ytt import fsio  # noqa: E402
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))   # 共有の部品 _runfields(Run の欄の形 → 封筒 + 束。RV A2)
import _runfields as RF  # noqa: E402

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
        self.tmp = testkit.tempdir(self)
        self.logs = os.path.join(self.tmp, "logs")
        os.makedirs(self.logs)
        self.media = []
        for i in range(3):
            p = os.path.join(self.tmp, "clip%d.mp4" % i)
            testkit.write_text(p, "x")
            self.media.append(p)
        self.env = {"YTT_MACHINE_FILE": os.path.join(self.tmp, "nai", "machine.json")}   # この PC の設定は無い(既定)

    def queue(self, tools=None, env=None):
        q = Q.Queue(None, env=env or self.env, poll=0.01, tools=tools or Tools(), log_dir=self.logs)
        self.addCleanup(q.close)
        return q

    @staticmethod
    def env_of(path, eid="0123456789"):
        return {"id": eid, "kind": "file", "input": {"path": path, "title": "切り抜き"}, "specVersion": 2}

    @staticmethod
    def sub(q, env, spec=None):
        """文字起こしだけ(束の run.upto transcribe)で submit"""
        spec = dict(spec or {})
        spec["run"] = dict(spec.get("run") or {}, upto="transcribe")
        return q.submit(env, spec)

    def active_file(self):
        with open(os.path.join(self.logs, Q.ACTIVE_FILE), encoding="utf-8") as f:
            return json.load(f)


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
        pub = self.sub(q, self.env_of(self.media[0]), {"transcribe": {"model": "large-v3"}})
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

    def test_learning_stamp_and_finished_hook(self):
        """F1 F6a: 学習の読み手があれば束の post.learning.version に版が入る・終わったら finished_hook(run)(失敗してもログだけ)"""
        seen = []

        class Tools2(Tools):
            def transcribe_start(self, req, bundle=None):
                seen.append(bundle["post"]["learning"]["version"])
                return super().transcribe_start(req, bundle)
        q = self.queue(Tools2())
        q.learning = mock.Mock(version="20261011-120000-abcdef12")
        done = []

        def hook(run):
            done.append((run.id, run.state))
            raise RuntimeError("壊れた hook")
        q.set_finished_hook(hook)
        self.sub(q, self.env_of(self.media[0]))
        _until(lambda: q.status()["idle"] and done, "終わったあとの hook")
        self.assertEqual(seen, ["20261011-120000-abcdef12"])
        self.assertEqual(done, [("0123456789", "done")])
        self.sub(q, self.env_of(self.media[1], eid="0123456780"), {"post": {"learning": {"version": "given"}}})   # 束に版があればそのまま
        _until(lambda: len(done) == 2, "2 本目")
        self.assertEqual(seen[-1], "given")

    def test_submit_rejects(self):
        """封筒の形が違う・同じ入力が待ち・実行中・同じ id は理由つきの ValueError(積まない)"""
        tools = Tools()
        tools.gate.clear()
        q = self.queue(tools)
        with self.assertRaises(ValueError):
            q.submit({"id": "x", "kind": "nai", "input": {}})
        with self.assertRaises(ValueError):
            self.sub(q, self.env_of(self.media[0]), {"transcribe": {"engine": "nai"}})
        self.sub(q, self.env_of(self.media[0]))
        with self.assertRaisesRegex(ValueError, "すでに実行中・順番待ち"):
            self.sub(q, self.env_of(self.media[0], "abcdef0123"))
        with self.assertRaisesRegex(ValueError, "もう待ち・実行中"):
            self.sub(q, self.env_of(self.media[1]))
        self.assertEqual(len(q.status()["runs"]), 1)
        tools.gate.set()
        _until(lambda: q.status()["idle"], "待ち・実行中が 0")

    def test_closed_rejects_submit_and_enqueue(self):
        """終了(close)のあとの submit と _enqueue は理由つきの ValueError(待ちに積まず、待ちの記録も作らない)"""
        q = self.queue()
        q.close()
        with self.assertRaisesRegex(ValueError, "終了しているところです"):
            self.sub(q, self.env_of(self.media[0]))
        with self.assertRaisesRegex(ValueError, "終了しているところです"):
            q._enqueue([1], lambda it, active: {"id": "x", "title": "", "reason": "x"})
        self.assertEqual(q.status()["runs"], [])
        self.assertFalse(os.path.exists(os.path.join(self.logs, Q.ACTIVE_FILE)))

    def test_submit_file_must_be_media(self):
        """動画ファイルの封筒は、実在する絶対パスで拡張子が動画・音声の物だけ(RS7-1 S4)"""
        q = self.queue()
        txt = os.path.join(self.tmp, "memo.txt")
        testkit.write_text(txt, "x")
        for path, why in ((os.path.join(self.tmp, "nai.mp4"), "見つかりません"), ("clip0.mp4", "見つかりません"), (txt, "動画・音声")):
            with self.assertRaisesRegex(ValueError, why, msg=path):
                self.sub(q, self.env_of(path))
        self.assertEqual(q.status()["runs"], [])

    def test_people_head_is_streamer(self):
        """封筒に配信者が無ければ、束の hints.people の先頭を照らし合わせた名前(合わなければ決めない = 実行中に)。封筒にあれば封筒(RS7-1 S4)"""
        tools = Tools()
        tools.gate.clear()
        q = self.queue(tools)
        spec = {"hints": {"people": [{"name": "ぺこら"}, {"name": "ゲスト"}]}}
        self.sub(q, self.env_of(self.media[0]), spec)
        self.sub(q, self.env_of(self.media[1], "abcdef0123"), {"hints": {"people": [{"name": "だれでもない人"}]}})
        self.sub(q, self.env_of(self.media[2], "fedcba9876"), dict(spec, hints=dict(spec["hints"], streamer="")))
        by = {r.id: r.streamer for r in q.runs}
        self.assertEqual(by, {"0123456789": "兎田ぺこら", "abcdef0123": None, "fedcba9876": ""})
        tools.gate.set()
        _until(lambda: q.status()["idle"], "待ち・実行中が 0")

    def test_without_spec_uses_build_spec_hook(self):
        """束を持たない実行(画面の欄から作った Run)は hook の build_spec(既定 = 束の既定 + この PC の設定)"""
        tools = Tools()
        q = self.queue(tools)
        with q.cv:
            out = q._push(RF.run_of(None, "t", "file", None, source_path=self.media[0]))
        _until(lambda: q.status()["idle"], "待ち・実行中が 0")
        self.assertEqual(tools.started, [(self.media[0], SP.DEFAULTS["transcribe"]["model"], SP.DEFAULTS["post"]["llmModel"])])
        self.assertEqual(q.status()["runs"][0]["id"], out["id"])


class TestRestore(Base):
    def test_close_keeps_and_next_queue_resumes(self):
        """終了(close)で止まった実行は待ちの記録(封筒 + 束)に残り、次の Queue が同じ id のまま、受けたときの束で続ける"""
        tools = Tools()
        tools.gate.clear()
        q = self.queue(tools)
        self.sub(q, self.env_of(self.media[0]), {"transcribe": {"model": "large-v3"}})
        self.sub(q, self.env_of(self.media[1], "abcdef0123"))
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
        """古い形(封筒に deliver.batch・note)の待ちの記録も戻す(batch・note は読んで捨てる)。封筒の無い記録・legacy つきの封筒は
        戻さない(RV A2)。RESTORE_MAX_AGE より前の物は戻さず記録に「中止」"""
        now = time.time()

        def env(rid, path):
            return {"id": rid, "kind": "file", "input": {"path": path, "title": "古い形"}, "requestId": None,
                    "deliver": {"dir": None, "batch": None, "pool": None, "origin": None, "tag": None}, "note": "", "createdAt": 0, "specVersion": 2}
        old = {"id": "0123456789", "mode": "file", "title": "古い形", "sourcePath": self.media[0], "created": now - 60,
               "steps": [{"key": "transcribe", "state": "wait", "detail": ""}], "envelope": env("0123456789", self.media[0]), "spec": {"run": {"upto": "transcribe"}}}
        v1 = dict(old, id="abcdef0124", envelope=dict(env("abcdef0124", self.media[2]), specVersion=1, legacy={"mode": "file"}))
        stale = dict(old, id="abcdef0123", sourcePath=self.media[1], created=now - Q.RESTORE_MAX_AGE - 60, envelope=env("abcdef0123", self.media[1]))
        fields_only = {k: v for k, v in dict(old, id="fedcba9876").items() if k != "envelope"}
        with open(os.path.join(self.logs, Q.ACTIVE_FILE), "w", encoding="utf-8") as f:
            json.dump({"v": Q.ACTIVE_VERSION, "runs": [{"id": "../x", "mode": "file"}, old, {"id": "abcdefabcd", "mode": "nope"}, stale, "壊れた",
                                                       fields_only, v1]}, f)   # 壊れた行・形の違う id・知らない mode は読み飛ばす
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
            testkit.write_json(os.path.join(self.logs, Q.ACTIVE_FILE), {"v": ver, "runs": [old]})
            logs, tools = [], Tools()
            q = Q.Queue(None, env=self.env, poll=0.01, tools=tools, log_dir=self.logs, log=logs.append)
            self.addCleanup(q.close)
            self.assertEqual(q.runs, [], ver)
            self.assertTrue(any("古い形(版 %d)" % ver in m for m in logs), logs)
            self.assertEqual(self.active_file(), {"v": Q.ACTIVE_VERSION, "runs": []})
            self.assertEqual(tools.started, [])

    def test_gone_shape_is_skipped_with_log(self):
        """今は無い形(束は読めるのに mode_of が None。例: 配信の run.from adopt)の待ちの記録は、束なしの既定(頭からパックまで)で戻さず、
        どれを飛ばしたかをログに 1 行(形を消したあとに古い記録が残っていても、黙って別の形で動かない)"""
        env = {"id": "0123456789", "kind": "url", "input": {"videoId": "abcdefghijk", "title": "古い形"}, "requestId": None, "createdAt": 0, "specVersion": 2}
        rec = {"id": "0123456789", "mode": "gone", "title": "古い形", "created": time.time() - 60, "steps": [], "envelope": env,
               "spec": {"run": {"from": "adopt"}}}
        testkit.write_json(os.path.join(self.logs, Q.ACTIVE_FILE), {"v": Q.ACTIVE_VERSION, "runs": [rec]})
        logs = []
        q = Q.Queue(None, env=self.env, poll=0.01, tools=Tools(), log_dir=self.logs, log=logs.append)
        self.addCleanup(q.close)
        self.assertEqual(q.runs, [])
        self.assertTrue(any("戻せないので飛ばしました" in m and "0123456789" in m and "gone" in m for m in logs), logs)

    def test_removed_autorun_modes(self):
        """10-19 に消したまとめて実行の形: 文字起こしまで(transcribe = 書き出しから upto transcribe)の記録は飛ばしてログ・
        採用後を全部(adopted = 書き出しから upto pack)の記録は書き出しから全部(full + run.from export)として同じ段で戻す"""
        def rec(rid, mode, run):
            env = {"id": rid, "kind": "url", "input": {"videoId": "abcdefghij" + rid[-1], "title": mode}, "requestId": None, "createdAt": 0, "specVersion": 2}
            return {"id": rid, "mode": mode, "title": mode, "created": time.time() - 60, "steps": [{"key": "export", "state": "done", "detail": ""}],
                    "envelope": env, "spec": {"run": run}}
        testkit.write_json(os.path.join(self.logs, Q.ACTIVE_FILE), {"v": Q.ACTIVE_VERSION, "runs": [
            rec("0123456781", "transcribe", {"from": "export", "upto": "transcribe"}), rec("0123456782", "adopted", {"from": "export", "upto": "pack"})]})
        logs, tools = [], Tools()
        tools.gate.clear()   # 戻した実行は動かさずに形だけ見る
        q = Q.Queue(None, env=self.env, poll=0.01, tools=tools, log_dir=self.logs, log=logs.append)
        self.addCleanup(q.close)
        self.addCleanup(tools.gate.set)
        self.assertEqual([(r.id, r.mode, [s["key"] for s in r.steps], r.public()["modeLabel"]) for r in q.runs],
                         [("0123456782", "full", ["export", "transcribe", "pack"], "書き出しから全部")])
        self.assertTrue(any("戻せないので飛ばしました" in m and "0123456781" in m and "transcribe" in m for m in logs), logs)


class TestCancel(Base):
    def test_cancel_queued_and_running(self):
        """待ちの中止はすぐ「中止」・実行中の中止は段が止まってから。どちらも待ちの記録から外れ、記録に残る"""
        tools = Tools()
        tools.gate.clear()
        q = self.queue(tools)
        self.sub(q, self.env_of(self.media[0]))
        self.sub(q, self.env_of(self.media[1], "abcdef0123"))
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
        self.sub(q, self.env_of(self.media[0]))
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

    def test_cancel(self):
        """掲示板の cancel は Queue.cancel。済んだ物は Refused・無い id は NotFound"""
        tools = Tools()
        tools.gate.clear()
        q = self.queue(tools)
        b = self.board(q)
        self.sub(q, self.env_of(self.media[0]), {"transcribe": {"model": "large-v3"}})
        _until(lambda: q.status()["running"] == 1, "実行中")
        out = b.cancel("run:0123456789")
        self.assertEqual((out["id"], out["canCancel"]), ("run:0123456789", False))   # 止める印 = もう止められない
        _until(lambda: q.status()["idle"], "待ち・実行中が 0")
        tools.gate.set()
        with self.assertRaises(B.Refused):   # 済んだ物は止められない
            b.cancel("run:0123456789")
        with self.assertRaises(B.NotFound):
            b.cancel("run:ffffffffff")
        self.assertIsNone(q.board_cancel("0123456789"))

    def test_board_job_shape(self):
        """board_job は掲示板の形のまま(normalize を通る)。失敗は error・案件の根は結果の束のパスの形だけで決める"""
        run = RF.run_of("vid", "配信", "full", 3)
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
        self.assertEqual(set(st) - {"live", "blocked", "machine"}, {"queued", "running", "done", "idle", "closed", "runs"})   # 今までの欄はそのまま(F1 F0-1 で 2 つ足した)
        self.assertIsNone(st["blocked"])

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
        self.sub(q, self.env_of(self.media[0]))
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


class TestFriendIntake(Base):
    """F1 F0-1: 処理の開始の空き容量の下限(status.blocked)・status の machine・submit の版違いと束の形"""

    def test_disk_blocked_shape(self):
        big = lambda p: (5 * Q.GB, 100 * Q.GB)
        self.assertIsNone(Q.disk_blocked(self.tmp, 4, usage=big))
        self.assertEqual(Q.disk_blocked(self.tmp, 20, usage=big), {"reason": "disk", "freeGB": 5.0, "minGB": 20})
        self.assertIsNone(Q.disk_blocked(self.tmp, 0, usage=big))     # 下限 0 = 見ない
        self.assertIsNone(Q.disk_blocked("", 20, usage=big))
        self.assertIsNone(Q.disk_blocked(self.tmp, 20, usage=lambda p: (_ for _ in ()).throw(OSError("x"))))   # 測れない = 止めない
        self.assertIsNotNone(Q.disk_blocked(os.path.join(self.tmp, "nai", "mada"), 100000))   # 無いフォルダは在る所まで上へ(本物の空き)

    def test_disk_min_blocks_start(self):
        """diskMinGB=100000 で submit -> 実行を始めず status.blocked が出る。空きが戻れば(見直しで)始まる"""
        tools = Tools()
        q = self.queue(tools, env=dict(self.env, YTT_MACHINE_DISK_MIN_GB="100000", YTT_MACHINE_CASE_ROOT=self.tmp))
        self.sub(q, self.env_of(self.media[0]))
        _until(lambda: q.status()["blocked"] is not None, "blocked")
        st = q.status()
        self.assertEqual((st["blocked"]["reason"], st["blocked"]["minGB"], st["queued"], st["running"], st["idle"]),
                         ("disk", 100000, 1, 0, False))
        self.assertIsInstance(st["blocked"]["freeGB"], float)
        self.assertEqual(tools.started, [])
        self.assertEqual([r["id"] for r in self.active_file()["runs"]], ["0123456789"])   # 待ちの記録に残る
        q.disk_check = lambda: None
        with q.cv:
            q.cv.notify_all()
        _until(lambda: q.status()["idle"], "空きが戻って済む")
        self.assertIsNone(q.status()["blocked"])
        self.assertEqual(len(tools.started), 1)

    def test_status_machine(self):
        """status.machine = この PC の設定の engine・device・llmModel と GPU(ytt/gpuinfo が無い・失敗 = null)"""
        with mock.patch.object(Q, "gpu_info", return_value={"name": "RTX 3060", "vramGB": 12}):
            q = self.queue(env=dict(self.env, YTT_MACHINE_LLM_MODEL="qwen3-4b"))
            m = q.status()["machine"]
            self.assertEqual((m["engine"], m["device"], m["llmModel"]), (SP.TX_ENGINES[0], SP.TX_DEVICES[0], "qwen3-4b"))
            _until(lambda: q.status()["machine"]["gpu"] is not None, "GPU を調べ終える")
            self.assertEqual(q.status()["machine"]["gpu"], {"name": "RTX 3060", "vramGB": 12})

    def test_gpu_info(self):
        """ytt/gpuinfo を読む。import できない・失敗 = null"""
        fake = types.ModuleType("ytt.gpuinfo")
        fake.info = lambda: {"name": "Radeon", "vramGB": None, "vendor": "amd"}
        with mock.patch.dict(sys.modules, {"ytt.gpuinfo": fake}):
            self.assertEqual(Q.gpu_info(), {"name": "Radeon", "vramGB": None, "vendor": "amd"})
            fake.info = lambda: 1 / 0
            self.assertIsNone(Q.gpu_info())
        with mock.patch.dict(sys.modules, {"ytt.gpuinfo": None}):
            self.assertIsNone(Q.gpu_info())

    def test_submit_spec_version_and_bad_spec(self):
        q = self.queue()
        with self.assertRaises(Q.SpecVersionError) as c:
            q.submit(dict(self.env_of(self.media[0]), specVersion=99))
        self.assertIn("99", str(c.exception))
        with self.assertRaises(Q.BadSpecError):
            self.sub(q, self.env_of(self.media[0]), {"nai": {}})
        with self.assertRaises(Q.BadSpecError):
            self.sub(q, self.env_of(self.media[0]), {"transcribe": {"nai": 1}})
        self.assertTrue(issubclass(Q.SpecVersionError, ValueError) and issubclass(Q.BadSpecError, ValueError))   # 今の呼び手は ValueError のまま
        self.assertEqual(q.status()["runs"], [])


from flow import runlog  # noqa: E402


class _FailTools(Tools):
    """fail を立てると文字起こしのジョブが失敗で終わる"""
    fail = False

    def jobs(self):
        return [dict(j, state="error", error="だめ") for j in super().jobs()] if self.fail else super().jobs()


class TestRunLog(Base):
    """終わった実行の記録(logs/autorun-runs.jsonl): 1 回だけ書く・起動し直しても past で前回が見える・history・回す・末尾だけ読む・書けなくても止めない"""

    def path(self):
        return os.path.join(self.logs, runlog.RUNS_LOG)

    def lines(self, path=None):
        """そのファイルだけの行(read_runs_log は .1 も読むので使わない)"""
        try:
            with open(path or self.path(), encoding="utf-8") as f:
                return [json.loads(x) for x in f if x.strip()]
        except FileNotFoundError:
            return []

    def wait_lines(self, n):
        """実行の状態が変わってから記録を書くまでの間があるので、行が n 行になるまで待つ"""
        _until(lambda: len(self.lines()) >= n, "記録 %d 行" % n)
        return self.lines()

    def make(self, **kw):
        q = Q.Queue(None, env=self.env, poll=0.01, tools=kw.pop("tools", None) or Tools(), log_dir=kw.pop("log_dir", self.logs), **kw)
        self.addCleanup(q.close)
        return q

    def run_file(self, q, i, eid):
        self.sub(q, self.env_of(self.media[i], eid=eid))
        _until(lambda: q.status()["idle"], "待ち・実行中が 0")
        return eid

    def test_done_and_error_are_written_once(self):
        tools = _FailTools()
        q = self.make(tools=tools)
        a = self.run_file(q, 0, "0000000001")
        tools.fail = True
        b = self.run_file(q, 1, "0000000002")
        got = self.wait_lines(2)
        self.assertEqual([(x["v"], x["id"], x["state"], x["kind"]) for x in got], [(1, a, "done", "file"), (1, b, "error", "file")])
        self.assertTrue(got[0]["finished"])
        q._log(next(r for r in q.runs if r.id == a))   # 同じ実行をもう一度書こうとしても 1 行のまま・終わった実行の中止も書かない
        q.cancel(a)
        time.sleep(0.05)
        self.assertEqual([x["id"] for x in self.lines()], [a, b])

    def test_restart_shows_past_and_memory_wins(self):
        q = self.make()
        a = self.run_file(q, 0, "0000000001")
        self.wait_lines(1)
        self.assertEqual(q.snapshot()["past"], [])   # メモリにある分は past に出さない(重ならない)
        q.close()
        q = self.make()   # 起動し直した
        snap = q.snapshot()
        self.assertEqual((snap["runs"], [(p["id"], p["state"]) for p in snap["past"]]), ([], [(a, "done")]))
        self.assertIn("steps", snap["past"][0])
        self.assertNotIn("sourcePath", snap["past"][0])   # past は画面に出す項目だけ(問い合わせを重くしない)
        b = self.run_file(q, 0, "0000000002")   # 同じ動画をもう一度 = メモリの方を出す
        self.wait_lines(2)
        self.assertEqual(q.snapshot()["past"], [])
        h = q.history()
        self.assertEqual(([x["id"] for x in h["runs"]], h["total"], h["more"]), ([b, a], 2, False))   # 新しい順

    def test_past_is_latest_per_target(self):
        recs = [dict(id="r%d" % i, kind="video", videoId="v%d" % (i % 3), docId=None, state="done", steps=[], v=1, finished=i) for i in range(7)]
        recs.append(dict(id="d1", kind="doc", videoId=None, docId="doc1", state="error", error="止まった", steps=[], v=1))
        with open(self.path(), "w", encoding="utf-8") as f:
            f.write("not json\n" + "".join(json.dumps(x) + "\n" for x in recs))   # 壊れた行の種類ごとの読み飛ばしは test_runlog
        q = self.make()
        self.assertEqual([p["id"] for p in q.snapshot()["past"]], ["d1", "r6", "r5", "r4"])   # 配信・文書ごとの最後の 1 件・新しい順
        self.assertEqual(q.history()["total"], 8)

    def test_rotates_at_limit(self):
        q = self.make(log_max=300)   # 1 件で超える大きさ
        ids = [self.run_file(q, 0, "0000000001")]
        self.wait_lines(1)
        ids.append(self.run_file(q, 1, "0000000002"))
        _until(lambda: os.path.exists(self.path() + ".1"), ".1 ができる")
        self.assertEqual([x["id"] for x in self.lines(self.path() + ".1")], ids[:1])   # 古い方は .1 へ(1 世代)
        self.assertEqual([x["id"] for x in self.wait_lines(1)], ids[1:])
        self.assertEqual([x["id"] for x in q.history()["runs"]], ids[::-1])   # 記録は .1 と今のファイルの両方から
        ids.append(self.run_file(q, 2, "0000000003"))
        _until(lambda: [x["id"] for x in self.lines(self.path() + ".1")] == ids[1:2], "いちばん古いものが消える")
        self.assertEqual([x["id"] for x in self.wait_lines(1)], ids[2:])

    def test_read_tail_only_on_start_and_history_bounds(self):
        rec = lambda i: json.dumps(dict(id="r%04d" % i, kind="video", videoId="v%04d" % i, docId=None, state="done", steps=[], v=1)) + "\n"  # noqa: E731
        with open(self.path(), "w", encoding="utf-8") as f:
            f.write("".join(rec(i) for i in range(4000)))   # 末尾だけ読む大きさを超える
        self.assertGreater(os.path.getsize(self.path()), Q.LOG_READ_BYTES)
        q = self.make()
        past = q.snapshot()["past"]
        self.assertEqual((len(past), past[0]["id"]), (Q.PAST_MAX, "r3999"))
        self.assertLess(len(q._past), 4000)   # 起動時は末尾だけ読む
        h = q.history(limit=10 ** 6, offset=-5)   # 範囲に丸める
        self.assertEqual((len(h["runs"]), h["offset"], h["total"], h["more"]), (Q.HISTORY_MAX, 0, 4000, True))
        self.assertEqual([x["id"] for x in q.history(limit=0, offset=3990)["runs"]], ["r0009"])
        h = q.history(limit="x", offset=3995)
        self.assertEqual((len(h["runs"]), h["more"]), (5, False))

    def test_unwritable_folder_does_not_stop_runs(self):
        blocker = os.path.join(self.tmp, "blocker")
        testkit.write_text(blocker, "x")   # フォルダの代わりにファイルがある = 書けない
        q = self.make(log_dir=os.path.join(blocker, "logs"))
        self.run_file(q, 0, "0000000001")
        self.assertEqual(q.status()["runs"][0]["state"], "done")
        _until(lambda: q.log_error, "書けなかった理由")
        self.assertEqual(q.history()["runs"], [])
        self.run_file(q, 1, "0000000002")   # 次の実行も続けられる
        self.assertEqual(q.status()["runs"][1]["state"], "done")

    def test_no_log_dir_keeps_memory_only(self):
        q = self.make(log_dir=None)
        self.run_file(q, 0, "0000000001")
        self.assertEqual(q.history(), {"runs": [], "total": 0, "more": False, "offset": 0})
        self.assertEqual(os.listdir(self.logs), [])


if __name__ == "__main__":
    unittest.main()
