"""ツール間の受け渡し(docs/pipeline.md の 2.1・4・6)。

- 切り抜き1本の素性 `youtube-tools-clip/v1`(書き出した mp4 の隣の `<名前>.clip.json`)を作って原子的に書く
- 実行中のポートの共有: `<リポジトリ直下>/.runtime/studio.json` の読み書きと、`GET /api/siblings` の中身
中身は共通部品 ytt_core(schemas・runtime。統合計画の段階2)にあり、ここはスタジオ用の呼び方(関数名・引数)を保つ薄い入口。
スタジオ固有の値(ツール名・版)は TOOL に入れる。
"""
import http.client  # noqa: F401  テストが handoff.http.client.HTTPConnection を差し替える(ytt_core.runtime も同じモジュールを使う)

import common
from ytt_core import fsio, runtime, schemas

CLIP_SCHEMA = schemas.CLIP_SCHEMA
TOOL = {"name": "clip-studio", "version": ""}   # 版は serve.py が SERVER_VERSION を入れる(版の正は serve.py のまま)
TOOL_APPS = runtime.TOOL_APPS
PING_TIMEOUT = runtime.PING_TIMEOUT
RUNTIME_MAX_BYTES = runtime.MAX_BYTES
iso_now = schemas.iso_now
valid_port = runtime.valid_port


def write_json(path, obj):
    """UTF-8(BOM なし)で、一時ファイルに書いてから置き換える(書きかけを他のツールに読ませない)。"""
    fsio.write_json(path, obj)


# ---------- youtube-tools-clip/v1 ----------
def manifest_path(media_path):
    """動画_0012.mp4 → 動画_0012.clip.json(拡張子を置き換える)。"""
    return schemas.clip_path_for(media_path)


def clip_manifest(media_path, duration, source, rng, mark, export):
    """1本ぶんの youtube-tools-clip/v1 を組み立てる(ytt_core.schemas.build_clip)。"""
    return schemas.build_clip(media_path, duration, source, rng, mark, export, TOOL)


def write_clip_manifest(media_path, **kw):
    """mp4 の隣に .clip.json を書いて、そのパスを返す。失敗したら OSError(呼び出し側で警告にする)。"""
    path = manifest_path(media_path)
    write_json(path, clip_manifest(media_path, **kw))
    return path


# ---------- 実行中のポートの共有(.runtime) ----------
def runtime_dir():
    """<clip-studio の1つ上>/.runtime。環境変数 YTT_RUNTIME_DIR があればそちら(テスト用)。"""
    return runtime.runtime_dir(common.CODE_DIR)


def runtime_path(tool):
    if tool not in TOOL_APPS:   # ファイル名に使うので、決まったIDだけ
        raise ValueError("unknown tool id")
    return runtime.runtime_path(runtime_dir(), tool)


def write_runtime(tool, port, version, path="/"):
    """起動時に <runtime>/<tool>.json を書く。書けなくても起動は続ける(戻り値 None)。
    path は画面の場所(入口の統合サーバーに取り込まれたときは "/studio/")。"""
    if tool not in TOOL_APPS:
        return None
    path = runtime.write_runtime(runtime_dir(), tool, port, version, path)
    if path is None:
        common.log_failure(".runtime の書き込み", OSError("%s に書けません" % runtime_dir()))
    return path


def remove_runtime(tool, port):
    """正常終了時に消す。別のプロセスが書き直したファイル(port・pid が違う)は消さない。"""
    return tool in TOOL_APPS and runtime.remove_runtime(runtime_dir(), tool, port)


def read_runtime_port(tool):
    """<runtime>/<tool>.json のポート。無い・壊れている・tool が違う・範囲外なら None(このファイルは信用しない)。"""
    return runtime.read_runtime_port(runtime_dir(), tool) if tool in TOOL_APPS else None


def ping_app(port, timeout=PING_TIMEOUT):
    """127.0.0.1:<port> の /api/ping の app(応答が無い・形が違えば None)。"""
    return runtime.ping_app(port, timeout)


def siblings(self_tool=None, self_port=None, timeout=PING_TIMEOUT, self_path="/"):
    """{"tools": {"studio": 8800, ...}}(取り込まれたツールがあれば "paths" も)。応答した(app が一致した)ものだけ。自分自身は問い合わせずに含める。"""
    return runtime.siblings(runtime_dir(), self_tool, self_port, timeout, self_path)
