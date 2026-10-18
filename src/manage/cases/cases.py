"""案件(配信1本)ごとの紐づけ(統合計画の段階4)。入口の「案件」画面(src/app/ui/home/portal.html)の中身を作る。

案件 = 切り抜きスタジオの動画1本(配信・ファイル)。その下に、書き出した切り抜きと、それぞれの文字起こし・パックを並べる。
紐づけは、各ツールが持っているデータを**読むたびに組み立て直す**(各ツールの記録と食い違わないように。2026-09-26 ユーザーと決定):
  - 切り抜き … スタジオの data.json の「書き出し済み」のマーク(書き出した mp4 の絶対パスを持つ)
  - 文字起こし … 文字起こしツールの transcripts/*.json(元の動画のパスが切り抜きと同じ。無ければ .clip.json の配信・マークが同じ。
                規則は src/manage/cases/txindex.py にあり、スタジオのセリフの表示と共通)
  - パック … 切り抜きの隣の <名前>_pack フォルダ(cut2resolve の既定の出力先)
案件ファイル(<作業データ>\\app\\cases.json)に持つのは、自動でできた切り抜きの記録(auto)だけ。各ツールのデータは読むだけで、書き換えない。
**RS8 B3-6**: 案件にした配信(data.json の行が case を持つ・または書き出し先の直下に 作業用/採用.json がある)の auto は、cases.json でなく
案件の 採用.json の上の段に持つ(書くのは flow/casebook.write・ロックは ytt/casefiles.lock。marks・sources は触らない)。
一覧は索引(data.json)∪ 書き出し先の走査。cases.json は案件の無い配信の分だけ(採用.json に auto がまだ無い案件は cases.json の auto を引き継いで書く)。
**MARKS-3**(決定 3-48 の「切り抜きの印を 3 本に」): 案件の状態・メモ・「見た」「未確認」「保留」は消した。採用.json・cases.json に残る古い欄
(status・memo・statusUpdatedAt・last・seenAt・deliveredAt・delivered)は読み飛ばすだけで書き換えない。スタジオから消えた配信の行は一覧に出さない(データは消さない)。

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

自動でできた切り抜きの確認(線 D の M9・M12・M13。計画 notes:plan/line-d-auto-pack.md の段階 4・6):
  - 配信(kind live)の切り抜きのうち、.clip.json の source.live.origin が auto(配信中の候補 = M11)か archive(配信後の解析 = M7)のものに
    clip["auto"] = {origin, originLabel, score, bench} を付ける(人の切り抜き manual は None = 今までどおり)。点数は .clip.json の source.live.score →
    mark.score → スタジオのマークの score の順(今は書き手が無いことが多い。無ければ None = 画面に出さない)。
    bench = 1 時間の枠から外れた候補(「控え」。M13: 書き出し済みなら取り消さない。ワーカーが付けたら出すだけ)
  - clip["review"] = {deliveredAt, delivered, failure, notSent?}: 届けたか(② flow/deliveries.delivered_marks = 届けた記録から毎回引く。案件には写さない。
    マークの空の古い行はパックのフォルダの名前で引く)・失敗の文(M3。src/flow/live_failures.failure_of だけが作る。<作業データ>/app/live/exports.json の
    書き出しのジョブをスタジオのマークで引く。読むだけ)。案件の autoClips {total}・一覧全体の auto も同じ数
  - 操作は auto_review(POST /api/cases/auto): deliver = 採用 = パックを zip にして Dropbox の 出力 へ(src/flow/deliver.py)/ discard = 要らない =
    パック・切り抜きの mp4・.clip.json などを ごみ箱フォルダ へ移す(片付けと同じ場所。片付けの TRASH_DAYS で起動時に消える)+ スタジオのマークを不採用に +
    その文字起こしを一覧で非表示に(データは消さない)。どちらも人の判断を ③ human/judgments に 1 行(who self・adopt / reject・via cases)
  - 案件ファイルには cases[配信]["auto"][スタジオのマーク] = {discardedAt, tx, expiredAt} を持つ(要らないにした文字起こし tx は
    「単体の文字起こし」に出さない。前の版 0.84〜0.86 が書いた origin・notSent は 10-19 に読むのをやめた = 本物の記録に 0 本)
  - まとめて実行で友人へ自動で送る形(D-SEND。notes:plan/done/d-send-requirements.md の 2-8): 送らなかったら届ける段が ② の送らなかった記録 logs/not-sent.jsonl に
    {配信, マーク, code, text, at}(理由の鍵と文は ② flow/sendpolicy.REASONS)を書く(flow/deliveries.record_not_sent。ds1 = 3-71 m3e)。送った物は届けた記録の mode full・origin auto で見分ける。
    どちらかがある切り抜きはライブでなくても clip["auto"] = {origin "full", originLabel "まとめて実行"}(品質のカードに出る)。
    clip["review"]["notSent"] は届けていない間だけ(案件の画面の札)
  - 日数の片付け(expire_unseen。10-16 ユーザー): 届けた自動の切り抜きは届けてから・届けていない物は作ってから EXPIRE_SEC でごみ箱へ。
    友人の依頼・届ける印・届けている途中は待つ。まとめて実行の自動の採用も同じ規則
"""
import datetime
import os
import re
import threading
import time
import urllib.parse

