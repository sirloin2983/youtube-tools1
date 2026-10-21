#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""まとめて実行(src/app/autorun.py)の段取りのテスト。ツールの API は偽物(FakeTools)で、本物の通し確認は tests/app/e2e_autorun.py。
実行(リポジトリ直下): python -m unittest tests/app/test_autorun.py"""
import json
import os
import re
import shutil
import sys
import time
import unittest
from unittest import mock

os.environ.setdefault("YTT_DATA_DIR", "inplace")   # テストは作業データを本物の置き場所(AppData など)に書かない(ytt.datadir)
TESTS = os.path.dirname(os.path.abspath(__file__))   # src/home/tests
HERE = os.path.join(os.path.dirname(os.path.dirname(TESTS)), "src", "app")   # home(入口の部品)
sys.path.insert(0, HERE)
sys.path.insert(0, TESTS)
sys.path.insert(0, os.path.dirname(HERE))
import autorun as A  # noqa: E402
from flow import deliver as deliver_mod  # noqa: E402  (届ける部品。② flow/delivery.py)
from flow import delivery as DL  # noqa: E402
from flow import packrec  # noqa: E402
from pipeline.pack import preview as pv  # noqa: E402
from human.friend import friend_feedback  # noqa: E402
import prefs as prefs_mod  # noqa: E402
from flow import runlog  # noqa: E402
from flow import run as RUN  # noqa: E402  (流れ作業のスイッチ PIPE_TX)
from flow import spec as SP  # noqa: E402
from flow import order as O  # noqa: E402  (欄 → 封筒 + 束の差分。受付は submit の 1 本)
from human.friend import intake as IN  # noqa: E402  (友人の受付の欄 → submit = submit_urls・submit_file)
from ytt import fsio  # noqa: E402
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))   # tests/(testkit)
import testkit  # noqa: E402
sys.path.insert(0, os.path.join(os.path.dirname(os.path.dirname(HERE)), "tests", "flow"))   # 共有の部品 _runfields(Run の欄の形 → 封筒 + 束)
import _runfields as RF  # noqa: E402


# ---- 受付の欄の写し(受付は submit の 1 本)。画面の UIKit.flow.order と友人の受付(intake)と同じ変換 ----
def _send_folder(ar):
    """友人へ自動で送る届け先の元 = 依頼の受付の Dropbox のフォルダ(ホームの設定 intake.folder。読み方は受付と同じ 1 か所)。決まっていなければ空の文字"""
    return IN.configured_folder(ar.prefs, prefs_mod.DEFAULTS["intake"]) if ar.prefs else ""


EXPORT = "export"   # テストの呼び名: 書き出しから全部(mode full + 束の run.from export。マークの行の「この後を」・書き出しのあと自動で。まとめて実行の形は full だけ = 10-19)


def start(ar, video_id, mode, top=None, streamer=None, marks=None, overwrite=False, auto_send=None):
    """ホームの案件の行・スタジオのマークの行の「まとめて実行」(画面の UIKit.flow.order → submit と同じ形)。mode = full(解析から全部)か EXPORT(書き出しから全部)。
    友人へ自動で送る(D-SEND): 解析から全部で、受付のフォルダが決まっていれば出どころ auto + 届け先。auto_send False(チェックを外した)= 出どころ auto で届け先なし"""
    if mode not in A.MODES and mode != EXPORT:
        raise ValueError("実行の形が正しくありません")
    if top is not None:
        SP.top_arg(top)   # 画面は 1〜20 に丸めてから送る(合わない数は ValueError)
    full = mode == "full"
    folder = _send_folder(ar) if full else ""
    dl = {"origin": "auto", "deliver_dir": IN.out_dir_of(folder) if auto_send is not False else None} if folder else {}
    env, diff = O.order("url", video_id=video_id, from_=None if full else "export", upto="pack",
                        top=top, streamer=streamer, marks=marks, repack=overwrite, **dl)
    return ar.submit(env, diff)


def _each(ar, items, make):
    """1 本ずつ submit(画面の UIKit.autorun.start と同じ: 断られた分は skipped・全部断られたら 1 本目の理由で ValueError)"""
    runs, skipped = [], []
    for it in items:
        try:
            runs.append(ar.submit(*make(it)))
        except ValueError as e:
            d = it if isinstance(it, dict) else {}
            skipped.append({"id": str(d.get("id") if isinstance(it, dict) else it)[:40], "title": str(d.get("title") or ""), "reason": str(e)})
    if not runs and skipped:
        raise ValueError(skipped[0]["reason"])
    return {"runs": runs, "skipped": skipped}


def start_new(ar, items, top=None, streamer=None, auto_send=None):
    """スタジオの ① 探す で選んだ配信を「解析から全部」で(1 本ずつ submit。まだスタジオに無い配信の印 fresh)"""
    if top is not None:
        SP.top_arg(top)
    folder = _send_folder(ar)
    dl = {"origin": "auto", "deliver_dir": IN.out_dir_of(folder) if auto_send is not False else None} if folder else {}

    def make(it):
        it = it if isinstance(it, dict) else {}
        title = str(it.get("title") or "").strip()
        return O.order("url", video_id=it.get("id"), title=title or it.get("id"), fresh={"title": title, "channel": str(it.get("channel") or "").strip()},
                       top=top, streamer=streamer, **dl)
    return _each(ar, items, make)


def start_docs(ar, ids, overwrite=False, streamer=None):
    """「編集」の履歴で選んだ文書をまとめて(文書 1 本ずつ submit)"""
    return _each(ar, list(dict.fromkeys(i for i in ids if isinstance(i, str))),
                 lambda tid: O.order("docs", doc_id=tid, title=tid, repack=overwrite, streamer=streamer))


def estimate(ar, video_id=None, mode=None, marks=None, top=None, doc_ids=None, overwrite=False, deliver=False):
    """AutoRunner.estimate の欄 -> POST /api/flow/estimate と同じ封筒 + 束の差分で(文書は 1 本ずつ見積もって足す = 画面と同じ)"""
    if doc_ids is not None:
        outs = [ar.estimate(*O.order("docs", doc_id=t, repack=overwrite)) for t in doc_ids]
        steps = [dict(s, count=sum(o["steps"][i]["count"] for o in outs)) for i, s in enumerate(outs[0]["steps"])]
        return dict(outs[0], steps=steps, total=sum(o["total"] for o in outs), nothing=all(o["nothing"] for o in outs))
    if mode not in A.MODES and mode != EXPORT:
        raise ValueError("実行の形が正しくありません")
    full = mode == "full"
    dl = {"origin": "auto", "deliver_dir": "D:/out"} if deliver and full else {}
    return ar.estimate(*O.order("url", video_id=video_id, from_=None if full else "export", upto="pack",
                                top=top, marks=marks, repack=overwrite, **dl))


def start_request(ar, items, **kw):
    return IN.submit_urls(ar, items, **kw)


def start_file(ar, path, title="", streamer=None, request_id=None, flow="check", deliver_dir=None, speakers=None, video_tracks=None, cut=None,
               engine=None, model=None, pool=None, normalize=True):
    """友人の動画の依頼(intake.submit_file)・ライブの書き出しの受け渡し(engine・model・pool。live_export.file_order と同じ欄)"""
    env, diff = O.order("file", path=path, title=title or __import__("os").path.basename(str(path)), normalize=normalize, upto="pack" if flow == "auto" else "transcribe",
                        streamer=streamer, request_id=request_id, deliver_dir=deliver_dir, speakers=speakers, video_tracks=video_tracks, cut=cut,
                        engine=engine, model=model, pool=pool)
    return ar.submit(env, diff)


def _fake_preview(video, out, **kw):
    """確認用の動画は ffmpeg を使うので偽物(中身は test_deliver の DeliverRun.test_deliver_run が本物の ffmpeg で確かめる)。差し替えは Base.setUp で(テストの間だけ。
    モジュールの読み込み時に差し替えると、同じプロセスで流す test_deliver の本物のテストまで偽物になる)"""
    with open(out, "wb") as f:
        f.write(b"PREVIEW")
    return True

VID = "abcdefghijk"


def write_old_pool(path, key, rid, title, deliver_dir, batch, recording, packs):
    """古い形の溜め(deliver-pool.json。組の batch 入り・ライブの録画 recording の分)を 1 つ置く"""
    testkit.write_json(path, {"schema": DL.POOL_SCHEMA, "pools": {key: {
        "rid": rid, "title": title, "deliverDir": deliver_dir, "batch": batch, "meta": {"recorder": "local", "recording": recording, "phase": "live"},
        "packs": packs, "delivered": [], "marks": {}, "created": 0, "updated": 0}}})


def AN(**kw):
    """解析の要求の settings(束の analyze 節 = 既定の全部に、変えた所を重ねた物。全部の項目を渡す)"""
    return dict(SP.DEFAULTS["analyze"], **kw)


_REAL_TOOL_SETTINGS = A.AutoRunner._tool_settings


def _fake_tool_settings(runner):
    """FakeTools のときは、その画面の設定(GET /api/settings の真似と同じ値)から束を組む。ほかは本物(作業データのファイル)"""
    c = runner.client
    if isinstance(c, FakeTools):
        return c.h_studio_GET_api_settings("", None)[1]["settings"], c.h_transcribe_GET_api_settings("", None)[1]
    return _REAL_TOOL_SETTINGS(runner)


_REAL_MEMO = A.MEMO_SEC


def setUpModule():
    A.AutoRunner._tool_settings = _fake_tool_settings
    A.MEMO_SEC = 0   # 受付の覚え(1 回の受付の間だけ)は TestMemo で。ほかは設定を変えたらすぐ効く


def tearDownModule():
    A.AutoRunner._tool_settings = _REAL_TOOL_SETTINGS
    A.MEMO_SEC = _REAL_MEMO


class FakeTools:
    """3ツールの API の最小の真似。ジョブは poll のたびに1段進む"""

    def __init__(self, tmp, marks, analysis=True):
        self.tmp = tmp
        self.c2r_dir = os.path.join(tmp, "cut2resolve")   # パックを作った記録(flow/packrec)の置き場所 = Base が YTT_CUT2RESOLVE_DIR に入れる
        self.txdir = os.path.join(tmp, "txdata", "transcripts")
        os.makedirs(self.txdir)
        self.video = {"id": VID, "kind": "youtube", "title": "配信A", "analysis": {"at": 1} if analysis else None, "marks": marks}
        self.calls = []
        self.export_busy = 0      # この回数だけ 409 busy を返す
        self.export_job = None
        self.export_one = False   # True = 書き出しは 1 回の問い合わせで 1 本ずつ進む(流れ作業のテスト)
        self.export_stop = None   # この本数が済んだら書き出しを進めない
        self.queue = []
        self.tx_jobs = {}
        self.c2r = {}
        self.edits = {}           # 「編集」のカット(文書の id → GET /api/edit の応答)
        self.packed = []          # POST /api/edit/pack
        self.fail_tx = False
        self.hold = False         # True のあいだジョブを進めない(中止のテスト)
        self.hold_q = False       # True のあいだ解析だけ進めない(起動し直すの確かめ = TestRestartInfo)
        self.review = {"precision": "fast", "maxHeight": 720, "exportVolume": 60, "exportLoudness": -16}
        self.analyze = None       # スタジオの画面で保存した解析の設定(settings.analyze)
        self.row_edge = None      # 「編集」の「行から」の設定(文字起こしの settings.rowEdge。⑥)
        self.subtitle = None      # 字幕の文字数の設定(文字起こしの settings.subtitle。②)
        self.tx_extra = {}        # そのほかの編集の設定(speakerColors・packLoudness・packVolume)
        self.known = True         # False = スタジオにまだ無い配信(① 探す から。解析のキューに入れるとできる)
        self.fail_pack = set()    # この動画のパックは失敗させる(失敗したときの動きのテスト)

    def clip_path(self, mid):
        return os.path.join(self.tmp, "out", mid + ".mp4")

    def call(self, tool, method, path, body=None):
        self.calls.append((tool, method, path, json.loads(json.dumps(body)) if body is not None else None))
        key = (tool, method, path.split("?")[0])
        h = getattr(self, "h_%s_%s_%s" % (tool, method, path.split("?")[0].strip("/").replace("/", "_").replace("-", "_")), None)
        if h is None:
            return 404, {"error": "not_found", "message": "なし %s" % (key,)}
        return h(path, body)

    def ok(self, tool, method, path, body=None):
        st, obj = self.call(tool, method, path, body)
        if st != 200:
            raise A.StepError(obj.get("message"))
        return obj

    # studio
    def h_studio_GET_api_video(self, path, body):
        if not self.known:
            return 404, {"error": "not_found", "message": "動画が見つかりません"}
        return 200, {"video": json.loads(json.dumps(self.video))}

    def h_studio_GET_api_settings(self, path, body):
        s = {"review": self.review}
        if self.analyze is not None:
            s["analyze"] = self.analyze
        return 200, {"settings": s}

    def h_studio_POST_api_queue_add(self, path, body):
        self.known = True
        qid = "q%d" % (len(self.queue) + 1)
        self.queue.append({"qid": qid, "videoId": VID, "status": "running", "progress": 0.0, "phase": "解析"})
        return 200, {"added": [{"qid": qid, "videoId": VID}], "rejected": []}

    def h_studio_POST_api_queue_cancel(self, path, body):
        for q in self.queue:
            if q["qid"] == body.get("qid") and q["status"] == "running":
                q["status"] = "cancelled"
        return 200, {"ok": True}

    def h_studio_GET_api_queue(self, path, body):
        for q in self.queue:
            if q["status"] == "running" and not self.hold and not self.hold_q:
                q["status"], q["marks"] = "done", 3
                self.video["analysis"] = {"at": 2}
                self.video["marks"] += [{"id": "a%d" % i, "src": "auto", "status": "", "score": s, "start": i * 10, "end": i * 10 + 5}
                                        for i, s in ((1, 2.0), (2, 9.0), (3, 5.0))]
        return 200, {"items": self.queue}

    def h_studio_POST_api_video_request_marks(self, path, body):
        """採用(F-5。スタジオの store.adopt_marks の真似): 区間を採用済みの手動マークに(同じ区間は使い回す)・人の採用(adoptedBy なし)を数に入れ・
        上限 top までの残りを自動の上位(不採用でない・区間と人の採用に重ならないもの)で埋める"""
        self.known = True
        self.request_marks = body
        rids, added = [], []
        for s, e in body["ranges"]:
            m = next((x for x in self.video["marks"] if abs(x["start"] - s) <= 0.5 and abs(x["end"] - e) <= 0.5), None)
            if m is None:
                m = {"id": "r%d" % (len(self.video["marks"]) + 1), "src": "manual", "status": "adopted", "score": None, "start": s, "end": e,
                     "adoptedBy": "request"}
                self.video["marks"].append(m)
                added.append(m["id"])
            elif m["status"] in ("", "rejected"):
                m["status"], m["adoptedBy"] = "adopted", "request"
                added.append(m["id"])
            rids.append(m["id"])
        hids = [m["id"] for m in self.video["marks"] if m["status"] in ("adopted", "exported") and not m.get("adoptedBy") and m["id"] not in rids]
        taken = [m for m in self.video["marks"] if m["id"] in rids or m["id"] in hids]
        autos = sorted((m for m in self.video["marks"] if m.get("src") == "auto" and m["status"] != "rejected" and m not in taken
                        and not any(m["start"] < t["end"] and t["start"] < m["end"] for t in taken)),
                       key=lambda m: -m["score"])[:max(0, body["top"] - len(taken))]
        for m in autos:
            if m["status"] == "":
                m["status"], m["adoptedBy"] = "adopted", "auto"
                added.append(m["id"])
        return 200, {"ok": True, "rangeIds": rids, "humanIds": hids, "autoIds": [m["id"] for m in autos], "added": added, "video": self.video}

    def h_studio_POST_api_export(self, path, body):
        if self.export_busy:
            self.export_busy -= 1
            return 409, {"error": "busy", "message": "別の書き出しが実行中です"}
        self.export_body = body
        self.export_job = {"id": "e1", "state": "running", "items": [{"id": i, "status": "queued"} for i in body["markIds"]]}
        return 200, self.export_job

    def h_studio_GET_api_export(self, path, body):
        j = self.export_job
        if j["state"] == "running" and not self.hold:
            todo = [it for it in j["items"] if it["status"] != "done"]
            if self.export_stop is not None and len(j["items"]) - len(todo) >= self.export_stop:
                return 200, j   # export_stop 本で止まる(流れ作業の中止のテスト)
            for it in todo[:1] if self.export_one else todo:
                it["status"] = "done"
                p = self.clip_path(it["id"])
                os.makedirs(os.path.dirname(p), exist_ok=True)
                with open(p, "wb") as f:
                    f.write(b"x")
                m = next(m for m in self.video["marks"] if m["id"] == it["id"])
                m.update(status="exported", path=p)
                it["path"] = p
            if all(it["status"] == "done" for it in j["items"]):
                j["state"] = "done"
        return 200, j

    def h_studio_POST_api_export_cancel(self, path, body):
        self.export_job["state"] = "cancelled"
        return 200, {"ok": True}

    # transcribe
    def h_transcribe_GET_api_settings(self, path, body):
        s = {"model": "small", "language": "ja", "boost": True, "secret": "使わない", "goalHours": 3}
        if self.row_edge is not None:
            s["rowEdge"] = self.row_edge
        if self.subtitle is not None:
            s["subtitle"] = self.subtitle
        s.update(self.tx_extra)
        return 200, s

    def h_transcribe_POST_api_transcribe(self, path, body):
        self.tx_at_export = getattr(self, "tx_at_export", None) or (self.export_job or {}).get("state")   # 最初に頼んだときの書き出しの状態
        jid = "t%d" % (len(self.tx_jobs) + 1)
        self.tx_jobs[jid] = {"id": jid, "state": "queued", "src": body["sourcePath"], "body": body}
        return 200, {"id": jid}

    def h_transcribe_GET_api_jobs(self, path, body):
        for j in self.tx_jobs.values():
            if j["state"] in ("queued", "running") and not self.hold:
                if self.fail_tx:
                    j["state"], j["error"] = "error", "モデルが読めません"
                    continue
                j["state"] = "done"
                tid = j["body"].get("intoDoc") or ("%012d" % int(j["id"][1:]))   # intoDoc = 行の無い文書に入れる(⑦(b))
                testkit.write_json(os.path.join(self.txdir, tid + ".json"), {"id": tid, "title": "題" + tid[-1], "sourcePath": j["src"], "updatedAt": 1,
                                                                            "segments": [{"start": 0, "end": 1, "text": "a"}]})
        return 200, {"jobs": list(self.tx_jobs.values())}

    def h_transcribe_POST_api_transcribe_cancel(self, path, body):
        self.tx_jobs[body["id"]]["state"] = "cancelled"
        return 200, {"ok": True}

    def h_transcribe_POST_api_export_file(self, path, body):
        return 200, {"path": os.path.join(self.tmp, body["id"] + ".transcript.json")}

    def h_transcribe_GET_api_edit(self, path, body):
        tid = path.split("id=", 1)[1]
        return 200, self.edits.get(tid, {"edit": None, "rev": 0})

    def h_transcribe_POST_api_edit_pack(self, path, body):
        self.packed.append(body)
        return 200, {"ok": True, "packRev": body["rev"]}

    # cut2resolve
    def h_cut2resolve_POST_api_build(self, path, body):
        self.c2r["body"] = body
        self.c2r.setdefault("bodies", []).append(body)
        self.c2r["job"] = {"id": "c1", "state": "running"}
        return 200, {"job": self.c2r["job"]}

    def h_cut2resolve_GET_api_job(self, path, body):
        if not self.hold and self.c2r["body"]["spec"]["video"] in self.fail_pack:
            self.c2r["job"].update(state="error", error={"message": "わざと失敗"})
            return 200, self.c2r["job"]
        if not self.hold:
            self.c2r["job"]["state"] = "done"
            v = self.c2r["body"]["spec"]["video"]
            d = os.path.splitext(v)[0] + "_pack"
            os.makedirs(d, exist_ok=True)
            open(os.path.join(d, "cut-plan.json"), "w").close()
            with open(os.path.join(d, os.path.basename(v)), "wb") as f:   # 切り抜きの動画の写し(確認用の動画の材料)
                f.write(b"v")
            self.mark_pack(d, [os.path.join(d, os.path.basename(v))], v)
            self.c2r["job"]["result"] = {"outDir": d, "files": [{"name": "cut-plan.json"}, {"name": "m1.edl"}]}
        return 200, self.c2r["job"]

    def mark_pack(self, d, files, video=""):
        """パックを作った記録を書く(本物の cut2resolve の after_build の代わり。「パック済み」は記録で決める = txindex.pack_info)"""
        packrec.write_record({"out_dir": d, "files": [("video", f) for f in files]}, video, False, c2r_dir=self.c2r_dir)


class Base(unittest.TestCase):
    marks = [{"id": "m1", "status": "adopted", "start": 1, "end": 5}, {"id": "m2", "status": "", "start": 9, "end": 12}]
    analysis = True

    def setUp(self):
        self.tmp = testkit.tempdir(self)
        self.addCleanup(setattr, pv, "make_preview", pv.make_preview)
        pv.make_preview = _fake_preview
        self.tools = FakeTools(self.tmp, json.loads(json.dumps(self.marks)), self.analysis)
        c2r_env = mock.patch.dict(os.environ, {"YTT_CUT2RESOLVE_DIR": self.tools.c2r_dir})   # find_pack は env を渡さずに読む(リポジトリの .data に書かない)
        c2r_env.start()
        self.addCleanup(c2r_env.stop)
        self.env = {"TRANSCRIBE_DATA_DIR": os.path.join(self.tmp, "txdata"), "YTT_DATA_DIR": os.path.join(self.tmp, "data")}
        self.r = self.make_runner()

    def tearDown(self):
        self.r.close()   # 一時フォルダは testkit.tempdir が後で消す

    def make_runner(self, **kw):
        """偽のツールにつないだ AutoRunner(既定は待たない・パックは案件の find_pack で探す)。kw は log_dir・prefs・sleep など"""
        kw.setdefault("sleep", lambda s: None)
        kw.setdefault("find_pack", A.txindex.pack_info)
        return A.AutoRunner(self.tools, os.path.join(self.tmp, "repo"), self.env, poll=0, **kw)

    def until(self, fn, timeout=10):
        """fn() が真になるまで待ってその値を返す(間に合わなければ落とす)"""
        end = time.time() + timeout
        while time.time() < end:
            v = fn()
            if v:
                return v
            time.sleep(0.01)
        self.fail("待ちきれません")

    def wait(self, run, timeout=10):
        """実行(一覧の dict)が終わるまで待って、終わったときの一覧の dict を返す"""
        def cur():
            x = next(x for x in self.r.snapshot()["runs"] if x["id"] == run["id"])
            return x if x["state"] not in ("queued", "running") else None
        return self.until(cur, timeout)

    def run_one(self, mode, top=None, timeout=10):
        return self.wait(start(self.r, VID, mode, top), timeout)

    def states(self, run):
        return {s["key"]: s["state"] for s in run["steps"]}

    def set_prefs(self, **autorun):
        """ホームの設定(一時フォルダの prefs.json)を実行の側に付ける。autorun = autorun 節に重ねる値"""
        p = prefs_mod.Prefs(os.path.join(self.tmp, "prefs.json"), fsio.atomic_write)
        if autorun:
            p.patch("autorun", autorun)
        self.r.prefs = p
        return p

    def empty(self, name):
        """一時フォルダに空のファイル(偽の動画)を置いてパスを返す"""
        path = os.path.join(self.tmp, name)
        open(path, "wb").close()
        return path

    def file_run(self, name, **kw):
        """空の動画 name を置いて動画の依頼(start_file)を 1 本流し、終わった実行を返す"""
        return self.wait(start_file(self.r, self.empty(name), **kw))

    def sub_calls(self):
        """字幕の色を覚える API(POST /api/speakers/sub)の呼ばれ方"""
        return [c for c in self.tools.calls if c[2] == "/api/speakers/sub"]

    def use_members(self):
        """配信者の色の一覧(兎田ぺこら 1 人)を一時フォルダに置いて使わせる"""
        self.env["YTT_HOLO_MEMBERS"] = testkit.write_json(os.path.join(self.tmp, "members.json"), {"groups": [{"name": "3期生", "members": [
            {"id": "usada-pekora", "name": "兎田ぺこら", "en": "Usada Pekora", "hex": "#7EC2FE"}]}]})

    def jobs_with_tid(self):
        """本物の「編集」のジョブは、できた文書の id(tid)を返す。偽の一覧にそれを足す"""
        jobs = self.tools.h_transcribe_GET_api_jobs

        def with_tid(path, body):
            st, obj = jobs(path, body)
            for j in obj["jobs"]:
                if j["state"] == "done":
                    j["tid"] = "%012d" % int(j["id"][1:])
            return st, obj
        self.tools.h_transcribe_GET_api_jobs = with_tid


class TestMarks(Base):
    """スタジオのマークの行の「この後を」:そのマークだけ 書き出し → 文字起こし → パック"""
    marks = [{"id": "m1", "status": "adopted", "start": 1, "end": 5}, {"id": "m3", "status": "adopted", "start": 20, "end": 25},
             {"id": "m2", "status": "", "start": 9, "end": 12}]

    def test_only_selected_mark(self):
        run = start(self.r, VID, "export", marks=["m3", "m3"])
        self.assertEqual((run["marks"], run["modeLabel"]), (["m3"], "書き出しから全部(1本)"))
        run = self.wait(run)
        self.assertEqual(run["state"], "done", run)
        self.assertEqual(self.tools.export_body["markIds"], ["m3"])                                   # 採用した m1 は書き出さない
        self.assertEqual([j["src"] for j in self.tools.tx_jobs.values()], [self.tools.clip_path("m3")])
        self.assertEqual([b["spec"]["video"] for b in self.tools.c2r["bodies"]], [self.tools.clip_path("m3")])
        # 書き出し済みのマークなら、文字起こし → パックだけ(書き出しは飛ばす)
        run = self.wait(start(self.r, VID, "export", marks=["m3"]))
        self.assertEqual({s["key"]: s["state"] for s in run["steps"]}["export"], "skip")

    def test_bad_marks(self):
        with self.assertRaisesRegex(ValueError, "マークの指定"):   # 形の違いは tests/flow/test_spec.py の test_marks_arg
            start(self.r, VID, "export", marks=["../x"])
        with self.assertRaisesRegex(ValueError, "書き出しから"):
            start(self.r, VID, "full", marks=["m1"])
        self.assertEqual(self.r.snapshot()["runs"], [])


class TestDocs(Base):
    """文書単位の実行(notes:docs/design/edit-tool-design.md の 12 ⑦(b)): 「編集」の履歴で選んだ文書を、行が無ければ文字起こし → パック"""

    def setUp(self):
        super().setUp()
        self.media = {}
        for tid, rows in (("aaaaaaaaaaa1", []), ("bbbbbbbbbbb2", [{"start": 0, "end": 2, "text": "こんにちは"}])):
            m = self.empty(tid + ".mp4")
            self.media[tid] = m
            testkit.write_json(os.path.join(self.tools.txdir, tid + ".json"), {"id": tid, "title": "文書" + tid[-1], "sourcePath": m, "updatedAt": 5, "segments": rows})

    def wait_all(self, runs, timeout=10):
        return {x["docId"]: x for x in (self.wait(r, timeout) for r in runs)}

    def test_transcribe_then_pack(self):
        res = start_docs(self.r, ["aaaaaaaaaaa1", "bbbbbbbbbbb2", "aaaaaaaaaaa1"])   # 同じ id を二度渡しても1つ
        self.assertEqual((len(res["runs"]), res["skipped"]), (2, []))
        self.assertEqual((res["runs"][0]["kind"], res["runs"][0]["modeLabel"]), ("doc", "文字起こし → パック"))
        got = self.wait_all(res["runs"])
        a, b = got["aaaaaaaaaaa1"], got["bbbbbbbbbbb2"]
        self.assertEqual((a["state"], [s["state"] for s in a["steps"]]), ("done", ["done", "done"]), a)
        self.assertEqual([s["state"] for s in b["steps"]], ["skip", "done"], b)          # 行がある文書は文字起こしを飛ばす
        tx = next(j for j in self.tools.tx_jobs.values())
        self.assertEqual(tx["body"]["intoDoc"], "aaaaaaaaaaa1")                           # 同じ文書に入れる
        self.assertEqual(sorted(b_["spec"]["video"] for b_ in self.tools.c2r["bodies"]), sorted(self.media.values()))

    def test_streamer_color_is_passed(self):
        """配信者の名前(字幕の文字の色): 照らし合わせた名前を cut2resolve に渡す(断り方は TestSubmitBase.test_streamer_checked_unless_friend)"""
        self.use_members()
        res = start_docs(self.r, ["bbbbbbbbbbb2"], streamer="ぺこら")
        self.assertEqual(res["runs"][0]["streamer"], "兎田ぺこら")
        self.wait_all(res["runs"])
        self.assertEqual(self.tools.c2r["bodies"][-1]["output"]["streamer"], "兎田ぺこら")
        res = start_docs(self.r, ["bbbbbbbbbbb2"], overwrite=True)                          # 入れなければ渡さない(黒い文字)
        self.wait_all(res["runs"])
        self.assertNotIn("streamer", self.tools.c2r["bodies"][-1]["output"])

    def test_missing_doc_is_skipped(self):
        self.tools.hold = True
        res = start_docs(self.r, ["bbbbbbbbbbb2", "zzzz"])
        self.assertEqual(([x["docId"] for x in res["runs"]], [(x["id"], x["reason"]) for x in res["skipped"]]),
                         (["bbbbbbbbbbb2"], [("zzzz", "文書が見つかりません")]))
        for r in res["runs"]:
            self.r.cancel(r["id"])
        self.tools.hold = False

    def test_existing_pack_is_skipped_unless_overwrite(self):
        d = os.path.splitext(self.media["bbbbbbbbbbb2"])[0] + "_pack"
        os.makedirs(d)
        with open(os.path.join(d, "clip.mp4"), "wb") as f:
            f.write(b"v")
        self.tools.mark_pack(d, [os.path.join(d, "clip.mp4")], self.media["bbbbbbbbbbb2"])
        got = self.wait_all(start_docs(self.r, ["bbbbbbbbbbb2"])["runs"])
        st = got["bbbbbbbbbbb2"]["steps"][1]
        self.assertEqual(st["state"], "skip")
        self.assertIn("パック済み", st["detail"])
        self.assertNotIn("bodies", self.tools.c2r)
        got = self.wait_all(start_docs(self.r, ["bbbbbbbbbbb2"], overwrite=True)["runs"])
        self.assertEqual(got["bbbbbbbbbbb2"]["steps"][1]["state"], "done")
        self.assertTrue(self.tools.c2r["bodies"][-1]["output"]["force"])                  # 作り直す = 上書き

    def test_missing_media_stops(self):
        os.unlink(self.media["bbbbbbbbbbb2"])
        got = self.wait_all(start_docs(self.r, ["bbbbbbbbbbb2"])["runs"])
        self.assertEqual(got["bbbbbbbbbbb2"]["state"], "error")
        self.assertIn("元の動画が見つかりません", got["bbbbbbbbbbb2"]["error"])


class TestModes(Base):
    def test_spec_is_built_at_accept(self):
        """束は受けたときに組む = 待ちの間に画面の設定を変えても、その実行の中身は変わらない(意図した変化)"""
        self.tools.tx_extra = {"model": "large-v3"}
        with mock.patch.object(self.r, "_wake", lambda: None):   # 糸を起こさない = 待ちのまま
            run = start(self.r, VID, "export")
        queued = next(r for r in self.r.runs if r.id == run["id"])
        self.assertEqual((queued.state, queued.spec["transcribe"]["model"]), ("queued", "large-v3"))
        self.tools.tx_extra = {"model": "small"}   # 待ちの間に設定を変えた
        with self.r.cv:
            self.r._wake()
        self.until(lambda: queued.state not in ("queued", "running"))
        self.assertEqual(queued.state, "done", queued.public())
        self.assertEqual(self.tools.tx_jobs["t1"]["body"]["model"], "large-v3")

    def test_cut_method_none_for_docs_without_cut(self):
        """カットを決めていない文書のカットの方法(ホームの設定 autorun.cut): none = 動画全体・カット済の行の字幕も消さない"""
        self.set_prefs(cut="none")
        run = self.run_one("export")
        self.assertEqual(run["state"], "done", run)
        spec = self.tools.c2r["body"]["spec"]
        self.assertEqual((spec["mode"], spec["listKind"], spec["listText"], spec["dropCutRows"], "preset" in spec), ("list", "drop", "", False, False))

    def test_cut_method_silence_uses_edit_settings(self):
        self.set_prefs(cut="silence")
        self.tools.tx_extra = {"cutSilence": {"noise": -40, "min": 0.8, "pad": 0.2, "x": 1, "pad2": True}}
        run = self.run_one("export")
        self.assertEqual(run["state"], "done", run)
        spec = self.tools.c2r["body"]["spec"]
        self.assertEqual((spec["mode"], spec["silence"]), ("silence", {"noise": -40, "min": 0.8, "pad": 0.2}))

    def test_cut_method_default_is_none(self):
        run = self.run_one("export")   # ホームの設定が無いときはカットしない
        self.assertEqual(self.tools.c2r["body"]["spec"]["mode"], "list")
        out = self.tools.c2r["body"]["output"]
        self.assertEqual((out["speakerColors"], out.get("loudness"), out.get("volume")), (True, None, 30))   # 既定: 色あり・音量 30%

    def test_adopted_mode_exports_transcribes_and_packs(self):
        """採用後を全部の代表。画面の設定は受付で読まれ、パックの本文まで届く(代表の 1 値 = 縦の 1 段の文字数。読み方の表は TestSpecFromSettings)"""
        self.set_prefs(cut="rows")
        self.tools.subtitle = {"wrapChars": {"vertical": 9, "horizontal": 14}}
        run = self.run_one("export")
        self.assertEqual(run["state"], "done", run)
        self.assertEqual(self.states(run), {"export": "done", "transcribe": "done", "pack": "done"})
        self.assertEqual((self.tools.export_body["markIds"], self.tools.export_body["volume"]), (["m1"], 60))   # スタジオの設定の音量
        self.assertEqual(self.tools.tx_jobs["t1"]["body"]["sourcePath"], self.tools.clip_path("m1"))
        self.assertNotIn("secret", self.tools.tx_jobs["t1"]["body"])   # 知らない設定は渡さない
        self.assertEqual(self.tools.c2r["body"]["spec"]["preset"], "transcript-rows")
        self.assertIs(self.tools.c2r["body"]["spec"]["rowEdge"], True)   # 設定が無ければ束の既定 = cut2resolve の既定(端を広げる)
        self.assertEqual((self.tools.c2r["body"]["output"]["textplus"], self.tools.c2r["body"]["output"]["textplusWrap"]), (True, 9))
        # もう一度押しても、作り直さない(まだ無いものだけ)
        n = len(self.tools.calls)
        again = self.run_one("export")
        self.assertEqual(self.states(again), {"export": "skip", "transcribe": "skip", "pack": "skip"})
        self.assertFalse(any(c[1] == "POST" for c in self.tools.calls[n:]), "2回目は何も作らない")

    def test_pack_follows_edit_cut(self):
        """「編集」でカットを決めてある文書は、そのカットのとおりに作る(spec.keeps。接している区間は1つに)・作った記録を「編集」に残す"""
        self.run_one("export")   # 書き出し → 文字起こし → パック(カットなし)
        tid = "%012d" % 1
        self.tools.edits[tid] = {"rev": 3, "edit": {"clips": [{"src": 0, "in": 0.5, "out": 1.0}, {"src": 0, "in": 1.0, "out": 2.0}, {"src": 0, "in": 3.0, "out": 4.0}]}}
        self.tools.packed.clear()
        run = self.wait(start(self.r, VID, "export", overwrite=True))   # カットを決めたので作り直す
        self.assertEqual(self.states(run)["pack"], "done", run)
        b = self.tools.c2r["body"]
        self.assertEqual((b["spec"]["keeps"], "preset" in b["spec"], b["spec"]["transcript"].endswith(tid + ".transcript.json"), b["output"]["textplus"]),
                         ([[0.5, 2.0], [3.0, 4.0]], False, True, True))
        self.assertEqual([(p["id"], p["rev"], p["files"]) for p in self.tools.packed], [(tid, 3, ["cut-plan.json", "m1.edl"])])
        self.assertIn("カットのとおり", next(s for s in run["steps"] if s["key"] == "pack")["detail"])

    def test_nothing_adopted_stops_early(self):
        for m in self.tools.video["marks"]:
            m["status"] = ""
        run = self.run_one("export")
        self.assertEqual(run["state"], "done")
        self.assertEqual(self.states(run), {"export": "skip", "transcribe": "skip", "pack": "skip"})

    def test_waits_while_studio_export_is_busy(self):
        self.tools.export_busy = 3
        run = self.run_one("export")
        self.assertEqual(run["state"], "done")
        self.assertEqual(sum(1 for c in self.tools.calls if c[2] == "/api/export" and c[1] == "POST"), 4)

    def test_transcribe_failure_stops_the_run(self):
        self.tools.fail_tx = True
        run = self.run_one("export")
        self.assertEqual((run["state"], self.states(run)["transcribe"], self.states(run)["pack"]), ("error", "error", "wait"))
        self.assertIn("モデルが読めません", run["error"])

    def test_tool_not_running(self):
        r = A.AutoRunner(A.ToolClient(lambda t: None), self.tmp, self.env, poll=0, sleep=lambda s: None, find_pack=lambda p: None)
        try:
            start(r, VID, "export")
            got = self.until(lambda: (lambda x: x if x["state"] not in ("queued", "running") else None)(r.snapshot()["runs"][0]))
            self.assertEqual(got["state"], "error")
            self.assertIn("切り抜きスタジオが動いていないので、この段を進められませんでした", got["error"])
        finally:
            r.close()


class TestFull(Base):
    marks = []
    analysis = False

    def test_full_mode_analyzes_and_adopts_top(self):
        run = self.run_one("full", top=2)
        self.assertEqual(run["state"], "done", run)
        self.assertEqual(self.states(run), {"analyze": "done", "adopt": "done", "export": "done", "transcribe": "done", "pack": "done"})
        self.assertEqual(sorted(self.tools.export_body["markIds"]), ["a2", "a3"])   # 点数の高い2件(9.0・5.0)
        add = [c for c in self.tools.calls if c[2] == "/api/queue/add"]
        self.assertEqual(add[0][3], {"items": [{"kind": "youtube", "videoId": VID}], "settings": AN(fill=2)})   # 保存した設定が無ければ既定値(束の既定 = スタジオの既定)。fill = 採用の上限(足りなければ埋める)


class TestNew(Base):
    """スタジオの ① 探す で選んだ配信:まだスタジオに無い配信を「解析から全部」"""
    marks = []
    analysis = False

    def setUp(self):
        super().setUp()
        self.tools.known = False

    def test_new_stream_goes_through_everything(self):
        res = start_new(self.r, [{"id": VID, "title": " 新しい配信 ", "channel": "ch"}], top=2)
        self.assertEqual(res["skipped"], [])
        run = res["runs"][0]
        self.assertEqual((run["mode"], run["title"], run["fromSearch"], run["top"]), ("full", "新しい配信", True, 2))
        run = self.wait(run)
        self.assertEqual(run["state"], "done", run)
        self.assertEqual(self.states(run), {"analyze": "done", "adopt": "done", "export": "done", "transcribe": "done", "pack": "done"})
        add = [c for c in self.tools.calls if c[2] == "/api/queue/add"]
        self.assertEqual(add[0][3]["items"], [{"kind": "youtube", "videoId": VID, "title": "新しい配信", "channel": "ch"}])   # 題名・配信者も渡す
        self.assertEqual(run["title"], "配信A")   # 解析のあとはスタジオの題名

    def test_already_known_stream_is_the_same_as_full(self):
        """スタジオにもうある(解析済み)配信は、解析を飛ばして続きから"""
        self.tools.known, self.tools.video["analysis"] = True, {"at": 1}
        self.tools.video["marks"] = [{"id": "a1", "src": "auto", "status": "", "score": 3.0, "start": 1, "end": 5}]
        run = self.wait(start_new(self.r, [{"id": VID, "title": "x"}])["runs"][0])
        self.assertEqual((run["state"], self.states(run)["analyze"]), ("done", "skip"), run)
        self.assertFalse([c for c in self.tools.calls if c[2] == "/api/queue/add"])

    def test_same_stream_is_skipped(self):
        self.tools.hold = True
        res = start_new(self.r, [{"id": VID, "title": "A"}, {"id": VID, "title": "A2"}])
        self.assertEqual((len(res["runs"]), [s["reason"] for s in res["skipped"]]), (1, ["同じ入力がすでに実行中・順番待ちです"]))
        with self.assertRaisesRegex(ValueError, "すでに実行中"):   # もう順番待ち・実行中(全部断られた = 画面は理由を出す)
            start_new(self.r, [{"id": VID}])
        with self.assertRaises(ValueError):
            start(self.r, VID, "export")        # 配信の画面からの実行とも重ねない


class TestPipeTx(Base):
    """流れ作業(flow/run.PIPE_TX): 書き出しの 1 本が済むたびに、その本の文字起こしを先に頼む。文字起こしの段はそのジョブを待つ"""
    marks = [{"id": "m1", "status": "adopted", "start": 1, "end": 5}, {"id": "m2", "status": "adopted", "start": 9, "end": 12}]

    def setUp(self):
        super().setUp()
        self.tools.export_one = True

    def tx_step(self, run):
        return next(s for s in run["steps"] if s["key"] == "transcribe")

    def test_transcribe_starts_while_exporting(self):
        self.jobs_with_tid()
        run = self.run_one("export")
        self.assertEqual((run["state"], self.states(run)), ("done", {"export": "done", "transcribe": "done", "pack": "done"}), run)
        self.assertEqual(self.tools.tx_at_export, "running")   # 2 本目を書き出している間に 1 本目を頼んだ
        self.assertEqual(sorted(j["src"] for j in self.tools.tx_jobs.values()), [self.tools.clip_path("m1"), self.tools.clip_path("m2")])   # 二重に頼まない
        st = self.tx_step(run)
        self.assertEqual(st["early"], 2)
        self.assertLessEqual(st["earlyAt"], st["startedAt"])
        self.assertEqual(len(run["newDocs"]), 2)

    def test_switch_off_is_the_old_order(self):
        with mock.patch.object(RUN, "PIPE_TX", False):
            run = self.run_one("export")
        self.assertEqual((run["state"], self.tools.tx_at_export), ("done", "done"))
        self.assertNotIn("early", self.tx_step(run))

    def test_cancel_during_export_cancels_early_transcribe(self):
        self.tools.export_stop = 1
        run = start(self.r, VID, "export")
        self.until(lambda: self.tools.tx_jobs.get("t1"))
        self.r.cancel(run["id"])
        got = self.wait(run)
        self.assertEqual((got["state"], self.tools.tx_jobs["t1"]["state"], self.states(got)["transcribe"]), ("cancelled", "cancelled", "wait"))


class TestControl(Base):
    def test_same_video_twice_is_refused_and_cancel(self):
        self.tools.hold = True
        run = start(self.r, VID, "export")
        with self.assertRaises(ValueError):
            start(self.r, VID, "full")
        self.until(lambda: self.r.snapshot()["runs"][0]["steps"][0]["state"] == "run")
        self.r.cancel(run["id"])
        got = self.wait(run)
        self.assertEqual(got["state"], "cancelled")
        self.assertIn(("studio", "POST", "/api/export/cancel", {"id": "e1"}), self.tools.calls)   # ツールの側の書き出しも止める
        with self.assertRaises(ValueError):
            self.r.cancel("nothere")

    def test_queued_runs_stay_queued_on_close(self):
        """入口の終了(M5): 順番待ちは消さずに「待ち」のまま(次の起動で続ける)。実行中の段はツールの側も取り消して止める"""
        self.tools.hold = True
        first = start(self.r, VID, "export")
        second = start(self.r, "zzzzzzzzzzz", "export")
        self.until(lambda: self.r.snapshot()["runs"][-1]["steps"][0]["state"] == "run")
        self.r.close()
        self.until(lambda: not any(x["state"] == "running" for x in self.r.snapshot()["runs"]))
        got ={x["id"]: x for x in self.r.snapshot()["runs"]}
        self.assertEqual((got[second["id"]]["state"], got[second["id"]]["message"]), ("queued", "ホームを終了したので、次の起動で続けます"))
        self.assertEqual((got[first["id"]]["state"], got[first["id"]]["steps"][0]["state"]), ("queued", "wait"))   # 途中の段は次の起動で頭から
        self.assertIn(("studio", "POST", "/api/export/cancel", {"id": "e1"}), self.tools.calls)   # ツールの側の書き出しは止める

class TestStage4(Base):
    """パックの設定は編集の設定のとおり・「行から」の形・配信単位の上書き・失敗したとき・やることが無い・見積もり"""
    marks = [{"id": "m1", "status": "adopted", "start": 1, "end": 5}, {"id": "m3", "status": "adopted", "start": 20, "end": 25}]

    def test_bad_row_edge_is_reported_not_failed(self):
        """受付で直した設定の知らせ(run.notes)はパックの段の文に出る(直し方は TestSpecFromSettings)"""
        self.tools.row_edge = {"on": "yes"}
        run = self.run_one("export")
        self.assertEqual(run["state"], "done", run)
        self.assertIn("「行から」の設定の形が正しくない", next(s for s in run["steps"] if s["key"] == "pack")["detail"])

    def test_nothing_to_do_and_overwrite(self):
        first = self.run_one("export")
        self.assertEqual((first["state"], first["nothing"]), ("done", False))
        self.assertEqual(len(first["docs"]), 2)   # 文字起こし・パックした文書(終わったら「校正を始める」で開く)
        again = self.run_one("export")   # もうパックがある: やることが無い
        self.assertEqual((again["state"], again["nothing"]), ("done", True))
        n = len(self.tools.c2r["bodies"])
        run = self.wait(start(self.r, VID, "export", overwrite=True))   # 配信単位でも作り直せる
        self.assertEqual((run["state"], run["overwrite"]), ("done", True), run)
        self.assertEqual(len(self.tools.c2r["bodies"]), n + 2)
        self.assertTrue(all(b["output"].get("force") for b in self.tools.c2r["bodies"][n:]))
        self.assertEqual(next(s for s in run["steps"] if s["key"] == "pack")["stateLabel"], "済み")

    def test_on_fail_next_continues(self):
        self.tools.fail_pack = {self.tools.clip_path("m1")}
        run = self.run_one("export")
        self.assertEqual(run["state"], "done", run)
        pk = next(s for s in run["steps"] if s["key"] == "pack")
        self.assertEqual((pk["state"], pk["stateLabel"]), ("warn", "一部失敗"))
        self.assertIn("失敗した 1 本", pk["detail"])

    def test_on_fail_stop(self):
        self.set_prefs(onFail="stop")
        self.tools.fail_pack = {self.tools.clip_path("m1")}
        run = self.run_one("export")
        self.assertEqual((run["state"], run["stateLabel"], run["onFail"]), ("error", "失敗", "stop"), run)
        self.assertIn("わざと失敗", run["error"])

    def test_estimate(self):
        e = estimate(self.r, VID, "export")
        self.assertEqual([(s["key"], s["count"]) for s in e["steps"]], [("export", 2), ("transcribe", None), ("pack", None)])   # 書き出しのあとで決まる
        self.assertEqual((e["total"], e["nothing"]), (2, False))
        self.assertEqual(self.tools.c2r, {})                                                                               # 見積もりは何も作らない
        self.run_one("export")
        e = estimate(self.r, VID, "export")
        self.assertEqual((e["total"], e["nothing"]), (0, True))
        self.assertIn("パック済み", e["reason"])
        e = estimate(self.r, VID, "export", overwrite=True)
        self.assertEqual([s["count"] for s in e["steps"]], [0, 0, 2])
        tid = next(d["id"] for d in A.txindex.load(A.txindex.folder(self.r.root, self.env)))
        e = estimate(self.r, doc_ids=[tid])
        self.assertEqual(([s["count"] for s in e["steps"]], e["nothing"]), ([0, 0], True))
        self.assertEqual([s["count"] for s in estimate(self.r, doc_ids=[tid], overwrite=True)["steps"]], [0, 1])
        with self.assertRaises(ValueError):
            estimate(self.r, VID, "nope")
        e = estimate(self.r, VID, "full", deliver=True)   # 届け先があれば末尾に deliver の行(本数はパックのあと = None)
        self.assertEqual(e["steps"][-1], {"key": "deliver", "label": "Dropbox へ届ける", "count": None, "note": "パックのあとで決まります"})
        self.assertEqual([s["key"] for s in estimate(self.r, VID, "full")["steps"]], ["analyze", "adopt", "export", "transcribe", "pack"])
        self.assertEqual([s["key"] for s in estimate(self.r, VID, "export", deliver=True)["steps"]], ["export", "transcribe", "pack"])
        # 見積もりも実行と同じ判定(pack_verdict)で、鍵が違うパックは作り直す数に入れる
        self.assertEqual(estimate(self.r, VID, "export")["total"], 0)
        with mock.patch.object(self.r, "_pack_state", return_value=("differ", None)):
            e = estimate(self.r, VID, "export")
        self.assertEqual([s["count"] for s in e["steps"]], [0, 0, 2])
        with mock.patch.object(self.r, "_pack_state", return_value=("same", None)), mock.patch.object(self.r, "find_pack", return_value=None):
            e = estimate(self.r, VID, "export")   # 鍵が同じなら、パックの置き場所が見つからなくても飛ばす(実行と同じ)
        self.assertEqual([s["count"] for s in e["steps"]], [0, 0, 0])


class TestStage5(Base):
    """配信者を指定しない実行は、覚えた名前 → チャンネル名から自動で。空で送れば色なし"""

    def test_auto_from_channel(self):
        self.tools.video["channel"] = "Pekora Ch. 兎田ぺこら"
        run = self.run_one("export")
        self.assertEqual(run["state"], "done", run)
        self.assertEqual((self.tools.c2r["body"]["output"].get("streamer"), run["streamer"], run["streamerFrom"]), ("兎田ぺこら", "兎田ぺこら", "auto"))
        self.assertIn("字幕の色: 兎田ぺこら(自動: チャンネル名から)", next(s for s in run["steps"] if s["key"] == "pack")["detail"])

    def test_explicit_empty_is_no_color(self):
        self.tools.video["channel"] = "Pekora Ch. 兎田ぺこら"
        cur = self.wait(start(self.r, VID, "export", streamer=""))
        self.assertEqual(cur["state"], "done", cur)
        self.assertNotIn("streamer", self.tools.c2r["body"]["output"])   # 空 = 色なし(チャンネル名からも入れない)

    def test_decided_at_accept(self):
        """覚えた名前で決まる配信者は受付で決める(待ちの間に覚えた名前を変えても変わらない)。決まらなければ実行中に(上の 2 つ)"""
        p = self.set_prefs()
        p.remember("videos", VID, "さくらみこ")
        with mock.patch.object(self.r, "_wake", lambda: None):
            run = start(self.r, VID, "export")
        self.assertEqual((run["streamer"], run["streamerFrom"]), ("さくらみこ", "video"))
        p.remember("videos", VID, "兎田ぺこら")
        with self.r.cv:
            self.r._wake()
        cur = self.wait(run)
        self.assertEqual((cur["state"], self.tools.c2r["body"]["output"].get("streamer")), ("done", "さくらみこ"))
        self.assertEqual(p.get(["streamer"])["streamer"]["docs"], {})   # 推定した名前は文書に覚えない(今までどおり)


class TestRunLog(Base):
    """終わった実行の記録に、まとめて実行の配信の欄(kind video・videoId)が入る。書き方・past・history・回す・書けないときは
    tests/flow/test_runqueue.py の TestRunLog"""

    def test_video_run_is_written(self):
        logs = os.path.join(self.tmp, "logs")
        self.r.close()
        self.r = self.make_runner(log_dir=logs)
        run = self.run_one("export")
        got = self.until(lambda: runlog.read_runs_log(os.path.join(logs, runlog.RUNS_LOG)))
        self.assertEqual([(x["id"], x["state"], x["kind"], x["videoId"]) for x in got], [(run["id"], "done", "video", VID)])


class TestRestore(Base):
    """線 D の M5: 入口の起動し直しで、まとめて実行の待ち・実行中を戻す(logs/autorun-active.json)。
    同じ run(同じ id)のまま、済んだ段は飛ばして、途中だった段は頭からやり直す。記録(autorun-runs.jsonl)には終わったときの 1 行だけ"""
    marks = [{"id": "m1", "status": "adopted", "start": 1, "end": 5}]

    def setUp(self):
        super().setUp()
        self.r.close()
        self.logs = os.path.join(self.tmp, "logs")
        self.jobs_with_tid()
        self.r = self.runner()

    def runner(self):
        return self.make_runner(log_dir=self.logs)

    def snap(self, rid):
        return next((x for x in self.r.snapshot()["runs"] if x["id"] == rid), None)

    def finished(self, rid):
        """起動し直しのあとの同じ id の実行が終わるまで待つ(戻る前は一覧に無いことがある)"""
        return self.until(lambda: (lambda x: x if x and x["state"] not in ("queued", "running") else None)(self.snap(rid)))

    def active(self):
        try:
            with open(os.path.join(self.logs, A.ACTIVE_FILE), encoding="utf-8") as f:
                return json.load(f)["runs"]
        except FileNotFoundError:
            return []
        except PermissionError:   # 置き換えの最中(Windows。3.12 で当たりやすくなった)= まだ。until がもう一度読む
            return None

    def lines(self):
        return runlog.read_runs_log(os.path.join(self.logs, runlog.RUNS_LOG))

    def restart(self, saved=None):
        """入口を止めて起動し直す。saved: 強制終了のふり(止める前の待ちの記録に戻してから起動する)"""
        self.r.close()
        self.until(lambda: not any(x["state"] == "running" for x in self.r.snapshot()["runs"]))
        if saved is not None:
            testkit.write_json(os.path.join(self.logs, A.ACTIVE_FILE), {"v": A.ACTIVE_VERSION, "runs": saved})
        self.r = self.runner()

    def test_file_run_in_transcribe_continues_after_restart(self):
        """リアルタイム切り抜きの書き出し → まとめて実行(文字起こし → パック)の文字起こしの途中で入口を止めて起動し直すと、同じ run が続く"""
        media = self.empty("ライブ.mp4")
        self.tools.hold = True
        run = start_file(self.r, media, title="ライブの切り抜き", flow="auto", engine="whisper.cpp", model="large-v3", normalize=False)   # ライブの書き出しは 30fps 済み
        self.until(lambda: (self.snap(run["id"]) or {}).get("steps", [{}])[0].get("state") == "run")
        saved = self.until(self.active)
        self.assertEqual([(x["id"], x["state"], x["mode"], x["engine"], x["steps"][0]["state"]) for x in saved],
                         [(run["id"], "running", "file_auto", "whisper.cpp", "run")])
        self.restart()
        self.assertEqual(self.lines(), [])                                    # 入口の終了で止まった分は「中止」と書かない
        got = self.snap(run["id"])
        self.assertIn(got["state"], ("queued", "running"))                     # 同じ id のまま戻って、すぐ続きを始める
        self.assertEqual((got["engine"], got["model"], got["title"], got["mode"]), ("whisper.cpp", "large-v3", "ライブの切り抜き", "file_auto"))
        self.tools.hold = False
        done = self.finished(run["id"])
        self.assertEqual((done["state"], done["id"]), ("done", run["id"]), done)
        self.assertEqual(self.states(done), {"transcribe": "done", "pack": "done"})   # 届け先なし = 段 deliver なし
        tx = [j for j in self.tools.tx_jobs.values() if j["src"] == media]
        self.assertEqual([j["state"] for j in tx], ["cancelled", "done"])      # 止めた文字起こしは取り消して、頭からやり直した
        self.assertEqual((tx[-1]["body"]["engine"], tx[-1]["body"]["model"]), ("whisper.cpp", "large-v3"))   # 実行ごとのエンジン・モデルも戻る
        self.until(lambda: self.lines())
        self.assertEqual([(x["id"], x["state"]) for x in self.lines()], [(run["id"], "done")])   # 記録は終わったときの 1 行だけ
        self.until(lambda: self.active() == [])

    def test_crash_continues_from_saved_steps(self):
        """強制終了(待ちの記録だけが残る): 済んだ段(書き出し)は飛ばし、途中の段(文字起こし)から続ける"""
        tx_hold = {"on": True}   # 文字起こしだけ止めておく(書き出しは進める)
        jobs = self.tools.h_transcribe_GET_api_jobs
        self.tools.h_transcribe_GET_api_jobs = lambda p, b: (200, {"jobs": list(self.tools.tx_jobs.values())}) if tx_hold["on"] else jobs(p, b)
        run = start(self.r, VID, "export")
        saved = self.until(lambda: (lambda a: a if a and [s["state"] for s in a[0]["steps"][:2]] == ["done", "run"] else None)(self.active()))   # 段の間(1 段目が済み・2 段目はまだ wait)の記録を拾わない
        self.assertEqual([s["state"] for s in saved[0]["steps"]], ["done", "run", "wait"])
        exports = sum(1 for c in self.tools.calls if c[1:3] == ("POST", "/api/export"))
        self.restart(saved=saved)   # 強制終了のふり: 止める前の記録のまま起動する
        tx_hold["on"] = False
        done = self.finished(run["id"])
        self.assertEqual((done["state"], self.states(done)), ("done", {"export": "done", "transcribe": "done", "pack": "done"}), done)
        self.assertEqual(sum(1 for c in self.tools.calls if c[1:3] == ("POST", "/api/export")), exports)   # 書き出しはやり直さない
        self.assertEqual(done["steps"][0]["detail"], saved[0]["steps"][0]["detail"])                      # 済んだ段の結果の文もそのまま
        self.assertEqual([(x["id"], x["state"]) for x in self.until(self.lines)], [(run["id"], "done")])

    def test_tools_not_ready_yet(self):
        """起動し直してすぐ: 使うツールが動くまで待ってから始める(入口の起動の直後はまだ準備中のことがある)"""
        ready = {"studio": False}
        self.tools.endpoint = lambda t: (1, "/") if ready.get(t, True) else None
        self.r.close()
        run = RF.run_of(VID, "配信", "export", 3)
        testkit.write_json(os.path.join(self.logs, A.ACTIVE_FILE), {"v": A.ACTIVE_VERSION, "runs": [run.saved()]})
        with mock.patch.object(A, "RESUME_WAIT", 30):
            self.r = self.make_runner(sleep=lambda s: time.sleep(0.01), log_dir=self.logs)
            self.until(lambda: "ツールの準備を待っています(studio)" in ((self.snap(run.id) or {}).get("message") or ""))
            self.assertFalse(any(c[0] == "studio" for c in self.tools.calls))
            ready["studio"] = True
            done = self.finished(run.id)
        self.assertEqual(done["state"], "done", done)


class TestRestartInfo(Base):
    """画面の「起動し直す」の材料(restart_info): 待ち・実行中の数と、実行中の段がツールで動かしている仕事(書き出しの段は入れない)"""

    def step_state(self, key):
        runs = [x for x in self.r.snapshot()["runs"] if x["state"] == "running"]
        return next((s["state"] for s in runs[0]["steps"] if s["key"] == key), None) if runs else None

    def test_idle_and_export(self):
        self.assertEqual(self.r.restart_info(), {"runs": 0, "redo": None})
        self.tools.hold = True
        start(self.r, VID, "export")
        start(self.r, "zzzzzzzzzzz", "export")
        self.until(lambda: self.step_state("export") == "run")
        self.assertEqual(self.r.restart_info(), {"runs": 2, "redo": None})   # 書き出しの段は redo にしない(書き出し中は今までどおり断る)
        owned = next(r.owned for r in self.r.runs if r.state == "running")
        self.assertEqual(owned[0], "export")   # 掲示板の親子の印(ex:<jid> を親の run の下に)
        self.assertEqual(len(owned[1]), 1)

    def test_transcribe_jobs_and_others(self):
        self.tools.hold = True
        start_file(self.r, self.empty("ライブ.mp4"), title="ライブの切り抜き")
        self.until(lambda: self.r.restart_info()["redo"])   # ジョブを入れて待ち始めるまで
        jid = next(iter(self.tools.tx_jobs))
        self.tools.tx_jobs[jid]["title"] = "ライブの切り抜き"
        self.assertEqual(self.r.restart_info(), {"runs": 1, "redo": {"tool": "transcribe", "labels": ["ライブの切り抜き"], "others": []}})
        self.tools.tx_jobs["u1"] = {"id": "u1", "state": "running", "title": "人が入れた文字起こし"}
        self.tools.tx_jobs["u2"] = {"id": "u2", "state": "done", "title": "済んだもの"}
        self.assertEqual(self.r.restart_info(timeout=1)["redo"]["others"], ["人が入れた文字起こし"])

    def test_analyze_queue(self):
        self.tools.video["analysis"] = None
        self.tools.hold_q = True
        start(self.r, VID, "full", 2)
        redo = self.until(lambda: self.r.restart_info()["redo"])
        self.assertEqual(redo, {"tool": "studio", "labels": [VID], "others": []})   # 枠の名前は題名か配信の ID(偽のキューには題名が無い)
        self.tools.queue.append({"qid": "q9", "videoId": "zzzzzzzzzzz", "title": "人が入れた解析", "status": "waiting"})
        self.assertEqual(self.r.restart_info()["redo"]["others"], ["人が入れた解析"])

    def test_pack_job(self):
        """パック(cut2resolve は 1 つずつ): この実行のジョブが動いていれば、そのツールの枠すべてがこの実行のもの"""
        self.tools.hold = True
        self.tools.c2r = {"job": {"id": "c1", "state": "running"}, "body": {"spec": {"video": "x"}}}
        self.assertEqual(A.AutoRunner._redo_work(self.tools, "cut2resolve", ["c1"]), {"tool": "cut2resolve", "labels": None, "others": []})
        self.tools.c2r["job"]["state"] = "done"
        self.assertIsNone(A.AutoRunner._redo_work(self.tools, "cut2resolve", ["c1"]))
        self.assertIsNone(A.AutoRunner._redo_work(self.tools, "intake", ["x"]))

    def test_delivered_is_saved_at_once(self):
        """届けたパックはすぐ待ちの記録に残す(段の途中で起動し直しても、同じパックを二度置かない)"""
        logs = os.path.join(self.tmp, "logs")
        self.r.close()
        self.r = self.make_runner(find_pack=None, log_dir=logs)
        pack = os.path.join(self.tmp, "a_pack")
        os.makedirs(pack)
        open(os.path.join(pack, "cut-plan.json"), "w").close()
        out = os.path.join(self.tmp, "出力")
        run = RF.run_of(VID, "配信", "request_auto", 1, deliver_dir=out, request_id="20261001-120000-abc123")   # 依頼(出どころ request = 出どころの印 .meta.json は置かない)
        run.state = "running"
        with self.r.cv:
            self.r.runs.append(run)
        self.r._deliver_one(run, pack)
        with open(os.path.join(logs, A.ACTIVE_FILE), encoding="utf-8") as f:
            saved = json.load(f)["runs"]
        self.assertEqual([x["delivered"] for x in saved], [[os.path.normpath(pack)]])
        self.assertEqual(sorted(n.split(".", 1)[1] for n in os.listdir(out)), ["meta.json", "zip"], "zip と印(依頼の分にも必ず)")


class TestRequests(Base):
    """友人からの依頼(src/human/friend/intake.py)の形: request = 解析 → 採用 → 書き出し → 文字起こし(パックなし)/ file = 動画を文字起こしだけ"""
    marks = []
    analysis = False

    def setUp(self):
        super().setUp()
        self.prefs = self.set_prefs()
        self.r.log_path = os.path.join(self.tmp, "logs", runlog.RUNS_LOG)
        self.jobs_with_tid()
        self.out = os.path.join(self.tmp, "Dropbox", "出力")   # 友人の受け取り(一時フォルダ)

    def request(self, item, **kw):
        """URL の依頼 1 本(item = 依頼の行)を流して、終わった実行を返す"""
        return self.wait(start_request(self.r, [item], **kw)["runs"][0])

    def auto_request(self, **kw):
        """① 全自動(URL)の依頼 1 本(上位 2 個・届け先 self.out)を流して、終わった実行を返す。kw は依頼の欄の上書き"""
        kw = dict({"request_id": self.RID, "deliver_dir": self.out}, **kw)
        return self.request({"id": VID, "top": 2, "title": "配信", "channel": ""}, **kw)

    def test_request_url(self):
        self.tools.known = False
        res = start_request(self.r, [{"id": VID, "top": 2, "title": "配信", "channel": "ch"}, {"id": "bad", "top": 2}], request_id="20261001-120000-abc123")
        self.assertEqual(len(res["skipped"]), 1)
        run = self.wait(res["runs"][0])
        # 依頼はいつも ① 全自動(② 軽く確認 = 文字起こしまでは 10-19 に消した)
        self.assertEqual((run["state"], run["mode"], run["modeLabel"], run["requestId"]), ("done", "request_auto", "依頼 ① 全自動: 解析 → パック", "20261001-120000-abc123"))
        self.assertEqual(list(self.states(run)), ["analyze", "adopt", "export", "transcribe", "pack"])   # 届け先なし = 段 deliver なし
        self.assertEqual(sorted(self.tools.export_body["markIds"]), ["a2", "a3"])   # 上位 2 個

    def test_file(self):
        media = self.empty("依頼.mp4")
        run = start_file(self.r, media, title="依頼", streamer="さくらみこ", request_id="rid")
        with self.assertRaisesRegex(ValueError, "すでに"):
            start_file(self.r, media)
        run = self.wait(run)
        self.assertEqual((run["state"], run["kind"], run["sourcePath"], run["modeLabel"]), ("done", "file", media, "動画ファイル: 文字起こしまで"), run)
        self.assertEqual([j["src"] for j in self.tools.tx_jobs.values()], [media])
        self.assertEqual(run["docs"], ["000000000001"])
        self.assertEqual(self.prefs.get(["streamer"])["streamer"]["docs"], {"000000000001": "さくらみこ"})   # パックのときの字幕の色
        # もう一度: 文字起こし済みなので飛ばす
        run = self.wait(start_file(self.r, media))
        # 段 normalize(start_file の既定。空のファイルは調べられない = 警告で続く。中身は tests/flow/test_run.py の TestStepNormalize)
        self.assertEqual(self.states(run), {"normalize": "warn", "transcribe": "skip"})

    def test_file_engine_and_model(self):
        """リアルタイム切り抜きの live.auto: 実行ごとのエンジン・モデルを文字起こしの要求に入れる(ほかは編集の設定のまま)"""
        run = self.file_run("ライブ.mp4", title="ライブ", engine="whisper.cpp", model="large-v3")
        self.assertEqual((run["state"], run["engine"], run["model"]), ("done", "whisper.cpp", "large-v3"), run)
        body = list(self.tools.tx_jobs.values())[-1]["body"]
        self.assertEqual((body["engine"], body["model"], body["language"]), ("whisper.cpp", "large-v3", "ja"))

    def live_clip(self, name, origin):
        """リアルタイム切り抜きの書き出し(src/flow/live_export.py の _finish)と同じ形の .clip.json を置いた動画"""
        from ytt import schemas
        media = self.empty(name)
        clip = {"schema": schemas.CLIP_SCHEMA, "range": {"start": 1200.0, "end": 1245.0}, "mark": {"id": "m1", "status": "exported", "src": "auto"},
                "source": {"kind": "live", "videoId": VID, "live": {"recorder": "local", "recording": "20261007-200000-" + VID, "origin": origin}}}
        testkit.write_json(schemas.clip_path_for(media), clip)
        return media

    def test_live_auto_clip_pack_is_whole_range(self):
        """線 D の M8: リアルタイム切り抜きの自動の採用(origin auto・archive)の切り抜きは、カットを指定していなければ区間の全体
        (ホームの autorun.cut が rows でも)= パックの区間は候補の区間のまま。人の採用(manual)は今までどおりホームの設定。live.auto.cut(M2)を選べばそれ"""
        self.prefs.patch("autorun", {"cut": "rows"})
        for name, origin, cut, want in (("auto.mp4", "auto", None, "list"), ("archive.mp4", "archive", None, "list"), ("manual.mp4", "manual", None, "preset"),
                                        ("auto-silence.mp4", "auto", "silence", "silence")):
            media = self.live_clip(name, origin)
            run = self.wait(start_file(self.r, media, title=name, flow="auto", cut=cut))
            self.assertEqual((run["state"], run["mode"]), ("done", "file_auto"), run)
            spec = self.tools.c2r["body"]["spec"]
            got = "preset" if "preset" in spec else spec["mode"]
            self.assertEqual(got, want, (name, spec))
            if want == "list":   # 区間の全体(削る区間なし・カット済の行の字幕も消さない)
                self.assertEqual((spec["listKind"], spec["listText"], spec["dropCutRows"], spec["minLen"]), ("drop", "", False, 0))
        self.assertFalse(A.live_auto_origin(os.path.join(self.tmp, "nai.mp4")))

    def zips(self, out):
        import zipfile
        return {n: sorted(zipfile.ZipFile(os.path.join(out, n)).namelist()) for n in os.listdir(out) if n.endswith(".zip")}

    def delivered(self, run):
        """実行が届けたパックのフォルダ(一覧の dict には出ないので Run から)"""
        return next(r for r in self.r.runs if r.id == run["id"]).delivered

    RID = "20261001-120000-abc123"

    def meta_of(self, out, zip_name):
        """zip の隣の印(<zip の名前(.zip 抜き)>.meta.json)を読む。UTF-8・BOM なし(友人のアプリの読み取りの約束)"""
        with open(os.path.join(out, zip_name[:-4] + ".meta.json"), "rb") as f:
            raw = f.read()
        self.assertFalse(raw.startswith(b"\xef\xbb\xbf"), "BOM なし")
        return json.loads(raw.decode("utf-8"))

    def make_packs(self, n, sub="packs"):
        """パックのフォルダ n 個(cut2resolve が作った形の最小: cut-plan.json + 切り抜きの動画の写し)-> 実行の並びのパス(run.packs と同じ書き方)"""
        out = []
        for i in range(1, n + 1):
            d = os.path.normpath(os.path.join(self.tmp, sub, "p%d_pack" % i))
            os.makedirs(d)
            open(os.path.join(d, "cut-plan.json"), "w").close()
            with open(os.path.join(d, "p%d.mp4" % i), "wb") as f:
                f.write(b"v")
            out.append(d)
        return out

    def direct_run(self, packs, out):
        """段取りを通さずに届ける段(_deliver_pending)だけを動かすための実行(パックは手で用意したもの)"""
        run = RF.run_of(VID, "配信", "request_auto", None, request_id=self.RID, deliver_dir=out)
        run.state = "running"
        run.packs = list(packs)
        with self.r.cv:
            self.r.runs.append(run)
        return run

    def fail_zips_after(self, n):
        """zip を作る関数の n 回目より後を「ディスクがいっぱい」(OSError)にする。-> 呼ばれた回数の入れ物"""
        orig = deliver_mod.zip_packs
        calls = {"n": 0}
        self.addCleanup(setattr, deliver_mod, "zip_packs", orig)

        def zip_packs(*a, **k):
            calls["n"] += 1
            if calls["n"] > n:
                raise OSError(28, "No space left on device")
            return orig(*a, **k)
        deliver_mod.zip_packs = zip_packs
        return calls

    def logs_dir(self):
        return os.path.join(self.tmp, "logs")

    def real(self, run):
        """一覧の dict でない、実行そのもの(Run)"""
        return next(r for r in self.r.runs if r.id == run["id"])

    def test_request_auto_delivers_packs(self):
        """① 全自動(URL): 解析 → 採用 → 書き出し → 文字起こし → パック → パックができるたびに 1 本ずつ届ける(組はない): 1 本の zip + 隣の確認用の動画 + 隣の印(meta)。
        実行の欄(依頼 id・配信・マーク)が印と届けた記録まで届く。置く順・印の欄の形は tests/flow/test_deliver.py の DeliverRun.test_deliver_run"""
        self.tools.known = False
        run = self.auto_request()
        self.assertEqual((run["state"], run["mode"]), ("done", "request_auto"), run)
        self.assertEqual(list(self.states(run)), ["analyze", "adopt", "export", "transcribe", "pack", "deliver"])
        self.assertEqual(self.states(run)["deliver"], "done")
        z2, z3 = "%s__a2.zip" % self.RID, "%s__a3.zip" % self.RID   # 1 本の zip は <依頼 id>__<パックの題>.zip
        self.assertEqual(sorted(os.listdir(self.out)), sorted([z2, z3] + [z[:-4] + e for z in (z2, z3) for e in (".preview.mp4", ".meta.json")]))
        got = self.zips(self.out)
        self.assertEqual(([n for n in got[z2] if not n.startswith("a2_pack/")], "a2_pack/a2.mp4" in got[z2]), ([], True), "1 本の zip に 1 本だけ")
        self.assertEqual([(self.meta_of(self.out, z)["requestId"], self.meta_of(self.out, z)["videoId"], self.meta_of(self.out, z)["markId"])
                          for z in (z2, z3)], [(self.RID, VID, "a2"), (self.RID, VID, "a3")])
        self.assertEqual(len(self.delivered(run)), 2)
        for z in (z2, z3):   # 友人の「要らない」で引く記録は zip ごと 1 行(パックは 1 つずつ)
            row = friend_feedback.find_delivery(self.logs_dir(), z)
            self.assertEqual((row["requestId"], row["videoId"], len(row["packs"])), (self.RID, VID, 1), row)
            self.assertTrue(all(p["markId"] and p["path"].endswith(".mp4") and os.path.isdir(p["dir"]) for p in row["packs"]), row)
        marks = next(r for r in self.r.runs if r.id == run["id"]).pack_marks
        packs = [p for z in (z2, z3) for p in friend_feedback.find_delivery(self.logs_dir(), z)["packs"]]
        self.assertEqual(sorted(marks), sorted(p["dir"] for p in packs))
        self.assertEqual(sorted(m["markId"] for m in marks.values()), sorted(p["markId"] for p in packs))

    def test_live_clips_each_delivered_as_the_run_ends(self):
        """ライブの切り抜き(1 本ごとに別の実行)も、その実行の中で 1 本ずつ届ける(溜めはしない = F3-6)。溜めは残らない"""
        for i in range(3):
            media = self.live_clip("l%d.mp4" % i, "auto")
            run = self.wait(start_file(self.r, media, title="l%d" % i, flow="auto", request_id=self.RID, deliver_dir=self.out))
            self.assertEqual(run["state"], "done", run)
            self.assertIn("%s__l%d.zip" % (self.RID, i), os.listdir(self.out))
            self.assertIn("%s__l%d.meta.json" % (self.RID, i), os.listdir(self.out))
        self.assertEqual(len(os.listdir(self.out)), 9)
        self.assertEqual(self.r.pools(), {})

    def test_without_preview_still_delivers_zip_and_meta(self):
        """確認用の動画を作れなくても(ffmpeg が無い・動画が壊れている)zip と印は届ける(印の preview は null)"""
        self.tools.known = False
        self.addCleanup(setattr, pv, "make_preview", pv.make_preview)
        pv.make_preview = lambda *a, **k: False
        run = self.auto_request()
        self.assertEqual(run["state"], "done", run)
        self.assertEqual(sorted(os.listdir(self.out)), sorted(["%s__a%d.%s" % (self.RID, i, e) for i in (2, 3) for e in ("zip", "meta.json")]))
        for i in (2, 3):
            self.assertIsNone(self.meta_of(self.out, "%s__a%d.zip" % (self.RID, i))["preview"])

    def test_each_pack_once_in_run_order(self):
        """段を通さずに届ける段(_deliver_pending)だけ: 4 本はそれぞれ 1 本ずつ・2 度目は何も置かない"""
        run = self.direct_run(self.make_packs(4), self.out)
        self.r._deliver_pending(run)
        zips = ["%s__p%d.zip" % (self.RID, i) for i in (1, 2, 3, 4)]
        self.assertEqual(sorted(os.listdir(self.out)), sorted(zips + [z[:-4] + e for z in zips for e in (".preview.mp4", ".meta.json")]))
        self.assertEqual(run.delivered, run.packs)
        self.r._deliver_pending(run)
        self.assertEqual(len(os.listdir(self.out)), 12)

    def test_stops_midway_keeps_placed_records(self):
        """2 本目の zip が置けなかった(ディスクがいっぱい): 1 本目の記録(deliveries.jsonl・届けた印)は残る。2 本目の確認用の動画・印は残さない"""
        packs = self.make_packs(3)
        run = self.direct_run(packs, self.out)
        calls = self.fail_zips_after(1)
        with self.assertRaisesRegex(A.StepError, "No space left on device"):
            self.r._deliver_pending(run)
        self.assertEqual(calls["n"], 2)
        z1 = "%s__p1.zip" % self.RID
        self.assertEqual(run.delivered, [packs[0]])
        self.assertEqual(sorted(os.listdir(self.out)), sorted([z1, z1[:-4] + ".preview.mp4", z1[:-4] + ".meta.json"]))
        row = friend_feedback.find_delivery(self.logs_dir(), z1)
        self.assertEqual((row["requestId"], [p["dir"] for p in row["packs"]]), (self.RID, [packs[0]]), row)
        self.assertIsNone(friend_feedback.find_delivery(self.logs_dir(), "%s__p2.zip" % self.RID))
        self.assertFalse([n for n in os.listdir(os.path.dirname(packs[0])) if n.startswith(".deliver")], "書きかけが残る")

    def test_nothing_placed_leaves_no_files(self):
        """1 本目の zip が置けなかった: 先に置いた確認用の動画・印も残さない・記録も届けた印も無い"""
        run = self.direct_run(self.make_packs(3), self.out)
        self.fail_zips_after(0)
        with self.assertRaisesRegex(A.StepError, "No space left on device"):
            self.r._deliver_pending(run)
        self.assertEqual(os.listdir(self.out), [])
        self.assertEqual(run.delivered, [])
        self.assertFalse(os.path.exists(os.path.join(self.logs_dir(), "deliveries.jsonl")))
        self.assertFalse([n for n in os.listdir(os.path.join(self.tmp, "packs")) if n.startswith(".deliver")], "書きかけが残る")

    def test_preview_copy_stops_midway_leaves_no_partial_file(self):
        """確認用の動画を 出力 へ写している途中で止まった(ディスクがいっぱい): 書きかけの確認用の動画を残さない"""
        def copyfile(src, dst, **_k):
            with open(dst, "wb") as f:
                f.write(b"PART")
            raise OSError(28, "No space left on device")
        run = self.direct_run(self.make_packs(3, "packs2"), self.out)
        with mock.patch.object(shutil, "copyfile", copyfile):
            with self.assertRaisesRegex(A.StepError, "No space left on device"):
                self.r._deliver_pending(run)
        self.assertEqual(os.listdir(self.out), [])
        self.assertEqual(run.delivered, [])

    def test_group_stops_the_run_with_failure_note(self):
        """通しで: 組の 2 本目の zip が置けなかった実行は「止まった」(error)。友人の受け取りに失敗の知らせの .txt、1 本目の記録は残る"""
        self.tools.known = False
        self.fail_zips_after(1)
        run = self.auto_request()
        self.assertEqual(run["state"], "error", run)
        self.assertEqual(self.states(run)["deliver"], "error")
        self.assertIn("No space left on device", run["error"])
        pre = "%s__%s" % (self.RID, run["title"])
        # 失敗の知らせは状態が error になったあとに置く(状態だけ見て読むと、まだ無いことがある)
        names = self.until(lambda: (lambda ns: ns if pre + ".失敗.txt" in ns else None)(os.listdir(self.out)), 3)
        self.assertEqual(sorted(n for n in names if n.endswith(".zip")), ["%s__a2.zip" % self.RID])
        self.assertIsNotNone(friend_feedback.find_delivery(self.logs_dir(), "%s__a2.zip" % self.RID))
        self.assertIsNone(friend_feedback.find_delivery(self.logs_dir(), "%s__a3.zip" % self.RID))

    def test_file_auto_delivers_and_failure_note(self):
        """① 全自動(動画): 文字起こし → パック → zip。止まったら 出力\\ に理由の .txt"""
        run = self.file_run("依頼.mp4", title="依頼", streamer="さくらみこ", request_id="rid1", flow="auto", deliver_dir=self.out)
        self.assertEqual((run["state"], run["mode"], list(self.states(run))), ("done", "file_auto", ["normalize", "transcribe", "pack", "deliver"]), run)
        self.assertEqual(self.tools.c2r["body"]["output"].get("streamer"), "さくらみこ")   # 選んだ配信者の色でパック
        self.assertNotIn("videoTracks", self.tools.c2r["body"]["output"])                 # 選ばなければ送らない(= 1)
        self.assertEqual(sorted(self.zips(self.out)), ["rid1__依頼.zip"])
        self.tools.fail_tx = True
        run = self.wait(start_file(self.r, self.empty("b.mp4"), title="二本目", request_id="rid2", flow="auto", deliver_dir=self.out))
        self.assertEqual(run["state"], "error")
        note = os.path.join(self.out, "rid2__二本目.失敗.txt")
        self.until(lambda: os.path.exists(note), 3)   # 失敗の知らせは状態が error になったあとに置く
        with open(note, encoding="utf-8-sig") as f:
            self.assertIn("モデルが読めません", f.read())

    def test_file_with_speakers_diarizes_new_doc(self):
        """話す人があれば、文字起こしのあとに話者分離(人数と名前を「編集」の /api/diarize へ)"""
        self._diarize_fake()
        run = self.file_run("コラボ.mp4", speakers={"count": 2, "names": ["兎田ぺこら"]})
        self.assertEqual((run["state"], list(self.states(run))), ("done", ["normalize", "transcribe", "diarize"]), run)
        body = self.tools.tx_jobs["d1"]["body"]
        self.assertEqual((body["tid"], body["numSpeakers"], body["names"]), ("000000000001", 2, ["兎田ぺこら"]))

    def _diarize_fake(self, sub=None):
        """話者分離(done 済みのジョブを返す)と、字幕の色を覚える API(POST /api/speakers/sub)の偽物。sub = (status, 応答) を返す関数(None = 404 = 古い編集)"""
        self.tools.h_transcribe_POST_api_diarize = lambda path, body: (self.tools.tx_jobs.setdefault("d1", {"id": "d1", "state": "done", "src": "", "body": body}) and (200, {"id": "d1"}))
        if sub is not None:
            self.tools.h_transcribe_POST_api_speakers_sub = sub

    STYLES = {"兎田ぺこら": {"color": "#7EC2FE"}}
    SPEAKERS = {"count": 2, "names": ["兎田ぺこら", "B"], "styles": STYLES}

    def test_file_with_styles_remembers_color_in_doc(self):
        """話者分離のあと、指定された字幕の色を文書に覚える(POST /api/speakers/sub {id, styles})。styles が空なら呼ばない"""
        self._diarize_fake(lambda path, body: (200, {"ok": True, "applied": list(body["styles"])}))
        run = self.file_run("コラボ.mp4", speakers=dict(self.SPEAKERS))
        self.assertEqual((run["state"], list(self.states(run))), ("done", ["normalize", "transcribe", "diarize"]), run)
        subs = self.sub_calls()
        self.assertEqual([(c[0], c[1], c[3]) for c in subs], [("transcribe", "POST", {"id": "000000000001", "styles": self.STYLES})])
        detail = next(s for s in run["steps"] if s["key"] == "diarize")["detail"]
        self.assertIn("字幕の色を覚えました", detail)
        self.assertNotIn("覚えられませんでした", detail)
        # 色の指定が無い(古い形・styles が空)なら呼ばない
        media2 = self.empty("ふたり.mp4")
        self.tools.calls.clear()
        run = self.wait(start_file(self.r, media2, speakers={"count": 2, "names": ["A", "B"], "styles": {}}))
        self.assertEqual(run["state"], "done", run)
        self.assertFalse(self.sub_calls())
        run = self.file_run("古い.mp4", speakers={"count": 2, "names": ["A", "B"]})   # styles の鍵そのものが無い
        self.assertEqual(run["state"], "done", run)
        self.assertFalse(self.sub_calls())

    def test_file_styles_not_sent_when_color_invalid(self):
        """実行の作り手が検査をすり抜けた色を渡しても、16 進 6 桁でなければ送らない(画面・Lua に入る前の 2 重の守り)"""
        self._diarize_fake(lambda path, body: (200, {"ok": True, "applied": []}))
        run = self.file_run("x.mp4", speakers={"count": 2, "names": ["A", "B"], "styles": {"A": {"color": "red\"); os.exit()"}, "B": {"color": "ff00aa"}}})
        self.assertEqual(run["state"], "done", run)
        self.assertEqual([c[3]["styles"] for c in self.tools.calls if c[2] == "/api/speakers/sub"], [{"B": {"color": "#FF00AA"}}])

    def test_file_styles_old_editor_does_not_stop_request(self):
        """古い「編集」(sub の API が無く 404)・その他の失敗でも、依頼は止めない(一部失敗にもしない)。段の知らせに足すだけ"""
        self._diarize_fake()   # sub の API なし = 404
        run = self.file_run("古い編集.mp4", speakers=dict(self.SPEAKERS), flow="auto", deliver_dir=os.path.join(self.tmp, "出力"))
        self.assertEqual((run["state"], list(self.states(run))), ("done", ["normalize", "transcribe", "diarize", "pack", "deliver"]), run)
        self.assertEqual(self.states(run)["diarize"], "done")
        self.assertIn("字幕の色を覚えられませんでした", next(s for s in run["steps"] if s["key"] == "diarize")["detail"])
        self.assertEqual(self.tools.c2r["body"]["output"]["speakerStyles"], self.STYLES, "パックには色を渡す")
        for i, res in enumerate(((500, {"error": "x"}), (200, {"ok": False}), (200, "x"))):
            self.tools.h_transcribe_POST_api_speakers_sub = lambda path, body, res=res: res
            run = self.file_run("n%d.mp4" % i, speakers=dict(self.SPEAKERS))
            self.assertEqual((run["state"], self.states(run)["diarize"]), ("done", "done"), run)
        def boom(path, body):
            raise OSError("つながらない")
        self.tools.h_transcribe_POST_api_speakers_sub = boom
        run = self.file_run("boom.mp4", speakers=dict(self.SPEAKERS))
        self.assertEqual((run["state"], self.states(run)["diarize"]), ("done", "done"), run)

    def test_file_styles_not_remembered_when_diarize_fails(self):
        """話者分離が失敗した文書には、色を覚えさせない"""
        self.tools.h_transcribe_POST_api_diarize = lambda path, body: (500, {"message": "話者分離が使えません"})
        self.tools.h_transcribe_POST_api_speakers_sub = lambda path, body: (200, {"ok": True, "applied": []})
        run = self.file_run("失敗.mp4", speakers=dict(self.SPEAKERS))
        self.assertEqual(self.states(run)["diarize"], "warn", run)
        self.assertFalse(self.sub_calls())
        self.tools.h_transcribe_POST_api_diarize = lambda path, body: (self.tools.tx_jobs.setdefault("d2", {"id": "d2", "state": "error", "error": "だめ", "src": "", "body": body}) and (200, {"id": "d2"}))
        run = self.file_run("失敗2.mp4", speakers=dict(self.SPEAKERS))
        self.assertEqual(self.states(run)["diarize"], "warn", run)
        self.assertFalse(self.sub_calls())

    def test_pack_request_has_speaker_styles_only_when_given(self):
        """パックの要求(output.speakerStyles)は、色の指定があるときだけ。無ければ鍵ごと付けない(今までと同じ要求)"""
        self._diarize_fake(lambda path, body: (200, {"ok": True, "applied": []}))
        out = os.path.join(self.tmp, "出力")
        run = self.file_run("あり.mp4", request_id="r1", flow="auto", deliver_dir=out, speakers=dict(self.SPEAKERS))
        self.assertEqual(run["state"], "done", run)
        self.assertEqual(self.tools.c2r["body"]["output"]["speakerStyles"], self.STYLES)
        run = self.file_run("なし.mp4", request_id="r2", flow="auto", deliver_dir=out, speakers={"count": 2, "names": ["A"], "styles": {}})
        self.assertEqual(run["state"], "done", run)
        self.assertNotIn("speakerStyles", self.tools.c2r["body"]["output"])
        run = self.file_run("話者なし.mp4", request_id="r3", flow="auto", deliver_dir=out)
        self.assertEqual(run["state"], "done", run)
        self.assertNotIn("speakerStyles", self.tools.c2r["body"]["output"])

    def test_request_url_with_styles_and_streamer(self):
        """URL の依頼(① 全自動): 配信者(streamer)はチャンネル名からの自動より優先・色の指定は文書に覚え、パックにも渡す。streamer が無ければ今までどおり自動"""
        self.tools.known = False
        self._diarize_fake(lambda path, body: (200, {"ok": True, "applied": []}))
        item = {"id": VID, "top": 1, "title": "配信", "channel": "Pekora Ch. 兎田ぺこら", "ranges": [(50, 60)]}
        run = self.request(item, request_id="rid1", deliver_dir=self.out, speakers=dict(self.SPEAKERS), streamer="さくらみこ")
        self.assertEqual((run["state"], run["streamer"], run["streamerFrom"]), ("done", "さくらみこ", None), run)
        self.assertEqual(list(self.states(run)), ["adopt", "export", "transcribe", "diarize", "pack", "deliver", "analyze_later"])
        out_body = self.tools.c2r["body"]["output"]
        self.assertEqual((out_body["streamer"], out_body["speakerStyles"]), ("さくらみこ", self.STYLES))
        self.assertTrue(self.sub_calls())
        # streamer なし / 空 = 今までどおりチャンネル名から自動
        for who in (None, ""):
            run = self.request(dict(item, ranges=[(70, 80)]), request_id="rid2", deliver_dir=self.out, streamer=who)
            self.assertEqual((run["state"], run["streamer"], run["streamerFrom"]), ("done", "兎田ぺこら", "auto"), run)
            self.assertEqual(self.tools.c2r["body"]["output"]["streamer"], "兎田ぺこら")
            self.assertNotIn("speakerStyles", self.tools.c2r["body"]["output"])

    def test_request_ranges_only_skips_analysis(self):
        """区間が切り抜く数に足りている: 解析なしで、区間(前後に 2 秒の余白)だけを書き出し → 文字起こし。解析は最後に順番へ入れるだけ(待たない。決定 3-49 Q6)"""
        self.tools.known = False
        run = self.request({"id": VID, "top": 2, "title": "配信", "channel": "ch", "ranges": [(100, 190), (1, 30)], "duration": 191.0}, request_id="rid")
        self.assertEqual((run["state"], list(self.states(run))), ("done", ["adopt", "export", "transcribe", "pack", "analyze_later"]), run)
        adds = [i for i, c in enumerate(self.tools.calls) if c[2] == "/api/queue/add"]
        self.assertEqual(len(adds), 1, "解析は最後に 1 回だけ順番へ")
        self.assertGreater(adds[0], max(i for i, c in enumerate(self.tools.calls) if c[2] == "/api/video/request-marks"), "切り抜く前には解析しない")
        self.assertIn("順番に入れました", next(s for s in run["steps"] if s["key"] == "analyze_later")["detail"])
        self.assertEqual(self.tools.request_marks, {"id": VID, "ranges": [[98.0, 191.0], [0.0, 32.0]], "top": 2, "title": "配信", "channel": "ch"})   # 余白は 0 と配信の長さで切る
        self.assertEqual(len(self.tools.export_body["markIds"]), 2)
        self.assertEqual(run["ranges"], [[100.0, 190.0], [1.0, 30.0]])
        self.assertIn("指定の区間 2 個", next(s for s in run["steps"] if s["key"] == "adopt")["detail"])

    def test_request_ranges_filled_with_auto(self):
        """区間が切り抜く数に足りない: 解析して、足りない分だけ自動の上位で埋める。採用の答え(区間・人の採用・自動)の id をこの実行が全部扱う
        (どれを選ぶかの規則は tests/human/review/test_studio.py の TestAdoptRule)"""
        self.tools.known = False
        self.tools.video["marks"] = [{"id": "old", "src": "manual", "status": "adopted", "score": None, "start": 500, "end": 510}]   # 前からある人の採用
        run = self.request({"id": VID, "top": 3, "ranges": [(18, 23)]}, request_id="rid")
        self.assertEqual((run["state"], list(self.states(run))), ("done", ["analyze", "adopt", "export", "transcribe", "pack"]), run)
        self.assertEqual((self.tools.request_marks["ranges"], self.tools.request_marks["top"]), ([[16.0, 25.0]], 3))
        self.assertEqual((len(self.tools.export_body["markIds"]), "old" in self.tools.export_body["markIds"], len(self.tools.tx_jobs)), (3, True, 3))

    def test_request_cut_and_resend_rebuilds_pack(self):
        """① 全自動: 友人が選んだカット(無音を削る)でパック。同じ配信・同じ区間の送り直しは、切り抜き・文字起こしを使い回してパックだけ作り直して届ける"""
        self.tools.known = False
        item = {"id": VID, "top": 1, "title": "配信", "ranges": [(50, 60)]}
        run = self.request(dict(item), request_id="rid1", deliver_dir=self.out, cut="silence", video_tracks=2)
        self.assertEqual((run["state"], list(self.states(run))), ("done", ["adopt", "export", "transcribe", "pack", "deliver", "analyze_later"]), run)
        self.assertEqual((self.tools.c2r["body"]["spec"]["mode"], self.tools.c2r["body"]["output"]["videoTracks"]), ("silence", 2))
        self.assertEqual(len(self.zips(self.out)), 1)
        jobs = len(self.tools.tx_jobs)
        run = self.request(dict(item), request_id="rid2", deliver_dir=self.out, cut="none", video_tracks=3)
        st = self.states(run)
        self.assertEqual((run["state"], st["export"], st["transcribe"], st["pack"], st["deliver"]), ("done", "skip", "skip", "done", "done"), run)
        self.assertEqual(len(self.tools.tx_jobs), jobs, "文字起こしは使い回す")
        body = self.tools.c2r["body"]
        self.assertEqual((body["spec"].get("mode"), body["spec"].get("listKind"), body["output"]["videoTracks"], body["output"].get("force")), ("list", "drop", 3, True))
        self.assertEqual(len(self.zips(self.out)), 2, "作り直したパックも届ける")
        # カットの指定が無い依頼(古いアプリ)は、ホームの設定(既定 = カットしない)
        self.request(dict(item, ranges=[(70, 80)]), request_id="rid3", deliver_dir=self.out)
        self.assertEqual(self.tools.c2r["body"]["spec"].get("listKind"), "drop")

    def test_request_weights_reanalyze_only_when_different(self):
        """解析の重み: 指定があればその重みで解析。解析済みで同じ重みなら使い回す・違えば解析し直す"""
        w = {"wAudio": 1.5, "wChat": 0.5, "wComments": 0.7}
        self.tools.analyze = {"count": 12, "wAudio": 1.0}
        self.tools.known = False
        run = self.request({"id": VID, "top": 1}, weights=w)
        self.assertEqual(self.states(run)["analyze"], "done", run)
        add = [c for c in self.tools.calls if c[2] == "/api/queue/add"]
        self.assertEqual(add[-1][3]["settings"], AN(count=12, wAudio=1.5, wChat=0.5, wComments=0.7, fill=1))   # ほかの設定はスタジオのまま
        self.tools.video["analysis"] = {"at": 3, "spec": dict(w, count=12)}
        run = self.request({"id": VID, "top": 1}, weights=dict(w))
        self.assertEqual(self.states(run)["analyze"], "skip")
        self.tools.queue.clear()
        run = self.request({"id": VID, "top": 1}, weights=dict(w, wChat=2.0))
        self.assertEqual(self.states(run)["analyze"], "done", run)
        self.assertEqual(len([c for c in self.tools.calls if c[2] == "/api/queue/add"]), 2)
        run = self.request({"id": VID, "top": 1})   # 指定なし: 解析済みなら使い回す
        self.assertEqual(self.states(run)["analyze"], "skip")

    def test_bad_range_is_skipped(self):
        res = start_request(self.r, [{"id": VID, "top": 1, "ranges": [[5, 1]]}])   # 区間の検査は tests/flow/test_spec.py の test_clean_ranges・test_pad_range
        self.assertEqual((res["runs"], res["skipped"][0]["reason"]), ([], "区間の指定が正しくありません"))


class TestFriendLength(Base):
    """友人の区間の長さを、依頼の自動の候補の長さに使う: ② flow/lengthhint が入口の実行記録の友人の区間からその場で数え、
    依頼(URL)で足りない分を自動で埋めるために解析するときだけ、解析の設定 length に重ねる。数え方の細かい所は tests/flow/test_lengthhint.py"""
    marks = []
    analysis = False

    def setUp(self):
        super().setUp()
        env_patch = mock.patch.dict(os.environ)
        env_patch.start()
        self.addCleanup(env_patch.stop)
        os.environ.pop(A.FRIEND_LENGTH_ENV, None)
        self.logs = []
        self.r.log = self.logs.append
        self.tools.analyze = {"count": 12, "length": 45, "preRatio": 0.65}
        self.tools.known = False
        from manage.cases import cases
        self.runs_log = cases.locations(self.r.root, self.env)["runs"]

    def write_runs(self, n=20, videos=5, length=38.4):
        """実行記録に友人の区間を n 個(配信 videos 本)。今の記録の後ろに足す"""
        os.makedirs(os.path.dirname(self.runs_log), exist_ok=True)
        with open(self.runs_log, "a", encoding="utf-8") as f:
            for i in range(n):
                f.write(json.dumps({"v": 1, "id": "past%d-%d" % (i, time.time_ns()), "state": "done", "steps": [], "kind": "video",
                                    "videoId": "fv%d" % (i % videos), "ranges": [[i * 1000.0, i * 1000.0 + length]]}) + "\n")

    def run_request(self, **kw):
        return self.wait(start_request(self.r, [{"id": VID, "top": 3, "ranges": [(50, 60)]}], request_id="rid", **kw)["runs"][0])   # 区間が足りない = 解析あり

    def settings(self):
        adds = [c for c in self.tools.calls if c[2] == "/api/queue/add"]
        return adds[-1][3]["settings"] if adds else None

    def test_used_when_enough(self):
        self.write_runs()
        run = self.run_request(weights={"wAudio": 1.5, "wChat": 1.0, "wComments": 1.0})
        self.assertEqual(run["state"], "done", run)
        self.assertEqual(self.settings(), AN(count=12, length=38, preRatio=0.65, wAudio=1.5, wChat=1.0, wComments=1.0, fill=3))
        self.assertEqual(run["friendLength"], {"length": 38, "file": "flow/lengthhint", "samples": 20, "videos": 5})
        self.assertIn("長さ 38 秒(友人の区間の実績から)", next(s for s in run["steps"] if s["key"] == "analyze")["detail"])
        self.assertIn("長さの目安を使います(場面が取れないときの長さ): 38 秒", self.logs[0])
        n = len(self.logs)
        self.r._friend_length()
        self.assertEqual(len(self.logs), n)   # 変わらなければログに出さない(数え方・上限は tests/flow/test_lengthhint.py)

    def test_only_for_requests(self):
        """ユーザー自身のまとめて実行には効かない。解析済みなら使い回す(長さが違っても解析し直さない)"""
        self.write_runs()
        self.tools.known = True
        run = self.run_one("full")
        self.assertEqual((run["state"], self.settings()), ("done", AN(count=12, length=45, preRatio=0.65, fill=3)))
        self.assertIsNone(run["friendLength"])
        # 解析済み(スタジオの設定の長さで)の配信: 依頼でも解析し直さない
        self.tools.video["analysis"] = {"at": 5, "spec": {"length": 45}}
        self.tools.calls.clear()
        run = self.run_request()
        self.assertEqual((self.states(run)["analyze"], self.settings(), run["friendLength"]), ("skip", None, None))

    def test_off(self):
        self.write_runs()
        os.environ[A.FRIEND_LENGTH_ENV] = "off"
        self.assertIsNone(self.r._friend_length())
        del os.environ[A.FRIEND_LENGTH_ENV]
        self.assertEqual(self.r._friend_length()["length"], 38)

        class P:
            def __init__(self, v):
                self.v = v

            def get(self, names):
                return {"autorun": {"friendLength": self.v}}
        self.r.prefs = P(False)
        self.assertIsNone(self.r._friend_length())
        self.r.prefs = P(True)
        self.assertEqual(self.r._friend_length()["length"], 38)


class TestSpecFromSettings(unittest.TestCase):
    """画面の設定 → 束(spec_from_settings を直接)。通しで届くことは代表の 1 値(TestModes.test_adopted_mode_exports_transcribes_and_packs)"""

    def test_each_setting_goes_to_the_bundle(self):
        studio = {"analyze": {"count": 5, "length": 30, "sensitivity": "high", "useChat": False}, "review": {"exportVolume": 60, "maxHeight": 720}}
        editor = {"rowEdge": {"on": False, "after": 0.5, "before": 0.3}, "subtitle": {"wrapChars": {"vertical": 9, "horizontal": 14}},
                  "speakerColors": False, "packLoudness": 0, "packVolume": 70, "packSize": "1920x1080", "packFps": "60", "packBackup": True,
                  "secret": "使わない"}
        b, notes = A.spec_from_settings(studio, editor, {"cut": "silence"})
        self.assertEqual(({k: b["analyze"][k] for k in studio["analyze"]}, b["export"]["volume"], notes), (studio["analyze"], 60, []))
        p = b["pack"]
        self.assertEqual((p["rowEdge"], p["wrapChars"], p["speakerColors"], p["loudness"], p["volume"], p["size"], p["cut"]),
                         (editor["rowEdge"], {"vertical": 9, "horizontal": 14}, False, 0, 70, "1920x1080", "silence"))
        self.assertEqual(SP.pack_output(b)[1]["textplusFps"], "30")   # fps・画質の上限は読まない(固定)
        self.assertNotIn("backup", p)
        self.assertNotIn("secret", json.dumps(b, ensure_ascii=False))   # 知らない設定は束に入れない

    def test_bad_row_edge_falls_back_with_note(self):
        b, notes = A.spec_from_settings({}, {"rowEdge": {"on": "yes"}}, {})
        self.assertEqual((b["pack"]["rowEdge"], notes), (SP.merge(None)["pack"]["rowEdge"], [A.ROW_EDGE_NOTE]))


class TestToolSettingsFiles(Base):
    """build_spec が読む画面の設定のファイル(スタジオの settings-ui.json・編集の settings.json。置き場所は ytt.datadir の規則)"""

    def test_reads_the_files(self):
        from ytt import datadir
        self.assertEqual(_REAL_TOOL_SETTINGS(self.r), ({}, {}))   # 無ければ空 = 束の既定
        sdir, tdir = datadir.resolve("studio", self.r.root, self.env), datadir.resolve("transcribe", self.r.root, self.env)
        self.assertEqual(tdir, os.path.join(self.tmp, "txdata"))
        for d, name, obj in ((sdir, "settings-ui.json", {"analyze": {"count": 5}, "review": {"maxHeight": 720}}),
                             (tdir, "settings.json", {"model": "large-v3", "packSize": "1920x1080"})):
            os.makedirs(d, exist_ok=True)
            with open(os.path.join(d, name), "wb") as f:
                f.write(b"\xef\xbb\xbf" + json.dumps(obj).encode("utf-8"))   # BOM 付きでも読む
        studio, editor = _REAL_TOOL_SETTINGS(self.r)
        self.assertEqual((studio["analyze"], editor["model"]), ({"count": 5}, "large-v3"))
        with mock.patch.object(A.AutoRunner, "_tool_settings", _REAL_TOOL_SETTINGS):
            bundle, notes = self.r.build_spec()
        # 画質の上限(review.maxHeight)は読まない(固定 = 上限なし)
        self.assertEqual((bundle["analyze"]["count"], bundle["transcribe"]["model"], bundle["pack"]["size"], notes), (5, "large-v3", "1920x1080", []))

    def test_build_spec_uses_home_cut(self):
        self.set_prefs(cut="silence")
        self.assertEqual(self.r.build_spec()[0]["pack"]["cut"], "silence")
        self.r.prefs = None
        self.assertEqual(self.r.build_spec()[0]["pack"]["cut"], "none")


class TestAutoSend(Base):
    """D-SEND(notes:plan/done/d-send-requirements.md): まとめて実行(full)で友人へ自動で送る。届け先は一時フォルダだけ(本物の Dropbox は使わない)。
    送るかは届け先があるかだけ(10-19 案 B3。終わってから 48 時間・友人の依頼済みは見ない)"""
    marks = []
    analysis = False
    TAG_RE = r"^\d{8}-\d{6}-[0-9a-f]{6}__"

    def setUp(self):
        super().setUp()
        from manage.cases import cases
        self.cases = cases
        self.r.close()
        self.logs = os.path.join(self.tmp, "logs")
        self.folder = os.path.join(self.tmp, "Dropbox", "切り抜き依頼")
        os.makedirs(self.folder)
        self.out = os.path.join(self.folder, "出力")
        self.prefs = prefs_mod.Prefs(os.path.join(self.tmp, "prefs.json"), fsio.atomic_write)
        self.prefs.patch("intake", {"folder": self.folder})
        self.msgs = []
        self.r = self.runner()

    def runner(self):
        return self.make_runner(prefs=self.prefs, log_dir=self.logs, log=self.msgs.append)

    def go(self, mode="full", auto_send=None, timeout=10):
        return self.wait(start(self.r, VID, mode, 2, auto_send=auto_send), timeout)

    def meta(self, zip_name):
        """zip の隣の印(.meta.json)"""
        return testkit.read_json(os.path.join(self.out, zip_name[:-4] + ".meta.json"))

    def step(self, run, key="deliver"):
        return next(s for s in run["steps"] if s["key"] == key)

    def recs(self):
        return self.cases.load_saved(self.cases.locations(os.path.join(self.tmp, "repo"), self.env)["cases"]).get(VID, {}).get("auto", {})

    def outs(self):
        return sorted(os.listdir(self.out)) if os.path.isdir(self.out) else []

    def rows(self):
        from flow import deliveries
        return deliveries.rows(self.logs) or []

    def notsent(self):
        """② の送らなかった記録(logs/not-sent.jsonl)-> {マーク: {code, text, at}}(この配信の分)"""
        from flow import deliveries
        return {m: r for (v, m), r in deliveries.not_sent_marks(self.logs).items() if v == VID}

    def test_full_sends_one_by_one_with_origin_auto(self):
        run = self.go()
        self.assertEqual((run["state"], self.step(run)["state"]), ("done", "done"), run)
        names = self.outs()
        zips = sorted(n for n in names if n.endswith(".zip"))
        self.assertEqual(sorted(names), sorted(z[:-4] + e for z in zips for e in (".zip", ".preview.mp4", ".meta.json")), names)   # 1 本ずつ
        self.assertEqual([self.meta(z)["origin"] for z in zips], ["auto", "auto"])   # 自動の分は印の出どころ auto(友人には「依頼なし」)
        rows = self.rows()   # 届けた記録の欄の形・案件の札は tests/flow/test_deliver.py の DeliverRun.test_deliver_run・tests/manage/cases/test_cases.py
        self.assertEqual(({(r["origin"], r["videoId"], r["mode"]) for r in rows}, sorted(p["markId"] for r in rows for p in r["packs"])),
                         ({("auto", VID, "full")}, ["a2", "a3"]))
        self.assertEqual(self.recs(), {}, "届けたは案件に写さない(② の届けた記録から引く)")

    def test_unchecked_keeps_quality_card(self):
        """チェックを外した(出どころ auto・届け先なし)= 何も置かないが、切り抜きごとに送らなかった記録 unchecked を残す
        (品質のカード 2-8 の「まとめて実行の切り抜き」に出る。10-19 の作り直しで一度消えかけた)"""
        run = self.go(auto_send=False)
        self.assertEqual((run["state"], self.step(run)["state"], self.step(run)["detail"]), ("done", "skip", DL.UNCHECKED_TEXT), run)
        self.assertEqual({k: r["code"] for k, r in self.notsent().items()}, {"a2": "unchecked", "a3": "unchecked"})
        self.assertEqual((self.outs(), self.rows()), ([], []))   # 案件が記録を読んで札とカードを出すのは tests/manage/cases/test_cases.py

    def test_requested_video_still_sends(self):
        """友人が依頼済みの配信でも送る(二重は防がない = 10-19 ユーザー決定。D-SEND 2-9 の取り下げ)"""
        from human.friend import friend_feedback
        import types
        friend_feedback.record_delivery(self.logs, "x.zip", types.SimpleNamespace(request_id="rid", id="r", video_id=VID, title=""), [])
        run = self.go()
        self.assertEqual(self.step(run)["state"], "done", run)
        self.assertEqual(len([n for n in self.outs() if n.endswith(".zip")]), 2)

    def test_park_then_flush_and_expire(self):
        """置けない(受付の Dropbox のフォルダが無い)→ 実行は失敗にせず溜めに預ける(段は warn・友人に .失敗.txt を置かない)→ フォルダが戻れば flush で届く。
        預けてから 3 日(DL.PARK_KEEP_SEC)を過ぎた溜めは送らずに消して送らなかった記録に expired"""
        shutil.rmtree(self.folder)
        run = self.go()
        self.assertEqual((run["state"], self.step(run)["state"]), ("done", "warn"), run)
        self.assertIn("送り直します", self.step(run)["detail"])
        self.assertFalse(os.path.exists(self.folder), "Dropbox でない所にフォルダを作らない")
        pools = self.r.pools()
        (key, p), = pools.items()
        self.assertTrue(key.startswith("full|") and key.endswith("|" + VID), key)
        self.assertEqual((p["waiting"], p["meta"]["origin"], p["meta"]["parked"]), (2, "auto", True))
        self.assertEqual(self.r.flush_pools(lambda m: False), 0, "フォルダが無い間は待つ")
        # 起動し直しても溜めは残る(logs/deliver-pool.json)
        self.r.close()
        self.r = self.runner()
        self.assertEqual(list(self.r.pools()), [key])
        os.makedirs(self.folder)
        self.assertEqual(self.r.flush_pools(lambda m: False), 2)
        self.assertEqual(self.r.pools(), {})
        names = self.outs()
        self.assertEqual(len([n for n in names if n.endswith(".zip")]), 2, names)
        self.assertTrue(all(re.match(self.TAG_RE, n) for n in names), names)
        self.assertEqual({r["origin"] for r in self.rows()}, {"auto"})
        self.assertEqual({r["mode"] for r in self.rows()}, {"full"})   # 溜めから送った分も実行の形 full(案件は届けた記録で見分ける)
        self.assertFalse(any("deliveredAt" in r for r in self.recs().values()), "届けたは案件に写さない")
        # 預けてから 3 日を過ぎた溜め(created 0)
        with self.r._pool_lock:
            self.r._pools_load()["full|x|" + VID] = {"rid": "x", "tag": None, "origin": "auto", "mode": "full", "title": "古い", "deliverDir": self.out,
                                                      "batch": None, "meta": {"origin": "auto", "videoId": VID, "parked": True},
                                                      "packs": [os.path.join(self.tmp, "out", "a2_pack")], "delivered": [],
                                                      "marks": {os.path.join(self.tmp, "out", "a2_pack"): {"path": "", "markId": "zz"}}, "created": 0, "updated": 0}
        before = self.outs()
        self.assertEqual(self.r.flush_pools(lambda m: False), 0)
        self.assertEqual((self.r.pools(), self.outs()), ({}, before))
        self.assertEqual((self.notsent()["zz"]["code"], self.notsent()["zz"]["text"]), (DL.EXPIRED, DL.EXPIRED_TEXT))
        self.assertTrue(any("送りませんでした" in m for m in self.msgs), self.msgs)

    def test_no_double_on_resume_or_rerun(self):
        """再開(待ちの記録から戻す)でも、同じ配信をもう一度 full で流しても、届けたパックを二度置かない"""
        run = self.go()
        first = self.outs()
        real = next(r for r in self.r.runs if r.id == run["id"])
        back = A.Run.restore(json.loads(json.dumps(real.saved())))
        self.assertEqual((back.deliver_origin, back.delivered), ("auto", real.delivered))
        self.assertTrue(re.match(r"^\d{8}-\d{6}-[0-9a-f]{6}$", back.deliver_tag), back.deliver_tag)
        st = {"state": "run", "detail": ""}
        self.r._step_deliver(back, st, self.tools.video)
        self.assertEqual(self.outs(), first)
        run2 = self.go()
        self.assertEqual((self.step(run2)["state"], self.step(run2)["detail"]), ("skip", "パックはもう友人へ届けてあります"), run2)
        self.assertEqual(self.outs(), first)

    def test_old_pool_is_readable(self):
        """古い溜め(tag・origin・mode が無い・組の batch 入り)も読めて、1 本ずつ届ける(古い待ちの記録は tests/flow/test_run.py の TestFromInput)"""
        pack = os.path.join(self.tmp, "p_pack")
        os.makedirs(pack)
        with open(os.path.join(pack, "p.mp4"), "wb") as f:
            f.write(b"v")
        write_old_pool(os.path.join(self.logs, DL.POOL_FILE), "live|rid9|local/rec", "20261001-120000-abc123", "t", self.out, 2, "rec", [pack])
        self.r.close()
        self.r = self.runner()
        self.assertEqual(self.r.flush_pools(lambda m: True), 1)
        names = self.outs()
        stem = "20261001-120000-abc123__p"
        self.assertEqual(names, sorted([stem + ".zip", stem + ".preview.mp4", stem + ".meta.json"]), names)   # 組ではなく 1 本ずつ(batch 2 は読まない)
        self.assertEqual(self.meta(stem + ".zip")["origin"], "request", "古い溜め(依頼の id)は依頼として届ける")

    def test_from_export_with_marks_sends(self):
        """書き出しから全部(mode full + 束の run.from export + marks。スタジオの「書き出しのあと自動でパックまで」・マークの行の「この後を」):
        解析・採用の段は無く、そのマークだけ書き出し → 文字起こし → パック → 段 deliver(出どころ auto)。届け済みのパックは除く"""
        first = self.go(auto_send=False)   # 解析・採用・書き出しまで(届けない)
        self.assertEqual(self.step(first)["state"], "skip", first)
        adds = len([c for c in self.tools.calls if c[2] == "/api/queue/add"])
        env, diff = O.order("url", video_id=VID, from_="export", upto="pack", marks=["a2"], origin="auto", deliver_dir=self.out)
        run = self.wait(self.r.submit(env, diff))
        self.assertEqual((run["state"], run["mode"], run["modeLabel"], [s["key"] for s in run["steps"]]),
                         ("done", "full", "書き出しから全部(1本)", ["export", "transcribe", "pack", "deliver"]), run)
        self.assertEqual(len([c for c in self.tools.calls if c[2] == "/api/queue/add"]), adds, "解析しない")
        self.assertEqual(self.step(run)["state"], "done", run)
        zips = [n for n in self.outs() if n.endswith(".zip")]
        self.assertEqual(([self.meta(z)["origin"] for z in zips], sorted(p["markId"] for r in self.rows() for p in r["packs"])), (["auto"], ["a2"]))
        self.assertEqual({(r["origin"], r["mode"]) for r in self.rows()}, {("auto", "full")})

    def test_only_full_with_folder_sends(self):
        """届けるのは full だけ・受付のフォルダが決まっているときだけ(2-10)。文書単位・adopted などは届けない"""
        self.prefs.patch("intake", {"folder": ""})
        run = self.go(auto_send=True)
        self.assertNotIn("deliver", [s["key"] for s in run["steps"]])
        self.prefs.patch("intake", {"folder": self.folder})
        run = self.go("export", auto_send=True)
        self.assertNotIn("deliver", [s["key"] for s in run["steps"]])
        self.assertEqual(self.outs(), [])

    def test_switch_off(self):
        """開発機の守り YTT_AUTO_SEND=off: 自動の分は届けない(印も残さない)"""
        with mock.patch.dict(os.environ, {"YTT_AUTO_SEND": "off"}):
            run = self.go()
        self.assertEqual(self.step(run)["state"], "skip", run)
        self.assertIn("YTT_AUTO_SEND", self.step(run)["detail"])
        self.assertEqual((self.outs(), self.rows()), ([], []))

    def test_failure_note_only_for_requests(self):
        """友人に失敗の知らせ(.失敗.txt)を置くのは依頼だけ(2-6)"""
        auto = RF.run_of(VID, "配信", "full", 2, deliver_dir=self.out, deliver_origin="auto", deliver_tag="20261016-120000-abcdef")
        auto.error = "わざと"
        self.r._deliver_failure(auto)
        self.assertEqual(self.outs(), [])
        req = RF.run_of(VID, "配信", "request_auto", 2, deliver_dir=self.out, request_id="20261016-120000-abcdef")
        req.error = "わざと"
        self.r._deliver_failure(req)
        self.assertEqual([n for n in self.outs() if n.endswith(".失敗.txt")], ["20261016-120000-abcdef__配信.失敗.txt"])


class TestSubmitBase(Base):
    """受付は submit の 1 本。束 = 土台(画面の設定 = build_spec)+ 差分 + この PC の設定。受けたときに決める物は必ず _accept"""

    def queued(self, pub):
        return next(r for r in self.r.runs if r.id == pub["id"])

    def test_screen_diff_gets_settings_base(self):
        """画面は差分だけ送る → 書き出しの音量・文字起こしの設定は設定ファイルの値"""
        self.tools.tx_extra = {"model": "large-v3", "quality": "fast"}
        with mock.patch.object(self.r, "_wake", lambda: None):
            run = self.queued(self.r.submit(*O.order("url", video_id=VID, from_="export")))
        self.assertEqual((run.spec["export"]["loudness"], run.spec["export"]["volume"], run.spec["transcribe"]["quality"]), (-16, 60, "fast"))
        self.assertEqual((run.mode, run.spec["run"]["upto"], run.spec["run"]["onFail"]), ("full", "pack", "next"))   # 書き出しからパックまで = 書き出しから全部(full + run.from export)

    def test_full_bundle_wins_over_base(self):
        """全部の束を送る呼び手(CLI・友人のアプリ)は、土台に負けない(この PC の設定だけは重なる)"""
        full = SP.validate(SP.merge({"export": {"loudness": -11, "volume": 90}, "transcribe": {"quality": "best"}}))
        self.tools.tx_extra = {"quality": "fast"}
        with mock.patch.object(self.r, "_wake", lambda: None):
            run = self.queued(self.r.submit(O.order("url", video_id=VID, from_="export")[0], full))
        self.assertEqual((run.spec["export"]["loudness"], run.spec["export"]["volume"], run.spec["transcribe"]["quality"]), (-11, 90, "best"))

    def test_on_fail_from_home_prefs(self):
        """1 本が失敗したときは、ホームの設定 autorun.onFail が土台の束の run.onFail に。差分の onFail が勝つ"""
        self.set_prefs(onFail="stop")
        with mock.patch.object(self.r, "_wake", lambda: None):
            a = self.queued(self.r.submit(*O.order("url", video_id=VID, from_="export")))
            b = self.queued(self.r.submit(*O.order("url", video_id="zzzzzzzzzzz", from_="export", on_fail="next")))
        self.assertEqual((a.on_fail, a.spec["run"]["onFail"], b.on_fail), ("stop", "stop", "next"))

    def test_friend_app_body(self):
        """友人の依頼の本文(版 2 = run.upto・hints.streamer・run.requested)が実行の欄になる(捨てる欄の読み方は tests/flow/test_envelope.py)"""
        v2 = {"id": "0123456789", "kind": "url", "input": {"url": "https://www.youtube.com/watch?v=" + VID}, "requestId": "20261016-120000-abcdef",
              "createdAt": 1, "specVersion": 2}
        s2 = {"adopt": {"top": 2}, "pack": {"cut": "silence", "videoTracks": 2}, "hints": {"streamer": "さくらみこ"},
              "run": {"requested": ["cut", "videoTracks"], "repack": True, "upto": "pack"}}
        with mock.patch.object(self.r, "_wake", lambda: None):
            r = self.queued(self.r.submit(v2, s2))
        self.assertEqual((r.mode, r.streamer, r.cut, r.video_tracks, r.overwrite, r.top), ("request_auto", "さくらみこ", "silence", 2, True, 2))
        self.assertEqual([s["key"] for s in r.steps], list(A.MODE_STEPS["request_auto"]))

    def test_streamer_checked_unless_friend(self):
        """配信者の名前は色の一覧と照らし合わせる(合わなければ 400 = ValueError)。友人の依頼(requestId あり)はそのまま・空 = 色なし"""
        self.use_members()
        with mock.patch.object(self.r, "_wake", lambda: None):
            with self.assertRaisesRegex(ValueError, "見つかりません"):
                self.r.submit(*O.order("url", video_id=VID, from_="export", streamer="だれか"))
            a = self.queued(self.r.submit(*O.order("url", video_id=VID, from_="export", streamer="ぺこら")))
            b = self.queued(self.r.submit(*O.order("url", video_id="bbbbbbbbbbb", from_="export", streamer="だれか", request_id="r1")))
            c = self.queued(self.r.submit(*O.order("url", video_id="ccccccccccc", from_="export", streamer="  ")))
        self.assertEqual((a.streamer, b.streamer, c.streamer), ("兎田ぺこら", "だれか", ""))


if __name__ == "__main__":
    unittest.main()
