"""書き出しの名前の規則(スタジオの書き出し src/pipeline/export/exporter.py と、ライブの書き出し src/pipeline/export/live_export.py が同じ規則を読む。
2026-10-09 見直し T8。以前は live_export が exporter の規則を写して持っていた = ツールをまたいで import しない決まりのため)。

- 置き場所: <書き出し先>/<動画・配信の名前>/(pick_folder)。作業用/.studio-id に持ち主(動画の id など)を書き、同じ名前の別の動画とは混ぜない
- 名前: <番号>_<開始>-<終わり>_<ラベル>(clip_base)。Windows の MAX_PATH(260)より短く収める(UTF-16 の単位で数える)
- 書きかけ: <名前>.partial.mp4 に書いて、仕上がったら <名前>.mp4 へ置き換える(partial_path・final_path)
名前を 1 バイトでも変えると、前に書き出したフォルダと別の名前になる(同じ動画が 2 つのフォルダに分かれる)ので、規則を変えるときは両方のテストを通す。
"""
import glob
import os
import re

from .schemas import WORK_DIR

# Windows の MAX_PATH(260)より少し短く抑える。長いパスを有効にしていない PC や、ffmpeg・yt-dlp の一時ファイル名(.part など)の分の余裕。
# UTF-16 の単位で数える(Windows のパスの長さの数え方。絵文字などは2つ分)
MAX_PATH_UNITS = 240
SUFFIX_ROOM = 36    # base のあとに付く最長の名前(作業用/ + _edit.partial.mp4.vol.mp4 / yt-dlp の区間取得の 作業用/ + _edit_dl.partial.f399.mp4.part など)
BASE_ROOM = 26      # 01_00h00m00s-00h00m00s(22文字)+ 連番 _NN の分。ラベルは余った分だけ付ける
# 書きかけの印(2026-09-30。設計レビュー studio の 4)。拡張子は .mp4 のまま(ffmpeg は拡張子で形式を決める)
PARTIAL = ".partial"
OWNER_FILE = ".studio-id"   # フォルダの持ち主の印(作業用/ の中。以前の置き方はフォルダの直下)
# Windows の予約名(拡張子を付けても・後ろに空白があっても使えない)。上付き数字の COM¹ などと CONIN$ / CONOUT$ も予約されている
_RES_DIGITS = [str(i) for i in range(1, 10)] + ["¹", "²", "³"]
WIN_RESERVED = {"CON", "PRN", "AUX", "NUL", "CONIN$", "CONOUT$"} | {"COM" + d for d in _RES_DIGITS} | {"LPT" + d for d in _RES_DIGITS}


