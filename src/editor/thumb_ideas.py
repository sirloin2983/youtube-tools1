#!/usr/bin/env python3
"""サムネの案を 6 つ並べた 1 枚を作る試作(提案 P5 の S = LLM なし。plan/thumb-ideas.md)。完成品ではなく、サムネを作るときの参照。

    python src/editor/thumb_ideas.py <切り抜きの動画> [--doc 文字起こしの id] [--name 配信者] [--out 出力の png]

- 入力: 切り抜きの動画(横 16:9 の配信の画面)と、その文字起こし(編集の作業データ transcripts/<id>.json。--doc が無ければ動画のパスが同じ文書を探す。無くても動く)
- 時刻の候補(2-1): 音の大きい瞬間(0.5 秒ごとの RMS)・場面の切り替わり(ffmpeg の scene)・感情の強い行(！？・伸ばし棒・笑い・同じ字の繰り返し)。
  点数の高い順に 3 秒以上離して 6 つ(足りなければ同じ時刻を別の型で使う)
- 6 案(5 と 6-1): 縦 9:16。型 A 上に小さい状況・下に大きいキャッチ / 型 B 大きい 2 行 / 型 C 吹き出しのセリフ / 型 D 一語ドン / 今の型 2 つ(3〜4 行の細めの文字)。
  切り取りは中央と右寄り(アバターの矩形を覚える仕組みは画面に組み込むときに)。チャンネルページで見える 2:3 の範囲の枠線を描く。キャッチは規則で文字起こしから拾う(LLM の案は M で足す)
- 出力: 2 列 × 3 行の PNG と、同じ名前の .json(案ごとの番号・型・時刻・文字・切り取り)。既定の置き場所は動画の隣の <名前>_thumb-ideas.png
- 文字: けいふぉんと(入っていれば)→ 游ゴシック Bold → BIZ UD ゴシック Bold。白か黄色の太い文字 + 黒の縁(6-1 の他チャンネルの型)。配信者のメンバーカラーが分かれば帯の色に(ytt.colors)
- 作業データ(文字起こし)は読むだけ。ffmpeg は ytt.tools.find_tool(環境変数 YTT_FFMPEG → PATH)
"""
import argparse
import array
import json
import os
import re
import subprocess
import sys
import tempfile
import unicodedata

HERE = os.path.dirname(os.path.abspath(__file__))
REPO = os.path.dirname(HERE)   # src(ツールの親 = ytt の置き場所。ytt.layout の src_root と同じ)
if REPO not in sys.path:
    sys.path.insert(0, REPO)
from ytt import datadir, docloc, tools  # noqa: E402

W, H = 540, 960                 # 1 案の大きさ(9:16)
SAFE_H = W * 3 // 2             # チャンネルページで見える 2:3 の範囲の高さ
MIN_GAP = 3.0                   # 時刻の候補どうしの間(秒)
N_CARDS = 6
FONTS = [os.path.join(os.environ.get("LOCALAPPDATA", ""), "Microsoft", "Windows", "Fonts", "keifont.ttf"),
         "C:/Windows/Fonts/keifont.ttf", "C:/Windows/Fonts/YuGothB.ttc", "C:/Windows/Fonts/BIZ-UDGothicB.ttc", "C:/Windows/Fonts/msgothic.ttc"]
LAYOUTS = [("A", "型A 状況 + キャッチ", "center"), ("B", "型B 大きい 2 行", "right"), ("C", "型C 吹き出し", "center"),
           ("D", "型D 一語ドン", "right"), ("E", "今の型(3〜4 行)", "center"), ("F", "今の型(右寄り)", "right")]
WORD_RE = re.compile(r"(なんで|うそ|嘘|やば|待って|まって|ちょ|えぇ+|えっ|は[?？]|ん[?？]|誰|あれ|おい|うわ+|ぎゃ+|最高|無理|好き)")
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


# ---------------------------------------------------------------- 入力(動画・文字起こし)

def ffmpeg_path():
    p = tools.find_tool("ffmpeg", "YTT_FFMPEG")
    if not p:
        raise ThumbError("ffmpeg が見つかりません(winget の Gyan.FFmpeg か、環境変数 YTT_FFMPEG)")
    return p


def probe(ff, video):
    """-> (長さの秒, 幅, 高さ)。ffmpeg -i の表示から読む"""
    r = subprocess.run([ff, "-hide_banner", "-i", video], capture_output=True, text=True, encoding="utf-8", errors="replace", creationflags=tools.no_window_flags())
    m = re.search(r"Duration: (\d+):(\d+):([\d.]+)", r.stderr)
    s = re.search(r"Video:.*?(\d{2,5})x(\d{2,5})", r.stderr)
    if not m or not s:
        raise ThumbError("動画を読めませんでした: %s" % os.path.basename(video))
    return int(m.group(1)) * 3600 + int(m.group(2)) * 60 + float(m.group(3)), int(s.group(1)), int(s.group(2))


