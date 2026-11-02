"""誰の声のカード(ソロの 10 秒・コラボの 10 秒)で [分からない] にしたカードの一覧を出す(11-02 ユーザー「わからないにしたやつ記憶しておいてほしい」)。
控えは src/app/check/voice_unknown.py(<app>/check/unknown-voice.jsonl と unknown-voice/<id>.wav)。Z で戻した分は出さない。読むだけ。

    py -3.12 dev/unknown_voices.py [--app <作業データ app のフォルダ>] [--json]
"""
import argparse
import json
import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "src"))
from app.check import voice_unknown  # noqa: E402


def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    ap.add_argument("--app", default=os.path.join(os.environ.get("LOCALAPPDATA", ""), "youtube-tools", "app"))
    ap.add_argument("--json", action="store_true", help="1 行 1 件の JSON で出す")
    a = ap.parse_args(argv)
    sys.stdout.reconfigure(encoding="utf-8")
    rows = voice_unknown.listing(a.app)
    for r in rows:
        if a.json:
            print(json.dumps(r, ensure_ascii=False))
        else:
            piece = " %s〜%s 秒" % tuple(r["piece"]) if r.get("piece") else ""
            print("%s  %s%s  %s  %s" % (r["day"], r.get("card"), piece, r.get("file") or "(音なし)", r.get("title") or ""))
    if not a.json:
        print("合計 %d 件" % len(rows))
    return 0


if __name__ == "__main__":
    sys.exit(main())
