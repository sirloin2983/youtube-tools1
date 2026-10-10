"""作業データのバックアップ(2026-10-03。docs/spec/data-location.md の「バックアップ」)。

作業データ(%LOCALAPPDATA%\\youtube-tools\\)はリポジトリの外にあり、git にも GitHub にも入らない。
2026-10-03 に Windows の入れ直しで失ったので、入口が動いている間に、決めた間隔で別のドライブのフォルダへ写す。

- 写す先: 設定(src/home/prefs.py の節 backup)の folder の下の `youtube-tools-data\\<ツールID>\\…`(作業データと同じ形。戻すときはそのまま写し戻す)
- 写すもの: 作り直せないもの(文字起こしと校正・カット・スタジオの data.json とマーク・採用の記録・設定・声の登録・パックの記録・案件)。
  写さないもの(SKIP_DIRS・SKIP_SUFFIX): キャッシュ・一時ファイル・ログ・モデル・実行ファイル・ブラウザのプロファイル・書き出した動画(取り直せる・大きい)。
  例外: `transcribe\\bin\\whisper.cpp-*`(作り直すのに Visual Studio が要るので写す。llama.cpp などダウンロードし直せるものは写さない)。
  評価用の音声 `transcribe\\eval-audio\\` は写す(SKIP に入れない。作り直せない)
- 写し方: 大きさか更新時刻が違うファイルだけ、一時的な名前へ写してから改名する。**写す先のファイルは消さない**
  (作業データで消したもの・壊れて空になったものに、バックアップを合わせて消さないため。古い分はたまる)。上書きされるファイルは、
  その日の最初の1回だけ `.prev` の名前で1つ前を残す(data.json などが壊れた形で上書きされても1つ前へ戻せる)
- シンボリックリンクはたどらない。写す先が作業データの中・作業データが写す先の中のときは断る
- 間隔(everyHours)が来たとき(変わっていなくても。検証の意味)のほかに、**変わったらすぐ写す**: 写す対象のファイルが前回の写し始めより新しく更新され、
  最後の変更から QUIET 秒(保存が続いている間は待つ)たっていれば、間隔を待たずに写す(CHECK_EVERY ごとに見る)
- 写し戻し: `restore_once`(コマンド `py -3.10 src/manage/keep/backup.py --restore <folder>`)。手順は docs/spec/data-location.md の「写し戻しの手順」
- 鍵(studio\\config.json の YouTube の API キー)も写る。写す先は自分の PC のドライブにする(共有のフォルダ・クラウドに置かない)
"""
import argparse
import datetime
import itertools
import os
import shutil
import sys
import threading
import time

_SRC = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))   # keep -> manage -> src
if _SRC not in sys.path:   # コマンドで単独に動かす(--restore)ときも ytt を読めるように(入口から読むときは入っている)
    sys.path.insert(0, _SRC)
from ytt import fsio, tools  # noqa: E402

STATE_FILE = "backup-state.json"
DEST_NAME = "youtube-tools-data"
FIRST_WAIT = 90            # 起動してから最初に見るまで(秒。ツールの起動・以前の場所からのコピーとぶつけない)
CHECK_EVERY = 180          # 時間が来たか・変わったかを見る間隔(秒)
QUIET = 120                # 最後の変更からこの秒数たってから、変わった分を写す(校正の保存が続いている間は待つ)
SKIP_DIRS = {"cache", "work", "logs", "models", "bin", "browser-profile", "exports", ".runtime", "__pycache__"}
SKIP_SUFFIX = (".log", ".tmp", ".lock")
SKIP_MARK = ".part-"       # datadir.prepare・fsio の途中のファイル
KEEP_BIN_PREFIX = "whisper.cpp-"   # transcribe\\bin の下で、これで始まるフォルダだけは写す(作り直しに Visual Studio が要る)
NOISY = (STATE_FILE, ".running.json")   # 写す対象だが「変わった」の判定には使わない(写すたびに・ジョブのたびに書き換わる)
PREV_SUFFIX = ".prev"
MAX_ERRORS = 20
STATE_MAX = 64 * 1024     # backup-state.json を読む上限(これより大きければ読めない扱い = 記録なし)
STATE_LABELS = {"off": "オフ", "idle": "動いています", "running": "写しています…", "error": "止まっています"}


