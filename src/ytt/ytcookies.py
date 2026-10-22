# -*- coding: utf-8 -*-
"""YouTube のログインの cookie を長持ちさせる(友人の PC。notes:docs/spec/friend.md の 13-13)。

yt-dlp には呼ぶたびの写し(<secrets>/run/)を渡す(ytt/tools.ytdlp_auth_args)。yt-dlp は終わると写しへ cookie を書き戻す
(YouTube が応答で回した新しい値)。元へ戻さないと古い値を使い続けて無効にされやすいので、次に yt-dlp を呼ぶ前にここで元へ戻す(merge_back)。
- 戻す写し: 名前の作った時刻より後に書かれた(= yt-dlp が書き戻した)・2 秒以上動いていない物。古い順に 1 つずつ。ロック(取れなければ次の回)
- 捨てる写し: 読めない・cookie が 1 つも無い(壊れた)・写した後に元が書き替わった(ログインし直した)・ログインの cookie が消えた
  (= YouTube がログインを切った。消える向きの書き戻しはしない。切れた時刻を記録 lostAt)
- 混ぜ方: 元の行を全部残し、写しの行で上書き・足す(写しが元の今の中身から作った物なら写しの勝ち、そうでなければ期限が同じか後の物だけ)。元から消す行は無い
- 書き方: 原子的な置き換え(ytt/fsio.atomic_write)。書いた後の更新時刻を記録へ(= ログインの時刻と区別する)
- 記録 <cookies の名前>.state.json: loginAt(ログインした時刻 = 外から元が書かれた時刻)・lostAt・merged・mergedAt・rejected・rejectedAt・rejectedWhy・wroteNs・loginNs
cookie の値は読まない(行の名前・domain・期限だけ見る。値は行ごとそのまま運ぶ)・ログに出さない。スイッチ: 環境変数 YTT_COOKIES_MERGE=0 で戻さない(今までの形)。
"""
import os
import re
import time

from . import fsio as _fsio

SWITCH_ENV = "YTT_COOKIES_MERGE"
RUN = "run"
LOCK = ".merge.lock"
HEADER = "# Netscape HTTP Cookie File"
HTTPONLY = "#HttpOnly_"
COPY_RE = re.compile(r"^(\d{13})-\d+-[0-9a-f]+-b(\d+)\.txt$")   # 作った時刻(ミリ秒)-pid-乱数-b<写したときの元の更新時刻 ns>
WROTE_AFTER_MS = 1500   # 作った時刻よりこれだけ後に書かれていれば yt-dlp が書き戻した
SETTLE_SEC = 2          # 書かれてからこれだけ動いていなければ書き終わった
MAX_BYTES = 4 * 1024 * 1024
# ログインそのものの cookie(どれかが写しで消えていれば YouTube がログインを切った)
LOGIN_NAMES = frozenset(("SID", "HSID", "SSID", "APISID", "SAPISID", "__Secure-1PSID", "__Secure-3PSID", "LOGIN_INFO"))


def enabled(env=None):
    env = os.environ if env is None else env
    return (env.get(SWITCH_ENV) or "").strip() != "0"


def state_path(src):
    return os.path.splitext(src)[0] + ".state.json"


def read_state(src):
    s = _fsio.read_json_or(state_path(src), {})
    return s if isinstance(s, dict) else {}


def _write_state(src, s):
    try:
        _fsio.write_json(state_path(src), s)
    except OSError:
        pass


def copy_name(now, base_ns):
    """写しの名前(作った時刻・写したときの元の更新時刻を持つ)"""
    return "%d-%d-%s-b%d.txt" % (int(now * 1000), os.getpid(), os.urandom(3).hex(), base_ns)


def parse(data):
    """Netscape 形式 -> [(キー (domain, path, name) か None, 期限, 行)]。cookie でない行(注釈・空行)はキー None。読めなければ None。
    値は見ない(行ごと運ぶ)"""
    try:
        text = data.decode("utf-8")
    except UnicodeDecodeError:
        return None
    rows = []
    for line in text.splitlines():
        body = line[len(HTTPONLY):] if line.startswith(HTTPONLY) else line
        if not body.strip() or body.startswith("#"):
            rows.append((None, 0, line))
            continue
        f = body.split("\t")
        if len(f) != 7 or not f[0] or not f[5]:
            return None
        try:
            exp = int(f[4] or 0)
        except ValueError:
            return None
        rows.append(((f[0].lower().lstrip("."), f[2], f[5]), exp, line))
    return rows


def _logins(rows, now):
    """ログインの cookie のキーの集まり(期限切れは除く。期限 0 = セッションの cookie)"""
    return {k for k, exp, _l in rows if k is not None and k[2] in LOGIN_NAMES and (exp == 0 or exp > now)}


