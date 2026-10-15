"""サムネの案の描く部分(提案 P5 の S。notes:plan/thumb-ideas.md の 7・8)。ffmpeg で動画から 1 枚ずつ切り取って文字を載せ、6 案を 1 枚の PNG にまとめる。
① の部品: 入力(動画の長さ・音の大きい瞬間・場面の切り替わり)・描き(切り取り・文字・枠・札・まとめ)。文字起こしを読む所・案の決め方・コマンドは editor/thumb_ideas.py(殻)が持つ。
ffmpeg は ytt.tools.find_tool(環境変数 YTT_FFMPEG → PATH → winget)。フォントは呼び手が font_path() で決めて渡す(この部品に状態を持たせない)。
"""
import array
import os
import re
import subprocess
import tempfile

from ytt import tools   # ffmpeg の場所と、ウィンドウを出さない指定

W, H = 540, 960                 # 1 案の大きさ(9:16)
SAFE_H = W * 3 // 2             # チャンネルページで見える 2:3 の範囲の高さ
FONTS = [os.path.join(os.environ.get("LOCALAPPDATA", ""), "Microsoft", "Windows", "Fonts", "keifont.ttf"),
         "C:/Windows/Fonts/keifont.ttf", "C:/Windows/Fonts/YuGothB.ttc", "C:/Windows/Fonts/BIZ-UDGothicB.ttc", "C:/Windows/Fonts/msgothic.ttc"]


# ---------------------------------------------------------------- 入力(ffmpeg)

class ThumbError(Exception):
    """作れなかった理由(文 = 画面・知らせに出す日本語・detail = ffmpeg の原文。編集のジョブ(ed_thumb)が捕まえる。コマンドでは SystemExit にして出す)"""
    def __init__(self, message, detail=""):
        super().__init__(message)
        self.message, self.detail = message, detail


def ffmpeg_path():
    p = tools.find_tool("ffmpeg")
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


# ---------------------------------------------------------------- 描く(ffmpeg)

def font_path():
    for p in FONTS:
        if p and os.path.isfile(p):
            return p
    raise ThumbError("日本語のフォントが見つかりません(游ゴシックか BIZ UD ゴシック)")


def fpath(p):
    """フィルタの中に書くパス(区切りを / に・: を逃がす)"""
    return "'" + p.replace("\\", "/").replace(":", "\\:") + "'"


def text_filter(font, tmp, key, text, size, x, y, color="white", border=8, bordercolor="black"):
    """drawtext(文字は UTF-8 のファイルで渡す = 日本語と記号を逃がさなくてよい)。font = フォントのパス"""
    path = os.path.join(tmp, "%s.txt" % key)
    with open(path, "w", encoding="utf-8") as f:
        f.write(text)
    return ("drawtext=fontfile=%s:textfile=%s:fontsize=%d:fontcolor=%s:borderw=%d:bordercolor=%s:x=%s:y=%s:shadowx=3:shadowy=3:shadowcolor=black@0.6"
            % (fpath(font), fpath(path), size, color, border, bordercolor, x, y))


def card_filters(tmp, n, layout, label, texts, color, font):
    """1 案のフィルタ(枠線・型ごとの文字・番号の札)-> [フィルタ]"""
    band = (color or "#1f2430").replace("#", "0x")
    f = ["drawbox=x=0:y=%d:w=%d:h=%d:color=white@0.55:t=2" % ((H - SAFE_H) // 2, W, SAFE_H)]
    lines = texts["lines"]
    if layout == "A":
        f.append("drawbox=x=0:y=130:w=%d:h=84:color=%s@0.88:t=fill" % (W, band))
        f.append(text_filter(font, tmp, "%d-top" % n, texts["top"] or "…", 40, "(w-text_w)/2", "150", border=4))
        for i, s in enumerate(lines):
            size = min(96, 500 // max(1, len(s)))
            f.append(text_filter(font, tmp, "%d-%d" % (n, i), s, size, "(w-text_w)/2", str(560 + i * (size + 18)), color="yellow", border=10))
    elif layout == "B":
        for i, s in enumerate(lines):
            size = min(110, 510 // max(1, len(s)))
            f.append(text_filter(font, tmp, "%d-%d" % (n, i), s, size, "(w-text_w)/2", str(540 + i * (size + 20)), border=12, bordercolor=band))
    elif layout == "C":
        f.append("drawbox=x=24:y=560:w=%d:h=%d:color=white@0.95:t=fill" % (W - 48, 70 + 64 * max(1, len(lines))))
        for i, s in enumerate(lines):
            f.append(text_filter(font, tmp, "%d-%d" % (n, i), s, 50, "(w-text_w)/2", str(592 + i * 64), color="black", border=0))
    elif layout == "D":
        w = texts["word"] or "…"
        f.append(text_filter(font, tmp, "%d-w" % n, w, min(220, 480 // max(1, len(w))), "(w-text_w)/2", "330", border=16, bordercolor=band))
    else:
        for i, s in enumerate(lines):
            f.append(text_filter(font, tmp, "%d-%d" % (n, i), s, 50, "(w-text_w)/2", str(560 + i * 66), border=4))
    f.append("drawbox=x=0:y=%d:w=%d:h=40:color=black@0.6:t=fill" % (H - 40, W))
    f.append(text_filter(font, tmp, "%d-label" % n, label, 24, "12", str(H - 34), border=0))
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


def draw_sheet(ff, video, vw, vh, cards, color, font, out, rect=None):
    """6 案を描いて 1 枚(out)にする。cards = [{"n": 番号(1 から), "layout": 型, "label": 札の文字, "t": 時刻, "crop": 切り取り, "texts": 型ごとの文字}]。
    一時のフォルダは中で作って消す。out のフォルダが無ければ作る。font = フォントのパス(font_path() の値)"""
    with tempfile.TemporaryDirectory(prefix="thumb-ideas-") as tmp:
        paths = []
        for c in cards:
            filters = card_filters(tmp, c["n"], c["layout"], c["label"], c["texts"], color, font)
            paths.append(render_card(ff, tmp, video, c["n"], c["t"], vw, vh, c["crop"], filters, rect))
        os.makedirs(os.path.dirname(os.path.abspath(out)), exist_ok=True)
        tile(ff, paths, out)
