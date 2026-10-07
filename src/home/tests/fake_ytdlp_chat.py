#!/usr/bin/env python3
"""テスト用の偽の yt-dlp(配信中の live_chat)。src/home/tests/test_live_detect.py が、盛り上がりの検出のワーカー(src/home/live_excite_worker.py の
ChatFeed)の yt-dlp の場所にこのファイルを渡す(.py なら同じ Python で動かす)。通信しない。
-o の名前(<stem>.%(ext)s)から <stem>.live_chat.json.part に 1 行 1 JSON を追記する(本物の配信中と同じ形 = 2026-10-07 の L0 の実測:
上位の鍵 isLive・replayChatItemAction・videoOffsetTimeMsec、renderer に timestampUsec)。

動きは環境変数 FAKE_YTDLP_CHAT(JSON のファイル)で決める。起動ごとに runs の次の要素を使う(足りなければ最後を繰り返す):
  {"log": 起動の記録のファイル(1 行 1 回の引数), "t0": 最初のメッセージの時刻(epoch),
   "runs": [{"mode": "write"|"stall"|"403"|"nochat"|"exit", "lines": 行数, "interval": 行の間の秒, "pad": 1 行に足す文字数, "code": 終了コード}]}
  write  … interval ごとに書き続ける(配信中のまま。lines は上限 = 書き終えたら待ち続ける)
  stall  … lines 行書いたら、何も書かずに待ち続ける(黙って止まる)
  403    … lines 行書いてから「HTTP Error 403: Forbidden」を出して終わる(終了コード 1)
  nochat … 「There are no subtitles for the requested languages」を出して終わる(ファイルを作らない。終了コード 0)
  exit   … lines 行書いて終わる(終了コード code)
  どの mode も "child": true なら、本物の yt-dlp(PyInstaller の 1 ファイルの exe)と同じく子プロセスを 1 つ起動して書くのは子にまかせ、親は子を待つ
  (子の pid は <log>.pids に 1 行ずつ。ワーカーが yt-dlp を止めたとき子も終わるかをテストが確かめる)
メッセージの時刻は t0 + 起動の番号 × 1000 + 行の番号(起動し直すほど新しい = 本物と同じく前の起動より後のメッセージ)。
"""
import json
import os
import subprocess
import sys
import time


def line(ts, pad):
    r = {"message": {"runs": [{"text": "草" + "x" * pad}]}, "timestampUsec": str(int(ts * 1e6)), "authorExternalChannelId": "UCfake"}
    return json.dumps({"isLive": True, "replayChatItemAction": {"actions": [{"addChatItemAction": {"item": {"liveChatTextMessageRenderer": r}}}]},
                       "videoOffsetTimeMsec": "1000"}, ensure_ascii=False) + "\n"


def main():
    args = sys.argv[1:]
    with open(os.environ["FAKE_YTDLP_CHAT"], encoding="utf-8") as f:
        spec = json.load(f)
    n = 0
    child = os.environ.get("FAKE_YTDLP_CHILD")
    if child is not None:   # 子: 親が数えた起動の番号のまま(記録は親が書いた)
        n = int(child)
    elif spec.get("log"):
        try:
            with open(spec["log"], encoding="utf-8") as f:
                n = sum(1 for _ in f)
        except OSError:
            n = 0
        with open(spec["log"], "a", encoding="utf-8") as f:
            f.write(json.dumps(args, ensure_ascii=False) + "\n")
    runs = spec.get("runs") or [{"mode": "write"}]
    run = runs[min(n, len(runs) - 1)]
    if run.get("child") and child is None:   # PyInstaller の 1 ファイルの exe のまね: 子を起動して、書くのは子にまかせて待つ
        p = subprocess.Popen([sys.executable, os.path.abspath(__file__)] + args, env=dict(os.environ, FAKE_YTDLP_CHILD=str(n)))
        if spec.get("log"):
            with open(spec["log"] + ".pids", "a", encoding="utf-8") as f:
                f.write("%d\n" % p.pid)
        return p.wait()
    mode = run.get("mode", "write")
    if mode == "nochat":
        print("[info] There are no subtitles for the requested languages", flush=True)
        return 0
    out = args[args.index("-o") + 1].replace(".%(ext)s", ".live_chat.json.part")
    t0 = float(spec.get("t0") or time.time()) + n * 1000
    lines = int(run.get("lines", 10 ** 9))
    interval, pad = float(run.get("interval", 0.05)), int(run.get("pad", 0))
    print("[youtube] Downloading live chat", flush=True)
    with open(out, "a", encoding="utf-8") as f:
        for i in range(lines):
            f.write(line(t0 + i, pad))
            f.flush()
            if mode == "write" or (mode == "stall" and i + 1 < lines):
                time.sleep(interval)
    if mode == "403":
        print("ERROR: unable to download video data: HTTP Error 403: Forbidden", flush=True)
        return 1
    if mode == "exit":
        return int(run.get("code", 0))
    while True:   # write・stall: 配信中のまま待つ(ワーカーが止める)
        time.sleep(1)


if __name__ == "__main__":
    sys.exit(main())
