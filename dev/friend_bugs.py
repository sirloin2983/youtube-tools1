#!/usr/bin/env python3
"""友人の不具合の書き出しの一覧を見る・友人の PC に「送って」の印を置く(ユーザーの PC。notes:plan/友人の不具合の自動対応-1025.md)。

    py -3.12 dev/friend_bugs.py                    # 受け取った状態の書き出しの一覧(新しい順。仕分け・種類・AI の結果)
    py -3.12 dev/friend_bugs.py --state needs      # 要対応だけ(handled・needs・material・report・broken)
    py -3.12 dev/friend_bugs.py --ask "ライブの録画が止まった前後の状態"   # 「送って」の印を置く(⑧)
    py -3.12 dev/friend_bugs.py --alerts           # 更新の見張りの知らせ(top 最上の急ぎ・warn 確かめてもらう・note 記録だけ)と、配った版・友人の今の版

一覧は依頼の受付の見回り(src/human/friend/bugs.py)が作業データの app\\friend-bugs\\ に作った物(3 日で消える)。読むだけ。
「送って」の印は <ホームの設定 intake.folder>/診断/送って/<id>.ask.json(Dropbox の /診断/送って/)。友人のアプリが見つけると、
状態の書き出しを trigger ask で手元の分ごと送ってきて、印を消す。届いた物は要対応として受け取られる。
"""
import argparse
import datetime
import os
import sys

REPO = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
SRC = os.path.join(REPO, "src")
if SRC not in sys.path:
    sys.path.insert(0, SRC)
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import friend_diag  # noqa: E402
from human.friend import bugs, upwatch  # noqa: E402
from ytt import datadir, fsio  # noqa: E402


def main(argv=None):
    ap = argparse.ArgumentParser(description="友人の不具合の書き出しの一覧・送っての印")
    ap.add_argument("--state", help="この仕分けだけ(handled・needs・material・report・broken)")
    ap.add_argument("--ask", metavar="NOTE", help="友人の PC に「送って」の印を置く(何が要るか。300 字まで・友人の画面には出ない)")
    ap.add_argument("--alerts", action="store_true", help="更新の見張りの知らせと、配った版・友人の今の版")
    a = ap.parse_args(argv)
    if a.alerts:
        app = datadir.locate("app", SRC)
        for r in upwatch.alerts(app):
            print("%s [%s] %s" % (datetime.datetime.fromtimestamp((r.get("at") or 0) / 1000.0).strftime("%m-%d %H:%M"), r.get("level"), r.get("text")))
        st = fsio.read_json_or(os.path.join(app, "friend-bugs", upwatch.STATE_NAME), None) or {}
        print("配った版: %s / 友人の今の版: %s / 最後に届いた: %s" % ((st.get("published") or {}).get("version"), (st.get("friend") or {}).get("version"),
              datetime.datetime.fromtimestamp(st["lastSeen"] / 1000.0).strftime("%m-%d %H:%M") if st.get("lastSeen") else "?"))
        return 0
    if a.ask is not None:
        d = friend_diag.default_dir()
        if not d:
            print("ホームの設定に受付のフォルダ(intake.folder)がありません")
            return 1
        print("置きました: %s" % bugs.ask(os.path.dirname(d), a.ask))
        return 0
    rows = [r for r in bugs.records(datadir.locate("app", SRC)) if not a.state or r.get("state") == a.state]
    for r in rows:
        at = datetime.datetime.fromtimestamp((r.get("at") or 0) / 1000.0).strftime("%m-%d %H:%M")
        kind = bugs.KINDS.get(r.get("kind") or 0, ("?",))[0]
        ai = r.get("ai") or {}
        print("%s %-8s %s | %s | %s%s" % (at, r.get("state"), kind, r.get("why") or "", r.get("summary") or "",
                                          (" | AI %s: %s" % (ai.get("state"), ai.get("head") or "")) if ai else ""))
    print("%d 件" % len(rows))
    return 0


if __name__ == "__main__":
    sys.exit(main())
