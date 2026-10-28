"""③ 書き出し(クリップマーカー cm/serve.py 由来): store の動画・マークから ffmpeg / yt-dlp でクリップを mp4 にする。

- file 動画は元ファイルを ffmpeg で切り出す。youtube 動画は yt-dlp(疑似モードでは STUDIO_FAKE_MEDIA を ffmpeg で切り出す)。
- 書き出す動画はいつも 30fps(H.264・yuv420p・AAC。作り直しの設定は ytt/normalize.py の1か所)。
  「精密」= veryfast・「高速」= ultrafast で作り直す(どちらも crf 18・位置ちょうど。コピーは fps を変えられないので使わない)。
- 出力先は <出力先>/<動画名>/ (動画ごとのフォルダ)。
- 形は「指定 → 結果」(OPT2 の J2): new_result(spec) → run(spec, res, ctl, on_done) → result_public(res)。
  ジョブの表・同時 1 本・履歴・枠(SLOTS)・取り消しの受付・掲示板は器 = ② の flow/export.ExportJobs(① は表を持たない)。
- 各 item が成功した時点で on_done(video_id, mark_id, "フォルダ/ファイル.mp4", 開始, 終了) を呼ぶ(store がマークを exported にする)。
- 書き出した mp4 ごとに、隣へ youtube-tools-clip/v1 の <名前>.clip.json を書く(notes:docs/spec/pipeline.md の 2.1。書けなくても書き出しは成功扱いで、警告だけ出す)。
"""
import concurrent.futures
import glob
import json
import os
import re
import subprocess
import time

from ytt import yturl as _yturl   # URL・動画 ID の形と入力の判定(sources.py を畳んだ)
from ytt import fsio as _fsio, jobs, loudness as _loud, names as _names, normalize as _norm, runtime as _runtime, schemas, tools as _tools
from ytt import mediainfo as _media, procs as _procs, studio_env as _env   # RS3-4 にスタジオの common から(呼ぶたびに持ち主から読む)
from ytt import marks as _marks   # 余白の上限(LD-2f)
from ytt.errors import ApiError
from ytt.textutil import fmt_ts, permission_message, redact   # 純粋な関数(差し替えない)
from . import outcheck as _outcheck   # 書き出しのあとの自動の点検(知らせるだけ)


MAX_EXPORT_CLIPS = 50
MAX_CLIP_SEC = 3600
EXPORT_IDLE = 600   # 書き出しのコマンドが、この秒数まったく出力しなければ中止
_STATS_TIME = re.compile(r"time=(\d+):(\d+):(\d+(?:\.\d+)?)")   # ffmpeg の統計の行の位置(yt-dlp の区間取得が流す。_pump_once の進み具合)
DEFAULT_EXPORT_VOLUME = 75   # 書き出しの音量(%)。元の音量(100)だと大きすぎるとのことで既定は下げ気味
MIN_EXPORT_VOLUME, MAX_EXPORT_VOLUME = 1, 200
# ラウドネス(聞こえ方の音量。LUFS)をそろえる(音量(%)の代わりに選べる)。YouTube は再生時に約 -14 LUFS に下げるので、それを目安にする
# 選べる値・ピークの上限・上げる量の上限と、測った結果の読み方は ytt/loudness.py の1か所(パック作りと共通)
LOUDNESS_CHOICES = _loud.CHOICES
TRUE_PEAK_CEIL = _loud.TRUE_PEAK_CEIL   # 上げたときに音が割れないよう、ピーク(トゥルーピーク)をこれより上げない(dBTP)
MAX_GAIN_DB = _loud.MAX_GAIN_DB         # 静かすぎる切り抜きを持ち上げすぎない(雑音まで大きくなる)
EDIT_HANDLE_SEC = 10.0   # 編集用素材の前後の上乗せ(秒)。10-29 から使わない(ytt/marks.CLIP_MARGIN_FIXED = 本体と同じ範囲)。edit_handle()


def edit_handle():
    """編集用素材を本体の範囲(余白つき)からさらに前後に広げる秒: 余白が固定(marks.CLIP_MARGIN_FIXED)なら 0 = 本体と同じ範囲"""
    return 0.0 if _marks.CLIP_MARGIN_FIXED else EDIT_HANDLE_SEC
# 名前の規則(MAX_PATH_UNITS・SUFFIX_ROOM・BASE_ROOM・予約名・UTF-16 の長さ・持ち主の印・連番)は ytt/names.py の 1 か所
# (入口のライブの書き出し src/flow/live_export.py と同じ規則)。ここの名前はテストと他の部品が読むので残す
MAX_PATH_UNITS, SUFFIX_ROOM, BASE_ROOM = _names.MAX_PATH_UNITS, _names.SUFFIX_ROOM, _names.BASE_ROOM
compact_ts, safe_name, is_reserved, path_units, trim_units = _names.compact_ts, _names.safe_name, _names.is_reserved, _names.path_units, _names.trim_units
unique_base, _read_owner, _write_owner = _names.unique_base, _names.read_owner, _names.write_owner
LOG_MAX = 200000    # export-log.txt がこれを超えたら export-log.old.txt に回す
# 書きかけの印(設計レビュー studio の 4)。書き出しは <base>.partial.mp4 に書き、音量・ラウドネスまで仕上がったら <base>.mp4 へ置き換える
# (途中で止まった・落ちたときに、壊れた・仕上がっていないファイルが完成品と同じ名前で残らないように)
PARTIAL = _names.PARTIAL
partial_path, is_partial, final_path = _names.partial_path, _names.is_partial, _names.final_path


class ExportError(Exception):
    pass


def log_export(note, cmd, tail):
    """失敗の切り分け用に、実行コマンドとツールの出力を <出力先>/export-log.txt に残す。"""
    try:
        d = _env.get_out_dir()
        os.makedirs(d, exist_ok=True)
        p = os.path.join(d, "export-log.txt")
        _env.rotate_log(p, LOG_MAX)   # 消さずに1世代(export-log.old.txt)残す(失敗の直後に大きくなって消える、を防ぐ)
        with open(p, "a", encoding="utf-8") as f:
            f.write("[%s] %s\n  cmd: %s\n  out: %s\n\n" % (time.strftime("%Y-%m-%d %H:%M:%S"), note, redact(" ".join(map(str, cmd))), " | ".join(redact(l) for l in tail[-12:])))
    except OSError:
        pass


_ERR_RE = re.compile(r"error|fail|forbidden|denied|invalid|not found|unable|HTTP|403|404|410|timed out|Unsupported|ERROR", re.I)


def reason(tail, n=3):
    """ツールの出力から、失敗の理由らしい行を選ぶ(なければ末尾)。"""
    lines = [redact(l)[:200] for l in (tail or [])]
    key = [l for l in lines if _ERR_RE.search(l) and "Stream #" not in l]
    return " / ".join((key or lines)[-n:])


def verify_output(path, expected, tail=None):
    """出力が空・壊れていないかを確認する。ffmpeg は開始位置が元動画の長さを超えても正常終了(空ファイル)するため必須。"""
    dur, has_v, _a, vline = _media.media_info(path)
    log_export("出力の映像情報: " + os.path.basename(path), [], [vline])
    if not has_v or dur is None or dur < max(0.5, expected * 0.5):
        detail = (" 詳細: " + reason(tail, 2)[:300]) if tail else ""
        raise ExportError("書き出したファイルが空か短すぎます(長さ %s 秒 / 期待 %.0f 秒)。%s" % ("不明" if dur is None else "%.1f" % dur, expected, detail))


def pick_folder(spec):
    """動画ごとの保存先フォルダ(<出力先>/<動画名>/)を決める。-> (フォルダ名, パス)。
    フォルダ内の 作業用/.studio-id に動画IDを記録し、同名の別動画とは混ざらないよう連番を付ける(ytt.names.pick_folder)。"""
    got = _names.pick_folder(_env.get_out_dir(), spec["title"], spec["videoId"], spec["videoId"])
    if got is None:
        raise ExportError("保存先フォルダを作れませんでした")
    return got


def promote(path):
    """仕上がった書きかけのファイルを本当の名前へ置き換える(ytt.fsio.replace_retry。一時的な共有違反は再試行)。本当の名前を返す。"""
    if not is_partial(path):
        return path
    final = final_path(path)
    info = _media.media_info_known(path)
    _fsio.replace_retry(path, final)
    _media.remember_media_info(final, info)   # 中身は同じ(.clip.json を書くときに測り直さない)
    return final


def _rm(*paths):
    """消せなくても続ける(使用中など)"""
    for p in paths:
        _fsio.unlink_quiet(p)


def drop_partial(path):
    """失敗・中止のときに書きかけを消す(音量の調整の途中の .vol.mp4 も)。書きかけでない(仕上がった)ファイルは消さない。"""
    if path and is_partial(path):
        _rm(path, path + ".vol.mp4")


