# -*- coding: utf-8 -*-
"""友人の玄関の ⚙(F2-5。notes:plan/f1-friend-requirements.md の 7 章・9-2・A-8。今の送るアプリの Settings.cs と同じ規則を Python で)。

項目と置き場所:
    受け取るの保存先    <玄関>/save-dir.json の dir(無ければ %USERPROFILE%/Videos/受け取ったパック = server.save_dir)
    一時保管            スタジオの書き出し先 outDir と machine の caseRoot(同じ値にそろえる)。7-3 = 選び直しても移さない(新しい物から新しい場所)
    文字起こしのエンジン machine の device(A = vulkan / C = cuda)。C にして部品が足りなければ取る(setup.Setup)
    YouTube の API キー  <作業データ>/app/keys.json の youtubeApiKey(画面へはキーを返さない =「入っている / 無い」だけ)。
                        貼ったら videos.list を 1 回呼んで確かめ、使えるときだけ保存(Settings.cs の YtKeyCheck と同じ)。消すと "" を書く
                        (places.api_key_env が前のアプリの keys.json へ戻らない印)。入れた・消したは環境変数 YTT_YT_API_KEY にもすぐ写す
    空き容量の下限      machine の diskMinGB(GB)
    カットの既定        <玄関>/form.json の cut(none = しない・silence = 無音を削る。初めは none = A-8)。送る欄には出さず、送るときの束に効く
フォルダは画面から打たせない: [選ぶ] で玄関が Windows のフォルダを選ぶ窓を開く(FriendApp.pick_folder。テストと見本は偽物)。
"""
import json
import os
import tempfile
import urllib.error
import urllib.parse
import urllib.request

from flow import machine as _machine, spec as _spec
from ytt import fsio as _fsio, studio_env as _studio_env

KEYS_NAME = "keys.json"
KEY_FIELD = "youtubeApiKey"
KEY_ENV = "YTT_YT_API_KEY"
KEY_HELP = "配信のコメントに書かれたタイムスタンプを、見どころを探す手がかりに使います。無くても動きます(コメントを使わないだけ)"   # 9-2 の文そのまま
KEY_PROBE = "https://www.googleapis.com/youtube/v3/videos?part=id&id=dQw4w9WgXcQ&key="
KEY_TIMEOUT = 10
SAVE_FILE = "save-dir.json"
SAVE_DEFAULT = ("Videos", "受け取ったパック")
CASES_NAME = "作業"
DEVICES = {"A": "vulkan", "C": "cuda"}
CUTS = _spec.CUTS            # none・silence
CUT_DEFAULT = "none"         # A-8


class SettingsError(ValueError):
    """変えられない(文は画面にそのまま出す)"""


# ---------------------------------------------------------------- API キー
def clean_key(s):
    return str(s or "").strip().strip("\"' \t\r\n")


def looks_like_key(s):
    from ytt import apikey as _apikey
    return bool(_apikey.KEY_RE.match(s or ""))


def judge(status, body):
    """videos.list の返事 -> (使えるか, 文)(Settings.cs の YtKeyCheck.Judge と同じ読み)。status 0 = つながらなかった(body に理由)"""
    if status == 200:
        return True, "使えます"
    if status == 0:
        return False, "つながりませんでした(%s)" % (body or "ネットワーク")
    reason, text = "", ""
    try:
        err = (json.loads(body or "{}") or {}).get("error") or {}
        text = str(err.get("message") or "")
        errs = err.get("errors") or []
        reason = str((errs[0] or {}).get("reason") or "") if errs and isinstance(errs[0], dict) else ""
        reason = reason or str(err.get("status") or "")
    except (ValueError, AttributeError, TypeError):
        pass
    r = reason.lower()
    if r in ("keyinvalid", "api_key_invalid", "badrequest", "invalid_argument") or "api key not valid" in text.lower():
        return False, "キーが違います(貼り直してください。前後の空白も入らないように)"
    if r in ("accessnotconfigured", "service_disabled") or "has not been used" in text.lower():
        return False, "このキーのプロジェクトで「YouTube Data API v3」が有効になっていません"
    if r in ("quotaexceeded", "ratelimitexceeded", "resource_exhausted"):
        return False, "今日の使える数の上限に達しています(キーは正しい形です。明日また使えます)"
    if r in ("ipreferer_blocked", "iprefererblocked", "api_key_http_referrer_blocked", "api_key_ip_address_blocked", "api_target_blocked",
             "forbidden", "permission_denied"):
        return False, "このキーは使える場所や API が制限されています(「YouTube Data API v3」だけを許可し、場所の制限は外してください)"
    return False, "確かめられませんでした(HTTP %d%s)" % (status, ", " + reason if reason else "")


