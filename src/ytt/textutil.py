"""ログ・画面に出す文と数の小物(標準ライブラリだけ)。

どれも純粋な関数(状態を持たない・差し替えない)なので、読む側は `from ytt.textutil import redact` の形で読んでよい。
- `redact`: 署名つき URL などをログ・画面に出さない
- `permission_message`: PermissionError を画面に出せる文に
- `tail_reason`: 外部コマンドの標準エラーの末尾から、原因らしい行を拾う
- `fmt_ts`(ffmpeg・yt-dlp に渡す時:分:秒.ミリ秒)・`fmt_ms`(画面の 分:秒)・`num`(数を範囲に収める。不正なら既定)
- `person_key`: 人(話者・メンバー)の名前を比べる鍵の 1 つの決まり(OPT-H1。決定 notes:plan/decisions.md の 3-47 Q8)
"""
import math
import re
import unicodedata

_URL_RE = re.compile(r"https?://\S+")
_REASON_RE = re.compile(r"error|fail|forbidden|denied|invalid|not found|unable|HTTP|403|404|private|unavailable|Sign in", re.I)


def redact(line):
    """署名つきURLなどはログ・画面に出さない。"""
    return _URL_RE.sub("<URL>", str(line))


def permission_message(error):
    """PermissionError(ほかの OSError でも可)→ 画面に出す文(対象のパスが分かれば添える)"""
    path = getattr(error, "filename2", None) or getattr(error, "filename", None)
    detail = " 対象: %s" % path if path else ""
    return ("ファイルへのアクセスが拒否されました。対象ファイルを再生・編集中のアプリを閉じ、"
            "保存先の書き込み権限とドライブの接続を確認してください。" + detail)


def tail_reason(err, n=2):
    """標準エラーの行の並び → 原因らしい行(無ければ最後の行)を n 行まで「 / 」でつないだ文(URL は伏せる)"""
    keep = [redact(l)[:220] for l in err if l.strip()]
    key = [l for l in keep if _REASON_RE.search(l)]
    return " / ".join((key or keep)[-n:])


def fmt_ts(t):
    """秒 → HH:MM:SS.mmm(ffmpeg・yt-dlp に渡す形。負の値は 0)"""
    ms = int(round(max(0.0, float(t)) * 1000))   # 先にミリ秒に丸める(秒の欄が 60.000 にならない)
    return "%02d:%02d:%02d.%03d" % (ms // 3600000, ms % 3600000 // 60000, ms % 60000 // 1000, ms % 1000)


def fmt_ms(t):
    """秒 → 分:秒(画面の経過時間)"""
    t = int(max(0, t))
    return "%d:%02d" % (t // 60, t % 60)


def num(v, lo, hi, default):
    """v を数にして lo〜hi に収める。数でない・真偽値・NaN なら default"""
    if isinstance(v, bool):
        return default
    try:
        x = float(v)
    except (TypeError, ValueError):
        return default
    return default if math.isnan(x) else max(lo, min(hi, x))


_KATA_TO_HIRA = {c: c - 0x60 for c in range(0x30A1, 0x30F7)}   # ァ〜ヶ → ぁ〜ゖ(ー・ヽヾ は そのまま)


def person_key(name):
    """人の名前を比べる鍵: 全角半角(NFKC)・大文字小文字・空白・ひらがなとカタカナの違いを無視する(同じ読みの別の人はいない前提。
    ローマ字とかな(pekora・ぺこら)は結ばない = 名簿の呼び名で結ぶ)。声を覚える・文脈の名前・1 人指定・確かめるの声・字幕の色の名前合わせが使う"""
    s = unicodedata.normalize("NFKC", str(name or "")).casefold()
    return re.sub(r"\s+", "", s).translate(_KATA_TO_HIRA)
