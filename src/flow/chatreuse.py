"""② ライブで取ったチャットの使い回し(決定 3-117)。配信中のワーカー(① pipeline/analyze/live_excite_worker.py)が読み終えた生のチャットを、
ここが決めた置き場所 <ライブの作業データ>/chat-keep へ移す(config.json の chatKeepDir)。配信後の全自動(flow/live_archive)がアーカイブを解析するとき、
そのチャットをリプレイの形に直して(① fetch.live_to_replay)、途切れが無ければ解析へ渡す(リプレイを取らない = 解析の取得の時間のほとんど)。

どれを渡すかはここだけが決める(① はライブのフォルダを探さない):
- 同じ配信(videoId)の残したファイル・アーカイブの 0 秒の絶対時刻 = 配信の開始時刻 t0 − 照合のずれ offset(live_archive の向き: アーカイブの秒 = 絶対時刻 − t0 + offset)
- 途切れ: 頭・終わり・メッセージの間の空きが GAP_MAX 秒まで・件数が MIN_COUNT 以上(起動し直しの継ぎ目・回しの抜け・録画より前に始まった配信は空きになる)
スイッチ MODE: off = 残さない(今までどおり消す)/ measure = 残して比べるだけ(解析はリプレイを取る。済んだらリプレイと 1 秒の箱を比べて
chat-reuse.jsonl に 1 行)/ on = 途切れが無ければ解析へ渡す / auto(既定)= 比べた記録が READY_N 本続けて近い(ready)までは measure、そのあと on。
近いの決まり(ok): 件数の比 0.9〜1.1・10 秒の箱の相関 0.9 以上・ずれ ±LAG_OK 秒(dev/chat_reuse_check.py の確かめ: 0 秒が ±5 秒ずれても
解析の遅れの推定が吸収して候補は同じ、20 秒ずれると候補が全部変わる)。片付けは物の終わりの日数(flow/retention.KEEP_SEC)。
"""
import glob
import json
import math
import os
import time

from pipeline.analyze import analyze as _analyze, fetch as _fetch
from ytt import fsio

from . import retention as _retention

MODE = "auto"        # スイッチ: off | measure | on | auto(上の説明)
READY_N = 2          # auto: 使い始めるまでに続けて近いと分かった配信の数
LAG_OK = 6           # 近いと見るずれの上限(秒)
KEEP_NAME = "chat-keep"
LOG_NAME = "chat-reuse.jsonl"
GAP_MAX = 300.0      # 頭・終わり・メッセージの間の空きの上限(秒)。超えたらリプレイを取る
MIN_COUNT = 30       # 解析がチャットを使う件数(analyze の 30 件)と同じ
LOG_MAX = 2 * 1024 * 1024


def keep_dir(store_dir):
    """生のチャットを移す先(ワーカーへは config.json の chatKeepDir。off なら None = 今までどおり消す)"""
    return os.path.join(store_dir, KEEP_NAME) if MODE != "off" else None


def files_of(store_dir, vid):
    """同じ配信の残したファイル(通し番号の順)"""
    d = os.path.join(store_dir, KEEP_NAME)

    def gen(p):
        try:
            return int(os.path.basename(p).split(".")[1])
        except (IndexError, ValueError):
            return 0
    return sorted(glob.glob(os.path.join(glob.escape(d), glob.escape(vid) + ".*.live_chat.json")), key=gen) if vid else []


def prepare(store_dir, vid, t0, offset, dur):
    """配信 vid のアーカイブの解析に渡すチャットを作る -> {"path"(渡してよい物 か None), "made"(作ったファイル), "stats", "why"}。
    path が None でも made があれば measure の比べに使える"""
    out = {"path": None, "made": None, "stats": None, "why": ""}
    files = files_of(store_dir, vid)
    if not files:
        out["why"] = "ライブで取ったチャットが残っていません"
        return out
    if not all(isinstance(x, (int, float)) and math.isfinite(x) for x in (t0, offset, dur)) or dur <= 0:
        out["why"] = "アーカイブの時刻(開始・ずれ・長さ)が分かりません"
        return out
    made = os.path.join(store_dir, KEEP_NAME, vid + ".replay.json")
    try:
        st = _fetch.live_to_replay(files, t0 - offset, dur, made)
    except (OSError, ValueError) as e:
        out["why"] = "ライブのチャットを直せませんでした: %s" % e.__class__.__name__
        return out
    out["made"], out["stats"] = made, st
    if st["count"] < MIN_COUNT:
        out["why"] = "ライブのチャットが少なすぎます(%d 件)" % st["count"]
    elif st["maxGap"] > GAP_MAX:
        out["why"] = "ライブのチャットに %d 秒の空きがあります(途切れ)" % st["maxGap"]
    else:
        out["path"] = made
    return out


