# -*- coding: utf-8 -*-
"""② 管理の層 flow: 送り返しの zip(F1 の F2。docs/design/f1-build.md の 2・3 の (f1d)(f1m)・plan/f1-friend-pc.md の決めたこと 11)。

友人の PC の ② は、依頼(封筒に requestId がある実行)が 1 本終わるたびに、`<app>/outbox/<requestId>__<runId>.zip` を組む。
アプリ(C#)が Dropbox の `/送り返し/` へ上げ、上げ終えたら `mark_done` で `outbox/済み/` へ移す(消さない = 直近 KEEP_DONE 件は残す)。
ユーザーの PC の受付が受け取る(human/friend/returns)。Dropbox を知らないのは ② の決まりのまま: ここは zip を作って並べるだけ。

zip の中身(動画・音声は入れない。ファイルは 作業用/ にある物だけ。壊れて読めない物は飛ばす):
- manifest.json   形 youtube-tools-outbox/v1・requestId・runId・作った時刻・版・入れた物の一覧・減らした物の印(trimmed)
- run.json        結果の束(作業用/runs/<実行id>.json)。秘密の名前の項目(apiKey・token など)は値を伏せる
- keys/           成果物の鍵(*.key.json。文字起こし・後処理・話者・切り抜き・パック)
- docs/           文字起こしの機械の結果と文書の .json(減らすときは最初に外す)
- candidates.json / adopted.json   案件の 作業用/候補.json・採用.json(候補と点数・採否)
- log-tail.txt    ログの末尾 LOG_TAIL_LINES 行(キーの形の文字は伏せる)
- health.json     この PC の調子の 1 枚(版・OS・Python・空き容量など。呼び手が health= で足せる)
上限 MAX_BYTES(50MB)。超えるときは docs → 候補 → ログの順に外して印を manifest の trimmed に書く(束と鍵は最後まで残す)。

何があっても上げない(実行は失敗にしない)ので、build は失敗したら None を返してログだけ。
標準ライブラリと ytt・flow だけ(③④ に依存しない)。
"""
import json
import logging
import os
import platform
import re
import time
import zipfile

from ytt import fsio as _fsio, version as _version
from . import runlog as _runlog

log = logging.getLogger("ytt.flow.outbox")

SCHEMA = "youtube-tools-outbox/v1"
OUTBOX_DIR = "outbox"
DONE_DIR = "済み"
MAX_BYTES = 50 * 1024 * 1024
LOG_TAIL_LINES = 2000
LOG_TAIL_READ = 2 * 1024 * 1024   # ログの末尾はこの大きさだけ読む
KEEP_DONE = 20
NAME_RE = re.compile(r"^([0-9A-Za-z_-]{1,64})__([0-9A-Za-z_-]{1,64})\.zip\Z")
SECRET_KEY_RE = re.compile(r"api[-_]?key|token|secret|passw|credential|authorization|cookie", re.I)
SECRET_TEXT_RE = re.compile(r"AIza[0-9A-Za-z_-]{20,}|sk-[0-9A-Za-z_-]{20,}|(?i:bearer)\s+[0-9A-Za-z._~+/=-]{16,}|X-YTT-Token\W+[0-9A-Za-z_-]{8,}")
MASK = "(伏せた)"
_JSON_MAX = 16 * 1024 * 1024


def outbox_dir(app_dir):
    """<app>/outbox(app_dir = 入口・ヘッドレスの作業データ app のフォルダ)"""
    return os.path.join(app_dir, OUTBOX_DIR)


def _safe(s):
    return re.sub(r"[^0-9A-Za-z_-]", "_", str(s or ""))[:64]


def scrub(obj):
    """JSON の中の秘密の名前の項目(apiKey・token・password など)の値を伏せる(新しい物を返す)。文字列の中の鍵の形も伏せる"""
    if isinstance(obj, dict):
        return {k: (MASK if SECRET_KEY_RE.search(str(k)) and isinstance(v, (str, int, float)) and v not in ("", None) else scrub(v)) for k, v in obj.items()}
    if isinstance(obj, list):
        return [scrub(v) for v in obj]
    if isinstance(obj, str):
        return SECRET_TEXT_RE.sub(MASK, obj)
    return obj


def _read_json(path):
    obj = _fsio.read_json_or(path, None, max_bytes=_JSON_MAX)
    return obj


def _json_bytes(obj):
    return json.dumps(obj, ensure_ascii=False, indent=1).encode("utf-8")


