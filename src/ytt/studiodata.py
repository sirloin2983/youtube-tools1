"""切り抜きスタジオの data.json(読むだけ)の配信の情報(役割で組み直す RS3-0A。2026-10-10 に編集の ed_store から移した。中身は同じ)。

編集の履歴の一覧の配信者・配信の題名(studio_videos)と、文字起こしの配信ごとの文脈(pipeline/transcribe/roster.stream_context の
チャンネル名とコラボ相手 = studio_stream)が読む。置き場所は workdata.STUDIO_DATA(起動時に編集の serve が datadir の規則で入れる)を
呼ぶたびに読む(テストの S.STUDIO_DATA = … が効く)。スタジオのデータは書き換えない。
読む側は呼ぶたびに studiodata.名前 で読む(テストの S.studio_stream の差し替えは編集の serve の名前の受付がここへ届ける)。
"""
import logging

import os

from . import casefiles as _casefiles, errors as _errors, fsio as _fsio, marks as _marks, workdata as _workdata, yturl as _yturl
from .textutil import num as _num

_log = logging.getLogger("ytt.studiodata")

STUDIO_JSON_MAX = 64 * 1024 * 1024   # 読む上限(スタジオの data.json・旧マーカーなど他のツールが書く JSON の上限の 1 か所。これより大きいものは読めない扱い)
SCHEMA = "clip-studio/v1"


# ---------------------------------------------------------------- data.json の行 1 つの読み方(書く側も同じ形で読む)
# スタジオの Store(③)と、スタジオなしの台帳 flow/studiobook(②。RS8 の「URL も CLI で」)が同じ 1 つを使う(Store から下ろした)
def load_live(vid, v):
    """ライブの録画の live(id は録画の id と同じ)。形が合わなければ ValueError(この1件だけ読み飛ばす)"""
    try:
        live = _yturl.check_live(v.get("live"))
    except _errors.ApiError as e:
        raise ValueError("live が正しくありません: %s" % e.message)
    if live["recording"] != vid:
        raise ValueError("live の録画 ID が id と違います")
    return live


def load_video(vid, v):
    """data.json の videos の 1 行 -> メモリの形(全部の形か、案件にした配信の索引の行)。形が合わなければ ValueError(この1件だけ読み飛ばす)"""
    if not isinstance(v, dict) or v.get("id") != vid or v.get("kind") not in ("youtube", "file", "live"):
        raise ValueError("id/kind が正しくありません")
    if "case" in v:   # 案件にした配信の索引の行(B3-4b)
        root = v["case"]
        if not isinstance(root, str) or not root or len(root) > 1000 or not os.path.isabs(root):
            raise ValueError("case が正しくありません")
        out = {"id": vid, "kind": v["kind"], "title": str(v.get("title") or "")[:120], "channel": str(v.get("channel") or "")[:100],
               "rev": v["rev"] if _marks.pos_int(v.get("rev")) else 1,
               "createdAt": _marks.ms_or_now(v.get("createdAt")), "updatedAt": _marks.ms_or_now(v.get("updatedAt")), "case": root}
        if v["kind"] == "live":
            out["live"] = load_live(vid, v)
        return out
    if v["kind"] == "file" and not isinstance(v.get("path"), str):
        raise ValueError("path がありません")
    live = load_live(vid, v) if v["kind"] == "live" else None
    an = v.get("analysis")
    out = {"id": vid, "kind": v["kind"], "title": str(v.get("title") or "")[:120], "channel": str(v.get("channel") or "")[:100],
           "duration": _num(v.get("duration"), 0, 1e6, 0.0), "fileName": str(v.get("fileName") or "")[:200] if v["kind"] == "file" else "",
           "path": v["path"] if v["kind"] == "file" else "", "marks": _marks.drop_archived(_marks.load_marks(v.get("marks")), v["kind"]),
           "analysis": an if isinstance(an, dict) else None, "rev": v["rev"] if _marks.pos_int(v.get("rev")) else 1,
           "createdAt": _marks.ms_or_now(v.get("createdAt")), "updatedAt": _marks.ms_or_now(v.get("updatedAt"))}
    if live:
        out["live"] = live   # live のときだけ持つキー(youtube・file の記録の形は変えない)
    return out


