# -*- coding: utf-8 -*-
"""アプリのフォルダの整理(形は Fable と相談 = 共有のメモ f3a-tidy-design.md。決定 3-86)。新しい版に入れ替えて起動できたあとと ⚙ から。

決まり:
- 許可の一覧(下の KINDS と各 _scan_*)に載る形の物だけが候補。載らない物は「分からない」= 消さず記録だけ(書き忘れ = 残る = 安全の向き)
- 黙って片付ける(auto): 作り直せる・写しが別にある・途中の物(*.old・更新の取り残し・学習の束の .part・回したログ・exe が消し損ねた古い版)。
  ただし 1 件 AUTO_MAX を超える物と、1 回で AUTO_TOTAL を超える分は聞く側へ回す(想定外の形の印)
- 1 回聞いて片付ける(ask): 友人の物かもしれない・判断が要る物(前の形の src・python・片付け忘れた作業のフォルダ・使っていないモデルと道具)。
  大きさでなく種類で分ける(小さくても友人の依頼かもしれない物は聞く)
- 触らない: ライブの録画(録画の部品が持ち主)・学習の束(同期が直近 3 版で回す)・受け取った物・受信箱の記録・設定と鍵・ごみ箱の中・印の無い物・
  current・previous・bad・自分の版・最後に書かれてから 24 時間以内の物(未来の時刻も新しい扱い・1970 年などの壊れた時刻は分からない扱い)
- 消し方: ごみ箱 = アプリのごみ箱(Windows のごみ箱は大きい物が確認なしで消えるので使わない)。同じドライブだけ(改名 1 回・別のドライブへ写さない):
  <一時保管>/ごみ箱/<YYYYMMDD>/整理/<種類>/(受信箱の 3 日の片付けが消す)か、別のドライブなら <home>/ごみ箱/<YYYYMMDD>/整理/(ここで 3 日で消す)。
  <日付>/manifest.jsonl に元の場所を 1 行ずつ。写しがある・作り直せる物(auto の消し方 delete)は直接消す
- 守り: 置き場所の外のパス・ネットワーク・リンクと接合点(とその中)は触らない。作業データの lock に別の持ち主がいたら作業のフォルダとモデルは見ない。
  使用中で動かせない物は飛ばして記録(次の回にまた)。走査(scan)は副作用なし・実行(apply)は移す口と消す口を差し替えられる(テストは本物を触らない)
"""
import datetime
import hashlib
import json
import os
import re
import shutil
import threading
import time

from flow import placement as _placement
from ytt import fsio as _fsio, trashbin as _trashbin

DAY = 86400
FRESH = DAY                 # 最後に書かれてからこの秒数より新しい物は候補にしない
CASE_DAYS = _trashbin.KEEP_DAYS   # 片付け忘れた作業のフォルダ・回したログの日数(物の終わりの日数)
AUTO_MAX = 100 * 1024 ** 2  # 黙る側の 1 件の上限(超えたら聞く)
AUTO_TOTAL = 20 * 1024 ** 3  # 1 回の自動で動かす量の上限(超えた分は聞く)
EPOCH_SANE = 946684800      # 2000-01-01。これより古い時刻は壊れた時刻 = 分からない
STATE_NAME = "cleanup.json"
TRASH_NAME = _trashbin.TRASH_DIR
TIDY_SUB = "整理"
APP_RE = re.compile(r"^app-(\d+\.\d+\.\d+)$")
LEFTOVER_RE = re.compile(r"^app-(\d+\.\d+\.\d+)(\.tmp|\.zip\.part)$")
LAUNCHER_FILES = ("FriendApp.exe", "Microsoft.Web.WebView2.Core.dll", "Microsoft.Web.WebView2.WinForms.dll", "WebView2Loader.dll")
ROTATED_LOGS = ("friendapp.log.1", "launcher.log.old", "autorun-runs.jsonl.1", "client-errors.jsonl.1")   # 回した 1 世代だけ(判定の記録の .old は入れない)
CASE_MARKS = (("作業用", "case.json"), ("作業用", ".studio-id"))   # アプリが作った作業のフォルダの印
SKIP_IN_CASES = (TRASH_NAME, "ライブの録画")                      # 一時保管の中で見ない(ごみ箱・録画の部品の物)
KNOWN_HOME = set(LAUNCHER_FILES) | {"config.json", "keys.json", "fetch.json", "members.json", "app-versions.json", "src", "python", "tools", "data",
                                    "作業", TRASH_NAME, "FriendApp-はじめに.txt", "manifest.json", "INSTALL.txt"}
