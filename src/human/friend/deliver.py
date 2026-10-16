"""パックを友人へ届ける(Dropbox の見張るフォルダの 出力\\ に zip で置く。友人のアプリの「受け取る」が読む)。
notes:docs/spec/friend.md の 2-7・2-16。

- deliver_one: 1 本を届ける(まとめ動画 → zip → 届けた記録 deliveries.jsonl)。まとめて実行の届ける段(同じフォルダの delivery.py の _deliver_one。組の中の 1 本も)と
  手で届ける(Deliveries = 「編集」の「友人へ届ける」・案件の「採用(友人へ届ける)」)が同じこれを使う(10-13 ユーザー決定 Q16)
- zip_packs: パックを zip に(中は <題>_pack/ が並ぶ)
- group_paths / clip_seconds / group_members / write_group_json: 組(n 本 = まとめ動画 1 本 + 1 本ずつの zip + 組の一覧 <名前>.group.json。2-16。ホーム 0.47.0)の名前・長さ・一覧
- make_preview / batch_preview: n 本の切り抜きをつなげた確認用の動画(480p・等速・各クリップに「i/N 題」の札。字幕なし)。友人が受け取る前に見るためのもの。
  place_preview が zip の隣に <zip の名前>.preview.mp4 で置く
- 名前: zip は <依頼 id>__<題>(delivery_name)。同じ名前があれば末尾に 4 文字足す(unique_zip)
- 出どころ(D-SEND 2-7。notes:plan/d-send-requirements.md): 届けた記録の origin は request(友人の依頼)・auto(自分の配信から自動で)・manual(手で届ける)。
  友人に見せる出どころ(face_origin)は request か auto(手で届けるも auto = 札「依頼なし」)。組は .group.json の上段 "origin"、
  1 本(組でない)で依頼でないときは zip より先に隣へ <zip の名前(.zip 抜き)>.meta.json {"v":1,"origin":"auto","sentAt":…}(write_meta_json)
- Deliveries: 手で「友人へ届ける」(画面の api/ytt/deliver)の裏の仕事。数 GB の zip は時間がかかるので、画面は状態を聞き直す
送れるのは cut2resolve が作ったパックのフォルダだけ(manage.cases.txindex.is_pack_dir。画面から任意のフォルダを Dropbox へ出させない)。
zip は動画を圧縮しない(ZIP_STORED)ので CPU はほとんど使わない → 重い処理の枠(jobs.SLOTS)は通さない(文字起こしの後ろで何時間も待たせないため)。
同時に作るのは1本だけ(ディスクの取り合いを避ける)。
"""
import datetime
import os
import shutil
import tempfile
import threading
import time
import types
import uuid
import zipfile

from ytt import fsio, normalize, tools
from . import friend_feedback  # noqa: E402  (届けた zip の中身の記録 deliveries.jsonl。友人の「要らない」が来たときに引く)
from .intake import BAD_NAME_CHARS, OUT_DIR  # noqa: E402  (見張るフォルダの 出力\ = 友人のアプリの「受け取る」が読む。フォルダの名前は受付の 1 か所)

VIDEO_EXT = (".mp4", ".mov", ".mkv", ".webm", ".m4v", ".wav", ".m4a")   # 圧縮しても小さくならない物は ZIP_STORED
CLIP_EXT = (".mp4", ".mov", ".mkv", ".webm", ".m4v")                     # パックの中の切り抜きの動画
PREVIEW_HEIGHT = 480           # まとめ動画の縦の画素数(速さは等速 = 2026-10-08 ユーザー決定。組の一覧の previewStart も等速が前提)
PREVIEW_CRF = 28               # まとめ動画の画質(本番より落とす。5 本 × 90 秒で 30〜50MB の見込み)
PREVIEW_LABEL_SEC = 0          # 各クリップの「i/N 題」の札を出す秒数(0 = ずっと出す。2026-10-08 ユーザー決定)
PREVIEW_TIMEOUT = 600          # まとめ動画を作る ffmpeg の上限(秒)
PREVIEW_SUFFIX = ".preview.mp4"        # zip の隣の名前(<zip の名前>.preview.mp4。友人のアプリが先にこれだけ取ってきて見る。zip の中には入れない)
META_SUFFIX = ".meta.json"             # 1 本のパックの出どころ(<zip の名前>.meta.json。D-SEND 2-7。友人のアプリの OutputFolder.MetaSuffix と同じ)
FONT_CANDIDATES = ("meiryo.ttc", "YuGothM.ttc", "msgothic.ttc")   # 札の文字(Windows の日本語フォント。無ければ札を付けない)
BAD_CHARS = BAD_NAME_CHARS   # ファイル名に使えない文字(受付と同じ決まり。intake.BAD_NAME_CHARS)
KEEP_JOBS = 20


