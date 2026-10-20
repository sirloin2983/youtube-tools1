# -*- coding: utf-8 -*-
"""④ データ: 学習の束を作る側(F1。notes:docs/design/f1-build.md の 2 の F1・3 の (f1c))。

ユーザーの PC の入口が、学習したもの(置換辞書・用語集・学習した置換・計算済みの規則・名簿・メンバーカラー・名簿にある人の声)を
同期フォルダの `学習/<版>/` に置く。友人の PC の ② は文書を読まずに、この束だけで学習を使う(読む側 `flow/learning.py`)。

    学習/
      latest.json                      {version, dir, createdAt}   友人のアプリはこれだけ見て新しい版を取る
      <YYYYMMDD-HHMMSS-sha8>/          版 = 作った時刻 + 中身の sha256 の先頭 8 字(zip にしない = Dropbox が差分で同期する)
        learning.json                  {schema, version, createdAt, files:[{path, sha256, size}]}   最後に書く = あれば完成
        settings.json                  置換辞書 replacements と用語集 glossary だけ(editor 設定の他の項目は入れない)
        learn-feedback.json            学習した置換の採用・却下の記録
        learned-rules.json             ③ learn.export_rules() の結果(確度「高」の置換・用語の順位・辞書の版の元)
        hololive-roster.json  members.json
        voices/<判別モデル>.json       名簿にある人の声だけ(配信者以外の声を出さない守り)

- 元が変わらなければ作らない(最新の版と中身の sha8 が同じ -> created False)。直近 keep 版(既定 3)を残して古い版は消す
- 声は個人を見分けられる情報なので、名簿の名前と一致する人だけを入れ、経路は 2 人の Dropbox だけ(リポジトリの外 = git に入らない)
- 作る・消すのは軽い(重い処理の SLOTS を通さない)。入口への配線(起動時・バックアップの見回り)は仕上げの段
"""
import hashlib
import json
import os
import re
import shutil
import time

from human.proof import learn as _learn
from ytt import colors as _colors, dictfmt as _dictfmt, fsio as _fsio, textutil as _textutil, workdata as _workdata

SCHEMA = "ytt-learning/v1"
PACK_FILE, LATEST_FILE, RULES_FILE = "learning.json", "latest.json", "learned-rules.json"
VERSION_RE = re.compile(r"^\d{8}-\d{6}-[0-9a-f]{8}$")
KEEP = 3


def _json_bytes(obj):
    return json.dumps(obj, ensure_ascii=False, sort_keys=True, indent=1).encode("utf-8")


def roster_names(roster):
    """名簿の辞書 -> 正規化した名前の集合(groups[].names)"""
    out = set()
    for g in (roster or {}).get("groups") or []:
        for n in (g.get("names") if isinstance(g, dict) else None) or []:
            if isinstance(n, str) and _textutil.person_key(n):
                out.add(_textutil.person_key(n))
    return out


def filter_voices(emb, voices_obj, names):
    """覚えた声のファイルの中身 -> 名簿の名前に一致する人だけにした中身(いなければ None)"""
    v = voices_obj.get("voices") if isinstance(voices_obj, dict) else None
    keep = {k: x for k, x in (v or {}).items() if isinstance(x, dict) and _textutil.person_key(k) in names}
    return {"schema": "ytt-voices/v1", "embedding": emb, "voices": keep} if keep else None


def collect(data_dir, roster_path, members_path, rules):
    """束に入れる中身 -> {束の中のパス: bytes}(元のファイルが無い物は入れない)。data_dir = 編集の作業データ(settings.json・learn-feedback.json・voices/)"""
    files = {}
    settings = _fsio.read_json_or(os.path.join(data_dir, "settings.json"), None, kind=dict) or {}
    keys = ("replacements", "glossary") if _dictfmt.USER_DICT else ("glossary",)   # 人の置換辞書は今はオフ = 束に入れない(ユーザー決定)
    picked = {k: settings[k] for k in keys if k in settings}
    if picked:
        files["settings.json"] = _json_bytes(picked)
    fb = _fsio.read_json_or(os.path.join(data_dir, "learn-feedback.json"), None, kind=dict)
    if fb is not None:
        files["learn-feedback.json"] = _json_bytes(fb)
    files[RULES_FILE] = _json_bytes(rules)
    roster = _fsio.read_json_or(roster_path, None, kind=dict) if roster_path else None
    if roster is not None:
        files["hololive-roster.json"] = _json_bytes(roster)
    members = _fsio.read_json_or(members_path, None, kind=(dict, list)) if members_path else None
    if members is not None:
        files["members.json"] = _json_bytes(members)
    names = roster_names(roster)
    vdir = os.path.join(data_dir, "voices")
    for fn in sorted(os.listdir(vdir)) if os.path.isdir(vdir) else ():
        if not fn.endswith(".json") or not names:
            continue
        got = filter_voices(fn[:-5], _fsio.read_json_or(os.path.join(vdir, fn), None, kind=dict), names)
        if got:
            files["voices/" + fn] = _json_bytes(got)
    return files


