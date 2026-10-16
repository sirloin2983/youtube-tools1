# -*- coding: utf-8 -*-
"""② 管理の層 flow: パックを作った記録(作業データの packs/<フォルダのハッシュ>.json)の持ち主(OPT-M2。notes:plan/opt-manage.md の 3b-1)。

パックを作り終えたところで、旧い入口(cut2resolve の POST /api/build)も入口なしの CLI(flow/tools の LocalTools.pack_start)も
同じ after_build を呼ぶ(設計原則の指摘 3: API と CLI が同じ「作れたあとの記録」)= 記録 + <パック>/pack.key.json(flow/keys.write_pack)。
① pipeline/pack は記録を知らない(作るだけ)。④ manage/cases/txindex はここの読み口(read_record・ready)で「パック済み」を決める。

記録の中身は以前パックに入れていた cut-plan.json と、フォルダ・動画・日時・中身のファイル。隠しファイルにしてパックに置かないのは、
Windows で上書きに失敗することがあるため(ユーザー決定 2026-09-26)。書けなくてもパックはできているので、呼び出し側は注意を出すだけ。
"""
import hashlib
import logging
import os
import time
from pathlib import Path

from ytt import datadir as _datadir, fsio as _fsio, layout as _layout

log = logging.getLogger(__name__)

SCHEMA = "youtube-tools-pack-record/v1"
MAX_BYTES = 256 * 1024   # 記録は 1 件 3KB ほど(10-14 の実データで最大 3.2KB。opt-manage 3b-2)
MAX_RECORDS = 1000       # 記録がこれを超えたら、フォルダが無くなったものから古い順に消す
VIDEO_EXTS = (".mp4", ".mov", ".mkv", ".m4v", ".webm")
REPO_ROOT = _layout.src_root()


def norm(p):
    """パスの比べ方(大文字小文字・区切りをそろえる。txindex の紐づけと同じ)"""
    return os.path.normcase(os.path.normpath(str(p))) if p else ""


def packs_dir(env=None, c2r_dir=None):
    """記録のフォルダ(cut2resolve の作業データの packs。YTT_DATA_DIR=inplace ならリポジトリ直下の .data/cut2resolve)。
    置き場所の規則は ytt.datadir.resolve の 1 か所(起動した cut2resolve が登録した場所。env を渡したときは使わない = テスト)。
    c2r_dir: cut2resolve のコードのフォルダ(serve.py が自分の場所を渡す。無ければ環境変数 YTT_CUT2RESOLVE_DIR → リポジトリの cut2resolve)"""
    legacy = c2r_dir or (os.environ if env is None else env).get("YTT_CUT2RESOLVE_DIR") or None
    root = os.path.dirname(os.path.abspath(legacy)) if legacy else REPO_ROOT   # inplace の .data は cut2resolve のフォルダの隣(テストが一時フォルダに写したときもその中)
    return os.path.join(_datadir.resolve("cut2resolve", root, env, legacy), "packs")


def record_name(dirpath):
    """パックのフォルダ → 記録のファイル名(フォルダのパスの大文字小文字をそろえたハッシュ)"""
    return hashlib.sha1(norm(dirpath).encode("utf-8")).hexdigest()[:20] + ".json"


def _files(rec):
    """記録の中身のファイル(パックのフォルダからの相対。外を指す物は外す)"""
    return [f for f in rec.get("files") or [] if isinstance(f, str) and f and not os.path.isabs(f) and ".." not in f.replace("\\", "/").split("/")]


def read_record(dirpath, env=None, c2r_dir=None):
    """パックを作った記録。フォルダがあり、記録した中身のファイルが 1 つでも残っているときだけ返す
    (フォルダを消した・作り直した後の古い記録で「パック済み」にしない)。-> 記録 か None"""
    if not dirpath:
        return None
    try:
        rec = _fsio.read_json_file(os.path.join(packs_dir(env, c2r_dir), record_name(dirpath)), MAX_BYTES)
    except (OSError, UnicodeError, ValueError):
        return None
    if not isinstance(rec, dict) or rec.get("schema") != SCHEMA or norm(rec.get("dir")) != norm(dirpath):
        return None
    if not any(os.path.isfile(os.path.join(str(dirpath), f)) for f in _files(rec)):
        return None
    return rec


