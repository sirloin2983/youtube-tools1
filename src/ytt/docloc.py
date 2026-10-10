"""文字起こしの文書の置き場所を引く口(文書 id → フォルダ。RS8 B-2)。

文書 <id>.json と横のファイル(DOC_SUFFIXES)・履歴 .hist/<id>/・控え .bak/ は、ふつうは作業データの transcripts
(workdata.TX_DIR)にある。案件のフォルダの 作業用 に置いた文書だけ、transcripts/<id>.loc.json(索引)がその場所を持つ。
索引が無ければ今までどおり TX_DIR なので、`S.TX_DIR = …` で置き場所を差し替えるテストはそのまま動く。

- 索引は文書ごとに 1 ファイル(壊れても、その 1 本が TX_DIR に戻るだけで済む)。書くのは place・消すのは unplace
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


def _folder_problem(tid, folder):
    """置き場所に使えないなら理由の文字列、使えるなら None(ネットワークのパスは名前だけで断り、ファイルには触らない)"""
    if not isinstance(folder, str) or not folder or not os.path.isabs(folder):
        return "絶対パスではない"
    if _remote(folder):
        return "ネットワーク上のパス"
    if os.path.basename(os.path.normpath(folder)) != _schemas.WORK_DIR:
        return "フォルダの名前が %s ではない" % _schemas.WORK_DIR
    if not os.path.isfile(os.path.join(folder, tid + ".json")):
        return "文書が無い"
    return None


def _fall_back(root, tid, why):
    key = (root, tid, why)
    if key not in _warned:
        _warned.add(key)
        log.warning("文書 %s の索引を使わず transcripts から読みます(%s)", tid, why)


def placed(tid, data_dir=None):
    """索引が指す 作業用 のフォルダ(確かめて使えるときだけ)か None(索引が無い・壊れている・使えない)"""
    path = loc_path(tid, data_dir)
    if not os.path.isfile(path):
        return None
    d = _fsio.read_json_or(path, None, LOC_MAX_BYTES, kind=dict)
    if d is None or d.get("version") != LOC_VERSION or d.get("id") != tid:
        _fall_back(tx_root(data_dir), tid, "索引が読めない")
        return None
    why = _folder_problem(tid, d.get("dir"))
    if why:
        _fall_back(tx_root(data_dir), tid, why)
        return None
    return os.path.normpath(d["dir"])


def doc_dir(tid, data_dir=None):
    """文書のフォルダ: 索引が使えればその 作業用、無ければ根(TX_DIR か <data_dir>/transcripts)"""
    return placed(tid, data_dir) or tx_root(data_dir)


def doc_file(tid, suffix, data_dir=None):
    """文書と横のファイルのパス(suffix は DOC_SUFFIXES のどれか。違えば ValueError)。文書ごとに同じフォルダ"""
    if suffix not in DOC_SUFFIXES:
        raise ValueError("文書の横のファイルの名前ではありません: %r" % (suffix,))
    return os.path.join(doc_dir(tid, data_dir), tid + suffix)


def hist_dir(tid, data_dir=None):
    """履歴のフォルダ <置き場所>/.hist/<id>"""
    return os.path.join(doc_dir(tid, data_dir), HIST_DIR, tid)


def bak_dir(tid, data_dir=None):
    """控えのフォルダ <置き場所>/.bak(同じ置き場所の文書で共有。中のファイル名が <id>. で始まる)"""
    return os.path.join(doc_dir(tid, data_dir), BAK_DIR)


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


def unplace(tid, data_dir=None):
    """索引を消して置き場所を根に戻す(文書のファイルは動かさない)。-> 索引があったか"""
    path = loc_path(tid, data_dir)
    had = os.path.isfile(path)
    _fsio.unlink_quiet(path)
    return had
