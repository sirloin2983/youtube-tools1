"""dev/ の測る道具(eval_asr.py・eval_speakers.py・eval_timing.py・eval_cut.py・eval_alt.py・eval_marks.py)の共通の部品。

- 置き場所: TOP(リポジトリ直下 = git)・REPO(src = ツールと ytt)。読み込むと REPO を sys.path に足す
- 作業データの場所(ytt.datadir の 1 か所。--data-dir は全ツールの作業データの親フォルダ = テスト用)・JSON の読み方・
  時期(--since / --until)・率と分布・git の rev・結果の保存(<ツールの作業データ>/evals/<領域>/<日時>.json。
  入口の src/eval/drill/accuracy.py が、道具の最後の行「保存: <パス>」(前と中身が同じなら「変わらず: <前のパス>」)と名前の形 <日時>.json で読む = 形を変えない)
- ①②③ の部品をこのプロセスの中で使う準備(prepare。編集の serve は読まない = OPT-E2。eval_asr・eval_speakers の run・eval_alt・eval_cloud)
"""
import atexit
import datetime
import os
import re
import shutil
import subprocess
import sys
import tempfile
import time

HERE = os.path.dirname(os.path.abspath(__file__))   # src/eval/tools
REPO = os.path.dirname(os.path.dirname(HERE))      # src(ツールと共通部品 ytt の置き場所)
TOP = os.path.dirname(REPO)                        # リポジトリ直下(git)
EDITOR = os.path.join(REPO, "editor")              # 編集のフォルダ(作業データの以前の既定の場所を引くだけ。serve は読まない)
if REPO not in sys.path:
    sys.path.insert(0, REPO)
from ytt import datadir, fsio, schemas  # noqa: E402
from ytt.fsio import read_json_or as read_json  # noqa: E402   read_json(path, default, limit) = JSON のファイル(BOM 可)。読めない・壊れている・NaN・limit バイト超は default

DOC_BYTES = 64 * 1024 * 1024    # 文書・記録の JSON を読むときの上限(limit を渡さない呼び出しにも付ける。fsio の既定は 16MiB)
SAVED_MARK = "保存: "            # 結果を残した最後の行の頭(入口の src/eval/drill/accuracy.py が SAVED_MARK として読む。形を変えない)
SAME_MARK = "変わらず: "          # 前の結果と中身が同じで書かなかったときの最後の行の頭(入口の accuracy.py が SAME_MARK として読む)
VOLATILE_KEYS = ("at", "git", "rev", "sec", "seconds", "elapsed")   # 「前と同じ」を見るときに除く、毎回変わる欄(時刻・git の版・かかった秒)


# ---------------------------------------------------------------- 引数の定義(since / until / json / data-dir は全部の道具で同じ)

def add_period_args(p, since_help, until_help="この日(YYYY-MM-DD。この日を含む)までだけ", json_help="同じ形の JSON を 文字起こしの作業データの evals/ 以下に残す"):
    """--since / --until / --json / --data-dir を足す(--data-dir は全ツールの作業データの親フォルダ = テスト用。
    eval_asr・eval_cloud の --data は文字起こしの作業データのフォルダそのもの = 意味が違うので別)"""
    p.add_argument("--since", help=since_help)
    p.add_argument("--until", help=until_help)
    p.add_argument("--json", action="store_true", help=json_help)
    p.add_argument("--data-dir", help="作業データの親フォルダ(既定 %%LOCALAPPDATA%%\\youtube-tools。テスト用)")


def split_ids(text):
    """「,」区切りの文書の id -> 空白を除いた list(指定が無い・空なら None)"""
    return [x.strip() for x in text.split(",") if x.strip()] if text else None


def label_name(text, limit=40):
    """結果のファイル名に使う名前(英数字と . - _ 以外は _ に)"""
    return re.sub(r"[^\w.-]+", "_", text)[:limit]


def data_env(data_dir, base=None):
    """--data-dir(全ツールの作業データの親フォルダ。テスト用)-> datadir に渡す環境変数。指定が無ければ base(None = 今の環境変数)"""
    return {"YTT_DATA_DIR": os.path.abspath(data_dir)} if data_dir else base


def locate(tool, data_dir=None, base=None):
    """-> ツール(transcribe・studio・app)の作業データのフォルダ。置き場所の規則は ytt.datadir の 1 か所"""
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


is_reviewed = schemas.is_eval_reviewed   # lint: keep 動画を全部聞いて確かめた文書か(正は ytt/schemas。C-EVAL 2a-1 で写しを寄せた)


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


