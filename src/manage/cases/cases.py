"""案件(配信1本)ごとの紐づけ(統合計画の段階4)。入口の「案件」画面(src/home/portal.html)の中身を作る。

案件 = 切り抜きスタジオの動画1本(配信・ファイル)。その下に、書き出した切り抜きと、それぞれの文字起こし・パックを並べる。
紐づけは、各ツールが持っているデータを**読むたびに組み立て直す**(各ツールの記録と食い違わないように。2026-09-26 ユーザーと決定):
  - 切り抜き … スタジオの data.json の「書き出し済み」のマーク(書き出した mp4 の絶対パスを持つ)
  - 文字起こし … 文字起こしツールの transcripts/*.json(元の動画のパスが切り抜きと同じ。無ければ .clip.json の配信・マークが同じ。
                規則は src/manage/cases/txindex.py にあり、スタジオのセリフの表示と共通)
  - パック … 切り抜きの隣の <名前>_pack フォルダ(cut2resolve の既定の出力先)
案件ファイル(<作業データ>\\app\\cases.json)に持つのは、人が付ける状態・メモと、最後に見えた紐づけ(元のファイルを消しても履歴が残るように)。
各ツールのデータは読むだけで、書き換えない。
**RS8 B3-6**: 案件にした配信(data.json の行が case を持つ・または書き出し先の直下に 作業用/採用.json がある)の状態・メモ・自動の確認は、cases.json でなく
案件の 採用.json の上の段(status・memo・statusUpdatedAt・auto)に持つ(書くのは flow/casebook.write・ロックは ytt/casefiles.lock。marks・sources は触らない)。
一覧は索引(data.json)∪ 書き出し先の走査。cases.json は案件の無い配信の分だけ(採用.json に欄がまだ無い案件は cases.json の行を引き継いで書き、行を消す)。

画面が一覧(1件1行)を組み立てやすいように、案件1件ごとに追加で持たせる項目(2026-09-26 画面の見直し。既存の項目は変えない):
  - streamedAt: 「いつの配信か」の目安(ms)。① スタジオの解析結果(analysis.uploadDate、実際の配信日)② 無ければ案件が
    スタジオに追加された時刻(createdAt)③ それも無ければ updatedAt、の順(デモ環境や解析前の動画では ①が無い)
  - tx: 切り抜き全体の文字起こし・校正の進み具合の合計 {clips, withTranscript, segments, proofed}
  - packs: 切り抜き全体のパックの有無の合計 {have, total, textplus}
  - next: 一覧に出す「次にやること」1つ {kind, label, count} か None(すべて済み)。TODO_ORDER(校正 → パック → 文字起こし → 書き出し → 候補の確認。
    仕掛かりを先に終わらせる)の順で最初に残っている作業。ホームの「次にやること」の並びも同じ表(build の todoOrder)を使うので、同じ配信なら
    上の一覧の先頭の作業と行のボタンが必ず同じになる(UI の見直し 1 周目 M1)。パックは「文字起こしが全部校正済みでパックがまだの切り抜き」の数
  - todo: 作業ごとの残りの数 {review, export, transcribe, proof, pack}(ホームの「次にやること」に種類ごとの行を出す。入口 0.42.0・S-6)
    review = 確認前の候補(採用・見送りを付けていないマーク)の数。まだ 1 本も採用・書き出ししていない配信だけ数える
    (選び始めたあとに残った候補は「選ばなかったもの」として扱い、次にやることに出し続けない)
  - remaining: next も含めた残作業の合計件数(並び替え「次にやることが多い順」に使う。候補の確認は候補の数ではなく配信 1 本で 1 件)
スタジオから消えた配信(gone)は、候補の確認・書き出しをスタジオでできないので数えない(文字起こし・校正・パックは残った切り抜きで数える)。

自動でできた切り抜きの確認(線 D の M9・M12・M13。計画 plan/line-d-auto-pack.md の段階 4・6):
  - 配信(kind live)の切り抜きのうち、.clip.json の source.live.origin が auto(配信中の候補 = M11)か archive(配信後の解析 = M7)のものに
    clip["auto"] = {origin, originLabel, score, bench} を付ける(人の切り抜き manual は None = 今までどおり)。点数は .clip.json の source.live.score →
    mark.score → スタジオのマークの score の順(今は書き手が無いことが多い。無ければ None = 画面に出さない)。
    bench = 1 時間の枠から外れた候補(「控え」。M13: 書き出し済みなら取り消さない。ワーカーが付けたら出すだけ)
  - clip["review"] = {seenAt, deliveredAt, delivered, failure, unconfirmed}: 人が見たか・届けたか(案件ファイルの auto)・失敗の文
    (M3。src/pipeline/live_failures.failure_of だけが作る。<作業データ>/app/live/exports.json の書き出しのジョブをスタジオのマークで引く。読むだけ)。
    unconfirmed = 見ても・届けてもいない(「自動の切り抜き: 未確認 n 件」の数)。案件の autoClips {total, unconfirmed}・一覧全体の auto も同じ数
  - 操作は auto_review(POST /api/cases/auto): seen = 見た / deliver = 採用 = パックを zip にして Dropbox の 出力 へ(src/human/friend/deliver.py。
    全自動では届けない = 10-06 ユーザー決定)/ discard = 要らない = パック・切り抜きの mp4・.clip.json などを ごみ箱フォルダ へ移す(片付けと同じ場所。
    片付けの TRASH_DAYS で起動時に消える)+ スタジオのマークを不採用に + live_feedback.jsonl に誤検出の記録 + その文字起こしを一覧で非表示に(データは消さない)
  - 案件ファイルには cases[配信]["auto"][スタジオのマーク] = {seenAt, deliveredAt, delivered, discardedAt, tx} を持つ(要らないにした文字起こし tx は
    「単体の文字起こし」に出さない)
"""
import datetime
import os
import re
import shutil
import threading
import time
import urllib.parse

from . import txindex   # 同じ manage/cases の兄弟
from ytt import casefiles, datadir, errors, fsio, schemas, studiodata, tools
from manage.keep import cleanup  # noqa: E402  (ごみ箱フォルダの場所・名前の付け方・manifest・一緒に片付ける途中のファイルの決まりは片付けと同じ)
from flow import casebook, live_failures   # 失敗の文は 1 か所。線 D の M3 / 案件の採用.json を書く口(RS8 B3-6)
from flow import placement   # 置き場所の持ち主(スタジオの data.json。RS6 b-B0)

