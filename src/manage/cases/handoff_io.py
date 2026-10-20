# -*- coding: utf-8 -*-
"""④ 受け渡し: 元の配信の情報(clip/v1)・受け渡しの JSON と SRT を動画の隣に保存
(notes:docs/spec/pipeline.md の 1・2・4・6)。

- clip/v1 の検証・読み・原子的な書き込み・.runtime の中身は ytt(schemas・fsio・runtime)。ここは .clip.json が指す動画を探す・
  動画の隣への保存の名前の規則(上書き / 別名)だけを持つ
- 受け渡しの JSON(transcript/v1・cut-plan/v1)と SRT の組み立ては flow/pack

- .runtime の置き場所 runtime_path_dir は app(editor/ed_state.py)
- 名前 handoff_io はスタジオの handoff(配信 → 編集の受け渡しの書き手)と重ねないため
名前は serve.py からも見える(serve.py の名前の受付 _ED_MODULES がこの部品へ転送する。テストの S.名前 = … もここに入る)。
ほかの部品の名前は `モジュール.名前` の形で呼ぶたびに読む(差し替えが効くように。from … import はしない)。
"""
import json
import os
import threading

from ytt import errors as _errors, fsio as _fsio, runtime as _runtime, schemas as _schemas  # noqa: E402
from ytt import tools as _tools  # noqa: E402   (動画と音声の小道具)
from flow import pack as _flowpack  # noqa: E402   (受け渡しの JSON と SRT の組み立て。RS6 a-5a に pipeline/pack/resolve_export から。呼ぶたびに _flowpack.名前 で読む)
from ytt import txbase as _txbase  # noqa: E402   ロガー log(RS3-E7 まで ed_state の別名で読んでいた)
from human.proof import store as _store  # noqa: E402   文書の読み・編集の内容(呼ぶたびに _store.名前 で読む)


TOOL_NAME = _runtime.TOOL_APPS["transcribe"]   # 受け渡しの tool.name(互換のため値は変えない)
MAX_OWN_FILE_BYTES = 64 * 1024 * 1024   # 「前にこのツールが書いたか」を確かめるときに読む上限
EXPORT_FORMATS = {                      # 動画の隣に保存するときの名前の後ろ(拡張子を置き換える)
    "transcript-v1": ".transcript.json",
    "srt": ".srt",
    "cut-plan-v1": ".cut-plan.json",
}
MAX_ALT_NAMES = 999


class PipelineError(Exception):
    """受け渡しの処理のエラー。_pipeline_error で ApiError({"error": code, "message": message})にする。"""

    def __init__(self, code, message, status=400):
        super().__init__(message)
        self.code, self.message, self.status = code, message, status


# ---------- 動画の隣への保存(書き込みの部品は ytt.fsio: 一時的なロックのやり直し・一時ファイル → 置き換え・既存を上書きしない作成) ----------
_beside_lock = threading.Lock()


def written_by_us(path, schema):
    """path が、このツールが前に書いた schema のファイルか(schema が同じで、tool.name が transcribe-tool)。
    cut-plan/v1 は他のツールも書ける形式なので、schema だけでなく書いたツールも確かめる(他のツールのファイルを上書きしない)。"""
    try:
        d = _fsio.read_json_file(path, MAX_OWN_FILE_BYTES)
    except (OSError, UnicodeError, ValueError):
        return False
    return isinstance(d, dict) and d.get("schema") == schema and isinstance(d.get("tool"), dict) and d["tool"].get("name") == TOOL_NAME


def _alt_name(stem, suffix, n):
    return "%s%s" % (stem, suffix) if n == 1 else "%s (%d)%s" % (stem, n, suffix)


def save_beside(media_path, suffix, data, schema=None):
    """動画のフォルダの 作業用/ に <動画の名前(拡張子を除く)><suffix> で保存する(途中のファイルは出力先の直下に置かない。
    ytt.schemas.work_dir。動画がもう 作業用 の中ならそこ)。戻り値 (保存したパス, 上書きしたか)。
    同名があるとき: schema を渡していて、それがこのツールが前に書いた同じ schema のファイルなら上書き。
    それ以外(SRT は常に)は「名前 (2).srt」「名前 (3).srt」… の順に、空いている名前(または前にこのツールが書いた同じ schema のもの)にする。
    書き込みは一時ファイル → 置き換え(書きかけのファイルを他のツールに読ませない)。"""
    if not os.path.isdir(os.path.dirname(os.path.abspath(media_path))):
        raise PipelineError("no_dir", "動画のフォルダが見つかりません: %s" % os.path.dirname(os.path.abspath(media_path)))
    folder = _schemas.work_dir(media_path)
    stem = os.path.splitext(os.path.basename(media_path))[0]
    target = os.path.join(folder, stem + suffix)   # エラーの説明用
    try:
        with _beside_lock:
            os.makedirs(folder, exist_ok=True)
            for n in range(1, MAX_ALT_NAMES + 1):
                p = os.path.join(folder, _alt_name(stem, suffix, n))
                if os.path.lexists(p):
                    # 同じ名前があっても、このツールが前に書いた同じ schema のものなら上書き(別名の「(2)」も同じ扱いにして、書き出すたびに増えないように)
                    if schema and os.path.isfile(p) and written_by_us(p, schema):
                        _fsio.atomic_write(p, data, fsync_required=True)   # 一時ファイル → 置き換え(失敗したら一時ファイルを消す)
                        return p, True
                    continue
                if _fsio.create_new(p, data):
                    return p, False
    except PermissionError as e:
        raise PipelineError("no_write", "動画のフォルダに書き込めません(%s)。読み取り専用のフォルダ・同期中のフォルダ・"
                                        "他のアプリで開いているファイルでないか確認してください" % (e.filename or folder))
    except OSError as e:
        hint = "(パスが長すぎる可能性があります。動画を浅いフォルダへ移してください)" if len(target) >= 250 else ""
        raise PipelineError("write_failed", "動画の隣に保存できませんでした: %s%s" % (e.strerror or e.__class__.__name__, hint))
    raise PipelineError("no_name", "同じ名前のファイルが多すぎるため保存できません(%s)" % (stem + suffix))


