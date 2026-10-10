"""ツール間の受け渡し(docs/spec/pipeline.md の 4)。

- 実行中のポートの共有: `<リポジトリ直下>/.runtime/studio.json` の読み書きと、`GET /api/siblings` の中身
中身は共通部品 ytt(runtime。統合計画の段階2)にあり、ここはスタジオ用の呼び方(関数名・引数)を保つ薄い入口。
切り抜き 1 本の素性(.clip.json)の組み立てと書き込みは RS3-5 で pipeline/export/manifest.py へ割った(書き出しが読む側。OPT1 で exporter.write_clip に畳んだ)。
"""
import http.client  # noqa: F401  テストが handoff.http.client.HTTPConnection を差し替える(ytt.runtime も同じモジュールを使う)

from ytt import runtime, studio_env as _env

TOOL_APPS = runtime.TOOL_APPS
PING_TIMEOUT = runtime.PING_TIMEOUT


# ---------- 実行中のポートの共有(.runtime) ----------
def runtime_dir():
    """<studio の1つ上>/.runtime。環境変数 YTT_RUNTIME_DIR があればそちら(テスト用)。"""
    return runtime.runtime_dir(_env.code_dir())


def write_runtime(tool, port, version, path="/"):
    """起動時に <runtime>/<tool>.json を書く。書けなくても起動は続ける(戻り値 None)。
    path は画面の場所(入口の統合サーバーに取り込まれたときは "/studio/")。tool は決まった ID だけ(ファイル名に使うため)"""
    if tool not in TOOL_APPS:
        return None
    path = runtime.write_runtime(runtime_dir(), tool, port, version, path)
    if path is None:
        _env.log_failure(".runtime の書き込み", OSError("%s に書けません" % runtime_dir()))
    return path


def remove_runtime(tool, port):
    """正常終了時に消す。別のプロセスが書き直したファイル(port・pid が違う)は消さない。"""
    return tool in TOOL_APPS and runtime.remove_runtime(runtime_dir(), tool, port)


def siblings(self_tool=None, self_port=None, timeout=PING_TIMEOUT, self_path="/"):
    """{"tools": {"studio": 8800, ...}}(取り込まれたツールがあれば "paths" も)。応答した(app が一致した)ものだけ。自分自身は問い合わせずに含める。"""
    return runtime.siblings(runtime_dir(), self_tool, self_port, timeout, self_path)