def _norm(p):
    return os.path.normcase(os.path.abspath(p))


def _overlaps(child, parent):
    """child が parent の中か(同じも含む)。重なりを断る検査なので、見かけのパス(abspath)とリンクを解いたパス(fsio.is_inside)の
    どちらで見ても中なら真(片方だけにすると、ジャンクション越しに重なる指定・見かけだけ重なる指定のどちらかを通してしまう)。
    ネットワーク上のパスは is_inside が調べない(False)ので、見かけのパスだけで決まる"""
    c, p = _norm(child), _norm(parent)
    return c == p or c.startswith(p.rstrip("\\/") + os.sep) or fsio.is_inside(child, parent)


def skip(name, is_dir):
    low = name.lower()
    if SKIP_MARK in low:
        return True
    return low in SKIP_DIRS if is_dir else low.endswith(SKIP_SUFFIX)


def _scan(root, enter, keep):
    """root の下のファイルを順に返す: (root からの相対パス, 大きさ, 更新時刻)。plan(写す側)と _walk_backup(写し戻す側)の歩き方。
    scandir を名前順・シンボリックリンクはたどらない・読めないものは飛ばす(安全の決まりはここ 1 か所)。
    enter(相対パス, 名前, 親の入り方) -> そのフォルダの入り方(None = 入らない)。keep(名前, 入り方) -> そのファイルを返すか。
    os.walk にしない(Windows では DirEntry がフォルダを読んだときの stat を持っているので、ファイルごとの stat が増えない)"""
    stack = [("", "")]   # (相対パス, 入り方)
    while stack:
        rel, mode = stack.pop()
        try:
            entries = sorted(os.scandir(os.path.join(root, rel)), key=lambda e: e.name)
        except OSError:
            continue
        for e in entries:
            try:
                if e.is_symlink():
                    continue
                r = os.path.join(rel, e.name)
                if e.is_dir(follow_symlinks=False):
                    sub = enter(r, e.name, mode)
                    if sub is not None:
                        stack.append((r, sub))
                elif e.is_file(follow_symlinks=False) and keep(e.name, mode):
                    st = e.stat(follow_symlinks=False)
                    yield r, st.st_size, st.st_mtime
            except OSError:
                continue


def _plan_enter(r, name, mode):
    """plan の入り方: "" = ふつう / "bin" = whisper.cpp- のフォルダだけ / "keep" = フォルダ名で除かない / None = 入らない"""
    low = name.lower()
    if mode == "bin":
        return "keep" if low.startswith(KEEP_BIN_PREFIX) else None
    if mode == "keep":
        return "keep"
    if low == "bin" and os.path.dirname(r).lower() == "transcribe":
        return "bin"
    if _excite_chat(r):
        return None   # 配信中の検出の生のチャット(他の視聴者の発言。64MB まで)は写さない(写すと、配信のあとワーカーが消しても写しに残る)
    return None if skip(name, True) else ""


def plan(source):
    """写す候補を順に返す: (作業データからの相対パス, 大きさ, 更新時刻)。シンボリックリンクはたどらない。
    transcribe\\bin の下は whisper.cpp- で始まるフォルダだけ入り、その中はフォルダ名で除かない(build の bin\\Release などの名前でも写す)"""
    return _scan(source, _plan_enter, lambda name, mode: mode != "bin" and not skip(name, False))


CASES_DIR = "cases"        # 写す先の下の、案件の 作業用 を置くフォルダ(<写す先>/youtube-tools-data/cases/<題名>/作業用/…)
CASE_WORK = "作業用"
CASE_STUDIO_ID = ".studio-id"


def _cases_enter(r, name, mode):
    """案件の根(outDir)の入り方: "" = outDir 直下 / "case" = 題名のフォルダ / "work" = 作業用(と runs)。動画・パック・その他は入らない"""
    if mode == "":
        return "case"
    if mode == "case":
        return "work" if name == CASE_WORK else None
    return "work" if name.lower() == "runs" else None


