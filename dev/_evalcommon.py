"""dev/ の測る道具(eval_cut.py・eval_alt.py・eval_effort.py・eval_marks.py)の共通の部品(2026-10-07 ③ dev の見直しでまとめた)。

- 置き場所: TOP(リポジトリ直下 = git)・REPO(src = ツールと ytt_core)。読み込むと REPO を sys.path に足す
- 作業データの場所(ytt_core.datadir の 1 か所。--data-dir は全ツールの作業データの親フォルダ = テスト用)・JSON の読み方・
  時期(--since / --until)・率と分布・git の rev・結果の保存(<ツールの作業データ>\\evals\\<領域>\\<日時>.json。
  入口の src/home/accuracy.py が、道具の最後の行「保存: <パス>」と名前の形 <日時>.json で読む = 形を変えない)
- eval_asr.py・eval_speakers.py・eval_timing.py は、まだこれを使っていない(同じ決まりの写しを持つ。使うように直すときは結果が変わらないことをテストで確かめる)
"""
import datetime
import json
import os
import subprocess
import sys
import time

HERE = os.path.dirname(os.path.abspath(__file__))
TOP = os.path.dirname(HERE)      # リポジトリ直下(git)
REPO = os.path.join(TOP, "src")   # ツールと ytt_core の置き場所
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

def git_rev():
    """今のコードの版(git の短い rev。分からなければ空)"""
    try:
        return subprocess.run(["git", "-C", TOP, "rev-parse", "--short", "HEAD"], capture_output=True, text=True, timeout=10).stdout.strip()
    except (OSError, subprocess.SubprocessError):
        return ""


def save(res, root, area):
    """結果を <root>\\evals\\<area>\\<日時>.json に残す(書きかけを残さない)-> パス"""
    d = os.path.join(root, "evals", area)
    os.makedirs(d, exist_ok=True)
    path = os.path.join(d, "%s.json" % datetime.datetime.now().strftime("%Y%m%d-%H%M%S"))
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
