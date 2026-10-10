"""① 自動の流れの経路(役割で組み直す RS1-7。計画 plan/role-restructure.md の 5-1)。

入力(配信の ID・文書の ID・動画ファイル)を、段(解析 → 採用 → 書き出し → 文字起こし → 話者分離 → パック)の順に、各ツールの公開している API を
client(call・ok)で呼んで進める。Run = 1 回の実行の状態(段・進み具合・待ちの記録の形)、Runner = 段の中身と待つ骨組み、run() = 入口の関数。
どの段も「まだ無いものだけ」作る(済んだ段は飛ばす)。中止は Cancelled、続けられない失敗は StepError。

import してよいのは標準ライブラリ・ytt・同じ flow の spec だけ(層の決まり。dev/tests/test_layering.py)。案件・ホームの設定・届けることを知る所は
Runner の hook(_await_tools・_checkpoint・_studio_video・_friend_length・_docs・_pick_doc・_pref・_live_auto_origin・_auto_streamer・
_after_pack・_remember_styles・_remember_doc_streamer)にして、既定は「何も知らない」安全な値にした。

src/home/autorun.py に残したもの(AutoRunner が Runner を継いで hook を埋める): 順番待ちと実行の糸(_loop)・受付(start*)・中止・状態と記録
(snapshot・history・autorun-runs.jsonl)・起動し直しで戻す(autorun-active.json)・見積もり・restart_info・Dropbox へ届けることと組の溜め・
HTTP の ToolClient。案件(cases・txindex)・ホームの設定(prefs)・届ける部品(deliver)を読むので、層の向きの上で ① に置けないため(RS3 で分ける)。
autorun は移した名前を同じ名前で読み直している(テストと live.py が autorun.StepError などを使う。例外は同じ物)。

将来 batch や live の流れを移すときは flow/run/ パッケージにせず兄弟モジュールにする(__init__ は import しない決まり)。

RS6 b-0(2026-10-10): 段は指定の束(Run.spec。run() が merge・validate して置く)を読む。各ツールの GET /api/settings は読まない
(入口の AutoRunner.build_spec が画面の設定から束を組む = ① は設定ファイルを読まない。束 → 本文は flow/spec.py の export_body・tx_opts・pack_output)。
Run の欄(top・ranges・weights・cut・engine・model・video_tracks・speakers など友人や画面の指定)は今のまま、束に重ねて使う(欄があれば欄が勝つ)。
束に入れない画面の値(精密・画質の上限・fps・用語集)は Run.screen(flow/spec.py の SCREEN)。
ツールの仕事は self.tools(flow/tools.py の HttpTools(client) = 今の API の形・LocalTools = 入口なし)に頼む。

RS6 b-A(2026-10-10): 採用は 1 つの段 _step_adopt(規則 F-5 はスタジオの store.adopt_marks の 1 か所 = 区間 ∪ 人の採用 ∪ 自動の上位で上限まで)。
RS6 b-K2(2026-10-10): 文字起こし・パックは成果物の鍵(flow/keys)を読んで飛ばす。文字起こし = 同じ・鍵なしは飛ばす / 違えば飛ばして印 TX_DIFFER /
force(Run.force か束の run.force)なら作り直す。パック = 違えば作り直す / 同じは飛ばす / 鍵なしは今のまま。
素の Runner の文書の一覧(_docs・_pick_doc の既定)は tools の docs・doc(HttpTools = GET /api/transcripts・LocalTools = 作業データを直に)。
"""
import os
import re
import sys
import time
import uuid

from ytt import colors
from . import keys as _keys, placement as _placement, spec as _spec, tools as _tools
from .spec import (CUTS, LIVE_AUTO_CUT, MAX_MARKS, TX_ENGINES, TX_MODEL_RE, WEIGHT_KEYS, clean_ranges, clean_weights,
                   pad_range)


MODES ={"full": "解析から全部", "adopted": "採用後を全部", "transcribe": "文字起こしまで"}
STEP_LABELS = {"analyze": "解析", "adopt": "採用(自動)", "export": "書き出し", "transcribe": "文字起こし", "pack": "パック",
               "deliver": "Dropbox へ届ける", "diarize": "話者分離"}
MODE_STEPS = {"full": ("analyze", "adopt", "export", "transcribe", "pack"), "adopted": ("export", "transcribe", "pack"),
              "transcribe": ("export", "transcribe"), "doc": ("transcribe", "pack"),
              "request": ("analyze", "adopt", "export", "transcribe"), "file": ("transcribe",),
              "request_auto": ("analyze", "adopt", "export", "transcribe", "pack", "deliver"),
              "file_auto": ("transcribe", "pack", "deliver")}
# 友人からの依頼(src/human/friend/intake.py。docs/spec/friend-intake.md)の形。ホームの画面の「まとめて実行」の選択肢には出さない(MODES に入れない)。
# 友人が送るときに選ぶ(2026-10-01 ユーザー決定): ① 全自動 auto = パックまで作って Dropbox の 出力\ へ / ② 軽く確認 check = 文字起こしまで /
# (③ 全部人が行う manual = 解析まで は RS5-F で無くした。② check は自分の配信の書き出しのあと(L2)と手で置いた動画・URL が使う)。request* = 配信の URL(解析 → 上位 N 個を採用 → 書き出し → …)/ file* = 友人が切り抜いた動画
REQUEST_MODES = {"request_auto": "依頼 ① 全自動: 解析 → パック", "request": "依頼 ② 軽く確認: 解析 → 文字起こし",
                 "file_auto": "依頼 ① 全自動: 文字起こし → パック", "file": "依頼 ② 軽く確認: 文字起こし"}
# 友人が時刻で指定した区間(送るアプリ 2.0.0。docs/spec/friend-intake.md の 2-6): 前後に余白を足してスタジオの手動マーク(採用)にする。
# 区間が切り抜く数(top)に足りない分だけ、自動マークの上位で埋める(スタジオの /api/video/request-marks)
REQUEST_URL_MODES = ("request", "request_auto")
# 文書単位の実行(docs/design/edit-tool-design.md の 12 ⑦(b)): 「編集」の履歴で選んだ文書を、行が無ければ文字起こし → パック。
# カットがある文書はカットのとおり(ユーザー決定 2026-09-27。配信単位の実行と同じ)。パックがあるときは既定で飛ばす(overwrite で上書き)
# 状態の言葉(気が利く画面へ 段4。どの入口の画面もこの言葉で出す = snapshot の labels)
STEP_STATE_LABELS = {"wait": "待ち", "run": "実行中", "done": "済み", "skip": "飛ばした", "warn": "一部失敗", "error": "失敗"}
RUN_STATE_LABELS = {"queued": "待ち", "running": "実行中", "done": "済み", "error": "失敗", "cancelled": "中止", "nothing": "やることがありませんでした"}
NOTHING_MESSAGE = "やることがありませんでした"
TX_DIFFER = "設定が違う(force で作り直し)"   # 文字起こし済みの文書の鍵が今の設定と違うときの印(飛ばす。RS6 b-K2・決定 3-29 Q4)
PACK_DIFFER = "字幕か設定が変わったので作り直しました"   # パックの鍵が今と違うときの知らせ(作り直す。同上)
DOC_MODE = "doc"
DOC_LABEL = "文字起こし → パック"
BUSY_WAIT = 5.0        # スタジオの書き出しが別の書き出しで塞がっているときの待ち間隔
# あとから解析(mode post_analyze。測るため)は RS4 で消した(代わりは src/eval/tools/eval_marks.py --analyze-missing)。
# 以前の待ちの記録に mode post_analyze が残っていても、MODE_STEPS に無いので restore が読み飛ばす
CANCEL_WAIT = 30.0                   # 取り消したスタジオの解析が止まるのを待つ秒(次の実行が同じ配信の解析を始められるように)
DONE_STEPS = ("done", "skip", "warn")   # 済んだ段(戻した実行では飛ばす)
RUN_ID_RE = re.compile(r"^[0-9a-f]{10}\Z")

FROM_MODE = {None: "full", "analyze": "full", "export": "adopted", "transcribe": DOC_MODE}   # run(from_=段) の配信の ID の入力 -> 実行の形

_num = _spec.num_ok   # 扱ってよい大きさの数か(src/flow/spec.py)


