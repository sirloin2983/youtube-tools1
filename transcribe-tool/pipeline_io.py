"""ツール間の受け渡し(docs/pipeline.md の約束 v1)を扱う部品。serve.py から呼ぶ。Python 標準ライブラリだけで動く。

- youtube-tools-clip/v1       … 切り抜きスタジオが mp4 の隣に置く .clip.json を探す・読む・検証する
- youtube-tools-transcript/v1 … 文字起こしの文書(transcribe/v1)から、受け渡し用の JSON を作る
- youtube-tools-cut-plan/v1   … 「カット済」でない行(残す区間)から、cut2resolve 用の JSON を作る
- SRT                         … 字幕(画面の書き出しと同じ規則)
- 動画の隣への保存            … 同名のファイルがあるときの「上書き / 別名」の規則と、原子的な書き込み
- .runtime/<ツールID>.json    … 実行中のポートの共有と、他のツールの問い合わせ(/api/siblings)

serve.py(17万文字)に直接足さず、ここに分けたのは、将来1つのアプリに統合するときに、この部品ごと移せるようにするため。
ツールに依らない部分(clip/v1 の検証・原子的な書き込み・.runtime)は共通部品 ytt_core(統合計画の段階2)に移し、ここからはそれを呼ぶ。
どの行を「残す」かの規則は resolve_export.is_kept / kept_spans に1か所だけ持ち、ここではそれを使う(規則を二重に持たない)。
"""
import os
import sys
import threading


def _load_core():
    """共通部品 ytt_core を読み込めるようにする(serve.py の _load_core と同じ規則。pipeline_io だけを読み込むテスト・道具のため)。"""
    here = os.path.dirname(os.path.abspath(__file__))
    for d in (os.environ.get("YTT_CORE_DIR"), os.path.dirname(here)):
        if d and os.path.isfile(os.path.join(d, "ytt_core", "__init__.py")):
            if d not in sys.path:
                sys.path.append(d)
            return


_load_core()
import resolve_export  # noqa: E402
from ytt_core import fsio, runtime, schemas  # noqa: E402

TOOL_NAME = "transcribe-tool"
CLIP_SCHEMA = schemas.CLIP_SCHEMA
TRANSCRIPT_SCHEMA = schemas.TRANSCRIPT_SCHEMA
CUT_PLAN_SCHEMA = schemas.CUT_PLAN_SCHEMA
CLIP_SUFFIX = schemas.CLIP_SUFFIX
MAX_SIDECAR_BYTES = schemas.MAX_CLIP_BYTES   # .clip.json の上限(中身は数百バイト。巨大なファイルを読まない)
MAX_OWN_FILE_BYTES = 64 * 1024 * 1024   # 「前にこのツールが書いたか」を確かめるときに読む上限
CLIP_DURATION_TOLERANCE = 3.0           # 動画の長さと .clip.json の durationSec の差がこれを超えたら警告(高速書き出しのずれは数秒)
EXPORT_FORMATS = {                      # 動画の隣に保存するときの名前の後ろ(拡張子を置き換える)
    "transcript-v1": ".transcript.json",
    "srt": ".srt",
    "cut-plan-v1": ".cut-plan.json",
}
MAX_ALT_NAMES = 999
RUNTIME_TOOLS = runtime.TOOL_APPS       # ツールID → /api/ping の app
MAX_RUNTIME_BYTES = runtime.MAX_BYTES
SIBLING_TIMEOUT = runtime.PING_TIMEOUT


class PipelineError(Exception):
    """受け渡しの処理のエラー。serve.py が {"error": code, "message": message} の形で返す。"""

    def __init__(self, code, message, status=400):
        super().__init__(message)
        self.code, self.message, self.status = code, message, status


# ---------- 共通(中身は ytt_core) ----------
read_json_file = fsio.read_json_file     # (path, max_bytes)。NaN・大きすぎるファイルは ValueError
iso_now = schemas.iso_now
_num = schemas.num
is_network_path = fsio.is_network_path   # ネットワーク上のパスは、利用者が押したボタン以外では調べない(NTLM のハッシュを送らないため)


def tool_info(version):
    return {"name": TOOL_NAME, "version": str(version)}


# ---------- youtube-tools-clip/v1(.clip.json) ----------
clip_path_for = schemas.clip_path_for    # 動画_0012.mp4 → 動画_0012.clip.json
validate_clip = schemas.validate_clip    # (clip の複製, None) / (None, 理由)
clip_offset = schemas.clip_offset        # 切り抜きの中の t が元の配信では offset + t(export.actualStart を優先)


