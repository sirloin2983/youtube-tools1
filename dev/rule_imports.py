#!/usr/bin/env python3
"""規則の見張りのうち、ソースを import して突き合わせる物(`dev/rule_checks.py` の続き)。

    python dev/rule_imports.py              # 全部流して問題を出す(lint.py の 11 番 `rule` が同じ物を呼ぶ)
    python dev/rule_imports.py --list

  - 突き合わせ(CHECKS): 定数・表・既定値が 2 か所で食い違わない / 置き場所のファイルが実在する。グループごとに子プロセス 1 つで流す(sys.path が違うため)。
  - 切り離し(ISOLATION): 入口やサーバーのプロセスにネイティブ部品(numpy など)・編集の serve・上の層の部品を読み込まない。
    1 つずつ別の子プロセスで import して、読み込まれた名前を調べる(別のプロセスでないと、ほかの import が混ざる)。
子プロセスは作業データを一時フォルダへ向け(YTT_DATA_DIR)、窓を出さない。
"""
import fnmatch
import json
import os
import subprocess
import sys
import tempfile
from concurrent.futures import ThreadPoolExecutor

HERE = os.path.dirname(os.path.abspath(__file__))
REPO = os.path.dirname(HERE)
SRC = os.path.join(REPO, "src")
MARK = "RULES-JSON:"
NOWIN = getattr(subprocess, "CREATE_NO_WINDOW", 0)

# グループ → sys.path の先頭に足すフォルダ(リポジトリからの相対)。最後に src も足す
GROUPS = {
    "app": ["src/app", "src"],
    "dev": ["dev", "src"],
    "studio": ["src/studio", "src"],
    "editor": ["src/editor", "src"],
    "c2r": ["src/cut2resolve", "src"],
}
CHECKS = []   # [(番号, 何を止めるか, 移した元のテスト, グループ, 関数)]


def check(rid, title, moved_from, group="app"):
    def deco(fn):
        CHECKS.append((rid, title, moved_from, group, fn))
        return fn
    return deco


NATIVE = ("numpy", "faster_whisper", "ctranslate2", "sherpa_onnx", "onnxruntime")
# 切り離し: (番号, 何を止めるか, 移した元のテスト, sys.path の先頭に足すフォルダ, 読み込むコード, 読み込まれてはいけない名前(fnmatch。 "eval.*" は eval と eval.○○))
ISOLATION = [
    ("I-01", "入口と録画の部品(live・server・flow.live_archive・live_export)が numpy を読まない", "tests/app/test_live_archive_api.py test_no_numpy_in_portal",
     ["src/app", "src"], "import live; from app import server; import flow.live_archive, flow.live_export", ["numpy"]),
    # 元のテストは子プロセスの結果を assert していなかった(何も見張っていない)。実際には tx_engines は読まれる(名前と版だけ。先頭でネイティブを読まない = I-04)ので、numpy・faster_whisper に絞った
    ("I-02", "入口が配信中の文字起こし(live_tx・live_detect)を読んでも numpy・faster_whisper を読まない", "(app のテストから移した)",
     ["src/app", "src"], "import live; import flow.live_tx, flow.live_detect", ["numpy", "faster_whisper"]),
    ("I-03", "入口とワーカー(live_detect・live_excite_worker)が numpy を読まない", "tests/pipeline/analyze/test_live_excite_worker.py test_no_numpy_in_portal_or_worker",
     ["src/app", "src"], "import live; from app import server; import flow.live_detect, pipeline.analyze.live_excite_worker", ["numpy"]),
    ("I-04", "tx_engines を読んでも numpy・faster_whisper・ctranslate2 を読まない(サーバー側でも読む。先頭でネイティブを読まない)",
     "tests/pipeline/transcribe/test_worker.py test_engine_module_has_no_native_imports・tests/pipeline/transcribe/test_qwen3.py test_engine_module_has_no_native_imports",
     ["src"], "from pipeline.transcribe import tx_engines", ["numpy", "faster_whisper", "ctranslate2", "sherpa_onnx"]),
    ("I-05", "flow.run が home(autorun・cases・prefs・deliver・friend_feedback・manage)を読まない", "tests/flow/test_run.py test_imports_without_home",
     ["src"], "import flow.run", ["autorun", "cases", "prefs", "deliver", "friend_feedback", "manage"]),
    ("I-06", "flow.runlog が autorun・launch・cases・prefs を読まない", "tests/flow/test_runlog.py test_autorun_is_not_needed",
     ["src"], "from flow import runlog", ["autorun", "launch", "cases", "prefs"]),
    ("I-07", "flow.runqueue が home・human・manage を読まない(画面なし・③ なしの ②)", "tests/flow/test_runqueue.py test_imports_without_home",
     ["src"], "import flow.runqueue", ["autorun", "cases", "prefs", "deliver", "delivery", "friend_feedback", "manage", "human", "home"]),
    ("I-08", "human.proof.doc_jobs が編集の serve を読まない(口は空のまま = 使う前に serve が登録する)", "tests/human/proof/test_doc_jobs.py test_import_without_serve",
     ["src", "src/editor"], "from human.proof import doc_jobs", ["serve"]),
    ("I-09", "clipjob が flow・human・manage・eval・serve・ed_* を読まない", "tests/pipeline/transcribe/test_clipjob.py test_reads_no_flow_human_or_app",
     ["src"], "from pipeline.transcribe import clipjob", ["flow", "flow.*", "human", "human.*", "manage", "manage.*", "eval", "eval.*", "serve", "ed_*"]),
    ("I-10", "diarize がネイティブ部品・serve・ed_*・eval・human を読まない", "tests/pipeline/transcribe/test_diarize.py test_no_native_app_or_eval",
     ["src"], "from pipeline.transcribe import diarize", list(NATIVE) + ["ed_*", "serve", "eval", "eval.*", "human", "human.*"]),
    ("I-11", "fill・llm がネイティブ部品・serve・ed_*・eval を読まない", "tests/pipeline/transcribe/test_fill_llm.py test_no_native_app_or_eval",
     ["src"], "from pipeline.transcribe import fill, llm", list(NATIVE) + ["ed_*", "serve", "eval", "eval.*"]),
    ("I-12", "文字起こしの部品(postproc・backend・roster・tx_engines・records・worker_client・recognize・diarize・fill・llm・retime・clipjob・replace・txbase)がネイティブ部品・serve・ed_*・eval を読まない",
     "tests/pipeline/transcribe/test_postproc.py test_no_native_app_or_eval", ["src"],
     "from pipeline.transcribe import postproc, backend, roster, tx_engines, records, worker_client, recognize, diarize, fill, llm, retime, clipjob, replace; from ytt import txbase",
     list(NATIVE) + ["ed_*", "serve", "eval", "eval.*"]),
    ("I-13", "backend が serve・ed_state・ed_jobs・eval を読まない(一時の口 txenv は無い)", "tests/pipeline/transcribe/test_txbackend.py test_no_app_or_eval",
     ["src"], "from pipeline.transcribe import backend; import importlib.util as _u; assert not _u.find_spec('pipeline.transcribe.txenv'), 'txenv が復活している'",
     ["serve", "ed_state", "ed_jobs", "eval", "eval.*"]),
    ("I-14", "認識ワーカー(pipeline.transcribe.worker)が import しただけでは serve・ed_*・eval・ネイティブ部品を読まない", "tests/pipeline/transcribe/test_worker_client.py test_import_reads_no_app_eval_or_native",
     ["src"], "import pipeline.transcribe.worker", list(NATIVE) + ["serve", "ed_*", "eval", "eval.*"]),
]


