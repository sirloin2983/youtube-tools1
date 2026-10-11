# -*- coding: utf-8 -*-
"""② 管理の層 flow: 段が道具を呼ぶ継ぎ目 Tools(役割で組み直す RS6 b-0。2026-10-10。docs/design/rs6-survey-2026-10-10/plan_order_v2.md の b-0)。

Runner(flow/run.py)の段は、ツールの仕事を self.tools.<動詞>(...) で頼む。動詞は今の各ツールの API 1 つずつ(返す形も API の応答のまま)。
  HttpTools(client) … 今の形(既定)。入口の中の 3 ツールの公開している API を client(call・ok)で呼ぶ。呼ぶ API と本文は RS6 b-0 の前と同じ
  LocalTools()      … 入口なしで動かす最小の形(app の CLI が使う)。文字起こし = ② flow/tx の動詞を同じスレッドで(ジョブの表は通さない。
                      重い処理の枠 ytt.jobs.SLOTS は取る)・パック = ① pipeline/pack の plan_cut → build_pack を直に。
                      配信の読み・解析・採用・書き出しは studio(② flow/studiobook の LocalStudio = スタジオなしの台帳。RS8 の「URL も CLI で」)を
                      渡したときだけ、その動詞に任せる(無ければ「入口に頼んでください」の StepError)。話者分離は作っていない(同じ StepError)。
                      文書は作業データ(ytt/workdata の TX_DIR。呼ぶ側が先に決める)に ② の write_machine_doc で書く(書き出し先の案件の動画なら
                      その 作業用 に置いて索引を TX_DIR に = placement.doc_home。RS8 B2-2)。人のカット(edit.json)は読まない
HttpTools の動詞の名前と返す形が「段が道具に頼むこと」の一覧(LocalTools は同じ名前で同じ形を返す)。
"""
import json
import os
import time
import urllib.parse
import uuid
from pathlib import Path

from pipeline.pack import cut2resolve_core as _core, pack as _pack, request as _packreq
from ytt import docloc as _docloc, errors as _errors, fsio as _fsio, jobs as _slots, schemas as _yschemas, tools as _ytools
from ytt import txbase as _txbase, txtext as _txtext, workdata as _workdata

from . import jobs as _jobs, keys as _keys, pack as _flowpack, tx as _tx
from . import machine as _machine, placement as _placement, spec as _spec


