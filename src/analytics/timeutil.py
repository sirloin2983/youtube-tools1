"""日付と時刻の定義(1 か所。監査の E2・E3・E4。plan/analytics-daily-report.md の 12-4 の 2)。

- Studio の数字の「日」は太平洋時間(PT)の日付。夏時間は 3 月の第 2 日曜 2:00 〜 11 月の第 1 日曜 2:00(UTC−7)、それ以外は UTC−8。
  Windows の Python には時間帯のデータベースが無いことがある(zoneinfo は tzdata が要る)ので、規則をここに書く
- 投稿の時刻・本数は日本時間(JST = UTC+9。夏時間なし)。ユーザーが数える日付に合わせる
- 公開からの経過は「時間」で数える。日の境目(PT)までの割合で日の値を分ける(公開日の数時間ぶんを落とさない。E2)
"""
import datetime

UTC = datetime.timezone.utc
JST = datetime.timezone(datetime.timedelta(hours=9))
WEEKDAYS = "月火水木金土日"


def _nth_sunday(year, month, n):
    d = datetime.date(year, month, 1)
    d += datetime.timedelta(days=(6 - d.weekday()) % 7)
    return d + datetime.timedelta(days=7 * (n - 1))


def pt_offset(utc_dt):
    """その時刻(UTC の aware datetime)の太平洋時間の UTC との差(timedelta)"""
    y = utc_dt.year
    start = datetime.datetime.combine(_nth_sunday(y, 3, 2), datetime.time(10), UTC)    # 2:00 PST = 10:00 UTC
    end = datetime.datetime.combine(_nth_sunday(y, 11, 1), datetime.time(9), UTC)      # 2:00 PDT = 9:00 UTC
    return datetime.timedelta(hours=-7 if start <= utc_dt < end else -8)


def to_pt(utc_dt):
    """UTC の aware datetime → 太平洋時間の aware datetime"""
    return utc_dt.astimezone(datetime.timezone(pt_offset(utc_dt)))


def pt_day_start_utc(day):
    """太平洋時間のその日の 0:00 を UTC の aware datetime で"""
    guess = datetime.datetime.combine(day, datetime.time(8), UTC)   # 0:00 PST
    off = pt_offset(guess)
    return datetime.datetime.combine(day, datetime.time(0), UTC) - off


def parse_utc(s):
    """"2026-10-07T21:00:08.000Z" などの ISO 文字列 → UTC の aware datetime(読めなければ None)"""
    if not isinstance(s, str) or not s:
        return None
    t = s.strip().replace("Z", "+00:00")
    try:
        d = datetime.datetime.fromisoformat(t)
    except ValueError:
        try:
            d = datetime.datetime.fromisoformat(t.split(".")[0] + ("+00:00" if t.endswith("+00:00") else ""))
        except ValueError:
            return None
    if d.tzinfo is None:
        d = d.replace(tzinfo=UTC)
    return d.astimezone(UTC)


def day_from_int(v):
    """20261007 → date(読めなければ None)"""
    try:
        v = int(v)
        return datetime.date(v // 10000, v // 100 % 100, v % 100)
    except (TypeError, ValueError):
        return None


def jst_date(utc_dt):
    return utc_dt.astimezone(JST).date()


def md(d):
    """date → "10/7"(画面と LINE の短い書き方)"""
    return "%d/%d" % (d.month, d.day)


def md_w(d):
    """date → "10/7(水)\""""
    return "%d/%d(%s)" % (d.month, d.day, WEEKDAYS[d.weekday()])


def elapsed_hours_at_day_end(pub_utc, day):
    """公開から、太平洋時間のその日の終わりまでの時間"""
    return (pt_day_start_utc(day + datetime.timedelta(days=1)) - pub_utc).total_seconds() / 3600.0


def add_months(d, n):
    m = d.month - 1 + n
    return datetime.date(d.year + m // 12, m % 12 + 1, 1)
