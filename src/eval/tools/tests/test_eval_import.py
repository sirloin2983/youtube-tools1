# -*- coding: utf-8 -*-
"""src/eval/tools/eval_import.py(評価データの取り込みチェック。友人用簡易版の計画 L5)のテスト。リポジトリ直下で:

    py -3.10 -m unittest src/eval/tools/tests/test_eval_import.py

すべて一時フォルダの中で作って確かめる(本物の置き場所 %LOCALAPPDATA%\\youtube-tools\\eval-intake は使わない)。
"""
import io
import json
import os
import shutil
import sys
import tempfile
import unittest
import zipfile

os.environ.setdefault("YTT_DATA_DIR", "inplace")
HERE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))   # src/eval/tools (道具の置き場所)
SRC = os.path.dirname(os.path.dirname(HERE))   # src(ツールと共通部品 ytt の置き場所)
REPO = os.path.dirname(SRC)   # リポジトリ直下
sys.path.insert(0, SRC)
from eval.tools import eval_import as I  # noqa: E402
from ytt_core import evaldata as ev  # noqa: E402

WID = "0123456789ab"


def parts(work_id=WID, streamer="配信者A", rows=None, raw=None, performers=None):
    """正しい中身(meta・final・asr_raw)の dict"""
    common = {"format": ev.FORMAT, "formatVersion": ev.FORMAT_VERSION, "workId": work_id}
    rows = rows if rows is not None else [
        {"id": "r1", "start": 0.0, "end": 1.5, "text": "えー こんにちは", "speaker": streamer, "checked": True, "raw": [0]},
        {"id": "r2", "start": 1.5, "end": 3.0, "text": "それな【笑】", "speaker": streamer, "checked": True, "raw": [1]},
        {"id": "r3", "start": 3.0, "end": 4.0, "text": "まだ", "speaker": streamer, "checked": False, "raw": [2]},
    ]
    raw = raw if raw is not None else [{"start": 0.0, "end": 1.5, "text": "えーこんにちは"}, {"start": 1.5, "end": 3.0, "text": "それな"},
                                       {"start": 3.0, "end": 4.0, "text": "まだ"}]
    meta = dict(common, rulesVersion=ev.RULES_VERSION, streamer=streamer,
                performers=performers if performers is not None else sorted({r["speaker"] for r in rows if r.get("checked")}),
                sourceName="video.mp4")
    return {"meta.json": meta, "final.json": dict(common, rows=rows), "asr_raw.json": dict(common, segments=raw)}


def write_zip(path, p=None, extra=None, drop=(), edits=b'{"op":"confirm","row":"r1","played":false}\n'):
    p = p or parts()
    with zipfile.ZipFile(path, "w", zipfile.ZIP_DEFLATED) as z:
        if "audio.flac" not in drop:
            z.writestr("audio.flac", b"fLaC" + b"\0" * 64)
        for k, v in p.items():
            if k not in drop:
                z.writestr(k, json.dumps(v, ensure_ascii=False))
        if "edits.jsonl" not in drop:
            z.writestr("edits.jsonl", edits)
        for name, data in (extra or {}).items():
            z.writestr(name, data)
    return path


def snapshot(root, skip):
    """root の中のファイルの一覧(skip の中は除く)"""
    out = set()
    for d, dirs, files in os.walk(root):
        if os.path.abspath(d).startswith(os.path.abspath(skip)):
            continue
        for f in files:
            out.add(os.path.relpath(os.path.join(d, f), root))
    return out


