"""書き出し(① pipeline/export/exporter)のテスト。
正しく動く道と、見本に混ぜられる端(長い出力先・長い題・絵文字・予約名の題・続きの番号・無音・知らない src・依頼の検査)は通し
(TestExportThrough・TestLiveSection の通し)で、本物の ffmpeg で合成した 30 秒の見本から書き出して出来上がった物をまとめて見る。
単体は通しでは起こせない物だけ(途中の失敗・中止・上書きの瞬間・古い ffmpeg・落ちた後の書きかけ・保存の失敗・ログの上限・yt-dlp の失敗)。

    py -3.12 -m unittest tests/pipeline/export/test_exporter.py
"""
import json
import math
import os
os.environ.setdefault("YTT_DATA_DIR", "inplace")   # テストは作業データを本物の置き場所(AppData など)に書かない(ytt.datadir)
import re
import shutil
import subprocess
import sys
import tempfile
import threading
import time
import unittest
from unittest.mock import Mock, patch

TESTS = os.path.dirname(os.path.abspath(__file__))
SRC = os.path.join(os.path.dirname(os.path.dirname(os.path.dirname(TESTS))), "src")   # tests → export → pipeline → src
HERE = os.path.join(SRC, "studio")   # テストが使うスタジオの殻 common のあるフォルダ(studio/。exporter 自身は common を読まない)
sys.path.insert(0, HERE)
sys.path.insert(0, SRC)
import startup  # noqa: E402,F401  (src を sys.path に足し、スタジオのフォルダを ytt/studio_env に知らせる)
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))))   # tests/(testkit)
import testkit  # noqa: E402
from ytt import errors, jobs, mediainfo, studio_env  # noqa: E402
from pipeline.export import exporter  # noqa: E402
from flow import board as _board, export as _fexport  # noqa: E402  (指定は ② の build_spec = 台帳から引く口・器は ② の ExportJobs)
from ytt import normalize, schemas  # noqa: E402  (途中のファイルの置き場所 WORK_DIR)

VID = "f0123456789"
LONG_TITLE = "とても長い配信タイトル" * 10 + "😀"


def _make_source(path, sec=30, gop=300, rate=60, video=None, audio=None):
    """キーフレームが5秒ごと(60fps・gop=300)の合成動画(映像+音声)。配信の録画によくある 60fps(書き出しで 30fps に作り直される)。
    video・audio: lavfi の指定を差し替える(明るさで時刻が分かる映像・無音の所がある音など)"""
    ff = studio_env.find_tool("ffmpeg")
    cmd = [ff, "-hide_banner", "-loglevel", "error", "-nostdin", "-y", "-f", "lavfi", "-i", video or "testsrc=size=64x64:rate=%d:duration=%d" % (rate, sec),
           "-f", "lavfi", "-i", audio or "sine=frequency=440:duration=%d" % sec, "-c:v", "libx264", "-preset", "veryfast", "-g", str(gop),
           "-keyint_min", str(gop), "-sc_threshold", "0", "-pix_fmt", "yuv420p", "-c:a", "aac", "-shortest", path]
    return subprocess.run(cmd, stdin=subprocess.DEVNULL).returncode == 0 and os.path.isfile(path)


# 明るさ = 秒 × 8(7 秒のコマは 56)。YouTube の区間取得の位置を最初のコマの明るさで確かめる
BRIGHT = "color=c=gray:size=64x64:rate=60:duration=30,format=yuv420p,geq=lum='min(250,T*8)':cb=128:cr=128"
# 20 秒からは無音(ラウドネスをそろえる書き出しが、無音の切り抜きを触らないことを見る)。音の大きさは sine と同じ 1/8
QUIET_TAIL = "aevalsrc='if(lt(t,20),sin(2*PI*440*t)/8,0)':s=44100:d=30"
_SHARED = {}


def _shared_dir():
    if "dir" not in _SHARED:
        _SHARED["dir"] = tempfile.mkdtemp()
    return _SHARED["dir"]


def _source(name="元の配信.mp4", video=None, audio=QUIET_TAIL):
    """モジュールで 1 回だけ作る見本の配信(作れなければ SkipTest)"""
    if name not in _SHARED:
        p = os.path.join(_shared_dir(), name)
        if not _make_source(p, video=video, audio=audio):
            raise unittest.SkipTest("テスト用動画を作れなかった")
        _SHARED[name] = p
    return _SHARED[name]


def _fake_ytdlp():
    p = os.path.join(_shared_dir(), "fake_ytdlp.py")
    if not os.path.isfile(p):
        with open(p, "w", encoding="utf-8") as f:
            f.write(FAKE_YTDLP)
    return p


def tearDownModule():
    if "dir" in _SHARED:
        shutil.rmtree(_SHARED["dir"], ignore_errors=True)
    _SHARED.clear()


def _job(clips):
    """① の結果の辞書(exporter.new_result と同じ形)"""
    return exporter.new_result({"videoId": "j1", "clips": clips})


def _run(res, spec, on_done=None, ctl=None):
    """① の run を同じ糸で動かす(器 = ② の flow/export は通さない)"""
    exporter.run(spec, res, ctl or jobs.Ctl(), on_done)
    return res


def _spec(src, clips, fast=False, volume=75):
    return {"videoId": VID, "title": "テスト 配信", "clips": clips, "fast": fast, "maxHeight": 0, "volume": volume,
            "kind": "file", "sourceTitle": "テスト 配信", "sourceFile": src, "sourceDuration": 30.0, "mode": "file", "sourcePath": src}


def _store(path, marks, vid=None, duration=30.0, title="テスト 配信"):
    """配信の台帳の代わり(internal だけ)。vid が None なら問い合わせの id をそのまま返す"""
    class Store:
        def internal(self, v):
            return {"id": vid or v, "kind": "file", "path": path, "title": title, "fileName": "", "duration": duration, "marks": marks}
    return Store()


def _fps(path):
    """r_frame_rate(ffprobe が無ければ None)"""
    i = normalize.probe(path)
    return i and i["r_frame_rate"]


def _level(path, ss=None, t=None):
    """デコードした音の平均の大きさ(dB。volumedetect)。ss・t: 測る区間"""
    cut = (["-ss", str(ss)] if ss is not None else []) + (["-t", str(t)] if t is not None else [])
    r = subprocess.run([studio_env.find_tool("ffmpeg"), "-hide_banner", "-nostdin"] + cut + ["-i", path, "-af", "volumedetect", "-vn", "-f", "null", "-"],
                       stdin=subprocess.DEVNULL, stdout=subprocess.PIPE, stderr=subprocess.STDOUT, text=True, errors="replace")
    return float(r.stdout.split("mean_volume:")[1].split("dB")[0])


def _loudness(path):
    return exporter.measure_loudness(jobs.Ctl(), {"start": 0.0, "end": 1.0, "progress": 0.0}, path)


def _y_avg(path):
    """最初のコマの明るさの平均(signalstats の YAVG)"""
    r = subprocess.run([studio_env.find_tool("ffmpeg"), "-hide_banner", "-nostdin", "-i", path, "-vf", "signalstats,metadata=print:key=lavfi.signalstats.YAVG",
                        "-frames:v", "1", "-f", "null", "-"], stdin=subprocess.DEVNULL, stdout=subprocess.PIPE, stderr=subprocess.STDOUT, text=True, errors="replace")
    m = re.search(r"YAVG=([\d.]+)", r.stdout)
    return float(m.group(1)) if m else None


