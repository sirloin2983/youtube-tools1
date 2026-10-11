# -*- coding: utf-8 -*-
"""② 管理の層 flow: 案件の候補と採用のファイルの書く側(RS8 B3-3・B3-4a。決定 3-37 の (r8j)〜(r8q)。下調べは WORKLOG の 10-11)。

**読む側・形・重ね方・ロックは ytt/casefiles(B3-4a で下ろした。ytt/studiodata が data.json の行の case から読むため)。ここは分ける split・案件の引き方 case_of・書く write**。
スタジオの配信 1 本(data.json の videos の 1 つの形)を、案件のフォルダの 2 つのファイルに分けて持つための読み書きと、分ける・重ねるの関数。
読む側は ytt/casefiles(B3-4a)・保存の経路に入れるのは B3-4b。

- `<案件>/作業用/候補.json`(CANDIDATES_SCHEMA。① の機械の候補): {schema, sources: {<スタジオの id>: {analysis, duration, auto: [手つかずの自動マーク]}}}
- `<案件>/作業用/採用.json`(ADOPTIONS_SCHEMA。③ の人の採用): {schema, sources: {<スタジオの id>: {kind, title, channel, fileName, path, rev,
  createdAt, updatedAt, live?, order?}}, marks: [マーク + source], rejected: [{source, id, start, end, at}], status, memo}。
  1 つの案件に配信が 2 本(ライブの録画 + アーカイブ)ありうるので sources で分け、マークは平らに置いて source を持たせる((r8k))。
  書き出しの結果の path と、file の配信の path は案件の根からの相対(区切りは /。根の外・正規化されていないパスは絶対のまま)((r8m))。
  order は画面の並びが時刻の順でないときだけ持つ(マークの id の並び)
- 分け方 `split`: 境目は今の Store.replace_auto と同じ(src auto で ytt/marks.touched が偽 = 候補・それ以外 = 採用)。
  重ねたときに見えなくなる候補(採用と same・rejected の印に当たる)は採用の側に残す = いつでも merge(*split(v)) == v
- 重ね方 `merge`: 画面 = 採用 ∪ (候補 − 採用と同じ id − 採用と ytt/marks.same で重なる物 − rejected の印に当たる物)。
  rejected の印は id か ytt/marks.similar(±5 秒・重なりの率)で当てる = 再解析で時刻が少しずれても外れない((r8l))
- 案件の引き方 `case_of`: 書き出したマークの path の親(作業用/ の中なら 1 つ上)で、作業用/.studio-id の持ち主がその配信のもの・
  書き出し先(outDir)の下・書き出し先が固定ディスク・ネットワーク上でない(flow/placement の doc_home と同じ規則)。
  1 つに決まらなければ None(題で探さない・勝手に直さない((r8o)))
- 読み `ytt/casefiles.read`・書き `write`: 案件の根を受ける。書く順は 採用 → 候補・どちらも fsio.write_json で原子的・採用.json だけ .bak 1 世代
  (今の採用.json が読めるときだけ写す。読めなければ .broken-<日時> へ退けて .bak を守る)・パスごとのロック `casefiles.lock(root)`(Store.lock のあとに取る。逆の順は作らない。casebook.lock を持ったままスタジオの API を呼ばない)。
  置き場所が見えない(ドライブが外れた・フォルダが消えた・ネットワーク上)ときは ytt/docloc と同じ 503 の形(code case_unseen)で断る
"""
import copy
import logging
import os
import shutil
import time

from ytt import casefiles as _cf, datadir as _datadir, errors as _errors, fsio as _fsio, marks as _marks, names as _names, schemas as _schemas
from ytt.casefiles import (ADOPTIONS_NAME, ADOPTIONS_SCHEMA, CANDIDATES_NAME, CANDIDATES_SCHEMA, MAX_REJECTED, empty_adoptions,
                           empty_candidates, lock, need_root, work_path, visible)

log = logging.getLogger("ytt.flow.casebook")