def safe_name(s, limit=180):
    return BAD_CHARS.sub("_", str(s or ""))[:limit]


def request_id(now=None):
    """友人のアプリの依頼の id と同じ形(YYYYMMDD-HHMMSS-xxxxxx)。アプリはこの形の先頭を除いた部分を題名に出す"""
    return time.strftime("%Y%m%d-%H%M%S", time.localtime(now)) + "-" + uuid.uuid4().hex[:6]


def delivery_name(rid, title):
    """出力 フォルダに置くものの名前(拡張子なし): <依頼 id>__<題>(友人のアプリはこの形から依頼 id と題を読む)"""
    return safe_name("%s__%s" % (rid, title))


def face_origin(origin):
    """届けた記録の出どころ(request・auto・manual)-> 友人に見せる出どころ(request か auto。手で届けるも auto = 札「依頼なし」。D-SEND 2-7・2-8)"""
    return "request" if origin in (None, "", "request") else "auto"


def _local_iso(when=None):
    """その時刻の地方時 + UTC とのずれ(2026-10-09T12:00:00+09:00 の形)"""
    return datetime.datetime.fromtimestamp(time.time() if when is None else when).astimezone().isoformat(timespec="seconds")


def meta_path_for(zip_path):
    """zip の隣に置く出どころの印の名前(<zip の名前(.zip 抜き)>.meta.json)"""
    return os.path.splitext(zip_path)[0] + META_SUFFIX


def write_meta_json(path, origin, now=None):
    """1 本のパックの出どころの印を書く(D-SEND 2-7)。UTF-8・BOM なし・1 行・原子的に(一時ファイルは友人のアプリの一覧に出ない)。-> 書いた中身"""
    doc = {"v": 1, "origin": origin, "sentAt": _local_iso(now)}
    fsio.write_json(path, doc, indent=None)
    return doc


def pack_title(d):
    """パックのフォルダの名前から題(<題>_pack の <題>)"""
    base = os.path.basename(os.path.normpath(d))
    return base[:-5] if base.endswith("_pack") else base


def unique_zip(out_dir, name):
    """out_dir/<name>.zip の、まだ無いパス(同じ名前があれば末尾に 4 文字足す)"""
    dest = os.path.join(out_dir, name + ".zip")
    if os.path.exists(dest):
        dest = os.path.join(out_dir, "%s-%s.zip" % (name, uuid.uuid4().hex[:4]))
    return dest


def scratch_path(pack_dir, tag, ext):
    """作りかけのファイルを置くパス(パックの隣 = Dropbox の外。名前は .deliver- で始まる。書きかけを同期させない・友人の一覧に出さない)"""
    return os.path.join(os.path.dirname(os.path.normpath(pack_dir)), ".deliver-%s%s%s" % (tag, uuid.uuid4().hex[:8], ext))


def remove_quiet(path):
    """あれば消す(消せなくても構わないもの: 作りかけの zip・まとめ動画・置きかけの preview)。None・空でもよい"""
    if path:
        fsio.unlink_quiet(path)


def zip_packs(dirs, out_dir, name, check=None, progress=None, dest=None):
    """n 本のパックのフォルダを 1 つの zip に(それぞれ <題>_pack/ の下に並ぶ)。同じ名前があれば末尾に 4 文字足す。
    dest を渡せばその名前に置く(先に unique_zip で決めて、隣に置くまとめ動画の名前をそろえるため)。-> 置いたパス。
    check(): 止めるなら例外を投げる(まとめて実行の中止)。progress(済んだバイト, 全体のバイト)。
    zip は Dropbox の外(最初のパックの隣)で作ってから移す。1980 年より前の更新時刻のファイルも入れる(strict_timestamps=False = 1980 年にそろう)"""
    dirs = [os.path.normpath(d) for d in dirs]
    os.makedirs(out_dir, exist_ok=True)
    files = []   # (ファイル, zip の中の名前, 大きさ)
    for d in dirs:
        top = os.path.basename(d)
        for base, _dirs, fs in os.walk(d):
            for f in sorted(fs):
                p = os.path.join(base, f)
                try:
                    files.append((p, os.path.join(top, os.path.relpath(p, d)), os.path.getsize(p)))
                except OSError:
                    pass
    total, done = sum(n for _p, _a, n in files) or 1, 0
    tmp = scratch_path(dirs[0], "", ".zip")
    try:
        with zipfile.ZipFile(tmp, "w", allowZip64=True, strict_timestamps=False) as z:
            for p, arc, n in files:
                if check:
                    check()
                video = os.path.splitext(p)[1].lower() in VIDEO_EXT
                z.write(p, arc, compress_type=zipfile.ZIP_STORED if video else zipfile.ZIP_DEFLATED)
                done += n
                if progress:
                    progress(done, total)
        dest = dest or unique_zip(out_dir, name)
        shutil.move(tmp, dest)
        return dest
    finally:
        remove_quiet(tmp)


