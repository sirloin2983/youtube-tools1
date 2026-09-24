"""ツール間の受け渡し(docs/pipeline.md の約束 v1)を扱う部品。serve.py から呼ぶ。Python 標準ライブラリだけで動く。

- youtube-tools-clip/v1       … 切り抜きスタジオが mp4 の隣に置く .clip.json を探す・読む・検証する
- youtube-tools-transcript/v1 … 文字起こしの文書(transcribe/v1)から、受け渡し用の JSON を作る
- youtube-tools-cut-plan/v1   … 「カット済」でない行(残す区間)から、cut2resolve 用の JSON を作る
- SRT                         … 字幕(画面の書き出しと同じ規則)
- 動画の隣への保存            … 同名のファイルがあるときの「上書き / 別名」の規則と、原子的な書き込み
- .runtime/<ツールID>.json    … 実行中のポートの共有と、他のツールの問い合わせ(/api/siblings)

serve.py(17万文字)に直接足さず、ここに分けたのは、将来1つのアプリに統合するときに、この部品ごと移せるようにするため。
どの行を「残す」かの規則は resolve_export.is_kept / kept_spans に1か所だけ持ち、ここではそれを使う(規則を二重に持たない)。
"""
import datetime
import json
import math
import os
import tempfile
import threading
import time
import urllib.request

import resolve_export

TOOL_NAME = "transcribe-tool"
CLIP_SCHEMA = "youtube-tools-clip/v1"
TRANSCRIPT_SCHEMA = "youtube-tools-transcript/v1"
CUT_PLAN_SCHEMA = "youtube-tools-cut-plan/v1"
CLIP_SUFFIX = ".clip.json"
MAX_SIDECAR_BYTES = 256 * 1024          # .clip.json の上限(中身は数百バイト。巨大なファイルを読まない)
MAX_OWN_FILE_BYTES = 64 * 1024 * 1024   # 「前にこのツールが書いたか」を確かめるときに読む上限
CLIP_DURATION_TOLERANCE = 3.0           # 動画の長さと .clip.json の durationSec の差がこれを超えたら警告(高速書き出しのずれは数秒)
EXPORT_FORMATS = {                      # 動画の隣に保存するときの名前の後ろ(拡張子を置き換える)
    "transcript-v1": ".transcript.json",
    "srt": ".srt",
    "cut-plan-v1": ".cut-plan.json",
}
MAX_ALT_NAMES = 999
RUNTIME_TOOLS = {"studio": "clip-studio", "transcribe": "transcribe-tool", "cut2resolve": "cut2resolve"}   # ツールID → /api/ping の app
MAX_RUNTIME_BYTES = 4096
SIBLING_TIMEOUT = 0.3


class PipelineError(Exception):
    """受け渡しの処理のエラー。serve.py が {"error": code, "message": message} の形で返す。"""

    def __init__(self, code, message, status=400):
        super().__init__(message)
        self.code, self.message, self.status = code, message, status


# ---------- 共通 ----------
def _reject_constant(name):
    raise ValueError("NaN / Infinity は JSON として受け付けません: %s" % name)


def read_json_file(path, max_bytes):
    """UTF-8(BOM があっても可)の JSON を読む。max_bytes を超えるファイル・NaN を含むものは ValueError。"""
    with open(path, "rb") as f:
        raw = f.read(max_bytes + 1)
    if len(raw) > max_bytes:
        raise ValueError("ファイルが大きすぎます")
    return json.loads(raw.decode("utf-8-sig"), parse_constant=_reject_constant)


def iso_now():
    """書いた日時(ISO 8601・時差付き。例: 2026-09-24T12:00:00+09:00)。"""
    return datetime.datetime.now().astimezone().isoformat(timespec="seconds")


def tool_info(version):
    return {"name": TOOL_NAME, "version": str(version)}


def _num(v):
    """有限の数(bool は除く)なら float、それ以外は None。"""
    if isinstance(v, bool) or not isinstance(v, (int, float)):
        return None
    v = float(v)
    return v if math.isfinite(v) else None


def is_network_path(p):
    """ネットワーク上のパス(\\\\サーバー\\共有\\… や //サーバー/…、\\\\?\\UNC\\…)か。
    Windows でこうしたパスの存在を確かめるだけで、そのサーバーへ接続して資格情報(NTLM のハッシュ)を送ってしまうため、
    利用者が押したボタン以外(URL の ?media= から自動で呼ばれる clip-info、他人が作った .clip.json の中のパス)では調べない。"""
    return str(p or "").replace("/", "\\").startswith("\\\\")


