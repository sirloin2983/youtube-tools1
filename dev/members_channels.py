"""名簿 friend-apps/holo-colors/members.json の JP・DEV_IS の各メンバーに YouTube のチャンネル ID(channel)を入れる・確かめる道具。

  py -3.10 dev/members_channels.py check
      channel が無い人は「無い」。あれば新着 RSS を取って作者名を出し、名前と合うかを 1 行ずつ出す。
  py -3.10 dev/members_channels.py set <member id> <UC...>
      その人の channel を足す・直す。ファイルの他の行は変えない(改行・インデント・順を保つ)。

標準ライブラリだけ。読むのは RSS だけで、外へ書くのは members.json だけ。
"""
import json
import os
import re
import sys
import unicodedata
import urllib.request
import xml.etree.ElementTree as ET
from concurrent.futures import ThreadPoolExecutor

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)
PATH = os.path.join(ROOT, "friend-apps", "holo-colors", "members.json")
BRANCHES = ("JP", "DEV_IS")
RSS = "https://www.youtube.com/feeds/videos.xml?channel_id={}"
UA = "Mozilla/5.0 (members_channels check; youtube-tools)"
ATOM = "{http://www.w3.org/2005/Atom}"
CHANNEL_RE = re.compile(r"^UC[A-Za-z0-9_-]{22}$")


def read_text():
    with open(PATH, encoding="utf-8", newline="") as f:
        return f.read()


def targets(data):
    """JP・DEV_IS の全メンバー(グループの順)。"""
    out = []
    for g in data["groups"]:
        if g.get("branch") in BRANCHES:
            out.extend(g["members"])
    return out


def norm(s):
    s = unicodedata.normalize("NFKC", s or "").lower()
    return re.sub(r"[^0-9a-z぀-ヿ一-鿿]", "", s)


def fetch_rss(channel):
    """(作者名の一覧, 番組名, エラー文) を返す。10 秒で諦める。"""
    req = urllib.request.Request(RSS.format(channel), headers={"User-Agent": UA})
    try:
        with urllib.request.urlopen(req, timeout=10) as r:
            body = r.read()
    except Exception as e:  # 通信の失敗は表示する
        return [], "", "取得失敗: " + type(e).__name__
    try:
        root = ET.fromstring(body)
    except ET.ParseError as e:
        return [], "", "XML 不正: " + str(e)
    title = root.findtext(ATOM + "title", default="")
    authors = []
    for entry in root.findall(ATOM + "entry"):
        name = entry.findtext(ATOM + "author/" + ATOM + "name", default="")
        if name and name not in authors:
            authors.append(name)
    return authors, title, ""


def verdict(m, authors, title):
    names = [norm(a) for a in authors] + [norm(title)]
    wanted = [norm(m.get("name")), norm(m.get("en"))]
    for w in wanted:
        if not w:
            continue
        for a in names:
            if a and (w == a or w in a or a in w):
                return "合う"
    return "合わない?"


def cmd_check():
    with open(PATH, encoding="utf-8") as f:
        data = json.load(f)
    members = targets(data)
    todo = [m for m in members if not m.get("channel")]
    have = [m for m in members if m.get("channel")]
    for m in todo:
        print(f"{m['id']:<22} 無い")
    counts = {"合う": 0, "合わない?": 0, "取得失敗": 0}
    with ThreadPoolExecutor(max_workers=4) as ex:
        results = list(ex.map(lambda m: fetch_rss(m["channel"]), have))
    for m, (authors, title, err) in zip(have, results):
        if err:
            counts["取得失敗"] += 1
            print(f"{m['id']:<22} {m['channel']}  {err}")
            continue
        v = verdict(m, authors, title)
        counts[v] += 1
        who = ", ".join(authors[:2]) or "(作者なし)"
        print(f"{m['id']:<22} {m['channel']}  {v}  作者: {who}  番組: {title}")
    print(f"--- 全 {len(members)} 人 / channel あり {len(have)} / 無い {len(todo)}"
          f" / 合う {counts['合う']} / 合わない? {counts['合わない?']} / 取得失敗 {counts['取得失敗']}")
    return 0


def cmd_set(member_id, channel):
    if not CHANNEL_RE.match(channel):
        print("channel は UC で始まる 24 文字の ID です:", channel)
        return 2
    raw = read_text()
    data = json.loads(raw)
    ids = [m["id"] for m in targets(data)]
    if member_id not in ids:
        print("JP・DEV_IS にいない id です:", member_id)
        return 2
    nl = "\r\n" if "\r\n" in raw else "\n"
    lines = raw.split(nl)
    # メンバーは 1 人 1 行の {...} の形。その行の中だけを書き換える
    start = next(i for i, ln in enumerate(lines) if ln.lstrip().startswith(f'{{"id": "{member_id}",'))
    line = lines[start]
    pair = f'"channel": "{channel}"'
    if re.search(r'"channel": "[^"]*"', line):
        line = re.sub(r'"channel": "[^"]*"', pair, line, count=1)
    else:
        # "en" の組の直後に入れる(無ければ "name" の組の直後)
        m = re.search(r'"en": "(?:[^"\\]|\\.)*", ', line) or re.search(r'"name": "(?:[^"\\]|\\.)*", ', line)
        if not m:
            print("en / name の欄が見つかりません:", member_id)
            return 2
        line = line[:m.end()] + pair + ", " + line[m.end():]
    lines[start] = line
    new = nl.join(lines)
    json.loads(new)  # 壊れていないことを確かめる
    with open(PATH, "w", encoding="utf-8", newline="") as f:
        f.write(new)
    print(f"{member_id}: channel = {channel}")
    return 0


def main(argv):
    if len(argv) >= 1 and argv[0] == "check":
        return cmd_check()
    if len(argv) == 3 and argv[0] == "set":
        return cmd_set(argv[1], argv[2])
    print(__doc__)
    return 2


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
