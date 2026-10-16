"""① まとめ動画(友人へ届ける前に見る、n 本の切り抜きをつなげた確認用の動画)とパックの中の切り抜きの動画の引き方(ds1 = 要件 1-5。② flow/deliver から分けた)。

- make_preview / batch_preview: n 本の切り抜きをつなげた確認用の動画(480p・等速・各クリップに「i/N 題」の札。字幕なし)。ffmpeg を動かす
- pack_video / pack_title / clip_seconds: パックのフォルダの中の切り抜きの動画・題・長さ(組の一覧の previewStart に使う)
- scratch_path / remove_quiet: 作りかけのファイルの置き場所(パックの隣 = Dropbox の外)と後片付け
Dropbox も届けた記録も知らない(届けるのは ② flow/deliver・flow/delivery)。ytt だけを読む。notes:docs/spec/friend.md の 2-13・2-16。
"""
import os
import shutil
import tempfile
import uuid

from ytt import fsio, normalize, tools

CLIP_EXT = (".mp4", ".mov", ".mkv", ".webm", ".m4v")                     # パックの中の切り抜きの動画
PREVIEW_HEIGHT = 480           # まとめ動画の縦の画素数(速さは等速 = 2026-10-08 ユーザー決定。組の一覧の previewStart も等速が前提)
PREVIEW_CRF = 28               # まとめ動画の画質(本番より落とす。5 本 × 90 秒で 30〜50MB の見込み)
PREVIEW_LABEL_SEC = 0          # 各クリップの「i/N 題」の札を出す秒数(0 = ずっと出す。2026-10-08 ユーザー決定)
PREVIEW_TIMEOUT = 600          # まとめ動画を作る ffmpeg の上限(秒)
FONT_CANDIDATES = ("meiryo.ttc", "YuGothM.ttc", "msgothic.ttc")   # 札の文字(Windows の日本語フォント。無ければ札を付けない)


def pack_title(d):
    """パックのフォルダの名前から題(<題>_pack の <題>)"""
    base = os.path.basename(os.path.normpath(d))
    return base[:-5] if base.endswith("_pack") else base


def scratch_path(pack_dir, tag, ext):
    """作りかけのファイルを置くパス(パックの隣 = Dropbox の外。名前は .deliver- で始まる。書きかけを同期させない・友人の一覧に出さない)"""
    return os.path.join(os.path.dirname(os.path.normpath(pack_dir)), ".deliver-%s%s%s" % (tag, uuid.uuid4().hex[:8], ext))


def remove_quiet(path):
    """あれば消す(消せなくても構わないもの: 作りかけの zip・まとめ動画・置きかけの preview)。None・空でもよい"""
    if path:
        fsio.unlink_quiet(path)


def pack_video(d):
    """パックのフォルダの中の切り抜きの動画(フォルダ直下でいちばん大きい動画。粗編集の _roughcut は除く)。無ければ None"""
    best = None
    try:
        names = os.listdir(d)
    except OSError:
        return None
    for n in names:
        p = os.path.join(d, n)
        stem, ext = os.path.splitext(n)
        if ext.lower() not in CLIP_EXT or stem.endswith("_roughcut") or not os.path.isfile(p):
            continue
        size = os.path.getsize(p)
        if best is None or size > best[0]:
            best = (size, p)
    return best[1] if best else None


def _font_file():
    """札の文字のフォント(Windows の日本語フォント)。無ければ None = 札を付けない"""
    base = os.path.join(os.environ.get("WINDIR") or "C:\\Windows", "Fonts")
    for n in FONT_CANDIDATES:
        p = os.path.join(base, n)
        if os.path.isfile(p):
            return p
    return None


def _fpath(p):
    """ffmpeg のフィルタの引数に入れるパス(区切りは / ・ドライブ名の : は \\: に)"""
    return p.replace("\\", "/").replace(":", "\\:")


def _run_ffmpeg(args, timeout, check):
    """ffmpeg を動かして終わるのを待つ。check() が例外を投げたら(中止)ffmpeg を止めて投げ直す。-> (終了コード, stderr の末尾)。
    時間切れは (1, "timeout")"""
    def cancelled():
        check()          # 止めるなら例外(tools.run が子を止めてから上げ直す)。戻り値は見ない
        return False
    r = tools.run(args, timeout=timeout, cancelled=cancelled if check else None, stdout=False)
    if r.why == "timeout":
        return 1, "timeout"
    return r.code, r.err[-400:].decode("utf-8", "replace").strip()


