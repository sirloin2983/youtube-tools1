"""ffmpeg -i で読むメディア情報と、その覚え(役割で組み直す RS3-4。2026-10-10 にスタジオの common.py から移した)。

`media_info(path)` → (長さ秒 or None, 映像あり, 音声あり, 映像ストリームの行)。ffprobe が無くても動く(ffmpeg -i の出力を読む)。
使う所: スタジオの解析(analyze)・配信の登録(store)・書き出し(pipeline/export/exporter)。
同じファイルに ffmpeg -i を何度もかけない(書き出し 1 本で約 11 回 → 5 回。2026-10-09 見直し T7)。
鍵は (パス・更新日時 ns・大きさ)(ytt.fsio.StampCache)。書き出しは一時の名前に書いてから置き換えるので、中身が変われば鍵も変わる。
時間では覚えない(テストが作り直した直後に測る)。ffmpeg を動かせなかったとき(例外)は覚えない。道具を差し替えたら全部忘れる。
ffmpeg の場所はスタジオの決まり(studio_env.find_tool = 環境変数 STUDIO_FFMPEG → YTT_FFMPEG → PATH → winget)、動かすのは procs.run_short(終了の流れで止められる)。
編集の動画・音声の小道具(ytt/tools の ffmpeg_info・probe_media)は別の決まり(TRANSCRIBE_FFMPEG・覚えない)なので、ここには寄せていない。
"""
import re
import subprocess

from . import fsio as _fsio, procs as _procs, studio_env as _env

MEDIA_CACHE_MAX = 256
_media_cache = _fsio.StampCache()
_media_ff = [None]
_NO_MEDIA = (None, False, False, "")


def _probe_media(ff, path):
    pr = _procs.run_short([ff, "-hide_banner", "-nostdin", "-protocol_whitelist", "file,pipe", "-i", path], timeout=60, merge_stderr=True)
    out = pr.stdout or ""
    m = re.search(r"Duration:\s*(\d+):(\d+):(\d+(?:\.\d+)?)", out)
    dur = int(m.group(1)) * 3600 + int(m.group(2)) * 60 + float(m.group(3)) if m else None
    vm = re.search(r"Stream #.*Video:.*", out)
    return dur, bool(vm), bool(re.search(r"Stream #.*Audio:", out)), (vm.group(0).strip()[:300] if vm else "")


def media_info(path):
    """(長さ秒 or None, 映像あり, 音声あり, 映像ストリームの行)。ffprobe がなくても動く。ファイルが変わっていなければ前の結果を使う"""
    ff = _env.find_tool("ffmpeg")
    if not ff:
        return _NO_MEDIA
    if _media_ff[0] != ff or len(_media_cache) > MEDIA_CACHE_MAX:
        _media_cache.clear()
        _media_ff[0] = ff
    try:
        return _media_cache.get(path, lambda p: _probe_media(ff, p)) or _NO_MEDIA   # 無いファイルは ffmpeg を動かさずに「分からない」
    except (OSError, subprocess.SubprocessError):
        return _NO_MEDIA


def media_info_known(path):
    """覚えている media_info の結果(ファイルが変わっていないときだけ。ffmpeg は動かさない)。無ければ None"""
    return _media_cache.peek(path)


def remember_media_info(path, info):
    """置き換え(名前の付け替え)で中身がそのまま移ったファイルに、移す前の media_info の結果を覚えさせる(info が None なら何もしない)"""
    if info is not None:
        _media_cache.set(path, info)
