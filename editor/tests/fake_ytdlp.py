#!/usr/bin/env python3
"""テスト用の偽の yt-dlp(環境変数 TRANSCRIBE_YTDLP にこのファイルのパスを入れて使う。ed_ytcap.ytcap_command が .py ならこの Python で動かす)。
通信しない。本物と同じく、-o の出力の名前(cap.%(ext)s)で cap.<言語>.json3 を書き、--print の形(YTCAP<TAB>公開の範囲<TAB>配信の状態<TAB>手の字幕の JSON)を標準出力へ。

環境変数:
  FAKE_YTDLP_MODE=auto(既定)|manual|none|private|unavailable|bot|unlisted|live|fail
      auto    自動字幕だけ(cap.ja-orig.json3 と、同じ中身の cap.ja.json3 = 本物も元の言葉が日本語なら同じ)
      manual  配信者が付けた字幕(cap.ja.json3 = FAKE_YTDLP_MANUAL_JSON3)と自動字幕(cap.ja-orig.json3)
      none    字幕なし(終了コード 0)
      private / unavailable / bot  本物と同じ形の ERROR を標準エラーへ・終了コード 1
      unlisted / live  --print の公開の範囲・配信の状態だけ変える(字幕は auto と同じ)
      fail    よく分からない失敗(終了コード 2)
  FAKE_YTDLP_JSON3=パス         自動字幕の中身(無ければ小さな既定)
  FAKE_YTDLP_MANUAL_JSON3=パス  配信者の字幕の中身(無ければ既定)
  FAKE_YTDLP_SLEEP=秒           終わる前に待つ(取り消し・時間の上限の確認)
  FAKE_YTDLP_LOG=パス           受け取った引数を 1 行 1 回の JSON で足す(使い回し・引数の確認)
"""
import json
import os
import sys
import time

DEFAULT_AUTO = {"events": [{"tStartMs": 0, "dDurationMs": 999999, "id": 1},
                           {"tStartMs": 1000, "dDurationMs": 3000, "segs": [{"utf8": "こんにちは"}, {"utf8": "テスト", "tOffsetMs": 600}]},
                           {"tStartMs": 4000, "aAppend": 1, "segs": [{"utf8": "\n"}]}]}
DEFAULT_MANUAL = {"events": [{"tStartMs": 1000, "dDurationMs": 3000, "segs": [{"utf8": "こんにちは(手)"}]}]}


def load(env, default):
    p = os.environ.get(env)
    if p:
        with open(p, encoding="utf-8") as f:
            return json.load(f)
    return default


def main():
    args = sys.argv[1:]
    if os.environ.get("FAKE_YTDLP_LOG"):
        with open(os.environ["FAKE_YTDLP_LOG"], "a", encoding="utf-8") as f:
            f.write(json.dumps(args, ensure_ascii=False) + "\n")
    mode = os.environ.get("FAKE_YTDLP_MODE", "auto")
    out = args[args.index("-o") + 1] if "-o" in args else "cap.%(ext)s"
    url = args[args.index("--") + 1] if "--" in args else ""
    vid = url.rsplit("=", 1)[-1]
    if float(os.environ.get("FAKE_YTDLP_SLEEP") or 0):
        time.sleep(float(os.environ["FAKE_YTDLP_SLEEP"]))
    if mode == "private":
        sys.stderr.write("ERROR: [youtube] %s: Private video. Sign in if you've been granted access to this video\n" % vid)
        return 1
    if mode == "unavailable":
        sys.stderr.write("ERROR: [youtube] %s: Video unavailable. This video has been removed by the uploader\n" % vid)
        return 1
    if mode == "bot":
        sys.stderr.write("ERROR: [youtube] %s: Sign in to confirm you’re not a bot. Use --cookies-from-browser or --cookies for the authentication.\n" % vid)
        return 1
    if mode == "fail":
        sys.stderr.write("ERROR: something strange happened\n")
        return 2
    avail = "unlisted" if mode == "unlisted" else "public"
    live = "is_live" if mode == "live" else "was_live"
    subs = {"live_chat": [{"ext": "json"}]}
    if mode == "manual":
        subs["ja"] = [{"ext": "json3"}]
    sys.stdout.write("[youtube] Extracting URL: %s\n" % url)
    sys.stdout.write("YTCAP\t%s\t%s\t%s\n" % (avail, live, json.dumps(subs)))

    def write(lang, obj):
        path = out.replace("%(ext)s", lang + ".json3").replace("%%", "%")
        with open(path, "w", encoding="utf-8") as f:
            json.dump(obj, f, ensure_ascii=False)
    if mode != "none":
        auto = load("FAKE_YTDLP_JSON3", DEFAULT_AUTO)
        write("ja-orig", auto)
        write("ja", load("FAKE_YTDLP_MANUAL_JSON3", DEFAULT_MANUAL) if mode == "manual" else auto)
    return 0


if __name__ == "__main__":
    sys.exit(main())
