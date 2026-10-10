"""文字起こしの文書の置き場所を引く口(文書 id → フォルダ。RS8 B-2)。

文書 <id>.json と横のファイル(DOC_SUFFIXES)・履歴 .hist/<id>/・控え .bak/ は、ふつうは作業データの transcripts
(workdata.TX_DIR)にある。案件のフォルダの 作業用 に置いた文書だけ、transcripts/<id>.loc.json(索引)がその場所を持つ。
索引が無ければ今までどおり TX_DIR なので、`S.TX_DIR = …` で置き場所を差し替えるテストはそのまま動く。

- 索引は文書ごとに 1 ファイル(壊れても、その 1 本が TX_DIR に戻るだけで済む)。書くのは place・消すのは unplace。
  新しい文書を案件に置くのは place_new(本体を書いてから索引。だめなら TX_DIR。RS8 B2-2)
- 書く側は for_write=True で引く: 索引があるのに使えない(ドライブが外れたなど)ときは TX_DIR に落とさず ApiError(doc_unseen・503)で断る
  (TX_DIR に別の文書が生まれて枝分かれしないように)。読む側は TX_DIR に落ちる(無ければ呼び手が 404)。見えない数は unseen
- 索引の場所は使う前に毎回確かめる: 絶対パス・ネットワーク上でない(UNC・割り当てたネットワークドライブ。存在を調べるだけで
  そのサーバーへ資格情報を送ってしまうため、触る前に断る)・フォルダの名前が 作業用・そこに <id>.json がある。
  どれかがだめなら TX_DIR に落とし、理由をログに 1 行(同じ文書・同じ理由は 1 回だけ)
- 文書 id は schemas.TID_RE(12 文字の 16 進)で検査する(id にパスの区切りや .. を入れて外のフォルダを指させない)。だめなら ValueError
- TX_DIR は呼ぶたびに workdata から読む(写さない)。data_dir を渡すと <data_dir>/transcripts を根にする
  (学習のもとを別の作業データから読むコマンドが、TX_DIR を一時的に差し替えずに済むように)
- 一時ファイル .tmp・途中の .resume・書き込みの確かめは文書ではないので、ここは引かない(TX_DIR のまま)
"""
import logging
import os

from . import errors as _errors
from . import fsio as _fsio
from . import schemas as _schemas
from . import workdata as _workdata

log = logging.getLogger("tx")   # 編集の記録(serve.log)と同じ logger

LOC_SUFFIX = ".loc.json"   # 索引 transcripts/<id>.loc.json({"version": 1, "id": <id>, "dir": <作業用 の絶対パス>})
LOC_VERSION = 1
LOC_MAX_BYTES = 64 * 1024
HIST_DIR = ".hist"         # 履歴 <置き場所>/.hist/<id>/<時刻>.json(human/proof/store)
BAK_DIR = ".bak"           # 機械が書き換える前の控え <置き場所>/.bak/<id>.pre-<種類>.json(human/proof/store・manage/cases/relink)

# 文書と同じ id で持つファイルの名前の終わり(文書を消す・移すときはこの全部を一緒に)。先頭が文書そのもの。
# 持ち主: .edit・.edit.broken = human/proof/store・.words = ytt/txwords・.asr = pipeline/transcribe/records・.diar = pipeline/transcribe/diarize・
# .alt = human/proof/alt・.ytcap = human/proof/ytcap・.llm = pipeline/transcribe/llm・.over = human/proof/overrides・
# .<段>.key = flow/keys(文書の段 transcribe・post・diar)。名前を足したら、ここと文書を消す所(editor/serve の _delete)の両方へ
DOC_KEY_STAGES = ("transcribe", "post", "diar")
DOC_SUFFIXES = (".json", ".edit.json", ".edit.broken.json", ".words.json", ".asr.json", ".diar.json", ".alt.json",
                ".ytcap.json", ".llm.json", ".over.json") + tuple("." + st + _schemas.KEY_SUFFIX for st in DOC_KEY_STAGES)

_warned = set()   # (根, id, 理由) をログに出した印(読むたびに同じ行を書かない)


def _check_tid(tid):
    if not isinstance(tid, str) or not _schemas.TID_RE.match(tid):
        raise ValueError("文書の id が正しくありません: %r" % (tid,))
    return tid


def tx_root(data_dir=None):
    """文書の根: data_dir があれば <data_dir>/transcripts、無ければ今の workdata.TX_DIR"""
    return os.path.join(data_dir, "transcripts") if data_dir else _workdata.TX_DIR


def loc_path(tid, data_dir=None):
    """索引のファイル <根>/<id>.loc.json"""
    return os.path.join(tx_root(data_dir), _check_tid(tid) + LOC_SUFFIX)