def compact_ts(t):
    """秒 → "01h02m05s"(負の数は 0)"""
    s = int(max(0, t))
    return "%02dh%02dm%02ds" % (s // 3600, s % 3600 // 60, s % 60)


def safe_name(s, n):
    """パス区切り・予約文字・制御文字と、yt-dlp の出力テンプレートで意味を持つ % を _ にして、n 文字までに(前後の空白・ドット・_ は除く)"""
    s = re.sub(r'[\\/:*?"<>|%\x00-\x1f]+', "_", str(s or ""))
    return s[:n].strip(" ._")


def is_reserved(name):
    return name.split(".", 1)[0].rstrip(" ").upper() in WIN_RESERVED


def path_units(s):
    """Windows のパスの長さ(UTF-16 の単位)。"""
    return len(str(s).encode("utf-16-le", "surrogatepass")) // 2


def trim_units(s, n):
    """UTF-16 の単位で n 以下になるよう後ろを削る(削った後の末尾の空白・ドット・_ も除く)。"""
    s = str(s)
    while s and path_units(s) > n:
        s = s[:-1]
    return s.rstrip(" ._")


# ---------- フォルダの持ち主の印 ----------
def read_owner(folder):
    """印を読む(作業用/ → 以前の置き方 = フォルダの直下)。無ければ None"""
    for m in (os.path.join(folder, WORK_DIR, OWNER_FILE), os.path.join(folder, OWNER_FILE)):
        try:
            with open(m, encoding="utf-8") as f:
                return f.read().strip()
        except OSError:
            continue
    return None


def write_owner(folder, owner):
    os.makedirs(os.path.join(folder, WORK_DIR), exist_ok=True)
    with open(os.path.join(folder, WORK_DIR, OWNER_FILE), "w", encoding="utf-8") as f:
        f.write(owner)


def pick_folder(root, title, owner, fallback):
    """動画ごとの保存先フォルダ(<root>/<名前>/)を決めて作る。-> (フォルダ名, パス)。100 通り試して作れなければ None。
    名前は title から(空なら fallback)。作業用/.studio-id に owner を書き、同じ名前で持ち主の違うフォルダとは混ぜない(連番 _2 …)。
    印の無いフォルダ(手で作られた)は、その owner のものとして使う。OSError(作れない)はそのまま上げる"""
    # 出力先が長いときは、フォルダ名を短くしてファイル名(BASE_ROOM + ラベル + SUFFIX_ROOM)の分を残す
    room = MAX_PATH_UNITS - path_units(root) - 1 - 3 - 1 - BASE_ROOM - SUFFIX_ROOM
    name = trim_units(safe_name(title, 60), max(8, min(60, room))) or fallback
    if is_reserved(name):
        name = "_" + name
    for i in range(1, 100):
        cand = name if i == 1 else "%s_%d" % (name, i)
        path = os.path.join(root, cand)
        if not os.path.exists(path):
            os.makedirs(path)
            write_owner(path, owner)
            return cand, path
        if os.path.isdir(path):
            got = read_owner(path)
            if got == owner:
                return cand, path
            if got is None:
                write_owner(path, owner)
                return cand, path
    return None


# ---------- 1 本の名前 ----------
def unique_base(base, folder):
    """フォルダ内で使われていない名前。<名前>.* だけでなく、同時に作る <名前>_edit.* も空いていることを確かめる
    (前回の編集用素材だけが残っていると、ffmpeg の -y で上書き・yt-dlp は取得済みとして古い物を使ってしまうため)。
    途中のファイルの 作業用/ の中も見る(2026-09-27 から .clip.json・_edit.mp4 などはそこ。以前の置き方の直下も見る)"""
    def used(name):
        return any(glob.glob(glob.escape(os.path.join(d, n)) + ".*")
                   for d in (folder, os.path.join(folder, WORK_DIR)) for n in (name, name + "_edit"))
    name, i = base, 2
    while used(name):
        name = "%s_%d" % (base, i)
        i += 1
    return name


def clip_base(folder, n, start, end, label, unique=unique_base):
    """切り抜き 1 本の名前(拡張子なし)= <番号 2 桁>_<開始>-<終わり>_<ラベル>。start・end は動画(録画)の頭からの秒。
    ラベルは、出力先 + ファイル名が MAX_PATH_UNITS に収まる分だけ付ける(連番 _NN と SUFFIX_ROOM の分を残す)。フォルダで空いている名前にする。
    unique: 空いている名前を選ぶ関数(呼ぶ側が自分の unique_base を渡す = テストが exporter.unique_base を差し替えて失敗の経路を作る)"""
    head = "%02d_%s-%s" % (n, compact_ts(start), compact_ts(end))
    room = MAX_PATH_UNITS - SUFFIX_ROOM - 3 - 1 - path_units(os.path.join(folder, head))
    label = trim_units(safe_name(label, 30), max(0, room))
    return unique(head + ("_" + label if label else ""), folder)


def partial_path(folder, base, ext=".mp4"):
    """書きかけのファイルの場所(同じフォルダ・<base>.partial.mp4。置き換えが同じドライブの中で済む)。"""
    return os.path.join(folder, base + PARTIAL + ext)


def is_partial(path):
    return os.path.splitext(os.path.basename(str(path or "")))[0].endswith(PARTIAL)


def final_path(path):
    """<base>.partial.<拡張子> → <base>.<拡張子>(書きかけでなければそのまま)。"""
    if not is_partial(path):
        return path
    d, n = os.path.split(path)
    root, ext = os.path.splitext(n)
    return os.path.join(d, root[:-len(PARTIAL)] + ext)
