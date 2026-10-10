# -*- coding: utf-8 -*-
"""② 文書の置き場: 文字起こしの保存・履歴(自動スナップショット)・整形・校正の手間・要約のキャッシュ・編集の内容(残す区間)・「文字起こしせずに開く」
(段10 で editor/serve.py から分けた ed_store。役割で組み直す RS3-E5a(2026-10-10)に human/proof/store.py へ移した。旧い名前 ed_store は転送だけの殻 = RS5 で消す)。

- 一覧と元の動画・パックの有無(list_transcripts・pack_info)と前回のパックの手順(pack_readme)は manage/cases/doclist.py(txindex を読むのはそちら)
- 評価ドリルの要約は持たない(eval/drill/drill.drill_docs が自前で文書を読んで足す。決定 3-25 #8)
- 編集の内容(edit.json)は文書と相互に呼ぶので割らない(文書の書き込みは必ず apply_edit_cuts を通す)
名前は serve.py からも見える(serve.py の名前の受付 _ED_MODULES がこの部品へ転送する。テストの S.名前 = … もここに入る)。
ほかの部品の名前は `モジュール.名前` の形で呼ぶたびに読む(差し替えが効くように。from … import はしない)。編集の ed_state は読まない(app = 上の層)。
"""
import bisect
import json
import os
import re
import shutil
import threading
import time
import uuid

from ytt import errors as _errors, fsio as _fsio, jobs as _heavy, schemas as _yschemas  # noqa: E402
from ytt import settings as _settings  # noqa: E402   編集の設定の読み書き load_settings(RS3-1 に ed_learn から ytt/settings へ)
from ytt import tools as _tools, workdata as _workdata  # noqa: E402   (置き場所と版の今の値・動画と音声の小道具。RS3-0A に ed_state・ed_store から移した)
from pipeline.pack import resolve_export  # noqa: E402   カットのたたき台・見積もり(RS3-E5b に editor から pipeline/pack へ。呼ぶたびに resolve_export.名前 で読む)
from ytt import txbase as _txbase  # noqa: E402   ロガー log・1 行の文字数の上限 MAX_TEXT(RS3-E5a まで ed_state の別名で読んでいた)


# ---------- 文字起こしの保存 ----------
def tx_path(tid):
    return os.path.join(_workdata.TX_DIR, tid + ".json")


def write_doc(tid, doc):
    """文書を書く(読みやすい JSON。fsio.atomic_write の fsync_required = 書き出しを確かめてから置き換え。停電のあとに空の文書を残さない)。文書の書き込みはここを通す"""
    _fsio.atomic_write(tx_path(tid), json.dumps(doc, ensure_ascii=False, indent=1).encode("utf-8"), fsync_required=True)


def snapshot(tid, force=True):
    """いまの文書を履歴へ1つ残す(hist_snapshot。残せなくても続ける)"""
    try:
        hist_snapshot(tid, force=force)
    except OSError:
        pass


def backup_doc(tid, kind):
    """機械が行を書き換える前の控え: .bak/<id>.pre-<kind>.json(直前の 1 世代)と履歴(「以前の版に戻す」で戻せる)"""
    bak = os.path.join(_workdata.TX_DIR, ".bak")
    os.makedirs(bak, exist_ok=True)
    shutil.copy2(tx_path(tid), os.path.join(bak, "%s.pre-%s.json" % (tid, kind)))
    snapshot(tid)


# ---------- 話者ごとの字幕の見た目 sub(2026-10-05。docs/spec/friend-intake.md の 6) ----------
# 色を単独の値で持たず「字幕の見た目」のまとまりの 1 項目にする(あとでフォント・大きさなどを足しても形を変えない)。
# 検査は鍵ごとの許可の一覧: 知っている鍵だけ受け、形を確かめ、知らない鍵・形の違う値は黙って捨てる(画面・Lua に入るので必ずここを通す)
def _sub_color(v):
    """字幕の文字の色: 16 進 6 桁(# はあってもなくても)→ "#RRGGBB"(大文字)。違えば None(規則は ytt.colors.norm_hex の 1 か所。文字列だけ)"""
    from ytt import colors as _colors
    return _colors.norm_hex(v) if isinstance(v, str) else None


SUB_STYLE_KEYS = {"color": _sub_color}   # 鍵 → 検査(値を返す・だめなら None)。足すときはここに 1 行
DIAR_NUM_MAX = 8   # 文書の diarNum(話者判別の人数)の上限。画面の #diarNum の選択肢(自動・1〜8 人)と同じ


def sanitize_sub_style(v):
    """話者の sub(字幕の見た目)を検査する -> 正しい鍵だけの dict。1 つも無ければ None(sub ごと持たない)"""
    if not isinstance(v, dict):
        return None
    out = {}
    for k, check in SUB_STYLE_KEYS.items():
        if k in v:
            x = check(v[k])
            if x is not None:
                out[k] = x
    return out or None