SCHEMA = "youtube-tools-cases/v1"
STATUSES = ("", "working", "posted", "skipped")        # 未設定・作業中・投稿済み・見送り
MAX_MEMO = 2000
MAX_JSON = 64 * 1024 * 1024
_lock = threading.Lock()
# 次にやることの順(仕掛かりを先に終わらせる)と、作業の名前。ホームの「次にやること」(portal.js)も build() の todoOrder でこの順を使う(正はここ 1 か所)
TODO_ORDER = ("proof", "pack", "transcribe", "export", "review")
TODO_LABEL = {"proof": "校正", "pack": "パックを作る", "transcribe": "文字起こし", "export": "書き出し", "review": "候補の確認"}
# 自動でできた切り抜き(線 D の M9)。.clip.json の source.live.origin(src/flow/live_export.py の ORIGINS の auto・archive)→ 画面に出す出どころ
AUTO_ORIGINS = {"auto": "配信中の候補", "archive": "配信後の解析"}
AUTO_OPS = ("seen", "deliver", "discard")
AUTO_KEEP = 2000                   # 案件 1 件で覚えておく確認の数(古いものから捨てる)
DISCARD_KIND = "discard"           # ごみ箱/<日付>/ の下の種類の名前(片付けの export・work などと並ぶ)
MARK_RE = re.compile(r"^[\w-]{1,40}\Z", re.ASCII)   # スタジオのマークの id(src/human/review/store.py の ID_RE と同じ形)
STUDIO_TRIES = 3                   # スタジオの保存とぶつかったときに読み直す回数(src/home/live.py の採用と同じ)
_busy, _busy_lock = set(), threading.Lock()   # 「要らない」の途中の (配信, マーク)(二度押し・窓を 2 つ並べたときに同じものを二重に動かさない)
_readers = {}                      # まとめて実行の記録のパス → live_failures.Reader(変わったときだけ読み直す)


def _read_json(path, limit=MAX_JSON):
    try:
        return fsio.read_json_file(path, limit)
    except (OSError, UnicodeError, ValueError):
        return None


def locations(repo_root, env=None):
    """{"studio": data.json, "transcripts": フォルダ, "cases": cases.json, "liveJobs": 線 D の書き出しのジョブ, "runs": まとめて実行の記録}。
    置き場所の規則は ytt.datadir.resolve の1か所
    (起動したツールが登録した場所 → STUDIO_HOME などの環境変数 → YTT_DATA_DIR・既定の場所。env を渡したときは登録を見ない)。
    スタジオの data.json は置き場所の持ち主 flow/placement の studio_data(RS6 b-B0。値は同じ)"""
    app = datadir.resolve("app", repo_root, env)
    return {"studio": placement.studio_data(repo_root, env), "transcripts": txindex.folder(repo_root, env),
            "cases": os.path.join(app, "cases.json"), "liveJobs": os.path.join(app, "live", "exports.json"),
            "runs": os.path.join(app, "logs", "autorun-runs.jsonl")}


# ---------------------------------------------------------------- 各ツールのデータを読む(読むだけ)

def read_studio(path):
    return studiodata.videos(path)


def read_transcripts(folder):
    """文字起こしの一覧(manage.cases.txindex。スタジオのセリフの表示と同じ読み方・紐づけの規則)"""
    return txindex.load(folder)


def find_pack(media_path):
    """切り抜きの隣の <名前>_pack(cut2resolve の既定の出力先)。-> {"dir", "textplus", "updatedAt"} か None。
    規則は src/manage/cases/txindex.pack_info の1か所(文字起こしの一覧と同じ判定)"""
    return txindex.pack_info(media_path)


def _upload_date_ms(s):
    """analysis.uploadDate("YYYYMMDD")→ ms。形が違えば 0"""
    if isinstance(s, str) and len(s) == 8 and s.isdigit():
        try:
            d = datetime.datetime(int(s[:4]), int(s[4:6]), int(s[6:8]), tzinfo=datetime.timezone.utc)
            return int(d.timestamp() * 1000)
        except ValueError:
            return 0
    return 0


def _int_ms(x):
    return x if isinstance(x, int) and not isinstance(x, bool) and x > 0 else 0


def _stream_time(v):
    """「いつの配信か」の目安(ms)。解析で分かった配信日 → 案件が増えた時刻 → 最後に触った時刻、の順"""
    an = v.get("analysis") if isinstance(v.get("analysis"), dict) else {}
    return _upload_date_ms(an.get("uploadDate")) or _int_ms(v.get("createdAt")) or _int_ms(v.get("updatedAt"))


def _case_extras(c):
    """一覧の1行に要る合計・「次にやること」(2026-09-26)。clips・marks だけから作れるので、案件の生成元(スタジオに
    まだある配信・消えた配信の最後に見えた内容)のどちらでも同じ規則で計算できる"""
    clips = c.get("clips") or []
    marks = c.get("marks") or {}
    gone = bool(c.get("gone"))                                                                      # スタジオから消えた配信(確認・書き出しはできない)
    total = len(clips)
    with_tx = [cl["transcript"] for cl in clips if cl.get("transcript")]
    have_pack = sum(1 for cl in clips if cl.get("pack"))
    picked = int(marks.get("adopted") or 0) + total                                                 # 採用・書き出しを 1 本でも決めたか
    review = 0 if gone or picked else int(marks.get("candidates") or 0)                             # 確認前の候補(まだ 1 本も選んでいない配信だけ)
    to_export = 0 if gone else int(marks.get("adopted") or 0)                                       # 採用済みでまだ書き出していない
    missing_tx = sum(1 for cl in clips if not cl.get("transcript"))                                 # 書き出し済みで文字起こしがまだ
    proofing = sum(1 for t in with_tx if t.get("proofed", 0) < t.get("segments", 0))                # 文字起こしはあるが校正が残っている
    missing_pack = total - have_pack                                                                # 書き出し済みでパックがまだ
    # パックを作れる = 文字起こしが全部校正済みでパックがまだ(校正の前にパックを勧めない。ホームの校正待ち・パック待ちと同じ条件)
    ready_pack = sum(1 for cl in clips if cl.get("transcript") and cl["transcript"].get("segments", 0) > 0
                     and cl["transcript"].get("proofed", 0) >= cl["transcript"]["segments"] and not cl.get("pack"))
    todo = {"review": review, "export": to_export, "transcribe": missing_tx, "proof": proofing, "pack": missing_pack}
    autos = [cl for cl in clips if cl.get("auto")]
    nxt = None
    for k in TODO_ORDER:
        n = ready_pack if k == "pack" else todo[k]
        if n > 0:
            nxt = {"kind": k, "label": TODO_LABEL[k], "count": n}
            break
    return {"tx": {"clips": total, "withTranscript": len(with_tx), "segments": sum(t["segments"] for t in with_tx),
                   "proofed": sum(t["proofed"] for t in with_tx)},
            "packs": {"have": have_pack, "total": total, "textplus": sum(1 for cl in clips if cl.get("pack") and cl["pack"].get("textplus"))},
            "next": nxt, "todo": todo,
            "remaining": (1 if review else 0) + to_export + missing_tx + proofing + missing_pack,
            "autoClips": {"total": len(autos), "unconfirmed": sum(1 for cl in autos if (cl.get("review") or {}).get("unconfirmed"))},
            "streamedAt": c.get("streamedAt") or c.get("updatedAt") or 0}


