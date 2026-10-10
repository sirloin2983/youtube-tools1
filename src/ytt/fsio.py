"""ファイルの読み書き(スタジオの common.atomic_write と、文字起こしの atomic_write / pipeline_io の書き込みを1つにしたもの)。

ほかに、各ツールが自前で書いていた小道具(2026-10-09。docs/design/code-review-simplify-2026-10-08.md の A・G10):
read_json_or(読めなければ既定値)・stamp / StampCache(更新日時と大きさが変わったときだけ読み直す)・rotate(ログの 1 世代の回し)・
is_inside(パスがフォルダの中か。セキュリティの検査に使う形はここ 1 か所)・dir_size(フォルダの大きさ)。"""
import glob
import json
import os
import shutil
import tempfile
import threading
import time

RETRY_WINERRORS = (5, 32, 33)   # アクセス拒否・共有違反・ロック違反(ウイルス対策・検索インデックス・同期ソフトが一瞬開いている)
REPLACE_ATTEMPTS = 4            # 待ちは 0.1 → 0.2 → 0.4 秒(合計 0.7 秒)


def replace_retry(src, dst):
    """os.replace。Windows の一時的なロック(winerror 5・32・33)だけ、短く待ってやり直す。
    それ以外の PermissionError(読み取り専用のフォルダなど)はすぐに上げる(待っても直らないため)。"""
    for attempt in range(REPLACE_ATTEMPTS):
        try:
            os.replace(src, dst)
            return
        except PermissionError as e:
            if getattr(e, "winerror", None) not in RETRY_WINERRORS or attempt == REPLACE_ATTEMPTS - 1:
                raise
            time.sleep(0.1 * 2 ** attempt)


def unlink_quiet(path):
    """ファイルを消す。消せなくても(無い・ロック中)上げない(後片付けの失敗で、本来のエラーを隠さない)"""
    try:
        os.unlink(path)
    except OSError:
        pass


def temp_in(folder, data, fsync_required=True):
    """folder に一時ファイル(.tmp-*.part)を作って data を書き、そのパスを返す。失敗したら一時ファイルを消して上げる。
    fsync_required=False なら、fsync できないドライブでも続ける。"""
    fd, tmp = tempfile.mkstemp(dir=folder, prefix=".tmp-", suffix=".part")
    try:
        with os.fdopen(fd, "wb") as f:
            f.write(data)
            f.flush()
            try:
                os.fsync(f.fileno())   # 停電・強制終了のあとに「中身が空のファイル」が残らないように
            except OSError:
                if fsync_required:
                    raise
    except BaseException:
        unlink_quiet(tmp)
        raise
    return tmp


def atomic_write(path, data: bytes, mode=None, fsync_required=False):
    """一時ファイルに書いてから置き換える(書きかけを他のツール・次の起動に読ませない。失敗しても元の内容は壊さない)。
    fsync_required=True は、ディスクへの書き出しに失敗したら保存も失敗にする(文字起こしの校正の成果など、失うと困るもの)。"""
    folder = os.path.dirname(path)
    os.makedirs(folder, exist_ok=True)
    tmp = temp_in(folder, data, fsync_required)
    try:
        if mode is not None:
            try:
                os.chmod(tmp, mode)
            except OSError:
                pass
        replace_retry(tmp, path)
    except BaseException:
        unlink_quiet(tmp)
        raise


def create_new(path, data):
    """path が無いときだけ、書き終えた内容で作る(True)。すでにあれば何もしない(False)。
    一時ファイルに書いてから、ハードリンク(既存のファイルを決して上書きしない)で置く。ハードリンクが使えないドライブ(exFAT など)では、
    存在を確かめてから置き換える(同じプロセスの中はロックで守る前提。呼び出し側がロックを持つ)。"""
    tmp = temp_in(os.path.dirname(path), data)
    try:
        try:
            os.link(tmp, path)
            return True
        except FileExistsError:
            return False
        except (OSError, NotImplementedError, AttributeError):
            if os.path.lexists(path):
                return False
            replace_retry(tmp, path)
            tmp = None
            return True
    finally:
        if tmp:
            unlink_quiet(tmp)