from . import txindex   # 同じ manage/cases の兄弟
from ytt import casefiles, datadir, errors, fsio, schemas, studiodata, tools
from manage.keep import trash as _trash   # ごみ箱へ移す・戻す・戻せなかった物の記録の 1 か所(OPT-M2)
from manage.keep import cleanup  # noqa: E402  (ごみ箱フォルダの場所・名前の付け方・manifest・一緒に片付ける途中のファイルの決まりは片付けと同じ)
from flow import casebook, live_failures   # 失敗の文は 1 か所。線 D の M3 / 案件の採用.json を書く口(RS8 B3-6)
from flow import deliveries as _deliveries   # 届けた記録の読み口(持ち主は ②。OPT-M2)
from flow import placement   # 置き場所の持ち主(スタジオの data.json。RS6 b-B0)
from human import judgments as _judgments   # 人の判断の記録(持ち主は ③。MARKS-3。④ は ③ を読める)

SCHEMA = "youtube-tools-cases/v1"
MAX_JSON = 64 * 1024 * 1024
_lock = threading.Lock()
# 次にやることの順(仕掛かりを先に終わらせる)と、作業の名前。ホームの「次にやること」(portal.js)も build() の todoOrder でこの順を使う(正はここ 1 か所)
TODO_ORDER = ("proof", "pack", "transcribe", "export", "review")
TODO_LABEL = {"proof": "校正", "pack": "パックを作る", "transcribe": "文字起こし", "export": "書き出し", "review": "候補の確認"}
# 自動でできた切り抜き(線 D の M9)。.clip.json の source.live.origin(src/flow/live_export.py の ORIGINS の auto・archive)→ 画面に出す出どころ
AUTO_ORIGINS = {"auto": "配信中の候補", "archive": "配信後の解析"}
# まとめて実行(mode full)で自動で採用して友人へ自動で送る形の切り抜き(D-SEND)。.clip.json はライブでないので、② の送らなかった記録・届けた記録(と前の版の案件の auto[マーク].origin "full")で見分ける
FULL_ORIGIN, FULL_LABEL = "full", "まとめて実行"
AUTO_OPS = ("deliver", "discard")   # 「見た」(seen)は MARKS-3 で消した(古い画面から来たら 400)
AUTO_KEEP = 2000                   # 案件 1 件で覚えておく確認の数(古いものから捨てる)
DISCARD_KIND = "discard"           # ごみ箱/<日付>/ の下の種類の名前(片付けの export・work などと並ぶ)
MARK_RE = re.compile(r"^[\w-]{1,40}\Z", re.ASCII)   # スタジオのマークの id(src/human/review/store.py の ID_RE と同じ形)
STUDIO_TRIES = 3                   # スタジオの保存とぶつかったときに読み直す回数(src/app/live.py の採用と同じ)
_busy, _busy_lock = set(), threading.Lock()   # 「要らない」の途中の (配信, マーク)(二度押し・窓を 2 つ並べたときに同じものを二重に動かさない)
_readers = {}                      # まとめて実行の記録のパス → live_failures.Reader(変わったときだけ読み直す)


def _read_json(path, limit=MAX_JSON):
    try:
        return fsio.read_json_file(path, limit)
    except (OSError, UnicodeError, ValueError):
        return None


def locations(repo_root, env=None):
    """{"studio": data.json, "transcripts": フォルダ, "cases": cases.json, "liveJobs": 線 D の書き出しのジョブ, "runs": まとめて実行の記録,
    "app": 入口の作業データ(人の判断の記録 judgments.jsonl の置き場所), "logs": 入口の記録(届けた記録 deliveries.jsonl の置き場所)}。
    置き場所の規則は ytt.datadir.resolve の1か所
    (起動したツールが登録した場所 → STUDIO_HOME などの環境変数 → YTT_DATA_DIR・既定の場所。env を渡したときは登録を見ない)。
    スタジオの data.json は置き場所の持ち主 flow/placement の studio_data(RS6 b-B0。値は同じ)"""
    app = datadir.resolve("app", repo_root, env)
    return {"studio": placement.studio_data(repo_root, env), "transcripts": txindex.folder(repo_root, env),
            "cases": os.path.join(app, "cases.json"), "liveJobs": os.path.join(app, "live", "exports.json"),
            "runs": os.path.join(app, "logs", "autorun-runs.jsonl"), "app": app, "logs": os.path.join(app, "logs")}


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
            # ホームの「やること」(種類ごとの件数。C0)。adopt = 候補の確認・proof = 校正待ち・pack = パックを作れる(校正済みでパックがまだ)・failed = 失敗のある切り抜き
            "todoSum": {"adopt": review, "proof": proofing, "pack": ready_pack,
                        "failed": sum(1 for cl in clips if (cl.get("review") or {}).get("failure"))},
            "remaining": (1 if review else 0) + to_export + missing_tx + proofing + missing_pack,
            "autoClips": {"total": len(autos)},
            "streamedAt": c.get("streamedAt") or c.get("updatedAt") or 0}


def clip_state(tx, pack):
    """切り抜き 1 本の進み具合(案件の画面の左の一覧の札。C0)-> {"state", "ratio"}。
    state: none(文字起こしがまだ)/ proofing(校正中 = 校正済みの行が足りない)/ proofed(校正済み)/ packed(パック済み)。ratio = 校正済みの行の割合(0〜1)。
    文字起こしがあっても行が 0 本なら none。パックがあれば校正の途中でも packed"""
    segs = (tx or {}).get("segments", 0)
    done = (tx or {}).get("proofed", 0)
    ratio = round(min(1.0, done / segs), 3) if segs > 0 else 0.0
    if pack:
        return {"state": "packed", "ratio": ratio}
    if not tx or segs <= 0:
        return {"state": "none", "ratio": 0.0}
    return {"state": "proofed" if done >= segs else "proofing", "ratio": ratio}


