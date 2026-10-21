"""① 確認用の動画(友人が受け取るかを決める前に見る、1 本の切り抜きの 480p の動画)とパックの中の切り抜きの動画の引き方(ds1 = 要件 1-5。② flow/deliver から分けた)。

- make_preview / clip_preview: 1 本の切り抜きの確認用の動画(480p・等速・字幕なし・札なし)。ffmpeg を動かす。
  (notes:plan/f1-friend-requirements.md の C-3-3・C-6)
- pack_video / pack_title / pack_seconds: パックのフォルダの中の切り抜きの動画・題・長さ(届く物の .meta.json の seconds)
- scratch_path / remove_quiet: 作りかけのファイルの置き場所(パックの隣 = Dropbox の外)と後片付け
Dropbox も届けた記録も知らない(届けるのは ② flow/deliver・flow/delivery)。ytt だけを読む。
"""
import os
import shutil
import tempfile
import uuid

from ytt import fsio, normalize, tools

LONG_PATH_AT = 240             # このくらい長いパスは \\?\ の形にして OS・ffmpeg に渡す(Windows の 260 文字の壁)
CLIP_EXT = (".mp4", ".mov", ".mkv", ".webm", ".m4v")                     # パックの中の切り抜きの動画
PREVIEW_HEIGHT = 480           # 確認用の動画の縦の画素数(速さは等速 = ユーザー決定)
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
        names = os.listdir(fsio.long_path(d))   # 友人の動画の題は長い = 題が 2 回入るパックのパスは 260 文字を超えうる(Windows)
    except OSError:
        return None
    for n in names:
        p = os.path.join(d, n)
        stem, ext = os.path.splitext(n)
        if ext.lower() not in CLIP_EXT or stem.endswith("_roughcut") or not os.path.isfile(fsio.long_path(p)):
            continue
        size = os.path.getsize(fsio.long_path(p))
        if best is None or size > best[0]:
            best = (size, p)
    if not best:
        return None
    return fsio.long_path(best[1]) if len(best[1]) >= LONG_PATH_AT else best[1]   # ffmpeg・ffprobe へ渡すときも長いパスの形


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


def _preview_args(ffmpeg, video, out, height, audio, vargs):
    """確認用の動画を作る ffmpeg の引数(height に縮めて等速・30fps・音は 96k の aac か無し)。vargs = 映像の作り方(normalize.video_tries の 1 つ)"""
    args = [ffmpeg, "-hide_banner", "-nostdin", "-y", "-loglevel", "error", "-i", video, "-vf", "scale=-2:%d" % height, "-map", "0:v:0"]
    args += ["-map", "0:a:0", "-c:a", "aac", "-b:a", "96k"] if audio else ["-an"]
    return args + ["-r", "30"] + list(vargs) + ["-pix_fmt", "yuv420p", "-movflags", "+faststart", out]


def make_preview(video, out_path, height=PREVIEW_HEIGHT, ffmpeg=None, ffprobe=None, timeout=PREVIEW_TIMEOUT, check=None, log=None):
    """1 本の切り抜きの、友人が中身を確かめるための動画を out_path に作る(480p・等速・字幕なし・札なし)。
    -> 作った作り方の名前(h264_amf・libx264 など。作れなければ None)。
    作り方は normalize.video_tries の順(GPU → 失敗したら libx264 で 1 回だけ)。作れなくても呼ぶ側は確認用の動画なしで届ける。
    音の無いクリップは音なしで作る"""
    log = log or (lambda msg: None)
    ffmpeg = ffmpeg or tools.find_tool("ffmpeg")
    if not ffmpeg or not video or not os.path.isfile(fsio.long_path(video)):
        return None
    info = normalize.probe(video, ffprobe=ffprobe) or {}
    audio = bool(info.get("has_audio"))
    dur = info.get("duration")
    if isinstance(dur, (int, float)) and dur > 0:
        timeout = max(timeout, dur * PREVIEW_PER_SEC)
    tmpdir = tempfile.mkdtemp(prefix="ytt-preview-")
    tmp_out = os.path.join(tmpdir, "preview.mp4")
    try:
        failed = []
        for how, vargs in normalize.video_tries(ffmpeg, "preview", "veryfast"):
            code, err = _run_ffmpeg(_preview_args(ffmpeg, video, tmp_out, height, audio, vargs), timeout, check)
            if code == 0 and os.path.isfile(tmp_out) and os.path.getsize(tmp_out) > 0:
                shutil.move(tmp_out, fsio.long_path(out_path))
                if failed:
                    log("確認用の動画: %s で作れなかったので %s で作りました(%s)" % (failed[0][0], how, failed[0][1][:200]))
                return how
            failed.append((how, err))
            if err == "timeout":
                break
            remove_quiet(tmp_out)
        log("確認用の動画を作れませんでした: %s" % failed[-1][1])
        return None
    finally:
        shutil.rmtree(tmpdir, ignore_errors=True)


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