def compare(live_path, replay_path, dur):
    """同じ配信のライブのチャット(リプレイの形に直した物)とリプレイを、解析と同じ読み方(① analyze.parse_chat)で 1 秒の箱にして比べる
    -> {"countLive", "countReplay", "ratio", "corr10"(10 秒の箱の活気の相関), "lag"(相関がいちばん高いずれの秒。±30)}"""
    n = int(math.ceil(dur))
    a, ca, _w = _analyze.parse_chat(live_path, n)
    b, cb, _w = _analyze.parse_chat(replay_path, n)

    def box(x):
        return [sum(x[i:i + 10]) for i in range(0, n, 10)]

    def corr(x, y):
        m = min(len(x), len(y))
        x, y = x[:m], y[:m]
        if m < 3:
            return None
        mx, my = sum(x) / m, sum(y) / m
        sx = math.sqrt(sum((v - mx) ** 2 for v in x))
        sy = math.sqrt(sum((v - my) ** 2 for v in y))
        return round(sum((p - mx) * (q - my) for p, q in zip(x, y)) / (sx * sy), 3) if sx and sy else None
    best = max(((corr(a[max(0, -k):], b[max(0, k):]) or -1.0, k) for k in range(-30, 31, 2)))
    return {"countLive": ca, "countReplay": cb, "ratio": round(ca / cb, 3) if cb else None, "corr10": corr(box(a), box(b)), "lag": best[1]}


def ok(got):
    """比べた結果が近いか(上の決まり)"""
    r, c, lag = got.get("ratio"), got.get("corr10"), got.get("lag")
    return all(isinstance(x, (int, float)) for x in (r, c, lag)) and 0.9 <= r <= 1.1 and c >= 0.9 and abs(lag) <= LAG_OK


def mode_now(store_dir):
    """今の形(off | measure | on)。auto は比べた記録の新しい READY_N 本がどれも近ければ on"""
    if MODE != "auto":
        return MODE
    rows = []
    try:
        with open(os.path.join(store_dir, LOG_NAME), encoding="utf-8") as f:
            for line in f:
                try:
                    d = json.loads(line)
                except ValueError:
                    continue
                if isinstance(d, dict) and d.get("kind") == "compare":
                    rows.append(d)
    except OSError:
        pass
    last = rows[-READY_N:]
    return "on" if len(last) >= READY_N and all(ok(d) for d in last) else "measure"


def log(store_dir, rec):
    """比べた結果・渡したかの記録(chat-reuse.jsonl に 1 行。大きくなりすぎたら書かない)"""
    p = os.path.join(store_dir, LOG_NAME)
    try:
        if os.path.isfile(p) and os.path.getsize(p) > LOG_MAX:
            return
        with open(p, "a", encoding="utf-8", newline="\n") as f:
            f.write(json.dumps(dict(rec, at=int(time.time())), ensure_ascii=False) + "\n")
    except OSError:
        pass


def prune(store_dir, now=None, keep=None):
    """残したチャットを物の終わりの日数で片付ける(更新が古い物から)-> 消した数"""
    now, keep = time.time() if now is None else now, _retention.KEEP_SEC if keep is None else keep
    n = 0
    for p in glob.glob(os.path.join(glob.escape(os.path.join(store_dir, KEEP_NAME)), "*")):
        try:
            if now - os.path.getmtime(p) > keep:
                fsio.unlink_quiet(p)
                n += 1
        except OSError:
            pass
    return n
