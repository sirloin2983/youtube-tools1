#!/usr/bin/env python3
"""評価データの取り込みチェック(あなた側。友人用 文字起こし簡易版の計画 L5。git の履歴(679ff01 以前)の docs/plan/friend-lite-plan.md)。

    py -3.10 dev/eval_import.py <zip か zip の入ったフォルダ> [...] [--dest フォルダ] [--force]

友人が送った「送る用ファイル」(日付_配信者_作業ID.zip。中身は src/ytt_core/evaldata.py の FILES)を確かめて、作業データの外の置き場所へ展開する。
弾く判定の最終版(git の履歴(679ff01 以前)の docs/design/briefs/friend-transcribe-lite/DESIGN_BRIEF.md の「文字起こしルールと評価データ」「セキュリティ」)。

- 置き場所(--dest。既定 %LOCALAPPDATA%\\youtube-tools\\eval-intake。Windows 以外は ~/.local/share/youtube-tools/eval-intake):
    works/<作業ID>/      … 展開した5つのファイル + check.json(判定・振り分け)
    rejected/<zip名>.json … 断った zip の理由と sha256(展開しない)
    routing.json          … 振り分け {"noTrain": [名前, ...]}(無ければ既定で作る。配信者か出演者が入っていれば学習に入れない)
    index.jsonl           … 1つの zip につき1行の記録
    .staging/             … 途中の置き場所(終われば消す)
- リポジトリの中・git の作業フォルダの中には置かない(Public のリポジトリに評価データを入れないため。realpath で比べる)
- 届いた zip は信用しない: まず置き場所の中へ写し(写しながら sha256。途中で消えても・書き換えられても、確かめたものと展開するものが同じ)、
  evaldata.check_zip → extract_zip。JSON は形式の名前と作業ID が zip の名前と合うか・絶対パスが残っていないかを確かめる
- データは消さない: 行・作業を外すのは check.json の印と理由だけ。元の zip も消さない(音声を二重に持たないため写しは残さず、sha256 を記録する)
- 同じ作業ID がすでにあれば「重複」で飛ばす。--force なら新しい方を途中の置き場所に用意してから入れ替える(断ったら前のまま)
- 終了コード: 0 = 断ったもの・失敗が無い、1 = 1つでも断った・失敗した、2 = 置き場所・振り分けの設定が使えない
"""
import argparse
import hashlib
import json
import os
import re
import shutil
import sys
import unicodedata
import uuid

HERE = os.path.dirname(os.path.abspath(__file__))
REPO = os.path.dirname(HERE)   # リポジトリ直下(「リポジトリの中には置けない」の判定に使う)
SRC = os.path.join(REPO, "src")   # ツールと ytt_core の置き場所
if SRC not in sys.path:
    sys.path.insert(0, SRC)
from eval.tools import evaldata as ev  # noqa: E402
from ytt import fsio  # noqa: E402
from ytt.schemas import iso_now as _now  # noqa: E402

CHECK_FORMAT = "youtube-tools-eval-check/v1"       # check.json の形式の名前
REJECT_FORMAT = "youtube-tools-eval-reject/v1"     # rejected/*.json の形式の名前
INDEX_FORMAT = "youtube-tools-eval-index/v1"
DEFAULT_ROUTING = {"noTrain": ["如月れん"]}
ZIP_LIMIT = sum(ev.MAX_BYTES.values()) + 16 * 1024 * 1024   # 届いた zip そのものの大きさの上限(中身の上限の合計 + zip の見出しの余裕)
NAME_LIMIT = 40           # 配信者・出演者の名前の長さの上限(記録に残す分)


class DestError(Exception):
    """置き場所・振り分けの設定が使えない(1つも取り込まずに止める)"""


# ---------------------------------------------------------------- 置き場所

def default_dest():
    base = os.environ.get("LOCALAPPDATA") if os.name == "nt" else ""
    if not base:
        base = os.environ.get("XDG_DATA_HOME") or os.path.join(os.path.expanduser("~"), ".local", "share")
    return os.path.join(base, "youtube-tools", "eval-intake")


