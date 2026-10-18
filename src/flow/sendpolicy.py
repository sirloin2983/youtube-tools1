# -*- coding: utf-8 -*-
"""② 管理の層 flow: 友人へ自動で送るかの判定(D-SEND の段 1。要件は notes:plan/done/d-send-requirements.md の 2-1・2-8・2-9)。

純粋(ファイル・ネットワークを読まない)。送る・送らないの決まりと、送らなかった理由の文(案件の画面とログで同じ言い方にそろえる 1 か所)だけを持つ。
出どころ(origin): "request" = 友人の依頼 / "auto" = 自分の配信から自動で / "manual" = 案件の画面の [友人へ届ける](人が決めた)。
判定をかけるのは "auto" だけ(ライブの自動の切り抜きは、いつも新しいので呼ばなくてよい)。
"""
import os

FRESH_SEC = 48 * 3600   # 終わってから何秒までの配信を自動で送るか(2-1。設定の欄は作らない)
ORIGINS = ("request", "auto", "manual")
ENV_SWITCH = "YTT_AUTO_SEND"   # 開発機の守り: off で origin auto の届けを止める(switched_off)
WAS_LIVE = ("was_live", "post_live")

# 理由の鍵 -> 文。stale だけ %(hours)d を持つ(reason_text に hours=)
REASONS = {"unchecked": "チェックを外したので送りません",
           "stale": "古い配信なので送りません(終わってから %(hours)d 時間)",
           "requested": "友人の依頼があるので送りません",
           "expired": "送らなかった(古くなった)",
           "unknown_end": "配信の終わった時刻が分からないので送りません"}


def _num(v):
    return isinstance(v, (int, float)) and not isinstance(v, bool)


def hours_since(ended_at, now):
    """終わってから何時間か(切り捨て。負は 0)"""
    return max(0, int((now - ended_at) // 3600))


def decide(origin, ended_at, now, requested, checked):
    """-> (送るか, 送らない理由の鍵か None)。origin が auto 以外(request・manual)はいつも送る(人が決めた・友人が頼んだ)。
    auto は上から: チェックを外した(unchecked)→ 友人の依頼がある(requested)→ 終わった時刻が分からない(unknown_end)→ 48 時間を過ぎた(stale)。
    ended_at・now は秒(epoch)。未来の ended_at は新しい扱い"""
    if origin != "auto":
        return True, None
    if not checked:
        return False, "unchecked"
    if requested:
        return False, "requested"
    if not _num(ended_at) or ended_at <= 0:
        return False, "unknown_end"
    if now - ended_at > FRESH_SEC:
        return False, "stale"
    return True, None


def reason_text(code, hours=None):
    """理由の鍵 -> 画面とログの文。知らない鍵は鍵をそのまま。stale は hours(時間)を入れる"""
    t = REASONS.get(code)
    if t is None:
        return str(code)
    return t % {"hours": int(hours or 0)} if "%(" in t else t


def ended_at_of(analysis):
    """スタジオの配信の行の analysis -> 配信が終わった時刻(epoch 秒)か None(分からない = 送らない)。
    liveStatus が was_live・post_live で releaseTs(配信の始まり)と duration(長さ。秒)があれば releaseTs + duration。
    ほか(動画・ライブ中・項目なし・壊れた値)は None(① pipeline/analyze/fetch.slim_meta の項目を batch が analysis に写す)"""
    if not isinstance(analysis, dict) or analysis.get("liveStatus") not in WAS_LIVE:
        return None
    start, dur = analysis.get("releaseTs"), analysis.get("duration")
    if not _num(start) or not _num(dur) or start <= 0 or dur <= 0:
        return None
    return float(start) + float(dur)


def switched_off(environ=None):
    """環境変数 YTT_AUTO_SEND=off(開発機の守り)か。True のとき origin auto の届けをしない"""
    env = os.environ if environ is None else environ
    return str(env.get(ENV_SWITCH) or "").strip().lower() == "off"