def _apply_state(cases):
    """全部の切り抜きに state・ratio を足す(スタジオから消えた配信の最後に見えた内容にも)"""
    for c in cases:
        for cl in c.get("clips") or []:
            cl.update(clip_state(cl.get("transcript"), cl.get("pack")))


# ---------------------------------------------------------------- 自動でできた切り抜き(線 D の M9)

def clip_live(media_path):
    """切り抜きの .clip.json の (source.live, mark)(線 D の書き出し = src/flow/live_export.py の _finish が書く。source.kind は live)。
    無い・読めない・ライブでない・ネットワーク上のパスなら (None, None)。まとめて実行の M8(src/app/autorun.py の live_auto_origin)も同じ読み方"""
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
    return {"origin": origin, "originLabel": AUTO_ORIGINS[origin], "score": None if score is None else round(score, 2), "bench": live.get("bench") is True,
            "deliver": bool(live.get("deliver"))}   # 届ける印つき(友人の依頼・live.autoDeliver)= まとめて実行が届ける物。日数の片付けは届けるまで待つ(opt-manage 2a-2)


def _full_info(mark):
    """まとめて実行の自動で送る形の切り抜き(② の送らなかった記録にあるか、届けた記録の mode full・origin auto)の clip["auto"]。
    日数の片付けはライブの自動の切り抜きと同じ規則(expire_unseen)"""
    score = schemas.num(mark.get("score"))
    return {"origin": FULL_ORIGIN, "originLabel": FULL_LABEL, "score": None if score is None else round(score, 2), "bench": False, "deliver": False}


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


def delivered_of(delivered, video_id, mark_id, path):
    """切り抜き 1 本の届けた(② flow/deliveries.delivered_marks の結果 delivered から)-> {"at", "zip", "origin", "mode"} か None。
    配信とマークで引き、無ければ切り抜きの隣のパックのフォルダの名前で引く(マークの空の古い行・配信の空の行。配信・マークが分かる行は同じ物だけ)"""
    if not delivered:
        return None
    by_mark, by_pack = delivered
    hit = by_mark.get((video_id, mark_id)) if mark_id else None
    if hit is None and path:
        p = by_pack.get(_deliveries.pack_name(txindex.pack_dir(path)))
        if p and p.get("videoId") in ("", video_id) and p.get("markId") in ("", mark_id):
            hit = p
    return hit


def _sent_full(dm):
    """届けた記録がまとめて実行の自動で送った物か(mode full・origin auto。D-SEND の届ける段)"""
    return bool(dm) and dm.get("mode") == "full" and dm.get("origin") == "auto"


def _apply_review(cases, saved, failures, delivered, not_sent=None):
    """自動でできた切り抜きに、届けた(② の届けた記録)と失敗の文と送らなかった理由(② の送らなかった記録 not_sent)を
    重ねる(clip["review"])。
    日数で片付けた(expiredAt)切り抜きで動画がもう無い物は一覧から外す(片付けはスタジオのマークを変えない = 10-14。マークは書き出し済みのまま残る)"""
    for c in cases:
        rec = _auto_records(saved.get(c["id"]))
        gone = [cl for cl in c.get("clips") or [] if not cl.get("exists")   # .clip.json もごみ箱へ移ったので auto は付かない(記録で見分ける)
                and isinstance(rec.get(cl.get("markId")), dict) and _int_ms(rec[cl.get("markId")].get("expiredAt"))]
        if gone:
            c["clips"] = [cl for cl in c["clips"] if cl not in gone]
            if isinstance(c.get("marks"), dict):
                c["marks"]["exported"] = len(c["clips"])
        for cl in c.get("clips") or []:
            if not cl.get("auto"):
                continue
            dm = delivered_of(delivered, c["id"], cl.get("markId"), cl.get("path"))
            done = _int_ms((dm or {}).get("at")) or (1 if dm else 0)   # 時刻の無い古い行も「届けた」(ずっと前)
            cl["review"] = {"deliveredAt": done, "delivered": (dm or {}).get("zip") or "", "failure": failures.get((c["id"], cl.get("markId")))}
            ns = (not_sent or {}).get((c["id"], cl.get("markId")))   # ② の記録(ds1)
            if not done and isinstance(ns, dict) and isinstance(ns.get("code"), str):   # 送らなかった理由(D-SEND。届けたあとは出さない)
                cl["review"]["notSent"] = {"code": ns["code"][:40], "text": str(ns.get("text") or "")[:200], "at": _int_ms(ns.get("at"))}


# ---------------------------------------------------------------- 組み立て

def _file_case(path):
    """文書の元の動画のパス -> (案件の根, case.json の id)。動画ファイルの案件(case.json の media.kind が file)でなければ ("", "")。読むだけ"""
    try:
        if not isinstance(path, str) or not path or not os.path.isabs(path) or fsio.is_network_path(path):
            return "", ""
        root = placement.case_root({"kind": "file", "path": path})
        got = placement.read_case(root) if root else None
        if got and (got.get("media") or {}).get("kind") == "file":
            _check_case_id(got["id"])
            return root, got["id"]
    except (OSError, ValueError):
        pass
    return "", ""


