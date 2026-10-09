"""切り抜きスタジオの data.json(読むだけ)の配信の情報(役割で組み直す RS3-0A。2026-10-10 に編集の ed_store から移した。中身は同じ)。

編集の履歴の一覧の配信者・配信の題名(studio_videos)と、文字起こしの配信ごとの文脈(pipeline/transcribe/roster.stream_context の
チャンネル名とコラボ相手 = studio_stream)が読む。置き場所は workdata.STUDIO_DATA(起動時に編集の serve が datadir の規則で入れる)を
呼ぶたびに読む(テストの S.STUDIO_DATA = … が効く)。スタジオのデータは書き換えない。
読む側は呼ぶたびに studiodata.名前 で読む(テストの S.studio_stream の差し替えは編集の serve の名前の受付がここへ届ける)。
"""
from . import fsio as _fsio, workdata as _workdata

STUDIO_JSON_MAX = 64 * 1024 * 1024   # 読む上限(編集の ed_misc.OTHER_JSON_MAX と同じ値。これより大きい data.json は読めない扱い)
_studio_cache = _fsio.StampCache()   # スタジオの data.json のパス → ({videoId: {"channel", "title"}}, コラボのまとまり [[videoId, …]])(更新日時と大きさでキャッシュ)


def _studio_parse(path):
    """スタジオの data.json → ({videoId: {"channel", "title"}}, コラボのまとまり [[videoId, …]])(読めなければ空)"""
    d = _fsio.read_json_or(path, None, max_bytes=STUDIO_JSON_MAX)
    out, groups = {}, []
    vids = d.get("videos") if isinstance(d, dict) else None
    if isinstance(vids, dict):
        for vid, v in list(vids.items())[:5000]:
            if isinstance(v, dict):
                out[str(vid)[:40]] = {"channel": str(v.get("channel") or "")[:100], "title": str(v.get("title") or "")[:200]}
    gs = d.get("groups") if isinstance(d, dict) else None
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