def _norm(p):
    return os.path.normcase(os.path.realpath(p))


def _git_root(path):
    """path(まだ無くてもよい)か、その上のフォルダに .git があればそのフォルダ。無ければ None"""
    cur = _norm(path)
    while True:
        if os.path.lexists(os.path.join(cur, ".git")):
            return cur
        up = os.path.dirname(cur)
        if up == cur:
            return None
        cur = up


def check_dest(dest):
    """置き場所を確かめて realpath を返す。リポジトリ・git の作業フォルダの中なら DestError(フォルダは作らない)"""
    if not dest:
        raise DestError("置き場所が空です")
    real = os.path.realpath(os.path.abspath(dest))
    if fsio.is_inside(real, REPO):   # 比べる相手(リポジトリ)はローカル。ネットワーク上の置き場所はここでは False だが、リポジトリの中ではないので結果は同じ
        raise DestError("リポジトリの中には置けません(評価データを Public のリポジトリに入れないため): %s" % real)
    g = _git_root(real)
    if g:
        raise DestError("git の作業フォルダの中には置けません(%s): %s" % (g, real))
    if os.path.lexists(real) and not os.path.isdir(real):
        raise DestError("フォルダではありません: %s" % real)
    return real


def _subdir(root, name):
    """root の直下のフォルダ(無ければ作る)。リンク・ジャンクションで外へ向いていたら DestError(たどらない)"""
    p = os.path.join(root, name)
    if os.path.islink(p):
        raise DestError("リンクになっています(たどりません): %s" % p)
    if not os.path.lexists(p):
        os.mkdir(p)
    if not os.path.isdir(p) or _norm(p) != os.path.normcase(os.path.join(_norm(root), name)):
        raise DestError("置き場所の外を指しています: %s" % p)
    return p


def prepare_dest(dest):
    """置き場所と中のフォルダを用意する -> realpath。routing.json が無ければ既定で作る"""
    real = check_dest(dest)
    os.makedirs(real, exist_ok=True)
    for name in ("works", "rejected", ".staging"):
        _subdir(real, name)
    rp = os.path.join(real, "routing.json")
    if os.path.islink(rp):
        raise DestError("routing.json がリンクになっています")
    if not os.path.exists(rp):
        _write_json(rp, DEFAULT_ROUTING)
    return real


def load_routing(root):
    """routing.json -> 学習に入れない名前の集合。読めない・形が違えば DestError(振り分けを決められないので取り込まない)"""
    rp = os.path.join(root, "routing.json")
    obj = fsio.read_json_or(rp, None, 1024 * 1024)
    if obj is None:
        raise DestError("routing.json を読めません(無い・大きすぎる・JSON ではない)")
    names = obj.get("noTrain") if isinstance(obj, dict) else None
    if not isinstance(names, list) or not all(isinstance(n, str) for n in names):
        raise DestError("routing.json の形が違います(\"noTrain\": [名前, ...])")
    return {_name_key(n) for n in names if n.strip()}


def _name_key(s):
    return unicodedata.normalize("NFKC", s).strip().casefold()


def _write_json(path, obj):
    fsio.write_json(path, obj, indent=1)


# ---------------------------------------------------------------- 1つの zip

def _copy_hash(src, dst):
    """src を dst へ写しながら sha256 -> (sha256, 大きさ)。上限を超えたら ValueError。消えたら OSError"""
    h, n = hashlib.sha256(), 0
    with open(src, "rb") as fi, open(dst, "wb") as fo:
        while True:
            chunk = fi.read(1024 * 1024)
            if not chunk:
                break
            n += len(chunk)
            if n > ZIP_LIMIT:
                raise ValueError("zip が大きすぎます(上限 %d バイト)" % ZIP_LIMIT)
            h.update(chunk)
            fo.write(chunk)
    return h.hexdigest(), n


def _read_part(work, name):
    with open(os.path.join(work, name), "rb") as f:
        data = f.read(ev.MAX_BYTES[name] + 1)
    if len(data) > ev.MAX_BYTES[name]:
        raise ev.BundleError("%s が大きすぎます" % name)
    return data