def virtual_cases(docs, taken, pack_finder=find_pack, case_finder=_file_case):
    """配信の案件に紐づかなかった文書 docs(txindex の文書)-> 案件の行の一覧(C0。brief 3-3・3-4)。
    動画ファイルの案件 = 元の動画のフォルダの case.json が file の物(id は case.json の id。取った id taken とぶつかれば orphan)/ eval = 評価用の文書(evalSet)/
    orphan = どれにも当たらない文書。eval・orphan は文書が無くても必ず 1 行ずつ(最後に)。行の形は配信の案件と同じ(clips は文書 1 本 = 1 行)"""
    groups, order = {}, []
    ev, orphan = [], []
    folders = {}
    for d in sorted(docs, key=lambda d: -d["updatedAt"]):
        if d.get("evalSet"):
            ev.append(d)
            continue
        src = d.get("sourcePath") or ""
        fold = os.path.dirname(os.path.abspath(src)) if src else ""
        if fold not in folders:
            folders[fold] = case_finder(src)
        root, cid = folders[fold]
        if cid and cid not in taken and cid not in ("eval", "orphan"):
            if cid not in groups:
                groups[cid] = (root, [])
                order.append(cid)
            groups[cid][1].append(d)
        else:
            orphan.append(d)
    rows = [_virtual_row(cid, "file", groups[cid][1], groups[cid][0], pack_finder) for cid in order]
    rows.append(_virtual_row("eval", "eval", ev, "", pack_finder))
    rows.append(_virtual_row("orphan", "orphan", orphan, "", pack_finder))
    return rows


def _virtual_row(cid, kind, docs, root, pack_finder):
    clips = []
    for d in docs:
        path = d.get("sourcePath") or ""
        clips.append({"markId": "", "label": d["title"][:80], "start": None, "end": None, "file": os.path.basename(path), "path": path,
                      "exists": bool(path) and os.path.isfile(path), "transcript": txindex.summary(d), "transcripts": 1, "transcriptIds": [d["id"]],
                      "pack": pack_finder(path) if path else None, "auto": None})
    titles = {"eval": "評価用", "orphan": "どの案件にも入らない文字起こし"}
    title = titles.get(cid) or (docs[0]["title"] if docs else cid)
    row = {"id": cid, "kind": "", "caseKind": kind, "root": root, "title": str(title)[:120], "channel": "", "duration": 0,
           "marks": {"total": 0, "adopted": 0, "exported": len(clips), "candidates": 0}, "clips": clips,
           "updatedAt": max([d["updatedAt"] for d in docs] or [0]), "gone": False, "caseFile": None}
    row["streamedAt"] = row["updatedAt"]
    _apply_state([row])
    row.update(_case_extras(row))
    return row


def _todo_totals(cases):
    """案件の todoSum の合計 {adopt, proof, pack, failed}(ホームの「やること」。画面で数えない)"""
    return {k: sum(c.get("todoSum", {}).get(k, 0) for c in cases if not c.get("gone")) for k in ("adopt", "proof", "pack", "failed")}


def _clip_doc(cl):
    t = cl.get("transcript")
    return t["id"] if t else ""


def _todo_first(cases):
    """種類ごとに、いちばん古い(配信日の早い)案件と、その中の最初の切り抜きの文書 -> {種類: {"case", "doc"}}(残りが無い種類は入れない)。
    ホームの「やること」を押したときの行き先"""
    out = {}
    for k in ("adopt", "proof", "pack", "failed"):
        hit = [c for c in cases if not c.get("gone") and c.get("todoSum", {}).get(k, 0) > 0]
        if not hit:
            continue
        c = min(hit, key=lambda c: (c.get("streamedAt") or 0, c["id"]))
        pick = {"proof": lambda cl: cl.get("state") == "proofing",
                "pack": lambda cl: cl.get("state") == "proofed",
                "failed": lambda cl: bool((cl.get("review") or {}).get("failure"))}.get(k)
        doc = next((_clip_doc(cl) for cl in c["clips"] if pick and pick(cl) and _clip_doc(cl)), "")
        out[k] = {"case": c["id"], "doc": doc}
    return out


def build(videos, transcripts, saved=None, pack_finder=find_pack, failures=None, case_finder=_file_case, delivered=None, not_sent=None):
    """-> {"cases": [...], "unlinked": [文字起こし], "todoOrder", "auto": {total}}。saved: cases.json の中身(自動でできた切り抜きの記録 auto)。
    failures: live_failures_by_mark の結果(線 D の書き出し・文字起こし・パックの失敗の文)。delivered: ② flow/deliveries.delivered_marks の結果(None = 届けたは無し)。
    not_sent: ② flow/deliveries.not_sent_marks の結果(送らなかった切り抜き。ds1。None = 無し)"""
    saved = saved or {}
    not_sent = not_sent or {}
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
            auto = auto_info(m, path) if v.get("kind") == "live" else None   # 自動でできた切り抜き(線 D の M9。ライブの録画だけ)
            mid = str(m.get("id") or "")
            if auto is None and ((vid, mid) in not_sent or _sent_full(delivered_of(delivered, vid, mid, path))):   # 送らなかった(② の記録)・送った
                auto = _full_info(m)   # まとめて実行の自動で送る形(D-SEND。送った物も送らなかった物も = 品質のカードに出る)
            clips.append({"markId": str(m.get("id") or ""), "label": str(m.get("label") or "")[:80], "start": m.get("start"), "end": m.get("end"),
                          "file": str(m.get("file") or ""), "path": path, "exists": bool(path) and os.path.isfile(path),
                          "transcript": txindex.summary(tx) if tx else None, "transcripts": n, "transcriptIds": ids, "pack": pack_finder(path) if path else None,
                          "auto": auto})
        cases.append({"id": vid, "kind": v.get("kind") or "", "caseKind": "file" if v.get("kind") == "file" else "stream", "root": "", "title": str(v.get("title") or v.get("fileName") or vid)[:120],
                      "channel": str(v.get("channel") or "")[:100], "duration": v.get("duration") or 0,
                      "marks": {"total": len(marks), "adopted": sum(1 for m in marks if m.get("status") == "adopted"),
                                "exported": len(clips), "candidates": sum(1 for m in marks if not m.get("status"))},
                      "clips": clips, "updatedAt": v.get("updatedAt") or 0, "streamedAt": _stream_time(v), "gone": False})
    # スタジオから消えた配信の行は出さない(MARKS-3。cases.json に残る最後に見えた紐づけ last は読み飛ばす = データは消さない)
    _apply_review(cases, saved, failures or {}, delivered, not_sent)
    _apply_state(cases)
    for c in cases:
        c.update(_case_extras(c))
    cases.sort(key=lambda c: -(c.get("updatedAt") or 0))
    # 「要らない」にした自動の切り抜きの文字起こしは、マークが不採用になって紐づかなくなっても「単体の文字起こし」に出さない
    dropped = {r.get("tx") for s in saved.values() for r in _auto_records(s).values() if isinstance(r, dict) and r.get("discardedAt") and r.get("tx")}
    unlinked = [dict(txindex.summary(t), sourcePath=t["sourcePath"]) for t in transcripts if t["id"] not in used and t["id"] not in dropped]
    unlinked.sort(key=lambda t: -t["updatedAt"])
    virtual = virtual_cases([t for t in transcripts if t["id"] not in used and t["id"] not in dropped], {c["id"] for c in cases}, pack_finder, case_finder)
    real = cases + [c for c in virtual if c["caseKind"] == "file"]
    return {"cases": cases, "unlinked": unlinked, "todoOrder": list(TODO_ORDER),
            "auto": {"total": sum(c["autoClips"]["total"] for c in cases)},
            # 案件の画面(C0): 配信の案件に紐づかなかった文書の入れ物 = 動画ファイルの案件(case.json のある物)・eval・orphan。cases には混ぜない(今の画面の数を変えない)
            "virtual": virtual, "todo": _todo_totals(real), "todoFirst": _todo_first(real)}


