#!/usr/bin/env python3
"""サムネの案を 6 つ並べた 1 枚を作る試作(提案 P5 の S = LLM なし。notes:plan/thumb-ideas.md)。完成品ではなく、サムネを作るときの参照。

    python src/editor/thumb_ideas.py <切り抜きの動画> [--doc 文字起こしの id] [--name 配信者] [--out 出力の png]

- 入力: 切り抜きの動画(横 16:9 の配信の画面)と、その文字起こし(編集の作業データ transcripts/<id>.json。--doc が無ければ動画のパスが同じ文書を探す。無くても動く)
- 時刻の候補(2-1): 音の大きい瞬間(0.5 秒ごとの RMS)・場面の切り替わり(ffmpeg の scene)・感情の強い行(！？・伸ばし棒・笑い・同じ字の繰り返し)。
  点数の高い順に 3 秒以上離して 6 つ(足りなければ同じ時刻を別の型で使う)
- 6 案(5 と 6-1): 縦 9:16。型 A 上に小さい状況・下に大きいキャッチ / 型 B 大きい 2 行 / 型 C 吹き出しのセリフ / 型 D 一語ドン / 今の型 2 つ(3〜4 行の細めの文字)。
  切り取りは中央と右寄り(アバターの矩形を覚える仕組みは画面に組み込むときに)。チャンネルページで見える 2:3 の範囲の枠線を描く。キャッチは規則で文字起こしから拾う(LLM の案は M で足す)
- 出力: 2 列 × 3 行の PNG と、同じ名前の .json(案ごとの番号・型・時刻・文字・切り取り)。既定の置き場所は動画の隣の <名前>_thumb-ideas.png
- 文字: けいふぉんと(入っていれば)→ 游ゴシック Bold → BIZ UD ゴシック Bold。白か黄色の太い文字 + 黒の縁(6-1 の他チャンネルの型)。配信者のメンバーカラーが分かれば帯の色に(ytt.colors)
- 作業データ(文字起こし)は読むだけ。ffmpeg は ytt.tools.find_tool(環境変数 YTT_FFMPEG → PATH → winget)
- 描く部分(ffmpeg で切り取り・文字を載せ・1 枚にまとめる)は ① の src/pipeline/export/thumb_cards.py。③ のこの殻は ② の src/flow/thumbs.py(動詞 font・scan・render)を通す。この殻は文字起こしを読んで案を決め、JSON を書く
"""
import argparse
import json
import os
import re
import sys
import unicodedata

HERE = os.path.dirname(os.path.abspath(__file__))
REPO = os.path.dirname(HERE)   # src(ツールの親 = ytt の置き場所。ytt.layout の src_root と同じ)
if REPO not in sys.path:
    sys.path.insert(0, REPO)
from ytt import datadir, docloc  # noqa: E402
from flow import thumbs as _thumbs  # noqa: E402  (描く部分 = ② の口 flow/thumbs。① pipeline/export/thumb_cards を直に読まない = ③ の層の向き)
ThumbError = _thumbs.ThumbError   # ed_thumb が thumb_ideas.ThumbError で捕まえる

MIN_GAP = 3.0                   # 時刻の候補どうしの間(秒)
N_CARDS = 6
LAYOUTS = [("A", "型A 状況 + キャッチ", "center"), ("B", "型B 大きい 2 行", "right"), ("C", "型C 吹き出し", "center"),
           ("D", "型D 一語ドン", "right"), ("E", "今の型(3〜4 行)", "center"), ("F", "今の型(右寄り)", "right")]
# ひらがなで始まる言葉は、前がひらがななら語の途中(「において」の「おい」・「好きなんです」の「なんで」)なので当てない。「おい」は後ろがひらがなでも当てない(「おいしい」)
WORD_RE = re.compile(r"(?:(?<![ぁ-ん])(?:なんで|うそ|やば|待って|まって|ちょ|えぇ+|えっ|は[?？]|ん[?？]|あれ|おい(?![ぁ-ん])|うわ+|ぎゃ+)|嘘|誰|最高|無理|好き)")
DOC_RE = re.compile(r"^[0-9a-f]{12}\.json\Z")


# ---------------------------------------------------------------- 文字起こし・キャッチ(純粋な部分)

def excite_score(text):
    """行の感情の強さ(！？・伸ばし棒・笑い・同じ字の繰り返し・感情の言葉)"""
    t = str(text or "")
    s = 2 * len(re.findall(r"[!！?？]", t)) + len(re.findall(r"ー{2,}|～", t)) + 2 * len(re.findall(r"笑|[wｗ]{2,}|草", t))
    s += 2 * len(re.findall(r"(.)\1{2,}", t)) + 3 * len(WORD_RE.findall(t))
    return s


def clean(text):
    """キャッチにする文字(空白と記号の続きを詰める)"""
    t = unicodedata.normalize("NFKC", str(text or "")).strip()
    t = re.sub(r"\s+", "", t)
    return re.sub(r"([!?。、…])\1+", r"\1", t)


