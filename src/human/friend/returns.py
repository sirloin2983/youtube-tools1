# -*- coding: utf-8 -*-
"""③ 人の層: 友人からの送り返しを受け取って並べる(F1 の F2。notes:docs/design/f1-build.md の (f1d))。

友人の PC のアプリが Dropbox の `/送り返し/` へ上げた物が、ユーザーの PC では同期フォルダ(intake.folder)の `送り返し\\` に届く:
- `<requestId>__<runId>.zip`            ② が組んだ 1 実行の結果(flow/outbox。動画なし)
- `<requestId>__<パック名>.verdict.json`  友人の採否 {"verdict": "keep"|"reject"|"made_video", "at": ミリ秒}(アプリが直に書く)
受け取ると `app\\friend-returns\\<YYYY-MM>\\<requestId>\\` に並べ(zip は `<runId>\\` へ展開・採否は `verdicts\\` へ)、元は `送り返し\\受付済み\\` へ移す
(消さない。形が違う・壊れた物は `送り返し\\失敗\\` へ理由の .txt つき)。
zip の中のパスは展開先の中だけ(zip slip を断る)。部品を壊す物・大きすぎる物は zip ごと断る。intake.scan から scan が 1 行で呼ばれる。
標準ライブラリと ytt・flow だけ。
"""
import datetime
import json
import os
import re
import shutil
import stat
import time
import zipfile

from ytt import fsio
from flow import outbox

RETURNS_DIR = "friend-returns"      # <app>/friend-returns/<YYYY-MM>/<requestId>/
IN_DIR, DONE_DIR, FAIL_DIR = "送り返し", "受付済み", "失敗"
VERDICT_SUFFIX = ".verdict.json"
VERDICTS = ("keep", "reject", "made_video")
VERDICT_RE = re.compile(r"^([0-9A-Za-z_-]{1,64})__([^\\/:*?\"<>|\x00-\x1f]{1,120})" + re.escape(VERDICT_SUFFIX) + r"\Z")
MAX_FILES = 2000                    # zip の中の数
MAX_TOTAL = 400 * 1024 * 1024       # 展開後の合計(zip 爆弾を断る)
MAX_VERDICT = 64 * 1024
SETTLE_SEC = 5                      # 更新から何秒たった物を受け取るか(同期の途中を触らない)
BROKEN_SEC = 3600                   # 壊れた zip を 失敗 へ移すまでの待ち(同期の途中かもしれない)


class Refused(Exception):
    """この zip は受け取れない(理由は str)"""


def returns_dir(app_dir):
    return os.path.join(app_dir, RETURNS_DIR)


def _month(ms=None, now=None):
    t = (ms / 1000.0) if isinstance(ms, (int, float)) and ms > 0 else (time.time() if now is None else now)
    return datetime.datetime.fromtimestamp(t).strftime("%Y-%m")


def _find_request_dir(app_dir, rid):
    """既に並べた依頼のフォルダ(月をまたいでも同じ所へ)。無ければ None"""
    root = returns_dir(app_dir)
    try:
        for m in sorted(os.listdir(root), reverse=True):
            p = os.path.join(root, m, rid)
            if os.path.isdir(p):
                return p
    except OSError:
        pass
    return None


def _member_dest(root, name):
    """zip のメンバー名 -> 展開先のパス。root の外・絶対パス・.. ・ドライブ文字・空の名前は Refused(zip slip)"""
    if not name or "\x00" in name:
        raise Refused("名前が正しくない物があります")
    norm = name.replace("\\", "/")
    if norm.startswith("/") or re.match(r"^[A-Za-z]:", norm) or any(part in ("..",) for part in norm.split("/")):
        raise Refused("展開先の外を指す名前があります: %s" % name[:80])
    dest = os.path.normpath(os.path.join(root, *[p for p in norm.split("/") if p]))
    if not fsio.is_inside(dest, root, strict=True):
        raise Refused("展開先の外を指す名前があります: %s" % name[:80])
    return dest


