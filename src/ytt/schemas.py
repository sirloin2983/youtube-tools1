"""受け渡しの形式(docs/spec/pipeline.md の 1・2)。youtube-tools-clip/v1 は、スタジオが書き(build_clip)、文字起こしが読む(load_clip_file)。
transcript/v1・cut-plan/v1 の組み立ては文字起こしツールの行の規則に依存するので、文字起こしの pipeline_io.py に残している。"""
import datetime
import hashlib
import json
import math
import os
import re
import time

from . import fsio

CLIP_SCHEMA = "youtube-tools-clip/v1"
TRANSCRIPT_SCHEMA = "youtube-tools-transcript/v1"
CUT_PLAN_SCHEMA = "youtube-tools-cut-plan/v1"
CLIP_SUFFIX = ".clip.json"
MAX_CLIP_BYTES = 256 * 1024   # .clip.json の上限(中身は数百バイト。巨大なファイルを読まない)
CLIP_MARK_SRCS = ("auto", "manual", "collab")


def iso_now():
    """書いた日時(ISO 8601・時差付き・秒まで。例: 2026-09-24T12:00:00+09:00)。"""
    return datetime.datetime.now().astimezone().isoformat(timespec="seconds")


def now_ms():
    """今の時刻(エポックのミリ秒の整数。文書・記録の at・updatedAt・createdAt と同じ単位。スタジオの store.now_ms の正。RS3-0B)"""
    return int(time.time() * 1000)


def num(v):
    """有限の数(bool は除く)なら float、それ以外は None(float にできない巨大な整数も None)。"""
    if isinstance(v, bool) or not isinstance(v, (int, float)):
        return None
    try:
        v = float(v)
    except OverflowError:   # JSON の 1 のあとに 0 が 400 個 など(以前はここで落ちていた)
        return None
    return v if math.isfinite(v) else None


def is_num(v):
    """有限の数か(bool・NaN・Infinity・float にできない巨大な整数は False)。num(v) is not None と同じ"""
    return num(v) is not None


def is_int(v):
    """JSON の整数か(bool は数えない。type(v) is int と同じ)"""
    return type(v) is int


def plain_int(v):
    """JSON の整数(bool は数えない)ならその値、違えば None"""
    return v if type(v) is int else None


def int_in(v, lo, hi):
    """JSON の整数(bool は数えない)で lo 以上 hi 以下ならその値、違えば None(ポート・件数・ミリ秒などの検査)"""
    return v if type(v) is int and lo <= v <= hi else None


def num_or(x, default=None):
    """float にできる有限の数(文字の "1.5" も可)ならその float、違えば default(要求の値の読み。編集の ed_state.num の正。RS2-1a)"""
    try:
        v = float(x)
    except (TypeError, ValueError):
        return default
    return v if math.isfinite(v) else default


def union_spans(spans):
    """区間 [(開始, 終了)…] を開始の順に並べ、重なる・接するものをつなぐ -> [[開始, 終了]…](編集の ed_state.union_spans の正。RS2-1a)"""
    out = []
    for a, b in sorted(spans):
        if out and a <= out[-1][1]:
            out[-1][1] = max(out[-1][1], b)
        else:
            out.append([a, b])
    return out


