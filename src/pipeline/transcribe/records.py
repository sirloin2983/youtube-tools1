# -*- coding: utf-8 -*-
"""① 文字起こしの記録: recognition.runs の 1 件(エンジンと版・設定・辞書の版・後処理)・配信ごとの文脈と声の検出の記録・
生出力(transcripts/<id>.asr.json)・単語の時刻(transcripts/<id>.words.json)の読み書き。

役割で組み直す RS2-5(2026-10-10)に編集の ed_jobs から移した(中身は同じ)。標準ライブラリ・ytt・同じパッケージの兄弟(backend・postproc・roster・
tx_engines・txbase)と ytt だけを読む。置き場所(ytt/workdata の TX_DIR)と名簿のファイル(roster.ROSTER)は呼ぶたびに持ち主から(RS3-0A まで txenv の口)。
辞書の版(dict_version)の置換辞書の組と学習の記録は、設定と学習(編集の ed_learn = 文書の側)を ① が直に読まないよう、引数(pairs・learned)で受け取る。
渡されなければ app(編集の serve.py)が set_dict_inputs で登録した口から読む(ed_jobs.dict_pairs・ed_jobs.dict_learned。呼ぶたびに読む = S.dict_pairs の差し替えが効く)。
dict_version を読むのは同じモジュールの _run_base だけ(テストの mock.patch.object(S, "dict_version", …) が届く)。
再認識で差し替えた機械の出力の記録(record_rerun・replaced_rows)は文書の側(ed_jobs。のちに human/proof)に残した。
"""
import functools
import hashlib
import json
import os
import time

from ytt import fsio as _fsio, workdata as _workdata
from . import backend as _backend, postproc, roster as _roster, tx_engines
from ytt import txbase as _txbase

_dict_inputs = {}


def set_dict_inputs(pairs, learned):
    """辞書の版の材料を読む口を登録する(app が読み込みのときに)。pairs(spec) -> 置換辞書の組 [(誤, 正)]・learned() -> 学習の記録を並べた文字"""
    _dict_inputs.update(pairs=pairs, learned=learned)


def _dict_input(name):
    try:
        return _dict_inputs[name]
    except KeyError:
        raise RuntimeError("records の辞書の版の材料 %s が登録されていません(編集の serve.py が set_dict_inputs で登録する)" % name) from None


@functools.lru_cache(maxsize=None)
def pkg_version(name):
    """入っているパッケージの版(読み込まずに dist-info から読む = サーバー側で faster_whisper などのネイティブの部品を import しない)。無ければ ''"""
    try:
        import importlib.metadata as _md
        return str(_md.version(name))
    except Exception:
        return ""


def engine_version(eng):
    """エンジン(tx_engines のクラス)の版: パッケージなら dist-info の版、実行ファイル(whisper.cpp・llama.cpp)なら決めた版"""
    return pkg_version(eng.package) if eng.package else eng.version(tx_engines.engine_home())


def _engine_ids(spec):
    """記録のエンジンと版(本物の認識。_run_base が backend の差し込み口から呼ぶ)-> (id, 版)。分からなくても記録は作る"""
    try:
        eng = tx_engines.get(tx_engines.engine_of(spec))
        return eng.id, engine_version(eng)
    except Exception:   # 記録のための値なので、エンジンの版が分からなくても認識・差し替えは止めない
        return tx_engines.engine_of(spec), ""


def run_engine(spec):
    """記録に書くエンジンと版 -> (id, 版)(今の Backend の差し込み口を通す = 疑似の認識では疑似の値)。
    最初の認識の記録(_run_base)と、② が「今の設定で認識したら何と書くか」を比べる所(flow/keys の transcribe の鍵)で同じ値にする"""
    return _backend.select().engine_ids(spec, _engine_ids)


def _run_base(spec, pairs=None):
    """recognition.runs の 1 件の共通の項目(最初の認識 recognition_run と再認識の記録 record_rerun で同じ。src/eval/tools/eval_* が読む):
    エンジンと版・モデル・言語・settings(beam・vadMode・boost・wordSplit・dict = 辞書の版)・at・post(行の後処理)。
    pairs = 作ってある置換辞書の組(dict_pairs。同じ設定を読み直さない)。エンジンの版が分からなくても記録は作る"""
    eid, ever = run_engine(spec)
    return {"engine": eid, "engineVersion": ever, "model": str(spec.get("model") or ""), "language": str(spec.get("language") or ""),
            "settings": {"beam": spec.get("beam"), "vadMode": spec.get("vadMode"), "boost": bool(spec.get("boost")), "wordSplit": bool(spec.get("wordSplit")),
                         "dict": dict_version(spec) if pairs is None else dict_version(spec, pairs)},
            "at": int(time.time() * 1000), "post": postproc.post_record()}


def recognition_run(spec, job, audio_sec, wall_sec, pairs=None):
    """文書の recognition.runs に残す、この認識の出どころ(エンジン・版・モデル・機器・かかった時間)。精度と速さを後から比べるため(計画 段0-1)"""
    run = _run_base(spec, pairs)
    run["device"] = job.get("device", "")
    run["settings"].update({"glossaryChars": len("、".join(spec.get("glossary") or [])), "promptChars": len("、".join(_roster.prompt_terms(spec))),
                            "context": [m["name"] for m in (spec.get("context") or {}).get("members") or []]})
    run.update({"audioSec": round(float(audio_sec or 0), 2), "wallSec": round(float(wall_sec), 2),
                **vad_record(job.get("vad"))})
    return run