def extract(zip_path, dest_root):
    """zip を dest_root へ展開する -> manifest の dict(無ければ {})。壊れた zip は zipfile.BadZipFile。
    断る物(Refused): 展開先の外へ出る名前・シンボリックリンク・MAX_FILES / MAX_TOTAL 超え。断ったときは何も残さない(途中まで書かない = 先に全部確かめる)"""
    with zipfile.ZipFile(zip_path) as z:
        infos = z.infolist()
        if len(infos) > MAX_FILES:
            raise Refused("ファイルが多すぎます(%d 件)" % len(infos))
        if sum(i.file_size for i in infos) > MAX_TOTAL:
            raise Refused("展開すると大きすぎます")
        plan = []
        for i in infos:
            if stat.S_ISLNK(i.external_attr >> 16):
                raise Refused("リンクが入っています: %s" % i.filename[:80])
            plan.append((i, _member_dest(dest_root, i.filename)))
        os.makedirs(dest_root, exist_ok=True)
        for i, dest in plan:
            if i.is_dir():
                os.makedirs(dest, exist_ok=True)
                continue
            os.makedirs(os.path.dirname(dest), exist_ok=True)
            with z.open(i) as src, open(dest, "wb") as out:
                n = 0
                while True:
                    b = src.read(1 << 20)
                    if not b:
                        break
                    n += len(b)
                    if n > MAX_TOTAL:
                        raise Refused("展開すると大きすぎます")
                    out.write(b)
    mf = fsio.read_json_or(os.path.join(dest_root, "manifest.json"), {}, kind=dict)
    return mf if mf.get("schema") == outbox.SCHEMA else {}


def parse_verdict(raw):
    """verdict.json の中身(bytes) -> {"verdict", "at"}。形が違えば ValueError(理由)"""
    try:
        d = json.loads(raw.decode("utf-8-sig"))
    except (UnicodeDecodeError, ValueError):
        raise ValueError("JSON として読めません")
    if not isinstance(d, dict) or d.get("verdict") not in VERDICTS:
        raise ValueError("verdict は %s のどれかにしてください" % " / ".join(VERDICTS))
    at = d.get("at")
    return {"verdict": d["verdict"], "at": int(at) if isinstance(at, (int, float)) and not isinstance(at, bool) else None}


def _move(folder, name, state, why=""):
    """送り返し\\<name> を 受付済み\\ か 失敗\\ へ(消さない。失敗には理由の .txt)"""
    src = os.path.join(folder, name)
    sub = os.path.join(folder, DONE_DIR if state == "accepted" else FAIL_DIR)
    os.makedirs(sub, exist_ok=True)
    dst = os.path.join(sub, name)
    if os.path.exists(dst):
        stem, ext = os.path.splitext(name)
        dst = os.path.join(sub, "%s-%d%s" % (stem, int(time.time()), ext))
    fsio.replace_retry(src, dst)
    if why:
        with open(os.path.splitext(dst)[0] + ".理由.txt", "w", encoding="utf-8-sig", newline="") as f:
            f.write(why + "\r\n")


def scan(sync_folder, app_dir, clock=None, log=None):
    """同期フォルダの 送り返し\\ を見て、届いた物を並べる -> [{"name", "kind"("run"|"verdict"), "state"("accepted"|"rejected"|"wait"), "reason"}]。
    何があっても上げない(受付の見回りを止めない)。フォルダが無ければ空"""
    log = log or (lambda msg: None)
    clock = clock or time.time
    folder = os.path.join(sync_folder, IN_DIR)
    results = []
    try:
        names = sorted(os.listdir(folder))
    except OSError:
        return results
    for n in names:
        p = os.path.join(folder, n)
        low = n.lower()
        try:
            if n.startswith((".", "~")) or not os.path.isfile(p) or not (low.endswith(".zip") or low.endswith(VERDICT_SUFFIX)):
                continue
            if clock() - os.path.getmtime(p) < SETTLE_SEC:
                continue
            res = _one(folder, app_dir, n, p, clock, log)
            if res:
                results.append(res)
        except Exception as e:   # 1 つのファイルで見回り全体を止めない
            log("送り返し: %s を扱えませんでした(%s: %s)" % (n, e.__class__.__name__, str(e)[:100]))
    return results