def _leftovers(*dirs):
    """書きかけ・音声の作り直しの途中・一時ファイル・区間取得の途中"""
    return [n for d in dirs if os.path.isdir(d) for n in os.listdir(d)
            if n.endswith((".part", ".vol.mp4")) or n.startswith(".tmp-") or exporter.PARTIAL in n or exporter.DL_TAG in n]


def _read_manifest(path, case):
    """.clip.json を BOM なしの UTF-8 として読む"""
    with open(path, "rb") as f:
        raw = f.read()
    case.assertFalse(raw.startswith(b"\xef\xbb\xbf"), path)
    return json.loads(raw.decode("utf-8")), raw


MARKS = [{"id": "m1", "start": 7.0, "end": 12.0, "label": "見どころ", "src": "manual", "status": "adopted"},
         {"id": "m2", "start": 1.0, "end": 3.0, "label": "", "src": "auto", "status": "adopted"},
         {"id": "m3", "start": 25.0, "end": 40.0, "label": "長いラベル" * 10, "src": "weird", "status": ""},   # 終わりが元の長さ(30 秒)を超える・知らない src
         {"id": "s", "start": 24.0, "end": 26.0, "label": "無音", "src": "manual", "status": ""},   # 余白 3 秒をつけても無音(20 秒から)
         {"id": "a", "start": 2.0, "end": 4.0, "label": "a", "src": "manual", "status": ""},
         {"id": "b", "start": 10.0, "end": 12.0, "label": "b", "src": "manual", "status": ""}]


