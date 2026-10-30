# -*- coding: utf-8 -*-
"""友人のライブの依頼の届け方 = 区切りごとにまとめて届ける(10-30 ユーザーの仮決定 = 研究のおすすめ。decisions の最後の【重】)。

前の形(スイッチ BATCH_ON を切ると戻る): 候補ごとに入口が最初に見てから waitMin 分たったら自動で採用(live_detect の M11)+ 配信の後はアーカイブの全自動(M7)が足す。
この形(友人のライブの依頼の録画だけ。自分の配信・依頼の無い録画は前の形のまま):
  配信中   … 録画の秒で BATCH_MIN 分ごとの区切り(ワーカーが測った秒 measuredSec が区切りを過ぎたとき)に、前の区切りより後に区間の決まった候補
             (控えも含む・見送り・仮・終わり待ち・場面の途中は除く)から、最終の候補の点の順に選んで採用する(= 届ける)。
             本数は 1 録画で合計 BATCH_LIVE 本・区切りの時刻 B までに min(BATCH_LIVE, round(BATCH_LIVE × B ÷ EXPECT_SEC)) 本(届かなかった分は次の区切りへ)。
  配信の終わり … ワーカーが帳簿を締めたら(peaks.json の ended)、アーカイブを待たずに、配信中の候補の元の全部から最終の候補の点の順に、
             届けた候補と重ならない物を BATCH_LIVE + BATCH_END − 届けた本数 だけ採用する。
  候補の元 … 配信中の帳簿の 1 時間あたりの本数を POOL_PER_HOUR にする(依頼の perHour の代わり。live_detect.requests_cfg)。
  アーカイブ … この形の録画はアーカイブの全自動で採用しない(live_archive._after_on。解析・比べ(測るだけ)・録画を消すかの判定・記録は今のまま)。
最終の候補の点(研究の queue200_201.lc_scores = 仮説 8 + 0.5 × 前後 60 秒の笑いの件数の z): 選ぶ候補の中の z で
  z(点数) + 1.0 × z(跳ねる箱の割合) + 0.5 × z(笑いの書き込みの割合) + LAUGH_W × z(山の前後 excite.LAUGH_NEAR 秒の笑いの件数)。
  跳ねる箱の割合・笑いの割合・笑いの件数は帳簿の印 chatRank(rate・laugh・lc。excite.PeakBook)。チャットの印が無い候補が混ざれば点数の順。
本数は採用の上限と同じく、つないだ候補を元の本数で数える(ytt/marks.pieces_of。10-28 ユーザー)。
長い配信(10-30 の 3 回目・ユーザーの仮採用・研究の 270 番 = queue270.py の S。スイッチ LONG_ON): ワーカーが測った秒が LONG_AFTER(3 時間)を超えたら、
  そこから先の区切りを LONG_MIN 分ごとにし、配信の終わりに回す分も配信中に届ける(合計 BATCH_LIVE + BATCH_END = 6 本のまま・配信の終わりの分は無し)。
  区切りの累計の本数 = 3 時間の時点の累計 + 長い配信の区切りの数(1 区切り 1 本・6 本まで)。帳簿を締めたとき 3 時間を超えていれば、
  残り(6 − 届けた本数)を最後の区切りとして、前の区切りより後に区間の決まった候補から選ぶ(研究は配信の長さ n で割り振り、最後の区切り = n で残りをそろえる)。
  印 source.live.batch.long = true・min = LONG_MIN。
縮め(10-30 の 2 回目。研究の 274 番 = queue274.py の shrink。スイッチ SHRINK_ON): 採用する前に候補の終わりを笑いの収まり(帳簿の印 chatRank.settle)まで縮める。
  配信中 = ふだんを候補の始まりより前の箱で出した収まり(settle)・縮める量は SHRINK_LIVE_CAP 秒まで(研究の queue135_136.shrinker・上限 60)。
  配信の終わり = ふだんを全部の箱で出した収まり(settleAll)・上限なし(研究の queue62_shorter.apply の「(b) 笑いの収まり」= 62 番の形)。
  どちらも 山 + SHRINK_KEEP 秒より前にはしない・長さ SHRINK_MIN 秒より短くしない・始まりは変えない(研究の始まりの寄せ = 声の途切れへ戻す は入れていない)。収まりが無ければそのまま。
印: 採用した候補の決定(decisions.json)・ジョブ・.clip.json の source.live.batch = {kind: live|end, round(何回目の区切りか。終わりは null), min(区切りの分), cut(縮めた秒)}。
状態: 録画のフォルダ(live/excite/<録画元>/<録画>/)の batch.json(live_detect が書く)= {v, round(済んだ区切り), seen(区切りで見た候補), queue(採用を待つ候補), end}。
研究の作り方(読むだけ): C:/dev/overlap-research/tools/queue247_249.py・queue248_255.py・queue253.py。製品にそのまま移せない所は decisions の【重】。
"""
import math
import os