def clean_partials(root=None, busy=None):
    """前回の途中で残った書きかけ(<出力先>/<動画>/ と その 作業用/ の *.partial.*)を消す(起動時に裏で1回)。
    busy: 書き出しが動いているかを返す関数(器 = ② の flow/export が持つ。真になったらやめる)。
    スタジオの印(.studio-id)のあるフォルダだけ(利用者が手で置いたファイルは触らない)。消した数を返す"""
    root = root or _env.get_out_dir()
    n = 0
    try:
        folders = [e.path for e in os.scandir(root) if e.is_dir()]
    except OSError:
        return 0
    for folder in folders:
        if _read_owner(folder) is None:
            continue
        for d in (folder, os.path.join(folder, schemas.WORK_DIR)):
            for f in glob.glob(glob.escape(d) + os.sep + "*" + PARTIAL + ".*"):
                if busy and busy():   # 起動の直後に書き出しが始まったら、その書きかけを消さないようにやめる
                    return n
                try:
                    os.unlink(f)
                    n += 1
                except OSError:
                    pass
    return n


# ---------- 依頼の検査 → spec ----------
def _bad(message):
    return ApiError("bad_request", message, 400)


def _bad_opt(detail):
    """画面が送った書き出しの設定の形が違う(画面の不具合でだけ起きる)。欄の名前(precision など)は本文に出さず detail へ(見直し S6)"""
    return ApiError("bad_request", "書き出しの設定が正しくありません(画面の不具合です。画面を読み込み直してから、もう一度試してください)", 400, {"detail": detail})


def _parse_opts(req):
    """precision・volume・loudness の検査(spec_from_video と build_section_spec で共通)。-> (precision, 音量%, ラウドネス or None)"""
    prec = req.get("precision")
    if prec not in (None, "accurate", "fast"):
        raise _bad_opt("precision")
    vol = req.get("volume", DEFAULT_EXPORT_VOLUME)
    if vol is None:
        vol = DEFAULT_EXPORT_VOLUME
    try:
        vol = int(vol)
    except (TypeError, ValueError):
        raise _bad_opt("volume")
    if not (MIN_EXPORT_VOLUME <= vol <= MAX_EXPORT_VOLUME):
        raise _bad_opt("volume: %d〜%d" % (MIN_EXPORT_VOLUME, MAX_EXPORT_VOLUME))
    loud = req.get("loudness")
    if loud in (None, False, 0):
        loud = None
    else:
        try:
            loud = float(loud)
        except (TypeError, ValueError):
            raise _bad_opt("loudness")
        if loud not in LOUDNESS_CHOICES:
            raise _bad_opt("loudness: " + " / ".join("%g" % x for x in LOUDNESS_CHOICES))
    return prec, vol, loud


def _margin(req):
    """margin(切り抜きの動画の前後に足す余白の秒。LD-2f)。10-29 から固定(marks.clip_margin。要求の値は読まない = スタジオの画面・② の自動とも)。
    スイッチ marks.CLIP_MARGIN_FIXED を切れば ② の束の export.margin が送る値(無い = 0。形が違えば 400)"""
    if _marks.CLIP_MARGIN_FIXED:
        return _marks.clip_margin()
    v = req.get("margin")
    if v is None:
        return 0.0
    if not schemas.is_num(v) or not 0 <= v <= _marks.CLIP_MARGIN_MAX:
        raise _bad_opt("margin: 0〜%g" % _marks.CLIP_MARGIN_MAX)
    return float(v)


def _max_height(req):
    """maxHeight(画質の上限)。決まった値以外は 0 = 上限なし"""
    try:
        mh = int(req.get("maxHeight") or 0)
    except (TypeError, ValueError):
        mh = 0
    return mh if mh in (480, 720, 1080, 1440, 2160) else 0


def _need_ffmpeg():
    if not _env.find_tool("ffmpeg"):
        raise ApiError("no_ffmpeg", "ffmpeg(書き出しに使う道具)が入っていません。黒い画面で winget install Gyan.FFmpeg を実行し、start.bat で起動し直してください", 400)   # 見直し S4: 「PATH に通す」は使う人に分からない


def _youtube_source(spec):
    """YouTube の動画の取り元を spec に入れる(yt-dlp。疑似モードでは STUDIO_FAKE_MEDIA のファイルを切り出す)"""
    if _env.fake():
        spec.update(mode="file", sourcePath=_env.fake_media())
    else:
        if not _env.find_tool("yt-dlp"):
            raise ApiError("no_ytdlp", "yt-dlp が見つかりません(README の準備手順を確認してください)", 400)
        spec["mode"] = "url"


def check_section_path(raw):
    """区間の書き出し(部品)の path(入口から来る値)を検査して、絶対パスを返す。
    絶対パス・.mp4・書き出し先の中(realpath で比べる)・親フォルダが実在・まだ無いファイル(上書きしない)だけ。"""
    if not isinstance(raw, str) or not raw or len(raw) > 1000 or "\x00" in raw or not os.path.isabs(raw):
        raise _bad("path は絶対パスで指定してください")
    path = os.path.abspath(raw)
    name = os.path.basename(path)
    # % は yt-dlp の出力テンプレートで意味を持つ。.partial で終わる名前は書きかけと区別できなくなる。予約名・制御文字は Windows で作れない
    if os.path.splitext(name)[1].lower() != ".mp4" or re.search(r"[\x00-\x1f%]", name) or is_reserved(name) or is_partial(path) or name != name.strip():
        raise _bad("path は .mp4 の正しい名前で指定してください")
    if path_units(path) + SUFFIX_ROOM > MAX_PATH_UNITS:
        raise _bad("path が長すぎます(途中のファイルの名前の分を残して %d 文字まで)" % (MAX_PATH_UNITS - SUFFIX_ROOM))
    if not _env.is_inside_out_dir(path):
        raise _bad("path は書き出し先のフォルダの中だけ指定できます")
    if not os.path.isdir(os.path.dirname(path)):
        raise _bad("path の親フォルダがありません")
    if os.path.lexists(path):
        raise _bad("同じ名前のファイルがすでにあります(上書きしません)")
    return path


def build_section_spec(req):
    """区間の書き出し(部品)の依頼 {videoId, start, end, path, volume?, loudness?, maxHeight?, precision?} → spec(器の start に渡す)。
    スタジオの配信・マークは見ない(登録の無い videoId でもよい)。作るのは YouTube の videoId の start〜end(アーカイブの秒)を、
    今の YouTube の書き出し(run_ytdlp: 区間取得 → 正確に切る → 30fps → 音量/ラウドネス)と同じ中身で、ちょうど path へ。"""
    vid = req.get("videoId")
    if not isinstance(vid, str) or not _yturl.VID_RE.match(vid):
        raise _bad("配信の ID が正しくありません(YouTube の ID は 11 文字)")
    s, e = schemas.num(req.get("start")), schemas.num(req.get("end"))   # 有限の数(bool・NaN・float にできない巨大な整数は None)
    if s is None or e is None:
        raise _bad("start・end が数値ではありません")
    if s < 0 or e <= s:
        raise _bad("start・end が正しくありません(0 ≤ start < end)")
    if e - s > MAX_CLIP_SEC:
        raise _bad("区間が長すぎます(%d 秒まで)" % MAX_CLIP_SEC)
    path = check_section_path(req.get("path"))
    prec, vol, loud = _parse_opts(req)
    _need_ffmpeg()
    stem, folder_path = os.path.splitext(os.path.basename(path))[0], os.path.dirname(path)
    item = {"id": "section", "start": round(s, 3), "end": round(e, 3), "title": stem, "label": "", "src": "manual", "markStatus": ""}
    spec = {"videoId": vid, "title": stem, "clips": [item], "fast": prec == "fast", "maxHeight": _max_height(req),
            "volume": vol, "loudness": loud, "kind": "youtube", "sourceTitle": "", "sourceFile": None, "sourceDuration": 0, "combine": False,
            "section": True, "finalPath": path, "outDir": folder_path, "folder": os.path.basename(folder_path)}
    _youtube_source(spec)
    return spec


