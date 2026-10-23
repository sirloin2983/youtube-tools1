"""元の配信とガイドラインの見張り(10-23。提案 P7・人の作業なしの候補の 13 番。表は保管庫 plan/人の作業なしの候補-1023.md)。

- 元の配信(週 1 回): 友人へ届けた切り抜きの元の配信(入口の logs/deliveries.jsonl の videoId。新しい物から SOURCE_MAX 本)を
  YouTube Data API の videos.list(part=status。50 本で 1 ユニット)で見て、公開でなくなった(非公開・限定公開・削除)物を記録する。
  前の回から変わった物だけを「新しい」とする。メンバー限定になったかは API では分からない(見ない)
- ガイドライン(月 1 回): 所属事務所の二次創作のガイドラインのページ(TERMS_URL)の「改定・改訂・制定」の日付を読み、前の回と違えば記録する。
  日付が読めなければ変わったとは言わない(ページの作りが変わっただけで知らせない)
- 結果は入口の作業データの watch.json。ホームの「調子」が読む(view)。見に行くのは「調子」を開いたときに期限を過ぎていれば裏で 1 回(due)
- 非公開になった配信の切り抜きをどうするかは決まっていない(提案 P7 の「議論」)= ここは知らせるだけ
- スイッチ: 環境変数 YTT_WATCH=0 で見ない。作業データを切り離したテスト・見本(YTT_DATA_DIR=inplace)でも見ない
"""
import json
import os
import re
import threading
import time
import urllib.request

from ytt import fsio as _fsio, version as _version, ytapi as _ytapi
from ytt.errors import ApiError

SWITCH_ENV = "YTT_WATCH"
STATE = "watch.json"
DELIVERIES = "deliveries.jsonl"
SOURCE_EVERY = 7 * 86400
TERMS_EVERY = 30 * 86400
SOURCE_MAX = 200               # 見る元の配信の本数(新しい物から。4 ユニット)
TERMS_URL = "https://hololivepro.com/terms/"
TERMS_MAX = 2 * 1024 * 1024
DATE_RE = re.compile(r"(20\d\d)\s*[年./-]\s*(\d{1,2})\s*[月./-]\s*(\d{1,2})\s*日?[^\n<]{0,12}?(改定|改訂|制定|更新)")
GONE = "削除されたか、見られません"
PRIVACY = {"private": "非公開", "unlisted": "限定公開"}


def enabled(env=None):
    env = os.environ if env is None else env
    return env.get(SWITCH_ENV) != "0" and env.get("YTT_DATA_DIR") != "inplace"


def delivered_sources(logs_dir, limit=SOURCE_MAX):
    """届けた切り抜きの元の配信 -> [(videoId, 題)](新しい順・重なりなし)"""
    out, seen = [], set()
    try:
        with open(os.path.join(logs_dir, DELIVERIES), encoding="utf-8", errors="replace") as f:
            lines = f.readlines()
    except OSError:
        return []
    for line in reversed(lines):
        try:
            d = json.loads(line)
        except ValueError:
            continue
        vid = d.get("videoId") if isinstance(d, dict) else None
        if isinstance(vid, str) and re.fullmatch(r"[\w-]{11}", vid) and vid not in seen:
            seen.add(vid)
            out.append((vid, str(d.get("title") or "")[:200]))
            if len(out) >= limit:
                break
    return out


def check_sources(sources, get=None):
    """[(videoId, 題)] -> {videoId: {"title", "state"}}(公開でない物だけ。state = 非公開・限定公開・削除されたか…)。API の失敗は ApiError"""
    get = get or _ytapi.get
    titles = dict(sources)
    found, out = {}, {}
    ids = [v for v, _t in sources]
    for i in range(0, len(ids), 50):
        part = ids[i:i + 50]
        r = get("videos", {"part": "status", "id": ",".join(part), "maxResults": 50})
        for it in (r or {}).get("items") or []:
            found[it.get("id")] = ((it.get("status") or {}).get("privacyStatus") or "")
        for v in part:
            st = found.get(v)
            if st is None:
                out[v] = {"title": titles.get(v, ""), "state": GONE}
            elif st != "public":
                out[v] = {"title": titles.get(v, ""), "state": PRIVACY.get(st, st)}
    return out


def _fetch(url, max_bytes=TERMS_MAX):
    req = urllib.request.Request(url, headers={"User-Agent": "ytt/%s" % _version.VERSION})
    with urllib.request.urlopen(req, timeout=20) as r:   # noqa: S310  (固定の https)
        return r.read(max_bytes)


