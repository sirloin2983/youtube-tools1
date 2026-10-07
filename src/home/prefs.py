"""ホームの設定(画面の直し「気が利く画面へ」の土台。docs/design/briefs/ux-consistency/REQUEST.md の 1)。

どの入口から変えても全部の入口の既定になる値を、ホームの作業データの prefs.json に1つだけ持つ:
  autorun  … まとめて実行の形・採用数・カットの方法・上書き・失敗したとき
  streamer … 配信者(字幕の色)の記憶: 文書 id / 配信(video id)/ チャンネル → 名前(空 = 「色なし」を覚えた)
  keymap   … 共通の再生キーの割り当て(編集・スタジオで同じ)
  intake   … 友人からの依頼の受付(src/home/intake.py。docs/spec/friend-intake.md): 見張るフォルダ・オン/オフ・既定の切り抜く数・上限
  backup   … 作業データのバックアップ(src/home/backup.py。docs/spec/data-location.md): オン/オフ・写す先のフォルダ・間隔(時間)
  accuracy … 精度の自動測定(src/home/accuracy.py。git の履歴(679ff01 以前)の docs/plan/q3-q4-design.md の (a)): enabled(**既定オン**。読むだけで軽い)・夜の窓 nightFrom〜nightTo(時。既定 1〜6。from > to は日をまたぐ)
  live     … リアルタイム切り抜き(線 D。src/home/live.py。**既定はオフ**): enabled・録画の置き場所 folder(空 = 録画の部品の前回の設定か既定 E:\Video\live-rec)・
             録画元の一覧 recorders(空 = 手元の1つ。[{id, name, url, token}]。token が空の手元の録画元は録画の部品の token.txt を読む)・
             録画の画質 quality(best|1080p|720p。既定 1080p。スタジオの URL の欄から始める録画 = POST /live/api/begin)・
             配信が終わったら自動で本番版に作り直す autoArchive(**既定オン**。src/home/live_archive.py。P4)・
             本番版に入れ替えたら録画を消す(マークの無い録画は 1 日で・退避した速報版は 7 日で)autoDelete(**既定オン**。src/home/live_cleanup.py。P4)・
             書き出したあとの自動の流れ auto {after: none|check|auto(既定 check)・cut: ""(ホームの autorun.cut)|none|silence・
             engine: ""(編集の設定)|faster-whisper|whisper.cpp|qwen3-asr|llama.cpp・model: ""(編集の設定)|モデルの名前}(線 D の M2。入口 0.39.0)。
             after は画面・API が書き出したあとを指定しないとき(POST /live/api/adopt など)の既定。cut・engine・model は書き出しを頼んだときに覚えてまとめて実行へ渡す・
             配信が終わったらアーカイブの解析で自動で切り抜いてパックまで作る autoAfterStream(**既定オフ**。線 D の M7。入口 0.40.0。src/home/live_archive.py)と
             その数 afterStreamPerHour(1 時間あたり。1〜30。既定 6)・
             配信中の盛り上がりの検出 detect {enabled(**既定オフ**), sens: high|normal|low(既定 normal), perHour: 1〜30(1 時間の候補の枠。既定 6)}
             (線 D の L2。src/home/live_detect.py・live_excite_worker.py)と、その候補の自動の採用 autoAdopt {enabled(**既定オフ**), waitMin: 1〜60(確定から待つ分。既定 5)}
             (M11)。どちらも節の中の鍵ごとに直す(送らなかった鍵は今のまま)
  hidden   … 一覧で非表示にした項目(2026-10-04): 一覧の名前(HIDE_LISTS)→ {項目の id: 非表示にした時刻(ms)}。
             画面の UIKit.hide が op "hide" で1件ずつ足す・外す(節ごと送ると、窓を2つ並べたときに相手の分を消すため)。データは消さない(表示だけ)
画面は api/ytt/prefs(入口の launch.py)で読み書きする。**節ごとに直す**(全体を上書きしない。窓を2つ並べたとき、後から送った側が他の節を消さないため)。
値は許可した形だけ受け付け、知らないキーは捨てる。壊れたファイルは読まずに既定で動き、次に書くときに退避してから書き直す。
"""
import json
import os
import re
import threading
import time

