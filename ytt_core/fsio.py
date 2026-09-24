"""ファイルの読み書き(スタジオの common.atomic_write と、文字起こしの atomic_write / pipeline_io の書き込みを1つにしたもの)。"""
import json
import os
import tempfile
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


def _unlink_quiet(path):
    try:
        os.unlink(path)
    except OSError:
        pass   # 後片付けの失敗で、本来のエラーを隠さない


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
        _unlink_quiet(tmp)
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
        _unlink_quiet(tmp)
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
            _unlink_quiet(tmp)


def write_json(path, obj, indent=2):
    """UTF-8(BOM なし)の JSON を原子的に書く(受け渡しのファイルの約束。docs/pipeline.md の 1)。"""
    atomic_write(path, (json.dumps(obj, ensure_ascii=False, indent=indent) + ("\n" if indent is not None else "")).encode("utf-8"))


def _reject_constant(name):
    raise ValueError("NaN / Infinity は JSON として受け付けません: %s" % name)


def read_json_file(path, max_bytes):
    """UTF-8(BOM があっても可)の JSON を読む。max_bytes を超えるファイル・NaN / Infinity を含むものは ValueError。
    他のツール・他人が作ったかもしれないファイルを読むときに使う(巨大なファイルで固まらないように)。"""
    with open(path, "rb") as f:
        raw = f.read(max_bytes + 1)
    if len(raw) > max_bytes:
        raise ValueError("ファイルが大きすぎます")
    return json.loads(raw.decode("utf-8-sig"), parse_constant=_reject_constant)


def is_network_path(p):
    """ネットワーク上のパス(\\\\サーバー\\共有\\… や //サーバー/…、\\\\?\\UNC\\…)か。
    Windows でこうしたパスの存在を確かめるだけで、そのサーバーへ接続して資格情報(NTLM のハッシュ)を送ってしまうため、
    利用者が押したボタン以外(URL から自動で呼ばれる処理、他人が作ったファイルの中のパス)では調べない。"""
    return str(p or "").replace("/", "\\").startswith("\\\\")