def spec_from_video(v, req):
    """書き出しの指定(束)を配信の dict v から組む。台帳(スタジオの Store・StudioBook)から v を引くのは ② flow/export.build_spec(① は台帳を知らない)。
    クライアントからは {id, markIds, precision, maxHeight} だけを受け取り、パス・タイトル・時刻は v(サーバーの配信の中身)から組み立てる。"""
    if v["kind"] == "live":   # 録画はスタジオのサーバーからは取りに行かない(入口のライブの書き出しが録画待ち・取得・30fps をする)
        raise _bad("ライブの録画は、画面の「マークしたらすぐ書き出す」から書き出します(この書き出しでは行えません)")
    ids = req.get("markIds")
    if not isinstance(ids, list) or not ids or not all(isinstance(i, str) for i in ids):
        raise _bad("書き出すマークを選んでください")
    if len(ids) > MAX_EXPORT_CLIPS:
        raise _bad("書き出すマークは1度に%d件までです" % MAX_EXPORT_CLIPS)
    prec, vol, loud = _parse_opts(req)
    by_id = {m["id"]: m for m in v["marks"]}
    clips, seen = [], set()
    for i in ids:
        m = by_id.get(i)
        if m is None or i in seen:
            continue
        seen.add(i)
        clips.append({"id": i, "start": m["start"], "end": m["end"], "title": m["label"] or compact_ts(m["start"]), "label": m["label"],
                      "src": m.get("src") or "manual", "markStatus": m.get("status") or ""})
    if not clips:
        raise _bad("書き出せるマークがありません(削除されたか、範囲が正しくありません)")
    combine = req.get("combine") is True   # 選んだマークを時刻の順につないで1本の mp4 に(ユーザー要望)
    if combine:
        if len(clips) < 2:
            raise _bad("つなげるマークを2つ以上選んでください")
        clips.sort(key=lambda c: c["start"])
        if sum(c["end"] - c["start"] for c in clips) > MAX_COMBINE_SEC:
            raise _bad("つなげた長さが長すぎます(%d分まで)" % (MAX_COMBINE_SEC // 60))
    _need_ffmpeg()
    spec = {"videoId": v["id"], "title": v["title"] or v["fileName"] or v["id"], "clips": clips, "fast": prec == "fast",
            "maxHeight": _max_height(req), "volume": vol, "loudness": loud,
            # .clip.json 用(元の配信の情報)。元のファイルのパスは file のときだけ入れる
            "kind": v["kind"], "sourceTitle": v["title"] or v.get("fileName") or "", "sourceFile": v["path"] if v["kind"] == "file" else None,
            "sourceDuration": v.get("duration") or 0, "combine": combine}
    margin = _margin(req)
    if margin and not combine:   # 余白(LD-2f)。つないで 1 本にするときは足さない(つなぎ目に余白が入る)
        spec["margin"] = margin
    if v["kind"] == "file":
        if not os.path.isfile(v["path"]):
            raise ApiError("no_file", "元の動画ファイルが見つかりません(移動・削除されていないか確認してください)", 400)
        spec.update(mode="file", sourcePath=v["path"])
    else:
        if not _env.fake() and not _yturl.VID_RE.match(str(v["id"])):   # yt-dlp に渡す URL は、検査済みの動画IDだけから組み立てる(data.json を手で直された場合の備え)
            raise ApiError("bad_request", "YouTube の配信の ID が正しくありません", 400)
        _youtube_source(spec)
    return spec


PUBLIC_PATHS = ("path", "manifest", "editPath", "editManifest")


def new_result(spec):
    """書き出しの結果の辞書(OPT2 の J2。純粋): run が state・folder・items(各本の status・progress・file・path…)・combined を書き込む。
    器(② の flow/export.ExportJobs)が id・outDir・waiting・created を自分の記録に持ち、public で今の GET /api/export の形にまとめる"""
    return {"videoId": spec.get("videoId"), "state": "running", "folder": "", "combined": None,
            "items": [dict(c, status="queued", progress=0.0, file=None, error=None) for c in spec["clips"]]}


def result_public(res):
    """GET /api/export の中身のうち結果の分(state・folder・items・combined)。各 item の path(書き出した mp4 の絶対パス)と
    manifest(隣の .clip.json の絶対パス。書けなければ null)は完了した item だけに入る(画面の「編集で開く」リンク ?media=<path> 用)。
    editPath / editManifest は前後10秒の編集用素材"""
    def paths(it):
        done = it["status"] == "done"
        return {k: (it.get(k) if done else None) for k in PUBLIC_PATHS}
    return {"state": res["state"], "folder": res.get("folder", ""),
            "items": [{**{k: it[k] for k in ("id", "start", "end", "title", "status", "progress", "file", "error")},
                       "warning": it.get("warning", ""), "loudness": it.get("loudness"), "encoder": it.get("encoder"), "check": it.get("check"), **paths(it)}
                      for it in res["items"]],
            "combined": _combined_public(res.get("combined"))}


def _combined_public(c):
    """つないだ1本(combine のときだけ)。path は出来上がったときだけ"""
    if not c:
        return None
    done = c.get("status") == "done"
    return {"status": c.get("status"), "progress": c.get("progress", 0.0), "file": c.get("file") if done else None, "path": c.get("path") if done else None,
            "error": c.get("error"), "loudness": c.get("loudness"), "count": c.get("count", 0), "seconds": round(float(c.get("end") or 0), 1)}


def _pump(ctl, cmd, it, dur, span=(0.0, 1.0)):
    """コマンドを実行して出力を読み、進捗(0〜1)を更新する。失敗時は ExportError。
    EXPORT_IDLE 秒のあいだ出力がなければ止める。中止・時間切れでは子プロセスごと止める。
    span: 2段で作るとき(YouTube の区間取得 → 切り出し)に、この段の進み具合を全体のどこに当てるか。
    ffmpeg が 5.1 より古くて -fps_mode を知らなければ、-vsync に替えて 1 回だけやり直す(ytt/normalize.run_with_legacy。OPT1)"""
    code, tail, why = _norm.run_with_legacy(lambda c: _pump_once(ctl, c, it, dur, span), cmd, cancelled=ctl.is_cancelled)
    if why == "cancel" or ctl.cancelled:
        raise ExportError("中止しました")
    if why == "idle":
        raise ExportError(_procs.idle_message("書き出し", EXPORT_IDLE))
    if code != 0:
        raise ExportError(reason(tail) or "終了コード %s" % code)
    return tail


def _pump_once(ctl, cmd, it, dur, span):
    """_pump の 1 回分。-> (終了コード, 出力の最後の 30 行, 止めた理由 None|"cancel"|"idle")。
    中身は ytt.tools.run_progress(spawn = 終了の流れで止まる・ctl の取り消しを見張りが見て子を止める。OPT2 の J2)。
    進み具合は -progress の out_time と、yt-dlp が流す ffmpeg の統計の行の time=(区間取得)の両方から"""
    lo, hi = span

    def put(sec):
        if dur > 0:
            it["progress"] = min(0.99, lo + (hi - lo) * min(1.0, sec / dur))

    def on_line(line):
        m = _STATS_TIME.search(line)
        if m:
            put(int(m.group(1)) * 3600 + int(m.group(2)) * 60 + float(m.group(3)))

    code, tail, why = _tools.run_progress(cmd, cancelled=ctl.is_cancelled, idle_sec=EXPORT_IDLE, on_time=put, tail=30,
                                          on_line=on_line, spawn=True)
    return code, tail, ("cancel" if ctl.cancelled else why)


def _make(ctl, cmd, it, dur, out, what, log_cmd=None):
    """cmd で out を作り(_pump)、空・短すぎないかを確かめる。失敗したら export-log.txt に残して out を消し、ExportError をそのまま上げる。
    log_cmd: ログに残すコマンド(直接の URL を含むときは省いたものを渡す)"""
    tail = []
    try:
        tail = _pump(ctl, cmd, it, dur)
        verify_output(out, dur, tail)
    except ExportError as e:
        log_export("%s 失敗: %s" % (what, e), cmd if log_cmd is None else log_cmd, tail)
        if os.path.exists(out):
            os.unlink(out)
        raise


# 書き出しの作り直しの設定は ytt/normalize.py の1か所(30fps・GPU か libx264 crf 18・yuv420p・AAC 192k・faststart)
PROGRESS = ["-progress", "pipe:1", "-nostats"]
ENC = _norm.ENC_ARGS + PROGRESS              # 精密(veryfast)の CPU の作り方
SECTION_PAD = 2.0   # YouTube の区間取得で、前後に足す秒数(yt-dlp ではそのまま取り、正確な区間は ffmpeg で切る)
DL_TAG = "_dl"      # 区間取得の途中のファイルの名前(<base>_dl.partial.mp4。作業用/ に置き、切り出したら消す)
EDIT_TAG = "_edit"  # 編集用素材の名前(<base>_edit.partial.mp4。作業用/)
# 区間取得の yt-dlp に渡す ffmpeg の読み方: 10 MB ずつ分けて頼む(1 本の長い取得は YouTube に絞られて遅い)
DL_FFMPEG_ARGS = "ffmpeg_i:-request_size 10485760"
DL_FAST_ENV = "YTT_DL_FAST"   # "0" で分けて頼まない(前の取り方)
_dl_chunk = {}   # ffmpeg のパス -> -request_size を知っているか(1 回だけ確かめる)


def _dl_args(ff):
    """区間取得の yt-dlp に足す引数。ffmpeg が http の -request_size を知っていれば 10 MB ずつ分けて頼む
    (本物の 314 秒の区間で 235 秒 → 9 秒)。YTT_DL_FAST=0・知らない古い ffmpeg では足さない(1 本の長い取得)"""
    if os.environ.get(DL_FAST_ENV, "").strip() == "0" or not ff:
        return []
    if ff not in _dl_chunk:
        try:
            p = _procs.run_short([ff, "-hide_banner", "-h", "protocol=http"], timeout=30)
            _dl_chunk[ff] = p.returncode == 0 and "request_size" in (p.stdout or "")
        except (OSError, subprocess.SubprocessError):
            _dl_chunk[ff] = False
    return ["--downloader-args", DL_FFMPEG_ARGS] if _dl_chunk[ff] else []


def _encs(spec):
    """作り直しの作り方の順 [(作り方の名前, 出力側の引数)](GPU → libx264。ytt/normalize.encode_tries。-progress は呼ぶ側)。
    高速 = libx264 の ultrafast(GPU は同じ)。音量(%)はここで最初の書き出しに組み込む(音声の作り直しは 1 回だけ = AAC の 2 回目の圧縮と
    ファイル全体の読み書きをしない。O3)。ラウドネスのときは測ってから apply_loudness が後でかける(測る前は量が分からないため)"""
    preset = _norm.FAST_PRESET if spec.get("fast") else _norm.PRESET
    vol = spec.get("volume", 100)
    af = [] if vol == 100 or spec.get("loudness") else ["-af", _loud.volume_filter(vol)]
    return [(how, enc + af) for how, enc in _norm.encode_tries(_env.find_tool("ffmpeg"), preset)]


def _encode(ctl, spec, it, build, outs, what, span=(0.0, 1.0), log_cmd=None, tries=None):
    """build(出力側の引数) -> コマンドの全部 で outs([(パス, 期待する長さ)])を作り、空・短すぎないかを確かめる。
    作り方は tries(既定 _encs(spec))の順(GPU で失敗したら outs を消して libx264 で 1 回だけ)。作った作り方は it["encoder"](.clip.json の export.encoder)。
    失敗は export-log.txt に残して outs を消す。最後の作り方も失敗・中止なら ExportError をそのまま上げる"""
    tries = tries or _encs(spec)
    dur = max(d for _p, d in outs)
    for n, (how, enc) in enumerate(tries, 1):
        cmd, tail = build(enc), []
        t0 = time.monotonic()
        try:
            tail = _pump(ctl, cmd, it, dur, span)
            for p, d in outs:
                verify_output(p, d, tail)
            it["expectSec"] = outs[0][1]   # 点検の長さの期待(outcheck)。outs[0] が本体(この時点で it に path はまだ無い)
            it["encoder"] = how
            _secs(it, "encode", time.monotonic() - t0)
            return
        except ExportError as e:
            if how != _norm.CPU and n < len(tries):   # GPU で作れず libx264 へ = 理由を .clip.json に(友人の診断で見る)
                it["gpuError"] = "%s: %s" % (how, str(e)[:200])
            log_export("%s 失敗(%s): %s" % (what, how, e), cmd if log_cmd is None else log_cmd, tail)
            for p, _d in outs:
                if os.path.exists(p):
                    os.unlink(p)
            if ctl.cancelled or n == len(tries):
                raise


def _method(spec):
    """.clip.json の export.mode に使う(fast = 高速の設定で作り直した。どちらも位置ちょうどなので actualStart は無い)"""
    return "fast" if spec.get("fast") else "encode"


def run_ffmpeg(ctl, spec, it, base):
    """戻り値は書きかけ(<base>.partial.mp4)の "フォルダ/名前"。本当の名前へは、仕上げのあと呼び出し側が promote で置き換える"""
    out = partial_path(spec["outDir"], base)
    dur = it["end"] - it["start"]
    src_len, has_v, _a, _l = _media.media_info(spec["sourcePath"])
    if not has_v:
        raise ExportError("指定したファイルから映像を読み取れません(動画ファイルか、壊れていないか確認してください)")
    it["srcLen"] = src_len
    if src_len is not None:
        if it["start"] >= src_len - 0.5:
            raise ExportError("開始 %s が、このファイルの長さ %s を超えています。別の動画ファイルを指定していませんか" % (fmt_ts(it["start"])[:8], fmt_ts(src_len)[:8]))
        dur = min(it["end"], src_len) - it["start"]  # 終了が元動画の末尾を超えるときは末尾まで
    ts, ff = fmt_ts(it["start"]), _env.find_tool("ffmpeg")
    base_cmd = [ff, "-hide_banner", "-nostdin", "-y", "-protocol_whitelist", "file,pipe"]
    # 1) -ss を -i の前に置く高速シーク(作り直すのでフレーム精度で切れる)
    # 2) 出力が空になるファイル向けの予備: -i の後に置く精密シーク(先頭から読むので遅いが確実)
    # 高速・精密のどちらも 30fps に作り直す(高速は x264 の速い設定。コピーでは fps を変えられないため)
    attempts = [lambda enc: base_cmd + ["-ss", ts, "-i", spec["sourcePath"], "-t", "%.3f" % dur] + enc + PROGRESS + [out],
                lambda enc: base_cmd + ["-i", spec["sourcePath"], "-ss", ts, "-t", "%.3f" % dur] + enc + PROGRESS + [out]]
    last = None
    for n, build in enumerate(attempts, 1):
        try:
            _encode(ctl, spec, it, build, [(out, dur)], "ffmpeg 方法%d" % n)
            it["method"] = _method(spec)
            return spec["folder"] + "/" + os.path.basename(out)
        except ExportError as e:
            last = e
            if ctl.cancelled:
                raise
            it["progress"] = 0
    raise last


def expected_len(spec, it):
    """書き出しで期待する長さ。元の長さ(分かれば)を超える分は含めない(元の末尾をまたぐマークは末尾までになるため)。"""
    lim = spec.get("sourceDuration") or 0
    end = min(it["end"], lim) if lim and lim > it["start"] else it["end"]
    return end - it["start"]


FORMAT_SORT = "res,vcodec:h264"   # 同じ高さなら H.264(avc1)を先に(無ければ今どおり AV1・VP9)。AV1 を CPU で読む作り直しが重かった(10-25 友人の PC・1 本 2〜3 分)


def _fsel(spec, hls=False):
    """yt-dlp の -f。hls = HLS(m3u8)の形式だけ(方法3。DASH の形式で中身が届かないときの別の道)"""
    mh = spec["maxHeight"]
    if hls:
        h = "[height<=%d]" % mh if mh else ""
        return "bv*[protocol^=m3u8]%s+ba[protocol^=m3u8]/b[protocol^=m3u8]%s" % (h, h)
    return "bv*+ba/b" if not mh else "bv*[height<=%d]+ba/b[height<=%d]/b" % (mh, mh)


def _ytdlp_cmd():
    """yt-dlp を起動するコマンドの先頭(テストで偽物の yt-dlp に差し替える)。
    --encoding utf-8: Windows の yt-dlp.exe は管にコンソールの文字コード(cp932)で書き、エラーの文の ’ が化ける(PYTHONIOENCODING は効かない)"""
    return [_env.find_tool("yt-dlp"), "--encoding", "utf-8"] + _tools.ytdlp_auth_args()   # 友人の PC でログインしていれば --cookies(ytt/tools)


def _work_dir(spec):
    """途中のファイルを置く 作業用/(編集用素材・つなぐ部品は、spec の出力先がもともと 作業用/)"""
    d = spec["outDir"]
    return d if os.path.basename(os.path.normpath(d)) == schemas.WORK_DIR else os.path.join(d, schemas.WORK_DIR)


def _drop_glob(prefix):
    _rm(*glob.glob(glob.escape(prefix) + ".*"))


def _ytdlp_sections(ctl, spec, it, base, hls=False):
    """方法1(hls = 方法3: 同じ 2 段を HLS の形式で): 2段で作る。
    1) yt-dlp で区間を**そのまま**取る(作り直さない・前後に SECTION_PAD 秒の余裕。作業用/<base>_dl.partial.mp4)
    2) ffmpeg で正確な区間に切り、30fps に作り直す(書き出しと同じ _encs)。取った区間のファイルは最後に消す。
    yt-dlp は区間を ffmpeg の入力側の -ss + コピーで取るので、取ったファイルの 0 秒 = 頼んだ開始(手前のキーフレームからの分は
    mp4 の edit list で隠れる)。万一、頼んだより長い(手前のキーフレームから見えている)ときは位置が分からないので、方法2(直接指定)に回す。
    it["keepRaw"](秒)があれば前後をその秒だけ広く取り、同じ 1 本の ffmpeg で編集用素材(前後その秒つき)も 作業用/<base>_edit.partial.mp4 に
    作って it["editMade"] に書く(読み込み 1 回で 2 本。1 本の切り抜きで YouTube への問い合わせは 1 回。export_edit_media が使う)"""
    lim = spec.get("sourceDuration") or 0
    pad = max(SECTION_PAD, float(it.get("keepRaw") or 0))
    dl_start = max(0.0, float(it["start"]) - pad)
    dl_end = float(it["end"]) + pad
    if lim and lim > it["start"]:
        dl_end = min(dl_end, lim)
    dl_len = dl_end - dl_start
    work = _work_dir(spec)
    os.makedirs(work, exist_ok=True)
    raw_base = os.path.join(work, base + DL_TAG + PARTIAL)   # yt-dlp の途中のファイル .f399.mp4.part なども、この名前から始まる
    _drop_glob(raw_base)   # 前回の残り(yt-dlp は同じ名前があると取得済みとして使ってしまう)
    out = partial_path(spec["outDir"], base)
    ff = _env.find_tool("ffmpeg")
    chunk = _dl_args(ff)

    def dl_cmd(extra):
        return _ytdlp_cmd() + ["--no-playlist", "--no-warnings", "--newline", "--ffmpeg-location", ff,
                               "--download-sections", "*%s-%s" % (fmt_ts(dl_start), fmt_ts(dl_end))] + extra + [
                               "-f", _fsel(spec, hls), "-S", FORMAT_SORT, "--merge-output-format", "mp4", "-o", _yturl.ytdlp_out(work, os.path.basename(raw_base) + ".%(ext)s"),
                               "--", _yturl.watch_url(spec["videoId"])]
    cmd = dl_cmd(chunk)
    tail, stage = [], "dl"
    t_get = time.monotonic()
    try:
        try:
            tail = _pump(ctl, cmd, it, dl_len, span=(0.0, 0.5))
        except ExportError as e:   # 分けて頼む取り方で取れなかった: 1 本の長い取得で 1 回だけ取り直す(止められた・中止はそのまま)
            if not chunk or ctl.cancelled or blocked(e):
                raise
            log_export("yt-dlp 区間取得(分けて頼む)失敗・分けずに取り直す: %s" % e, cmd, [])
            _drop_glob(raw_base)
            cmd = dl_cmd([])
            tail = _pump(ctl, cmd, it, dl_len, span=(0.0, 0.5))
        files = [f for f in glob.glob(glob.escape(raw_base) + ".*")
                 if not f.endswith((".part", ".ytdl", ".temp")) and ".temp." not in os.path.basename(f)]
        if not files:
            raise ExportError("出力ファイルが見つかりませんでした")
        raw = raw_base + ".mp4" if raw_base + ".mp4" in files else sorted(files)[0]
        need = expected_len(spec, it)
        verify_output(raw, need, tail)
        raw_info = _media.media_info(raw)
        raw_len = raw_info[0]
        _secs(it, "get", time.monotonic() - t_get)
        it["input"] = src_shape(raw_info[3])
        if raw_len is not None and raw_len > dl_len + 1.0:
            raise ExportError("取った区間の開始の位置が分かりません(頼んだ %.1f 秒より長い %.1f 秒)" % (dl_len, raw_len))
        off = float(it["start"]) - dl_start   # 取ったファイルの中での開始
        dur = min(need, raw_len - off) if raw_len is not None else need
        if dur < 0.5:
            raise ExportError("取った区間が短すぎます(%.1f 秒)" % (raw_len or 0))
        outs = [(out, dur, off)]
        if it.get("keepRaw") is not None:   # 編集用素材: マーク(余白つき)の前後 keepRaw 秒(0 = 本体と同じ範囲)(0 秒より前・取れた末尾より後へは出さない)
            e_start = max(0.0, float(it["start"]) - float(it["keepRaw"]))
            e_off = max(0.0, e_start - dl_start)
            e_dur = float(it["end"]) + float(it["keepRaw"]) - e_start
            if raw_len is not None:
                e_dur = min(e_dur, raw_len - e_off)
            outs.append((partial_path(work, base + EDIT_TAG), e_dur, e_off))

        def build(enc):   # 読み込みは 1 回(-i の後の -ss = 出力ごとにコマ単位で正確に切る)・出力ごとに同じ作り方
            cmd = [ff, "-hide_banner", "-nostdin", "-y", "-protocol_whitelist", "file,pipe", "-i", raw] + PROGRESS
            for p, d, o in outs:
                cmd += ["-ss", "%.3f" % o, "-t", "%.3f" % d, "-map", "0:v:0", "-map", "0:a:0?", "-sn", "-dn"] + enc + [p]
            return cmd
        stage = "cut"
        _encode(ctl, spec, it, build, [(p, d) for p, d, _o in outs], "yt-dlp 区間取得 → 切り出し", span=(0.5, 1.0))
        it["method"] = _method(spec)
        if len(outs) > 1:
            it["editMade"] = {"path": outs[1][0], "start": dl_start + outs[1][2], "encoder": it.get("encoder")}
        return out
    except ExportError as e:
        if stage == "dl":   # 切り出しの失敗は _encode が残した
            log_export("yt-dlp 区間取得 失敗: %s" % e, cmd, tail)
        if os.path.exists(out):
            os.unlink(out)
        raise
    finally:
        _drop_glob(raw_base)   # 取った区間は、成功・失敗のどちらでも残さない


def stream_urls(spec):
    """yt-dlp -g で映像/音声の直接URLを得る(取得だけで、ダウンロードはしない)。"""
    cmd = _ytdlp_cmd() + ["--no-playlist", "--no-warnings", "-g", "-f", _fsel(spec), "-S", FORMAT_SORT, "--", _yturl.watch_url(spec["videoId"])]
    try:
        p = _procs.run_short(cmd, timeout=90)   # spawn を通す(終了の流れで止められる・窓を出さない)
    except (OSError, subprocess.SubprocessError):
        raise ExportError("yt-dlp を実行できませんでした")
    urls = [l.strip() for l in (p.stdout or "").splitlines() if l.strip()]
    if p.returncode != 0 or not urls or len(urls) > 2 or not all(u.startswith(("https://", "http://")) for u in urls):
        log_export("yt-dlp -g 失敗", cmd, ((p.stderr or "").strip().splitlines() or [""])[-3:])
        raise ExportError("ストリームのURLを取得できません: " + redact(((p.stderr or "").strip().splitlines() or ["不明"])[-1])[:200])
    return urls


def _ytdlp_stream(ctl, spec, it, base):
    """方法2(予備): 直接URLを ffmpeg に渡して、その区間だけ読み込む。方法1で空になる場合に有効。"""
    urls = stream_urls(spec)
    out = partial_path(spec["outDir"], base)
    dur = expected_len(spec, it)
    cmd = [_env.find_tool("ffmpeg"), "-hide_banner", "-nostdin", "-y", "-protocol_whitelist", "file,http,https,tcp,tls,crypto"]
    for u in urls:
        cmd += ["-ss", fmt_ts(it["start"]), "-i", u]
    if len(urls) == 2:
        cmd += ["-map", "0:v:0", "-map", "1:a:0"]
    cmd += ["-t", "%.3f" % dur]
    _encode(ctl, spec, it, lambda enc: cmd + enc + PROGRESS + [out], [(out, dur)], "ストリーム直接指定", log_cmd=["ffmpeg", "...(URLは省略)..."])
    it["method"] = _method(spec)
    return out


# YouTube に止められた(bot 判定・429・ログインの切れ)ときの yt-dlp の字句(小文字)。この失敗のあとは同じ動画へすぐ問い合わせ直さない
# (方法2 も同じ動画の残りの切り抜きも。重ねるほど回線が疑われる)
BLOCKED_WORDS = ("not a bot", "http error 429", "too many requests", "cookies are no longer valid")


def blocked(text):
    """YouTube に止められた失敗の文か"""
    low = str(text or "").lower()
    return any(w in low for w in BLOCKED_WORDS)


def run_ytdlp(ctl, spec, it, base):
    try:
        out = _ytdlp_sections(ctl, spec, it, base)
    except ExportError as e1:
        if ctl.cancelled:
            raise
        if blocked(e1):   # 止められた: 方法2(yt-dlp -g)で叩き直さない
            raise ExportError("方法1(区間取得): %s / 方法2(直接指定): YouTube に止められたので試していません" % str(e1)[:300])
        it["progress"] = 0
        try:
            out = _ytdlp_stream(ctl, spec, it, base)
        except ExportError as e2:
            if ctl.cancelled:
                raise
            both = "方法1(区間取得): %s / 方法2(直接指定): %s" % (str(e1)[:200], str(e2)[:200])
            if blocked(e2):
                raise ExportError(both + " / 方法3(HLS): YouTube に止められたので試していません")
            # 方法3: DASH の形式(方法1・2 が使う)で中身が届かないとき、HLS の形式(別の URL から届く)で同じ 2 段をもう 1 回
            # (10-24 友人の PC で方法1 が 2 秒・音なし、方法2 が空になった。画質は DASH と同じくらいまで選べる)
            it["progress"] = 0
            try:
                out = _ytdlp_sections(ctl, spec, it, base, hls=True)
            except ExportError as e3:
                if ctl.cancelled:
                    raise
                raise ExportError(both + " / 方法3(HLS): %s" % str(e3)[:200])
    return spec["folder"] + "/" + os.path.basename(out)


def _reencode_audio(ctl, it, path, afilter, what):
    """映像は無劣化のまま(-c:v copy)、音声だけフィルタをかけて再エンコードし、元のファイルと置き換える。"""
    tmp = path + ".vol.mp4"
    # 期待する長さは、切り出した動画そのものの長さ(マークの終了が元の末尾を超えると、切り出しは末尾で止まって短くなるため)
    dur = _media.media_info(path)[0] or (it["end"] - it["start"])
    cmd = _loud.reencode_args(_env.find_tool("ffmpeg"), path, tmp, afilter)
    _make(ctl, cmd, it, dur, tmp, what)
    info = _media.media_info_known(tmp)   # _make の確かめで測った結果(置き換えたあとのファイルの中身と同じ)
    _fsio.replace_retry(tmp, path)
    _media.remember_media_info(path, info)


def measure_loudness(ctl, it, path):
    """(統合ラウドネス LUFS, トゥルーピーク dBTP)。無音・測れないときは (None, None)。ffmpeg の loudnorm で測るだけ(書き換えない)"""
    dur = _media.media_info(path)[0] or (it["end"] - it["start"])
    cmd = _loud.measure_args(_env.find_tool("ffmpeg"), path)
    tail = _pump(ctl, cmd, it, dur)
    return _loud.parse("\n".join(tail))


def apply_loudness(ctl, spec, it):
    """切り抜き(と前後10秒つきの編集用素材)の聞こえ方の音量を spec["loudness"](LUFS)にそろえる。
    切り抜き本体で測った分だけ、両方に**同じ量**だけ音量をかける(Resolve で切り抜きと編集用素材を差し替えても音量が変わらないように)。
    上げる量は、どちらのピークも TRUE_PEAK_CEIL を超えない・MAX_GAIN_DB を超えない範囲まで(音が割れない・雑音を持ち上げすぎない)。
    -> it["loudness"] = {"target", "measured", "gainDb"}(無音で測れないときは skipped)"""
    target = spec.get("loudness")
    if not target:
        return
    main = it["path"]
    edit = it.get("editPath")
    edit = edit if edit and os.path.isfile(edit) else None
    paths = [main] + ([edit] if edit else [])
    t0 = time.monotonic()
    got = _both([lambda p=p: measure_loudness(ctl, it, p) for p in paths])   # 本体と編集用素材は別のファイル = 同時に測る・作り直す(結果は 1 本ずつと同じ)
    i, tp = got[0]
    if i is None:
        it["loudness"] = {"target": target, "skipped": "音声が無いか、無音のため測れませんでした"}
        return
    etp = got[1][1] if edit else None
    gain = _loud.gain(target, i, tp, etp)
    if abs(gain) >= _loud.MIN_GAIN_DB:
        _both([lambda p=p: _reencode_audio(ctl, it, p, _loud.gain_filter(gain), "ラウドネス調整") for p in paths])
    it["loudness"] = {"target": target, "measured": round(i, 1), "gainDb": gain}
    _secs(it, "loudness", time.monotonic() - t0)


_SRC_CODEC = re.compile(r"Video:\s*([A-Za-z0-9_]+)")
_SRC_SIZE = re.compile(r"\b(\d{2,5})x(\d{2,5})\b")
_SRC_FPS = re.compile(r"([\d.]+)\s*fps")


def src_shape(line):
    """ffmpeg -i の映像の行 -> {vcodec, height, fps}(分からない欄は None)。書き出しの元の形の印(友人の診断で読み込みの重さを見る)"""
    line = str(line or "")
    c, sz, f = _SRC_CODEC.search(line), _SRC_SIZE.search(line), _SRC_FPS.search(line)
    return {"vcodec": c.group(1) if c else None, "height": int(sz.group(2)) if sz else None, "fps": float(f.group(1)) if f else None}


def _secs(it, key, sec):
    """書き出しの段ごとの秒を it["secs"] に足す(.clip.json の export.secs)"""
    secs = it.setdefault("secs", {})
    secs[key] = round(secs.get(key, 0) + sec, 1)


def _both(fns):
    """呼び出しを同時に(1 つなら今の糸で)-> 結果の並び。失敗は最初の物を上げる(ほかが終わるのを待ってから)"""
    if len(fns) < 2:
        return [f() for f in fns]
    with concurrent.futures.ThreadPoolExecutor(len(fns)) as ex:
        futs = [ex.submit(f) for f in fns]
        concurrent.futures.wait(futs)
    return [f.result() for f in futs]


MAX_COMBINE_SEC = 3600   # つないだ長さの上限(秒)


def _runner(spec):
    """切り出す関数(YouTube は yt-dlp、手元のファイル・疑似モードは ffmpeg)"""
    return run_ytdlp if spec["mode"] == "url" else run_ffmpeg


def _fail(ctl, it, e, context):
    """1本(または つないだ1本)の失敗・中止を it に書く。ExportError は理由をそのまま、
    それ以外(権限・想定外)は studio-errors.log に残して、画面には短い文だけ出す"""
    if isinstance(e, ExportError):
        it["status"] = "cancelled" if ctl.cancelled else "error"
        it["error"] = None if ctl.cancelled else str(e)[:400]
        return
    _env.log_failure(context, e)
    it["status"] = "error"
    it["error"] = permission_message(e) if isinstance(e, PermissionError) else "内部エラー: %s(詳細は studio-errors.log)" % e.__class__.__name__


def _run_combine(res, ctl, spec):
    """選んだマークを1本ずつ 作業用/ に切り出し(音量は切り出しの作り直しの中で)、時刻の順につないで出力先の直下に1本の mp4 を作る。切り出した部品は最後に消す。
    つないだ動画は元の配信の1つの区間ではないので、.clip.json は書かず、マークにも「書き出し済み」を付けない
    (.clip.json の時刻 = 元の配信の時刻 の約束を崩さないため。文字起こしは画面の「編集で開く」から)。ラウドネスは、つないだ1本で測ってそろえる"""
    work = os.path.join(spec["outDir"], schemas.WORK_DIR)
    os.makedirs(work, exist_ok=True)
    pspec = dict(spec, outDir=work, folder=spec["folder"] + "/" + schemas.WORK_DIR)
    comb = res["combined"] = {"status": "queued", "progress": 0.0, "file": None, "path": None, "error": None, "start": 0.0, "end": 0.0,
                              "count": len(res["items"])}
    pieces = []
    try:
        for idx, it in enumerate(res["items"], 1):
            if ctl.cancelled:
                it["status"] = "cancelled"
                continue
            it["status"] = "running"
            try:
                base = unique_base("つなぐ_%02d_%s-%s" % (idx, compact_ts(it["start"]), compact_ts(it["end"])), work)
                rel = _runner(spec)(ctl, pspec, it, base)
                pieces.append(os.path.join(work, os.path.basename(rel)))   # できた直後に後始末の一覧へ(この先で止まっても残さない。M2)
                it["status"], it["progress"] = "done", 1.0
            except Exception as e:
                _fail(ctl, it, e, "つなぐ部品の書き出し")
        if ctl.cancelled or any(i["status"] != "done" for i in res["items"]):
            comb["status"] = "cancelled" if ctl.cancelled else "error"
            comb["error"] = None if ctl.cancelled else "切り出せなかった区間があるので、つなぎませんでした"
            res["state"] = "cancelled" if ctl.cancelled else "error"
            return
        comb["status"] = "running"
        items = res["items"]
        base = unique_base("つなぎ_%s-%s_%d本" % (compact_ts(items[0]["start"]), compact_ts(items[-1]["end"]), len(items)), spec["outDir"])
        out = partial_path(spec["outDir"], base)   # 書きかけに書いて、ラウドネスまで済んだら本当の名前へ
        comb["path"] = out
        concat_pieces(ctl, comb, pieces, out)
        apply_loudness(ctl, spec, comb)
        comb["path"] = promote(out)
        comb["file"] = spec["folder"] + "/" + os.path.basename(comb["path"])
        comb["status"], comb["progress"] = "done", 1.0
        res["state"] = "done"
    except Exception as e:
        _fail(ctl, comb, e, "つなぐ")
        res["state"] = comb["status"]
    finally:
        for p in pieces:
            _rm(p)
        if comb.get("status") != "done":
            drop_partial(comb.get("path"))


def concat_pieces(ctl, it, pieces, out):
    """部品の mp4 を時刻の順につなぐ(再エンコード。つなぎ目で絵と音がずれないように concat フィルタ。音声の無い部品があれば映像だけ)"""
    infos = [_media.media_info(p) for p in pieces]
    has_a = all(i[2] for i in infos)
    total = sum(float(i[0] or 0) for i in infos)
    it["end"] = total
    cmd = [_env.find_tool("ffmpeg"), "-hide_banner", "-nostdin", "-y"]
    for p in pieces:
        cmd += ["-i", p]
    # 部品はもう 30fps だが、つないだ1本も確実に 30fps の固定にする(-filter_complex と -vf は一緒に使えないので、fps はグラフの中で)
    fc = "".join("[%d:v:0]setsar=1,%s[v%d];" % (k, _norm.fps_filter(), k) for k in range(len(pieces)))
    fc += "".join("[v%d]%s" % (k, "[%d:a:0]" % k if has_a else "") for k in range(len(pieces)))
    fc += "concat=n=%d:v=1:a=%d[v]%s" % (len(pieces), 1 if has_a else 0, "[a]" if has_a else "")
    cmd += ["-filter_complex", fc, "-map", "[v]"] + (["-map", "[a]"] if has_a else [])
    tries = _norm.encode_tries(_env.find_tool("ffmpeg"), in_graph=True)   # 音量は部品で済み
    _encode(ctl, {}, it, lambda enc: cmd + enc + PROGRESS + [out], [(out, total)], "つなぐ", tries=tries)


def _drop_edit(it):
    """編集用素材を諦めるとき: 書きかけの素材と、その .edit.json を消す(仕上がった素材は消さない)。"""
    path = it.pop("editPath", None)
    if path and is_partial(path):
        drop_partial(path)
        side = it.pop("editSidecar", None)
        if side:
            _rm(side)


def export_edit_media(ctl, spec, it, base, runner):
    """Create an additional media file with trim handles and a portable sidecar."""
    edit_it = dict(it)
    edit_it.pop("keepRaw", None)    # 編集用素材をもう 1 本は取らない(_edit_edit の書きかけと YouTube への再問い合わせを出さない)
    edit_it.pop("editMade", None)
    edit_it["secs"] = {}            # 浅い写しなので、本体の段ごとの秒に足し込まない
    edit_it["start"] = max(0.0, float(it["start"]) - edit_handle())   # 10-29 から 0 = 本体(余白つき)と同じ範囲
    edit_it["end"] = float(it["end"]) + edit_handle()
    edit_it["progress"] = 0.0
    # 編集用素材と .edit.json は途中のファイルなので 作業用/ に書く(出力先の直下はパックと元動画だけ)
    wspec = dict(spec, outDir=os.path.join(spec["outDir"], schemas.WORK_DIR), folder=spec.get("folder", "") + "/" + schemas.WORK_DIR)
    os.makedirs(wspec["outDir"], exist_ok=True)
    made = it.get("editMade")
    if made and os.path.isfile(made["path"]):   # 本体と同じ ffmpeg で作った(_ytdlp_sections。YouTube へもう問い合わせない)
        media_path = made["path"]
        edit_it.update(start=made["start"], method=_method(spec), encoder=made.get("encoder"))
        rel = wspec["folder"] + "/" + os.path.basename(media_path)
    else:
        rel = runner(ctl, wspec, edit_it, base + EDIT_TAG)   # 書きかけ(<base>_edit.partial.mp4。音量は本体と同じ spec で作り直しの中で)
        media_path = os.path.join(wspec["outDir"], os.path.basename(rel))
    actual, _v, _a, _line = _media.media_info(media_path)
    selection_in = float(it["start"]) - edit_it["start"]
    selected = float(it["end"]) - float(it["start"])
    expected = edit_it["end"] - edit_it["start"]
    handle_after = max(0.0, (actual if actual is not None else expected) - selection_in - selected)
    sidecar = os.path.join(wspec["outDir"], base + ".edit.json")
    # 素材はまだ書きかけ(<base>_edit.partial.mp4)。仕上げのあと _run_job が本当の名前へ置き換えるので、そちらの名前を書く
    data = {"schema": "clip-studio/edit-media/v1", "media": os.path.basename(final_path(media_path)),
            "selectionIn": round(selection_in, 3), "handleBefore": round(selection_in, 3),
            "handleAfter": round(handle_after, 3), "sourceStart": edit_it["start"], "sourceEnd": edit_it["end"]}
    it["editPath"] = media_path   # 先に覚える(.edit.json が書けなかったときも、書きかけを呼び出し側が消せるように)
    it["editSidecar"] = sidecar
    _fsio.write_json(sidecar, data, indent=2)   # Windows の一時的なロックは再試行
    it["editRange"] = (edit_it["start"], edit_it["end"])
    it["editMethod"] = edit_it.get("method")
    it["editEncoder"] = edit_it.get("encoder")
    it["editSrcLen"] = edit_it.get("srcLen")
    return rel


# ---------- youtube-tools-clip/v1(.clip.json) ----------
def _clip_export_info(spec, method, loudness=None, encoder=None, extra=None):
    """.clip.json の export。mode は fast(高速の設定で作り直した)/ precise。どちらも位置ちょうど(range.start が 0 秒)なので actualStart は付けない
    encoder = 映像を作った作り方(libx264・h264_nvenc など。印)・encodeSet = その画質の設定の版(normalize.enc_set)。
    余白つき(LD-2f)の actualStart・margin は write_manifests が足す"""
    info = {"mode": "fast" if method in ("fast", "copy") else "precise"}
    if encoder:
        info["encoder"], info["encodeSet"] = encoder, _norm.enc_set()
    if spec.get("loudness"):
        info["loudness"] = loudness or {"target": spec["loudness"]}   # そろえたラウドネス(音量(%)は使っていない)
    else:
        info["volume"] = spec.get("volume", 100)
    info.update(extra or {})   # 元の形(input)・段ごとの秒(secs)・GPU で作れなかった理由(gpuError)
    return info


TOOL = {"name": _runtime.TOOL_APPS["studio"], "version": ""}   # .clip.json の tool(版は serve.py が SERVER_VERSION を入れる。OPT1 で manifest.py から)


def write_clip(media_path, duration, source, rng, mark, export):
    """mp4 の .clip.json(youtube-tools-clip/v1。ytt.schemas.build_clip)を 作業用/ に書いて、そのパスを返す。失敗したら OSError(呼び出し側で警告にする)。
    UTF-8(BOM なし)で、一時ファイルに書いてから置き換える(書きかけを他のツールに読ませない。ytt.fsio.write_json。作業用/ も作る)。
    (ytt の部品を呼び直さず、ここで直に書く)"""
    path = schemas.clip_path_for(media_path)
    _fsio.write_json(path, schemas.build_clip(media_path, duration, source, rng, mark, export, TOOL))
    return path


def write_manifests(spec, it, mark_status):
    """書き出した mp4(と編集用素材)の .clip.json を 作業用/ に書く。range は元の配信の秒(元の長さを超える分は切り詰める)。"""
    kind = spec.get("kind") or ("file" if spec.get("mode") == "file" else "youtube")
    source = {"kind": kind, "videoId": spec.get("videoId"), "title": spec.get("sourceTitle") or "", "path": spec.get("sourceFile")}
    mark = {"id": it.get("id"), "label": it.get("label"), "status": mark_status, "src": it.get("src")}
    # 元の長さが分かれば、終了をそこで切り詰める(ffmpeg は元の末尾で止まる)

    def end_of(end, src_len):
        lim = src_len or spec.get("sourceDuration") or 0
        return min(end, lim) if lim and lim > 0 else end
    media = it["path"]
    dur = _media.media_info(media)[0]
    ex = _clip_export_info(spec, it.get("method"), it.get("loudness"), it.get("encoder"), {k: it[k] for k in ("input", "secs", "gpuError", "check") if it.get(k)})
    end = end_of(it["end"], it.get("srcLen"))
    if it.get("clipRange"):   # 余白つき(LD-2f): range はマークのまま・動画の 0 秒 = actualStart(schemas.clip_offset が読む)・margin = 実際に足せた前後の秒(印)
        cf, ct = it["clipRange"]
        ex.update(actualStart=cf, margin={"before": round(it["start"] - cf, 3), "after": round(max(0.0, ct - end), 3)})
    it["manifest"] = write_clip(media, dur, source, (it["start"], end), mark, ex)
    if it.get("editPath") and it.get("editRange"):
        es, ee = it["editRange"]
        edur = _media.media_info(it["editPath"])[0]
        ex = _clip_export_info(spec, it.get("editMethod"), it.get("loudness"), it.get("editEncoder"))
        ex.update(purpose="edit-handles", selection={"start": it["start"], "end": it["end"]})   # 切り抜き本体の範囲(元の配信の秒)
        it["editManifest"] = write_clip(it["editPath"], edur, source, (es, end_of(ee, it.get("editSrcLen"))), mark, ex)


def run(spec, res, ctl, on_done=None):
    """① の書き出し(OPT2 の J2): spec(spec_from_video / build_section_spec の束)を書き出し、res(new_result の辞書)に結果を書き込む。
    ctl(ytt/jobs.Ctl)は取り消しの合図だけを見る(子プロセスは run_progress の見張りが止める)。枠(SLOTS)・同時 1 本・履歴は器(② の flow/export)。
    想定外の例外は studio-errors.log に残してそのまま上げる(res を「実行中」のまま残さない後始末は器)"""
    ctl = ctl or jobs.Ctl()
    try:
        if spec.get("section"):
            _run_section(res, ctl, spec)
        else:
            _run_job(res, ctl, spec, on_done)
    except BaseException as e:
        _env.log_failure("書き出し(ジョブ全体)", e)
        raise


def _run_section(res, ctl, spec):
    """区間の書き出し(部品): 1本(YouTube の videoId の区間)を、ちょうど spec["finalPath"] へ作る。
    マーク・配信のデータ・.clip.json・学習の記録・編集用素材は作らない・書かない(呼ぶ側の入口が自分で扱う)。
    中身は _run_job の1本ぶんと同じ(run_ytdlp(音量も)→ ラウドネス → 書きかけを本当の名前へ)"""
    it = res["items"][0]
    final = spec["finalPath"]
    base = os.path.splitext(os.path.basename(final))[0]
    res["folder"] = spec["folder"]
    it["status"] = "running"
    try:
        it["file"] = _runner(spec)(ctl, spec, it, base)   # 書きかけ(<base>.partial.mp4)
        it["path"] = os.path.join(spec["outDir"], os.path.basename(it["file"]))
        apply_loudness(ctl, spec, it)
        if os.path.lexists(final):   # 作っている間に同じ名前ができた: 置き換えると上書きになるので断る
            raise ExportError("書き出し先に同じ名前のファイルができたので、置きませんでした")
        it["path"] = promote(it["path"])
        it["file"] = spec["folder"] + "/" + os.path.basename(it["path"])
        it["status"], it["progress"] = "done", 1.0
    except Exception as e:
        _fail(ctl, it, e, "区間の書き出し")
    finally:
        if it["status"] != "done":   # 失敗・中止: 書きかけを残さない
            drop_partial(it.get("path"))
            drop_partial(partial_path(spec["outDir"], base))
            it["path"] = None
    res["state"] = "done" if it["status"] == "done" else ("cancelled" if ctl.cancelled else "error")


def _run_job(res, ctl, spec, on_done=None):
    try:
        os.makedirs(_env.get_out_dir(), exist_ok=True)
        spec["folder"], spec["outDir"] = pick_folder(spec)
    except (ExportError, OSError) as e:
        _env.log_failure("書き出し先の準備", e)
        for it in res["items"]:
            it["status"], it["error"] = "error", permission_message(e) if isinstance(e, PermissionError) else str(e)[:200]
        res["state"] = "error"
        return
    res["folder"] = spec["folder"]
    if spec.get("combine"):
        return _run_combine(res, ctl, spec)
    stop = None   # YouTube に止められた失敗の文(このあとの切り抜きは yt-dlp を呼ばずに同じ失敗にする)
    for idx, it in enumerate(res["items"], _names.next_clip_number(spec["outDir"])):   # 同じ配信のフォルダにある書き出しの続きの番号から
        if ctl.cancelled:
            it["status"] = "cancelled"
            continue
        if stop:
            it["status"], it["error"] = "error", stop
            continue
        it["status"] = "running"
        try:
            _export_clip(ctl, spec, it, idx, on_done)
        except Exception as e:  # 想定外の失敗でもジョブ全体は止めない
            _fail(ctl, it, e, "クリップ書き出し")
        finally:
            if it["status"] != "done":   # 失敗・中止: 書きかけを残さない(仕上がって本当の名前になったものは消さない)
                drop_partial(it.get("path"))
                _drop_edit(it)
        if spec.get("mode") == "url" and (it.get("blocked") or (it["status"] == "error" and blocked(it.get("error")))):
            stop = it.get("blocked") if it["status"] != "error" else it["error"]
            it.pop("blocked", None)
    res["state"] = "cancelled" if ctl.cancelled else ("error" if any(i["status"] == "error" for i in res["items"]) else "done")


def _pad_item(spec, it):
    """余白(spec の margin。LD-2f)があれば it の start・end を前後に広げる(0 より前・分かっている元の長さより後へは出さない)。
    -> 広げた始まり(元の秒)か None(余白なし = 何もしない)。戻すのは呼び出し側"""
    margin = float(spec.get("margin") or 0)
    if margin <= 0:
        return None
    lim = spec.get("sourceDuration") or 0
    a = max(0.0, float(it["start"]) - margin)
    b = float(it["end"]) + margin
    if lim and lim > it["end"]:
        b = min(b, float(lim))
    it["start"], it["end"] = round(a, 3), round(b, 3)
    return it["start"]


def _export_clip(ctl, spec, it, idx, on_done):
    """_run_job の1本ぶん: 切り出し(音量も)→ 編集用素材 → ラウドネス → 本当の名前へ → マークへの記録・.clip.json。
    失敗は例外で返す(状態と書きかけの片付けは呼び出し側)"""
    # <番号>_<開始>-<終わり>_<ラベル>(パスの長さに収まる分)。unique はここの名前を通す(テストが exporter.unique_base を差し替える)
    base = _names.clip_base(spec["outDir"], idx, it["start"], it["end"], it["label"], unique=unique_base)
    runner = _runner(spec)
    warnings = []
    mark = (it["start"], it["end"])
    clip_from = _pad_item(spec, it)   # 余白(LD-2f): 切り出し・編集用素材の間だけ it の区間を広げる(名前・マーク・.clip.json の range はマークのまま)
    if spec.get("mode") == "url":
        it["keepRaw"] = edit_handle()   # 編集用素材の分まで 1 回で取る(_ytdlp_sections。0 でも同じ 1 回で作る)
    try:
        it["file"] = runner(ctl, spec, it, base)   # 書きかけ(<base>.partial.mp4)
        it["path"] = os.path.join(spec["outDir"], os.path.basename(it["file"]))
        if clip_from is not None:
            got = _media.media_info(it["path"])[0]
            it["clipRange"] = (clip_from, round(clip_from + (got if got else it["end"] - it["start"]), 3))
        try:
            it["editFile"] = export_edit_media(ctl, spec, it, base, runner)
        except Exception as e:
            _drop_edit(it)
            if ctl.cancelled:   # 中止(終了の流れを含む)なら、本体も仕上げずに止める(書きかけは _run_job の finally で消える)
                raise ExportError("中止しました")
            _env.log_failure("Resolve edit media", e)
            warnings.append("Resolve用の編集用素材を作れませんでした: %s" % str(e)[:180])
            if blocked(e):
                it["blocked"] = str(e)[:400]   # 素材で止められた: 次の切り抜きも yt-dlp を呼ばない(_run_job)
    finally:
        it["start"], it["end"] = mark
        it.pop("keepRaw", None)
        made = it.pop("editMade", None)
        if made and made["path"] != it.get("editPath"):   # 作ったが編集用素材として使わなかった(途中で止まった)
            drop_partial(made["path"])
    apply_loudness(ctl, spec, it)   # 編集用素材ができてから、両方に同じ量をかける
    # 仕上がったので本当の名前へ(ここまでに止まったら、書きかけは _run_job の finally で消える)。切り抜き本体 → 編集用素材の順
    it["path"] = promote(it["path"])
    it["file"] = spec["folder"] + "/" + os.path.basename(it["path"])
    if it.get("editPath"):
        try:
            it["editPath"] = promote(it["editPath"])
            it["editFile"] = spec["folder"] + "/" + schemas.WORK_DIR + "/" + os.path.basename(it["editPath"])
        except OSError as e:   # 本体はできているので、編集用素材だけ諦める(作れなかったときと同じ扱い)
            _env.log_failure("Resolve edit media の仕上げ", e)
            _drop_edit(it)
            warnings.append("Resolve用の編集用素材を仕上げられませんでした: %s" % (e.strerror or e.__class__.__name__))
    recorded = False
    if on_done:
        try:
            clip = {"clip": it["clipRange"]} if it.get("clipRange") else {}   # 余白つき(LD-2f)のときだけ = 余白なしは今までと同じ呼び方
            recorded = bool(on_done(spec["videoId"], it["id"], it["file"], it["start"], it["end"], it.get("path"), **clip))
        except Exception as e:   # 動画はできているが、マークへの記録失敗は通知する
            _env.log_failure("書き出し済みマークの保存", e)
            warnings.append("動画は保存できましたが、書き出し済みの記録に失敗しました。再実行前に出力ファイルを確認してください。")
    try:   # 書き出しのあとの自動の点検(長さ・音・黒いコマ・声の途中の切れ)。気になる所は .clip.json の export.check と結果の check に残すだけ(止めない)
        it["check"] = _outcheck.check(it["path"], it.get("expectSec"), _env.find_tool("ffmpeg"))
    except Exception as e:   # 点検は補助。読めなくても書き出しは済んでいる
        _env.log_failure("書き出しのあとの点検", e)
    try:
        # 書き出し中にマークを動かした等で記録されなかったときは、書き出しを始めた時点の判定を入れる
        write_manifests(spec, it, "exported" if recorded else (it.get("markStatus") or ""))
    except Exception as e:   # 受け渡し用の情報が書けなくても、書き出した動画はそのまま使える
        _env.log_failure("切り抜きの情報ファイル(.clip.json)の保存", e)
        it["manifest"] = None
        warnings.append("切り抜きの情報ファイル(.clip.json)を保存できませんでした(動画はそのまま使えます): %s"
                        % (permission_message(e) if isinstance(e, PermissionError) else str(e)[:160]))
    if warnings:
        it["warning"] = " / ".join(warnings)
    it["status"], it["progress"] = "done", 1.0
