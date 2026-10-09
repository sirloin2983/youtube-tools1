"""raw(ブックマークが Studio の内部 API から取った JSON)→ 形をそろえたデータ。

raw の形(既存の「Youtube日次」の Apps Script が Drive の raw/<日付>.json に置く。監査 plan/analytics-daily-report.md の 12-1):
- fetched_at(UTC)・received_at・date(JST の受信日)・channel
- daily: [{DAY(PT の日。20261007), CREATOR_CONTENT_TYPE(SHORTS / VIDEO_ON_DEMAND / …), ENGAGED_VIEWS, EXTERNAL_VIEWS,
          TOTAL_ESTIMATED_EARNINGS, SUBSCRIBERS_NET_CHANGE}]
- daily_total: [{DAY, 同じ 4 つ}](全形式の合計)
- videos: [{id, title, published(UTC), length, short, privacy, ev, views, vtr(視聴を継続 %。累計), awp, rev, subs}](公開からの累計)
- video_days: {id: [[DAY, ENGAGED_VIEWS, EXTERNAL_VIEWS], …]}(公開 92 日以内の動画の日ごと)

数え方の決まり(1 か所):
- 本数は公開(VIDEO_PRIVACY_PUBLIC)の動画だけ。公開日時が読めない・1970 年(非公開の印)は数えない
- ショートは short(Studio の isShortsRenderable)が真のもの
- 収益の値は Studio の値 ÷ REV_DIVISOR(監査: 1/1000 して USD の前提。文書化されていないので、画面と見比べて確かめるまで「要確認」と出す)
- 配信者は題名のハッシュタグのうち、メンバーの一覧(ytt_core.colors。ホロカラーの members.json)と名前が完全に合うもの。最初の 1 人が主
"""
import datetime
import re

from . import timeutil as T

REV_DIVISOR = 1000.0
METRICS = ("ev", "views", "rev", "subs")
KEYS = {"ENGAGED_VIEWS": "ev", "EXTERNAL_VIEWS": "views", "TOTAL_ESTIMATED_EARNINGS": "rev", "SUBSCRIBERS_NET_CHANGE": "subs"}
TYPES = {"SHORTS": "shorts", "VIDEO_ON_DEMAND": "long"}
TAG_RE = re.compile(r"#([^\s／/【】#|｜]+)")
MAX_VIDEOS = 5000
EPOCH_GUARD = datetime.datetime(2005, 1, 1, tzinfo=T.UTC)


class DataError(ValueError):
    """raw の形が違う(分析できない)"""


class Video:
    __slots__ = ("id", "title", "pub", "pub_pt", "pub_jst", "length", "short", "public", "ev", "views", "vtr", "awp", "rev", "subs",
                 "members", "days")

    def __init__(self, d, members):
        self.id = str(d.get("id") or "")
        self.title = str(d.get("title") or "")
        self.pub = T.parse_utc(d.get("published"))
        if self.pub is not None and self.pub < EPOCH_GUARD:
            self.pub = None
        self.pub_pt = T.to_pt(self.pub).date() if self.pub else None
        self.pub_jst = self.pub.astimezone(T.JST) if self.pub else None
        self.length = _num(d.get("length"))
        self.short = d.get("short") is True
        self.public = d.get("privacy") == "VIDEO_PRIVACY_PUBLIC" and self.pub is not None
        self.ev, self.views = _num(d.get("ev")), _num(d.get("views"))
        self.vtr = _num(d.get("vtr")) if self.short else None
        if self.vtr is not None and not 0 < self.vtr <= 100:
            self.vtr = None   # 長尺・まだ値が無い動画は 0 で来る
        self.awp = _num(d.get("awp"))
        self.rev = _num(d.get("rev")) / REV_DIVISOR
        self.subs = _num(d.get("subs"))
        self.members = members
        self.days = {}   # PT の日 → (ev, views)。video_days があるものだけ

    @property
    def member(self):
        return self.members[0] if self.members else ""

    def short_title(self, n=24):
        """題名の【…】の見出し(無ければ先頭 n 文字)"""
        m = re.match(r"\s*【([^】]{1,30})】", self.title)
        if m:
            return m.group(1)
        t = re.sub(r"【[^】]*】", "", self.title).strip()
        return t[:n]


class Dataset:
    """1 つの raw から作るデータ。日の値は {PT の日: {"ev", "views", "rev", "subs"}} を kind("shorts"・"long"・"total")ごとに"""

    def __init__(self):
        self.channel = ""
        self.fetched = None        # Studio から取った時刻(UTC)= スマホでタップした時刻
        self.received = None       # Apps Script が受け取った時刻
        self.date_jst = None       # raw の名前の日付(JST の受信日)
        self.pt_today = None       # 取った時刻の PT の日(この日はまだ途中)
        self.series = {"shorts": {}, "long": {}, "total": {}}
        self.videos = []
        self.by_id = {}
        self.warnings = []

    @property
    def days(self):
        return sorted(self.series["total"])

    def value(self, kind, metric, day):
        r = self.series[kind].get(day)
        return r[metric] if r else 0.0

    def public_videos(self, short=None):
        return [v for v in self.videos if v.public and (short is None or v.short == short)]


