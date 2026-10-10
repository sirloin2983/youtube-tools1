# -*- coding: utf-8 -*-
"""文字起こしの単語の時刻 transcripts/<id>.words.json の読み書き(標準ライブラリ・ytt の fsio と workdata だけ = 純粋な形の記録)。

役割で組み直す RS6 a-5b(2026-10-10)に pipeline/transcribe/records から ytt へ下ろした(中身は同じ)。③ 人(doc_jobs・rerun)と ② flow/tx が直に読む
(① は単語の時刻を読まない)。置き場所は ytt/workdata の TX_DIR を呼ぶたびに読む。編集の serve の名前の受付に並ぶ(S.words_path・S.read_words)。
"""
import json
import time

from ytt import docloc as _docloc, fsio as _fsio

# 行のデータには入れない = 画面の保存で落ちたり古くなったりしないように(12 ②)
WORDS_SCHEMA = "youtube-tools-words/v1"
MAX_WORDS_BYTES = 32 * 1024 * 1024


def words_path(tid, for_write=False):
    """<id>.words.json のパス(for_write = 書く所。索引があるのに置き場所が見えなければ断る = docloc.doc_dir)"""
    return _docloc.doc_file(tid, ".words.json", for_write=for_write)


def read_words(tid):
    """文書の単語の時刻 [[開始, 終了, 文字], ...](時刻の順)。無い・壊れていれば None"""
    d = _fsio.read_schema_json(words_path(tid), MAX_WORDS_BYTES, WORDS_SCHEMA, "words")
    if d is None:
        return None
    out = []
    for w in d["words"]:
        if isinstance(w, list) and len(w) == 3 and all(isinstance(x, (int, float)) and not isinstance(x, bool) for x in w[:2]) and isinstance(w[2], str):
            out.append([float(w[0]), float(w[1]), w[2]])
    return sorted(out, key=lambda w: (w[0], w[1]))


def write_words(tid, words, model=""):
    """単語の時刻を保存する(空なら消す)。書けなくても文字起こしは失敗にしない(呼び出し側で記録だけ)"""
    if not words:
        _fsio.unlink_quiet(words_path(tid, for_write=True))
        return
    body = {"schema": WORDS_SCHEMA, "model": str(model or ""), "updatedAt": int(time.time() * 1000),
            "words": sorted(words, key=lambda w: (w[0], w[1]))}
    _fsio.atomic_write(words_path(tid, for_write=True), json.dumps(body, ensure_ascii=False, separators=(",", ":")).encode("utf-8"), fsync_required=True)
