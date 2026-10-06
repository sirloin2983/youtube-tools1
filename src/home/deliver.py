"""パックを友人へ届ける(Dropbox の見張るフォルダの 出力\\ に zip で置く。友人のアプリの「受け取る」が読む)。
docs/spec/friend-intake.md の 2-7。

- zip_pack: 1本のパックのフォルダを zip にして置く。① 全自動(src/home/autorun.py)と「編集」の ③ パックの「友人へ届ける」が同じものを使う
- Deliveries: 「友人へ届ける」(画面の api/ytt/deliver)の裏の仕事。数 GB の zip は時間がかかるので、画面は状態を聞き直す
送れるのは cut2resolve が作ったパックのフォルダだけ(ytt_core.txindex.is_pack_dir。画面から任意のフォルダを Dropbox へ出させない)。
zip は動画を圧縮しない(ZIP_STORED)ので CPU はほとんど使わない → 重い処理の枠(jobs.SLOTS)は通さない(文字起こしの後ろで何時間も待たせないため)。
同時に作るのは1本だけ(ディスクの取り合いを避ける)。
"""
import os
import re
import shutil
import threading
import time
import uuid
import zipfile

OUT_DIR = "出力"   # src/home/intake.py の OUT_DIR と同じ
VIDEO_EXT = (".mp4", ".mov", ".mkv", ".webm", ".m4v", ".wav", ".m4a")   # 圧縮しても小さくならない物は ZIP_STORED
BAD_CHARS = re.compile(r'[\\/:*?"<>|\x00-\x1f]')
KEEP_JOBS = 20


def safe_name(s, limit=180):
    return BAD_CHARS.sub("_", str(s or ""))[:limit]


def request_id(now=None):
    """友人のアプリの依頼の id と同じ形(YYYYMMDD-HHMMSS-xxxxxx)。アプリはこの形の先頭を除いた部分を題名に出す"""
    return time.strftime("%Y%m%d-%H%M%S", time.localtime(now)) + "-" + uuid.uuid4().hex[:6]


def zip_pack(d, out_dir, name, check=None, progress=None):
    """パックのフォルダ d を zip にして out_dir/<name>.zip に置く。-> 置いたパス。
    zip は Dropbox の外(パックの隣)で作ってから移す(書きかけを同期させない・友人の一覧に出さない)。同じ名前があれば末尾に4文字足す。
    check(): 止めるなら例外を投げる(まとめて実行の中止)。progress(済んだバイト, 全体のバイト)"""
    d = os.path.normpath(d)
    os.makedirs(out_dir, exist_ok=True)
    files = []
    for base, _dirs, fs in os.walk(d):
        for f in sorted(fs):
            p = os.path.join(base, f)
            try:
                files.append((p, os.path.getsize(p)))
            except OSError:
                pass
    total, done = sum(n for _p, n in files) or 1, 0
    tmp = os.path.join(os.path.dirname(d), ".deliver-%s.zip" % uuid.uuid4().hex[:8])
    try:
        with zipfile.ZipFile(tmp, "w", allowZip64=True) as z:
            top = os.path.basename(d)
            for p, n in files:
                if check:
                    check()
                arc = os.path.join(top, os.path.relpath(p, d))
                video = os.path.splitext(p)[1].lower() in VIDEO_EXT
                z.write(p, arc, compress_type=zipfile.ZIP_STORED if video else zipfile.ZIP_DEFLATED)
                done += n
                if progress:
                    progress(done, total)
        dest = os.path.join(out_dir, name + ".zip")
        if os.path.exists(dest):
            dest = os.path.join(out_dir, "%s-%s.zip" % (name, uuid.uuid4().hex[:4]))
        shutil.move(tmp, dest)
        return dest
    finally:
        if os.path.exists(tmp):
            try:
                os.remove(tmp)
            except OSError:
                pass


class Deliveries:
    """「友人へ届ける」の仕事。folder(): 見張るフォルダ(ホームの設定 intake.folder)。is_pack(dir): cut2resolve が作ったパックか"""

    def __init__(self, folder, is_pack, log=None, clock=time.time):
        self.folder, self.is_pack, self.log, self.clock = folder, is_pack, log or (lambda m: None), clock
        self.lock = threading.Lock()
        self.jobs = {}
        self.busy = threading.Lock()   # 同時に作るのは1本

    def start(self, d, title=""):
        """-> 仕事の状態。断るときは ValueError(画面にそのまま出す文)"""
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
        threading.Thread(target=self._run, args=(job, os.path.join(folder, OUT_DIR)), daemon=True, name="deliver").start()
        return dict(job)

    def _run(self, job, out_dir):
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