def preview_path_for(zip_path):
    """zip の隣に置くまとめ動画の名前(<zip の名前>.preview.mp4。友人のアプリは名前で zip と組にする)"""
    return os.path.splitext(zip_path)[0] + PREVIEW_SUFFIX


def place_preview(preview, zip_path):
    """まとめ動画を zip の隣に <zip の名前>.preview.mp4 で写す(元の一時ファイルは呼ぶ側が消す)。-> 置いたパス。
    zip より先に置く(友人のアプリは zip が見えたら、まとめ動画もそろっているとみなす)"""
    dest = preview_path_for(zip_path)
    shutil.copyfile(preview, dest)
    return dest


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


def deliver_one(d, out_dir, name, log_dir=None, run=None, marks=None, with_preview=True, check=None, progress=None, log=None, origin="request",
                ended_at=None):
    """1 本のパックを友人へ届ける(notes:docs/spec/friend.md の 2-7・2-16。まとめて実行の 1 本ずつ・組の中の 1 本・手で届ける の 1 か所):
    ① with_preview なら、その切り抜きだけのまとめ動画 <zip の名前>.preview.mp4 を zip より先に隣へ(作れなければ zip だけ。組の中では組のものを使うので付けない)
    ①' 組でない 1 本(with_preview)で依頼でない(origin auto・manual)なら、出どころの印 <zip の名前>.meta.json を zip より先に隣へ(D-SEND 2-7。組の中は組の一覧が持つ)
    ② zip <name>.zip(同じ名前があれば末尾に 4 文字)③ 届けた記録 deliveries.jsonl に 1 行(log_dir と run があるとき。友人の「要らない」が引く。書けなくても止めない)。
    run = request_id・id・video_id・title を持つ物(まとめて実行の実行か、手で届けるときの代わり)・marks = {パックのフォルダ: {"path", "markId"}}。
    origin = 届けた記録の出どころ(request・auto・manual)・ended_at = 配信が終わった時刻(秒。分からなければ None)。
    -> 置いた zip のパス。途中で失敗したら置いたまとめ動画・印を消して例外をそのまま上げる(一時のまとめ動画はいつも消す)"""
    preview = batch_preview([d], check=check, log=log) if with_preview else None
    placed, meta = None, None
    face = face_origin(origin)
    try:
        os.makedirs(out_dir, exist_ok=True)
        dest = unique_zip(out_dir, name)
        if preview:
            placed = preview_path_for(dest)   # place_preview の途中で止まっても書きかけを残さないように先に控える
            place_preview(preview, dest)
        if with_preview and face != "request":
            meta = meta_path_for(dest)
            write_meta_json(meta, face)
        zip_packs([d], out_dir, name, check=check, progress=progress, dest=dest)
    except BaseException:
        remove_quiet(placed)
        remove_quiet(meta)
        raise
    finally:
        remove_quiet(preview)
    if log_dir and run is not None:
        friend_feedback.record_delivery(log_dir, dest, run, [d], marks, origin or "request", ended_at)
    return dest


# ---- 組で届ける(notes:docs/spec/friend.md の 2-16。ホーム 0.47.0): まとめ動画 1 本 + 1 本ずつの zip + 組の一覧 <名前>.group.json
GROUP_SUFFIX = ".group.json"


def group_paths(out_dir, name):
    """組の名前 <依頼 id>__<題> 1-5 -> (まとめ動画のパス, 組の一覧のパス, 使う名前)。同じ名前の組があれば末尾に 4 文字足す(zip の unique_zip と同じ)"""
    if os.path.exists(os.path.join(out_dir, name + PREVIEW_SUFFIX)) or os.path.exists(os.path.join(out_dir, name + GROUP_SUFFIX)):
        name = "%s-%s" % (name, uuid.uuid4().hex[:4])
    return os.path.join(out_dir, name + PREVIEW_SUFFIX), os.path.join(out_dir, name + GROUP_SUFFIX), name