KINDS = {   # 種類: (画面の言葉, 扱い, 消し方)
    "old-exe": ("前の版の exe の残り", "auto", "delete"),
    "update-leftover": ("更新の取り残し", "auto", "delete"),
    "learning-part": ("学習の束の取り残し", "auto", "delete"),
    "old-log": ("古いログ", "auto", "delete"),
    "old-version": ("古い版のフォルダ", "auto", "trash"),
    "legacy": ("前の形の部品(src・python)", "ask", "trash"),
    "orphan-case": ("片付け忘れた作業のフォルダ", "ask", "trash"),
    "unused-model": ("使っていないモデル", "ask", "trash"),
    "unused-tool": ("使っていない道具", "ask", "trash"),
}


def _vt(v):
    try:
        return tuple(int(x) for x in v.split("."))
    except (AttributeError, ValueError):
        return (0,)


def _newest_mtime(path, limit=20000):
    """ファイルはその mtime・フォルダは中の最新(リンクは辿らない)。読めなければ None"""
    lp = _fsio.long_path(path)
    try:
        best = os.stat(lp).st_mtime
    except OSError:
        return None
    if not os.path.isdir(lp):
        return best
    n = 0
    for root, dirs, files in os.walk(lp):
        dirs[:] = [d for d in dirs if not _fsio.is_link(os.path.join(root, d))]
        for f in files:
            n += 1
            if n > limit:
                return best
            try:
                best = max(best, os.stat(os.path.join(root, f)).st_mtime)
            except OSError:
                continue
    return best


def _size_or_0(path):
    try:
        return os.path.getsize(path)
    except OSError:
        return 0


def _size(path):
    return _fsio.dir_size(_fsio.long_path(path))[0]


def _has_link_inside(path):
    lp = _fsio.long_path(path)
    if _fsio.is_link(lp):
        return True
    if not os.path.isdir(lp):
        return False
    for root, dirs, _files in os.walk(lp):
        for d in dirs:
            if _fsio.is_link(os.path.join(root, d)):
                return True
    return False


def _abs_strings(obj, out):
    """JSON の中の絶対パスらしい文字列を全部集める(受信箱・待ち行列が指している物 = 片付けない物)"""
    if isinstance(obj, str):
        if len(obj) > 3 and os.path.isabs(obj):
            out.add(os.path.normcase(os.path.normpath(obj)))
    elif isinstance(obj, dict):
        for v in obj.values():
            _abs_strings(v, out)
    elif isinstance(obj, list):
        for v in obj:
            _abs_strings(v, out)
    return out


def _touches(path, refs):
    """path の中か、path を中に含む物が refs にあるか"""
    p = os.path.normcase(os.path.normpath(path))
    for r in refs:
        if r == p or r.startswith(p + os.sep) or p.startswith(r + os.sep):
            return True
    return False