# ---------------------------------------------------------------- 自動でできた切り抜き(線 D の M9)

def clip_live(media_path):
    """切り抜きの .clip.json の (source.live, mark)(線 D の書き出し = src/flow/live_export.py の _finish が書く。source.kind は live)。
    無い・読めない・ライブでない・ネットワーク上のパスなら (None, None)。まとめて実行の M8(src/home/autorun.py の live_auto_origin)も同じ読み方"""
    if not isinstance(media_path, str) or not media_path or fsio.is_network_path(media_path):   # ネットワーク上のパスには触らない(資格情報を送らない。txindex と同じ)
        return None, None
    cp = schemas.find_clip_path(media_path)
    clip = schemas.load_clip_file(cp)[0] if cp else None
    src = clip.get("source") if isinstance(clip, dict) else None
    live = src.get("live") if isinstance(src, dict) and src.get("kind") == "live" else None
    if not isinstance(live, dict):
        return None, None
    return live, clip.get("mark") if isinstance(clip.get("mark"), dict) else {}


def auto_info(mark, media_path):
    """自動でできた切り抜きなら {origin, originLabel, score, bench}、人の切り抜き・.clip.json が無い・読めないなら None。
    mark: スタジオのマーク(点数 score を持つことがある)"""
    live, cmark = clip_live(media_path)
    origin = live.get("origin") if live else None
    if origin not in AUTO_ORIGINS:
        return None
    score = next((x for x in (schemas.num(live.get("score")), schemas.num(cmark.get("score")), schemas.num(mark.get("score"))) if x is not None), None)
    return {"origin": origin, "originLabel": AUTO_ORIGINS[origin], "score": None if score is None else round(score, 2), "bench": live.get("bench") is True}


def live_failures_by_mark(loc):
    """線 D の書き出しのジョブ(<作業データ>/app/live/exports.json)の失敗 -> {(スタジオの配信, マーク): {kind, kindLabel, text}}。
    同じマークのジョブが複数あれば新しいものだけ。文は live_failures.failure_of だけが作る(「調子」・LIVE の帯と同じ文)。読むだけ"""
    from flow import live_export   # 入口のプロセスでは読み込み済み(ここで読むのは、ライブの配信が無ければ要らないため)
    d = _read_json(loc["liveJobs"], 8 * 1024 * 1024)
    jobs_ = d.get("jobs") if isinstance(d, dict) and d.get("schema") == live_export.JOBS_SCHEMA else None
    latest = {}
    for j in jobs_ if isinstance(jobs_, list) else []:
        st = j.get("studio") if isinstance(j, dict) else None
        if isinstance(st, dict) and st.get("video") and st.get("mark"):
            k = (str(st["video"]), str(st["mark"]))
            if k not in latest or str(j.get("updated") or "") >= str(latest[k].get("updated") or ""):
                latest[k] = j
    if not latest:
        return {}
    reader = _readers.get(loc["runs"]) or _readers.setdefault(loc["runs"], live_failures.Reader(loc["runs"]))
    try:
        runs = reader.runs()
    except Exception:   # 記録を読めなくても、書き出しの失敗は出す
        runs = {}
    out = {}
    for k, j in latest.items():
        f = live_failures.failure_of(j, runs.get(j.get("runId")) if j.get("runId") else None)
        if f:
            out[k] = {"kind": f["kind"], "kindLabel": f["kindLabel"], "text": f["text"]}
    return out


def _auto_records(s):
    """案件ファイルの 1 件の auto(スタジオのマーク → 確認の記録)の写し。壊れた項目は除く"""
    a = s.get("auto") if isinstance(s, dict) else None
    return {k: v for k, v in a.items() if isinstance(k, str) and isinstance(v, dict)} if isinstance(a, dict) else {}


def _apply_review(cases, saved, failures):
    """自動でできた切り抜きに、人の確認(案件ファイルの auto)と失敗の文を重ねる(clip["review"])"""
    for c in cases:
        rec = _auto_records(saved.get(c["id"]))
        for cl in c.get("clips") or []:
            if not cl.get("auto"):
                continue
            r = rec.get(cl.get("markId")) if isinstance(rec.get(cl.get("markId")), dict) else {}
            seen, done = _int_ms(r.get("seenAt")), _int_ms(r.get("deliveredAt"))
            cl["review"] = {"seenAt": seen, "deliveredAt": done, "delivered": str(r.get("delivered") or "")[:200],
                            "failure": failures.get((c["id"], cl.get("markId"))), "unconfirmed": not (seen or done)}


# ---------------------------------------------------------------- 組み立て