def load_clip_file(path):
    """(clip, 警告)。読めない・壊れている・別の版なら (None, 理由)。"""
    return schemas.load_clip_file(path, MAX_SIDECAR_BYTES)


def find_clip(media_path, media_duration=None):
    """動画の隣の .clip.json を探す。戻り値 (clip または None, 警告または None, .clip.json のパスまたは None)。
    media_duration(秒)を渡すと、.clip.json の durationSec と大きく違うときに警告を付ける(clip は使う)。"""
    p = clip_path_for(media_path)
    if not os.path.isfile(p):
        return None, None, None
    clip, warn = load_clip_file(p)
    if clip and media_duration:
        d = _num((clip.get("media") or {}).get("durationSec"))
        if d is not None and abs(d - float(media_duration)) > CLIP_DURATION_TOLERANCE:
            warn = "動画の長さ(%.1f秒)が .clip.json の記録(%.1f秒)と違います。書き出し直した動画かもしれません(元の配信の位置がずれる可能性があります)" % (float(media_duration), d)
    return clip, warn, p


def resolve_clip_media(clip_json_path, clip, media_exts):
    """.clip.json が指す動画の実際のパス。①media.path にあればそれ ②無ければ .clip.json と同じフォルダの media.name
    ③それも無ければ、同じフォルダの「.clip.json と同じ名前 + 動画の拡張子」。見つからなければ None。
    (フォルダごと移動した・友人に渡した場合への備え。docs/pipeline.md の 1)"""
    media = clip.get("media") if isinstance(clip.get("media"), dict) else {}
    folder = os.path.dirname(os.path.abspath(clip_json_path))
    cands = []
    if isinstance(media.get("path"), str) and media["path"].strip():
        cands.append(media["path"].strip())
    if isinstance(media.get("name"), str) and media["name"].strip():
        cands.append(os.path.join(folder, os.path.basename(media["name"].strip().replace("\\", "/"))))   # 名前だけを使う(../ などでフォルダの外を指させない)
    stem = os.path.abspath(clip_json_path)[:-len(CLIP_SUFFIX)]
    cands += [stem + ext for ext in sorted(media_exts)]
    for c in cands:
        try:
            if is_network_path(c):   # .clip.json の中身(他人が作ったものかもしれない)でネットワークに接続しない
                continue
            if os.path.isfile(c) and os.path.splitext(c)[1].lower() in media_exts:
                return os.path.abspath(c)
        except (OSError, ValueError):
            continue
    return None


# ---------- youtube-tools-transcript/v1 ----------
def sorted_segments(doc):
    """文書の行を開始時刻の順に(画面の sortSegs と同じ、開始時刻だけの安定ソート)。時刻が壊れた行は除く。"""
    out = []
    for g in doc.get("segments") or []:
        if not isinstance(g, dict):
            continue
        a, b = _num(g.get("start")), _num(g.get("end"))
        if a is None or b is None or b < a:
            continue
        out.append(g)
    return sorted(out, key=lambda g: float(g["start"]))


def build_transcript_v1(doc, version):
    """文書 → youtube-tools-transcript/v1。時刻は「動画ファイルの先頭 = 0 秒」(文書の保存形式のまま。範囲指定の文字起こしでも同じ)。
    機械の出力(original)・学習用の情報(params・flag・tags・dismissed など)は入れない(受け渡しに不要で、個人データを増やさないため)。
    文字が空の行は入れない(画面の書き出しと同じ)。speaker は speakers の並び順の番号(話者なしは null)。"""
    speakers, index = [], {}
    for s in doc.get("speakers") or []:
        if isinstance(s, dict) and s.get("id") not in (None, "") and s.get("id") not in index:
            index[s["id"]] = len(speakers)
            speakers.append({"id": len(speakers), "name": str(s.get("name") or s["id"])[:60]})
    segs = []
    for g in sorted_segments(doc):
        text = str(g.get("text") or "").strip()
        if not text:
            continue
        segs.append({"id": str(g.get("id") or ""), "start": round(float(g["start"]), 3), "end": round(float(g["end"]), 3), "text": text,
                     "speaker": index.get(g.get("speaker")), "proofed": g.get("proofed") is True, "cut": g.get("cutState") == "cut"})
    out = {"schema": TRANSCRIPT_SCHEMA, "tool": tool_info(version), "createdAt": iso_now(),
           "media": {"path": str(doc.get("sourcePath") or ""), "name": str(doc.get("sourceName") or os.path.basename(str(doc.get("sourcePath") or ""))),
                     "durationSec": _num(doc.get("duration"))}}
    if isinstance(doc.get("clip"), dict):
        out["clip"] = doc["clip"]
    out.update({"title": str(doc.get("title") or ""), "language": str(doc.get("language") or ""), "speakers": speakers, "segments": segs})
    if doc.get("whole") is False:   # 範囲を指定して文字起こしした文書は、その範囲も示す(約束に無い項目。読む側は無視してよい)
        out["transcribedRange"] = {"start": _num(doc.get("start")) or 0.0, "end": _num(doc.get("end"))}
    return out