MAX_BYTES = 1024 * 1024   # 2026-10-04 に 256KB から(非表示の一覧の分)
MAX_REMEMBER = 2000        # 配信者の記憶は種類ごとにこの件数まで(古い順に捨てる)
NAME_MAX = 60
KEY_MAX = 120
SECTIONS = ("autorun", "streamer", "keymap", "intake", "backup", "hidden", "live", "accuracy")
PATCHABLE = ("autorun", "keymap", "intake", "backup", "live", "accuracy")
AUTORUN_MODES = ("full", "adopted", "transcribe")      # src/home/autorun.py の MODES と同じ名前
CUT_METHODS = ("rows", "none", "silence")
ON_FAIL = ("next", "stop")
STREAMER_KINDS = ("docs", "videos", "channels")
# 非表示にできる一覧(UIKit.hide の list と同じ名前): 案件(ホーム。配信の id)・次にやること(ホーム。"<種類>:<id>")・
# 文字起こし(編集の履歴・ホームの単体の文字起こし。文書の id)・配信(スタジオ ③ の配信の一覧。配信の id)・届いた依頼・まとめて実行の記録
HIDE_LISTS = ("cases", "todo", "transcripts", "videos", "intake", "runs")
HIDE_MAX = 2000            # 一覧ごとにこの件数まで(古い順に捨てる = 古い項目がまた見えるだけで、データは消えない)
HIDE_IDS_MAX = 200         # 1回で送れる数
COMBO_RE = re.compile(r"^(?:Shift\+)?(?:[^\x00-\x1f\x7f]|[A-Z][A-Za-z0-9]{1,20})$")   # UIKit.keys.comboOf の表記(Shift+ と、1文字かキーの名前)
ACTION_RE = re.compile(r"^[A-Za-z][A-Za-z0-9_.-]{0,40}$")
DEFAULTS = {"autorun": {"mode": None, "top": 3, "cut": "none", "friendLength": True,   # 既定はカットしない(2026-10-01 ユーザー決定)
                         "overwrite": False, "onFail": "next"},
            "streamer": {k: {} for k in STREAMER_KINDS},
            "keymap": {"playback": {}},
            "intake": {"enabled": False, "folder": "", "top": 3, "dailyMax": 5, "maxHours": 8, "maxGB": 20, "interval": 30},
            "backup": {"enabled": False, "folder": "", "everyHours": 1},
            "hidden": {k: {} for k in HIDE_LISTS},
            "live": {"enabled": False, "folder": "", "recorders": [], "quality": "1080p", "autoArchive": True, "autoDelete": True,
                     "auto": {"after": "check", "cut": "", "engine": "", "model": ""}, "autoAfterStream": False, "afterStreamPerHour": 6,
                     "detect": {"enabled": False, "sens": "normal", "perHour": 6}, "autoAdopt": {"enabled": False, "waitMin": 5}},
            "accuracy": {"enabled": True, "nightFrom": 1, "nightTo": 6}}
INTAKE_RANGES = {"top": (1, 10, "既定の切り抜く数"), "dailyMax": (1, 50, "1日の上限"), "maxHours": (1, 24, "配信の長さの上限(時間)"),
                 "maxGB": (1, 200, "動画の大きさの上限(GB)"), "interval": (10, 600, "見る間隔(秒)")}
FOLDER_MAX = 260
RECORDERS_MAX = 8
RECORDER_ID_RE = re.compile(r"^[a-z][a-z0-9-]{0,15}\Z")
RECORDER_URL_RE = re.compile(r"^http://[A-Za-z0-9.\-]{1,100}:\d{2,5}\Z")   # 2台(P5)は LAN の http(合言葉つき)。パス・利用者名は付けさせない
RECORDER_TOKEN_RE = re.compile(r"^[A-Za-z0-9_-]{20,128}\Z")
LIVE_QUALITIES = ("best", "1080p", "720p")   # 録画の画質(src/recorder/rec_core.py の QUALITIES と同じ名前。既定 1080p = DEFAULT_QUALITY)
LIVE_AFTERS = ("none", "check", "auto")      # 書き出したあと(src/home/live_export.py の AFTERS と同じ名前)
LIVE_CUTS = ("", "none", "silence")          # 自動のパックのカット(src/home/autorun.py の CUTS。"" = ホームの autorun.cut)
LIVE_ENGINES = ("", "faster-whisper", "whisper.cpp", "qwen3-asr", "llama.cpp")   # 認識エンジン(src/editor/tx_engines.py の ENGINES の id。"" = 編集の設定。editor は読み込まない)
LIVE_MODEL_RE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._-]{0,59}\Z")   # モデルの名前(large-v3・small など。"" = 編集の設定)
LIVE_PER_HOUR = (1, 30)                      # 配信後の全自動(M7)の 1 時間あたりの数(上限はスタジオの解析の候補の数の上限 30)
LIVE_SENS = ("high", "normal", "low")        # 配信中の検出の感度(src/ytt_core/excite.py の SENS の名前)
LIVE_WAIT_MIN = (1, 60)                      # 自動の採用(M11)の、確定から待つ分


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
    if "friendLength" in v:   # 友人の依頼の自動の候補に、友人の区間の長さの実績を使う(autorun._friend_length。false で止める)
        out["friendLength"] = v["friendLength"] is not False
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
    """作業データのバックアップの設定(src/home/backup.py)。写す先が作業データの中でないか・ドライブがあるかは、写すときに確かめて画面に出す(ここでは形だけ)"""
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