def build(videos, transcripts, saved=None, pack_finder=find_pack, failures=None):
    """-> {"cases": [...], "unlinked": [文字起こし], "todoOrder", "auto": {total, unconfirmed}}。saved: cases.json の中身(状態・メモ・最後に見えた紐づけ・
    自動でできた切り抜きの確認)。failures: live_failures_by_mark の結果(線 D の書き出し・文字起こし・パックの失敗の文)"""
    saved = saved or {}
    used = set()
    cases = []
    for vid, v in videos.items():
        if not isinstance(v, dict):
            continue
        marks = [m for m in (v.get("marks") or []) if isinstance(m, dict)]
        clips = []
        for m in sorted((m for m in marks if m.get("status") == "exported"), key=lambda m: (m.get("start") or 0)):
            path = m.get("path") if isinstance(m.get("path"), str) else ""
            tx, n, ids = txindex.pick(transcripts, vid, m.get("id"), path)
            used.update(ids)
            clips.append({"markId": str(m.get("id") or ""), "label": str(m.get("label") or "")[:80], "start": m.get("start"), "end": m.get("end"),
                          "file": str(m.get("file") or ""), "path": path, "exists": bool(path) and os.path.isfile(path),
                          "transcript": txindex.summary(tx) if tx else None, "transcripts": n, "pack": pack_finder(path) if path else None,
                          "auto": auto_info(m, path) if v.get("kind") == "live" else None})   # 自動でできた切り抜き(線 D の M9。ライブの録画だけ)
        s = saved.get(vid) if isinstance(saved.get(vid), dict) else {}
        cases.append({"id": vid, "kind": v.get("kind") or "", "title": str(v.get("title") or v.get("fileName") or vid)[:120],
                      "channel": str(v.get("channel") or "")[:100], "duration": v.get("duration") or 0,
                      "marks": {"total": len(marks), "adopted": sum(1 for m in marks if m.get("status") == "adopted"),
                                "exported": len(clips), "candidates": sum(1 for m in marks if not m.get("status"))},
                      "clips": clips, "status": s.get("status") if s.get("status") in STATUSES else "",
                      "memo": str(s.get("memo") or "")[:MAX_MEMO], "statusUpdatedAt": s.get("statusUpdatedAt") or 0,
                      "updatedAt": v.get("updatedAt") or 0, "streamedAt": _stream_time(v), "gone": False})
    # スタジオから消えた動画も、状態・メモを付けていれば、最後に見えた紐づけで残す
    for cid, s in saved.items():
        if cid not in videos and isinstance(s, dict) and (s.get("status") or s.get("memo")) and isinstance(s.get("last"), dict):
            last = dict(s["last"], id=cid, status=s.get("status") if s.get("status") in STATUSES else "",
                        memo=str(s.get("memo") or "")[:MAX_MEMO], gone=True)
            cases.append(last)
    _apply_review(cases, saved, failures or {})
    for c in cases:
        c.update(_case_extras(c))
    cases.sort(key=lambda c: -(c.get("updatedAt") or 0))
    # 「要らない」にした自動の切り抜きの文字起こしは、マークが不採用になって紐づかなくなっても「単体の文字起こし」に出さない
    dropped = {r.get("tx") for s in saved.values() for r in _auto_records(s).values() if isinstance(r, dict) and r.get("discardedAt") and r.get("tx")}
    unlinked = [dict(txindex.summary(t), sourcePath=t["sourcePath"]) for t in transcripts if t["id"] not in used and t["id"] not in dropped]
    unlinked.sort(key=lambda t: -t["updatedAt"])
    return {"cases": cases, "unlinked": unlinked, "todoOrder": list(TODO_ORDER),
            "auto": {k: sum(c["autoClips"][k] for c in cases) for k in ("total", "unconfirmed")}}


# ---------------------------------------------------------------- 案件ファイル

def load_saved(path):
    d = _read_json(path, 16 * 1024 * 1024)
    if not isinstance(d, dict) or d.get("schema") != SCHEMA or not isinstance(d.get("cases"), dict):
        return {}
    return d["cases"]


def _write(path, saved):
    os.makedirs(os.path.dirname(path), exist_ok=True)
    fsio.write_json(path, {"schema": SCHEMA, "cases": saved})


# ---------------------------------------------------------------- 案件の根(RS8 B3-6。状態・メモ・自動の確認は案件の 採用.json の上の段へ)
FIELDS = ("status", "memo", "statusUpdatedAt", "auto")   # cases.json の 1 件から 採用.json の上の段に移った欄(last は案件の行では要らない)


def _scan_roots(repo_root, env=None):
    """書き出し先(outDir)の直下で 作業用/採用.json を持つフォルダ = 案件の根の一覧(読むだけ・固定ディスクの外・ネットワーク上は見ない)"""
    try:
        out = datadir.studio_out_dir(repo_root, env)
        if not os.path.isabs(out) or casefiles.is_remote(out) or not fsio.is_fixed_drive(out) or not os.path.isdir(out):
            return []
        names = sorted(os.listdir(out))
    except OSError:
        return []
    return [os.path.join(out, n) for n in names
            if os.path.isfile(casefiles.work_path(os.path.join(out, n), casefiles.ADOPTIONS_NAME))]


def _studio_view(repo_root, env, loc):
    """-> (配信 {id: 配信}, 案件の根 {配信の id: 根})。配信 = data.json の索引(案件の行は 候補.json・採用.json を重ねた形。ytt/studiodata)
    ∪ 書き出し先の走査で見つけた案件の配信(索引に無い物 = 索引を失っても一覧に出る)"""
    videos = dict(read_studio(loc["studio"]))
    roots = {vid: v["case"] for vid, v in videos.items() if isinstance(v, dict) and isinstance(v.get("case"), str) and v["case"]}
    for root in _scan_roots(repo_root, env):
        try:
            cands, adopts = casefiles.read(root, cached=True)
        except errors.ApiError:
            continue
        for sid in adopts["sources"]:
            if sid in videos:
                continue
            v = casefiles.merge(cands, adopts, sid, root)
            if v is not None:
                v["case"] = root
                videos[sid], roots[sid] = v, root
    return videos, roots


def _fields_of(adopts):
    """採用.json の上の段 -> {status, memo, statusUpdatedAt, auto} のうち持っている物(空なら {})"""
    return {k: adopts[k] for k in FIELDS if adopts.get(k)}