# ---------------------------------------------------------------- 突き合わせ(app)

@check("C-01", "採用の既定(perHour・waitMin・pad)が束 spec.DEFAULTS の 1 か所から読まれる", "(app のテストから移した)")
def c_adopt_defaults():
    from flow import live_detect, spec
    from app import prefs
    a = spec.DEFAULTS["adopt"]
    live = prefs.DEFAULTS["live"]
    pairs = [("prefs live.afterStreamPerHour", live["afterStreamPerHour"], a["perHour"]), ("prefs live.detect.perHour", live["detect"]["perHour"], a["perHour"]),
             ("prefs live.autoAdopt.waitMin", live["autoAdopt"]["waitMin"], a["waitMin"]), ("prefs live.auto.pad", live["auto"]["pad"], a["pad"]),
             ("live_detect DETECT_DEFAULT.perHour", live_detect.DETECT_DEFAULT["perHour"], a["perHour"]),
             ("live_detect ADOPT_DEFAULT.waitMin", live_detect.ADOPT_DEFAULT["waitMin"], a["waitMin"])]
    return ["%s が束の adopt と違う: %r != %r" % p for p in pairs if p[1] != p[2]]


@check("C-02", "配信中の文字起こしの値(版・exe・モデルのファイル名・置き場所)が編集の認識エンジン tx_engines と同じ", "(app のテストから移した)")
def c_live_tx_constants():
    from flow import live_tx as TX
    from app import prefs as P
    from pipeline.transcribe import tx_engines as te
    out = []
    pairs = [("WCPP_VERSION", TX.WCPP_VERSION, te.WHISPER_CPP["version"]), ("WCPP_EXE", TX.WCPP_EXE, te.WCPP_EXE),
             ("WCPP_MODEL_FILES", TX.WCPP_MODEL_FILES, {k: v["file"] for k, v in te.WCPP_MODELS.items()}),
             ("prefs.LIVE_TX_MODELS", P.LIVE_TX_MODELS, tuple(te.WCPP_MODELS)),
             ("既定のモデル", (P.DEFAULTS["live"]["liveTx"]["model"], TX.DEFAULT_MODEL), ("large-v3", "large-v3"))]
    out += ["%s が違う: %r != %r" % p for p in pairs if p[1] != p[2]]
    d = os.path.join(tempfile.gettempdir(), "ytt-livetx-x", "editor")

    class FakeLive:
        root = None

        def cfg(self):
            return {"liveTx": {"model": "large-v3"}}
    tx = TX.LiveTx(FakeLive())
    tx.data_dir = lambda: d
    p = tx.paths()
    if (os.path.dirname(p["exe"]), os.path.basename(p["exe"])) != (te.wcpp_bin_dir(d), te.WCPP_EXE):
        out.append("LiveTx.paths の exe が tx_engines の置き場所と違う: %s" % p["exe"])
    if p["model"] != os.path.join(te.wcpp_model_dir(d), te.WCPP_MODELS["large-v3"]["file"]):
        out.append("LiveTx.paths の model が tx_engines の置き場所と違う: %s" % p["model"])
    return out


@check("C-03", "入口のポート範囲と各ツールの既定ポートが重ならない", "tests/app/test_launch.py test_port_ranges_do_not_overlap_tools")
def c_port_ranges():
    from app import server as L
    portal = set(range(L.DEFAULT_PORT, L.DEFAULT_PORT + L.PORT_RANGE))
    return ["入口のポート範囲とツール %s の既定ポートが重なる" % spec["id"] for spec in L.TOOLS if portal & set(range(spec["port"], spec["port"] + 20))]


@check("C-04", "一つのプロセスに取り込むツール間で同じ名前の部品を作らない", "tests/app/test_mount.py test_tools_do_not_share_module_names")
def c_tool_module_names():
    from app import mount as M
    from ytt import layout
    seen, out = {}, []
    for d in (layout.TOOL_DIRS["studio"], layout.TOOL_DIRS["cut2resolve"], layout.TOOL_DIRS["transcribe"], "app"):
        path = os.path.join(SRC, d)
        if not os.path.isdir(path):
            continue
        for name in sorted(M.tool_modules(path)):
            if name in seen:
                out.append("部品 %s が %s と %s の両方にある" % (name, seen[name], d))
            seen[name] = d
    return out


