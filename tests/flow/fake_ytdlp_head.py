# -*- coding: utf-8 -*-
"""偽の yt-dlp(tests/flow/test_live_head.py)。本物の YouTube へは繋がない。
引数と cookies の環境変数の有無を FAKE_HEAD_OUT/<頭の名前>.args.json に書き、子(眠るだけ)を 1 つ作ってその pid を FAKE_HEAD_OUT/<頭の名前>.pids に書き、
<頭>.mp4 に少しずつ書き続ける(止められるまで)。環境変数 FAKE_HEAD_MODE=fail なら ERROR を出して終わる。"""
import json
import os
import subprocess
import sys
import time

COOKIES_ENV = "YTT_YTDLP_COOKIES"


def main(argv):
    out = argv[argv.index("-o") + 1]
    prefix = out[:-len(".%(ext)s")]
    rec = os.path.join(os.environ["FAKE_HEAD_OUT"], os.path.basename(prefix))
    with open(rec + ".args.json", "w", encoding="utf-8") as f:
        json.dump({"argv": argv, "cookieEnv": COOKIES_ENV in os.environ}, f)
    if os.environ.get("FAKE_HEAD_MODE") == "fail":
        print("ERROR: [youtube] fake: This live event has ended.", flush=True)
        return 1
    child = subprocess.Popen([sys.executable, "-c", "import time; time.sleep(600)"], creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0))
    with open(rec + ".pids", "w", encoding="utf-8") as f:
        f.write("%d %d" % (os.getpid(), child.pid))
    with open(prefix + ".mp4", "ab") as f:
        while True:
            f.write(b"\0" * 20000)
            f.flush()
            time.sleep(0.05)


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