@unittest.skipUnless(studio_env.find_tool("ffmpeg") and studio_env.find_tool("ffprobe"), "ffmpeg・ffprobe が無い環境ではスキップ")
class TestExportThrough(unittest.TestCase):
    """書き出しの通し: ② の口(build_spec → ExportJobs.start → public)から本物の ffmpeg で 3 回書き出し、
    出来上がった mp4・.clip.json・編集用素材・完了の呼び返し・GET /api/export の形・器の同時 1 本・掲示板をまとめて確かめる。
    出力先は長いパス(書き出し先の上限の近く)・題は長い日本語と絵文字"""
    @classmethod
    def setUpClass(cls):
        cls.src = _source()

    def setUp(self):
        self.tmp = testkit.tempdir(self)
        studio_env.set_home(self.tmp)
        deep = os.path.join(self.tmp, "d" * max(1, 170 - exporter.path_units(studio_env.get_out_dir())))
        studio_env.set_home(deep)   # 書き出し先(<置き場所>/exports)が 170 文字ほど
        self.addCleanup(studio_env.set_home, self.tmp)

    def export(self, req, recorded=lambda mark_id: True, title=LONG_TITLE, during=None):
        spec = _fexport.build_spec(_store(self.src, MARKS, VID, title=title), dict({"id": VID}, **req))
        calls, cmds = [], []

        def on_done(*a, **kw):
            calls.append((a, kw))
            return recorded(a[1])
        real = exporter._pump

        def pump(ctl, cmd, *a, **kw):
            cmds.append(cmd)
            return real(ctl, cmd, *a, **kw)
        ex = _fexport.ExportJobs()
        self.addCleanup(ex.clear)
        board = _board.Board()
        ex.attach_board(board)
        with patch.object(exporter, "_pump", side_effect=pump):
            rec = ex.start(spec, on_done)
            if during:
                during(ex, rec, board)
            self.assertTrue(testkit.wait_for(lambda: not ex.is_busy(), 120, 0.05))
        board.refresh()
        self.assertEqual(board.get("ex:" + rec["id"])["state"], "done")
        return spec, rec, ex.public(rec["id"]), calls, cmds

    def test_export_through(self):
        self.check_requests()
        folder = self.check_precise()
        self.check_fast_margin_loudness(folder)
        self.check_combine()

    def check_requests(self):
        """build_spec(② の口)の検査: 音量・余白・ラウドネスの値・YouTube の配信の ID(URL を組む前に断る)"""
        path = os.path.join(self.tmp, "01_clip.mp4")
        open(path, "wb").close()
        store = _store(path, [{"id": "m1", "start": 1.0, "end": 2.0, "label": ""}])

        def spec(**req):
            return _fexport.build_spec(store, dict({"id": "v1", "markIds": ["m1"]}, **req))
        for bad in (dict(volume=0), dict(volume=201), dict(volume=-5), dict(volume="abc"), dict(margin=99),
                    dict(loudness=-13), dict(loudness=-40), dict(loudness="x"), dict(loudness=[1])):
            with self.subTest(bad=bad), self.assertRaises(errors.ApiError):
                spec(**bad)
        self.assertEqual((spec(margin=10).get("margin"), "margin" in spec()), (10.0, False))
        self.assertEqual((spec()["loudness"], spec(loudness=-14)["loudness"], spec(loudness=0)["loudness"]), (None, -14.0, None))   # 送らなければ音量(%)

        class S:
            def internal(self, vid):
                return {"id": "-o /tmp/x", "kind": "youtube", "marks": [{"id": "m1", "start": 0, "end": 1, "label": ""}], "title": "", "fileName": "", "path": ""}
        with patch.dict(os.environ, {"STUDIO_FAKE": ""}), patch.object(studio_env, "find_tool", return_value="/bin/true"):
            with self.assertRaises(errors.ApiError) as cm:
                _fexport.build_spec(S(), {"id": "x", "markIds": ["m1"]})
        self.assertIn("配信の ID", cm.exception.message)   # 文では配信の意味の「動画」は「配信」と呼ぶ

    def check_precise(self):
        """精度優先・音量 50%・3 本(書き出し中にマークが動いた 1 本・終わりが元の長さを超える 1 本)。動いている間は同時 1 本・書き出し先を変えない"""
        def during(ex, rec, board):
            self.assertTrue(ex.is_busy_for(VID) and not ex.is_busy_for("bbcdefghijk"))
            with self.assertRaises(errors.ApiError) as c:
                ex.start({"videoId": "bbcdefghijk", "clips": []})
            self.assertEqual((c.exception.status, c.exception.code), (409, "busy"))
            with self.assertRaises(errors.ApiError) as c:
                studio_env.set_out_dir(os.path.join(self.tmp, "other"), ex.is_busy)
            self.assertEqual(c.exception.status, 409)
            with self.assertRaises(errors.ApiError) as c:
                ex.public("nai")
            self.assertEqual(c.exception.status, 404)
            board.refresh()
            j = board.get("ex:" + rec["id"])
            self.assertEqual((j["kind"], j["title"], j["canCancel"], j["canRetry"]), ("export", "書き出し 3 本", True, False))
        spec, rec, pub, calls, cmds = self.export({"markIds": ["m1", "m2", "m3"], "volume": 50}, recorded=lambda mid: mid != "m2", during=during)
        res = rec["res"]
        self.assertEqual(list(pub), ["id", "state", "outDir", "folder", "waiting", "items", "combined"])   # GET /api/export の形
        self.assertEqual((rec["state"], pub["state"], pub["folder"], pub["outDir"], pub["waiting"], pub["combined"]),
                         ("done", "done", res["folder"], studio_env.get_out_dir(), False, None))
        self.assertEqual([(p["status"], p["warning"]) for p in pub["items"]], [("done", "")] * 3, [i.get("error") for i in res["items"]])
        self.assertLess(len(res["folder"]), 60)   # 長い題でもフォルダの名前は短く
        it, it2, it3 = res["items"]
        folder = os.path.dirname(it["path"])
        work = os.path.join(folder, schemas.WORK_DIR)   # 途中のファイル
        self.assertEqual([os.path.basename(i["path"])[:3] for i in res["items"]], ["01_", "02_", "03_"])
        for i in res["items"]:   # パスの長さ: 一番長い 作業用/ の中も上限まで・本体は途中の名前の分を残す
            self.assertLessEqual(exporter.path_units(i["editManifest"]), exporter.MAX_PATH_UNITS)
            self.assertLessEqual(exporter.path_units(os.path.splitext(i["path"])[0]) + exporter.SUFFIX_ROOM, exporter.MAX_PATH_UNITS)
        # 精度優先 = veryfast・crf 18 で作り直し、音量(%)は切り出しの -af に入る(後から音声だけ作り直さない)
        cut = [c for c in cmds if "-preset" in c]
        self.assertEqual([(c[c.index("-preset") + 1], c[c.index("-crf") + 1], c[c.index("-af") + 1]) for c in cut], [("veryfast", "18", "volume=0.500")] * 6)
        # 完了の呼び返し: (配信 ID・マーク ID・出力の相対名・始め・終わり・書き出した mp4 の絶対パス = マークに残す)。余白なしは clip を付けない
        self.assertEqual([c[0][:2] for c in calls], [(VID, "m1"), (VID, "m2"), (VID, "m3")])
        self.assertEqual(calls[0], ((VID, "m1", it["file"], 7.0, 12.0, it["path"]), {}))
        self.assertEqual(it["file"], res["folder"] + "/" + os.path.basename(it["path"]))
        # 切り抜き本体: 30fps・長さ・音量 50% = デコードした音が元の同じ所より約 -6dB
        self.assertEqual((_fps(it["path"]), _fps(it["editPath"])), ("30/1", "30/1"))   # 60fps の元から、切り抜きも編集用素材も 30fps に
        self.assertAlmostEqual(mediainfo.media_info(it["path"])[0], 5.0, delta=0.3)
        self.assertAlmostEqual(_level(it["path"]) - _level(self.src, 7, 5), -6.02, delta=0.5)
        # .clip.json(BOM なしの UTF-8・作業用/ に)。出力先が長いので、名前にラベルは入らない
        base = os.path.splitext(os.path.basename(it["path"]))[0]
        self.assertEqual(base, "01_00h00m07s-00h00m12s")
        self.assertEqual(it["manifest"], os.path.join(work, base + ".clip.json"))
        d, _raw = _read_manifest(it["manifest"], self)
        self.assertEqual((d["schema"], d["tool"]), ("youtube-tools-clip/v1", exporter.TOOL))
        self.assertRegex(d["createdAt"], r"[+-]\d\d:\d\d$")
        self.assertEqual((d["media"]["path"], d["media"]["name"]), (it["path"], os.path.basename(it["path"])))
        self.assertAlmostEqual(d["media"]["durationSec"], 5.0, delta=0.3)
        self.assertEqual(round(d["media"]["durationSec"], 3), d["media"]["durationSec"])   # 3 桁に丸める
        self.assertEqual(d["range"], {"start": 7.0, "end": 12.0})   # 元の配信の秒
        self.assertEqual(d["source"], {"kind": "file", "videoId": VID, "url": None, "title": LONG_TITLE, "path": self.src})
        self.assertEqual(d["mark"], {"id": "m1", "label": "見どころ", "status": "exported", "src": "manual"})
        enc = d["export"].pop("encoder")   # 作った作り方の印(GPU が使えない・失敗した PC では libx264)
        self.assertIn(enc, ["libx264"] + [c for c, _a in normalize.GPU_ENCODERS])
        self.assertEqual(d["export"], {"mode": "precise", "volume": 50})   # 余白なしは actualStart なし(= range.start)
        # 前後10秒の編集用素材: 作業用/ に・その範囲の .clip.json・.edit.json は本当の名前を指す
        self.assertTrue(it["editPath"].endswith("_edit.mp4") and os.path.isfile(it["editPath"]) and os.path.dirname(it["editPath"]) == work)
        self.assertEqual(it["editManifest"], os.path.splitext(it["editPath"])[0] + ".clip.json")
        e = testkit.read_json(it["editManifest"])
        self.assertEqual(e["media"]["path"], it["editPath"])
        self.assertEqual(e["range"], {"start": 0.0, "end": 22.0})
        self.assertEqual((e["export"]["purpose"], e["export"]["selection"]), ("edit-handles", {"start": 7.0, "end": 12.0}))
        side = os.path.join(work, base + ".edit.json")
        self.assertEqual(testkit.read_json(side)["media"], os.path.basename(it["editPath"]))
        self.assertFalse(exporter.is_partial(it["path"]) or exporter.is_partial(it["editPath"]))
        # GET /api/export のパス
        p = pub["items"][0]
        self.assertEqual((p["path"], p["manifest"], p["editPath"], p["editManifest"], p["file"]),
                         (it["path"], it["manifest"], it["editPath"], it["editManifest"], it["file"]))
        # 書き出し中にマークを動かした(記録されなかった)1 本は、始めた時点の判定のまま
        d2 = testkit.read_json(it2["manifest"])
        self.assertEqual((d2["mark"]["status"], d2["mark"]["src"]), ("adopted", "auto"))
        # 終わりが元の長さを超える 1 本は元の末尾まで・知らない src は manual に丸める
        d3 = testkit.read_json(it3["manifest"])
        self.assertEqual((d3["range"], d3["mark"]["src"]), ({"start": 25.0, "end": 30.0}, "manual"))
        self.assertEqual(testkit.read_json(it3["editManifest"])["range"], {"start": 15.0, "end": 30.0})
        # 出力先の直下は切り抜きの mp4 だけ・書きかけや途中のファイルは残さない
        self.assertEqual(sorted(n for n in os.listdir(folder) if os.path.isfile(os.path.join(folder, n))),
                         sorted(os.path.basename(i["path"]) for i in res["items"]))
        self.assertEqual(_leftovers(folder, work), [])
        return folder

    def check_fast_margin_loudness(self, folder):
        """同じ配信のフォルダへ 2 回目: 高速(ultrafast で作り直し)・余白 3 秒・ラウドネス -14 LUFS の 2 本(1 本は無音)。
        番号は前の書き出しと書きかけの続きから"""
        open(os.path.join(folder, "メモ.txt"), "w").close()
        partial = os.path.join(folder, "04_00h01m00s-00h01m05s.partial.mp4")   # ほかの書き出しの書きかけも番号を使っている
        open(partial, "wb").close()
        spec, rec, pub, calls, cmds = self.export({"markIds": ["m1", "s"], "precision": "fast", "margin": 3, "loudness": -14})
        os.remove(partial)
        it, si = rec["res"]["items"]
        self.assertEqual((rec["state"], it["status"], it["start"], it["end"]), ("done", "done", 7.0, 12.0), it.get("error"))   # 画面へ返す区間はマークのまま
        self.assertEqual(os.path.dirname(it["path"]), folder)
        self.assertEqual([os.path.basename(i["path"])[:3] for i in (it, si)], ["05_", "06_"])
        # 高速 = 速い設定での作り直し(コピーでは fps を変えられず、開始もキーフレームへずれるため)。ラウドネスのときは -af を付けない
        cut = [c for c in cmds if "-preset" in c]
        self.assertEqual([(c[c.index("-preset") + 1], c[c.index("-crf") + 1], "-af" in c) for c in cut], [("ultrafast", "18", False)] * 4)
        self.assertFalse(any("copy" == c[c.index("-c") + 1] for c in cmds if "-c" in c))
        self.assertEqual((_fps(it["path"]), _fps(it["editPath"])), ("30/1", "30/1"))
        # 余白: 動画は 4〜15 秒・range はマークのまま・actualStart と margin が印
        d = testkit.read_json(it["manifest"])
        self.assertEqual(d["range"], {"start": 7.0, "end": 12.0})
        self.assertAlmostEqual(d["media"]["durationSec"], 11.0, delta=0.3)
        self.assertEqual((d["export"]["mode"], d["export"]["actualStart"], d["export"]["margin"]["before"]), ("fast", 4.0, 3.0))
        self.assertAlmostEqual(d["export"]["margin"]["after"], 3.0, delta=0.3)
        self.assertEqual((schemas.clip_offset(d), schemas.clip_mark_span(d)), (4.0, (3.0, 8.0)))
        (args, kw), _ = calls
        self.assertEqual(args[3:5], (7.0, 12.0))
        self.assertEqual(kw["clip"][0], 4.0)
        self.assertAlmostEqual(kw["clip"][1], 15.0, delta=0.3)
        self.assertEqual(testkit.read_json(it["editManifest"])["range"]["start"], 0.0)   # 編集用素材 = 余白つきの動画の前後 10 秒
        # ラウドネス: 切り抜きと編集用素材に同じ量をかけて、どちらも目標に(同じ音なので同じ大きさ)・ピークは上限まで
        lo = it["loudness"]
        self.assertEqual(lo["target"], -14.0)
        self.assertAlmostEqual(lo["measured"], _loudness(self.src)[0], delta=1.0)
        i_main, tp_main = _loudness(it["path"])
        self.assertAlmostEqual(i_main, -14.0, delta=1.0)
        self.assertAlmostEqual(_loudness(it["editPath"])[0], -14.0, delta=1.0)
        self.assertLessEqual(tp_main, exporter.TRUE_PEAK_CEIL + 0.5)
        for m in (it["manifest"], it["editManifest"]):
            ex = testkit.read_json(m)["export"]
            self.assertEqual(ex["loudness"], lo)
            self.assertNotIn("volume", ex)   # 音量(%)は使っていない
        self.assertEqual(pub["items"][0]["loudness"], lo)
        # 無音の切り抜き: 測れないので skipped・音声を作り直さない(作り直しは 1 本目の本体と編集用素材の 2 回だけ)
        self.assertEqual((si["status"], si["loudness"]["target"]), ("done", -14.0), si.get("error"))
        self.assertIn("skipped", si["loudness"])
        self.assertEqual(sum(1 for c in cmds if "-c:v" in c and c[c.index("-c:v") + 1] == "copy"), 2)
        self.assertEqual(_loudness(si["path"]), (None, None))
        self.assertEqual(_leftovers(folder, os.path.join(folder, schemas.WORK_DIR)), [])

    def check_combine(self):
        """つなぐ: 選んだ順でなく時刻の順・余白は足さない・音量は既定(75%)・30fps の 1 本だけが残る。題が予約名(CON.txt)でもフォルダを作れる"""
        spec, rec, pub, calls, cmds = self.export({"markIds": ["b", "a"], "combine": True, "margin": 3}, title="CON.txt")
        self.assertEqual(([c["id"] for c in spec["clips"]], spec["volume"]), (["a", "b"], exporter.DEFAULT_EXPORT_VOLUME))
        self.assertNotIn("margin", spec)
        c = rec["res"]["combined"]
        self.assertEqual((rec["state"], c["status"], rec["res"]["folder"]), ("done", "done", "_CON.txt"), c.get("error"))
        self.assertAlmostEqual(mediainfo.media_info(c["path"])[0], 4.0, delta=0.3)
        self.assertEqual(_fps(c["path"]), "30/1")
        self.assertAlmostEqual(_level(c["path"]) - _level(self.src, 2, 2), 20 * math.log10(0.75), delta=0.5)
        self.assertEqual((pub["combined"]["path"], pub["combined"]["count"]), (c["path"], 2))
        self.assertEqual(calls, [])   # つないだ 1 本はマークに「書き出し済み」を付けない
        folder = os.path.dirname(c["path"])
        work = os.path.join(folder, schemas.WORK_DIR)
        self.assertTrue(os.path.isfile(c["path"]) and os.path.dirname(c["path"]) == folder)   # 出力先の直下に 1 本
        self.assertEqual([n for d in (folder, work) for n in os.listdir(d) if n.startswith("つなぐ_")], [])   # 切り出した部品は消える
        self.assertEqual(_leftovers(folder, work), [])