class HttpTools:
    """今の形: 各ツールの公開している API を client で呼ぶ(call -> (HTTP の番号, JSON)・ok -> JSON か StepError)"""

    def __init__(self, client):
        self.client = client

    # 切り抜きスタジオ(配信・解析・採用・書き出し)
    def video(self, vid):
        """配信 1 本 -> (HTTP の番号, {"video"})"""
        return self.client.call("studio", "GET", "/api/video?id=" + vid)

    def analyze_add(self, item, settings):
        """解析の順番に入れる -> {"added", "rejected"}"""
        return self.client.ok("studio", "POST", "/api/queue/add", {"items": [item], "settings": settings})

    def analyze_items(self):
        """解析の順番の一覧"""
        return self.client.ok("studio", "GET", "/api/queue").get("items") or []

    def analyze_cancel(self, qid):
        self.client.call("studio", "POST", "/api/queue/cancel", {"qid": qid})

    def request_marks(self, body):
        """採用(F-5。body = {"id", "ranges", "top", "title"?, "channel"?}): 区間を採用済みのマークに・人の採用を数に入れ・上限までの残りを自動の上位で
        -> {"rangeIds", "humanIds", "autoIds", "added", "video"}"""
        return self.client.ok("studio", "POST", "/api/video/request-marks", body)

    def export_start(self, body):
        """書き出しを始める -> (HTTP の番号, 応答)(409 busy は段が待ってやり直す)"""
        return self.client.call("studio", "POST", "/api/export", body)

    def export_job(self, jid):
        return self.client.ok("studio", "GET", "/api/export?id=" + jid)

    def export_cancel(self, jid):
        self.client.call("studio", "POST", "/api/export/cancel", {"id": jid})

    # 編集(文字起こし・話者分離・文書・カット)
    def transcribe_start(self, req, bundle=None):
        """文字起こしのジョブを入れる -> ジョブの id。bundle は使わない(編集が要求の値と自分の設定で決める)"""
        return self.client.ok("transcribe", "POST", "/api/transcribe", req).get("id")

    def jobs(self):
        """編集のジョブの一覧(文字起こし・話者分離)"""
        return self.client.ok("transcribe", "GET", "/api/jobs").get("jobs") or []

    def transcribe_cancel(self, jid):
        self.client.call("transcribe", "POST", "/api/transcribe/cancel", {"id": jid})

    def diarize_start(self, body):
        """話者分離のジョブを入れる -> (HTTP の番号, 応答)"""
        return self.client.call("transcribe", "POST", "/api/diarize", body)

    def edit(self, tid):
        """「編集」のカット -> (HTTP の番号, {"edit", "rev"})"""
        return self.client.call("transcribe", "GET", "/api/edit?id=" + urllib.parse.quote(str(tid)))

    def transcript_file(self, tid):
        """文書の受け渡しの JSON(transcript-v1)を書く -> {"path"}"""
        return self.client.ok("transcribe", "POST", "/api/export-file", {"id": tid, "format": "transcript-v1"})

    def record_pack(self, body):
        """作ったパックを「編集」に残す(カット・字幕を直したら作り直しと知らせるため)。残せなくても上げない"""
        self.client.call("transcribe", "POST", "/api/edit/pack", body)

    def docs(self):
        """文書の一覧(GET /api/transcripts の要約。RS6 b-K2)-> [{"id", "title", "sourceName", "videoId", "updatedAt", "count"}]。
        動画の場所と行は持たない(doc(tid) で読む。素の Runner の _pick_doc が名前で絞ってから読む。入口の AutoRunner は案件の txindex で引く)"""
        items = self.client.ok("transcribe", "GET", "/api/transcripts").get("items") or []
        return [{"id": str(it["id"]), "title": str(it.get("title") or ""), "sourceName": str(it.get("sourceName") or ""),
                 "videoId": str(it.get("videoId") or ""), "updatedAt": it.get("updatedAt") or 0, "count": it.get("segments") or 0}
                for it in items if isinstance(it, dict) and it.get("id")]

    def doc(self, tid):
        """文書 1 つ(GET /api/transcript)-> 一覧の 1 行の形(doc_row。動画の場所・行・clip を持つ)か None(無い・読めない)"""
        st, obj = self.client.call("transcribe", "GET", "/api/transcript?id=" + urllib.parse.quote(str(tid)))
        return doc_row(str(tid), obj) if st == 200 and isinstance(obj, dict) else None

    # パック(cut2resolve)
    def pack_start(self, body):
        """パックを作り始める -> (HTTP の番号, {"job"})(409 exists = 同じ名前のパックがある・409 busy は段が待ってやり直す)"""
        return self.client.call("cut2resolve", "POST", "/api/build", body)

    def pack_job(self, jid):
        return self.client.ok("cut2resolve", "GET", "/api/job?id=" + jid)

    def pack_cancel(self, jid):
        self.client.call("cut2resolve", "POST", "/api/job/cancel", {"id": jid})


def _step_error(msg):
    """段の失敗 StepError(画面・結果に出す)。run.py は読み込みの時でなく呼ぶ時に読む(run が tools を読むため)"""
    from .run import StepError
    return StepError(msg)


def _refuse(what):
    """LocalTools に無い段 -> StepError"""
    return _step_error("%sは、入口(ホームのまとめて実行)に頼んでください(入口なしの実行で使えるのは文字起こし・パックと、"
                       "コマンドに URL を渡したときの配信の段だけです)" % what)


def _public(job):
    """ジョブの表に見せる形(本体の指定 spec と子プロセス proc は出さない)"""
    return {k: v for k, v in job.items() if k not in ("spec", "proc")}


def doc_row(tid, d):
    """文書(transcripts/<id>.json の中身)-> 段が読む一覧の 1 行(manage/cases/txindex の形にそろえる):
    {"id", "title", "sourcePath", "sourceName", "videoId", "clip", "updatedAt", "count", "segments": [{start, end, text, cut}]}"""
    segs = [{"start": g.get("start"), "end": g.get("end"), "text": str(g.get("text") or ""), "cut": g.get("cutState") == "cut"}
            for g in d.get("segments") or [] if isinstance(g, dict)]
    clip = d.get("clip") if isinstance(d.get("clip"), dict) else None
    src = (clip or {}).get("source") if isinstance((clip or {}).get("source"), dict) else {}
    path = d.get("sourcePath") if isinstance(d.get("sourcePath"), str) else ""
    return {"id": tid, "title": str(d.get("title") or tid), "sourcePath": path, "sourceName": str(d.get("sourceName") or os.path.basename(path)),
            "videoId": str(src.get("videoId") or ""), "clip": clip, "updatedAt": d.get("updatedAt") or 0, "count": len(segs), "segments": segs}