def _clean_accuracy(v, cur):
    """精度の自動測定の設定(src/home/accuracy.py)。夜の窓は時(開始 0〜23・終わり 1〜24。0 → 24 は一日中)。開始と終わりが同じだと窓が無いので断る(日をまたぐ 22 → 6 は可)"""
    out = dict(cur)
    if "enabled" in v:
        out["enabled"] = v["enabled"] is True
    for k, lo, hi, label in (("nightFrom", 0, 23, "夜の窓の開始(時)"), ("nightTo", 1, 24, "夜の窓の終わり(時)")):
        if k in v:
            x = v[k]
            if isinstance(x, bool) or not isinstance(x, int) or not lo <= x <= hi:
                raise PrefsError("%sは %d〜%d の整数で指定してください" % (label, lo, hi))
            out[k] = x
    if out["nightFrom"] == out["nightTo"]:
        raise PrefsError("夜の窓の開始と終わりは違う時刻にしてください")
    return out


def _clean_live(v, cur):
    """リアルタイム切り抜きの設定(src/home/live.py)。置き場所のドライブがあるかは録画の部品が確かめて画面に出す(ここでは形だけ)。
    録画元の合言葉は、送られなかった(空)ときは同じ id の今の値を残す(画面には合言葉を返さないため)"""
    out = {"enabled": cur.get("enabled") is True, "folder": cur.get("folder") or "", "recorders": [dict(r) for r in cur.get("recorders") or []],
           "quality": cur.get("quality") if cur.get("quality") in LIVE_QUALITIES else DEFAULTS["live"]["quality"],
           "autoArchive": cur.get("autoArchive") is not False, "autoDelete": cur.get("autoDelete", DEFAULTS["live"]["autoDelete"]) is True,   # 消すのは明示的に true のときだけ
           "auto": _clean_live_auto(cur.get("auto") if isinstance(cur.get("auto"), dict) else {}, DEFAULTS["live"]["auto"], strict=False),
           "autoAfterStream": cur.get("autoAfterStream") is True,   # 自動で採用するのは明示的に true のときだけ(既定オフ)
           "afterStreamPerHour": cur.get("afterStreamPerHour") if _per_hour_ok(cur.get("afterStreamPerHour")) else DEFAULTS["live"]["afterStreamPerHour"],
           "detect": _clean_live_detect(cur.get("detect") if isinstance(cur.get("detect"), dict) else {}, DEFAULTS["live"]["detect"], strict=False),
           "autoAdopt": _clean_live_adopt(cur.get("autoAdopt") if isinstance(cur.get("autoAdopt"), dict) else {}, DEFAULTS["live"]["autoAdopt"], strict=False)}
    for k, fn, label in (("detect", _clean_live_detect, "配信中の候補の設定(detect)"), ("autoAdopt", _clean_live_adopt, "自動の採用の設定(autoAdopt)")):
        if k in v:   # 線 D の L2・M11。節の中の鍵ごとに直す
            if not isinstance(v[k], dict):
                raise PrefsError("%sの形が正しくありません" % label)
            out[k] = fn(v[k], out[k])
    if "auto" in v:   # 書き出したあとの自動の流れ(M2)。節の中の鍵ごとに直す(送らなかった鍵は今のまま)
        if not isinstance(v["auto"], dict):
            raise PrefsError("書き出したあとの設定(auto)の形が正しくありません")
        out["auto"] = _clean_live_auto(v["auto"], out["auto"])
    if "enabled" in v:
        out["enabled"] = v["enabled"] is True
    if "folder" in v:
        out["folder"] = _clean_folder(v["folder"])
    if "quality" in v:   # 録画の画質(スタジオの URL の欄から始めた録画。POST /live/api/begin)
        if v["quality"] not in LIVE_QUALITIES:
            raise PrefsError("録画の画質は %s のどれかにしてください" % "・".join(LIVE_QUALITIES))
        out["quality"] = v["quality"]
    if "autoArchive" in v:   # 配信が終わったら自動で本番版に作り直す(P4)
        if not isinstance(v["autoArchive"], bool):
            raise PrefsError("「自動で本番版に作り直す」は true か false で指定してください")
        out["autoArchive"] = v["autoArchive"]
    if "autoAfterStream" in v:   # 配信が終わったらアーカイブの解析で自動で切り抜く(M7)
        if not isinstance(v["autoAfterStream"], bool):
            raise PrefsError("「配信後に自動で切り抜く」は true か false で指定してください")
        out["autoAfterStream"] = v["autoAfterStream"]
    if "afterStreamPerHour" in v:
        if not _per_hour_ok(v["afterStreamPerHour"]):
            raise PrefsError("1 時間あたりの数は %d〜%d の整数で指定してください" % LIVE_PER_HOUR)
        out["afterStreamPerHour"] = v["afterStreamPerHour"]
    if "autoDelete" in v:   # 本番版に入れ替えたら録画を消す・マークの無い録画は 1 日で消す(P4。src/home/live_cleanup.py)
        if not isinstance(v["autoDelete"], bool):
            raise PrefsError("「録画を消す」は true か false で指定してください")
        out["autoDelete"] = v["autoDelete"]
    if "recorders" in v:
        rs = v["recorders"]
        if not isinstance(rs, list) or len(rs) > RECORDERS_MAX:
            raise PrefsError("録画元の一覧の形が正しくありません(%d まで)" % RECORDERS_MAX)
        old = {r.get("id"): r for r in out["recorders"]}
        clean, ids = [], set()
        for r in rs:
            if not isinstance(r, dict):
                raise PrefsError("録画元の一覧の形が正しくありません")
            rid, url, token = r.get("id"), r.get("url"), r.get("token") or ""
            if not isinstance(rid, str) or not RECORDER_ID_RE.match(rid) or rid in ids:
                raise PrefsError("録画元の id は英小文字で始まる 16 字までで、重ならないようにしてください")
            if not isinstance(url, str) or not RECORDER_URL_RE.match(url) or not 1024 <= int(url.rsplit(":", 1)[1]) <= 65535:
                raise PrefsError("録画元の URL は http://<名前か IP>:<ポート> で指定してください")
            if not isinstance(token, str) or (token and not RECORDER_TOKEN_RE.match(token)):
                raise PrefsError("録画元の合言葉の形が正しくありません")
            if not token and (old.get(rid) or {}).get("url") == url:   # URL を変えたら前の合言葉は使わない(別の相手へ送らない)
                token = (old.get(rid) or {}).get("token") or ""
            ids.add(rid)
            clean.append({"id": rid, "name": _clean_name(r.get("name") or rid) or rid, "url": url, "token": token})
        out["recorders"] = clean
    return out


