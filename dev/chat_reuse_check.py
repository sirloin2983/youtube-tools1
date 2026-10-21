"""ライブのチャットの使い回し(src/flow/chatreuse.py。決定 3-117)の精度の確かめ: 同じ配信で、使い回したチャットとリプレイのチャットの
1 秒の箱と解析の候補(時刻・点数)を比べる。

    py -3.12 dev/chat_reuse_check.py <videoId> [<videoId> …] [--live <ライブで残したファイル> …] [--shift 秒]

--live が無いときは、リプレイ(スタジオの cache/chat)の各メッセージの絶対時刻(timestampUsec)からライブで取った形を作る(配信中に取った物の代わり。
時刻の当て方 = 絶対時刻 − アーカイブの 0 秒 の確かめになる)。アーカイブの 0 秒は「絶対時刻 − リプレイの秒」の中央値 + --shift(照合のずれの誤差を見る)。
--live があるときの 0 秒は --zero(epoch 秒)で渡す。音量はスタジオの控え(cache/signals)を読むだけ。解析の記録(archive)・控えは書かない。
"""
import argparse
import json
import os
import statistics
import sys
import tempfile

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(ROOT, "src"))

from flow import chatreuse as CR  # noqa: E402
from pipeline.analyze import analyze as AN, fetch as FE  # noqa: E402
from ytt import datadir as _datadir, studio_env as _env  # noqa: E402


def zero_of(replay):
    """リプレイの (絶対時刻 − 秒) の中央値 = アーカイブの 0 秒の絶対時刻と、そのばらつき(秒の四分位の幅)"""
    xs = []
    with open(replay, encoding="utf-8", errors="replace") as f:
        for line in f:
            try:
                ra = json.loads(line).get("replayChatItemAction") or {}
                off = int(ra.get("videoOffsetTimeMsec")) / 1000.0
            except (ValueError, TypeError, AttributeError):
                continue
            for a in ra.get("actions") or []:
                item = (a.get("addChatItemAction") or {}).get("item") or {}
                r = next(iter(item.values()), None) if item else None
                if isinstance(r, dict) and r.get("timestampUsec"):
                    xs.append(int(r["timestampUsec"]) / 1e6 - off)
    q = statistics.quantiles(xs, n=4) if len(xs) > 4 else [0, 0, 0]
    return statistics.median(xs), round(q[2] - q[0], 2), len(xs)


def analyze(vid, chat_file=None):
    """スタジオの既定の設定で解析(音量は控え・コメントは使わない・記録は書かない)-> 候補 [(start, end, score)]"""
    spec = AN.make_spec({"kind": "youtube", "videoId": vid}, AN.validate_settings({"useComments": False}))
    if chat_file:
        spec["chatFile"] = chat_file
    res = AN.run(spec)
    return [(round(c["start"], 1), round(c["end"], 1), round(c.get("score") or 0, 2)) for c in res["candidates"]], res["counts"]["chat"]


def match(a, b, tol=10.0):
    """候補の突き合わせ: a の山(start)から tol 秒以内の b がある数・時刻の差の平均・点数の比の平均"""
    hit, dt, ratio = 0, [], []
    for s, _e, sc in a:
        near = min(b, key=lambda x: abs(x[0] - s)) if b else None
        if near and abs(near[0] - s) <= tol:
            hit += 1
            dt.append(abs(near[0] - s))
            if sc:
                ratio.append(near[2] / sc)
    return {"same": hit, "of": len(a), "dtMean": round(statistics.mean(dt), 1) if dt else None,
            "scoreRatio": round(statistics.mean(ratio), 3) if ratio else None}


def main(argv=None):
    ap = argparse.ArgumentParser(description="ライブのチャットの使い回しの精度の確かめ")
    ap.add_argument("vids", nargs="+")
    ap.add_argument("--live", nargs="*", default=None)
    ap.add_argument("--zero", type=float, default=None)
    ap.add_argument("--shift", type=float, default=0.0)
    a = ap.parse_args(argv)
    _env.set_home(_datadir.resolve("studio"))   # スタジオの作業データ(控えを読むだけ)
    AN._save_record = lambda *x, **k: None   # 解析の記録は書かない(確かめるだけ)
    for vid in a.vids:
        replay = FE.chat_cache_path(vid)
        sig = AN.load_sig(vid)
        if not os.path.isfile(replay) or not sig:
            print(json.dumps({"vid": vid, "error": "リプレイか音量の控えがありません"}, ensure_ascii=False))
            continue
        z, spread, n = zero_of(replay)
        zero = (a.zero if a.zero is not None else z) + a.shift
        with tempfile.TemporaryDirectory() as tmp:
            made = os.path.join(tmp, vid + ".replay.json")
            st = FE.live_to_replay(a.live or [replay], zero, sig["dur"], made)
            bins = CR.compare(made, replay, sig["dur"])
            ref, nref = analyze(vid)
            got, ngot = analyze(vid, made)
        print(json.dumps({"vid": vid, "dur": sig["dur"], "zeroSpread": spread, "shift": a.shift, "stats": st, "bins": bins,
                          "chatCount": [nref, ngot], "cands": match(ref, got), "candsBack": match(got, ref)}, ensure_ascii=False))


if __name__ == "__main__":
    main()