def clip_seconds(dirs, ffprobe=None):
    """各パックの切り抜きの長さ(秒。分からなければ None)。組の一覧の previewStart・duration に使う(まとめ動画は等速なので頭からの秒がそのまま)"""
    out = []
    for d in dirs:
        v = pack_video(d)
        info = normalize.probe(v, ffprobe=ffprobe) if v else None
        dur = (info or {}).get("duration")
        out.append(float(dur) if isinstance(dur, (int, float)) and dur > 0 else None)
    return out


def group_members(zips, titles, seconds):
    """組の一覧の packs: [{"n", "zip", "title", "previewStart", "duration"}]。zips = [(何本目, zip のパス)]。長さの分からないクリップがあれば previewStart はそこから None"""
    out, at = [], 0.0
    for (n, zp), title, sec in zip(zips, titles, seconds):
        item = {"n": n, "zip": os.path.basename(zp), "title": title, "previewStart": round(at, 2) if at is not None else None,
                "duration": round(sec, 2) if sec is not None else None}
        out.append(item)
        at = at + sec if at is not None and sec is not None else None
    return out


def write_group_json(path, title, rng, preview_path, members, now=None, origin=None):
    """組の一覧を書く(最後に置く = 友人のアプリは一覧が見えたら組がそろっているとみなす)。UTF-8・BOM なし・1 行。
    原子的に書く(一時ファイルから置き換える = 書きかけの一覧を Dropbox に乗せない。一時ファイル .tmp-*.part は友人のアプリの一覧に出ない)。
    sentAt は その時刻の地方時 + UTC とのずれ(2026-10-09T12:00:00+09:00 の形)。origin = 友人に見せる出どころ request か auto(D-SEND 2-7。
    None = 書かない = 古い形。友人のアプリは無ければ依頼として読む)"""
    doc = {"v": 1, "title": title, "range": rng, "preview": os.path.basename(preview_path) if preview_path else None, "packs": list(members),
           "sentAt": _local_iso(now)}
    if origin is not None:
        doc["origin"] = origin
    fsio.write_json(path, doc, indent=None)
    return doc