def _per_hour_ok(x):
    return isinstance(x, int) and not isinstance(x, bool) and LIVE_PER_HOUR[0] <= x <= LIVE_PER_HOUR[1]


def _clean_keys(v, cur, defaults, checks, strict):
    """live の中の小さな節(auto・detect・autoAdopt)を鍵ごとに直す。checks: {鍵: (よいか, 断る文)}。
    strict=False は保存してある値を読むとき(形の違う鍵は既定に戻す。断らない)。今の値が壊れていたら既定に戻す"""
    out = {k: cur.get(k, defaults[k]) for k in defaults}
    for k, (ok, msg) in checks.items():
        if k in v:
            if ok(v[k]):
                out[k] = v[k]
            elif strict:
                raise PrefsError(msg)
    for k, (ok, _msg) in checks.items():
        if not ok(out[k]):
            out[k] = defaults[k]
    return out


def _int_in(x, lo, hi):
    return isinstance(x, int) and not isinstance(x, bool) and lo <= x <= hi


def _clean_live_detect(v, cur, strict=True):
    """live.detect(線 D の L2。配信中の盛り上がりの検出)"""
    return _clean_keys(v, cur, DEFAULTS["live"]["detect"], {
        "enabled": (lambda x: isinstance(x, bool), "「配信中の候補」は true か false で指定してください"),
        "sens": (lambda x: x in LIVE_SENS, "感度(sens)は high・normal・low のどれかにしてください"),
        "perHour": (lambda x: _int_in(x, *LIVE_PER_HOUR), "1 時間の候補の数(perHour)は %d〜%d の整数で指定してください" % LIVE_PER_HOUR)}, strict)