def plan_cases(out_dir):
    """案件の根 <outDir>/<題名>/作業用/ の *.json(runs の結果の束・.clip.json・.edit.json・鍵を含む)と .studio-id だけを順に返す: (outDir からの相対パス, 大きさ, 更新時刻)。
    動画・_edit.mp4・*_pack は写さない。outDir が無い・未設定なら何も返さない"""
    if not out_dir or not os.path.isdir(out_dir):
        return iter(())
    return _scan(out_dir, _cases_enter, lambda name, mode: mode == "work" and not skip(name, False) and (name.lower().endswith(".json") or name == CASE_STUDIO_ID))


def _excite_chat(rel):
    """<ツール>/live/excite/chat(配信中の検出の生のチャット)か"""
    return rel.replace(os.sep, "/").lower().endswith("live/excite/chat")


def _excite_noisy(rel):
    """<ツール>/live/excite/ の下(worker.json は 30 秒ごと・peaks.json/state.json/series.jsonl は 1 分ごとに書き換わる)。写すが「変わった」の判定には使わない"""
    return "/live/excite/" in rel.replace(os.sep, "/").lower()


def latest_change(source, out_dir=None):
    """写す対象のファイルの、いちばん新しい更新時刻(無ければ None)。NOISY の名前は数えない。out_dir = 案件の根(runs が変わったら写す)"""
    newest = None
    for rel, _size, mtime in itertools.chain(plan(source), plan_cases(out_dir)):
        if os.path.basename(rel).lower() in NOISY or _excite_noisy(rel):
            continue
        if newest is None or mtime > newest:
            newest = mtime
    return newest


def same(dst, size, mtime):
    try:
        st = os.stat(dst)
    except OSError:
        return False
    return st.st_size == size and abs(st.st_mtime - mtime) < 2.0   # FAT・exFAT の更新時刻は 2 秒きざみ


def copy_one(src, dst, day=None):
    """一時的な名前へ写してから改名。すでにあるファイルは、その日(day = YYYY-MM-DD)の最初の1回だけ `.prev` に1つ前を残す。
    day が None なら 1つ前は残さない(写し戻し)"""
    os.makedirs(os.path.dirname(dst), exist_ok=True)
    tmp = "%s%s%d" % (dst, SKIP_MARK, os.getpid())
    try:
        shutil.copy2(src, tmp)
        if day is not None and os.path.exists(dst):
            prev = dst + PREV_SUFFIX
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
        fsio.unlink_quiet(tmp)   # 写しきれなかった一時ファイル(置き換えたあとは無い)


def run_once(source, folder, day=None, stop=None, on_file=None, out_dir=None):
    """作業データ source を folder\\youtube-tools-data へ写す。out_dir(案件の根)があれば、その作業用の json を cases の下へも写す。-> {"copied", "same", "bytes", "errors": [..], "dest"}
    断るとき(場所が正しくない・ドライブが無い)は ValueError"""
    if not source or not os.path.isdir(source):
        raise ValueError("作業データのフォルダが見つかりません")
    if not folder or not os.path.isabs(folder):
        raise ValueError("バックアップ先のフォルダが決まっていません")
    drive = os.path.splitdrive(os.path.abspath(folder))[0]
    if drive and not os.path.isdir(drive + os.sep):
        raise ValueError("バックアップ先のドライブ(%s)が見つかりません" % drive)
    dest = os.path.join(os.path.abspath(folder), DEST_NAME)
    if _overlaps(dest, source) or _overlaps(source, dest) or _overlaps(folder, source):
        raise ValueError("バックアップ先を作業データの中(または外側)にはできません。別のドライブのフォルダを指定してください")
    os.makedirs(dest, exist_ok=True)
    day = day or datetime.date.today().isoformat()
    out = {"copied": 0, "same": 0, "bytes": 0, "errors": [], "dest": dest}
    with_cases = bool(out_dir) and os.path.isdir(out_dir) and not _overlaps(out_dir, dest) and not _overlaps(dest, out_dir)
    items = itertools.chain(((rel, source, rel, size, mtime) for rel, size, mtime in plan(source)),
                            ((os.path.join(CASES_DIR, rel), out_dir, rel, size, mtime) for rel, size, mtime in plan_cases(out_dir)) if with_cases else ())
    for rel, root, src_rel, size, mtime in items:
        if stop is not None and stop():
            break
        dst = os.path.join(dest, rel)
        if same(dst, size, mtime):
            out["same"] += 1
            continue
        try:
            copy_one(os.path.join(root, src_rel), dst, day)
            out["copied"] += 1
            out["bytes"] += size
            if on_file:
                on_file(rel)
        except OSError as e:   # 使用中・読めないファイルは飛ばして続ける(次の回でもう一度)
            if len(out["errors"]) < MAX_ERRORS:
                out["errors"].append("%s: %s" % (rel, tools.why(e)))
    return out


