# -*- coding: utf-8 -*-
"""② 管理の層 flow: 成果物の鍵を書く・読む(役割で組み直す RS6 b-K1。2026-10-10。決定 3-29 / plan/role-restructure.md 4 節の決まり 4・5-2)。

鍵(youtube-tools-key/v1。形と hash の計算は ytt/schemas の make_key・validate_key)は「この成果物は何から作ったか」の印。① pipeline は鍵を知らず、
② の段が終わったところ(ここの write_*)で書く。読むのは ② の段(RS6 b-K2。flow/run.py): 文字起こしは transcribe_state(違えば飛ばして印・
force で作り直す)、パックは pack_state(違えば作り直す)。鍵が無い成果物は今のまま。
鍵が書けなくても段は失敗にしない(ログだけ。書けなければ False)。

置き場所:
- 切り抜き(動画)の横   作業用/<名前>.export.key.json(schemas.key_path。media_key_path)
- 文書                  transcripts/<id>.transcribe.key.json・<id>.post.key.json・<id>.diar.key.json(workdata.TX_DIR の下。doc_key_path。文書を消すときは一緒に消す)
- パック                <パックのフォルダ>/pack.key.json(pack_key_path)

段ごとの inputs(組み立ては下の *_inputs。秒は ms の整数に):
- export     {media: media_identity, start, end, settings}
- transcribe {export: 切り抜きの鍵の hash か {media}, engine, engineVersion, model, language, quality(beam), vadMode, boost, (span)}
- post       {transcribe: transcribe の hash, post: 後処理の設定, dict: 辞書の版}
- diar       {transcribe: transcribe の hash, people: 出る人, voices: 覚えた声の版(ファイルの内容のハッシュ)}
- pack       {clips: 切り抜きの鍵の hash の並び, doc: カットの指定と字幕のファイルの中身の版, settings: パックの設定}(pack_body_inputs。
             作る前に分かる材料だけ = 段が比べられる。b-K1 の「カット計画の版」から RS6 b-K2 で替えた)
"""
import hashlib
import json
import logging
import os

from pipeline.pack import pack as _pack, resolve_textplus as _tp
from ytt import colors as _colors, errors as _errors, fsio as _fsio, loudness as _loud, schemas as _schemas, version as _version, workdata as _workdata

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


def post_inputs(transcribe_hash, post_settings, dict_version, learning_version=""):
    """learning_version = 束の post.learning.version。空(既定)のときは inputs に書かない = 今の鍵と同じ値"""
    out = {"transcribe": transcribe_hash, "post": post_settings, "dict": dict_version}
    if learning_version:
        out["learning"] = learning_version
    return out


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
        if write("post", doc_key_path(tid, "post"), post_inputs(key["hash"], run.get("post"), st.get("dict"), spec.get("learningVersion") or "")):
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


PACK_PATH_KEYS = ("video", "transcript", "srt", "plan")   # パックの要求の spec のうちファイルの場所(鍵には場所でなく中身を入れる)
PACK_FORM = 2   # pack の鍵の inputs の形(2 = 要求の本文から = RS6 b-K2)。これと違う鍵(b-K1 のカット計画の版の形)は「鍵なし」と同じに扱う(一度の作り直しをしない)
_FILE_META = ("createdAt", "tool")                         # 受け渡しの JSON のうち、作るたびに変わる項目(中身の版に入れない)


def _file_part(path):
    """パックの材料のファイル(受け渡しの JSON・SRT・カット計画)の中身の版。JSON なら作った日時と道具を除いて、ほかはバイト列のまま。読めなければ ""
    (同じ文書から作り直した受け渡しの JSON は、文字・行・話者が同じなら同じ版 = 「字幕が新しい」だけを見分ける)"""
    try:
        with open(path, "rb") as f:
            raw = f.read()
    except (OSError, TypeError, ValueError):
        return ""
    try:
        obj = json.loads(raw.decode("utf-8-sig"))
    except ValueError:
        return hashlib.sha256(raw).hexdigest()[:16]
    if isinstance(obj, dict):
        obj = {k: v for k, v in obj.items() if k not in _FILE_META}
    return _short(obj)