def write_json(path, obj, indent=2, mode=None, fsync_required=False, allow_nan=True, separators=None):
    """UTF-8(BOM なし)の JSON を原子的に書く(受け渡しのファイルの約束。docs/spec/pipeline.md の 1)。
    mode を渡すとそのファイルの権限(例 0o600 = 鍵のファイル。atomic_write と同じ)。
    fsync_required=True はディスクへの書き出しに失敗したら保存も失敗にする(失うと困る成果。atomic_write と同じ)。
    allow_nan=False は NaN / Infinity を書かない(ValueError。JSON として読めないファイルを作らない)。
    separators=(",", ":") で詰めて書く(末尾の改行は indent があるときだけ)"""
    text = json.dumps(obj, ensure_ascii=False, indent=indent, allow_nan=allow_nan, separators=separators) + ("\n" if indent is not None else "")
    atomic_write(path, text.encode("utf-8"), mode=mode, fsync_required=fsync_required)


def append_jsonl(path, rows, separators=(",", ":")):
    """1 行 1 JSON のファイル(series.jsonl など)に rows を足す(回さない。回すなら append_line)"""
    with open(path, "a", encoding="utf-8") as f:
        for row in rows:
            f.write(json.dumps(row, separators=separators) + "\n")


class TooLarge(ValueError):
    """read_json_file が max_bytes を超えたファイルを断ったときの ValueError(呼び手が「大きすぎる」と「壊れている」を言い分けられるように)"""


def _reject_constant(name):
    raise ValueError("NaN / Infinity は JSON として受け付けません: %s" % name)


def read_json_file(path, max_bytes, allow_nan=False):
    """UTF-8(BOM があっても可)の JSON を読む。max_bytes を超えるファイル・NaN / Infinity を含むものは ValueError。
    他のツール・他人が作ったかもしれないファイルを読むときに使う(巨大なファイルで固まらないように)。
    allow_nan=True なら NaN / Infinity をそのまま float として通す(json.dump の既定で書いた自分のファイル。以前の読み方との互換)"""
    with open(path, "rb") as f:
        raw = f.read(max_bytes + 1)
    if len(raw) > max_bytes:
        raise TooLarge("ファイルが大きすぎます")
    if allow_nan:
        return json.loads(raw.decode("utf-8-sig"))
    return json.loads(raw.decode("utf-8-sig"), parse_constant=_reject_constant)


def is_network_path(p):
    """ネットワーク上のパス(\\\\サーバー\\共有\\… や //サーバー/…、\\\\?\\UNC\\…)か。
    Windows でこうしたパスの存在を確かめるだけで、そのサーバーへ接続して資格情報(NTLM のハッシュ)を送ってしまうため、
    利用者が押したボタン以外(URL から自動で呼ばれる処理、他人が作ったファイルの中のパス)では調べない。"""
    return str(p or "").replace("/", "\\").startswith("\\\\")


def norm_path(p):
    """同じ動画かを比べる鍵: 絶対パスにして大文字小文字・区切りをそろえる(normcase(abspath))。ファイルには触らない(RS3-E5a に編集の ed_state から)"""
    return os.path.normcase(os.path.abspath(p))


# ---------- 各ツールにあった小道具(2026-10-09) ----------
READ_OR_MAX = 16 * 2**20   # read_json_or の既定の大きさの上限(設定・記録のファイル。これより大きいものは「読めない」扱い)


def read_json_or(path, default=None, max_bytes=READ_OR_MAX, kind=None, allow_nan=False):
    """JSON のファイルを「読めれば読む」(read_json_file の上げない版)。-> 中身 か default。
    無い・読めない・UTF-8 でない・JSON でない・NaN / Infinity を含む・max_bytes より大きい・入れ子が深すぎる・
    kind(dict・list など。タプルで複数も可)の形でない、のどれでも default を返す。BOM があってもよい。
    allow_nan=True なら NaN / Infinity を float として通す(default にしない)。
    default は複製しない(書き換える呼び出し側は、{} などをその場で作って渡す)"""
    try:
        d = read_json_file(path, max_bytes, allow_nan=allow_nan)
    except (OSError, UnicodeError, ValueError, RecursionError):
        return default
    return d if kind is None or isinstance(d, kind) else default


def read_schema_json(path, max_bytes, schema, key, kind=list):
    """付き物の JSON(編集の <id>.words.json・.asr.json・.diar.json・.alt.json・.ytcap.json など)を読む。
    形が違う(schema が違う・d[key] が kind でない)・無い・壊れていれば None(編集の ed_state.read_schema_json の正。RS2-1a)"""
    try:
        d = read_json_file(path, max_bytes)
    except (OSError, UnicodeError, ValueError):
        return None
    if not isinstance(d, dict) or d.get("schema") != schema or not isinstance(d.get(key), kind):
        return None
    return d