@unittest.skipUnless(studio_env.find_tool("ffmpeg"), "ffmpeg が無い環境ではスキップ")
class TestExportFailures(unittest.TestCase):
    """途中の失敗・中止: 完成品の名前のファイル・書きかけ・部品・.edit.json を残さない"""
    @classmethod
    def setUpClass(cls):
        cls.src = _source()

    def setUp(self):
        self.tmp = testkit.tempdir(self)
        studio_env.set_home(self.tmp)

    def export(self, clips):
        calls = []
        job = _run(_job(clips), _spec(self.src, clips), lambda *a: calls.append(a) or True)
        return job, calls

    def _files(self, job):
        folder = os.path.join(studio_env.get_out_dir(), job["folder"])
        out = []
        for d in (folder, os.path.join(folder, schemas.WORK_DIR)):
            if os.path.isdir(d):
                out += [n for n in os.listdir(d) if os.path.isfile(os.path.join(d, n)) and n != ".studio-id"]
        return sorted(out)

    def test_combine_failure_leaves_no_piece(self):
        """つなぐ書き出しが部品の 2 本目・つなぐ段のどちらで失敗しても、切り出した部品と書きかけを残さない"""
        clips = [{"id": "a", "start": 2.0, "end": 4.0, "title": "a", "label": "a", "src": "manual", "markStatus": ""},
                 {"id": "b", "start": 10.0, "end": 12.0, "title": "b", "label": "b", "src": "manual", "markStatus": ""}]
        real = exporter.run_ffmpeg
        n = [0]

        def second_fails(ctl, spec, it, base):
            n[0] += 1
            if n[0] == 2:
                raise exporter.ExportError("2 本目の切り出し 失敗")
            return real(ctl, spec, it, base)
        for name, patcher in (("piece", patch.object(exporter, "run_ffmpeg", side_effect=second_fails)),
                              ("concat", patch.object(exporter, "concat_pieces", side_effect=exporter.ExportError("つなぐ 失敗")))):
            with self.subTest(name=name):
                n[0] = 0
                job = _job(clips)
                with patcher:
                    _run(job, dict(_spec(self.src, clips), combine=True))
                self.assertEqual((job["state"], job["combined"]["status"]), ("error", "error"))
                self.assertEqual(self._files(job), [])

    def test_failure_after_cut_leaves_no_file(self):
        """切り出しのあと(ラウドネスの調整など)で失敗しても、完成品の名前のファイル・書きかけ・.edit.json を残さない。GET /api/export はパスを出さない"""
        clip = {"id": "m7", "start": 7.0, "end": 12.0, "title": "x", "label": "", "src": "manual", "markStatus": ""}
        seen = []

        def boom(job, spec, it):
            seen.append((it["path"], it.get("editPath")))
            raise exporter.ExportError("ラウドネス調整 失敗")
        with patch.object(exporter, "apply_loudness", side_effect=boom):
            job, calls = self.export([clip])
        it = job["items"][0]
        self.assertEqual((job["state"], it["status"]), ("error", "error"))
        self.assertTrue(exporter.is_partial(seen[0][0]) and exporter.is_partial(seen[0][1]))   # 仕上げの間は書きかけの名前
        self.assertEqual(self._files(job), [])
        self.assertEqual(calls, [])   # 書き出し済みの記録もしない
        pub = exporter.result_public(job)["items"][0]
        self.assertEqual((pub["path"], pub["manifest"], pub["editPath"], pub["editManifest"]), (None, None, None, None))

    def test_cancel_during_edit_media_leaves_no_file(self):
        clip = {"id": "m8", "start": 7.0, "end": 12.0, "title": "x", "label": "", "src": "manual", "markStatus": ""}
        real = exporter.run_ffmpeg
        state = {"n": 0}

        def cancel_on_second(job, spec, it, base):   # 1回目 = 本体、2回目 = 編集用素材 の切り出しで「中止」
            state["n"] += 1
            if state["n"] == 2:
                job.cancel()   # job = ① に渡る Ctl
                raise exporter.ExportError("中止しました")
            return real(job, spec, it, base)
        with patch.object(exporter, "run_ffmpeg", side_effect=cancel_on_second):
            job, _ = self.export([clip])
        self.assertEqual((job["state"], job["items"][0]["status"]), ("cancelled", "cancelled"))
        self.assertEqual(self._files(job), [])


