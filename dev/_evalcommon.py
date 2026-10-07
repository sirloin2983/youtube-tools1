"""dev/ の測る道具(eval_asr.py・eval_speakers.py・eval_timing.py・eval_cut.py・eval_alt.py・eval_effort.py・eval_marks.py)の共通の部品
(2026-10-07 ③ dev の見直しでまとめ、見直しの 2 周目で eval_asr・eval_speakers・eval_timing も使うようにした)。

- 置き場所: TOP(リポジトリ直下 = git)・REPO(src = ツールと ytt_core)・EDITOR(src/editor)。読み込むと REPO を sys.path に足す
- 作業データの場所(ytt_core.datadir の 1 か所。--data-dir は全ツールの作業データの親フォルダ = テスト用)・JSON の読み方・
  時期(--since / --until)・率と分布・git の rev・結果の保存(<ツールの作業データ>/evals/<領域>/<日時>.json。
  入口の src/home/accuracy.py が、道具の最後の行「保存: <パス>」と名前の形 <日時>.json で読む = 形を変えない)
- editor の部品をこのプロセスの中で使うときの読み込み(load_serve。eval_asr・eval_speakers・eval_timing・eval_effort・eval_alt)
"""
import atexit
import datetime
import importlib.util
import json
import os
import shutil
import subprocess
import sys
import tempfile
import time

HERE = os.path.dirname(os.path.abspath(__file__))
TOP = os.path.dirname(HERE)      # リポジトリ直下(git)
REPO = os.path.join(TOP, "src")   # ツールと ytt_core の置き場所
EDITOR = os.path.join(REPO, "editor")
if REPO not in sys.path:
    sys.path.insert(0, REPO)
from ytt_core import datadir  # noqa: E402


# ---------------------------------------------------------------- 読み込み(読むだけ)

def read_json(path, default=None, limit=None):
    """JSON のファイル(BOM があってもよい)。読めない・壊れている・limit バイトより大きいときは default"""
    try:
        if limit and os.path.getsize(path) > limit:
            return default
        with open(path, "r", encoding="utf-8-sig") as f:
            return json.load(f)
    except (OSError, ValueError):
        return default


def data_env(data_dir, base=None):
    """--data-dir(全ツールの作業データの親フォルダ。テスト用)-> datadir に渡す環境変数。指定が無ければ base(None = 今の環境変数)"""
    return {"YTT_DATA_DIR": os.path.abspath(data_dir)} if data_dir else base


def locate(tool, data_dir=None, base=None):
    """-> ツール(transcribe・studio・app)の作業データのフォルダ。置き場所の規則は ytt_core.datadir の 1 か所"""
    return datadir.locate(tool, REPO, data_env(data_dir, base))


# ---------------------------------------------------------------- 時期(原則 4: 時期で分ける)

def day_ms(s, end=False):
    """YYYY-MM-DD(この PC の時刻)-> その日の始まり(end=True なら次の日の始まり)のミリ秒"""
    try:
        d = datetime.datetime.strptime(s, "%Y-%m-%d")
    except (TypeError, ValueError):
        raise SystemExit("日付は YYYY-MM-DD で指定してください: %r" % s)
    if end:
        d += datetime.timedelta(days=1)
    return int(time.mktime(d.timetuple()) * 1000)


def period(since, until):
    """--since / --until -> (since のミリ秒か None, until の次の日の始まりのミリ秒か None)。until はその日を含む"""
    return (day_ms(since) if since else None), (day_ms(until, end=True) if until else None)


def in_period(t, since_ms, until_ms, unknown=True):
    """時刻 t(ミリ秒)が時期の中か。時期の指定が無ければいつも True。t が分からない(None)ときは unknown"""
    if since_ms is None and until_ms is None:
        return True
    if t is None:
        return unknown
    return (since_ms is None or t >= since_ms) and (until_ms is None or t < until_ms)


def period_label(since, until):
    return "%s 〜 %s" % (since or "最初", until or "今") if (since or until) else "全期間"


# ---------------------------------------------------------------- 数の小道具

def rate(c, n):
    return round(c / n, 4) if n else None


def pct(x, width=4):
    """割合の表示(width = 数字の幅。0 なら詰める)。None は「  -  」"""
    return "  -  " if x is None else "%*.0f%%" % (width, x * 100)


