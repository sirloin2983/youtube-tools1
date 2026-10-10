"""ツール間の受け渡し(docs/spec/pipeline.md の約束 v1)のうち、読み・保存・.runtime を扱う部品(層 manage)。serve.py から呼ぶ。Python 標準ライブラリだけで動く。

- youtube-tools-clip/v1       … 切り抜きスタジオが mp4 の隣に置く .clip.json を探す・読む・検証する
- 動画の隣への保存            … 同名のファイルがあるときの「上書き / 別名」の規則と、原子的な書き込み
- .runtime/<ツールID>.json    … 実行中のポートの共有と、他のツールの問い合わせ(/api/siblings)

受け渡しの JSON(transcript/v1・cut-plan/v1)と SRT を組み立てる部分(build_*)は、RS3-E5b で pipeline/pack/resolve_export へ移した
(パックが読む形を作る側なので ① に置く。manage から ① を読む向きは正しい)。呼ぶ側は resolve_export.build_transcript_v1 などと読む。

serve.py(17万文字)に直接足さず、ここに分けたのは、将来1つのアプリに統合するときに、この部品ごと移せるようにするため。
ツールに依らない部分(clip/v1 の検証・原子的な書き込み・.runtime)は共通部品 ytt(統合計画の段階2)に移し、ここからはそれを呼ぶ。
"""
import os
import threading

from ytt import fsio, runtime, schemas

TOOL_NAME = runtime.TOOL_APPS["transcribe"]   # 受け渡しの tool.name(互換のため値は変えない)
CLIP_SCHEMA = schemas.CLIP_SCHEMA
TRANSCRIPT_SCHEMA = schemas.TRANSCRIPT_SCHEMA
CUT_PLAN_SCHEMA = schemas.CUT_PLAN_SCHEMA
CLIP_SUFFIX = schemas.CLIP_SUFFIX
MAX_SIDECAR_BYTES = schemas.MAX_CLIP_BYTES   # .clip.json の上限(中身は数百バイト。巨大なファイルを読まない)
MAX_OWN_FILE_BYTES = 64 * 1024 * 1024   # 「前にこのツールが書いたか」を確かめるときに読む上限
EXPORT_FORMATS = {                      # 動画の隣に保存するときの名前の後ろ(拡張子を置き換える)
    "transcript-v1": ".transcript.json",
    "srt": ".srt",
    "cut-plan-v1": ".cut-plan.json",
}
MAX_ALT_NAMES = 999
RUNTIME_TOOLS = runtime.TOOL_APPS       # ツールID → /api/ping の app
SIBLING_TIMEOUT = runtime.PING_TIMEOUT


class PipelineError(Exception):
    """受け渡しの処理のエラー。serve.py が {"error": code, "message": message} の形で返す。"""

    def __init__(self, code, message, status=400):
        super().__init__(message)
        self.code, self.message, self.status = code, message, status


# ---------- 共通(中身は ytt) ----------
read_json_file = fsio.read_json_file     # (path, max_bytes)。NaN・大きすぎるファイルは ValueError
iso_now = schemas.iso_now
is_network_path = fsio.is_network_path   # ネットワーク上のパスは、利用者が押したボタン以外では調べない(NTLM のハッシュを送らないため)


# ---------- youtube-tools-clip/v1(.clip.json) ----------
clip_path_for = schemas.clip_path_for    # 動画_0012.mp4 → 動画_0012.clip.json
validate_clip = schemas.validate_clip    # (clip の複製, None) / (None, 理由)
clip_offset = schemas.clip_offset        # 切り抜きの中の t が元の配信では offset + t(export.actualStart を優先)


def load_clip_file(path):
    """(clip, 警告)。読めない・壊れている・別の版なら (None, 理由)。"""
    return schemas.load_clip_file(path, MAX_SIDECAR_BYTES)


find_clip = schemas.find_clip       # (動画のパス, 長さ=None) → (clip, 警告, .clip.json のパス)。動画の長さと大きく違えば警告(RS3-0A から本体は ytt/schemas = 文字起こしの受付も同じ物を読む)


