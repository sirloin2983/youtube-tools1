# -*- coding: utf-8 -*-
"""flow/placement(② 置き場所の持ち主・結果の束・.flow.lock。役割で組み直す RS6 b-B0)のテスト。

    py -3.10 -m unittest src/flow/tests/test_placement.py -v

- 値が今と同じ: スタジオの data.json(案件の locations の以前の式・編集の studio_data_path の以前の式・スタジオ自身の studio_env)
- 案件の根: 配信 = 書き出しと同じ規則のフォルダ(作らない)・動画ファイル = 動画のあるフォルダ・作業用 / runs
- 結果の束: 終わり方(done・error・cancelled・stopped)・段ごとの成果物と鍵・run() の最後に書く・書けなくても上げない・索引の resultPath から読める
- .flow.lock: 取る・二重に取れない・返す・取り残し(動いていない pid・閉じたポート・壊れた中身)は取り直せる・他人の印は消さない
"""
import os
os.environ.setdefault("YTT_DATA_DIR", "inplace")   # 作業データは読み書きしない(一時フォルダだけ)
import json
import shutil
import socket
import subprocess
import sys
import tempfile
import unittest
from unittest import mock

SRC = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))   # tests -> flow -> src
sys.path.insert(0, SRC)
from flow import keys, placement, run as run_mod, runlog  # noqa: E402
from ytt import datadir, layout, names, schemas, studio_env, workdata  # noqa: E402

TID = "abc123def456"


def _touch(path, data=b"x"):
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with open(path, "wb") as f:
        f.write(data)
    return path


