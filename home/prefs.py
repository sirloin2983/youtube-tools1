"""ホームの設定(画面の直し「気が利く画面へ」の土台。.design/ux-consistency/REQUEST.md の 1)。

どの入口から変えても全部の入口の既定になる値を、ホームの作業データの prefs.json に1つだけ持つ:
  autorun  … まとめて実行の形・採用数・カットの方法・上書き・失敗したとき
  streamer … 配信者(字幕の色)の記憶: 文書 id / 配信(video id)/ チャンネル → 名前(空 = 「色なし」を覚えた)
  keymap   … 共通の再生キーの割り当て(編集・スタジオで同じ)
  intake   … 友人からの依頼の受付(home/intake.py。docs/design/friend-intake.md): 見張るフォルダ・オン/オフ・既定の切り抜く数・上限
  backup   … 作業データのバックアップ(home/backup.py。docs/spec/data-location.md): オン/オフ・写す先のフォルダ・間隔(時間)
画面は api/ytt/prefs(入口の launch.py)で読み書きする。**節ごとに直す**(全体を上書きしない。窓を2つ並べたとき、後から送った側が他の節を消さないため)。
値は許可した形だけ受け付け、知らないキーは捨てる。壊れたファイルは読まずに既定で動き、次に書くときに退避してから書き直す。
"""
import json
import os
import re
import threading
import time

MAX_BYTES = 256 * 1024
MAX_REMEMBER = 2000        # 配信者の記憶は種類ごとにこの件数まで(古い順に捨てる)
NAME_MAX = 60
KEY_MAX = 120
SECTIONS = ("autorun", "streamer", "keymap", "intake", "backup")
PATCHABLE = ("autorun", "keymap", "intake", "backup")
AUTORUN_MODES = ("full", "adopted", "transcribe")      # home/autorun.py の MODES と同じ名前
CUT_METHODS = ("rows", "none", "silence")
ON_FAIL = ("next", "stop")
STREAMER_KINDS = ("docs", "videos", "channels")
COMBO_RE = re.compile(r"^(?:Shift\+)?(?:[^\x00-\x1f\x7f]|[A-Z][A-Za-z0-9]{1,20})$")   # UIKit.keys.comboOf の表記(Shift+ と、1文字かキーの名前)
ACTION_RE = re.compile(r"^[A-Za-z][A-Za-z0-9_.-]{0,40}$")
DEFAULTS = {"autorun": {"mode": None, "top": 3, "cut": "none",   # 既定はカットしない(2026-10-01 ユーザー決定)
                         "overwrite": False, "onFail": "next"},
            "streamer": {k: {} for k in STREAMER_KINDS},
            "keymap": {"playback": {}},
            "intake": {"enabled": False, "folder": "", "top": 3, "dailyMax": 5, "maxHours": 8, "maxGB": 20, "interval": 30},
            "backup": {"enabled": False, "folder": "", "everyHours": 24}}
INTAKE_RANGES = {"top": (1, 10, "既定の切り抜く数"), "dailyMax": (1, 50, "1日の上限"), "maxHours": (1, 24, "配信の長さの上限(時間)"),
                 "maxGB": (1, 200, "動画の大きさの上限(GB)"), "interval": (10, 600, "見る間隔(秒)")}
FOLDER_MAX = 260


class PrefsError(ValueError):
    pass


def _clean_autorun(v, cur):
    out = dict(cur)
    if "mode" in v:
        if v["mode"] is not None and v["mode"] not in AUTORUN_MODES:
            raise PrefsError("まとめて実行の形が正しくありません")
        out["mode"] = v["mode"]
    if "top" in v:
        if not isinstance(v["top"], int) or isinstance(v["top"], bool) or not 1 <= v["top"] <= 20:
            raise PrefsError("採用数は 1〜20 で指定してください")
        out["top"] = v["top"]
    if "cut" in v:
        if v["cut"] not in CUT_METHODS:
            raise PrefsError("カットの方法が正しくありません")
        out["cut"] = v["cut"]
    if "overwrite" in v:
        out["overwrite"] = v["overwrite"] is True
    if "onFail" in v:
        if v["onFail"] not in ON_FAIL:
            raise PrefsError("失敗したときの動きが正しくありません")
        out["onFail"] = v["onFail"]
    return out