def _saved_view(saved, roots):
    """cases.json の中身に、案件にした配信の分(採用.json の上の段)を重ねる。採用.json に何も無い案件は cases.json の行を使う(移す前の記録)"""
    out = dict(saved)
    for vid, root in roots.items():
        try:
            rec = _fields_of(casefiles.read(root, cached=True)[1])
        except errors.ApiError:
            continue
        if rec:
            out[vid] = rec
    return out


def _edit_case(loc, root, vid, change):
    """案件にした配信の状態・メモ・自動の確認を採用.json の上の段に書く(呼ぶ側が _lock を持つ)。change(rec) は rec(上の段の欄)を直して値を返す。
    採用.json に欄がまだ無く cases.json に行があれば、それを引き継いで書き、cases.json の行を消す(移す前の記録)。
    ロックは案件のだけ(スタジオの Store のロックは取らない)。採用.json の marks・sources には触らない。-> change の値。案件にこの配信が無ければ None"""
    old = None
    with casefiles.lock(root):
        _c, adopts = casefiles.read(root)
        if vid not in adopts["sources"]:
            return None
        rec = _fields_of(adopts)
        if not rec:
            old = load_saved(loc["cases"]).get(vid)
            if isinstance(old, dict):
                rec = {k: old[k] for k in FIELDS if old.get(k)}
        got = change(rec)
        for k in FIELDS:
            if rec.get(k):
                adopts[k] = rec[k]
            else:
                adopts.pop(k, None)
        adopts.setdefault("status", "")
        adopts.setdefault("memo", "")
        casebook.write(root, adoptions=adopts)
    if isinstance(old, dict):   # 採用.json に移したので cases.json の行は要らない
        saved = load_saved(loc["cases"])
        if saved.pop(vid, None) is not None:
            _write(loc["cases"], saved)
    return got


def _case_file(c):
    """案件の case.json の要点 {id, createdAt} か None(書き出した切り抜きのフォルダから引く。無い・壊れていれば None)"""
    for cl in c.get("clips") or ():
        if cl.get("exists") and cl.get("path"):
            got = placement.read_case(placement.case_root({"kind": "file", "path": cl["path"]}))
            return {"id": got["id"], "createdAt": got.get("createdAt") or 0} if got else None
    return None


def snapshot(repo_root, env=None):
    """画面用の一覧。最後に見えた紐づけ(状態・メモを付けた案件だけ)を案件ファイルに残す"""
    loc = locations(repo_root, env)
    with _lock:
        saved = load_saved(loc["cases"])
        videos, roots = _studio_view(repo_root, env, loc)
        fails = live_failures_by_mark(loc) if any(isinstance(v, dict) and v.get("kind") == "live" for v in videos.values()) else {}
        res = build(videos, read_transcripts(loc["transcripts"]), _saved_view(saved, roots), failures=fails)
        changed = False
        for c in res["cases"]:
            s = saved.get(c["id"])
            if s is not None and not c["gone"] and c["id"] not in roots:   # 案件にした配信は last を持たない(採用.json の側が正)
                last = {k: c[k] for k in ("kind", "title", "channel", "duration", "marks", "updatedAt", "streamedAt")}
                last["clips"] = [{k: x for k, x in cl.items() if k != "review"} for cl in c["clips"]]   # 人の確認・失敗の文は毎回重ね直す(残さない)
                if s.get("last") != last:
                    s["last"] = last
                    changed = True
        if changed:
            try:
                _write(loc["cases"], saved)
            except OSError:
                pass
    for c in res["cases"]:   # 案件のフォルダの case.json(読むだけ。無い案件は今までどおり。書くのは flow/placement.ensure_case だけ)
        c["caseFile"] = _case_file(c)
    res["casesFile"] = loc["cases"]
    return res


def _check_case_id(case_id):
    if not isinstance(case_id, str) or not (1 <= len(case_id) <= 64) or not all(ch.isalnum() or ch in "-_" for ch in case_id):
        raise ValueError("案件の指定が正しくありません")
    return case_id


def update(repo_root, case_id, status=None, memo=None, env=None):
    """状態・メモを付ける。-> 更新後の {status, memo, statusUpdatedAt}"""
    _check_case_id(case_id)
    if status is not None and status not in STATUSES:
        raise ValueError("状態が正しくありません")
    if memo is not None and (not isinstance(memo, str) or len(memo) > MAX_MEMO):
        raise ValueError("メモは %d 文字までです" % MAX_MEMO)
    loc = locations(repo_root, env)
    with _lock:
        root = _studio_view(repo_root, env, loc)[1].get(case_id)
        if root:
            def change(rec):
                if status is not None:
                    rec["status"] = status
                    rec["statusUpdatedAt"] = int(time.time() * 1000)
                if memo is not None:
                    rec["memo"] = memo
                return {"status": rec.get("status", ""), "memo": rec.get("memo", ""), "statusUpdatedAt": rec.get("statusUpdatedAt", 0)}
            try:
                got = _edit_case(loc, root, case_id, change)
            except errors.ApiError as e:   # 案件のフォルダが見えない・採用.json が壊れている(画面には 400 で文を出す)
                raise ValueError(e.message)
            if got is not None:
                return got
        saved = load_saved(loc["cases"])
        s = saved.setdefault(case_id, {})
        if status is not None:
            s["status"] = status
            s["statusUpdatedAt"] = int(time.time() * 1000)
        if memo is not None:
            s["memo"] = memo
        if not s.get("status") and not s.get("memo") and not _auto_records(s):
            saved.pop(case_id, None)   # 何も付けていない案件は持たない(ファイルを小さく。自動でできた切り抜きの確認があれば残す)
        _write(loc["cases"], saved)
        return {"status": s.get("status", ""), "memo": s.get("memo", ""), "statusUpdatedAt": s.get("statusUpdatedAt", 0)}


# ---------------------------------------------------------------- 自動でできた切り抜きの確認の操作(線 D の M9・M12)

class ReviewError(ValueError):
    """画面に出す理由(code は HTTP の番号・error は短い名前)"""

    def __init__(self, message, code=409, error="conflict"):
        super().__init__(message)
        self.code, self.error = code, error


