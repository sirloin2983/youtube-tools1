"""設定ファイル(JSON の辞書)の読み書きの共通部品(設定を 1 つにまとめる 段 2 = S4。docs/spec/settings.md の 4)。

ホームの prefs.json(src/home/prefs.py)・スタジオの settings-ui.json(src/studio/store.py)・編集の settings.json(src/editor/ed_learn.py)が
同じ決まりで扱う: 読めない・形が違う・大きすぎるファイルは「壊れている」として既定({})で動き、次に書くときに `.broken-<日時>` に退避してから
書き直す(中身を調べられるように消さない)。書き込みは原子的(fsio.atomic_write)で、大きさの上限を超えたら保存しない(SettingsTooLarge)。
節(section)の名前の形と、節を差し替える・節の中の鍵を直す・最上位の鍵を直す、の 3 つの書き方もここで 1 つにする。
ファイルは分けたまま(data-location.md とバックアップの形・ツール単独のテストを変えないため)。API の形(各ツールの /api/settings・api/ytt/prefs)は変えていない。

使い方:
    sf = SettingsFile(path, max_bytes=1024 * 1024)
    d = sf.read()                                  # 中身(新しい dict。壊れていれば {})
    sf.set_section("review", {...})                # 節を丸ごと置き換える(名前は SECTION_RE)
    sf.patch_section("autorun", value, cleaner)    # cleaner(value, cur) -> new を節に入れる(検査はツール側の関数)
    sf.update_keys({"packFps": "30"}, allow)       # 最上位の鍵を、allow[key](value) が真のものだけ直す
    sf.merge_top({"glossary": "...", "old": None}, skip=allow)   # 最上位の鍵を合わせる(None = 消す。skip の鍵は触らない)
    with sf.lock: d, broken = sf.load(); ...; sf.save(d, broken)   # 自分で読み書きするとき(ホームの remember・hide など)
"""
import json
import os
import re
import threading
import time

from . import fsio

SECTION_RE = re.compile(r"[A-Za-z][A-Za-z0-9_-]{0,31}")
KEY_MAX = 60           # 最上位の鍵の長さの上限(merge_top)
PATCH_MAX = 200        # 1 回の merge_top で直せる鍵の数


class SettingsError(ValueError):
    """保存できない・直せない(文はそのまま画面に出せる日本語)。ツール側は自分のエラーの型(ApiError・PrefsError)に包み直す"""


class SettingsTooLarge(SettingsError):
    """大きさの上限を超えた(ツール側は 413 にする)"""


def section_name_ok(name):
    """節の名前の形(英字で始まる 32 文字まで。英数字・_・-)"""
    return isinstance(name, str) and bool(SECTION_RE.fullmatch(name))


def retire_broken(path):
    """壊れたファイルを `<path>.broken-<日時>` に退避する(消さない = 中身を調べられるように)。-> 退避先 か None(無い・退避できない)"""
    if not os.path.exists(path):
        return None
    dst = "%s.broken-%s" % (path, time.strftime("%Y%m%d-%H%M%S"))
    try:
        os.replace(path, dst)
    except OSError:
        return None
    return dst