def short_hash(text):
    """辞書などの中身の版(SHA-256 の先頭 10 文字)。中身そのものは残さず、同じ版かどうかだけ分かるようにする"""
    return hashlib.sha256(str(text).encode("utf-8")).hexdigest()[:10]


_roster_hashes = _fsio.StampCache()


def _file_hash(path):
    with open(path, "rb") as f:
        return hashlib.sha256(f.read()).hexdigest()[:10]


def roster_hash():
    """名簿のファイル(配信ごとの文脈・用語の自動追加の材料)の版。ファイルの更新日時と大きさが同じなら前の結果。読めなければ ''"""
    try:
        return _roster_hashes.get(_roster.ROSTER, _file_hash) or ""
    except OSError:
        return ""


def dict_version(spec, pairs=None, learned=None):
    """この認識に使った辞書の版(マスタープラン Q2。recognition.runs の settings.dict と文書の params.dict)。
    glossary = 用語集(自動で足した語を含む。ヒントに入った語)・replacements = 置換辞書(autoDict のとき)・
    learned = 学習済みの置換と採用・却下の記録(autoLearned のとき)・roster = 名簿のファイル。
    辞書を変えた前後で成績を分ける・同じ版どうしで比べるために、中身ではなく短いハッシュだけを残す。使っていない・読めないものは入れない。
    pairs = 呼ぶ側で作ってある置換辞書の組(ed_jobs.dict_pairs(spec)。設定と名簿を読み直さない)・learned = 学習の記録を並べた文字(ed_jobs.dict_learned())。
    渡さなければ app が set_dict_inputs で登録した口から読む(RS2-5。① は設定・学習を直に読まない)"""
    out = {}
    try:
        gl = [str(t) for t in spec.get("glossary") or []]
        if gl:
            out["glossary"] = short_hash("\n".join(gl))
        if spec.get("autoDict"):
            out["replacements"] = short_hash("\n".join("%s=>%s" % p for p in (_dict_input("pairs")(spec) if pairs is None else pairs)))   # 0.59.7 から名簿の表記ゆれの表も入る(表が変わると版が変わる)
        if spec.get("autoLearned"):
            out["learned"] = short_hash(_dict_input("learned")() if learned is None else learned)
    except (OSError, ValueError, TypeError, KeyError) as e:   # 記録のための値なので、作れなくても認識は止めない
        _txbase.log.warning("辞書の版を作れませんでした: %s", e)
    rh = roster_hash()
    if rh:
        out["roster"] = rh
    return out


def context_record(spec):
    """文書の params に残す配信ごとの文脈(出る人と材料・ヒントに入った語の数)。使っていなければ None"""
    ctx = spec.get("context") or {}
    if not ctx.get("members"):
        return None
    return {"members": [{"name": m["name"], "from": list(m.get("from") or [])} for m in ctx["members"]][:10], "terms": len(ctx.get("terms") or [])}


def vad_record(vad):
    """recognition.runs に残す声の検出の記録(使った設定・捨てた秒・やり直し)。分からなければ {}"""
    if not vad:
        return {}
    return {"vadUsed": vad.get("used"), "vadRemovedSec": vad.get("removedSec", 0.0), "vadRetries": list(vad.get("retries") or [])}


# ---------- 生出力(transcripts/<id>.asr.json。分ける前・置換の前の認識の結果。単語ごとの時刻と確信度。記録の土台 = 機械の最初の結果を書き換えずに残す) ----------
ASR_SCHEMA = "youtube-tools-asr-raw/v1"
MAX_ASR_BYTES = 64 * 1024 * 1024


def asr_path(tid):
    return os.path.join(_workdata.TX_DIR, tid + ".asr.json")


def capture_raw(gen, raw, shift=0.0):
    """認識の行の流れ gen をそのまま流しながら、生出力を raw に足す(文字・時刻・自信の度合い・単語 [[開始, 終了, 文字, 確信度]])"""
    for s in gen:
        try:
            ws, ps = s.get("words") or [], s.get("wordProbs") or []
            raw.append({"start": round(float(s["start"]) + shift, 3), "end": round(float(s["end"]) + shift, 3), "text": str(s.get("text") or ""),
                        **postproc.machine_conf(s), "words": [[round(a + shift, 3), round(b + shift, 3), t, ps[i] if i < len(ps) else None]
                                                     for i, (a, b, t) in enumerate(ws)]})
        except (KeyError, TypeError, ValueError):
            pass   # 生出力が残せなくても文字起こしは止めない
        yield s


def write_asr(tid, segments, run):
    """生出力を保存する(run = recognition.runs の1件 = モデル・設定・版)。書けなくても文字起こしは失敗にしない(呼び出し側)"""
    body = {"schema": ASR_SCHEMA, "run": run, "segments": segments, "updatedAt": int(time.time() * 1000)}
    _fsio.atomic_write(asr_path(tid), json.dumps(body, ensure_ascii=False, separators=(",", ":")).encode("utf-8"), fsync_required=True)


def read_asr(tid):
    """生出力 {"schema", "run", "segments"}。無い・壊れていれば None"""
    return _fsio.read_schema_json(asr_path(tid), MAX_ASR_BYTES, ASR_SCHEMA, "segments")