from ytt import fsio, marks as _marks, schemas
from pipeline.analyze import excite

BATCH_ON = True              # スイッチ: False = 前の形(waitMin 分たったら採用・配信の後はアーカイブの全自動)
BATCH_MIN = 30               # 配信中の区切りの間隔(分)
BATCH_LIVE = 4               # 配信中に届ける本数(1 録画の合計)
BATCH_END = 2                # 配信の終わりに届ける本数(配信中に届かなかった分はここへ足す)
POOL_PER_HOUR = 10           # 配信中の候補の元の 1 時間あたりの本数(依頼の perHour の代わり)
EXPECT_SEC = 2 * 3600.0      # 配信中の本数の割り振りに使う配信の長さの見込み(研究は本当の長さで割り振る = 配信中は分からないので仮の値)
LONG_ON = True               # スイッチ: 長い配信の切り替えだけを切る(False = 3 時間を超えても 30 分ごと・4 + 2 のまま)
LONG_AFTER = 3 * 3600.0      # 長い配信に切り替える、ワーカーが測った秒(3 時間)
LONG_MIN = 60                # 長い配信の区切りの間隔(分)
SHRINK_ON = True             # スイッチ: 縮めだけを切る(False = 帳簿の区間のまま届ける)
SHRINK_KEEP = 10.0           # 縮めても山のあとに残す秒
SHRINK_MIN = 20.0            # 縮めたあとの最短の長さ(秒)
SHRINK_LIVE_CAP = 60.0       # 配信中に縮める量の上限(秒。研究の 274 番 = 60。136 番は 30)
SHRINK_END_CAP = None        # 配信の終わりに縮める量の上限(秒。None = 上限なし = 研究の 62 番の形)
LAUGH_W = 0.5               # 笑いの件数の z の重み
STATE_FILE = "batch.json"
OUT = ("dismissed",)


def on(req):
    """この録画をこの形で届けるか(友人のライブの依頼の録画で、スイッチがオン)"""
    return BATCH_ON and req is not None


def batch_sec():
    return BATCH_MIN * 60.0


def settled(pk):
    """区間の決まった候補か(見送り・仮・終わり待ち・場面の途中は除く。採用済みは含む)"""
    return (isinstance(pk, dict) and pk.get("state") not in OUT and not pk.get("provisional") and not pk.get("endPending")
            and not pk.get("sceneOpen") and schemas.is_num(pk.get("start")) and schemas.is_num(pk.get("end")) and isinstance(pk.get("id"), str))


def live_quota(b):
    """区切りの時刻 b(録画の秒)までに配信中で届ける本数(累計。長い配信に切り替える前の形)"""
    return min(BATCH_LIVE, int(math.floor(BATCH_LIVE * b / EXPECT_SEC + 0.5)))