class Backup:
    def __init__(self, prefs, source, data_dir, log=None, clock=None, first_wait=FIRST_WAIT, check_every=CHECK_EVERY, defaults=None, out_dir=None):
        """prefs: src/home/prefs.py の Prefs(節 backup)。defaults: 設定が読めないときに使う節の既定(入口が prefs.DEFAULTS["backup"] を渡す。
        prefs を読み込まない = app の部品に依存しない。None = 空 = オフ扱い)。source: 作業データの親フォルダ(datadir.data_root()。None = inplace なので写さない)。
        data_dir: ホームの作業データ(app。最後に写した時刻の記録を置く)。
        out_dir: 案件の根(スタジオの書き出し先)。文字列か、呼ぶたびに返す関数(設定で変わるので)。None・無いフォルダ = 案件の 作業用 は写さない"""
        self.prefs, self.source, self.data_dir = prefs, source, data_dir
        self.defaults = defaults
        self.out_dir = out_dir
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
        return fsio.read_json_or(self.state_path, {}, max_bytes=STATE_MAX, kind=dict)

    def _save_state(self):
        try:
            fsio.write_json(self.state_path, self.last, indent=None)
        except OSError as e:
            self.log("バックアップ: 記録を書けませんでした(%s)" % (tools.why(e)))

    def _out_dir(self):
        try:
            v = self.out_dir() if callable(self.out_dir) else self.out_dir
        except OSError:
            return None
        return v if isinstance(v, str) and os.path.isabs(v) else None

    def _cfg(self):
        try:
            return dict(self.prefs.get(["backup"])["backup"])
        except (OSError, ValueError, KeyError):
            return dict(self.defaults or {})

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
                # 画面には「何が起きたか + どうするか」だけ。例外の名前・原文はログへ(UI の見直し M9)
                self.state, self.message = "error", "バックアップが途中で止まりました。写す先のフォルダを確かめてください。次の回でもう一度試します。続くときは、詳しくの「ログ」を見てください"
                self.log("バックアップ: 内部エラー: %s %s" % (e.__class__.__name__, str(e)[:200]))
            self.wake.wait(self.check_every)

    def changed(self, cfg):
        """前回の写し始めより新しく更新された対象があり、最後の変更から QUIET 秒たっているか(まだ写したことが無いときは due が決める)"""
        base = self.last.get("started", self.last.get("ok"))
        if not isinstance(base, (int, float)) or self.last.get("folder") != cfg.get("folder"):
            return False
        newest = latest_change(self.source, self._out_dir())
        return newest is not None and newest > base and self.clock() - newest >= QUIET

    def due(self, cfg):
        ok = self.last.get("ok")
        return not isinstance(ok, (int, float)) or self.clock() - ok >= float(cfg.get("everyHours") or 1) * 3600 \
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
        if not force and not self.due(cfg) and not self.changed(cfg):
            if self.state != "error":
                self.state = "idle"
            return None
        with self.lock:
            self.state, self.message = "running", ""
            t0 = self.clock()
            try:
                r = run_once(self.source, cfg.get("folder") or "", stop=lambda: self.closed, out_dir=self._out_dir())
            except ValueError as e:
                self.state, self.message = "error", str(e)
                self.last = dict(self.last, tried=self.clock(), error=str(e))
                self._save_state()
                self.log("バックアップ: " + str(e))
                return None
            now = self.clock()
            # started: 次の「変わった」の基準。写せなかったファイルがあれば進めない(静かになってから、もう一度写す)
            started = t0 if not r["errors"] else self.last.get("started", 0.0)
            self.last = {"ok": now, "tried": now, "started": started, "folder": cfg.get("folder"), "dest": r["dest"], "copied": r["copied"], "same": r["same"],
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


def _walk_backup(root):
    """バックアップ側の (相対パス, 大きさ, 更新時刻)。`.prev`(1つ前の控え)と途中のファイルは数えない。シンボリックリンクはたどらない"""
    return _scan(root, lambda r, name, mode: "", lambda name, mode: not name.lower().endswith(PREV_SUFFIX) and SKIP_MARK not in name.lower())


def restore_once(folder, target, stop=None, dry_run=False):
    """`<folder>\\youtube-tools-data\\` から target(作業データ)へ、無い・違うファイルを写し戻す。
    -> {"copied", "same", "newer", "bytes", "errors": [..], "source"}。newer = target のほうが新しいので上書きしなかった数。
    `.prev` は写さない・シンボリックリンクはたどらない・target のファイルは消さない。dry_run なら写さずに数だけ(copied = 写すことになる数)。
    場所が正しくないときは ValueError"""
    if not folder or not os.path.isabs(folder):
        raise ValueError("バックアップのフォルダを絶対パスで指定してください")
    src_root = os.path.join(os.path.abspath(folder), DEST_NAME)
    if not os.path.isdir(src_root):
        raise ValueError("バックアップが見つかりません(%s)" % src_root)
    if not target:
        raise ValueError("写し戻す先(作業データ)が決まっていません")
    target = os.path.abspath(target)
    if _overlaps(src_root, target) or _overlaps(target, src_root):
        raise ValueError("バックアップと写し戻す先が重なっています")
    out = {"copied": 0, "same": 0, "newer": 0, "bytes": 0, "errors": [], "source": src_root}
    for rel, size, mtime in _walk_backup(src_root):
        if stop is not None and stop():
            break
        dst = os.path.join(target, rel)
        if same(dst, size, mtime):
            out["same"] += 1
            continue
        try:
            if os.path.exists(dst) and os.stat(dst).st_mtime > mtime + 2.0:   # target のほうが新しい(バックアップのあとで直した)
                out["newer"] += 1
                continue
            if not dry_run:
                copy_one(os.path.join(src_root, rel), dst, None)
            out["copied"] += 1
            out["bytes"] += size
        except OSError as e:
            if len(out["errors"]) < MAX_ERRORS:
                out["errors"].append("%s: %s" % (rel, tools.why(e)))
    return out


def main(argv=None):
    ap = argparse.ArgumentParser(description="作業データのバックアップの写し戻し(入口を止めてから。docs/spec/data-location.md)")
    ap.add_argument("--restore", metavar="FOLDER", required=True, help="バックアップ先のフォルダ(その下の youtube-tools-data から写し戻す)")
    ap.add_argument("--target", metavar="DIR", help="写し戻す先(既定: 作業データの本物の場所)")
    ap.add_argument("--yes", action="store_true", help="確認を聞かない")
    a = ap.parse_args(argv)
    target = a.target
    if not target:
        from ytt import datadir
        target = datadir.data_root()
    try:
        r = restore_once(a.restore, target, dry_run=True)
    except ValueError as e:
        print("できません: %s" % e)
        return 2
    print("写し戻し元: %s\n写し戻す先: %s" % (r["source"], os.path.abspath(target)))
    print("写す %d 個(%.1f MB)・同じ %d 個・写す先のほうが新しいので上書きしない %d 個" % (r["copied"], r["bytes"] / 1048576.0, r["same"], r["newer"]))
    for m in r["errors"]:
        print("  読めない: " + m)
    if not r["copied"]:
        print("写すものはありません。")
        return 0
    if not a.yes and input("入口を止めてありますか。写し戻しますか? [y/N] ").strip().lower() not in ("y", "yes"):
        print("やめました。")
        return 1
    r = restore_once(a.restore, target)
    print("写し戻しました: %d 個(%.1f MB)・上書きしなかった %d 個・失敗 %d 個" % (r["copied"], r["bytes"] / 1048576.0, r["newer"], len(r["errors"])))
    for m in r["errors"]:
        print("  失敗: " + m)
    return 0 if not r["errors"] else 3


if __name__ == "__main__":
    sys.exit(main())