_VIDEO_OWN = ("id", "marks", "analysis", "duration")   # 配信の欄のうち 採用.json の sources に写さない物(id は鍵・残りは別の持ち主)


def owners(video):
    """その配信の案件の持ち主の印(.studio-id)として認める値: スタジオの id・ライブなら配信の videoId と live-<録画 id>
    (ライブの書き出しの持ち主は videoId か live-<録画 id>。flow/live_export)"""
    got = {str(video.get("id") or "")}
    live = video.get("live") if isinstance(video.get("live"), dict) else None
    if video.get("kind") == "live" and live:
        if live.get("videoId"):
            got.add(str(live["videoId"]))
        if live.get("recording"):
            got.add("live-" + str(live["recording"]))
    got.discard("")
    return got


def case_of(video, out_dir=None):
    """スタジオの配信(data.json の形)-> 案件の根か None。書き出したマークの path の親(作業用/ の中なら 1 つ上)のうち、
    作業用/.studio-id の持ち主がこの配信(owners)・書き出し先 out_dir(None = スタジオの設定 = ytt.datadir.studio_out_dir)の下・
    書き出し先が固定ディスクでネットワーク上でない、を満たすものが 1 つだけのとき。読むだけ(作らない・書かない)。題で探さない"""
    try:
        out = out_dir or _datadir.studio_out_dir()
        if not isinstance(out, str) or not os.path.isabs(out) or _cf.is_remote(out) or not _fsio.is_fixed_drive(out):
            return None
        want = owners(video)
        seen, good = set(), []
        for m in video.get("marks") or ():
            p = m.get("path") if isinstance(m, dict) and m.get("status") == "exported" else None
            if not isinstance(p, str) or not p or not os.path.isabs(p) or _cf.is_remote(p):
                continue
            root = os.path.normpath(_schemas.media_folder(p))
            key = _fsio.norm_path(root)
            if key in seen:
                continue
            seen.add(key)
            if _fsio.is_inside(root, out, strict=True) and os.path.isdir(root) and _names.read_owner(root) in want:
                good.append(root)
        return good[0] if len(good) == 1 else None
    except Exception as e:   # 設定が読めない・パスが変 など = 引けない(案件にしない)
        log.info("案件を引けませんでした: %s %s", e.__class__.__name__, str(e)[:150])
        return None



def _rejected_of(c, sid, at):
    return {"source": sid, "id": c["id"], "start": c["start"], "end": c["end"], "at": at}