class SettingsFile:
    """1 つの設定ファイル(JSON の辞書)。読む・書く・節や鍵を直す。スレッドから同時に呼んでよい(lock は RLock = 入れ子で使える)"""

    def __init__(self, path, max_bytes=1024 * 1024, writer=None, indent=1, lock=None, retire=True):
        """writer(path, bytes): 原子的な書き込み(省略で fsio.atomic_write)。indent: 書くときの字下げ(None で 1 行)。
        lock: 外から渡すロック(ツールの既存のロックと同じ物を使うとき)。retire: 壊れたファイルを書き直す前に退避するか"""
        self.path = path
        self.max_bytes = max_bytes
        self.write = writer or fsio.atomic_write
        self.indent = indent
        self.lock = lock if lock is not None else threading.RLock()
        self.retire = retire

    # ---- 読む ----
    def load(self):
        """-> (中身, 壊れていたか)。無い = ({}, False)。読めない・JSON でない・辞書でない・大きすぎる・NaN を含む = ({}, True)。
        中身は毎回新しい dict(呼ぶ側が書き換えてよい)"""
        if not os.path.exists(self.path):
            return {}, False
        d = fsio.read_json_or(self.path, None, max_bytes=self.max_bytes, kind=dict)
        return (d, False) if isinstance(d, dict) else ({}, True)

    def read(self):
        """中身だけ(壊れていれば {})"""
        return self.load()[0]

    # ---- 書く ----
    def dumps(self, d):
        return json.dumps(d, ensure_ascii=False, indent=self.indent).encode("utf-8")

    def save(self, d, broken=False):
        """d を書く。大きさの上限を超えたら SettingsError(ファイルは変えない)。broken なら先に今のファイルを退避する。
        書けないとき(OSError)は上げる(ツール側が「保存できませんでした」にする)"""
        if not isinstance(d, dict):
            raise SettingsError("設定は辞書で指定してください")
        data = self.dumps(d)
        if len(data) > self.max_bytes:
            raise SettingsTooLarge("設定が大きすぎて保存できません(%d KB まで)" % (self.max_bytes // 1024))
        if broken and self.retire:
            retire_broken(self.path)
        os.makedirs(os.path.dirname(self.path) or ".", exist_ok=True)
        self.write(self.path, data)

    def update(self, fn):
        """ロックの中で 読む → fn(d) → 書く。fn は d を書き換えて、返したい値を返す(None でよい)。読み書きの間にほかの書き込みが挟まらない"""
        with self.lock:
            d, broken = self.load()
            result = fn(d)
            self.save(d, broken)
            return result

    # ---- 節(section)----
    def set_section(self, name, value):
        """節を丸ごと置き換える(スタジオの analyze・review の節)。-> 置いた値"""
        if not section_name_ok(name):
            raise SettingsError("section の名前が正しくありません")
        if not isinstance(value, dict):
            raise SettingsError("value は辞書で指定してください")

        def put(d):
            d[name] = value
            return value
        return self.update(put)

    def patch_section(self, name, value, cleaner, current=None):
        """節の中の鍵を直す(送った鍵だけ)。cleaner(value, cur) が検査して新しい節を返す(ツール側の関数。範囲の外は ValueError 系を上げる)。
        current(d) があれば今の節の値をそれで決める(保存してある値を検査し直して使うとき)。-> 新しい節"""
        if not section_name_ok(name):
            raise SettingsError("section の名前が正しくありません")
        if not isinstance(value, dict):
            raise SettingsError("値の形が正しくありません")

        def put(d):
            cur = current(d) if current else (d.get(name) if isinstance(d.get(name), dict) else {})
            new = cleaner(value, cur)
            d[name] = new
            return new
        return self.update(put)

    # ---- 最上位の鍵(編集の settings.json は平らな 1 段)----
    def update_keys(self, values, allow):
        """最上位の鍵を、allow[key](value) が真のものだけ直す(ほかの画面から直してよい決まった項目)。-> 直したあとの {鍵: 値}"""
        if not isinstance(values, dict) or not values:
            raise SettingsError("直す値がありません")
        for k, v in values.items():
            chk = allow.get(k) if isinstance(allow, dict) else None
            if not chk or not chk(v):
                raise SettingsError("その設定は直せません: %s" % str(k)[:40])

        def put(d):
            d.update(values)
            return {k: d[k] for k in values}
        return self.update(put)

    def merge_top(self, patch, skip=()):
        """最上位の鍵を合わせる(画面が最後に保存した内容との差だけ送る形)。値が None の鍵は消す。skip の鍵は触らない
        (値の検査がある update_keys だけで直す項目)。形が違えば SettingsError"""
        if (not isinstance(patch, dict) or len(patch) > PATCH_MAX
                or any(not isinstance(k, str) or not k or len(k) > KEY_MAX for k in patch)):
            raise SettingsError("設定の直し方(patch)の形が正しくありません")

        def put(d):
            for k, v in patch.items():
                if k in skip:
                    continue
                if v is None:
                    d.pop(k, None)
                else:
                    d[k] = v
            return None
        self.update(put)
