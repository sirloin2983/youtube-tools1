# -*- coding: utf-8 -*-
"""② 管理の層 flow: 成果物の鍵を書く・読む(役割で組み直す RS6 b-K1。2026-10-10。決定 3-29 / plan/role-restructure.md 4 節の決まり 4・5-2)。

鍵(youtube-tools-key/v1。形と hash の計算は ytt/schemas の make_key・validate_key)は「この成果物は何から作ったか」の印。① pipeline は鍵を知らず、
② の段が終わったところ(ここの write_*)で書く。この段は書くだけ: 読んで「同じなら飛ばす・違えば印を付ける」のは b-K2(stale が使う)。
鍵が書けなくても段は失敗にしない(ログだけ。書けなければ False)。鍵のファイルが増えるだけで、今の動き・画面は変えない。

置き場所:
- 切り抜き(動画)の横   作業用/<名前>.export.key.json(schemas.key_path。media_key_path)
- 文書                  transcripts/<id>.transcribe.key.json・<id>.post.key.json・<id>.diar.key.json(workdata.TX_DIR の下。doc_key_path。文書を消すときは一緒に消す)
- パック                <パックのフォルダ>/pack.key.json(pack_key_path)

段ごとの inputs(組み立ては下の *_inputs。秒は ms の整数に):
- export     {media: media_identity, start, end, settings}
- transcribe {export: 切り抜きの鍵の hash か {media}, engine, engineVersion, model, language, quality(beam), vadMode, boost, (span)}
- post       {transcribe: transcribe の hash, post: 後処理の設定, dict: 辞書の版}
- diar       {transcribe: transcribe の hash, people: 出る人, voices: 覚えた声の版(ファイルの内容のハッシュ)}
- pack       {clips: 切り抜きの鍵の hash の並び, doc: カット計画の版, settings: パックの設定}
"""
import hashlib
import json
import logging
import os

from ytt import fsio as _fsio, schemas as _schemas, version as _version, workdata as _workdata

log = logging.getLogger("ytt.flow.keys")

PACK_KEY_NAME = "pack.key.json"


def _made_by():
    return {"name": "flow", "version": _version.VERSION}


# ---------- 置き場所 ----------
def media_key_path(media_path, stage="export"):
    """動画の鍵の場所(動画_0012.mp4 → 作業用/動画_0012.export.key.json)"""
    return _schemas.key_path(media_path, stage)


def doc_key_path(tid, stage):
    """文書の鍵の場所(transcripts/<id>.<段>.key.json)。id の形が正しくなければ ValueError"""
    if not _schemas.TID_RE.match(str(tid or "")):
        raise ValueError("文書の id が正しくありません")
    if stage not in _schemas.KEY_STAGES:
        raise ValueError("段が正しくありません: %r" % (stage,))
    return os.path.join(_workdata.TX_DIR, tid + "." + stage + _schemas.KEY_SUFFIX)


def pack_key_path(folder):
    return os.path.join(folder, PACK_KEY_NAME)


# ---------- 書く・読む ----------
def write(stage, kpath, inputs, made_by=None):
    """鍵を kpath に原子的に書く。-> 書けたら True。書けなければ False(ログだけ。段は失敗にしない)"""
    try:
        key = _schemas.make_key(stage, inputs, made_by or _made_by())
        _fsio.write_json(kpath, key)
        return True
    except (OSError, TypeError, ValueError) as e:
        log.warning("鍵を書けませんでした(%s %s): %s %s", stage, kpath, e.__class__.__name__, str(e)[:150])
        return False


def read(kpath, stage):
    """鍵を読む。-> 鍵(dict)。無い・壊れている・別の段なら None"""
    try:
        obj = _fsio.read_json_or(kpath, None, kind=dict)
    except OSError:
        return None
    key, _warn = _schemas.validate_key(obj)
    if key is None or key["stage"] != stage:
        return None
    return key