def fmt_hms(t):
    """秒 → 「時:分:秒」(0:01:05。負は 0。編集の ed_state.fmt_hms の正。RS2-1a)"""
    t = max(0, int(t))
    return "%d:%02d:%02d" % (t // 3600, t % 3600 // 60, t % 60)


def _r3(x):
    return None if x is None else round(float(x), 3)


# ---------- 文字起こしの文書の形の小道具(役割で組み直す RS2-9 に編集の ed_state から移した。ed_state には同じ物の別名がある) ----------
TID_RE = re.compile(r"^[0-9a-f]{12}$")   # 文書の id の形(12 文字の 16 進)
# 組み込みの話者「ゲーム音声など」(ゲームのキャラ・NPC・動画の音声など、その場かぎりの声。2026-10-05。plan/line-b-overlap.md の 6)。
# 文書の speakers に {"id": OTHER_SPK_ID, "name": OTHER_SPK_NAME, "builtin": OTHER_SPK_BUILTIN} で 1 つだけ入る(選んだときに画面が足す)。
# 名前は変えない・声を覚えない・判別のやり直しで上書きしない。画面の app.js の OTHER_SP と同じ値(変えるときは両方)
OTHER_SPK_ID = "other"
OTHER_SPK_NAME = "ゲーム音声など"
OTHER_SPK_BUILTIN = "other"
OTHER_SPK_COLOR = "#8a8f98"


def other_speaker(sp):
    """文書の話者が組み込みの「ゲーム音声など」か(id で決める。sanitize_transcript が id と印をそろえる)"""
    return isinstance(sp, dict) and sp.get("id") == OTHER_SPK_ID


def no_sub_row(g):
    """行の印 noSub(字幕に出さない)。真のときだけ持つ。カットの「残す」には今までどおり数える"""
    return isinstance(g, dict) and g.get("noSub") is True


# 行の印 draft(機械が置いた下書き・まだ人が打っていない。2026-10-05。話者の部品 human/proof/speakers の ovdraft_)。決まった文字列のときだけ持つ。
# "overlap" = 声があるのに行の無い所に置いた空の行(重なりの下書き)。文字を打ったら画面が外す。文字の無い行なので字幕・カット・パックには出ない
# "missing" = 主の話者も含めて、声があるのにどの行も無い所(抜けの下書き。音のメモ overlap は付けない。決まりは overlap と同じ)
ROW_DRAFT_KINDS = ("overlap", "missing")


def blank_draft_row(g):
    """機械の下書きのまま(印 draft があって文字が空)の行か"""
    return isinstance(g, dict) and g.get("draft") in ROW_DRAFT_KINDS and not str(g.get("text") or "").strip()


# ---------- 途中のファイルの置き場所(2026-09-27。git の履歴(679ff01 以前)の docs/archive/followup-2026-09-27.md の 1) ----------
# 出力先(動画のフォルダ)の直下に並べるのはパックと元動画(書き出した切り抜き)だけ(ユーザー決定)。それ以外の途中のファイル
# (.clip.json・.edit.json・_edit.mp4・.transcript.json・.srt・.cut-plan.json・.studio-id)は下のフォルダ「作業用」に書く。
# 以前の置き方(動画の隣)のファイルは動かさない。読む側は「作業用/ → 動画の隣」の順に探す(find_sidecar)。
# cut2resolve(ytt_core を読まないコマンドもある)は cut2resolve_core.WORK_DIR に同じ名前を持つ(test_serve が同じか確かめる)
WORK_DIR = "作業用"
# 動画と同じ名前で持つ途中のファイルの名前の終わり(全部。2026-10-09 に一覧だけ置いた)。各ツールの一覧は目的ごとに少しずつ違うので、
# まだここを読んでいない: 入口の片付け cleanup.SIDECARS(.studio-id 無し)・cleanup._media_stem(_edit.clip.json 無し)・
# 編集の ed_relink.EVAL_SIDECARS(_edit.clip.json・.studio-id 無し)。寄せるときは、足りない名前を足してよいかを確かめてから
SIDECAR_SUFFIXES = (".clip.json", ".edit.json", ".transcript.json", ".cut-plan.json", ".srt", "_edit.mp4", "_edit.clip.json", ".studio-id")


def work_dir(media_path):
    """動画の途中のファイルを書くフォルダ: 動画のフォルダの 作業用/(動画がもう 作業用 の中なら、そのフォルダ。_edit.mp4 など)"""
    folder = os.path.dirname(os.path.abspath(media_path))
    return folder if os.path.basename(folder) == WORK_DIR else os.path.join(folder, WORK_DIR)


def media_folder(sidecar_path):
    """途中のファイル → 動画のフォルダ(作業用 の中なら1つ上)"""
    folder = os.path.dirname(os.path.abspath(sidecar_path))
    return os.path.dirname(folder) if os.path.basename(folder) == WORK_DIR else folder


def sidecar_path(media_path, suffix):
    """途中のファイルを書く場所(動画_0012.mp4 + .clip.json → 作業用/動画_0012.clip.json)"""
    return os.path.join(work_dir(media_path), os.path.splitext(os.path.basename(media_path))[0] + suffix)


def sidecar_candidates(media_path, suffix):
    """途中のファイルを読む場所の候補(作業用/ → 以前の置き方 = 動画の隣)"""
    new, old = sidecar_path(media_path, suffix), os.path.splitext(os.path.abspath(media_path))[0] + suffix
    return [new] if os.path.normcase(new) == os.path.normcase(old) else [new, old]


def find_sidecar(media_path, suffix):
    """候補のうち、あるもの(無ければ None)。ネットワーク上のパスかどうかは呼び出し側で確かめる
    (os.path.isfile は OSError・ValueError(NUL を含むパス)を中で握って False を返すので、ここでは囲まない)"""
    return next((p for p in sidecar_candidates(media_path, suffix) if os.path.isfile(p)), None)


# ---------- youtube-tools-clip/v1 ----------
def clip_path_for(media_path):
    """.clip.json を書くパス(作業用/ の中。動画_0012.mp4 → 作業用/動画_0012.clip.json)。読むときは find_clip_path"""
    return sidecar_path(media_path, CLIP_SUFFIX)


def find_clip_path(media_path):
    """動画の .clip.json(作業用/ → 以前の置き方 = 動画の隣)。無ければ None"""
    return find_sidecar(media_path, CLIP_SUFFIX)


def build_clip(media_path, duration, source, rng, mark, export, tool):
    """切り抜き1本ぶんの youtube-tools-clip/v1 を組み立てる。
    source: {"kind": "youtube"|"file", "videoId", "title", "path"(file のときだけ元のファイル)}
    rng: (元の配信での開始秒, 終了秒)。mark: {"id","label","status","src"}。export: {"mode": "precise"|"fast", ...}。tool: {"name","version"}。
    API キーなどの秘密や、元動画以外の個人のパスは入れない(ここに渡さない)。"""
    kind = "file" if source.get("kind") == "file" else "youtube"
    vid = str(source.get("videoId") or "")
    src = {"kind": kind, "videoId": vid,
           "url": ("https://www.youtube.com/watch?v=" + vid) if kind == "youtube" and vid else None,
           "title": str(source.get("title") or ""), "path": source.get("path") if kind == "file" else None}
    return {"schema": CLIP_SCHEMA, "tool": {"name": str(tool.get("name", "")), "version": str(tool.get("version", ""))}, "createdAt": iso_now(),
            "media": {"path": os.path.abspath(media_path), "name": os.path.basename(media_path), "durationSec": _r3(duration)},
            "source": src,
            "range": {"start": _r3(rng[0]), "end": _r3(rng[1])},
            "mark": {"id": str(mark.get("id") or ""), "label": str(mark.get("label") or ""), "status": str(mark.get("status") or ""),
                     "src": mark.get("src") if mark.get("src") in CLIP_MARK_SRCS else "manual"},
            "export": dict(export)}


def validate_clip(obj):
    """(clip, 警告)。使えるときは (中身の複製, None)、使えないときは (None, 理由)。
    知らない項目は残す(前方互換。transcript/v1 に「中身そのもの」を入れる約束のため)。範囲(range)が正しくないものは使わない。"""
    if not isinstance(obj, dict):
        return None, ".clip.json の形式が正しくありません(JSON のオブジェクトではありません)"
    schema = obj.get("schema")
    if schema != CLIP_SCHEMA:
        if isinstance(schema, str) and schema.startswith("youtube-tools-clip/"):
            return None, ".clip.json は未対応の版です(%s。このツールが読めるのは %s)" % (schema[:40], CLIP_SCHEMA)
        return None, ".clip.json の schema が %s ではありません" % CLIP_SCHEMA
    rng = obj.get("range")
    a, b = (num(rng.get("start")), num(rng.get("end"))) if isinstance(rng, dict) else (None, None)
    if a is None or b is None or a < 0 or b <= a:
        return None, ".clip.json の range(元の配信の範囲)が正しくありません"
    for key in ("source", "media", "mark", "export", "tool"):
        if key in obj and obj[key] is not None and not isinstance(obj[key], dict):
            return None, ".clip.json の %s の形式が正しくありません" % key
    ex = obj.get("export") or {}
    if "actualStart" in ex and ex["actualStart"] is not None:
        v = num(ex["actualStart"])
        if v is None or v < 0:
            return None, ".clip.json の export.actualStart が正しくありません"
    return json.loads(json.dumps(obj, ensure_ascii=False)), None   # 呼び出し側が書き換えても元に響かないよう複製


def clip_offset(clip):
    """切り抜きの中の時刻 t が、元の配信では offset + t になる offset(export.actualStart があれば優先)。"""
    ex = clip.get("export") or {}
    v = num(ex.get("actualStart")) if isinstance(ex, dict) else None
    return v if v is not None and v >= 0 else float(clip["range"]["start"])


def load_clip_file(path, max_bytes=MAX_CLIP_BYTES):
    """(clip, 警告)。読めない・壊れている・別の版なら (None, 理由)。"""
    try:
        obj = fsio.read_json_file(path, max_bytes)
    except (OSError, UnicodeError, ValueError) as e:
        return None, ".clip.json を読めません(%s)" % (e.__class__.__name__ if isinstance(e, OSError) else str(e)[:80])
    return validate_clip(obj)


# ---------- youtube-tools-key/v1(成果物の鍵。plan/role-restructure.md 4 の 4・5-2。2026-10-09 RS1-5) ----------
# 成果物(切り抜き 1 本・認識・パックなど)の横に置く小さな JSON。「同じ鍵の成果物があれば作らない = 使い回し」の判定に使う。
# RS1 では形と純粋な関数だけを置く(どこにも書かない)。書く側は RS6。
KEY_SCHEMA = "youtube-tools-key/v1"
KEY_VERSION = 1
# diar(話者判別)は認識とは別の成果物(F-6: 出る人を直しても重い認識をやり直さない)。post = 後処理(軽い。辞書が育つたびに当て直してよい)
KEY_STAGES = ("ingest", "analyze", "export", "transcribe", "diar", "post", "pack")
KEY_SUFFIX = ".key.json"
MEDIA_KINDS = ("recording", "archive", "file")


def sec_ms(x):
    """秒 → ミリ秒の整数(鍵の入力に区間の時刻を入れるときの形)。NaN・無限大・bool・数でないものは ValueError"""
    v = num(x)
    if v is None:
        raise ValueError("秒として使えない値です: %r" % (x,))
    return int(round(v * 1000))


def _nonempty_str(v, name):
    if not isinstance(v, str) or not v.strip():
        raise ValueError("%s は空でない文字列にしてください" % name)
    return v


def _is_hex(s, n):
    return isinstance(s, str) and len(s) == n and all(c in "0123456789abcdef" for c in s)


def media_identity(kind, **kw):
    """元の媒体の識別(F-1)。切り抜きの鍵に入れて、配信中の録画からの速報版と、アーカイブからの本番版が同じ鍵にならないようにする。
    recording: recorder=録画の部品の名前/id, recording=録画 id。archive: videoId=YouTube の動画 ID。
    file: sha256=中身のハッシュ(file_digest で出す。ファイル名や更新日時は入れない = 動かしても同じ)。
    決まった項目以外・足りない項目・空の値は ValueError"""
    fields = {"recording": ("recorder", "recording"), "archive": ("videoId",), "file": ("sha256",)}
    if kind not in fields:
        raise ValueError("媒体の種類が正しくありません: %r(%s のどれか)" % (kind, "・".join(MEDIA_KINDS)))
    if set(kw) != set(fields[kind]):
        raise ValueError("%s に必要な項目は %s です" % (kind, "・".join(fields[kind])))
    out = {"kind": kind}
    for name in fields[kind]:
        out[name] = _nonempty_str(kw[name], name)
    if kind == "file":
        out["sha256"] = out["sha256"].lower()
        if not _is_hex(out["sha256"], 64):
            raise ValueError("sha256 は 64 桁の 16 進数にしてください")
    return out


def file_digest(path, chunk=1 << 20):
    """ファイルの内容の sha256(16 進 64 桁)。1MB ずつ読む(巨大な動画でもメモリを食わない)。読めなければ OSError"""
    h = hashlib.sha256()
    with open(path, "rb") as f:
        while True:
            b = f.read(chunk)
            if not b:
                break
            h.update(b)
    return h.hexdigest()


def _norm(v):
    """鍵の入力を正規化する。float は小数 3 桁(ミリ秒)に丸め、整数と同じ値なら int にする(12.0 と 12 を同じにする)。
    理由: 秒の値は計算の経路で 12.3456789 と 12.3460001 のように揺れる。丸めずにハッシュすると同じ区間なのに鍵が食い違い、
    使い回しの当たり率が下がる(ミリ秒より細かい違いは映像の上で意味がない)。
    int・str・bool・None は変えない。list(tuple も)・dict(キーは str だけ)は中まで。NaN・無限大は ValueError、ほかの型は TypeError"""
    if v is None or isinstance(v, (bool, str)):
        return v
    if isinstance(v, int):
        return v
    if isinstance(v, float):
        if not math.isfinite(v):
            raise ValueError("NaN・無限大は鍵に入れられません")
        r = round(v, 3)
        return int(r) if r == int(r) else r
    if isinstance(v, (list, tuple)):
        return [_norm(x) for x in v]
    if isinstance(v, dict):
        if not all(isinstance(k, str) for k in v):
            raise TypeError("鍵の入力の dict のキーは文字列だけです")
        return {k: _norm(x) for k, x in v.items()}
    raise TypeError("鍵の入力に使えない型です: %s" % type(v).__name__)


def canon(obj):
    """ハッシュする前の正規の JSON 文字列(キーを並べ替え・空白なし・日本語はそのまま)。同じ中身なら同じ文字列になる"""
    return json.dumps(obj, sort_keys=True, separators=(",", ":"), ensure_ascii=False)


def _key_hash(stage, v, inputs):
    # at・madeBy は入れない(いつ・誰が作ったかで鍵が変わると、使い回しの判定にならない)
    return hashlib.sha256(canon({"stage": stage, "v": v, "inputs": inputs}).encode("utf-8")).hexdigest()


def make_key(stage, inputs, made_by=None):
    """成果物の鍵(youtube-tools-key/v1)を作る。inputs は dict(float は _norm で丸める)。
    hash = sha256(canon({stage, v, inputs}))。madeBy({name, version})と at(書いた日時)は付けるがハッシュには入らない"""
    if stage not in KEY_STAGES:
        raise ValueError("段が正しくありません: %r(%s のどれか)" % (stage, "・".join(KEY_STAGES)))
    if not isinstance(inputs, dict):
        raise TypeError("inputs は dict にしてください")
    norm = _norm(inputs)
    key = {"schema": KEY_SCHEMA, "v": KEY_VERSION, "stage": stage, "inputs": norm, "hash": _key_hash(stage, KEY_VERSION, norm)}
    if made_by is not None:
        key["madeBy"] = {"name": str(made_by.get("name", "")), "version": str(made_by.get("version", ""))}
    key["at"] = iso_now()
    return key


def validate_key(obj):
    """(key, 警告)。使えるときは (中身の複製, None)、使えないときは (None, 理由)。
    schema・段・hash の形を調べ、inputs からハッシュを計算し直して一致を確かめる(書き換えられた鍵・壊れた鍵を使わない)"""
    if not isinstance(obj, dict):
        return None, "鍵の形式が正しくありません(JSON のオブジェクトではありません)"
    schema = obj.get("schema")
    if schema != KEY_SCHEMA:
        if isinstance(schema, str) and schema.startswith("youtube-tools-key/"):
            return None, "鍵は未対応の版です(%s。このツールが読めるのは %s)" % (schema[:40], KEY_SCHEMA)
        return None, "鍵の schema が %s ではありません" % KEY_SCHEMA
    stage, ver, inputs, h = obj.get("stage"), obj.get("v"), obj.get("inputs"), obj.get("hash")
    if stage not in KEY_STAGES:
        return None, "鍵の stage が正しくありません"
    if not is_int(ver) or ver != KEY_VERSION:
        return None, "鍵の v が正しくありません"
    if not isinstance(inputs, dict):
        return None, "鍵の inputs の形式が正しくありません"
    if not _is_hex(h, 64):
        return None, "鍵の hash が 64 桁の 16 進数ではありません"
    try:
        calc = _key_hash(stage, ver, _norm(inputs))
    except (TypeError, ValueError):
        return None, "鍵の inputs に使えない値があります"
    if calc != h:
        return None, "鍵の hash が inputs と合いません(書き換えられたか壊れています)"
    return json.loads(json.dumps(obj, ensure_ascii=False)), None


def same_key(a, b):
    """2 つの鍵が同じ成果物を指すか(どちらも正しく、段と hash が同じ)。作った日時・作った人は見ない"""
    ka, kb = validate_key(a)[0], validate_key(b)[0]
    return ka is not None and kb is not None and ka["stage"] == kb["stage"] and ka["hash"] == kb["hash"]


def key_path(path, stage):
    """鍵を書く場所(作業用/ の中。動画_0012.mp4 + export → 作業用/動画_0012.export.key.json)。パスの計算だけで IO はしない"""
    if stage not in KEY_STAGES:
        raise ValueError("段が正しくありません: %r" % (stage,))
    return sidecar_path(path, "." + stage + KEY_SUFFIX)