class Deliveries:
    """手で「友人へ届ける」の仕事。folder(): 見張るフォルダ(入口の Intake.folder)。is_pack(dir): cut2resolve が作ったパックか。
    log_dir: 届けた記録 deliveries.jsonl を書くフォルダ(入口の logs。None = 書かない)。作り方はまとめて実行と同じ deliver_one(まとめ動画 + zip + 記録)"""

    def __init__(self, folder, is_pack, log=None, clock=time.time, log_dir=None):
        self.folder, self.is_pack, self.log, self.clock = folder, is_pack, log or (lambda m: None), clock
        self.log_dir = log_dir
        self.lock = threading.Lock()
        self.jobs = {}
        self.busy = threading.Lock()   # 同時に作るのは1本
        self._finished = {}            # 仕事の id -> 終わった時刻(ms)。掲示板が読む(status には出さない)

    def start(self, d, title="", on_done=None, clip=None):
        """-> 仕事の状態。断るときは ValueError(画面にそのまま出す文)。
        on_done(仕事の状態): 置き終えたときに 1 回だけ呼ぶ(自動でできた切り抜きの「採用」が案件に「届けた」を残す。src/manage/cases/cases.py。線 D の M12)。
        clip: 届けた記録に残す切り抜き {"path", "markId", "videoId"}(分かるとき。友人の「要らない」で切り抜きの動画も片付けるため。無ければパックだけ)"""
        if not isinstance(d, str) or not d.strip() or len(d) > 1024:
            raise ValueError("パックのフォルダがありません")
        d = os.path.normpath(d.strip())
        if not self.is_pack(d):
            raise ValueError("cut2resolve が作ったパックのフォルダではありません(作り直してから届けてください)")
        folder = self.folder() or ""
        if not folder:
            raise ValueError("友人からの依頼の受付で、Dropbox のフォルダが決まっていません(ホームの設定で指定してください)")
        if not os.path.isdir(folder):
            raise ValueError("Dropbox のフォルダが見つかりません: %s" % folder)
        title = (title.strip() if isinstance(title, str) else "") or pack_title(d) or "pack"
        rid = request_id(self.clock())
        name = delivery_name(rid, title)
        job = {"id": uuid.uuid4().hex[:10], "state": "running", "message": "zip にしています", "progress": 0.0,
               "dir": d, "name": name + ".zip", "error": "", "startedAt": int(self.clock() * 1000)}
        clip = clip if isinstance(clip, dict) else {}
        # 届けた記録の行の「実行」の代わり(依頼 id = zip の名前の頭・実行 id = 仕事の id)。出どころは manual(友人には「依頼なし」= D-SEND 2-8)
        run = types.SimpleNamespace(request_id=rid, id="dl" + job["id"], video_id=str(clip.get("videoId") or ""), title=title, deliver_origin="manual")
        marks = {d: {"path": str(clip.get("path") or ""), "markId": str(clip.get("markId") or "")}}
        with self.lock:
            if self._running_locked(d):
                raise ValueError("このパックは今、届けているところです")
            self.jobs[job["id"]] = job
            for k in [k for k, j in self.jobs.items() if j["state"] != "running"][:-KEEP_JOBS]:
                del self.jobs[k]
                self._finished.pop(k, None)
        threading.Thread(target=self._run, args=(job, os.path.join(folder, OUT_DIR), on_done, run, marks), daemon=True, name="deliver").start()
        return dict(job)

    def running(self, d):
        """そのパックのフォルダを今 zip にしているか(届けている途中のパックを「要らない」で動かさない。src/manage/cases/cases.py)"""
        with self.lock:
            return self._running_locked(d)

    def _running_locked(self, d):
        """running の中身(self.lock を持っている間に呼ぶ)。パスは大文字・小文字と区切りをそろえて比べる"""
        d = os.path.normcase(os.path.normpath(str(d or "")))
        return any(j["state"] == "running" and os.path.normcase(j["dir"]) == d for j in self.jobs.values())

    def _run(self, job, out_dir, on_done=None, run=None, marks=None):
        def prog(done, total):
            job["message"] = "zip にしています"
            job["progress"] = round(done / total, 3)
        if not self.busy.acquire(blocking=False):
            job["message"] = "前のパックを届け終わるのを待っています"
            self.busy.acquire()
        try:
            job["message"] = "まとめ動画を作っています"
            dest = deliver_one(job["dir"], out_dir, job["name"][:-4], log_dir=self.log_dir, run=run, marks=marks, progress=prog, log=self.log,
                               origin=getattr(run, "deliver_origin", None) or "manual")
            done = dict(state="done", progress=1.0, name=os.path.basename(dest),
                        message="Dropbox の 出力 に置きました。同期が終わると友人のアプリの「受け取る」に出ます")
            self.log("友人へ届ける: %s を 出力 に置きました" % os.path.basename(dest))
            if on_done:   # 記録してから done にする(画面は done を見てすぐ一覧を読み直すので、先に done にすると「届けた」がまだ無い一覧を読む。10-09)
                try:
                    on_done(dict(job, **done))
                except Exception as e:   # 記録できなくても、届けたことは変わらない(ログにだけ残す)
                    self.log("友人へ届ける: 届けたことを記録できませんでした: %r" % (e,))
            job.update(done)
        except Exception as e:   # noqa: BLE001  (zip にできないファイルなど何でも error にする。running のまま残すと同じパックを二度と届けられない)
            why = tools.why(e) if isinstance(e, OSError) else "%s: %s" % (e.__class__.__name__, str(e)[:200])
            job.update(state="error", error=why, message="届けられませんでした: %s" % why)
            self.log("友人へ届ける: 失敗 %s (%s)" % (job["dir"], job["message"]))
        finally:
            self.busy.release()
            with self.lock:
                self._finished[job["id"]] = int(self.clock() * 1000)

    # ---- 掲示板(RS8 の ② の口 S2。flow/board.py。頭 dl・id = dl:<仕事の id>。入口が board を渡して 1 回呼ぶ。取り消し・やり直しは無い) ----
    def attach_board(self, board):
        board.register("dl", source=self.board_jobs)

    def board_jobs(self):
        """掲示板の引く形: 仕事(入れた順)-> [Job の辞書]。target.path = パックのフォルダ(案件の根は掲示板の case_hook が引く)"""
        with self.lock:
            rows = [(dict(j), self._finished.get(j["id"])) for j in self.jobs.values()]
        out = []
        for j, fin in rows:
            state = j["state"] if j["state"] in ("running", "done", "error") else "error"
            out.append({"id": "dl:" + j["id"], "kind": "deliver", "target": {"path": j["dir"]}, "title": j["name"], "state": state,
                        "phase": j["message"], "progress": j["progress"], "createdAt": j["startedAt"], "startedAt": j["startedAt"], "finishedAt": fin,
                        "error": {"code": None, "text": j["message"], "detail": j["error"] or None} if state == "error" else None})
        return out

    def status(self, job_id):
        with self.lock:
            j = self.jobs.get(job_id) if isinstance(job_id, str) else None
            return dict(j) if j else None