def _clean_name(v):
    return re.sub(r"[\x00-\x1f\x7f]", "", unicodedata.normalize("NFC", v)).strip()[:NAME_LIMIT] if isinstance(v, str) else ""


def validate_parts(work, work_id):
    """展開した中身を読んで確かめる -> (meta, final, asr_raw, edits, 問題の一覧)"""
    problems = []
    try:
        meta = ev.read_json_bytes(_read_part(work, "meta.json"), "meta.json")
        final = ev.read_json_bytes(_read_part(work, "final.json"), "final.json")
        asr_raw = ev.read_json_bytes(_read_part(work, "asr_raw.json"), "asr_raw.json")
        edits = ev.read_edits(_read_part(work, "edits.jsonl"))
    except (ev.BundleError, OSError) as e:
        return None, None, None, None, [str(e)]
    for name, obj in (("meta.json", meta), ("final.json", final), ("asr_raw.json", asr_raw)):
        if obj.get("format") != ev.FORMAT:
            problems.append("%s の形式が違います: %r" % (name, str(obj.get("format"))[:60]))
        if obj.get("workId") != work_id:
            problems.append("%s の作業ID が zip の名前と違います: %r" % (name, str(obj.get("workId"))[:40]))
        for where, s in ev.find_abs_paths(obj)[:3]:
            problems.append("絶対パスが残っている: %s の %s" % (name, where or "(先頭)"))
    rows, segs = final.get("rows"), asr_raw.get("segments")
    if not isinstance(rows, list) or not all(isinstance(r, dict) for r in rows):
        problems.append("final.json の rows の形が違います")
    if segs is not None and (not isinstance(segs, list) or not all(isinstance(s, dict) for s in segs)):
        problems.append("asr_raw.json の segments の形が違います")
    if not isinstance(meta.get("performers", []), list):
        problems.append("meta.json の performers の形が違います")
    return meta, final, asr_raw, edits, problems


def routing_of(meta, final, no_train):
    """学習に入れるか -> (入れるか, 理由の一覧)。配信者・出演者(meta)と確認済みの行の話者(final)を noTrain と比べる"""
    names = [_clean_name(meta.get("streamer"))] + [_clean_name(p) for p in meta.get("performers") or []]
    names += [_clean_name(r.get("speaker")) for r in final.get("rows") or [] if r.get("checked")]
    hit = []
    for n in names:
        if n and _name_key(n) in no_train and n not in hit:
            hit.append(n)
    return (not hit), ["学習に入れない人が出ています: %s" % n for n in hit]


