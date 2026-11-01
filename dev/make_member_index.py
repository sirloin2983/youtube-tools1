#!/usr/bin/env python3
"""確かめるの話者カードの「ほかのメンバーを足す」の欄が使う、メンバーの探し方の表を作る(11-02 ユーザー「ひらがな・ローマ字・呼び名で絞れる」)。

    py -3.12 dev/make_member_index.py        # src/app/check/member_index.json を作り直す

材料(読むだけ):
  名簿          src/pipeline/transcribe/hololive-roster.json の groups(期ごとの札の順)と members の aliases(呼ばれる形)
  色・ローマ字  friend-apps/holo-colors/members.json の hex・en
  読み・呼ばれ方 保管庫 plan/名前と呼び方の表.xlsx のシート「人」の読み(B 列)と、シート「呼び方」の 3 行目「いつもの呼ばれ方」
                (かっこの中は読み = 両方を探す言葉にする)。保管庫が無い PC では読みと呼ばれ方なしで作る
出す形: {"groups": [{label, names: [名前…]}], "members": {名前: {yomi, en, calls: [..], hex}}}。グループ名・番組名の組(units)は入れない
"""
import json
import os
import re
import sys
import zipfile

REPO = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
ROSTER = os.path.join(REPO, "src", "pipeline", "transcribe", "hololive-roster.json")
COLORS = os.path.join(REPO, "friend-apps", "holo-colors", "members.json")
TABLE = r"D:\Obsidian保管庫\youtube-tools\plan\名前と呼び方の表.xlsx"
OUT = os.path.join(REPO, "src", "app", "check", "member_index.json")
SKIP_GROUPS = ("units",)


def _sheet_rows(z, name):
    """xlsx のシート(インラインの文字だけの表)-> [[マスの文字…]](マスの位置は列の文字で詰める)"""
    x = z.read(name).decode("utf-8")
    out = []
    for r in re.findall(r"<row[^>]*>(.*?)</row>", x, re.S):
        cells = {}
        for ref, body in re.findall(r'<c r="([A-Z]+)\d+"[^>]*>(.*?)</c>', r, re.S):
            cells[ref] = re.sub(r"<[^>]+>", "", body)
        width = max((ord(k[-1]) - 64 + 26 * (len(k) - 1) for k in cells), default=0)
        out.append([cells.get(chr(65 + i) if i < 26 else "A" + chr(65 + i - 26), "") for i in range(width)])
    return out


def _words(text):
    """「みこ先輩(みこせんぱい)、みこち」-> ["みこ先輩", "みこせんぱい", "みこち"]"""
    out = []
    for part in re.split(r"[、,]", text or ""):
        part = part.strip()
        m = re.match(r"^(.*?)[(（]([^)）]*)[)）]$", part)
        out += [m.group(1).strip(), m.group(2).strip()] if m else [part]
    return [w for w in out if w]


def table():
    """-> ({名前: 読み}, {名前: [いつもの呼ばれ方…]})"""
    if not os.path.exists(TABLE):
        return {}, {}
    z = zipfile.ZipFile(TABLE)
    sheets = re.findall(r'<sheet [^>]*name="([^"]+)"', z.read("xl/workbook.xml").decode("utf-8"))
    people = _sheet_rows(z, "xl/worksheets/sheet%d.xml" % (sheets.index("人") + 1))
    calls = _sheet_rows(z, "xl/worksheets/sheet%d.xml" % (sheets.index("呼び方") + 1))
    yomi = {r[0]: r[1] for r in people[3:] if len(r) > 1 and r[0] and r[1]}
    head = next((r for r in calls if r and r[0].startswith("呼ぶ人")), [])
    usual = next((r for r in calls if r and r[0] == "いつもの呼ばれ方"), [])
    return yomi, {n: _words(usual[i]) for i, n in enumerate(head) if i and n and i < len(usual)}


def main():
    roster = json.load(open(ROSTER, encoding="utf-8"))
    colors = {m["name"]: m for g in json.load(open(COLORS, encoding="utf-8"))["groups"] for m in g.get("members") or ()}
    aliases = {m["name"]: list(m.get("aliases") or ()) for m in roster["members"]}
    yomi, usual = table()
    groups, members = [], {}
    for g in roster.get("groups") or ():
        if g.get("id") in SKIP_GROUPS:
            continue
        names = [n for n in g.get("names") or () if isinstance(n, str)]
        groups.append({"label": str(g.get("label") or g.get("id")), "names": names})
        for n in names:
            c = colors.get(n) or {}
            members[n] = {"yomi": yomi.get(n, ""), "en": c.get("en", ""), "hex": c.get("hex", ""),
                          "calls": list(dict.fromkeys(usual.get(n, []) + aliases.get(n, [])))}
    with open(OUT, "w", encoding="utf-8", newline="\n") as f:
        json.dump({"about": "dev/make_member_index.py が作る(手で直さない)", "groups": groups, "members": members}, f, ensure_ascii=False, indent=1)
        f.write("\n")
    print("メンバー %d 人・組 %d・読み %d 人・呼ばれ方 %d 人 → %s" % (len(members), len(groups), sum(1 for m in members.values() if m["yomi"]),
                                                       sum(1 for n in members if usual.get(n)), OUT))
    return 0


if __name__ == "__main__":
    sys.exit(main())