def dist(values, digits=3, p90=False):
    """数のそろいの分布 -> {"n", "min", "p25", "median", "p75"(, "p90"), "max", "mean"}(digits 桁に丸める。空なら n だけ)"""
    v = sorted(x for x in values if x is not None)
    if not v:
        return {"n": 0}

    def q(p):
        k = (len(v) - 1) * p
        lo = int(k)
        hi = min(lo + 1, len(v) - 1)
        return round(v[lo] + (v[hi] - v[lo]) * (k - lo), digits)
    out = {"n": len(v), "min": round(v[0], digits), "p25": q(0.25), "median": q(0.5), "p75": q(0.75)}
    if p90:
        out["p90"] = q(0.9)
    out.update(max=round(v[-1], digits), mean=round(sum(v) / len(v), digits))
    return out


# ---------------------------------------------------------------- 記録・保存

def git_rev(dirty=None):
    """今のコードの版(git の短い rev。分からなければ空)。dirty = リポジトリ直下からのフォルダ(例 src/editor)。
    そこに未コミットの変更があれば「+変更あり」を付ける(eval_asr。測った editor がコミットした版と違うことを残す)"""
    try:
        rev = subprocess.run(["git", "-C", TOP, "rev-parse", "--short", "HEAD"], capture_output=True, text=True, timeout=10).stdout.strip()
        if dirty and subprocess.run(["git", "-C", TOP, "status", "--porcelain", "--", dirty], capture_output=True, text=True, timeout=10).stdout.strip():
            rev += "+変更あり"
        return rev
    except (OSError, subprocess.SubprocessError):
        return ""


def save(res, root, area, suffix="", out=None):
    """結果を <root>/evals/<area>/<日時><suffix>.json に残す(書きかけを残さない)-> パス。
    suffix = 名前の後ろ(eval_asr = "_<名前>"・eval_speakers の run = "-run")。out = 作業データではなくそのファイルに書く(eval_timing --out)"""
    if out:
        path = os.path.abspath(out)
        os.makedirs(os.path.dirname(path) or ".", exist_ok=True)
    else:
        d = os.path.join(root, "evals", area)
        os.makedirs(d, exist_ok=True)
        path = os.path.join(d, "%s%s.json" % (datetime.datetime.now().strftime("%Y%m%d-%H%M%S"), suffix))
    tmp = path + ".tmp"
    with open(tmp, "w", encoding="utf-8") as f:
        json.dump(res, f, ensure_ascii=False, indent=1)
    os.replace(tmp, path)
    return path


def utf8_stdout():
    """Windows のコンソールでも日本語の表を出せるように(できなければそのまま)"""
    try:
        sys.stdout.reconfigure(encoding="utf-8")
    except (AttributeError, ValueError):
        pass


# ---------------------------------------------------------------- editor の部品を読む(採点・認識・判別をこのプロセスの中で)

SERVE_NAME = "tx_serve_for_eval"   # sys.modules に登録する名前(普通の import の serve とは別の名前)