class TestLegacyFfmpeg(unittest.TestCase):
    def test_old_ffmpeg_retries_once_with_vsync(self):
        """ffmpeg 5.1 より古い(-fps_mode を知らない)ときは -vsync に替えて 1 回だけやり直す。中止ではやり直さない(ほかの失敗の判定は ytt 側)"""
        old = (1, ["Unrecognized option 'fps_mode'.", "Error splitting the argument list: Option not found"], None)
        cmd = ["ffmpeg", "-i", "a.mp4"] + exporter.ENC + ["out.mp4"]
        calls = []

        def fake(results):
            def once(job, c, it, dur, span):
                calls.append(c)
                return results.pop(0)
            return once
        job, it = jobs.Ctl(), {}
        with patch.object(exporter, "_pump_once", fake([old, (0, ["ok"], None)])):
            self.assertEqual(exporter._pump(job, cmd, it, 2.0), ["ok"])
        self.assertEqual((len(calls), "-vsync" in calls[1], "-fps_mode" in calls[1]), (2, True, False))
        calls.clear()
        with patch.object(exporter, "_pump_once", fake([(1, list(old[1]), "cancel")])), self.assertRaises(exporter.ExportError) as cm:
            stop = jobs.Ctl()
            stop.cancel()
            exporter._pump(stop, cmd, it, 2.0)
        self.assertEqual((len(calls), str(cm.exception)), (1, "中止しました"))


class TestPartialNames(unittest.TestCase):
    def test_clean_partials_only_in_studio_folders(self):
        """前回の途中(落ちた・止めた)で残った書きかけを、起動時にスタジオのフォルダの中だけ消す"""
        with tempfile.TemporaryDirectory() as root:
            ours, theirs = os.path.join(root, "配信A"), os.path.join(root, "手で作った")
            exporter._write_owner(ours, "abcdefghijk")
            os.makedirs(theirs)
            keep = [os.path.join(ours, "01_a.mp4"), os.path.join(ours, schemas.WORK_DIR, "01_a_edit.mp4"), os.path.join(theirs, "x.partial.mp4")]
            gone = [os.path.join(ours, "02_b.partial.mp4"), os.path.join(ours, schemas.WORK_DIR, "02_b_edit.partial.mp4"),
                    os.path.join(ours, "03_c.partial.f399.mp4.part"), os.path.join(ours, "02_b.partial.mp4.vol.mp4")]
            for f in keep + gone:
                open(f, "wb").close()
            self.assertEqual(exporter.clean_partials(root), len(gone))
            self.assertEqual([f for f in keep if os.path.exists(f)], keep)
            self.assertEqual([f for f in gone if os.path.exists(f)], [])
            # 書き出しが始まっていたら消さない(busy = 器 flow/export の is_busy を呼び手が渡す)
            open(gone[0], "wb").close()
            self.assertEqual(exporter.clean_partials(root, busy=lambda: True), 0)
            self.assertTrue(os.path.exists(gone[0]))


class TestManifestFailure(unittest.TestCase):
    def test_manifest_write_failure_is_only_a_warning(self):
        with tempfile.TemporaryDirectory() as tmp:
            studio_env.set_home(tmp)
            item = {"id": "m1", "start": 0.0, "end": 5.0, "label": "", "title": "t", "src": "manual", "markStatus": ""}
            job = _job([item])
            spec = {"videoId": "abcdefghijk", "mode": "file", "kind": "youtube", "title": "t"}
            denied = PermissionError(13, "denied", os.path.join(tmp, "clip.clip.json"))
            with patch.object(exporter, "pick_folder", return_value=("video", tmp)), \
                    patch.object(exporter, "run_ffmpeg", return_value="video/clip.mp4"), \
                    patch.object(exporter, "export_edit_media", return_value="video/clip_edit.mp4"), \
                    patch.object(exporter, "write_clip", side_effect=denied), patch.object(studio_env, "log_failure") as log:
                _run(job, spec, Mock(return_value=True))
            it = job["items"][0]
            self.assertEqual((job["state"], it["status"]), ("done", "done"))   # 書き出し自体は成功
            self.assertIn(".clip.json", it["warning"])
            self.assertIn("clip.clip.json", it["warning"])   # どのファイルか分かる
            pub = exporter.result_public(job)["items"][0]
            self.assertEqual((pub["path"], pub["manifest"]), (os.path.join(tmp, "clip.mp4"), None))
            log.assert_called_once()

    def test_unknown_duration_is_null(self):
        """書き出した動画の長さを測れなかった(ffprobe が読めない)ときは durationSec を null に"""
        d = schemas.build_clip("a.mp4", None, {"kind": "file", "videoId": VID, "title": "t", "path": "C:\\v\\元.mp4"}, (0, 5), {"id": "m1"}, {"mode": "fast"}, exporter.TOOL)
        self.assertIsNone(d["media"]["durationSec"])