def probe_key(key):
    """videos.list を 1 回(接続先は固定)-> (status, body)。status 0 = つながらなかった"""
    try:
        with urllib.request.urlopen(KEY_PROBE + urllib.parse.quote(key, safe=""), timeout=KEY_TIMEOUT) as r:
            return r.status, r.read(200000).decode("utf-8", "replace")
    except urllib.error.HTTPError as e:
        try:
            return e.code, e.read(200000).decode("utf-8", "replace")
        except OSError:
            return e.code, ""
    except (urllib.error.URLError, OSError, ValueError) as e:
        return 0, e.__class__.__name__


def check_key(key, probe=probe_key):
    """-> (使えるか, 文)"""
    if not looks_like_key(key):
        return False, "キーの形が違います(英数字と - _ だけの 30〜40 字ほどです)"
    status, body = probe(key)
    return judge(status, body)


def keys_path(data_root):
    return os.path.join(data_root, "app", KEYS_NAME)


def load_key(data_root):
    d = _fsio.read_json_or(keys_path(data_root), {}, kind=dict)
    return clean_key(d.get(KEY_FIELD))


def save_key(data_root, key):
    """keys.json に書く(ほかの項目は残す)。空なら "" を書く(前のアプリのキーへ戻らない印)"""
    p = keys_path(data_root)
    d = _fsio.read_json_or(p, {}, kind=dict)
    d[KEY_FIELD] = key or ""
    _fsio.write_json(p, d, indent=None)


# ---------------------------------------------------------------- フォルダ
def check_folder(raw):
    """選んだフォルダ -> 絶対パス(作れて書ける・ドライブの直下でない)。違えば SettingsError"""
    s = str(raw or "").strip().strip('"')
    if not s or "\x00" in s or len(s) > 400 or not os.path.isabs(s):
        raise SettingsError("フォルダを選び直してください")
    s = os.path.abspath(s)
    if os.path.dirname(s) == s:
        raise SettingsError("ドライブの直下ではなく、その中のフォルダ(例: D:\\切り抜き)を選んでください")
    try:
        os.makedirs(s, exist_ok=True)
        with tempfile.NamedTemporaryFile(dir=s, prefix=".write-test-"):
            pass
    except OSError as e:
        raise SettingsError("そのフォルダは作れないか、書き込めません(%s)" % str(e.strerror or e)[:120])
    return s


def _studio_set_out_dir(d):
    """一時保管 = スタジオの書き出し先(実行中の書き出しは登録したときの場所のまま = 7-3 の移さない)"""
    try:
        _studio_env.set_out_dir(d, busy=lambda: False)
    except Exception as e:   # noqa: BLE001  (ytt/errors.ApiError: % の入った名前など)
        raise SettingsError(str(getattr(e, "message", "") or e))


