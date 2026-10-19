"""作業データの片付け(全体の計画 段9 9-2。ユーザー決定: 元動画も候補に・ごみ箱フォルダ経由・日数を決めて消す)。

候補を種類ごとに出し(候補の一覧はここが持つ)、画面で確かめた物だけを **ごみ箱フォルダ**(<入口の作業データ>\\ごみ箱\\<日付>\\)へ**移す**。
すぐには消さない。TRASH_DAYS を過ぎた日付のフォルダは入口の起動時に purge で消す(戻したいときは、それまでにエクスプローラーで戻す。manifest.jsonl に元の場所)。
候補として出していないパスは move で受け付けない(API に好きなパスを渡しても消せない)。

候補の種類:
- export … スタジオの書き出しの元動画のうち、Text+ のパック(動画のコピー入り)から PACK_AGE_DAYS 日たったもの(案件は src/manage/cases/cases.snapshot の cases)と、
  届けたあとパックだけが片付いた自動の切り抜き(届けてから PACK_AGE_DAYS 日)。日数で出すのは**このパックだけで編集できるとき**だけ(flow/packrec.ready =
  記録したファイルが全部あって空でない・動画と Lua が入っている。部品 M1。移す直前にもう一度見る)。案件の状態(投稿済み・見送り)は条件にしない(MARKS-3)
- work   … 動画の「作業用」フォルダの途中のファイルのうち、元の動画がもう無いもの(記録から辿れない)
- cache  … 「編集」の波形のキャッシュ(いつでも作り直せる)
- log    … 回したログ(*.old.log・*.log.old・*.1・*.old)
- intake … 依頼の受付の 受付済み\\<日付>\\ のうち KEEP_DAYS より古い日付のもの(受け取った動画。動画は 受付済み に残る決まり)と、
  友人の送り返しの 送り返し\\受付済み\\<日付>\\ のうち KEEP_DAYS より古い日付のもの(同じ決まり。9g-2)と、
  友人の依頼の動画の置き場所 = 書き出し先の 依頼\\<日付>_<題>_<id6>\\(1 依頼 = 1 案件)・作業データの app\\intake\\<日付>\\<依頼 id>\\(書き出し先が固定ディスクでない PC)。
  届けた記録(logs/deliveries.jsonl)にその依頼があれば**最後に届けてから** KEEP_DAYS 日、手で置いた動画(依頼 id が無い)は受け付けた日から KEEP_DAYS 日
  (Q15。decisions 3-48)。届けていない依頼は日数がたっても出さない(文書・パックの元になる動画のため)。
  移すのは**動画とパックだけ**(作業用\\ の文書と履歴は残す = Q4。人が直した行を失わない・文書はバックアップの学習データに入る)
- failed … 受付の 失敗\\ と 送り返しの 送り返し\\失敗\\ の中の物(ファイルもフォルダも更新日時から KEEP_DAYS 日。理由の .txt は一緒に。9g-2)
"""
import hashlib
import os
import shutil
import time

from flow import deliveries as _deliveries   # 届けた記録の読み口(持ち主は ②。7x-2)
from flow import packrec as _packrec   # パックの中身の確かめ(部品 M1)
from flow import placement   # 依頼のフォルダの名前・案件の身分証 case.json・案件の根の置き場所の読み方(④ は ② を読める)
from human.friend import returns as _returns   # 友人の送り返し(同期フォルダの 送り返し\\ と その 受付済み・失敗 の名前。持ち主は ③ human/friend/returns)
from ytt import datadir, fsio, schemas, trashbin

from . import trash as _trash

