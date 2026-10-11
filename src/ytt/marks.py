"""マークの純粋な語彙(スタジオの data.json の配信のマーク。RS8 B3-2 で human/review/store.py から下ろした)。

ファイルにもロックにも触らない関数と定数だけ(標準ライブラリと ytt だけを import する)。
読み書きとロックは human/review/store.py の Store(B3-3 からは ② の置き場)、API の検査(validate_marks)と学習の記録も store に残る。
採用の規則 F-5 は pipeline/analyze/adopt.py(この語彙を読む)。ライブの採用(flow/live_adopt.py)・マークの正本(flow/live_export.py の
MarkStore)・束の検査(flow/spec.py)も、同じ区間の幅・長さの上限をここから読む(前は値を写していた)。

- マークの形: id・start・end(秒。小数 1 桁)・label・src(auto|manual|collab)・score・reasons・parts・peak・live・
  status(""|adopted|rejected|exported)・file・path・archived・createdAt・auto0・auto0Orig・collabFrom・adoptedBy
- 同じ区間 = 開始・終了の差がどちらも DUP_TOL(0.5 秒)以内(same・near)。少しでも重なる = overlaps。
  同じ場所 = ±SPOT_TOL(5 秒)以内で重なりが短いほうの半分以上(similar。人が消した候補の印の当て方。B3-3)
- 手を入れた自動マーク = 判定した・ラベルあり・時刻を EDIT_TOL より動かした(touched。再解析で残す境目)
- ライブの採用の使い回し = 同じ区間の最初のマーク(near_mark)・番号 = 開始の順の位置(order_of)(RS8 B3-5)
"""
import math
import operator
import os
import re
import sys

from ytt import schemas

ID_RE = re.compile(r"^[\w-]{1,40}\Z", re.ASCII)   # マーク・配信・グループの id
MAX_MARKS = 500
MAX_MARK_SEC = 3600
MAX_REQUEST_RANGES = 10  # 友人の依頼で1本の配信に指定できる区間の数(採用の規則 F-5 の ranges)
MAX_TIME = 1e7          # 秒。これを超える値は不正(巨大な数値対策)
PART_KEYS = ("audio", "chat", "comments")
STATUS_CLIENT = ("", "adopted", "rejected")   # クライアントが設定できる状態(exported はサーバーだけ)
DUP_TOL = 0.5           # 自動マークが既存マークとこれ以内のずれなら「同じ区間」
EDIT_TOL = 0.05         # 書き出し済みマークの時刻がこれより動いたら「書き出し済み」を外す
SPOT_TOL = 5.0          # 「同じ場所」(similar)の開始・終了の差の上限(秒。人が消した候補の印を再解析のずれにも当てる)
SPOT_RATIO = 0.5        # 「同じ場所」の重なりの率の下限(重なり / 短いほうの長さ)


def pos_int(x):
    """正の整数か(真偽値は除く)"""
    return schemas.is_int(x) and x > 0


by_score = lambda m: -(m["score"] or 0)            # noqa: E731  点数の高い順
by_time = operator.itemgetter("start", "end")      # 時刻の順


def ms_or_now(x):
    """保存された時刻(ミリ秒の正の整数)。壊れていれば今の時刻"""
    return x if pos_int(x) else schemas.now_ms()


def _warn(msg):
    sys.stderr.write("[marks] " + msg + "\n")


class BadMark(Exception):
    """マークの区間・形が正しくない(理由の文を持つ。呼ぶ側が 400 などに直す)"""


def fnum(v):
    """有限の数(文字列の数も受ける)。真偽値・数でない物・NaN・Infinity は None"""
    if isinstance(v, bool):
        return None
    try:
        x = float(v)
    except (TypeError, ValueError):
        return None
    return x if math.isfinite(x) else None


def num_strict(v):
    """JSON の数値(int/float)だけを受け付ける。文字列・真偽値・NaN・Infinity・巨大な値は None。"""
    x = schemas.num(v)
    return x if x is not None and abs(x) <= MAX_TIME else None


def clean_reasons(v):
    """理由の文(6 件・40 字まで)。リストでなければ []"""
    return [str(r)[:40] for r in v[:6]] if isinstance(v, list) else []


def clean_parts(v):
    """材料ごとの点数 {audio, chat, comments}(数のものだけ・小数 2 桁)。辞書でなければ {}"""
    parts = {}
    if isinstance(v, dict):
        for k in PART_KEYS:
            x = fnum(v.get(k))
            if x is not None:
                parts[k] = round(x, 2)
    return parts


