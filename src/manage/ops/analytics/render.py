"""日報・週報・月報の LINE の文面と HTML(calc の結果 → 文字列)。

- HTML は 1 枚で完結(外部のファイル・スクリプトなし。Apps Script の閲覧ページの中でも、ツールの画面の中でも同じに見える)
- スマホ幅(360px〜)・明るい / 暗い表示の両方。数字はすべて「いつのデータか」を横に書く(12-4 の 4)
- EV(エンゲージビュー)と再生回数を混ぜない。収益は単位を確かめるまで「要確認」と書く
"""
import datetime
import html

from . import timeutil as T

DAY = datetime.timedelta(days=1)


def esc(s):
    return html.escape(str(s if s is not None else ""), quote=True)


def man(x):
    """12,345 → 1.2万。1 万未満はそのまま"""
    if x is None:
        return "—"
    x = float(x)
    if abs(x) >= 10000:
        v = x / 10000.0
        return ("%.0f万" if abs(v) >= 100 else "%.1f万") % v
    return "{:,.0f}".format(x)


def pct(x, sign=False, digits=0):
    if x is None:
        return "—"
    s = ("%+." if sign else "%.") + str(digits) + "f%%"
    return s % (x * 100)


def usd(x):
    return "—" if x is None else "$%s" % "{:,.2f}".format(x)


def d_md(iso):
    return T.md(datetime.date.fromisoformat(iso)) if iso else "—"


def d_mdw(iso):
    return T.md_w(datetime.date.fromisoformat(iso)) if iso else "—"


CSS = """
:root{--bg:#fbfbfa;--fg:#17202b;--sub:#56606c;--line:#e2e5e9;--card:#fff;--ok:#1d6b35;--warn:#8a5a00;--bad:#b3261e;--accent:#2563c9;--bar:#9dbbe8;--bar2:#2563c9;--hatch:#c9d8ee}
@media (prefers-color-scheme: dark){:root{--bg:#14181d;--fg:#e8ecf0;--sub:#a7b0ba;--line:#2c333b;--card:#1b2027;--ok:#6fcf8d;--warn:#e7b54b;--bad:#ff8a80;--accent:#8ab4f8;--bar:#3d5a85;--bar2:#8ab4f8;--hatch:#2d3e57}}
*{box-sizing:border-box}body{margin:0;background:var(--bg);color:var(--fg);font-family:"BIZ UDPGothic","Hiragino Sans","Noto Sans CJK JP",sans-serif;font-size:15px;line-height:1.6}
main{max-width:680px;margin:0 auto;padding:16px 16px 48px}
header{border-bottom:2px solid var(--fg);padding-bottom:8px;margin-bottom:12px}
.kicker{font-size:12px;font-weight:700;color:var(--sub);margin:0}h1{font-size:20px;margin:2px 0 4px;line-height:1.35}
.meta{font-size:12px;color:var(--sub);display:flex;flex-wrap:wrap;gap:0 12px;margin:0}
h2{font-size:16px;margin:24px 0 6px;padding-top:10px;border-top:1px solid var(--line)}
h3{font-size:14px;margin:14px 0 4px}
ol.sum{margin:0;padding-left:20px}ol.sum li{margin:0 0 4px}
.big{font-size:30px;font-weight:700;line-height:1.15;font-variant-numeric:tabular-nums}.big small{font-size:13px;font-weight:400;color:var(--sub)}
.sub,.note{font-size:12.5px;color:var(--sub);margin:4px 0}
table{width:100%;border-collapse:collapse;font-size:13.5px;margin-top:6px}
th{text-align:left;font-weight:600;color:var(--sub);font-size:12px;border-bottom:1px solid var(--fg);padding:4px;line-height:1.3;vertical-align:bottom}
td{border-bottom:1px solid var(--line);padding:5px 4px;vertical-align:top}td.n,th.n{text-align:right;white-space:nowrap;font-variant-numeric:tabular-nums}
td small{display:block;color:var(--sub);font-size:11.5px;white-space:normal}td.k{white-space:nowrap}
.tw{max-width:100%;overflow-x:auto}
.ok{color:var(--ok);font-weight:700}.warn{color:var(--warn);font-weight:700}.bad{color:var(--bad);font-weight:700}.dim{color:var(--sub)}
.tag{display:inline-block;font-size:11.5px;border:1px solid currentColor;border-radius:4px;padding:0 4px;margin-right:4px;white-space:nowrap}
.warnbox{border:1px solid var(--bad);border-radius:6px;padding:8px 10px;margin:10px 0;font-size:13px}
dl{font-size:12.5px;margin:0;display:grid;grid-template-columns:7.5em 1fr;gap:4px 8px}dt{font-weight:600}dd{margin:0;color:var(--sub)}
svg{display:block;margin-top:6px;width:100%;max-width:520px;height:auto}svg text{fill:var(--sub);font-size:10px}
svg text.lab{fill:var(--fg);font-weight:600;paint-order:stroke;stroke:var(--bg);stroke-width:3px}
"""


def page(title, kicker, meta, body):
    body = body.replace("<table>", "<div class=\"tw\"><table>").replace("</table>", "</table></div>")   # 狭い画面では表だけ横に動かす
    return ("<!doctype html><html lang=\"ja\"><head><meta charset=\"utf-8\">"
            "<meta name=\"viewport\" content=\"width=device-width,initial-scale=1\"><title>%s</title><style>%s</style></head>"
            "<body><main><header><p class=\"kicker\">%s</p><h1>%s</h1><p class=\"meta\">%s</p></header>%s</main></body></html>"
            % (esc(title), CSS, esc(kicker), esc(title), "".join("<span>%s</span>" % esc(m) for m in meta), body))


def provenance(r):
    c = r["conf"]
    return ["タップ %s" % r["fetchedJst"], "確定 EV: %s まで" % d_md(c["ev"]),
            "収益: %s まで" % (d_md(c["rev"]) if c.get("rev") else "未確定"), "日付は太平洋時間・本数は日本時間"]


# ------------------------------------------------------------------ YPP