def _media_is_30fps(path):
    """素材がちょうど 30fps か(ytt.normalize の probe。ffprobe が無い・読めないときは False = 設定の値を使う)。2026-10-04 Q1"""
    try:
        from ytt import normalize
        info = normalize.probe(path)
    except Exception:
        return False
    fps = (info or {}).get("fps")
    return isinstance(fps, (int, float)) and abs(fps - 30) <= 0.01


def _has_captions(doc):
    """文書に残す字幕の行(文字があってカットしていない行)があるか"""
    return any(s.get("text", "").strip() and not s.get("cut") for s in doc.get("segments") or [])


class Cancelled(Exception):
    """中止(人の中止・入口の終了)"""


class StepError(Exception):
    """段を続けられない失敗(文は画面に出す)"""


JOB_STATE_JA = {"error": "失敗しました", "cancelled": "取り消されました", "skipped": "飛ばされました"}   # ツールの状態名(英語)を画面の言葉に


def _job_why(j):
    """ツールの仕事(文字起こし・パック)が終わらなかった理由の文。ツールの文があればそれ、無ければ状態名を日本語に(cancelled などを出さない)"""
    return str(j.get("error") or JOB_STATE_JA.get(j.get("state"), "理由は不明です"))


def clean_pool(p):
    """組の溜めの指定 {key, rid, title, meta: {recorder, recording, phase}} を検査した形か None(live_export._handoff が作る)"""
    if not isinstance(p, dict) or not isinstance(p.get("key"), str) or not 0 < len(p["key"]) <= 200:
        return None
    meta = p.get("meta") if isinstance(p.get("meta"), dict) else {}
    return {"key": p["key"], "rid": str(p.get("rid") or "")[:120], "title": str(p.get("title") or "")[:120],
            "meta": {k: str(meta[k])[:120] for k in ("recorder", "recording", "phase") if isinstance(meta.get(k), str)}}