def clamp_end(dur, s, e):
    """終わりを配信の長さ dur(秒。0・None なら切らない)で切る。開始より後でなくなれば None"""
    if dur and dur > 0:
        e = min(e, round(float(dur), 1))
    return e if e > s else None


def check_times(s_raw, e_raw):
    """開始・終了(秒)を検査して、小数1桁に丸めた (start, end) を返す。不正なら BadMark(理由)。"""
    s, e = num_strict(s_raw), num_strict(e_raw)
    if s is None or e is None:
        raise BadMark("開始・終了が数値ではありません(または大きすぎます)")
    if s < 0:
        raise BadMark("開始が0秒より前です")
    s, e = round(s, 1), round(e, 1)
    if e <= s:
        raise BadMark("終了が開始より後になっていません")
    if e - s > MAX_MARK_SEC:
        raise BadMark("長さが%d秒を超えています" % MAX_MARK_SEC)
    return s, e


def auto0(v):
    """機械の最初の区間 [開始, 終了](小数 1 桁)。形が違えば None"""
    if isinstance(v, (list, tuple)) and len(v) == 2:
        a, b = fnum(v[0]), fnum(v[1])
        if a is not None and b is not None:
            return [round(a, 1), round(b, 1)]
    return None


def collab_from(v):
    """コラボ転写マークの由来({videoId, markId})を検査する。不正なら None。"""
    if isinstance(v, dict):
        vid, mid = v.get("videoId"), v.get("markId")
        if isinstance(vid, str) and ID_RE.match(vid) and isinstance(mid, str) and ID_RE.match(mid):
            return {"videoId": vid, "markId": mid}
    return None


def clean_server(d):
    """サーバーだけが決める項目(src, 点数, 理由, 書き出し状態, auto0, collabFrom)を、型を整えて取り出す。"""
    st = d.get("status") if d.get("status") in ("", "adopted", "rejected", "exported") else ""
    f = str(d.get("file") or "")[:300] if st == "exported" and isinstance(d.get("file"), str) else ""
    # 書き出した mp4 の絶対パス(サーバーだけが決める。画面のマークの行から他のツールへ渡すリンクに使う。出力先を後で変えても元の場所が分かる)
    fp = d.get("path") if st == "exported" and f and isinstance(d.get("path"), str) and len(d.get("path")) <= 600 and "\x00" not in d.get("path") else ""
    score, peak = fnum(d.get("score")), fnum(d.get("peak"))
    reasons, parts = clean_reasons(d.get("reasons")), clean_parts(d.get("parts"))
    src = d.get("src") if d.get("src") in ("auto", "collab") else "manual"
    return {"src": src, "score": None if score is None else round(score, 2), "reasons": reasons, "parts": parts,
            "peak": None if peak is None else round(peak, 1), "status": st, "file": f if st == "exported" else "", "path": fp,
            # 本番版(アーカイブで作り直した版)に入れ替え済みの印(線 D の P4。サーバーだけが決める。live の配信のマークだけ = drop_archived で他は外す)
            "archived": d.get("archived") is True and st == "exported" and bool(f),
            "createdAt": ms_or_now(d.get("createdAt")),
            "auto0": auto0(d.get("auto0")) if src in ("auto", "collab") else None,
            "auto0Orig": auto0(d.get("auto0Orig")) if src == "manual" else None,   # 再解析で手動に変わったマークの、最初の自動区間(replace_auto だけが書く)
            "collabFrom": collab_from(d.get("collabFrom")) if src == "collab" else None,
            # 人ではなく機械が採用にした印(Q2。adopt_top = "auto"・request_marks の区間 = "request")。人が状態を変えたら外れる(build_mark)
            "adoptedBy": d.get("adoptedBy") if d.get("adoptedBy") in ("auto", "request") and st in ("adopted", "exported") else None}


