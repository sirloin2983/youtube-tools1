"""鍵の置き場(11-07 ユーザー OK「よい」: 鍵とログインは別に持つ。鍵の置き場 = 入口の作業データの app\\secrets)。

- 設定のファイル(analytics/config.json・live/excite/config.json など)には鍵の名前だけを書き、値はここ <app>/secrets/keys.json
  ({"v": 1, "keys": {名前: 値}})に置く。ログインの cookie(secrets/youtube-cookies.txt = app/ytlogin)とは別のファイル
- 値はログ・画面・例外の文に出さない(このモジュールの例外の文にも名前しか入れない)
- 名前は英小文字・数字・. _ - だけ(例 analytics.secret・live.recorder.local)
"""
import json
import os
import re

from . import fsio

DIR_NAME = "secrets"
FILE_NAME = "keys.json"
NAME_RE = re.compile(r"^[a-z0-9][a-z0-9._-]{0,63}$")
MAX_BYTES = 256 * 1024


def path_for(app_dir):
    """入口の作業データ(app)のフォルダ -> 鍵の置き場のファイル"""
    return os.path.join(app_dir, DIR_NAME, FILE_NAME)


def beside(tool_dir):
    """ほかのツールの作業データ(<root>/<ツール>)から、同じ親の入口の鍵の置き場(<root>/app/secrets/keys.json)"""
    return path_for(os.path.join(os.path.dirname(os.path.abspath(tool_dir)), "app"))


def check_name(name):
    if not isinstance(name, str) or not NAME_RE.match(name):
        raise ValueError("鍵の名前が正しくありません")
    return name


def _load(path):
    d = fsio.read_json_or(path, None, MAX_BYTES, kind=dict) if path else None
    keys = (d or {}).get("keys")
    return {k: v for k, v in keys.items() if isinstance(k, str) and isinstance(v, str)} if isinstance(keys, dict) else {}


def get(path, name):
    """鍵の値(無ければ "")"""
    if not path or not isinstance(name, str) or not NAME_RE.match(name):
        return ""
    return _load(path).get(name, "")


def has(path, name):
    return bool(get(path, name))


def put(path, name, value):
    """鍵を書く(空なら消す)。値が今と同じなら書かない -> 書いたか"""
    check_name(name)
    if not isinstance(value, str):
        raise ValueError("鍵の値は文字列だけです")
    keys = _load(path)
    if keys.get(name, "") == value:
        return False
    if value:
        keys[name] = value
    else:
        keys.pop(name, None)
    os.makedirs(os.path.dirname(path), exist_ok=True)
    fsio.atomic_write(path, json.dumps({"v": 1, "keys": keys}, ensure_ascii=False, indent=1).encode("utf-8"))
    return True


def stamp(path):
    """鍵の置き場が変わったかを見る印(更新の時刻と大きさ。値は含まない)。無ければ None"""
    try:
        st = os.stat(path)
    except OSError:
        return None
    return [st.st_mtime_ns, st.st_size]
