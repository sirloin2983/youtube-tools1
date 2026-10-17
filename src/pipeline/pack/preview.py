"""① 確認用の動画(友人が受け取るかを決める前に見る、1 本の切り抜きの 480p の動画)とパックの中の切り抜きの動画の引き方(ds1 = 要件 1-5。② flow/deliver から分けた)。

- make_preview / clip_preview: 1 本の切り抜きの確認用の動画(480p・等速・字幕なし・札なし)。ffmpeg を動かす。
  F3-6(notes:plan/f1-friend-requirements.md の C-3-3・C-6): 5 本ずつの組のまとめ動画(つなげて「i/N 題」の札)はやめ、1 本ずつにした
- pack_video / pack_title / pack_seconds: パックのフォルダの中の切り抜きの動画・題・長さ(届く物の .meta.json の seconds)
- batch_preview / clip_seconds: 友人の PC の受信箱(src/friendapp/engine.py)が組の確認用の動画と長さの一覧に使う間だけ残す古い口
  (n 本をつなげる・札なし。F3-B / F3-7 で受信箱が 1 本ずつになったら消す)
- scratch_path / remove_quiet: 作りかけのファイルの置き場所(パックの隣 = Dropbox の外)と後片付け
Dropbox も届けた記録も知らない(届けるのは ② flow/deliver・flow/delivery)。ytt だけを読む。
"""
import os
import shutil
import tempfile
import uuid

from ytt import fsio, normalize, tools

CLIP_EXT = (".mp4", ".mov", ".mkv", ".webm", ".m4v")                     # パックの中の切り抜きの動画
PREVIEW_HEIGHT = 480           # 確認用の動画の縦の画素数(速さは等速 = 2026-10-08 ユーザー決定)
PREVIEW_CRF = 28               # 確認用の動画の画質(本番より落とす。90 秒で 6〜10MB の見込み)
PREVIEW_TIMEOUT = 600          # 確認用の動画を作る ffmpeg の上限(秒)。長い切り抜きは長さ × PREVIEW_PER_SEC まで延ばす
PREVIEW_PER_SEC = 0.5          # (友人の依頼の区間は長さの上限なし = 3 時間の切り抜きでも 600 秒で切らない)


def pack_title(d):
    """パックのフォルダの名前から題(<題>_pack の <題>)"""
    base = os.path.basename(os.path.normpath(d))
    return base[:-5] if base.endswith("_pack") else base


def scratch_path(pack_dir, tag, ext):
    """作りかけのファイルを置くパス(パックの隣 = Dropbox の外。名前は .deliver- で始まる。書きかけを同期させない・友人の一覧に出さない)"""
    return os.path.join(os.path.dirname(os.path.normpath(pack_dir)), ".deliver-%s%s%s" % (tag, uuid.uuid4().hex[:8], ext))


def remove_quiet(path):
    """あれば消す(消せなくても構わないもの: 作りかけの zip・確認用の動画・置きかけの preview)。None・空でもよい"""
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


def _preview_args(ffmpeg, video, out, height, audio):
    """確認用の動画を作る ffmpeg の引数(height に縮めて等速・30fps・音は 96k の aac か無し)"""
    args = [ffmpeg, "-hide_banner", "-nostdin", "-y", "-loglevel", "error", "-i", video, "-vf", "scale=-2:%d" % height, "-map", "0:v:0"]
    args += ["-map", "0:a:0", "-c:a", "aac", "-b:a", "96k"] if audio else ["-an"]
    return args + ["-r", "30", "-c:v", "libx264", "-preset", "veryfast", "-crf", str(PREVIEW_CRF), "-pix_fmt", "yuv420p", "-movflags", "+faststart", out]