def stale(kpath, stage, inputs):
    """今の材料 inputs と書いてある鍵を比べる(b-K2 が使う)。-> "same"(同じ)| "differ"(違う)| "none"(鍵が無い・壊れている)"""
    have = read(kpath, stage)
    if have is None:
        return "none"
    try:
        now = _schemas.make_key(stage, inputs)
    except (TypeError, ValueError):
        return "none"
    return "same" if have["hash"] == now["hash"] else "differ"


def remove(kpath):
    """鍵を消す(無ければ何もしない)。-> 消せたか、元から無ければ True"""
    try:
        os.remove(kpath)
        return True
    except FileNotFoundError:
        return True
    except OSError as e:
        log.warning("鍵を消せませんでした(%s): %s", kpath, e)
        return False


def key_hash(kpath, stage):
    """鍵の hash(無い・壊れていれば None)"""
    k = read(kpath, stage)
    return k["hash"] if k else None


# ---------- 段ごとの inputs(純粋な関数)----------
def export_inputs(media_id, start, end, export_settings):
    """media_id = schemas.media_identity の結果。start・end = 元の媒体の秒"""
    return {"media": media_id, "start": _schemas.sec_ms(start), "end": _schemas.sec_ms(end), "settings": export_settings or {}}


def transcribe_inputs(export_hash, engine, engine_version, model, language, quality, vad_mode, boost, span=None):
    """export_hash = 切り抜きの export の鍵の hash(無ければ媒体の識別 {media: ...} の dict)。span = (開始, 終了) 秒(媒体の一部を認識したとき)"""
    out = {"export": export_hash, "engine": engine, "engineVersion": engine_version, "model": model, "language": language,
           "quality": quality, "vadMode": vad_mode, "boost": bool(boost)}
    if span is not None:
        out["span"] = [_schemas.sec_ms(span[0]), _schemas.sec_ms(span[1])]
    return out


def post_inputs(transcribe_hash, post_settings, dict_version):
    return {"transcribe": transcribe_hash, "post": post_settings, "dict": dict_version}


def diar_inputs(transcribe_hash, people, voices_version):
    return {"transcribe": transcribe_hash, "people": people, "voices": voices_version}


def pack_inputs(clip_hashes, doc_rev, pack_settings):
    return {"clips": list(clip_hashes), "doc": doc_rev, "settings": pack_settings or {}}


# ---------- 媒体の識別 ----------
_digests = {}


def _file_sha(path):
    """ファイルの内容の sha256(大きさと更新日時が同じなら前の結果。巨大な動画を段のたびに読み直さない)。読めなければ None"""
    try:
        st = os.stat(path)
        ck = (os.path.abspath(path), st.st_size, st.st_mtime_ns)
        if ck not in _digests:
            if len(_digests) > 200:
                _digests.clear()
            _digests[ck] = _schemas.file_digest(path)
        return _digests[ck]
    except OSError:
        return None


def file_media(path):
    """動画ファイル → media_identity("file", sha256)。読めなければ None"""
    sha = _file_sha(path)
    return _schemas.media_identity("file", sha256=sha) if sha else None


def _short(obj):
    return hashlib.sha256(_schemas.canon(obj).encode("utf-8")).hexdigest()[:16]


# ---------- 書く所から呼ぶ口 ----------
def write_export(clip_path, media_id, start, end, settings):
    """書き出しが済んだ切り抜き clip_path の export の鍵を書く(スタジオの書き出し・ライブの書き出し・F-1 の入れ替え)。-> 書けたか"""
    if media_id is None:
        return False
    try:
        inputs = export_inputs(media_id, start, end, settings)
    except (TypeError, ValueError) as e:
        log.warning("export の鍵の材料が正しくありません: %s", e)
        return False
    return write("export", media_key_path(clip_path, "export"), inputs)


def studio_media(spec):
    """スタジオの書き出しの spec から元の媒体の識別(youtube = archive・file = 内容のハッシュ)。それ以外・分からなければ None"""
    kind = spec.get("kind") or ("file" if spec.get("mode") == "file" else "youtube")
    try:
        if kind == "file":
            return file_media(spec.get("sourcePath") or spec.get("sourceFile") or "")
        if kind == "youtube":
            return _schemas.media_identity("archive", videoId=str(spec.get("videoId") or ""))
    except ValueError:
        return None
    return None


