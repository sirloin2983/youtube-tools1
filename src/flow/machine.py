# -*- coding: utf-8 -*-
"""② 管理の層 flow: この PC の設定(機械の都合)を 1 か所に(役割で組み直す RS7-1 の S1。決定 3-30 の Q1・plan/f1-friend-pc.md の決めたこと 8・9)。

束(flow/spec.py)は「何を作るか」。ここは「この PC でどう動かすか」= 束に入れない機械の都合:
  engine       文字起こしのエンジン(spec.TX_ENGINES = whisper.cpp だけ。0.58.0。旧い faster-whisper などは読むときに whisper.cpp)
  device       認識の機器(spec.TX_DEVICES = vulkan だけ。0.58.0。旧い auto・cuda・cpu は読むときに vulkan)
  llmModel     LLM の後処理のモデル(pipeline/transcribe/tx_engines の LLAMA_TEXT_MODELS の名前)
  caseRoot     案件の根(書き出し先 = 今はスタジオの outDir)
  diskMinGB    空き容量の下限(GB。下回ったら新しい録画と処理を始めない = F1 の決めたこと 7。読むのは後の段)
  learningDir  学習データの場所(既定 = 作業データの根 = 今の場所。データは動かさない。決定 3-30 の Q3)
  docMove      入口の起動のときに文字起こしの文書を案件の 作業用 へ自動で移すか(真偽。既定 false = 移さない。RS8 B2-3 の
               manage/cases/docmove。移す規則をユーザーが見てからオンにするスイッチ。コマンドの --now・--back は関係なく使える)

読む順の強さ: 引数 > 環境変数(ENV)> ファイル(作業データの根の machine.json)> 既定(DEFAULT の説明)。
  既定 = 今の値: engine・device は編集の設定 settings.json(ytt/settings・workdata.SETTINGS)の device とそこから決まるエンジン・
  llmModel = qwen3-8b(llm.py の LLM_MODEL と同じ。test_machine が確かめる)・caseRoot = スタジオの outDir(datadir.studio_out_dir)・
  diskMinGB = 20・learningDir = 作業データの根・docMove = false。
  machine.json が無ければ読むときに既定から組む(書くのは save を呼んだときだけ)。ファイル・環境変数の合わない値は使わずに次の層へ(ログに 1 行)。
  置き場所: 環境変数 YTT_MACHINE_FILE があればそれ。無ければ作業データの根(datadir.data_root。YTT_DATA_DIR=inplace のときは src = 各ツールのフォルダの親)。

束に重ねる overlay(束): 受けた束の transcribe.engine・device と post.llmModel を、この PC の設定で上書きした新しい束を返す(F1 の決めたこと 9 =
  処理する PC の ② が自分の機械の設定を重ねて流す)。**重ねるのは引数・環境変数・ファイルで決めた値だけ**(既定から来た値は重ねない =
  machine.json も環境変数も無い今の PC では束・鍵・要求の本文が今と同じ。一時の形: 編集の ⚙ のエンジン・デバイスがここへ書くようになったら(S6b)
  ファイルの値として重なる)。device だけを決めたときは、束のエンジンが機器から決まるエンジン(spec.implied_engine)だったときだけエンジンも合わせる。

環境変数の整理(S1): 機械の都合の物は下の ENV(device は YTT_MACHINE_DEVICE だけ。旧い名前 TRANSCRIBE_DEVICE は ② では読まない)。
  ① の認識ワーカー(worker_client)は要求の本文の機器を先にする(本文が auto のときだけ TRANSCRIBE_DEVICE を見る = ② を通らない呼び出しの互換)。
  ① の調整の環境変数(TRANSCRIBE_CUDA_COMPUTE・TRANSCRIBE_CPU_THREADS・TRANSCRIBE_LLAMA_THREADS・TRANSCRIBE_DIAR_THREADS・TRANSCRIBE_ENGINE_DIR・
  TRANSCRIBE_MODEL_IDLE_SEC・TRANSCRIBE_WORKER_PRIORITY)は machine の項目ではない(認識ワーカーのプロセスが自分で読む。今のまま)。
  テスト・疑似の旗(TRANSCRIBE_BACKEND・TRANSCRIBE_FAKE_* など)は触らない。
  TRANSCRIBE_SPLIT_CHARS(行を分ける文字数)は「何を作るか」= 束の post.splitChars の側なので machine に入れない。入口の束は splitChars を
  いつも要求に入れる(S2)ので、入口からの流れでは効かず、編集の画面から始めた文字起こしでだけ効く開発用の旗として残す(一時の形。RS7-1 S1)。
標準ライブラリ・ytt・flow/spec だけを読む(入口のプロセスで pipeline/transcribe を読まない = live_tx と同じ)。
"""
import copy
import logging
import os

