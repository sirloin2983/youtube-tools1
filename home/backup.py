"""作業データのバックアップ(2026-10-03。docs/spec/data-location.md の「バックアップ」)。

作業データ(%LOCALAPPDATA%\\youtube-tools\\)はリポジトリの外にあり、git にも GitHub にも入らない。
2026-10-03 に Windows の入れ直しで失ったので、入口が動いている間に、決めた間隔で別のドライブのフォルダへ写す。

- 写す先: 設定(home/prefs.py の節 backup)の folder の下の `youtube-tools-data\\<ツールID>\\…`(作業データと同じ形。戻すときはそのまま写し戻す)
- 写すもの: 作り直せないもの(文字起こしと校正・カット・スタジオの data.json とマーク・採用の記録・設定・声の登録・パックの記録・案件)。
  写さないもの(SKIP_DIRS・SKIP_SUFFIX): キャッシュ・一時ファイル・ログ・モデル・実行ファイル・ブラウザのプロファイル・書き出した動画(取り直せる・大きい)
- 写し方: 大きさか更新時刻が違うファイルだけ、一時的な名前へ写してから改名する。**写す先のファイルは消さない**
  (作業データで消したもの・壊れて空になったものに、バックアップを合わせて消さないため。古い分はたまる)。上書きされるファイルは、
  その日の最初の1回だけ `.prev` の名前で1つ前を残す(data.json などが壊れた形で上書きされても1つ前へ戻せる)
- シンボリックリンクはたどらない。写す先が作業データの中・作業データが写す先の中のときは断る
- 鍵(studio\\config.json の YouTube の API キー)も写る。写す先は自分の PC のドライブにする(共有のフォルダ・クラウドに置かない)
"""
import datetime
import json
import os
import shutil
import threading
import time

STATE_FILE = "backup-state.json"
DEST_NAME = "youtube-tools-data"
FIRST_WAIT = 90            # 起動してから最初に見るまで(秒。ツールの起動・以前の場所からのコピーとぶつけない)
CHECK_EVERY = 600          # 時間が来たかを見る間隔(秒)
SKIP_DIRS = {"cache", "work", "logs", "models", "bin", "browser-profile", "exports", ".runtime", "__pycache__"}
SKIP_SUFFIX = (".log", ".tmp", ".lock")
SKIP_MARK = ".part-"       # datadir.prepare・fsio の途中のファイル
MAX_ERRORS = 20
STATE_LABELS = {"off": "オフ", "idle": "動いています", "running": "写しています…", "error": "止まっています"}


def _norm(p):
    return os.path.normcase(os.path.abspath(p))


def _inside(child, parent):
    c, p = _norm(child), _norm(parent)
    return c == p or c.startswith(p.rstrip("\\/") + os.sep)


def skip(name, is_dir):
    low = name.lower()
    if SKIP_MARK in low:
        return True
    return low in SKIP_DIRS if is_dir else low.endswith(SKIP_SUFFIX)


def plan(source):
    """写す候補を順に返す: (作業データからの相対パス, 大きさ, 更新時刻)。シンボリックリンクはたどらない"""
    stack = [""]
    while stack:
        rel = stack.pop()
        try:
            entries = sorted(os.scandir(os.path.join(source, rel)), key=lambda e: e.name)
        except OSError:
            continue
        for e in entries:
            try:
                if e.is_symlink():
                    continue
                r = os.path.join(rel, e.name)
                if e.is_dir(follow_symlinks=False):
                    if not skip(e.name, True):
                        stack.append(r)
                elif e.is_file(follow_symlinks=False) and not skip(e.name, False):
                    st = e.stat(follow_symlinks=False)
                    yield r, st.st_size, st.st_mtime
            except OSError:
                continue


def same(dst, size, mtime):
    try:
        st = os.stat(dst)
    except OSError:
        return False
    return st.st_size == size and abs(st.st_mtime - mtime) < 2.0   # FAT・exFAT の更新時刻は 2 秒きざみ


