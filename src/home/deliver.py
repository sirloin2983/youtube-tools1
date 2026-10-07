"""パックを友人へ届ける(Dropbox の見張るフォルダの 出力\\ に zip で置く。友人のアプリの「受け取る」が読む)。
docs/spec/friend-intake.md の 2-7。

- zip_pack: 1本のパックのフォルダを zip にして置く。① 全自動(src/home/autorun.py)と「編集」の ③ パックの「友人へ届ける」が同じものを使う
- zip_packs: n 本のパックを 1 つの zip に(① 全自動の「n 本ごとにまとめて届ける」。2026-10-07 ユーザー決定 n=5)。中は <題>_pack/ が並び、まとめ動画も入る
- make_preview: n 本の切り抜きをつなげた確認用の動画(480p・2 倍速・各クリップの頭に「i/N 題」の札。字幕なし)。友人が受け取る前に見るためのもの
- Deliveries: 「友人へ届ける」(画面の api/ytt/deliver)の裏の仕事。数 GB の zip は時間がかかるので、画面は状態を聞き直す
送れるのは cut2resolve が作ったパックのフォルダだけ(ytt_core.txindex.is_pack_dir。画面から任意のフォルダを Dropbox へ出させない)。
zip は動画を圧縮しない(ZIP_STORED)ので CPU はほとんど使わない → 重い処理の枠(jobs.SLOTS)は通さない(文字起こしの後ろで何時間も待たせないため)。
同時に作るのは1本だけ(ディスクの取り合いを避ける)。
"""
import os
import re
import shutil
import subprocess
import tempfile
import threading
import time
import uuid
import zipfile

from ytt_core import normalize, tools

OUT_DIR = "出力"   # src/home/intake.py の OUT_DIR と同じ
VIDEO_EXT = (".mp4", ".mov", ".mkv", ".webm", ".m4v", ".wav", ".m4a")   # 圧縮しても小さくならない物は ZIP_STORED
CLIP_EXT = (".mp4", ".mov", ".mkv", ".webm", ".m4v")                     # パックの中の切り抜きの動画
PREVIEW_SPEED = 2.0            # まとめ動画の再生速度(2026-10-07 ユーザー決定: 2 倍。音の高さは変えない)
PREVIEW_HEIGHT = 480           # まとめ動画の縦の画素数
PREVIEW_CRF = 28               # まとめ動画の画質(本番より落とす。5 本 × 90 秒で 15〜25MB の見込み)
PREVIEW_LABEL_SEC = 2          # 各クリップの頭に「i/N 題」の札を出す秒数(速くしたあとの時間)
PREVIEW_TIMEOUT = 600          # まとめ動画を作る ffmpeg の上限(秒)
PREVIEW_NAME = "まとめ.mp4"            # zip の中の名前
PREVIEW_SUFFIX = ".preview.mp4"        # zip の隣の名前(<zip の名前>.preview.mp4。友人のアプリが先にこれだけ取ってきて見る)
FONT_CANDIDATES = ("meiryo.ttc", "YuGothM.ttc", "msgothic.ttc")   # 札の文字(Windows の日本語フォント。無ければ札を付けない)
BAD_CHARS = re.compile(r'[\\/:*?"<>|\x00-\x1f]')
KEEP_JOBS = 20


def safe_name(s, limit=180):
    return BAD_CHARS.sub("_", str(s or ""))[:limit]


def request_id(now=None):
    """友人のアプリの依頼の id と同じ形(YYYYMMDD-HHMMSS-xxxxxx)。アプリはこの形の先頭を除いた部分を題名に出す"""
    return time.strftime("%Y%m%d-%H%M%S", time.localtime(now)) + "-" + uuid.uuid4().hex[:6]


def unique_zip(out_dir, name):
    """out_dir/<name>.zip の、まだ無いパス(同じ名前があれば末尾に 4 文字足す)"""
    dest = os.path.join(out_dir, name + ".zip")
    if os.path.exists(dest):
        dest = os.path.join(out_dir, "%s-%s.zip" % (name, uuid.uuid4().hex[:4]))
    return dest


def zip_pack(d, out_dir, name, check=None, progress=None):
    """パックのフォルダ d を zip にして out_dir/<name>.zip に置く。-> 置いたパス。
    zip は Dropbox の外(パックの隣)で作ってから移す(書きかけを同期させない・友人の一覧に出さない)。同じ名前があれば末尾に4文字足す。
    check(): 止めるなら例外を投げる(まとめて実行の中止)。progress(済んだバイト, 全体のバイト)"""
    return _zip_many([d], out_dir, name, None, check, progress, None)