def loud_times(ff, video, step=0.5):
    """0.5 秒ごとの音の大きさの上位 -> [(時刻, 点数, "loud")]"""
    r = subprocess.run([ff, "-hide_banner", "-loglevel", "error", "-i", video, "-vn", "-ac", "1", "-ar", "8000", "-f", "s16le", "-"],
                       capture_output=True, creationflags=tools.no_window_flags())
    a = array.array("h")
    a.frombytes(r.stdout[: len(r.stdout) // 2 * 2])
    n = int(8000 * step)
    rms = [(sum(x * x for x in a[i:i + n]) / max(1, len(a[i:i + n]))) ** 0.5 for i in range(0, len(a), n)]
    if not rms:
        return []
    mean = sum(rms) / len(rms)
    sd = (sum((v - mean) ** 2 for v in rms) / len(rms)) ** 0.5 or 1.0
    return [(round(i * step + step / 2, 2), round((v - mean) / sd, 2), "loud") for i, v in enumerate(rms) if v > mean + sd]


def scene_times(ff, video):
    """場面の切り替わり(scene > 0.35)の直後 -> [(時刻, 点数, "scene")]"""
    r = subprocess.run([ff, "-hide_banner", "-i", video, "-an", "-vf", "select='gt(scene,0.35)',showinfo", "-f", "null", "-"],
                       capture_output=True, text=True, encoding="utf-8", errors="replace", creationflags=tools.no_window_flags())
    return [(round(float(m) + 0.4, 2), 1.0, "scene") for m in re.findall(r"pts_time:([\d.]+)", r.stderr)]


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


# ---------------------------------------------------------------- 描く(ffmpeg)

def font_path():
    for p in FONTS:
        if p and os.path.isfile(p):
            return p
    raise ThumbError("日本語のフォントが見つかりません(游ゴシックか BIZ UD ゴシック)")


def fpath(p):
    """フィルタの中に書くパス(区切りを / に・: を逃がす)"""
    return "'" + p.replace("\\", "/").replace(":", "\\:") + "'"


def text_filter(tmp, key, text, size, x, y, color="white", border=8, bordercolor="black"):
    """drawtext(文字は UTF-8 のファイルで渡す = 日本語と記号を逃がさなくてよい)"""
    path = os.path.join(tmp, "%s.txt" % key)
    with open(path, "w", encoding="utf-8") as f:
        f.write(text)
    return ("drawtext=fontfile=%s:textfile=%s:fontsize=%d:fontcolor=%s:borderw=%d:bordercolor=%s:x=%s:y=%s:shadowx=3:shadowy=3:shadowcolor=black@0.6"
            % (fpath(FONT), fpath(path), size, color, border, bordercolor, x, y))


def card_filters(tmp, n, layout, label, texts, color):
    """1 案のフィルタ(枠線・型ごとの文字・番号の札)-> [フィルタ]"""
    band = (color or "#1f2430").replace("#", "0x")
    f = ["drawbox=x=0:y=%d:w=%d:h=%d:color=white@0.55:t=2" % ((H - SAFE_H) // 2, W, SAFE_H)]
    lines = texts["lines"]
    if layout == "A":
        f.append("drawbox=x=0:y=130:w=%d:h=84:color=%s@0.88:t=fill" % (W, band))
        f.append(text_filter(tmp, "%d-top" % n, texts["top"] or "…", 40, "(w-text_w)/2", "150", border=4))
        for i, s in enumerate(lines):
            size = min(96, 500 // max(1, len(s)))
            f.append(text_filter(tmp, "%d-%d" % (n, i), s, size, "(w-text_w)/2", str(560 + i * (size + 18)), color="yellow", border=10))
    elif layout == "B":
        for i, s in enumerate(lines):
            size = min(110, 510 // max(1, len(s)))
            f.append(text_filter(tmp, "%d-%d" % (n, i), s, size, "(w-text_w)/2", str(540 + i * (size + 20)), border=12, bordercolor=band))
    elif layout == "C":
        f.append("drawbox=x=24:y=560:w=%d:h=%d:color=white@0.95:t=fill" % (W - 48, 70 + 64 * max(1, len(lines))))
        for i, s in enumerate(lines):
            f.append(text_filter(tmp, "%d-%d" % (n, i), s, 50, "(w-text_w)/2", str(592 + i * 64), color="black", border=0))
    elif layout == "D":
        w = texts["word"] or "…"
        f.append(text_filter(tmp, "%d-w" % n, w, min(220, 480 // max(1, len(w))), "(w-text_w)/2", "330", border=16, bordercolor=band))
    else:
        for i, s in enumerate(lines):
            f.append(text_filter(tmp, "%d-%d" % (n, i), s, 50, "(w-text_w)/2", str(560 + i * 66), border=4))
    f.append("drawbox=x=0:y=%d:w=%d:h=40:color=black@0.6:t=fill" % (H - 40, W))
    f.append(text_filter(tmp, "%d-label" % n, label, 24, "12", str(H - 34), border=0))
    return f


def crop_box(crop, vw, vh, rect=None):
    """切り取りの箱 -> (幅, 高さ, x, y)。center = 中央を縦いっぱい(ゲームの画面 = 状況)/ right = 右下を寄せる(ゲーム実況のアバターはたいてい右下)/
    rect = アバターの矩形 (x, y, 幅, 高さ) を指定したときの寄せ(矩形を含む 9:16 の箱。画面に組み込むときは配信者ごとに覚える)"""
    if crop == "zoom" and rect:
        rx, ry, rw, rh = rect
        ch = min(vh, max(rh, rw * 16 // 9) * 6 // 5)
        cw = min(vw, ch * 9 // 16)
        x = min(max(0, rx + rw // 2 - cw // 2), vw - cw)
        y = min(max(0, ry + rh // 2 - ch // 2), vh - ch)
        return cw, ch, x, y
    if crop == "right":
        ch = vh * 7 // 10
        cw = min(vw, ch * 9 // 16)
        return cw, ch, vw - cw, vh - ch
    cw = min(vw, vh * 9 // 16)
    return cw, vh, (vw - cw) // 2, 0


def render_card(ff, tmp, video, n, t, vw, vh, crop, filters, rect=None):
    """1 案の PNG(時刻 t の 1 枚 → 9:16 に切り取り → 540×960 → 文字)-> パス"""
    cw, ch, x, y = crop_box(crop, vw, vh, rect)
    out = os.path.join(tmp, "card%d.png" % n)
    vf = ",".join(["crop=%d:%d:%d:%d" % (cw, ch, x, y), "scale=%d:%d" % (W, H)] + filters)
    for at in (t, max(0.0, t - 1.0)):   # 取れなければ 1 秒前でもう一度
        r = subprocess.run([ff, "-hide_banner", "-loglevel", "error", "-y", "-ss", "%.2f" % at, "-i", video, "-frames:v", "1", "-vf", vf, out],
                           capture_output=True, text=True, encoding="utf-8", errors="replace", creationflags=tools.no_window_flags())
        if r.returncode == 0 and os.path.isfile(out):
            break
    if r.returncode != 0 or not os.path.isfile(out):
        raise ThumbError("案 %d を描けませんでした" % n, r.stderr.strip()[-300:])
    return out


def tile(ff, cards, out):
    """6 案を 2 列 × 3 行の 1 枚に"""
    ins = []
    for c in cards:
        ins += ["-i", c]
    layout = "|".join("%d_%d" % ((i % 2) * W, (i // 2) * H) for i in range(len(cards)))
    r = subprocess.run([ff, "-hide_banner", "-loglevel", "error", "-y"] + ins + ["-filter_complex", "xstack=inputs=%d:layout=%s" % (len(cards), layout), "-frames:v", "1", out],
                       capture_output=True, text=True, encoding="utf-8", errors="replace", creationflags=tools.no_window_flags())
    if r.returncode != 0:
        raise ThumbError("1 枚にまとめられませんでした", r.stderr.strip()[-300:])


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
    global FONT
    FONT = font_path()
    ff = ffmpeg_path()
    duration, vw, vh = probe(ff, video)
    rows = doc_rows(doc)
    cands = loud_times(ff, video) + scene_times(ff, video) + [((r["start"] + r["end"]) / 2, float(excite_score(r["text"])), "row") for r in rows if excite_score(r["text"])]
    times = select_times(cands, duration)
    color = member_color(name, video + " " + str((doc or {}).get("title") or ""))
    out = out or os.path.splitext(video)[0] + "_thumb-ideas.png"
    rec = {"schema": "youtube-tools-thumb-ideas/v1", "video": video, "doc": (doc or {}).get("id"), "font": os.path.basename(FONT), "color": color, "cards": []}
    with tempfile.TemporaryDirectory(prefix="thumb-ideas-") as tmp:
        cards = []
        for n, ((key, label, _default), (t, score, src), c) in enumerate(zip(LAYOUTS, times, crops_for(crop, rect)), 1):
            texts = card_texts(key, rows, t)
            filters = card_filters(tmp, n, key, "%d  %s  %s" % (n, label, mmss(t)), texts, color)
            cards.append(render_card(ff, tmp, video, n, t, vw, vh, c, filters, rect))
            rec["cards"].append({"n": n, "layout": key, "label": label, "at": round(t, 2), "from": src, "crop": c, **texts})
        os.makedirs(os.path.dirname(os.path.abspath(out)), exist_ok=True)
        tile(ff, cards, out)
    with open(os.path.splitext(out)[0] + ".json", "w", encoding="utf-8") as f:
        json.dump(rec, f, ensure_ascii=False, indent=1)
    return out, rec


FONT = ""


class ThumbError(Exception):
    """作れなかった理由(文 = 画面・知らせに出す日本語・detail = ffmpeg の原文。編集のジョブ(ed_thumb)が捕まえる。コマンドでは SystemExit にして出す)"""
    def __init__(self, message, detail=""):
        super().__init__(message)
        self.message, self.detail = message, detail


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