class Run:
    """1 回の実行(配信・文書・動画ファイル 1 つぶん)の状態。段の並びは MODE_STEPS[mode]"""

    def __init__(self, video_id, title, mode, top, doc_id=None, overwrite=False, streamer=None, marks=None, fresh=None, on_fail="next",
                 source_path=None, request_id=None, deliver_dir=None, speakers=None, video_tracks=None, ranges=None, cut=None, weights=None, duration=None,
                 engine=None, model=None, deliver_batch=None, pool=None, force=False):
        self.id = uuid.uuid4().hex[:10]
        self.force = force is True   # 鍵が同じ・違っても作り直す(文字起こし = 新しい文書・パック = 上書き。束の run.force と同じ。RS6 b-K2)
        self.pool = clean_pool(pool)   # ライブの切り抜きの組の溜め {"key", "rid", "title", "meta": {recorder, recording, phase}}(None = この実行の中で届ける)
        self.engine = engine if engine in TX_ENGINES else None   # 文字起こしのエンジン(None = 編集の設定のまま。リアルタイム切り抜きの live.auto。M2)
        self.model = model if isinstance(model, str) and TX_MODEL_RE.match(model) else None   # 同じくモデル(None = 編集の設定のまま)
        self.deliver_batch = deliver_batch if isinstance(deliver_batch, int) and not isinstance(deliver_batch, bool) and 1 <= deliver_batch <= 10 else None   # 友人の依頼ごとの届け方(1 = 1 本ずつ・n = n 本の組。None = ホームの設定 intake.deliverBatch。2-16)
        self.ranges = list(ranges or [])   # 友人が時刻で指定した区間 [(開始, 終了)](余白の前。URL の依頼 ①②。足りない分は自動で埋める)
        self.cut = cut if cut in CUTS else None   # 友人が選んだカットの方法(① のパック。None = ホームの設定)
        self.weights = weights             # 友人が指定した解析の重み(None = スタジオの設定のまま)
        self.friend_length = None          # 解析に使った「友人の区間の実績からの長さ」{"length", "preRatio"?, "file", "samples", "videos"}(使ったときだけ)
        self.duration = duration           # 受付のときに調べた配信の長さ(秒。スタジオにまだ無い配信の区間を端で切るのに使う)
        self.video_tracks = video_tracks   # 友人が選んだ Resolve の映像トラックの数(2〜5。① 全自動のパック。None = 編集の既定 = 1。2026-10-02)
        self.speakers = speakers         # 友人が入れた「配信者」{"count", "names", "styles"?: {名前: {"color": "#RRGGBB"}}}。あれば文字起こしのあとに話者分離(2026-10-01)。styles = 字幕の色(文書に覚え、パックにも渡す)
        self.new_docs = []               # この実行で文字起こしした文書(話者分離はこれだけ。前からある文書の話者は人が直したかもしれない)
        self.deliver_dir = deliver_dir   # ① 全自動: パックを zip にして置く所(Dropbox の 出力\)。失敗したら理由の .txt も
        self.packs = []                  # この実行で作ったパックのフォルダ
        self.delivered = []              # 届けたパックのフォルダ(同じものを2回置かない)
        self.pack_marks = {}             # パックのフォルダ -> {"path": 切り抜きの動画, "markId": スタジオのマーク}。友人の「要らない」で片付ける相手(2026-10-08)
        self.pack_hint = None            # _step_pack が _pack_one の直前に置く {"path", "markId"}(_pack_one が pack_marks へ移す)
        self.source_path = source_path   # 依頼の動画(mode file。作業データへコピーしたもの)
        self.request_id = request_id     # 友人からの依頼の id(src/human/friend/intake.py)
        self.video_id, self.title, self.mode, self.top = video_id, title, mode, top
        self.doc_id, self.overwrite = doc_id, bool(overwrite)   # overwrite = パックがあれば作り直す(文書単位も配信単位も。段4 S-12)
        self.on_fail = on_fail if on_fail in ("next", "stop") else "next"   # 切り抜きの1本が失敗したとき: next = 残りを続ける / stop = そこで止める
        self.nothing = False       # どの段もやることが無かった(「完了」と言わない。段4 S-4)
        self.docs = []             # この実行で文字起こし・パックした文書の id(終わったら「校正を始める」で開く。段4)
        self.streamer_from = None  # 配信者を自動で決めたときの出どころ(doc / video / channel = 覚えた名前・auto = チャンネル名から。段5)
        self.streamer = streamer   # 字幕の文字の色にする配信者(照らし合わせ済みの名前。手で入れたときだけ。git の履歴(679ff01 以前)の docs/archive/followup-2026-09-27.md の 4)
        self.marks = marks         # このマークだけ(スタジオのマークの行の「この後を」。None = 配信の全部。git の履歴(679ff01 以前)の docs/archive/followup-2026-09-27.md の 3)
        self.fresh = fresh         # ① 探す から: {"title", "channel"}(まだスタジオに無いかもしれない配信。解析のキューに入れるときに渡す)
        self.state = "queued"
        self.message = "順番待ち"
        self.error = ""
        self.created = time.time()
        self.finished = None
        self.cancel = False
        self.logged = False        # 記録のファイルに書いた(1つの実行は1回だけ書く。B-6)
        self.resumed = False       # 入口を起動し直して戻した実行(M5。始める前にツールの準備を待つ)
        self.spec = None           # 指定の束(run() が merge・validate して置く。段が読む = RS6 b-0。待ちの記録・public には出さない)
        self.screen = None         # 束に入れない画面の値(flow/spec.py の SCREEN。入口の AutoRunner が置く。None = 固定の値。残さない)
        self.owned = None          # 今ツールで動かしている仕事 (ツールの ID, [ジョブ・キューの id])(「起動し直す」の確かめ = restart_info。残さない)
        self.result_path = None    # 結果の束 <案件>/作業用/runs/<id>.json(終わったら flow/placement.write_result が置く。記録の 1 行の resultPath = 索引。RS6 b-B0)
        keys = list(MODE_STEPS[mode])
        if mode in REQUEST_URL_MODES and self.ranges and len(self.ranges) >= (top or 0):
            keys.remove("analyze")   # 区間が切り抜く数に足りている: 解析なしで、その区間だけを取りに行く
        if speakers and "transcribe" in keys:
            keys.insert(keys.index("transcribe") + 1, "diarize")
        self.steps = [{"key": k, "label": STEP_LABELS[k], "state": "wait", "detail": ""} for k in keys]

    def saved(self):
        """待ちの記録(autorun-active.json)に残す形(M5)。restore で同じ実行に戻せるだけの値"""
        return {"id": self.id, "videoId": self.video_id, "title": self.title, "mode": self.mode, "top": self.top, "docId": self.doc_id,
                "overwrite": self.overwrite, "streamer": self.streamer, "streamerFrom": self.streamer_from, "marks": list(self.marks) if self.marks else None,
                "fresh": self.fresh, "onFail": self.on_fail, "sourcePath": self.source_path, "requestId": self.request_id, "deliverDir": self.deliver_dir,
                "speakers": self.speakers, "videoTracks": self.video_tracks, "ranges": [list(r) for r in self.ranges], "cut": self.cut, "weights": self.weights,
                "duration": self.duration, "engine": self.engine, "model": self.model, "friendLength": self.friend_length, "deliverBatch": self.deliver_batch,
                "pool": self.pool, "docs": list(self.docs), "newDocs": list(self.new_docs), "packs": list(self.packs), "delivered": list(self.delivered),
                "packMarks": dict(self.pack_marks), "force": self.force,
                "created": self.created, "state": self.state, "message": self.message,
                "steps": [{"key": s["key"], "state": s["state"], "detail": s["detail"]} for s in self.steps]}

    @classmethod
    def restore(cls, d):
        """saved() の形 -> 「待ち」の Run(同じ id。済んだ段はそのまま・途中の段は待ちに)。形が違えば None(手で直した・壊れた記録は読み飛ばす)"""
        if not isinstance(d, dict) or not RUN_ID_RE.match(str(d.get("id") or "")) or d.get("mode") not in MODE_STEPS:
            return None

        def s(k, n=1000):
            v = d.get(k)
            return v if isinstance(v, str) and 0 < len(v) <= n else None

        def strs(k, n=200):
            v = d.get(k)
            return [x for x in v if isinstance(x, str) and 0 < len(x) <= 1000][:n] if isinstance(v, list) else []
        top = d.get("top")
        vt = d.get("videoTracks")
        try:
            run = cls(s("videoId", 64), str(d.get("title") or "")[:120], d["mode"], top if isinstance(top, int) and not isinstance(top, bool) else None,
                      doc_id=s("docId", 40), overwrite=d.get("overwrite") is True, streamer=s("streamer", 120) if d.get("streamer") != "" else "",
                      marks=tuple(strs("marks", MAX_MARKS)) or None, fresh=d.get("fresh") if isinstance(d.get("fresh"), dict) else None,
                      on_fail=d.get("onFail"), source_path=s("sourcePath"), request_id=s("requestId", 120), deliver_dir=s("deliverDir"),
                      speakers=d.get("speakers") if isinstance(d.get("speakers"), dict) else None,
                      video_tracks=vt if isinstance(vt, int) and not isinstance(vt, bool) else None, ranges=clean_ranges(d.get("ranges")),
                      cut=d.get("cut"), weights=clean_weights(d.get("weights")), duration=d.get("duration") if _num(d.get("duration")) else None,
                      engine=d.get("engine"), model=d.get("model"), deliver_batch=d.get("deliverBatch"), pool=d.get("pool"), force=d.get("force") is True)
        except (TypeError, ValueError, KeyError):
            return None
        run.id = d["id"]
        if _num(d.get("created")) or (isinstance(d.get("created"), (int, float)) and not isinstance(d.get("created"), bool)):
            run.created = float(d["created"])
        run.streamer_from = s("streamerFrom", 20)
        run.friend_length = d.get("friendLength") if isinstance(d.get("friendLength"), dict) else None
        run.docs, run.new_docs = strs("docs"), strs("newDocs")
        run.packs, run.delivered = strs("packs"), strs("delivered")
        pm = d.get("packMarks") if isinstance(d.get("packMarks"), dict) else {}
        run.pack_marks = {str(k): {"path": str(v.get("path") or ""), "markId": str(v.get("markId") or "")} for k, v in pm.items() if isinstance(v, dict)}
        old = {x.get("key"): x for x in d.get("steps") or [] if isinstance(x, dict)}
        for st in run.steps:
            o = old.get(st["key"]) or {}
            if o.get("state") in DONE_STEPS:   # 済んだ段はそのまま(続きから)。途中だった段(run)・待ちは頭から
                st["state"], st["detail"] = o["state"], str(o.get("detail") or "")[:500]
        run.resumed = True
        run.message = "ホームを起動し直したので、続きから進めます"
        return run

    @classmethod
    def from_input(cls, input, from_=None):
        """run() の入力 -> 待ちの Run。{"videoId", "title"?, "top"?}(from_ で形を選ぶ = FROM_MODE)・{"docId", "title"?}(文書 → 文字起こし → パック)・
        {"path", "title"?}(動画ファイル → 文字起こし)。どれも "force"?: true = 鍵が同じ・違っても作り直す。形が違えば ValueError"""
        d = input if isinstance(input, dict) else {}
        title = str(d.get("title") or "")[:120]
        force = d.get("force") is True
        if d.get("videoId"):
            if from_ not in FROM_MODE:
                raise ValueError("from は %s のどれかです" % "・".join(k for k in FROM_MODE if k))
            return cls(str(d["videoId"]), title, FROM_MODE[from_], _spec.top_arg(d.get("top")), force=force)
        if d.get("docId"):
            return cls(None, title or str(d["docId"]), DOC_MODE, None, doc_id=str(d["docId"]), force=force)
        if d.get("path"):
            return cls(None, title or os.path.basename(str(d["path"])), "file", None, source_path=str(d["path"]), force=force)
        raise ValueError("入力は videoId・docId・path のどれかです")

    def key(self):
        """配信・文書ごとの前回の結果を引くキー"""
        if self.source_path:
            return ("file", self.source_path)
        return ("doc", self.doc_id) if self.doc_id else ("video", self.video_id)

    def step(self, key):
        return next(s for s in self.steps if s["key"] == key)

    def public(self):
        return {"id": self.id, "kind": "file" if self.source_path else "doc" if self.doc_id else "video", "docId": self.doc_id, "overwrite": self.overwrite,
                "force": self.force,
                "sourcePath": self.source_path, "requestId": self.request_id, "ranges": [list(r) for r in self.ranges] or None, "cut": self.cut,
                "engine": self.engine, "model": self.model,
                "friendLength": dict(self.friend_length) if self.friend_length else None,
                "videoId": self.video_id, "title": self.title, "mode": self.mode,
                "modeLabel": (MODES.get(self.mode) or REQUEST_MODES.get(self.mode) or DOC_LABEL) +("(%d本)" % len(self.marks) if self.marks and self.mode not in REQUEST_URL_MODES else ""), "top": self.top,
                "streamer": self.streamer, "streamerFrom": self.streamer_from, "marks": list(self.marks) if self.marks else None, "fromSearch": bool(self.fresh),
                "state": self.state, "stateLabel": RUN_STATE_LABELS["nothing" if self.nothing and self.state == "done" else self.state],
                "nothing": self.nothing, "onFail": self.on_fail, "docs": list(self.docs[:20]),
                "message": self.message, "error": self.error, "created": int(self.created * 1000),
                "finished": int(self.finished * 1000) if self.finished else None, "resultPath": self.result_path,
                "steps": [dict(s, stateLabel=STEP_STATE_LABELS.get(s["state"], s["state"])) for s in self.steps]}