def copy_one(src, dst, day):
    """一時的な名前へ写してから改名。すでにあるファイルは、その日の最初の1回だけ `.prev` に1つ前を残す"""
    os.makedirs(os.path.dirname(dst), exist_ok=True)
    tmp = "%s%s%d" % (dst, SKIP_MARK, os.getpid())
    try:
        shutil.copy2(src, tmp)
        if os.path.exists(dst):
            prev = dst + ".prev"
            try:
                fresh = os.path.exists(prev) and datetime.date.fromtimestamp(os.stat(prev).st_mtime).isoformat() == day
            except OSError:
                fresh = False
            if not fresh:
                try:
                    if os.path.exists(prev):
                        os.remove(prev)
                    os.replace(dst, prev)
                    os.utime(prev, None)   # 「いつ1つ前にしたか」を更新時刻に入れる(Windows の作成時刻は改名で変わらないので使えない)
                except OSError:
                    pass   # 1つ前を残せなくても、新しい分は写す
        os.replace(tmp, dst)
    finally:
        if os.path.exists(tmp):
            try:
                os.remove(tmp)
            except OSError:
                pass


def run_once(source, folder, day=None, stop=None, on_file=None):
    """作業データ source を folder\\youtube-tools-data へ写す。-> {"copied", "same", "bytes", "errors": [..], "dest"}
    断るとき(場所が正しくない・ドライブが無い)は ValueError"""
    if not source or not os.path.isdir(source):
        raise ValueError("作業データのフォルダが見つかりません")
    if not folder or not os.path.isabs(folder):
        raise ValueError("バックアップ先のフォルダが決まっていません")
    drive = os.path.splitdrive(os.path.abspath(folder))[0]
    if drive and not os.path.isdir(drive + os.sep):
        raise ValueError("バックアップ先のドライブ(%s)が見つかりません" % drive)
    dest = os.path.join(os.path.abspath(folder), DEST_NAME)
    if _inside(dest, source) or _inside(source, dest) or _inside(folder, source):
        raise ValueError("バックアップ先を作業データの中(または外側)にはできません。別のドライブのフォルダを指定してください")
    os.makedirs(dest, exist_ok=True)
    day = day or datetime.date.today().isoformat()
    out = {"copied": 0, "same": 0, "bytes": 0, "errors": [], "dest": dest}
    for rel, size, mtime in plan(source):
        if stop is not None and stop():
            break
        dst = os.path.join(dest, rel)
        if same(dst, size, mtime):
            out["same"] += 1
            continue
        try:
            copy_one(os.path.join(source, rel), dst, day)
            out["copied"] += 1
            out["bytes"] += size
            if on_file:
                on_file(rel)
        except OSError as e:   # 使用中・読めないファイルは飛ばして続ける(次の回でもう一度)
            if len(out["errors"]) < MAX_ERRORS:
                out["errors"].append("%s: %s" % (rel, e.strerror or e.__class__.__name__))
    return out