def sanitize_transcript(obj, base=None):
    """クライアントから来た編集内容を検査して、保存できる形にする。"""
    speakers, seen = [], set()
    for s in (obj.get("speakers") or [])[:21]:   # 20 人 + 組み込みの「ゲーム音声など」
        if not isinstance(s, dict):
            continue
        sid = re.sub(r"[^\w-]", "", str(s.get("id", "")))[:12]
        if not sid or sid in seen:
            continue
        if sid == _yschemas.OTHER_SPK_ID:   # 組み込みの話者: 名前・色・印は決まった値(画面から名前を変えさせない)。字幕の見た目は持たない(字幕に出さない話者)
            seen.add(sid)
            speakers.append({"id": sid, "name": _yschemas.OTHER_SPK_NAME, "color": _yschemas.OTHER_SPK_COLOR, "builtin": _yschemas.OTHER_SPK_BUILTIN})
            continue
        if sum(1 for x in speakers if x.get("id") != _yschemas.OTHER_SPK_ID) >= 20:
            continue
        seen.add(sid)
        one = {"id": sid, "name": str(s.get("name", ""))[:30] or sid, "color": re.sub(r"[^#\w]", "", str(s.get("color", "")))[:9]}
        st = sanitize_sub_style(s.get("sub"))   # 字幕の見た目(今は文字の色だけ。画面の行の色 color とは別)
        if st:
            one["sub"] = st
        speakers.append(one)
    segs, ids = [], set()
    now = _yschemas.now_ms()
    base_at = {}   # 保存済みの校正済みの行 id -> 校正した時刻(以前の文書で時刻が無ければ None = 分からないまま。今の時刻を作らない)
    for g in (base or {}).get("segments") or []:
        if isinstance(g, dict) and g.get("proofed") is True and isinstance(g.get("id"), str):
            at = g.get("proofedAt")
            base_at[g["id"]] = at if (_yschemas.plain_int(at) or 0) > 0 else None
    for i, sg in enumerate(obj.get("segments") or []):
        if i >= _yschemas.MAX_SEGMENTS:
            raise _errors.ApiError("too_many", "行数が多すぎます", 400)
        if not isinstance(sg, dict):
            continue
        a, b = _yschemas.num_or(sg.get("start")), _yschemas.num_or(sg.get("end"))
        if a is None or b is None or a < 0 or b < a:
            continue
        sid = re.sub(r"[^\w-]", "", str(sg.get("id", "")))[:16] or "s%d" % (i + 1)
        while sid in ids:
            sid += "x"
        ids.add(sid)
        sp = str(sg.get("speaker", ""))
        one = {"id": sid, "start": round(a, 2), "end": round(b, 2), "text": str(sg.get("text", ""))[:_txbase.MAX_TEXT],
               "speaker": sp if sp in seen else "", "flag": str(sg.get("flag", ""))[:100]}
        tg = [t for t in _yschemas.ROW_TAGS if isinstance(sg.get("tags"), list) and t in sg["tags"]]   # 音の状態のメモ(聞き取れない・声が重なる・BGMが大きい)
        if tg:
            one["tags"] = tg
        if sg.get("proofed") is True:   # 校正済み(人が聞いて、この行の文字が正しいと確認した印)。学習・精度測定の正解データに使う
            one["proofed"] = True
            # 初めて校正済みにした時刻(ミリ秒。マスタープラン Q2 = 時期で分けて測る)。保存済みの同じ id の行から引き継ぎ(画面の値は使わない)、
            # 保存済みで校正済みでなかった行は今。外した行は残さない(次に校正済みにした時刻から数え直す)。
            # この項目より前に校正済みだった行は時刻を作らない(分からないまま。時期で分けるときは「時刻なし = この版より前」)
            at = base_at[sid] if sid in base_at else now
            if at is not None:
                one["proofedAt"] = at
        if sg.get("cutState") == "cut":
            one["cutState"] = "cut"
        if sg.get("noSub") is True:   # 字幕に出さない(ゲームの声など。真のときだけ持つ)。機械の出力 original は変えない
            one["noSub"] = True
        if isinstance(sg.get("fill"), dict) and isinstance(sg["fill"].get("from"), str):   # 別の読みで埋めた行の元の文字(ed_fill。画面の「別の読み」の札で戻す)
            one["fill"] = {"from": sg["fill"]["from"][:_txbase.MAX_TEXT], "by": str(sg["fill"].get("by") or "")[:20]}
        if sg.get("draft") in _yschemas.ROW_DRAFT_KINDS:   # 機械の下書き(重なりの所に置いた空の行など。決まった文字列のときだけ。文字を打ったら画面が外す。2026-10-05)
            one["draft"] = sg["draft"]
        segs.append(one)
    out = dict(base or {})
    if "evalSet" in obj:   # 評価用の印(キーが来たときだけ変える。古い画面から保存しても外れないように)
        if obj.get("evalSet") is True:
            out["evalSet"] = True
        else:
            out.pop("evalSet", None)
    if _settings.in_eval_dir(out.get("sourcePath")):   # 評価用のフォルダの動画は外せない(2026-10-01 ユーザー決定)
        out["evalSet"] = True
    # 「動画を全部聞いて確かめた」印(評価ドリル。eval/drill/drill.drill_reviewed)は base から引き継ぐだけ(画面から送られた値は使わない = out は base の写し)。
    # 評価用を外したら一緒に外す(評価用でない間は一括置換・再認識などで機械が書き換えられるため、付け直すときは聞き直す)
    if out.get("evalSet") is not True:
        out.pop("evalReviewed", None)
    out.update({"title": str(obj.get("title", out.get("title", "")))[:120], "speakers": speakers, "segments": segs,
                "updatedAt": now})
    return out


def doc_length(d):
    """文書の長さ(秒): 範囲の終わり − 始まり → 動画の長さ − 始まり → 無ければ(古い文書・長さの記録が無い文書)最後の行の終わりまで"""
    segs = [s for s in (d.get("segments") or []) if isinstance(s, dict)]
    a = _yschemas.num_or(d.get("start"), 0.0) or 0.0
    b = _yschemas.num_or(d.get("end"))
    dur = _yschemas.num_or(d.get("duration"))
    if b is not None and b > a:
        return b - a
    if dur is not None and dur > a:
        return dur - a
    return max(0.0, max([_yschemas.num_or(s.get("end"), 0.0) or 0.0 for s in segs] or [0.0]) - a)


# 文書ごとの要約のキャッシュは 1 つ(2026-10-09。docs/design/code-review-simplify-2026-10-08.md の C・G7-2)。
# 一覧(manage/cases/doclist.list_transcripts)・文字起こし済みの判定・評価ドリル(eval/drill/drill.drill_docs)が同じ要約を使うので、
# 保存のたびに変わった文書の JSON を読むのは 1 回だけ(以前は 3 つのキャッシュが別々に読んでいた)。
# 鍵 = (パス, 更新日時ns, 大きさ)。パスも入れるのは、作業データの場所を切り替えたとき(テストの一時フォルダ)に同じ id・同じ大きさ・同じ時刻の別の文書を引かないため
_summary_cache = {}   # tid -> (鍵, 要約)。名前はテストが clear するので変えない
_summary_lock = threading.Lock()


def good_row(g):
    """定点(評価ドリルの条件)に数える行(校正済み・聞き取れない印なし)"""
    return g.get("proofed") is True and "unclear" not in (g.get("tags") or [])


def row_dur(g):
    """行の長さ(秒。読めない時刻は 0)"""
    return max(0.0, (_yschemas.num_or(g.get("end"), 0.0) or 0.0) - (_yschemas.num_or(g.get("start"), 0.0) or 0.0))


def _load_doc(path):
    """文書の JSON(読めない・dict でなければ None)。read_transcript と同じ読み方(このツールが書いたファイル)"""
    try:
        with open(path, "r", encoding="utf-8") as f:
            d = json.load(f)
    except (OSError, ValueError):
        return None
    return d if isinstance(d, dict) else None