def build_mark(m, old, trusted=False):
    """1件のマークを検査して整形する。不正なら BadMark。old: 同じ id の既存マーク(サーバー由来の値を引き継ぐ)。id は呼び出し側で検査済み。"""
    s, e = check_times(m.get("start"), m.get("end"))
    if old is not None:
        srv = clean_server(old)
        cs = m.get("status") if m.get("status") in STATUS_CLIENT else None   # クライアントが決められる状態(exported・未指定は無視)
        moved = abs(s - old["start"]) > EDIT_TOL or abs(e - old["end"]) > EDIT_TOL
        if srv["status"] == "exported":
            # 書き出し済みのマークの開始・終了を動かしたら、書き出し済みの扱いを外す(ファイルは別物になるため)。採用済みだった扱いに戻す
            if cs is not None:
                srv["status"], srv["file"] = cs, ""
            elif moved:
                srv["status"], srv["file"] = "adopted", ""
        elif cs is not None:
            srv["status"] = cs
        if cs is not None and cs != old.get("status"):
            srv["adoptedBy"] = None   # 人が状態を変えた = 人の判断になった
    elif trusted:
        srv = clean_server(m)
    else:
        srv = clean_server({})   # クライアントが作る新しいマークは、必ず手動・未書き出し(状態は 候補/採用/不採用 だけ指定できる)
        if m.get("status") in STATUS_CLIENT:
            srv["status"] = m["status"]
        if pos_int(m.get("createdAt")):
            srv["createdAt"] = m["createdAt"]
    label = m.get("label")
    d = {"id": m["id"], "start": s, "end": e, "label": label.strip()[:120] if isinstance(label, str) else "", "src": srv["src"], "score": srv["score"],
         "reasons": srv["reasons"], "parts": srv["parts"], "peak": srv["peak"], "live": bool(m.get("live")), "status": srv["status"], "file": srv["file"],
         "createdAt": srv["createdAt"]}
    if srv["file"] and srv.get("path"):   # file を外したとき(範囲の変更・状態の変更)は path も外れる
        d["path"] = srv["path"]
    if srv["file"] and srv.get("archived"):   # path と同じ扱い: 書き出し済みでなくなる(時刻を変えた・状態を変えた)と一緒に消える
        d["archived"] = True
    for k in ("auto0", "auto0Orig", "collabFrom"):
        if srv.get(k):
            d[k] = srv[k]
    if srv.get("adoptedBy") and d["status"] in ("adopted", "exported"):
        d["adoptedBy"] = srv["adoptedBy"]
    return d


def new_mark(prefix, s, e, status=""):
    """サーバーが作る新しいマーク(手動・ラベルなしで整形する。src などは呼び出し側が上書きする)。id は prefix + 乱数"""
    return build_mark({"id": prefix + os.urandom(5).hex(), "start": s, "end": e, "label": "", "live": False, "status": status, "createdAt": schemas.now_ms()}, None)


def load_marks(raw):
    """保存済み(信頼できる)マークの読み込み。壊れた1件は読み飛ばす(ログに残す)。"""
    out, seen = [], set()
    for m in raw if isinstance(raw, list) else []:
        try:
            if not isinstance(m, dict) or not isinstance(m.get("id"), str) or not ID_RE.match(m["id"]) or m["id"] in seen:
                raise BadMark("id")
            c = build_mark(m, None, True)
        except Exception as e:
            _warn("壊れたマークを読み飛ばしました: %s" % str(e)[:80])
            continue
        seen.add(c["id"])
        out.append(c)
        if len(out) >= MAX_MARKS:
            break
    return out


def drop_archived(marks, kind):
    """archived(本番版の印)は live の配信のマークだけ。data.json を手で直されても、他の種類には付けない"""
    if kind != "live":
        for m in marks:
            m.pop("archived", None)
    return marks


def near(a_s, a_e, b_s, b_e, tol=DUP_TOL):
    """2 つの区間の開始・終了の差がどちらも tol 秒以内か(同じ区間)"""
    return abs(a_s - b_s) <= tol and abs(a_e - b_e) <= tol


def same(a, b):
    """2 つのマーク(start・end を持つ辞書)が同じ区間か(±DUP_TOL 秒)"""
    return near(a["start"], a["end"], b["start"], b["end"])


def near_mark(marks, a, b, tol=DUP_TOL):
    """マークの並びのうち区間 [a, b] と同じ区間(開始・終了の差がどちらも tol 秒以内)の最初のマークか None。
    ライブの採用の使い回し(RS8 B3-5。スタジオの Store.adopt_live・案件の flow/casebook.live_adopt で同じ決まり)"""
    return next((m for m in marks if isinstance(m, dict) and near(m.get("start") or 0, m.get("end") or 0, a, b, tol)), None)


def order_of(marks, mid):
    """マークの番号 n = 開始(同じなら終了)の順に並べた位置(1 から。そのマークが無ければ 0)。ライブの書き出しの名前の番号(スタジオの画面と同じ)"""
    order = sorted((m for m in marks if isinstance(m, dict)), key=lambda m: (m.get("start") or 0, m.get("end") or 0))
    return next((i + 1 for i, m in enumerate(order) if m.get("id") == mid), 0)