from ytt import datadir as _datadir, layout as _layout, settings as _settings, workdata as _workdata
from . import spec as _spec

log = logging.getLogger("ytt.flow.machine")

FILE_NAME = "machine.json"
SCHEMA = "youtube-tools-machine/v1"
FILE_ENV = "YTT_MACHINE_FILE"            # machine.json の場所を直に決める(テスト・別の置き場所)
FILE_MAX = 64 * 1024
FIELDS = ("engine", "device", "llmModel", "caseRoot", "diskMinGB", "learningDir", "docMove")
DEVICES = _spec.TX_DEVICES               # spec.SCHEMA の transcribe.device と同じ(旧い値は check が spec.read_legacy_tx で読み替える)
LLM_MODEL = "qwen3-8b"                   # pipeline/transcribe/llm.py の LLM_MODEL(入口のプロセスで llm を読まないので値を持つ。test_machine が同じことを確かめる)
DISK_MIN_GB = 20
DISK_MAX_GB = 100000
# 項目 -> 環境変数の名前(前にある物が先)
ENV = {"engine": ("YTT_MACHINE_ENGINE",),
       "device": ("YTT_MACHINE_DEVICE",),
       "llmModel": ("YTT_MACHINE_LLM_MODEL",),
       "caseRoot": ("YTT_MACHINE_CASE_ROOT",),
       "diskMinGB": ("YTT_MACHINE_DISK_MIN_GB",),
       "learningDir": ("YTT_MACHINE_LEARNING_DIR",),
       "docMove": ("YTT_MACHINE_DOC_MOVE",)}
BOOL_WORDS = {"1": True, "true": True, "yes": True, "on": True, "0": False, "false": False, "no": False, "off": False}   # 環境変数の真偽の書き方
SOURCES = ("arg", "env", "file", "default")


# ---------- 値の検査 ----------
def check(field, value):
    """1 項目の値を確かめる -> 整えた値。合わなければ理由つきの ValueError(知らない項目も)。
    engine・device の旧い値(0.57.0 までの faster-whisper・auto・cpu など)は断らずに今の値へ読み替える(spec.read_legacy_tx = 束と同じ決まり)"""
    if field in ("engine", "device"):
        value = _spec.read_legacy_tx(field, value)
    if field == "engine":
        if value in _spec.TX_ENGINES and isinstance(value, str):
            return value
        raise ValueError("engine は %s のどれかにしてください" % "・".join(_spec.TX_ENGINES))
    if field == "device":
        if value in DEVICES and isinstance(value, str):
            return value
        raise ValueError("device は %s のどれかにしてください" % "・".join(DEVICES))
    if field == "llmModel":
        if isinstance(value, str) and _spec.TX_MODEL_RE.match(value):
            return value
        raise ValueError("llmModel は英数字と . _ - の 60 字までの名前にしてください")
    if field in ("caseRoot", "learningDir"):
        if isinstance(value, str) and value.strip() and len(value) <= 1000 and os.path.isabs(value.strip()):
            return os.path.normpath(value.strip())
        raise ValueError("%s は絶対パスにしてください" % field)
    if field == "diskMinGB":
        if isinstance(value, str):
            try:
                value = float(value.strip())
            except ValueError:
                raise ValueError("diskMinGB は 0〜%d の数(GB)にしてください" % DISK_MAX_GB)
        if _spec.num_ok(value) and 0 <= value <= DISK_MAX_GB:
            return int(value) if float(value).is_integer() else round(float(value), 1)
        raise ValueError("diskMinGB は 0〜%d の数(GB)にしてください" % DISK_MAX_GB)
    if field == "docMove":
        if isinstance(value, str) and value.strip().lower() in BOOL_WORDS:
            return BOOL_WORDS[value.strip().lower()]
        if isinstance(value, bool):
            return value
        raise ValueError("docMove は true か false にしてください")
    raise ValueError("知らない項目です: %s(使えるのは %s)" % (field, "・".join(FIELDS)))