def _clean_live_adopt(v, cur, strict=True):
    """live.autoAdopt(線 D の M11。候補の自動の採用)"""
    return _clean_keys(v, cur, DEFAULTS["live"]["autoAdopt"], {
        "enabled": (lambda x: isinstance(x, bool), "「候補を自動で採用する」は true か false で指定してください"),
        "waitMin": (lambda x: _int_in(x, *LIVE_WAIT_MIN), "待つ分(waitMin)は %d〜%d の整数で指定してください" % LIVE_WAIT_MIN)}, strict)


def _clean_live_auto(v, cur, strict=True):
    """live.auto(M2)。strict=False は保存してある値を読むとき(形の違う鍵は既定に戻す。断らない)"""
    checks = {"after": (lambda x: x in LIVE_AFTERS, "書き出したあと(after)は none・check・auto のどれかにしてください"),
              "cut": (lambda x: x in LIVE_CUTS, "カット(cut)は 空(ホームの設定)・none・silence のどれかにしてください"),
              "engine": (lambda x: x in LIVE_ENGINES, "認識エンジン(engine)は 空(編集の設定)・%s のどれかにしてください" % "・".join(LIVE_ENGINES[1:])),
              "model": (lambda x: isinstance(x, str) and (x == "" or bool(LIVE_MODEL_RE.match(x))), "モデル(model)は英数字と . _ - の 60 字までにしてください(空 = 編集の設定)")}
    return _clean_keys(v, cur, DEFAULTS["live"]["auto"], checks, strict)


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


def _read_hidden(v):
    out = {}
    for k in HIDE_LISTS:
        d = v.get(k) if isinstance(v, dict) else None
        out[k] = {str(a)[:KEY_MAX]: int(b) for a, b in (d.items() if isinstance(d, dict) else [])
                  if isinstance(b, (int, float)) and not isinstance(b, bool)}
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
        if name == "accuracy":
            try:
                return _clean_accuracy(v if isinstance(v, dict) else {}, DEFAULTS["accuracy"])
            except PrefsError:
                return dict(DEFAULTS["accuracy"])
        if name == "keymap":
            try:
                return _clean_keymap(v if isinstance(v, dict) else {}, DEFAULTS["keymap"])
            except PrefsError:
                return {"playback": {}}
        if name == "hidden":
            return _read_hidden(v)
        if name == "live":
            try:
                return _clean_live(v if isinstance(v, dict) else {}, DEFAULTS["live"])
            except PrefsError:
                return dict(DEFAULTS["live"], recorders=[], auto=dict(DEFAULTS["live"]["auto"]), detect=dict(DEFAULTS["live"]["detect"]),
                            autoAdopt=dict(DEFAULTS["live"]["autoAdopt"]))
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
            new = {"autorun": _clean_autorun, "keymap": _clean_keymap, "intake": _clean_intake, "backup": _clean_backup,
                   "live": _clean_live, "accuracy": _clean_accuracy}[section](value, cur)
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

    def hide(self, lst, ids, hidden=True):
        """一覧 lst の項目 ids を非表示にする(hidden=False で表示に戻す)。-> その一覧の {id: 時刻}。
        同じ id はつけ直すと新しい方へ動かし、HIDE_MAX を超えたら古い順に捨てる"""
        if lst not in HIDE_LISTS:
            raise PrefsError("非表示にできない一覧です: %s" % str(lst)[:40])
        if isinstance(ids, str):
            ids = [ids]
        if not isinstance(ids, list) or not ids or len(ids) > HIDE_IDS_MAX:
            raise PrefsError("非表示にする項目の指定が正しくありません")
        for i in ids:
            if not isinstance(i, str) or not i.strip() or len(i) > KEY_MAX or any(ord(ch) < 32 for ch in i):
                raise PrefsError("非表示にする項目の指定が正しくありません")
        now = int(time.time() * 1000)
        with self.lock:
            d, broken = self._load()
            hd = _read_hidden(d.get("hidden"))
            m = hd[lst]
            for i in ids:
                m.pop(i, None)
                if hidden is not False:
                    m[i] = now
            while len(m) > HIDE_MAX:
                m.pop(next(iter(m)))
            d["hidden"] = hd
            self._save(d, broken)
            return m