def short_rounds():
    """長い配信に切り替えるまでの区切りの数(3 時間 ÷ 30 分 = 6。LONG_AFTER の区切りまでは前の形)"""
    return int(LONG_AFTER // batch_sec())


def is_long(k):
    """k 番目の区切りが長い配信の区切りか"""
    return LONG_ON and k > short_rounds()


def round_of(b):
    """ワーカーが測った秒 b -> 過ぎた区切りの番号(1 から。長い配信は LONG_AFTER の後 LONG_MIN 分ごと)"""
    if not schemas.is_num(b) or b <= 0:
        return 0
    if not LONG_ON or b <= LONG_AFTER:
        return int(b // batch_sec())
    return short_rounds() + int((b - LONG_AFTER) // (LONG_MIN * 60.0))


def round_at(k):
    """k 番目の区切りの録画の秒"""
    if not is_long(k):
        return k * batch_sec()
    return LONG_AFTER + (k - short_rounds()) * LONG_MIN * 60.0


def quota(k):
    """k 番目の区切りまでに配信中で届ける本数(累計)。長い配信は 3 時間の時点の累計 + 長い区切りの数(合計 BATCH_LIVE + BATCH_END まで)"""
    if not is_long(k):
        return live_quota(round_at(k))
    return min(BATCH_LIVE + BATCH_END, live_quota(LONG_AFTER) + k - short_rounds())


def final_scores(cs):
    """候補の一覧 -> 最終の候補の点(同じ順)。チャットの印(chatRank の rate・laugh・lc)が揃わなければ点数"""
    sc = [float(c.get("score") or 0.0) for c in cs]
    ranks = [c.get("chatRank") if isinstance(c.get("chatRank"), dict) else None for c in cs]
    if len(cs) < 2 or any(r is None or not all(schemas.is_num(r.get(k)) for k in ("rate", "laugh", "lc")) for r in ranks):
        return sc
    wb, wl = excite.RERANK_W
    z = excite.zlist
    zs_, zb, zl, zc = z(sc), z([r["rate"] for r in ranks]), z([r["laugh"] for r in ranks]), z([r["lc"] for r in ranks])
    return [a + wb * b + wl * c + LAUGH_W * d for a, b, c, d in zip(zs_, zb, zl, zc)]


def ranked(cs):
    """候補を最終の候補の点の高い順に(同じ点なら点数の高い順)"""
    sc = final_scores(cs)
    order = sorted(range(len(cs)), key=lambda i: (-sc[i], -float(cs[i].get("score") or 0.0)))
    return [cs[i] for i in order]


def overlaps(pk, others):
    return any(o["start"] < pk["end"] and pk["start"] < o["end"] for o in others)


def take(order, room, taken):
    """順に並べた候補から、採用済み・選んだ候補と重ならない物を、元の本数で room 本まで"""
    out = []
    for pk in order:
        if room <= 0:
            break
        n = _marks.pieces_of(pk)
        if pk.get("state") == "adopted" or n > room or overlaps(pk, taken + out):
            continue
        out.append(pk)
        room -= n
    return out


def pick_live(peaks, seen, room):
    """配信中の区切り: 前の区切りより後に区間の決まった候補(seen に無い・採用済みでない)から room 本"""
    new = [p for p in peaks if settled(p) and p["id"] not in seen and p.get("state") != "adopted"]
    return take(ranked(new), room, [p for p in peaks if settled(p) and p.get("state") == "adopted"])


def pick_end(peaks, room):
    """配信の終わり: 候補の元の全部(点の z は採用済みも入れた全部の中で)から、採用済みと重ならない物を room 本"""
    pool = [p for p in peaks if settled(p)]
    return take(ranked(pool), room, [p for p in pool if p.get("state") == "adopted"])


def mark(kind, rnd, long=False):
    """候補・ジョブ・.clip.json に残す印(long = 長い配信の形で選んだ)"""
    return {"kind": kind, "round": rnd, "min": LONG_MIN if long else BATCH_MIN, **({"long": True} if long else {})}


def shrink(pk, kind):
    """採用する前に候補の終わりを笑いの収まりまで縮める -> (候補の写し, 縮めた秒)。kind = live(配信中)| end(配信の終わり)"""
    cr = pk.get("chatRank") if isinstance(pk.get("chatRank"), dict) else {}
    p = cr.get("settle" if kind == "live" else "settleAll")
    if not SHRINK_ON or not schemas.is_num(p):
        return dict(pk), 0.0
    s, e0 = float(pk["start"]), float(pk["end"])
    at = pk.get("peak") if schemas.is_num(pk.get("peak")) else (s + e0) / 2.0
    cap = SHRINK_LIVE_CAP if kind == "live" else SHRINK_END_CAP
    e = min(e0, max(float(p), at + SHRINK_KEEP))
    if cap is not None:
        e = max(e, e0 - cap)
    if e - s < SHRINK_MIN:
        e = min(e0, s + SHRINK_MIN)
    return dict(pk, end=round(e, 3)), round(e0 - e, 1)


def clean_mark(v):
    """採用の本文の batch -> 印か None(入口の中から渡す。形の違う物は残さない)"""
    if not isinstance(v, dict) or v.get("kind") not in ("live", "end"):
        return None
    rnd = v.get("round")
    mn = v.get("min")
    return {"kind": v["kind"], "round": rnd if isinstance(rnd, int) and not isinstance(rnd, bool) and rnd >= 0 else None,
            "min": mn if isinstance(mn, int) and not isinstance(mn, bool) and mn > 0 else BATCH_MIN,
            **({"cut": float(v["cut"])} if schemas.is_num(v.get("cut")) and v["cut"] > 0 else {}),
            **({"long": True} if v.get("long") is True else {})}


def load(folder):
    d = fsio.read_json_or(os.path.join(folder, STATE_FILE), None, 1024 * 1024, kind=dict) or {}
    rnd = d.get("round")
    return {"v": 1, "round": rnd if isinstance(rnd, int) and not isinstance(rnd, bool) else 0,
            "seen": [x for x in d.get("seen") or [] if isinstance(x, str)],
            "queue": [x for x in d.get("queue") or [] if isinstance(x, dict) and isinstance(x.get("id"), str) and clean_mark(x.get("batch"))],
            "end": d.get("end") is True}


def save(folder, st, dump):
    os.makedirs(folder, exist_ok=True)
    fsio.atomic_write(os.path.join(folder, STATE_FILE), dump(st))