def zip_packs(dirs, out_dir, name, extra=None, check=None, progress=None, dest=None):
    """n 本のパックのフォルダを 1 つの zip に(それぞれ <題>_pack/ の下に並ぶ)。extra = [(ファイル, zip の中の名前)](まとめ動画)。
    dest を渡せばその名前に置く(先に unique_zip で決めて、隣に置くまとめ動画の名前をそろえるため)。-> 置いたパス"""
    return _zip_many(list(dirs), out_dir, name, extra, check, progress, dest)


def _zip_many(dirs, out_dir, name, extra, check, progress, dest):
    """zip_pack と zip_packs の中身。zip は Dropbox の外(最初のパックの隣)で作ってから移す(書きかけを同期させない・友人の一覧に出さない)"""
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
    for p, arc in extra or []:
        try:
            files.append((p, arc, os.path.getsize(p)))
        except OSError:
            pass
    total, done = sum(n for _p, _a, n in files) or 1, 0
    tmp = os.path.join(os.path.dirname(dirs[0]), ".deliver-%s.zip" % uuid.uuid4().hex[:8])
    try:
        with zipfile.ZipFile(tmp, "w", allowZip64=True) as z:
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
        if os.path.exists(tmp):
            try:
                os.remove(tmp)
            except OSError:
                pass


def remove_quiet(path):
    """あれば消す(消せなくても構わないもの: 途中のまとめ動画・置きかけの preview)"""
    try:
        if path and os.path.exists(path):
            os.remove(path)
    except OSError:
        pass


def preview_path_for(zip_path):
    """zip の隣に置くまとめ動画の名前(<zip の名前>.preview.mp4。友人のアプリは名前で zip と組にする)"""
    return os.path.splitext(zip_path)[0] + PREVIEW_SUFFIX


def pack_title(d):
    """パックのフォルダの名前から題(<題>_pack の <題>)"""
    base = os.path.basename(os.path.normpath(d))
    return base[:-5] if base.endswith("_pack") else base


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


def _atempo(speed):
    """音を speed 倍速に(高さは変えない)。atempo は 1 段で 2 倍までなので、それより速ければ段を重ねる(3 倍 → 2.0 と 1.5)"""
    parts, s = [], float(speed)
    while s > 2.0:
        parts.append("atempo=2.0")
        s /= 2.0
    parts.append("atempo=%g" % s)
    return ",".join(parts)


def _run_ffmpeg(args, timeout, check):
    """ffmpeg を動かして終わるのを待つ。check() が例外を投げたら(中止)ffmpeg を止めて投げ直す。-> (終了コード, stderr の末尾)"""
    proc = subprocess.Popen(args, stdin=subprocess.DEVNULL, stdout=subprocess.DEVNULL, stderr=subprocess.PIPE, creationflags=tools.no_window_flags())
    end = time.time() + timeout
    while True:
        try:
            err = proc.communicate(timeout=0.5)[1]
            return proc.returncode, (err or b"")[-400:].decode("utf-8", "replace").strip()
        except subprocess.TimeoutExpired:
            if check:
                try:
                    check()
                except BaseException:
                    tools.kill_quiet(proc)
                    raise
            if time.time() > end:
                tools.kill_quiet(proc)
                return 1, "timeout"