def _num(v):
    if isinstance(v, bool) or v is None:
        return 0.0
    try:
        f = float(v)
    except (TypeError, ValueError):
        return 0.0
    return f if f == f and abs(f) < 1e15 else 0.0


def member_matcher(entries):
    """メンバーの一覧(ytt_core.colors.load の結果)→ 題名 → [メンバーの名前](出てきた順・重なりなし)"""
    try:
        from ytt import colors
    except ImportError:   # 単体で読むテスト(ytt_core が無い)では照らし合わせない
        return lambda title: []
    keys = {}
    for e in entries or []:
        for k in (e.get("name"), e.get("en"), e.get("id")):
            nk = colors.normalize(k)
            if nk and nk not in keys and not e.get("mine"):
                keys[nk] = e["name"]

    def match(title):
        out = []
        for t in TAG_RE.findall(title or ""):
            name = keys.get(colors.normalize(t))
            if name and name not in out:
                out.append(name)
        return out
    return match


def parse(raw, members=None):
    """raw(dict)→ Dataset。形が違えば DataError。members: 題名 → [名前] の関数(member_matcher)"""
    if not isinstance(raw, dict):
        raise DataError("raw が JSON のオブジェクトではありません")
    for k in ("fetched_at", "daily", "daily_total", "videos"):
        if k not in raw:
            raise DataError("raw に %s がありません" % k)
    ds = Dataset()
    ds.channel = str(raw.get("channel") or "")
    ds.fetched = T.parse_utc(raw.get("fetched_at"))
    if ds.fetched is None:
        raise DataError("raw の fetched_at が読めません")
    ds.received = T.parse_utc(raw.get("received_at")) or ds.fetched
    ds.date_jst = str(raw.get("date") or T.jst_date(ds.fetched).isoformat())
    ds.pt_today = T.to_pt(ds.fetched).date()
    match = members or (lambda title: [])

    bad = 0
    for row in raw.get("daily") or []:
        kind = TYPES.get(row.get("CREATOR_CONTENT_TYPE")) if isinstance(row, dict) else None
        day = T.day_from_int(row.get("DAY")) if isinstance(row, dict) else None
        if day is None:
            bad += 1
            continue
        if kind:
            _put(ds.series[kind], day, row)
    for row in raw.get("daily_total") or []:
        day = T.day_from_int(row.get("DAY")) if isinstance(row, dict) else None
        if day is None:
            bad += 1
            continue
        _put(ds.series["total"], day, row)
    if bad:
        ds.warnings.append("日ごとの行のうち %d 行は日付が読めないので使いませんでした" % bad)
    if not ds.series["total"]:
        raise DataError("raw に日ごとの数字がありません")
    # 日の抜けは 0 で埋める(Studio は値が無い日を返さないことがある。最初の日から最後の日まで)
    first, last = min(ds.series["total"]), max(ds.series["total"])
    d = first
    while d <= last:
        for kind in ds.series:
            ds.series[kind].setdefault(d, {m: 0.0 for m in METRICS})
        d += datetime.timedelta(days=1)

    vids = raw.get("videos") or []
    if not isinstance(vids, list):
        raise DataError("raw の videos が配列ではありません")
    for v in vids[:MAX_VIDEOS]:
        if not isinstance(v, dict) or not v.get("id"):
            continue
        vid = Video(v, match(str(v.get("title") or "")))
        if vid.id in ds.by_id:
            continue
        ds.videos.append(vid)
        ds.by_id[vid.id] = vid
    if not ds.videos:
        ds.warnings.append("動画の一覧が空です")
    vd = raw.get("video_days") or {}
    if isinstance(vd, dict):
        for vid, rows in vd.items():
            v = ds.by_id.get(vid)
            if v is None or not isinstance(rows, list):
                continue
            for r in rows:
                if isinstance(r, list) and len(r) >= 2:
                    day = T.day_from_int(r[0])
                    if day is not None:
                        v.days[day] = (_num(r[1]), _num(r[2]) if len(r) > 2 else 0.0)
    ds.videos.sort(key=lambda x: x.pub or datetime.datetime.min.replace(tzinfo=T.UTC))
    return ds


def _put(series, day, row):
    cur = series.setdefault(day, {m: 0.0 for m in METRICS})
    for k, m in KEYS.items():
        val = _num(row.get(k))
        cur[m] += val / REV_DIVISOR if m == "rev" else val