def _preview_args(ffmpeg, videos, out, height, audio, label_files=None, font=None):
    """まとめ動画を作る ffmpeg の引数。各クリップを height に縮めて等速で concat。
    label_files = クリップごとの札の文字のファイル(drawtext の textfile。日本語をそのまま渡すため)。None なら札なし。
    札は PREVIEW_LABEL_SEC 秒(0 = ずっと)"""
    parts = []
    for i in range(len(videos)):
        chain = "[%d:v]scale=-2:%d" % (i, height)
        if label_files:
            chain += (",drawtext=fontfile='%s':textfile='%s':fontsize=28:fontcolor=white:box=1:boxcolor=black@0.6:boxborderw=8:x=16:y=16"
                      % (_fpath(font), _fpath(label_files[i]))) + (":enable='lt(t,%d)'" % PREVIEW_LABEL_SEC if PREVIEW_LABEL_SEC > 0 else "")
        parts.append(chain + "[v%d]" % i)
        if audio:
            parts.append("[%d:a]anull[a%d]" % (i, i))
    n = len(videos)
    parts.append("".join("[v%d]%s" % (i, "[a%d]" % i if audio else "") for i in range(n)) +
                 "concat=n=%d:v=1:a=%d[v]%s" % (n, 1 if audio else 0, "[a]" if audio else ""))
    args = [ffmpeg, "-hide_banner", "-nostdin", "-y", "-loglevel", "error"]
    for v in videos:
        args += ["-i", v]
    args += ["-filter_complex", ";".join(parts), "-map", "[v]"]
    args += ["-map", "[a]", "-c:a", "aac", "-b:a", "96k"] if audio else ["-an"]
    return args + ["-r", "30", "-c:v", "libx264", "-preset", "veryfast", "-crf", str(PREVIEW_CRF), "-pix_fmt", "yuv420p", "-movflags", "+faststart", out]


def _label_files(tmpdir, labels, n):
    """札の文字「i/N 題」を 1 本ずつファイルに書く -> パスの一覧"""
    out = []
    for i in range(n):
        tf = os.path.join(tmpdir, "label%d.txt" % i)
        with open(tf, "w", encoding="utf-8") as f:
            f.write("%d/%d %s" % (i + 1, n, labels[i] if i < len(labels) else ""))
        out.append(tf)
    return out


def make_preview(videos, out_path, labels=None, height=PREVIEW_HEIGHT, ffmpeg=None, ffprobe=None, timeout=PREVIEW_TIMEOUT, check=None, log=None):
    """n 本の切り抜きをつなげた、友人が中身を確かめるための動画を out_path に作る(480p・等速・
    各クリップに「i/N 題」の札(PREVIEW_LABEL_SEC 秒。0 = ずっと)。字幕は入れない)。-> 作れたか。作れなくても呼ぶ側はまとめ動画なしで届ける。
    音の無いクリップが混ざっていれば音なしで作る。札はフォントが無い・drawtext で失敗したときは付けずにもう一度作る"""
    log = log or (lambda msg: None)
    ffmpeg = ffmpeg or tools.find_tool("ffmpeg")
    videos = [v for v in videos if v and os.path.isfile(v)]
    if not ffmpeg or not videos:
        return False
    labels = list(labels or [pack_title(os.path.dirname(v)) for v in videos])
    audio = all((normalize.probe(v, ffprobe=ffprobe) or {}).get("has_audio") for v in videos)
    font = _font_file()
    tmpdir = tempfile.mkdtemp(prefix="ytt-preview-")
    tmp_out = os.path.join(tmpdir, "preview.mp4")
    try:
        for with_labels in ((True, False) if font else (False,)):
            label_files = _label_files(tmpdir, labels, len(videos)) if with_labels else None
            code, err = _run_ffmpeg(_preview_args(ffmpeg, videos, tmp_out, height, audio, label_files, font), timeout, check)
            if code == 0 and os.path.isfile(tmp_out) and os.path.getsize(tmp_out) > 0:
                shutil.move(tmp_out, out_path)
                return True
            log("まとめ動画を作れませんでした(札%s): %s" % ("あり" if with_labels else "なし", err))
        return False
    finally:
        shutil.rmtree(tmpdir, ignore_errors=True)


def batch_preview(dirs, check=None, log=None):
    """n 本のパックのまとめ動画を、作りかけの名前で最初のパックの隣に作る(札の題 = パックの題)。-> パスか None(パックに切り抜きの動画が
    無い・ffmpeg が無い・作れなかった)。使い終わったら呼ぶ側が remove_quiet で消す"""
    videos = [pack_video(d) for d in dirs]
    if not dirs or not all(videos):
        return None
    out = scratch_path(dirs[0], "preview-", ".mp4")
    if make_preview(videos, out, [pack_title(d) for d in dirs], check=check, log=log):
        return out
    remove_quiet(out)
    return None


def clip_seconds(dirs, ffprobe=None):
    """各パックの切り抜きの長さ(秒。分からなければ None)。組の一覧の previewStart・duration に使う(まとめ動画は等速なので頭からの秒がそのまま)"""
    out = []
    for d in dirs:
        v = pack_video(d)
        info = normalize.probe(v, ffprobe=ffprobe) if v else None
        dur = (info or {}).get("duration")
        out.append(float(dur) if isinstance(dur, (int, float)) and dur > 0 else None)
    return out