def stamp(path):
    """(更新日時 ns, 大きさ)。無い・調べられなければ None(「ファイルが変わったときだけ読み直す」キャッシュの鍵)"""
    try:
        st = os.stat(path)
    except (OSError, ValueError):
        return None
    return (st.st_mtime_ns, st.st_size)


class StampCache:
    """ファイルの中身を、更新日時と大きさ(stamp)が変わったときだけ読み直すキャッシュ。スレッドから同時に呼んでよい。
    get(path, load): stamp が前と同じなら覚えた値、違えば load(path) を呼んで覚える(load の結果が None でも覚える)。
      ファイルが無い・調べられなければ None を返す(覚えた値は prune まで残す)。load は鍵のロックの外で呼ぶ(重い読みで他を待たせない)。
      load が上げた例外はそのまま上げる(覚えない)
    peek(path): stamp が前と同じときだけ覚えた値(読み直さない)。無い・変わった・覚えていなければ None
    set(path, value): 今の stamp で value を覚える(上書き。ファイルが無ければ覚えずに False)。名前の付け替えで中身が移ったファイルに使う
    prune(keep, folder=None): keep に無い鍵を外す(folder を渡すと、そのフォルダの直下の鍵だけを見る)。clear(): 全部外す。
    len()・in・for で覚えている鍵を見られる(テスト用)"""

    def __init__(self):
        self._d = {}
        self._lock = threading.Lock()

    def get(self, path, load):
        key = stamp(path)
        if key is None:
            return None
        with self._lock:
            hit = self._d.get(path)
            if hit is not None and hit[0] == key:
                return hit[1]
        value = load(path)
        with self._lock:
            self._d[path] = (key, value)
        return value

    def peek(self, path):
        key = stamp(path)
        if key is None:
            return None
        with self._lock:
            hit = self._d.get(path)
        return hit[1] if hit is not None and hit[0] == key else None

    def set(self, path, value):
        key = stamp(path)
        if key is None:
            return False
        with self._lock:
            self._d[path] = (key, value)
        return True

    def prune(self, keep, folder=None):
        keep = set(keep)
        with self._lock:
            for p in [p for p in self._d if p not in keep and (folder is None or os.path.dirname(p) == folder)]:
                del self._d[p]

    def clear(self):
        with self._lock:
            self._d.clear()

    def __len__(self):
        return len(self._d)

    def __contains__(self, path):
        return path in self._d

    def __iter__(self):
        """覚えている鍵(パス)の写し"""
        with self._lock:
            return iter(list(self._d))


def rotate(path, limit, old=None):
    """ログを 1 世代だけ回す: path が limit バイトを超えていたら old へ置き換える(前の old は消える)。-> 回したか。
    old を省くと <名前>.old.log(.log で終わらなければ <名前>.old)。画面のエラーの記録のように <名前>.1 にしたいときは old に渡す。
    無い・使用中などで回せなければ何もしない(上げない。呼ぶ側はそのまま追記する)"""
    if old is None:
        old = path[:-4] + ".old.log" if path.endswith(".log") else path + ".old"
    try:
        if os.path.getsize(path) > limit:
            os.replace(path, old)
            return True
    except OSError:
        pass
    return False


def append_line(path, line, max_bytes):
    """1 行を書き足す(max_bytes を超えていたら先に <path>.1 へ回す = 1 世代)。書けなければ OSError。line は改行つきの文字列(UTF-8 で書く)。
    画面のエラーの記録(clientlog)・まとめて実行の記録(autorun)・採用の記録(live_export)が同じ形で使う(RS3-0B で clientlog から移した)"""
    os.makedirs(os.path.dirname(path), exist_ok=True)
    rotate(path, max_bytes, old=path + ".1")
    with open(path, "a", encoding="utf-8") as f:
        f.write(line)