class Settings:
    """⚙ の中身(server.py の口が呼ぶ)。places["cases"] を選び直したときに書き換える(受信箱・送る・ライブは places["cases"] をそのつど読む)。
    form = 送る欄の前回の値(api.Api。cut を持つ)・setup = 初回の取得の係・engine_fn = ② か None"""

    def __init__(self, places, api, setup=None, engine_fn=lambda: None, log=None, probe=probe_key, set_out_dir=_studio_set_out_dir,
                 machine_file=None, env=None):
        self.places, self.api, self.setup, self.engine_fn = places, api, setup, engine_fn
        self.log = log or (lambda msg: None)
        self.probe, self.set_out_dir = probe, set_out_dir
        self.machine_file = machine_file      # None = flow/machine.path()(作業データの根の machine.json)
        self.env = os.environ if env is None else env

    # ---- 読む
    def save_default(self):
        return os.path.join(self.env.get("USERPROFILE") or os.path.expanduser("~"), *SAVE_DEFAULT)

    def cases_default(self):
        return os.path.join(self.places.get("home") or os.path.dirname(self.places["data"]), CASES_NAME)

    def _machine(self):
        try:
            return _machine.load(p=self.machine_file)
        except (OSError, ValueError):
            return {"device": "vulkan", "diskMinGB": _machine.DISK_MIN_GB, "caseRoot": None}

    def view(self):
        m = self._machine()
        save = self.places["save"]()
        cases = self.places["cases"]
        gpu = None
        eng = self.engine_fn()
        ms = getattr(getattr(eng, "queue", None), "machine_status", None)
        if callable(ms):
            try:
                g = (ms() or {}).get("gpu")
                gpu = {"name": str(g.get("name") or "")[:80], "vramGB": g.get("vramGB")} if isinstance(g, dict) and g.get("name") else None
            except Exception:   # noqa: BLE001  (GPU を調べられなくても ⚙ は出す)
                gpu = None
        return {"saveDir": save, "saveIsDefault": os.path.normcase(save) == os.path.normcase(self.save_default()),
                "caseRoot": cases, "caseIsDefault": os.path.normcase(os.path.abspath(cases)) == os.path.normcase(os.path.abspath(self.cases_default())),
                "engine": "C" if m.get("device") == "cuda" else "A", "gpu": gpu,
                "apiKey": bool(load_key(self.places["data"]) or self.env.get(KEY_ENV)), "apiKeyHelp": KEY_HELP,
                "diskMinGB": m.get("diskMinGB"), "cut": self.api.form().get("cut", CUT_DEFAULT)}

    # ---- フォルダ
    def set_folder(self, what, raw):
        """[選ぶ] で選んだフォルダ(what = save・cases)を保存 -> 文"""
        if what not in ("save", "cases"):
            raise SettingsError("変えられる場所ではありません")
        d = check_folder(raw)
        if what == "save":
            _fsio.write_json(os.path.join(self.places["friend"], SAVE_FILE), {"dir": d}, indent=None)
            self.log("受け取るの保存先を変えました: %s" % d)
            return "受け取るの保存先を変えました。これから受け取る物はここに置きます(今ある物は移しません)"
        self.set_out_dir(d)
        _machine.save({"caseRoot": d}, p=self.machine_file)
        self.places["cases"] = d
        self.log("一時保管を変えました: %s" % d)
        return "一時保管を変えました。新しい物からここに作ります(今ある物は移さず、片付けを待ちます)"

    def reset_folder(self, what):
        """既定に戻す"""
        if what == "save":
            _fsio.unlink_quiet(os.path.join(self.places["friend"], SAVE_FILE))
            return "受け取るの保存先を既定(%s)に戻しました" % self.save_default()
        if what == "cases":
            self.set_folder("cases", self.cases_default())
            return "一時保管を既定(アプリのフォルダの 作業)に戻しました。新しい物からここに作ります"
        raise SettingsError("変えられる場所ではありません")

    # ---- エンジン・空き容量・カット
    def update(self, body):
        """{engine?: A|C, diskMinGB?: 数, cut?: none|silence} -> {"message", "fetching"}。合わなければ SettingsError(どれも書かない)"""
        patch, msgs, cut, fetching = {}, [], None, False
        if "engine" in body:
            if body["engine"] not in DEVICES:
                raise SettingsError("エンジンは A か C を選んでください")
            patch["device"] = DEVICES[body["engine"]]
        if "diskMinGB" in body:
            try:
                patch["diskMinGB"] = _machine.check("diskMinGB", body["diskMinGB"])
            except ValueError:
                raise SettingsError("空き容量の下限は 0〜%d の数(GB)で入れてください" % _machine.DISK_MAX_GB)
        if "cut" in body:
            if body["cut"] not in CUTS:
                raise SettingsError("カットは「しない」か「無音を削る」を選んでください")
            cut = body["cut"]
        if patch:
            _machine.save(patch, p=self.machine_file)
        if cut is not None:
            self.api.set_cut(cut)
            msgs.append("カットの既定を「%s」にしました(次に送る物から)" % ("無音を削る" if cut == "silence" else "しない"))
        if "diskMinGB" in patch:
            self._live_floor(patch["diskMinGB"])
            msgs.append("空き容量の下限を %s GB にしました" % patch["diskMinGB"])
        if "device" in patch:
            c = patch["device"] == "cuda"
            msgs.append("C(CUDA)にしました。次の処理から使います" if c else "A(Vulkan)にしました。次の処理から使います")
            if c:
                fetching, why = self._fetch_cuda()
                if fetching:
                    msgs.append("足りない部品を取ってきます(進み具合は受信箱の上の「初回の準備」)")
                elif why:
                    msgs.append(why)
        self.log("⚙: %s" % "・".join(msgs))
        return {"message": "。".join(m.rstrip("。") for m in msgs) if msgs else "変えるものがありません", "fetching": fetching}

    def _live_floor(self, gb):
        """録画の空き容量の下限もすぐ変える(ライブ係は起こしたときに読むので)"""
        live = getattr(self.engine_fn(), "live", None)
        if live is not None and hasattr(live, "disk_min_gb"):
            live.disk_min_gb = gb

    def _fetch_cuda(self):
        """エンジン C の部品(CUDA 版の whisper.cpp)が足りなければ取り始める -> (始めたか, 始められない理由)"""
        st = self.setup
        if st is None or not st.checked:
            return False, ""
        try:
            miss = [i["name"] for i in st.missing() if i["unzip"] == "wcpp"]
        except Exception:   # noqa: BLE001
            return False, ""
        if not miss:
            return False, ""
        if st.running():
            return False, "部品を取っている途中です。取り終えたあと、受信箱の上の「初回の準備」から C の部品も取れます"
        try:
            st.start(only=set(miss))
            return True, ""
        except ValueError as e:
            return False, "C の部品を取れません: %s" % e

    # ---- API キー
    def set_key(self, raw):
        """貼ったキーを確かめて保存 -> (使えるか, 文)。空なら消す"""
        key = clean_key(raw)
        if not key:
            save_key(self.places["data"], "")
            self.env.pop(KEY_ENV, None)
            self.log("API キーを消しました")
            return True, "消しました"
        ok, msg = check_key(key, self.probe)
        if not ok:
            return False, msg
        save_key(self.places["data"], key)
        self.env[KEY_ENV] = key
        self.log("API キーを保存しました")
        return True, msg + "(保存しました)"