# ---------- 受け渡しの API(notes:docs/spec/pipeline.md の 2・4・6) ----------
def _pipeline_error(e):
    return _errors.ApiError(e.code, e.message, e.status)


def export_file(req):
    """POST /api/export-file {"id", "format": transcript-v1|srt|cut-plan-v1, "baseUpdatedAt"?, "wrap"?, "speakerNames"?}
    → 動画の隣に保存して {"path", "name", "overwritten", "format", "count"}。保存済みの内容を書き出す(画面は先に保存してから呼ぶ)。
    baseUpdatedAt を付けると、保存済みの版と違うとき 409(画面の表示と違う内容を書き出さないため)。"""
    tid = str(req.get("id") or "")
    fmt = req.get("format")
    if fmt not in EXPORT_FORMATS:
        raise _errors.ApiError("bad_format", "format は transcript-v1 / srt / cut-plan-v1 のどれかにしてください", 400)
    doc = _store.read_transcript(tid)
    b = req.get("baseUpdatedAt")
    if b is not None and doc.get("updatedAt") and b != doc.get("updatedAt"):
        raise _errors.ApiError("conflict", "保存されていない変更があるか、別の場所で更新されています。保存してから、もう一度書き出してください", 409)
    src = str(doc.get("sourcePath") or "")
    if not src:
        raise _errors.ApiError("no_media", "この文字起こしには元の動画のパスがありません(動画の隣には保存できません。ダウンロードを使ってください)", 400)
    if not os.path.isfile(src):
        raise _errors.ApiError("no_media", "元の動画が見つかりません(移動・削除した可能性があります): %s" % src, 400)
    suffix = EXPORT_FORMATS[fmt]
    if fmt == "transcript-v1":
        obj, count = _flowpack.handoff_files(doc, fmt)
        schema = _schemas.TRANSCRIPT_SCHEMA
        if not count:
            raise _errors.ApiError("empty", "書き出す行がありません(文字のある行がありません)", 400)
        data = (json.dumps(obj, ensure_ascii=False, indent=1) + "\n").encode("utf-8")
    elif fmt == "cut-plan-v1":
        ed, _broken = _store.read_edit(tid)
        # 「編集」のカットがあれば、残す区間はそのとおり(行の区間ではなく)
        obj, count = _flowpack.handoff_files(doc, fmt, keeps=_store.edit_keeps_sec(ed) if ed else None)
        schema = _schemas.CUT_PLAN_SCHEMA
        if not count:
            raise _errors.ApiError("empty", "残す区間がありません(すべての行が「カット済」か、文字のある行がありません)", 400)
        data = (json.dumps(obj, ensure_ascii=False, indent=1) + "\n").encode("utf-8")
    else:
        try:
            wrap = max(0, min(200, int(req.get("wrap") or 0)))
        except (TypeError, ValueError):
            wrap = 0
        text, count = _flowpack.handoff_files(doc, fmt, wrap, req.get("speakerNames") is True)
        schema = None   # SRT は中身で「前にこのツールが書いたか」を判断できないので、同名があれば常に別名にする
        if not count:
            raise _errors.ApiError("empty", "書き出す行がありません(文字のある行がありません)", 400)
        data = text.encode("utf-8")   # BOM なし(notes:docs/spec/pipeline.md の 1)
    try:
        path, overwritten = save_beside(src, suffix, data, schema)
    except PipelineError as e:
        raise _pipeline_error(e)
    _txbase.log.info("動画の隣に保存: %s %s(%s)", fmt, os.path.basename(path), "上書き" if overwritten else "新規")
    return {"path": path, "name": os.path.basename(path), "overwritten": overwritten, "format": fmt, "count": count}
