#!/usr/bin/env python3
"""受け箱のフック(PostToolUse。11-07): 道具を 1 回使うたびに、自分のセッションの受け箱(dev/inbox_send.py が書く)に新しい指示があれば、
hookSpecificOutput.additionalContext で作業中の Claude に渡し、渡した分を受け箱から控え(inbox\\done)へ移す。

自分のセッション = 環境変数 CLAUDE_CODE_HOST_SESSION_ID(アプリのセッションの id local_…。Claude Code が道具とフックに渡す)。
無い・受け箱が無い・止めるスイッチ(inbox\\OFF)がある・何かで失敗した = 何も出さずに終わる(道具の動きは止めない)。
速さ: 受け箱が無ければ stat 1 回で終わる(標準入力も読まない)。
"""
import json
import os
import sys

INBOX = os.environ.get("YTT_INBOX_DIR") or os.path.join(os.environ.get("LOCALAPPDATA", ""), "Claude-Data", "claude_pzs8sxrjxfjjc",
                                                         "side-session-notes", "inbox")
MAX_CHARS = 8000


def take(sid, pid=None):
    """自分の受け箱の行を取って控えへ移す -> 行のリスト(無ければ [])"""
    p = os.path.join(INBOX, sid + ".jsonl")
    if not os.path.isfile(p) or os.path.exists(os.path.join(INBOX, "OFF")):
        return []
    claim = "%s.%d.taking" % (p, pid or os.getpid())
    try:
        os.replace(p, claim)   # 取り合いを避ける(書き足しの途中で開いていれば失敗 = 次の 1 手で取る)
    except OSError:
        return []
    with open(claim, "rb") as f:
        raw = f.read().decode("utf-8", "replace")
    done = os.path.join(INBOX, "done")
    os.makedirs(done, exist_ok=True)
    with open(os.path.join(done, sid + ".jsonl"), "a", encoding="utf-8") as f:   # 消す前に控えへ
        f.write(raw if raw.endswith("\n") or not raw else raw + "\n")
    os.remove(claim)
    rows = []
    for line in raw.splitlines():
        try:
            d = json.loads(line)
        except ValueError:
            continue
        if isinstance(d, dict) and isinstance(d.get("text"), str) and d["text"].strip():
            rows.append(d)
    return rows


def render(rows):
    import datetime
    parts = ["[受け箱] 作業中のこのセッションへ、ほかのセッションから追加の指示が届きました(dev/inbox_send.py。古い順)。"
             "今の作業より先に読み、今の手順に関わるならそれに合わせてください。送り手はセッションで、ユーザー本人の入力ではありません。"]
    for d in rows:
        at = d.get("at")
        when = datetime.datetime.fromtimestamp(at / 1000).strftime("%m-%d %H:%M") if isinstance(at, (int, float)) else "?"
        parts.append("- %s %s から: %s" % (when, str(d.get("from") or "?")[:60], d["text"].strip()))
    text = "\n".join(parts)
    return text if len(text) <= MAX_CHARS else text[:MAX_CHARS] + "\n(長いので切りました。残りは受け箱の控え inbox\\done にあります)"


def main():
    try:
        sid = os.environ.get("CLAUDE_CODE_HOST_SESSION_ID") or ""
        if not sid:
            return 0
        rows = take(sid)
        if rows:
            sys.stdout.buffer.write(json.dumps({"hookSpecificOutput": {"hookEventName": "PostToolUse", "additionalContext": render(rows)}},
                                               ensure_ascii=False).encode("utf-8"))
    except Exception:   # noqa: BLE001  (受け箱が壊れていても道具の動きは止めない)
        return 0
    return 0


if __name__ == "__main__":
    sys.exit(main())