SCHEMA_TYPES = ("bool", "enum", "int", "number", "text", "folder", "textarea", "link")
NO_UI = {"autorun.mode", "live.recorders", "live.liveTx.model"}   # 画面に出さない鍵(mode は案件ごと・recorders は一覧・liveTx.model は固定)


def schema_shape_problems(sc):
    """設定の画面のスキーマの書き方: 節の id・鍵が重ならない・型/ラベル/選択肢/範囲/既定/when の参照が決まりどおり"""
    out, ids, keys = [], [], []
    all_keys = [x["key"] for s2 in sc["sections"] for g2 in s2.get("groups", []) for x in g2["items"]]
    for sec in sc["sections"]:
        ids.append(sec["id"])
        if not sec.get("title"):
            out.append("節 %s に title が無い" % sec["id"])
        for g in sec.get("groups", []):
            if not (g.get("store") or sec.get("store") or sec.get("kind")):
                out.append("節 %s の組に store が無い" % sec["id"])
            for it in g["items"]:
                k = it["key"]
                keys.append(k)
                if it["type"] not in SCHEMA_TYPES:
                    out.append("%s: 知らない型 %r" % (k, it["type"]))
                if not it.get("label"):
                    out.append("%s: label が無い" % k)
                if it["type"] == "enum":
                    if not it.get("options"):
                        out.append("%s: options が無い" % k)
                    elif it["default"] not in [o[0] for o in it["options"]]:
                        out.append("%s: 既定が選択肢に無い" % k)
                if it["type"] in ("int", "number"):
                    if "min" not in it or "max" not in it:
                        out.append("%s: min/max が無い" % k)
                    elif not it["min"] <= it["default"] <= it["max"]:
                        out.append("%s: 既定が範囲の外" % k)
                if it["type"] == "link" and not it.get("link", {}).get("href"):
                    out.append("%s: link.href が無い" % k)
                if it.get("when") and it["when"]["key"] not in all_keys:
                    out.append("%s: when が知らない鍵 %s を指す" % (k, it["when"]["key"]))
    if len(ids) != len(set(ids)):
        out.append("節の id が重なる")
    if len(keys) != len(set(keys)):
        out.append("鍵が重なる")
    return out


def _leaf(d, parts):
    for p in parts:
        if not isinstance(d, dict) or p not in d:
            return KeyError
        d = d[p]
    return d


def _leaves(d, prefix=""):
    for k, v in d.items():
        if isinstance(v, dict) and v:
            yield from _leaves(v, prefix + k + ".")
        else:
            yield prefix + k


def schema_items(sc, store):
    for sec in sc["sections"]:
        for g in sec.get("groups", []):
            if (g.get("store") or sec.get("store")) == store:
                for it in g["items"]:
                    yield it


def _schema():
    with open(os.path.join(SRC, "app", "ui", "settings", "schema.json"), encoding="utf-8") as f:
        return json.load(f)


@check("C-05", "設定の画面のスキーマ(schema.json)の書き方・prefs の鍵と既定値との一致・全部の鍵が画面に出る(出さない鍵は NO_UI)",
       "tests/app/test_settings_schema.py test_shape・test_keys_exist_and_defaults_match・test_all_leaves_are_in_schema")
def c_settings_schema():
    from app import prefs as PR
    sc = _schema()
    out = schema_shape_problems(sc)
    items = list(schema_items(sc, "home"))
    for it in items:
        parts = it["key"].split(".")
        if parts[0] not in PR.PATCHABLE:
            out.append("%s: prefs の PATCHABLE に無い" % it["key"])
            continue
        d = _leaf(PR.DEFAULTS[parts[0]], parts[1:])
        if d is KeyError:
            out.append("prefs.py に無い鍵: %s" % it["key"])
        elif "default" in it and it["default"] != d:
            out.append("既定値が違う: %s(画面 %r・prefs %r)" % (it["key"], it["default"], d))
    keys = {it["key"] for it in items}
    for sec in {k.split(".")[0] for k in keys}:
        for x in _leaves(PR.DEFAULTS[sec]):
            k = sec + "." + x
            if k not in keys and k not in NO_UI:
                out.append("画面に無い設定(出すか NO_UI に書く): %s" % k)
    return out


@check("C-06", "スタジオの設定の画面: 解析の鍵と画面の項目が過不足なく対応・review の型は決まった 4 種", "tests/studio/test_settings_schema.py test_analyze_covers_all_keys・test_review_items_shape")
def c_studio_schema():
    from pipeline.analyze import analyze
    sc = _schema()
    out = []
    items = [it for it in schema_items(sc, "studio") if it["key"].startswith("analyze.")]
    if not items:
        out.append("studio の analyze の項目が無い")
    keys = {it["key"].split(".", 1)[1] for it in items}
    out += ["画面に無い解析の設定: %s" % k for k in analyze.validate_settings({}) if k not in keys and k not in ("noCache", "fill")]   # noCache は 1 回だけの印・fill は自動の流れが採用の本数を渡す(どちらも保存しない)
    out += ["review の項目 %s の型が決まった 4 種でない: %s" % (it["key"], it["type"]) for it in schema_items(sc, "studio")
            if it["key"].startswith("review.") and it["type"] not in ("bool", "enum", "int", "number")]
    return out


@check("C-07", "入口の題名(PORTAL_TITLE)とホームの画面の title が同じ文字", "tests/app/test_window.py test_portal_title_matches_page")
def c_portal_title():
    from app import server as L
    with open(os.path.join(L.HOME_UI_DIR, "portal.html"), encoding="utf-8") as f:
        return [] if "<title>%s</title>" % L.PORTAL_TITLE in f.read() else ["portal.html の <title> が PORTAL_TITLE(%s)と違う" % L.PORTAL_TITLE]


