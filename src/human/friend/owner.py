# -*- coding: utf-8 -*-
"""③ 人の層: 受付のフォルダの持ち主(今の道具か、新しい道具 friend-requests か)を決める 1 か所(根っこの直しの段 8 = 横2。
notes:道具の作り直し/友人の依頼の処理/原因の分析/根っこの直しの計画-11-19.md の段 8)。

持ち主の正は、新しい道具の settings.json の intakeDir 1 つ。新しい道具の入口が動いているか(host.lock)・今の道具のホームの
スイッチ(intake.enabled)では決めない(ロックは「動いているか」の印で、持ち主の印ではない)。
- owner(folder): settings.json を 4 つの答えで読む。無い(新しい道具を入れていない PC)= OLD(今の道具が持ち主)。
  中身があって intakeDir が folder と同じ = NEW。今は読めない(ほかのプロセスが掴んでいる・権限)= BUSY。壊れている = BROKEN。
  BUSY と BROKEN は「読まない側」に倒す(2 つの道具が同じ依頼を作って 2 組届けるより、待つ方が戻しやすい)= owner_is_new が真。
- 今の道具の、友人へ物を置く道は、どれも owner_is_new を通す: 依頼を読む(intake)・自分の配信の自動の切り抜き(app/live)・
  引き継ぎ(bugs._takeover)・友人のアプリを配る道具(dev/build_friend_zip.py と配る回 pubqueue)。
- 依頼ごとに「どちらが受けたか」は、新しい道具の records\\<依頼 id>\\ の有る無しで見る(taken_by_new)。不具合の AI への指示が使う。
- 見張り: 新しい道具の入口が動いているかは host_running(locks\\host.lock をほかのプロセスが持っているか)。
  ロックは取らずに、頭の 1 バイトを読めるかで見る(ytt.fsio.is_locked)。試しに取ると、ちょうど起きた入口が「二重の入口」で終わるため。
- 自分の配信を新しい道具へ依頼として渡す(hand_over_live。決めたこと 41): 受付のフォルダの直下に、友人のアプリと同じ形の
  ライブの依頼の JSON <依頼 id>.request.json を置く(書きかけは頭が「.」の名前 = 新しい道具の受付は見ない)。
  新しい道具が録画・検出・届けをする(届け元は 1 つ。友人が同じ配信を頼んだ時は、新しい道具の「同じ配信の断り」が 1 つにする)。
置き場の決め方と settings.json の読み方は、新しい道具の fr/settings.py(data_dir・_path)と同じ順にする(--data は見ない)。
"""
import os
import re
import time

from ytt import fsio

NEW_HOST_ENV, NEW_HOST_DIR_NAME = "FR_DATA", "friend-requests-data"
SETTINGS = "settings.json"
SETTINGS_MAX = 256 * 1024
HOST_LOCK = ("locks", "host.lock")
RECORDS = "records"
REQ_SUFFIX = ".request.json"
RID_RE = re.compile(r"^\d{8}-\d{6}-[0-9a-f]{6}\Z")   # 新しい道具の依頼 id(fr/flow/request.REQUEST_ID)
OLD, NEW, BUSY, BROKEN = "old", "new", "busy", "broken"


def new_host_dir(environ=None):
    """新しい道具の記録の置き場(環境変数 FR_DATA → USERPROFILE の下の friend-requests-data。新しい道具の settings.data_dir と同じ順)"""
    environ = os.environ if environ is None else environ
    v = str(environ.get(NEW_HOST_ENV) or "").strip()
    if v:
        return os.path.abspath(v)
    return os.path.abspath(os.path.join(environ.get("USERPROFILE") or os.path.expanduser("~"), NEW_HOST_DIR_NAME))


def owner(folder, base=None):
    """受付のフォルダ folder の持ち主 -> OLD・NEW・BUSY・BROKEN(上の説明)。folder が空なら OLD(読む物が無い)"""
    if not folder:
        return OLD
    base = base or new_host_dir()
    try:
        raw = fsio.read_json_file(os.path.join(base, SETTINGS), SETTINGS_MAX)
    except FileNotFoundError:
        return OLD
    except (ValueError, UnicodeDecodeError, RecursionError):   # 形の崩れ・大きすぎる(TooLarge は ValueError)
        return BROKEN
    except OSError:   # 掴まれている・権限・置き場がフォルダでない
        return BUSY
    if not isinstance(raw, dict):
        return BROKEN
    v = raw.get("intakeDir")
    if v is None or v == "":
        return OLD
    if not isinstance(v, str):
        return BROKEN   # 新しい道具も読めない(SettingsError)= 入口が起きない。読まない側に倒す
    theirs = os.path.abspath(os.path.join(base, os.path.expandvars(v)))   # 新しい道具の settings._path と同じ読み方(相対なら置き場から)
    return NEW if _same_dir(theirs, folder) else OLD


def owner_is_new(folder, base=None):
    """今の道具が folder へ物を置いてはいけないか(持ち主が新しい道具・分からない)"""
    return owner(folder, base) != OLD


def taken_by_new(rid, base=None):
    """依頼 id rid を新しい道具が受けたか(その records\\<依頼 id>\\ がある)"""
    if not isinstance(rid, str) or not RID_RE.match(rid):
        return False
    return os.path.isdir(os.path.join(base or new_host_dir(), RECORDS, rid))


def host_running(base=None):
    """新しい道具の入口が動いているか(入口のロックをほかのプロセスが持っている)"""
    return fsio.is_locked(os.path.join(base or new_host_dir(), *HOST_LOCK))


def live_request(rid, url, sent_at=None):
    """新しい道具へ渡すライブの依頼の JSON(友人のアプリの request_doc の kind live と同じ鍵。新しい道具が読むのは v・kind・id・url ほか。
    ライブの値は新しい道具が固定の値を使う)"""
    t = time.localtime(time.time() if sent_at is None else sent_at)
    iso = time.strftime("%Y-%m-%dT%H:%M:%S", t) + _offset(t)
    return {"v": 1, "kind": "live", "id": rid, "flow": "auto", "url": url, "streamer": "", "videoTracks": 1, "cut": "none", "sentAt": iso}


def hand_over_live(folder, rid, url, sent_at=None):
    """自分の配信を新しい道具へライブの依頼として渡す: folder の直下に <依頼 id>.request.json を置く -> 置いたパス。置けなければ OSError"""
    path = os.path.join(folder, rid + REQ_SUFFIX)
    fsio.write_json(path, live_request(rid, url, sent_at), indent=None)   # 書きかけは .tmp-*.part(頭が「.」= 新しい道具の受付は見ない)
    return path


def _offset(t):
    off = -(time.altzone if t.tm_isdst > 0 and time.daylight else time.timezone)
    return "%s%02d:%02d" % ("+" if off >= 0 else "-", abs(off) // 3600, abs(off) % 3600 // 60)


def _same_dir(a, b):
    if os.path.normcase(os.path.normpath(os.path.abspath(a))) == os.path.normcase(os.path.normpath(os.path.abspath(b))):
        return True
    if fsio.is_network_path(a) or fsio.is_network_path(b):
        return False
    try:
        return os.path.samefile(a, b)
    except OSError:
        return False
