"""計算(plan/analytics-daily-report.md の 4 節と 12-4 の方針)。入力は data.Dataset、出力は JSON にできる dict。

方針(監査の誤り E1〜E7 を繰り返さない):
- 固定のファイルに頼らない。すべてその raw から計算し直す(E1)
- 公開からの伸びは「経過時間」で数える(PT の日の値を、公開から日の終わりまでの時間で並べて線でつなぐ。E2)
- 確定: エンゲージビュー(EV)は「取った時刻の PT の日 − 2 日」まで(前日は大きく欠ける)。収益はそれまでのうち値が入っている最後の日(E3)
- 当たり・外れは固定の数字ではなく、過去の動画(同じ経過時間)の中の順位で決める(E6)
- 見込みは毎回、過去の時点から同じ方法で出し直して実際と比べ(答え合わせ)、その誤差を確率の幅に入れる(E5)
- 数字の出どころ(確定の日・計算に使った本数)を結果に必ず入れる(E1・E4)
"""
import datetime
import math
import random
import statistics

from . import timeutil as T

DAY = datetime.timedelta(days=1)
YPP_TARGET = 10_000_000          # 直近 90 日のショートの EV(Studio の数字)
YPP_WINDOW = 90
YPP_START = datetime.date(2027, 2, 1)   # この日から、直近 90 日で 1,000 万が要る(以後も毎日の窓で保つ。ユーザー確認 10-09)
YPP_KEEP_UNTIL = datetime.date(2027, 3, 29)   # 「その後も保つ」を見る最後の日(週ごとに見る)
GRID_STEP = 24.0                 # 伸び方の曲線の刻み(時間)
TAIL_DAYS = 3 * 365              # 曲線を伸ばす先(日)
LAUNCH_HOURS = (24, 48, 72)
WEEK_HOURS = 168
LABELS = ((0.8, "当たり"), (0.5, "中間"), (0.2, "伸び悩み"), (0.0, "外れ"))
LENGTH_BANDS = ((0, 20, "〜20秒"), (21, 30, "21〜30秒"), (31, 40, "31〜40秒"), (41, 50, "41〜50秒"), (51, 10**6, "51秒〜"))
HOUR_BANDS = ((0, 9, "0〜9時"), (9, 12, "9〜12時"), (12, 15, "12〜15時"), (15, 18, "15〜18時"), (18, 21, "18〜21時"), (21, 24, "21〜24時"))
MIN_GROUP = 3                    # 群の比較に出す最少の本数
BOUNDARY = datetime.date(2026, 10, 1)   # 境目(ユーザーが本格的にサポートを始め、戦略が変わった日。10-09 ユーザー。画面で変えられる)
MIN_POOL = 12                    # 強さの見本に要る最少の本数(足りない側は見込みを出さない)
CAP_Q = 1.0                     # 伸び率の重みの頭打ち(分位。1.0 = 頭打ちなし)
POOL_DAYS = 35                  # これからの動画の伸びの強さの見本にする期間(日。チャンネルの調子の変化に付いていく長さ)
SIMS = 600


# ------------------------------------------------------------------ 確定

def confirmed(ds):
    """-> {"ptToday", "ev", "rev", "last"}(date)。ev = EV の確定の最後の日・rev = 収益の確定の最後の日(無ければ None)"""
    last = max(ds.days)
    ev = min(ds.pt_today - 2 * DAY, last)
    revs = [d for d in ds.days if d <= ev and ds.value("total", "rev", d) > 0]
    return {"ptToday": ds.pt_today, "ev": ev, "rev": max(revs) if revs else None, "last": last}


def day_end_utc(day):
    return T.pt_day_start_utc(day + DAY)


# ------------------------------------------------------------------ 動画ごとの伸び(経過時間)

def points(v, until_day):
    """[(公開からの時間, 累計 EV)]。until_day までの日だけ。最初は (0, 0)"""
    pts = [(0.0, 0.0)]
    cum = 0.0
    for day in sorted(v.days):
        if day > until_day:
            break
        cum += v.days[day][0]
        h = T.elapsed_hours_at_day_end(v.pub, day)
        if h <= 0:
            continue
        pts.append((h, cum))
    return pts


def cum_at(pts, h):
    """経過 h 時間の累計(線でつなぐ)。h が記録の終わりより先なら None"""
    if h > pts[-1][0] + 1e-9:
        return None
    for (h0, c0), (h1, c1) in zip(pts, pts[1:]):
        if h <= h1:
            return c0 + (c1 - c0) * ((h - h0) / (h1 - h0) if h1 > h0 else 1.0)
    return pts[-1][1]


def covered(v):
    """日ごとの記録が公開日から揃っている動画か(video_days は公開 92 日以内の動画だけ)"""
    return bool(v.days) and v.pub is not None and min(v.days) <= v.pub_pt + DAY


def shorts_with_days(ds):
    return [v for v in ds.public_videos(short=True) if covered(v)]


class Curve:
    """平均の伸び方 G(h) = 公開から h 時間の累計 EV(動画 1 本あたり)。h は GRID_STEP の刻み。
    作り方はチェーンラダー法(保険の支払いの見込みと同じ): 1 日目の累計は平均、そこから先は「k 日目 → k+1 日目」の伸び率を、
    k+1 日目まで記録のある同じ動画どうしの合計の比で求めてつなぐ。日がたった所ほど記録のある動画が少なく顔ぶれが変わるが、
    比は同じ動画どうしで取るので、顔ぶれの違い(大当たりの 1 本が入る・抜ける)で曲線が膨らまない(2026-10-09 の答え合わせで、
    平均をそのまま使うと既にある動画の伸びを 2〜10 倍に見込んでいた)。大当たりの重みは上位 10% の値で頭打ちにする。
    記録の先は、伸び率 − 1 が最後の 3 週と同じ割合で小さくなっていくとして伸ばす"""

    def __init__(self, videos, until_day, min_n=8):
        end = day_end_utc(until_day)
        series = []
        for v in videos:
            if v.pub is None or v.pub >= end:
                continue
            pts = points(v, until_day)
            cs = [0.0]
            k = 1
            while k * GRID_STEP <= pts[-1][0]:
                cs.append(cum_at(pts, k * GRID_STEP))
                k += 1
            if len(cs) > 1:
                series.append(cs)
        self.n0 = len(series)
        g = [0.0]
        if series:
            g.append(statistics.fmean(s[1] for s in series))
        factors = []
        k = 1
        while True:
            pairs = [(s[k], s[k + 1]) for s in series if len(s) > k + 1 and s[k] > 0]
            if len(pairs) < min_n:
                break
            cap = sorted(a for a, _ in pairs)[int(CAP_Q * (len(pairs) - 1))]
            num = sum(min(1.0, cap / a) * b for a, b in pairs)
            den = sum(min(1.0, cap / a) * a for a, b in pairs)
            factors.append(max(1.0, num / den) if den > 0 else 1.0)
            k += 1
        for f in factors:
            g.append(g[-1] * f)
        self.covered_steps = len(g) - 1
        if len(g) < 2:
            g = [0.0, 0.0]
        tail = [f - 1.0 for f in factors[-21:]]
        r = 0.9
        if len(tail) >= 4 and tail[0] > 0 and tail[-1] > 0:
            r = (tail[-1] / tail[0]) ** (1.0 / (len(tail) - 1))
        self.decay = min(0.98, max(0.8, r))
        step = (factors[-1] - 1.0) if factors else 0.0
        steps_needed = int(TAIL_DAYS * 24 / GRID_STEP)
        while len(g) <= steps_needed:
            step *= self.decay
            g.append(g[-1] * (1.0 + step))
        self.g = g

    def at(self, h):
        if h <= 0:
            return 0.0
        x = h / GRID_STEP
        i = int(x)
        if i + 1 >= len(self.g):
            return self.g[-1]
        return self.g[i] + (self.g[i + 1] - self.g[i]) * (x - i)


def quality(v, curve, until_day, prior_h=24.0):
    """その動画の伸びの強さ q(平均の伸び方に対する倍率)。公開直後は平均(1)に寄せる(少ないデータで振れないように)"""
    end = day_end_utc(until_day)
    h = (end - v.pub).total_seconds() / 3600.0
    if h <= 0:
        return 1.0
    pts = points(v, until_day)
    c = cum_at(pts, min(h, pts[-1][0])) or 0.0
    g, g0 = curve.at(min(h, pts[-1][0])), curve.at(prior_h)
    return (c + g0) / (g + g0) if (g + g0) > 0 else 1.0


# ------------------------------------------------------------------ 本数(日本時間)

def count_posts(ds, start, end, short=True):
    """日本時間の start〜end(両端を含む date)に公開した公開中の動画の本数"""
    return sum(1 for v in ds.public_videos(short=short) if start <= v.pub_jst.date() <= end)