# ---------- youtube-tools-clip/v1(.clip.json) ----------
def clip_path_for(media_path):
    """動画の隣の .clip.json のパス(拡張子を置き換える。動画_0012.mp4 → 動画_0012.clip.json)。"""
    return os.path.splitext(media_path)[0] + CLIP_SUFFIX


def validate_clip(obj):
    """(clip, 警告)。使えるときは (中身そのもの, None)、使えないときは (None, 理由)。
    知らない項目は残す(前方互換。transcript/v1 に「中身そのもの」を入れる約束のため)。範囲(range)が正しくないものは使わない。"""
    if not isinstance(obj, dict):
        return None, ".clip.json の形式が正しくありません(JSON のオブジェクトではありません)"
    schema = obj.get("schema")
    if schema != CLIP_SCHEMA:
        if isinstance(schema, str) and schema.startswith("youtube-tools-clip/"):
            return None, ".clip.json は未対応の版です(%s。このツールが読めるのは %s)" % (schema[:40], CLIP_SCHEMA)
        return None, ".clip.json の schema が %s ではありません" % CLIP_SCHEMA
    rng = obj.get("range")
    a, b = (_num(rng.get("start")), _num(rng.get("end"))) if isinstance(rng, dict) else (None, None)
    if a is None or b is None or a < 0 or b <= a:
        return None, ".clip.json の range(元の配信の範囲)が正しくありません"
    for key in ("source", "media", "mark", "export", "tool"):
        if key in obj and obj[key] is not None and not isinstance(obj[key], dict):
            return None, ".clip.json の %s の形式が正しくありません" % key
    ex = obj.get("export") or {}
    if "actualStart" in ex and ex["actualStart"] is not None:
        v = _num(ex["actualStart"])
        if v is None or v < 0:
            return None, ".clip.json の export.actualStart が正しくありません"
    return json.loads(json.dumps(obj, ensure_ascii=False)), None   # 呼び出し側が書き換えても元に響かないよう複製


def clip_offset(clip):
    """切り抜きの中の時刻 t が、元の配信では offset + t になる offset(export.actualStart があれば優先)。"""
    ex = clip.get("export") or {}
    v = _num(ex.get("actualStart")) if isinstance(ex, dict) else None
    return v if v is not None and v >= 0 else float(clip["range"]["start"])


def load_clip_file(path):
    """(clip, 警告)。読めない・壊れている・別の版なら (None, 理由)。"""
    try:
        obj = read_json_file(path, MAX_SIDECAR_BYTES)
    except (OSError, UnicodeError, ValueError) as e:
        return None, ".clip.json を読めません(%s)" % (e.__class__.__name__ if isinstance(e, OSError) else str(e)[:80])
    return validate_clip(obj)


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


def _replace_retry(src, dst):
    """os.replace。Windows でウイルス対策・検索インデックスが一瞬ファイルを開いていて失敗することがあるので、少し待って数回やり直す。"""
    for i in range(6):
        try:
            os.replace(src, dst)
            return
        except PermissionError:
            if os.name != "nt" or i == 5:
                raise
            time.sleep(0.05 * (i + 1))


def _temp_in(folder, data):
    fd, tmp = tempfile.mkstemp(dir=folder, prefix=".tmp-", suffix=".part")
    try:
        with os.fdopen(fd, "wb") as f:
            f.write(data)
            f.flush()
            os.fsync(f.fileno())
    except BaseException:
        try:
            os.unlink(tmp)
        except OSError:
            pass
        raise
    return tmp


def _create_new(path, data):
    """path が無いときだけ、書き終えた内容で作る(True)。すでにあれば何もしない(False)。
    一時ファイルに書いてから、ハードリンク(既存のファイルを決して上書きしない)で置く。
    ハードリンクが使えないドライブ(exFAT など)では、存在を確かめてから置き換える(ロックの中なので、このツール同士では競合しない)。"""
    folder = os.path.dirname(path)
    tmp = _temp_in(folder, data)
    try:
        try:
            os.link(tmp, path)
            return True
        except FileExistsError:
            return False
        except (OSError, NotImplementedError, AttributeError):
            if os.path.lexists(path):
                return False
            _replace_retry(tmp, path)
            tmp = None
            return True
    finally:
        if tmp:
            try:
                os.unlink(tmp)
            except OSError:
                pass


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