def studio_export_settings(spec):
    """スタジオの書き出しの設定のうち、出来上がりの映像・音に効くもの"""
    return {"fast": bool(spec.get("fast")), "maxHeight": spec.get("maxHeight"), "volume": spec.get("volume"), "loudness": spec.get("loudness")}


def write_studio_export(spec, clip_path, start, end):
    """スタジオの書き出しの 1 本が仕上がったときに呼ぶ(app の serve から)。-> 書けたか"""
    if not clip_path:
        return False
    return write_export(clip_path, studio_media(spec), start, end, studio_export_settings(spec))


def _clip_basis(source_path):
    """文字起こし・パックの材料に入れる、元の動画の素性: 切り抜きの export の鍵の hash(あれば)。無ければ {media: 動画の内容の識別}。分からなければ None"""
    if not source_path:
        return None
    h = key_hash(media_key_path(source_path, "export"), "export")
    if h:
        return h
    m = file_media(source_path)
    return {"media": m} if m else None


def write_after_transcribe(tid, spec, run):
    """文字起こしが文書の横に書けた直後に呼ぶ: transcribe と post の鍵を <id>.transcribe.key.json・<id>.post.key.json に。
    run = 文書の recognition.runs の最初の記録(engine・engineVersion・model・language・settings{beam・vadMode・boost・dict}・post)。-> 書けた段の数"""
    try:
        st = run.get("settings") or {}
        span = (spec["start"], spec["end"]) if not spec.get("whole") and spec.get("end") is not None and spec.get("start") is not None else None
        ti = transcribe_inputs(_clip_basis(spec.get("sourcePath")), run.get("engine", ""), run.get("engineVersion", ""), run.get("model", ""),
                               run.get("language", ""), st.get("beam"), st.get("vadMode"), st.get("boost"), span)
        key = _schemas.make_key("transcribe", ti, _made_by())
        n = 0
        if write("transcribe", doc_key_path(tid, "transcribe"), ti):
            n += 1
        if write("post", doc_key_path(tid, "post"), post_inputs(key["hash"], run.get("post"), st.get("dict"))):
            n += 1
        return n
    except (TypeError, ValueError, KeyError) as e:
        log.warning("文字起こしの鍵を書けませんでした(%s): %s %s", tid, e.__class__.__name__, str(e)[:150])
        return 0


def write_diar(tid, people, voices_path=None):
    """話者判別の記録を書いた直後に呼ぶ: <id>.diar.key.json。people = 出る人({requested・embedding・(name)})・
    voices_path = 覚えた声のファイル(内容のハッシュを版にする。無ければ空)。-> 書けたか"""
    try:
        voices = _file_sha(voices_path) if voices_path and os.path.isfile(voices_path) else ""
        return write("diar", doc_key_path(tid, "diar"),
                     diar_inputs(key_hash(doc_key_path(tid, "transcribe"), "transcribe"), people, voices or ""))
    except (TypeError, ValueError) as e:
        log.warning("判別の鍵を書けませんでした(%s): %s", tid, e)
        return False


def write_pack(out_dir, video, cut_plan, settings):
    """パックを作り終えたところで呼ぶ: <パック>/pack.key.json。video = 元の動画(横の export の鍵の hash があれば clips に入れる)・
    cut_plan = 残す区間の計画(版は内容のハッシュ)・settings = パックの設定。-> 書けたか"""
    try:
        clips = []
        h = key_hash(media_key_path(video, "export"), "export") if video else None
        if h:
            clips.append(h)
        elif video:
            m = file_media(str(video))
            clips.append(_short(m) if m else "")
        doc_rev = _short(json.loads(json.dumps(cut_plan, default=str)))
        return write("pack", pack_key_path(str(out_dir)), pack_inputs(clips, doc_rev, json.loads(json.dumps(settings, default=str))))
    except (TypeError, ValueError, OSError) as e:
        log.warning("パックの鍵を書けませんでした(%s): %s", out_dir, e)
        return False