# ---------------------------------------------------------------- 案件ファイル

def load_saved(path):
    d = _read_json(path, 16 * 1024 * 1024)
    if not isinstance(d, dict) or d.get("schema") != SCHEMA or not isinstance(d.get("cases"), dict):
        return {}
    return d["cases"]


def _write(path, saved):
    os.makedirs(os.path.dirname(path), exist_ok=True)
    fsio.write_json(path, {"schema": SCHEMA, "cases": saved})


# ---------------------------------------------------------------- 案件の根(RS8 B3-6。自動でできた切り抜きの記録は案件の 採用.json の上の段へ)
FIELDS = ("auto",)   # cases.json の 1 件から 採用.json の上の段に移った欄のうち、今も読み書きする物(状態・メモは MARKS-3 で消した = 読み飛ばす)


def _scan_roots(repo_root, env=None):
    """書き出し先(outDir)の直下で 作業用/採用.json を持つフォルダ = 案件の根の一覧(読むだけ・固定ディスクの外・ネットワーク上は見ない)"""
    try:
        out = datadir.studio_out_dir(repo_root, env)
        if not os.path.isabs(out) or casefiles.is_remote(out) or not fsio.is_fixed_drive(out) or not os.path.isdir(out):
            return []
        # 根の置き場所(outDir 直下・友人の依頼 <outDir>/依頼/<日付>_<題>_<id6>)は ② placement.case_roots の 1 か所
        return [d for d in placement.case_roots(out) if os.path.isfile(casefiles.work_path(d, casefiles.ADOPTIONS_NAME))]
    except OSError:
        return []


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
    """採用.json の上の段 -> {auto} を持っていれば(空なら {})"""
    return {k: adopts[k] for k in FIELDS if adopts.get(k)}


def _saved_view(saved, roots):
    """cases.json の中身に、案件にした配信の分(採用.json の上の段)を重ねる。採用.json に auto が無い案件は cases.json の行を使う(移す前の記録)"""
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
    """案件にした配信の自動でできた切り抜きの記録を採用.json の上の段に書く(呼ぶ側が _lock を持つ)。change(rec) は rec(上の段の欄)を直して値を返す。
    採用.json に auto がまだ無く cases.json の行に auto があれば、それを引き継いで書く(cases.json は書き換えない = 以後は採用.json が勝つ)。
    上の段の古い欄(状態・メモ)は読んだまま書き戻す(書き換えない)。ロックは案件のだけ(スタジオの Store のロックは取らない)。
    採用.json の marks・sources には触らない。-> change の値。案件にこの配信が無ければ None"""
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
        casebook.write(root, adoptions=adopts)
    return got


def _case_file(c):
    """案件の case.json の要点 {id, createdAt} か None(書き出した切り抜きのフォルダから引く。無い・壊れていれば None)"""
    for cl in c.get("clips") or ():
        if cl.get("exists") and cl.get("path"):
            got = placement.read_case(placement.case_root({"kind": "file", "path": cl["path"]}))
            return {"id": got["id"], "createdAt": got.get("createdAt") or 0} if got else None
    return None


def snapshot(repo_root, env=None):
    """画面用の一覧(読むだけ。案件ファイルは書かない)"""
    loc = locations(repo_root, env)
    with _lock:
        saved = load_saved(loc["cases"])
        videos, roots = _studio_view(repo_root, env, loc)
        fails = live_failures_by_mark(loc) if any(isinstance(v, dict) and v.get("kind") == "live" for v in videos.values()) else {}
        res = build(videos, read_transcripts(loc["transcripts"]), _saved_view(saved, roots), failures=fails,
                    delivered=_deliveries.delivered_marks(loc["logs"]), not_sent=_deliveries.not_sent_marks(loc["logs"]))
    for c in res["cases"]:   # 案件のフォルダの case.json(読むだけ。無い案件は今までどおり。書くのは flow/placement.ensure_case だけ)
        c["caseFile"] = _case_file(c)
        c["root"] = roots.get(c["id"], "")   # ② の status?case= の鍵(案件にした配信だけ。無ければ "")。URL には出さない
    res["casesFile"] = loc["cases"]
    return res


