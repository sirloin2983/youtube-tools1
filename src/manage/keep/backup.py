"""作業データのバックアップ(notes:docs/spec/data.md の「バックアップ」)。

作業データ(%LOCALAPPDATA%\\youtube-tools\\)はリポジトリの外にあり、git にも GitHub にも入らない。
Windows の入れ直しなどで失わないように、入口が動いている間に、決めた間隔で別のドライブのフォルダへ写す。

- 写す先: 設定(src/app/prefs.py の節 backup)の folder の下の `youtube-tools-data\\<ツールID>\\…`(作業データと同じ形。戻すときはそのまま写し戻す)
- 守る物(ユーザー決定。decisions 3-48): 作業データそのものではなく**学習データ・ツール・関連資料**。だから頻繁でなくてよい = 間隔(everyHours。既定 24 時間)と「今すぐ」だけ
- 写すもの: 作り直せないもの(文字起こしと校正・カット・スタジオの data.json とマーク・採用の記録・設定・声の登録・パックの記録・案件)と、
  **評価用データ・学習用データの動画**(settings.evalDirs のフォルダと、その隣の 学習用データ。YouTube の元は消える・非公開になりうる・正解の時刻はその動画に
  合わせてある。写す先の media\\<ドライブ>\\<パス> に元と同じ形で。動画は変わらないので写すのは最初の 1 回。スイッチ COPY_MEDIA)。
  写さないもの(SKIP_DIRS・SKIP_SUFFIX・SKIP_TOP): キャッシュ・一時ファイル・ログ・分析(analytics)・モデル・実行ファイル・ブラウザのプロファイル・書き出した動画(取り直せる・大きい)。
  例外: `transcribe\\bin\\whisper.cpp-*`(作り直すのに Visual Studio が要るので写す。llama.cpp などダウンロードし直せるものは写さない)。
  評価用の音声 `transcribe\\eval-audio\\` は写さない(元の配信の音声から作り直せるため)
- 写し方: 大きさか更新時刻が違うファイルだけ、一時的な名前へ写してから改名する。上書きされるファイルは、
  その日の最初の1回だけ `.prev` の名前で1つ前を残す(data.json などが壊れた形で上書きされても1つ前へ戻せる)
- 古い分を消す(prune。10-29 ユーザー「最新のやつをとったら過去のやつは消していい」。スイッチ PRUNE = False で前の形 = 消さない):
  **完全に写せた回(complete = 止めていない・写せなかった物も読めなかった物も無い)のあとだけ**、写す先から
  (1) 元(作業データ・案件の根・前の書き出し先)にもう無いファイルの写し (2) 古い `.prev`(PREV_KEEP_DAYS より前・元の写しを消した物)を消す。
  評価用・学習用の動画(media/)は元の動画がある物は残す(評価用のフォルダの設定から外れても)・元が無い物は消す・元のドライブが無ければ消さない。
  その回で歩かなかった所(案件の根が無い回の cases/ など)は触らない。消す数が写しの PRUNE_MAX_SHARE を超えるときは消さない(作業データ側の事故で
  バックアップまで消えないように)。消した数と大きさは backup-state.json の pruned と入口のログに
- シンボリックリンクはたどらない。写す先が作業データの中・作業データが写す先の中のときは断る
- 写す時: 間隔(everyHours)が来たとき(変わっていなくても。検証の意味)と「今すぐ」だけ(変わったらすぐ写す、ことはしない)。
  **読めなかったフォルダ・調べられなかったファイル・写せなかったファイルが 1 つでもあれば「完全に写せた」にしない**(部品 M3): 読める物は写し続け、
  完全に写せた時刻 ok は進めず、RETRY_SEC のあとでもう一度試す
- 写し戻し: `restore_once`(コマンド `py -3.12 src/manage/keep/backup.py --restore <folder>`)。手順は notes:docs/spec/data.md の「写し戻しの手順」。
  写すときと同じ決まりを通す(写さない場所の物 = 受付の写しなどは戻さない)。
  案件の 作業用 の写し(cases/)は作業データの根へは戻さず、案件の根(--out-dir。既定はスタジオの設定の書き出し先)へ戻す。既にあるファイルは上書きしない。
  評価用・学習用の動画(media/)は元の場所へ戻す(既にあるファイルは上書きしない・そのドライブが無ければ戻さない)
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
from flow import placement  # noqa: E402   案件の置き場所の名前(依頼・runs)を元から読む(④ は ② を読める)
from ytt import docloc, fsio, names, schemas, settings, tools  # noqa: E402

STATE_FILE = "backup-state.json"
DEST_NAME = "youtube-tools-data"
FIRST_WAIT = 90            # 起動してから最初に見るまで(秒。ツールの起動とぶつけない)
CHECK_EVERY = 180          # 時間が来たかを見る間隔(秒)
RETRY_SEC = 3600           # 完全に写せなかった(読めないフォルダ・写せないファイルがあった)ときに、もう一度試すまで(秒)
SKIP_DIRS = {"cache", "work", "logs", "models", "bin", "browser-profile", "exports", ".runtime", "__pycache__", "intake",   # intake = app/intake の友人の依頼の動画の写し(元は友人の Dropbox)
             "eval-audio",   # 評価用の音声(元の配信の音声から作り直せる)
             "friend-build-cache", ".tmp"}   # friend-build-cache = dev/build_friend_zip.py がダウンロードした zip(取り直せる)・.tmp = 一時ファイル
SKIP_TOP = {"analytics"}   # 作業データの直下で写さないフォルダ(分析の記録 = 守る物の外。ユーザー「ログと分析は外す」)
SKIP_SUFFIX = (".log", ".tmp", ".lock")
SKIP_MARK = ".part-"       # 写し・fsio の途中のファイル
KEEP_BIN_PREFIX = "whisper.cpp-"   # transcribe\\bin の下で、これで始まるフォルダだけは写す(作り直しに Visual Studio が要る)
COPY_MEDIA = True          # 評価用・学習用の動画を写す(スイッチ。False = 作業データと案件の 作業用 だけ)
MEDIA_DIR = "media"        # 写す先の下の、評価用・学習用の動画を置くフォルダ(<写す先>/youtube-tools-data/media/<ドライブ>/<パス>)
LEARN_NAME = "学習用データ"   # 評価用のフォルダの隣の学習用のフォルダ
PREV_SUFFIX = ".prev"
PRUNE = True              # 完全に写せた回のあと、古い分(元に無い物の写し・古い .prev)を消す(10-29。False = 前の形 = 写す先は消さない)
PREV_KEEP_DAYS = 3        # .prev(1 つ前の写し)を残す日数(物の終わりの日数 3 日と同じ。新しい .prev は壊れた上書きから戻すために残す)
PRUNE_MAX_SHARE = 0.5     # 写しのこの割合より多く消すことになったら、消さない(元が丸ごと見えない・空になった事故の守り)
MAX_ERRORS = 20
STATE_MAX = 64 * 1024     # backup-state.json を読む上限(これより大きければ読めない扱い = 記録なし)
STATE_LABELS = {"off": "オフ", "idle": "動いています", "running": "写しています…", "error": "止まっています"}


def _overlaps(child, parent):
    """child が parent の中か(同じも含む)。重なりを断る検査なので、見かけのパス(abspath)とリンクを解いたパス(fsio.is_inside)の
    どちらで見ても中なら真(片方だけにすると、ジャンクション越しに重なる指定・見かけだけ重なる指定のどちらかを通してしまう)。
    ネットワーク上のパスは is_inside が調べない(False)ので、見かけのパスだけで決まる"""
    c, p = fsio.norm_path(child), fsio.norm_path(parent)
    return c == p or c.startswith(p.rstrip("\\/") + os.sep) or fsio.is_inside(child, parent)


def skip(name, is_dir):
    low = name.lower()
    if SKIP_MARK in low:
        return True
    return low in SKIP_DIRS if is_dir else low.endswith(SKIP_SUFFIX)


def _scan(root, enter, keep, errors=None):
    """root の下のファイルを順に返す: (root からの相対パス, 大きさ, 更新時刻)。plan(写す側)と _walk_backup(写し戻す側)の歩き方。
    scandir を名前順・シンボリックリンクはたどらない・読めないものは飛ばす(安全の決まりはここ 1 か所)。
    enter(相対パス, 名前, 親の入り方) -> そのフォルダの入り方(None = 入らない)。keep(名前, 入り方) -> そのファイルを返すか。
    errors(リスト)を渡すと、飛ばしたものを足す(「読めないフォルダ: …」「調べられないファイル: …」。部品 M3 = 読めない物があれば完全に写せたにしない)。
    root そのものが無いのは失敗にしない(案件の根・評価用のフォルダがまだ無い)。
    os.walk にしない(Windows では DirEntry がフォルダを読んだときの stat を持っているので、ファイルごとの stat が増えない)"""
    def fail(what, rel, e):
        if errors is not None:
            errors.append("%s: %s: %s" % (what, rel or ".", tools.why(e)))
    stack = [("", "")]   # (相対パス, 入り方)
    while stack:
        rel, mode = stack.pop()
        try:
            entries = sorted(os.scandir(os.path.join(root, rel)), key=lambda e: e.name)
        except FileNotFoundError:
            if rel:   # 歩いている間に消えたフォルダ(写す物も無い)
                continue
            return
        except OSError as e:
            fail("読めないフォルダ", rel, e)
            continue
        for e in entries:
            r = os.path.join(rel, e.name)
            try:
                if e.is_symlink():
                    continue
                if e.is_dir(follow_symlinks=False):
                    sub = enter(r, e.name, mode)
                    if sub is not None:
                        stack.append((r, sub))
                elif e.is_file(follow_symlinks=False) and keep(e.name, mode):
                    st = e.stat(follow_symlinks=False)
                    yield r, st.st_size, st.st_mtime
            except FileNotFoundError:
                continue   # 歩いている間に消えた(写す物が無い = 失敗ではない)
            except OSError as ex:
                fail("調べられないファイル", r, ex)


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
    if not os.path.dirname(r) and low in SKIP_TOP:
        return None
    return None if skip(name, True) else ""


def _plan_keep(name, mode):
    return mode != "bin" and not skip(name, False)


def plan(source, errors=None):
    """写す候補を順に返す: (作業データからの相対パス, 大きさ, 更新時刻)。シンボリックリンクはたどらない。
    transcribe\\bin の下は whisper.cpp- で始まるフォルダだけ入り、その中はフォルダ名で除かない(build の bin\\Release などの名前でも写す)。
    errors = _scan と同じ(読めなかった物を足すリスト)"""
    return _scan(source, _plan_enter, _plan_keep, errors)


CASES_DIR = "cases"        # 写す先の下の、案件の 作業用 を置くフォルダ(<写す先>/youtube-tools-data/cases/<題名>/作業用/…)
PREV_CASES_DIR = "cases-prev"   # 前の書き出し先に残った案件の 作業用(<写す先>/youtube-tools-data/cases-prev/<ドライブ>/<パス>/<題名>/作業用/…。写し戻しは手で)
CASE_WORK = schemas.WORK_DIR
CASE_STUDIO_ID = names.OWNER_FILE   # 作業用/.studio-id(案件の持ち主の印)
REQUEST_DIR = placement.REQUEST_DIR   # 友人の依頼の案件を置く outDir の下のフォルダ(依頼)
# 作業用の下で入るフォルダ → 入り方(RS8 B2-0。結果の束 runs・文書の履歴 .hist・機械の書き換え前の控え .bak)。名前は持ち主(② placement・ytt docloc)から読む。
# ここに無い名前(速報版・.tmp・.resume など)には入らない。.hist だけは <tid> のフォルダの 1 段下まで入る。
# 案件の中で写すのは .json だけ(採用.json.bak = ② casebook の 1 世代の控えは写さない。写す先の .prev が同じ役をする)
CASE_SUBDIRS = {placement.RUNS_DIR.lower(): "runs", docloc.HIST_DIR.lower(): "hist", docloc.BAK_DIR.lower(): "bak"}


def _cases_enter(r, name, mode):
    """案件の根(placement.case_roots の 1 つ)の下の入り方: "" = 根の直下 / "work" = 作業用 / "runs"・"bak" = その中(下には入らない) /
    "hist" = .hist(下の <tid> のフォルダへは "histdoc" で入り、その下には入らない)。動画・パック・その他は入らない"""
    if mode == "":
        return "work" if name == CASE_WORK else None
    if mode == "work":
        return CASE_SUBDIRS.get(name.lower())
    if mode == "hist":
        return None if skip(name, True) else "histdoc"
    return None


def _cases_keep(name, mode):
    """案件の 作業用 の下で写すファイル: *.json(途中のファイル `.part-` を除く)と、作業用の直下の .studio-id"""
    if mode == "" or skip(name, False):
        return False
    return name.lower().endswith(".json") or (mode == "work" and name == CASE_STUDIO_ID)


def plan_cases(out_dir, errors=None):
    """案件の根 <outDir>/<題名>/作業用/ の *.json(runs の結果の束・.clip.json・.edit.json・鍵を含む)と .studio-id、
    作業用の下の .hist/<tid>/*.json(文書の履歴)・.bak/*.json(機械の書き換え前の控え)を順に返す: (outDir からの相対パス, 大きさ, 更新時刻)。
    動画・_edit.mp4・*_pack・速報版・.tmp・.resume は写さない。outDir が無い・未設定なら何も返さない。
    写し戻し(restore_once の out_dir)も、バックアップの cases/ をこの決まりで歩く(cases/ の下は outDir と同じ形)"""
    if not out_dir or not os.path.isdir(out_dir):
        return iter(())
    return _plan_cases(out_dir, errors)


def _plan_cases(out_dir, errors):
    """案件の根ごとに 作業用 の下を歩く(根の一覧 = ② placement.case_roots。outDir 直下と 依頼 の 1 段下)"""
    def fail(where, e):
        if errors is not None:
            errors.append("読めないフォルダ: %s: %s" % (os.path.relpath(where, out_dir), tools.why(e)))
    for root in placement.case_roots(out_dir, fail):
        base = os.path.relpath(root, out_dir)
        for r, size, mtime in _scan(root, _cases_enter, _cases_keep, errors):
            yield os.path.join(base, r), size, mtime


def _excite_chat(rel):
    """<ツール>/live/excite/chat(配信中の検出の生のチャット)か"""
    return rel.replace(os.sep, "/").lower().endswith("live/excite/chat")


# ---------- 評価用・学習用の動画(media/)----------
def default_media_dirs():
    """写す評価用・学習用のフォルダ: 編集の設定の評価用のフォルダ(ytt/settings.eval_dirs = あるもの・ネットワークでない・作業データの外)と、
    それぞれの隣の 学習用データ(あれば)。COPY_MEDIA が False なら []"""
    if not COPY_MEDIA:
        return []
    out = []
    for d in settings.eval_dirs():
        out.append(d)
        learn = os.path.join(os.path.dirname(os.path.normpath(d)), LEARN_NAME)
        if os.path.isdir(learn) and not fsio.is_remote_drive(learn):
            out.append(learn)
    return list(dict.fromkeys(os.path.abspath(p) for p in out))


def media_rel(path):
    """評価用・学習用のフォルダの絶対パス → 写す先の media/ の下の相対パス(media\\<ドライブの文字>\\<パス>。元へ戻せる形)。ドライブの文字が無ければ None"""
    drive, rest = os.path.splitdrive(os.path.abspath(path))
    letter = drive.rstrip(":")
    if len(letter) != 1 or not letter.isalpha():
        return None   # ネットワーク上のパスなどは写さない
    return os.path.join(MEDIA_DIR, letter.upper(), rest.strip("\\/"))


def _media_enter(r, name, mode):
    return None if skip(name, True) else ""


def _media_keep(name, mode):
    return not skip(name, False)


def plan_media(folder, errors=None):
    """評価用・学習用のフォルダの下のファイル(動画・作業用の .clip.json など。キャッシュ・ログ・途中のファイルは除く)を順に返す: (folder からの相対パス, 大きさ, 更新時刻)"""
    if not folder or not os.path.isdir(folder):
        return iter(())
    return _scan(folder, _media_enter, _media_keep, errors)


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


def _media_items(folder, mrel, errors):
    """run_once の写す物の並び(写す先の相対パス, 元の根, 元の相対パス, 大きさ, 更新時刻)のうち、評価用・学習用のフォルダ 1 つ分"""
    for rel, size, mtime in plan_media(folder, errors):
        yield os.path.join(mrel, rel), folder, rel, size, mtime


def _prev_items(prev, errors):
    """前の書き出し先 1 つ分の案件の 作業用 の json(写す先は cases-prev/<ドライブ>/<パス>/… = 元へ戻せる形。見直し 3 の 4)"""
    prel = media_rel(prev)
    if not prel:
        return
    base = os.path.join(PREV_CASES_DIR, os.path.relpath(prel, MEDIA_DIR))
    for rel, size, mtime in plan_cases(prev, errors):
        yield os.path.join(base, rel), prev, rel, size, mtime


def run_once(source, folder, day=None, stop=None, on_file=None, out_dir=None, media_dirs=(), prev_out_dirs=()):
    """作業データ source を folder\\youtube-tools-data へ写す。out_dir(案件の根)があれば、その作業用の json を cases の下へも写す。
    prev_out_dirs(前の書き出し先。書き出し先を変えたあとも案件の文書はそこに残る)の 作業用 の json は cases-prev の下へ。
    media_dirs(評価用・学習用のフォルダの絶対パス)の中身は media の下へ(元の場所と同じ形)。
    -> {"copied", "same", "bytes", "errors": [写せなかったファイル], "scanErrors": [読めなかったフォルダ・調べられなかったファイル], "dest", "complete"}。
    complete = どちらの失敗も無く、途中で止めなかった。断るとき(場所が正しくない・ドライブが無い)は ValueError"""
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
    out = {"copied": 0, "same": 0, "bytes": 0, "failed": 0, "errors": [], "scanFailed": 0, "scanErrors": [], "dest": dest, "complete": False}
    scan_errors = []
    with_cases = bool(out_dir) and os.path.isdir(out_dir) and not _overlaps(out_dir, dest) and not _overlaps(dest, out_dir)
    media = [(m, media_rel(m)) for m in media_dirs or ()
             if isinstance(m, str) and os.path.isabs(m) and not _overlaps(m, dest) and not _overlaps(dest, m) and not _overlaps(m, source)]
    cur_out = os.path.normcase(os.path.abspath(out_dir)) if with_cases else None
    prev = []
    for p in prev_out_dirs or ():
        if not (isinstance(p, str) and os.path.isabs(p) and os.path.isdir(p)) or _overlaps(p, dest) or _overlaps(dest, p) or _overlaps(p, source):
            continue
        if os.path.normcase(os.path.abspath(p)) in (cur_out, *(os.path.normcase(os.path.abspath(x)) for x in prev)):
            continue
        prev.append(p)
    items = itertools.chain(((rel, source, rel, size, mtime) for rel, size, mtime in plan(source, scan_errors)),
                            ((os.path.join(CASES_DIR, rel), out_dir, rel, size, mtime) for rel, size, mtime in plan_cases(out_dir, scan_errors)) if with_cases else (),
                            *(_prev_items(p, scan_errors) for p in prev),
                            *(_media_items(m, mrel, scan_errors) for m, mrel in media if mrel))
    stopped = False
    for rel, root, src_rel, size, mtime in items:
        if stop is not None and stop():
            stopped = True
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
            out["failed"] += 1
            if len(out["errors"]) < MAX_ERRORS:
                out["errors"].append("%s: %s" % (rel, tools.why(e)))
    out["scanErrors"] = scan_errors[:MAX_ERRORS]
    out["scanFailed"] = len(scan_errors)
    out["complete"] = not stopped and not out["failed"] and not scan_errors
    if PRUNE and out["complete"]:   # 完全に写せたときだけ(途中の失敗・読めないフォルダ・止めた回は何も消さない)
        out["pruned"] = prune(dest, source, out_dir if with_cases else None, prev, stop=stop)
    return out


def _source_of(rel, source, out_dir, prev_bases):
    """写す先の相対パス -> 元のパス か None(この回で歩かなかった所・元のドライブが無い = 消す判断をしない)"""
    parts = rel.split(os.sep)
    top = parts[0].lower()
    if top == CASES_DIR:
        return os.path.join(out_dir, *parts[1:]) if out_dir and len(parts) > 1 else None
    if top == PREV_CASES_DIR:
        for base, p in prev_bases:
            if rel.lower().startswith(base.lower() + os.sep):
                return os.path.join(p, rel[len(base) + 1:])
        return None
    if top == MEDIA_DIR:
        if len(parts) < 3 or len(parts[1]) != 1 or not parts[1].isalpha():
            return None
        root = parts[1].upper() + ":" + os.sep
        return os.path.join(root, *parts[2:]) if os.path.isdir(root) else None
    return os.path.join(source, rel)


def prune(dest, source, out_dir=None, prev_dirs=(), now=None, stop=None, dry=False):
    """写す先 dest の古い分を消す(頭の説明の「古い分を消す」)。dry = 数えるだけ。
    -> {"files", "bytes"(元に無い物の写し), "prev", "prevBytes"(古い .prev), "skipped"(消さなかった理由。空 = 消した)}"""
    now = time.time() if now is None else now
    out = {"files": 0, "bytes": 0, "prev": 0, "prevBytes": 0, "skipped": ""}
    if not (source and os.path.isdir(source) and os.path.isdir(dest)):
        out["skipped"] = "元か写す先のフォルダが見つかりません"
        return out
    prev_bases = []
    for p in prev_dirs or ():
        prel = media_rel(p)
        if prel:
            prev_bases.append((os.path.join(PREV_CASES_DIR, os.path.relpath(prel, MEDIA_DIR)), p))
    errors, files, prevs = [], {}, []
    for rel, size, mtime in _scan(dest, lambda r, n, m: "", lambda n, m: SKIP_MARK not in n.lower(), errors):
        if rel.lower().endswith(PREV_SUFFIX):
            prevs.append((rel, size, mtime))
        else:
            files[rel.lower()] = (rel, size)
    if errors:
        out["skipped"] = "写す先に読めない所があります"
        return out
    gone = []
    for key, (rel, size) in files.items():
        src = _source_of(rel, source, out_dir, prev_bases)
        if src is not None and not os.path.lexists(src):
            gone.append((rel, size))
    gone_keys = {r.lower() for r, _s in gone}
    old_prev = [(rel, size) for rel, size, mtime in prevs
                if rel[:-len(PREV_SUFFIX)].lower() in gone_keys or rel[:-len(PREV_SUFFIX)].lower() not in files or now - mtime > PREV_KEEP_DAYS * 86400]
    if files and len(gone) > PRUNE_MAX_SHARE * len(files):
        out["skipped"] = "元に無い物が写しの %d 割を超えます(%d 個)。作業データ側の事故かもしれないので消しません" % (round(PRUNE_MAX_SHARE * 10), len(gone))
        return out
    dirs = set()
    for rel, size in gone + old_prev:
        if stop is not None and stop():
            break
        if not dry:
            try:
                os.remove(os.path.join(dest, rel))
            except FileNotFoundError:
                pass
            except OSError:
                continue
            dirs.add(os.path.dirname(rel))
        k = "prev" if rel.lower().endswith(PREV_SUFFIX) else "files"
        out[k] += 1
        out["prevBytes" if k == "prev" else "bytes"] += size
    for d in sorted(dirs, key=lambda x: -x.count(os.sep)):   # 空になったフォルダ(深い方から。写す先そのものは残す)
        while d:
            try:
                os.rmdir(os.path.join(dest, d))
            except OSError:
                break
            d = os.path.dirname(d)
    return out


class Backup:
    def __init__(self, prefs, source, data_dir, log=None, clock=None, first_wait=FIRST_WAIT, check_every=CHECK_EVERY, defaults=None, out_dir=None,
                 media_dirs=None, prev_out_dirs=None):
        """prefs: src/app/prefs.py の Prefs(節 backup)。defaults: 設定が読めないときに使う節の既定(入口が prefs.DEFAULTS["backup"] を渡す。
        prefs を読み込まない = app の部品に依存しない。None = 空 = オフ扱い)。source: 作業データの親フォルダ(datadir.data_root()。None = inplace なので写さない)。
        data_dir: ホームの作業データ(app。最後に写した時刻の記録を置く)。
        out_dir: 案件の根(スタジオの書き出し先)。文字列か、呼ぶたびに返す関数(設定で変わるので)。None・無いフォルダ = 案件の 作業用 は写さない。
        media_dirs: 評価用・学習用のフォルダの一覧か、呼ぶたびに返す関数(入口が default_media_dirs を渡す)。None = 写さない(テスト)。
        prev_out_dirs: 前の書き出し先の一覧か、呼ぶたびに返す関数(入口が outdirs の outDirs を渡す)。None = 写さない"""
        self.prefs, self.source, self.data_dir = prefs, source, data_dir
        self.defaults = defaults
        self.out_dir = out_dir
        self.media_dirs = media_dirs
        self.prev_out_dirs = prev_out_dirs
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

    def _media_dirs(self):
        return self._dirs(self.media_dirs, "評価用のフォルダ")

    def _prev_out_dirs(self):
        return self._dirs(self.prev_out_dirs, "前の書き出し先")

    def _dirs(self, src, what):
        try:
            v = src() if callable(src) else src
        except Exception as e:   # noqa: BLE001  設定が読めなくても、作業データと案件は写す(受け方が狭いと tick ごと止まる = 見直し 3 の 26)
            self.log("バックアップ: %sの設定を読めませんでした(%s)" % (what, tools.why(e)))
            return []
        return [p for p in v or [] if isinstance(p, str) and os.path.isabs(p)]

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

    def due(self, cfg):
        """写す時が来たか: 写す先を変えた・まだ完全に写せたことが無い・完全に写せてから間隔がたった。
        ただし前の回が完全に写せなかった(partial)なら、その試しから RETRY_SEC は待つ(読めないフォルダを 3 分ごとに歩き直さない)"""
        if self.last.get("folder") != cfg.get("folder"):
            return True
        ok, now, tried = self.last.get("ok"), self.clock(), self.last.get("tried")
        if self.last.get("partial") and isinstance(tried, (int, float)):   # 完全に写せなかった回のあとは、ok の間隔より先に RETRY_SEC で見る(見直し 3 の 24)
            return now - tried >= RETRY_SEC
        return not (isinstance(ok, (int, float)) and now - ok < float(cfg.get("everyHours") or 24) * 3600)

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
                r = run_once(self.source, cfg.get("folder") or "", stop=lambda: self.closed, out_dir=self._out_dir(), media_dirs=self._media_dirs(),
                             prev_out_dirs=self._prev_out_dirs())
            except ValueError as e:
                if self.last.get("error") != str(e):   # 同じ文(ドライブが無い)を続けて書かない(見直し 3 の 25)
                    self.log("バックアップ: " + str(e))
                self.state, self.message = "error", str(e)
                self.last = dict(self.last, tried=self.clock(), error=str(e), partial=True)   # partial = 次は RETRY_SEC のあと
                self._save_state()
                return None
            now = self.clock()
            # ok = 完全に写せた時刻(読めないフォルダ・写せないファイルがあれば進めない = 部品 M3)。
            # 写す先を変えたのに完全でなければ、前の先の ok は持ち越さない(新しい先にはまだ全部が無い)
            same_folder = self.last.get("folder") == cfg.get("folder")
            ok = now if r["complete"] else (self.last.get("ok") if same_folder else None)
            self.last = {"ok": ok, "tried": now, "partial": not r["complete"], "folder": cfg.get("folder"), "dest": r["dest"], "copied": r["copied"],
                         "same": r["same"], "bytes": r["bytes"], "errors": r["errors"], "scanErrors": r["scanErrors"], "seconds": round(now - t0, 1)}
            if r.get("pruned"):
                self.last["pruned"] = dict(r["pruned"], at=now)
            self._save_state()
            self.state = "idle"
            why = []
            if r["failed"]:
                why.append("写せなかったファイルが %d 個(使用中など)" % r["failed"])
            if r["scanFailed"]:
                why.append("読めなかったフォルダ・ファイルが %d 個" % r["scanFailed"])
            self.message = ("%s あります。読める物は写しました。%d 分後にもう一度試します" % ("・".join(why), RETRY_SEC // 60)) if why else ""
            self.log("バックアップ: %d 個を写しました(変わりなし %d 個・%.1f MB・%s)%s" % (
                r["copied"], r["same"], r["bytes"] / 1048576.0, r["dest"], " %s" % "・".join(why) if why else ""))
            for m in (r["scanErrors"] + r["errors"])[:5]:
                self.log("バックアップ:   " + m)
            pr = r.get("pruned")
            if pr and pr["skipped"]:
                self.log("バックアップ: 古い分は消しませんでした(%s)" % pr["skipped"])
            elif pr and (pr["files"] or pr["prev"]):
                self.log("バックアップ: 古い分を消しました(元に無い物の写し %d 個・%.1f MB・古い .prev %d 個・%.1f MB)" % (
                    pr["files"], pr["bytes"] / 1048576.0, pr["prev"], pr["prevBytes"] / 1048576.0))
            return r

    def snapshot(self):
        cfg = self._cfg()
        ok = self.last.get("ok")
        return dict(cfg, state=self.state, stateLabel=STATE_LABELS[self.state], message=self.message, source=self.source,
                    lastOk=int(ok * 1000) if isinstance(ok, (int, float)) else None, dest=self.last.get("dest"),
                    copied=self.last.get("copied"), same=self.last.get("same"), bytes=self.last.get("bytes"), partial=bool(self.last.get("partial")),
                    errors=(list(self.last.get("scanErrors") or []) + list(self.last.get("errors") or []))[:MAX_ERRORS])


def _walk_enter(r, name, mode):
    """写し戻す側の入り方: 直下の cases/・media/ には入らない(作業データの根へ戻す物ではない。_restore_cases・_restore_media が戻す)。
    ほかは写す側(_plan_enter)と同じ決まり = 写さない場所の物(app/intake の動画・analytics など)は戻さない(6c-1)"""
    if not os.path.dirname(r) and name.lower() in (CASES_DIR, MEDIA_DIR):
        return None
    return _plan_enter(r, name, mode)


def _walk_backup(root):
    """バックアップ側の (相対パス, 大きさ, 更新時刻)。`.prev`(1つ前の控え)と途中のファイルは数えない。シンボリックリンクはたどらない。
    写す側と同じ決まり(_walk_enter・_plan_keep)を通す"""
    return _scan(root, _walk_enter, lambda name, mode: not name.lower().endswith(PREV_SUFFIX) and _plan_keep(name, mode))


def _restore_media(src_root, out, stop=None, dry_run=False):
    """バックアップの media/<ドライブ>/<パス> を元の場所(<ドライブ>:\\<パス>)へ写し戻す。既にあるファイルは上書きしない(数は mediaKept)。
    そのドライブが無いときは戻さない(数は mediaSkipped)。out の media* に数を足す"""
    base = os.path.join(src_root, MEDIA_DIR)
    for rel, size, mtime in _scan(base, _media_enter, lambda name, mode: not name.lower().endswith(PREV_SUFFIX) and _media_keep(name, mode)):
        if stop is not None and stop():
            break
        parts = rel.split(os.sep, 1)
        if len(parts) != 2 or len(parts[0]) != 1 or not parts[0].isalpha():
            continue
        drive = parts[0].upper() + ":" + os.sep
        if not os.path.isdir(drive):
            out["mediaSkipped"] += 1
            continue
        _put_back(os.path.join(base, rel), os.path.join(drive, parts[1]), size, mtime, out, "media", os.path.lexists, os.path.join(MEDIA_DIR, rel), dry_run)


def _put_back(src, dst, size, mtime, out, key, keep, label, dry_run):
    """1 つのファイルを写し戻す: 同じなら <key>Same、keep(dst) なら <key>Kept(上書きしない)、ほかは写して <key>Copied と bytes。
    key が "" なら same・newer・copied(作業データの根)。失敗は errors へ(MAX_ERRORS まで)"""
    names = ("same", "newer", "copied") if not key else (key + "Same", key + "Kept", key + "Copied")
    try:
        if same(dst, size, mtime):
            out[names[0]] += 1
        elif keep(dst):
            out[names[1]] += 1
        else:
            if not dry_run:
                copy_one(src, dst, None)
            out[names[2]] += 1
            out["bytes"] += size
    except OSError as e:
        if len(out["errors"]) < MAX_ERRORS:
            out["errors"].append("%s: %s" % (label, tools.why(e)))


def _restore_cases(src_root, out_dir, out, stop=None, dry_run=False):
    """バックアップの cases/<題名>/作業用/… を <out_dir>/<題名>/作業用/… へ写し戻す(RS8 B2-0)。
    歩き方は plan_cases と同じ(写した物だけが戻る)。**既にあるファイルは、中身が違っても上書きしない**(案件の 作業用 は人が直した文書なので、
    作業データの根と違い「バックアップのほうが新しい」でも上書きしない。数は kept)。out の cases* に数を足す"""
    for rel, size, mtime in plan_cases(os.path.join(src_root, CASES_DIR)):
        if stop is not None and stop():
            break
        _put_back(os.path.join(src_root, CASES_DIR, rel), os.path.join(out_dir, rel), size, mtime, out, "cases", os.path.lexists, os.path.join(CASES_DIR, rel), dry_run)


def _check_out_dir(out_dir, src_root):
    """写し戻す案件の根を確かめる -> 絶対パス。正しくなければ ValueError(相対パス・ドライブが無い・バックアップと重なる)"""
    if not os.path.isabs(out_dir):
        raise ValueError("案件の根(outDir)を絶対パスで指定してください")
    out_dir = os.path.abspath(out_dir)
    drive = os.path.splitdrive(out_dir)[0]
    if drive and not os.path.isdir(drive + os.sep):
        raise ValueError("案件の根のドライブ(%s)が見つかりません" % drive)
    if _overlaps(src_root, out_dir) or _overlaps(out_dir, src_root):
        raise ValueError("バックアップと案件の根(outDir)が重なっています")
    return out_dir


def restore_once(folder, target, stop=None, dry_run=False, out_dir=None, media=True):
    """`<folder>\\youtube-tools-data\\` から target(作業データ)へ、無い・違うファイルを写し戻す。
    out_dir(案件の根。入口がスタジオの設定から渡す値と同じ)を渡すと、バックアップの cases/<題名>/作業用/ をそこへも写し戻す
    (こちらは既にあるファイルを上書きしない)。渡さなければ cases/ は戻さず、数だけ casesSkipped に出す。
    media = 評価用・学習用の動画(media/)も元の場所へ戻す(既にあるファイルは上書きしない)。
    -> {"copied", "same", "newer", "bytes", "errors": [..], "source", "outDir", "casesCopied", "casesSame", "casesKept", "casesSkipped",
    "mediaCopied", "mediaSame", "mediaKept", "mediaSkipped"}。
    newer = target のほうが新しいので上書きしなかった数。casesKept = 案件の根に既にあるので上書きしなかった数。
    `.prev` は写さない・シンボリックリンクはたどらない・target のファイルは消さない。dry_run なら写さずに数だけ(copied・casesCopied = 写すことになる数)。
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
    out_dir = _check_out_dir(out_dir, src_root) if out_dir else None
    out = {"copied": 0, "same": 0, "newer": 0, "bytes": 0, "errors": [], "source": src_root, "outDir": out_dir,
           "casesCopied": 0, "casesSame": 0, "casesKept": 0, "casesSkipped": 0, "mediaCopied": 0, "mediaSame": 0, "mediaKept": 0, "mediaSkipped": 0}
    if out_dir:
        _restore_cases(src_root, out_dir, out, stop, dry_run)
    else:
        out["casesSkipped"] = sum(1 for _ in plan_cases(os.path.join(src_root, CASES_DIR)))
    if media:
        _restore_media(src_root, out, stop, dry_run)
    for rel, size, mtime in _walk_backup(src_root):
        if stop is not None and stop():
            break
        _put_back(os.path.join(src_root, rel), os.path.join(target, rel), size, mtime, out, "",
                  lambda dst: os.path.exists(dst) and os.stat(dst).st_mtime > mtime + 2.0, rel, dry_run)   # newer = target のほうが新しい(バックアップのあとで直した)
    return out


def _studio_out_dir_from(*roots):
    """写し戻すときの案件の根の既定: roots(写し戻す先・バックアップ)の順に studio/settings.json の outDir(空でない絶対パス)を探し、
    無ければ <最初の root>/studio/exports(ytt/datadir.studio_out_dir と同じ決まり。あちらは今の作業データの場所しか読めないので、ここは root を受ける)"""
    for root in roots:
        st = fsio.read_json_or(os.path.join(root, "studio", "settings.json"), None, kind=dict)
        v = st.get("outDir") if st else None
        if isinstance(v, str) and v and os.path.isabs(v):
            return v
    return os.path.join(roots[0], "studio", "exports")


def main(argv=None):
    ap = argparse.ArgumentParser(description="作業データのバックアップの写し戻し(入口を止めてから。notes:docs/spec/data.md)")
    ap.add_argument("--restore", metavar="FOLDER", required=True, help="バックアップ先のフォルダ(その下の youtube-tools-data から写し戻す)")
    ap.add_argument("--target", metavar="DIR", help="写し戻す先(既定: 作業データの本物の場所)")
    ap.add_argument("--out-dir", metavar="DIR", help="案件の 作業用 を写し戻す案件の根(既定: スタジオの設定の書き出し先。既にあるファイルは上書きしない)")
    ap.add_argument("--yes", action="store_true", help="確認を聞かない")
    a = ap.parse_args(argv)
    target = a.target
    if not target:
        from ytt import datadir
        target = datadir.data_root()
    out_dir = a.out_dir
    if not out_dir and a.restore and os.path.isabs(a.restore):
        out_dir = _studio_out_dir_from(os.path.abspath(target), os.path.join(os.path.abspath(a.restore), DEST_NAME))
        try:
            _check_out_dir(out_dir, os.path.join(os.path.abspath(a.restore), DEST_NAME))
        except ValueError as e:   # 既定の場所が使えないときは案件だけ戻さない(作業データの根は戻す)。--out-dir で指定したときは断る
            print("案件の 作業用 は写し戻しません: %s" % e)
            out_dir = None
    try:
        r = restore_once(a.restore, target, dry_run=True, out_dir=out_dir)
    except ValueError as e:
        print("できません: %s" % e)
        return 2
    print("写し戻し元: %s\n写し戻す先: %s" % (r["source"], os.path.abspath(target)))
    print("写す %d 個・同じ %d 個・写す先のほうが新しいので上書きしない %d 個" % (r["copied"], r["same"], r["newer"]))
    if r["outDir"]:
        print("案件の 作業用(%s): 写す %d 個・同じ %d 個・既にあるので上書きしない %d 個" % (r["outDir"], r["casesCopied"], r["casesSame"], r["casesKept"]))
    elif r["casesSkipped"]:
        print("案件の 作業用 %d 個は写し戻しません(--out-dir で案件の根を指定すると戻します)" % r["casesSkipped"])
    if r["mediaCopied"] or r["mediaSame"] or r["mediaKept"] or r["mediaSkipped"]:
        print("評価用・学習用の動画(元の場所へ): 写す %d 個・同じ %d 個・既にあるので上書きしない %d 個・ドライブが無いので戻さない %d 個" % (
            r["mediaCopied"], r["mediaSame"], r["mediaKept"], r["mediaSkipped"]))
    print("合わせて %.1f MB" % (r["bytes"] / 1048576.0))
    for m in r["errors"]:
        print("  読めない: " + m)
    if not r["copied"] and not r["casesCopied"] and not r["mediaCopied"]:
        print("写すものはありません。")
        return 0
    if not a.yes and input("入口を止めてありますか。写し戻しますか? [y/N] ").strip().lower() not in ("y", "yes"):
        print("やめました。")
        return 1
    r = restore_once(a.restore, target, out_dir=out_dir)
    print("写し戻しました: %d 個(%.1f MB)・上書きしなかった %d 個・失敗 %d 個" % (r["copied"] + r["casesCopied"] + r["mediaCopied"], r["bytes"] / 1048576.0,
                                                                     r["newer"] + r["casesKept"] + r["mediaKept"], len(r["errors"])))
    for m in r["errors"]:
        print("  失敗: " + m)
    return 0 if not r["errors"] else 3


if __name__ == "__main__":
    sys.exit(main())