def _plain(x):
    """比べるための形: 毎回変わる欄(VOLATILE_KEYS。時刻・git の版・かかった秒)をどの深さからも除く"""
    if isinstance(x, dict):
        return {k: _plain(v) for k, v in x.items() if k not in VOLATILE_KEYS}
    if isinstance(x, list):
        return [_plain(v) for v in x]
    return x


def previous_same(res, root, area, suffix=""):
    """同じ置き場所(<root>/evals/<area>/)の最新の結果(同じ suffix のもの)と、毎回変わる欄を除いて中身が同じなら、その前のファイルのパス。違う・前が無い・読めないなら None。
    本番は結果のファイルを読まない"""
    d = os.path.join(root, "evals", area)
    pat = re.compile(r"^\d{8}-\d{6}%s\.json\Z" % re.escape(suffix))
    try:
        names = sorted(n for n in os.listdir(d) if pat.match(n))
    except OSError:
        return None
    if not names:
        return None
    path = os.path.join(d, names[-1])
    prev = read_json(path, None, DOC_BYTES)
    return path if prev is not None and _plain(prev) == _plain(res) else None


def save(res, root, area, suffix=""):
    """結果を <root>/evals/<area>/<日時><suffix>.json に残す(書きかけを残さない)-> パス。
    suffix = 名前の後ろ(eval_asr = "_<名前>"・eval_speakers の run = "-run")。
    前の結果(previous_same)と中身が同じなら書かずに、その前のファイルのパスを返す(毎晩同じ結果が貯まらない)"""
    same = previous_same(res, root, area, suffix)
    if same:
        return same
    path = os.path.join(root, "evals", area, "%s%s.json" % (datetime.datetime.now().strftime("%Y%m%d-%H%M%S"), suffix))
    fsio.write_json(path, res, indent=1)   # フォルダも作る・Windows の一時的なロックは待ってやり直す
    return path


def report_saved(res, enabled, root, area, suffix=""):
    """enabled なら save して、最後の行「保存: <パス>」を出す(入口の accuracy.py がこの行を読む)。
    前と中身が同じで書かなかったときは、代わりに「変わらず: <前のファイル>」を出す(入口は latest を残して at だけ進める)"""
    if enabled:
        same = previous_same(res, root, area, suffix)
        if same:
            print("\n" + SAME_MARK + same)
        else:
            print("\n" + SAVED_MARK + save(res, root, area, suffix))


def utf8_stdout():
    """Windows のコンソールでも日本語の表を出せるように(できなければそのまま)"""
    try:
        sys.stdout.reconfigure(encoding="utf-8")
    except (AttributeError, ValueError):
        pass


# ---------------------------------------------------------------- ①②③ の部品をこのプロセスの中で使う準備(採点・認識・判別)

_PREPARED = {}   # この道具の部品の作業データ(一時フォルダ。1 プロセスで 1 つ)


def prepare(backend=None, prefix="eval_"):
    """入口(編集の serve)を読まずに、①②③ の部品をこのプロセスの中で使う準備 -> 部品の作業データ(一時フォルダ)。何度呼んでもよい。
    OPT-E2(1c。設計原則のレビューの指摘 4)まで load_serve が編集の serve.py を別名で読み、その読み込みの副作用(置き場所・名簿・疑似の登録)と
    名前の転送(S.名前)に頼っていた。今は要る物を ② flow/wire.setup_headless に明示して渡し、道具は持ち主のモジュールを直に読む:
    - 部品の作業データ = 一時フォルダ <prefix>…(本物の作業データの横に何も書かない。本物は道具が自分で読む。このプロセスの終わりに消す)。
      環境変数 TRANSCRIBE_DATA_DIR は書き換えない(このあとの locate は本物を指したまま)
    - スタジオの data.json = 環境変数 TRANSCRIBE_STUDIO_DATA(テスト)か、置き場所の持ち主 flow/placement(--context auto が配信のチャンネル名・コラボ相手を読む)
    - 本物と疑似の選び方 = ① backend.mode()(環境変数 TRANSCRIBE_BACKEND。backend = "fake" なら疑似の認識・判別 = テストと採点の関数だけを使うとき)
    - 認識・判別はこのプロセスの中(① worker_client.IN_WORKER。GPU の部品の場所はワーカーと同じ)。モデルへ渡す音声は認識ワーカーの受け口と同じ形に(in_process_models)
    - 辞書の版の材料の学習の記録 = ③ doc_jobs.dict_learned(編集の serve の登録と同じ)"""
    from flow import placement, wire
    from pipeline.transcribe import backend as txbackend
    from eval.fake import fake_asr, fake_worker
    from human.proof import doc_jobs
    if backend:
        os.environ[txbackend.ENV] = backend
    if "tmp" not in _PREPARED:
        _PREPARED["tmp"] = tempfile.mkdtemp(prefix=prefix)
        atexit.register(shutil.rmtree, _PREPARED["tmp"], True)
    wire.setup_headless(data_dir=_PREPARED["tmp"], studio_data=os.environ.get("TRANSCRIBE_STUDIO_DATA") or placement.studio_data(),
                        in_process=True, backend_name=txbackend.mode, fake_backend=fake_asr.FAKE, fake_worker_module=fake_worker.__name__,
                        dict_learned=lambda: doc_jobs.dict_learned())
    in_process_models()
    return _PREPARED["tmp"]