class TestExportLog(unittest.TestCase):
    def test_log_is_rotated_not_deleted(self):
        """export-log.txt が上限を超えたら 1 世代 .old に回す(長く使った後にしか来ない)"""
        with tempfile.TemporaryDirectory() as tmp, patch.object(studio_env, "get_out_dir", return_value=tmp), patch.object(exporter, "LOG_MAX", 100):
            exporter.log_export("first " + "x" * 200, ["ffmpeg"], [])
            exporter.log_export("second", ["ffmpeg"], [])
            with open(os.path.join(tmp, "export-log.old.txt"), encoding="utf-8") as f:
                self.assertIn("first", f.read())
            with open(os.path.join(tmp, "export-log.txt"), encoding="utf-8") as f:
                self.assertIn("second", f.read())


# 偽物の yt-dlp: --download-sections の区間を、手元の動画から本物の yt-dlp と同じ形(入力側の -ss + コピー)で取る。
# 受け取った引数を FAKE_YTDLP_LOG に1行ずつ残す。FAKE_YTDLP_PREROLL=1 なら頼んだより3秒手前から取る(位置が分からない場合)。-g(方法2)は失敗する
FAKE_YTDLP = r'''
import json, os, subprocess, sys
args = sys.argv[1:]
with open(os.environ["FAKE_YTDLP_LOG"], "a", encoding="utf-8") as f:
    f.write(json.dumps(args) + "\n")
if "-g" in args:
    print("ERROR: fake", file=sys.stderr)
    sys.exit(1)
val = lambda k: args[args.index(k) + 1]
def secs(t):
    h, m, s = t.split(":")
    return int(h) * 3600 + int(m) * 60 + float(s)
a, b = val("--download-sections").lstrip("*").split("-")
s, e = secs(a), secs(b)
if os.environ.get("FAKE_YTDLP_PREROLL") == "1":
    s = max(0.0, s - 3)
out = val("-o").replace("%(ext)s", "mp4").replace("%%", "%")
print("[download] Destination: " + out, flush=True)
r = subprocess.run([val("--ffmpeg-location"), "-hide_banner", "-loglevel", "error", "-nostdin", "-y", "-ss", "%.3f" % s, "-t", "%.3f" % (e - s),
                    "-i", os.environ["FAKE_YTDLP_SRC"], "-c", "copy", "-f", "mp4", out], stdin=subprocess.DEVNULL)
sys.exit(r.returncode)
'''


def _youtube_spec(clips):
    spec = dict(_spec(None, clips), kind="youtube", videoId="abcdefghijk", sourceFile=None, mode="url")
    spec.pop("sourcePath")
    return spec


@unittest.skipUnless(studio_env.find_tool("ffmpeg") and studio_env.find_tool("ffprobe"), "ffmpeg・ffprobe が無い環境ではスキップ")
class TestYoutubeTwoStage(unittest.TestCase):
    """YouTube の区間取得(2段: yt-dlp で区間をそのまま取る → ffmpeg で正確な区間に切る)の yt-dlp の失敗の道。正しく動く道は TestLiveSection の通し"""
    @classmethod
    def setUpClass(cls):
        cls.src = _source("yt.mp4", BRIGHT, None)
        cls.fake = _fake_ytdlp()

    def setUp(self):
        self.tmp = testkit.tempdir(self)
        studio_env.set_home(self.tmp)
        self.log = os.path.join(self.tmp, "ytdlp-args.jsonl")

    def calls(self):
        with open(self.log, encoding="utf-8") as f:
            return [json.loads(l) for l in f]

    def test_blocked_by_youtube_stops_asking_again(self):
        """YouTube に止められた(bot 判定)ら、方法2(-g)も同じ動画の残りの切り抜きも yt-dlp を呼ばない = 1 回だけ問い合わせて全部同じ失敗"""
        msg = "ERROR: [youtube] abcdefghijk: Sign in to confirm you’re not a bot. Use --cookies-from-browser or --cookies"
        bad = os.path.join(self.tmp, "bot_ytdlp.py")
        with open(bad, "w", encoding="utf-8") as f:
            f.write("import json, os, sys\nopen(os.environ['FAKE_YTDLP_LOG'], 'a').write(json.dumps(sys.argv[1:]) + '\\n')\n"
                    "sys.stderr.buffer.write(%r.encode('utf-8') + b'\\n')\nsys.exit(1)\n" % msg)
        clips = [{"id": "m%d" % i, "start": 3.0 * i, "end": 3.0 * i + 2, "title": "t", "label": "", "src": "manual", "markStatus": ""} for i in range(1, 4)]
        job = _job(clips)
        with patch.dict(os.environ, {"FAKE_YTDLP_LOG": self.log}), patch.object(exporter, "_ytdlp_cmd", return_value=[sys.executable, bad]):
            _run(job, _youtube_spec(clips), lambda *a: True)
        calls = self.calls()
        self.assertEqual(len(calls), 1, calls)   # 区間取得の 1 回だけ(-g も 2 本目・3 本目も呼ばない)
        self.assertEqual([it["status"] for it in job["items"]], ["error"] * 3)
        self.assertTrue(all("not a bot" in it["error"] for it in job["items"]))
        self.assertIn("試していません", job["items"][0]["error"])
        self.assertTrue(exporter.blocked("HTTP Error 429: Too Many Requests") and not exporter.blocked("timed out"))

    def test_ytdlp_error_text_is_read_as_utf8(self):
        """yt-dlp のエラーの文(UTF-8)が化けない: ’ ' と全角の記号がそのまま失敗の文に。
        本物の yt-dlp.exe は --encoding utf-8 が無いと管に cp932 で書くので、起こすコマンドに必ず付ける"""
        with patch.object(studio_env, "find_tool", lambda n: "yt-dlp.exe"):
            self.assertEqual(exporter._ytdlp_cmd(), ["yt-dlp.exe", "--encoding", "utf-8"])
        msg = "ERROR: [youtube] abcdefghijk: Sign in to confirm you’re not a bot. it's【全角】「記号」〜"
        bad = os.path.join(self.tmp, "bad_ytdlp.py")
        with open(bad, "w", encoding="utf-8") as f:
            f.write("import sys\nsys.stderr.buffer.write(%r.encode('utf-8') + b'\\n')\nsys.exit(1)\n" % msg)
        clip = {"id": "m1", "start": 7.0, "end": 12.0, "title": "t", "label": "", "src": "manual", "markStatus": ""}
        job = _job([clip])
        with patch.object(exporter, "_ytdlp_cmd", return_value=[sys.executable, bad]):
            _run(job, _youtube_spec([clip]), lambda *a: True)
        err = job["items"][0].get("error") or ""
        self.assertIn("you’re not a bot", err)
        self.assertIn("it's【全角】「記号」〜", err)
        self.assertNotIn("\ufffd", err)
        # 本物の yt-dlp(無い環境ではここだけ飛ばす)に URL でない文字(’ と全角)を渡す = ネットを使わずにエラーの文が出る。_ytdlp_cmd の形で UTF-8 のまま読める
        if studio_env.find_tool("yt-dlp"):
            from ytt import procs as _procs
            p = _procs.run_short(exporter._ytdlp_cmd() + ["--", "テスト’you're【】"], timeout=60)
            self.assertNotEqual(p.returncode, 0)
            self.assertIn("テスト’you're【】", p.stderr)

    def test_unknown_start_falls_back_and_cleans_up(self):
        """取ったファイルが頼んだより長い(手前のキーフレームから見えている)ときは、位置が分からないので方法2(直接指定)へ回す"""
        clip = {"id": "m1", "start": 15.0, "end": 17.5, "title": "t", "label": "", "src": "manual", "markStatus": ""}   # 取る始まり 5 秒より手前から取れる所
        job = _job([clip])
        env = {"FAKE_YTDLP_LOG": self.log, "FAKE_YTDLP_SRC": self.src, "FAKE_YTDLP_PREROLL": "1"}
        with patch.dict(os.environ, env), patch.object(exporter, "_ytdlp_cmd", return_value=[sys.executable, self.fake]):
            _run(job, _youtube_spec([clip]), lambda *a: True)
        it = job["items"][0]
        self.assertEqual(it["status"], "error")
        self.assertIn("開始の位置", it["error"])
        self.assertIn("-g", self.calls()[-1])   # 方法2 を試した
        folder = os.path.join(studio_env.get_out_dir(), job["folder"])
        left = [n for dd in (folder, os.path.join(folder, schemas.WORK_DIR)) if os.path.isdir(dd) for n in os.listdir(dd)
                if os.path.isfile(os.path.join(dd, n)) and n != ".studio-id"]
        self.assertEqual(left, [])