def make_preview(videos, out_path, labels=None, speed=PREVIEW_SPEED, height=PREVIEW_HEIGHT, ffmpeg=None, ffprobe=None, timeout=PREVIEW_TIMEOUT, check=None,
                 log=None):
    """n 本の切り抜きをつなげた、友人が中身を確かめるための動画を out_path に作る(480p・speed 倍速で音の高さは変えない・
    各クリップの頭に「i/N 題」の札。字幕は入れない = 2026-10-07 ユーザー決定)。-> 作れたか。作れなくても呼ぶ側はまとめ動画なしで届ける。
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
            n, parts = len(videos), []
            for i, v in enumerate(videos):
                chain = "[%d:v]scale=-2:%d,setpts=PTS/%g" % (i, height, speed)
                if with_labels:
                    tf = os.path.join(tmpdir, "label%d.txt" % i)
                    with open(tf, "w", encoding="utf-8") as f:
                        f.write("%d/%d %s" % (i + 1, n, labels[i] if i < len(labels) else ""))
                    chain += (",drawtext=fontfile='%s':textfile='%s':fontsize=28:fontcolor=white:box=1:boxcolor=black@0.6:boxborderw=8:x=16:y=16:enable='lt(t,%d)'"
                              % (_fpath(font), _fpath(tf), PREVIEW_LABEL_SEC))
                parts.append(chain + "[v%d]" % i)
                if audio:
                    parts.append("[%d:a]%s[a%d]" % (i, _atempo(speed), i))
            parts.append("".join("[v%d]%s" % (i, "[a%d]" % i if audio else "") for i in range(n)) +
                         "concat=n=%d:v=1:a=%d[v]%s" % (n, 1 if audio else 0, "[a]" if audio else ""))
            args = [ffmpeg, "-hide_banner", "-nostdin", "-y", "-loglevel", "error"]
            for v in videos:
                args += ["-i", v]
            args += ["-filter_complex", ";".join(parts), "-map", "[v]"]
            args += ["-map", "[a]", "-c:a", "aac", "-b:a", "96k"] if audio else ["-an"]
            args += ["-r", "30", "-c:v", "libx264", "-preset", "veryfast", "-crf", str(PREVIEW_CRF), "-pix_fmt", "yuv420p", "-movflags", "+faststart", tmp_out]
            code, err = _run_ffmpeg(args, timeout, check)
            if code == 0 and os.path.isfile(tmp_out) and os.path.getsize(tmp_out) > 0:
                shutil.move(tmp_out, out_path)
                return True
            log("まとめ動画を作れませんでした(札%s): %s" % ("あり" if with_labels else "なし", err))
        return False
    finally:
        shutil.rmtree(tmpdir, ignore_errors=True)


class Deliveries:
    """「友人へ届ける」の仕事。folder(): 見張るフォルダ(ホームの設定 intake.folder)。is_pack(dir): cut2resolve が作ったパックか"""

    def __init__(self, folder, is_pack, log=None, clock=time.time):
        self.folder, self.is_pack, self.log, self.clock = folder, is_pack, log or (lambda m: None), clock
        self.lock = threading.Lock()
        self.jobs = {}
        self.busy = threading.Lock()   # 同時に作るのは1本

    def start(self, d, title="", on_done=None):
        """-> 仕事の状態。断るときは ValueError(画面にそのまま出す文)。
        on_done(仕事の状態): 置き終えたときに 1 回だけ呼ぶ(自動でできた切り抜きの「採用」が案件に「届けた」を残す。src/home/cases.py。線 D の M12)"""
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
        title = title.strip() if isinstance(title, str) else ""
        base = os.path.basename(d)
        base = base[:-5] if base.endswith("_pack") else base
        name = safe_name("%s__%s" % (request_id(self.clock()), title or base or "pack"))
        job = {"id": uuid.uuid4().hex[:10], "state": "running", "message": "zip にしています", "progress": 0.0,
               "dir": d, "name": name + ".zip", "error": "", "startedAt": int(self.clock() * 1000)}
        with self.lock:
            if any(j["state"] == "running" and j["dir"] == d for j in self.jobs.values()):
                raise ValueError("このパックは今、届けているところです")
            self.jobs[job["id"]] = job
            for k in [k for k, j in self.jobs.items() if j["state"] != "running"][:-KEEP_JOBS]:
                del self.jobs[k]
        threading.Thread(target=self._run, args=(job, os.path.join(folder, OUT_DIR), on_done), daemon=True, name="deliver").start()
        return dict(job)

    def running(self, d):
        """そのパックのフォルダを今 zip にしているか(届けている途中のパックを「要らない」で動かさない。src/home/cases.py)"""
        d = os.path.normcase(os.path.normpath(str(d or "")))
        with self.lock:
            return any(j["state"] == "running" and os.path.normcase(j["dir"]) == d for j in self.jobs.values())

    def _run(self, job, out_dir, on_done=None):
        def prog(done, total):
            job["progress"] = round(done / total, 3)
        if not self.busy.acquire(blocking=False):
            job["message"] = "前のパックを届け終わるのを待っています"
            self.busy.acquire()
        try:
            job["message"] = "zip にしています"
            dest = zip_pack(job["dir"], out_dir, job["name"][:-4], progress=prog)
            job.update(state="done", progress=1.0, name=os.path.basename(dest),
                       message="Dropbox の 出力 に置きました。同期が終わると友人のアプリの「受け取る」に出ます")
            self.log("友人へ届ける: %s を 出力 に置きました" % os.path.basename(dest))
            if on_done:
                try:
                    on_done(dict(job))
                except Exception as e:   # 記録できなくても、届けたことは変わらない(ログにだけ残す)
                    self.log("友人へ届ける: 届けたことを記録できませんでした: %r" % (e,))
        except OSError as e:
            job.update(state="error", error=e.strerror or e.__class__.__name__,
                       message="届けられませんでした: %s" % (e.strerror or e.__class__.__name__))
            self.log("友人へ届ける: 失敗 %s (%s)" % (job["dir"], job["message"]))
        finally:
            self.busy.release()

    def status(self, job_id):
        with self.lock:
            j = self.jobs.get(job_id) if isinstance(job_id, str) else None
            return dict(j) if j else None