@check("C-08", "配りの表(STATIC)の案件の画面の行が、実在するファイルを指す", "tests/app/test_cases_page.py test_static_table_points_to_files")
def c_static_table():
    from app import server as L
    return ["STATIC の %s が実在しない: %s" % (url, os.path.join(base, name)) for url, (name, base) in L.STATIC.items()
            if (url.startswith("/cases") or url == "/portal-edit.js") and not os.path.isfile(os.path.join(base, name))]


@check("C-09", "束(flow/spec)の検査の表と既定の鍵の一致・固定の項目は鍵に入れない・autorun は同じ名前を読み直す・既定が各ツールの既定と同じ",
       "tests/flow/test_spec.py test_autorun_still_exposes_the_names・test_defaults_are_valid_and_complete・test_fixed_items_are_not_keys・test_defaults_match_the_tools")
def c_spec_consistency():
    from flow import spec
    from app import autorun as A
    from pipeline.analyze import analyze
    from pipeline.export import exporter
    from pipeline.pack import cut2resolve_core as C, pack, resolve_textplus as TP
    out = []

    def eq(what, a, b):
        if a != b:
            out.append("%s: %r != %r" % (what, a, b))
    for name in ("RANGE_MAX", "CUTS", "TX_ENGINES", "TX_MODEL_RE", "WEIGHT_KEYS", "MAX_MARKS", "DEFAULT_TOP", "LIVE_AUTO_CUT", "clean_ranges", "clean_weights"):
        if getattr(A, name) is not getattr(spec, name):
            out.append("autorun.%s が spec.%s と同じ物でない(転送の名前)" % (name, name))
    if A._top_arg is not spec.top_arg or A._num is not spec.num_ok:
        out.append("autorun._top_arg/_num が spec の物でない")
    if hasattr(A.AutoRunner, "_marks_arg"):
        out.append("受付の欄の検査 _marks_arg が autorun に残っている(置き場所は flow/order.py・envelope)")
    eq("validate(merge(None)) と DEFAULTS", spec.validate(spec.merge(None)), spec.DEFAULTS)
    eq("merge({}) と DEFAULTS", spec.merge({}), spec.DEFAULTS)
    eq("DEFAULTS の節と SECTIONS", tuple(spec.DEFAULTS), spec.SECTIONS)
    eq("SCHEMA の節と SECTIONS", set(spec.SCHEMA), set(spec.SECTIONS))
    for sec in spec.SECTIONS:   # 検査の表と既定値の鍵は同じ(片方だけ増やした食い違いを落とす)
        eq("SCHEMA と DEFAULTS の鍵(%s)" % sec, set(spec.SCHEMA[sec]), set(spec.DEFAULTS[sec]))
    for k in spec.FIXED:
        out += ["固定の項目 %s が既定の鍵 %s に入っている" % (k, sec) for sec in spec.SECTIONS if k in spec.DEFAULTS[sec]]
    eq("FIXED fps", spec.FIXED["fps"], 30)
    if "upto" in spec.FIXED:
        out.append("FIXED に旧い upto がある(どこまで・失敗したときは束の run.upto・run.onFail)")
    eq("run.upto・run.onFail・hints.streamer の既定", (spec.DEFAULTS["run"]["upto"], spec.DEFAULTS["run"]["onFail"], spec.DEFAULTS["hints"]["streamer"]), ("pack", "next", None))
    got = analyze.validate_settings({})
    got.pop("noCache")
    got.pop("fill")   # 埋める数は束に入れない(② の段が採用の上限 adopt.top から渡す)
    if got.pop("shape") not in ("scene", "fixed"):   # 区間の形は束に入れない(既定は ① のスイッチ excite.SHAPE_DEFAULT の 1 か所)
        out.append("analyze の shape の既定が scene/fixed でない")
    eq("束の analyze と analyze の既定", got, spec.DEFAULTS["analyze"])
    eq("束の export.volume と exporter", spec.DEFAULTS["export"]["volume"], exporter.DEFAULT_EXPORT_VOLUME)
    eq("束の pack.cutSilence と cut2resolve_core", spec.DEFAULTS["pack"]["cutSilence"], {"noise": C.DEFAULT_NOISE_DB, "min": C.DEFAULT_SILENCE_MIN, "pad": C.DEFAULT_SILENCE_PAD})
    eq("束の pack.wrapChars と Text+", spec.DEFAULTS["pack"]["wrapChars"], TP.WRAP_DEFAULT)
    eq("束の pack.rowEdge と pack の既定", pack.row_edge_from(spec.DEFAULTS["pack"]["rowEdge"]), pack.row_edge_from(None))
    return out


@check("C-10", "機械の既定の LLM(machine.LLM_MODEL・束の post.llmModel)が llm.py の既定で、登録済みの文章モデル", "tests/flow/test_machine.py test_llm_default_matches_llm_py")
def c_llm_default():
    from flow import machine as M, spec as S
    from pipeline.transcribe import llm, tx_engines
    out = []
    if M.LLM_MODEL != llm.LLM_MODEL:
        out.append("machine.LLM_MODEL(%s)が llm.LLM_MODEL(%s)と違う" % (M.LLM_MODEL, llm.LLM_MODEL))
    if S.DEFAULTS["post"]["llmModel"] != llm.LLM_MODEL:
        out.append("束の post.llmModel が llm.LLM_MODEL と違う")
    if M.LLM_MODEL not in tx_engines.LLAMA_TEXT_MODELS:
        out.append("machine.LLM_MODEL が tx_engines.LLAMA_TEXT_MODELS に無い")
    return out