class LocalTools:
    """入口なしで動かす最小の形(HttpTools と同じ動詞・同じ返す形)。仕事はその場で終わらせ、ジョブの id を返す(段は終わった状態を読む)"""

    def __init__(self, learning=None, studio=None):
        """learning = 学習データを読む人(無ければ置換辞書と名簿の表だけ = 今まで)。呼ぶ側(app の CLI)が ③ の学習から作って渡す
        (② は ③ を読まない)。持つ口は 2 つ: glossary(ユーザーの用語) -> 自動で足す用語・learned() -> 確度「高」の学習済み置換の選び方か None。
        置き場所(machine の learningDir)は渡す側が決める(束には入れない = 決定 3-30)。
        studio = 配信の段の動詞(flow/studiobook.LocalStudio。URL の実行で app の CLI が作って渡す。None = 配信の段は断る)"""
        self.learning = learning
        self.studio = studio
        self._jobs = {}    # 文字起こしのジョブの id -> ジョブ
        self._packs = {}   # パックの仕事の id -> {"id", "state", "result" / "error"}

    # 配信の段(studio があればスタジオなしの台帳に任せる・無ければ入口に頼む)
    def _studio(self, what):
        if self.studio is None:
            raise _refuse(what)
        return self.studio

    def video(self, vid):
        return self._studio("配信の読み").video(vid)

    def studio_video(self, vid):
        """台帳の配信 1 本(全部の形)か {}(台帳が無い・無い・読めない)。結果の束が切り抜きを引く手がかり(Runner の _studio_video)"""
        if self.studio is None:
            return {}
        st, obj = self.studio.video(vid)
        return (obj.get("video") or {}) if st == 200 else {}

    def analyze_add(self, item, settings):
        return self._studio("解析").analyze_add(item, settings)

    def analyze_items(self):
        return self._studio("解析").analyze_items()

    def analyze_cancel(self, qid):
        """取り消す(台帳が無ければ取り消す解析は無い = analyze_add が断る)"""
        if self.studio is not None:
            self.studio.analyze_cancel(qid)

    def request_marks(self, body):
        return self._studio("採用").request_marks(body)

    def export_start(self, body):
        return self._studio("書き出し").export_start(body)

    def export_job(self, jid):
        return self._studio("書き出し").export_job(jid)

    def export_cancel(self, jid):
        """取り消す(台帳が無ければ取り消す書き出しは無い = export_start が断る)"""
        if self.studio is not None:
            self.studio.export_cancel(jid)

    def diarize_start(self, body):
        raise _refuse("話者分離")

    # 文字起こし
    def transcribe_start(self, req, bundle=None):
        """動画 1 本を文字起こしして文書を書く(同じスレッドで終わらせる)-> ジョブの id。req = 束の tx_opts + sourcePath(+ 段が決めた engine・model)。
        bundle = 後処理の値(行を分ける文字数・後処理の 3 つ・文脈)。② が足すこと = ジョブの状態・枠 SLOTS・一時の wav・文書と記録を書く・
        この PC の設定(flow/machine.py。決めた値だけ)を束に重ねて LLM の後処理のモデルを指定に入れる(RS7-1 S1。重ねても同じ束なら何も変わらない)"""
        b = _machine.overlay(bundle if bundle is not None else _spec.merge(None))
        jid = uuid.uuid4().hex[:12]
        job = {"id": jid, "kind": "transcribe", "state": "queued", "phase": "待機中", "progress": 0.0, "cancel": False, "segments": 0,
               "error": "", "tid": None, "createdAt": int(time.time() * 1000)}
        self._jobs[jid] = job
        if not (_workdata.TX_DIR and _workdata.ROOT):
            job.update(state="error", phase="失敗", error="作業データの置き場所が決まっていません(呼ぶ側が ytt.workdata の set_root・set_data_dir で決めてください)")
            return jid
        with _jobs.job_errors(job):
            job["spec"] = spec = self._tx_spec(req, b, self.learning)
            if b["post"].get("llmModel", _spec.DEFAULTS["post"]["llmModel"]) != _spec.DEFAULTS["post"]["llmModel"]:   # 既定のモデルなら入れない(指定は今と同じ)
                spec["llmModel"] = b["post"]["llmModel"]
            job["title"] = spec["title"]
            with _slots.SLOTS.slot("flow", spec["title"], cancelled=lambda: job["cancel"], on_wait=lambda: job.update(phase=_slots.WAIT_MESSAGE)) as ok:
                if not ok:
                    _jobs.set_cancelled(job)
                    return jid
                self._transcribe(job, spec)
        return jid

    @staticmethod
    def _tx_spec(req, b, learning=None):
        """要求と束 -> 文字起こしのジョブの指定(「編集」の受付 validate_job と同じ形。評価用・入れる文書・2 つ目のエンジン・YouTube の字幕・
        話者の自動の判別・疑わしい所の認識し直しは ③ の物なので使わない。学習した用語・置換は learning があるときだけ = 入口の経路と同じ優先:
        ユーザーの用語が先・自動の用語はその後ろ。RS7-1 F-k)"""
        src = _ytools.check_source(req.get("sourcePath"))
        dur = _ytools.media_duration(src)
        clip, clip_warn, _clip_path = _yschemas.find_clip(src, dur)
        title = os.path.splitext(os.path.basename(src))[0][:120]
        model = _tx.check_model(str(req.get("model") or "large-v3").strip())
        lang = req.get("language") if req.get("language") in _txbase.LANGS else "ja"
        post = b["post"]
        glossary = _txtext.split_terms(req.get("glossary"))[:200]
        gauto = list(learning.glossary(glossary)) if learning is not None and post.get("autoGloss") is not False else []
        engine, ctx = _tx.request_engine(req, model, {"clip": clip, "title": title, "sourceName": os.path.basename(src), "sourcePath": src},
                                         post["autoContext"])
        return {"sourcePath": src, "sourceName": os.path.basename(src), "start": 0.0, "end": round(dur, 2) if dur else None, "intoDoc": None,
                "duration": dur, "whole": True, "model": model, "engine": engine, "language": lang, "beam": 1 if req.get("quality") == "fast" else 5,
                "device": req.get("device") if req.get("device") in ("auto", "cuda", "cpu", "vulkan") else "auto",
                "vadMode": req.get("vadMode") if req.get("vadMode") in ("weak", "normal", "off") else "weak",
                "boost": req.get("boost") is True, "autoDict": req.get("autoDict") is not False, "wordSplit": req.get("wordSplit") is not False,
                "splitChars": post["splitChars"], "autoRedo": post["autoRedo"], "autoAlt": False, "autoYtcap": False,
                "autoFill": post["autoFill"], "autoLlm": post["autoLlm"], "stripNames": post["stripNames"], "autoDiarize": False,
                "stripPunct": req.get("stripPunct") is not False, "glossary": glossary + gauto, "glossAuto": gauto,
                "learningVersion": b["post"]["learning"]["version"], "context": ctx, "evalSet": False, "autoLearned": post["autoLearned"], "clip": clip, "warnings": [clip_warn] if clip_warn else [], "title": title}

    def _transcribe(self, job, spec):
        """認識 → 文書の機械の分と記録を書く → 一覧に足す(job_temp_wav が失敗・取り消しをジョブの状態にする)"""
        with _jobs.job_temp_wav(job) as wav:
            learned = self.learning.learned() if self.learning is not None and spec.get("autoLearned") else None
            clip = _tx.transcribe_clip(job, spec, wav, _tx.dict_pairs(spec), learned)
            tid = uuid.uuid4().hex[:12]
            # 書き出し先の案件の動画なら、その 作業用 に置く(評価用・案件でなければ今までどおり transcripts。RS8 B2-2)
            _tx.write_machine_doc(tid, clip["fields"], spec, _placement.doc_home(spec["sourcePath"], eval_set=spec.get("evalSet") is True))
            _tx.write_clip_records(tid, clip, spec)
            _jobs.job_done(job, tid)

    def jobs(self):
        return [_public(j) for j in self._jobs.values()]

    def transcribe_cancel(self, jid):
        """その場で終わらせるので、取り消しは印だけ(動いている間には届かない)"""
        if jid in self._jobs:
            self._jobs[jid]["cancel"] = True

    def docs(self):
        """作業データ(ytt/workdata の TX_DIR)の文書を直に読んだ一覧(doc_row の形。RS6 b-K2。置き場所が決まっていなければ [])"""
        out = []
        for tid in _docloc.iter_tids():
            row = self.doc(tid)
            if row:
                out.append(row)
        return out

    def doc(self, tid):
        """文書 1 つ(doc_row の形)か None(無い・読めない)"""
        try:
            d = _read_doc(_docloc.doc_file(str(tid), ".json"))
        except (_errors.ApiError, TypeError, ValueError):
            return None
        return doc_row(str(tid), d) if d.get("segments") is not None else None

    def edit(self, tid):
        """人のカット(③ の edit.json)は読まない = カットなし"""
        return 404, {}

    def transcript_file(self, tid):
        """文書の受け渡しの JSON(transcript-v1。② flow/pack.handoff_files)を作業データの一時フォルダに書く -> {"path"}"""
        doc = _read_doc(_docloc.doc_file(tid, ".json"))
        obj, count = _flowpack.handoff_files(doc, "transcript-v1")
        if not count:
            raise _step_error("パックに渡す文字のある行がありません")
        path = os.path.join(_workdata.TMP_DIR, tid + ".transcript.json")
        _fsio.write_json(path, obj, indent=1)
        return {"path": path}

    def record_pack(self, body):
        """カットのとおりのパックの記録(③)は残さない(人のカットを読まないので呼ばれない)"""

    # パック
    def pack_start(self, body):
        """パックをその場で作る -> (200, {"job"}) / (409, exists) / (400, 理由)。body は cut2resolve の POST /api/build と同じ形(段が作る 4 つの形:
        カットのとおり keeps・行から preset・カットしない list・無音で削る silence)。② が足すこと = 本文 → ① の Request と引数・枠 SLOTS・上書きの確かめ"""
        sp, o = body.get("spec") or {}, body.get("output") or {}
        try:
            req = _packreq.request_from_spec(sp)
            out = _packreq.output_from_spec(o, req.video)
        except _errors.ApiError as e:   # cut2resolve の API と同じ検査(pipeline/pack/request.py)。理由と番号もそのまま
            return e.status, {"error": e.code, "message": e.message}
        except (_core.ToolError, ValueError, TypeError, KeyError) as e:
            return 400, {"error": "bad_value", "message": str(e)}
        out_dir = out["dir"]
        if not out["force"]:
            names = _pack.expected_paths(req, out_dir, bool(req.sub or req.transcript), render=out["render"], copy_video=out["copyVideo"],
                                         textplus=out["textplus"], backup=out["backup"], plan_file=False, readme_file=False)
            existing = [p.name for p in names.values() if p.exists()]
            if existing:
                return 409, {"error": "exists", "message": "出力ファイルが既にあります", "files": existing}
        jid = uuid.uuid4().hex[:12]
        job = self._packs[jid] = {"id": jid, "state": "running", "message": ""}
        with _slots.SLOTS.slot("flow", "パック: " + req.video.name) as ok:
            if not ok:
                job.update(state="cancelled")
                return 200, {"job": dict(job)}
            try:
                job.update(state="done", result=_build(req, out_dir, out))
                _keys.write_pack(job["result"]["outDir"], sp, o)   # <パック>/pack.key.json(cut2resolve の API と同じ。書けなくてもログだけ。RS6 b-K2)
            except (_core.ToolError, ValueError, OSError) as e:
                job.update(state="error", error={"message": str(e)})
        return 200, {"job": dict(job)}

    def pack_job(self, jid):
        j = self._packs.get(jid)
        return dict(j) if j else {"id": jid, "state": "error", "error": {"message": "パックの仕事が見つかりません"}}

    def pack_cancel(self, jid):
        """その場で終わらせるので取り消す物は無い"""


def _read_doc(path):
    try:
        with open(path, encoding="utf-8-sig") as f:
            doc = json.load(f)
    except (OSError, ValueError) as e:
        raise _errors.ApiError("not_found", "文書を読めません: %s" % e, 404)
    return doc if isinstance(doc, dict) else {}


def _build(req, out_dir, out):
    """① plan_cut → build_pack -> 段が読む結果 {"outDir", "files", "warnings"}"""
    plan = _pack.plan_cut(req)
    spk_map, _shown = _packreq.speaker_colors_for(plan, out)
    res = _pack.build_pack(plan, out_dir, render=out["render"], copy_video=out["copyVideo"], textplus=out["textplus"], textplus_target=out["textplusTarget"],
                           force=out["force"], backup=out["backup"], plan_file=False, readme_file=False, textplus_wrap=out["textplusWrap"],
                           textplus_color=out["textplusColor"], speaker_colors=spk_map or None,
                           loudness=out["loudness"], volume=out["volume"], video_tracks=out["videoTracks"])
    return {"outDir": str(res["out_dir"]), "files": [{"kind": k, "name": Path(p).name, "path": str(p)} for k, p in res["files"]],
            "warnings": res["warnings"]}