class Base(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.mkdtemp(prefix="evimp-")
        self.inbox = os.path.join(self.tmp, "inbox")
        os.mkdir(self.inbox)
        self.dest = os.path.join(self.tmp, "dest")

    def tearDown(self):
        shutil.rmtree(self.tmp, ignore_errors=True)

    def zp(self, name="2026-10-02_配信者A_%s.zip" % WID):
        return os.path.join(self.inbox, name)

    def works(self):
        w = os.path.join(self.dest, "works")
        return sorted(os.listdir(w)) if os.path.isdir(w) else []

    def index(self):
        with open(os.path.join(self.dest, "index.jsonl"), encoding="utf-8") as f:
            return [json.loads(x) for x in f if x.strip()]

    def rejected(self):
        d = os.path.join(self.dest, "rejected")
        out = []
        for n in sorted(os.listdir(d)):
            with open(os.path.join(d, n), encoding="utf-8") as f:
                out.append(json.load(f))
        return out


class Good(Base):
    def test_import(self):
        z = write_zip(self.zp())
        res = I.import_zip(z, self.dest)
        self.assertEqual(res["result"], "imported", res)
        self.assertEqual(self.works(), [WID])
        wd = os.path.join(self.dest, "works", WID)
        self.assertEqual(sorted(os.listdir(wd)), sorted(list(ev.FILES) + ["check.json"]))
        with open(os.path.join(wd, "check.json"), encoding="utf-8") as f:
            c = json.load(f)
        self.assertEqual(c["format"], I.CHECK_FORMAT)
        self.assertEqual(c["workId"], WID)
        self.assertEqual(c["zipName"], os.path.basename(z))
        self.assertEqual(len(c["sha256"]), 64)
        self.assertEqual(c["rulesVersion"], ev.RULES_VERSION)
        self.assertEqual(c["formatVersion"], ev.FORMAT_VERSION)
        self.assertEqual(c["streamer"], "配信者A")
        self.assertEqual(c["performers"], ["配信者A"])
        self.assertTrue(c["judge"]["work"]["use"])
        rows = {r["id"]: r for r in c["judge"]["rows"]}
        self.assertTrue(rows["r1"]["use"])
        self.assertFalse(rows["r2"]["use"])            # 記号の形式違い → その行だけ外す
        self.assertTrue(any(x.startswith("記号") for x in rows["r2"]["reasons"]))
        self.assertEqual(rows["r3"]["reasons"], ["未確認"])
        self.assertEqual(c["judge"]["notes"]["confirmedWithoutListening"], 1)
        self.assertEqual(c["rows"], {"total": 3, "usable": 1})
        self.assertTrue(c["train"])
        self.assertEqual(c["trainReasons"], [])
        self.assertFalse(c["replaced"])
        idx = self.index()
        self.assertEqual(len(idx), 1)
        self.assertEqual((idx[0]["workId"], idx[0]["result"], idx[0]["use"], idx[0]["usable"]), (WID, "imported", True, 1))
        # 途中の置き場所は空・routing.json は既定で作られている・元の zip は消さない
        self.assertEqual(os.listdir(os.path.join(self.dest, ".staging")), [])
        with open(os.path.join(self.dest, "routing.json"), encoding="utf-8") as f:
            self.assertEqual(json.load(f), I.DEFAULT_ROUTING)
        self.assertTrue(os.path.isfile(z))

    def test_duplicate_and_force(self):
        z = write_zip(self.zp())
        self.assertEqual(I.import_zip(z, self.dest)["result"], "imported")
        res = I.import_zip(z, self.dest)
        self.assertEqual(res["result"], "duplicate")
        # 入れ替え: 新しい中身(行を1つ足した)が入る
        p = parts()
        p["final.json"]["rows"].append({"id": "r4", "start": 4.0, "end": 5.0, "text": "追加", "speaker": "配信者A", "checked": True, "raw": []})
        os.unlink(z)
        write_zip(z, p)
        res = I.import_zip(z, self.dest, force=True)
        self.assertEqual(res["result"], "imported")
        self.assertTrue(res["replaced"])
        with open(os.path.join(self.dest, "works", WID, "check.json"), encoding="utf-8") as f:
            c = json.load(f)
        self.assertEqual(c["rows"]["total"], 4)
        self.assertTrue(c["replaced"])
        self.assertEqual([x["result"] for x in self.index()], ["imported", "duplicate", "imported"])
        self.assertEqual(os.listdir(os.path.join(self.dest, ".staging")), [])

    def test_force_with_bad_zip_keeps_old(self):
        z = write_zip(self.zp())
        I.import_zip(z, self.dest)
        os.unlink(z)
        write_zip(z, drop=("final.json",))
        res = I.import_zip(z, self.dest, force=True)
        self.assertEqual(res["result"], "rejected")
        self.assertTrue(os.path.isfile(os.path.join(self.dest, "works", WID, "final.json")))   # 前のものはそのまま

    def test_routing_no_train(self):
        z = write_zip(self.zp("2026-10-02_如月れん_%s.zip" % WID), parts(streamer="如月れん"))
        res = I.import_zip(z, self.dest)
        self.assertEqual(res["result"], "imported")
        self.assertFalse(res["train"])
        with open(os.path.join(self.dest, "works", WID, "check.json"), encoding="utf-8") as f:
            c = json.load(f)
        self.assertFalse(c["train"])
        self.assertTrue(any("如月れん" in r for r in c["trainReasons"]))
        self.assertTrue(c["judge"]["work"]["use"])        # 評価には使える

    def test_routing_performer_and_custom(self):
        os.makedirs(self.dest)
        with open(os.path.join(self.dest, "routing.json"), "w", encoding="utf-8") as f:
            json.dump({"noTrain": ["ゲストB"]}, f, ensure_ascii=False)
        z = write_zip(self.zp(), parts(performers=["配信者A", "ゲストB"]))
        res = I.import_zip(z, self.dest)
        self.assertFalse(res["train"])

    def test_tidy_suspect_excludes_work(self):
        raw = [{"start": float(i), "end": i + 1.0, "text": "えー あのー えっと まあ そうですね"} for i in range(5)]
        rows = [{"id": "r%d" % i, "start": float(i), "end": i + 1.0, "text": "そうですね", "speaker": "A", "checked": True, "raw": [i]} for i in range(5)]
        z = write_zip(self.zp(), parts(rows=rows, raw=raw))
        res = I.import_zip(z, self.dest)
        self.assertEqual(res["result"], "imported")
        self.assertFalse(res["use"])
        self.assertFalse(res["train"])
        self.assertEqual(res["usable"], 0)
        with open(os.path.join(self.dest, "works", WID, "check.json"), encoding="utf-8") as f:
            c = json.load(f)
        self.assertFalse(c["judge"]["work"]["use"])
        self.assertTrue(any("フィラー" in r for r in c["judge"]["work"]["reasons"]))


class Evil(Base):
    def assertRejected(self, z, needle):
        before = snapshot(self.tmp, self.dest)
        res = I.import_zip(z, self.dest)
        self.assertEqual(res["result"], "rejected", res)
        self.assertTrue(any(needle in r for r in res["reasons"]), res["reasons"])
        self.assertEqual(self.works(), [])
        self.assertEqual(os.listdir(os.path.join(self.dest, ".staging")), [])
        self.assertEqual(snapshot(self.tmp, self.dest), before)   # 置き場所の外には何も書かない
        recs = self.rejected()
        self.assertEqual(len(recs), 1)
        self.assertEqual(recs[0]["format"], I.REJECT_FORMAT)
        self.assertEqual(len(recs[0]["sha256"]), 64)
        self.assertTrue(recs[0]["problems"])
        self.assertEqual(self.index()[-1]["result"], "rejected")
        return res

    def test_parent_path(self):
        self.assertRejected(write_zip(self.zp(), extra={"../evil.txt": b"x"}), "危ない名前")
        self.assertFalse(os.path.exists(os.path.join(self.tmp, "evil.txt")))

    def test_absolute_path(self):
        self.assertRejected(write_zip(self.zp(), extra={"/etc/evil": b"x"}), "危ない名前")

    def test_extra_file(self):
        self.assertRejected(write_zip(self.zp(), extra={"video.mp4": b"x"}), "想定外のファイル")

    def test_symlink(self):
        p = parts()
        with zipfile.ZipFile(self.zp(), "w") as z:
            z.writestr("audio.flac", b"fLaC")
            for k, v in p.items():
                z.writestr(k, json.dumps(v, ensure_ascii=False))
            info = zipfile.ZipInfo("edits.jsonl")
            info.external_attr = (0o120777 << 16)
            z.writestr(info, "../../secret")
        self.assertRejected(self.zp(), "リンク")

    def test_missing_file(self):
        self.assertRejected(write_zip(self.zp(), drop=("asr_raw.json",)), "asr_raw.json がありません")

    def test_meta_workid_mismatch(self):
        p = parts()
        p["meta.json"]["workId"] = "ffffffffffff"
        self.assertRejected(write_zip(self.zp(), p), "作業ID が zip の名前と違います")

    def test_format_mismatch(self):
        p = parts()
        p["final.json"]["format"] = "something/v9"
        self.assertRejected(write_zip(self.zp(), p), "形式が違います")

    def test_abs_path_in_final(self):
        p = parts()
        p["final.json"]["rows"][0]["text"] = r"C:\Users\bob\Videos\a.mp4 を見て"
        self.assertRejected(write_zip(self.zp(), p), "絶対パスが残っている")

    def test_bad_json_shape(self):
        p = parts()
        p["final.json"]["rows"] = ["not a dict"]
        self.assertRejected(write_zip(self.zp(), p), "rows の形が違います")

    def test_bad_zip_name(self):
        res = self.assertRejected(write_zip(self.zp("evil.zip")), "作業ID が分かりません")
        self.assertIsNone(res["workId"])

    def test_not_a_zip(self):
        with open(self.zp(), "wb") as f:
            f.write(b"not a zip at all")
        self.assertRejected(self.zp(), "zip として読めません")

    def test_rejected_name_collision_keeps_both(self):
        z = write_zip(self.zp(), extra={"x.txt": b"1"})
        I.import_zip(z, self.dest)
        os.unlink(z)
        write_zip(z, extra={"y.txt": b"2"})
        I.import_zip(z, self.dest)
        self.assertEqual(len(self.rejected()), 2)


class DestAndCli(Base):
    def test_dest_inside_repo_refused(self):
        d = os.path.join(REPO, "_eval_intake_should_not_exist")
        with self.assertRaises(I.DestError):
            I.prepare_dest(d)
        self.assertFalse(os.path.exists(d))
        out = io.StringIO()
        _r, code = I.run([self.inbox], d, out=out)
        self.assertEqual(code, 2)
        self.assertFalse(os.path.exists(d))
        self.assertIn("リポジトリの中", out.getvalue())

    def test_dest_inside_git_tree_refused(self):
        os.mkdir(os.path.join(self.tmp, ".git"))
        with self.assertRaises(I.DestError):
            I.prepare_dest(self.dest)
        self.assertFalse(os.path.exists(self.dest))

    def test_bad_routing_stops(self):
        os.makedirs(self.dest)
        with open(os.path.join(self.dest, "routing.json"), "w", encoding="utf-8") as f:
            f.write("{broken")
        write_zip(self.zp())
        _r, code = I.run([self.inbox], self.dest, out=io.StringIO())
        self.assertEqual(code, 2)
        self.assertEqual(self.works(), [])

    def test_folder_with_many_zips_and_exit_codes(self):
        write_zip(self.zp("2026-10-01_A_aaaaaaaaaaaa.zip"), parts("aaaaaaaaaaaa", "A"))
        write_zip(self.zp("2026-10-02_B_bbbbbbbbbbbb.zip"), parts("bbbbbbbbbbbb", "B"))
        with open(os.path.join(self.inbox, "notes.txt"), "w") as f:   # zip 以外は見ない
            f.write("x")
        out = io.StringIO()
        results, code = I.run([self.inbox], self.dest, out=out)
        self.assertEqual(code, 0)
        self.assertEqual(sorted(r["result"] for r in results), ["imported", "imported"])
        self.assertEqual(self.works(), ["aaaaaaaaaaaa", "bbbbbbbbbbbb"])
        self.assertIn("取り込み 2", out.getvalue())
        # もう一度 = 重複だけ → 0
        _r, code = I.run([self.inbox], self.dest, out=io.StringIO())
        self.assertEqual(code, 0)
        # 断るものが混ざる → 1
        write_zip(self.zp("2026-10-03_C_cccccccccccc.zip"), parts("cccccccccccc", "C"), extra={"x.exe": b"MZ"})
        out = io.StringIO()
        _r, code = I.run([self.inbox], self.dest, out=out)
        self.assertEqual(code, 1)
        self.assertIn("[断った]", out.getvalue())

    def test_missing_argument_is_error(self):
        _r, code = I.run([os.path.join(self.inbox, "nope_0123456789ab.zip")], self.dest, out=io.StringIO())
        self.assertEqual(code, 1)

    def test_main(self):
        write_zip(self.zp())
        buf = io.StringIO()
        old = sys.stdout
        sys.stdout = buf
        try:
            code = I.main([self.zp(), "--dest", self.dest])
            code2 = I.main([self.zp(), "--dest", self.dest])
            code3 = I.main([self.zp(), "--dest", self.dest, "--force"])
        finally:
            sys.stdout = old
        self.assertEqual((code, code2, code3), (0, 0, 0))
        self.assertEqual([x["result"] for x in self.index()], ["imported", "duplicate", "imported"])
        self.assertIn("[重複]", buf.getvalue())

    def test_default_dest_outside_repo(self):
        self.assertFalse(I.fsio.is_inside(I.default_dest(), REPO))
        self.assertTrue(I.default_dest().endswith(os.path.join("youtube-tools", "eval-intake")))


if __name__ == "__main__":
    unittest.main()