def transcript_summary(tid):
    """文書1件の要約(一覧の1行 + 元ファイル・範囲)。評価ドリルの要約は eval/drill/drill.drill_docs が自前で足す(RS3-E5a。② が ④ を読まない)。ファイルの更新日時と大きさが同じなら、前に読んだ結果を使う。読めなければ None。"""
    path = tx_path(tid)
    st = _fsio.stamp(path)
    if st is None:
        return None
    key = (path,) + st
    with _summary_lock:
        hit = _summary_cache.get(tid)
    if hit and hit[0] == key:
        return hit[1]
    d = _load_doc(path)
    if d is None:
        return None   # 読めない(書きかけ・ほかのアプリが開いている)ものは覚えない = 次にもう一度読む
    segs = [s for s in (d.get("segments") or []) if isinstance(s, dict)]
    text_rows = sum(1 for s in segs if str(s.get("text") or "").strip())
    proofed = sum(1 for s in segs if s.get("proofed") is True and str(s.get("text") or "").strip())
    length = doc_length(d)
    clip = d.get("clip") if isinstance(d.get("clip"), dict) else None
    src = clip.get("source") if clip and isinstance(clip.get("source"), dict) else {}
    rng = clip.get("range") if clip and isinstance(clip.get("range"), dict) else {}
    mk = clip.get("mark") if clip and isinstance(clip.get("mark"), dict) else {}
    sm = {"id": tid, "title": d.get("title", ""), "sourceName": d.get("sourceName", ""), "start": d.get("start", 0),
          "end": d.get("end"), "model": d.get("model", ""), "segments": len(d.get("segments") or []),
          "createdAt": d.get("createdAt", 0), "updatedAt": d.get("updatedAt", 0), "evalSet": d.get("evalSet") is True,
          "hasClip": clip is not None,
          # v0.15.0: 履歴の一覧で見分け・絞り込みに使う(校正の進み具合・長さ・元の配信)
          "rows": text_rows, "proofed": proofed, "cut": sum(1 for s in segs if s.get("cutState") == "cut"),
          "flagged": sum(1 for s in segs if str(s.get("flag") or "").strip()), "durationSec": round(max(0.0, length), 1),
          "videoId": str(src.get("videoId") or "")[:40] if clip else "", "clipTitle": str(src.get("title") or "")[:200] if clip else "",
          "clipStart": _yschemas.num_or(rng.get("start")), "clipEnd": _yschemas.num_or(rng.get("end")), "markLabel": str(mk.get("label") or "")[:80],
          "_sourcePath": d.get("sourcePath") or "", "_whole": bool(d.get("whole")),
          "_aliases": [r["from"] for r in d.get("relinks") or [] if isinstance(r, dict) and r.get("why") == "normalize30" and isinstance(r.get("from"), str) and r["from"]][-5:],   # 30fps の写しへ付け替える前のパス(Q1)
          "_key": key}
    with _summary_lock:
        _summary_cache[tid] = (key, sm)
    return sm


def _tids():
    return [n[:-5] for n in (os.listdir(_workdata.TX_DIR) if os.path.isdir(_workdata.TX_DIR) else []) if n.endswith(".json") and _yschemas.TID_RE.match(n[:-5])]


def prune_cache(cache, keep, lock=None):
    """文書ごとのキャッシュ {tid: …} から、keep に無い(消えた)文書の分を捨てる"""
    with lock or _summary_lock:
        for k in [k for k in cache if k not in keep]:
            cache.pop(k, None)


def summaries():
    """全文書の (id, 要約 transcript_summary, 動画のパス)(読めない文書は除く。要約はキャッシュ = 文書を読み直さない)。
    最後まで回したら、消えた文書の要約を捨てる"""
    seen = set()
    for tid in _tids():
        seen.add(tid)
        sm = transcript_summary(tid)
        if sm:
            yield tid, sm, str(sm.get("_sourcePath") or "")
    prune_cache(_summary_cache, seen)


# 一覧と元の動画・パックの有無(PACK_CHECK_BUDGET・pack_info・_files_state・list_transcripts)と前回のパックの手順(pack_readme)は
# manage/cases/doclist.py へ移した(RS3-E5a。txindex = ③ を読むのはそちら)


def read_transcript(tid):
    if not _yschemas.TID_RE.match(tid or "") or not os.path.isfile(tx_path(tid)):
        raise _errors.ApiError("not_found", "文字起こしが見つかりません", 404)
    d = _load_doc(tx_path(tid))
    if d is None:
        raise _errors.ApiError("broken", "文字起こしファイルを読み込めません", 500)
    return d


# ---------- 履歴(自動スナップショット)と保存の競合検出 ----------
HIST_INTERVAL = 600     # 秒。保存のたびではなく、前回の履歴からこれだけ経っていたら1つ残す
HIST_KEEP = 30          # 1本あたりの保持数(古いものから消す)
_save_lock = threading.Lock()


def _hist_dir(tid):
    return os.path.join(_workdata.TX_DIR, ".hist", tid)


def hist_stamps(tid):
    d = _hist_dir(tid)
    out = []
    if os.path.isdir(d):
        for n in os.listdir(d):
            if n.endswith(".json") and n[:-5].isdigit():
                out.append(int(n[:-5]))
    return sorted(out)


def hist_snapshot(tid, force=False):
    """いまの保存内容を履歴へ1つ残す。直近の履歴が新しければ(force でなければ)何もしない。"""
    src = tx_path(tid)
    if not os.path.isfile(src):
        return None
    stamps = hist_stamps(tid)
    now = _yschemas.now_ms()
    if not force and stamps and now - stamps[-1] < HIST_INTERVAL * 1000:
        return None
    d = _hist_dir(tid)
    os.makedirs(d, exist_ok=True)
    ts = now if not stamps or now > stamps[-1] else stamps[-1] + 1
    shutil.copy2(src, os.path.join(d, "%d.json" % ts))
    stamps.append(ts)
    for old in stamps[:-HIST_KEEP]:
        _fsio.unlink_quiet(os.path.join(d, "%d.json" % old))
    return ts


def list_history(tid):
    read_transcript(tid)
    items = []
    for ts in reversed(hist_stamps(tid)):
        d = _load_doc(os.path.join(_hist_dir(tid), "%d.json" % ts))
        if d is None:
            continue
        segs = d.get("segments") or []
        items.append({"ts": ts, "segments": len(segs), "proofed": sum(1 for s in segs if s.get("proofed") is True),
                      "chars": sum(len(s.get("text", "")) for s in segs)})
    return items


def save_transcript(tid, obj):
    """編集内容の保存。baseUpdatedAt が付いていて、保存済みの版とずれていれば 409(別のタブ・再認識などで先に更新されている)。"""
    with _save_lock:
        base = read_transcript(tid)
        b = obj.get("baseUpdatedAt")
        if b is not None and not obj.get("force") and base.get("updatedAt") and b != base.get("updatedAt"):
            raise _errors.ApiError("conflict", "別の場所で先に更新されています(別のタブ、再認識、話者分離など)。読み込み直すか、この内容で上書きするか選んでください", 409)
        doc = sanitize_transcript(obj, base)
        effort_rows(base, doc)   # 校正済みにした行・外した行の数(校正の手間。Q2)
        apply_edit_cuts(tid, doc)   # 編集の内容があれば、行の「カット済」はそちらから決める(画面の古い印で上書きしない)
        snapshot(tid, False)   # 履歴が残せなくても保存は止めない
        write_doc(tid, doc)
        return doc