def _one(folder, app_dir, n, p, clock, log):
    if n.lower().endswith(VERDICT_SUFFIX):
        m = VERDICT_RE.match(n)
        if not m:
            _move(folder, n, "rejected", "名前が <依頼 id>__<パック名>%s の形ではありません" % VERDICT_SUFFIX)
            return {"name": n, "kind": "verdict", "state": "rejected", "reason": "名前の形"}
        if os.path.getsize(p) > MAX_VERDICT:
            _move(folder, n, "rejected", "大きすぎます")
            return {"name": n, "kind": "verdict", "state": "rejected", "reason": "大きすぎます"}
        try:
            with open(p, "rb") as f:
                v = parse_verdict(f.read())
        except ValueError as e:
            _move(folder, n, "rejected", str(e))
            return {"name": n, "kind": "verdict", "state": "rejected", "reason": str(e)}
        rid, pack = m.group(1), m.group(2)
        d = _find_request_dir(app_dir, rid) or os.path.join(returns_dir(app_dir), _month(v["at"], clock()), rid)
        out = os.path.join(d, "verdicts")
        os.makedirs(out, exist_ok=True)
        fsio.write_json(os.path.join(out, pack + VERDICT_SUFFIX), dict(v, requestId=rid, pack=pack))
        _move(folder, n, "accepted")
        return {"name": n, "kind": "verdict", "state": "accepted", "reason": ""}
    m = outbox.NAME_RE.match(n)
    if not m:
        _move(folder, n, "rejected", "名前が <依頼 id>__<実行 id>.zip の形ではありません")
        return {"name": n, "kind": "run", "state": "rejected", "reason": "名前の形"}
    rid, run_id = m.group(1), m.group(2)
    d = _find_request_dir(app_dir, rid)
    month_dir = d or os.path.join(returns_dir(app_dir), _month(None, clock()), rid)
    dest = os.path.join(month_dir, run_id)
    tmp = dest + ".part"
    try:
        if os.path.isdir(tmp):
            _rmtree(tmp)
        mf = extract(p, tmp)
        if os.path.isdir(dest):
            _rmtree(dest)   # 同じ実行の送り直しは置き換える
        os.replace(tmp, dest)
    except zipfile.BadZipFile:
        _rmtree(tmp)
        if clock() - os.path.getmtime(p) >= BROKEN_SEC:
            _move(folder, n, "rejected", "zip として読めません")
            return {"name": n, "kind": "run", "state": "rejected", "reason": "壊れた zip"}
        return {"name": n, "kind": "run", "state": "wait", "reason": "同期の途中かもしれません"}
    except Refused as e:
        _rmtree(tmp)
        _move(folder, n, "rejected", str(e))
        log("送り返し: %s を断りました(%s)" % (n, e))
        return {"name": n, "kind": "run", "state": "rejected", "reason": str(e)}
    if mf.get("requestId") not in (None, rid):   # 名前と中身の依頼 id が食い違う(置き場所は名前の方。印だけ残す)
        log("送り返し: %s の中の requestId が名前と違います" % n)
    _move(folder, n, "accepted")
    return {"name": n, "kind": "run", "state": "accepted", "reason": ""}


def _rmtree(path):
    shutil.rmtree(path, ignore_errors=True)


def iter_requests(app_dir):
    """並べた依頼の一覧 -> [{"month", "requestId", "dir", "runs": [{"runId", "dir", "manifest", "result"}], "verdicts": {パック名: {verdict, at}}}]。
    読むだけ。壊れた JSON は飛ばす"""
    out = []
    root = returns_dir(app_dir)
    try:
        months = sorted(os.listdir(root))
    except OSError:
        return out
    for mo in months:
        mp = os.path.join(root, mo)
        if not os.path.isdir(mp):
            continue
        for rid in sorted(os.listdir(mp)):
            rp = os.path.join(mp, rid)
            if not os.path.isdir(rp):
                continue
            runs, verdicts = [], {}
            for sub in sorted(os.listdir(rp)):
                sp = os.path.join(rp, sub)
                if sub == "verdicts" and os.path.isdir(sp):
                    for vn in sorted(os.listdir(sp)):
                        if vn.endswith(VERDICT_SUFFIX):
                            v = fsio.read_json_or(os.path.join(sp, vn), None, kind=dict)
                            if v and v.get("verdict") in VERDICTS:
                                verdicts[vn[:-len(VERDICT_SUFFIX)]] = {"verdict": v["verdict"], "at": v.get("at")}
                elif os.path.isdir(sp) and not sub.endswith(".part"):
                    runs.append({"runId": sub, "dir": sp, "manifest": fsio.read_json_or(os.path.join(sp, "manifest.json"), {}, kind=dict),
                                 "result": fsio.read_json_or(os.path.join(sp, "run.json"), {}, kind=dict)})
            out.append({"month": mo, "requestId": rid, "dir": rp, "runs": runs, "verdicts": verdicts})
    return out