def find_doc(repo_root, tid, env=None):
    """文書 tid を持つ案件の 1 件 -> {"case": 案件の行, "docId", "markId"} か None(GET /api/cases?doc=<tid>。案件の画面が d だけの URL から案件を聞く)。
    配信の案件を先に、無ければ動画ファイルの案件・eval・orphan の順"""
    if not isinstance(tid, str) or not schemas.TID_RE.match(tid):
        raise ValueError("文書の指定が正しくありません")
    res = snapshot(repo_root, env)
    for c in res["cases"] + res["virtual"]:
        for cl in c["clips"]:
            if tid in (cl.get("transcriptIds") or ()) or (cl.get("transcript") or {}).get("id") == tid:
                return {"case": c, "docId": tid, "markId": cl.get("markId") or ""}
    return None


def _check_case_id(case_id):
    if not isinstance(case_id, str) or not (1 <= len(case_id) <= 64) or not all(ch.isalnum() or ch in "-_" for ch in case_id):
        raise ValueError("案件の指定が正しくありません")
    return case_id


# ---------------------------------------------------------------- 自動でできた切り抜きの確認の操作(線 D の M9・M12)

class ReviewError(ValueError):
    """画面に出す理由(code は HTTP の番号・error は短い名前)"""

    def __init__(self, message, code=409, error="conflict"):
        super().__init__(message)
        self.code, self.error = code, error


def auto_review(repo_root, body, deliveries=None, studio=None, trash=None, hide=None, env=None):
    """POST /api/cases/auto {op, id(案件 = スタジオの配信), markId(スタジオのマーク)}-> (HTTP の番号, JSON)。
    op: deliver = 採用 = 友人へ届ける(パックがあるときだけ)/ discard = 要らない。自動でできた切り抜き(clip["auto"])だけを受け付ける
    (人の切り抜きは、この口では届けない・動かさない)。古い画面の seen(見た)は 400(MARKS-3 で消した)。部品は入口が渡す: deliveries = deliver.Deliveries・
    studio(method, path, body) -> (番号, JSON)(取り込んだスタジオの API = src/app/live.py の Live.studio_call)・trash = cleanup.Cleanup
    (ごみ箱フォルダの場所)・hide(文書の id) = その文字起こしを一覧で非表示に(ホームの設定の hidden)"""
    body = body if isinstance(body, dict) else {}
    op = body.get("op")
    try:
        if op not in AUTO_OPS:
            raise ReviewError("op は deliver・discard のどれかです", 400, "bad_request")
        case_id, mark_id = _check_case_id(body.get("id")), body.get("markId")
        if not isinstance(mark_id, str) or not MARK_RE.match(mark_id):
            raise ReviewError("切り抜きの指定(markId)が正しくありません", 400, "bad_request")
        c, cl = _find_auto(repo_root, case_id, mark_id, env)
        if op == "deliver":
            return 200, _deliver(repo_root, c, cl, deliveries, env)
        return 200, _discard(repo_root, c, cl, studio, trash, hide, deliveries, env)
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


EXPIRE_SEC = 3 * 86400   # 自動の切り抜きを片付けるまで(届けていない物は動画を作ってから・届けた物は届けてから。10-09・10-14・10-16 ユーザー)
# 届けた自動の切り抜きも、届けてから EXPIRE_SEC で自動でごみ箱へ(10-14 ユーザー「どんどん消していい」= decisions 3-48 Q2)。
# スイッチ(既定オン = 10-15 ユーザー「既定でオンにして」。止めるならこの 1 か所を False に)
TRASH_DELIVERED = True


def expire_unseen(repo_root, studio, trash, hide, deliveries, env=None, now=None, max_age=EXPIRE_SEC, is_request=None):
    """自動の切り抜き(ライブの自動の採用とまとめて実行の自動の採用)を日数で片付ける(10-16 ユーザー。「見た」の守りは無し):
    届けていない物は動画を作ってから max_age(この版より前の物は数え始めの時刻 expire_since から)・届けた物は届けてから max_age(TRASH_DELIVERED がオンのとき = 既定)。
    片付け方 = ごみ箱フォルダへ移す(cleanup の TRASH_DAYS でさらに消える)・文字起こしを一覧で非表示に(データは消さない)・案件の記録に expiredAt。
    **スタジオのマークは不採用にしない・人の判断の記録に書かない**(片付けは評価と無関係 = 人が確認していない物を評価・学習に入れない。10-14 ユーザー)。
    片付けない: 人の切り抜き・届ける途中の物(.clip.json の live.deliver か、is_request(録画元, 録画) が真で、まだ届けていない)・
    届けている途中のパック・ネットワーク上のパス。届けた記録を読めないときは何もしない(届けたかが分からない)。-> 片付けた [(案件, マーク)]"""
    loc = locations(repo_root, env)
    if trash is None or studio is None or _deliveries.delivered_marks(loc["logs"]) is None:
        return []
    now = time.time() if now is None else now
    since = expire_since(loc["app"], now)
    if since is None:
        return []   # 数え始めの時刻を読めない・書けない: 片付けない(安全側)
    out = []
    for c in snapshot(repo_root, env)["cases"]:
        for cl in c.get("clips") or []:
            if _expire_one(repo_root, c, cl, studio, trash, hide, deliveries, env, now, max_age, is_request, since):
                out.append((c["id"], cl["markId"]))
    return out