def restore_history(tid, ts):
    with _save_lock:
        read_transcript(tid)
        if not isinstance(ts, int) or ts not in hist_stamps(tid):
            raise _errors.ApiError("not_found", "その履歴は見つかりません", 404)
        p = os.path.join(_hist_dir(tid), "%d.json" % ts)
        try:
            old = _load_doc(p)
            if old is None:
                raise _errors.ApiError("broken", "履歴を読み込めません", 500)
            hist_snapshot(tid, force=True)      # 戻す前の状態も残す(戻したことを取り消せるように)
            old["updatedAt"] = _yschemas.now_ms()
            cur = read_transcript(tid)
            if isinstance(cur.get("effort"), dict):   # 校正の手間の累計は戻さない(戻すのは文字と行。マスタープラン Q2)
                old["effort"] = cur["effort"]
            else:
                old.pop("effort", None)
            if _settings.in_eval_dir(old.get("sourcePath")):   # 評価用のフォルダの動画は、印の無い版へ戻しても評価用のまま
                old["evalSet"] = True
            apply_edit_cuts(tid, old)   # 戻すのは文字と行。カットは今の編集の内容のまま
            write_doc(tid, old)
        except (OSError, ValueError):
            raise _errors.ApiError("broken", "履歴を読み込めません", 500)
        return old


# ---------- 校正の手間(マスタープラン Q2。文書ごとの累計 effort = {"activeSec", "cutSec", "sessions", "proofedRows", "unproofedRows", "lastAt"}) ----------
# 時間(activeSec = 1 文字起こし のタブで操作していた秒・cutSec = 2 カット / 3 パック・sessions = 開いて作業した回数)は画面が POST /api/effort で送る。
# 行(proofedRows = 校正済みにした行・unproofedRows = 外した行)は保存のときにサーバーが数える(どの画面から保存しても同じ数え方)。
# どれも文書の updatedAt を動かさない(記録のために画面の保存の競合 baseUpdatedAt / 409 を起こさない)
MAX_EFFORT_SEC = 3600   # 1回に足せる秒の上限(画面は 30 秒刻みで数え、5 分たまったとき・離れたとき・文書を切り替えるときに送る)
EFFORT_KEYS = ("activeSec", "cutSec", "sessions", "proofedRows", "unproofedRows")


def _effort_of(doc):
    ef = doc.get("effort") if isinstance(doc.get("effort"), dict) else {}
    out = {k: max(0, _yschemas.plain_int(ef.get(k)) or 0) for k in EFFORT_KEYS}
    if _yschemas.plain_int(ef.get("lastAt")):
        out["lastAt"] = ef["lastAt"]
    return out


def effort_rows(base, doc):
    """保存で校正済みにした行・外した行(保存済みの文書 base と、これから書く doc の同じ id の行を比べる)を doc の effort に足す"""
    before = {g.get("id") for g in (base or {}).get("segments") or [] if isinstance(g, dict) and g.get("proofed") is True}
    after = {g["id"]: g.get("proofed") is True for g in doc.get("segments") or []}
    on = sum(1 for i, p in after.items() if p and i not in before)
    off = sum(1 for i in before if i in after and not after[i])
    if on or off:
        ef = _effort_of(doc)
        ef["proofedRows"] += on
        ef["unproofedRows"] += off
        ef["lastAt"] = doc.get("updatedAt") or _yschemas.now_ms()
        doc["effort"] = ef


def add_effort(obj):
    """POST /api/effort {"id", "activeSec", "cutSec"?, "newSession"?} -> {"effort": 累計}。文書の effort の時間と回数に足す。
    **文書の updatedAt は変えない**。保存と同じロックの中で読み直して足す"""
    tid = str(obj.get("id") or "")
    sec, cut = _yschemas.plain_int(obj.get("activeSec", 0)), _yschemas.plain_int(obj.get("cutSec", 0))
    if sec is None or cut is None or not 0 <= sec <= MAX_EFFORT_SEC or not 0 <= cut <= MAX_EFFORT_SEC:
        raise _errors.ApiError("bad_request", "activeSec・cutSec は 0〜%d 秒の整数にしてください" % MAX_EFFORT_SEC, 400)
    with _save_lock:
        doc = read_transcript(tid)
        ef = _effort_of(doc)
        if not sec and not cut:
            return {"effort": ef}
        ef["activeSec"] += sec
        ef["cutSec"] += cut
        ef["sessions"] += 1 if obj.get("newSession") is True else 0
        ef["lastAt"] = _yschemas.now_ms()
        doc["effort"] = ef
        write_doc(tid, doc)
        return {"effort": ef}


def set_diar_num(obj):
    """POST /api/doc-diarnum {"id", "diarNum"} -> {"diarNum"}。文書ごとの話者判別の人数(0 = 自動・1〜8 人。気が利く画面へ 段7 E-6)。
    画面が選んだときだけ送る(開いたときの既定 = その文書の話者の数は画面が決める)。**文書の updatedAt は変えない**
    (人数を選んだだけで保存の競合 409・パックの「作り直しが要る」を起こさない。校正の手間 add_effort と同じ)。画面の保存(PUT)は前の値を残す"""
    n = obj.get("diarNum")
    if _yschemas.int_in(n, 0, DIAR_NUM_MAX) is None:
        raise _errors.ApiError("bad_request", "diarNum は 0〜%d の整数にしてください" % DIAR_NUM_MAX, 400)
    tid = str(obj.get("id") or "")
    with _save_lock:
        doc = read_transcript(tid)   # id の形もここで確かめる(TID_RE)
        doc["diarNum"] = n
        write_doc(tid, doc)
        return {"diarNum": n}


# ---------- 編集の内容(残す区間。「編集」ツールのカットの正。docs/design/edit-tool-design.md の 4・5) ----------
# 文書 transcripts/<id>.json の隣の <id>.edit.json。校正の保存(文書の baseUpdatedAt)と、タイムラインの細かい保存(rev)を別にするため別のファイル。
# 行の「カット済」(cutState)は、編集の内容があるときは常にそこから決める(文書のどの書き込みでも apply_edit_cuts を通す)。
EDIT_SCHEMA = "youtube-tools-edit/v1"
MAX_EDIT_BYTES = 1024 * 1024
MAX_CLIPS = 5000
MAX_MEDIA_SEC = 24 * 3600
EDIT_ORIGINS = ("rows", "silence", "list", "plan", "manual", "all", "whole")   # whole = 「カットしない(動画全体)」を選んだ(気が利く画面へ 段3)
CUT_TOLERANCE_FRAMES = 0.75   # 行の時間のうち、残す区間に入るのがこれ未満(フレーム)なら「カット済」。区間の端はフレームに、行の時刻は 0.01 秒に丸めてあるため
_edit_cache = {}   # tid -> ((更新日時ns, 大きさ), 一覧用の要約)


def edit_path(tid):
    return os.path.join(_workdata.TX_DIR, tid + ".edit.json")


_real = _yschemas.num   # JSON の数(真偽値・文字列・NaN・float にできない巨大な整数は数として扱わない)。-> float か None


def _fps_pair(v):
    if not isinstance(v, list) or len(v) != 2 or any(_yschemas.plain_int(x) is None for x in v):
        return None
    n, d = v
    if not (1 <= n <= 1000000 and 1 <= d <= 1000000 and 1 <= n / d <= 300):
        return None
    return [n, d]


