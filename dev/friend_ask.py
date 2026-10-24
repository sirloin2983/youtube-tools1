#!/usr/bin/env python3
"""友人の PC に「送って」の印を置く(ユーザーの PC。notes:plan/友人の不具合の自動対応-1025.md の ⑧)。AI が不具合を調べていて情報が足りないときに流す。

    py -3.12 dev/friend_ask.py --note "ライブの録画が止まった前後の状態"

置き場所は <ホームの設定 intake.folder>/診断/送って/<id>.ask.json(Dropbox の /診断/送って/)。友人のアプリが見つけると、状態の書き出しを
trigger ask で手元の分ごと送ってきて、印を消す。届いた物は依頼の受付の見回り(src/human/friend/bugs.py)が要対応として受け取る。
"""
import argparse
import os
import sys

REPO = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
SRC = os.path.join(REPO, "src")
if SRC not in sys.path:
    sys.path.insert(0, SRC)
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import friend_diag  # noqa: E402
from human.friend import bugs  # noqa: E402


def main(argv=None):
    ap = argparse.ArgumentParser(description="友人の PC に「送って」の印を置く")
    ap.add_argument("--note", default="", help="何が要るか(300 字まで。友人の画面には出ない)")
    a = ap.parse_args(argv)
    d = friend_diag.default_dir()
    if not d:
        print("ホームの設定に受付のフォルダ(intake.folder)がありません")
        return 1
    print("置きました: %s" % bugs.ask(os.path.dirname(d), a.note))
    return 0


if __name__ == "__main__":
    sys.exit(main())