def _pack_settings(o):
    """パックの要求の output -> 出来上がりに効く設定を、送り方の違い(省略・既定の値・名前の書き方)をそろえた形で(cut2resolve の API の受付と同じ読み方)。
    出力先 dir と上書き force は入れない。形が違えば ValueError"""
    textplus = bool(o.get("textplus"))
    target = _tp.parse_target(o.get("textplusFps"), o.get("textplusSize"))
    who, hex_ = _colors.resolve(o.get("streamer") if isinstance(o.get("streamer"), str) else "")
    styles = o.get("speakerStyles") if isinstance(o.get("speakerStyles"), dict) else {}
    loud = _loud.check_target(o.get("loudness"))
    return {"textplus": textplus, "copyVideo": _pack.normalize_outputs(o.get("copyVideo"), False, textplus)[0], "render": bool(o.get("render")),
            "backup": o.get("backup") is True, "target": [target["fps"], target["width"], target["height"]],
            "textplusWrap": None if o.get("textplusWrap") in (None, "") else int(o["textplusWrap"]), "color": hex_ or None, "who": who if hex_ else None,
            "speakerColors": o.get("speakerColors") is not False,
            "speakerStyles": {_colors.normalize(k): _colors.norm_hex((v or {}).get("color")) for k, v in sorted(styles.items()) if isinstance(v, dict)} or None,
            "loudness": loud, "volume": None if loud is not None else _loud.check_volume(o.get("volume")),
            "videoTracks": 1 if o.get("videoTracks") in (None, "") else _tp.video_tracks_value(o.get("videoTracks"))}


def pack_body_inputs(spec, output):
    """パックの要求(cut2resolve の POST /api/build の本文の spec・output)-> pack の鍵の inputs(RS6 b-K2)。作る前に分かる材料だけで組む
    (② の段が「今作ったら同じか」を比べ、cut2resolve と LocalTools が作り終えたところで同じ関数で書く):
    clips = 元の動画の素性(切り抜きの export の鍵の hash か内容のハッシュ)・doc = カットの指定(場所を除く)と字幕のファイルの中身の版・
    settings = 出来上がりに効く設定(_pack_settings)。形が違えば ValueError・TypeError"""
    video = str(spec["video"])
    basis = _clip_basis(video)
    clip = basis if isinstance(basis, str) else (_short(basis) if basis else "")
    cut = {k: v for k, v in spec.items() if k not in PACK_PATH_KEYS}
    files = {k: _file_part(spec[k]) for k in PACK_PATH_KEYS[1:] if spec.get(k)}
    return dict(pack_inputs([clip], _short(json.loads(json.dumps({"cut": cut, "files": files}, default=str))), _pack_settings(output or {})),
                form=PACK_FORM)


def pack_dir_key_path(video):
    """動画の既定のパックのフォルダ(① pack.default_out_dir = <名前>_pack。段は出力先を指定しない)の鍵の場所"""
    return pack_key_path(str(_pack.default_out_dir(video)))


def pack_dir(video):
    """動画の既定のパックのフォルダ(<名前>_pack)のパス。あるかどうかは見ない"""
    return str(_pack.default_out_dir(video))


def write_pack(out_dir, spec, output):
    """パックを作り終えたところで呼ぶ(cut2resolve の API・LocalTools): <パック>/pack.key.json。spec・output = パックの要求の本文(pack_body_inputs)。
    -> 書けたか(書けなくてもパックはできている = ログだけ)"""
    try:
        return write("pack", pack_key_path(str(out_dir)), pack_body_inputs(spec, output))
    except (TypeError, ValueError, KeyError, OSError) as e:
        log.warning("パックの鍵を書けませんでした(%s): %s", out_dir, e)
        return False


