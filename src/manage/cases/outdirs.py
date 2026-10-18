# -*- coding: utf-8 -*-
"""④ 書き出し先を変えたあとの案件の繋ぎ直し(決定 3-37 の (r8o))と、入口の「調子」の「置き場所」の数。

移行の道具(文書を案件へ移す docmove・配信の記録を案件へ移す markmove)は消した(opt-manage 役割 4)。ここに残るのは通常機能だけ:
- relink_out_dir(data_path, out_dir): 入口が起動のたびに呼ぶ。今の書き出し先を OUT_DIRS_NAME に覚え、案件が見えない配信の case を、
  前の書き出し先の下の相対パスで今の書き出し先の下に付け替えられれば付け替える(題では探さない)。スイッチは無い。inplace では呼ばれない。
- relink(data_path, vid, folder): 手の繋ぎ直し(入口の画面の直す口からも呼べる)。.studio-id が配信の物で 採用.json にその配信があるときだけ。
- status(data_path, tx_dir): 「調子」の「置き場所」の 1 行の材料(見えない文書・見えない案件・繋ぎ直した本数)。何も無ければ None。

書き先: 覚える書き出し先と繋ぎ直した本数は data.json の隣(スタジオの作業データ)の OUT_DIRS_NAME。data.json の書き換えは flow/studiobook の set_cases。

コマンド(入口を終了してから。.flow.lock を取る):
    py -3.12 src/manage/cases/outdirs.py --relink <配信の id> <フォルダ>
"""
import argparse
import os
import sys

_SRC = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))   # cases -> manage -> src
if _SRC not in sys.path:   # コマンドで単独に動かすときも ytt・flow を読めるように(入口から読むときは入っている)
    sys.path.insert(0, _SRC)
from flow import casebook as _casebook, placement as _placement, studiobook as _studiobook  # noqa: E402
from ytt import casefiles as _cf, docloc as _docloc, errors as _errors, fsio as _fsio, names as _names, schemas as _schemas  # noqa: E402

OUT_DIRS_NAME = ".out-dirs.json"     # <スタジオの作業データ>/.out-dirs.json(data.json の隣)
OUT_DIRS_VERSION = 1
OUT_DIRS_KEEP = 5                    # 覚えておく書き出し先の数(新しい順)
OUT_DIRS_MAX = 256 * 1024
DATA_MAX = 256 * 2**20               # data.json を読む上限


# ---------------------------------------------------------------- data.json・覚える書き出し先
def read_data(path):
    """data.json の中身(dict。videos が dict)か None(無い・読めない・形が違う)"""
    d = _fsio.read_json_or(path, None, DATA_MAX, kind=dict, allow_nan=True)
    return d if isinstance(d, dict) and isinstance(d.get("videos"), dict) else None


def state_path(data_path):
    return os.path.join(os.path.dirname(data_path), OUT_DIRS_NAME)


def read_state(data_path):
    """覚えている書き出し先(outDirs)と繋ぎ直した本数(relinkedTotal)。無い・壊れている = {}"""
    return _fsio.read_json_or(state_path(data_path), {}, OUT_DIRS_MAX, kind=dict)


def _write_state(data_path, **kw):
    d = dict(read_state(data_path), **kw)
    d["version"] = OUT_DIRS_VERSION
    _fsio.write_json(state_path(data_path), d)


# ---------------------------------------------------------------- 繋ぎ直す((r8o))
def relink_problem(row, folder):
    """索引の行 row を folder に繋ぎ直せないなら理由の文、繋げるなら None(.studio-id がその配信の物・採用.json にその配信がある)"""
    why = _cf.problem(folder)
    if why:
        return why
    if _names.read_owner(folder) not in _casebook.owners(row):
        return "フォルダの持ち主(作業用/.studio-id)がこの配信の物でない"
    try:
        adopts = _cf.read(folder)[1]
    except _errors.ApiError as e:
        return e.message
    return None if row.get("id") in adopts["sources"] else "案件の採用の記録(採用.json)にこの配信が無い"


def relink(data_path, vid, folder, log=None):
    """索引の行 vid の case を folder にする(relink_problem が None のときだけ)。-> None(繋いだ)か理由の文"""
    log = log or print
    d = read_data(data_path)
    row = (d or {}).get("videos", {}).get(vid) if d else None
    if not isinstance(row, dict) or not row.get("case"):
        return "data.json に案件にした配信 %s がありません" % vid
    folder = os.path.normpath(os.path.abspath(folder))
    why = relink_problem(row, folder)
    if why:
        return why
    _studiobook.StudioBook(data_path).set_cases({vid: folder})
    log("配信 %s の案件を繋ぎ直しました: %s → %s" % (vid, row["case"], folder))
    return None