@check("C-11", "LiveSession が口(LiveHost)の名前を全部持ち、メソッドは口の引数を受けられる", "tests/flow/test_livehost.py test_live_has_every_name")
def c_livehost_names():
    import inspect
    import shutil
    from flow import livehost as H, livesession as LS
    own = vars(H.LiveHost)
    names = set(own.get("__annotations__", {})) | {k for k, v in own.items() if callable(v) and not (k.startswith("__") and k.endswith("__"))}
    out = [] if "_rec_status" in names else ["LiveHost に _rec_status が無い(口の名前を読み損ねている)"]
    tmp = tempfile.mkdtemp(prefix="ytt-rule-livehost-")
    live = None
    try:
        live = LS.LiveSession(tmp, os.path.join(tmp, "logs"), cfg=lambda: {}, log=lambda m: None, spawn=False,
                              store_dir=os.path.join(tmp, "live"), out_dir=lambda: os.path.join(tmp, "out"))
        for name in sorted(names):
            if not (name in vars(live) or hasattr(type(live), name)):
                out.append("LiveSession に口の名前 %s が無い" % name)
                continue
            want = own.get(name)
            got = inspect.getattr_static(live, name, None)
            if not callable(want) or isinstance(got, property) or not callable(got):
                continue
            have = inspect.signature(getattr(live, name)).parameters
            out += ["%s(%s): 口の引数を受けられない" % (name, p) for p in list(inspect.signature(want).parameters)[1:] if p not in have]
    finally:
        if live is not None:
            live.detector.stop()
        shutil.rmtree(tmp, ignore_errors=True)
    return out


def _const(path, name):
    """ソースの最上位の `名前 = 定数の式` を import せずに読む"""
    import ast
    with open(path, encoding="utf-8") as f:
        tree = ast.parse(f.read())
    for node in tree.body:
        if isinstance(node, ast.Assign) and any(isinstance(t, ast.Name) and t.id == name for t in node.targets):
            return eval(compile(ast.Expression(node.value), path, "eval"), {"__builtins__": {}})   # 定数の式(15 * 60 など)だけ
    raise KeyError("%s に %s が無い" % (os.path.basename(path), name))


@check("C-12", "夜の測定の領域の道具が実在し呼び方が受けられる・しきい値(GOALS)が道具の「まだ少ない」の定数と同じ",
       "tests/eval/drill/test_accuracy.py test_every_area_tool_exists・test_goal_thresholds_match_the_tools")
def c_accuracy_areas():
    from eval.drill import accuracy
    from app import prefs as prefs_mod
    from ytt import fsio
    out = []
    tools_dir = os.path.join(SRC, "eval", "tools")
    for a in accuracy.AREAS:
        if not os.path.isfile(os.path.join(tools_dir, a["script"])):
            out.append("%s(領域 %s)が src/eval/tools/ に無い" % (a["script"], a["id"]))
    tmp = tempfile.mkdtemp(prefix="ytt-rule-accuracy-")
    try:
        real = accuracy.Accuracy(prefs_mod.Prefs(os.path.join(tmp, "app", "prefs.json"), fsio.atomic_write), os.path.join(tmp, "app"), SRC)
        out += ["領域 %s の呼び方が作れない" % a["id"] for a in accuracy.AREAS if real.commands(a) is None]
    finally:
        import shutil
        shutil.rmtree(tmp, ignore_errors=True)
    by_args = {a["id"]: a["args"] for a in accuracy.AREAS}
    if by_args["speakers"] != ("run", "--or-stored", "--json"):
        out.append("夜の話者の呼び方が既定(run --or-stored --json)でない: %r" % (by_args["speakers"],))
    if "--apply" not in by_args["timing"]:
        out.append("夜の時刻の呼び方に --apply が無い")
    by = {g["id"]: g["target"] for g in accuracy.GOALS}
    gates = dict(_const(os.path.join(tools_dir, "eval_asr.py"), "GATES"))
    pairs = [("g1", gates["G1"]), ("g2fixed", gates["G2"]), ("speakers", _const(os.path.join(tools_dir, "eval_speakers.py"), "FEW_ROWS")),
             ("marks", _const(os.path.join(tools_dir, "eval_marks.py"), "FEW_VIDEOS")), ("packs", _const(os.path.join(tools_dir, "eval_cut.py"), "FEW_PACKS")),
             ("alt", _const(os.path.join(tools_dir, "eval_alt.py"), "FEW_CANDS")), ("fill", _const(os.path.join(tools_dir, "eval_fill.py"), "FEW_ROWS")),
             ("timing", _const(os.path.join(tools_dir, "eval_timing.py"), "FEW_ROWS"))]
    out += ["しきい値 %s(GOALS %r)が道具の定数 %r と違う" % (gid, by[gid], want) for gid, want in pairs if by[gid] != want]
    if accuracy.TIMING_FEW_ROWS != _const(os.path.join(tools_dir, "eval_timing.py"), "FEW_ROWS"):
        out.append("accuracy.TIMING_FEW_ROWS が eval_timing.FEW_ROWS と違う")
    return out


@check("C-13", "パックの既定(ノイズ・無音・先頭・リール・CRF)が cut2resolve_core の 1 か所・自動カットの SCHEMA が CUT_PLAN_SCHEMA と同じ",
       "tests/pipeline/pack/test_cut2resolve.py test_defaults_agree")