def sanitize_edit(obj):
    """画面から来た編集の内容を検査して、保存できる形にする(知らない項目は捨てる。rev・packRev はサーバーが付ける)。
    v1: 動画は文書の動画1本だけ(sources は1つ・clips の src は 0)。区間は元の動画の秒で、時刻の順・重ならない。区間が0個も受け付ける(全部削った状態)"""
    if not isinstance(obj, dict):
        raise _errors.ApiError("bad_edit", "編集の内容の形が正しくありません", 400)
    srcs = obj.get("sources")
    if not isinstance(srcs, list) or len(srcs) != 1 or not isinstance(srcs[0], dict):
        raise _errors.ApiError("bad_edit", "動画(sources)は1つだけにしてください(複数の切り抜きをつなぐのは、まだ使えません)", 400)
    fps, dur = _fps_pair(srcs[0].get("fps")), _real(srcs[0].get("duration"))
    if fps is None or dur is None or not 0 < dur <= MAX_MEDIA_SEC:
        raise _errors.ApiError("bad_edit", "動画の fps・長さが正しくありません", 400)
    clips = obj.get("clips")
    if not isinstance(clips, list) or len(clips) > MAX_CLIPS:
        raise _errors.ApiError("bad_edit", "区間(clips)は %d 個までです" % MAX_CLIPS, 400)
    limit = dur + fps[1] / fps[0] + 1e-6   # 長さ + 1フレームまで(フレームの境目に丸めた分)
    out, prev = [], 0.0
    for c in clips:
        if not isinstance(c, dict):
            raise _errors.ApiError("bad_edit", "区間の形が正しくありません", 400)
        src = c.get("src", 0)
        if isinstance(src, bool) or src != 0:
            raise _errors.ApiError("bad_edit", "区間の動画(src)は 0 だけにしてください(複数の切り抜きをつなぐのは、まだ使えません)", 400)
        a, b = _real(c.get("in")), _real(c.get("out"))
        if a is None or b is None or not 0 <= a < b <= limit:
            raise _errors.ApiError("bad_edit", "区間の時刻が正しくありません(0 ≤ 始まり < 終わり ≤ 動画の長さ)", 400)
        if a < prev - 1e-6:
            raise _errors.ApiError("bad_edit", "区間は時刻の順に、重ならないように並べてください", 400)
        ra, rb = round(a, 3), round(b, 3)
        if rb <= ra:
            raise _errors.ApiError("bad_edit", "区間が短すぎます", 400)
        out.append({"src": 0, "in": ra, "out": rb})
        prev = b
    return {"sources": [{"fps": fps, "duration": round(dur, 3)}], "clips": out,
            "origin": obj.get("origin") if obj.get("origin") in EDIT_ORIGINS else "manual"}


DRAFT_ORIGINS = ("rows", "all", "whole", "silence", "list", "plan")   # 機械が作るたたき台(manual は人の操作なので入れない)


def sanitize_draft(v):
    """初めてのたたき台の記録 draft(マスタープラン Q2。人の最終 = 保存したカット・パックの cutPlan と並べて、たたき台の規則を直すため)を確かめる。
    {"origin": たたき台の種類, "settings": {名前: 数・真偽・短い文字}(行から = 行の端の設定 rowEdge・無音 = しきい値など), "keepsSec": [[開始, 終了], …], "at"}。
    記録のための値なので、正しくなければ None(= 保存しない。カットの保存は止めない)"""
    if not isinstance(v, dict) or v.get("origin") not in DRAFT_ORIGINS:
        return None
    keeps = v.get("keepsSec")
    if not isinstance(keeps, list) or len(keeps) > MAX_CLIPS:
        return None
    out_k, prev = [], 0.0
    for x in keeps:
        a, b = (_real(x[0]), _real(x[1])) if isinstance(x, list) and len(x) == 2 else (None, None)
        if a is None or b is None or not 0 <= a < b <= MAX_MEDIA_SEC or a < prev - 1e-6:
            return None
        out_k.append([round(a, 3), round(b, 3)])
        prev = b
    st = v.get("settings") if isinstance(v.get("settings"), dict) else {}
    settings = {}
    for k, x in list(st.items())[:20]:
        if not isinstance(k, str) or not re.fullmatch(r"[A-Za-z][\w]{0,29}", k, re.A):
            continue
        if isinstance(x, bool) or (isinstance(x, str) and len(x) <= 100 and not any(ord(ch) < 32 for ch in x)):
            settings[k] = x
        elif _real(x) is not None:
            settings[k] = round(_real(x), 4)
    at = v.get("at")
    return {"origin": v["origin"], "settings": settings, "keepsSec": out_k,
            "at": at if (_yschemas.plain_int(at) or 0) > 0 else _yschemas.now_ms()}


def read_edit(tid):
    """保存済みの編集の内容。-> (中身 または None, 壊れているか)。形が正しくないもの(手で書き換えた・書きかけ)は壊れている扱い"""
    try:
        d = _fsio.read_json_file(edit_path(tid), MAX_EDIT_BYTES)   # 上限を超える・UTF-8 でない・NaN を含む = ValueError(壊れている扱い)
    except FileNotFoundError:
        return None, False
    except (OSError, ValueError):
        return None, True
    try:
        if not isinstance(d, dict) or d.get("schema") != EDIT_SCHEMA or _yschemas.plain_int(d.get("rev")) is None:
            return None, True
        out = sanitize_edit(d)
    except (ValueError, _errors.ApiError):
        return None, True
    pr = d.get("packRev")
    out.update({"schema": EDIT_SCHEMA, "rev": max(0, d["rev"]), "updatedAt": d.get("updatedAt") if isinstance(d.get("updatedAt"), int) else 0,
                "packRev": max(0, _yschemas.plain_int(pr) or 0)})
    if isinstance(d.get("pack"), dict):
        out["pack"] = d["pack"]
    draft = sanitize_draft(d.get("draft"))   # 初めてのたたき台の記録(Q2。以前の edit.json には無い)
    if draft:
        out["draft"] = draft
    return out, False


def edit_cut_flags(segs, edit):
    """編集の内容から、各行が「カット済」か。-> [bool](segs と同じ順)。
    行の時間が全部、削る区間に入っていれば(残す区間に入るのが CUT_TOLERANCE_FRAMES 未満なら)カット済。
    ごく短い行(2 × 許す幅 以下)は、行の真ん中が残す区間に入っているかで決める。画面の cut.js も同じ規則"""
    clips = edit["clips"]
    fps = edit["sources"][0]["fps"]
    tol = CUT_TOLERANCE_FRAMES * fps[1] / fps[0]
    starts = [c["in"] for c in clips]
    out = []
    for s in segs:
        a, b = _yschemas.num_or(s.get("start"), 0.0), _yschemas.num_or(s.get("end"), 0.0)
        i = max(0, bisect.bisect_right(starts, a) - 1)
        if b - a <= 2 * tol:
            mid = (a + b) / 2
            j = bisect.bisect_right(starts, mid) - 1
            out.append(not (j >= 0 and clips[j]["in"] <= mid < clips[j]["out"]))
            continue
        kept = 0.0
        while i < len(clips) and clips[i]["in"] < b:
            kept += max(0.0, min(b, clips[i]["out"]) - max(a, clips[i]["in"]))
            i += 1
        out.append(kept < tol)
    return out