class _Tmp(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.mkdtemp(prefix="flowplace_")
        self.addCleanup(shutil.rmtree, self.tmp, True)


class TestStudioData(_Tmp):
    """スタジオの data.json の場所は、置き場所の持ち主 3 系統の以前の値と同じ"""

    def tearDown(self):
        datadir.register("studio", None)

    @staticmethod
    def old_cases(repo_root, env):   # manage/cases の locations の以前の式
        return os.path.join(datadir.resolve("studio", repo_root, env), "data.json")

    @staticmethod
    def old_editor(repo_root):   # 編集の serve.studio_data_path の以前の式(環境変数 TRANSCRIBE_STUDIO_DATA の無いとき)
        legacy = layout.tool_dir("studio", repo_root)
        new = os.path.join(datadir.resolve("studio", repo_root, legacy_dir=legacy), "data.json")
        return new if os.path.isfile(new) or datadir.registered("studio") or datadir.override("studio") else os.path.join(legacy, "data.json")

    def test_same_as_cases(self):
        for env in ({"YTT_DATA_DIR": self.tmp}, {"YTT_DATA_DIR": "inplace"}, {"STUDIO_HOME": os.path.join(self.tmp, "s")}):
            self.assertEqual(placement.studio_data(self.tmp, env), self.old_cases(self.tmp, env), env)
        self.assertEqual(placement.studio_data(None, {"YTT_DATA_DIR": self.tmp}), os.path.join(self.tmp, "studio", "data.json"))

    def test_same_as_editor(self):
        with mock.patch.dict(os.environ, {"YTT_DATA_DIR": os.path.join(self.tmp, "data")}):
            os.environ.pop("STUDIO_HOME", None)
            # 新しい置き場に無い・登録も STUDIO_HOME も無い = 以前の場所(スタジオのフォルダ)
            self.assertEqual(placement.studio_data(self.tmp, legacy=True), self.old_editor(self.tmp))
            self.assertEqual(placement.studio_data(self.tmp, legacy=True), os.path.join(layout.tool_dir("studio", self.tmp), "data.json"))
            # 新しい置き場にある = そちら
            _touch(os.path.join(self.tmp, "data", "studio", "data.json"), b"{}")
            self.assertEqual(placement.studio_data(self.tmp, legacy=True), self.old_editor(self.tmp))
            self.assertEqual(placement.studio_data(self.tmp, legacy=True), os.path.join(self.tmp, "data", "studio", "data.json"))
        with mock.patch.dict(os.environ, {"STUDIO_HOME": os.path.join(self.tmp, "home")}):
            self.assertEqual(placement.studio_data(self.tmp, legacy=True), self.old_editor(self.tmp))

    def test_same_as_studio_itself(self):
        """スタジオの serve は決めた場所を set_home して datadir.register する = studio_env.p と同じ場所を読む"""
        old = studio_env._home
        self.addCleanup(setattr, studio_env, "_home", old)
        home = os.path.join(self.tmp, "studio-home")
        studio_env.set_home(home)
        datadir.register("studio", studio_env.home())
        self.assertEqual(placement.studio_data(), studio_env.p("data.json"))
        self.assertEqual(placement.studio_data(legacy=True), studio_env.p("data.json"))
        self.assertEqual(placement.studio_data(), self.old_cases(None, None))
        self.assertEqual(placement.studio_data(legacy=True), self.old_editor(None))

    def test_workdata_default_is_the_legacy_value(self):
        """編集の workdata.set_root の読み込み直後の既定(ytt の側。変えない)は、placement の legacy の値と同じ"""
        saved = {k: getattr(workdata, k) for k in ("ROOT", "DATA_DIR", "TX_DIR", "TMP_DIR", "EVAL_BASE", "SETTINGS", "FEEDBACK", "MARKER_DATA", "STUDIO_DATA")}
        self.addCleanup(lambda: [setattr(workdata, k, v) for k, v in saved.items()])
        with mock.patch.dict(os.environ, {"YTT_DATA_DIR": "inplace"}):
            for k in ("TRANSCRIBE_STUDIO_DATA", "TRANSCRIBE_DATA_DIR", "STUDIO_HOME"):
                os.environ.pop(k, None)
            workdata.set_root(os.path.join(self.tmp, "editor"))
            self.assertEqual(workdata.STUDIO_DATA, placement.studio_data(self.tmp, legacy=True))


class TestCaseRoot(_Tmp):
    def setUp(self):
        super().setUp()
        self.out = os.path.join(self.tmp, "exports")
        os.makedirs(self.out)

    def test_file(self):
        v = _touch(os.path.join(self.tmp, "req", "v.mp4"))
        self.assertEqual(placement.case_root({"kind": "file", "path": v}), os.path.join(self.tmp, "req"))
        edit = _touch(os.path.join(self.tmp, "req", schemas.WORK_DIR, "v_edit.mp4"))
        self.assertEqual(placement.case_root({"kind": "file", "path": edit}), os.path.join(self.tmp, "req"))
        self.assertEqual(placement.work_dir({"kind": "file", "path": v}), os.path.join(self.tmp, "req", schemas.WORK_DIR))
        self.assertEqual(placement.runs_dir({"kind": "file", "path": v}), os.path.join(self.tmp, "req", schemas.WORK_DIR, "runs"))
        self.assertIsNone(placement.case_root({"kind": "file", "path": os.path.join(self.tmp, "nai", "v.mp4")}))
        for bad in (None, {}, {"kind": "file"}, {"kind": "video"}, {"kind": "x", "path": v}):
            self.assertIsNone(placement.case_root(bad))
            self.assertIsNone(placement.runs_dir(bad))

    def test_video_same_folder_as_export(self):
        """書き出し(ytt.names.pick_folder)が選ぶフォルダと同じ。引くだけで作らない"""
        media = {"kind": "video", "videoId": "vid00000001", "title": "配信の題名"}
        self.assertIsNone(placement.case_root(media, self.out))
        self.assertEqual(os.listdir(self.out), [])   # 作っていない
        _name, path = names.pick_folder(self.out, "配信の題名", "vid00000001", "vid00000001")
        self.assertEqual(placement.case_root(media, self.out), path)
        # 同じ題名の別の配信は連番のフォルダ
        _n2, path2 = names.pick_folder(self.out, "配信の題名", "vid00000002", "vid00000002")
        self.assertNotEqual(path, path2)
        self.assertEqual(placement.case_root(dict(media, videoId="vid00000002"), self.out), path2)
        self.assertIsNone(placement.case_root(dict(media, videoId="vid00000003"), self.out))
        # 題名が空 = 書き出しと同じく videoId の名前
        _n3, path3 = names.pick_folder(self.out, "", "vid00000004", "vid00000004")
        self.assertEqual(placement.case_root({"kind": "video", "videoId": "vid00000004", "title": ""}, self.out), path3)

    def test_video_handmade_folder_is_not_claimed(self):
        os.makedirs(os.path.join(self.out, "手で作った"))
        self.assertIsNone(placement.case_root({"kind": "video", "videoId": "v1", "title": "手で作った"}, self.out))
        self.assertIsNone(names.read_owner(os.path.join(self.out, "手で作った")))   # 印を書いていない

    def test_video_clips_win(self):
        clip = _touch(os.path.join(self.tmp, "elsewhere", "01_00h00m01s-00h00m09s.mp4"))
        media = {"kind": "video", "videoId": "v1", "title": "x", "clips": [os.path.join(self.tmp, "gone.mp4"), clip]}
        self.assertEqual(placement.case_root(media, self.out), os.path.join(self.tmp, "elsewhere"))

    def test_pick_folder_unchanged(self):
        """find_folder を足すために分けた pick_folder の名前の規則は前と同じ"""
        a = names.pick_folder(self.out, 'a/b:c*"d', "o1", "fb")
        self.assertEqual(a[0], "a_b_c_d")
        self.assertEqual(names.pick_folder(self.out, 'a/b:c*"d', "o1", "fb"), a)
        self.assertEqual(names.pick_folder(self.out, 'a/b:c*"d', "o2", "fb")[0], "a_b_c_d_2")
        self.assertEqual(names.pick_folder(self.out, "CON", "o3", "fb")[0], "_CON")
        self.assertEqual(names.pick_folder(self.out, "   ", "o4", "fb")[0], "fb")
        _touch(os.path.join(self.out, "ふぁいる"))   # 同じ名前のファイルは飛ばす
        self.assertEqual(names.pick_folder(self.out, "ふぁいる", "o5", "fb")[0], "ふぁいる_2")
        self.assertEqual(names.find_folder(self.out, "ふぁいる", "o5", "fb")[0], "ふぁいる_2")


class _Runner(run_mod.Runner):
    """execute だけを差し替えた Runner(段は動かさない)"""

    def __init__(self, do=None, docs=(), video=None):
        super().__init__(client=None)
        self.do, self.docs_list, self.video = do, list(docs), video

    def execute(self, run):
        if self.do:
            self.do(run)

    def _docs(self):
        return self.docs_list

    def _studio_video(self, vid):
        return self.video or {}


class TestResult(_Tmp):
    def setUp(self):
        super().setUp()
        self.video = _touch(os.path.join(self.tmp, "req", "依頼.mp4"))
        tx = os.path.join(self.tmp, "transcripts")
        os.makedirs(tx)
        p = mock.patch.object(workdata, "TX_DIR", tx)
        p.start()
        self.addCleanup(p.stop)
        self.tx = tx

    def runs(self):
        return os.path.join(self.tmp, "req", schemas.WORK_DIR, "runs")

    def test_file_run_done(self):
        def do(run):
            run.step("transcribe")["state"] = "done"
            run.docs.append(TID)
            run.new_docs.append(TID)
            run.doc_id = TID
        _touch(os.path.join(self.tx, TID + ".json"), b"{}")
        keys.write("transcribe", keys.doc_key_path(TID, "transcribe"), {"a": 1})
        r = run_mod.run(None, {"path": self.video}, hooks=_Runner(do))
        path = os.path.join(self.runs(), r.id + ".json")
        self.assertEqual(r.result_path, path)
        self.assertEqual(r.public()["resultPath"], path)
        with open(path, encoding="utf-8") as f:
            b = json.load(f)
        self.assertEqual((b["schema"], b["id"], b["state"], b["error"]), (runlog.RESULT_SCHEMA, r.id, "done", ""))
        self.assertEqual(b["input"]["kind"], "file")
        self.assertEqual(b["input"]["sourcePath"], self.video)
        self.assertEqual(b["spec"], r.spec)   # 有効な束
        self.assertEqual([s["key"] for s in b["steps"]], [s["key"] for s in r.steps])
        tx = b["outputs"]["transcribe"]
        self.assertEqual(tx, [{"doc": TID, "path": os.path.join(self.tx, TID + ".json"), "key": keys.doc_key_path(TID, "transcribe"), "post": None}])
        self.assertEqual((b["outputs"]["export"], b["outputs"]["pack"], b["packs"], b["failures"]), ([], [], [], []))
        self.assertIsInstance(b["at"], int)
        # 索引(入口の記録の 1 行 = Run.public + v)から読める
        self.assertEqual(runlog.read_result(dict(r.public(), v=runlog.LOG_VERSION)), b)

    def test_error_and_cancel(self):
        def boom(run):
            run.step("transcribe")["state"] = "run"
            raise run_mod.StepError("文字起こしに失敗しました: x")
        with self.assertRaises(run_mod.StepError):
            run_mod.run(None, {"path": self.video}, hooks=_Runner(boom))
        (name,) = os.listdir(self.runs())
        with open(os.path.join(self.runs(), name), encoding="utf-8") as f:
            b = json.load(f)
        self.assertEqual((b["state"], b["error"]), ("error", "文字起こしに失敗しました: x"))
        self.assertEqual(b["failures"], [{"step": "transcribe", "state": "error", "detail": "文字起こしに失敗しました: x"}])
        self.assertEqual([s["state"] for s in b["steps"] if s["key"] == "transcribe"], ["error"])

        def stop(run):
            run.step("transcribe")["state"] = "run"
            raise run_mod.Cancelled()
        run = run_mod.Run.from_input({"path": self.video})
        with self.assertRaises(run_mod.Cancelled):
            run_mod.run(None, run, hooks=_Runner(stop))
        self.assertEqual(placement.result(run, run_mod.Cancelled())["state"], "stopped")   # 入口の終了 = 次の起動で続く
        with open(run.result_path, encoding="utf-8") as f:
            b = json.load(f)
        self.assertEqual(b["state"], "stopped")
        self.assertEqual([s["state"] for s in b["steps"] if s["key"] == "transcribe"], ["wait"])
        run.cancel = True
        self.assertEqual(placement.result(run, run_mod.Cancelled())["state"], "cancelled")
        self.assertEqual(placement.result(run, KeyError("x"))["error"], "想定外の失敗(KeyError)")

    def test_video_run_outputs_and_keys(self):
        out = os.path.join(self.tmp, "exports")
        _n, folder = names.pick_folder(out, "題名", "vid0000000a", "vid0000000a")
        clip = _touch(os.path.join(folder, "01_00h00m01s-00h00m09s.mp4"))
        other = _touch(os.path.join(folder, "02_00h00m10s-00h00m19s.mp4"))
        keys.write_export(clip, schemas.media_identity("archive", videoId="vid0000000a"), 1, 9, {})
        pack = os.path.join(folder, "01_00h00m01s-00h00m09s_pack")
        os.makedirs(pack)
        video = {"marks": [{"id": "m1", "status": "exported", "path": clip}, {"id": "m2", "status": "exported", "path": other},
                           {"id": "m3", "status": "adopted", "path": None}]}
        run = run_mod.Run("vid0000000a", "題名", "adopted", None, marks=("m1",))
        run.packs.append(pack)
        run.pack_marks[pack] = {"path": clip, "markId": "m1"}
        path = placement.write_result(run, None, _Runner(video=video), out_dir=out)
        self.assertEqual(path, os.path.join(folder, schemas.WORK_DIR, "runs", run.id + ".json"))
        with open(path, encoding="utf-8") as f:
            b = json.load(f)
        self.assertEqual(b["outputs"]["export"], [{"path": os.path.normpath(clip), "key": keys.media_key_path(os.path.normpath(clip))}])
        self.assertEqual(b["outputs"]["pack"], [{"path": pack, "key": None, "clip": clip}])
        self.assertEqual(b["packs"], [pack])
        # 切り抜きの分からない実行も、書き出しと同じ規則で案件を引く
        run2 = run_mod.Run("vid0000000a", "題名", "full", 3)
        self.assertEqual(placement.write_result(run2, None, _Runner(), out_dir=out), os.path.join(folder, schemas.WORK_DIR, "runs", run2.id + ".json"))

    def test_doc_run_uses_doc_source(self):
        run = run_mod.Run.from_input({"docId": TID})
        path = placement.write_result(run, None, _Runner(docs=[{"id": TID, "sourcePath": self.video}]))
        self.assertEqual(path, os.path.join(self.runs(), run.id + ".json"))
        self.assertIsNone(placement.write_result(run_mod.Run.from_input({"docId": TID}), None, _Runner()))   # 文書が分からない

    def test_never_raises(self):
        run = run_mod.Run.from_input({"path": os.path.join(self.tmp, "nai", "v.mp4")})
        self.assertIsNone(placement.write_result(run))   # 案件が無い
        self.assertIsNone(run.result_path)
        _touch(os.path.join(self.tmp, "req", schemas.WORK_DIR, "runs"))   # runs がファイル = 書けない
        run = run_mod.Run.from_input({"path": self.video})
        with self.assertLogs("ytt.flow.placement", "WARNING"):
            self.assertIsNone(placement.write_result(run))

        class Bad(_Runner):
            def _docs(self):
                raise RuntimeError("x")
        run = run_mod.Run.from_input({"docId": TID})
        with self.assertLogs("ytt.flow.placement", "WARNING"):
            self.assertIsNone(placement.write_result(run, None, Bad()))
        # run() の元の例外は束を書く処理に隠されない
        with mock.patch.object(placement, "result", side_effect=RuntimeError("x")), self.assertLogs("ytt.flow.placement", "WARNING"):
            with self.assertRaises(run_mod.StepError):
                run_mod.run(None, {"path": self.video}, hooks=_Runner(lambda r: (_ for _ in ()).throw(run_mod.StepError("e"))))


def _dead_pid():
    p = subprocess.Popen([sys.executable, "-c", "pass"])
    p.wait()
    return p.pid


class TestEnsureCase(_Tmp):
    def setUp(self):
        super().setUp()
        self.video = _touch(os.path.join(self.tmp, "req", "依頼.mp4"))
        self.media = {"kind": "file", "path": self.video}
        self.case = os.path.join(self.tmp, "req", "case.json")

    def test_creates_once_and_idempotent(self):
        a = placement.ensure_case(self.media, channel="ch")
        self.assertTrue(os.path.isfile(self.case))
        self.assertEqual((a["schema"], a["title"], a["channel"], a["media"]), ("youtube-tools-case/v1", "依頼", "ch", {"kind": "file", "path": self.video}))
        self.assertTrue(a["id"].startswith("f-") and a["madeBy"]["name"] == "flow" and isinstance(a["createdAt"], int))
        with open(self.case, "rb") as f:
            before = f.read()
        b = placement.ensure_case(self.media, channel="別")   # 2 回目は読むだけ(上書きしない)
        self.assertEqual(b, a)
        with open(self.case, "rb") as f:
            self.assertEqual(f.read(), before)
        self.assertEqual(placement.read_case(os.path.join(self.tmp, "req")), a)

    def test_broken_not_overwritten(self):
        _touch(self.case, "{壊れた".encode("utf-8"))
        self.assertIsNone(placement.ensure_case(self.media))
        with open(self.case, "rb") as f:
            self.assertEqual(f.read(), "{壊れた".encode("utf-8"))
        self.assertIsNone(placement.read_case(os.path.join(self.tmp, "req")))

    def test_unknown_case_is_none_and_nothing_made(self):
        self.assertIsNone(placement.ensure_case({"kind": "file", "path": os.path.join(self.tmp, "nai", "v.mp4")}))
        self.assertFalse(os.path.exists(os.path.join(self.tmp, "nai")))

    def test_video_id_from_studio_id_or_video_id(self):
        out = os.path.join(self.tmp, "exports")
        os.makedirs(out)
        media = {"kind": "video", "videoId": "vid00000001", "title": "配信の題名"}
        _name, path = names.pick_folder(out, "配信の題名", "vid00000001", "vid00000001")   # .studio-id を書く
        c = placement.ensure_case(media, out)
        self.assertEqual((c["id"], c["title"], c["media"]), ("vid00000001", "配信の題名", {"kind": "video", "videoId": "vid00000001"}))
        self.assertTrue(os.path.isfile(os.path.join(path, "case.json")))
        self.assertEqual(names.read_owner(path), "vid00000001")   # .studio-id は残る

    def test_write_result_makes_case(self):
        tx = os.path.join(self.tmp, "transcripts")
        os.makedirs(tx)
        with mock.patch.object(workdata, "TX_DIR", tx):
            run_mod.run(None, {"path": self.video}, hooks=_Runner(lambda run: None))
        self.assertTrue(os.path.isfile(self.case))
        self.assertEqual(placement.read_case(os.path.join(self.tmp, "req"))["media"]["path"], self.video)


class TestLock(_Tmp):
    def path(self):
        return os.path.join(self.tmp, placement.LOCK_NAME)

    def write(self, obj):
        with open(self.path(), "w", encoding="utf-8") as f:
            f.write(obj if isinstance(obj, str) else json.dumps(obj))

    def test_acquire_release(self):
        self.assertIsNone(placement.lock_info(self.tmp))
        h = placement.acquire(data_root=self.tmp)
        info = placement.lock_info(self.tmp)
        self.assertEqual((info["pid"], info["port"]), (os.getpid(), None))
        self.assertIsInstance(info["at"], int)
        with self.assertRaises(placement.LockBusy) as cm:   # 二重には取れない
            placement.acquire(data_root=self.tmp)
        self.assertEqual(cm.exception.info["pid"], os.getpid())
        self.assertTrue(placement.release(h))
        self.assertFalse(os.path.exists(self.path()))
        self.assertIsNone(placement.lock_info(self.tmp))
        self.assertFalse(placement.release(h))      # 返し済み
        self.assertFalse(placement.release(None))
        placement.release(placement.acquire(data_root=self.tmp))   # 返したらまた取れる

    def test_stale_lock_is_taken_over(self):
        for stale in ({"pid": _dead_pid(), "port": None, "at": 1, "token": "t"}, "{壊れた", {"pid": "x"}, []):
            self.write(stale)
            self.assertIsNone(placement.lock_info(self.tmp), stale)
            h = placement.acquire(data_root=self.tmp)
            self.assertEqual(placement.lock_info(self.tmp)["pid"], os.getpid())
            placement.release(h)

    def test_port_must_be_open(self):
        s = socket.socket()
        s.bind(("127.0.0.1", 0))
        s.listen(16)
        port = s.getsockname()[1]
        try:
            h = placement.acquire(port, self.tmp)
            self.assertEqual(placement.lock_info(self.tmp)["port"], port)
            with self.assertRaises(placement.LockBusy):
                placement.acquire(data_root=self.tmp)
        finally:
            s.close()
        # ポートが閉じた(pid は動いている = 使い回しかもしれない)= 取り残し
        self.assertIsNone(placement.lock_info(self.tmp))
        placement.release(placement.acquire(data_root=self.tmp))
        self.assertFalse(placement.release(h))   # 取り直された印は消さない
        with self.assertRaises(ValueError):
            placement.acquire(80, self.tmp)

    def test_release_keeps_others_lock(self):
        h = placement.acquire(data_root=self.tmp)
        self.write({"pid": os.getpid(), "port": None, "at": 1, "token": "someone-else"})
        self.assertFalse(placement.release(h))
        self.assertTrue(os.path.exists(self.path()))

    def test_lock_path(self):
        with mock.patch.dict(os.environ, {"YTT_DATA_DIR": self.tmp}):
            self.assertEqual(placement.lock_path(), os.path.join(self.tmp, ".flow.lock"))
        with mock.patch.dict(os.environ, {"YTT_DATA_DIR": "inplace", "YTT_RUNTIME_DIR": os.path.join(self.tmp, "rt")}):
            self.assertEqual(placement.lock_path(), os.path.join(self.tmp, "rt", ".flow.lock"))
        self.assertEqual(placement.lock_path(os.path.join(self.tmp, "x")), os.path.join(self.tmp, "x", ".flow.lock"))


if __name__ == "__main__":
    unittest.main()