# ---------- 置き場所 ----------
def root(env=None):
    """作業データの根(datadir.data_root。inplace なら src = 各ツールのフォルダの親)"""
    return _datadir.data_root(env) or _layout.src_root()


def path(env=None):
    """machine.json の場所(環境変数 YTT_MACHINE_FILE → 作業データの根)"""
    env = os.environ if env is None else env
    p = (env.get(FILE_ENV) or "").strip()
    return os.path.abspath(p) if p else os.path.join(root(env), FILE_NAME)


def _file(p):
    return _settings.SettingsFile(p, max_bytes=FILE_MAX, indent=1)


# ---------- 層ごとの値 ----------
def read_file(p=None, env=None):
    """machine.json の使える項目だけ -> {項目: 値}(無い・壊れている = {}。合わない値・知らない項目は使わない = ログに 1 行)"""
    p = p or path(env)
    d, broken = _file(p).load()
    if broken:
        log.warning("この PC の設定(%s)を読めないので既定で動きます", p)
    out = {}
    for k, v in d.items():
        if k == "schema":
            continue
        try:
            out[k] = check(k, v)
        except ValueError as e:
            log.warning("この PC の設定(%s)の %s を使いません: %s", p, k, e)
    return out


def read_env(env=None):
    """環境変数の使える項目だけ -> {項目: 値}(合わない値は使わない = ログに 1 行)"""
    env = os.environ if env is None else env
    out = {}
    for field, names in ENV.items():
        for name in names:
            raw = (env.get(name) or "").strip()
            if not raw:
                continue
            try:
                out[field] = check(field, raw)
                break
            except ValueError as e:
                log.warning("環境変数 %s を使いません: %s", name, e)
    return out


def _editor_device():
    """編集の設定 settings.json の device(旧い auto・cuda・cpu は vulkan に読む。無い・合わなければ vulkan = 0.58.0 から選べるのは GPU だけ)。
    置き場所は workdata.SETTINGS(呼ぶたびに読む)、まだ決まっていなければ(入口の外)編集の作業データの settings.json"""
    p = _workdata.SETTINGS or os.path.join(_datadir.resolve("transcribe"), "settings.json")
    v = _spec.read_legacy_tx("device", _settings.SettingsFile(p).read().get("device"))
    return v if v in DEVICES and isinstance(v, str) else DEVICES[0]


def _default(field, have, env):
    """既定 = 今の値(have = 上の層で決まった値。engine は device から決める)"""
    if field == "device":
        return _editor_device()
    if field == "engine":
        return _spec.implied_engine(have["device"])
    if field == "llmModel":
        return LLM_MODEL
    if field == "caseRoot":
        return _datadir.studio_out_dir(env=None if env is os.environ else env)
    if field == "diskMinGB":
        return DISK_MIN_GB
    if field == "docMove":
        return False
    return root(env)   # learningDir