def split(video, root=None, prev=None, keep_candidates=False, at=None):
    """スタジオの配信 1 本(data.json の形)-> (候補.json, 採用.json) の中身。いつでも merge(*split(v), v["id"], root) == v(並びも)。
    - prev = 今の (候補, 採用)(None = 無い)。ほかの配信(sources)・この配信の消した印・状態・メモはそのまま引き継ぐ
    - 境目は Store.replace_auto と同じ(src auto で touched でない = 候補)。重ねたとき見えなくなる候補は採用の側に残す
    - keep_candidates=True(人の保存。① の 候補.json を書き換えない道): 候補は prev のこの配信の物をそのまま使い、
      画面から消えた候補(id が配信に無く、まだ見えている物)に消した印を足す(at = 印の時刻。None = 今)
    - root(案件の根)を渡すと、書き出しの結果の path と file の配信の path を根からの相対にする"""
    sid = video["id"]
    pc, pa = prev or (None, None)
    cands = copy.deepcopy(pc) if pc else empty_candidates()
    adopts = copy.deepcopy(pa) if pa else empty_adoptions()
    rejected = [r for r in adopts["rejected"] if r.get("source") == sid]
    adopts["marks"] = [m for m in adopts["marks"] if m.get("source") != sid]
    adopts["rejected"] = [r for r in adopts["rejected"] if r.get("source") != sid]
    marks = copy.deepcopy(video.get("marks") or [])
    in_video = {m["id"] for m in marks}
    if keep_candidates:
        pool = copy.deepcopy((cands["sources"].get(sid) or {}).get("auto") or [])
        by_id = {c["id"]: c for c in pool}
        cand_ids = {m["id"] for m in marks if by_id.get(m["id"]) == m}
    else:
        pool = [m for m in marks if m.get("src") == "auto" and not _marks.touched(m)]
        cand_ids = {m["id"] for m in pool}
    stamp = at if _marks.pos_int(at) else _schemas.now_ms()
    while True:   # 見えなくなる候補を採用の側へ移す(移すと採用が増えて、ほかの候補が隠れることがあるので、変わらなくなるまで)
        adopted = [m for m in marks if m["id"] not in cand_ids]
        if keep_candidates:
            gone = {r["id"] for r in rejected if r.get("id")}
            rejected += [_rejected_of(c, sid, stamp) for c in visible(pool, adopted, rejected)
                         if c["id"] not in in_video and c["id"] not in gone]
        bad = cand_ids - {c["id"] for c in visible(pool, adopted, rejected)}
        if not bad:
            break
        cand_ids -= bad
    src = {k: copy.deepcopy(v) for k, v in video.items() if k not in _VIDEO_OWN}
    if src.get("path"):
        src["path"] = _cf.rel_path(src["path"], root)
    shown = [c for c in pool if c["id"] in cand_ids]
    if [m["id"] for m in _cf.ordered(adopted + shown, None)] != [m["id"] for m in marks]:
        src["order"] = [m["id"] for m in marks]
    for m in adopted:
        if m.get("path"):
            m["path"] = _cf.rel_path(m["path"], root)
        m["source"] = sid
    adopts["sources"][sid] = src
    adopts["marks"] += adopted
    adopts["rejected"] += rejected[-MAX_REJECTED:]
    cands["sources"][sid] = {"analysis": copy.deepcopy(video.get("analysis")), "duration": video.get("duration") or 0.0,
                             "auto": pool if keep_candidates else shown}
    return cands, adopts


def _set_aside(path):
    """読めない 採用.json を <名前>.broken-<日時> へ退ける(.bak を壊れた物で上書きしないため)。退けられなければ OSError"""
    ts = time.strftime("%Y%m%d-%H%M%S")
    name, n = path + ".broken-" + ts, 0
    while os.path.exists(name):
        n += 1
        name = "%s.broken-%s-%d" % (path, ts, n)
    os.replace(path, name)
    log.warning("読めない 採用.json を退けました: %s", name)


def write(root, candidates=None, adoptions=None):
    """案件の 候補.json・採用.json を書く(None の側は書かない)。順は 採用 → 候補・どちらも原子的。
    採用.json は書く前に今の物を .bak へ 1 世代(今の物が読めるときだけ。読めなければ .broken-<日時> へ退ける)。
    形の名前が違えば ValueError。置き場所が見えなければ ApiError 503(case_unseen)・書けなければ ApiError 500(save_failed)"""
    for doc, schema in ((candidates, CANDIDATES_SCHEMA), (adoptions, ADOPTIONS_SCHEMA)):
        if doc is not None and (not isinstance(doc, dict) or doc.get("schema") != schema):
            raise ValueError("案件のファイルの形が違います(%s)" % schema)
    with lock(root):
        need_root(root)
        try:
            if adoptions is not None:
                ap = work_path(root, ADOPTIONS_NAME)
                if os.path.exists(ap):
                    if _cf.read_doc(ap, _cf.parse_adoptions)[0] is not None:
                        try:
                            shutil.copyfile(ap, ap + ".bak")   # 1 つ前の世代(できなくても保存は続ける)
                        except OSError as e:
                            log.info("採用.json の控えを作れませんでした: %s", e)
                    else:
                        _set_aside(ap)
                _fsio.write_json(ap, adoptions, indent=1, fsync_required=True)
            if candidates is not None:
                _fsio.write_json(work_path(root, CANDIDATES_NAME), candidates, indent=1)
        except OSError as e:
            log.warning("案件のファイルを書けませんでした: %s %s", root, e)
            raise _errors.ApiError("save_failed", "案件のファイルを保存できませんでした(ディスクの空きなど)", 500, {"dir": root})