def is_inside(path, root, strict=False):
    """path が root の中か(strict=True なら root そのものは含めない)。許可したフォルダの中だけを読み書きさせる検査に使う(セキュリティの決まりはここ 1 か所)。
    いちばん厳しい形にそろえた(2026-10-09。各ツールの 6 通りは realpath の有無・ネットワークの扱いが違った):
    - ネットワーク上のパス(どちらか)は調べずに False(存在を確かめるだけで資格情報を送るため。is_network_path)
    - realpath で比べる(シンボリックリンク・ジャンクション・.. で外へ出られない。まだ無いファイルでもよい = 親のリンクは解く)
    - 大文字小文字をそろえて比べ、文字列の頭ではなくフォルダの区切りで比べる(C:/data と C:/data2 を取り違えない。commonpath)
    - 空・別のドライブ・NUL を含む・調べられないときは False
    False は「中だと確かめられなかった」の意味。「中にあれば断る」検査に使うときは、ネットワーク上のパスを呼ぶ側で先に断ること"""
    if not path or not root or is_network_path(path) or is_network_path(root):
        return False
    try:
        p, r = os.path.normcase(os.path.realpath(path)), os.path.normcase(os.path.realpath(root))
        if os.path.commonpath([p, r]) != r:
            return False
    except (OSError, ValueError, TypeError):
        return False
    return not (strict and p == r)


def dir_size(path):
    """(バイト数, ファイル数)。ファイルを渡せばその大きさと 1。フォルダは中身の合計(リンクはたどらない・数えない)。
    無い・読めないものは数えない(無ければ (0, 0)。上げない)"""
    if os.path.isfile(path):
        try:
            return os.path.getsize(path), 1
        except OSError:
            return 0, 0
    total = count = 0
    for dirpath, dirnames, filenames in os.walk(path):
        dirnames[:] = [d for d in dirnames if not os.path.islink(os.path.join(dirpath, d))]
        for n in filenames:
            fp = os.path.join(dirpath, n)
            try:
                if not os.path.islink(fp):
                    total += os.path.getsize(fp)
                    count += 1
            except OSError:
                pass
    return total, count


def existing_parent(path):
    """path が今あればそのまま、無ければ上へたどって最初にあるパス(まだ無いフォルダの空き容量を調べる前に)。
    根までたどっても無ければ根(ドライブなど)を返す。空・None はそのまま返す(上げない)"""
    probe = path
    while probe and not os.path.exists(probe):
        parent = os.path.dirname(probe)
        if parent == probe:
            break
        probe = parent
    return probe


def is_remote_drive(p):
    """Windows のネットワークドライブ(net use で割り当てた Z: など)か。ドライブの種類を聞くだけで、ファイルには触らない
    (RS3-1 に editor/ed_relink.py の _remote_drive から)"""
    if os.name != "nt":
        return False
    drive = os.path.splitdrive(p)[0]
    if len(drive) != 2 or drive[1] != ":":
        return False
    try:
        import ctypes
        return ctypes.windll.kernel32.GetDriveTypeW(drive + "\\") == 4   # DRIVE_REMOTE
    except (AttributeError, OSError, ValueError):
        return False


def same_drive(a, b):
    """2 つのパスが同じドライブか(大文字小文字は区別しない)"""
    return os.path.splitdrive(os.path.abspath(a))[0].lower() == os.path.splitdrive(os.path.abspath(b))[0].lower()


def move_file(a, b, log=None):
    """ファイルを移す。同じドライブなら名前を変えるだけ。別のドライブ(C: → E: など。評価用のフォルダへ取り込むとき)は
    コピー(.part)→ 大きさを確かめる → 名前を付ける → 元を消す。元を消せなければ(開いているなど)コピーを消して OSError(元のまま)。
    log: 別のドライブへ移したときに 1 行書くロガー(省略で書かない)。RS3-1 に editor/ed_relink.py の _move から"""
    try:
        os.rename(a, b)
        return
    except OSError as e:
        if same_drive(a, b) or os.path.exists(b):
            raise
        first = e
    part = b + ".part"
    try:
        shutil.copy2(a, part)
        if os.path.getsize(part) != os.path.getsize(a):
            raise OSError("コピーの大きさが合いません: %s" % os.path.basename(a))
        os.rename(part, b)
        try:
            os.remove(a)
        except OSError:
            os.remove(b)
            raise
    except BaseException:
        unlink_quiet(part)
        raise
    if log is not None:
        log.info("別のドライブへ移した: %s → %s(最初の名前の変更: %s)", a, b, first)


def prune_cache(d, pattern, keep):
    """フォルダ d の中の pattern に合うファイルを、古いものから消して keep 本にする(キャッシュの整理。失敗は黙って諦める。RS6 a-5a に analyze から)"""
    try:
        fs = sorted((os.path.getmtime(p), p) for p in glob.glob(os.path.join(glob.escape(d), pattern)))
        for _, p in fs[:-keep]:
            os.remove(p)
    except OSError:
        pass