def content_sha8(files):
    """中身の sha256 の先頭 8 字(パスの順に、パスと各ファイルの sha256 を連ねる)"""
    h = hashlib.sha256()
    for path in sorted(files):
        h.update(path.encode("utf-8") + b"\0" + hashlib.sha256(files[path]).hexdigest().encode("ascii") + b"\n")
    return h.hexdigest()[:8]


def versions(learn_root):
    """作ってある版(新しい順)"""
    try:
        names = os.listdir(learn_root)
    except OSError:
        return []
    return sorted((n for n in names if VERSION_RE.match(n) and os.path.isfile(os.path.join(learn_root, n, PACK_FILE))), reverse=True)


def build(learn_root, data_dir=None, roster_path=None, members_path=None, rules=None, keep=KEEP, now=None):
    """学習の束を learn_root(同期フォルダの 学習/)に作る -> {"version", "dir", "created": 作ったか}。
    data_dir 既定 = ytt/workdata.DATA_DIR(編集の作業データ)・roster_path = 名簿(入口が ① の roster.ROSTER を渡す。無ければ束に入れない)・members_path 既定 = ytt/colors の場所・
    rules 既定 = ③ learn.export_rules()。元が変わらなければ作らず最新の版を返す"""
    data_dir = data_dir or _workdata.DATA_DIR
    members_path = members_path or _colors.members_path()
    rules = _learn.export_rules() if rules is None else rules
    files = collect(data_dir, roster_path, members_path, rules)
    sha8 = content_sha8(files)
    have = versions(learn_root)
    if have and have[0].endswith("-" + sha8):
        _ensure_latest(learn_root, have[0])
        return {"version": have[0], "dir": os.path.join(learn_root, have[0]), "created": False}
    ts = time.time() if now is None else now
    version = "%s-%s" % (time.strftime("%Y%m%d-%H%M%S", time.localtime(ts)), sha8)
    final = os.path.join(learn_root, version)
    if os.path.isdir(final):
        return {"version": version, "dir": final, "created": False}
    os.makedirs(learn_root, exist_ok=True)
    for n in os.listdir(learn_root):   # 前に途中で止まった作りかけを片付ける
        if n.endswith(".tmp"):
            shutil.rmtree(os.path.join(learn_root, n), ignore_errors=True)
    tmp = final + ".tmp"
    listing = []
    for path in sorted(files):
        _fsio.atomic_write(os.path.join(tmp, *path.split("/")), files[path])
        listing.append({"path": path, "sha256": hashlib.sha256(files[path]).hexdigest(), "size": len(files[path])})
    _fsio.write_json(os.path.join(tmp, PACK_FILE), {"schema": SCHEMA, "version": version, "createdAt": int(ts * 1000), "files": listing})
    os.replace(tmp, final)
    _ensure_latest(learn_root, version)
    for old in versions(learn_root)[max(1, int(keep)):]:
        shutil.rmtree(os.path.join(learn_root, old), ignore_errors=True)
    return {"version": version, "dir": final, "created": True}


def _ensure_latest(learn_root, version):
    cur = _fsio.read_json_or(os.path.join(learn_root, LATEST_FILE), None, kind=dict)
    if not cur or cur.get("version") != version:
        pack = _fsio.read_json_or(os.path.join(learn_root, version, PACK_FILE), None, kind=dict) or {}
        _fsio.write_json(os.path.join(learn_root, LATEST_FILE), {"schema": SCHEMA, "version": version, "dir": version, "createdAt": pack.get("createdAt", 0)})
