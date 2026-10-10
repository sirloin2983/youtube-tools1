"""YouTube Data API のキー(役割で組み直す RS3-4。2026-10-10 にスタジオの common.py から移した)。

キーは環境変数 YOUTUBE_API_KEY が優先、無ければスタジオのデータの置き場所の config.json(`{"apiKey": …}`。コミットしない・0600 で書く)。
使う所: スタジオの ① 探す(rank)・② の動画のコメント欄(analyze)・設定の API(serve)。
読む側は `apikey.get_api_key()` を呼ぶたびに読む(テストの差し替えはスタジオの common.py の転送でここへ届く。RS5 で消す)。
"""
import json
import os
import re

from . import errors, fsio as _fsio, studio_env as _env

KEY_RE = re.compile(r"^[A-Za-z0-9_-]{20,80}\Z")


def get_api_key():
    """(キー, "env"|"file"|None)。環境変数 YOUTUBE_API_KEY が優先。"""
    key = os.environ.get("YOUTUBE_API_KEY", "").strip()
    if key:
        return key, "env"
    key = str(_fsio.read_json_or(_env.p("config.json"), {}, kind=dict).get("apiKey", "")).strip()
    if key:
        return key, "file"
    return "", None


def set_api_key(raw):
    """キーを保存する(空なら config.json を消す)。形が違えば ApiError 400。戻り値はキーがあるか"""
    key = str(raw or "").strip()
    if key and not KEY_RE.match(key):
        raise errors.ApiError("key_format", "APIキーの形式が正しくありません", 400)
    if key:
        _fsio.atomic_write(_env.p("config.json"), json.dumps({"apiKey": key}).encode("utf-8"), 0o600)
    elif os.path.exists(_env.p("config.json")):
        os.unlink(_env.p("config.json"))
    return bool(get_api_key()[0])