def apply_edit_cuts(tid, doc, edit=None):
    """編集の内容があれば、文書の行の cutState をそれに合わせる(文書の書き込みは全部ここを通す)。
    -> 変わった行の数。編集の内容が無い・壊れているときは None(行の cutState はそのまま = 以前の使い方)"""
    if edit is None:
        edit, _broken = read_edit(tid)
        if not edit:
            return None
    segs = [s for s in (doc.get("segments") or []) if isinstance(s, dict)]
    changed = 0
    for s, cut in zip(segs, edit_cut_flags(segs, edit)):
        if cut != (s.get("cutState") == "cut"):
            changed += 1
        if cut:
            s["cutState"] = "cut"
        else:
            s.pop("cutState", None)
    return changed


DRAFT_SLOT_WAIT = 10.0   # 「行から」の行の端の無音を調べる順番(SLOTS)を待つ上限(秒)。過ぎたら無音を調べずに決まった余白で広げる


def _draft_slot(label):
    deadline = time.monotonic() + DRAFT_SLOT_WAIT
    return _heavy.tool_slot(label, cancelled=lambda: time.monotonic() > deadline)   # SLOTS の札の名前は ytt/jobs の configure(tool=)(編集の serve が入れる)


def edit_draft(tid, rows=False):
    """GET /api/edit/draft?id=&rows=1 : 動画の fps・長さと、たたき台「行から」(残す行が無ければ全部残す)。計算は cut2resolve の pack.py(resolve_export.edit_draft)。
    「行から」を計算するのは、カットが無い(壊れている)文書か rows=1(「行から」のボタン)のときだけ(行の端の無音を調べるのは重いので、開くたびにしない)。
    行の端を広げるかは設定の rowEdge(docs/design/edit-tool-design.md の 12 ⑥)。無音の検出は SLOTS を通す(DRAFT_SLOT_WAIT 秒待っても空かなければ決まった余白)。
    カット・パックに使えないとき(動画が無い・ネットワーク上・音声だけ)は {"unavailable": {"code", "message"}}。
    ネットワーク上の動画は調べない(カット・パックに使えない理由を画面に出す。一覧・clip-info と同じく、開くだけで資格情報を送らない)。
    隣の .cut-plan.json(スタジオなどの残す区間の指定)があるかも返す(たたき台「スタジオ」)"""
    doc = read_transcript(tid)
    src = str(doc.get("sourcePath") or "")

    def unavailable(code, message):   # 使えない理由は 200 で返す(画面が毎回エラーとして記録しないように。文書が無いときだけ 404)
        return {"unavailable": {"code": code, "message": message}}
    if not src:
        return unavailable("no_source", "この文書には動画のパスがありません")
    if _fsio.is_network_path(src):
        return unavailable("network_path", "ネットワーク上の動画は、カットとパックに使えません(このパソコンにコピーして開いてください)")
    if not os.path.isfile(src):
        return unavailable("source_missing", "元の動画が見つかりません(移動・削除した可能性があります)")
    try:
        need = bool(rows) or not read_edit(tid)[0]
        out = resolve_export.edit_draft(doc, _workdata.SERVER_VERSION, rows=need, row_edge=_settings.load_settings().get("rowEdge"), heavy=_draft_slot)
    except resolve_export.ResolveExportError as e:
        msg = str(e)
        if "動画ストリーム" in msg:
            return unavailable("no_video", "映像の無いファイル(音声だけ)は、カットとパックに使えません")
        return unavailable("draft_failed", msg)
    out["planBeside"] = _yschemas.find_sidecar(src, ".cut-plan.json") or ""   # 作業用\ → 以前の置き方(動画の隣)
    return out


def edit_keeps_sec(edit):
    """編集の内容の残す区間(秒)。接している区間(分割しただけ)は1つにまとめる(パックと同じ)。
    区間は sanitize_edit が 3 桁に丸めて時刻の順に並べてあるので、つなぎ方は _yschemas.union_spans(接していればつなぐ)と同じ"""
    return _yschemas.union_spans((c["in"], c["out"]) for c in edit["clips"])


def keeps_arg(v):
    """画面から来た残す区間 [[開始, 終了], ...](秒)の検査(cut2resolve の keeps_from_spec と同じ決まり)"""
    if not isinstance(v, list) or not 1 <= len(v) <= MAX_CLIPS:
        raise _errors.ApiError("bad_keeps", "残す区間は 1〜%d 個にしてください" % MAX_CLIPS, 400)
    out, prev = [], 0.0
    for x in v:
        a, b = (_real(x[0]), _real(x[1])) if isinstance(x, list) and len(x) == 2 else (None, None)
        if a is None or b is None or not 0 <= a < b <= MAX_MEDIA_SEC or a < prev:
            raise _errors.ApiError("bad_keeps", "残す区間は時刻の順に、重ならないように [開始, 終了] で指定してください", 400)
        out.append([a, b])
        prev = b
    return out


def edit_preview(obj):
    """POST /api/edit/preview {"id", "keeps"}: カットのとおりに作ったときのパックの見積もり(区間の数・カット後の長さ・Text+ 字幕の数・注意)。ファイルは作らない"""
    doc = read_transcript(str(obj.get("id") or ""))
    keeps = keeps_arg(obj.get("keeps"))
    src = str(doc.get("sourcePath") or "")
    if not src or _fsio.is_network_path(src) or not os.path.isfile(src):
        raise _errors.ApiError("no_media", "元の動画が見つかりません", 400)
    try:
        return resolve_export.edit_preview(doc, keeps, _workdata.SERVER_VERSION, wrap_arg(obj.get("wrap")))
    except resolve_export.ResolveExportError as e:
        raise _errors.ApiError("preview_failed", str(e), 400)


def wrap_arg(v, size=None):
    """Text+ 字幕の1段の文字数(0〜40)。無ければ設定の subtitle.wrapChars(size が横 1920x1080 なら横、それ以外は縦)"""
    if _yschemas.is_num(v) and 0 <= v <= 40:
        return int(v)
    from . import doc_jobs   # 呼ぶときに読む(doc_jobs は読み込みのときにこの部品を読むので、循環を作らない)
    sub = doc_jobs.subtitle_settings()
    return sub["wrapChars"]["horizontal" if str(size or "") == "1920x1080" else "vertical"]