def posts_summary(ds):
    """直近 7 日・28 日(日本時間。取った日の前日まで)の本数"""
    today = T.jst_date(ds.fetched)
    y = today - DAY
    out = {"through": y.isoformat(), "short7": count_posts(ds, y - 6 * DAY, y), "long7": count_posts(ds, y - 6 * DAY, y, short=False),
           "short28": count_posts(ds, y - 27 * DAY, y), "todayShort": count_posts(ds, today, today)}
    out["perWeek28"] = round(out["short28"] / 4.0, 1)
    return out


# ------------------------------------------------------------------ YPP

def ypp_now(ds, conf):
    """確定した日までの直近 90 日のショートの EV と、14 日平均・必要なペース"""
    end = conf["ev"]
    s90 = sum(ds.value("shorts", "ev", end - i * DAY) for i in range(YPP_WINDOW))
    a14 = sum(ds.value("shorts", "ev", end - i * DAY) for i in range(14)) / 14.0
    unconf = [(d.isoformat(), ds.value("shorts", "ev", d)) for d in ds.days if d > end]
    return {"through": end.isoformat(), "sum90": round(s90), "ratio": s90 / YPP_TARGET, "avg14": round(a14),
            "need": round(YPP_TARGET / YPP_WINDOW), "speculative": unconf}


class Model:
    """見込みの計算の準備(origin = 何日までの確定のデータで見込むか)。
    1 日のショートの EV = 古い動画の分(日ごとの記録の無い動画。指数で減る) + 記録のある動画 q×曲線の増え + これからの動画 q~×曲線の増え"""

    def __init__(self, ds, origin):
        self.ds, self.origin = ds, origin
        end = day_end_utc(origin)
        self.vids = [v for v in shorts_with_days(ds) if v.pub < end]
        self.curve = Curve(self.vids, origin)
        self.q = {v.id: quality(v, self.curve, origin) for v in self.vids}
        # 古い動画の分 = チャンネルのショートの EV − 記録のある動画の合計(origin までの直近 28 日で減り具合を見る)
        backlog = []
        for i in range(28):
            d = origin - (27 - i) * DAY
            known = sum(v.days.get(d, (0.0, 0.0))[0] for v in self.vids)
            backlog.append(max(0.0, self.ds.value("shorts", "ev", d) - known))
        a, b = sum(backlog[:7]) / 7.0, sum(backlog[-7:]) / 7.0
        lam = math.log(a / b) / 21.0 if a > 0 and b > 0 else 0.0
        self.backlog0, self.lam = b, min(0.05, max(0.0, lam))
        # これからの動画の q の見本(既定: origin の前 POOL_DAYS 日に公開して 72 時間たったもの。境目の前後は pool_between で)
        lo = end - datetime.timedelta(days=POOL_DAYS)
        self.pool = self.pool_between(lo, end) or [1.0]
        # 公開の時刻(PT の日の 0 時からの時間)の見本
        hrs = sorted(((v.pub - T.pt_day_start_utc(v.pub_pt)).total_seconds() / 3600.0) for v in self.vids if v.pub >= lo)
        self.hours = hrs or [12.0]

    def pool_between(self, lo, hi):
        """lo〜hi(UTC)に公開して、origin の時点で 72 時間たった動画の q"""
        last = day_end_utc(self.origin) - datetime.timedelta(hours=72)
        return [self.q[v.id] for v in self.vids if lo <= v.pub < hi and v.pub <= last]

    def base_daily(self, day, lam=None):
        """記録のある動画と古い動画の、その日の見込み(lam = 古い動画の減り方を変えて試すとき)"""
        k = (day - self.origin).days
        s = self.backlog0 * math.exp(-(self.lam if lam is None else lam) * k)
        s0, s1 = T.pt_day_start_utc(day), T.pt_day_start_utc(day + DAY)
        for v in self.vids:
            h0, h1 = (s0 - v.pub).total_seconds() / 3600.0, (s1 - v.pub).total_seconds() / 3600.0
            s += self.q[v.id] * (self.curve.at(h1) - self.curve.at(max(0.0, h0)))
        return s

    def slot_total(self, pub_utc, days):
        """その時刻に公開した平均の動画(q=1)が、days(続いた日の並び)の日に稼ぐ EV の合計 = 曲線の両端の差"""
        if not days:
            return 0.0
        h0 = (T.pt_day_start_utc(min(days)) - pub_utc).total_seconds() / 3600.0
        h1 = (T.pt_day_start_utc(max(days) + DAY) - pub_utc).total_seconds() / 3600.0
        return self.curve.at(h1) - self.curve.at(max(0.0, h0)) if h1 > 0 else 0.0

    def schedule(self, per_week, last_day):
        """origin の翌日〜last_day に、週 per_week 本を毎日均等に(端数は日をまたいで積む)。公開の時刻は見本の分位"""
        out, acc = [], 0.0
        d = self.origin + DAY
        per_day = per_week / 7.0
        while d <= last_day:
            acc += per_day
            n = int(acc + 1e-9)
            acc -= n
            for i in range(n):
                hr = self.hours[min(len(self.hours) - 1, int((i + 0.5) / n * len(self.hours)))]
                out.append(T.pt_day_start_utc(d) + datetime.timedelta(hours=hr))
            d += DAY
        return out


def _window(check_day):
    """その日の判定に使う 90 日(check_day の前日まで)"""
    return [check_day - (i + 1) * DAY for i in range(YPP_WINDOW)]