def ready(dirpath, env=None, c2r_dir=None):
    """このパックだけで編集できるか -> (真偽, 理由)。read_record は記録したファイルが 1 つでもあれば有効にするので、ここは記録したファイルが
    **全部**あって空でないこと・動画が入っていること・Text+ パックなら Lua の手順書が入っていることを見る(ハッシュは取らない = 重い)。
    片付けが元の素材を候補にする前(部品 M1)と、鍵が同じパックを飛ばす前(部品 F3。keys.pack_state)の両方がこれを見る"""
    rec = read_record(dirpath, env, c2r_dir)
    if not rec:
        return False, "パックを作った記録が無い"
    files = _files(rec)
    for f in files:
        try:
            if os.path.getsize(os.path.join(str(dirpath), f)) <= 0:
                return False, "パックの中の %s が空" % f
        except OSError:
            return False, "パックの中の %s が無い" % f
    if not any(f.lower().endswith(VIDEO_EXTS) for f in files):
        return False, "パックに動画が入っていない"
    if rec.get("textplus") is True and not any(f.lower().endswith(".lua") for f in files):
        return False, "パックに Text+ の手順書(Lua)が無い"
    return True, ""


def write_record(res, video, textplus, backup, color=None, tool=None, env=None, c2r_dir=None):
    """記録を書く(after_build から)。res = ① build_pack の結果(out_dir・files・plan・editMedia・videoCopy)。書けなければ OSError・ValueError"""
    out_dir = Path(res["out_dir"])
    d = packs_dir(env, c2r_dir)
    os.makedirs(d, exist_ok=True)
    rec = {"schema": SCHEMA, "tool": tool or {"name": "youtube-tools"},
           "dir": str(out_dir), "video": str(video), "textplus": bool(textplus), "backup": bool(backup),
           "builtAt": int(time.time() * 1000), "files": [Path(p).relative_to(out_dir).as_posix() for _, p in res["files"]],
           "editMedia": res.get("editMedia"), "cutPlan": res.get("plan"),
           "videoCopy": res.get("videoCopy"),   # 音量をかけて写した動画の条件(C.gain_copy_record)。次のパックで同じなら作り直さない(E-15 の続き)
           "textColor": (color or {}).get("hex"), "streamer": (color or {}).get("who")}   # 字幕の文字の色(配信者の名前を入れたとき)
    _fsio.write_json(os.path.join(d, record_name(out_dir)), rec, indent=1)
    _trim(d)


def _trim(d):
    """記録が MAX_RECORDS を超えたら、フォルダが無くなったものから古い順に消す(読めない・形の違う記録はフォルダが無いものとして)"""
    try:
        names = [os.path.join(d, n) for n in os.listdir(d) if n.endswith(".json")]
        if len(names) > MAX_RECORDS:
            names.sort(key=os.path.getmtime)
            for n in names[:len(names) - MAX_RECORDS]:
                folder = _fsio.read_json_or(n, {}, kind=dict).get("dir")
                if not (isinstance(folder, str) and os.path.isdir(folder)):
                    os.unlink(n)
    except OSError:
        pass


def after_build(res, video, spec, output, textplus, backup, color=None, tool=None, env=None, c2r_dir=None):
    """パックを作れたあとの記録(API と CLI が同じこれを呼ぶ)= 記録 + <パック>/pack.key.json。
    -> 注意の文の一覧(書けなかった物。パックはできているので失敗にしない)"""
    from . import keys as _keys   # keys.pack_state がここの ready を読むので、呼ぶときだけ(読み込みの輪を作らない)
    warnings = []
    try:
        write_record(res, video, textplus, backup, color, tool, env, c2r_dir)
    except (OSError, ValueError, TypeError) as e:
        log.warning("パックの記録を書けません: %s", e)
        warnings.append("パックを作った記録を残せませんでした(一覧の「パック済み」が出ないことがあります): %s" % e)
    _keys.write_pack(res["out_dir"], spec or {}, output or {})   # 書けなくてもログだけ(RS6 b-K1・K2)
    return warnings