def get_edit(tid):
    """GET /api/edit?id= -> {"edit": 中身 | null, "rev", "broken"}(無ければ null と rev 0)"""
    doc = read_transcript(tid)
    d, broken = read_edit(tid)
    pk = (d or {}).get("pack") or {}
    stale = pack_stale({"packRev": d["packRev"] if d else 0, "editRev": d["rev"] if d else 0, "updatedAt": doc.get("updatedAt") or 0,
                        "_packDocAt": pk.get("docUpdatedAt") if isinstance(pk.get("docUpdatedAt"), int) else 0})
    return {"edit": d, "rev": d["rev"] if d else 0, "broken": broken, "packStale": stale}


def save_edit(tid, obj):
    """PUT /api/edit?id= {"edit", "baseRev", "draft"?} -> {"rev", "cutRows", "updatedAt"}。baseRev が保存済みの rev と違えば 409(別のタブ・窓で先に保存された)。
    draft = 画面がそのカットを始めたたき台(sanitize_draft)。保存済みの edit.json に draft が無いときだけ一度だけ書く(上書きしない。Q2)。
    文書の行の cutState も同じロックの中で合わせる(画面から2回に分けて送らない)。文書の updatedAt は変えない
    (cutState は編集の内容から決まる値なので、校正の保存の競合の検出(baseUpdatedAt)に巻き込まない)"""
    base = obj.get("baseRev")
    if _yschemas.plain_int(base) is None or base < 0:
        raise _errors.ApiError("bad_request", "baseRev(読み込んだときの rev)を付けてください", 400)
    clean = sanitize_edit(obj.get("edit"))
    with _save_lock:
        doc = read_transcript(tid)
        cur, broken = read_edit(tid)
        rev = cur["rev"] if cur else 0
        if base != rev:
            raise _errors.ApiError("conflict", "別のタブか窓で、先にカットが保存されています。読み直すか、こちらの内容で上書きするか選んでください", 409, {"rev": rev})
        if broken:   # 壊れたファイルは上書きする前に1つだけ残す(調べられるように)
            try:
                shutil.copy2(edit_path(tid), os.path.join(_workdata.TX_DIR, tid + ".edit.broken.json"))
            except OSError:
                pass
        now = _yschemas.now_ms()
        d = dict(clean, schema=EDIT_SCHEMA, rev=rev + 1, updatedAt=now, packRev=cur["packRev"] if cur else 0)
        if cur and cur.get("pack"):
            d["pack"] = cur["pack"]
        if cur and cur.get("draft"):
            d["draft"] = cur["draft"]
        elif not cur:   # 初めての保存(壊れていたファイルの上書きを含む)のときだけ。以前の版で作った edit.json には後から足さない(始めたたき台が分からないため)
            draft = sanitize_draft(obj.get("draft"))
            if draft:
                d["draft"] = draft
        body = json.dumps(d, ensure_ascii=False, indent=1).encode("utf-8")
        if len(body) > MAX_EDIT_BYTES:
            raise _errors.ApiError("too_big", "区間が多すぎて保存できません", 413)
        _fsio.atomic_write(edit_path(tid), body, fsync_required=True)   # 先に編集の内容(文書の書き込みが失敗しても、次の保存で cutState は合う)
        if apply_edit_cuts(tid, doc, d):
            write_doc(tid, doc)
        cut_rows = [s.get("id") for s in doc.get("segments") or [] if isinstance(s, dict) and s.get("cutState") == "cut"]
        return {"rev": d["rev"], "cutRows": cut_rows, "updatedAt": now}


PACK_OUTPUT_LOUDNESS = (0, -11, -14, -16, -18)


def _pack_text(v, limit):
    """出力の設定の文字列: 長さの上限以内・制御文字なし(改行・タブ・NUL などを含めば None)"""
    if not isinstance(v, str) or len(v) > limit or any(ord(ch) < 32 or ord(ch) == 127 for ch in v):
        return None
    return v


# 出力の設定の鍵と検査(値を受けるなら True)。必須は全部そろわなければ output なし。任意は入っていれば正しいこと
_PACK_REQUIRED = (("fps", lambda v: isinstance(v, str) and re.fullmatch(r"\d{1,3}", v, re.A) is not None),
                  ("size", lambda v: v in ("1080x1920", "1920x1080")),
                  ("wrap", lambda v: _yschemas.int_in(v, 0, 40) is not None),
                  *((k, lambda v: isinstance(v, bool)) for k in ("textplus", "backup", "render", "speakerColors")))
_PACK_OPTIONAL = (("streamer", lambda v: _pack_text(v, 200) is not None),
                  ("loudness", lambda v: _yschemas.is_num(v) and v in PACK_OUTPUT_LOUDNESS),
                  ("volume", lambda v: _yschemas.int_in(v, 1, 200) is not None))


def sanitize_pack_output(o):
    """POST /api/edit/pack の output(作ったときの出力の設定)を確かめる。決まった鍵だけ残し(余計な鍵は黙って捨てる)、
    必須の鍵が1つでも正しくなければ、あるいは任意の鍵が入っていて正しくなければ None(= 記録には output を入れない。
    古い画面・まとめて実行 home/autorun.py は output を送らないので、エラーにはしない)。bool は int でもあるので数の検査は schemas で(bool を数えない)。
    鍵と検査は表 _PACK_REQUIRED・_PACK_OPTIONAL(足すときは 1 行。並びは記録の鍵の順)"""
    if not isinstance(o, dict):
        return None
    out = {}
    for k, ok in _PACK_REQUIRED:
        if not ok(o.get(k)):
            return None
        out[k] = o[k]
    for k, ok in _PACK_OPTIONAL:
        if k in o:
            if not ok(o[k]):
                return None
            out[k] = o[k]
    if "advanced" in o:
        adv = o["advanced"]
        if not isinstance(adv, dict):
            return None
        a = {}
        for k in ("srcStartTc", "recStart", "reel"):
            if k in adv:
                t = _pack_text(adv[k], 40)
                if t is None:
                    return None
                a[k] = t
        out["advanced"] = a
    if "speakerStyles" in o:   # 話者ごとの字幕の見た目 {話者の名前: {"color": "#RRGGBB"}}(文書の話者の sub。2026-10-05)
        ss = o["speakerStyles"]
        if not isinstance(ss, dict) or len(ss) > 21:
            return None
        styles = {}
        for name, st in ss.items():
            nm = _pack_text(name, 60)
            one = sanitize_sub_style(st)
            if not nm or one is None:
                return None
            styles[nm] = one
        if styles:
            out["speakerStyles"] = styles
    return out