def merge_rows(src_rows, copy_rows, copy_wins):
    """元の行に写しの行を混ぜる -> 行の文字の並び(元から消す行は無い)"""
    out, at = [], {}
    for k, exp, line in src_rows:
        if k is not None:
            at[k] = len(out)
        out.append([k, exp, line])
    for k, exp, line in copy_rows:
        if k is None:
            continue
        if k not in at:
            at[k] = len(out)
            out.append([k, exp, line])
        elif copy_wins or exp == 0 or exp >= out[at[k]][1]:
            out[at[k]][1:] = [exp, line]
    lines = [r[2] for r in out]
    if not lines or not lines[0].startswith("# Netscape"):
        lines.insert(0, HEADER)
    return lines


def _read(path):
    with open(path, "rb") as f:
        return f.read(MAX_BYTES + 1)


def merge_back(src, now=None, env=None):
    """yt-dlp が書き戻した写しを元へ戻す(上の説明)-> {"merged", "rejected", "busy"}。失敗しても例外は出さない(次の回)"""
    out = {"merged": 0, "rejected": 0, "busy": False}
    if not src or not enabled(env):
        return out
    run = os.path.join(os.path.dirname(src), RUN)
    if not os.path.isdir(run):
        return out
    lock = _fsio.try_lock(os.path.join(run, LOCK))
    if lock is None:
        out["busy"] = True
        return out
    try:
        _merge_locked(src, run, time.time() if now is None else now, out)
    except OSError:
        pass
    finally:
        _fsio.unlock(lock)
    return out


def _merge_locked(src, run, now, out):
    try:
        st = os.stat(src)
    except OSError:
        return   # ログアウトした = 写しは要らない(24 時間で消える)
    s = read_state(src)
    if s.get("wroteNs") != st.st_mtime_ns and s.get("loginNs") != st.st_mtime_ns:   # 外(ログインの小窓)が書いた = ログインした
        s.update(loginNs=st.st_mtime_ns, loginAt=int(st.st_mtime * 1000), wroteNs=None)
    cands = []
    for n in os.listdir(run):
        m = COPY_RE.match(n)
        if not m:
            continue
        p = os.path.join(run, n)
        try:
            mt = os.path.getmtime(p)
        except OSError:
            continue
        if mt * 1000 > int(m.group(1)) + WROTE_AFTER_MS and now - mt >= SETTLE_SEC:
            cands.append((mt, p, int(m.group(2))))
    changed = False
    for _mt, p, base in sorted(cands):
        why = _merge_one(src, p, base, s, now)
        if why == "merged":
            out["merged"] += 1
            changed = True
            s["merged"] = int(s.get("merged") or 0) + 1
            s["mergedAt"] = int(now * 1000)
        elif why != "same":
            out["rejected"] += 1
            changed = True
            s["rejected"] = int(s.get("rejected") or 0) + 1
            s.update(rejectedAt=int(now * 1000), rejectedWhy=why)
            if why == "lost":
                s["lostAt"] = int(now * 1000)
        _fsio.unlink_quiet(p)
    if changed or s != read_state(src):
        _write_state(src, s)


def _merge_one(src, p, base, s, now):
    """写し 1 つ -> merged・same(変わらない)・broken・stale(写した後にログインし直した)・lost(ログインが切れた)"""
    try:
        data = _read(p)
    except OSError:
        return "broken"
    rows = parse(data) if 0 < len(data) <= MAX_BYTES else None
    if not rows or not any(k for k, _e, _l in rows):
        return "broken"
    if base < int(s.get("loginNs") or 0):
        return "stale"
    try:
        cur_ns = os.stat(src).st_mtime_ns
        src_rows = parse(_read(src))
    except OSError:
        return "stale"
    if src_rows is None:
        return "stale"   # 元が読めない = 触らない(ログインし直すまで)
    if _logins(src_rows, now) - _logins(rows, now):
        return "lost"
    lines = merge_rows(src_rows, rows, copy_wins=(base == cur_ns))
    if lines == [r[2] for r in src_rows]:
        return "same"
    _fsio.atomic_write(src, ("\n".join(lines) + "\n").encode("utf-8"))
    s["wroteNs"] = os.stat(src).st_mtime_ns
    return "merged"


def login_at(src):
    """ログインした時刻(ミリ秒)か 0。元を書き戻しで書き替えても変わらない(記録の loginAt)"""
    try:
        if not src or os.path.getsize(src) <= 0:
            return 0
        st = os.stat(src)
    except OSError:
        return 0
    s = read_state(src)
    if s.get("wroteNs") == st.st_mtime_ns and s.get("loginAt"):
        return int(s["loginAt"])
    return int(st.st_mtime * 1000)


def facts(src):
    """診断に入れる物(時刻と数だけ。値・名前は入れない)-> dict か None(ログインしていない)"""
    at = login_at(src)
    if not at:
        return None
    s = read_state(src)
    out = {"loginAt": at}
    for k in ("lostAt", "merged", "mergedAt", "rejected", "rejectedAt", "rejectedWhy"):
        if s.get(k) is not None:
            out[k] = s[k]
    if (out.get("lostAt") or 0) < at:
        out.pop("lostAt", None)
    return out


def forget(src):
    """ログアウトのとき記録も消す"""
    _fsio.unlink_quiet(state_path(src))