# 日数は「精度のデータは残す・ただの控えは早めに消す」の方針(notes:docs/spec/data.md)。値は ytt/trashbin.KEEP_DAYS の 1 か所
KEEP_DAYS = trashbin.KEEP_DAYS       # 受け付けた依頼の動画(受付済み。作業データに写しがある = ただの控え)を候補に出すまでの日数
TRASH_DAYS = trashbin.KEEP_DAYS      # ごみ箱フォルダの日付のフォルダを起動時に消すまでの日数
PACK_AGE_DAYS = trashbin.KEEP_DAYS   # パック(Text+ = 動画のコピー入り)を作ってからこの日数たった元動画も候補(案件の状態を変えなくても出る)
REQUEST_DIR = placement.REQUEST_DIR   # 書き出し先の下の友人の依頼のフォルダ(依頼)
APP_INTAKE = "intake"     # 作業データ app の下の、友人の依頼の動画の写し(app\intake\<日付>\<依頼 id>\。書き出し先が固定ディスクでない PC)
DELIVERIES_LOG = _deliveries.LOG      # 届けた記録(持ち主は ② flow/deliveries。logs の中)
ROOTS_FILE = "trash-roots.json"   # 作業データの外に作ったごみ箱フォルダの一覧(起動時の purge が見る)
DRIVE_TRASH = "youtube-tools ごみ箱"   # 動画のドライブに書き出し先が無いときのごみ箱(<ドライブ>\youtube-tools ごみ箱\)
REASON_SUFFIX = ".理由.txt"   # 失敗\\ の物に添える断った理由(受付・送り返しとも。returns._move と intake の決まり)
KINDS = (("export", "スタジオの書き出しの元動画(パックから %d 日・届けてから %d 日でパックなし)" % (PACK_AGE_DAYS, PACK_AGE_DAYS)),
         ("work", "作業用の途中のファイル(元の動画が無い)"),
         ("cache", "波形のキャッシュ(作り直せる)"),
         ("log", "古いログ"),
         ("intake", "受け付けた依頼の動画・友人の送り返しの受付済み(届けてから・手で置いた物は受け付けてから %d 日。文書は残す)" % KEEP_DAYS),
         ("failed", "断って失敗\\ に置いた物(受付と送り返し。更新から %d 日・理由の .txt つき)" % KEEP_DAYS))
VIDEO_EXTS = (".mp4", ".mkv", ".mov", ".webm", ".m4v", ".avi", ".ts")
MAX_ITEMS = 500


def _id(path):
    return hashlib.sha1(os.path.normcase(os.path.abspath(path)).encode("utf-8")).hexdigest()[:16]


def _size(path):
    """バイト数(フォルダは中身の合計。リンクはたどらない・数えない。読めない物は飛ばす)"""
    return fsio.dir_size(path)[0]


def _mtime(path):
    try:
        return int(os.path.getmtime(path))
    except OSError:
        return 0


def _item(kind, path, note="", extra=()):
    """extra = 一緒に移す途中のファイル(元動画の _edit.mp4・作業用の .clip.json など)"""
    extra = [x for x in extra if os.path.isfile(x)]
    return {"id": _id(path), "kind": kind, "path": path, "name": os.path.basename(path.rstrip("\\/")), "bytes": _size(path) + sum(_size(x) for x in extra),
            "mtime": _mtime(path), "dir": os.path.isdir(path), "note": note, "extra": extra}


def _parts_item(kind, folder, note, parts=None):
    """依頼の置き場所 folder の中の**動画とパックだけ**を移す候補(作業用\\ の文書と履歴は残す。Q4)。parts を渡さなければ folder の直下の動画と
    <名前>_pack のフォルダ。移す物が無ければ None(もう片付けた)"""
    if parts is None:
        try:
            names = sorted(os.listdir(folder))
        except OSError:
            return None
        parts = [os.path.join(folder, n) for n in names
                 if (os.path.isfile(os.path.join(folder, n)) and n.lower().endswith(VIDEO_EXTS))
                 or (os.path.isdir(os.path.join(folder, n)) and n.lower().endswith("_pack"))]
    if not parts:
        return None
    return {"id": _id(folder), "kind": kind, "path": folder, "name": os.path.basename(folder.rstrip("\\/")), "bytes": sum(_size(x) for x in parts),
            "mtime": _mtime(folder), "dir": True, "note": note + "(動画とパックだけ。文書は残す)", "extra": [], "parts": parts}


def _drive(p):
    return os.path.normcase(os.path.splitdrive(os.path.abspath(p))[0])