def auto_review(repo_root, body, deliveries=None, studio=None, feedback=None, trash=None, hide=None, env=None):
    """POST /api/cases/auto {op, id(案件 = スタジオの配信), markId(スタジオのマーク)}-> (HTTP の番号, JSON)。
    op: seen = 見た / deliver = 採用 = 友人へ届ける(パックがあるときだけ)/ discard = 要らない。自動でできた切り抜き(clip["auto"])だけを受け付ける
    (人の切り抜きは、この口では届けない・動かさない)。部品は入口が渡す: deliveries = deliver.Deliveries・studio(method, path, body) -> (番号, JSON)
    (取り込んだスタジオの API = src/home/live.py の Live.studio_call)・feedback(行) = live_feedback.jsonl に 1 行・trash = cleanup.Cleanup
    (ごみ箱フォルダの場所)・hide(文書の id) = その文字起こしを一覧で非表示に(ホームの設定の hidden)"""
    body = body if isinstance(body, dict) else {}
    op = body.get("op")
    try:
        if op not in AUTO_OPS:
            raise ReviewError("op は seen・deliver・discard のどれかです", 400, "bad_request")
        case_id, mark_id = _check_case_id(body.get("id")), body.get("markId")
        if not isinstance(mark_id, str) or not MARK_RE.match(mark_id):
            raise ReviewError("切り抜きの指定(markId)が正しくありません", 400, "bad_request")
        c, cl = _find_auto(repo_root, case_id, mark_id, env)
        if op == "seen":
            return 200, {"ok": True, "review": _remember(repo_root, case_id, mark_id, env)}
        if op == "deliver":
            return 200, _deliver(repo_root, c, cl, deliveries, feedback, env)
        return 200, _discard(repo_root, c, cl, studio, feedback, trash, hide, deliveries, env)
    except ReviewError as e:
        return e.code, {"error": e.error, "message": str(e)}
    except errors.ApiError as e:   # 案件のフォルダが見えない・採用.json が壊れている
        return e.status, {"error": e.code, "message": e.message}
    except ValueError as e:
        return 400, {"error": "bad_request", "message": str(e)}
    except OSError as e:
        return 500, {"error": "write", "message": "案件ファイルを書けませんでした: %s" % tools.why(e)}


def _find_auto(repo_root, case_id, mark_id, env):
    """今の一覧(画面と同じ組み立て)から、案件と自動でできた切り抜きを引く"""
    res = snapshot(repo_root, env)
    c = next((x for x in res["cases"] if x["id"] == case_id), None)
    cl = next((x for x in (c or {}).get("clips") or [] if x.get("markId") == mark_id), None)
    if cl is None:
        raise ReviewError("その切り抜きは一覧にありません(もう片付けたかもしれません。一覧を読み込み直してください)", 404, "not_found")
    if not cl.get("auto"):
        raise ReviewError("自動でできた切り抜きではありません(人が書き出した切り抜きは「編集」の 3 パック から届けます)")
    return c, cl


def remember_delivered(repo_root, media_path, zip_name, env=None):
    """まとめて実行が自動で届けた(live.autoDeliver・友人のライブ配信の依頼)切り抜きに「届けた」を残す(src/home/autorun.py の _record_delivery から)。
    ライブの切り抜きでなければ何もしない。-> 残したか"""
    live, _m = clip_live(media_path)
    st = (live or {}).get("studio") if isinstance(live, dict) else None
    if not isinstance(st, dict) or not st.get("video") or not st.get("mark"):
        return False
    _remember(repo_root, str(st["video"]), str(st["mark"]), env, delivered=str(zip_name or ""))
    return True


EXPIRE_SEC = 3 * 86400   # 見ても届けてもいない自動の切り抜きを片付けるまで(切り抜きの動画を作ってから。10-09 ユーザー「3 日経ってもみなければ多分みない」)


def expire_unseen(repo_root, studio, feedback, trash, hide, deliveries, env=None, now=None, max_age=EXPIRE_SEC, is_request=None):
    """見ても届けてもいない自動の切り抜き(clip.review.unconfirmed)で、動画を作ってから max_age たったものを片付ける(10-09 ユーザー決定)。
    片付け方は「要らない」(_discard)と同じ = ごみ箱フォルダへ移す(cleanup の TRASH_DAYS でさらに消える)・スタジオのマークを不採用に・文字起こしを一覧で非表示に。
    違うのは live_feedback.jsonl の行が event expire・人の判定なし(eval_marks の「悪い」に数えない)と、案件の記録の expiredAt。
    片付けない: 見た・届けた・採用した切り抜き・人の切り抜き・友人の依頼の録画の切り抜き(.clip.json の live.deliver か、is_request(録画元, 録画) が真)・
    届けている途中のパック・ネットワーク上のパス。-> 片付けた [(案件, マーク)]"""
    if trash is None or studio is None:
        return []
    now = time.time() if now is None else now
    out = []
    for c in snapshot(repo_root, env)["cases"]:
        for cl in c.get("clips") or []:
            if _expire_one(repo_root, c, cl, studio, feedback, trash, hide, deliveries, env, now, max_age, is_request):
                out.append((c["id"], cl["markId"]))
    return out


def _expire_one(repo_root, c, cl, studio, feedback, trash, hide, deliveries, env, now, max_age, is_request):
    rv = cl.get("review") or {}
    path = cl.get("path") or ""
    if not cl.get("auto") or not rv.get("unconfirmed") or not path or fsio.is_network_path(path) or not os.path.isfile(path):
        return False
    age = now - os.path.getmtime(path)
    if age < max_age:
        return False
    live, _m = clip_live(path)
    if not live or live.get("deliver") or (is_request is not None and is_request(live.get("recorder"), live.get("recording"))):
        return False   # 友人の依頼・自動で届ける切り抜きは片付けない(届けるのは まとめて実行。届けば「届けた」になる)
    pack = txindex.pack_dir(path)
    if pack and deliveries is not None and deliveries.running(pack):
        return False
    key = (c["id"], cl["markId"])
    with _busy_lock:
        if key in _busy:
            return False
        _busy.add(key)
    try:
        row = _feedback_row(c, cl, event="expire", human=False, ageDays=round(age / 86400.0, 1))
        _moved, where, _st = discard_clip(trash, studio, c["id"], cl["markId"], path, pack)
        tid = (cl.get("transcript") or {}).get("id") or ""
        if tid and hide:
            try:
                hide(tid)
            except (OSError, ValueError):
                pass
        _remember(repo_root, c["id"], cl["markId"], env, discarded=tid, expired=True)
        if feedback:
            feedback(dict(row, trash=where))
        return True
    except (ReviewError, OSError):   # 動かせない・マークを不採用にできない(元に戻してある): 次の見回りでまた試す
        return False
    finally:
        with _busy_lock:
            _busy.discard(key)