def relink_out_dir(data_path, out_dir, log=None):
    """起動のとき: 今の書き出し先を OUT_DIRS_NAME に覚え、案件が見えない索引の行を、前の書き出し先の下の相対パスで今の書き出し先の下に
    繋ぎ直せれば繋ぐ((r8o)。題で探さない)。-> 繋ぎ直した本数。data.json が無ければ何もしない"""
    log = log or (lambda msg: None)
    d = read_data(data_path)
    if d is None or not isinstance(out_dir, str) or not os.path.isabs(out_dir):
        return 0
    cur = os.path.normpath(out_dir)
    prev = [x for x in (read_state(data_path).get("outDirs") or []) if isinstance(x, str) and os.path.isabs(x)]
    olds = [x for x in prev if _fsio.norm_path(x) != _fsio.norm_path(cur)]
    moves = {}
    for vid, row in d["videos"].items():
        root = row.get("case") if isinstance(row, dict) else None
        if not isinstance(root, str) or not root or not _cf.problem(root):
            continue
        for old in olds:
            if not _under(root, old):
                continue
            new = os.path.normpath(os.path.join(cur, os.path.relpath(root, old)))
            if relink_problem(row, new) is None:
                moves[vid] = new
                log("書き出し先が変わったので、配信 %s の案件を繋ぎ直しました: %s → %s" % (vid, root, new))
                break
    n = _studiobook.StudioBook(data_path).set_cases(moves) if moves else 0
    keep = [cur] + [x for x in prev if _fsio.norm_path(x) != _fsio.norm_path(cur)]
    if keep[:OUT_DIRS_KEEP] != prev[:OUT_DIRS_KEEP] or n:
        r = read_state(data_path)
        _write_state(data_path, outDirs=keep[:OUT_DIRS_KEEP], relinkedTotal=int(r.get("relinkedTotal") or 0) + n)
    return n


def _under(path, base):
    """path が base の下か(文字で比べる = 見えないドライブ・ネットワーク上のパスを調べない)"""
    p, b = os.path.normcase(os.path.normpath(path)), os.path.normcase(os.path.normpath(base))
    return p.startswith(b.rstrip("\\/") + os.sep)


# ---------------------------------------------------------------- 入口の「調子」の「置き場所」
_data_cache = _fsio.StampCache()


def _unseen_cases(data_path):
    """案件が見えない配信の数(索引の case の根のうち、今は案件として読めない物)"""
    def load(p):
        d = read_data(p)
        return [row["case"] for row in (d or {}).get("videos", {}).values() if isinstance(row, dict) and isinstance(row.get("case"), str) and row["case"]] \
            if d else []
    roots = _data_cache.get(data_path, load) or []
    return sum(1 for r in roots if _cf.problem(r))


def status(data_path, tx_dir=None):
    """「調子」の「置き場所」の 1 行の材料: 見えない文書の数(tx_dir = 文書の作業データの根。None なら数えない)・見えない案件の数・
    繋ぎ直した本数(累計)。何も無ければ None(行を出さない)"""
    docs = _docloc.unseen(tx_dir) if tx_dir else {"count": 0, "reasons": {}}
    cases = _unseen_cases(data_path)
    relinked = int(read_state(data_path).get("relinkedTotal") or 0)
    if not docs["count"] and not cases and not relinked:
        return None
    return {"docs": docs["count"], "docReasons": docs["reasons"], "cases": cases, "relinked": relinked}


# ---------------------------------------------------------------- コマンド
def main(argv=None):
    ap = argparse.ArgumentParser(prog="outdirs.py", description="書き出し先を変えたあとの案件の繋ぎ直し(入口を終了してから)")
    ap.add_argument("--relink", nargs=2, required=True, metavar=("配信のid", "フォルダ"),
                    help="索引の case を繋ぎ直す(.studio-id が一致して 採用.json にその配信があるときだけ)")
    a = ap.parse_args(argv)
    try:
        lock = _placement.acquire(None)
    except _placement.LockBusy as e:
        print("入口(または別のコマンド)が同じ作業データを使っています(pid %s)。入口を「すべて終了」してから流してください" % e.info.get("pid"))
        return 4
    try:
        why = relink(_placement.studio_data(), a.relink[0], a.relink[1])
        print("繋ぎ直しました" if why is None else "繋ぎ直しませんでした: %s" % why)
        return 0 if why is None else 1
    finally:
        _placement.release(lock)


if __name__ == "__main__":
    sys.exit(main())