@unittest.skipUnless(studio_env.find_tool("ffmpeg") and studio_env.find_tool("ffprobe"), "ffmpeg・ffprobe が無い環境ではスキップ")
class TestLiveSection(unittest.TestCase):
    """YouTube の通し(書き出しの 2 段と、POST /api/live/section の区間の書き出し・疑似モード・依頼の検査)と、区間の書き出しの失敗・上書き・中止。
    区間の書き出しは、YouTube の videoId の区間を今の YouTube の書き出しと同じ中身で、ちょうど指定の path へ(マーク・.clip.json・編集用素材は作らない)"""
    @classmethod
    def setUpClass(cls):
        cls.src = _source("yt.mp4", BRIGHT, None)
        cls.fake = _fake_ytdlp()

    def setUp(self):
        self.tmp = testkit.tempdir(self)
        studio_env.set_home(self.tmp)
        self.folder = os.path.join(studio_env.get_out_dir(), "配信フォルダ")
        os.makedirs(self.folder)
        self.final = os.path.join(self.folder, "01_速報版を作り直す.mp4")
        self.log = os.path.join(self.tmp, "ytdlp-args.jsonl")
        real = studio_env.find_tool
        self.patches = [patch.dict(os.environ, {"STUDIO_FAKE": "0", "FAKE_YTDLP_LOG": self.log, "FAKE_YTDLP_SRC": self.src, "FAKE_YTDLP_PREROLL": ""}),
                        patch.object(studio_env, "find_tool", lambda n: "yt-dlp" if n == "yt-dlp" else real(n)),   # 本物の yt-dlp が無くても組み立てられる
                        patch.object(exporter, "_ytdlp_cmd", return_value=[sys.executable, self.fake])]
        for p in self.patches:
            p.start()

    def tearDown(self):
        for p in self.patches:
            p.stop()

    def req(self, **kw):
        return dict({"videoId": "abcdefghijk", "start": 7, "end": 12, "path": self.final}, **kw)

    def run_section(self, **kw):
        spec = exporter.build_section_spec(self.req(**kw))
        return _run(exporter.new_result(spec), spec)

    def tree(self):
        return sorted(os.path.relpath(os.path.join(d, n), self.folder) for d, _ds, ns in os.walk(self.folder) for n in ns)

    def sections(self):
        """yt-dlp に頼んだ区間(読んだら記録を消す)"""
        with open(self.log, encoding="utf-8") as f:
            calls = [json.loads(l) for l in f]
        os.remove(self.log)
        self.assertFalse(any("--force-keyframes-at-cuts" in c for c in calls))   # 区間取得では作り直さない
        return [c[c.index("--download-sections") + 1] for c in calls]

    def test_youtube_export_and_section_through(self):
        self.check_bad_requests()
        # 書き出し: 前後に編集用素材の 10 秒(EDIT_HANDLE_SEC。SECTION_PAD より広い)の余裕で 1 回だけ取り(本体と編集用素材は同じ取得から切る)、
        # 正確な区間・30fps に切る。.clip.json に API キーを入れない
        clip = {"id": "m1", "start": 7.0, "end": 12.0, "title": "t", "label": "見どころ.v2", "src": "manual", "markStatus": ""}   # 名前に点
        cmds, real = [], exporter._pump
        with patch.dict(os.environ, {"YOUTUBE_API_KEY": "AIzaSyDUMMYKEYDUMMYKEY12345"}), \
                patch.object(exporter, "_pump", side_effect=lambda ctl, cmd, *a, **kw: cmds.append(cmd) or real(ctl, cmd, *a, **kw)):
            job = _run(_job([clip]), dict(_youtube_spec([clip]), sourceTitle="配信 <b>", volume=100), lambda *a: True)
        it = job["items"][0]
        self.assertEqual((job["state"], it["status"]), ("done", "done"), it.get("error"))
        self.assertTrue(cmds and not [c for c in cmds if "-af" in c], cmds)   # 音量 100% は音のフィルタを足さない
        self.assertEqual((cmds[-1].count("-i"), cmds[-1].count("-ss")), (1, 2), cmds)   # 本体と編集用素材を 1 本の ffmpeg で(読み込み 1 回)
        self.assertEqual(self.sections(), ["*00:00:00.000-00:00:22.000"])
        self.assertAlmostEqual(mediainfo.media_info(it["path"])[0], 5.0, delta=0.2)
        self.assertEqual((_fps(it["path"]), _fps(it["editPath"])), ("30/1", "30/1"))
        self.assertAlmostEqual(_y_avg(it["path"]), 56, delta=3)      # 最初のコマ = 元の 7 秒(余裕の秒ぶんずれていない)
        self.assertAlmostEqual(_y_avg(it["editPath"]), 0, delta=3)   # 編集用素材は 0 秒から
        base = os.path.splitext(os.path.basename(it["path"]))[0]
        self.assertTrue(base.endswith("_見どころ.v2"), base)
        self.assertEqual(it["manifest"], os.path.join(os.path.dirname(it["path"]), schemas.WORK_DIR, base + ".clip.json"))   # 最後の拡張子だけを替える
        d, raw = _read_manifest(it["manifest"], self)
        self.assertEqual((d["range"], d["export"]["mode"]), ({"start": 7.0, "end": 12.0}, "precise"))
        self.assertEqual(d["source"], {"kind": "youtube", "videoId": "abcdefghijk", "url": "https://www.youtube.com/watch?v=abcdefghijk",
                                       "title": "配信 <b>", "path": None})   # youtube のときは元のパスを入れない
        self.assertNotIn(b"AIza", raw)
        folder = os.path.dirname(it["path"])
        self.assertEqual(_leftovers(folder, os.path.join(folder, schemas.WORK_DIR)), [])   # 取った区間(_dl)・書きかけは残さない
        # 区間の書き出し(ラウドネスつき・高速・高さの上限): 今の書き出しと同じ区間取得(前後 2 秒)・ちょうど指定の path に仕上がりの mp4 だけ
        spec = exporter.build_section_spec(self.req(volume=100, loudness=-14, maxHeight=720, precision="fast"))
        self.assertEqual((spec["volume"], spec["loudness"], spec["maxHeight"], spec["fast"], spec["mode"]), (100, -14.0, 720, True, "url"))
        job = _run(exporter.new_result(spec), spec)
        it = job["items"][0]
        self.assertEqual((job["state"], it["status"]), ("done", "done"), it.get("error"))
        pub = exporter.result_public(job)["items"][0]
        self.assertEqual((pub["path"], pub["manifest"], pub["editPath"], pub["status"]), (self.final, None, None, "done"))
        self.assertEqual(pub["file"], "配信フォルダ/" + os.path.basename(self.final))
        self.assertAlmostEqual(pub["loudness"]["target"], -14.0)
        self.assertEqual(self.sections(), ["*00:00:05.000-00:00:14.000"])
        self.assertAlmostEqual(mediainfo.media_info(self.final)[0], 5.0, delta=0.2)
        self.assertEqual(_fps(self.final), "30/1")
        self.assertAlmostEqual(_y_avg(self.final), 56, delta=3)
        self.assertEqual(self.tree(), [os.path.basename(self.final)])   # .clip.json・編集用素材・書きかけ・取った区間・.studio-id は作らない
        self.assertEqual(os.listdir(os.path.join(self.folder, schemas.WORK_DIR)), [])
        # 疑似モード(STUDIO_FAKE): yt-dlp を使わず、手元の見本の動画から同じ区間を書き出す(音量を送らなければ既定)
        fake = os.path.join(self.folder, "02_疑似.mp4")
        with patch.dict(os.environ, {"STUDIO_FAKE": "1", "STUDIO_FAKE_MEDIA": self.src}):
            spec = exporter.build_section_spec(self.req(path=fake))
            self.assertEqual((spec["mode"], spec["sourcePath"], spec["volume"]), ("file", self.src, exporter.DEFAULT_EXPORT_VOLUME))
            job = _run(exporter.new_result(spec), spec)
        self.assertEqual(job["items"][0]["status"], "done", job["items"][0].get("error"))
        self.assertEqual(_fps(fake), "30/1")
        self.assertAlmostEqual(_y_avg(fake), 56, delta=3)
        self.assertFalse(os.path.exists(self.log))   # yt-dlp は呼ばない
        with patch.dict(os.environ, {"STUDIO_FAKE": "1", "STUDIO_FAKE_MEDIA": ""}), self.assertRaises(errors.ApiError) as c:
            exporter.build_section_spec(self.req(path=os.path.join(self.folder, "c.mp4")))
        self.assertEqual(c.exception.status, 500)

    def check_bad_requests(self):
        """区間の書き出しの依頼の検査(配信の ID・区間・path は書き出し先の中の新しい .mp4 だけ・音量・ラウドネス・精度)"""
        out = studio_env.get_out_dir()
        os.makedirs(os.path.join(out, "x"), exist_ok=True)
        exists = os.path.join(self.folder, "exists.mp4")
        with open(exists, "wb") as f:
            f.write(b"x")
        bads = [dict(videoId="short"), dict(videoId="abcdefghijk\n"), dict(videoId="あいうえおかきくけこさ"), dict(videoId=None), dict(videoId=12345678901), dict(videoId="abcdefghij/"),
                dict(start=-1), dict(start=12), dict(start=13), dict(end=7), dict(start="7"), dict(start=None), dict(start=True), dict(end=float("nan")), dict(end=float("inf")),
                dict(start=0, end=3601), dict(end=None), dict(start=10 ** 400), dict(end=10 ** 400),   # float にできない巨大な整数(OverflowError にしない)
                dict(path=None), dict(path=""), dict(path="rel.mp4"), dict(path=os.path.join(self.folder, "a.mkv")), dict(path=os.path.join(self.folder, "a")),
                dict(path=os.path.join(self.folder, "a%b.mp4")), dict(path=os.path.join(self.folder, "a.partial.mp4")), dict(path=os.path.join(self.folder, "CON.mp4")),
                dict(path=os.path.join(_shared_dir(), "outside.mp4")), dict(path=os.path.join(out, "..", "outside.mp4")), dict(path=os.path.join(self.folder, "..", "..", "o.mp4")),
                dict(path=os.path.join(out, "nodir", "a.mp4")), dict(path=exists), dict(path=os.path.join(self.folder, "a" * 300 + ".mp4")),
                dict(path=os.path.join(out, "x")), dict(path="a\x00.mp4"),
                dict(volume=0), dict(volume=201), dict(volume="abc"), dict(loudness=-13), dict(loudness="x"), dict(precision="turbo")]
        for kw in bads:
            with self.subTest(kw=kw), self.assertRaises(errors.ApiError) as c:
                exporter.build_section_spec(self.req(**kw))
            self.assertEqual((c.exception.status, c.exception.code), (400, "bad_request"), kw)
        # 正しい形は通る(マークも配信の登録も要らない)・path の親が書き出し先そのもの(直下)でもよい・送らなければ音量は既定
        self.assertEqual(exporter.build_section_spec(self.req(path=os.path.join(out, "direct.mp4")))["outDir"], out)
        got = exporter.build_section_spec(self.req(start=0, end=3600, loudness=0, maxHeight=None, volume=None))
        self.assertEqual((got["clips"][0]["end"], got["volume"]), (3600.0, exporter.DEFAULT_EXPORT_VOLUME))
        os.remove(exists)

    def test_failure_leaves_nothing(self):
        with patch.dict(os.environ, {"FAKE_YTDLP_PREROLL": "1"}):   # 取った区間の開始の位置が分からない → 方法2(失敗)
            job = self.run_section(start=9.5, end=12)
        self.assertEqual((job["state"], job["items"][0]["status"]), ("error", "error"))
        self.assertFalse(os.path.exists(self.final))
        self.assertEqual(self.tree(), [])

    def test_does_not_overwrite_a_file_that_appeared(self):
        def appear(*a, **kw):
            with open(self.final, "wb") as f:
                f.write(b"mine")
        with patch.object(exporter, "apply_loudness", side_effect=appear):
            job = self.run_section()
        self.assertEqual(job["items"][0]["status"], "error")
        with open(self.final, "rb") as f:
            self.assertEqual(f.read(), b"mine")
        self.assertEqual(self.tree(), [os.path.basename(self.final)])   # 書きかけは消える

    def test_cancel(self):
        def slow(ctl, *a, **kw):
            for _ in range(200):
                if ctl.cancelled:
                    raise exporter.ExportError("中止しました")
                time.sleep(0.05)
        with patch.object(exporter, "run_ytdlp", side_effect=slow):
            spec = exporter.build_section_spec(self.req())
            job, ctl = exporter.new_result(spec), jobs.Ctl()   # 同時 1 本(409)は器 = ② の flow/export の側(通しの TestExportThrough)
            t = threading.Thread(target=_run, args=(job, spec, None, ctl))
            t.start()
            time.sleep(0.2)
            ctl.cancel()
            t.join(10)
        self.assertEqual((job["state"], job["items"][0]["status"]), ("cancelled", "cancelled"))
        self.assertFalse(os.path.exists(self.final))


if __name__ == "__main__":
    unittest.main(verbosity=1)
