"""作業データの片付け(全体の計画 段9 9-2。ユーザー決定: ごみ箱フォルダ経由・日数を決めて消す。10-24: 手で選ぶ画面をやめて自動だけ)。

物は **ごみ箱フォルダ**(動画と同じドライブ。作業データ・書き出し先\\ごみ箱\\<日付>\\)へ**移す**。すぐには消さない。
TRASH_DAYS を過ぎた日付のフォルダは入口の起動時に purge で消す(戻したいときは、それまでにエクスプローラーで戻す。manifest.jsonl に元の場所)。

自動で移す物(auto_clean。入口の起動のすぐあとと AUTO_EVERY_SEC ごと。ユーザー 10-24「精度改善以外で、自分用に動画を保存する意味がない」):
- 友人へ届けて KEEP_DAYS 日たった切り抜き(届けた記録 logs/deliveries.jsonl のパックのフォルダ・切り抜きの動画・その _edit.mp4)
- 友人の依頼の動画の置き場所 = 書き出し先の 依頼\\<日付>_<題>_<id6>\\(1 依頼 = 1 案件)・作業データの app\\intake\\<日付>\\<依頼 id>\\
  (書き出し先が固定ディスクでない PC)の動画とパック。**最後に届けてから** KEEP_DAYS 日(Q15。decisions 3-48)。届けていない依頼・手で置いた動画は移さない
- 依頼の受付の 受付済み\\<日付>\\・友人の送り返しの 送り返し\\受付済み\\<日付>\\ のうち KEEP_DAYS より古い日付のもの(ただの控え。9g-2)
- 受付の 失敗\\ と 送り返しの 送り返し\\失敗\\ の中の物(更新日時から KEEP_DAYS 日。理由の .txt は一緒に)
- 届けていない書き出し(ユーザー 10-24「自動でいい」): 案件(配信)の切り抜きの動画・_edit.mp4・パックのフォルダが、どれも KEEP_DAYS 日より前の物
- 完成品のパック(ユーザー 10-24「E に置いてある完成品のパックも、3 日待って消して」): 書き出し先(out_dirs)の下の <名前>_pack のフォルダと、
  その書き出しの動画(<名前>.mp4・<名前>_edit.mp4)。作ってから(中の一番新しいファイルから)KEEP_DAYS 日。届けたかは見ない。
  学習用データ・評価用データのフォルダの下(KEEP_FOLDERS)・確かめるで待っている切り抜き・評価用は外す
移さない物: 文書・作業用の記録・字幕(.transcript.json・.clip.json・.edit.json・.srt。精度の材料 = Q4)・評価用の動画と
確かめるの「切り抜く価値」で答えを待っている切り抜き(keep_paths。入口が渡す)・まとめて実行が動いている配信(busy_ids)・
手で置いた依頼の動画・録画(書き出し先の案件の切り抜きでない物は見ない)
"""
import hashlib
import os
import time

from flow import deliveries as _deliveries   # 届けた記録の読み口(持ち主は ②。7x-2)
from flow import retention   # 物の終わりの日数(1 か所)
from flow import placement   # 依頼のフォルダの名前・案件の身分証 case.json・案件の根の置き場所の読み方(④ は ② を読める)
from human.friend import returns as _returns   # 友人の送り返し(同期フォルダの 送り返し\\ と その 受付済み・失敗 の名前。持ち主は ③ human/friend/returns)
from ytt import fsio, trashbin

from . import trash as _trash   # 動画と一緒に動かす途中のファイル

# 日数は「精度のデータは残す・ただの控えは早めに消す」の方針(notes:docs/spec/data.md)。値は flow/retention.KEEP_DAYS の 1 か所
KEEP_DAYS = retention.KEEP_DAYS       # 届けてから・受け付けてから、自動で移すまでの日数
TRASH_DAYS = retention.KEEP_DAYS      # ごみ箱フォルダの日付のフォルダを起動時に消すまでの日数
REQUEST_DIR = placement.REQUEST_DIR   # 書き出し先の下の友人の依頼のフォルダ(依頼)
APP_INTAKE = "intake"     # 作業データ app の下の、友人の依頼の動画の写し(app\intake\<日付>\<依頼 id>\。書き出し先が固定ディスクでない PC)
DELIVERIES_LOG = _deliveries.LOG      # 届けた記録(持ち主は ② flow/deliveries。logs の中)
ROOTS_FILE = "trash-roots.json"   # 作業データの外に作ったごみ箱フォルダの一覧(起動時の purge が見る)
DRIVE_TRASH = "youtube-tools ごみ箱"   # 動画のドライブに書き出し先が無いときのごみ箱(<ドライブ>\youtube-tools ごみ箱\)
REASON_SUFFIX = ".理由.txt"   # 失敗\\ の物に添える断った理由(受付・送り返しとも。returns._move と intake の決まり)
VIDEO_EXTS = (".mp4", ".mkv", ".mov", ".webm", ".m4v", ".avi", ".ts")
AUTO_DELIVERED = True   # 自動で移す(ユーザー 10-24。False = 何も移さない。ごみ箱の古い日付は今までどおり消す)
AUTO_EVERY_SEC = 12 * 3600   # 自動で移す間隔(起動のすぐあとと、そのあと 12 時間ごと)
OLD_PACKS = True        # 完成品のパックを作ってから KEEP_DAYS 日で移す(10-24。False = 案件・届けた記録で分かる物だけ = 前の形)
KEEP_FOLDERS = ("学習用データ", "評価用データ")   # この名前のフォルダの下は、完成品のパックでも移さない(研究と学習の材料・精度の評価)
PACK_DEPTH = 4          # 書き出し先から <名前>_pack を探す深さ(書き出し先\<配信>\<名前>_pack が 2。依頼のフォルダの分の余裕)


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