def record_pack(obj):
    """POST /api/edit/pack {"id", "rev", "docUpdatedAt", "dir", "files"}: 画面がパックを作り終えたときに呼ぶ(rev は増やさない)。
    packRev = そのパックを作った編集の rev。rev ≠ packRev か、文書の updatedAt が docUpdatedAt より新しければ「作り直し」"""
    tid = str(obj.get("id") or "")
    rev, dua = obj.get("rev"), obj.get("docUpdatedAt")
    if _yschemas.plain_int(rev) is None or rev < 1 or _yschemas.plain_int(dua) is None or dua < 0:
        raise _errors.ApiError("bad_request", "rev・docUpdatedAt が正しくありません", 400)
    out_dir = obj.get("dir")
    if not isinstance(out_dir, str) or not out_dir or len(out_dir) > 1000 or any(ch in out_dir for ch in "\x00\r\n") or not os.path.isabs(out_dir):
        raise _errors.ApiError("bad_request", "パックのフォルダ(dir)が正しくありません", 400)
    files = [os.path.basename(str(x))[:200] for x in (obj.get("files") or []) if isinstance(x, str)][:40] if isinstance(obj.get("files"), list) else []
    output = sanitize_pack_output(obj.get("output"))
    with _save_lock:
        read_transcript(tid)
        cur, _broken = read_edit(tid)
        if not cur:
            raise _errors.ApiError("no_edit", "カットがまだ保存されていません", 409)
        if rev > cur["rev"]:
            raise _errors.ApiError("bad_request", "rev が保存済みのカットより新しくなっています", 400)
        now = _yschemas.now_ms()
        pk = {"rev": rev, "at": now, "docUpdatedAt": dua, "dir": out_dir, "files": files}
        if output is not None:
            pk["output"] = output
        d = dict(cur, packRev=rev, pack=pk)
        _fsio.atomic_write(edit_path(tid), json.dumps(d, ensure_ascii=False, indent=1).encode("utf-8"), fsync_required=True)
        return {"ok": True, "packRev": rev, "at": now}


def edit_summary(tid):
    """一覧の各文書の編集・パックの状態(ファイルの更新日時と大きさが同じなら前の結果)。"""
    key = _fsio.stamp(edit_path(tid))
    if key is None:
        _edit_cache.pop(tid, None)
        return {"hasEdit": False, "editRev": 0, "packRev": 0, "_packDocAt": 0, "packAt": 0}
    hit = _edit_cache.get(tid)
    if hit and hit[0] == key:
        return hit[1]
    d, _broken = read_edit(tid)
    pk = (d or {}).get("pack") or {}
    sm = {"hasEdit": bool(d), "editRev": d["rev"] if d else 0, "packRev": d["packRev"] if d else 0,
          "_packDocAt": pk.get("docUpdatedAt") if isinstance(pk.get("docUpdatedAt"), int) else 0,
          "packAt": pk.get("at") if isinstance(pk.get("at"), int) else 0}
    _edit_cache[tid] = (key, sm)
    return sm


def pack_stale(item):
    """パックを作ったあとにカットか文字が変わったか(一覧と画面の「作り直し」の知らせ。規則はここ1か所)"""
    return bool(item.get("packRev")) and (item.get("editRev") != item.get("packRev") or (item.get("updatedAt") or 0) > (item.get("_packDocAt") or 0))


def doc_has_rows(doc):
    return any(isinstance(s, dict) and str(s.get("text") or "").strip() for s in doc.get("segments") or [])


def fill_doc(spec, fields):
    """文字起こしの結果を、文字起こしの無い文書(intoDoc)に入れる。id・題名・作った日・clip・編集の内容はそのまま。
    -> 入れた文書の id。その間に文書が消えた・行が入った・動画が変わったときは None(呼び出し側が新しい文書にする。結果は捨てない)"""
    tid = spec["intoDoc"]
    with _save_lock:
        try:
            doc = read_transcript(tid)
        except _errors.ApiError:
            doc = None
        same = doc is not None and _fsio.norm_path(str(doc.get("sourcePath") or "")) == os.path.normcase(spec["sourcePath"])
        if not same or doc_has_rows(doc):
            spec.setdefault("warnings", []).append("文字起こしを入れる文書が変わっていたため、新しい文字起こしとして保存しました")
            return None
        doc.update(fields)
        if spec.get("clip") and not doc.get("clip"):
            doc["clip"] = spec["clip"]
        if spec.get("evalSet"):
            doc["evalSet"] = True   # 評価用として文字起こしした(外すのは画面の「評価用にする」)
        doc.pop("evalReviewed", None)   # 機械が行を書いたので「全部聞いて確かめた」印は外す(行の無い文書を確かめ済みにしていたとき)
        apply_edit_cuts(tid, doc)   # 先にカットを決めてあれば、行の「カット済」もそれに合わせる
        write_doc(tid, doc)
        return tid


_open_lock = threading.Lock()


def find_doc_for_media(path):
    """その動画の文書(行のある文書・更新が新しいものを先に)。-> {"id", "rows"} か None。パスを比べるだけで、ファイルには触らない"""
    p = str(path or "").strip().strip('"')
    if not p or "\x00" in p:
        return None
    key = _fsio.norm_path(p)
    best = None
    for tid, sm, _sp in summaries():
        if not any(p and _fsio.norm_path(p) == key for p in [sm["_sourcePath"]] + list(sm.get("_aliases") or ())):
            continue
        rank = (sm["rows"] > 0, sm.get("updatedAt") or 0)
        if best is None or rank > best[0]:
            best = (rank, {"id": tid, "rows": sm["rows"]})
    return best[1] if best else None


def open_video(req):
    """POST /api/open-video {"path", "title"?} -> {"id", "created", "warnings"}。「文字起こしせずに開く」: 動画のパスだけで文書を作る。
    同じ動画の文書があればそれを返す(行のある文書・新しいものを先に)。隣の .clip.json があれば文書の clip に入れる(スタジオの切り抜きと紐づく)。
    文書にした動画は /media で配るので、動画・音声の拡張子で、ffmpeg で映像か音声が読めるものだけ受け付ける"""
    src = _tools.check_source(req.get("path"))
    with _open_lock:   # 同じ動画を続けて2回開いても、文書を2つ作らない
        hit = find_doc_for_media(src)
        if hit:
            return {"id": hit["id"], "created": False, "warnings": []}
        dur, has_v, has_a = _tools.probe_media(src)
        if not (has_v or has_a):
            raise _errors.ApiError("bad_media", "動画・音声として読めませんでした(壊れているか、対応していない形式です)", 400)
        clip, warn, _cp = _yschemas.find_clip(src, dur)
        tid = uuid.uuid4().hex[:12]
        now = _yschemas.now_ms()
        doc = {"schema": "transcribe/v1", "id": tid, "title": str(req.get("title") or "").strip()[:120] or os.path.splitext(os.path.basename(src))[0][:120],
               "sourcePath": src, "sourceName": os.path.basename(src), "start": 0, "end": round(dur, 2) if dur else None, "whole": True,
               "duration": dur, "model": "", "language": "", "params": {}, "speakers": [], "segments": [], "original": [],
               "createdAt": now, "updatedAt": now}
        if clip:
            doc["clip"] = clip
        with _save_lock:
            write_doc(tid, doc)
    _txbase.log.info("文字起こしせずに開く: %s", os.path.basename(src))
    return {"id": tid, "created": True, "warnings": [warn] if warn else []}