def terms_mark(html):
    """ガイドラインのページ -> 改定などの日付の並び("2025-03-01 改定" …。新しい順)か ""(読めない)"""
    text = re.sub(r"<[^>]+>", " ", html or "")
    got = {"%s-%02d-%02d %s" % (m.group(1), int(m.group(2)), int(m.group(3)), m.group(4)) for m in DATE_RE.finditer(text)}
    return " / ".join(sorted(got, reverse=True))


class Watch:
    """view() = 「調子」に出す形。期限を過ぎていれば裏で 1 回見に行く(get・fetch・clock はテストで差し替える)"""

    def __init__(self, app_dir, logs_dir, log=None, get=None, fetch=None, clock=time.time, env=None):
        self.path = os.path.join(app_dir, STATE)
        self.logs_dir = logs_dir
        self.log = log or (lambda m: None)
        self.get, self.fetch, self.clock, self.env = get, fetch or _fetch, clock, env
        self._lock = threading.Lock()
        self._running = False

    def state(self):
        return _fsio.read_json_or(self.path, {}, kind=dict)

    def _save(self, s):
        try:
            _fsio.write_json(self.path, s)
        except OSError:
            pass

    def view(self, start=True):
        """{"sources": {"at", "checked", "changed": [{videoId, title, state, since}], "error"}, "terms": {"at", "mark", "changedAt", "prev", "error"}} か None(まだ何も無い)"""
        if start:
            self.due()
        s = self.state()
        return {k: s[k] for k in ("sources", "terms") if k in s} or None

    def due(self):
        """期限を過ぎていれば裏で見る(同時に 1 つ)-> 始めたか"""
        if not enabled(self.env):
            return False
        s, now = self.state(), self.clock()
        want = now - float((s.get("sources") or {}).get("at") or 0) >= SOURCE_EVERY or now - float((s.get("terms") or {}).get("at") or 0) >= TERMS_EVERY
        with self._lock:
            if not want or self._running:
                return False
            self._running = True
        threading.Thread(target=self._run_safe, daemon=True, name="watch").start()
        return True

    def _run_safe(self):
        try:
            self.run()
        finally:
            with self._lock:
                self._running = False

    def run(self, now=None):
        """期限を過ぎた物を見る(同じスレッドで。テストはこれを呼ぶ)-> state"""
        now = self.clock() if now is None else now
        s = self.state()
        src = dict(s.get("sources") or {})
        if now - float(src.get("at") or 0) >= SOURCE_EVERY:
            sources = delivered_sources(self.logs_dir)
            try:
                got = check_sources(sources, self.get)
                prev = {x["videoId"]: x for x in src.get("changed") or [] if isinstance(x, dict)}
                changed = [dict(v, videoId=k, since=(prev[k]["since"] if k in prev and prev[k].get("state") == v["state"] else int(now * 1000)))
                           for k, v in got.items()]
                new = [x for x in changed if x["since"] == int(now * 1000)]
                src = {"at": now, "checked": len(sources), "changed": changed, "error": ""}
                if new:
                    self.log("見張り: 届けた切り抜きの元の配信が公開でなくなりました %d 本(%s)" % (len(new), "・".join("%s %s" % (x["videoId"], x["state"]) for x in new[:5])))
            except ApiError as e:   # キーが無い・上限など: 次の期限まで待つ(理由を出す)
                src = dict(src, at=now, error=str(e)[:200])
            s["sources"] = src
        terms = dict(s.get("terms") or {})
        if now - float(terms.get("at") or 0) >= TERMS_EVERY:
            try:
                mark = terms_mark(self.fetch(TERMS_URL).decode("utf-8", "replace"))
                if mark and terms.get("mark") and mark != terms["mark"]:
                    terms.update(prev=terms["mark"], changedAt=int(now * 1000))
                    self.log("見張り: ガイドラインの改定の日付が変わりました(%s → %s)" % (terms["prev"], mark))
                terms.update(at=now, mark=mark or terms.get("mark") or "", error="" if mark else "改定の日付を読めませんでした(ページの形が変わったかもしれません)")
            except (OSError, ValueError) as e:
                terms.update(at=now, error="ページを読めませんでした(%s)" % e.__class__.__name__)
            terms["url"] = TERMS_URL
            s["terms"] = terms
        self._save(s)
        return s