def pack_state(video, make_body):
    """動画の既定のパックの鍵と、今作ったときの材料を比べる(RS6 b-K2)。-> ("same" | "differ" | "none", 作った本文 か None)。
    鍵が無い・壊れていれば ("none", None)(make_body は呼ばない = 鍵の無い今のパックは今のまま)。make_body() -> {"spec", "output", ...}(段が送る本文)。
    make_body が上げる例外(段の StepError)はそのまま上げる。材料の形が違えば none"""
    try:
        have = read(pack_dir_key_path(video), "pack")
    except (TypeError, ValueError):
        return "none", None
    if have is None or have["inputs"].get("form") != PACK_FORM:
        return "none", None
    built = make_body()
    body = built[0] if isinstance(built, tuple) else built
    try:
        now = _schemas.make_key("pack", pack_body_inputs(body["spec"], body["output"]))
    except (TypeError, ValueError, KeyError):
        return "none", built
    return ("same" if now["hash"] == have["hash"] else "differ"), built


def _same_with(key, stage, **changes):
    """書いてある鍵の inputs の一部を今の値に替えて hash を作り直し、同じか(替えた所だけを比べる)"""
    try:
        return _schemas.make_key(stage, dict(key["inputs"], **changes))["hash"] == key["hash"]
    except (TypeError, ValueError):
        return False


def stored_state(tid, source_path, doc_updated_at=0):
    """今の設定を知らずに分かる範囲の鍵の状態(④ manage/cases/txindex.key_state が読む。読むだけ。RS6 b-K2)-> {"transcribe", "pack"}。
    transcribe: 文書 tid の鍵の「元の切り抜き」が今の切り抜きの素性と違う(書き出し直した)= differ。pack: 動画の既定のパックの鍵の「元の切り抜き」が違うか、
    文書が鍵より後に直された(字幕が新しい)= differ。鍵が無い・文書が無ければ none"""
    out = {"transcribe": "none", "pack": "none"}
    if not source_path:
        return out
    basis = _clip_basis(source_path)
    try:
        tk = read(doc_key_path(tid, "transcribe"), "transcribe") if tid else None
        pkpath = pack_dir_key_path(source_path)
        pk = read(pkpath, "pack")
    except (TypeError, ValueError):
        return out
    if tk:
        out["transcribe"] = "same" if _same_with(tk, "transcribe", export=basis) else "differ"
    if pk and pk["inputs"].get("form") == PACK_FORM:
        clip = basis if isinstance(basis, str) else (_short(basis) if basis else "")
        try:
            newer = bool(doc_updated_at) and doc_updated_at > os.path.getmtime(pkpath) * 1000
        except OSError:
            newer = False
        out["pack"] = "same" if _same_with(pk, "pack", clips=[clip]) and not newer else "differ"
    return out


# ---------- 文字起こしの鍵を読む(RS6 b-K2) ----------
def transcribe_req_inputs(source_path, req):
    """文字起こしの要求 req(束の tx_opts + 段が決めた engine・model。「編集」の受付 validate_job と同じ読み方)で今 source_path を認識したら
    write_after_transcribe が書く transcribe の inputs。動画全体(段は範囲を指定しない)。使えないエンジン・モデルなら ApiError・ValueError"""
    from pipeline.transcribe import records as _records, worker_client as _wc   # 呼ぶときだけ(鍵を書くだけの所で認識の部品を読まない)
    model = str(req.get("model") or "large-v3").strip()
    if not _wc.valid_model(model):
        raise ValueError("モデル名が正しくありません")
    spec = {"engine": _wc.req_engine(req, model), "model": model, "language": str(req.get("language") or "ja"),
            "beam": 1 if req.get("quality") == "fast" else 5,
            "vadMode": req.get("vadMode") if req.get("vadMode") in ("weak", "normal", "off") else ("off" if req.get("vad") is False else "weak"),
            "boost": req.get("boost") is True}
    eid, ever = _records.run_engine(spec)
    return transcribe_inputs(_clip_basis(source_path), eid, ever, model, spec["language"], spec["beam"], spec["vadMode"], spec["boost"])


def transcribe_state(tid, source_path, req):
    """文書 tid の transcribe の鍵と、今の要求で認識したときの材料を比べる -> "same" | "differ" | "none"(鍵が無い・壊れている・今の材料が分からない)"""
    try:
        kpath = doc_key_path(tid, "transcribe")
        if read(kpath, "transcribe") is None:
            return "none"
        return stale(kpath, "transcribe", transcribe_req_inputs(source_path, req))
    except (_errors.ApiError, TypeError, ValueError, OSError):
        return "none"