def lines_of(text, width, max_lines):
    """文字を width 字ずつの行に(区切りの記号・助詞のあとで切れるなら切る)。入りきらなければ最後の行を … で終える"""
    t = clean(text)
    out = []
    while t and len(out) < max_lines:
        if len(t) <= width:
            out.append(t)
            t = ""
            break
        cut = max((i + 1 for i, ch in enumerate(t[:width]) if ch in "、。!?！？ねよがはをにでもとって"), default=width)
        cut = cut if cut >= width // 2 else width
        out.append(t[:cut])
        t = t[cut:]
    if t and out:
        out[-1] = out[-1][:max(1, width - 1)] + "…"
    return out


def one_word(text):
    """型D の一語(感情の言葉があればそれ、無ければ頭の 3 字)"""
    m = WORD_RE.search(clean(text))
    return m.group(0) if m else (clean(text)[:3] or "…")


def row_at(rows, t):
    """時刻 t の行(t を含む行、無ければいちばん近い行)。行が無ければ None"""
    best, bd = None, None
    for r in rows:
        d = 0.0 if r["start"] <= t <= r["end"] else min(abs(r["start"] - t), abs(r["end"] - t))
        if bd is None or d < bd:
            best, bd = r, d
    return best


def select_times(cands, duration, n=N_CARDS, gap=MIN_GAP):
    """候補 [(時刻, 点数, 出どころ)] -> 点数の高い順に gap 秒以上離した n 個(時刻の順)。足りなければ均等な時刻で埋める"""
    picked = []
    last = max(0.3, duration - 1.0)   # 終わりの間際は 1 枚を取れないことがある
    for t, s, src in sorted(cands, key=lambda c: -c[1]):
        if 0.3 <= t <= last and all(abs(t - p[0]) >= gap for p in picked):
            picked.append((t, s, src))
        if len(picked) >= n:
            break
    k = 1
    while len(picked) < n and duration > 0:
        t = round(duration * k / (n + 1), 2)
        if all(abs(t - p[0]) >= 0.5 for p in picked):
            picked.append((t, 0.0, "even"))
        k += 1
        if k > 4 * n:
            break
    return sorted(picked[:n])


def card_texts(layout, rows, t):
    """型ごとの文字 -> {"top": 小さい行 | None, "lines": [大きい行], "word": 一語 | None}"""
    r = row_at(rows, t)
    text = r["text"] if r else ""
    prev = row_at([x for x in rows if r and x["end"] <= r["start"]], t) if r else None
    if layout == "A":
        return {"top": (lines_of(prev["text"], 14, 1) or [""])[0] if prev else "", "lines": lines_of(text, 7, 2), "word": None}
    if layout == "B":
        return {"top": None, "lines": lines_of(text, 6, 2), "word": None}
    if layout == "C":
        return {"top": None, "lines": lines_of(text, 9, 2), "word": None}
    if layout == "D":
        return {"top": None, "lines": [], "word": one_word(text)}
    return {"top": None, "lines": lines_of(text, 10, 4), "word": None}


def find_doc(video, doc_id=None, tdir=None):
    """文字起こしの文書(--doc の id か、動画のパスが同じ文書)-> 文書 | None(作業データは読むだけ)"""
    tdir = tdir or os.path.join(datadir.locate("transcribe"), "transcripts")
    # 置き場所の索引(案件の 作業用)を見るのは、名前が transcripts のフォルダ(作業データの文書の根)のときだけ
    data_dir = os.path.dirname(os.path.normpath(tdir)) if os.path.basename(os.path.normpath(tdir)) == "transcripts" else None
    if data_dir:
        tids = [doc_id] if doc_id else docloc.iter_tids(data_dir)
        names = [t + ".json" for t in tids]
    else:
        names = [doc_id + ".json"] if doc_id else (sorted(os.listdir(tdir)) if os.path.isdir(tdir) else [])
    key = os.path.normcase(os.path.abspath(video))
    for name in names:
        if not DOC_RE.match(name):
            continue
        try:
            path = docloc.doc_file(name[:-5], ".json", data_dir) if data_dir else os.path.join(tdir, name)
            with open(path, encoding="utf-8-sig") as f:
                d = json.load(f)
        except (OSError, ValueError):
            continue
        if doc_id or os.path.normcase(os.path.abspath(str(d.get("sourcePath") or ""))) == key:
            return d
    return None


def doc_rows(doc):
    """文書の行(字幕に出さない行・空の行は除く。時刻は動画の秒 = 文書の秒 − 文書の開始)"""
    if not doc:
        return []
    base = float(doc.get("start") or 0)
    return [{"start": float(s["start"]) - base, "end": float(s["end"]) - base, "text": str(s["text"])}
            for s in doc.get("segments") or [] if s.get("text") and not s.get("noSub") and s.get("cutState") != "cut"]