def make_preview(video, out_path, height=PREVIEW_HEIGHT, ffmpeg=None, ffprobe=None, timeout=PREVIEW_TIMEOUT, check=None, log=None):
    """1 本の切り抜きの、友人が中身を確かめるための動画を out_path に作る(480p・等速・字幕なし・札なし)。-> 作れたか。
    作れなくても呼ぶ側は確認用の動画なしで届ける。音の無いクリップは音なしで作る"""
    log = log or (lambda msg: None)
    ffmpeg = ffmpeg or tools.find_tool("ffmpeg")
    if not ffmpeg or not video or not os.path.isfile(video):
        return False
    info = normalize.probe(video, ffprobe=ffprobe) or {}
    audio = bool(info.get("has_audio"))
    dur = info.get("duration")
    if isinstance(dur, (int, float)) and dur > 0:
        timeout = max(timeout, dur * PREVIEW_PER_SEC)
    tmpdir = tempfile.mkdtemp(prefix="ytt-preview-")
    tmp_out = os.path.join(tmpdir, "preview.mp4")
    try:
        code, err = _run_ffmpeg(_preview_args(ffmpeg, video, tmp_out, height, audio), timeout, check)
        if code == 0 and os.path.isfile(tmp_out) and os.path.getsize(tmp_out) > 0:
            shutil.move(tmp_out, out_path)
            return True
        log("確認用の動画を作れませんでした: %s" % err)
        return False
    finally:
        shutil.rmtree(tmpdir, ignore_errors=True)


def _concat_args(ffmpeg, videos, out, height, audio):
    """(古い口)n 本を height に縮めて等速で concat する ffmpeg の引数(札なし)"""
    parts = []
    for i in range(len(videos)):
        parts.append("[%d:v]scale=-2:%d[v%d]" % (i, height, i))
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


def batch_preview(dirs, check=None, log=None):
    """(古い口。友人の PC の受信箱の組だけ)n 本のパックをつなげた確認用の動画を、作りかけの名前で最初のパックの隣に作る(札なし)。
    1 本なら clip_preview と同じ。-> パスか None"""
    if len(dirs or ()) == 1:
        return clip_preview(dirs[0], check=check, log=log)
    videos = [pack_video(d) for d in dirs or ()]
    ffmpeg = tools.find_tool("ffmpeg")
    if not dirs or not all(videos) or not ffmpeg:
        return None
    audio = all((normalize.probe(v) or {}).get("has_audio") for v in videos)
    out = scratch_path(dirs[0], "preview-", ".mp4")
    code, err = _run_ffmpeg(_concat_args(ffmpeg, videos, out, PREVIEW_HEIGHT, audio), PREVIEW_TIMEOUT, check)
    if code == 0 and os.path.isfile(out) and os.path.getsize(out) > 0:
        return out
    (log or (lambda m: None))("確認用の動画を作れませんでした: %s" % err)
    remove_quiet(out)
    return None


def clip_seconds(dirs, ffprobe=None):
    """(古い口。友人の PC の受信箱)各パックの切り抜きの長さの一覧(秒か None)"""
    return [pack_seconds(d, ffprobe=ffprobe) for d in dirs]


def clip_preview(d, check=None, log=None):
    """パック 1 本の確認用の動画を、作りかけの名前でパックの隣に作る。-> パスか None(パックに切り抜きの動画が無い・ffmpeg が無い・作れなかった)。
    使い終わったら呼ぶ側が remove_quiet で消す"""
    video = pack_video(d)
    if not video:
        return None
    out = scratch_path(d, "preview-", ".mp4")
    if make_preview(video, out, check=check, log=log):
        return out
    remove_quiet(out)
    return None


def pack_seconds(d, ffprobe=None):
    """パックの切り抜きの長さ(秒。分からなければ None)。届く物の .meta.json の seconds"""
    v = pack_video(d)
    info = normalize.probe(v, ffprobe=ffprobe) if v else None
    dur = (info or {}).get("duration")
    return float(dur) if isinstance(dur, (int, float)) and not isinstance(dur, bool) and dur > 0 else None
