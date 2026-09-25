#!/usr/bin/env python3
"""ui-kit(共通の見た目)を各ツールへ写す / ずれていないか確かめる。

    python tools/sync_ui_kit.py          # 写す
    python tools/sync_ui_kit.py --check  # ずれがあれば一覧を出して終了コード 1(テスト用)

正本は ui-kit/ui-kit.css と ui-kit/ui-kit.js。各ツールは実行時に ui-kit/ を参照しない(フォルダ単体で動く)ように、
写しを自分のフォルダに持つ。写し先:
  - clip-studio/ui-kit.css, clip-studio/ui-kit.js         (静的ファイルとして配信)
  - cut2resolve/ui-kit.css, cut2resolve/ui-kit.js         (同上)
  - transcribe-tool/ui-kit.js                             (同上。CSP 対応で index.html から外に出した)
  - transcribe-tool/index.html の中の印の間                  (CSS だけは画面が1ファイルのため埋め込み)
      /* ui-kit:css:begin */ … /* ui-kit:css:end */   (<style> の中。インラインの CSS は CSP で許可している)
"""
import os
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
KIT = os.path.join(ROOT, "ui-kit")
HEADER = "/* このファイルは ui-kit/ から tools/sync_ui_kit.py で写したもの。直すときは ui-kit/ の正本を直して写し直す */\n"
FILE_TARGETS = [("clip-studio", ("css", "js")), ("cut2resolve", ("css", "js")), ("transcribe-tool", ("js",))]
EMBED_TARGETS = [("transcribe-tool", "index.html", ("css",))]
MARKS = {"css": ("/* ui-kit:css:begin */", "/* ui-kit:css:end */"), "js": ("/* ui-kit:js:begin */", "/* ui-kit:js:end */")}


def read(path):
    with open(path, encoding="utf-8", newline="") as f:
        return f.read()


def write(path, text):
    tmp = path + ".tmp-sync"
    with open(tmp, "w", encoding="utf-8", newline="") as f:
        f.write(text)
    os.replace(tmp, path)


def kit():
    return {"css": read(os.path.join(KIT, "ui-kit.css")), "js": read(os.path.join(KIT, "ui-kit.js"))}


def expected_files(k):
    out = {}
    for tool, names in FILE_TARGETS:
        d = os.path.join(ROOT, tool)
        if not os.path.isdir(d):
            continue
        for name in names:
            out[os.path.join(d, "ui-kit.%s" % name)] = HEADER + k[name]
    return out


def embed(text, k, where, names=("css", "js")):
    """印の間を正本で置き換えた文字列を返す。印が無い・順番が変なら ValueError。names で css/js の一方だけにもできる。"""
    for name in names:
        b, e = MARKS[name]
        i, j = text.find(b), text.find(e)
        if i < 0 or j < 0 or j < i or text.count(b) != 1 or text.count(e) != 1:
            raise ValueError("%s: 印 %s … %s が1組ありません" % (where, b, e))
        body = k[name]
        if name == "js" and "</script" in body.lower():
            raise ValueError("ui-kit.js に </script が含まれていて埋め込めません")
        if name == "css" and "</style" in body.lower():
            raise ValueError("ui-kit.css に </style が含まれていて埋め込めません")
        text = text[: i + len(b)] + "\n" + body.rstrip("\n") + "\n" + text[j:]
    return text


def main(argv):
    check = "--check" in argv
    k = kit()
    diffs = []
    for path, want in expected_files(k).items():
        have = read(path) if os.path.exists(path) else None
        if have != want:
            diffs.append(os.path.relpath(path, ROOT))
            if not check:
                write(path, want)
    for tool, name, names in EMBED_TARGETS:
        path = os.path.join(ROOT, tool, name)
        if not os.path.exists(path):
            continue
        have = read(path)
        try:
            want = embed(have, k, os.path.relpath(path, ROOT), names)
        except ValueError as e:
            print("エラー: %s" % e, file=sys.stderr)
            return 2
        if have != want:
            diffs.append(os.path.relpath(path, ROOT))
            if not check:
                write(path, want)
    if check:
        if diffs:
            print("ui-kit の写しが正本とずれています(python tools/sync_ui_kit.py で写し直す):")
            for d in diffs:
                print("  " + d)
            return 1
        print("ui-kit の写しはすべて正本と一致しています")
        return 0
    print("写しました: " + (", ".join(diffs) if diffs else "(変更なし)"))
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