def c_pack_defaults():
    import dataclasses
    import inspect
    from pipeline.pack import cut2resolve_core as C, auto_cut as AC, pack
    out = []
    req = {f.name: f.default for f in dataclasses.fields(pack.Request)}

    def param(fn, name):
        return inspect.signature(fn).parameters[name].default

    def eq(what, a, b):
        if a != b:
            out.append("%s: %r != %r" % (what, a, b))
    eq("Request の既定", (req["noise"], req["silence_min"], req["silence_pad"], req["rec_start"], req["reel"]),
       (C.DEFAULT_NOISE_DB, C.DEFAULT_SILENCE_MIN, C.DEFAULT_SILENCE_PAD, C.DEFAULT_REC_START, C.DEFAULT_REEL))
    eq("detect_silence の既定", [param(C.detect_silence, n) for n in ("noise_db", "min_sec", "pad_sec")], [C.DEFAULT_NOISE_DB, C.DEFAULT_SILENCE_MIN, C.DEFAULT_SILENCE_PAD])
    eq("リール・先頭の既定", (param(C.build_edl, "reel"), param(C.build_edl, "rec_start"), param(C.write_pack, "args_reel"), param(C.write_pack, "rec_start"), param(C.check_timecodes, "rec_start")),
       (C.DEFAULT_REEL, C.DEFAULT_REC_START, C.DEFAULT_REEL, C.DEFAULT_REC_START, C.DEFAULT_REC_START))
    eq("CRF の既定", (param(C.render_rough_cut, "crf"), param(pack.build_pack, "crf")), (C.DEFAULT_CRF, C.DEFAULT_CRF))
    eq("_reel('')", C._reel(""), C.DEFAULT_REEL)
    eq("auto_cut.SCHEMA", AC.SCHEMA, C.CUT_PLAN_SCHEMA)
    return out


@check("C-14", "Text+ の雛形がパックに同梱され、install の書き出しに雛形の名前が入る", "tests/pipeline/pack/test_pack.py test_template_is_bundled")
def c_textplus_template():
    import zipfile
    from pathlib import Path
    from pipeline.pack import resolve_textplus as RTP
    out = []
    template = Path(RTP.__file__).with_name(RTP.TEMPLATE_NAME)
    with zipfile.ZipFile(template) as archive:
        if "project.xml" not in archive.namelist():
            out.append("雛形の zip に project.xml が無い")
    install = RTP.installer_script("test.mov")
    out += ["installer_script に %s が無い" % w for w in ("textplus-template.drb", "__C2R_TEMPLATE_PATH__") if w not in install]
    return out


@check("C-15", "移動・削除・バックアップの一覧(DOC_SUFFIXES)に機械の層・人の層の接尾辞が入る", "tests/human/proof/test_commit.py test_layer_suffixes_go_with_the_doc")
def c_doc_suffixes():
    from ytt import docloc, schemas
    return ["DOC_SUFFIXES に %s が無い" % n for n, v in (("MACH_SUFFIX", schemas.MACH_SUFFIX), ("HUM_SUFFIX", schemas.HUM_SUFFIX)) if v not in docloc.DOC_SUFFIXES]


@check("C-16", "録画元との約束の正規表現・関数(ID_RE・REC_RE・SEG_URI_RE・iso_epoch・epoch_iso・video_id)が ytt.recproto の同じ物(写しを作らない)",
       "tests/pipeline/analyze/test_live_excite_worker.py test_same_objects")
def c_recproto_same_objects():
    from ytt import recproto
    from flow import live_export as LX
    from pipeline.analyze import live_excite_worker as W
    out = []
    for name, w, lx, core in (("ID_RE", W.ID_RE, LX.ID_RE, recproto.RECORDER_ID_RE), ("REC_RE", W.REC_RE, LX.REC_RE, recproto.REC_ID_RE),
                              ("SEG_URI_RE", W.SEG_URI_RE, LX.SEG_URI_RE, recproto.SEG_URI_RE), ("iso_epoch", W.iso_epoch, LX.iso_epoch, recproto.iso_epoch),
                              ("epoch_iso", W.epoch_iso, LX.epoch_iso, recproto.epoch_iso), ("video_id", W.video_id, LX.video_id_of, recproto.video_id_of)):
        if w is not core:
            out.append("live_excite_worker.%s が recproto の物でない(写しがある)" % name)
        if lx is not core:
            out.append("live_export.%s が recproto の物でない(写しがある)" % name)
    return out


@check("C-17", "フォルダの並び(app・studio・editor・cut2resolve)・ツールの場所・serve.py の実在・holo-colors の場所", "tests/ytt/test_ytt_core.py test_tool_dirs")
def c_layout():
    from ytt import layout
    top = REPO
    out = []

    def eq(what, a, b):
        if a != b:
            out.append("%s: %r != %r" % (what, a, b))
    eq("src_root", layout.src_root(), SRC)
    eq("repo_root", layout.repo_root(), top)
    eq("repo_root('/x/src')", layout.repo_root("/x/src"), os.path.dirname(os.path.abspath("/x/src")))
    eq("src のフォルダ名", os.path.basename(SRC), layout.SRC_DIR)
    for tool, name in {"app": "app", "studio": "studio", "transcribe": "editor", "cut2resolve": "cut2resolve"}.items():
        eq("tool_dir(%s)" % tool, layout.tool_dir(tool), os.path.join(SRC, name))
        eq("tool_dir(%s, '/r')" % tool, layout.tool_dir(tool, "/r"), os.path.join("/r", name))
    needs = [os.path.join(layout.src_root(), "ytt", "layout.py"), os.path.join(top, "start.bat"), os.path.join(SRC, "app", "server.py"),
             os.path.join(top, layout.HOLO_COLORS_DIR, "members.json")] + [os.path.join(layout.tool_dir(t), "serve.py") for t in ("studio", "transcribe", "cut2resolve")]
    out += ["実在しない: %s" % p for p in needs if not os.path.isfile(p)]
    eq("holo_colors_dir", layout.holo_colors_dir(), os.path.join(top, "friend-apps", "holo-colors"))
    try:
        layout.tool_dir("clip-studio")   # 識別子はツールの ID(フォルダ名ではない)
        out.append("tool_dir('clip-studio') が KeyError にならない")
    except KeyError:
        pass
    return out