def _remember(repo_root, case_id, mark_id, env=None, delivered=None, discarded=None, expired=False):
    """案件ファイルに確認を残す(見た = seenAt。届けた・要らないも「見た」に数える)。delivered: 置いた zip の名前・discarded: 文字起こしの id("" = 無い)。
    -> その記録 {seenAt, deliveredAt?, delivered?, discardedAt?, tx?}"""
    now = int(time.time() * 1000)
    loc = locations(repo_root, env)

    def remember(s):
        recs = _auto_records(s)
        r = dict(recs.get(mark_id)) if isinstance(recs.get(mark_id), dict) else {}
        if not _int_ms(r.get("seenAt")):
            r["seenAt"] = now
        if delivered is not None:
            r.update(deliveredAt=now, delivered=str(delivered)[:200])
        if discarded is not None:
            r.update(discardedAt=now, tx=str(discarded)[:64])
        if expired:   # 見ないまま日数がたって片付けた(人の「要らない」ではない。seenAt は付けない)
            r["expiredAt"] = now
            if not r.get("seenAt") or r["seenAt"] == now:
                r.pop("seenAt", None)
        recs[mark_id] = r
        if len(recs) > AUTO_KEEP:   # 古いもの(最後に触った時刻)から捨てる
            keep = sorted(recs, key=lambda k: -max(_int_ms(recs[k].get(x)) for x in ("seenAt", "deliveredAt", "discardedAt")))[:AUTO_KEEP]
            recs = {k: recs[k] for k in keep}
        s["auto"] = recs
        return r

    with _lock:
        root = _studio_view(repo_root, env, loc)[1].get(case_id)
        if root:
            try:
                got = _edit_case(loc, root, case_id, remember)
            except errors.ApiError as e:   # 案件のフォルダが見えない・採用.json が壊れている(呼び手は OSError を受ける)
                raise OSError(e.message)
            if got is not None:
                return got
        saved = load_saved(loc["cases"])
        r = remember(saved.setdefault(case_id, {}))
        _write(loc["cases"], saved)
        return r


def _feedback_row(c, cl, **kw):
    """live_feedback.jsonl の 1 行(src/home/live.py の採用の行と同じ形: 出どころ・人か・判定・録画元・録画・マークの正本の id・スタジオの配信とマーク・区間・ラベル)。
    .clip.json を読むので、ファイルを動かす前に作る"""
    live, _m = clip_live(cl.get("path"))
    live = live or {}
    return dict({"origin": (cl.get("auto") or {}).get("origin"), "recorder": live.get("recorder"), "recording": live.get("recording"),
                 "markId": live.get("markId"), "studio": {"video": c["id"], "mark": cl.get("markId")}, "start": cl.get("start"), "end": cl.get("end"),
                 "label": cl.get("label") or "", "file": cl.get("file") or ""}, **kw)


def _deliver(repo_root, c, cl, deliveries, feedback, env):
    """採用 = 友人へ届ける(M12)。パックを zip にして Dropbox の 出力 へ(deliver.Deliveries。数 GB は時間がかかるので裏で。画面は
    api/ytt/deliver の status で聞き直す)。置き終えたら案件に「届けた」を残し、live_feedback.jsonl に人の「良い」(event deliver)を 1 行"""
    rv = cl.get("review") or {}
    if rv.get("deliveredAt"):
        raise ReviewError("この切り抜きはもう届けました(%s)" % (rv.get("delivered") or "Dropbox の 出力"))
    pack = cl.get("pack") or {}
    if not pack.get("dir"):
        raise ReviewError("パックがまだありません(文字起こし → パックが済むと届けられます)")
    if deliveries is None:
        raise ReviewError("届ける仕組みが使えません", 503, "unavailable")
    row = _feedback_row(c, cl, event="deliver", human=True, verdict="good")
    case_id, mark_id = c["id"], cl["markId"]

    def done(job):
        _remember(repo_root, case_id, mark_id, env, delivered=job.get("name") or "")
        if feedback:
            feedback(dict(row, delivered=job.get("name") or ""))
    try:
        job = deliveries.start(pack["dir"], "", on_done=done)   # 題は空 = パックのフォルダの名前(友人のアプリの「受け取る」に出る)
    except ValueError as e:   # Dropbox のフォルダが決まっていない・見つからない・届けている途中 など(文はそのまま画面へ)
        raise ReviewError(str(e))
    _remember(repo_root, case_id, mark_id, env)
    return {"ok": True, "job": job}


def _discard(repo_root, c, cl, studio, feedback, trash, hide, deliveries, env):
    """要らない(M9): ① パック・切り抜きの mp4・.clip.json などの途中のファイルを ごみ箱フォルダ へ移す(片付け src/manage/keep/cleanup.py と同じ場所。
    片付けの TRASH_DAYS で起動時に消える。すぐには消さない)② スタジオのマークを不採用(rejected)に(画面と同じ PUT /api/video)③ live_feedback.jsonl に
    誤検出の記録(人の「悪い」= event reject)④ その文字起こしを一覧で非表示に(データは消さない)⑤ 案件に「要らない」を残す。
    ② ができなければ ① を元に戻す(パックだけ消えてマークが残る、を作らない)。-> {ok, moved, trash, studio}"""
    if trash is None or studio is None:
        raise ReviewError("ごみ箱フォルダか切り抜きスタジオが使えません", 503, "unavailable")
    key = (c["id"], cl["markId"])
    with _busy_lock:
        if key in _busy:
            raise ReviewError("この切り抜きは今、片付けている途中です")
        _busy.add(key)
    try:
        path = cl.get("path") or ""
        pack = txindex.pack_dir(path) if path else ""
        if pack and deliveries is not None and deliveries.running(pack):
            raise ReviewError("このパックは今、友人へ届けている途中です(終わってから押してください)")
        row = _feedback_row(c, cl, event="reject", human=True, verdict="bad")
        moved, where, st = discard_clip(trash, studio, c["id"], cl["markId"], path, pack)
        tid = (cl.get("transcript") or {}).get("id") or ""
        if tid and hide:
            try:
                hide(tid)
            except (OSError, ValueError):   # 非表示にできなくても片付けは済んでいる(一覧の「単体の文字起こし」には出さない)
                pass
        _remember(repo_root, c["id"], cl["markId"], env, discarded=tid)
        if feedback:
            feedback(dict(row, trash=where))
        return {"ok": True, "moved": len(moved), "trash": where, "studio": st}
    finally:
        with _busy_lock:
            _busy.discard(key)