def _tail(path, lines=LOG_TAIL_LINES):
    """ログの末尾 lines 行(伏せたあと)。読めなければ None"""
    try:
        size = os.path.getsize(path)
        with open(path, "rb") as f:
            f.seek(max(0, size - LOG_TAIL_READ))
            raw = f.read()
    except OSError:
        return None
    text = raw.decode("utf-8", "replace").splitlines()
    if size > LOG_TAIL_READ and text:
        text = text[1:]   # 途中から読んだ最初の行は捨てる
    return SECRET_TEXT_RE.sub(MASK, "\n".join(text[-lines:])) + "\n"


def default_health(path_for_disk=None):
    """この PC の調子の 1 枚(最小。秘密・個人のパスは入れない)"""
    h = {"version": _version.VERSION, "platform": platform.platform(), "python": platform.python_version(), "machine": platform.machine()}
    try:
        h["freeGB"] = round(_fsio.disk_space(path_for_disk or os.getcwd())[0] / 1e9, 1)
    except (OSError, TypeError):
        pass
    return h


def _gather(result, run_path):
    """結果の束から入れる物の一覧 -> [(zip の中の名前, パス, 区分)]。区分 = key / doc / candidates / adopted"""
    out, seen = [], set()

    def add(arc, path, kind):
        if isinstance(path, str) and path and os.path.isfile(path) and path not in seen:
            seen.add(path)
            out.append((arc, path, kind))

    outs = result.get("outputs") if isinstance(result.get("outputs"), dict) else {}
    n = 0
    for stage, items in outs.items():
        for it in items if isinstance(items, list) else ():
            if not isinstance(it, dict):
                continue
            for k in ("key", "post"):
                n += 1
                add("keys/%s/%d-%s" % (stage, n, os.path.basename(it[k])) if isinstance(it.get(k), str) else "", it.get(k), "key")
            if stage == "transcribe" and isinstance(it.get("path"), str):
                base = os.path.splitext(it["path"])[0]
                add("docs/" + os.path.basename(it["path"]), it["path"], "doc")
                for suf in (".asr.json", ".diar.json"):
                    add("docs/" + os.path.basename(base) + suf, base + suf, "doc")
    work = os.path.dirname(os.path.dirname(run_path))   # <案件>/作業用/runs/<id>.json -> <案件>/作業用
    add("candidates.json", os.path.join(work, "候補.json"), "candidates")
    add("adopted.json", os.path.join(work, "採用.json"), "adopted")
    return out