def fake_job():
    """editor の extract_audio などに渡す、取り消しも進み具合も使わない空のジョブ"""
    return {"cancel": False, "proc": None, "phase": "", "state": "", "device": "", "progress": 0.0}


def audio_span(doc, data, doc_id=None, boost=None):
    """文書の音声の出どころ(元の動画 → 保管データの dataset/docs/<id>/full.flac。今ある保管データだけ)-> (extract_audio の spec, 行の時刻の基準の秒, "動画" か "保管の音声")。
    どちらも無ければ RuntimeError。ネットワーク上の動画は読まない(存在を確かめるだけで資格情報を送ってしまう。eval_speakers にあった決まりを全部の道具に)。
    boost = None なら spec に boost を入れない(extract_audio は spec.get("boost") で見る = 無ければ偽)"""
    src = str(doc.get("sourcePath") or "")
    start, end = schemas.num_or(doc.get("start"), 0.0) or 0.0, schemas.num_or(doc.get("end"))
    full = os.path.join(data, "dataset", "docs", doc_id or doc["id"], "full.flac")
    extra = {} if boost is None else {"boost": boost}
    if src and not fsio.is_network_path(src) and os.path.isfile(src):
        return dict({"sourcePath": src, "start": start, "end": end}, **extra), start, "動画"
    if os.path.isfile(full):   # 保管データの全体の音声(文書の範囲の先頭 = 0 秒)
        return dict({"sourcePath": full, "start": 0.0, "end": None}, **extra), start, "保管の音声"
    raise RuntimeError("音声が見つかりません(元の動画も保管データの full.flac も無い)")


class InProcessModel:
    """このプロセスの中で読んだモデル(IN_WORKER)の包み。transcribe に来た音声を、認識ワーカーの受け口(pipeline/transcribe/worker の _audio)と同じ形に直して渡す。
    editor のサーバー側の書き方は、モデルの代理(RemoteModel)に WavSlice・WavRef(wav のパスとサンプルの範囲だけ。ワーカーが読む)を渡す。
    道具ではそれが faster-whisper に直接届き、読めずに落ちる("File object has no read() method")。
    包まないと、丸まった窓のある文書は読めずに落ち、eval_asr run が「とばしました」で数えない。ほかの属性(params・hooks など)は中のモデルのものを読み書きする"""

    def __init__(self, model, audio_of):
        object.__setattr__(self, "_model", model)
        object.__setattr__(self, "_audio_of", audio_of)

    def __getattr__(self, name):
        return getattr(self._model, name)

    def __setattr__(self, name, value):
        setattr(self._model, name, value)

    def transcribe(self, audio, **kw):
        return self._model.transcribe(self._audio_of(audio), **kw)


def in_process_models():
    """① models._load_model_local(このプロセスの中でモデルを読む本体)が返すモデルを InProcessModel で包む。
    持ち主の部品は普通の import(何回 prepare しても同じもの)なので、包むのは 1 回だけ"""
    from pipeline.transcribe import models, worker_client
    from pipeline.transcribe import worker as txw  # noqa: E402  認識ワーカーの受け口(読み込むだけでは何も起動しない)
    if getattr(models._load_model_local, "in_process", False):
        return
    local = models._load_model_local

    def audio_of(a):
        if isinstance(a, worker_client.WavSlice):
            return txw._audio({"wav": a.path, "from": a.a, "to": a.b})
        return a.path if isinstance(a, worker_client.WavRef) else a

    def load_local(*a, **k):
        model, dev = local(*a, **k)
        return InProcessModel(model, audio_of), dev
    load_local.in_process = True
    models._load_model_local = load_local