def discard_clip(trash, studio, video_id, mark_id, media, pack=None):
    """切り抜き 1 本ぶん(動画・パック・途中のファイル)を ごみ箱フォルダ へ移し、スタジオのマークを不採用に(画面と同じ PUT /api/video)。
    マークを不採用にできなければ移したものを元に戻す(パックだけ消えてマークが残る、を作らない)。mark_id が空(スタジオのマークが無い
    = 友人の動画の依頼のパック)なら移すだけ。-> (移したもの [(元, 先)], ごみ箱の場所, スタジオの返事 "rejected"/"gone"/None)。
    M9 の「要らない」(_discard)はマークも不採用に。友人の「要らない」(src/human/friend/friend_feedback.py)は mark_id を空で呼んでマークを変えない
    (友人の採用の基準はこちらの送る基準と別。2026-10-08 ユーザー決定)"""
    pack = pack if pack is not None else (txindex.pack_dir(media) if media else "")
    moved, where = _to_trash(trash, media, pack)
    st = None
    if mark_id and video_id:
        try:
            st = _studio_reject(studio, video_id, mark_id)
        except ReviewError:
            _put_back(moved)
            raise
    _write_manifest(where, moved)
    return moved, where, st


def _to_trash(trash, media, pack):
    """切り抜き 1 本ぶんのファイルを ごみ箱/<日付>/discard/<名前>/ へ移す(作業用 の物は その中の 作業用/)。-> ([(元, 先)], 移した先のフォルダ)。
    1 つでも移せなければ、移した分を戻して ReviewError(Resolve・エクスプローラーで開いていると移せない)"""
    extra = [p for suf in cleanup.SIDECARS for p in schemas.sidecar_candidates(media, suf)] if media else []
    files = [p for p in [media, pack] + extra if p and os.path.exists(p)]
    if not files:
        return [], ""
    day = time.strftime("%Y-%m-%d")
    root = trash.trash_for(files[0])
    dest = cleanup.free_path(os.path.join(root, day, DISCARD_KIND, os.path.splitext(os.path.basename(media or pack))[0] or "clip"))
    moved = []
    try:
        for p in files:
            sub = schemas.WORK_DIR if os.path.basename(os.path.dirname(p)) == schemas.WORK_DIR else ""
            d = os.path.join(dest, sub) if sub else dest
            os.makedirs(d, exist_ok=True)
            to = cleanup.free_path(os.path.join(d, os.path.basename(p.rstrip("\\/"))))
            shutil.move(p, to)   # 同じドライブなら改名、別のドライブなら写して消す
            moved.append((p, to))
    except (OSError, shutil.Error) as e:
        _put_back(moved)
        raise ReviewError("ファイルを ごみ箱フォルダ へ移せなかったので、片付けませんでした(Resolve やエクスプローラーで開いていれば閉じて、もう一度): %s"
                          % (getattr(e, "strerror", None) or str(e)[:120]))
    try:   # 作業データ・書き出し先の外のごみ箱フォルダも、起動時に消す一覧へ(片付けの move と同じ)
        trash.remember_root(root)
    except OSError:
        pass
    return moved, dest


def _put_back(moved):
    """移した物を元の場所へ戻す(新しい順に。戻せなかった物はごみ箱フォルダに残る = 消えはしない)"""
    for src, to in reversed(moved):
        try:
            shutil.move(to, src)
        except (OSError, shutil.Error):
            pass


def _write_manifest(where, moved):
    """ごみ箱/<日付>/manifest.jsonl に元の場所を残す(where = ごみ箱/<日付>/discard/<名前>。書き方は片付けと同じ cleanup.append_manifest。戻したいときに見る)"""
    if not moved:
        return
    now = int(time.time() * 1000)
    try:
        cleanup.append_manifest(os.path.dirname(os.path.dirname(where)), [{"from": src, "to": to, "at": now, "kind": DISCARD_KIND} for src, to in moved])
    except OSError:   # 書けなくても、移した物は ごみ箱フォルダ の中にある
        pass


def _studio_ok(code, d):
    if code is None:
        raise ReviewError("切り抜きスタジオにつながらないので、片付けませんでした: %s" % ((d or {}).get("message") or ""), 502, "studio_down")
    if code != 200 or not isinstance(d, dict):
        raise ReviewError("切り抜きスタジオが断ったので、片付けませんでした: %s" % ((d or {}).get("message") or "HTTP %s" % code), 502, "studio_bad")
    return d


def _studio_reject(studio, vid, mark_id):
    """スタジオのマークを不採用(rejected)に(画面の保存と同じ PUT /api/video。baseRev つき・ぶつかったら読み直して 3 回まで)。
    -> "rejected" / "gone"(配信・マークがもう無い)。つながらない・断られたら ReviewError"""
    for _try in range(STUDIO_TRIES):
        code, d = studio("GET", "/api/video?id=" + urllib.parse.quote(vid))
        if code == 404:
            return "gone"
        v = _studio_ok(code, d).get("video") or {}
        marks = [m for m in v.get("marks") or [] if isinstance(m, dict)]
        hit = next((m for m in marks if m.get("id") == mark_id), None)
        if hit is None:
            return "gone"
        if hit.get("status") == "rejected":
            return "rejected"
        code, d = studio("PUT", "/api/video", {"id": vid, "marks": [dict(m, status="rejected") if m is hit else m for m in marks], "baseRev": v.get("rev")})
        if code == 409:   # 画面の保存・書き出しとぶつかった: 読み直してもう一度
            continue
        _studio_ok(code, d)
        return "rejected"
    raise ReviewError("切り抜きスタジオの配信が続けて書き換えられているので、マークを不採用にできませんでした(少し待ってもう一度)")