def scenario(ol, name):
    """名前の付いた本数("予定"・"直近7日"・"28日平均")の見込み"""
    return next((s for s in ol["scenarios"] if name in s.get("names", [])), ol["scenarios"][len(ol["scenarios"]) // 2])


def pool_keys(ol):
    return [k for k in ("after", "before", "recent") if k in ol["pools"]]


def probs(s, ol, key="prob"):
    return [s[k][key] for k in pool_keys(ol)]


def prob_range(s, ol, key="prob"):
    ps = probs(s, ol, key)
    lo, hi = min(ps), max(ps)
    return "%s〜%s" % (pct(lo), pct(hi)) if hi - lo >= 0.01 else pct(lo)


def ypp_state(r):
    """-> (印, 色の class, 一言)。90 日の合計と見込みの両方を見る。見込みは予定の本数(無ければ 28 日平均)・強さの見本のうち控えめな側で決める"""
    y, ol = r["ypp"], r["outlook"]
    now = scenario(ol, "予定" if ol.get("plan") else "28日平均")
    ps = probs(now, ol)
    lo, hi = min(ps), max(ps)
    if y["ratio"] >= 1 and lo >= 0.8:
        return "●", "ok", "届いている"
    if lo >= 0.8:
        return "●", "ok", "予定の本数なら届く見込み" if ol.get("plan") else "今の本数なら届く見込み"
    if hi >= 0.5:
        return "▲", "warn", "届くかは 1 本あたりの強さ次第"
    return "■", "bad", "このままでは届かない見込み"


def ypp_html(r):
    y, ol, bt = r["ypp"], r["outlook"], r["outlook"]["backtest"]
    mark, cls, word = ypp_state(r)
    keys = pool_keys(ol)
    head = "".join("<th class=\"n\">%s<br>中央(10〜90%%)</th>" % esc(ol["pools"][k]["label"]) for k in keys)
    rows = []
    for s in ol["scenarios"]:
        cur = bool(s.get("names"))
        cells = "".join("<td class=\"n\">%s<small>%s〜%s</small></td>" % (man(s[k]["p50"]), man(s[k]["p10"]), man(s[k]["p90"])) for k in keys)
        rows.append("<tr%s><td class=\"k\">週 %d 本%s</td>%s<td class=\"n\"><b>%s</b><small>保つ %s</small></td></tr>" % (
            " style=\"font-weight:700\"" if cur else "", s["perWeek"], "<small>%s</small>" % esc("・".join(s["names"])) if cur else "",
            cells, prob_range(s, ol), prob_range(s, ol, "keepProb")))
    need = "・".join("%s: 週 %s 本" % (ol["pools"][k]["label"], ol["need50"][k] if ol["need50"][k] else "120 本でも届かない") for k in keys)
    cnt = ol["poolCounts"]
    missing = [] if "after" in ol["pools"] else ["10/1 以降の動画はまだ %d 本なので、その強さでの見込みは %d 本から出します" % (cnt["after"], ol["minPool"])]
    bt_rows = "".join("<tr><td>%s から 28 日</td><td class=\"n\">%s</td><td class=\"n\">%s</td><td class=\"n\">%s</td></tr>" % (
        d_md(x["origin"]), man(x["pred"]), man(x["actual"]), pct(x["err"], True)) for x in bt["rows"])
    top = ("<h2>YPP(直近 90 日のショートの EV が 1,000 万)</h2>"
           "<div class=\"%s\">%s %s</div><div class=\"big\">%s<small> / 1,000万(%s・%s まで確定)</small></div>"
           "<p class=\"sub\">14 日平均 %s/日(必要なペース %s/日)・2027/2/1 から毎日、直近 90 日で判定</p>"
           % (cls, mark, word, man(y["sum90"]), pct(y["ratio"]), d_md(y["through"]), man(y["avg14"]), man(y["need"])))
    table = ("<h3>2/1 の見込み(本数ごと)</h3>%s"
             "<table><thead><tr><th>本数</th>%s<th class=\"n\">届く確率</th></tr></thead><tbody>%s</tbody></table>"
             "<p class=\"note\">%s。「保つ」= 2/1〜3/29 の毎週の判定で一度も下回らない確率。届く確率が 50%% になる本数 — %s</p>"
             % ("".join("<p class=\"note\">%s</p>" % esc(x) for x in missing), head, "".join(rows), esc(ol["basis"]), esc(need)))
    method = ("<h3>見込みの方法の答え合わせ(過去の時点から 28 日)</h3>"
              "<table><thead><tr><th>時点</th><th class=\"n\">見込み</th><th class=\"n\">実際</th><th class=\"n\">ずれ</th></tr></thead>"
              "<tbody>%s</tbody></table><p class=\"note\">実際の投稿のとおりに投稿したとして、その時点までのデータで見込んだ値。"
              "どれも 10/1 より前(戦略が変わる前)なので目安。ここで測った誤差を、確率の幅に入れている。</p>"
              "<h3>この見込みの仮定</h3><ul class=\"note\">%s</ul>" % (bt_rows, "".join("<li>%s</li>" % esc(a) for a in ol["assume"])))
    return (top + backcalc_html(ol) + table + hits_html(ol) + sensitivity_html(ol) + cannibal_html(ol) + trend_html(ol)
            + ledger_html(r) + method)


def backcalc_html(ol):
    """① 必要な数の逆算"""
    b = ol.get("backcalc")
    if not b:
        return ""
    keys = pool_keys(ol)
    rows = []
    for x in b["rows"]:
        cells = "".join("<td class=\"n\">%s<small>必要の %s・届く動画 %s</small></td>" % (
            man(x[k]["mean7"]), pct(x[k]["ratio"]), pct(x[k]["share"])) for k in keys)
        rows.append("<tr><td class=\"k\">週 %d 本<small>%d 本</small></td><td class=\"n\"><b>%s</b></td>%s</tr>" % (
            x["perWeek"], x["videos"], man(x["need7"]), cells))
    return ("<h3>① 必要な数の逆算(確率を使わない見方)</h3>"
            "<p class=\"sub\">2/1 の判定の 90 日(%s〜%s)で 1,000 万(1 日平均 %s)。そのうち確定した日の実際 %s・今ある動画と古い動画の見込み %s。"
            "残りを、これから出す動画で稼ぐ必要がある。</p>"
            "<table><thead><tr><th>本数</th><th class=\"n\">必要な 1 本あたり<br>(公開 7 日の EV)</th>%s</tr></thead><tbody>%s</tbody></table>"
            "<p class=\"note\">「必要な 1 本あたり」= これから出す動画が平均でこれだけ稼げば届く(公開 7 日の EV に直した値)。"
            "右の列 = 見本の動画の平均(必要に対する割合)と、見本のうち必要を超える動画の割合。平均が 100%% を超えていれば、平均どおりなら届く。</p>"
            % (d_md(b["window"][0]), d_md(b["window"][1]), man(b["perDay"]), man(b["known"]), man(b["base"]),
               "".join("<th class=\"n\">%s<br>(平均)</th>" % esc(ol["pools"][k]["label"]) for k in keys), "".join(rows)))


def hits_html(ol):
    """⑤ 当たりへの頼り方"""
    h = ol.get("hits")
    if not h:
        return ""
    return ("<h3>⑤ 当たりへの頼り方</h3>"
            "<p>直近 90 日のショートの EV のうち、上位 5%%(%d 本)の動画が %s。"
            "週 %d 本で、見本から大当たり(上位 5%%)を除くと、2/1 に届く確率は %s → <b>%s</b>(中央 %s → %s)。"
            "大当たり 1 本(上位 1%%)は 2/1 の判定の 90 日に 約 %s を足す(ふつうの 1 本は 約 %s)。</p>"
            "<p class=\"note\">大当たりが出るかで結果が大きく変わるほど、見込みは当てにくい。大当たりを除いても届くなら安心できる。</p>"
            % (h["top5n"], pct(h["top5"]), h["rate"], pct(h["prob"]), pct(h["probNoHits"]), man(h["p50"]), man(h["p50NoHits"]),
               man(h["bigOne"]), man(h["typicalOne"])))


def sensitivity_html(ol):
    """④ 感度の表"""
    s = ol.get("sensitivity")
    if not s:
        return ""
    rows = "".join("<tr><td>%s</td><td class=\"n\">%s</td><td class=\"n %s\">%s</td></tr>" % (
        esc(x["name"]), pct(x["prob"]), "bad" if x["diff"] <= -0.1 else "ok" if x["diff"] >= 0.1 else "", "—" if i == 0 else pct(x["diff"], True))
        for i, x in enumerate(s["rows"]))
    return ("<h3>④ 感度の表(仮定を 1 つずつ動かしたときの、2/1 に届く確率)</h3>"
            "<table><thead><tr><th>動かしたもの</th><th class=\"n\">確率</th><th class=\"n\">基準との差</th></tr></thead><tbody>%s</tbody></table>"
            "<p class=\"note\">基準 = 週 %d 本・%s。食い合いは「見本の頃の週 %.0f 本」と比べて本数が多いほど 1 本あたりが下がるとしたもの。"
            "差の大きい行の仮定ほど、結果を左右している。</p>" % (rows, s["rate"], esc(ol["pools"][ol["mainKey"]]["label"]), s["ref"]))


def cannibal_html(ol):
    c = ol.get("cannibal")
    if not c:
        return ""
    if c.get("e") is None:
        return "<h3>食い合い(A2)の推定</h3><p class=\"note\">%s(%d 本)</p>" % (esc(c["note"]), c["n"])
    word = "見られない" if c["lo"] <= 0 <= c["hi"] else "ありそう" if c["lo"] > 0 else "本数が多い日のほうが伸びている"
    return ("<h3>食い合い(A2)の推定</h3><p>同じ週の中で、投稿の多い日の動画ほど伸びが小さいか: e = <b>%.2f</b>(80%% の幅 %.2f〜%.2f)→ 食い合いは%s。"
            "%d 日・%d 本、日の本数 %s 本。</p><p class=\"note\">e = 0 なら食い合いなし、0.5 なら本数を 2 倍にすると 1 本あたりが 約 3 割下がる。%s</p>"
            % (c["e"], c["lo"], c["hi"], word, c["days"], c["n"], "・".join(str(x) for x in c["perDay"]), esc(c["note"])))


def trend_html(ol):
    """② 1 本あたりの強さの推移"""
    t = ol.get("trend")
    if not t or not t["rows"]:
        return ""
    rows = list(t["rows"]) + [x for x in (t.get("before"), t.get("after")) if x]
    body = "".join("<tr><td>%s</td><td class=\"n\">%d</td><td class=\"n\">%s<small>%s〜%s</small></td><td class=\"n\">%s</td></tr>" % (
        esc(x["name"]), x["n"], man(x["mean"]), man(x["lo"]), man(x["hi"]), man(x["median"])) for x in rows)
    return ("<h3>② 1 本あたりの強さの推移(%s)</h3>"
            "<table><thead><tr><th>公開</th><th class=\"n\">本数</th><th class=\"n\">平均(80%% の幅)</th><th class=\"n\">中央値</th></tr></thead>"
            "<tbody>%s</tbody></table><p class=\"note\">月は公開の月(日本時間)。幅が重ならないほど、差ははっきりしている。最後の 2 行は境目の前後。</p>"
            % (esc(t["metric"]), body))


def ledger_html(r):
    """⑥ 見込みの記録と答え合わせ"""
    lg = r.get("ledger")
    if not lg:
        return ("<h3>⑥ 見込みの記録</h3><p class=\"note\">毎日の見込み(28 日後の 90 日の合計)を記録し、その日が確定したら実際と比べます。"
                "記録は今日から始まり、最初の答え合わせは 28 日後です。</p>")
    ev = lg["evaluated"][-10:]
    if not ev:
        return "<h3>⑥ 見込みの記録</h3><p class=\"note\">記録 %d 件。最初の答え合わせは、最初の記録の 28 日後です。</p>" % lg["total"]
    body = "".join("<tr><td>%s の見込み<small>%s の 90 日</small></td><td class=\"n\">%s</td><td class=\"n\">%s</td><td class=\"n\">%s</td></tr>" % (
        d_md(x["made"]), d_md(x["target"]), man(x["p50"]), man(x["actual"]), pct(x["err"], True)) for x in reversed(ev))
    errs = [abs(x["err"]) for x in lg["evaluated"] if x.get("err") is not None]
    return ("<h3>⑥ 見込みの記録と答え合わせ</h3><table><thead><tr><th>いつの見込み</th><th class=\"n\">見込み</th><th class=\"n\">実際</th>"
            "<th class=\"n\">ずれ</th></tr></thead><tbody>%s</tbody></table><p class=\"note\">答え合わせ済み %d 件(平均のずれ %s)・待ち %d 件。"
            "日がたつほど、10/1 以降の見込みの当たり具合が分かる。</p>" % (body, len(errs), pct(sum(errs) / len(errs)) if errs else "—", lg["pending"]))


def bars_svg(r, days, values, conf_iso, need=None, title=""):
    """日ごとの棒(確定は塗り・未確定は斜線)。need があれば横線"""
    w, h, left, top, bottom = 360, 150, 42, 10, 22
    vmax = max([v for v in values if v is not None] + [need or 0, 1]) * 1.1
    n = len(days)
    bw = (w - left - 4) / float(n)
    y = lambda v: top + (h - top - bottom) * (1 - v / vmax)
    parts = ["<svg viewBox=\"0 0 %d %d\" width=\"100%%\" role=\"img\" aria-label=\"%s\"><defs><pattern id=\"hh\" width=\"4\" height=\"4\" "
             "patternUnits=\"userSpaceOnUse\" patternTransform=\"rotate(45)\"><rect width=\"4\" height=\"4\" fill=\"var(--bg)\"/>"
             "<line x1=\"0\" y1=\"0\" x2=\"0\" y2=\"4\" stroke=\"var(--hatch)\" stroke-width=\"2\"/></pattern></defs>" % (w, h, esc(title))]
    for frac in (0, 0.5, 1):
        v = vmax / 1.1 * frac
        parts.append("<line x1=\"%d\" x2=\"%d\" y1=\"%.1f\" y2=\"%.1f\" stroke=\"var(--line)\"/><text x=\"%d\" y=\"%.1f\" text-anchor=\"end\">%s</text>"
                     % (left, w, y(v), y(v), left - 3, y(v) + 3, man(v)))
    for i, (d, v) in enumerate(zip(days, values)):
        if v is None:
            continue
        x = left + i * bw + 1
        fill = "url(#hh)" if d.isoformat() > conf_iso else ("var(--bar2)" if need and v >= need else "var(--bar)")
        parts.append("<rect x=\"%.1f\" y=\"%.1f\" width=\"%.1f\" height=\"%.1f\" fill=\"%s\"/>" % (x, y(v), max(1, bw - 2), h - bottom - y(v), fill))
        if i % 7 == (n - 1) % 7:
            parts.append("<text x=\"%.1f\" y=\"%d\" text-anchor=\"middle\">%s</text>" % (x + bw / 2, h - 8, T.md(d)))
    if need:
        parts.append("<line x1=\"%d\" x2=\"%d\" y1=\"%.1f\" y2=\"%.1f\" stroke=\"var(--fg)\" stroke-dasharray=\"4 3\"/>"
                     "<text class=\"lab\" x=\"%d\" y=\"%.1f\">必要なペース %s</text>" % (left, w, y(need), y(need), left + 4, y(need) - 3, man(need)))
    parts.append("</svg>")
    return "".join(parts)


# ------------------------------------------------------------------ 日報

def launch_rows(rows):
    out = []
    for x in rows:
        cls = {"当たり": "ok", "外れ": "bad", "伸び悩み": "warn"}.get(x["label"], "dim")
        when = "%d 時間で %s" % (x["hours"], man(x["value"])) if x.get("hours") else "速報 %s" % man(x["value"])
        rank = "上位 %d%%" % round((1 - x["pct"]) * 100) if x.get("pct") is not None else ""
        vtr = ("継続 %.0f%%" % x["vtr"]) if x.get("vtr") else ""
        out.append("<tr><td>%s<small>%s・%s</small></td><td class=\"n\">%s<small>%s</small></td><td class=\"n\"><span class=\"%s\">%s</span>"
                   "<small>%s</small></td></tr>" % (esc(x["title"]), esc(x["pub"]), esc(x.get("member") or "—"), esc(when), esc(rank), cls,
                                                     esc(x["label"] + ("" if x.get("final") or x["label"] == "判定前" else "(途中)")), esc(vtr)))
    return "".join(out)


def daily_parts(r):
    """-> (LINE の文面, HTML)"""
    y, ol, la, an, dy, po = r["ypp"], r["outlook"], r["launch"], r["anomaly"], r["day"], r["posts"]
    mark, cls, word = ypp_state(r)
    hits = [x for x in la["rows"] if x["label"] == "当たり"]
    odd = [a for a in an["items"] if a["state"] != "ok"]
    date = datetime.date.fromisoformat(r["dateJst"]) if r.get("dateJst") else T.jst_date(datetime.datetime.fromisoformat(r["fetched"]))
    lines = ["【日報 %s】タップ %s・確定 %s まで" % (T.md_w(date), r["fetchedJst"][11:], d_md(r["conf"]["ev"])),
             "YPP %s %s:90日 %s(%s)" % (mark, word, man(y["sum90"]), pct(y["ratio"])),
             "・" + outlook_brief(ol),
             "・%s:ショート EV %s(7日平均比 %s)・登録 %+d" % (d_md(dy["day"]), man(dy["shortEv"]), pct(dy["vsAvg7"], True), dy["subs"])]
    if dy.get("revDay"):
        lines.append("・収益 %s:%s(7日平均比 %s)" % (d_md(dy["revDay"]), usd(dy["rev"]), pct(dy["revVsAvg7"], True)))
    lines.append("・直近7日の投稿:ショート %d本・長尺 %d本" % (po["short7"], po["long7"]))
    if hits:
        lines.append("・初動の当たり %d本:%s" % (len(hits), "・".join(h["title"] for h in hits[:4])))
    for a in odd:
        lines.append("・いつもと違う:%sが%s(%s。過去%d週 %s〜%s)" % (a["name"], "低い" if a["state"] == "low" else "高い", fmt_metric(a["key"], a["now"]),
                                                     an["weeks"], fmt_metric(a["key"], a["min"]), fmt_metric(a["key"], a["max"])))
    if r["warnings"]:
        lines.append("⚠ %s" % r["warnings"][0])

    days = [datetime.date.fromisoformat(r["conf"]["ev"]) - (27 - i) * DAY for i in range(30)]
    series = r.get("series") or {}
    vals = [series.get(d.isoformat()) for d in days]
    an_rows = "".join("<tr><td>%s</td><td class=\"n %s\">%s</td><td class=\"n\">%s〜%s<small>中央 %s</small></td></tr>" % (
        esc(a["name"]), {"low": "bad", "high": "ok"}.get(a["state"], ""), fmt_metric(a["key"], a["now"]),
        fmt_metric(a["key"], a["min"]), fmt_metric(a["key"], a["max"]), fmt_metric(a["key"], a["median"])) for a in an["items"])
    warn = "".join("<div class=\"warnbox\">⚠ %s</div>" % esc(w) for w in r["warnings"])
    body = (warn + "<ol class=\"sum\">%s</ol>" % "".join("<li>%s</li>" % esc(l.lstrip("・")) for l in lines[1:4])
            + ypp_html(r)
            + "<h2>ショートの EV(日ごと)</h2>" + bars_svg(r, days, vals, r["conf"]["ev"], y["need"], "ショートの EV")
            + "<p class=\"note\">斜線 = まだ確定していない日(あとで増える)。濃い色 = 必要なペース以上。</p>"
            + "<h2>初動(直近 7 日に公開したショート)</h2><table><thead><tr><th>動画</th><th class=\"n\">EV</th><th class=\"n\">判定</th></tr></thead>"
            + "<tbody>%s</tbody></table><p class=\"note\">%s 比べた本数: %s。(途中)= 72 時間たっていないので、たった時間で比べた途中の判定。</p>" % (
                launch_rows(la["rows"]), esc(la["rule"]), esc("・".join("%s時間 %s本" % (k, v) for k, v in la["benchN"].items())))
            + "<h2>いつもと違うところ</h2><table><thead><tr><th>指標(%s まで 7 日)</th><th class=\"n\">今</th><th class=\"n\">過去 %d 週の範囲</th></tr></thead>"
              "<tbody>%s</tbody></table><p class=\"note\">範囲の外なら色を付けます。EV ÷ 再生回数が下がるのは、ループ以外で最初の数秒で離れる人が増えたとき。</p>"
            % (d_md(an["through"]), an["weeks"], an_rows)
            + "<h2>投稿の本数(日本時間)</h2><p>直近 7 日(%s まで):ショート %d 本・長尺 %d 本/直近 28 日:ショート %d 本(週 %.1f 本)/今日:%d 本</p>" % (
                d_md(po["through"]), po["short7"], po["long7"], po["short28"], po["perWeek28"], po["todayShort"])
            + ("<h2>結果の指標と当たり率</h2>" + outcomes_html(r["outcomes"]) if r.get("outcomes") else "")
            + terms())
    title = "日報 %s" % T.md_w(date)
    return "\n".join(lines), page(title, "Youtube分析", provenance(r), body)


def fmt_metric(key, v):
    if v is None:
        return "—"
    if key == "ratio":
        return "%.0f%%" % (v * 100)
    if key == "vtr":
        return "%.1f%%" % v
    return man(v)


def terms():
    return ("<h2>用語と決まり</h2><dl>"
            "<dt>EV</dt><dd>エンゲージビュー。冒頭の数秒より先まで見られた回数で、YPP の判定に使う数字。ループは数えない(再生回数とは別)</dd>"
            "<dt>確定</dt><dd>Studio の数字は前日分が大きく欠けるので、EV はタップした日(太平洋時間)の 2 日前まで、収益は値が入った最後の日までを確定とする</dd>"
            "<dt>初動の判定</dt><dd>公開からの経過時間で比べる(公開した時刻で有利・不利が出ないように)。基準は固定の数字ではなく、直近 90 日のショートの中の順位</dd>"
            "<dt>視聴を継続</dt><dd>ショートのフィードでスワイプされずに見られた割合(Studio)。公開からの累計</dd>"
            "<dt>見込み</dt><dd>今ある動画の残りの伸び + これから出す動画(1 本あたりの強さは直近の動画から抜き出す)+ 古い動画の分。毎回、過去の時点から同じ方法で見込んで答え合わせをする</dd>"
            "<dt>収益</dt><dd>Studio の値 ÷ 1000(単位は Studio の画面と見比べて確かめるまで要確認)</dd></dl>")


# ------------------------------------------------------------------ 週報・月報

def totals_table(cur, prev, extra=None, extra_name=""):
    def row(name, k, f):
        cells = "<td class=\"n\">%s</td><td class=\"n\">%s</td>" % (f(cur[k]), f(prev[k]))
        ch = cur[k] / prev[k] - 1 if prev[k] else None
        cells += "<td class=\"n\">%s</td>" % pct(ch, True)
        if extra is not None:
            cells += "<td class=\"n\">%s</td>" % f(extra[k])
        return "<tr><td>%s</td>%s</tr>" % (name, cells)
    head = "<tr><th></th><th class=\"n\">今</th><th class=\"n\">前</th><th class=\"n\">増減</th>%s</tr>" % (
        "<th class=\"n\">%s</th>" % extra_name if extra is not None else "")
    return ("<table><thead>%s</thead><tbody>%s%s%s%s</tbody></table>%s" % (
        head, row("ショートの EV", "shortEv", man), row("長尺の EV", "longEv", man), row("収益", "rev", usd), row("登録者の純増", "subs", lambda v: "%+d" % v),
        "<p class=\"note\">収益の未確定の日: %d 日</p>" % cur["revUnconfirmed"] if cur.get("revUnconfirmed") else ""))


def group_html(t, title):
    if not t["rows"]:
        return "<h3>%s</h3><p class=\"note\">比べられる群がありません(%d 本以上の群が無い)</p>" % (esc(title), 3)
    rows = "".join("<tr><td>%s</td><td class=\"n\">%d</td><td class=\"n\">%s</td><td class=\"n %s\">×%.2f</td></tr>" % (
        esc(x["key"]), x["n"], man(x["median"]), "ok" if x["ratio"] and x["ratio"] >= 1.25 else "bad" if x["ratio"] and x["ratio"] <= 0.8 else "",
        x["ratio"] or 0) for x in t["rows"])
    return ("<h3>%s</h3><table><thead><tr><th></th><th class=\"n\">本数</th><th class=\"n\">中央値</th><th class=\"n\">全体比</th></tr></thead>"
            "<tbody>%s</tbody></table><p class=\"note\">全体の中央値 %s(%d 本)。3 本未満の群は出さない。</p>" % (esc(title), rows, man(t["overall"]), t["n"]))


def outlook_brief(ol):
    if not ol:
        return ""
    a, b = scenario(ol, "直近7日"), scenario(ol, "28日平均")
    if ol.get("plan"):
        p = scenario(ol, "予定")
        return "2/1 に届く確率:予定(週%d本)なら %s(直近7日は週%d本・28日平均は週%d本)" % (p["perWeek"], prob_range(p, ol), a["perWeek"], b["perWeek"])
    if a is b:
        return "2/1 に届く確率(週%d本のまま)%s" % (a["perWeek"], prob_range(a, ol))
    return "2/1 に届く確率:直近7日のペース(週%d本)なら %s・28日平均(週%d本)なら %s" % (
        a["perWeek"], prob_range(a, ol), b["perWeek"], prob_range(b, ol))


def weekly_parts(r):
    w = r["week"]
    t, p = w["totals"], w["prev"]
    title = "週報 %s〜%s" % (d_md(w["start"]), d_md(w["end"]))
    lines = ["【%s】確定 %s まで" % (title, d_md(r["conf"]["ev"])),
             "・ショート EV %s(前週比 %s)・投稿 %d本(前週 %d本)" % (man(t["shortEv"]), pct(t["shortEv"] / p["shortEv"] - 1 if p["shortEv"] else None, True),
                                                       w["posts"]["short"], w["posts"]["prevShort"]),
             "・収益 %s・登録 %+d" % (usd(t["rev"]), t["subs"]),
             "・初動の当たり %d本/%d本" % (w["hits"], len([x for x in w["videos"] if x["pct"] is not None]))]
    top = [x for x in w["videos"] if x["value"] is not None][:3]
    if top:
        lines.append("・上位:%s" % "・".join("%s %s" % (x["title"], man(x["value"])) for x in top))
    bm = w["byMember"]["rows"]
    if bm:
        lines.append("・配信者(直近28日・72時間の中央値):上 %s/下 %s" % (bm[0]["key"], bm[-1]["key"]))
    if r.get("outlook"):
        lines.append("・" + outlook_brief(r["outlook"]))
    vids = "".join("<tr><td>%s<small>%s</small></td><td class=\"n\">%s</td><td class=\"n\">%s</td><td class=\"n\">%s</td></tr>" % (
        esc(x["title"]), esc(x["member"] or "—"), man(x["value"]) if x["value"] is not None else "未確定",
        ("上位 %d%%" % round((1 - x["pct"]) * 100)) if x["pct"] is not None else "—", ("%.0f%%" % x["vtr"]) if x["vtr"] else "—") for x in w["videos"])
    vt = w["vtr"]
    body = ("<ol class=\"sum\">%s</ol>" % "".join("<li>%s</li>" % esc(l.lstrip("・")) for l in lines[1:])
            + "<h2>週の合計(%s〜%s・太平洋時間の日)</h2>" % (d_mdw(w["start"]), d_mdw(w["end"]))
            + totals_table(t, p, w["avg4"], "4週平均")
            + "<p>投稿(日本時間の同じ日付):ショート %d 本(前週 %d 本)・長尺 %d 本</p>" % (w["posts"]["short"], w["posts"]["prevShort"], w["posts"]["long"])
            + "<h2>この週に公開したショート(%s)</h2><table><thead><tr><th>動画</th><th class=\"n\">72時間</th><th class=\"n\">順位</th>"
              "<th class=\"n\">継続</th></tr></thead><tbody>%s</tbody></table>" % (esc(w["metric"]), vids)
            + "<p class=\"note\">視聴を継続の中央値: この週 %s・前の 4 週 %s</p>" % (fmt_metric("vtr", vt["now"]), fmt_metric("vtr", vt["prev4"]))
            + "<h2>何を切るか(直近 28 日に公開したショート・72 時間の EV)</h2>"
            + group_html(w["byMember"], "配信者(題名の最初のメンバー)") + group_html(w["byLength"], "長さ")
            + regime_html(r.get("regime"))
            + (deep_html(r["deep"]) if r.get("deep") else "")
            + (ypp_html(r) if r.get("outlook") else "") + terms())
    return "\n".join(lines), page(title, "Youtube分析", provenance(r), body)


def _rate_table(rows, first="帯"):
    if not rows:
        return "<p class=\"note\">データが足りません</p>"
    body = "".join("<tr><td>%s</td><td class=\"n\">%d</td><td class=\"n\">%s</td><td class=\"n\">%s</td></tr>" % (
        esc(x["key"]), x["n"], man(x["median"]), pct(x["hitRate"])) for x in rows)
    return ("<table><thead><tr><th>%s</th><th class=\"n\">本数</th><th class=\"n\">中央値</th><th class=\"n\">当たりの割合</th></tr></thead>"
            "<tbody>%s</tbody></table>" % (esc(first), body))


def outcomes_html(d):
    """結果の指標(視聴を継続・平均視聴率・再生 ÷ EV)の帯ごとの当たり率(日報・週報・月報)"""
    parts = ["<p class=\"note\">%s〜%s に公開したショート %d 本・公開 %d 時間の EV。当たり = この期間の上位 20%%(%s 以上)。"
             "どれも公開からの累計の値(結果の側の数字)。どの帯から当たりが出ているかを見る。関係があっても原因とは限らない。</p>" % (
                 d_md(d["from"]), d_md(d["to"]), d["n"], d["hours"], man(d["hitLine"]))]
    for o in d["outcomes"]:
        parts.append("<p class=\"sub\"><b>%s</b></p>%s" % (esc(o["name"]), _rate_table(o["rows"])))
    return "".join(parts)


def regime_html(g):
    """境目(10/1)の前と後の比較(週報・月報)"""
    if not g or "after" not in g:
        return "<h2>10/1 の前と後</h2><p class=\"note\">%s</p>" % esc((g or {}).get("note", ""))
    a, b = g["after"], g["before"]

    def row(name, k, f):
        ch = a[k] / b[k] - 1 if a.get(k) is not None and b.get(k) else None
        return "<tr><td>%s</td><td class=\"n\">%s</td><td class=\"n\">%s</td><td class=\"n\">%s</td></tr>" % (
            name, f(b.get(k)), f(a.get(k)), pct(ch, True))
    num = lambda f: (lambda v: "—" if v is None else f(v))
    body = (row("ショートの EV(1 日平均)", "shortEv", num(man)) + row("収益(1 日平均)", "rev", num(usd))
            + row("登録者(1 日平均)", "subs", num(lambda v: "%+.1f" % v)) + row("投稿(1 日あたり)", "posts", num(lambda v: "%.1f 本" % v))
            + row("1 本あたり 72 時間(平均)", "mean72", num(man)) + row("1 本あたり 72 時間(中央値)", "median72", num(man))
            + row("当たりの割合", "hitRate", num(pct)) + row("視聴を継続(中央値)", "vtr", num(lambda v: "%.1f%%" % v)))
    ci = g.get("meanRatioCI")
    ci_s = "1 本あたりの平均の比の 80%% の幅: ×%.2f〜×%.2f(%s)。" % (
        ci[0], ci[1], "1 を含まないので差ははっきりしている" if ci[0] > 1 or ci[1] < 1 else "1 を含むので、まだ差ははっきりしない") if ci else ""
    return ("<h2>10/1 の前と後(同じ %d 日ずつ)</h2><table><thead><tr><th></th><th class=\"n\">前<br>%s〜%s</th><th class=\"n\">後<br>%s〜%s</th>"
            "<th class=\"n\">変化</th></tr></thead><tbody>%s</tbody></table><p class=\"note\">%s%s 本数(1 本あたり): 前 %d 本・後 %d 本。</p>"
            % (g["n"], d_md(g["beforeRange"][0]), d_md(g["beforeRange"][1]), d_md(g["afterRange"][0]), d_md(g["afterRange"][1]),
               body, esc(ci_s), esc(g["note"]) + "。", b["n"], a["n"]))


def deep_html(d):
    """中身の分析(週報は直近 28 日・月報は直近 90 日)"""
    parts = ["<h2>中身の分析</h2><h3>結果の指標と当たり</h3>" + outcomes_html(d)]
    s = d["subs"]
    parts.append("<h3>登録につながる動画(EV 1 万あたりの登録者・配信者別)</h3>")
    if s["rows"]:
        parts.append("<table><thead><tr><th>配信者</th><th class=\"n\">本数</th><th class=\"n\">登録 / EV1万</th></tr></thead><tbody>%s</tbody></table>"
                     "<p class=\"note\">全体の中央値 %.1f 人。公開からの累計で、3 本以上の配信者だけ。</p>" % (
                         "".join("<tr><td>%s</td><td class=\"n\">%d</td><td class=\"n\">%.1f</td></tr>" % (esc(x["key"]), x["n"], x["per10k"]) for x in s["rows"]),
                         s["overall"] or 0))
    else:
        parts.append("<p class=\"note\">データが足りません</p>")
    rv = d["revenue"]
    parts.append("<h3>収益(ショート・EV 1,000 あたり)</h3>")
    if rv["weeks"]:
        parts.append("<table><thead><tr><th>週(まで)</th><th class=\"n\">EV 1,000 あたり</th><th class=\"n\">収益</th><th class=\"n\">EV</th></tr></thead><tbody>%s</tbody></table>" % "".join(
            "<tr><td>%s</td><td class=\"n\">%s</td><td class=\"n\">%s</td><td class=\"n\">%s</td></tr>" % (
                d_md(x["end"]), usd(x["rpm"]) if x["rpm"] is not None else "—", usd(x["rev"]), man(x["ev"])) for x in rv["weeks"]))
    if rv["byMember"]:
        parts.append("<table><thead><tr><th>配信者</th><th class=\"n\">本数</th><th class=\"n\">EV 1,000 あたり</th></tr></thead><tbody>%s</tbody></table>" % "".join(
            "<tr><td>%s</td><td class=\"n\">%d</td><td class=\"n\">%s</td></tr>" % (esc(x["key"]), x["n"], usd(x["rpm"])) for x in rv["byMember"]))
    parts.append("<p class=\"note\">収益は Studio の値 ÷ 1000(単位は要確認)。週ごとは収益が確定した日まで。</p>")
    c = d["concentration"]
    parts.append("<h3>当たりへの頼り具合(直近 28 日)</h3><p>記録のある動画 %d 本のうち、上位 5 本で %s・上位 10%% で %s(直近 28 日のショートの EV のうち、日ごとの記録のある動画の分)</p>" % (
        c["videos"], pct(c["top5"]), pct(c["top10pct"])))
    if d["momentum"]:
        parts.append("<h3>配信者の勢い(期間の後半 ÷ 前半)</h3><table><thead><tr><th>配信者</th><th class=\"n\">前半</th><th class=\"n\">後半</th><th class=\"n\">比</th></tr></thead><tbody>%s</tbody></table>"
                     "<p class=\"note\">それぞれ 2 本以上ある配信者だけ。本数が少ないので目安。</p>" % "".join(
                         "<tr><td>%s</td><td class=\"n\">%s<small>%d 本</small></td><td class=\"n\">%s<small>%d 本</small></td><td class=\"n\">×%.2f</td></tr>" % (
                             esc(x["key"]), man(x["old"]), x["nOld"], man(x["new"]), x["nNew"], x["ratio"] or 0) for x in d["momentum"]))
    parts.append("<h3>題名</h3>" + _rate_table(d["titleLength"], "見出し(【】)の長さ"))
    if d["titleWords"]:
        parts.append("<table><thead><tr><th>よく使う見出し</th><th class=\"n\">本数</th><th class=\"n\">中央値</th><th class=\"n\">全体比</th></tr></thead><tbody>%s</tbody></table>" % "".join(
            "<tr><td>%s</td><td class=\"n\">%d</td><td class=\"n\">%s</td><td class=\"n\">×%.2f</td></tr>" % (esc(x["key"]), x["n"], man(x["median"]), x["ratio"] or 0)
            for x in d["titleWords"]))
    lg = d["longevity"]
    parts.append("<h3>伸びの続き方(平均の動画)</h3><p>28 日の EV を 100 とすると、1 日目まで %s・3 日目まで %s・7 日目まで %s。90 日では %s</p>" % (
        pct(lg["d1"]), pct(lg["d3"]), pct(lg["d7"]), pct(lg["d90"])))
    lo = d["long"]
    parts.append("<h3>長尺(%d 本・チャンネルの EV のうち %s)</h3>" % (lo["n"], pct(lo["shareEv"])))
    if lo["videos"]:
        parts.append("<table><thead><tr><th>動画</th><th class=\"n\">EV</th><th class=\"n\">平均視聴率</th><th class=\"n\">収益</th><th class=\"n\">登録</th></tr></thead><tbody>%s</tbody></table>" % "".join(
            "<tr><td>%s<small>%s・%d 分</small></td><td class=\"n\">%s</td><td class=\"n\">%.0f%%</td><td class=\"n\">%s</td><td class=\"n\">%+d</td></tr>" % (
                esc(x["title"]), x["pub"], x["length"] // 60, man(x["ev"]), x["awp"] or 0, usd(x["rev"]), x["subs"]) for x in lo["videos"]))
    return "".join(parts)


def effects_html(e):
    parts = ["<h2>効き目の表(%s〜%s に公開したショート %d 本・%s)</h2>" % (d_md(e["from"]), d_md(e["to"]), e["n"], esc(e["metric"])),
             "<p class=\"note\">要因ごとに、群の中央値を全体の中央値と比べた倍率。差の大きい要因から並べる。"
             "「安定」= 期間の前半と後半で同じ向き。「同じ配信者の中で」= 配信者ごとの中央値で割ってから比べた倍率(配信者の違いの影響を除く)。"
             "灰色 = 前半と後半で向きが変わる(当てにならない)。関係があっても原因とは限らない。</p>"]
    for f in e["factors"]:
        rows = []
        for x in f["rows"]:
            dim = x.get("stable") is False
            rows.append("<tr%s><td>%s</td><td class=\"n\">%d</td><td class=\"n\">%s</td><td class=\"n\">×%.2f</td><td class=\"n\">%s</td><td class=\"n\">%s</td></tr>" % (
                " class=\"dim\"" if dim else "", esc(x["key"]), x["n"], man(x["median"]), x["ratio"] or 0,
                "—" if x.get("withinMember") is None else "×%.2f" % x["withinMember"],
                "安定" if x.get("stable") else "変わる" if x.get("stable") is False else "—"))
        parts.append("<h3>%s(差 %.2f)</h3><table><thead><tr><th></th><th class=\"n\">本数</th><th class=\"n\">中央値</th><th class=\"n\">全体比</th>"
                     "<th class=\"n\">同じ配信者の中で</th><th class=\"n\">前後半</th></tr></thead><tbody>%s</tbody></table>" % (
                         esc(f["factor"]), f["spread"], "".join(rows)))
    return "".join(parts)


def monthly_parts(r):
    mo = r["month"]
    t, p = mo["totals"], mo["prev"]
    title = "月報 %s" % mo["month"].replace("-", "年") + "月"
    strong = [f for f in mo["effects"]["factors"] if any(x.get("stable") and x["ratio"] and (x["ratio"] >= 1.25 or x["ratio"] <= 0.8) for x in f["rows"])]
    lines = ["【%s】確定 %s まで" % (title, d_md(r["conf"]["ev"])),
             "・ショート EV %s(前月比 %s)・投稿 %d本(前月 %d本)" % (man(t["shortEv"]), pct(t["shortEv"] / p["shortEv"] - 1 if p["shortEv"] else None, True),
                                                       mo["posts"]["short"], mo["posts"]["prevShort"]),
             "・収益 %s(前月 %s)・登録 %+d" % (usd(t["rev"]), usd(p["rev"]), t["subs"])]
    for f in strong[:2]:
        best = [x for x in f["rows"] if x.get("stable") and x["ratio"]]
        if best:
            b = max(best, key=lambda x: x["ratio"])
            lines.append("・効き目:%s は「%s」が ×%.2f(%d本・安定)" % (f["factor"], b["key"], b["ratio"], b["n"]))
    if r.get("outlook"):
        lines.append("・" + outlook_brief(r["outlook"]))
    weeks = "".join("<tr><td>%s〜%s</td><td class=\"n\">%s</td><td class=\"n\">%d</td></tr>" % (
        d_md(x["start"]), d_md(x["end"]), man(x["shortEv"]), x["posts"]) for x in mo["weeks"])
    body = ("<ol class=\"sum\">%s</ol>" % "".join("<li>%s</li>" % esc(l.lstrip("・")) for l in lines[1:])
            + "<h2>月の合計(太平洋時間の日)</h2>" + totals_table(t, p)
            + "<p>投稿(日本時間):ショート %d 本(前月 %d 本)・長尺 %d 本</p>" % (mo["posts"]["short"], mo["posts"]["prevShort"], mo["posts"]["long"])
            + "<h3>週ごと</h3><table><thead><tr><th>週</th><th class=\"n\">ショートの EV</th><th class=\"n\">投稿</th></tr></thead><tbody>%s</tbody></table>" % weeks
            + regime_html(r.get("regime")) + effects_html(mo["effects"]) + (deep_html(r["deep"]) if r.get("deep") else "")
            + (ypp_html(r) if r.get("outlook") else "") + terms())
    return "\n".join(lines), page(title, "Youtube分析", provenance(r), body)
