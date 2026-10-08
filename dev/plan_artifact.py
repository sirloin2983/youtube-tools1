#!/usr/bin/env python3
"""plan/ の HTML(index.html・user-tasks.html)を、claude.ai の Artifact(リンクで開けるページ。スマホでも見る)用に 1 枚ずつまとめる。

    python dev/plan_artifact.py [--out <フォルダ>]     # 既定: <リポジトリ直下>/.artifact-build/plan/

Artifact は外部の CSS・JS を読めない(CDN 以外)ので、plan.css・data.js・plan.js(2 ページ共通の表示部品)を各ページに埋め込む。
主のページ(index.html)は Artifact 側が <head> を付けるので、<title> と <style> から始まる本文だけ(doctype・html・head・body は無し)。
2 枚目(user-tasks.html)は files として出すので、完全な HTML のまま(自分の doctype を持つ)。
md は Artifact に無いので、上のページ切り替えの md(決めたこと・改善案)は外し、ほかの md へのリンクはファイル名の文字だけにする
(画面が作るリンクは window.PLAN_NO_MD を見て plan.js の docLink が文字にする)。
公開は Claude Code が Artifact ツールで行う(plan/data.js を直したら、これを流して公開し直す)。
"""
import argparse
import os
import re
import sys

REPO = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
PLAN = os.path.join(REPO, "plan")


def read(name):
    with open(os.path.join(PLAN, name), encoding="utf-8") as f:
        return f.read()


def inline_assets(html, css, data, common):
    for tag, body in (('<link rel="stylesheet" href="plan.css">', "<style>\n" + css + "\n</style>"),
                      ('<script src="data.js"></script>', "<script>\nwindow.PLAN_NO_MD = true;\n" + data + "\n</script>"),
                      ('<script src="plan.js"></script>', "<script>\n" + common + "\n</script>")):
        if tag not in html:
            raise SystemExit("plan の HTML に %s が無い(埋め込めない)" % tag)
        html = html.replace(tag, body)
    # md へのリンクは外す(Artifact には無い)。ページ切り替えの 2 つは消し、ほかはファイル名の文字だけ
    html = re.sub(r'<a href="(decisions|improvements)\.md">[^<]*</a>', "", html)
    html = re.sub(r'<a href="[^"]+\.md">([^<]*)</a>', r'<span class="mdref">\1</span>', html)
    return html


def main_fragment(html):
    """<title> と <style> と <script>(データ)を先頭に、<body> の中身を続ける(doctype・html・head・body を外す)"""
    title = re.search(r"<title>(.*?)</title>", html, re.S).group(0)
    head = re.search(r"<head>(.*?)</head>", html, re.S).group(1)
    keep = re.findall(r"<style>.*?</style>|<script>.*?</script>", head, re.S)
    body = re.search(r"<body>(.*?)</body>", html, re.S).group(1)
    return title + "\n" + "\n".join(keep) + "\n" + body.strip() + "\n"


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--out", default=os.path.join(REPO, ".artifact-build", "plan"))
    a = ap.parse_args()
    css, data, common = read("plan.css"), read("data.js"), read("plan.js")
    os.makedirs(a.out, exist_ok=True)
    index = inline_assets(read("index.html"), css, data, common)
    tasks = inline_assets(read("user-tasks.html"), css, data, common)
    with open(os.path.join(a.out, "index.html"), "w", encoding="utf-8") as f:
        f.write(main_fragment(index))
    with open(os.path.join(a.out, "user-tasks.html"), "w", encoding="utf-8") as f:
        f.write(tasks)
    print("wrote", a.out)
    return 0


if __name__ == "__main__":
    sys.exit(main())