def import_zip(path, dest, force=False, no_train=None):
    """1つの zip を取り込む -> 結果の dict {"result": imported|duplicate|rejected|error, "zipName", "workId", "reasons", ...}。
    dest は prepare_dest 済みでなくてもよい(ここで用意する)。no_train を渡さなければ routing.json を読む"""
    root = prepare_dest(dest)
    if no_train is None:
        no_train = load_routing(root)
    zname = os.path.basename(path)
    res = {"zipName": zname, "workId": None, "result": "error", "reasons": [], "sha256": None, "at": _now()}
    work_id = ev.work_id_of(zname)
    target = os.path.join(root, "works", work_id) if work_id else None
    if work_id and os.path.lexists(target) and not force:
        res.update(workId=work_id, result="duplicate", reasons=["同じ作業ID がすでに取り込まれています(入れ替えるなら --force)"])
        return _finish(root, res)
    stage = os.path.join(root, ".staging", uuid.uuid4().hex)
    os.mkdir(stage)
    try:
        incoming = os.path.join(stage, "incoming.zip")
        try:
            res["sha256"], res["size"] = _copy_hash(path, incoming)
        except ValueError as e:
            return _reject(root, res, [str(e)])
        except OSError as e:   # 途中で消えた・読めない(断ったのではなく失敗)
            res["reasons"] = ["zip を読めません: %s" % e]
            return _finish(root, res)
        if not work_id:
            return _reject(root, res, ["zip の名前から作業ID が分かりません(日付_配信者_作業ID.zip。作業ID は 12 文字の 0-9a-f)"])
        res["workId"] = work_id
        _ok, problems = ev.check_zip(incoming)
        if problems:
            return _reject(root, res, problems)
        work = os.path.join(stage, "work")
        try:
            ev.extract_zip(incoming, work)
        except (ev.BundleError, OSError) as e:
            return _reject(root, res, ["展開できません: %s" % e])
        os.unlink(incoming)
        meta, final, asr_raw, edits, problems = validate_parts(work, work_id)
        if problems:
            return _reject(root, res, problems)
        try:
            judged = ev.judge(final, asr_raw, edits)
        except (TypeError, ValueError, AttributeError, KeyError) as e:
            return _reject(root, res, ["判定できません(中身の形が違います): %s" % e])
        train, train_reasons = routing_of(meta, final, no_train)
        if not judged["work"]["use"]:
            train = False
            train_reasons.append("作業ごと外しています(評価にも学習にも使わない)")
        usable = sum(1 for c in judged["rows"] if c["use"]) if judged["work"]["use"] else 0
        check = {"format": CHECK_FORMAT, "checkedAt": _now(), "zipName": zname, "sha256": res["sha256"], "size": res.get("size"),
                 "workId": work_id, "rulesVersion": meta.get("rulesVersion"), "formatVersion": meta.get("formatVersion"),
                 "streamer": _clean_name(meta.get("streamer")), "performers": [_clean_name(p) for p in meta.get("performers") or []][:20],
                 "judge": {"work": judged["work"], "rows": judged["rows"], "notes": judged["notes"]},
                 "rows": {"total": len(judged["rows"]), "usable": usable}, "train": train, "trainReasons": train_reasons,
                 "replaced": bool(force and os.path.lexists(target))}
        if check["rulesVersion"] != ev.RULES_VERSION or check["formatVersion"] != ev.FORMAT_VERSION:
            check["versionNote"] = "ルール・形式の版が今と違います(今は rulesVersion %d・formatVersion %d)" % (ev.RULES_VERSION, ev.FORMAT_VERSION)
        _write_json(os.path.join(work, "check.json"), check)
        _install(root, stage, work, target)
        res.update(result="imported", use=judged["work"]["use"], usable=usable, rows=len(judged["rows"]), train=train,
                   reasons=judged["work"]["reasons"] + train_reasons, replaced=check["replaced"])
        return _finish(root, res)
    finally:
        shutil.rmtree(stage, ignore_errors=True)


def _install(root, stage, work, target):
    """用意した work を works/<作業ID> へ。前のものがあれば途中の置き場所へ退かしてから入れ替え、最後に消す(--force)"""
    old = None
    if os.path.lexists(target):
        if os.path.islink(target) or _norm(target) != os.path.normcase(os.path.join(_norm(os.path.join(root, "works")), os.path.basename(target))):
            raise DestError("works の中の %s がリンクになっています" % os.path.basename(target))
        old = os.path.join(stage, "old")
        os.replace(target, old)
    try:
        os.replace(work, target)
    except OSError:
        if old:   # 入れ替えに失敗したら前のものを戻す
            os.replace(old, target)
        raise
    # old は stage の中なので、import_zip の最後にまとめて消える


def _reject(root, res, problems):
    res.update(result="rejected", reasons=list(problems))
    rec = {"format": REJECT_FORMAT, "checkedAt": res["at"], "zipName": res["zipName"], "workId": res.get("workId"),
           "sha256": res.get("sha256"), "size": res.get("size"), "problems": list(problems)}
    base = ev.safe_part(res["zipName"], 120)
    p = os.path.join(root, "rejected", base + ".json")
    if os.path.lexists(p):   # 同じ名前で中身の違う zip が来たら、前の記録を残して別の名前にする
        prev = fsio.read_json_or(p, None, 1024 * 1024, dict)
        same = prev is not None and prev.get("sha256") == rec["sha256"]
        if not same or os.path.islink(p):
            p = os.path.join(root, "rejected", "%s.%s.json" % (base, (rec["sha256"] or uuid.uuid4().hex)[:12]))
    _write_json(p, rec)
    res["record"] = os.path.relpath(p, root)
    return _finish(root, res)