class Runner:
    """① の経路: 段の中身(_step_*・_doc_*・_file_*)と、ツールの仕事を待つ骨組み(_check・_wait・_call_when_free・_poll)。
    client = ツールの API(call(ツール, メソッド, パス, body) -> (HTTP の番号, JSON)・ok(同じ) -> JSON か StepError)。
    tools = 段が仕事を頼む先(flow/tools.py。既定は HttpTools(client) = 今の API の形)。
    hook の既定は「何も知らない」安全な値(入口の AutoRunner が案件・ホームの設定・届けることで埋める)"""

    def __init__(self, client, env=None, poll=1.0, sleep=None, log=None, clock=None, find_pack=None, tools=None):
        """poll = ツールの仕事を見に行く間隔(秒)。sleep・clock はテスト用。log = 1 行のログ。find_pack(動画のパス) = パックの有無(既定は「無い」)"""
        self.client, self.env, self.poll = client, env, poll
        self.tools = tools if tools is not None else _tools.HttpTools(client)
        self.sleep = sleep or time.sleep
        self.log = log or (lambda msg: None)
        self.clock = clock or time.time
        self.find_pack = find_pack or (lambda path: None)
        self.closed = False   # 入口の終了(_check が止める)

    # ------------------------------------------------------------ hook(既定 = 何も知らない。src/home/autorun.py の AutoRunner が埋める)
    def _await_tools(self, run):
        """戻した実行(M5)で、使うツールの準備を待つ。既定は待たない"""
        run.resumed = False

    def _checkpoint(self, run):
        """段の始まりと済んだとき(起動し直しで続けるための待ちの記録)。既定は残さない"""

    def _studio_video(self, vid):
        """スタジオの一覧の 1 本(元の動画の場所など)。既定は {}"""
        return {}

    def _friend_length(self):
        """友人の区間の長さの実績(解析の設定に重ねる)。既定は None = 使わない"""
        return None

    def _docs(self):
        """文字起こしの文書の一覧。既定は道具の一覧(HttpTools = GET /api/transcripts の要約・LocalTools = 作業データの文書を直に。RS6 b-K2)"""
        return self.tools.docs()

    def _full_doc(self, d):
        """一覧の 1 行 -> 動画の場所と行を持つ形(要約だけの行は tools.doc で読む)か None"""
        if d is None or "sourcePath" in d:
            return d
        return self.tools.doc(d["id"])

    def _pick_doc(self, docs, video_id, mark_id, path):
        """切り抜きの文書 1 つか None。既定は道具の一覧から: 動画の名前(か配信)で絞り、新しい順に中身を読んで、動画のパスが同じ・
        か配信とマークが同じ物(manage/cases/txindex の紐づけと同じ考え。30fps の写しへの付け替えの前のパスは見ない)。RS6 b-K2"""
        want = os.path.normcase(os.path.abspath(path)) if path else ""
        name = os.path.basename(path or "")
        cands = sorted((d for d in docs if (d.get("sourceName") or os.path.basename(d.get("sourcePath") or "")) == name
                        or (video_id and d.get("videoId") == video_id)), key=lambda d: d.get("updatedAt") or 0, reverse=True)
        for d in cands:
            full = self._full_doc(d)
            if not full:
                continue
            if want and full.get("sourcePath") and os.path.normcase(os.path.abspath(full["sourcePath"])) == want:
                return full
            clip = full.get("clip") or {}
            src = clip.get("source") if isinstance(clip.get("source"), dict) else {}
            mk = clip.get("mark") if isinstance(clip.get("mark"), dict) else {}
            if video_id and mark_id and src.get("videoId") == video_id and mk.get("id") == mark_id:
                return full
        return None

    def _pref(self, key, default=None):
        """ホームの設定 autorun の値。既定は default"""
        return default

    def _live_auto_origin(self, media):
        """切り抜きがリアルタイム切り抜きの自動の採用か(M8)。既定は False"""
        return False

    def _auto_streamer(self, run, doc=None, v=None):
        """指定の無い実行の配信者を決める(段5)。既定は決めない(字幕の色なし)"""

    def _after_pack(self, run, st, prefix):
        """パックが 1 本できたとき(① 全自動は n 本たまるごとに届ける)。既定は何もしない"""

    def _remember_styles(self, tid, styles):
        """字幕の色を文書の話者に覚える。-> 覚えたか。既定は False"""
        return False

    def _remember_doc_streamer(self, tid, name):
        """依頼で選んだ配信者を、文書の配信者として覚える。-> 覚えたか。既定は False"""
        return False

    # ------------------------------------------------------------ 待つ骨組み
    def _check(self, run):
        if run.cancel or self.closed:
            raise Cancelled()

    def _wait(self, run, seconds=None):
        self._check(run)
        self.sleep(self.poll if seconds is None else seconds)
        self._check(run)

    def _bundle(self, run):
        """この実行の束(run() が置いた物。置かれていなければ既定の束を置く)"""
        if run.spec is None:
            run.spec = _spec.merge(None)
        return run.spec

    def _force(self, run):
        """鍵が同じ・違っても作り直すか(Run の force か束の run.force。RS6 b-K2)"""
        return run.force or self._bundle(run)["run"]["force"] is True

    @staticmethod
    def _tx_state(doc, path, opts):
        """切り抜き path の文書 doc の transcribe の鍵と、今の要求 opts で認識したときの材料を比べる(flow/keys)-> same | differ | none"""
        return _keys.transcribe_state(doc["id"], path, opts)

    def _pack_state(self, run, doc, media, pack_opts, v=None):
        """切り抜き media の既定のパックの鍵と、今作ったときの材料を比べる -> (same | differ | none, _pack_body の結果 か None)。
        鍵が無ければ本文を作らない(今のパックは今のまま)。本文を作れなければ (none, None)"""
        def make():
            self._auto_streamer(run, doc, v)
            return self._pack_body(run, doc, media, pack_opts)
        try:
            return _keys.pack_state(media, make)
        except StepError:
            return "none", None

    def _call_when_free(self, run, st, send, waiting):
        """send() で仕事を頼み、ツールが 409 busy(別の処理の最中)なら BUSY_WAIT 秒ごとにやり直す(待つ間は st に waiting の文)。-> (HTTP の番号, 応答)"""
        while True:
            status, res = send()
            if not (status == 409 and res.get("error") == "busy"):
                return status, res
            st["detail"] = waiting
            self._wait(run, BUSY_WAIT)

    def _poll(self, run, owned, read, cancel=None, start=None):
        """ツールの仕事が終わるまで待つ骨組み(解析・書き出し・文字起こし・パック・「編集」のジョブで共通)。-> read() の結果
        owned: 起動し直すときに止めてよいツールの仕事(run.owned。None = 書き出しのように自分の仕事にしない)。終わったら外す。
        start(): 待つ前の投入(中止されたら、投入済みの分も cancel で取り消す)。read(): 終わったら None 以外、まだなら None(進み具合は read の中で st へ)。
        中止(Cancelled)なら cancel()(ツールの仕事を取り消す)を呼んでから上げ直す"""
        run.owned = owned
        try:
            if start is not None:
                start()
            while True:
                self._wait(run)
                r = read()
                if r is not None:
                    return r
        except Cancelled:
            if cancel is not None:
                cancel()
            raise
        finally:
            run.owned = None

    def _video(self, run):
        st, obj = self.tools.video(run.video_id)
        if st == 404 and run.fresh:   # ① 探す から: 解析のキューに入れるまではスタジオに無い(受け取った題名で進める)
            return {"kind": "youtube", "title": run.title}
        if st != 200:
            raise StepError(obj.get("message") or "スタジオがうまく応答しませんでした。少し待って、もう一度実行してください(済んだ段は飛ばします)")
        v = obj.get("video") or {}
        run.title = str(v.get("title") or v.get("fileName") or run.video_id)[:120]
        return v

    # ------------------------------------------------------------ 実行
    def execute(self, run):
        """1 回の実行を段の順に進める(入口の糸 autorun._loop が run() を通して呼ぶ)。中止は Cancelled・失敗は StepError を上げる"""
        if run.resumed:   # 入口を起動し直して戻した実行(M5): ツールの準備を待つ
            self._await_tools(run)
        if run.source_path:   # 依頼の動画(mode file): _file_<段>
            return self._run_steps(run, lambda key, st: getattr(self, "_file_" + key)(run, st))
        if run.doc_id:   # 文書単位(⑦(b)): _doc_<段>
            return self._run_steps(run, lambda key, st: getattr(self, "_doc_" + key)(run, st))
        cur = [self._video(run)]   # 配信: _step_<段>。段が済むたびにスタジオの配信を読み直す

        def refresh():
            cur[0] = self._video(run)
        self._run_steps(run, lambda key, st: getattr(self, "_step_" + key)(run, st, cur[0]), refresh)

    def _run_steps(self, run, call, after=None):
        """段を順に進める。call(段の鍵, 段) -> "stop" ならそこで止めて残りを飛ばす。after() = 段が済むたび(記録のあと)"""
        for key in [s["key"] for s in run.steps]:
            self._check(run)
            st = run.step(key)
            if st["state"] in DONE_STEPS:   # 戻した実行(M5)の済んだ段は飛ばす(続きから)
                continue
            st["state"] = "run"
            run.message = st["label"]
            self._checkpoint(run)   # どの段の途中か(M5。起動し直したらこの段から)
            result = call(key, st)
            if st["state"] == "run":
                st["state"] = "done"
            self._checkpoint(run)   # 段が済んだ(M5)
            if after:
                after()
            if result == "stop":   # 続けても意味がない(採用するマークが無いなど)
                for s in run.steps:
                    if s["state"] == "wait":
                        s["state"], s["detail"] = "skip", s["detail"] or "前の段で止めました"
                break
        self._finish_message(run)

    def _finish_message(self, run):
        """どの段も飛ばした = やることが無かった(「完了」と言わない。段4 S-4)"""
        if all(s["state"] == "skip" for s in run.steps):
            run.nothing = True
            run.message = NOTHING_MESSAGE + (": " + run.message if run.message and run.message != "完了" else "")
        elif not run.message or run.message in [s["label"] for s in run.steps]:
            run.message = "完了"

    # 解析 -------------------------------------------------------
    def _weights_differ(self, run, v):
        """友人が指定した解析の重みが、今の解析の結果の重みと違うか(違えば解析し直す。音量・チャットの取り込み済みのデータは使い回される)"""
        if not run.weights:
            return False
        spec = (v.get("analysis") or {}).get("spec") if isinstance(v.get("analysis"), dict) else None
        spec = spec if isinstance(spec, dict) else {}
        return any(not _num(spec.get(k)) or round(float(spec[k]), 1) != run.weights[k] for k in WEIGHT_KEYS)

    def _step_analyze(self, run, st, v):
        if v.get("analysis") and not self._weights_differ(run, v):
            st["state"], st["detail"] = "skip", "解析済み(前の結果を使います)" if run.request_id else "解析済み"
            return None
        item = {"kind": v.get("kind") or "youtube", "videoId": run.video_id}
        if run.fresh and item["kind"] == "youtube":   # ① 探す から: 題名・配信者はスタジオの一覧にそのまま出る(解析の前に分かっている分)
            item.update({k: run.fresh[k] for k in ("title", "channel") if run.fresh.get(k)})
        if item["kind"] == "file":
            path = self._studio_video(run.video_id).get("path")
            if not path:
                raise StepError("元の動画ファイルの場所が分かりません")
            item = {"kind": "file", "path": path}
        self._analyze_item(run, st, item, run.video_id)
        return None

    def _analyze_item(self, run, st, item, video_id):
        """スタジオの解析のキューに入れて、終わるまで待つ(配信の解析と、依頼 ③ の動画の解析で共通)"""
        # 解析の設定は束の analyze 節(入口はスタジオの画面で保存したもの = 段階7-1 から組む。RS6 b-0)
        saved = dict(self._bundle(run)["analyze"])
        own = saved != _spec.DEFAULTS["analyze"]   # 既定と違う = スタジオの画面で変えた設定
        if run.weights:   # 友人が指定した重み(ほかの解析の設定はスタジオのまま)
            saved = dict(saved, **run.weights)
        fl = self._friend_length() if run.mode in REQUEST_URL_MODES else None
        if fl:   # 友人の依頼の足りない分を自動で埋める: 自動の候補の長さを、友人が選んだ区間の長さの実績に合わせる(解析し直しの理由にはしない)
            saved = dict(saved, **{k: fl[k] for k in ("length", "preRatio") if k in fl})
            run.friend_length = fl
        res = self.tools.analyze_add(item, saved)
        added = res.get("added") or []
        qid = added[0]["qid"] if added else None
        if not qid:
            rej = (res.get("rejected") or [{}])[0].get("reason") or ""
            if "すでにキュー" not in rej:
                raise StepError("解析を始められませんでした: %s" % (rej or "理由不明"))
        st["detail"] = "解析中(%s)" % ("依頼の重み(音声 %s・チャット %s・コメント %s)" % tuple(run.weights[k] for k in WEIGHT_KEYS) if run.weights
                                    else "スタジオで保存した解析の設定" if own else "解析の設定は既定値。スタジオの ② で設定を変えると次から使います")
        fl_note = ("。長さ %d 秒%s(友人の区間の実績から)" % (fl["length"], "・山の前 %.2f" % fl["preRatio"] if "preRatio" in fl else "")) if fl else ""
        st["detail"] += fl_note
        def read():
            items = self.tools.analyze_items()
            it = next((i for i in items if (i.get("qid") == qid if qid else i.get("videoId") == video_id)), None)
            if it is None:
                raise StepError("解析の順番から外れました(スタジオで取り消したかもしれません)。もう一度実行してください")
            st["detail"] = "%s %d%%" % (it.get("phase") or "", round((it.get("progress") or 0) * 100))
            if it.get("status") == "done":
                st["detail"] = "解析しました(候補 %s 件)" % it.get("marks", "?") + fl_note
                return True
            if it.get("status") in ("error", "cancelled", "skipped"):
                raise StepError("解析が終わりませんでした: %s" % (it.get("error") or JOB_STATE_JA.get(it.get("status"), "理由は不明です")))
            return None
        # 人が入れた解析(qid なし)を待つときは自分の仕事にしない・中止しても止めない(この実行が入れた解析だけ取り消す)
        self._poll(run, ("studio", [qid]) if qid else None, read, (lambda: self._cancel_analysis(qid)) if qid else None)
        return None

    def _cancel_analysis(self, qid):
        """スタジオの解析のキューの1件を取り消し(POST /api/queue/cancel)、止まるまで待つ(CANCEL_WAIT 秒まで)。
        次の実行が同じ配信の解析をキューに入れられるように・重い処理の枠を空けてから進むため。失敗しても上げない(中止の途中)"""
        try:
            self.tools.analyze_cancel(qid)
            for _ in range(int(CANCEL_WAIT / self.poll) if self.poll > 0 else 30):
                it = next((i for i in self.tools.analyze_items() if i.get("qid") == qid), None)
                if it is None or it.get("status") not in ("waiting", "running"):
                    return
                self.sleep(self.poll)
        except Exception:
            return

    # 採用 -------------------------------------------------------
    def _step_adopt(self, run, st, v):
        """採用(F-5。規則はスタジオの 1 つ = tools.request_marks の先の store.adopt_marks。RS6 b-A):
        友人が時刻で指定した区間(前後に束の adopt.pad 秒の余白)∪ 人が採用したマーク ∪ 自動マークの点数の高い順(上限 = Run の top か束の adopt.top までの残り)。
        不採用と、区間・人の採用に重なる自動マークは除く。人が採用済みの配信の再実行でも、上限までの残りを自動で足す。
        友人の依頼(URL)は、この実行で扱うマークをその集合にする(run.marks。同じ配信の送り直しでは、前に作った切り抜き・文字起こしを使い回す)"""
        ad = self._bundle(run)["adopt"]
        top = run.top if run.top is not None else ad["top"]
        dur = v.get("duration") or run.duration
        body = {"id": run.video_id, "ranges": [pad_range(s, e, dur, ad["pad"]) for s, e in run.ranges], "top": top}
        if run.fresh:
            body.update({k: run.fresh[k] for k in ("title", "channel") if run.fresh.get(k)})
        res = self.tools.request_marks(body)
        rids, hids, aids = res.get("rangeIds") or [], res.get("humanIds") or [], res.get("autoIds") or []
        added = set(res.get("added") or [])
        chosen = tuple(dict.fromkeys(rids + hids + aids))
        if run.mode in REQUEST_URL_MODES:
            run.marks = chosen
        if not chosen:
            st["state"], st["detail"] = "skip", "採用できる候補がありません"
            run.message = "採用できる候補がありませんでした"
            return "stop"
        new_auto = sum(1 for i in aids if i in added)
        short = top - len(rids) - len(hids) - len(aids)
        parts = (["指定の区間 %d 個(前後に %g 秒の余白)" % (len(rids), ad["pad"])] if rids else []) + \
            (["人が採用した %d 本" % len(hids)] if hids else []) + \
            (["前に自動で採用した %d 本" % (len(aids) - new_auto)] if len(aids) > new_auto else []) + \
            (["自動で %d 本を足しました(点数の高い順)" % new_auto] if new_auto else [])
        st["detail"] = "・".join(parts) + ("。候補が足りず %d 本は選べませんでした" % short if short > 0 else "")
        if not added and run.mode not in REQUEST_URL_MODES:   # 新しく採用したものが無い(前の採用をそのまま使う)
            st["state"] = "skip"
            st["detail"] += "(新しく採用したものはありません)"
        return None

    # 書き出し ---------------------------------------------------
    def _mine(self, run, v):
        """この実行で扱うマーク(マークを選んだ実行ならそれだけ)"""
        return [m for m in v.get("marks") or [] if not run.marks or m.get("id") in run.marks]

    def _step_export(self, run, st, v):
        ids = [m["id"] for m in self._mine(run, v) if m.get("status") == "adopted"]
        if not ids:
            done = sum(1 for m in self._mine(run, v) if m.get("status") == "exported")
            st["state"], st["detail"] = "skip", ("書き出し済み %d 本(新しく採用したものはありません)" % done if done else "採用したマークがありません")
            return None if done else "stop"
        body = _spec.export_body(self._bundle(run), run.video_id, ids[:50], run.screen)
        status, res = self._call_when_free(run, st, lambda: self.tools.export_start(body), "別の書き出しが終わるのを待っています")
        if status != 200:
            raise StepError("書き出しを始められませんでした: %s" % (res.get("message") or "HTTP %d" % status))
        jid = res.get("id")

        def read():
            j = self.tools.export_job(jid)
            items = j.get("items") or []
            st["detail"] = ("他のツールの重い処理を待っています" if j.get("waiting")
                            else "%d / %d 本" % (sum(1 for i in items if i.get("status") == "done"), len(items)))
            return j if j.get("state") != "running" else None
        # 書き出しは自分の仕事にしない(owned なし = 書き出しの最中は起動し直しを断る。REDO_STEPS)
        items = self._poll(run, None, read, lambda: self.tools.export_cancel(jid)).get("items") or []
        done = sum(1 for i in items if i.get("status") == "done")
        bad = [i for i in items if i.get("status") == "error"]
        st["detail"] = "%d 本を書き出しました" % done + ("(%d 本失敗)" % len(bad) if bad else "")
        if bad and (not done or run.on_fail == "stop"):
            raise StepError("書き出しに失敗しました(%d 本): %s" % (len(bad), bad[0].get("error") or ""))
        if bad:
            st["state"] = "warn"
        return None

    # 文字起こし -------------------------------------------------
    def _clips(self, v, run=None):
        return [m for m in (self._mine(run, v) if run else v.get("marks") or []) if m.get("status") == "exported" and isinstance(m.get("path"), str) and m["path"]
                and os.path.isfile(m["path"])]

    def _step_transcribe(self, run, st, v):
        clips = self._clips(v, run)
        if not clips:
            st["state"], st["detail"] = "skip", "書き出した切り抜きがありません"
            return "stop"
        docs = self._docs()
        opts = self._tx_opts(run)
        todo, differ, redo = [], 0, 0
        for m in clips:   # 文書のある切り抜きは鍵を見る(RS6 b-K2): 同じ・鍵なし = 飛ばす / 違う = 飛ばして印 / force = 作り直す(新しい文書。人の直しは引き継ぐ)
            doc = self._pick_doc(docs, run.video_id, m.get("id"), m["path"])
            if not doc:
                todo.append(m)
            elif self._force(run):
                todo.append(m)
                redo += 1
            elif self._tx_state(doc, m["path"], opts) == "differ":
                differ += 1
        note = ("。うち %d 本は%s" % (differ, TX_DIFFER)) if differ else ""
        if not todo:
            st["state"], st["detail"] = "skip", "%d 本とも文字起こし済み" % len(clips) + note
            return None
        jobs = []   # 入れたジョブ(同じリストに足していく = 起動し直すときに止めてよい仕事 run.owned)

        def submit():
            for m in todo:
                self._check(run)
                jobs.append(self.tools.transcribe_start(dict(opts, sourcePath=m["path"]), bundle=self._bundle(run)))

        def read():
            all_jobs = {j.get("id"): j for j in self.tools.jobs()}
            mine = [all_jobs.get(j) or {"state": "error", "error": "文字起こしのジョブが見つかりません"} for j in jobs]
            fin = [j for j in mine if j.get("state") in ("done", "error", "cancelled")]
            cur = next((j for j in mine if j.get("state") not in ("done", "error", "cancelled", "queued")), None)
            st["detail"] = "%d / %d 本" % (len(fin), len(jobs)) + (" ・ %s %d%%" % (cur.get("phase") or "", round((cur.get("progress") or 0) * 100)) if cur else "")
            return mine if len(fin) == len(jobs) else None

        def cancel():
            for j in jobs:
                self.tools.transcribe_cancel(j)
        mine = self._poll(run, ("transcribe", jobs), read, cancel, start=submit)
        ok = [j for j in mine if j.get("state") == "done"]
        bad = [j for j in mine if j.get("state") != "done"]
        run.docs += [j["tid"] for j in ok if j.get("tid") and j["tid"] not in run.docs]
        run.new_docs += [j["tid"] for j in ok if j.get("tid")]
        st["detail"] = "%d 本を文字起こししました" % len(ok) + ("(%d 本失敗)" % len(bad) if bad else "") + \
            ("。うち %d 本は作り直し(force)" % redo if redo else "") + note + "。字幕の校正は「編集」の 1 文字起こしで"
        if bad and (not ok or run.on_fail == "stop"):
            raise StepError("文字起こしに失敗しました(%d 本): %s" % (len(bad), _job_why(bad[0])))
        if bad:
            st["state"] = "warn"
        return None

    # パック -----------------------------------------------------
    def _edit_keeps(self, doc):
        """「編集」のカット(残す区間の秒。接している区間 = 分割しただけの所は1つに)と rev。無い・読めなければ (None, 0)"""
        status, res = self.tools.edit(doc["id"])
        e = res.get("edit") if status == 200 and isinstance(res, dict) else None
        clips = e.get("clips") if isinstance(e, dict) else None
        if not clips:
            return None, 0
        out = []
        for c in clips:
            a, b = float(c["in"]), float(c["out"])
            if out and a <= out[-1][1] + 1e-9:
                out[-1][1] = max(out[-1][1], b)
            else:
                out.append([a, b])
        return out, int(res.get("rev") or 0)

    def _pack_settings(self, run):
        """パックの作り方(束の pack 節 = 入口では編集の設定の 3 パック のタブと同じ値。気が利く画面へ 段4):
        行から作るときの端の広げ方(rowEdge)・Text+ の置き先(fps・大きさ)・1段の文字数(縦横に合わせる)・話者の色・音量・予備・無音で削るときの値(cutSilence)。
        fps は画面だけの値(Run.screen)。知らせ = 入口が設定を束にするときに直した所(行からの設定の形が変なら既定で作った、など)。
        -> (rowEdge, output に足すもの, cutSilence, 知らせ)"""
        row_edge, wrap_out, cut_silence = _spec.pack_output(self._bundle(run), run.screen)
        # 素材は 30fps にそろえる(2026-10-04 Q1)。素材がちょうど 30fps のときは、画面の packFps(60 など)に関係なく 30 にする(_pack_one)
        return row_edge, wrap_out, cut_silence, _spec.clean_screen(run.screen)["packNotes"]

    def _cut_method(self, run=None):
        """カットを決めていない文書のカットの方法(束の pack.cut。入口はホームの設定 autorun.cut から。既定はカットしない = 2026-10-01)"""
        return (self._bundle(run) if run is not None else _spec.DEFAULTS)["pack"]["cut"]

    @staticmethod
    def _speaker_styles(run):
        """友人が指定した人ごとの字幕の見た目 -> {名前: {"color": "#RRGGBB"}}(無ければ {})。
        色は画面・Lua に入るので、ここでも 16 進 6 桁だけにそろえ直す(intake の検査を通ってきたはずだが、実行の作り手がほかにも増えたときのため)"""
        out = {}
        raw = (run.speakers or {}).get("styles")
        for name, sty in (raw.items() if isinstance(raw, dict) else []):
            hx = colors.norm_hex(sty.get("color")) if isinstance(name, str) and name and isinstance(sty, dict) and isinstance(sty.get("color"), str) else None
            if hx:
                out[name] = {"color": hx}
        return out

    def _pack_body(self, run, doc, media, pack_opts):
        """1本のパックの要求の本文(cut2resolve の POST /api/build。上書き force は送る直前に足す)。「編集」でカットを決めてあればそのとおり
        (3 パック のタブのパックと同じ中身)、無ければ文字起こしの行だけを残す規則(preset transcript-rows)など。-> (本文, 残す区間 か None, カットの rev)"""
        row_edge, wrap_out, cut_silence = pack_opts[:3]
        if wrap_out.get("textplusFps", "30") != "30" and _media_is_30fps(media):
            wrap_out = dict(wrap_out, textplusFps="30")   # 素材がちょうど 30fps なら設定の packFps に関係なく 30(Q1。_pack_settings の説明)
        keeps, rev = self._edit_keeps(doc)
        if keeps:
            captions = _has_captions(doc)
            tr = self.tools.transcript_file(doc["id"]) if captions else {}
            spec = dict({"video": media, "keeps": keeps}, **({"transcript": tr.get("path")} if captions else {}))
            body = {"spec": spec, "output": dict({"textplus": captions, "copyVideo": True}, **wrap_out)}
        else:   # カットを決めていない文書: カットの方法(ホームの設定。rows = 行から・none = カットしない・silence = 無音で削る)
            tr = self.tools.transcript_file(doc["id"])
            # 友人が選んだカット(① の依頼)・リアルタイム切り抜きの live.auto.cut(M2)。無ければ、自動の採用の切り抜きは区間の全体(M8)、ほかはホームの設定
            method = run.cut or (LIVE_AUTO_CUT if run.source_path and self._live_auto_origin(media) else self._cut_method(run))
            if method == "none":   # 動画全体(削る区間なし)。カット済の行の字幕も消さない
                spec = {"video": media, "transcript": tr.get("path"), "mode": "list", "listKind": "drop", "listText": "", "dropCutRows": False, "minLen": 0}
            elif method == "silence":   # 無音で削る(値は編集の設定 cutSilence。無ければ cut2resolve の既定)
                spec = {"video": media, "transcript": tr.get("path"), "mode": "silence", "silence": cut_silence}
            else:
                spec = {"video": media, "transcript": tr.get("path"), "preset": "transcript-rows"}
                if isinstance(row_edge, (bool, dict)):
                    spec["rowEdge"] = row_edge
            body = {"spec": spec, "output": dict({"textplus": True}, **wrap_out)}
        if run.video_tracks:   # 友人が選んだ映像トラックの数(字幕はその上のトラック)
            body["output"]["videoTracks"] = run.video_tracks
        self._auto_streamer(run, doc)
        if run.streamer:   # 字幕の文字を配信者のメンバーカラーに(cut2resolve が同じ規則で照らし合わせる)
            body["output"]["streamer"] = run.streamer
        styles = self._speaker_styles(run)
        if styles:   # 友人が指定した話者ごとの字幕の色(古い cut2resolve は知らない鍵を読み飛ばす。空なら鍵ごと付けない = 今までと同じ要求)
            body["output"]["speakerStyles"] = styles
        return body, keeps, rev

    def _pack_one(self, run, st, doc, media, pack_opts, force=False, prefix="", built=None):
        """1本のパックを cut2resolve で作る(本文は _pack_body。built = 鍵を比べるときに作った本文があれば使い回す)。
        -> ("made", カットのとおりか) か ("exists", False)(同じ名前のパックがあり force でない)"""
        body, keeps, rev = built or self._pack_body(run, doc, media, pack_opts)
        if force:
            body["output"]["force"] = True
        status, res = self._call_when_free(run, st, lambda: self.tools.pack_start(body), prefix + "cut2resolve の別の処理が終わるのを待っています")
        if status == 409 and res.get("error") == "exists":
            return "exists", False
        if status != 200:
            raise StepError("パックを作れませんでした: %s" % (res.get("message") or "HTTP %d" % status))
        jid = (res.get("job") or {}).get("id")

        def read():
            j = self.tools.pack_job(jid)
            if j.get("state") != "running":
                return j
            if j.get("message"):
                st["detail"] = prefix + j["message"]
            return None
        j = self._poll(run, ("cut2resolve", [jid]), read, lambda: self.tools.pack_cancel(jid))
        if j.get("state") != "done":
            err = j.get("error")
            raise StepError("パックを作れませんでした: %s" % ((err.get("message") if isinstance(err, dict) else err) or _job_why(j)))
        r = j.get("result") or {}
        out = os.path.normpath(r["outDir"]) if r.get("outDir") else ""   # 届けた印(run.delivered)と同じ書き方にそろえる
        if out and out not in run.packs:
            run.packs.append(out)   # ① 全自動で Dropbox へ届けるもの
            run.pack_marks[out] = dict(run.pack_hint or {})   # どの切り抜き・どのマークのパックか(_step_pack が hint を置く。友人の「要らない」で引く)
            run.pack_hint = None
            self._after_pack(run, st, prefix)   # ① 全自動: n 本たまるごとに届ける(全部を待たない。AutoRunner)
        if keeps:   # 作った記録(packRev)を「編集」に残す(カット・字幕を直したら「作り直し」と知らせるため)。残せなくてもパックはできている
            self.tools.record_pack({"id": doc["id"], "rev": rev, "docUpdatedAt": int(doc.get("updatedAt") or 0),
                                    "dir": r.get("outDir") or "", "files": [f.get("name") for f in r.get("files") or [] if isinstance(f, dict)]})
        return "made", bool(keeps)

    def _step_pack(self, run, st, v):
        clips = self._clips(v, run)
        docs = self._docs()
        opts = self._pack_settings(run)
        force_all = run.overwrite or self._force(run)
        todo, no_tx, made, stale = [], 0, 0, 0
        for m in clips:   # パックの鍵(RS6 b-K2): 違う(字幕が新しい・設定が違う)= 作り直す / 同じ = 飛ばす / 鍵なし = 今のまま(無ければ作る・あれば上書きのときだけ)
            doc = self._pick_doc(docs, run.video_id, m.get("id"), m["path"])
            if not doc:
                no_tx += 1
                continue
            state, built = ("none", None) if force_all else self._pack_state(run, doc, m["path"], opts, v)
            if force_all or state == "differ":
                todo.append((m, doc, True, built))
                stale += state == "differ"
            elif state != "same" and not self.find_pack(m["path"]):
                todo.append((m, doc, False, built))
        if not todo:
            st["state"], st["detail"] = "skip", ("パック済み(「パックがあれば作り直す(上書き)」を選ぶと作り直します)" if clips and not no_tx else "文字起こしのある切り抜きがありません")
            return None
        skipped, failed, by_edit = [], [], 0
        self._auto_streamer(run, todo[0][1] if todo else None, v)
        for i, (m, doc, force, built) in enumerate(todo, 1):
            self._check(run)
            prefix = "%d / %d 本 ・ " % (i - 1, len(todo))
            st["detail"] = prefix.rstrip(" ・ ")
            try:
                run.pack_hint = {"path": m["path"], "markId": str(m.get("id") or "")}
                res, cut = self._pack_one(run, st, doc, m["path"], opts, force=force, prefix=prefix, built=built)
            except StepError as e:
                if run.on_fail == "stop":
                    raise
                failed.append("%s(%s)" % (os.path.basename(m["path"]), str(e)[:120]))   # 次へ進む設定: 残りを続ける
                continue
            if res == "exists":
                skipped.append(os.path.basename(m["path"]))   # 同じ名前のパックがある: 上書きしない(人が作り直したものかもしれない)
                continue
            made += 1
            by_edit += 1 if cut else 0
            if doc["id"] not in run.docs:
                run.docs.append(doc["id"])
        if failed and not made:
            raise StepError("パックを作れませんでした: %s" % failed[0])
        st["detail"] = "%d 本のパックを作りました" % made + ("(うち %d 本は「編集」のカットのとおり)" % by_edit if by_edit else "") + \
            ("。前のパックを上書きしました" if force_all and not run.request_id else "") + \
            ("。うち %d 本は%s" % (stale, PACK_DIFFER) if stale else "") + "。字幕を校正したら「編集」のパックのタブで作り直してください"
        if skipped:
            st["detail"] += "。同じ名前のパックがあるので上書きしなかったもの: %s" % "・".join(skipped[:5])
        if failed:
            st["state"] = "warn"
            st["detail"] += "。失敗した %d 本: %s" % (len(failed), "・".join(failed[:3]))
        for n in opts[3]:
            st["detail"] += "。" + n
        if run.streamer_from:   # 自動で入れた配信者は進み具合に出す(コラボで相手の色になることがあるため。段5)
            st["detail"] += "。字幕の色: %s(%s)" % (run.streamer, "自動: チャンネル名から" if run.streamer_from == "auto" else "前回の名前")
        return None

    # 文書単位の実行(⑦(b)) -------------------------------------
    def _doc(self, run):
        d = self._full_doc(next((x for x in self._docs() if x["id"] == run.doc_id), None))
        if not d:
            raise StepError("文書が見つかりません(消した可能性があります)")
        run.title = d["title"] or run.title
        src = d.get("sourcePath") or ""
        if not src or not os.path.isfile(src):
            raise StepError("元の動画が見つかりません(移動・削除した可能性があります)")
        return d

    def _tx_opts(self, run):
        """文字起こしの要求の設定の部分(束から = flow/spec.py の tx_opts。入口では「編集」の設定のうち文字起こしの項目 = 画面から文字起こしするときと同じ値)"""
        return _spec.tx_opts(self._bundle(run), run.screen)

    def _wait_job(self, run, jid, st=None, what="文字起こし"):
        """「編集」のジョブ 1 つが終わるまで待つ(st があれば進み具合を出す)。中止されたらジョブを取り消して上げる。-> 終わったジョブ"""
        def read():
            j = next((x for x in self.tools.jobs() if x.get("id") == jid),
                     {"state": "error", "error": "%sのジョブが見つかりません" % what})
            if j.get("state") in ("done", "error", "cancelled"):
                return j
            if st is not None:
                st["detail"] = "%s %d%%" % (j.get("phase") or "", round((j.get("progress") or 0) * 100))
            return None
        return self._poll(run, ("transcribe", [jid]), read, lambda: self.tools.transcribe_cancel(jid))

    def _doc_transcribe(self, run, st):
        doc = self._doc(run)
        if doc["count"]:
            st["state"], st["detail"] = "skip", "文字起こし済み"
            return None
        jid = self.tools.transcribe_start(dict(self._tx_opts(run), sourcePath=doc["sourcePath"], intoDoc=doc["id"]), bundle=self._bundle(run))
        j = self._wait_job(run, jid, st)
        if j.get("state") != "done":
            raise StepError("文字起こしに失敗しました: %s" % _job_why(j))
        st["detail"] = "文字起こししました。字幕の校正は「編集」の 1 文字起こしで"
        return None

    def _doc_pack(self, run, st):
        doc = self._doc(run)
        opts = self._pack_settings(run)
        force = run.overwrite or self._force(run)
        state, built = ("none", None) if force else self._pack_state(run, doc, doc["sourcePath"], opts)   # パックの鍵(RS6 b-K2。_step_pack と同じ)
        if state == "same" or (state == "none" and not force and self.find_pack(doc["sourcePath"])):
            st["state"], st["detail"] = "skip", "パック済み(「作り直す」を選ぶと上書きします)"
            return None
        if not _has_captions(doc) and not self._edit_keeps(doc)[0]:
            st["state"], st["detail"] = "skip", "残す字幕の行もカットも無いので、パックを作れません(2 カット のタブで区間を決めると作れます)"
            return None
        res, cut = self._pack_one(run, st, doc, doc["sourcePath"], opts, force=force or state == "differ", built=built)
        if res == "exists":   # find_pack で見つからない名前違いのパック(以前の版で作ったもの)など
            st["state"], st["detail"] = "skip", "同じ名前のパックがあるので上書きしませんでした(「作り直す」を選ぶと上書きします)"
            return None
        st["detail"] = "パックを作りました" + ("(「編集」のカットのとおり)" if cut else "(文字起こしの行から)") + \
            ("。前のパックを上書きしました" if force else "。" + PACK_DIFFER if state == "differ" else "") + "".join("。" + n for n in opts[3])
        return None

    # 話者分離(友人の「話す人」) --------------------------------
    def _step_diarize(self, run, st, v=None):
        """この実行で文字起こしした文書を、友人が入れた人数で話者分離し、名前は覚えている声と照らし合わせる(1人なら判別せずその人)。
        失敗しても次の段へ進む(字幕は話者なしのまま。一部失敗)"""
        tids = list(dict.fromkeys(run.new_docs))
        if not tids:
            st["state"], st["detail"] = "skip", "新しく文字起こしした文書がありません"
            return None
        sp = run.speakers or {}
        body = {"numSpeakers": sp.get("count"), "names": list(sp.get("names") or []), "recognize": True}
        styles = self._speaker_styles(run)   # 友人が指定した字幕の色(あれば話者分離のあと、文書に覚える)
        bad, no_color = [], []
        for i, tid in enumerate(tids, 1):
            self._check(run)
            st["detail"] = "%d / %d 本" % (i - 1, len(tids))
            status, res = self.tools.diarize_start(dict(body, tid=tid))
            if status != 200:
                bad.append(res.get("message") or "HTTP %d" % status)
                continue
            j = self._wait_job(run, res.get("id"), what="話者分離")
            if j.get("state") != "done":
                bad.append(j.get("error") or j.get("state"))
            elif styles and not self._remember_styles(tid, styles):
                no_color.append(tid)
        n = sp.get("count")
        st["detail"] = "%d 本を %d 人に分けました" % (len(tids) - len(bad), n) + ("(名前: %s)" % "・".join(sp["names"]) if sp.get("names") else "") + \
            "。名前の分からない人は「話者1」などのまま"
        if styles and len(no_color) < len(tids) - len(bad):
            st["detail"] += "。字幕の色を覚えました(%s)" % "・".join(styles)
        if no_color:   # 古い「編集」など。依頼は止めない(一部失敗にもしない。パックには色を渡すので、その分の字幕には効く)
            st["detail"] += "。字幕の色を覚えられませんでした(%d 本)" % len(no_color)
        if bad:
            st["state"] = "warn"
            st["detail"] += "。失敗した %d 本: %s" % (len(bad), str(bad[0])[:120])
        return None

    def _file_diarize(self, run, st):
        return self._step_diarize(run, st)

    # 依頼の動画(mode file) -------------------------------------
    def _file_pack(self, run, st):
        if not run.doc_id:
            st["state"], st["detail"] = "skip", "文字起こしの文書がありません"
            return "stop"
        return self._doc_pack(run, st)

    def _file_transcribe(self, run, st):
        if not os.path.isfile(run.source_path):
            raise StepError("依頼の動画が見つかりません(移動・削除した可能性があります)")
        doc = self._pick_doc(self._docs(), None, None, run.source_path)
        opts = self._tx_opts(run)
        if run.engine:   # 実行ごとに選んだエンジン・モデル(リアルタイム切り抜きの live.auto。M2)。無ければ編集の設定のまま
            opts["engine"] = run.engine
        if run.model:
            opts["model"] = run.model
        redo = bool(doc and doc.get("count") and self._force(run))   # 鍵(RS6 b-K2): force なら作り直す(新しい文書。人の直しは引き継ぐ)
        if doc and doc.get("count") and not redo:
            differ = self._tx_state(doc, run.source_path, opts) == "differ"   # 違えば飛ばして印・同じ / 鍵なしは飛ばす
            st["state"], st["detail"] = "skip", "文字起こし済み" + ("(%s)" % TX_DIFFER if differ else "")
            tid = doc["id"]
        else:
            jid = self.tools.transcribe_start(dict(opts, sourcePath=run.source_path), bundle=self._bundle(run))
            j = self._wait_job(run, jid, st)
            if j.get("state") != "done":
                raise StepError("文字起こしに失敗しました: %s" % _job_why(j))
            tid = j.get("tid")
            if tid:
                run.new_docs.append(tid)
            st["state"], st["detail"] = "done", ("文字起こしし直しました(force)" if redo else "文字起こししました") + "。字幕の校正は「編集」で"
        if tid and tid not in run.docs:
            run.docs.append(tid)
        run.doc_id = tid or None   # ① 全自動: この文書でパックを作る
        if tid and run.streamer and self._remember_doc_streamer(tid, run.streamer):   # 依頼で選んだ配信者を、この文書の配信者として覚える(パックのときの字幕の色。段5 の記憶と同じ)
            st["detail"] += "。配信者: %s" % run.streamer
        return None


def run(client, input, spec=None, from_=None, hooks=None, tools=None):
    """① の入口: 入力(Run か {"videoId"}・{"docId"}・{"path"}。Run.from_input)を段の順に進めて、その Run を返す(中止は Cancelled・失敗は StepError)。
    spec = 指定の束(変えたい所だけ。None = 既定)。flow/spec.py の merge で既定に重ね validate で確かめて Run.spec に置く(形が違えば ValueError。段は始めない)。
    hooks = hook を埋めた Runner(入口の AutoRunner)。None = 素の Runner(tools = 仕事を頼む先。None = HttpTools(client)。hooks があれば hooks の物)"""
    bundle = _spec.validate(_spec.merge(spec))
    runner = hooks if hooks is not None else Runner(client, tools=tools)
    r = input if isinstance(input, Run) else Run.from_input(input, from_)
    r.spec = bundle
    try:
        runner.execute(r)
    finally:   # 終わったら(失敗・中止でも)結果の束を案件の 作業用/runs/ へ(書けなくても上げない。RS6 b-B0)
        _placement.write_result(r, sys.exc_info()[1], runner)
    return r