def _remote(p):
    return _fsio.is_network_path(p) or _fsio.is_remote_drive(p)


def check_folder(folder):
    """文書の置き場所(作業用)の形として使えないなら理由の文字列、使えるなら None: 絶対パス・ネットワーク上でない・名前が 作業用。
    ネットワークのパスは名前だけで断り、ファイルには触らない(文書があるかは見ない = 新しい文書を置く前に place_new が使う)"""
    if not isinstance(folder, str) or not folder or not os.path.isabs(folder):
        return "絶対パスではない"
    if _remote(folder):
        return "ネットワーク上のパス"
    if os.path.basename(os.path.normpath(folder)) != _schemas.WORK_DIR:
        return "フォルダの名前が %s ではない" % _schemas.WORK_DIR
    return None


def _folder_problem(tid, folder):
    """置き場所に使えないなら理由の文字列、使えるなら None(check_folder + そこに <id>.json がある)"""
    why = check_folder(folder)
    if why:
        return why
    if not os.path.isfile(os.path.join(folder, tid + ".json")):
        return "文書が無い"
    return None


def _fall_back(root, tid, why):
    key = (root, tid, why)
    if key not in _warned:
        _warned.add(key)
        log.warning("文書 %s の索引を使わず transcripts から読みます(%s)", tid, why)


def _loc_state(tid, data_dir=None):
    """索引の状態 -> (使える 作業用 のフォルダか None, 使えない理由か None)。索引が無ければ (None, None)(ログは書かない)"""
    path = loc_path(tid, data_dir)
    if not os.path.isfile(path):
        return None, None
    d = _fsio.read_json_or(path, None, LOC_MAX_BYTES, kind=dict)
    if d is None or d.get("version") != LOC_VERSION or d.get("id") != tid:
        return None, "索引が読めない"
    why = _folder_problem(tid, d.get("dir"))
    return (None, why) if why else (os.path.normpath(d["dir"]), None)


def placed(tid, data_dir=None):
    """索引が指す 作業用 のフォルダ(確かめて使えるときだけ)か None(索引が無い・壊れている・使えない)"""
    got, why = _loc_state(tid, data_dir)
    if why:
        _fall_back(tx_root(data_dir), tid, why)
    return got


UNSEEN_CODE = "doc_unseen"   # 書きを断ったときの ApiError の code(索引はあるが置き場所が見えない)


def doc_dir(tid, data_dir=None, for_write=False):
    """文書のフォルダ: 索引が使えればその 作業用、無ければ根(TX_DIR か <data_dir>/transcripts)。
    for_write=True(書く側): 索引があるのに使えない(ドライブが外れた・フォルダが消えた・索引が壊れた)ときは根に落とさず
    ApiError(UNSEEN_CODE・503)で断る(TX_DIR に別の文書が生まれて枝分かれするのを防ぐ)。読む側(既定)は今までどおり根に落ちる"""
    got, why = _loc_state(tid, data_dir)
    if why:
        if for_write:
            raise _errors.ApiError(UNSEEN_CODE, "文書の置き場所(案件のフォルダ)が見えません(%s)。ドライブをつないでから、もう一度試してください" % why,
                                   503, {"tid": tid, "reason": why})
        _fall_back(tx_root(data_dir), tid, why)
    return got or tx_root(data_dir)


def doc_file(tid, suffix, data_dir=None, for_write=False):
    """文書と横のファイルのパス(suffix は DOC_SUFFIXES のどれか。違えば ValueError)。文書ごとに同じフォルダ。for_write は doc_dir と同じ"""
    if suffix not in DOC_SUFFIXES:
        raise ValueError("文書の横のファイルの名前ではありません: %r" % (suffix,))
    return os.path.join(doc_dir(tid, data_dir, for_write), tid + suffix)


def hist_dir(tid, data_dir=None, for_write=False):
    """履歴のフォルダ <置き場所>/.hist/<id>。for_write は doc_dir と同じ"""
    return os.path.join(doc_dir(tid, data_dir, for_write), HIST_DIR, tid)


def bak_dir(tid, data_dir=None, for_write=False):
    """控えのフォルダ <置き場所>/.bak(同じ置き場所の文書で共有。中のファイル名が <id>. で始まる)。for_write は doc_dir と同じ"""
    return os.path.join(doc_dir(tid, data_dir, for_write), BAK_DIR)


def iter_tids(data_dir=None):
    """文書の id の一覧(並べ替え済み・重複なし): 根の <id>.json と、使える索引の和。
    索引はあるが使えない(ドライブが外れているなど)文書は、根に文書があるときだけ出す(読めない id を一覧に出さない)"""
    root = tx_root(data_dir)
    try:
        names = os.listdir(root) if root else []
    except OSError:
        names = []
    out = set()
    for n in names:
        if n.endswith(LOC_SUFFIX):
            tid = n[:-len(LOC_SUFFIX)]
            if _schemas.TID_RE.match(tid) and placed(tid, data_dir):
                out.add(tid)
        elif n.endswith(".json") and _schemas.TID_RE.match(n[:-5]):
            out.add(n[:-5])
    return sorted(out)