# ---------- youtube-tools-cut-plan/v1 ----------
def build_cut_plan_v1(doc, version):
    """文書 → youtube-tools-cut-plan/v1。区間 = resolve_export.kept_spans(「カット済」でない・文字のある行を、重なる・接するものでまとめる)。
    行と行の間のすき間は残さない(Resolve パッケージと同じ)。時刻は動画ファイルの先頭基準の秒(フレームへの変換は受け取る側)。"""
    spans = resolve_export.kept_spans(sorted_segments(doc))
    segs = []
    for i, sp in enumerate(spans, 1):
        label = "".join(str(g.get("text") or "").strip() for g in sp["segments"])
        segs.append({"id": "segment-%03d" % i, "start": round(sp["start"], 3), "end": round(sp["end"], 3), "status": "adopted",
                     "label": label[:40] + ("…" if len(label) > 40 else ""), "lines": [str(g.get("id") or "") for g in sp["segments"]]})
    return {"schema": CUT_PLAN_SCHEMA, "tool": tool_info(version), "createdAt": iso_now(),
            "media": {"path": str(doc.get("sourcePath") or ""), "name": str(doc.get("sourceName") or os.path.basename(str(doc.get("sourcePath") or ""))),
                      "durationSec": _num(doc.get("duration"))},
            "title": str(doc.get("title") or ""), "segments": segs}


# ---------- SRT ----------
def wrap_text(text, n):
    """n 文字ごとに改行(画面の wrapText と同じ。文字はコードポイント単位で数える)。n=0 は折り返さない。"""
    if not n:
        return text
    return "\n".join(text[i:i + n] for i in range(0, len(text), n))


def build_srt(doc, wrap=0, speaker_names=False, base=0.0):
    """画面の SRT 書き出し(index.html の exportRows / buildExport)と同じ規則:
    文字が空の行は出さない・終わりが基準より前の行は出さない・開始は 0 未満にしない・話者名は「[名前] 」を頭に付ける。
    動画の隣に保存する SRT は、その動画の先頭を 0 秒にする(base=0。範囲指定の文書でも動画の時刻のまま)。
    カット済の行も出す(字幕は動画全体に対するもの。カットは cut-plan と一緒に cut2resolve が適用する)。"""
    names = {s.get("id"): str(s.get("name") or "") for s in doc.get("speakers") or [] if isinstance(s, dict)}
    cues = []
    for g in sorted_segments(doc):
        text = str(g.get("text") or "").strip()
        a, b = float(g["start"]) - base, float(g["end"]) - base
        if not text or b <= 0:
            continue
        name = names.get(g.get("speaker"), "") if speaker_names and g.get("speaker") else ""
        cues.append((max(0.0, a), b, ("[%s] " % name if name else "") + wrap_text(text, wrap)))
    return resolve_export.srt_text(cues), len(cues)


# ---------- 動画の隣への保存 ----------
_beside_lock = threading.Lock()


# 書き込みの部品は ytt_core.fsio(Windows の一時的なロックのやり直し・一時ファイル → 置き換え・既存を上書きしない作成)
_replace_retry = fsio.replace_retry
_temp_in = fsio.temp_in
_create_new = fsio.create_new


def written_by_us(path, schema):
    """path が、このツールが前に書いた schema のファイルか(schema が同じで、tool.name が transcribe-tool)。
    cut-plan/v1 は他のツールも書ける形式なので、schema だけでなく書いたツールも確かめる(他のツールのファイルを上書きしない)。"""
    try:
        d = read_json_file(path, MAX_OWN_FILE_BYTES)
    except (OSError, UnicodeError, ValueError):
        return False
    return isinstance(d, dict) and d.get("schema") == schema and isinstance(d.get("tool"), dict) and d["tool"].get("name") == TOOL_NAME