def member_color(name, hay):
    """配信者のメンバーカラー(--name か、動画のパス・題名に名前があるメンバー)-> "#RRGGBB" | None"""
    try:
        from ytt import colors
        entries = colors.load()
    except Exception:   # 色は飾り。読めなくても案は作る
        return None
    if name:
        m = colors.lookup(name, entries)["match"]
        return m["hex"] if m else None
    hit = [e for e in entries if e.get("name") and e["name"] in hay]
    return max(hit, key=lambda e: len(e["name"]))["hex"] if hit else None


def mmss(t):
    return "%02d:%04.1f" % (int(t // 60), t % 60)


def crops_for(mode, rect):
    """--crop と --rect -> 6 案の切り取り(alt = 型ごとの既定 = 中央と右下を交互。rect があれば右下の代わりに矩形へ寄せる)"""
    out = []
    for _key, _label, default in LAYOUTS:
        c = default if mode == "alt" else mode
        out.append("zoom" if rect and c in ("right", "zoom") else ("right" if c == "zoom" else c))
    return out


def make(video, doc=None, name=None, out=None, crop="alt", rect=None):
    """案の一覧を作る -> (png のパス, 記録)"""
    font = _thumbs.font()
    duration, vw, vh, found = _thumbs.scan(video)
    rows = doc_rows(doc)
    cands = found + [((r["start"] + r["end"]) / 2, float(excite_score(r["text"])), "row") for r in rows if excite_score(r["text"])]
    times = select_times(cands, duration)
    color = member_color(name, video + " " + str((doc or {}).get("title") or ""))
    out = out or os.path.splitext(video)[0] + "_thumb-ideas.png"
    rec = {"schema": "youtube-tools-thumb-ideas/v1", "video": video, "doc": (doc or {}).get("id"), "font": os.path.basename(font), "color": color, "cards": []}
    plan = []
    for n, ((key, label, _default), (t, score, src), c) in enumerate(zip(LAYOUTS, times, crops_for(crop, rect)), 1):
        texts = card_texts(key, rows, t)
        plan.append({"n": n, "layout": key, "label": "%d  %s  %s" % (n, label, mmss(t)), "t": t, "crop": c, "texts": texts})
        rec["cards"].append({"n": n, "layout": key, "label": label, "at": round(t, 2), "from": src, "crop": c, **texts})
    _thumbs.render(video, vw, vh, plan, color, font, out, rect)
    with open(os.path.splitext(out)[0] + ".json", "w", encoding="utf-8") as f:
        json.dump(rec, f, ensure_ascii=False, indent=1)
    return out, rec


def main(argv=None):
    p = argparse.ArgumentParser(description="サムネの案を 6 つ並べた 1 枚を作る(LLM なしの試作。完成品ではなく参照)")
    p.add_argument("video", help="切り抜きの動画")
    p.add_argument("--doc", help="文字起こしの文書の id(無ければ動画のパスが同じ文書を探す)")
    p.add_argument("--name", help="配信者の名前(メンバーカラーの帯に使う。無ければ動画のパスから探す)")
    p.add_argument("--out", help="出力の png(既定は動画の隣の <名前>_thumb-ideas.png)")
    p.add_argument("--crop", choices=("alt", "center", "right"), default="alt", help="切り取り: alt = 中央と右下を交互(既定)/ center = 全部中央(雑談の配信など、アバターが中央)/ right = 全部右下")
    p.add_argument("--rect", help="アバターの矩形 x,y,幅,高さ(元の動画の画素)。指定すると右下の代わりにそこへ寄せる")
    args = p.parse_args(argv)
    rect = None
    if args.rect:
        try:
            rect = tuple(int(v) for v in args.rect.split(","))
        except ValueError:
            rect = ()
        if len(rect) != 4 or min(rect) < 0 or rect[2] == 0 or rect[3] == 0:
            raise SystemExit("--rect は x,y,幅,高さ の 4 つの整数で(例 1300,500,600,580)")
    try:
        sys.stdout.reconfigure(encoding="utf-8")
    except (AttributeError, ValueError):
        pass
    if not os.path.isfile(args.video):
        raise SystemExit("動画がありません: %s" % args.video)
    doc = find_doc(args.video, args.doc)
    try:
        out, rec = make(args.video, doc, args.name, args.out, args.crop, rect)
    except ThumbError as e:
        raise SystemExit(e.message + (": " + e.detail if e.detail else ""))
    print("文字起こし: %s・帯の色: %s・フォント: %s" % (rec["doc"] or "(なし)", rec["color"] or "(なし)", rec["font"]))
    for c in rec["cards"]:
        print("  %d %s %s(%s)%s" % (c["n"], c["label"], mmss(c["at"]), c["from"], " / ".join(([c["top"]] if c["top"] else []) + c["lines"] + ([c["word"]] if c["word"] else []))))
    print("保存: " + out)
    return 0


if __name__ == "__main__":
    sys.exit(main())