def load_serve(backend=None, prefix="eval_asr_", keep_env=True):
    """src/editor/serve.py を読み込む(サーバーは起動しない)-> serve。名前は serve の名前の受付で、分けた部品(ed_jobs・ed_state など)の名前も読める。
    - **sys.modules に登録してから読む**: serve の「S.名前 = …」は、登録して読んだときだけ持ち主の部品へ転送される(serve.py の _ServeModule)。
      2026-10-07 まで eval_asr.py は登録せずに読んでいたので、下の IN_WORKER・STUDIO_DATA と、道具やテストが「S.QUANT_ON = …」のように
      差し替えた値が部品に届いていなかった(serve の上に同じ名前ができるだけ。eval_asr.py の先頭の説明)
    - 認識・判別はこのプロセスの中で動かす(IN_WORKER。認識ワーカーを起動しない。GPU の部品の場所はワーカーと同じに整える)
    - スタジオの data.json は、起動したツールと同じ決め方(studio_data_path。--context auto がスタジオの配信のチャンネル名・コラボ相手を読む)
    - serve 自身の作業データ(TRANSCRIBE_DATA_DIR)は一時フォルダ <prefix>…(本物の作業データの横に何も書かない。本物は道具が自分で読む)。
      一時フォルダはこのプロセスの終わりに消す。keep_env = True なら環境変数は一時フォルダを指したまま(eval_timing・eval_effort はそれを見て先に消す)/
      False なら読み込んだあと元に戻す(このあとの datadir.locate が一時フォルダを指さないように。eval_speakers)
    backend = TRANSCRIBE_BACKEND(fake = 疑似の認識・判別。テストと、採点の関数だけを使うとき)"""
    os.environ.setdefault("YTT_CORE_DIR", REPO)
    old = os.environ.get("TRANSCRIBE_DATA_DIR")
    tmp = tempfile.mkdtemp(prefix=prefix)
    atexit.register(shutil.rmtree, tmp, True)
    os.environ["TRANSCRIBE_DATA_DIR"] = tmp
    if backend:
        os.environ["TRANSCRIBE_BACKEND"] = backend
    spec = importlib.util.spec_from_file_location(SERVE_NAME, os.path.join(EDITOR, "serve.py"))
    mod = importlib.util.module_from_spec(spec)
    sys.modules[SERVE_NAME] = mod
    try:
        spec.loader.exec_module(mod)
    except BaseException:
        sys.modules.pop(SERVE_NAME, None)
        raise
    finally:   # 部品は読み込んだときに置き場所を決め終えている
        if not keep_env:
            if old is None:
                os.environ.pop("TRANSCRIBE_DATA_DIR", None)
            else:
                os.environ["TRANSCRIBE_DATA_DIR"] = old
    mod.IN_WORKER = True                         # -> ed_jobs.IN_WORKER
    mod.STUDIO_DATA = mod.studio_data_path()     # -> ed_state.STUDIO_DATA(読むだけ)
    mod.setup_cuda_paths()                       # 認識ワーカーの起動と同じ(pip の CUDA の部品の場所。無ければ何もしない)
    in_process_models(mod)                       # モデルへ渡す音声を、認識ワーカーの受け口と同じ形に(InProcessModel)
    return mod


class InProcessModel:
    """このプロセスの中で読んだモデル(IN_WORKER)の包み。transcribe に来た音声を、認識ワーカーの受け口(tx_worker の _audio)と同じ形に直して渡す。
    editor のサーバー側の書き方は、モデルの代理(RemoteModel)に WavSlice・WavRef(wav のパスとサンプルの範囲だけ。ワーカーが読む)を渡す。
    道具ではそれが faster-whisper に直接届き、読めずに落ちる("File object has no read() method")。
    2026-10-07 夜に分かった: 見直し 2 周目で IN_WORKER が届くようになってから、1 秒丸めの聞き直し(ed_jobs.quant_words_provider)がこれで落ち、
    eval_asr run は丸まった窓のある文書を「とばしました」で数えていなかった。ほかの属性(params・hooks など)は中のモデルのものを読み書きする"""

    def __init__(self, model, audio_of):
        object.__setattr__(self, "_model", model)
        object.__setattr__(self, "_audio_of", audio_of)

    def __getattr__(self, name):
        return getattr(self._model, name)

    def __setattr__(self, name, value):
        setattr(self._model, name, value)

    def transcribe(self, audio, **kw):
        return self._model.transcribe(self._audio_of(audio), **kw)


def in_process_models(S):
    """ed_jobs._load_model_local(このプロセスの中でモデルを読む本体)が返すモデルを InProcessModel で包む。
    部品(ed_jobs)は load_serve を何回呼んでも同じもの(普通の import)なので、包むのは 1 回だけ"""
    J = S.ed_jobs
    if getattr(J._load_model_local, "in_process", False):
        return
    import tx_worker  # noqa: E402  認識ワーカーの受け口(読み込むだけでは何も起動しない)
    SP, local = S.ed_speakers, J._load_model_local

    def audio_of(a):
        if isinstance(a, SP.WavSlice):
            return tx_worker._audio({"wav": a.path, "from": a.a, "to": a.b})
        return a.path if isinstance(a, SP.WavRef) else a

    def load_local(*a, **k):
        model, dev = local(*a, **k)
        return InProcessModel(model, audio_of), dev
    load_local.in_process = True
    J._load_model_local = load_local
