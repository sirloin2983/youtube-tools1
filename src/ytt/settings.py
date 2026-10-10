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

編集の設定(settings.json)の読み書きと鍵の検査(load_settings・patch_settings・merge_settings・replace_settings・SETTINGS_PATCH_KEYS)も
ここに置く(役割で組み直す RS3-1。2026-10-10 に editor/ed_learn.py から移した = どの層の部品も ed_learn を読まずに設定を読める)。
置き場所は ytt/workdata の SETTINGS を呼ぶたびに読む(テストの S.SETTINGS = … が効く)。鍵の検査は持ち主の部品が register_patch_key で足す
(2 つ目のエンジンの altEngine は ed_alt)。
評価用のフォルダの判定(eval_dirs・in_eval_dir・eval_name_guard。設定 evalDirs を読む)もここ(RS0-f。RS3-1 に ed_relink から)。編集の部品・テストは serve の名前の受付(S.load_settings など)からも読める。
"""
import json
import os
import re
import threading
import time

from . import errors as _errors, fsio, workdata as _workdata

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


# ---------- 編集の設定(settings.json。RS3-1 に editor/ed_learn.py から移した)----------
SETTINGS_MAX = 400000   # settings.json の大きさの上限(バイト)。読むときも書くときも同じ
_settings_lock = threading.RLock()   # 設定の読み→書きを 1 つにする(SettingsFile に渡す)


def _write_fsync(path, data):
    """fsync に失敗したら保存も失敗にする書き込み(編集の ed_state.atomic_write と同じ = 停電のあとに空の設定を残さない)"""
    fsio.atomic_write(path, data, fsync_required=True)


def _settings_file():
    """編集の設定ファイル(読む・書く・退避・大きさの上限は SettingsFile。ホーム・スタジオと同じ決まり。S4 2026-10-09)。
    workdata.SETTINGS はテストが差し替えるので、呼ぶたびに作る(軽い)"""
    return SettingsFile(_workdata.SETTINGS, max_bytes=SETTINGS_MAX, writer=_write_fsync, indent=1, lock=_settings_lock)


def load_settings():
    """編集の設定(settings.json)。無い・壊れている・dict でなければ {}(毎回新しい dict = 呼ぶ側が書き換えてよい)。
    BOM 付きも読む(メモ帳の「UTF-8 (BOM 付き)」で直されても読めるように)。1 回の要求で何度も使うときは、頭で 1 回読んで渡す"""
    return _settings_file().read()


# ほかの画面から直してよい設定と、その値の検査(送ったキーだけ直す。全体を上書きしない = 窓を並べても他の値を消さない。気が利く画面へ 1)。
# 編集のほかの部品が持つ値で検査する鍵は、その持ち主が register_patch_key で足す(altEngine = ed_alt の ALT_ENGINES)。evalDirs は下の評価用の節
SETTINGS_PATCH_KEYS = {"packLoudness": lambda v: not isinstance(v, bool) and v in (0, -11, -14, -16, -18),   # パックの音量(LUFS。0 = % で決める)
                       "packVolume": lambda v: isinstance(v, int) and not isinstance(v, bool) and 1 <= v <= 200,   # packLoudness が 0 のときの音量(%)
                       # パックの出力(3 パック のタブ・まとめて実行の欄が同じ値を読み書きする。気が利く画面へ 段4)
                       "packFps": lambda v: v in ("24", "25", "30", "50", "60"),
                       "packSize": lambda v: v in ("1080x1920", "1920x1080"),
                       "speakerColors": lambda v: isinstance(v, bool),
                       "packBackup": lambda v: isinstance(v, bool),
                       "packRender": lambda v: isinstance(v, bool),   # 粗編集の動画つき(段4 4-2: 覚える)
                       # キー配置(校正のキー。キーの一覧 = 設定の部品 UIKit.keymap が送る。気が利く画面へ 段6)
                       "keymap": lambda v: _keymap_ok(v),
                       # 話者判別のあと、短い 1 行だけ別の人になるのをならす(S2。試験中・既定オフ。pipeline/transcribe/diarize の smooth_)
                       "diarSmooth": lambda v: isinstance(v, bool),
                       # 2 カット の「無音 ▾」の値(気が利く画面へ 段7 E-5)。まとめて実行(pipeline/run.py の _pack_settings)も同じ鍵を読む
                       "cutSilence": lambda v: _cut_silence_ok(v),
                       # サムネの案の切り取り(パックの所の「サムネの案」。alt = 中央と右下を交互。P5。ed_thumb.THUMB_CROPS)
                       "thumbCrop": lambda v: v in ("alt", "center", "right")}
# 無音で削るときの値の範囲(cut2resolve の serve.py の spec_to_request と同じ。範囲の外は cut2resolve が 400 にする)
CUT_SILENCE_RANGE = {"noise": (-90, 0), "min": (0.05, 60), "pad": (0, 10)}
_KM_ID_RE = re.compile(r"^[A-Za-z][A-Za-z0-9_]{0,40}$")
_KM_COMBO_RE = re.compile(r"^(?:Shift\+)?(?:[^\x00-\x1f\x7f]|[A-Z][A-Za-z0-9]{1,20})$")   # UIKit.keys.comboOf の表記(home/prefs.py と同じ)


def register_patch_key(name, check):
    """api/settings/patch で直してよい鍵と、その値の検査 check(v) -> bool を足す(持ち主の部品が読み込みのときに 1 回。
    同じ名前をもう一度足したら置き換える = テストが部品を読み直しても重ならない)"""
    if not isinstance(name, str) or not name or not callable(check):
        raise ValueError("register_patch_key: 鍵の名前と検査の関数が要ります")
    SETTINGS_PATCH_KEYS[name] = check


def _cut_silence_ok(v):
    """{"noise", "min", "pad"} の 3 つがそろい、どれも範囲の中の数(bool・NaN・無限は断る)"""
    return (isinstance(v, dict) and set(v) == set(CUT_SILENCE_RANGE)
            and all(isinstance(x, (int, float)) and not isinstance(x, bool) and x == x and CUT_SILENCE_RANGE[k][0] <= x <= CUT_SILENCE_RANGE[k][1] for k, x in v.items()))


def _keymap_ok(v):
    return (isinstance(v, dict) and len(v) <= 60
            and all(isinstance(k, str) and _KM_ID_RE.fullmatch(k) and isinstance(c, str) and (c == "" or _KM_COMBO_RE.fullmatch(c)) for k, c in v.items()))


def _settings_error(e):
    """SettingsFile のエラーを API のエラーに(大きすぎる = 413。ほかは 400)"""
    if isinstance(e, SettingsTooLarge):
        return _errors.ApiError("too_big", "設定が大きすぎます", 413)
    return _errors.ApiError("bad_request", str(e), 400)


def patch_settings(obj):
    """POST /api/settings/patch {"values": {鍵: 値}}: SETTINGS_PATCH_KEYS の項目だけを、値を検査して直す(送った鍵だけ)"""
    try:
        out = _settings_file().update_keys(obj.get("values"), SETTINGS_PATCH_KEYS)
    except SettingsError as e:
        raise _settings_error(e)
    return {"ok": True, "values": out}


def merge_settings(obj):
    """PUT /api/settings {"patch": {キー: 値 | null}}: 最上位のキーだけを、ロックの中で今のファイルに合わせる(null = そのキーを消す)。
    api/settings/patch で直す項目(SETTINGS_PATCH_KEYS)は、丸ごとの保存と同じくここでは変えない(値の検査があるそちらの API だけで直す)。
    案の比較: 版(rev)で 409 にする案は競合を確実に見つけるが、設定の画面に「読み直す/上書き」の選択を作ることになる
    → キー単位の合わせで十分(同じキーを2つの窓で同時に変えたときだけ後勝ち。git の履歴(679ff01 以前)の docs/plan/phase2-data-safety.md の 6)"""
    p = obj.get("patch")
    if set(obj) != {"patch"} or not isinstance(p, dict):
        raise _errors.ApiError("bad_request", "設定の直し方(patch)の形が正しくありません", 400)
    try:
        _settings_file().merge_top(p, skip=SETTINGS_PATCH_KEYS)
    except SettingsError as e:
        raise _settings_error(e)
    return {"ok": True}


def replace_settings(obj):
    """PUT /api/settings(patch 無し = 丸ごと): 画面の設定で置き換える。ほかの画面から api/settings/patch で直す項目(SETTINGS_PATCH_KEYS)は
    サーバーの値を残す(古い画面が戻さないように)"""
    if not isinstance(obj, dict):
        raise _errors.ApiError("bad_request", "設定は辞書で指定してください", 400)

    def put(d):
        keep = {k: d[k] for k in SETTINGS_PATCH_KEYS if k in d}
        d.clear()
        d.update({k: v for k, v in obj.items() if k not in SETTINGS_PATCH_KEYS})
        d.update(keep)
    try:
        _settings_file().update(put)
    except SettingsError as e:
        raise _settings_error(e)
    return {"ok": True}


# ---------- 評価用のフォルダの判定(2026-10-01 ユーザー決定。docs/spec/eval-folder.md。RS3-1 に editor/ed_relink.py から移した = RS0-f)----------
# 設定 evalDirs のフォルダ(の下)にある動画は、精度を測るためだけのデータ。文字起こし・保存・付け替え・履歴から戻すときに評価用の印を付ける。
# 判定はパスを比べるだけ(ネットワーク上のパスには触らない)。整理(名前をそろえる)と仮置きは editor/ed_relink に残る
EVAL_DIRS_MAX = 10
EVAL_NAME_WORD = "評価用"


def _eval_dirs_ok(v):
    """設定 evalDirs の形(10 個まで・ドライブから始まる・ネットワーク上でない・「:」の代替ストリームでない)"""
    return (isinstance(v, list) and len(v) <= EVAL_DIRS_MAX
            and all(isinstance(p, str) and 3 <= len(p) <= 1000 and os.path.isabs(p) and not fsio.is_network_path(p)
                    and not any(ch in p for ch in "\x00\r\n") and ":" not in os.path.splitdrive(p)[1] for p in v))


SETTINGS_PATCH_KEYS["evalDirs"] = lambda v: _eval_dirs_ok(v)   # 評価用のフォルダ(この中の動画は評価用。整理で名前をそろえる。2026-10-01)


def eval_dirs():
    """設定の評価用のフォルダ(あるものだけ)。ネットワーク上・作業データの中は使わない"""
    v = load_settings().get("evalDirs")
    if not _eval_dirs_ok(v):
        return []
    out = []
    for p in v:
        p = os.path.abspath(p)
        try:
            if not fsio.is_remote_drive(p) and os.path.isdir(p) and not fsio.is_inside(p, _workdata.DATA_DIR) and not fsio.is_inside(_workdata.DATA_DIR, p):
                out.append(p)
        except (OSError, ValueError):
            pass
    return out


def in_eval_dir(path, dirs=None):
    """動画のパスが評価用のフォルダの中か(パスを比べるだけ。ネットワーク上のパスには触らない)"""
    s = str(path or "")
    if not s or fsio.is_network_path(s) or not os.path.isabs(s):
        return False
    return any(fsio.is_inside(s, d) for d in (eval_dirs() if dirs is None else dirs))


def eval_name_guard(path, is_eval=False, todo="文字起こししてください"):
    """設定 evalDirs が空(未設定・消えた)なのに、動画のパスのフォルダ名のどこかに「評価用」が入っているときは止めて案内する
    (設定が消えたまま文字起こしすると、評価用の動画が学習用の文書に混ざる。master-plan Q0)。設定があれば今までどおり(何もしない)。
    is_eval: 評価用として始める(画面のチェック・評価用の文書)なら混ざらないので通す。パスの文字を調べるだけでファイルには触らない"""
    if is_eval:
        return
    v = load_settings().get("evalDirs")
    if _eval_dirs_ok(v) and v:
        return
    if any(EVAL_NAME_WORD in part for part in re.split(r"[\\/]+", os.path.dirname(str(path or "")))):
        raise _errors.ApiError("eval_dir_unset", "評価用のフォルダの中の動画のようです。⚙ の『評価用のフォルダ』を設定してから%s(設定が無いと学習用に混ざります)" % todo, 400)