def _finish(root, res):
    line = {"format": INDEX_FORMAT, "at": res["at"], "workId": res.get("workId"), "zipName": res["zipName"], "result": res["result"],
            "use": res.get("use"), "usable": res.get("usable"), "train": res.get("train"), "sha256": res.get("sha256")}
    ip = os.path.join(root, "index.jsonl")
    if os.path.islink(ip):
        raise DestError("index.jsonl がリンクになっています")
    with open(ip, "a", encoding="utf-8") as f:
        f.write(json.dumps(line, ensure_ascii=False) + "\n")
    return res


# ---------------------------------------------------------------- まとめて・CLI

def collect(paths):
    """引数(zip かフォルダ)-> (zip のパスの一覧, 見つからない引数の一覧)。フォルダは直下の *.zip だけ(名前順)"""
    out, missing = [], []
    for p in paths:
        if os.path.isdir(p):
            out += [os.path.join(p, n) for n in sorted(os.listdir(p)) if n.lower().endswith(ev.ZIP_SUFFIX) and os.path.isfile(os.path.join(p, n))]
        elif os.path.isfile(p):
            out.append(p)
        else:
            missing.append(p)
    return out, missing


LABEL = {"imported": "取り込み", "duplicate": "重複", "rejected": "断った", "error": "失敗"}


def summary_line(res):
    s = "[%s] %s" % (LABEL.get(res["result"], res["result"]), res["zipName"])
    if res["result"] == "imported":
        s += "  使える行 %d/%d%s%s" % (res.get("usable") or 0, res.get("rows") or 0, "" if res.get("use") else "  作業ごと外した",
                                        "" if res.get("train") else "  学習に入れない")
        if res.get("replaced"):
            s += "  (入れ替えた)"
    for r in res.get("reasons") or []:
        s += "\n    - " + r
    return s


def run(paths, dest, force=False, out=None):
    """-> (結果の一覧, 終了コード)"""
    out = out or sys.stdout
    try:
        root = prepare_dest(dest)
        no_train = load_routing(root)
    except (DestError, OSError) as e:
        print("置き場所が使えません: %s" % e, file=out)
        return [], 2
    zips, missing = collect(paths)
    results = []
    for p in missing:
        results.append({"zipName": os.path.basename(p) or p, "result": "error", "reasons": ["見つかりません: %s" % p]})
    for p in zips:
        try:
            res = import_zip(p, root, force=force, no_train=no_train)
        except (DestError, OSError) as e:
            res = {"zipName": os.path.basename(p), "result": "error", "reasons": [str(e)]}
        results.append(res)
    for res in results:
        print(summary_line(res), file=out)
    counts = {k: sum(1 for r in results if r["result"] == k) for k in LABEL}
    print("合計: 取り込み %(imported)d・重複 %(duplicate)d・断った %(rejected)d・失敗 %(error)d" % counts, file=out)
    print("置き場所: %s" % root, file=out)
    return results, (1 if counts["rejected"] or counts["error"] else 0)


def main(argv=None):
    ap = argparse.ArgumentParser(description="評価データ(送る用 zip)の取り込みチェック")
    ap.add_argument("paths", nargs="+", help="zip か、zip の入ったフォルダ")
    ap.add_argument("--dest", default=None, help="置き場所(既定 %s)" % default_dest())
    ap.add_argument("--force", action="store_true", help="同じ作業ID がすでにあれば入れ替える")
    a = ap.parse_args(argv)
    try:
        sys.stdout.reconfigure(errors="replace")   # Windows のコンソールで表示できない文字があっても止めない
    except (AttributeError, ValueError):
        pass
    _results, code = run(a.paths, a.dest or default_dest(), force=a.force)
    return code


if __name__ == "__main__":
    sys.exit(main())
