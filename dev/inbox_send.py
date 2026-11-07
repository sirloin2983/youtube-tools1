#!/usr/bin/env python3
"""作業中のセッションへの追加の指示を、そのセッションの受け箱に書き足す(11-07。ユーザー OK「これでいい」)。

アプリの SendMessage は、相手が作業中だと今の作業が終わるまで読まれない。受け箱に書くと、相手のフック(dev/inbox_hook.py。
道具を 1 回使うたびに動く PostToolUse)が次の 1 手で読ませる。相手が idle なら今までどおり SendMessage でよい。

    py -3.12 dev/inbox_send.py local_<相手の id> "指示の文"
    py -3.12 dev/inbox_send.py --list            # 受け箱に残っている(まだ読まれていない)物

宛先はアプリのセッションの id(local_…。「Linked sessions now」の id)。送り手は自分の CLAUDE_CODE_HOST_SESSION_ID(無ければ "?")。
置き場所: 共有のメモのフォルダ(side-session-notes)の inbox\\<相手の id>.jsonl。読まれた分は inbox\\done\\<相手の id>.jsonl へ移る。
止めるスイッチ: inbox\\OFF というファイルを置くと、フックは何もしない(この道具も書かずに断る)。
"""
import argparse
import json
import os
import re
import sys
import time

sys.stdout.reconfigure(encoding="utf-8")
NOTES = os.path.join(os.environ.get("LOCALAPPDATA", ""), "Claude-Data", "claude_pzs8sxrjxfjjc", "side-session-notes")
INBOX = os.environ.get("YTT_INBOX_DIR") or os.path.join(NOTES, "inbox")
ID_RE = re.compile(r"^local_[0-9a-f-]{36}$")
TEXT_MAX = 4000


def box(sid):
    return os.path.join(INBOX, sid + ".jsonl")


def send(to, text, sender=None, now=None):
    """-> 書いた行。宛先の形が違う・止めるスイッチがあれば ValueError"""
    if not ID_RE.match(to or ""):
        raise ValueError("宛先はアプリのセッションの id(local_ と 36 文字)にしてください: %r" % (to,))
    if os.path.exists(os.path.join(INBOX, "OFF")):
        raise ValueError("受け箱は止めてあります(%s の OFF)。SendMessage で送ってください" % INBOX)
    text = str(text or "").strip()
    if not text:
        raise ValueError("指示の文が空です")
    row = {"at": int((time.time() if now is None else now) * 1000), "from": sender or os.environ.get("CLAUDE_CODE_HOST_SESSION_ID") or "?",
           "text": text[:TEXT_MAX]}
    os.makedirs(INBOX, exist_ok=True)
    with open(box(to), "a", encoding="utf-8") as f:
        f.write(json.dumps(row, ensure_ascii=False) + "\n")
    return row


def main():
    ap = argparse.ArgumentParser(description="作業中のセッションの受け箱に追加の指示を書き足す")
    ap.add_argument("to", nargs="?", help="宛先のアプリのセッションの id(local_…)")
    ap.add_argument("text", nargs="?", help="指示の文")
    ap.add_argument("--list", action="store_true", help="まだ読まれていない受け箱を並べる")
    a = ap.parse_args()
    if a.list:
        for fn in sorted(os.listdir(INBOX)) if os.path.isdir(INBOX) else []:
            if fn.endswith(".jsonl"):
                with open(os.path.join(INBOX, fn), encoding="utf-8") as f:
                    n = sum(1 for line in f if line.strip())
                print("%s  %d 件" % (fn[:-6], n))
        return 0
    if not a.to or not a.text:
        ap.error("宛先と指示の文が要ります")
    try:
        row = send(a.to, a.text)
    except ValueError as e:
        print("[断った] %s" % e)
        return 1
    print("受け箱に書きました(%s・%d 字)。相手が次に道具を使うときに読まれます" % (a.to, len(row["text"])))
    return 0


if __name__ == "__main__":
    sys.exit(main())