class Backup:
    def __init__(self, prefs, source, data_dir, log=None, clock=None, first_wait=FIRST_WAIT, check_every=CHECK_EVERY):
        """prefs: home/prefs.py の Prefs(節 backup)。source: 作業データの親フォルダ(datadir.data_root()。None = inplace なので写さない)。
        data_dir: ホームの作業データ(app。最後に写した時刻の記録を置く)"""
        self.prefs, self.source, self.data_dir = prefs, source, data_dir
        self.log = log or (lambda msg: None)
        self.clock = clock or time.time
        self.first_wait, self.check_every = first_wait, check_every
        self.state_path = os.path.join(data_dir, STATE_FILE)
        self.lock = threading.Lock()       # 写す処理を1つずつ
        self.wake = threading.Event()
        self.force = False                 # 「今すぐ」
        self.closed = False
        self.thread = None
        self.state = "off"
        self.message = ""
        self.last = self._load_state()

    def _load_state(self):
        try:
            with open(self.state_path, "rb") as f:
                d = json.loads(f.read(64 * 1024).decode("utf-8-sig"))
        except (OSError, ValueError):
            d = None
        return d if isinstance(d, dict) else {}

    def _save_state(self):
        try:
            os.makedirs(self.data_dir, exist_ok=True)
            tmp = self.state_path + ".tmp"
            with open(tmp, "wb") as f:
                f.write(json.dumps(self.last, ensure_ascii=False).encode("utf-8"))
            os.replace(tmp, self.state_path)
        except OSError as e:
            self.log("バックアップ: 記録を書けませんでした(%s)" % (e.strerror or e.__class__.__name__))

    def _cfg(self):
        import prefs as prefs_mod
        try:
            return dict(self.prefs.get(["backup"])["backup"])
        except (OSError, ValueError, KeyError):
            return dict(prefs_mod.DEFAULTS["backup"])

    def start(self):
        if self.thread is None:
            self.thread = threading.Thread(target=self._loop, name="backup", daemon=True)
            self.thread.start()

    def close(self):
        self.closed = True
        self.wake.set()

    def run_now(self):
        self.force = True
        self.wake.set()

    def _loop(self):
        self.wake.wait(self.first_wait)
        while not self.closed:
            self.wake.clear()
            try:
                self.tick()
            except Exception as e:   # 想定外でも止めない(次の回でやり直す)
                self.state, self.message = "error", "内部エラー: %s %s" % (e.__class__.__name__, str(e)[:200])
                self.log("バックアップ: " + self.message)
            self.wake.wait(self.check_every)

    def due(self, cfg):
        ok = self.last.get("ok")
        return not isinstance(ok, (int, float)) or self.clock() - ok >= float(cfg.get("everyHours") or 24) * 3600 \
            or self.last.get("folder") != cfg.get("folder")

    def tick(self):
        """時間が来ていれば(または「今すぐ」なら)写す"""
        cfg = self._cfg()
        force, self.force = self.force, False
        if self.source is None:
            self.state, self.message = "off", "作業データがツールのフォルダの中にある形(inplace)では、バックアップしません"
            return None
        if not cfg.get("enabled"):
            self.state, self.message = "off", "" if cfg.get("folder") else "バックアップ先のフォルダを決めて、オンにしてください"
            return None
        if not force and not self.due(cfg):
            if self.state != "error":
                self.state = "idle"
            return None
        with self.lock:
            self.state, self.message = "running", ""
            t0 = self.clock()
            try:
                r = run_once(self.source, cfg.get("folder") or "", stop=lambda: self.closed)
            except ValueError as e:
                self.state, self.message = "error", str(e)
                self.last = dict(self.last, tried=self.clock(), error=str(e))
                self._save_state()
                self.log("バックアップ: " + str(e))
                return None
            now = self.clock()
            self.last = {"ok": now, "tried": now, "folder": cfg.get("folder"), "dest": r["dest"], "copied": r["copied"], "same": r["same"],
                         "bytes": r["bytes"], "errors": r["errors"], "seconds": round(now - t0, 1)}
            self._save_state()
            self.state = "idle"
            self.message = "写せなかったファイルが %d 個あります(使用中など。次の回でもう一度写します)" % len(r["errors"]) if r["errors"] else ""
            self.log("バックアップ: %d 個を写しました(変わりなし %d 個・%.1f MB・%s)%s" % (
                r["copied"], r["same"], r["bytes"] / 1048576.0, r["dest"], " 写せなかった %d 個" % len(r["errors"]) if r["errors"] else ""))
            return r

    def snapshot(self):
        cfg = self._cfg()
        ok = self.last.get("ok")
        return dict(cfg, state=self.state, stateLabel=STATE_LABELS[self.state], message=self.message, source=self.source,
                    lastOk=int(ok * 1000) if isinstance(ok, (int, float)) else None, dest=self.last.get("dest"),
                    copied=self.last.get("copied"), same=self.last.get("same"), bytes=self.last.get("bytes"),
                    errors=list(self.last.get("errors") or [])[:MAX_ERRORS])