class Tidy:
    """玄関に 1 つ。places = 置き場所・inbox = 受信箱・queue_fn() = ② の待ち行列か None・setup = 初回の準備の係・sync = 同期・version = 今の版。
    move(src, dst)・remove(path)・rmtree(path) = 動かす・消す口(テストは差し替える)"""

    def __init__(self, places, inbox, queue_fn=lambda: None, setup=None, sync=None, version="0.0.0", env=None, clock=time.time, log=None,
                 move=None, remove=None, rmtree=None, open_folder=None):
        self.places, self.inbox, self.queue_fn, self.setup, self.sync, self.version = places, inbox, queue_fn, setup, sync, version
        self.env = os.environ if env is None else env
        self.clock, self.log = clock, log or (lambda msg: None)
        self.move = move or (lambda a, b: os.replace(_fsio.long_path(a), _fsio.long_path(b)))
        self.remove = remove or (lambda p: os.remove(_fsio.long_path(p)))
        self.rmtree = rmtree or (lambda p: shutil.rmtree(_fsio.long_path(p)))
        self.open_folder = open_folder
        self.lock = threading.Lock()
        self.thread = None
        self.items = []          # 最後に調べた候補
        self.unknown = []        # 分からない物 [(名前, 大きさ)]
        self.started = clock()
        self.st = _fsio.read_json_or(self._state_path(), {}, kind=dict)

    # ---------------------------------------------------------------- 場所
    def _state_path(self):
        return os.path.join(self.places["friend"], STATE_NAME)

    def _save_state(self):
        try:
            _fsio.write_json(self._state_path(), self.st, indent=1)
        except OSError as e:
            self.log("整理の記録を書けませんでした: %s" % e.__class__.__name__)

    def home(self):
        return self.places.get("home") or ""

    def data(self):
        return self.places["data"]

    def case_roots(self):
        """見る一時保管(今の場所と既定の <home>/作業。選び直しても移さないので両方)"""
        out = []
        for r in (self.places.get("cases"), os.path.join(self.home(), "作業") if self.home() else None):
            if r and os.path.isdir(_fsio.long_path(r)) and not _fsio.is_link(r) and os.path.normcase(r) not in [os.path.normcase(x) for x in out]:
                out.append(r)
        return out

    def _versions(self):
        d = _fsio.read_json_or(os.path.join(self.home(), "app-versions.json"), None, kind=dict)
        return d if isinstance(d, dict) else None

    # ---------------------------------------------------------------- 調べる(副作用なし)
    def blocked(self):
        """今は調べない・片付けない理由(作業中など)か None"""
        q = self.queue_fn()
        try:
            st = q.status() if q is not None else {"idle": True}
        except Exception:   # noqa: BLE001
            st = {"idle": False}
        if not st.get("idle", True):
            return "作っている物があるので、終わってから整理します"
        if self.sync is not None and self.sync.busy():
            return "同期の途中なので、少しあとで整理します"
        if self.setup is not None and (self.setup.awake() or not self.setup.done):
            return "初回の準備が済んでから整理します"
        try:
            if any(r.get("state") in ("waiting", "recording", "sent", "making") for r in self.inbox.view()):
                return "送った物を作っている・待っている間は整理しません"
        except Exception:   # noqa: BLE001
            return "受信箱を読めないので整理しません"
        return None

    def _fresh(self, path, now):
        """新しすぎる(24 時間以内・未来)か、時刻が壊れている = 候補にしない"""
        m = _newest_mtime(path)
        return m is None or m < EPOCH_SANE or now - m < FRESH

    def _item(self, kind, path, size=None, where=None):
        label, mode, how = KINDS[kind]
        size = _size(path) if size is None else size
        rel = where or (os.path.relpath(path, self.home()) if self.home() and _fsio.is_inside(path, self.home()) else path)
        iid = hashlib.sha1((kind + "\0" + os.path.normcase(path)).encode("utf-8")).hexdigest()[:12]
        return {"id": iid, "kind": kind, "label": label, "path": path, "where": rel, "bytes": size, "mode": mode, "how": how}

    def scan(self):
        """候補を調べる -> {"items": [...], "unknown": [(名前, 大きさ)]}。何も動かさない"""
        now = self.clock()
        items, unknown = [], []
        home = self.home()
        if home and os.path.isdir(home) and not _fsio.is_link(home):
            items += self._scan_home(home, now, unknown)
        items += self._scan_data(now)
        other = _placement.lock_info(self.data())
        if not (other and other.get("pid") not in (None, os.getpid())):   # 同じ作業データを 2 つ目のアプリが使っている = 作業のフォルダとモデルは見ない
            items += self._scan_cases(now, unknown)
            items += self._scan_parts(now)
        # 黙る側の上限: 1 件 AUTO_MAX・合わせて AUTO_TOTAL を超えたら聞く
        total = 0
        for it in items:
            if it["mode"] == "auto":
                total += it["bytes"]
                if it["bytes"] > AUTO_MAX or total > AUTO_TOTAL:
                    it["mode"] = "ask"
        return {"items": items, "unknown": unknown}

    def _scan_home(self, home, now, unknown):
        out = []
        rec = self._versions()
        cur, prev = (rec or {}).get("current") or "", (rec or {}).get("previous") or ""
        bad = set((rec or {}).get("bad") or [])
        keep = {cur, prev, self.version} | bad
        for name in sorted(os.listdir(home)):
            path = os.path.join(home, name)
            if _fsio.is_link(path):
                continue
            if name.endswith(".old") and name[:-4] in LAUNCHER_FILES:
                out.append(self._item("old-exe", path))
                continue
            m = LEFTOVER_RE.match(name)
            if m:
                if m.group(1) not in keep and not (self.sync is not None and self.sync.busy()) and not self._fresh(path, now):
                    out.append(self._item("update-leftover", path))
                continue
            m = APP_RE.match(name)
            if m:
                v = m.group(1)
                if rec is not None and prev and v not in keep and _vt(v) < _vt(prev) and not _has_link_inside(path):
                    out.append(self._item("old-version", path))
                continue
            if name in KNOWN_HOME:
                continue
            unknown.append((name, _size_or_0(path) if os.path.isfile(path) else 0))
        # 前の形(直下の src・python): exe の Prune の条件(current・previous の版のフォルダがそろい、前の形の版 <= previous)なのに残っている物
        lv = self._legacy_version(home)
        if rec is not None and cur and prev and os.path.isdir(os.path.join(home, "app-" + cur)) and os.path.isdir(os.path.join(home, "app-" + prev)) \
                and (lv is None or _vt(lv) <= _vt(prev)):
            for d in ("src", "python"):
                p = os.path.join(home, d)
                if os.path.isdir(p) and not _has_link_inside(p) and _vt(self.version) > (0,) and self.version != lv:
                    out.append(self._item("legacy", p))
        return out

    def _legacy_version(self, home):
        p = os.path.join(home, "src", "ytt", "version.py")
        try:
            with open(p, encoding="utf-8") as f:
                m = re.search(r'^VERSION\s*=\s*"([0-9.]+)"', f.read(), re.M)
            return m.group(1) if m else None
        except OSError:
            return None

    def _scan_data(self, now):
        out = []
        logs = os.path.join(self.places["friend"], "logs")
        for name in ROTATED_LOGS:
            p = os.path.join(logs, name)
            m = _newest_mtime(p) if os.path.isfile(p) else None
            if m is not None and m >= EPOCH_SANE and now - m >= CASE_DAYS * DAY:
                out.append(self._item("old-log", p))
        learn = os.path.join(self.data(), "learning")
        if os.path.isdir(learn) and not _fsio.is_link(learn):
            for name in os.listdir(learn):
                p = os.path.join(learn, name)
                if name.endswith(".part") and os.path.isdir(p) and not _fsio.is_link(p) and not self._fresh(p, now):
                    out.append(self._item("learning-part", p))
        return out

    def _refs(self):
        """受信箱の全部の行(済みも)と待ち行列(実行中・待ち・記録)が指しているパス"""
        refs = set()
        try:
            _abs_strings(_fsio.read_json_or(self.inbox.path, {}, kind=dict), refs)
        except Exception:   # noqa: BLE001
            refs.add("*")   # 読めない = 何も片付けない
        q = self.queue_fn()
        if q is not None:
            try:
                _abs_strings(q.status(), refs)
                _abs_strings(q.history(limit=200), refs)
            except Exception:   # noqa: BLE001
                refs.add("*")
        return refs

    def _scan_cases(self, now, unknown):
        out = []
        refs = self._refs()
        if "*" in refs:
            return out
        try:
            ids = {r.get("id") for r in _fsio.read_json_or(self.inbox.path, {}, kind=dict).get("rows") or [] if isinstance(r, dict)}
        except Exception:   # noqa: BLE001
            return out
        for root in self.case_roots():
            for base in (root, os.path.join(root, "依頼")):
                if not os.path.isdir(_fsio.long_path(base)) or _fsio.is_link(base):
                    continue
                for name in os.listdir(_fsio.long_path(base)):
                    p = os.path.join(base, name)
                    if name in SKIP_IN_CASES or (base == root and name == "依頼") or not os.path.isdir(_fsio.long_path(p)) or _fsio.is_link(p):
                        continue
                    if not any(os.path.isfile(_fsio.long_path(os.path.join(p, *mk))) for mk in CASE_MARKS):
                        unknown.append((os.path.relpath(p, root), 0))
                        continue
                    if _touches(p, refs):
                        continue
                    cj = _fsio.read_json_or(_fsio.long_path(os.path.join(p, "作業用", "case.json")), {}, kind=dict)
                    if cj.get("requestId") in ids and cj.get("requestId"):
                        continue
                    m = _newest_mtime(p)
                    if m is None or m < EPOCH_SANE or now - m < CASE_DAYS * DAY or _has_link_inside(p):
                        continue
                    out.append(self._item("orphan-case", p, where=os.path.relpath(p, root)))
        return out

    def _scan_parts(self, now):
        """使っていないモデルと道具: 準備済み・fetch.json の物が全部そろっているときだけ。fetch.json の置き場所の中で、どの行の物でもない物"""
        out = []
        st = self.setup
        if st is None or not st.done:
            return out
        try:
            items = st.items()
            if not items or st.missing():
                return out
        except Exception:   # noqa: BLE001
            return out
        named = self._config_text()
        tx = os.path.join(self.data(), "transcribe")
        want_files, model_dirs, tool_dirs = set(), set(), set()
        for it in items:
            base = self.data() if it.get("base") == "data" else self.home()
            dest = os.path.normpath(os.path.join(base, *(it.get("dest") or "").split("/")))
            for x in [it.get("file"), it.get("member"), it.get("top")] + list(it.get("parts") or []):
                if x:
                    want_files.add(os.path.basename(str(x)).lower())
            if _fsio.is_inside(dest, os.path.join(tx, "models"), strict=True):
                model_dirs.add(dest)
            if self.home() and _fsio.is_inside(dest, os.path.join(self.home(), "tools"), strict=True):
                tool_dirs.add(os.path.normcase(dest))
        for d in sorted(model_dirs):
            if not os.path.isdir(d) or _fsio.is_link(d):
                continue
            for name in os.listdir(d):
                p = os.path.join(d, name)
                if not os.path.isfile(p) or name.lower() in want_files or name.startswith(".fetched-") or name.lower() in named or self._fresh(p, now):
                    continue
                out.append(self._item("unused-model", p))
        tools = os.path.join(self.home(), "tools") if self.home() else ""
        if tools and os.path.isdir(tools) and not _fsio.is_link(tools):
            for name in os.listdir(tools):
                p = os.path.join(tools, name)
                if not os.path.isdir(p) or _fsio.is_link(p) or name.lower().startswith("whisper.cpp-"):
                    continue
                if any(os.path.normcase(p) == t or t.startswith(os.path.normcase(p) + os.sep) for t in tool_dirs):
                    continue
                if any(f.startswith(".fetched-") for f in os.listdir(p)) or name.lower() in named or self._fresh(p, now) or _has_link_inside(p):
                    continue
                out.append(self._item("unused-tool", p))
        return out

    def _config_text(self):
        """設定のファイル(machine.json・setup.json・transcribe の *.json)に出てくる名前(手で選んだモデルを守る)"""
        names = set()
        files = [os.path.join(self.places["friend"], "setup.json")]
        tx = os.path.join(self.data(), "transcribe")
        if os.path.isdir(tx):
            files += [os.path.join(tx, n) for n in os.listdir(tx) if n.endswith(".json")]
        try:
            from flow import machine as _machine
            files.append(_machine.path())
        except Exception:   # noqa: BLE001
            pass
        for f in files:
            try:
                with open(f, encoding="utf-8", errors="replace") as fh:
                    text = fh.read(2 * 1024 * 1024).lower()
            except (OSError, TypeError):
                continue
            names.update(re.findall(r"[^\\/\"'\s:]+\.[a-z0-9]{2,8}", text))
        return names

    # ---------------------------------------------------------------- 片付ける
    def trash_root(self, path):
        """path と同じドライブのごみ箱の根(<一時保管>/ごみ箱 か <home>/ごみ箱)か None(どちらとも違う = 動かさない)"""
        def dev(p):
            try:
                return os.stat(_fsio.long_path(p)).st_dev
            except OSError:
                return None
        d = dev(path)
        for root in self.case_roots() + ([self.home()] if self.home() else []):
            if d is not None and dev(root) == d:
                return os.path.join(root, TRASH_NAME)
        return None

    def apply(self, items):
        """候補を片付ける -> {"count", "bytes", "failed": [(where, 理由)]}"""
        day = datetime.datetime.fromtimestamp(self.clock()).strftime("%Y%m%d")
        done = size = 0
        failed = []
        manifests = {}
        for it in items:
            p = it["path"]
            try:
                if not os.path.lexists(_fsio.long_path(p)):
                    continue
                if _fsio.is_link(p) or _has_link_inside(p):
                    raise OSError("リンクや接合点があるので触りません")
                if it["how"] == "delete":
                    if os.path.isdir(_fsio.long_path(p)):
                        self.rmtree(p)
                    else:
                        self.remove(p)
                else:
                    root = self.trash_root(p)
                    if root is None:
                        raise OSError("同じドライブにごみ箱を作れないので動かしません")
                    day_dir = os.path.join(root, day, TIDY_SUB, it["kind"])
                    os.makedirs(_fsio.long_path(day_dir), exist_ok=True)
                    dest = _trashbin.free_path(os.path.join(day_dir, os.path.basename(p)), check=lambda x: os.path.lexists(_fsio.long_path(x)))
                    self.move(p, dest)
                    manifests.setdefault(os.path.join(root, day), []).append({"from": p, "to": dest, "at": int(self.clock()), "kind": it["kind"],
                                                                             "bytes": it["bytes"], "version": self.version})
                done += 1
                size += it["bytes"]
                self.log("整理: %s %s(%s・%s)" % ("消した" if it["how"] == "delete" else "ごみ箱へ", it["where"], it["label"], _mb(it["bytes"])))
            except OSError as e:
                failed.append((it["where"], str(e)[:120]))
                self.log("整理: 動かせませんでした %s(%s)" % (it["where"], e.__class__.__name__))
        for day_dir, rows in manifests.items():
            try:
                _trashbin.append_manifest(_fsio.long_path(day_dir), rows)
            except OSError:
                self.log("整理: ごみ箱の記録を書けませんでした")
        return {"count": done, "bytes": size, "failed": failed}

    def purge_home_trash(self):
        """<home>/ごみ箱 の 3 日より前の日付のフォルダを消す(一時保管のごみ箱は受信箱が消す)"""
        t = os.path.join(self.home(), TRASH_NAME) if self.home() else ""
        if not t or not os.path.isdir(_fsio.long_path(t)) or _fsio.is_link(t):
            return
        cut = datetime.datetime.fromtimestamp(self.clock() - CASE_DAYS * DAY).strftime("%Y%m%d")
        for name in os.listdir(_fsio.long_path(t)):
            if re.fullmatch(r"\d{8}", name) and name < cut:
                shutil.rmtree(_fsio.long_path(os.path.join(t, name)), ignore_errors=True)

    # ---------------------------------------------------------------- 画面・口
    def rescan(self):
        why = self.blocked()
        if why:
            return why
        got = self.scan()
        with self.lock:
            self.items, self.unknown = got["items"], got["unknown"]
        for name, size in got["unknown"]:
            self.log("整理: 何か分からないので触りません %s" % name)
        return None

    def view(self):
        with self.lock:
            asks = [it for it in self.items if it["mode"] == "ask"]
            running = self.thread is not None and self.thread.is_alive()
            v = {"state": "applying" if running else "idle", "ask": bool(asks) and not self.st.get("asked") and not running,
                 "askCount": len(asks), "askBytes": sum(it["bytes"] for it in asks),
                 "items": [{k: it[k] for k in ("id", "kind", "label", "where", "bytes", "mode")} for it in self.items],
                 "unknownCount": len(self.unknown), "autoDone": self.st.get("autoDone"), "last": self.st.get("last"),
                 "blocked": None, "trash": any(os.path.isdir(_fsio.long_path(os.path.join(r, TRASH_NAME))) for r in self.case_roots() + [self.home()] if r)}
        return v

    def start_apply(self, ids=None, auto=False):
        """候補を裏の糸で片付ける(ids = その物だけ・無ければ ask の全部)。始められなければ ValueError"""
        with self.lock:
            if self.thread is not None and self.thread.is_alive():
                raise ValueError("片付けている途中です")
            pick = [it for it in self.items if (it["id"] in ids if ids else (it["mode"] == "auto" if auto else it["mode"] == "ask"))]
            if not pick:
                raise ValueError("片付ける物がありません")
            self.thread = threading.Thread(target=self._job, args=(pick, auto), name="friend-tidy", daemon=True)
            self.thread.start()

    def _job(self, pick, auto):
        why = self.blocked()
        if why:
            self.log("整理をやめました: %s" % why)
            return
        res = self.apply(pick)
        at = int(self.clock() * 1000)
        with self.lock:
            done_ids = {it["id"] for it in pick}
            self.items = [it for it in self.items if it["id"] not in done_ids]
            if auto:
                self.st["autoDone"] = {"count": res["count"], "bytes": res["bytes"], "at": at}
            else:
                self.st["asked"] = True
                self.st["last"] = {"at": at, "count": res["count"], "bytes": res["bytes"], "failed": len(res["failed"]),
                                   "message": "%d 件 %s を片付けました(3 日はごみ箱に残ります)" % (res["count"], _mb(res["bytes"])) +
                                              ("・%d 件は動かせませんでした" % len(res["failed"]) if res["failed"] else "")}
        self._save_state()

    def later(self):
        with self.lock:
            self.st["asked"] = True
        self._save_state()

    def wait(self, timeout=None):
        t = self.thread
        if t is not None:
            t.join(timeout)

    def maybe_auto(self):
        """新しい版で起動できたあとの 1 回(版ごと): exe から・この版が current・戻した版でない・準備済み・同期の 1 周目のあと・作業が無い
        -> 走ったか。黙る側はその場で片付け、聞く側は帯で 1 回聞く"""
        if (self.env.get("YTT_FRIEND_LAUNCHER") or "").strip() != "1" or (self.env.get("YTT_FRIEND_ROLLBACK") or "").strip():
            return False
        if self.st.get("version") == self.version:
            return False
        rec = self._versions()
        if rec is not None and rec.get("current") and rec.get("current") != self.version:
            return False   # 前の形から動いている・まだ current になっていない(exe の記録が付いてくるのを待つ)
        if self.clock() - self.started < 150 or (self.sync is not None and not (self.sync.status() or {}).get("at") and self.sync.has_key()):
            return False
        if self.rescan():
            return False
        self.purge_home_trash()
        with self.lock:
            self.st = {"version": self.version, "scannedAt": int(self.clock() * 1000), "asked": False}
            autos = [it for it in self.items if it["mode"] == "auto"]
        self._save_state()
        self.log("整理: 新しい版 %s で調べました(黙って %d 件・聞く %d 件・分からない %d 件)" % (
            self.version, len(autos), len([it for it in self.items if it["mode"] == "ask"]), len(self.unknown)))
        if autos:
            try:
                self.start_apply(auto=True)
            except ValueError:
                pass
        return True


def _mb(n):
    return "%.1f GB" % (n / 1e9) if n >= 1e9 else "%d MB" % max(1, round(n / 1e6)) if n >= 1e6 else "%d KB" % max(1, round(n / 1e3))
