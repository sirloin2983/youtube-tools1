# -*- coding: utf-8 -*-
"""③ 人の層: 友人からの送り返しを受け取って並べる(F1 の F2。notes:docs/design/f1-build.md の (f1d))。

友人の PC のアプリが Dropbox の `/送り返し/` へ上げた物が、ユーザーの PC では同期フォルダ(intake.folder)の `送り返し\\` に届く:
- `<requestId>__<runId>.zip`            ② が組んだ 1 実行の結果(flow/outbox。動画なし)
- `<requestId>__<パック名>[~<at 13 桁>].verdict.json`  友人の判断(アプリが直に書く。並べた verdicts\\ にもそのまま残す。parse_verdict):
  v 2(notes:plan/f1-friend-requirements.md の C-3-4・C-3-6・C-4-1)= {"v":2, "id", "judge": good|bad|unknown|retract, "reason"(bad = boring|cut),
  "of"(retract = 取り消す記録の id), "by"?: "auto"(3 日の自動の見送り), "zip", "videoId"?, "markId"?, "origin"?, "at"}
- `<requestId>__notice-<at 13 桁>.notice.json`  [作る人に知らせる](C-2-16)= {"v":1, "kind":"failure", "message", "detail", "code", "title", "appVersion", "at", "log"}。
  `<依頼>\\notices\\` に並べ、ホームの「依頼の受付」に出す(recent_notices)・ログに 1 行
受け取ると `app\\friend-returns\\<YYYY-MM>\\<requestId>\\` に並べ(zip は `<runId>\\` へ展開・採否は `verdicts\\` へ)、元は `送り返し\\受付済み\\<日付>\\` へ移す
(消さない。受付の 受付済み と同じ日付のフォルダ。形が違う・壊れた物・扱えなかった物は `送り返し\\失敗\\` へ理由の .txt つき)。
zip の中のパスは展開先の中だけ(zip slip を断る。Windows の予約名・: を含む名前も断る)。部品を壊す物・大きすぎる物は zip ごと断る。intake.scan から scan が 1 行で呼ばれる。
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

from flow import deliveries, outbox
from human import judgments
from ytt import fsio, tools

RETURNS_DIR = "friend-returns"      # <app>/friend-returns/<YYYY-MM>/<requestId>/
IN_DIR, DONE_DIR, FAIL_DIR = "送り返し", "受付済み", "失敗"
VERDICT_SUFFIX = ".verdict.json"
LOGS_DIR = "logs"                  # 届けた記録 deliveries.jsonl の置き場所(app の直下の logs)
JUDGES = ("good", "bad", "unknown", "retract")   # v 2 の judge(good・bad・unknown は人の判断の what にそのまま)
ID_RE = re.compile(r"^[0-9A-Za-z_-]{1,64}\Z")    # 判断の記録の id(友人のアプリが作る)・videoId・markId
ORIGINS = ("request", "auto")       # 採否の任意の origin(D-SEND 2-7。友人に見せる出どころ = flow/deliver.face_origin と同じ 2 つ)
VERDICT_RE = re.compile(r"^([0-9A-Za-z_-]{1,64})__([^\\/:*?\"<>|\x00-\x1f]{1,120}?)(~[0-9]{13})?" + re.escape(VERDICT_SUFFIX) + r"\Z")
NOTICE_SUFFIX = ".notice.json"
NOTICE_RE = re.compile(r"^([0-9A-Za-z_-]{1,64})__notice-([0-9]{13})" + re.escape(NOTICE_SUFFIX) + r"\Z")
NOTICES_DIR = "notices"             # <依頼>\notices\ = 作る人への知らせ(実行の結果のフォルダと見分ける)
MAX_NOTICE = 256 * 1024
NOTICE_TEXT = {"message": 500, "detail": 4000, "code": 40, "title": 200, "appVersion": 40, "log": 128 * 1024}   # 知らせの文字の欄の長さの上限
NOTICE_DAYS = 7                     # ホームに出す知らせ(この日数の分)
NOTICE_SHOW = 10
ZIP_NAME_RE = re.compile(r'^[^\\/:*?"<>|\x00-\x1f]{1,200}\Z')   # verdict の zip の名前
MAX_FILES = 2000                   # zip の中の数
MAX_TOTAL = 400 * 1024 * 1024       # 展開後の合計(zip 爆弾を断る)
MAX_VERDICT = 64 * 1024
SETTLE_SEC = 5                      # 更新から何秒たった物を受け取るか(同期の途中を触らない)
BROKEN_SEC = 3600                   # 壊れた zip を 失敗 へ移すまでの待ち(同期の途中かもしれない)
AT_MAX = 10 ** 13                   # verdict の at(ミリ秒)の上限(西暦 2286 年。これより大きい・0 以下は時刻なしと読む)
_RESERVED_RE = re.compile(r"^(con|prn|aux|nul|com[0-9]|lpt[0-9])(\..*)?$", re.I)   # Windows の予約名(拡張子つきも)


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
    """zip のメンバー名 -> 展開先のパス。root の外・絶対パス・.. ・ドライブ文字・空の名前は Refused(zip slip)。
    Windows の予約名(CON・NUL・COM1 など)・: を含む名前(別のデータの流れ)も Refused"""
    if not name or "\x00" in name:
        raise Refused("名前が正しくない物があります")
    norm = name.replace("\\", "/")
    if norm.startswith("/") or re.match(r"^[A-Za-z]:", norm) or any(part in ("..",) for part in norm.split("/")):
        raise Refused("展開先の外を指す名前があります: %s" % name[:80])
    if ":" in norm or any(_RESERVED_RE.match(part.rstrip(" .")) for part in norm.split("/") if part):
        raise Refused("Windows で使えない名前があります: %s" % name[:80])
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
    """verdict.json の中身(bytes)-> _parse_v2 の辞書。v 2 でない・形が違えば ValueError(理由)"""
    try:
        d = json.loads(raw.decode("utf-8-sig"))
    except (UnicodeDecodeError, ValueError):
        raise ValueError("JSON として読めません")
    if not isinstance(d, dict) or d.get("v") != 2:
        raise ValueError("判断の形(v 2)ではありません")
    return _parse_v2(d)


def _at(v):
    """ミリ秒の時刻(0 < at < AT_MAX の数だけ。整数にそろえる)か None"""
    return int(v) if isinstance(v, (int, float)) and not isinstance(v, bool) and 0 < v < AT_MAX else None


def _parse_v2(d):
    """v 2 の判断 -> {"judge", "id", "at", ("reason"・"of"・"by"・"origin"・"zip"・"videoId"・"markId")}。形が違えば ValueError。
    at は 0 < at < AT_MAX の数(ミリ秒)だけ。ほかは None = 受け取った時刻の月に並べる。origin = 届いた物の出どころ request・auto(D-SEND 2-7。任意)"""
    judge = d.get("judge")
    if judge not in JUDGES:
        raise ValueError("judge は %s のどれかにしてください" % " / ".join(JUDGES))
    rid = d.get("id")
    if not isinstance(rid, str) or not ID_RE.match(rid):
        raise ValueError("id は英数字・_・- の 64 文字までにしてください")
    out = {"v": 2, "judge": judge, "id": rid, "at": _at(d.get("at"))}
    if judge == "bad":
        if d.get("reason") not in judgments.FRIEND_REASONS:
            raise ValueError("届かなくてよかったの理由(reason)は %s のどれかにしてください" % " / ".join(judgments.FRIEND_REASONS))
        out["reason"] = d["reason"]
    if judge == "retract":
        if not isinstance(d.get("of"), str) or not ID_RE.match(d["of"]):
            raise ValueError("戻す(retract)には取り消す記録の id(of)が要ります")
        out["of"] = d["of"]
    if d.get("by") == "auto" and judge == "unknown":   # 3 日の自動の見送り(人が押したのではない)
        out["by"] = "auto"
    if d.get("origin") in ORIGINS:
        out["origin"] = d["origin"]
    z = d.get("zip")
    if isinstance(z, str) and ZIP_NAME_RE.match(z) and z.lower().endswith(".zip"):
        out["zip"] = z
    for k in ("videoId", "markId"):   # 届いた .meta.json の値を返す(友人の PC で処理した物は届けた記録に無いので、これで切り抜きを引く)
        if isinstance(d.get(k), str) and ID_RE.match(d[k]):
            out[k] = d[k]
    return out


def parse_notice(raw):
    """[作る人に知らせる] の .notice.json(bytes)-> 整えた辞書。形が違えば ValueError(理由)。文字の欄は NOTICE_TEXT の長さで切る"""
    try:
        d = json.loads(raw.decode("utf-8-sig"))
    except (UnicodeDecodeError, ValueError):
        raise ValueError("JSON として読めません")
    if not isinstance(d, dict) or d.get("v") != 1 or d.get("kind") != "failure":
        raise ValueError("v 1・kind failure の知らせではありません")
    if not isinstance(d.get("message"), str) or not d["message"].strip():
        raise ValueError("message(友人に見えていた文)がありません")
    out = {"v": 1, "kind": "failure", "at": _at(d.get("at"))}
    for k, cap in NOTICE_TEXT.items():
        v = d.get(k)
        out[k] = v[:cap] if isinstance(v, str) else ""
    rid = d.get("requestId")
    out["requestId"] = rid if isinstance(rid, str) and ID_RE.match(rid) else ""
    return out


def _move(folder, name, state, why="", now=None):
    """送り返し\\<name> を 受付済み\\<日付>\\ か 失敗\\ へ(消さない。失敗には理由の .txt)。now = 日付と同じ名前の印に使う時刻(既定は今)"""
    now = time.time() if now is None else now
    src = os.path.join(folder, name)
    sub = os.path.join(folder, DONE_DIR, datetime.datetime.fromtimestamp(now).strftime("%Y-%m-%d")) if state == "accepted" else os.path.join(folder, FAIL_DIR)
    os.makedirs(sub, exist_ok=True)
    dst = os.path.join(sub, name)
    if os.path.exists(dst):
        stem, ext = os.path.splitext(name)
        dst = os.path.join(sub, "%s-%d%s" % (stem, int(now), ext))
    fsio.replace_retry(src, dst)
    if why:
        with open(os.path.splitext(dst)[0] + ".理由.txt", "w", encoding="utf-8-sig", newline="") as f:
            f.write(why + "\r\n")


def scan(sync_folder, app_dir, clock=None, log=None, feedback=None):
    """同期フォルダの 送り返し\\ を見て、届いた物を並べる -> [{"name", "kind"("run"|"verdict"), "state"("accepted"|"rejected"|"wait"), "reason"}]。
    何があっても上げない(受付の見回りを止めない)。フォルダが無ければ空。
    feedback: 友人の「要らない」を片付ける関数(入口の friend_feedback.apply。受付が渡す)。Dropbox で届けたパック(verdict の zip が .zip の名前)の
    bad・unknown は片付ける"""
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
            if n.startswith((".", "~")) or not os.path.isfile(p) or not (low.endswith(".zip") or low.endswith(VERDICT_SUFFIX) or low.endswith(NOTICE_SUFFIX)):
                continue
            if clock() - os.path.getmtime(p) < SETTLE_SEC:
                continue
            res = _one(folder, app_dir, n, p, clock, log, feedback)
            if res:
                results.append(res)
        except OSError as e:   # 読めない・使用中など(同期の途中かもしれない)= 次の見回りでもう一度。1 つのファイルで見回り全体を止めない
            log("送り返し: %s を扱えませんでした(%s: %s)" % (n, e.__class__.__name__, str(e)[:100]))
        except Exception as e:   # 想定外(中身の形など): 送り返し\ に残し続けない = 失敗 へ理由つきで
            why = "扱えませんでした(%s: %s)" % (e.__class__.__name__, str(e)[:100])
            log("送り返し: %s を%s" % (n, why))
            try:
                _move(folder, n, "rejected", why, clock())
            except OSError:
                pass
            results.append({"name": n, "kind": _kind(low), "state": "rejected", "reason": why})
    return results


def _kind(low):
    return "verdict" if low.endswith(VERDICT_SUFFIX) else "notice" if low.endswith(NOTICE_SUFFIX) else "run"


def _one(folder, app_dir, n, p, clock, log, feedback=None):
    if n.lower().endswith(NOTICE_SUFFIX):
        return _one_notice(folder, app_dir, n, p, clock, log)
    if n.lower().endswith(VERDICT_SUFFIX):
        m = VERDICT_RE.match(n)
        if not m:
            _move(folder, n, "rejected", "名前が <依頼 id>__<パック名>%s の形ではありません" % VERDICT_SUFFIX, clock())
            return {"name": n, "kind": "verdict", "state": "rejected", "reason": "名前の形"}
        if os.path.getsize(p) > MAX_VERDICT:
            _move(folder, n, "rejected", "大きすぎます", clock())
            return {"name": n, "kind": "verdict", "state": "rejected", "reason": "大きすぎます"}
        try:
            with open(p, "rb") as f:
                v = parse_verdict(f.read())
        except ValueError as e:
            _move(folder, n, "rejected", str(e), clock())
            return {"name": n, "kind": "verdict", "state": "rejected", "reason": str(e)}
        rid, pack, stamp = m.group(1), m.group(2), m.group(3) or ""
        d = _find_request_dir(app_dir, rid) or os.path.join(returns_dir(app_dir), _month(v["at"], clock()), rid)
        out = os.path.join(d, "verdicts")
        os.makedirs(out, exist_ok=True)
        fsio.write_json(os.path.join(out, pack + stamp + VERDICT_SUFFIX), dict(v, requestId=rid, pack=pack))   # ~<at> = 同じ切り抜きの判断・取り消しを並べる
        _judge_v2(app_dir, v, rid, pack, clock, log)
        if v["judge"] in ("bad", "unknown") and v.get("zip") and feedback is not None:
            _discard(feedback, v, rid, log)
        _move(folder, n, "accepted", "", clock())
        return {"name": n, "kind": "verdict", "state": "accepted", "reason": ""}
    m = outbox.NAME_RE.match(n)
    if not m:
        _move(folder, n, "rejected", "名前が <依頼 id>__<実行 id>.zip の形ではありません", clock())
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
            _move(folder, n, "rejected", "zip として読めません", clock())
            return {"name": n, "kind": "run", "state": "rejected", "reason": "壊れた zip"}
        return {"name": n, "kind": "run", "state": "wait", "reason": "同期の途中かもしれません"}
    except Refused as e:
        _rmtree(tmp)
        _move(folder, n, "rejected", str(e), clock())
        log("送り返し: %s を断りました(%s)" % (n, e))
        return {"name": n, "kind": "run", "state": "rejected", "reason": str(e)}
    if mf.get("requestId") not in (None, rid):   # 名前と中身の依頼 id が食い違う(置き場所は名前の方。印だけ残す)
        log("送り返し: %s の中の requestId が名前と違います" % n)
    _move(folder, n, "accepted", "", clock())
    return {"name": n, "kind": "run", "state": "accepted", "reason": ""}


def _discard(feedback, v, rid, log):
    """Dropbox で届けたパックの見送り・届かなくてよかったを片付ける(届けた記録に無ければ何もしない。失敗は記録に 1 行 = 判断は受け取る)"""
    fb = {"zip": v["zip"], "verdict": "reject", "requestId": rid, "title": "", "judged": True}   # judged = 判断の記録はこちらで書いた(apply は片付けだけ)
    if v.get("origin"):
        fb["origin"] = v["origin"]
    try:
        res = feedback(fb) or {}
    except (OSError, ValueError, RuntimeError) as e:
        res = {"ok": False, "reason": "%s: %s" % (e.__class__.__name__, str(e)[:120])}
    log("送り返し: 見送った %s を%s" % (v["zip"], "片付けました" if res.get("ok") else "片付けませんでした(%s)" % (res.get("reason") or "")[:160]))


def _delivered_pack(logs_dir, rid, pack):
    """届けた記録(② flow/deliveries)で、依頼 rid のパック pack(フォルダの名前)を引く -> (行, パック)。同じ名前が複数なら新しい行。引けなければ (None, None)"""
    found = (None, None)
    for r in deliveries.rows(logs_dir) or []:
        if r.get("requestId") != rid:
            continue
        for p in r.get("packs") or []:
            if isinstance(p, dict) and os.path.basename(str(p.get("dir") or "")) == pack:
                found = (r, p)
    return found


def _delivered_zip(logs_dir, zip_name):
    """届けた記録で zip の名前(1 本ずつ = パックは 1 つ)を引く -> (行, パック)。引けなければ (None, None)"""
    found = (None, None)
    for r in deliveries.rows(logs_dir) or []:
        if r.get("zip") == zip_name and r.get("packs") and isinstance(r["packs"][0], dict):
            found = (r, r["packs"][0])
    return found


def _judge_v2(app_dir, v, rid, pack, clock, log):
    """v 2 の判断を人の判断の記録に 1 行(who friend・via friend_verdict・key vd2:<友人の記録の id>)。
    good・bad(reason)・unknown(by auto)はそのまま what に。retract は of の記録の行(key vd2:<of>)を取り消す(見つからなければログだけ)。
    切り抜きは 届けた記録の zip → 依頼とパックの名前 → 届いた .meta.json から返った videoId・markId の順に引く(友人の PC で処理した物は 3 つ目だけ)"""
    at = v.get("at") or int(clock() * 1000)
    key = "vd2:" + v["id"]
    try:
        if v["judge"] == "retract":
            hit = next((r for r in judgments.rows(app_dir) if r.get("key") == "vd2:" + v["of"]), None)
            if hit is None:
                log("送り返し: 戻す %s の元の判断が人の判断の記録にありません" % pack)
                return
            judgments.record(app_dir, who="friend", what="retract", of=hit["id"], origin=hit["origin"], via="friend_verdict",
                             videoId=hit["videoId"], markId=hit["markId"], at=at, key=key, ref=hit.get("ref"))
            return
        logs = os.path.join(app_dir, LOGS_DIR)
        r, p = _delivered_zip(logs, v["zip"]) if v.get("zip") else (None, None)
        if r is None:
            r, p = _delivered_pack(logs, rid, pack)
        r, p = r or {}, p or {}
        vid, mid = str(r.get("videoId") or "") if p.get("markId") else "", str(p.get("markId") or "")
        if not mid and v.get("markId") and v.get("videoId"):
            vid, mid = v["videoId"], v["markId"]
        origin = v.get("origin") or (deliveries.origin_of(r) if r else "request")
        judgments.record(app_dir, who="friend", what=v["judge"], reason=v.get("reason"), by=v.get("by"), origin=origin, via="friend_verdict",
                         videoId=vid, markId=mid, at=at, key=key,
                         ref={"pack": pack, "requestId": rid, "zip": v.get("zip") or str(r.get("zip") or ""), "runId": str(r.get("runId") or "")})
    except (ValueError, OSError) as e:
        log("送り返し: %s の判断を人の判断の記録に書けませんでした(%s)" % (pack, tools.why(e)))


def _one_notice(folder, app_dir, n, p, clock, log):
    """[作る人に知らせる](C-2-16)の 1 つ: <依頼>\\notices\\ へ並べてログに 1 行。元は 受付済み へ"""
    m = NOTICE_RE.match(n)
    if not m:
        _move(folder, n, "rejected", "名前が <依頼 id>__notice-<時刻>%s の形ではありません" % NOTICE_SUFFIX, clock())
        return {"name": n, "kind": "notice", "state": "rejected", "reason": "名前の形"}
    if os.path.getsize(p) > MAX_NOTICE:
        _move(folder, n, "rejected", "大きすぎます", clock())
        return {"name": n, "kind": "notice", "state": "rejected", "reason": "大きすぎます"}
    try:
        with open(p, "rb") as f:
            d = parse_notice(f.read())
    except ValueError as e:
        _move(folder, n, "rejected", str(e), clock())
        return {"name": n, "kind": "notice", "state": "rejected", "reason": str(e)}
    rid = m.group(1)
    d["at"] = d["at"] or int(m.group(2))
    d["requestId"] = d["requestId"] or rid
    base = _find_request_dir(app_dir, rid) or os.path.join(returns_dir(app_dir), _month(d["at"], clock()), rid)
    out = os.path.join(base, NOTICES_DIR)
    os.makedirs(out, exist_ok=True)
    fsio.write_json(os.path.join(out, n), dict(d, receivedAt=int(clock() * 1000)))
    log("友人から知らせ: %s%s(詳しくはホームの「依頼の受付」)" % ((d["title"] + ": ") if d["title"] else "", d["message"][:200]))
    _move(folder, n, "accepted", "", clock())
    return {"name": n, "kind": "notice", "state": "accepted", "reason": ""}


def recent_notices(app_dir, now=None, days=NOTICE_DAYS, limit=NOTICE_SHOW):
    """ホームに出す友人からの知らせ(受け取ってから days 日の分・新しい順に limit 件)-> [{"at", "receivedAt", "requestId", "title", "message", "detail", "code",
    "appVersion", "hasLog"}]。ログの本文は並べたファイルに残す(画面には出さない)。読むだけ・壊れたファイルは飛ばす"""
    now = time.time() if now is None else now
    since = (now - days * 86400) * 1000
    out, root = [], returns_dir(app_dir)
    try:
        months = sorted(os.listdir(root))[-2:]   # 7 日なら今月と先月で足りる
    except OSError:
        return out
    for mo in months:
        mp = os.path.join(root, mo)
        try:
            rids = os.listdir(mp)
        except OSError:
            continue
        for rid in rids:
            nd = os.path.join(mp, rid, NOTICES_DIR)
            try:
                names = os.listdir(nd)
            except OSError:
                continue
            for nn in names:
                if not nn.endswith(NOTICE_SUFFIX):
                    continue
                d = fsio.read_json_or(os.path.join(nd, nn), None, kind=dict)
                got = d.get("receivedAt") if d else None
                if not isinstance(got, int) or got < since:
                    continue
                out.append({"at": d.get("at"), "receivedAt": got, "requestId": str(d.get("requestId") or rid), "hasLog": bool(d.get("log")),
                            **{k: str(d.get(k) or "") for k in ("title", "message", "detail", "code", "appVersion")}})
    out.sort(key=lambda x: x["receivedAt"], reverse=True)
    return out[:limit]


def _rmtree(path):
    shutil.rmtree(path, ignore_errors=True)


def iter_requests(app_dir):
    """並べた依頼の一覧 -> [{"month", "requestId", "dir", "runs": [{"runId", "dir", "manifest", "result"}], "verdicts": {名前: {judge, at}}}]。
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
                            if v and v.get("judge") in JUDGES:
                                verdicts[vn[:-len(VERDICT_SUFFIX)]] = dict(judge=v["judge"], at=v.get("at"),
                                                                           **({"origin": v["origin"]} if v.get("origin") in ORIGINS else {}))
                elif sub == NOTICES_DIR:
                    continue
                elif os.path.isdir(sp) and not sub.endswith(".part"):
                    runs.append({"runId": sub, "dir": sp, "manifest": fsio.read_json_or(os.path.join(sp, "manifest.json"), {}, kind=dict),
                                 "result": fsio.read_json_or(os.path.join(sp, "run.json"), {}, kind=dict)})
            out.append({"month": mo, "requestId": rid, "dir": rp, "runs": runs, "verdicts": verdicts})
    return out