def resolve_clip_media(clip_json_path, clip, media_exts):
    """.clip.json が指す動画の実際のパス。①media.path にあればそれ ②無ければ動画のフォルダの media.name
    ③それも無ければ、動画のフォルダの「.clip.json と同じ名前 + 動画の拡張子」。見つからなければ None。
    動画のフォルダ = .clip.json が 作業用/ の中なら1つ上(元動画は直下・途中のファイルは 作業用/。2026-09-27)、そうでなければ同じフォルダ。
    (フォルダごと移動した・友人に渡した場合への備え。docs/spec/pipeline.md の 1)"""
    media = clip.get("media") if isinstance(clip.get("media"), dict) else {}
    folders = list(dict.fromkeys([schemas.media_folder(clip_json_path), os.path.dirname(os.path.abspath(clip_json_path))]))
    cands = []
    if isinstance(media.get("path"), str) and media["path"].strip():
        cands.append(media["path"].strip())
    if isinstance(media.get("name"), str) and media["name"].strip():
        base = os.path.basename(media["name"].strip().replace("\\", "/"))   # 名前だけを使う(../ などでフォルダの外を指させない)
        cands += [os.path.join(f, base) for f in folders]
    name = os.path.basename(os.path.abspath(clip_json_path))[:-len(CLIP_SUFFIX)]
    cands += [os.path.join(f, name + ext) for f in folders for ext in sorted(media_exts)]
    for c in cands:
        try:
            if is_network_path(c):   # .clip.json の中身(他人が作ったものかもしれない)でネットワークに接続しない
                continue
            if os.path.isfile(c) and os.path.splitext(c)[1].lower() in media_exts:
                return os.path.abspath(c)
        except (OSError, ValueError):
            continue
    return None


# ---------- 動画の隣への保存 ----------
_beside_lock = threading.Lock()


# 書き込みの部品は ytt.fsio(Windows の一時的なロックのやり直し・一時ファイル → 置き換え・既存を上書きしない作成)
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
    """動画のフォルダの 作業用/ に <動画の名前(拡張子を除く)><suffix> で保存する(途中のファイルは出力先の直下に置かない。
    2026-09-27。ytt.schemas.work_dir。動画がもう 作業用 の中ならそこ)。戻り値 (保存したパス, 上書きしたか)。
    同名があるとき: schema を渡していて、それがこのツールが前に書いた同じ schema のファイルなら上書き。
    それ以外(SRT は常に)は「名前 (2).srt」「名前 (3).srt」… の順に、空いている名前(または前にこのツールが書いた同じ schema のもの)にする。
    書き込みは一時ファイル → 置き換え(書きかけのファイルを他のツールに読ませない)。"""
    if not os.path.isdir(os.path.dirname(os.path.abspath(media_path))):
        raise PipelineError("no_dir", "動画のフォルダが見つかりません: %s" % os.path.dirname(os.path.abspath(media_path)))
    folder = schemas.work_dir(media_path)
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
                        fsio.atomic_write(p, data, fsync_required=True)   # 一時ファイル → 置き換え(失敗したら一時ファイルを消す)
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


# ---------- 実行中のポートの共有(.runtime/<ツールID>.json)と /api/siblings(中身は ytt.runtime) ----------
valid_port = runtime.valid_port


# 中身は ytt.runtime(名前は今までどおり。呼ぶ側は位置で渡す):
runtime_dir = runtime.runtime_dir          # (ツールのフォルダ) → <1つ上>/.runtime。環境変数 YTT_RUNTIME_DIR があればそちら(テスト用)
write_runtime = runtime.write_runtime      # (rdir, ツールID, ポート, 版, 画面の場所="/") 起動時に書く。書けなくても起動は続ける(None)。
                                           # 画面の場所は入口の統合サーバーに取り込まれたときは "/transcribe/"
remove_runtime = runtime.remove_runtime    # (rdir, ツールID, ポート) 正常終了時に消す。自分が書いたもの(同じポート・同じプロセス)のときだけ


def ping(port, expect_app, timeout=SIBLING_TIMEOUT):
    """http://127.0.0.1:<port>/api/ping が応答し、app が expect_app なら True。"""
    return runtime.ping_app(port, timeout) == expect_app


def siblings(rdir, self_id, self_port, timeout=SIBLING_TIMEOUT, self_path="/"):
    """{"tools": {ツールID: ポート}}。.runtime の記録のうち、応答した(app が一致した)ものだけ。自分自身は常に含める。
    入口の統合サーバーに取り込まれたツールがあれば {"paths": {"studio": "/studio/"}} も付く(ytt.runtime.siblings)。"""
    return runtime.siblings(rdir, self_id, self_port, timeout, self_path)