def similar(a, b, tol=SPOT_TOL, ratio=SPOT_RATIO):
    """2 つのマーク(start・end を持つ辞書)が「同じ場所」か(same より緩い。RS8 B3-3・決定 3-37 の (r8l))。
    開始・終了の差がどちらも tol 秒(5 秒)以内で、重なりが短いほうの長さの ratio(半分)以上。
    人が消した候補の印(採用.json の rejected)を、再解析で時刻が少しずれた新しい候補にも当てるのに使う(flow/casebook)。
    重なりの率も見るのは、短い区間どうしが ±5 秒でほとんど重ならないのに同じとみなさないため"""
    if not near(a["start"], a["end"], b["start"], b["end"], tol):
        return False
    inter = min(a["end"], b["end"]) - max(a["start"], b["start"])
    short = min(a["end"] - a["start"], b["end"] - b["start"])
    return short > 0 and inter >= short * ratio


def overlaps(a_s, a_e, b_s, b_e):
    """2つの区間が少しでも重なっているか。コラボ転写・採用の規則で「既に同じような部分にマークがある」の判定に使う
    (same の ±0.5秒より緩い基準。転写側は COLLAB_MARGIN で前後に広げてあるので、単純な重なりで十分)。"""
    return a_s < b_e and b_s < a_e


def touched(m):
    """ユーザーが手を入れた自動マークか(採用・不採用・書き出し済み / ラベルあり / 時刻を動かした)。"""
    a0 = m.get("auto0")
    return (m["status"] != "" or bool(m["label"]) or not a0 or abs(m["start"] - a0[0]) > EDIT_TOL or abs(m["end"] - a0[1]) > EDIT_TOL)


def replace_auto(marks, cands, hide=None):
    """解析の候補を配信のマークに入れる(スタジオの再解析 human/review/store と、スタジオなしの解析 flow/studiobook で同じ 1 つ。RS8 の「URL も CLI で」で下ろした)。
    手を入れていない・書き出していない自動マークだけを置き換える。手を入れた自動マーク(touched)は手動マークとして残す(点数・理由は保持。
    auto0 は auto0Orig へ = 機械の最初の結果を残す)。新しい自動マークは、残したマークと同じ区間(same)なら作らない。
    hide(新しい自動マークの並び) -> 出す物の並び(案件の人が消した候補の印に当たる物を除く。None = 除かない)。
    -> (新しい一覧(時刻の順・MAX_MARKS まで。残したマークを優先し、自動を点数の高い順で減らす), 新しい自動マークの数)。marks・cands は変えない"""
    kept = []
    for m in marks:
        if m["src"] != "auto":
            kept.append(m)
        elif touched(m):
            k = dict(m, src="manual")
            a0 = k.pop("auto0", None)
            if a0:
                k["auto0Orig"] = a0
            kept.append(k)
    autos = []
    for c in cands:
        try:
            s, e = check_times(c["start"], c["end"])   # 手動と同じ規則(長さの上限など)
        except (BadMark, KeyError, TypeError):
            continue
        m = new_mark("a", s, e)
        m.update({"src": "auto", "score": fnum(c.get("score")), "reasons": clean_reasons(c.get("reasons")), "peak": fnum(c.get("peak")),
                  "parts": clean_parts(c.get("parts")), "auto0": [s, e]})
        if any(same(m, o) for o in kept + autos):
            continue
        autos.append(m)
    if hide is not None:
        autos = list(hide(autos))
    if len(kept) + len(autos) > MAX_MARKS:   # 残したマークを優先し、自動を減らす
        autos = sorted(autos, key=by_score)[:max(0, MAX_MARKS - len(kept))]
    return sorted(kept + autos, key=by_time)[:MAX_MARKS], len(autos)


def exported_mark(m, relfile, abspath=None, archived=None, live=False):
    """マーク m を「書き出し済み」にした新しいマーク(m は変えない。スタジオの Store.mark_exported と flow/studiobook で同じ 1 つ)。
    relfile = 書き出し先からの相対(区切り /)・abspath = 書き出した mp4 の絶対パス(あれば)。
    archived(live の配信だけ = live が真。線 D の P4): True = 本番版に入れ替え済みの印を立てる / False = 外す /
    None = ファイルが同じ(file・path が同じ)なら今の印のまま、違うファイルになったら外す"""
    nm = dict(m)
    old_file, old_path = m.get("file") if m["status"] == "exported" else None, m.get("path")
    nm["status"], nm["file"] = "exported", str(relfile)[:300]
    if isinstance(abspath, str) and abspath and len(abspath) <= 600 and os.path.isabs(abspath):
        nm["path"] = abspath
    else:
        nm.pop("path", None)
    same_file = old_file == nm["file"] and old_path == nm.get("path")
    if live and (archived is True or (archived is None and same_file and m.get("archived"))):
        nm["archived"] = True
    else:
        nm.pop("archived", None)
    return nm
