"""切り抜き 1 本の素性 `youtube-tools-clip/v1`(書き出した mp4 の隣の `<名前>.clip.json`)を作って原子的に書く(docs/spec/pipeline.md の 2.1・6)。

RS3-5(2026-10-10)で studio/handoff.py から割った(書き出し exporter が読む側。実行中のポートの共有 `.runtime` は studio/handoff.py に残る)。
中身は ytt(schemas・fsio)にあり、ここはスタジオ用の呼び方(関数名・引数)を保つ薄い入口。ツール名・版は TOOL に入れる(版は serve.py が入れる)。
"""
from ytt import fsio, runtime, schemas

TOOL = {"name": runtime.TOOL_APPS["studio"], "version": ""}   # 版は serve.py が SERVER_VERSION を入れる(版の正は serve.py のまま)


def manifest_path(media_path):
    """動画_0012.mp4 → 作業用/動画_0012.clip.json(途中のファイルは下のフォルダ。ytt.schemas.WORK_DIR)。"""
    return schemas.clip_path_for(media_path)


def clip_manifest(media_path, duration, source, rng, mark, export):
    """1本ぶんの youtube-tools-clip/v1 を組み立てる(ytt.schemas.build_clip)。"""
    return schemas.build_clip(media_path, duration, source, rng, mark, export, TOOL)


def write_clip_manifest(media_path, **kw):
    """mp4 の .clip.json を 作業用/ に書いて、そのパスを返す。失敗したら OSError(呼び出し側で警告にする)。
    UTF-8(BOM なし)で、一時ファイルに書いてから置き換える(書きかけを他のツールに読ませない。ytt.fsio.write_json)"""
    path = manifest_path(media_path)
    fsio.write_json(path, clip_manifest(media_path, **kw))   # 作業用/ は atomic_write が作る
    return path