EXPIRE_SINCE_FILE = "expire-since.json"   # 日数の片付けを数え始めた時刻(入口の作業データ app の中。10-16 ユーザー)


def expire_since(app_dir, now):
    """日数の片付けを数え始めた時刻(秒)。初めて見回ったときに now を {"v": 1, "at": ミリ秒} で 1 回だけ書き、以後は読む
    (この版より前にできた切り抜きを、入れた直後の見回りでまとめて片付けない = 届けていない物の起点は max(作った時刻, この時刻))。
    壊れている・読めない・書けないなら None(呼び手は片付けない)"""
    p = os.path.join(app_dir, EXPIRE_SINCE_FILE)
    if not os.path.exists(p):
        try:
            os.makedirs(app_dir, exist_ok=True)
            fsio.write_json(p, {"v": 1, "at": int(now * 1000)})
        except OSError:
            return None
    d = _read_json(p, 4096)
    at = _int_ms(d.get("at")) if isinstance(d, dict) and d.get("v") == 1 else 0
    return at / 1000.0 if at else None


def _expire_one(repo_root, c, cl, studio, trash, hide, deliveries, env, now, max_age, is_request, since=0.0):
    rv = cl.get("review") or {}
    path = cl.get("path") or ""
    if not cl.get("auto") or not path or fsio.is_network_path(path) or not os.path.isfile(path):
        return False
    sent = _int_ms(rv.get("deliveredAt"))
    if sent:
        if not TRASH_DELIVERED:
            return False
        age = now - sent / 1000.0
    else:
        age = now - max(os.path.getmtime(path), since)   # 届けていない物は作った時刻か数え始めの時刻の遅い方から
    if age < max_age:
        return False
    live, _m = clip_live(path)
    if not live and cl["auto"].get("origin") != FULL_ORIGIN:
        return False
    if not sent and live and (live.get("deliver") or (is_request is not None and is_request(live.get("recorder"), live.get("recording")))):
        return False   # 友人の依頼・自動で届ける切り抜きは、届けるまで片付けない(届けるのは まとめて実行。届けば「届けた」になる)
    pack = txindex.pack_dir(path)
    if pack and deliveries is not None and deliveries.running(pack):
        return False
    key = (c["id"], cl["markId"])
    with _busy_lock:
        if key in _busy:
            return False
        _busy.add(key)
    try:
        discard_clip(trash, studio, c["id"], "", path, pack)   # マーク "" = 移すだけ(マークは不採用にしない)
        tid = (cl.get("transcript") or {}).get("id") or ""
        if tid and hide:
            try:
                hide(tid)
            except (OSError, ValueError):
                pass
        _remember(repo_root, c["id"], cl["markId"], env, discarded=tid, expired=True)
        return True
    except (ReviewError, OSError):   # 動かせない(元に戻してある): 次の見回りでまた試す
        return False
    finally:
        with _busy_lock:
            _busy.discard(key)


def _remember(repo_root, case_id, mark_id, env=None, discarded=None, expired=False):
    """案件ファイルに自動でできた切り抜きの記録を残す。discarded: 要らない・日数の片付けで移した文字起こしの id("" = 無い)・
    expired: 日数で片付けた(人の「要らない」ではない)。
    古い欄(seenAt・deliveredAt・delivered・origin・notSent)は読み飛ばし、書き換えない。-> その記録 {discardedAt?, tx?, expiredAt?}"""
    now = int(time.time() * 1000)
    loc = locations(repo_root, env)

    def remember(s):
        recs = _auto_records(s)
        r = dict(recs.get(mark_id)) if isinstance(recs.get(mark_id), dict) else {}
        if discarded is not None:
            r.update(discardedAt=now, tx=str(discarded)[:64])
        if expired:
            r["expiredAt"] = now
        recs[mark_id] = r
        if len(recs) > AUTO_KEEP:   # 古いもの(最後に触った時刻)から捨てる
            keep = sorted(recs, key=lambda k: -max([_int_ms(recs[k].get(x)) for x in ("discardedAt", "expiredAt", "seenAt", "deliveredAt")]))[:AUTO_KEEP]
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


def _judgment(c, cl, what, event):
    """人の判断の記録(③ human/judgments)の 1 行の欄(who self・via cases)。.clip.json を読むので、ファイルを動かす前に作る。
    key = lf:<時刻>:<録画 か 配信>:<スタジオのマーク>:<deliver か reject>(写しの live_feedback の人の行と同じ形 = 二重にならない)"""
    live, _m = clip_live(cl.get("path"))
    live = live or {}
    at = int(time.time() * 1000)
    rec = live.get("recording") if isinstance(live.get("recording"), str) else ""
    row = {"at": at, "who": "self", "videoId": c["id"], "markId": cl["markId"], "what": what,
           "origin": "auto" if (cl.get("auto") or {}).get("origin") == FULL_ORIGIN else "live", "via": "cases",
           "key": "lf:%d:%s:%s:%s" % (at, rec or c["id"], cl["markId"], event), "ref": {"recorder": live.get("recorder"), "recording": rec}}
    for k in ("start", "end"):
        if schemas.num(cl.get(k)) is not None:
            row[k] = schemas.num(cl.get(k))
    return row


def _judge(repo_root, row, env):
    """人の判断を 1 行書く。書けなくても操作は済んでいる(-> 書けたか)"""
    try:
        _judgments.record(locations(repo_root, env)["app"], **row)
        return True
    except (OSError, ValueError):
        return False