def build(result_path, app_dir, request_id=None, health=None, log_path=None, max_bytes=MAX_BYTES, now=None):
    """結果の束 result_path の実行の送り返し zip を <app>/outbox に組む -> zip のパスか None。
    request_id = 依頼の id(None = 束の封筒の requestId。どちらも無い = 友人の依頼でないので作らない)。
    health = 調子の 1 枚(dict。None = default_health)。log_path = ログのファイル(その末尾を入れる。None = 入れない)"""
    try:
        result = _read_json(result_path)
        if not isinstance(result, dict) or result.get("schema") != _runlog.RESULT_SCHEMA:
            return None
        rid = request_id or ((result.get("envelope") or {}).get("requestId") if isinstance(result.get("envelope"), dict) else None)
        if not rid:
            return None
        run_id = _safe(result.get("id"))
        if not run_id:
            return None
        name = "%s__%s.zip" % (_safe(rid), run_id)
        if not NAME_RE.match(name):
            return None
        entries = _gather(result, result_path)
        trimmed = []
        run_json = _json_bytes(scrub(result))
        log_text = _tail(log_path) if log_path else None
        hl = _json_bytes(scrub(health if isinstance(health, dict) else default_health(os.path.dirname(result_path))))
        # 外す順: docs -> candidates / adopted -> ログ。束・鍵・manifest・health は最後まで残す
        drop_order = ["doc", "candidates", "adopted", "log"]
        dropped = set()
        size = len(run_json) + len(hl) + (len(log_text.encode("utf-8")) if log_text else 0)
        sizes = []
        for arc, path, kind in entries:
            try:
                sizes.append(os.path.getsize(path))
            except OSError:
                sizes.append(0)
        total = size + sum(sizes)
        for kind in drop_order:
            if total <= max_bytes * 0.9:   # 圧縮で小さくなるが、見積もりは非圧縮で安全側に
                break
            if kind == "log":
                if log_text:
                    total -= len(log_text.encode("utf-8"))
                    log_text = None
                    dropped.add("log")
                    trimmed.append("log")
                continue
            for (arc, path, k), sz in zip(entries, sizes):
                if k == kind:
                    total -= sz
                    dropped.add(path)
            trimmed.append(kind)
        keep = [(a, p, k) for a, p, k in entries if p not in dropped and a]
        os.makedirs(outbox_dir(app_dir), exist_ok=True)
        dst = os.path.join(outbox_dir(app_dir), name)
        tmp = dst + ".part"
        names = []
        with zipfile.ZipFile(tmp, "w", zipfile.ZIP_DEFLATED) as z:
            z.writestr("run.json", run_json)
            names.append("run.json")
            for arc, path, kind in keep:
                data = None
                if path.lower().endswith(".json"):
                    obj = _read_json(path)
                    data = _json_bytes(scrub(obj)) if obj is not None else None
                    if data is None:
                        continue
                else:
                    try:
                        with open(path, "rb") as f:
                            data = f.read(_JSON_MAX)
                    except OSError:
                        continue
                z.writestr(arc, data)
                names.append(arc)
            if log_text:
                z.writestr("log-tail.txt", log_text.encode("utf-8"))
                names.append("log-tail.txt")
            z.writestr("health.json", hl)
            names.append("health.json")
            manifest = {"schema": SCHEMA, "requestId": str(rid)[:120], "runId": run_id, "at": int((time.time() if now is None else now) * 1000),
                        "madeBy": {"name": "flow", "version": _version.VERSION}, "files": names + ["manifest.json"], "trimmed": trimmed}
            z.writestr("manifest.json", _json_bytes(manifest))
        if os.path.getsize(tmp) > max_bytes:   # 圧縮後も超える(見積もりが外れた)= 束と鍵だけにして作り直す
            os.unlink(tmp)
            with zipfile.ZipFile(tmp, "w", zipfile.ZIP_DEFLATED) as z:
                z.writestr("run.json", run_json)
                z.writestr("manifest.json", _json_bytes({"schema": SCHEMA, "requestId": str(rid)[:120], "runId": run_id, "at": int(time.time() * 1000),
                                                         "files": ["run.json", "manifest.json"], "trimmed": ["doc", "candidates", "adopted", "log", "keys"]}))
        _fsio.replace_retry(tmp, dst)
        return dst
    except Exception as e:   # 実行は失敗にしない(呼び手は終わったあとの hook)
        log.warning("送り返しの zip を作れませんでした: %s %s", e.__class__.__name__, str(e)[:150])
        return None


def list_outbox(app_dir):
    """送り返す zip の一覧(古い順)-> [{"id": zip の名前, "requestId", "runId", "size", "at"(更新のミリ秒)}]。
    HTTP の口 GET /api/flow/outbox の中身(F6 で server.py が {"files": これ} で返す)。書きかけ(.part)は出さない"""
    d = outbox_dir(app_dir)
    out = []
    try:
        names = os.listdir(d)
    except OSError:
        return out
    for n in names:
        m = NAME_RE.match(n)
        p = os.path.join(d, n)
        if not m or not os.path.isfile(p):
            continue
        try:
            st = os.stat(p)
        except OSError:
            continue
        out.append({"id": n, "requestId": m.group(1), "runId": m.group(2), "size": st.st_size, "at": int(st.st_mtime * 1000)})
    out.sort(key=lambda x: (x["at"], x["id"]))
    return out


def mark_done(app_dir, zip_id):
    """上げ終えた印: outbox/<id> を outbox/済み/ へ移す -> 移したら True(無い・名前が違う = False)。
    口 POST /api/flow/outbox/done {id}。名前は NAME_RE の形だけ(パスを通さない)。済みは新しい KEEP_DONE 件だけ残す"""
    if not isinstance(zip_id, str) or not NAME_RE.match(zip_id):
        return False
    src = os.path.join(outbox_dir(app_dir), zip_id)
    if not os.path.isfile(src):
        return False
    done = os.path.join(outbox_dir(app_dir), DONE_DIR)
    os.makedirs(done, exist_ok=True)
    _fsio.replace_retry(src, os.path.join(done, zip_id))
    try:
        olds = sorted((os.path.join(done, n) for n in os.listdir(done) if NAME_RE.match(n)), key=os.path.getmtime)
        for p in olds[:-KEEP_DONE]:
            _fsio.unlink_quiet(p)
    except OSError:
        pass
    return True