def _layers(args, env, p):
    if args:
        bad = [k for k in args if k not in FIELDS]
        if bad:
            raise ValueError("知らない項目です: %s(使えるのは %s)" % ("・".join(map(str, bad)), "・".join(FIELDS)))
    a = {k: check(k, v) for k, v in (args or {}).items() if v is not None}
    return a, read_env(env), read_file(p, env)


def explicit(args=None, env=None, p=None):
    """引数・環境変数・ファイルで決めた項目だけ -> {項目: 値}(既定から来た値は入れない。overlay が重ねる物)"""
    a, e, f = _layers(args, env, p)
    out = dict(f)
    out.update(e)
    out.update(a)
    return out


def load(args=None, env=None, p=None):
    """この PC の設定 -> {engine, device, llmModel, caseRoot, diskMinGB, learningDir, "sources": {項目: arg | env | file | default}}。
    args = {項目: 値}(None の値は無いのと同じ。合わない値・知らない項目は ValueError)"""
    env = os.environ if env is None else env
    a, e, f = _layers(args, env, p)
    out, src = {}, {}
    for field in ("device",) + tuple(x for x in FIELDS if x != "device"):   # engine の既定は device から決めるので device を先に
        for name, layer in (("arg", a), ("env", e), ("file", f)):
            if field in layer:
                out[field], src[field] = layer[field], name
                break
        else:
            out[field], src[field] = _default(field, out, env), "default"
    res = {k: out[k] for k in FIELDS}
    res["sources"] = {k: src[k] for k in FIELDS}
    return res


def get(field, args=None, env=None, p=None):
    """1 項目の今の値(load と同じ読む順)"""
    if field not in FIELDS:
        raise ValueError("知らない項目です: %s" % field)
    return load(args, env, p)[field]


# ---------- 書く ----------
def save(patch, p=None, env=None):
    """machine.json に patch({項目: 値}。None = その項目を消して既定へ)を重ねて原子的に書く(ytt/settings の SettingsFile)。
    -> 書いたあとのファイルの中身。値が合わない・知らない項目は ValueError(ファイルは変えない)"""
    if not isinstance(patch, dict):
        raise ValueError("この PC の設定は {項目: 値} の形にしてください")
    clean = {}
    for k, v in patch.items():
        if k not in FIELDS:
            raise ValueError("知らない項目です: %s(使えるのは %s)" % (k, "・".join(FIELDS)))
        clean[k] = None if v is None else check(k, v)
    sf = _file(p or path(env))

    def put(d):
        for k in list(d):   # 合わない値・知らない項目は書き直すときに落とす(読むときも使っていない)
            if k != "schema" and (k not in FIELDS or not _ok(k, d[k])):
                d.pop(k)
        for k, v in clean.items():
            if v is None:
                d.pop(k, None)
            else:
                d[k] = v
        d["schema"] = SCHEMA
        return dict(d)
    return sf.update(put)


def _ok(field, value):
    try:
        check(field, value)
        return True
    except ValueError:
        return False


# ---------- 束に重ねる ----------
def overlay(bundle, args=None, env=None, p=None):
    """受けた束(flow/spec.py の束)に、この PC の設定(引数・環境変数・ファイルで決めた値だけ)を重ねた新しい束を返す。
    重ねるのは transcribe.engine・transcribe.device・post.llmModel。束は検査しない(呼ぶ側の検査済みの束に、検査済みの値を入れるだけ)"""
    out = copy.deepcopy(bundle)
    m = explicit(args, env, p)
    t = out.get("transcribe")
    if isinstance(t, dict):
        if "device" in m:
            derived = t.get("engine") == _spec.implied_engine(t.get("device"))   # 束のエンジンが機器から決まっていた(入口の束の作り方)
            t["device"] = m["device"]
            if "engine" not in m and derived:
                t["engine"] = _spec.implied_engine(m["device"])
        if "engine" in m:
            t["engine"] = m["engine"]
    if "llmModel" in m and isinstance(out.get("post"), dict):
        out["post"]["llmModel"] = m["llmModel"]
    return out