def _alt_name(stem, suffix, n):
    return "%s%s" % (stem, suffix) if n == 1 else "%s (%d)%s" % (stem, n, suffix)


def save_beside(media_path, suffix, data, schema=None):
    """動画の隣に <動画の名前(拡張子を除く)><suffix> で保存する。戻り値 (保存したパス, 上書きしたか)。
    同名があるとき: schema を渡していて、それがこのツールが前に書いた同じ schema のファイルなら上書き。
    それ以外(SRT は常に)は「名前 (2).srt」「名前 (3).srt」… の順に、空いている名前(または前にこのツールが書いた同じ schema のもの)にする。
    書き込みは一時ファイル → 置き換え(書きかけのファイルを他のツールに読ませない)。"""
    folder = os.path.dirname(os.path.abspath(media_path))
    if not os.path.isdir(folder):
        raise PipelineError("no_dir", "動画のフォルダが見つかりません: %s" % folder)
    stem = os.path.splitext(os.path.basename(media_path))[0]
    target = os.path.join(folder, stem + suffix)   # エラーの説明用
    try:
        with _beside_lock:
            for n in range(1, MAX_ALT_NAMES + 1):
                p = os.path.join(folder, _alt_name(stem, suffix, n))
                if os.path.lexists(p):
                    # 同じ名前があっても、このツールが前に書いた同じ schema のものなら上書き(別名の「(2)」も同じ扱いにして、書き出すたびに増えないように)
                    if schema and os.path.isfile(p) and written_by_us(p, schema):
                        tmp = _temp_in(folder, data)
                        try:
                            _replace_retry(tmp, p)
                        except BaseException:
                            try:
                                os.unlink(tmp)
                            except OSError:
                                pass
                            raise
                        return p, True
                    continue
                if _create_new(p, data):
                    return p, False
    except PermissionError as e:
        raise PipelineError("no_write", "動画のフォルダに書き込めません(%s)。読み取り専用のフォルダ・同期中のフォルダ・"
                                        "他のアプリで開いているファイルでないか確認してください" % (e.filename or folder))
    except OSError as e:
        hint = "(パスが長すぎる可能性があります。動画を浅いフォルダへ移してください)" if len(target) >= 250 else ""
        raise PipelineError("write_failed", "動画の隣に保存できませんでした: %s%s" % (e.strerror or e.__class__.__name__, hint))
    raise PipelineError("no_name", "同じ名前のファイルが多すぎるため保存できません(%s)" % (stem + suffix))


# ---------- 実行中のポートの共有(.runtime/<ツールID>.json)と /api/siblings(中身は ytt_core.runtime) ----------
valid_port = runtime.valid_port


def runtime_dir(tool_root):
    """<ツールのフォルダの1つ上>/.runtime。環境変数 YTT_RUNTIME_DIR があればそちら(テスト用)。"""
    return runtime.runtime_dir(tool_root)


def write_runtime(rdir, tool_id, port, version):
    """起動時に書く。書けなくても起動は続ける(None を返す)。pid は「自分が書いた記録か」の確認だけに使う。"""
    return runtime.write_runtime(rdir, tool_id, port, version)


def remove_runtime(rdir, tool_id, port):
    """正常終了時に消す。自分が書いたもの(同じポート・同じプロセス)のときだけ。"""
    return runtime.remove_runtime(rdir, tool_id, port)


def read_runtime_entries(rdir):
    """[(ツールID, ポート)]。知らないツールID・名前と中身が合わない・ポートが範囲外のものは捨てる。"""
    out = []
    for tool_id in RUNTIME_TOOLS:
        port = runtime.read_runtime_port(rdir, tool_id)
        if port is not None:
            out.append((tool_id, port))
    return out


def ping(port, expect_app, timeout=SIBLING_TIMEOUT):
    """http://127.0.0.1:<port>/api/ping が応答し、app が expect_app なら True。"""
    return runtime.ping_app(port, timeout) == expect_app


def siblings(rdir, self_id, self_port, timeout=SIBLING_TIMEOUT):
    """{"tools": {ツールID: ポート}}。.runtime の記録のうち、応答した(app が一致した)ものだけ。自分自身は常に含める。"""
    return runtime.siblings(rdir, self_id, self_port, timeout)
