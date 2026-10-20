# -*- coding: utf-8 -*-
"""④ 文字起こしの一覧と、元の動画・パックの有無・前回のパックの手順(役割で組み直す RS3-E5a)。

- list_transcripts … GET /api/transcripts の items(文書の要約 + 編集・パックの状態 + 配信者 + 元の動画の有無とパック)
- pack_readme … GET /api/edit/pack-readme(前回のパックの Resolve での手順)
文書の読み書きと要約のキャッシュは ③ の human/proof/store(呼ぶたびに store.名前 で読む)。パックの有無の規則は隣の txindex の 1 か所
(入口の案件の画面と同じ判定。txindex を読むのは編集ではここだけ)。スタジオの data.json は ytt/studiodata を読むだけ。
"""
import os
import time

from ytt import errors as _errors, fsio as _fsio, studiodata as _studiodata  # noqa: E402
from human.proof import store  # noqa: E402   文書の要約・編集の内容(呼ぶたびに store.名前 で読む)
from flow import pack as _flowpack  # noqa: E402   パックの手順の作り直し(呼ぶたびに _flowpack.名前 で読む)
from . import txindex  # noqa: E402   パックの有無・パックのフォルダかの判定(規則の 1 か所)

PACK_CHECK_BUDGET = 2.0   # 秒。一覧1回でパック・動画の有無を調べる時間の上限(外付けの取り外し・つながらないネットワークドライブで一覧が止まらないように)


def _files_state(items):
    """一覧の各文書の、元の動画の有無(mediaOk)とパック(pack)。フォルダごとに1回だけ存在を確かめ、全体で PACK_CHECK_BUDGET 秒まで。
    ネットワーク上のパス(//サーバー/…)は調べない(一覧を開くだけでそのサーバーへ資格情報を送らないため。clip_info と同じ考え)。
    調べなかった・調べきれなかったものは mediaOk = None(不明)。"""
    t0 = time.monotonic()
    dirs = {}
    for it in items:
        sp = it.pop("_sp", "")
        it["mediaOk"], it["pack"] = None, None
        if not sp or not os.path.isabs(sp) or _fsio.is_network_path(sp):
            if not sp:
                it["mediaOk"] = False
            continue
        if time.monotonic() - t0 > PACK_CHECK_BUDGET:
            continue
        folder = os.path.dirname(sp)
        if folder not in dirs:
            try:
                dirs[folder] = os.path.isdir(folder)
            except (OSError, ValueError):
                dirs[folder] = False
        if not dirs[folder]:
            it["mediaOk"] = False
            continue
        try:
            it["mediaOk"] = os.path.isfile(sp)
        except (OSError, ValueError):
            it["mediaOk"] = False
        p = txindex.pack_info(sp)   # 一覧の API にフォルダのパスは出さない
        it["pack"] = {"textplus": p["textplus"], "updatedAt": p["updatedAt"]} if p else None


def list_transcripts():
    """GET /api/transcripts の items。作った日が新しい順(画面で並べ替える)。
    校正の進み具合(rows・proofed・cut・flagged)・長さ(durationSec)・元の配信(videoId・clipTitle・clipStart/End・markLabel)・
    配信者(channel。スタジオの data.json から)・元の動画の有無(mediaOk)・パック(pack)も返す。"""
    items, seen = [], set()
    for tid in store._tids():
        seen.add(tid)
        sm = store.transcript_summary(tid)
        if sm:
            it = dict({k: v for k, v in sm.items() if not k.startswith("_")}, _sp=sm["_sourcePath"])
            it.update(store.edit_summary(tid))   # 「編集」: カットの有無・rev・パックを作った rev(履歴の「パック済み」「作り直しが要る」)
            it["packStale"] = store.pack_stale(it)
            it.pop("_packDocAt", None)
            items.append(it)
    store.prune_summaries(seen)   # 消した文書の分は捨てる
    studio = _studiodata.studio_videos()
    for it in items:
        sv = studio.get(it["videoId"]) if it["videoId"] else None
        it["channel"] = sv["channel"] if sv else ""
        if sv and sv["title"]:
            it["streamTitle"] = sv["title"]   # スタジオで題名を直していれば、そちらを見出しに使う
    _files_state(items)
    items.sort(key=lambda x: x["createdAt"], reverse=True)
    return items


PACK_README_NAMES = ("友人へ.txt", "予備_EDLで開く手順.txt")   # 手順書のファイルを持つ形のパック(今のパックは入れない)


def pack_readme(tid):
    """GET /api/edit/pack-readme?id=: 前回のパックの Resolve での手順。記録したフォルダが cut2resolve のパック
    (cut2resolve のパックを作った記録がある。txindex.is_pack_dir)のときだけ読む。
    今のパックは手順書のファイルが無いので、パックの Lua から作り直す(flow.pack.instructions)。Lua が無ければ手順書のファイルを読む"""
    store.read_transcript(tid)
    d, _ = store.read_edit(tid)
    pk = (d or {}).get("pack") or {}
    folder = pk.get("dir") if isinstance(pk.get("dir"), str) else ""
    if not folder or _fsio.is_network_path(folder) or not txindex.is_pack_dir(folder):
        raise _errors.ApiError("not_found", "前回のパックのフォルダが見つかりません(移動・削除した可能性があります)", 404)
    text = _flowpack.instructions(folder)
    if text:
        return {"name": "", "text": text}
    for n in PACK_README_NAMES:
        try:
            with open(os.path.join(folder, n), "rb") as f:
                return {"name": n, "text": f.read(256 * 1024).decode("utf-8-sig", "replace")}
        except OSError:
            continue
    raise _errors.ApiError("not_found", "パックの中に Resolve での手順を作る材料(.lua)がありません", 404)