def _clean_folder(f):
    """PC の中の絶対パスだけ(空 = 決めていない)。ネットワークのパスは断る(見るたびにサーバーへ資格情報を送らない)"""
    if not isinstance(f, str):
        raise PrefsError("フォルダは文字で指定してください")
    f = f.strip().strip('"').strip()
    if f:
        if len(f) > FOLDER_MAX or any(ord(ch) < 32 for ch in f):
            raise PrefsError("フォルダの指定が長すぎるか、使えない文字があります")
        if f.replace("/", "\\").startswith("\\\\"):
            raise PrefsError("ネットワーク上のフォルダは選べません(この PC のドライブのフォルダを指定してください)")
        if not os.path.isabs(f) or (os.name == "nt" and not re.match(r"^[A-Za-z]:[\\/]", f)):
            raise PrefsError("フォルダは C:\\… のような絶対パスで指定してください")
    return f


def _clean_backup(v, cur):
    """作業データのバックアップの設定(home/backup.py)。写す先が作業データの中でないか・ドライブがあるかは、写すときに確かめて画面に出す(ここでは形だけ)"""
    out = dict(cur)
    if "enabled" in v:
        out["enabled"] = v["enabled"] is True
    if "folder" in v:
        out["folder"] = _clean_folder(v["folder"])
    if "everyHours" in v:
        x = v["everyHours"]
        if isinstance(x, bool) or not isinstance(x, int) or not 1 <= x <= 168:
            raise PrefsError("バックアップの間隔は 1〜168 時間で指定してください")
        out["everyHours"] = x
    if out["enabled"] and not out["folder"]:
        raise PrefsError("バックアップ先のフォルダを指定してから、オンにしてください")
    return out


def _clean_intake(v, cur):
    """依頼の受付の設定。フォルダは PC の中の絶対パスだけ(ネットワークのパスは断る = 見張るたびにサーバーへ資格情報を送らない)。
    フォルダがあるかは見張りの処理が毎回確かめて画面に出す(ここでは形だけ)"""
    out = dict(cur)
    if "enabled" in v:
        out["enabled"] = v["enabled"] is True
    if "folder" in v:
        out["folder"] = _clean_folder(v["folder"])
    for k, (lo, hi, label) in INTAKE_RANGES.items():
        if k in v:
            x = v[k]
            if isinstance(x, bool) or not isinstance(x, (int, float)) or not lo <= x <= hi or (k in ("top", "dailyMax", "interval") and x != int(x)):
                raise PrefsError("%sは %d〜%d で指定してください" % (label, lo, hi))
            out[k] = int(x) if k in ("top", "dailyMax", "interval") else x
    return out


def _clean_keymap(v, cur):
    out = {"playback": dict(cur.get("playback") or {})}
    pb = v.get("playback")
    if pb is not None:
        if not isinstance(pb, dict) or len(pb) > 40:
            raise PrefsError("キーの割り当ての形が正しくありません")
        clean = {}
        for k, c in pb.items():
            if not isinstance(k, str) or not ACTION_RE.fullmatch(k) or not isinstance(c, str) or (c and not COMBO_RE.fullmatch(c)):
                raise PrefsError("キーの割り当ての形が正しくありません: %s" % str(k)[:40])
            clean[k] = c
        out["playback"] = clean   # 再生キーは一覧ごと送る(画面の一覧 = 全部の割り当て)
    return out


def _clean_name(name):
    if not isinstance(name, str):
        raise PrefsError("名前は文字で指定してください")
    s = name.strip()
    if len(s) > NAME_MAX or any(ord(ch) < 32 for ch in s):
        raise PrefsError("名前が長すぎるか、使えない文字があります")
    return s


def _read_streamer(v):
    out = {}
    for k in STREAMER_KINDS:
        d = v.get(k) if isinstance(v, dict) else None
        out[k] = {str(a)[:KEY_MAX]: str(b)[:NAME_MAX] for a, b in (d.items() if isinstance(d, dict) else []) if isinstance(b, str)}
    return out


def guess_streamer(prefs, doc_id=None, video_id=None, channel=None, from_channel=None):
    """配信者(字幕の色)の名前を決める(気が利く画面へ 段5)。順: 文書に覚えた名前 → 配信に覚えた名前 → チャンネルに覚えた名前 →
    チャンネル名から(from_channel(channel) -> 名前 か None。1人に決まるときだけ)。
    -> {"name": 名前("" = 「色なし」を覚えている・None = 決まらない), "source": "doc"|"video"|"channel"|"auto"|None}"""
    st = prefs.get(["streamer"])["streamer"] if prefs else {"docs": {}, "videos": {}, "channels": {}}
    for kind, key in (("docs", doc_id), ("videos", video_id), ("channels", channel)):
        if isinstance(key, str) and key and key in st[kind]:
            return {"name": st[kind][key], "source": kind[:-1] if kind != "docs" else "doc"}
    name = from_channel(channel) if from_channel and channel else None
    return {"name": name, "source": "auto" if name else None}