def _newest(path):
    """ファイルの更新時刻・フォルダなら中の一番新しいファイルの更新時刻(秒。ファイルが無ければフォルダ自身)"""
    if not os.path.isdir(path):
        return _mtime(path)
    times = [_mtime(os.path.join(d, f)) for d, _dirs, files in os.walk(path) for f in files]
    return max(times) if times else _mtime(path)


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
        self._known = {}          # id → item(auto_clean が出した物だけ move できる)

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

    # ---------- 届けた物を自動で移す(ユーザー 10-24「精度改善以外で、自分用に動画を保存する意味がない」) ----------
    def delivered_items(self, keep_paths=()):
        """自動で移す物 -> [item](parts = 動画とパックのフォルダだけ)。友人へ届けて keep_days 日たった切り抜き(届けた記録のパックのフォルダ・
        切り抜きの動画・その _edit.mp4)と、依頼の置き場所の動画とパック(_requests)。届けていない物・keep_paths(確かめるで答えを待っている
        切り抜きの動画)は出さない。文書・作業用の記録・字幕は移さない(精度の材料)"""
        got = _deliveries.rows(os.path.join(self.app_dir, "logs"))
        if got is None:
            return []   # 届けたかが分からない = 何も移さない
        now, days = self.clock(), self.keep_days * 86400
        keep = {os.path.normcase(os.path.abspath(p)) for p in keep_paths or () if isinstance(p, str) and p}
        last = {}   # パックのフォルダ -> (最後に届けた時刻 秒, フォルダ, 切り抜きの動画)
        for d in got:
            at = d.get("at")
            sec = at / 1000.0 if isinstance(at, (int, float)) and not isinstance(at, bool) and at > 0 else 0.0
            for pk in d.get("packs") or ():
                if not isinstance(pk, dict) or not isinstance(pk.get("dir"), str) or not pk["dir"]:
                    continue
                k = os.path.normcase(os.path.abspath(pk["dir"]))
                if k not in last or sec > last[k][0]:
                    last[k] = (sec, pk["dir"], pk.get("path") if isinstance(pk.get("path"), str) else "")
        out, taken = [], set()
        for it in self._requests():   # 依頼の置き場所(依頼\\)の動画とパック。下の届けた記録のパックと同じ物は 1 回だけ
            if it["kind"] == "intake" and "届けてから" in it["note"]:   # 届けた依頼だけ(手で置いた動画 = 届けていない は残す)
                it["parts"] = [p for p in it["parts"] if os.path.normcase(os.path.abspath(p)) not in keep]
                if it["parts"]:
                    it["bytes"] = sum(_size(p) for p in it["parts"])
                    taken.update(os.path.normcase(os.path.abspath(p)) for p in it["parts"])
                    out.append(it)
        for sec, pdir, clip in last.values():
            if not sec or now - sec <= days or os.path.normcase(os.path.abspath(pdir)) in taken:
                continue   # 時刻の無い古い行・まだ日数がたっていない・依頼の置き場所で移す
            clip = clip if clip and os.path.isfile(clip) else ""
            if clip and os.path.normcase(os.path.abspath(clip)) in keep:
                continue   # 確かめるで答えを待っている(パックも残す = 案件の画面から同じ物を見られる)
            parts = ([pdir] if os.path.isdir(pdir) else []) + ([clip] if clip else [])
            parts += [p for p in _trash.existing_sidecars(clip) if p.lower().endswith(VIDEO_EXTS)] if clip else []
            if not parts:
                continue
            name = "%s_%s" % (os.path.basename(os.path.dirname(pdir.rstrip("\\/"))), os.path.basename(pdir.rstrip("\\/")))
            it = _parts_item("export", os.path.dirname(pdir.rstrip("\\/")), "届けてから %d 日" % int((now - sec) // 86400), parts)
            it.update(id=_id(pdir), name=name[:120])
            out.append(it)
        return out

    def stale_exports(self, cases, keep_paths=(), busy_ids=(), taken=()):
        """届けていない書き出し(ユーザー 10-24「自動でいい」): 案件(配信)の切り抜きの動画・その _edit.mp4・パックのフォルダの、
        どれも keep_days 日より前に書いた物(パックの中の一番新しいファイルまで見る = 作っている途中・作り直したばかりは移さない)。
        keep_paths(評価用の動画・確かめるで待っている物)・busy_ids(まとめて実行が今動いている配信)・taken(ほかの決まりで移す物)は除く"""
        now, days = self.clock(), self.keep_days * 86400
        keep = {os.path.normcase(os.path.abspath(p)) for p in keep_paths or () if isinstance(p, str) and p}
        taken = set(taken)
        out = []
        for c in cases or ():
            if not isinstance(c, dict) or c.get("id") in busy_ids:
                continue
            for cl in c.get("clips") or ():
                p = cl.get("path") if isinstance(cl, dict) else None
                if not isinstance(p, str) or not p or not os.path.isfile(p):
                    continue
                key = os.path.normcase(os.path.abspath(p))
                if key in keep or key in taken:
                    continue
                pk = cl.get("pack") if isinstance(cl.get("pack"), dict) else {}
                pdir = pk.get("dir") if isinstance(pk.get("dir"), str) else ""
                parts = [p] + [x for x in _trash.existing_sidecars(p) if x.lower().endswith(VIDEO_EXTS)] + ([pdir] if pdir and os.path.isdir(pdir) else [])
                if any(os.path.normcase(os.path.abspath(x)) in taken for x in parts) or now - max(_newest(x) for x in parts) <= days:
                    continue
                it = _parts_item("export", os.path.dirname(p), "書き出してから %d 日・届けていない" % int((now - max(_newest(x) for x in parts)) // 86400), parts)
                it.update(id=_id(p), name=("%s_%s" % (os.path.basename(os.path.dirname(p)), os.path.basename(p)))[:120])
                taken.update(os.path.normcase(os.path.abspath(x)) for x in parts)
                out.append(it)
        return out

    def old_packs(self, keep_paths=(), taken=(), busy_dirs=()):
        """完成品のパック(10-24): 書き出し先の下の <名前>_pack と、隣の書き出しの動画(<名前>.mp4 と _edit.mp4)。
        中の一番新しいファイルから keep_days 日たった物。KEEP_FOLDERS の下・ごみ箱・keep_paths(確かめるで待っている切り抜き・評価用の動画)・
        taken(ほかの決まりで移す物)・busy_dirs(まとめて実行が今動いている配信の切り抜きのあるフォルダ)は除く"""
        if not OLD_PACKS:
            return []
        now, days = self.clock(), self.keep_days * 86400
        keep = {os.path.normcase(os.path.abspath(p)) for p in keep_paths or () if isinstance(p, str) and p}
        taken = set(taken)
        out, seen = [], set()
        for root in self._out_dirs():
            base = root.rstrip("\\/").count(os.sep)
            for cur, dirs, _files in os.walk(root):
                if any(k in cur for k in KEEP_FOLDERS) or os.path.basename(cur) in (trashbin.TRASH_DIR, DRIVE_TRASH) or os.path.normcase(cur) in busy_dirs:
                    dirs[:] = []
                    continue
                if cur.count(os.sep) - base >= PACK_DEPTH:
                    dirs[:] = []
                packs = [d for d in dirs if d.lower().endswith("_pack")]
                dirs[:] = [d for d in dirs if d not in packs and d not in KEEP_FOLDERS and d != trashbin.TRASH_DIR]
                for d in packs:
                    pdir = os.path.join(cur, d)
                    key = os.path.normcase(os.path.abspath(pdir))
                    if key in seen or key in taken or os.path.islink(pdir) or os.path.isjunction(pdir):
                        continue
                    seen.add(key)
                    stem = os.path.join(cur, d[:-5])
                    clips = [p for p in (stem + e for e in VIDEO_EXTS) if os.path.isfile(p)]
                    clips += [x for c in clips for x in _trash.existing_sidecars(c) if x.lower().endswith(VIDEO_EXTS)]
                    parts = [pdir] + clips
                    if any(os.path.normcase(os.path.abspath(x)) in keep or os.path.normcase(os.path.abspath(x)) in taken for x in parts):
                        continue
                    age = now - max(_newest(x) for x in parts)
                    if age <= days:
                        continue
                    it = _parts_item("export", cur, "作ってから %d 日・完成品のパック" % int(age // 86400), parts)
                    if it:
                        it.update(id=_id(pdir), name=("%s_%s" % (os.path.basename(cur), d))[:120])
                        taken.update(os.path.normcase(os.path.abspath(x)) for x in parts)
                        out.append(it)
        return out

    def auto_items(self, keep_paths=(), intake_dir=None, cases=None, busy_ids=()):
        """自動で移す物の全部: 届けた切り抜き・依頼の置き場所(delivered_items)・届けていない書き出し(stale_exports。cases があるとき)・
        受付の写し(_app_intake の届けた物)・受付済みと失敗(_intake・_failed)"""
        keep = {os.path.normcase(os.path.abspath(p)) for p in keep_paths or () if isinstance(p, str) and p}
        out = self.delivered_items(keep_paths)
        if cases:
            out += self.stale_exports(cases, keep_paths, busy_ids, {os.path.normcase(os.path.abspath(x)) for it in out for x in it["parts"]})
        busy_dirs = {os.path.normcase(os.path.dirname(os.path.abspath(cl["path"]))) for c in cases or () if isinstance(c, dict) and c.get("id") in busy_ids
                     for cl in c.get("clips") or () if isinstance(cl, dict) and isinstance(cl.get("path"), str) and cl["path"]}
        out += self.old_packs(keep_paths, {os.path.normcase(os.path.abspath(x)) for it in out for x in it["parts"]}, busy_dirs)   # 完成品のパック(10-24)
        for it in self._app_intake():
            if "届けてから" in it["note"]:
                it["parts"] = [p for p in it["parts"] if os.path.normcase(os.path.abspath(p)) not in keep]
                if it["parts"]:
                    it["bytes"] = sum(_size(p) for p in it["parts"])
                    out.append(it)
        out += self._intake(intake_dir) + self._failed(intake_dir)
        self._known = {it["id"]: it for it in out}   # move はここで出した物だけ
        return out

    def auto_clean(self, keep_paths=(), intake_dir=None, dry_run=False, cases=None, busy_ids=()):
        """自動でごみ箱へ(AUTO_DELIVERED)。-> {"items": [{kind, name, path, bytes, parts, note}], "moved": 数, "failed": 数, "bytes"}。
        dry_run = 一覧だけ(移さない)。移した物は ごみ箱\\<日付>\\<種類>\\ に入り、trash_days 日で消える(今の決まり)"""
        if not AUTO_DELIVERED:
            return {"items": [], "moved": 0, "failed": 0, "bytes": 0}
        items = self.auto_items(keep_paths, intake_dir, cases, busy_ids)
        res = {"items": [{"kind": it["kind"], "name": it["name"], "path": it["path"], "bytes": it["bytes"], "parts": list(it.get("parts") or [it["path"]] + list(it.get("extra") or [])),
                          "note": it["note"]} for it in items],
               "moved": 0, "failed": 0, "bytes": sum(it["bytes"] for it in items)}
        if dry_run or not items:
            return res
        r = self.move([it["id"] for it in items])
        res["moved"], res["failed"] = len(r["moved"]), len(r["failed"])
        return res

    # ---------- 移す・消す ----------
    def move(self, ids):
        """auto_clean が出した物だけを ごみ箱\\<日付>\\<種類>\\ へ移す。-> {"moved": [...], "failed": [{id, path, error}], "unknown": [ids], "trash": ...}"""
        moved, failed, unknown = [], [], []
        for i in ids if isinstance(ids, list) else []:
            it = self._known.get(str(i))
            if not it:
                unknown.append(str(i)[:40])
                continue
            src = it["path"]
            if it.get("parts"):
                self._move_parts(it, moved, failed)
                continue
            # 元動画と途中のファイルは <名前>\ にまとめる(作業用の物は その中の 作業用\)。元動画が移せなければほかは移さない・
            # 途中のファイルが移せなくても元動画は移した(次の候補の work に出る)
            stem = os.path.splitext(it["name"])[0] if it.get("extra") else None
            r = trashbin.to_trash(self, [src] + list(it.get("extra") or []), it["kind"], stem, need_first=True, clock=self.clock,
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
        r = trashbin.to_trash(self, it["parts"], it["kind"], it["name"], clock=self.clock, log=lambda m: self.log("片付け: " + m))
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
        return len(trashbin.purge(root, self.trash_days, self.clock(), log=self.log))


_old_day_dirs = trashbin.old_day_dirs   # 日付のフォルダの決まりは ytt/trashbin の 1 か所(受付済み と ごみ箱フォルダ。① の録画の部品も)