def _deliver(repo_root, c, cl, deliveries, env):
    """採用 = 友人へ届ける(M12)。パックを zip にして Dropbox の 出力 へ(deliver.Deliveries。数 GB は時間がかかるので裏で。画面は
    api/ytt/deliver の status で聞き直す)。届けた記録は Deliveries が ② の deliveries.jsonl に書く(一覧の「届けた」はそこから引く)。
    受け付けたら人の判断(adopt)を 1 行。-> {ok, job, judged}"""
    rv = cl.get("review") or {}
    if rv.get("deliveredAt"):
        raise ReviewError("この切り抜きはもう届けました(%s)" % (rv.get("delivered") or "Dropbox の 出力"))
    pack = cl.get("pack") or {}
    if not pack.get("dir"):
        raise ReviewError("パックがまだありません(文字起こし → パックが済むと届けられます)")
    if deliveries is None:
        raise ReviewError("届ける仕組みが使えません", 503, "unavailable")
    row = _judgment(c, cl, "adopt", "deliver")
    try:
        job = deliveries.start(pack["dir"], "",   # 題は空 = パックのフォルダの名前(友人のアプリの「受け取る」に出る)
                               clip={"path": cl.get("path") or "", "markId": cl["markId"], "videoId": c["id"]})   # 届けた記録に切り抜きも(友人の「要らない」で mp4 も片付く。Q16)
    except ValueError as e:   # Dropbox のフォルダが決まっていない・見つからない・届けている途中 など(文はそのまま画面へ)
        raise ReviewError(str(e))
    return {"ok": True, "job": job, "judged": _judge(repo_root, row, env)}


def _discard(repo_root, c, cl, studio, trash, hide, deliveries, env):
    """要らない(M9): ① パック・切り抜きの mp4・.clip.json などの途中のファイルを ごみ箱フォルダ へ移す(片付け src/manage/keep/cleanup.py と同じ場所。
    片付けの TRASH_DAYS で起動時に消える。すぐには消さない)② スタジオのマークを不採用(rejected)に(画面と同じ PUT /api/video)③ 人の判断(reject)を 1 行
    ④ その文字起こしを一覧で非表示に(データは消さない)⑤ 案件に「要らない」(discardedAt・tx)を残す。
    ② ができなければ ① を元に戻す(パックだけ消えてマークが残る、を作らない)。-> {ok, moved, trash, studio, judged}"""
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
        row = _judgment(c, cl, "reject", "reject")
        moved, where, st = discard_clip(trash, studio, c["id"], cl["markId"], path, pack)
        tid = (cl.get("transcript") or {}).get("id") or ""
        if tid and hide:
            try:
                hide(tid)
            except (OSError, ValueError):   # 非表示にできなくても片付けは済んでいる(一覧の「単体の文字起こし」には出さない)
                pass
        _remember(repo_root, c["id"], cl["markId"], env, discarded=tid)
        return {"ok": True, "moved": len(moved), "trash": where, "studio": st, "judged": _judge(repo_root, row, env)}
    finally:
        with _busy_lock:
            _busy.discard(key)


def discard_clip(trash, studio, video_id, mark_id, media, pack=None):
    """切り抜き 1 本ぶん(動画・パック・途中のファイル)を ごみ箱フォルダ へ移し、スタジオのマークを不採用に(画面と同じ PUT /api/video)。
    マークを不採用にできなければ移したものを元に戻す(パックだけ消えてマークが残る、を作らない)。mark_id が空(スタジオのマークを変えない)なら移すだけ。
    -> (移したもの [(元, 先)], ごみ箱の場所, スタジオの返事 "rejected"/"gone"/None)。
    M9 の「要らない」(_discard)はマークも不採用に。友人の「要らない」(src/human/friend/friend_feedback.py)はマークがあっても mark_id を空で呼んで
    マークを変えない(友人の採用の基準はこちらの送る基準と別。2026-10-08 ユーザー決定)。
    移す・戻すは ④ keep/trash の 1 か所(設計原則の指摘 1): 戻せずにごみ箱に残った物は manifest に元の場所を書き、ReviewError の文で知らせる"""
    pack = pack if pack is not None else (txindex.pack_dir(media) if media else "")
    extra = [p for suf in cleanup.SIDECARS for p in schemas.sidecar_candidates(media, suf)] if media else []
    files = [p for p in [media, pack] + extra if p and os.path.exists(p)]
    stem = os.path.splitext(os.path.basename(media or pack))[0] or "clip"
    res = _trash.to_trash(trash, files, DISCARD_KIND, stem, all_or_nothing=True, record=False)
    if res["failed"]:   # 1 つでも移せなかった(Resolve・エクスプローラーで開いていると移せない)= 移した分は戻した
        raise ReviewError("ファイルを ごみ箱フォルダ へ移せなかったので、片付けませんでした(Resolve やエクスプローラーで開いていれば閉じて、もう一度): %s%s"
                          % (res["failed"][0][1][:120], _left_note(res)))
    st = None
    if mark_id and video_id:
        try:
            st = _studio_reject(studio, video_id, mark_id)
        except ReviewError as e:
            _trash.put_back(res)
            if res["left"]:
                raise ReviewError(str(e) + _left_note(res), e.code, e.error) from e
            raise
    _trash.record(res)
    return res["moved"], res["dest"], st


def _left_note(res):
    """戻せずにごみ箱に残った物の知らせ(元の場所は manifest に書いてある)。無ければ空"""
    if not res.get("left"):
        return ""
    return "。%d 個は元へ戻せず、ごみ箱フォルダ(%s)に残っています(元の場所は同じ日付のフォルダの manifest.jsonl)" % (len(res["left"]), res["dest"])


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