def ypp_checks():
    """判定を見る日: 2/1 と、その後 3/29 まで週ごと(「その後も保つ」)"""
    return [YPP_START + i * 7 * DAY for i in range((YPP_KEEP_UNTIL - YPP_START).days // 7 + 1)]


class Fixed:
    """見込みの決まった部分(本数ごとに変わらない): 判定の窓ごとの、確定した日の実際 + 記録のある動画と古い動画の見込み"""

    def __init__(self, ds, conf, m, checks, lam=None):
        self.windows = [_window(c) for c in checks]
        cache = {}
        self.known, self.base = [], []
        for w in self.windows:
            known = sum(ds.value("shorts", "ev", d) for d in w if d <= conf["ev"])
            rest = 0.0
            for d in w:
                if d > conf["ev"]:
                    if d not in cache:
                        cache[d] = m.base_daily(d, lam)
                    rest += cache[d]
            self.known.append(known)
            self.base.append(rest)


def forecast(ds, conf, per_week, sigma, sims=SIMS, seed=None, model=None, pool=None, strength=1.0, e=0.0, ref=None, lam=None,
             extra=(), fixed=None):
    """週 per_week 本のまま続けたときの、2/1 の判定と、その後(週ごと)の 90 日の合計の見込み(モンテカルロ)。
    - pool: これからの動画の強さ q の見本(既定はモデルの見本)。1 本ずつ見本から抜き出す = 当たり・外れのばらつきはここで入る
    - sigma: 見込みの方法そのものの誤差(対数。期間の長さで広げて全体に掛ける)
    - strength: これからの動画の強さに掛ける倍率(感度の表)・e と ref: 食い合い(週 ref 本のときの強さが、週 per_week 本では (per_week/ref)^(−e) 倍)
    - lam: 古い動画の減り方を変える(感度の表)・extra: 2/1 のほかに 90 日の合計の中央値を出す日(見込みの記録の答え合わせ用)
    -> {"perWeek", "p10", "p50", "p90", "prob", "keepProb", "keepMin50", "extra"}"""
    m = model or Model(ds, conf["ev"])
    pool = pool or m.pool
    checks = ypp_checks() + [c for c in extra]
    fx = fixed if fixed is not None and len(fixed.windows) == len(checks) else Fixed(ds, conf, m, checks, lam)
    span = max(1.0, (YPP_START - conf["ev"]).days / 28.0)
    sig = sigma * math.sqrt(span)
    mult = strength * ((per_week / float(ref)) ** (-e) if e and ref else 1.0)
    slots = m.schedule(per_week, max(checks) - DAY)
    slot_s = [[m.slot_total(p, [d for d in w if d > conf["ev"]]) for w in fx.windows] for p in slots]
    rnd = random.Random(seed if seed is not None else conf["ev"].toordinal() * 1000 + int(per_week * 10))
    nmain = len(ypp_checks())
    res = [[] for _ in checks]
    keep_ok = 0
    for _ in range(sims):
        noise = math.exp(rnd.gauss(0.0, sig)) if sig > 0 else 1.0
        qs = [rnd.choice(pool) for _ in slots]
        ok = True
        for wi in range(len(checks)):
            fut = sum(q * s[wi] for q, s in zip(qs, slot_s)) * mult
            val = fx.known[wi] + (fx.base[wi] + fut) * noise
            res[wi].append(val)
            if wi < nmain and val < YPP_TARGET:
                ok = False
        keep_ok += ok
    first = sorted(res[0])
    mins = sorted(min(res[wi][i] for wi in range(nmain)) for i in range(sims))
    q = lambda arr, p: arr[min(len(arr) - 1, int(p * len(arr)))]
    return {"perWeek": per_week, "p10": round(q(first, 0.1)), "p50": round(q(first, 0.5)), "p90": round(q(first, 0.9)),
            "prob": sum(1 for x in first if x >= YPP_TARGET) / float(sims), "keepProb": keep_ok / float(sims),
            "keepMin50": round(q(mins, 0.5)), "checks": [c.isoformat() for c in checks[:nmain]],
            "extra": {c.isoformat(): round(q(sorted(res[nmain + i]), 0.5)) for i, c in enumerate(extra)}}


def backtest(ds, conf, horizon=28, origins=5):
    """過去の時点(確定の日の 28〜56 日前)から、実際の投稿のとおりに投稿したとして次の 28 日のショートの EV を見込み、実際と比べる。
    -> {"rows": [{"origin", "pred", "actual", "err"}], "mape", "sigma"}。曲線・q・古い動画の減り方の誤り(本数の読み違いは含まない)"""
    rows = []
    for k in range(origins):
        origin = conf["ev"] - (horizon + 7 * k) * DAY
        if origin < min(ds.days) + 35 * DAY:
            break
        m = Model(ds, origin)
        days = [origin + (i + 1) * DAY for i in range(horizon)]
        pred = sum(m.base_daily(d) for d in days)
        end = day_end_utc(origin)
        mean_q = statistics.fmean(m.pool)
        fut = [v for v in ds.public_videos(short=True) if v.pub is not None and end <= v.pub < day_end_utc(days[-1])]
        pred += sum(mean_q * m.slot_total(v.pub, days) for v in fut)
        actual = sum(ds.value("shorts", "ev", d) for d in days)
        if actual > 0:
            rows.append({"origin": origin.isoformat(), "pred": round(pred), "actual": round(actual), "err": pred / actual - 1.0})
    if not rows:
        return {"rows": [], "mape": None, "bias": 0.0, "sigma": 0.3, "horizon": horizon}
    logs = [math.log(r["actual"] / r["pred"]) if r["pred"] > 0 else 0.0 for r in rows]
    clip = lambda x: max(-0.5, min(0.5, x))
    bias = clip(statistics.fmean(logs))   # 見込みが平均どれだけ低かったか(対数)。この分を補正する
    # 補正したあとの当たり具合は、その回を除いた残りの回で決めた補正で測る(自分の答えで自分を補正して良く見せない)
    resid = []
    for i, (r, x) in enumerate(zip(rows, logs)):
        others = logs[:i] + logs[i + 1:]
        b_i = clip(statistics.fmean(others)) if others else 0.0
        r["errCorrected"] = r["pred"] * math.exp(b_i) / r["actual"] - 1.0
        resid.append(x - b_i)
    sigma = max(0.1, math.sqrt(statistics.fmean([x * x for x in resid])))
    mape = statistics.fmean(abs(r["err"]) for r in rows)
    mape_c = statistics.fmean(abs(r["errCorrected"]) for r in rows)
    return {"rows": rows, "mape": mape, "mapeCorrected": mape_c, "bias": bias, "factor": math.exp(bias), "sigma": sigma, "horizon": horizon}


def boundary_utc(boundary):
    """境目の日(日本時間の 0 時)を UTC で"""
    return datetime.datetime.combine(boundary, datetime.time(0), T.JST).astimezone(T.UTC)


def pools_for(m, conf, boundary):
    """これからの動画の強さの見本を 2 通り: after = 境目以降に公開した動画 / before = 境目の前 POOL_DAYS 日の動画。
    MIN_POOL 本に足りない方は出さない(両方足りなければ直近 POOL_DAYS 日)"""
    b = boundary_utc(boundary)
    out = {}
    after = m.pool_between(b, day_end_utc(conf["ev"]))
    before = m.pool_between(b - datetime.timedelta(days=POOL_DAYS), b)
    if len(after) >= MIN_POOL:
        out["after"] = after
    if len(before) >= MIN_POOL:
        out["before"] = before
    if not out:
        out["recent"] = m.pool
    return out, {"after": len(after), "before": len(before)}


POOL_LABELS = {"after": "10/1 以降の動画の強さ", "before": "10/1 より前の動画の強さ", "recent": "直近の動画の強さ"}


def ypp_outlook(ds, conf, posts, bt=None, sims=SIMS, plan=None, boundary=None):
    """予定の本数(plan。画面の設定)と、直近 7 日・28 日平均の本数、その前後で 2/1 の見込み。
    1 本あたりの強さは境目(既定 10/1。ユーザーが本格的にサポートを始めた日)の後と前の 2 通り。
    答え合わせのずれを掛けて「伸びが続く」とする見方(A5)は、戦略が変わったので使わない(10-09 ユーザー)"""
    boundary = boundary or BOUNDARY
    bt = bt or backtest(ds, conf)
    m = Model(ds, conf["ev"])
    pools, counts = pools_for(m, conf, boundary)
    now = max(1.0, posts["perWeek28"])
    recent = max(1, posts["short7"])
    rates = {round(now), recent, max(1, round(min(now, recent) * 0.75))}
    if plan:
        rates |= {int(plan), round(plan * 1.25)}
    else:
        rates.add(round(max(now, recent) * 1.25))
    rates = sorted(rates)
    fixed = Fixed(ds, conf, m, ypp_checks())
    sigma = bt["sigma"]
    sc = []
    for r in rates:
        row = {"perWeek": r, "names": [n for n, v in (("予定", int(plan) if plan else None), ("直近7日", recent), ("28日平均", round(now))) if r == v]}
        for k, p in pools.items():
            row[k] = forecast(ds, conf, r, sigma, sims=sims, model=m, pool=p, fixed=fixed)
        sc.append(row)
    n_need = min(200, sims)

    def need_for(p):
        lo, hi = 1, 120
        if forecast(ds, conf, hi, sigma, sims=n_need, model=m, pool=p, fixed=fixed)["prob"] < 0.5:
            return None
        while lo < hi:
            mid = (lo + hi) // 2
            if forecast(ds, conf, mid, sigma, sims=n_need, model=m, pool=p, fixed=fixed)["prob"] >= 0.5:
                hi = mid
            else:
                lo = mid + 1
        return lo
    main_rate = int(plan) if plan else round(now)
    main_key = "after" if "after" in pools else next(iter(pools))
    out = {"basis": "本数は日本時間。直近 7 日 %d 本・直近 28 日 %d 本(週 %.1f 本)%s" % (
               posts["short7"], posts["short28"], posts["perWeek28"], "・予定 週 %d 本" % plan if plan else ""),
           "now": now, "recent": recent, "plan": plan, "boundary": boundary.isoformat(), "scenarios": sc,
           "pools": {k: {"label": POOL_LABELS[k], "n": len(p), "mean": statistics.fmean(p), "g7": statistics.fmean(p) * m.curve.at(WEEK_HOURS)}
                     for k, p in pools.items()},
           "poolCounts": counts, "minPool": MIN_POOL, "need50": {k: need_for(p) for k, p in pools.items()}, "backtest": bt,
           "assume": ["これからの動画の強さは、見本の動画(%s)から 1 本ずつ抜き出す(当たり・外れのばらつきはここで入る)" % "・".join(
                          "%s %d 本" % (POOL_LABELS[k], len(p)) for k, p in pools.items()),
                      "本数を増やしても 1 本あたりは変わらない(食い合いなし。食い合いがある場合は感度の表と食い合いの推定)",
                      "古い動画(日ごとの記録の無い分)は直近 28 日の減り方で減り続ける",
                      "伸び方の曲線は、記録の先(92 日以降)も伸び率が一定の割合で小さくなる",
                      "見込みの方法の誤差(幅に入れる)は、10/1 より前の 28 日の答え合わせで測ったもの(戦略が変わったので目安)",
                      "季節の波(年末年始・大きなイベント)は入っていない(チャンネルが 1 年未満で測れない)"],
           "mainRate": main_rate, "mainKey": main_key}
    p = pools[main_key]
    out["backcalc"] = backcalc(ds, conf, m, fixed, sorted({main_rate, recent, round(now)}), pools)
    out["hits"] = hit_dependence(ds, conf, m, fixed, main_rate, p, sigma, sims)
    out["sensitivity"] = sensitivity(ds, conf, m, fixed, main_rate, p, sigma, sims, pools_ref_rate(ds, conf, boundary, main_key))
    out["cannibal"] = cannibalization(ds, conf)
    out["trend"] = strength_trend(ds, conf, boundary)
    return out


def pools_ref_rate(ds, conf, boundary, key):
    """見本の動画を出していた頃の週の本数(食い合いの基準)"""
    b = boundary
    if key == "after":
        days = max(1, (T.jst_date(ds.fetched) - b).days)
        return count_posts(ds, b, T.jst_date(ds.fetched) - DAY) / days * 7.0
    lo = b - POOL_DAYS * DAY
    return count_posts(ds, lo, b - DAY) / POOL_DAYS * 7.0


def backcalc(ds, conf, m, fixed, rates, pools):
    """① 必要な数の逆算: 2/1 の判定の 90 日で 1,000 万に届くには、これから出す動画が 1 本あたり(公開 7 日の EV に直して)平均いくら要るか。
    確定した日の実際と、今ある動画・古い動画の見込み(A3・A4)を引いた残りを、予定の本数で割る。確率の計算(抜き出し・誤差)を使わない"""
    known, base = fixed.known[0], fixed.base[0]
    w = [d for d in fixed.windows[0] if d > conf["ev"]]
    g7 = m.curve.at(WEEK_HOURS)
    rows = []
    for r in rates:
        slots = m.schedule(r, max(w))
        s = sum(m.slot_total(p, w) for p in slots)
        need_q = (YPP_TARGET - known - base) / s if s > 0 else None
        row = {"perWeek": r, "videos": len(slots), "needQ": need_q, "need7": need_q * g7 if need_q is not None else None}
        for k, p in pools.items():
            row[k] = {"mean7": statistics.fmean(p) * g7, "ratio": statistics.fmean(p) / need_q if need_q else None,
                      "share": sum(1 for x in p if need_q is not None and x >= need_q) / len(p)}
        rows.append(row)
    return {"window": [min(fixed.windows[0]).isoformat(), max(fixed.windows[0]).isoformat()], "known": round(known), "base": round(base),
            "need": YPP_TARGET, "perDay": round(YPP_TARGET / YPP_WINDOW), "rows": rows}


def hit_dependence(ds, conf, m, fixed, rate, pool, sigma, sims):
    """⑤ 当たりへの頼り方: これまでの 90 日の EV のうち上位 5% の動画の割合・大当たりが無かった場合の確率・大当たり 1 本の重み"""
    d90 = [conf["ev"] - i * DAY for i in range(YPP_WINDOW)]
    per = sorted((sum(v.days.get(d, (0.0, 0.0))[0] for d in d90) for v in shorts_with_days(ds)), reverse=True)
    tot = sum(per)
    k5 = max(1, int(round(len(per) * 0.05)))
    srt = sorted(pool)
    cut = srt[int(0.95 * (len(srt) - 1))]
    trimmed = [x for x in pool if x < cut] or pool
    base = forecast(ds, conf, rate, sigma, sims=sims, model=m, pool=pool, fixed=fixed)
    no_hits = forecast(ds, conf, rate, sigma, sims=sims, model=m, pool=trimmed, fixed=fixed)
    w = [d for d in fixed.windows[0] if d > conf["ev"]]
    slots = m.schedule(rate, max(w))
    avg_s = statistics.fmean([m.slot_total(p, w) for p in slots]) if slots else 0.0
    big = srt[int(0.99 * (len(srt) - 1))]
    return {"videos": len(per), "top5": sum(per[:k5]) / tot if tot else None, "top5n": k5,
            "prob": base["prob"], "probNoHits": no_hits["prob"], "p50": base["p50"], "p50NoHits": no_hits["p50"],
            "bigOne": round(big * avg_s), "typicalOne": round(statistics.median(pool) * avg_s), "rate": rate}


def sensitivity(ds, conf, m, fixed, rate, pool, sigma, sims, ref):
    """④ 感度の表: 仮定を 1 つずつ動かしたときの 2/1 に届く確率"""
    run = lambda **kw: forecast(ds, conf, kw.pop("rate", rate), kw.pop("sigma", sigma), sims=sims, model=m, pool=pool,
                                fixed=kw.pop("fx", fixed), **kw)["prob"]
    rows = [("基準(予定の本数・見本どおり)", run())]
    rows += [("1 本あたりの強さ −20%", run(strength=0.8)), ("1 本あたりの強さ +20%", run(strength=1.2)),
             ("本数 週 %d 本" % max(1, rate - 8), run(rate=max(1, rate - 8))), ("本数 週 %d 本" % (rate + 7), run(rate=rate + 7)),
             ("食い合い 小(e=0.3)", run(e=0.3, ref=ref)), ("食い合い 大(e=0.5)", run(e=0.5, ref=ref))]
    lam2 = min(0.1, max(0.01, m.lam * 2))
    fx2 = Fixed(ds, conf, m, ypp_checks(), lam2)
    rows += [("古い動画の減りが速い(1 日 %.1f%%)" % (lam2 * 100), run(lam=lam2, fx=fx2)),
             ("方法の誤差を 0 にする", run(sigma=0.0)), ("方法の誤差を 2 倍にする", run(sigma=sigma * 2))]
    base = rows[0][1]
    return {"rows": [{"name": n, "prob": p, "diff": p - base} for n, p in rows], "ref": ref, "rate": rate}


def cannibalization(ds, conf, days=120):
    """A2 食い合いの推定(本数を下げて試してはいない = これまでの実績から)。
    1 本ずつの公開 72 時間の EV を、その週(日本時間)の中央値で割った値の対数を、その日の本数の対数で回帰した傾き。e = −傾き。
    週の中で比べるので、チャンネル全体の調子の変化は除かれる。日の本数の幅が狭いと推定はぶれる"""
    end = day_end_utc(conf["ev"])
    lo = end - datetime.timedelta(days=days)
    vids = [(v, video_metric(v, conf, 72)) for v in ds.public_videos(short=True) if lo <= v.pub < end]
    vids = [(v, x) for v, x in vids if x and x > 0]
    per_day = {}
    for v in ds.public_videos(short=True):
        per_day[v.pub_jst.date()] = per_day.get(v.pub_jst.date(), 0) + 1
    weeks = {}
    for v, x in vids:
        weeks.setdefault(v.pub_jst.date().isocalendar()[:2], []).append(x)
    pts = []
    for v, x in vids:
        wk = weeks[v.pub_jst.date().isocalendar()[:2]]
        if len(wk) >= 5:
            pts.append((math.log(per_day[v.pub_jst.date()]), math.log(x / statistics.median(wk)), v.pub_jst.date()))
    if len(pts) < 30 or len({p[0] for p in pts}) < 3:
        return {"e": None, "n": len(pts), "note": "日の本数の違いが少なく、推定できません"}

    def slope(ps):
        mx, my = statistics.fmean(p[0] for p in ps), statistics.fmean(p[1] for p in ps)
        sxx = sum((p[0] - mx) ** 2 for p in ps)
        return sum((p[0] - mx) * (p[1] - my) for p in ps) / sxx if sxx > 0 else 0.0
    b = slope(pts)
    by_day = {}
    for p in pts:
        by_day.setdefault(p[2], []).append(p)
    keys = sorted(by_day)
    rnd = random.Random(7)
    boots = []
    for _ in range(300):   # 日ごとに抜き出し直す(同じ日の動画はまとめて)
        sample = [p for _k in keys for p in by_day[rnd.choice(keys)]]
        boots.append(-slope(sample))
    boots.sort()
    counts = sorted({math.exp(p[0]) for p in pts})
    return {"e": -b, "lo": boots[int(0.1 * len(boots))], "hi": boots[int(0.9 * len(boots))], "n": len(pts), "days": len(keys),
            "perDay": [int(round(c)) for c in counts], "note": "これまでの投稿の実績から(本数を下げて試してはいない)。80% の幅"}


def strength_trend(ds, conf, boundary, months=6):
    """② 1 本あたりの強さの推移: 公開した月(日本時間)ごとと、境目以降の公開 7 日の EV(平均と中央値・平均の 80% の幅)"""
    rnd = random.Random(11)
    end = day_end_utc(conf["ev"])
    items = [(v, video_metric(v, conf, WEEK_HOURS)) for v in ds.public_videos(short=True) if v.pub < end]
    items = [(v, x) for v, x in items if x is not None]
    first = T.add_months(conf["ev"].replace(day=1), -(months - 1))

    def summ(xs, name):
        boots = sorted(statistics.fmean(rnd.choice(xs) for _ in xs) for _ in range(300))
        return {"name": name, "n": len(xs), "mean": statistics.fmean(xs), "median": statistics.median(xs),
                "lo": boots[int(0.1 * len(boots))], "hi": boots[int(0.9 * len(boots))]}
    rows = []
    m = first
    while m <= conf["ev"]:
        nxt = T.add_months(m, 1)
        xs = [x for v, x in items if m <= v.pub_jst.date() < nxt]
        if len(xs) >= MIN_GROUP:
            rows.append(summ(xs, m.strftime("%Y-%m")))
        m = nxt
    xs = [x for v, x in items if v.pub_jst.date() >= boundary]
    after = summ(xs, "%s 以降" % T.md(boundary)) if len(xs) >= MIN_GROUP else None
    xs = [x for v, x in items if boundary - 28 * DAY <= v.pub_jst.date() < boundary]
    before = summ(xs, "その前の 28 日") if len(xs) >= MIN_GROUP else None
    return {"rows": rows, "after": after, "before": before, "metric": "公開 7 日の EV(確定したもの)"}


def ledger_row(ds, conf, outlook):
    """⑥ 見込みの記録の 1 行: 今日の見込み(28 日後と 2/1 の 90 日の合計)。あとで実際と比べる"""
    target = conf["ev"] + 28 * DAY
    m = Model(ds, conf["ev"])
    pools, _ = pools_for(m, conf, datetime.date.fromisoformat(outlook["boundary"]))
    p = pools[outlook["mainKey"]]
    f = forecast(ds, conf, outlook["mainRate"], outlook["backtest"]["sigma"], sims=200, model=m, pool=p, extra=[target + DAY])
    return {"made": conf["ev"].isoformat(), "target": target.isoformat(), "p50": f["extra"][(target + DAY).isoformat()],
            "rate": outlook["mainRate"], "pool": outlook["mainKey"], "ypp50": f["p50"], "prob": f["prob"]}


def ledger_eval(ds, conf, rows):
    """記録した見込みのうち、目標の日が確定したものを実際と比べる"""
    out = []
    for r in rows:
        t = datetime.date.fromisoformat(r["target"])
        if t <= conf["ev"]:
            actual = sum(ds.value("shorts", "ev", t - i * DAY) for i in range(YPP_WINDOW))
            out.append(dict(r, actual=round(actual), err=r["p50"] / actual - 1 if actual else None))
    return {"evaluated": out, "pending": len(rows) - len(out), "total": len(rows)}


# ------------------------------------------------------------------ 初動(公開からの伸び)

def bench(ds, conf, hours, days=90):
    """比べる相手: 確定の日から見て hours 時間以上たったショートのうち、直近 days 日に公開したもの。-> 値の昇順"""
    end = day_end_utc(conf["ev"])
    lo = end - datetime.timedelta(days=days)
    out = []
    for v in shorts_with_days(ds):
        if lo <= v.pub and (end - v.pub).total_seconds() / 3600.0 >= hours:
            c = cum_at(points(v, conf["ev"]), hours)
            if c is not None:
                out.append(c)
    return sorted(out)


def pct(sorted_vals, x):
    """x より小さい値の割合(0〜1)"""
    if not sorted_vals:
        return None
    lo = sum(1 for y in sorted_vals if y < x)
    eq = sum(1 for y in sorted_vals if y == x)
    return (lo + eq / 2.0) / len(sorted_vals)


def label(p):
    if p is None:
        return "判定前"
    for th, name in LABELS:
        if p >= th:
            return name
    return LABELS[-1][1]


def launches(ds, conf, days=7):
    """直近 days 日(日本時間)に公開したショートの初動。確定した経過時間のうち 72・48・24 時間の大きいほうで、過去の同じ時間と比べた順位"""
    end = day_end_utc(conf["ev"])
    benches = {h: bench(ds, conf, h) for h in LAUNCH_HOURS}
    vtrs = sorted(v.vtr for v in ds.public_videos(short=True) if v.vtr and v.pub and v.pub >= end - datetime.timedelta(days=90))
    today = T.jst_date(ds.fetched)
    rows = []
    for v in ds.public_videos(short=True):
        if v.pub_jst.date() < today - (days - 1) * DAY:
            continue
        hrs = (end - v.pub).total_seconds() / 3600.0
        at = max([h for h in LAUNCH_HOURS if h <= hrs], default=None)
        row = {"id": v.id, "title": v.short_title(), "member": v.member, "pub": v.pub_jst.strftime("%m/%d %H:%M"),
               "vtr": v.vtr, "vtrPct": pct(vtrs, v.vtr) if v.vtr else None, "hours": at}
        if at is not None and covered(v):
            val = cum_at(points(v, conf["ev"]), at)
            p = pct(benches[at], val)
            row.update(value=round(val), pct=p, label=label(p), final=at == 72, n=len(benches[at]))
        else:   # まだ 24 時間ぶん確定していない: 速報(確定していない日も含めた今の累計)。順位は付けない
            row.update(value=round(sum(x[0] for x in v.days.values())), pct=None, label="判定前", final=False, speculative=True,
                       n=len(benches[24]))
        rows.append(row)
    rows.sort(key=lambda r: r["pub"])
    return {"rows": rows, "rule": "公開から 72 時間(足りなければ 48・24 時間)の EV を、直近 90 日に公開したショートの同じ時間と比べた順位。"
                                  "上位 20% = 当たり・20〜50% = 中間・50〜80% = 伸び悩み・下位 20% = 外れ",
            "benchN": {str(h): len(b) for h, b in benches.items()}}


# ------------------------------------------------------------------ 異変

def anomalies(ds, conf, weeks=8):
    """直近 7 日を、その前の weeks 週(7 日ずつ)の範囲と比べる。範囲の外なら印。
    - EV ÷ 再生回数(ショート。冒頭で離れる人が増えると下がる)
    - 公開 24 時間の EV の中央値(その週に公開したショート)
    - 視聴を継続 % の中央値(その週に公開したショート)"""
    def win(i):
        e = conf["ev"] - 7 * i * DAY
        return [e - j * DAY for j in range(7)]
    vids = shorts_with_days(ds)
    allv = ds.public_videos(short=True)

    def stats(days):
        ev = sum(ds.value("shorts", "ev", d) for d in days)
        vw = sum(ds.value("shorts", "views", d) for d in days)
        lo, hi = T.pt_day_start_utc(days[-1]), day_end_utc(days[0])
        l24 = [cum_at(points(v, conf["ev"]), 24) for v in vids if lo <= v.pub < hi]
        l24 = [x for x in l24 if x is not None]
        vt = [v.vtr for v in allv if v.vtr and lo <= v.pub < hi]
        return {"ratio": ev / vw if vw else None, "launch24": statistics.median(l24) if l24 else None,
                "vtr": statistics.median(vt) if vt else None, "n": len(vt)}
    cur = stats(win(0))
    prev = [stats(win(i)) for i in range(1, weeks + 1)]
    names = {"ratio": "EV ÷ 再生回数", "launch24": "公開 24 時間の EV の中央値", "vtr": "視聴を継続 % の中央値"}
    out = []
    for k, name in names.items():
        vals = [p[k] for p in prev if p[k] is not None]
        if cur[k] is None or len(vals) < 4:
            continue
        lo, hi = min(vals), max(vals)
        state = "low" if cur[k] < lo else "high" if cur[k] > hi else "ok"
        out.append({"key": k, "name": name, "now": cur[k], "min": lo, "max": hi, "median": statistics.median(vals), "state": state})
    return {"items": out, "weeks": weeks, "through": conf["ev"].isoformat()}


# ------------------------------------------------------------------ 日・週・月の集計

def totals(ds, days, conf):
    """その日々の合計(ショート・長尺の EV・再生・収益・登録者)。確定していない日の数も"""
    t = {"shortEv": 0.0, "longEv": 0.0, "shortViews": 0.0, "rev": 0.0, "subs": 0.0}
    for d in days:
        t["shortEv"] += ds.value("shorts", "ev", d)
        t["longEv"] += ds.value("long", "ev", d)
        t["shortViews"] += ds.value("shorts", "views", d)
        t["rev"] += ds.value("total", "rev", d)
        t["subs"] += ds.value("total", "subs", d)
    t["evUnconfirmed"] = sum(1 for d in days if d > conf["ev"])
    t["revUnconfirmed"] = sum(1 for d in days if conf["rev"] is None or d > conf["rev"])
    return {k: (round(v, 2) if k == "rev" else round(v)) if isinstance(v, float) else v for k, v in t.items()}


def day_report_numbers(ds, conf):
    """確定した日の数字と 7 日平均との比(日報の 1 行)"""
    d = conf["ev"]
    ev = ds.value("shorts", "ev", d)
    avg7 = sum(ds.value("shorts", "ev", d - (i + 1) * DAY) for i in range(7)) / 7.0
    out = {"day": d.isoformat(), "shortEv": round(ev), "vsAvg7": ev / avg7 - 1 if avg7 else None,
           "subs": round(ds.value("total", "subs", d))}
    r = conf["rev"]
    if r:
        rv = ds.value("total", "rev", r)
        ravg = sum(ds.value("total", "rev", r - (i + 1) * DAY) for i in range(7)) / 7.0
        out.update(revDay=r.isoformat(), rev=round(rv, 2), revVsAvg7=rv / ravg - 1 if ravg else None)
    return out


def video_metric(v, conf, hours):
    if not covered(v):
        return None
    if (day_end_utc(conf["ev"]) - v.pub).total_seconds() / 3600.0 < hours:
        return None
    return cum_at(points(v, conf["ev"]), hours)


def group_table(rows, key_fn, order=None, min_n=MIN_GROUP):
    """rows = [(video, 値)] → 群ごとの本数・中央値・全体の中央値との比"""
    allv = [x for _, x in rows]
    overall = statistics.median(allv) if allv else None
    groups = {}
    for v, x in rows:
        for k in (key_fn(v) or []):
            groups.setdefault(k, []).append(x)
    out = []
    for k, xs in groups.items():
        if len(xs) < min_n:
            continue
        med = statistics.median(xs)
        out.append({"key": k, "n": len(xs), "median": round(med), "ratio": med / overall if overall else None})
    if order:
        out.sort(key=lambda r: order.index(r["key"]) if r["key"] in order else 99)
    else:
        out.sort(key=lambda r: -r["median"])
    return {"rows": out, "overall": round(overall) if overall is not None else None, "n": len(rows)}


def length_band(v):
    for lo, hi, name in LENGTH_BANDS:
        if lo <= v.length <= hi:
            return [name]
    return []


def hour_band(v):
    h = v.pub_jst.hour
    return [name for lo, hi, name in HOUR_BANDS if lo <= h < hi]


def week_report(ds, conf, posts, outlook=None):
    """週報: 確定した最後の日曜(PT の日)までの 1 週(月〜日)"""
    end = conf["ev"] - ((conf["ev"].weekday() + 1) % 7) * DAY   # その日以前の日曜
    days = [end - i * DAY for i in range(7)]
    prev = [d - 7 * DAY for d in days]
    four = [d - 7 * k * DAY for k in range(1, 5) for d in days]
    cur, pv = totals(ds, days, conf), totals(ds, prev, conf)
    f4 = totals(ds, four, conf)
    f4 = {k: (v / 4.0 if isinstance(v, (int, float)) and k not in ("evUnconfirmed", "revUnconfirmed") else v) for k, v in f4.items()}
    start_jst, end_jst = days[-1], days[0]   # 本数は同じ日付を日本時間で数える
    week_posts = {"short": count_posts(ds, start_jst, end_jst), "long": count_posts(ds, start_jst, end_jst, short=False),
                  "prevShort": count_posts(ds, start_jst - 7 * DAY, end_jst - 7 * DAY)}
    # その週に公開したショートの 72 時間(確定したものだけ)と、直近 28 日の配信者別・長さ別
    lo = T.pt_day_start_utc(days[-1])
    hi = day_end_utc(days[0])
    b72 = bench(ds, conf, 72)
    wk = []
    for v in ds.public_videos(short=True):
        if lo <= v.pub < hi:
            x = video_metric(v, conf, 72)
            wk.append({"id": v.id, "title": v.short_title(), "member": v.member, "value": round(x) if x is not None else None,
                       "pct": pct(b72, x) if x is not None else None, "vtr": v.vtr})
    wk.sort(key=lambda r: -(r["value"] or -1))
    rec = []
    lo28 = hi - datetime.timedelta(days=28)
    for v in ds.public_videos(short=True):
        if lo28 <= v.pub < hi:
            x = video_metric(v, conf, 72)
            if x is not None:
                rec.append((v, x))
    vt_now = [v.vtr for v in ds.public_videos(short=True) if v.vtr and lo <= v.pub < hi]
    vt_prev = [v.vtr for v in ds.public_videos(short=True) if v.vtr and lo - datetime.timedelta(days=28) <= v.pub < lo]
    return {"start": days[-1].isoformat(), "end": end.isoformat(), "totals": cur, "prev": pv, "avg4": f4, "posts": week_posts,
            "videos": wk, "hits": sum(1 for r in wk if r["pct"] is not None and r["pct"] >= 0.8),
            "byMember": group_table(rec, lambda v: v.members[:1]), "byLength": group_table(rec, length_band, [b[2] for b in LENGTH_BANDS]),
            "vtr": {"now": statistics.median(vt_now) if vt_now else None, "prev4": statistics.median(vt_prev) if vt_prev else None},
            "metric": "公開 72 時間の EV(確定したもの)", "outlook": outlook}


def effect_table(ds, conf, end_day, days=90, hours=WEEK_HOURS):
    """効き目の表(4-4): 直近 days 日に公開したショートの 7 日の EV を、要因ごとに比べる。
    群ごとに本数・中央値・全体との比・期間の前半と後半で同じ向きか・同じ配信者の中で比べた比"""
    hi = day_end_utc(end_day)
    lo = hi - datetime.timedelta(days=days)
    rows = []
    for v in ds.public_videos(short=True):
        if lo <= v.pub < hi:
            x = video_metric(v, conf, hours)
            if x is not None:
                rows.append((v, x))
    rows.sort(key=lambda r: r[0].pub)
    by_day = {}
    for v in ds.public_videos(short=True):
        by_day.setdefault(v.pub_jst.date(), []).append(v)
    pubs = sorted(v.pub for v in ds.public_videos(short=True))

    def per_day(v):
        n = len(by_day.get(v.pub_jst.date(), []))
        return ["1〜3 本の日"] if n <= 3 else ["4〜5 本の日"] if n <= 5 else ["6 本以上の日"]

    def gap(v):
        prev = [p for p in pubs if p < v.pub]
        if not prev:
            return []
        h = (v.pub - prev[-1]).total_seconds() / 3600.0
        return ["前の投稿から 2 時間未満"] if h < 2 else ["2〜4 時間"] if h < 4 else ["4〜8 時間"] if h < 8 else ["8 時間以上"]

    factors = [("配信者", lambda v: v.members[:1], None),
               ("コラボ", lambda v: ["2 人以上"] if len(v.members) >= 2 else ["1 人"] if v.members else [], None),
               ("長さ", length_band, [b[2] for b in LENGTH_BANDS]),
               ("投稿の時刻(日本時間)", hour_band, [b[2] for b in HOUR_BANDS]),
               ("曜日(日本時間)", lambda v: [T.WEEKDAYS[v.pub_jst.weekday()] + "曜"], [c + "曜" for c in T.WEEKDAYS]),
               ("その日の本数", per_day, ["1〜3 本の日", "4〜5 本の日", "6 本以上の日"]),
               ("前の投稿からの間隔", gap, ["前の投稿から 2 時間未満", "2〜4 時間", "4〜8 時間", "8 時間以上"])]
    half = len(rows) // 2
    first, second = rows[:half], rows[half:]
    mem_med = {}
    for v, x in rows:
        if v.member:
            mem_med.setdefault(v.member, []).append(x)
    mem_med = {k: statistics.median(xs) for k, xs in mem_med.items() if len(xs) >= MIN_GROUP}
    out = []
    for name, fn, order in factors:
        t = group_table(rows, fn, order)
        a, b = group_table(first, fn, order, 1), group_table(second, fn, order, 1)
        ra = {r["key"]: r["ratio"] for r in a["rows"]}
        rb = {r["key"]: r["ratio"] for r in b["rows"]}
        for r in t["rows"]:
            x, y = ra.get(r["key"]), rb.get(r["key"])
            r["stable"] = None if x is None or y is None else (x - 1) * (y - 1) > 0
            if name != "配信者":
                rel = [xv / mem_med[v.member] for v, xv in rows if v.member in mem_med and r["key"] in (fn(v) or [])]
                r["withinMember"] = statistics.median(rel) if len(rel) >= MIN_GROUP else None
        spread = max((r["ratio"] for r in t["rows"]), default=1) - min((r["ratio"] for r in t["rows"]), default=1)
        out.append({"factor": name, "rows": t["rows"], "spread": spread, "overall": t["overall"]})
    out.sort(key=lambda f: -f["spread"])
    return {"factors": out, "n": len(rows), "from": (end_day - (days - 1) * DAY).isoformat(), "to": end_day.isoformat(),
            "metric": "公開 7 日(168 時間)の EV"}


def month_report(ds, conf, outlook=None):
    """月報: 確定した最後の日までに終わった最後の月"""
    first_of_this = conf["ev"].replace(day=1)
    if (conf["ev"] + DAY).day == 1:   # 月末まで確定していればその月
        first_of_this = T.add_months(first_of_this, 1)
    m0 = T.add_months(first_of_this, -1)
    m1 = first_of_this - DAY
    days = [m0 + i * DAY for i in range((m1 - m0).days + 1)]
    p0 = T.add_months(m0, -1)
    pdays = [p0 + i * DAY for i in range((m0 - p0).days)]
    out = {"month": m0.strftime("%Y-%m"), "start": m0.isoformat(), "end": m1.isoformat(), "totals": totals(ds, days, conf),
           "prev": totals(ds, pdays, conf), "posts": {"short": count_posts(ds, m0, m1), "long": count_posts(ds, m0, m1, short=False),
                                                       "prevShort": count_posts(ds, p0, m0 - DAY)},
           "effects": effect_table(ds, conf, m1), "outlook": outlook}
    weeks = []
    d = m0 - m0.weekday() * DAY
    while d <= m1:
        wd = [x for x in (d + i * DAY for i in range(7)) if m0 <= x <= m1]
        weeks.append({"start": wd[0].isoformat(), "end": wd[-1].isoformat(), "shortEv": round(sum(ds.value("shorts", "ev", x) for x in wd)),
                      "posts": count_posts(ds, wd[0], wd[-1])})
        d += 7 * DAY
    out["weeks"] = weeks
    return out


def check(ds, conf, posts):
    """食い違いの検査(12-4 の 6)。-> [警告の文]"""
    out = list(ds.warnings)
    # 形式別の合計が全体と大きく違わないか(Studio の値の取り違え)
    for d in [conf["ev"] - i * DAY for i in range(7)]:
        s = ds.value("shorts", "ev", d) + ds.value("long", "ev", d)
        t = ds.value("total", "ev", d)
        if t > 0 and abs(s - t) / t > 0.05:
            out.append("%s のショート + 長尺の EV が全体と 5%% 以上違います(%d と %d)" % (d.isoformat(), s, t))
            break
    # 本数: 動画の一覧の公開日で数えた本数と、日ごとの記録のある動画の本数
    lo = T.jst_date(ds.fetched) - 7 * DAY
    a = count_posts(ds, lo, T.jst_date(ds.fetched) - DAY)
    b = sum(1 for v in shorts_with_days(ds) if lo <= v.pub_jst.date() <= T.jst_date(ds.fetched) - DAY)
    if a != b:
        out.append("直近 7 日のショートの本数が、動画の一覧(%d 本)と日ごとの記録(%d 本)で違います" % (a, b))
    if (ds.fetched - day_end_utc(conf["ev"])).total_seconds() > 4 * 86400:
        out.append("データが古い可能性があります(確定の日から 4 日以上)")
    return out


def daily(ds, sims=SIMS, plan=None, boundary=None):
    """日報に要るものを全部(週報・月報も同じ部品で作る)。plan = 予定の週の本数・boundary = 境目の日(画面の設定)"""
    conf = confirmed(ds)
    posts = posts_summary(ds)
    bt = backtest(ds, conf)
    out = {"fetched": ds.fetched.isoformat(), "fetchedJst": ds.fetched.astimezone(T.JST).strftime("%Y-%m-%d %H:%M"),
           "dateJst": ds.date_jst, "conf": {k: (v.isoformat() if v else None) for k, v in conf.items()},
           "posts": posts, "ypp": ypp_now(ds, conf), "outlook": ypp_outlook(ds, conf, posts, bt, sims=sims, plan=plan, boundary=boundary),
           "launch": launches(ds, conf), "anomaly": anomalies(ds, conf), "day": day_report_numbers(ds, conf)}
    out["warnings"] = check(ds, conf, posts)
    first = conf["ev"] - 40 * DAY
    out["series"] = {d.isoformat(): round(ds.value("shorts", "ev", d)) for d in ds.days if d >= first}
    return out


KINDS = ("daily", "weekly", "monthly")


def report(ds, kind="daily", sims=SIMS, plan=None, boundary=None, ledger=None):
    """日報(daily)・週報(weekly)・月報(monthly)の計算。どれも日報の中身(YPP の見込みと角度・初動・異変)を含む。
    日報は「結果の指標と当たり率」(直近 90 日)、週報は直近 28 日・月報は直近 90 日の「中身の分析」と境目の前後の比較。
    ledger = これまでの見込みの記録(service が持つ。目標の日が確定したものを答え合わせする)"""
    if kind not in KINDS:
        raise ValueError("kind は daily・weekly・monthly のどれか")
    boundary = boundary or BOUNDARY
    r = daily(ds, sims=sims, plan=plan, boundary=boundary)
    r["kind"] = kind
    conf = confirmed(ds)
    if ledger:
        r["ledger"] = ledger_eval(ds, conf, ledger)
    if kind == "daily":   # 日報には結果の指標と当たり率だけ(10-09 ユーザー)
        r["outcomes"] = deep_dive(ds, conf, conf["ev"], days=90)
    elif kind == "weekly":
        r["week"] = week_report(ds, conf, r["posts"])
        r["deep"] = deep_dive(ds, conf, datetime.date.fromisoformat(r["week"]["end"]), days=28)
        r["regime"] = regime_compare(ds, conf, boundary)
    else:
        r["month"] = month_report(ds, conf)
        r["deep"] = deep_dive(ds, conf, datetime.date.fromisoformat(r["month"]["end"]), days=90)
        r["regime"] = regime_compare(ds, conf, boundary)
    return r


def regime_compare(ds, conf, boundary):
    """境目(10/1)の前と後の比較: 同じ日数ずつ。チャンネルの日の値(PT の日)・本数(日本時間)・1 本あたり(公開 72 時間の EV)・当たり・継続 %。
    1 本あたりの比には、抜き出し直しで 80% の幅を付ける(日数が少ないうちは幅が広い)"""
    after_days = [d for d in ds.days if boundary <= d <= conf["ev"]]
    n = len(after_days)
    if n < 3:
        return {"n": n, "note": "境目から確定した日がまだ %d 日です(3 日から比べます)" % n}
    before_days = [boundary - (i + 1) * DAY for i in range(n)]

    def chan(days, kind, metric):
        return sum(ds.value(kind, metric, d) for d in days) / len(days)
    rev_after = [d for d in after_days if conf["rev"] and d <= conf["rev"]]
    rev_before = [boundary - (i + 1) * DAY for i in range(len(rev_after))]
    end = day_end_utc(conf["ev"])
    b = boundary_utc(boundary)
    hit_line = bench(ds, conf, 72)
    top = hit_line[int(0.8 * (len(hit_line) - 1))] if hit_line else None

    def vids(lo, hi):
        xs = [(v, video_metric(v, conf, 72)) for v in ds.public_videos(short=True) if lo <= v.pub < hi]
        return [(v, x) for v, x in xs if x is not None]
    va = vids(b, end)
    vb = vids(b - datetime.timedelta(days=n), b)

    def side(days, rdays, vs, start, stop):
        xs = [x for _, x in vs]
        vt = [v.vtr for v, _ in vs if v.vtr]
        return {"shortEv": chan(days, "shorts", "ev"), "rev": chan(rdays, "total", "rev") if rdays else None,
                "subs": chan(days, "total", "subs"), "posts": count_posts(ds, start, stop) / float((stop - start).days + 1),
                "n": len(xs), "mean72": statistics.fmean(xs) if xs else None, "median72": statistics.median(xs) if xs else None,
                "hitRate": sum(1 for x in xs if top is not None and x >= top) / len(xs) if xs else None,
                "vtr": statistics.median(vt) if vt else None}
    a = side(after_days, rev_after, va, boundary, min(T.jst_date(ds.fetched) - DAY, boundary + (n - 1) * DAY))
    bb = side(before_days, rev_before, vb, boundary - n * DAY, boundary - DAY)
    ci = None
    if len(va) >= 3 and len(vb) >= 3:
        rnd = random.Random(5)
        xa, xb = [x for _, x in va], [x for _, x in vb]
        rs = sorted(statistics.fmean(rnd.choice(xa) for _ in xa) / statistics.fmean(rnd.choice(xb) for _ in xb) for _ in range(400))
        ci = [rs[int(0.1 * len(rs))], rs[int(0.9 * len(rs))]]
    return {"n": n, "boundary": boundary.isoformat(), "after": a, "before": bb, "meanRatioCI": ci,
            "afterRange": [after_days[0].isoformat(), after_days[-1].isoformat()],
            "beforeRange": [before_days[-1].isoformat(), before_days[0].isoformat()],
            "note": "1 本あたりは公開 72 時間の EV(確定したもの)。当たり = 直近 90 日の上位 20%。日の値は太平洋時間・本数は日本時間"}


# ------------------------------------------------------------------ 中身の分析(ページを足す。ユーザーの希望 10-09)

VTR_BANDS = ((0, 55, "〜55%"), (55, 60, "55〜60%"), (60, 65, "60〜65%"), (65, 70, "65〜70%"), (70, 75, "70〜75%"), (75, 101, "75%〜"))
AWP_BANDS = ((0, 80, "〜80%"), (80, 95, "80〜95%"), (95, 110, "95〜110%"), (110, 130, "110〜130%"), (130, 10**6, "130%〜"))
LOOP_BANDS = ((0, 1.8, "〜1.8"), (1.8, 2.1, "1.8〜2.1"), (2.1, 2.4, "2.1〜2.4"), (2.4, 2.8, "2.4〜2.8"), (2.8, 10**6, "2.8〜"))


def _band(x, bands):
    if x is None:
        return []
    for lo, hi, name in bands:
        if lo <= x < hi:
            return [name]
    return []


def _hit_table(rows, key_fn, order, top):
    """群ごとの本数・中央値・当たり(期間の上位 20%)の割合"""
    groups = {}
    for v, x in rows:
        for k in key_fn(v) or []:
            groups.setdefault(k, []).append(x)
    out = []
    for k in order:
        xs = groups.get(k) or []
        if xs:
            out.append({"key": k, "n": len(xs), "median": round(statistics.median(xs)), "hitRate": sum(1 for x in xs if x >= top) / len(xs)})
    return out


def deep_dive(ds, conf, end_day, days=90, hours=WEEK_HOURS):
    """結果の指標と当たり率・登録・収益・当たりへの頼り具合・配信者の勢い・題名・伸びの続き方・長尺"""
    hi = day_end_utc(end_day)
    lo = hi - datetime.timedelta(days=days)
    shorts = [v for v in ds.public_videos(short=True) if lo <= v.pub < hi]
    rows = [(v, x) for v in shorts for x in [video_metric(v, conf, hours)] if x is not None]
    if len(rows) < 10:   # 7 日たった動画が少ない(週報の 28 日など)ときは 72 時間で
        hours = 72
        rows = [(v, x) for v in shorts for x in [video_metric(v, conf, hours)] if x is not None]
    vals = sorted(x for _, x in rows)
    top = vals[int(0.8 * (len(vals) - 1))] if vals else 0
    out = {"from": (end_day - (days - 1) * DAY).isoformat(), "to": end_day.isoformat(), "n": len(rows), "hours": hours,
           "hitLine": round(top) if vals else None}
    # 1. 結果の指標(視聴を継続・平均視聴率・再生 ÷ EV)の帯ごとの当たり率
    loop = lambda v: v.views / v.ev if v.ev > 0 else None
    out["outcomes"] = [
        {"name": "視聴を継続 %", "rows": _hit_table(rows, lambda v: _band(v.vtr, VTR_BANDS), [b[2] for b in VTR_BANDS], top)},
        {"name": "平均視聴率 %(100% 超 = 見直し・ループ)", "rows": _hit_table(rows, lambda v: _band(v.awp, AWP_BANDS), [b[2] for b in AWP_BANDS], top)},
        {"name": "再生 ÷ EV(1 回の EV あたりの再生。大きいほどループ・すぐ離れる再生が多い)",
         "rows": _hit_table(rows, lambda v: _band(loop(v), LOOP_BANDS), [b[2] for b in LOOP_BANDS], top)}]
    # 2. 登録につながる動画(EV 1 万あたりの登録者。公開からの累計)
    conv = {}
    for v in shorts:
        if v.ev >= 1000:
            for mname in v.members[:1] or ["(配信者なし)"]:
                conv.setdefault(mname, []).append(v.subs / v.ev * 10000)
    allc = [c for cs in conv.values() for c in cs]
    out["subs"] = {"overall": statistics.median(allc) if allc else None,
                   "rows": sorted(({"key": k, "n": len(cs), "per10k": statistics.median(cs)} for k, cs in conv.items() if len(cs) >= MIN_GROUP),
                                  key=lambda r: -r["per10k"])}
    # 3. 収益: EV 1,000 あたりの収益(週ごと・確定した日だけ)と、配信者別(動画の累計)
    weeks = []
    if conf["rev"]:
        e = conf["rev"]
        for i in range(8):
            wd = [e - (7 * i + j) * DAY for j in range(7)]
            ev = sum(ds.value("shorts", "ev", d) for d in wd)
            rv = sum(ds.value("shorts", "rev", d) for d in wd)
            weeks.append({"end": wd[0].isoformat(), "rpm": rv / ev * 1000 if ev else None, "rev": round(rv, 2), "ev": round(ev)})
    rpm_m = {}
    for v in shorts:
        if v.ev >= 3000:
            for mname in v.members[:1] or ["(配信者なし)"]:
                rpm_m.setdefault(mname, []).append(v.rev / v.ev * 1000)
    out["revenue"] = {"weeks": list(reversed(weeks)),
                      "byMember": sorted(({"key": k, "n": len(xs), "rpm": statistics.median(xs)} for k, xs in rpm_m.items() if len(xs) >= MIN_GROUP),
                                         key=lambda r: -r["rpm"])}
    # 4. 当たりへの頼り具合: 直近 28 日の EV(日ごとの記録のある動画)のうち上位の動画の割合
    d28 = [conf["ev"] - i * DAY for i in range(28)]
    per = sorted((sum(v.days.get(d, (0.0, 0.0))[0] for d in d28) for v in shorts_with_days(ds)), reverse=True)
    tot = sum(per)
    k10 = max(1, len(per) // 10)
    out["concentration"] = {"videos": len(per), "top5": sum(per[:5]) / tot if tot else None, "top10pct": sum(per[:k10]) / tot if tot else None,
                            "channel": sum(ds.value("shorts", "ev", d) for d in d28)}
    # 5. 配信者の勢い: 期間の後半と前半の中央値の比
    half = lo + (hi - lo) / 2
    a, b = {}, {}
    for v, x in rows:
        if v.member:
            (b if v.pub >= half else a).setdefault(v.member, []).append(x)
    out["momentum"] = sorted(({"key": k, "nOld": len(a[k]), "nNew": len(b[k]), "old": round(statistics.median(a[k])), "new": round(statistics.median(b[k])),
                               "ratio": statistics.median(b[k]) / statistics.median(a[k]) if statistics.median(a[k]) else None}
                              for k in a if k in b and len(a[k]) >= 2 and len(b[k]) >= 2), key=lambda r: -(r["ratio"] or 0))
    # 6. 題名: 見出し(【】)の長さと、よく使う見出し
    def head(v):
        m = v.short_title()
        return m if v.title.lstrip().startswith("【") else ""
    hl = lambda v: ["見出し 1〜2 文字"] if 0 < len(head(v)) <= 2 else ["3〜4 文字"] if 3 <= len(head(v)) <= 4 else ["5 文字以上"] if len(head(v)) >= 5 else []
    out["titleLength"] = _hit_table(rows, hl, ["見出し 1〜2 文字", "3〜4 文字", "5 文字以上"], top)
    words = {}
    for v, x in rows:
        h = head(v)
        if h:
            words.setdefault(h, []).append(x)
    overall = statistics.median(vals) if vals else None
    out["titleWords"] = sorted(({"key": k, "n": len(xs), "median": round(statistics.median(xs)), "ratio": statistics.median(xs) / overall if overall else None}
                                for k, xs in words.items() if len(xs) >= MIN_GROUP), key=lambda r: -r["median"])
    # 7. 伸びの続き方(平均の曲線: 28 日の EV のうち 1・3・7 日までの割合)
    cv = Model(ds, conf["ev"]).curve
    g28 = cv.at(28 * 24)
    out["longevity"] = {"d1": cv.at(24) / g28 if g28 else None, "d3": cv.at(72) / g28 if g28 else None, "d7": cv.at(168) / g28 if g28 else None,
                        "d90": cv.at(90 * 24) / g28 if g28 else None}
    # 8. 長尺
    longs = [v for v in ds.public_videos(short=False) if lo <= v.pub < hi]
    dd = [end_day - i * DAY for i in range(days)]
    lev = sum(ds.value("long", "ev", d) for d in dd)
    tev = sum(ds.value("total", "ev", d) for d in dd)
    out["long"] = {"videos": [{"title": v.short_title(30), "pub": v.pub_jst.strftime("%m/%d"), "length": int(v.length), "ev": round(v.ev),
                               "awp": v.awp, "rev": round(v.rev, 2), "subs": round(v.subs)} for v in sorted(longs, key=lambda v: -v.ev)[:15]],
                   "shareEv": lev / tev if tev else None, "n": len(longs)}
    return out


def period_key(ds, kind):
    """その raw で作る報告の「期間の名前」(送り直しの判定に使う)。日報 = 受信日・週報 = 週の初め・月報 = 月"""
    conf = confirmed(ds)
    if kind == "weekly":
        end = conf["ev"] - ((conf["ev"].weekday() + 1) % 7) * DAY
        return (end - 6 * DAY).isoformat()
    if kind == "monthly":
        first = conf["ev"].replace(day=1)
        if (conf["ev"] + DAY).day == 1:
            first = T.add_months(first, 1)
        return T.add_months(first, -1).strftime("%Y-%m")
    return ds.date_jst