def unseen(data_dir=None):
    """索引はあるが使えない(ドライブが外れている・フォルダが消えた・索引が壊れている など)文書の数と理由
    -> {"count": 本数, "reasons": {理由: 本数}}(入口の調子の 1 行に出す。数えるだけ = ログは書かない・ファイルは読むだけ)"""
    root = tx_root(data_dir)
    try:
        names = os.listdir(root) if root else []
    except OSError:
        names = []
    reasons = {}
    for n in names:
        tid = n[:-len(LOC_SUFFIX)] if n.endswith(LOC_SUFFIX) else ""
        if not _schemas.TID_RE.match(tid):
            continue
        why = _loc_state(tid, data_dir)[1]
        if why:
            reasons[why] = reasons.get(why, 0) + 1
    return {"count": sum(reasons.values()), "reasons": reasons}


def place(tid, folder, data_dir=None):
    """文書の置き場所を folder にする(索引を原子的に書く)。folder は <id>.json がもうある 作業用 のフォルダ
    (文書を書いてから索引を書く = 途中で落ちても、索引が文書の無い場所を指さない)。根そのものを渡すと unplace と同じ。
    使えない folder は ValueError(理由つき)。-> 索引のパス(根に戻したときは None)"""
    _check_tid(tid)
    root = tx_root(data_dir)
    if isinstance(folder, str) and folder and root and _fsio.norm_path(folder) == _fsio.norm_path(root):
        unplace(tid, data_dir)
        return None
    why = _folder_problem(tid, folder)
    if why:
        raise ValueError("文書 %s をそこに置けません(%s): %s" % (tid, why, folder))
    path = loc_path(tid, data_dir)
    os.makedirs(root, exist_ok=True)
    _fsio.write_json(path, {"version": LOC_VERSION, "id": tid, "dir": os.path.normpath(os.path.abspath(folder))})
    _warned.difference_update({k for k in _warned if k[0] == root and k[1] == tid})
    return path


def place_new(tid, folder, write, data_dir=None):
    """新しい文書を作るときの 1 か所(RS8 B2-2): folder(作業用。None なら今までどおり)に本体を書いてから索引を書く。
    write(path) = <id>.json を原子的に書く呼び手の関数(中身は呼び手が持つ)。-> 書いた本体のパス。
    - folder が None・形が使えない(check_folder)・案件の根(folder の親)が無い・この id が既に文書か索引を持つ → 今までどおり
      doc_file(tid, ".json", for_write=True) に書く(作業用は作らない。根を作らない = 外れたドライブに新しいフォルダを作らない)
    - 作業用 が無ければ作る → <作業用>/<id>.json を書く → place。書けない・place が落ちた(OSError・ValueError)ときは
      作業用 の本体を消して根(TX_DIR)に書き直す(ログ 1 行。新しい文書は失わない)"""
    _check_tid(tid)
    root = tx_root(data_dir)
    if folder is not None:
        why = check_folder(folder)
        if not why and not os.path.isdir(os.path.dirname(os.path.normpath(folder))):
            why = "案件のフォルダが無い"
        if not why and (os.path.exists(loc_path(tid, data_dir)) or os.path.exists(os.path.join(root, tid + ".json"))):
            why = "この id の文書が既にある"
        if why:
            log.warning("新しい文書 %s を案件に置けません(%s)。transcripts に置きます: %s", tid, why, folder)
            folder = None
    if folder is None:
        path = doc_file(tid, ".json", data_dir, for_write=True)
        write(path)
        return path
    folder = os.path.normpath(os.path.abspath(folder))
    path = os.path.join(folder, tid + ".json")
    try:
        os.makedirs(folder, exist_ok=True)
        write(path)
        place(tid, folder, data_dir)
        return path
    except (OSError, ValueError) as e:
        _fsio.unlink_quiet(path)
        log.warning("新しい文書 %s を案件に置けませんでした(%s %s)。transcripts に書き直します: %s", tid, e.__class__.__name__, str(e)[:150], folder)
    _fsio.unlink_quiet(loc_path(tid, data_dir))
    path = os.path.join(root, tid + ".json")
    os.makedirs(root, exist_ok=True)
    write(path)
    return path


def unplace(tid, data_dir=None):
    """索引を消して置き場所を根に戻す(文書のファイルは動かさない)。-> 索引があったか"""
    path = loc_path(tid, data_dir)
    had = os.path.isfile(path)
    _fsio.unlink_quiet(path)
    return had