# ---------- 実行中のポートの共有(.runtime/<ツールID>.json)と /api/siblings ----------
def runtime_dir(tool_root):
    """<ツールのフォルダの1つ上>/.runtime。環境変数 YTT_RUNTIME_DIR があればそちら(テスト用)。"""
    return os.environ.get("YTT_RUNTIME_DIR") or os.path.join(os.path.dirname(os.path.abspath(tool_root)), ".runtime")


def valid_port(v):
    return isinstance(v, int) and not isinstance(v, bool) and 1 <= v <= 65535


def write_runtime(rdir, tool_id, port, version):
    """起動時に書く。書けなくても起動は続ける(None を返す)。pid は参考のためだけ(生きているかの判定には使わない)。"""
    info = {"tool": tool_id, "port": int(port), "version": str(version), "startedAt": iso_now(), "pid": os.getpid()}
    try:
        os.makedirs(rdir, exist_ok=True)
        path = os.path.join(rdir, tool_id + ".json")
        tmp = _temp_in(rdir, json.dumps(info, ensure_ascii=False).encode("utf-8"))
        try:
            _replace_retry(tmp, path)
        except BaseException:
            try:
                os.unlink(tmp)
            except OSError:
                pass
            raise
        return path
    except (OSError, ValueError):
        return None


def remove_runtime(rdir, tool_id, port):
    """正常終了時に消す。ただし、自分が書いたもの(同じポート・同じプロセス)のときだけ
    (別のポートで後から起動した同じツールの記録を消さないため)。"""
    path = os.path.join(rdir, tool_id + ".json")
    try:
        d = read_json_file(path, MAX_RUNTIME_BYTES)
    except (OSError, UnicodeError, ValueError):
        return False
    if not isinstance(d, dict) or d.get("port") != port or d.get("pid") != os.getpid():
        return False
    try:
        os.unlink(path)
        return True
    except OSError:
        return False


def read_runtime_entries(rdir):
    """[(ツールID, ポート)]。知らないツールID・名前と中身が合わない・ポートが範囲外のものは捨てる。"""
    out = []
    for tool_id in RUNTIME_TOOLS:
        try:
            d = read_json_file(os.path.join(rdir, tool_id + ".json"), MAX_RUNTIME_BYTES)
        except (OSError, UnicodeError, ValueError):
            continue
        if isinstance(d, dict) and d.get("tool") == tool_id and valid_port(d.get("port")):
            out.append((tool_id, d["port"]))
    return out


_no_proxy = urllib.request.build_opener(urllib.request.ProxyHandler({}))   # 127.0.0.1 への問い合わせを、環境変数のプロキシに回さない


def ping(port, expect_app, timeout=SIBLING_TIMEOUT):
    """http://127.0.0.1:<port>/api/ping が応答し、app が expect_app なら True。問い合わせ先は 127.0.0.1 に固定(ファイルの内容で別のホストに向けさせない)。"""
    if not valid_port(port):
        return False
    try:
        with _no_proxy.open("http://127.0.0.1:%d/api/ping" % port, timeout=timeout) as r:
            d = json.loads(r.read(65536).decode("utf-8", "replace"))
        return isinstance(d, dict) and d.get("app") == expect_app
    except Exception:   # 応答なし・拒否・時間切れ・壊れた応答は「動いていない」とみなす
        return False


def siblings(rdir, self_id, self_port, timeout=SIBLING_TIMEOUT):
    """{"tools": {ツールID: ポート}}。.runtime の記録を読み、応答した(app が一致した)ものだけ。自分自身は常に含める。
    問い合わせは並列にして、全体でもおよそ timeout 秒で返す。"""
    found = {self_id: self_port}
    entries = [(t, p) for t, p in read_runtime_entries(rdir) if t != self_id]
    results = {}

    def check(tool_id, port):
        if ping(port, RUNTIME_TOOLS[tool_id], timeout):
            results[tool_id] = port

    threads = [threading.Thread(target=check, args=e, daemon=True) for e in entries]
    for th in threads:
        th.start()
    deadline = time.time() + timeout + 0.2
    for th in threads:
        th.join(max(0.0, deadline - time.time()))
    found.update(dict(results))
    return {"tools": found}