@check("C-18", "名簿(roster.json)の形: 人は組に入る・呼び名は 1 人だけ・地域は組から決めた物と合う・グループ名は人でない", "tests/pipeline/transcribe/test_roster.py test_members_are_in_groups・test_member_regions_follow_groups")
def c_roster_file():
    from pipeline.transcribe import roster as R
    path = os.path.join(SRC, "pipeline", "transcribe", "hololive-roster.json")
    sys.path.insert(0, HERE)
    import rule_checks
    with open(path, encoding="utf-8") as f:
        out = rule_checks.roster_problems(json.load(f), R.GROUP_REGION, R.REGIONS)
    r = R.load(path)
    if len(r["members"]) < 50:
        out.append("R.load が名簿を読めていない(%d 人)" % len(r["members"]))
    if "ホロライブ" in r["people"]:
        out.append("グループ名が people に入っている")
    if R.channel_regions(path).get("UCp6993wxpyDPHUpavwDFqgg") != "JP":
        out.append("ときのそらのチャンネルの地域が JP でない")
    if R.channel_regions(os.path.join(os.path.dirname(path), "no-such-roster.json")) != {}:
        out.append("読めない名簿のとき channel_regions が空でない")
    return out


# ---------------------------------------------------------------- 突き合わせ(ツール別)

@check("C-19", "cut2resolve の作業フォルダ名が ytt.schemas.WORK_DIR と同じ(コマンドは ytt を読まない写しを持つ)", "tests/cut2resolve/test_serve.py test_work_dir_matches_ytt_core", "c2r")
def c_c2r_work_dir():
    import serve
    from ytt import schemas as ys
    return [] if serve.C.WORK_DIR == ys.WORK_DIR else ["cut2resolve の WORK_DIR(%r)が ytt.schemas.WORK_DIR(%r)と違う" % (serve.C.WORK_DIR, ys.WORK_DIR)]


@check("C-20", "編集のツールの識別子(APP_ID)と案件の書き出しの名前が ytt.runtime の表(TOOL_APPS)と同じ", "tests/editor/test_edit.py test_same_as_runtime_table", "editor")
def c_editor_identity():
    import serve as S
    from ytt import runtime
    from manage.cases import handoff_io
    out = []
    if S.APP_ID != runtime.TOOL_APPS["transcribe"]:
        out.append("編集の serve.APP_ID が runtime.TOOL_APPS['transcribe'] と違う")
    if handoff_io.TOOL_NAME != runtime.TOOL_APPS["transcribe"]:
        out.append("handoff_io.TOOL_NAME が runtime.TOOL_APPS['transcribe'] と違う")
    return out


@check("C-21", "スタジオのツールの識別子(APP_ID・server_version・書き出しの tool)が ytt.runtime の表(TOOL_APPS)と同じ", "tests/studio/test_handoff.py test_same_as_runtime_table", "studio")
def c_studio_identity():
    import startup  # noqa: F401  (src を sys.path に足し、スタジオのフォルダを ytt/studio_env に知らせる)
    import serve
    from pipeline.export import exporter
    from ytt import runtime
    want = runtime.TOOL_APPS["studio"]
    pairs = [("serve.APP_ID", serve.APP_ID), ("Handler.server_version", serve.Handler.server_version), ("exporter.TOOL['name']", exporter.TOOL["name"])]
    return ["スタジオの %s(%r)が runtime.TOOL_APPS['studio'](%r)と違う" % (n, v, want) for n, v in pairs if v != want]


# ---------------------------------------------------------------- 友人に配る zip の決まり(dev/build_friend_zip.py)

@check("C-22", "友人に配る zip: 名簿・鍵・出力先の既定の置き場所が決まった場所・必須の src が git の追跡に入る・yt-dlp は公式の版で固定・本物の src に個人データが無い・wheel の版の読み方",
       "tests/dev/test_build_friend_zip.py test_default_members_and_key_sources・test_required_src_is_tracked・test_ytdlp_pinned_to_official_hash・test_real_src_is_clean・test_pins_from_requirements", "dev")
def c_build_friend_zip():
    import re
    import shutil
    import build_friend_zip as B
    out = []
    norm = lambda p: p.replace("\\", "/")   # noqa: E731
    if not norm(B.MEMBERS_SRC).endswith("friend-apps/holo-colors/members.json") or not os.path.isfile(B.MEMBERS_SRC):
        out.append("MEMBERS_SRC が friend-apps/holo-colors/members.json でないか実在しない")
    if not norm(B.KEY_SRC).endswith("friend-apps/launcher/config.json"):
        out.append("KEY_SRC が friend-apps/launcher/config.json でない")
    if not norm(B.default_out(True)).endswith("friend-apps/launcher/dist"):
        out.append("default_out(first) が friend-apps/launcher/dist でない")
    try:
        B.check_src()   # 新しいアプリの必須の物(REQUIRED_SRC)が git に入っている
    except B.BuildError as e:
        out.append(str(e))
    if not set(B.REQUIRED_SRC) <= set(B.src_files()):
        out.append("REQUIRED_SRC が src_files() に全部入っていない")
    if any("FriendInbox" in n for n in B.REQUIRED_SRC):
        out.append("REQUIRED_SRC に旧い FriendInbox がある")
    import ast
    for f in B.src_files():   # zip に入れる層(許可リスト)は、zip に入れない層を読まない
        if not f.endswith(".py"):
            continue
        with open(os.path.join(B.REPO, *f.split("/")), encoding="utf-8") as fh:
            tree = ast.parse(fh.read())
        for n in ast.walk(tree):
            mods = [a.name for a in n.names] if isinstance(n, ast.Import) else [n.module] if isinstance(n, ast.ImportFrom) and n.module and not n.level else []
            for m in mods:
                top = m.split(".")[0]
                if top in ("app", "cut2resolve", "editor", "eval", "human", "manage", "studio"):
                    out.append("%s:%d が zip に入れない層 %s を読む" % (f, n.lineno, m))
    t = next((t for t in B.TOOLS if t["name"] == "yt-dlp"), None)
    if t is None:
        out.append("TOOLS に yt-dlp が無い")
    else:
        if not re.search(r"/releases/download/\d{4}\.\d{2}\.\d{2}/yt-dlp\.exe$", t["url"]):
            out.append("yt-dlp の URL が公式の版の形でない: %s" % t["url"])
        if not re.search(r"^[0-9a-f]{64}$", t["sha256"]):
            out.append("yt-dlp の sha256 の形が違う")
        if not t["size"] > 1000000:
            out.append("yt-dlp の size が小さすぎる")
    stage = tempfile.mkdtemp(prefix="ytt-rule-zip-")
    try:
        B.lay_src(stage)
        out += ["本物の src の中: %s" % x for x in B.audit(stage, False)]
    finally:
        shutil.rmtree(stage, ignore_errors=True)
    pins = B.wheel_pins()
    if [p.split("==")[0] for p in pins] != list(B.WHEEL_NAMES) or not all("==" in p for p in pins):
        out.append("wheel_pins が WHEEL_NAMES の順の 名前==版 でない: %r" % (pins,))
    return out