class Cleanup:
    def __init__(self, app_dir, repo_root=None, env=None, log=None, clock=time.time, keep_days=KEEP_DAYS, out_dirs=None,
                 trash_days=TRASH_DAYS):
        """out_dirs = スタジオの書き出し先など(呼ぶたびに読む関数でもよい)。作業データと別のドライブの物は、そのドライブのここ\\ごみ箱\\ へ移す。
        keep_days = 受け付けた依頼の動画を候補に出すまでの日数・trash_days = ごみ箱フォルダの日付のフォルダを消すまでの日数"""
        self.app_dir = os.path.abspath(app_dir)
        self.out_dirs = out_dirs
        self.repo_root, self.env = repo_root, env
        self.log = log or (lambda m: None)
        self.clock, self.keep_days, self.trash_days = clock, keep_days, trash_days
        self._known = {}          # id → item(直前に出した候補だけ move できる)

    @property
    def trash_dir(self):
        return os.path.join(self.app_dir, trashbin.TRASH_DIR)

    def _out_dirs(self):
        v = self.out_dirs() if callable(self.out_dirs) else self.out_dirs
        return [os.path.abspath(x) for x in v or [] if isinstance(x, str) and x]

    def trash_for(self, path):
        """移す先のごみ箱フォルダ(ユーザー決定: 動画と同じドライブ。別のドライブへ数 GB を写さない・C: を圧迫しない)。
        作業データと同じドライブ → 作業データの ごみ箱、書き出し先と同じドライブ → <書き出し先>\\ごみ箱、それ以外 → <ドライブ>\\youtube-tools ごみ箱"""
        d = _drive(path)
        if d == _drive(self.app_dir):
            return self.trash_dir
        for o in self._out_dirs():
            if _drive(o) == d:
                return os.path.join(o, trashbin.TRASH_DIR)
        return os.path.join(os.path.splitdrive(os.path.abspath(path))[0] + os.sep, DRIVE_TRASH)

    def trash_roots(self):
        """purge が見るごみ箱フォルダ: 作業データ・書き出し先・作ったことのある場所(trash-roots.json)"""
        roots = [self.trash_dir] + [os.path.join(o, trashbin.TRASH_DIR) for o in self._out_dirs()]
        roots += [x for x in self._read_roots() if isinstance(x, str)]
        return list(dict.fromkeys(os.path.normcase(os.path.abspath(r)) for r in roots))

    def _read_roots(self):
        """trash-roots.json の中身(リスト。無い・読めない・リストでなければ [])"""
        return fsio.read_json_or(os.path.join(self.app_dir, ROOTS_FILE), [], kind=list)

    def remember_root(self, root):
        """作業データの外に作ったごみ箱フォルダを trash-roots.json に足す(起動時の purge が見る。片付けの move と案件の「要らない」が呼ぶ)。
        原子的に書く(書きかけで落ちても前の一覧が残る = 作ったことのあるごみ箱フォルダを purge が見失わない)"""
        if os.path.normcase(root) == os.path.normcase(self.trash_dir):
            return
        v = self._read_roots()
        if root not in v:
            fsio.write_json(os.path.join(self.app_dir, ROOTS_FILE), v + [root], indent=None)

    # ---------- 候補 ----------
    def candidates(self, cases=None, intake_dir=None):
        """-> {"kinds": [{kind, label, count, bytes, items}], "bytes", "trash": ごみ箱フォルダ, "trashRoots", "keepDays", "trashDays", "packAgeDays", "at"}"""
        found = {k: [] for k, _ in KINDS}
        try:
            found["export"] = self._exports(cases or [])
        except Exception as e:
            self.log("片付けの候補(元動画)を調べられませんでした: %r" % (e,))
        try:
            found["work"] = self._work_orphans(cases or [])
        except Exception as e:
            self.log("片付けの候補(作業用)を調べられませんでした: %r" % (e,))
        found["cache"] = self._cache()
        found["log"] = self._logs()
        found["intake"] = self._intake(intake_dir)
        try:
            found["intake"] += self._requests()
        except Exception as e:
            self.log("片付けの候補(友人の依頼の案件)を調べられませんでした: %r" % (e,))
        try:
            found["intake"] += self._app_intake()
        except Exception as e:
            self.log("片付けの候補(受付の写し)を調べられませんでした: %r" % (e,))
        try:
            found["failed"] = self._failed(intake_dir)
        except Exception as e:
            self.log("片付けの候補(失敗の物)を調べられませんでした: %r" % (e,))
        self._known = {}
        kinds, total = [], 0
        for k, label in KINDS:
            items = sorted(found[k], key=lambda x: x["mtime"])[:MAX_ITEMS]
            for it in items:
                self._known[it["id"]] = it
            b = sum(x["bytes"] for x in items)
            total += b
            kinds.append({"kind": k, "label": label, "count": len(items), "bytes": b, "items": items})
        return {"kinds": kinds, "bytes": total, "trash": self.trash_dir, "trashRoots": self.trash_roots(), "keepDays": self.keep_days,
                "trashDays": self.trash_days, "packAgeDays": PACK_AGE_DAYS, "at": int(self.clock() * 1000)}

    def _exports(self, cases):
        """パックがある元動画のうち、Text+ のパック(動画のコピー入り。元動画が無くても Resolve で開ける)を作って PACK_AGE_DAYS 日たったもの・
        届けたあとパックだけが片付いた自動の切り抜き。_edit.mp4・作業用の途中のファイルも一緒に(extra)"""
        out, seen, now = [], set(), self.clock()
        for c in cases:
            if not isinstance(c, dict):
                continue
            for cl in c.get("clips") or []:
                p = cl.get("path") if isinstance(cl, dict) else None
                if not p or not cl.get("exists") or not os.path.isfile(p):
                    continue
                pk = cl.get("pack")
                if not pk:
                    # 自動の切り抜きで、届けたあとパックだけが片付いた物(友人の「要らない」はパックしか消さない = mp4 が残る。
                    # notes:plan/done/opt-manage.md の 2a-1)。届けてから PACK_AGE_DAYS 日で候補に出す
                    rv = cl.get("review") if cl.get("auto") else None
                    sent = rv.get("deliveredAt") if isinstance(rv, dict) else 0
                    if isinstance(sent, (int, float)) and sent > 0 and now - sent / 1000.0 > PACK_AGE_DAYS * 86400:
                        key = os.path.normcase(p)
                        if key not in seen:
                            seen.add(key)
                            title = str(c.get("title") or c.get("id") or "")[:40]
                            out.append(_item("export", p, "案件「%s」(届けてから %d 日・パックなし)" % (
                                title, int((now - sent / 1000.0) // 86400)), schemas.existing_sidecars(p)))
                    continue
                at = pk.get("updatedAt") if isinstance(pk, dict) else 0
                aged = isinstance(pk, dict) and pk.get("textplus") is True and isinstance(at, (int, float)) and at > 0 \
                    and now - at / 1000.0 > PACK_AGE_DAYS * 86400
                if not aged:
                    continue
                key = os.path.normcase(p)
                if key in seen:
                    continue
                pack_dir = pk.get("dir")
                if pack_dir and not self._pack_ready(pack_dir):
                    continue   # パックの動画などが欠けている = 元の素材がまだ要る(部品 M1)
                seen.add(key)
                title = str(c.get("title") or c.get("id") or "")[:40]
                why = "パックから %d 日" % int((now - at / 1000.0) // 86400)
                it = _item("export", p, "案件「%s」(%s)" % (title, why), schemas.existing_sidecars(p))
                if pack_dir:
                    it["packDir"] = pack_dir   # move の直前にもう一度見る
                out.append(it)
        return out

    def _pack_ready(self, pack_dir):
        """このパックだけで編集できるか(packrec.ready。調べられなければ偽 = 元の素材を残す側)"""
        try:
            return _packrec.ready(pack_dir, self.env)[0]
        except Exception as e:
            self.log("片付け: パック %s を確かめられませんでした: %r" % (pack_dir, e))
            return False

    def _work_orphans(self, cases):
        """案件の動画のフォルダにある 作業用\\ の中で、対応する動画が無いファイル"""
        folders, out = set(), []
        for c in cases:
            for cl in (c.get("clips") or []) if isinstance(c, dict) else []:
                p = cl.get("path") if isinstance(cl, dict) else None
                if p:
                    folders.add(os.path.dirname(p))
        for folder in sorted(folders):
            wd = os.path.join(folder, schemas.WORK_DIR)
            if not os.path.isdir(wd):
                continue
            try:
                names = os.listdir(wd)
            except OSError:
                continue
            for n in names:
                fp = os.path.join(wd, n)
                if not os.path.isfile(fp):
                    continue
                stem = _media_stem(n)
                if stem is None:
                    continue
                if not any(os.path.isfile(os.path.join(folder, stem + ext)) for ext in VIDEO_EXTS):
                    out.append(_item("work", fp, "元の動画「%s」が見つからない" % stem))
        return out

    def _cache(self):
        try:
            d = os.path.join(datadir.resolve("transcribe", self.repo_root, self.env), "cache", "peaks")
        except Exception:
            return []
        if not os.path.isdir(d):
            return []
        try:
            return [_item("cache", os.path.join(d, n)) for n in os.listdir(d) if os.path.isfile(os.path.join(d, n))]
        except OSError:
            return []

    def _logs(self):
        out = []
        dirs = [os.path.join(self.app_dir, "logs")]
        for tool in ("studio", "transcribe", "cut2resolve"):
            try:
                dirs.append(datadir.resolve(tool, self.repo_root, self.env))
            except Exception:
                pass
        for d in dirs:
            try:
                names = os.listdir(d)
            except OSError:
                continue
            for n in names:
                low = n.lower()
                if low.endswith((".old.log", ".log.old", ".log.1", ".jsonl.1", ".old")) or (low.endswith(".1") and ".log" in low):
                    p = os.path.join(d, n)
                    if os.path.isfile(p):
                        out.append(_item("log", p))
        return out

    def _intake(self, intake_dir):
        """受付済み\\<日付>\\ と 送り返し\\受付済み\\<日付>\\ の、受け取った日から keep_days 日たった日付のフォルダ"""
        if not intake_dir:
            return []
        now, days = self.clock(), self.keep_days
        out = [_item("intake", p, "受け付けた日 %s" % n[:10]) for n, p in _old_day_dirs(os.path.join(intake_dir, "受付済み"), days, now)]
        back = os.path.join(intake_dir, _returns.IN_DIR, _returns.DONE_DIR)
        out += [_item("intake", p, "友人の送り返しを受け取った日 %s" % n[:10]) for n, p in _old_day_dirs(back, days, now)]
        return out

    def _failed(self, intake_dir):
        """受付の 失敗\\ と 送り返しの 送り返し\\失敗\\ の中の物(ファイルもフォルダも更新日時から keep_days 日たったもの)。
        理由の .txt は一緒に移す(.txt だけの行は作らない)"""
        if not intake_dir:
            return []
        now, out = self.clock(), []
        roots = ((os.path.join(intake_dir, "失敗"), "受付の失敗"),
                 (os.path.join(intake_dir, _returns.IN_DIR, _returns.FAIL_DIR), "送り返しの失敗"))
        for root, label in roots:
            try:
                names = sorted(os.listdir(root))
            except OSError:
                continue
            for n in names:
                p = os.path.join(root, n)
                if n.endswith(REASON_SUFFIX):
                    continue
                try:
                    mt = os.path.getmtime(p)
                except OSError:
                    continue
                if now - mt <= self.keep_days * 86400:
                    continue
                out.append(_item("failed", p, "%s・更新から %d 日" % (label, int((now - mt) // 86400)),
                                 [os.path.splitext(p)[0] + REASON_SUFFIX]))
        return out

    def _delivered(self):
        """届けた記録(② flow/deliveries の読み口)-> {依頼 id: 最後に届けた時刻(秒)}。依頼 id は元の形と、英数字だけの末尾 6 文字の両方で引ける
        (依頼のフォルダの名前は末尾 6 文字しか持たない)。読めなければ None(= 届けたかが分からないので、届けた依頼は何も出さない)"""
        got = _deliveries.delivered_requests(os.path.join(self.app_dir, "logs"))
        if got is None:
            return None
        out = {}
        for rid, sec in got.items():
            for k in (rid, placement.request_id6(rid)):
                out[k] = max(out.get(k, 0.0), sec)
        return out

    def _due(self, rid, received_day, delivered, now):
        """依頼の動画を片付けてよいか -> 理由の文か None。rid = 依頼 id("" = 手で置いた動画)。received_day = 受け付けた日 YYYY-MM-DD"""
        days = self.keep_days * 86400
        if rid:
            sent = delivered.get(rid) if delivered else None
            if sent is None:
                return None   # まだ届けていない(届けた記録が読めない)= 文書・パックの元なので出さない
            if now - sent <= days:
                return None
            return "届けてから %d 日" % int((now - sent) // 86400) if sent else "届け済み"
        try:
            day = time.mktime(time.strptime(received_day[:10], "%Y-%m-%d"))
        except ValueError:
            return None
        return "手で置いた動画・受け付けてから %d 日" % int((now - day) // 86400) if now - day > days else None

    def _requests(self):
        """書き出し先の 依頼\\<日付>_<題>_<id6>\\ の案件の動画とパック(作業用の文書は残す)。依頼 id は 作業用\\case.json の requestId
        (無ければ手で置いた動画 = 受け付けた日から数える)。case.json が無い・読めないフォルダは出さない(何の依頼か分からない)"""
        delivered, now, out = self._delivered(), self.clock(), []
        for o in self._out_dirs():
            for root in [d for d, is_req in placement.case_parents(o) if is_req]:   # 依頼の案件の置き場所は ② placement の 1 か所
                for name, p in _old_day_dirs(root, self.keep_days, now):
                    case = placement.read_case(p)
                    if not case:
                        continue
                    rid = case.get("requestId") if isinstance(case.get("requestId"), str) else ""
                    why = self._due(rid, name, delivered, now)
                    it = _parts_item("intake", p, "受け付けた日 %s・%s" % (name[:10], why)) if why else None
                    if it:
                        out.append(it)
        return out

    def _app_intake(self):
        """作業データの app\\intake\\<日付>\\<依頼 id>\\(受付の写し。書き出し先が固定ディスクでない PC の置き場所)の動画とパック。
        依頼 id が m で始まる(手で置いた動画)なら受け付けた日から、ほかは最後に届けてから数える。<日付>\\ の直下に置いてある動画
        (依頼 id の分からない形)は受け付けた日から"""
        delivered, now, out = self._delivered(), self.clock(), []
        base = os.path.join(self.app_dir, APP_INTAKE)
        for day, dp in _old_day_dirs(base, self.keep_days, now):
            try:
                names = sorted(os.listdir(dp))
            except OSError:
                continue
            loose = [os.path.join(dp, n) for n in names if os.path.isfile(os.path.join(dp, n)) and n.lower().endswith(VIDEO_EXTS)]
            if loose:
                why = self._due("", day, delivered, now)
                if why:
                    out.append(_parts_item("intake", dp, "受付の写し %s・%s" % (day[:10], why), loose))
            for n in names:
                p = os.path.join(dp, n)
                if not os.path.isdir(p):
                    continue
                rid = "" if n.startswith("m") else n
                why = self._due(rid, day, delivered, now)
                it = _parts_item("intake", p, "受付の写し %s・%s" % (day[:10], why)) if why else None
                if it:
                    out.append(it)
        return out

    # ---------- 移す・消す ----------
    def move(self, ids):
        """候補として出した物だけを ごみ箱\\<日付>\\<種類>\\ へ移す。-> {"moved": [...], "failed": [{id, path, error}], "unknown": [ids], "trash": ...}"""
        moved, failed, unknown = [], [], []
        for i in ids if isinstance(ids, list) else []:
            it = self._known.get(str(i))
            if not it:
                unknown.append(str(i)[:40])
                continue
            src = it["path"]
            if it.get("packDir") and not self._pack_ready(it["packDir"]):   # 候補を出したあとでパックの中身が欠けた(部品 M1)
                failed.append({"id": it["id"], "path": src, "error": "パックの動画などが欠けているので、元の動画は移しませんでした"})
                continue
            if it.get("parts"):
                self._move_parts(it, moved, failed)
                continue
            # 元動画と途中のファイルは <名前>\ にまとめる(作業用の物は その中の 作業用\)。元動画が移せなければほかは移さない・
            # 途中のファイルが移せなくても元動画は移した(次の候補の work に出る)
            stem = os.path.splitext(it["name"])[0] if it.get("extra") else None
            r = _trash.to_trash(self, [src] + list(it.get("extra") or []), it["kind"], stem, need_first=True, clock=self.clock,
                                log=lambda m: self.log("片付け: " + m))
            if r["moved"] and r["moved"][0][0] == src:
                moved.append(dict(it, to=r["moved"][0][1]))
                self._known.pop(it["id"], None)
                self.log("片付け: %s → %s" % (src, r["moved"][0][1]))
            else:
                failed.append({"id": it["id"], "path": src, "error": (r["failed"][0][1] if r["failed"] else "移せませんでした")[:200]})
        return {"moved": moved, "failed": failed, "unknown": unknown, "trash": self.trash_dir}

    def _move_parts(self, it, moved, failed):
        """依頼の置き場所の動画とパックだけを ごみ箱\\<日付>\\<種類>\\<フォルダ名>\\ へ(フォルダと 作業用\\ は残す)。移せた物は manifest に 1 行ずつ。
        1 つも移せなければ failed、一部でも移せたら moved(移せなかった物は次の候補にまた出る)"""
        r = _trash.to_trash(self, it["parts"], it["kind"], it["name"], clock=self.clock, log=lambda m: self.log("片付け: " + m))
        if r["moved"]:
            moved.append(dict(it, to=r["dest"]))
            self._known.pop(it["id"], None)
            self.log("片付け: %s の動画とパック %d 個 → %s" % (it["path"], len(r["moved"]), r["dest"]))
        else:
            failed.append({"id": it["id"], "path": it["path"], "error": (r["failed"][0][1] if r["failed"] else "移す物がありません")[:200]})

    def purge(self):
        """TRASH_DAYS を過ぎた日付のフォルダを消す(起動時。どのドライブのごみ箱フォルダも)。-> 消した日付のフォルダの数"""
        return sum(self._purge_root(r) for r in self.trash_roots())

    def _purge_root(self, root):
        n = 0
        for name, p in _old_day_dirs(root, self.trash_days, self.clock()):
            shutil.rmtree(p, ignore_errors=True)
            if not os.path.isdir(p):
                n += 1
                self.log("ごみ箱フォルダの %s を消しました(%d 日を過ぎた)" % (name, self.trash_days))
        return n


_old_day_dirs = trashbin.old_day_dirs   # 日付のフォルダの決まりは ytt/trashbin の 1 か所(受付済み と ごみ箱フォルダ。① の録画の部品も)


def _media_stem(name):
    """作業用の途中のファイル名 → 元の動画の名前(拡張子なし)。知らない形なら None。
    名前が文字起こしの文書の id(schemas.TID_RE。`<tid>.edit.json` など)なら None: 作業用に置く文字起こしの文書とその付き物(RS8 B2)は
    動画の付き物ではない(動画の名前と比べると、いつも「元の動画が無い」になって片付けの候補に出てしまう)。
    名前が空(作業用/.studio-id = 案件の持ち主の印)も None。
    名前の終わりは長い物から比べる(X_edit.clip.json を .clip.json で先に切ると X_edit になり、元の X.mp4 があっても「無い」の候補に出た = 7d-1)"""
    for suffix in ("_edit.clip.json", ".transcript.json", ".clip.json", ".edit.json", ".cut-plan.json", ".studio-id", "_edit.mp4", ".srt"):
        if name.endswith(suffix):
            stem = name[:-len(suffix)]
            return None if not stem or schemas.TID_RE.match(stem) else stem
    return None