class Prefs:
    def __init__(self, path, writer):
        """writer(path, bytes): 原子的な書き込み(ytt_core.fsio.atomic_write)"""
        self.path = path
        self.write = writer
        self.lock = threading.Lock()

    def _load(self):
        """-> (中身, 壊れていたか)"""
        try:
            with open(self.path, "rb") as f:
                raw = f.read(MAX_BYTES + 1)
        except FileNotFoundError:
            return {}, False
        except OSError:
            return {}, True
        try:
            d = json.loads(raw.decode("utf-8-sig")) if len(raw) <= MAX_BYTES else None
        except ValueError:
            d = None
        return (d, False) if isinstance(d, dict) else ({}, True)

    def _section(self, d, name):
        v = d.get(name)
        if name == "autorun":
            try:
                return _clean_autorun(v if isinstance(v, dict) else {}, DEFAULTS["autorun"])
            except PrefsError:
                return dict(DEFAULTS["autorun"])
        if name == "intake":
            try:
                return _clean_intake(v if isinstance(v, dict) else {}, DEFAULTS["intake"])
            except PrefsError:
                return dict(DEFAULTS["intake"])
        if name == "backup":
            try:
                return _clean_backup(v if isinstance(v, dict) else {}, DEFAULTS["backup"])
            except PrefsError:
                return dict(DEFAULTS["backup"])
        if name == "keymap":
            try:
                return _clean_keymap(v if isinstance(v, dict) else {}, DEFAULTS["keymap"])
            except PrefsError:
                return {"playback": {}}
        return _read_streamer(v)

    def get(self, sections=None):
        names = [s for s in (sections or SECTIONS) if s in SECTIONS]
        with self.lock:
            d, _broken = self._load()
            return {n: self._section(d, n) for n in names}

    def _save(self, d, broken):
        if broken and os.path.exists(self.path):   # 壊れたファイルは消さずに退避(中身を調べられるように)
            try:
                os.replace(self.path, "%s.broken-%s" % (self.path, time.strftime("%Y%m%d-%H%M%S")))
            except OSError:
                pass
        data = json.dumps(d, ensure_ascii=False, indent=1).encode("utf-8")
        if len(data) > MAX_BYTES:
            raise PrefsError("設定が大きすぎて保存できません")
        os.makedirs(os.path.dirname(self.path) or ".", exist_ok=True)
        self.write(self.path, data)

    def patch(self, section, value):
        """節を直す(送ったキーだけ)。-> その節の新しい値"""
        if section not in PATCHABLE:
            raise PrefsError("その設定は直せません: %s" % str(section)[:40])
        if not isinstance(value, dict):
            raise PrefsError("値の形が正しくありません")
        with self.lock:
            d, broken = self._load()
            cur = self._section(d, section)
            new = {"autorun": _clean_autorun, "keymap": _clean_keymap, "intake": _clean_intake, "backup": _clean_backup}[section](value, cur)
            d[section] = new
            self._save(d, broken)
            return new

    def remember(self, kind, key, name):
        """配信者の記憶を1件(文書 id / 配信 / チャンネル → 名前)。name が "" = 「色なし」を覚える(自動で入れ直さない)。
        同じキーは新しい方へ動かし、MAX_REMEMBER を超えたら古い順に捨てる"""
        if kind not in STREAMER_KINDS:
            raise PrefsError("覚える種類が正しくありません")
        if not isinstance(key, str) or not key.strip() or len(key) > KEY_MAX or any(ord(ch) < 32 for ch in key):
            raise PrefsError("覚える相手の指定が正しくありません")
        name = _clean_name(name)
        with self.lock:
            d, broken = self._load()
            st = _read_streamer(d.get("streamer"))
            m = st[kind]
            m.pop(key, None)
            m[key] = name
            while len(m) > MAX_REMEMBER:
                m.pop(next(iter(m)))
            d["streamer"] = st
            self._save(d, broken)
            return st