# ---------------------------------------------------------------- 流す

def pattern_match(name, patterns):
    return any(fnmatch.fnmatchcase(name, p) for p in patterns)


def forbidden_loaded(modules, patterns):
    """読み込まれたモジュール名のうち patterns(fnmatch)に当たる物"""
    return sorted(m for m in modules if pattern_match(m, patterns))


def child_group(group):
    """子プロセスの中: グループの突き合わせを全部流す -> {番号: [問題]}"""
    out = {}
    for rid, _t, _m, g, fn in CHECKS:
        if g != group:
            continue
        try:
            out[rid] = fn()
        except Exception as e:   # 規則の側の不具合も止める(黙って通さない)
            out[rid] = ["規則が動かない: %s: %s" % (type(e).__name__, e)]
    return out


def child_isolation(rid):
    """子プロセスの中: import して、読み込まれてはいけない名前を調べる"""
    for row in ISOLATION:
        if row[0] == rid:
            _id, _t, _m, _paths, code, forbidden = row
            try:
                exec(code, {})
            except Exception as e:
                return {rid: ["読み込めない: %s: %s" % (type(e).__name__, e)]}
            bad = forbidden_loaded(list(sys.modules), forbidden)
            return {rid: ["読み込んではいけない %s を読んでいる" % ", ".join(bad)] if bad else []}
    return {rid: ["知らない番号"]}


def child_main(argv):
    kind, name = argv[0], argv[1]
    paths = GROUPS[name] if kind == "--group" else next(r[3] for r in ISOLATION if r[0] == name)
    sys.path[:0] = [os.path.join(REPO, *p.split("/")) for p in paths if p != "src"]
    if "src" in paths:
        (sys.path.insert if paths[0] == "src" else sys.path.append)(*((0, SRC) if paths[0] == "src" else (SRC,)))
    result = child_group(name) if kind == "--group" else child_isolation(name)
    sys.stdout.write("\n" + MARK + json.dumps(result, ensure_ascii=False) + "\n")
    return 0


def run_job(job):
    kind, name = job
    env = dict(os.environ, PYTHONDONTWRITEBYTECODE="1", PYTHONIOENCODING="utf-8")
    tmp = tempfile.mkdtemp(prefix="ytt-rule-data-")
    env.update(YTT_DATA_DIR=tmp, YTT_RUNTIME_DIR=os.path.join(tmp, ".runtime"))
    try:
        p = subprocess.run([sys.executable, "-X", "utf8", os.path.abspath(__file__), "--child", kind, name], capture_output=True, timeout=300, env=env, creationflags=NOWIN, cwd=tmp)
    except subprocess.TimeoutExpired:
        return {(name if kind == "--group" else name): ["子プロセスが 300 秒で終わらない"]}
    finally:
        import shutil
        shutil.rmtree(tmp, ignore_errors=True)
    text = p.stdout.decode("utf-8", "replace")
    for line in reversed(text.splitlines()):
        if line.startswith(MARK):
            return json.loads(line[len(MARK):])
    ids = [r[0] for r in CHECKS if r[3] == name] if kind == "--group" else [name]
    return {i: ["子プロセスが結果を出さない(終了 %s): %s" % (p.returncode, p.stderr.decode("utf-8", "replace").strip()[-300:])] for i in ids}


def run(repo=REPO, only=None):
    """突き合わせと切り離しを全部流す -> [(番号, 問題)]。子プロセスは並べて流す"""
    jobs = [("--group", g) for g in GROUPS if any(r[3] == g and (not only or r[0] in only) for r in CHECKS)]
    jobs += [("--iso", r[0]) for r in ISOLATION if not only or r[0] in only]
    found = []
    with ThreadPoolExecutor(max_workers=min(8, max(1, os.cpu_count() or 4))) as ex:
        for res in ex.map(run_job, jobs):
            for rid, problems in res.items():
                if not only or rid in only:
                    found += [(rid, p) for p in problems]
    return sorted(found)


def main(argv=None):
    argv = list(sys.argv[1:] if argv is None else argv)
    if argv[:1] == ["--child"]:
        return child_main(argv[1:])
    try:
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    except Exception:
        pass
    if "--list" in argv:
        for rid, title, moved, _g, _fn in CHECKS:
            print("%s  %s  <- %s" % (rid, title, moved))
        for rid, title, moved, *_ in ISOLATION:
            print("%s  %s  <- %s" % (rid, title, moved))
        return 0
    found = run()
    for rid, p in found:
        print("%s  %s" % (rid, p))
    print("合計 %d 件(0 で合格)" % len(found))
    return 1 if found else 0


if __name__ == "__main__":
    sys.exit(main())