def _case_row(vid, row):
    """案件にした配信(行が case = 案件の根を持つ)-> 案件の 候補.json・採用.json を重ねた全部の形(行の marks は見ない。RS8 B3-4a)。
    案件が見えない(ドライブが外れた・フォルダが消えた・ファイルが壊れた・採用.json にこの配信が無い)ときは、索引の行に
    caseUnseen: true と marks 空の形を足して返す(一覧の行は出す。書く側は 503 にする)。ファイルの更新日時と大きさが同じなら読み直さない"""
    root = row.get("case")
    if not isinstance(root, str) or not root:
        return row
    try:
        cands, adopts = _casefiles.read(root, cached=True)
        v = _casefiles.merge(cands, adopts, str(vid), root)
    except _errors.ApiError as e:
        _log.info("案件を読めません: %s %s", getattr(e, "code", ""), root)
        v = None
    if v is None:
        return dict(row, marks=[], duration=row.get("duration") or 0.0, analysis=None, caseUnseen=True)
    v["case"] = root
    return v


def read(path=None):
    """スタジオの data.json(path を省くと workdata.STUDIO_DATA)を読む。-> dict か None(無い・読めない・大きすぎる・JSON の最上位が dict でない)。
    data.json を直に読む所はここを通す。videos の行が case(案件の根)を持つ配信は、案件の候補.json・採用.json を重ねた全部の形にして返す(B3-4a)"""
    d = _fsio.read_json_or(path if path else _workdata.STUDIO_DATA, None, max_bytes=STUDIO_JSON_MAX)
    if not isinstance(d, dict):
        return None
    vids = d.get("videos")
    if isinstance(vids, dict) and any(isinstance(v, dict) and v.get("case") for v in vids.values()):
        d["videos"] = {k: (_case_row(k, v) if isinstance(v, dict) else v) for k, v in vids.items()}
    return d


def load_all(path=None):
    """-> {"schema", "videos", "groups"}(全部の形。壊れていた・無い・形が違う部分は空の形。呼ぶたびに読み直し、複製を返す)"""
    d = read(path) or {}
    videos, groups = d.get("videos"), d.get("groups")
    return {"schema": d.get("schema") if isinstance(d.get("schema"), str) else SCHEMA,
            "videos": videos if isinstance(videos, dict) else {}, "groups": groups if isinstance(groups, dict) else {}}


def videos(path=None):
    """-> {配信の id: 配信}(読めなければ {})"""
    return load_all(path)["videos"]


def video(vid, path=None):
    """-> 配信 1 本の dict か None"""
    v = videos(path).get(str(vid or ""))
    return v if isinstance(v, dict) else None


_studio_cache = _fsio.StampCache()   # スタジオの data.json のパス → ({videoId: {"channel", "title"}}, コラボのまとまり [[videoId, …]])(更新日時と大きさでキャッシュ)


def _studio_parse(path):
    """スタジオの data.json → ({videoId: {"channel", "title"}}, コラボのまとまり [[videoId, …]])(読めなければ空)"""
    d = read(path)
    out, groups = {}, []
    vids = d.get("videos") if d else None
    if isinstance(vids, dict):
        for vid, v in list(vids.items())[:5000]:
            if isinstance(v, dict):
                out[str(vid)[:40]] = {"channel": str(v.get("channel") or "")[:100], "title": str(v.get("title") or "")[:200]}
    gs = d.get("groups") if d else None
    for g in (list(gs.values())[:2000] if isinstance(gs, dict) else []):
        ms = g.get("members") if isinstance(g, dict) else None
        if isinstance(ms, list):
            groups.append([str(m)[:40] for m in ms[:50] if isinstance(m, str)])
    return out, groups


def _studio_load():
    """切り抜きスタジオの data.json(読むだけ。置き場所は workdata.STUDIO_DATA = 編集の serve の studio_data_path() と同じ規則 = 入口の案件の画面・manage/cases/txindex と同じ)。
    -> ({videoId: {"channel", "title"}}, コラボのまとまり [[videoId, …]])。一覧のたびに大きな data.json を読み直さないよう、
    ファイルの更新日時と大きさが同じなら前の結果を使う。"""
    path = _workdata.STUDIO_DATA
    r = _studio_cache.get(path, _studio_parse)
    _studio_cache.prune([path])   # 覚えるのは今の場所の 1 つだけ
    return r if r is not None else ({}, [])


def studio_videos():
    """-> {videoId: {"channel", "title"}}(履歴の一覧の配信者・配信の題名)"""
    return _studio_load()[0]


def studio_stream(video_id):
    """配信 -> {"channel", "title", "collab": [{"videoId", "channel", "title"}]}(コラボ = スタジオで同じまとまりにした他の配信)。無ければ None"""
    vids, groups = _studio_load()
    vid = str(video_id or "")[:40]
    if vid not in vids:
        return None
    collab, seen = [], {vid}
    for g in groups:
        if vid in g:
            for m in g:
                if m not in seen and len(collab) < 12:
                    seen.add(m)
                    collab.append(dict(vids.get(m) or {"channel": "", "title": ""}, videoId=m))
    return dict(vids[vid], collab=collab)
