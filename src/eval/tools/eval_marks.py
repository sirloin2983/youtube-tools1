#!/usr/bin/env python3
"""盛り上がりの検出(スタジオの自動マーク)の当たり具合を、人の判定の記録で測る道具(線 C の土台。plan/line-bc-master-plan.md の Q3・I-4a)。

    python src/eval/tools/eval_marks.py [--since YYYY-MM-DD] [--until YYYY-MM-DD] [--json] [--data-dir 作業データの親フォルダ] [--status-fallback]
    python src/eval/tools/eval_marks.py --live [--since …] [--until …] [--json]     配信ごと(線 D の D-12。下の「--live」)
    python src/eval/tools/eval_marks.py --analyze-missing [--wait] [--limit N]     未解析の友人の配信の解析をスタジオに頼む(下の「--analyze-missing」)

- --analyze-missing(役割で組み直す計画 RS4。入口の「あとから解析」の代わり): 作業データは読むだけ。**この口だけは、動いているスタジオに解析を頼む**
  (書くのはスタジオ)。友人が区間を指定したのに解析していない配信(下の friendRanges の「未解析」)を区間の新しい順に N 本(既定 10 = スタジオの解析のキューの上限)、
  スタジオの画面で保存した解析の設定で解析のキューに入れる(解析済み・スタジオに無い配信は飛ばす。友人の重み・区間の長さは使わない)。
  スタジオの場所は src/.runtime/studio.json、書き込みの合言葉は画面の HTML から読む(src/eval/tools/_studioapi.py)。スタジオが動いていなければ終了コード 2
- 作業データは**読むだけ**(どの口も。スタジオの data.json・feedback.jsonl(と .old)・archive/<動画ID>.json.gz・入口の logs/autorun-runs.jsonl・
  cut2resolve の packs/)。何も書き換えない。--json のときだけ、結果を スタジオの作業データの evals\\marks\\<日時>.json に残す(原則 3: 機械の最初の結果と人の最終を並べる)
- feedback の行は markId(あれば)で突き合わせる。無い以前の行は区間(auto0)で突き合わせる。
- 「自動マーク」の集まり = data.json の自動マーク(再解析で手動に変わったものも含む)+ archive の最後の解析の候補(消えたものを補う)+
  feedback にだけ残っているもの(候補のまま削除した・判定のあと削除した)。同じマークは最初の自動区間(auto0)で突き合わせる(±0.6 秒)。
  点数の順(高い順)に並べ、人の判定を当てる。
- 人の判定 = feedback.jsonl の行を時刻の順に見た最後の結果: adopt・export = 良い / reject・delete = 悪い / unadopt・delete_judged(採用・書き出し済みの削除)= 取り消し(判定なしに戻る)。
  data.json のマークがあれば、いまの status を優先する(候補に戻した・不採用にした、が行に残らない場合がある)
- **まとめて実行(自動採用)・依頼が自動で埋めた分は人の判断ではないので「良い」に数えない**(友人が時刻で指定した区間も、この数え方では外れる。区間は下の friendRanges で別に測る)。
  マークの adoptedBy(auto / request)と、feedback の行の adoptedBy(書き出しの行を含む)で見分ける。
  印の無い以前の記録だけ、近似として入口の実行記録(autorun-runs.jsonl)で、その配信に「採用」の段が実行されていて、人の adopt の行が無いものを「自動採用」とみなす(近似)。
  採用・書き出しの status があるのに行も実行記録も無いものは「記録なし」として別に数える(--status-fallback を付けると人の判定として数える)
- 指標(全体・配信の種類ごと・配信ごと):
    上位 N(5・10・20・全部)の採用率 = 良い ÷ 判定済み(判定なしは分母に入れず、数を別に出す。参考として 良い ÷ N 件 の採用率(全体)も出す)
    書き出し率 = 書き出した ÷ 良い / パックになった率 = パックがある ÷ 書き出した(manage.cases.txindex.pack_info)/ 友人に届けた率 = 届けた ÷ 書き出した(入口の実行記録の deliver の段)
    手で足したマーク(manual_add = 見逃し)= 数・割合(手で足した ÷ (手で足した + 良い自動マーク))・近くの自動マークの点数と距離の分布
    区間の端のずれ = 良い自動マークの dStart・dEnd(人が直した量。秒)の分布と、0.5 秒以上直した率 / 採用の取り消しの数
- 友人が時刻で指定した区間(結果の `friendRanges`・表示の最後の節): 友人が依頼で入れた区間は「自動の候補を見ずに人が選んだ見どころ」で、
  候補に出なかった場面も含む。出どころ 1 = 入口の実行記録の videoId・ranges(指定したまま)/ 2 = それが無い以前の分は、スタジオのマークの adoptedBy が request の手動マーク
  (前後の余白 FRIEND_PAD を引いて戻す。人が状態を変えると印が外れるので取りこぼす)。同じ配信・同じ区間(±0.6 秒)は 1 つにまとめる。
  自動の候補(上の「自動マークの集まり」。点数の高い順)と比べ、当たり(区間と時間が重なる候補。定数 HIT_OVERLAP)・上位 N で拾えた率・見逃し・長さごとの拾えた率などを出す。
  解析していない配信(自動の候補も解析の記録も無い)の区間は「未解析」として別に数え、見逃しに入れない
- 人が選んだ区間の長さ(結果の `clipLength`・表示の最後の節): 自動マークの長さは解析の設定 length・preRatio の固定なので、人が実際に選んだ長さから目安を出す。
  見本 = friend(友人の区間。未解析の配信も長さは使う)/ manual(手で足したマーク。依頼のマーク・友人の区間と同じものは数えない)/
  adjusted(人が良いにして端を 0.5 秒以上直した自動マークの、直したあとの長さ)/ kept(良いにして直さなかった自動マーク = 今の設定の長さのまま)。
  5 秒未満・600 秒超は外れ値(数だけ別に)。suggest = friend・manual・adjusted の長さの中央値(10〜120 に収める。kept は中央値に入れず数だけ添える)と、
  見本の区間の中にある候補の山の位置の割合(山 − 開始)÷ 長さ の中央値(0.3〜0.9)。見本 20 個・配信 5 本以上で enough。設定は書き換えない(読むだけ。入口が --json の結果の clipLength.suggest を読む)
- --since / --until(原則 4: 時期で分ける)は、マークの作られた日時(data.json は createdAt・archive は解析の日時・feedback だけのものは最初の行の日時)と
  手で足した・取り消した行の日時で絞る(until はその日を含む)。配信が 10 本未満のときは「まだ少ない(参考)」と出す(少ないデータで決めすぎない)。
  friendRanges は実行の記録の時刻(出どころ 2 はマークの作られた時刻)で絞る。解析済みの区間が 20 未満・配信が 5 本未満のときは「まだ少ない(参考)」
- C1 の入口の数(結果の overall.judgedElsewhere・judgedAll。K2 = 10-08 決定): 判定のある配信の数に、スタジオの判定の外の人の判定も足す =
  線 D の録画(live/live_feedback.jsonl の人の「届けた」「要らない」)と、友人の返事(logs/friend_feedback.jsonl。配信は videoId → 実行記録の runId →
  切り抜きのフォルダの順にたどる)。採用率・見逃しなどの指標には混ぜない(友人が採る基準は送る基準と別 = 10-08 ユーザー決定)。入口の「調子」の
  「採用の記録 配信 10 本」は judgedAll を読む(src/eval/drill/accuracy.py の summarize_marks)
- --live(線 D の D-12。L5 の土台): 入口の配信ごとの記録(入口の作業データ live/reports/<録画元>__<録画>.json。src/flow/live_report.py が録画中に書き、
  終わったら締める)と採用の記録(live/live_feedback.jsonl)を読んで、録画ごとに 候補(枠・控え・見送り)・採用(自動・人)・人の判定(届けた = 良い /
  要らない = 悪い。自動の採用だけ)・配信中の候補とアーカイブの候補の重なり(detect_compare の行 = 配信後の全自動 M7 が書く)・ワーカーの遅れとメモリの最大・
  配信中の文字起こしの成否・書き出しの待ち・空き を並べる。時期は記録の startedAt(行は at)で絞る。録画が 5 本未満なら「まだ少ない(参考)」。
  --json は スタジオの作業データの evals\\marks\\<日時>-live.json
"""
import argparse
import calendar
import gzip
import json
import os
import re
import sys
import time
import urllib.parse

HERE = os.path.dirname(os.path.abspath(__file__))
SRC = os.path.dirname(os.path.dirname(HERE))   # tools -> eval -> src
if not __package__:   # スクリプトとして起動したとき(py -3.10 src/eval/tools/eval_marks.py)だけ。src を先頭に・この道具のフォルダは外す(兄弟は絶対 import で読む。見本 pipeline/transcribe/worker.py)
    sys.path[:] = [SRC] + [p for p in sys.path if os.path.normcase(os.path.abspath(p or os.curdir)) not in (os.path.normcase(HERE), os.path.normcase(SRC))]
from eval.tools import _studioapi as API  # noqa: E402  スタジオの API を呼ぶ(--analyze-missing だけ)
from eval.tools import _evalcommon as C  # noqa: E402  共通の部品(作業データの場所・時期・率・分布・保存。src を sys.path に足す)
from eval.tools._evalcommon import pct, rate, read_json  # noqa: E402
from manage.cases import txindex  # noqa: E402
from ytt import studiodata  # noqa: E402  スタジオの data.json の読み口
from pipeline.analyze import excite  # noqa: E402

SCHEMA = "youtube-tools-marks-eval/v1"
TOPS = (5, 10, 20)
FEW_VIDEOS = 10          # これより少ない配信数のときは「まだ少ない(参考)」
TOL = 0.6                # 同じ区間とみなす秒(src/human/review/store.py の DUP_TOL 0.5 に少し余裕)
EDIT_SEC = 0.5           # これ以上端を動かしたら「直した」
NEAR_SEC = 15.0          # 手で足したマークの近くに自動マークがあったとみなす距離(秒)
MAX_JSONL_BYTES = 256 * 1024 * 1024
HUMAN_EVENTS = ("adopt", "export", "reject", "delete")
RETRACT_EVENTS = ("unadopt", "delete_judged")
FRIEND_FEW_RANGES = 20   # friendRanges: 解析済みの区間がこれより少ない・
FRIEND_FEW_VIDEOS = 5    # 配信がこれより少ないときは「まだ少ない(参考)」
HIT_OVERLAP = 0.5        # friendRanges の当たり: 候補の真ん中が区間の中、または重なりが候補の長さのこの割合以上
FRIEND_PAD = 2.0         # 依頼で自動で足される前後の余白(src/flow/spec.py の RANGE_PAD と同じ値。出どころ 2 で引く)
FRIEND_SHORT, FRIEND_LONG = 30.0, 120.0   # 区間の長さの区切り(30 秒未満 / 30〜120 秒 / 120 秒以上)。端のずれは 120 秒未満の区間だけ
PART_ON = excite.PART_ON              # 点数の内訳が「効いた」とみなす値(候補の理由の付け方と同じ 1 か所 = src/pipeline/analyze/excite.py)
DEFAULT_PRE = excite.PRE_RATIO_DEFAULT   # clipLength: 山の位置の既定(解析の記録に preRatio が無いとき)
CL_OUTLIER_MIN, CL_OUTLIER_MAX = 5.0, 600.0   # 人が選んだ区間の長さの外れ値(この外は数だけ別に出して、目安に入れない)
CL_LENGTH_MIN, CL_LENGTH_MAX = 10, 120        # 目安の長さの範囲(スタジオの解析の設定 length の範囲)
CL_PRE_MIN, CL_PRE_MAX = 0.3, 0.9             # 目安の preRatio の範囲(同 preRatio の範囲)
CL_PRE_MIN_SAMPLES = 10   # 山の位置の見本がこれ未満なら preRatio の目安は出さない(None)
CL_ENOUGH_SAMPLES, CL_ENOUGH_VIDEOS = 20, 5   # 目安の enough: 見本 20 以上かつ配信 5 本以上
ARCHIVE_ID_RE = re.compile(r"^[\w-]{1,40}\Z", re.ASCII)


# ---------------------------------------------------------------- 読み込み(読むだけ)

def read_jsonl(path):
    """1行ずつ JSON として読む(壊れた行・書きかけの行は飛ばす)。無ければ []"""
    out = []
    try:
        if os.path.getsize(path) > MAX_JSONL_BYTES:
            return out
        with open(path, "rb") as f:
            for raw in f:
                try:
                    d = json.loads(raw.decode("utf-8"))
                except (ValueError, UnicodeDecodeError):
                    continue
                if isinstance(d, dict):
                    out.append((raw.strip(), d))
    except OSError:
        pass
    return out


def locate(data_dir=None):
    """-> (env, studio のフォルダ, 入口(app)のフォルダ)。置き場所の規則は ytt.datadir の1か所。
    data_dir を渡したとき(テスト)は、そこを全ツールの作業データの親フォルダとして使う(cut2resolve の packs も同じ親の下)"""
    return C.data_env(data_dir), C.locate("studio", data_dir), C.locate("app", data_dir)


def studio_videos(studio):
    """スタジオの data.json の videos(読めない・形が違えば {})。ライブの録画も含めたまま"""
    return studiodata.videos(os.path.join(studio, "data.json"))


def load_feedback(studio):
    """feedback.jsonl.old → feedback.jsonl の行(重複は同じ行の文字列で除く。.old へ移すときの途中停止で重なることがある)。時刻の順"""
    seen, rows = set(), []
    for name in ("feedback.jsonl.old", "feedback.jsonl"):
        for raw, d in read_jsonl(os.path.join(studio, name)):
            if raw in seen or not isinstance(d.get("videoId"), str):
                continue
            seen.add(raw)
            rows.append(d)
    rows.sort(key=lambda r: str(r.get("ts") or ""))   # 同じ時刻なら書いた順のまま(sort は安定)
    return rows


def archive_reader(studio):
    """load_archive を配信ごとに 1 回だけ読む形にしたもの(1 回の evaluate の中で使い回す。gz を何度も開かない)"""
    cache = {}

    def get(vid):
        if vid not in cache:
            cache[vid] = load_archive(studio, vid)
        return cache[vid]
    return get


def load_archive(studio, vid):
    """archive/<動画ID>.json.gz の最後の解析 -> {"at", "type", "candidates"} か None"""
    if not ARCHIVE_ID_RE.match(vid):
        return None
    try:
        with gzip.open(os.path.join(studio, "archive", vid + ".json.gz"), "rt", encoding="utf-8") as f:
            d = json.load(f)
    except (OSError, ValueError, EOFError):
        return None
    runs = d.get("runs") if isinstance(d, dict) and d.get("v") == 1 else None
    run = next((r for r in reversed(runs) if isinstance(r, dict)), None) if isinstance(runs, list) else None
    if not run:
        return None
    return {"at": run.get("at"), "type": run.get("type") or d.get("type"), "spec": run.get("spec") if isinstance(run.get("spec"), dict) else {}, "candidates": [c for c in run.get("candidates") or [] if isinstance(c, dict)]}


def run_records(app):
    """入口の実行記録(autorun-runs.jsonl.1 → 今のファイル)の行(壊れた行は飛ばす)"""
    return [r for name in ("autorun-runs.jsonl.1", "autorun-runs.jsonl") for _, r in read_jsonl(os.path.join(app, "logs", name))]


def load_runs(app, records=None):
    """入口の実行記録 -> (自動採用の段が動いた配信の ID の集合, {配信 ID: 友人へ届けたマークの ID の集合}, 届けたがマークの ID が無い実行の数)。
    records = run_records(app) を読んであれば渡す(同じファイルを 2 回読まない)"""
    machine, delivered, unknown = set(), {}, 0
    for r in run_records(app) if records is None else records:
        vid = r.get("videoId")
        if not isinstance(vid, str) or not isinstance(r.get("steps"), list):
            continue
        states = {s.get("key"): s.get("state") for s in r["steps"] if isinstance(s, dict)}
        if states.get("adopt") == "done":
            machine.add(vid)
        if states.get("deliver") == "done":
            ids = r.get("marks")
            if isinstance(ids, list) and ids:
                delivered.setdefault(vid, set()).update(str(x) for x in ids)
            else:
                unknown += 1
    return machine, delivered, unknown


# ---------------------------------------------------------------- 日時・数の小道具

def ts_ms(ts):
    try:
        return int(time.mktime(time.strptime(str(ts), "%Y-%m-%dT%H:%M:%S")) * 1000)
    except (ValueError, OverflowError):
        return None


def num(x):
    return float(x) if isinstance(x, (int, float)) and not isinstance(x, bool) and x == x and abs(x) < 1e9 else None


def dist(values):
    """数のそろいの分布(秒・点数なので 2 桁。90% も)-> {"n", "min", "p25", "median", "p75", "p90", "max", "mean"}(空なら n だけ)"""
    return C.dist(values, 2, True)


def same(a0, b0):
    return abs(a0[0] - b0[0]) <= TOL and abs(a0[1] - b0[1]) <= TOL


def pair(v):
    if isinstance(v, (list, tuple)) and len(v) == 2 and num(v[0]) is not None and num(v[1]) is not None:
        return (float(v[0]), float(v[1]))
    return None


# ---------------------------------------------------------------- 自動マークの集まりを作る

def build_videos(studio, rows, runs, packs, since=None, until=None, status_fallback=False, dvideos=None, archive=None):
    """-> ({動画 ID: video}, 注意の一覧)。video = {"id", "title", "type", "auto": [item], "manual": [item], "adds": [...], "retracts": n}
    item(自動マーク)= {"a0", "score", "start", "end", "t", "src"(data / archive / feedback), "status", "path", "markId", "events", "verdict", "origin", ...}
    dvideos = studio_videos(studio)・archive = archive_reader(studio) を読んであれば渡す(無ければここで読む)"""
    machine, delivered, _unknown = runs
    dvideos = studio_videos(studio) if dvideos is None else dvideos
    dvideos = {k: v for k, v in dvideos.items() if not (isinstance(v, dict) and v.get("kind") == "live")}   # ライブの録画は解析していない(手のマークだけ)
    archive = archive or archive_reader(studio)
    by_row = {}
    for r in rows:
        if r.get("kind") == "live":   # ライブの録画(線 D の P3。解析していない)は盛り上がりの検出の評価に入れない(スタジオは 2026-10-05 から書かない)
            continue
        by_row.setdefault(r["videoId"], []).append(r)
    videos = {}
    notes = []

    def in_range(t):
        return C.in_period(t, since, until)   # 日時が分からないものは落とさない

    for vid in sorted(set(dvideos) | set(by_row)):
        dv = dvideos.get(vid) if isinstance(dvideos.get(vid), dict) else {}
        an = dv.get("analysis") if isinstance(dv.get("analysis"), dict) else {}
        arch = archive(vid)
        rv = by_row.get(vid, [])
        typ = an.get("type") or next((r.get("type") for r in rv if r.get("type")), None) or (arch or {}).get("type") or "不明"
        V = {"id": vid, "title": str(dv.get("title") or "")[:80], "type": typ, "auto": [], "manual": [], "adds": [], "retracts": 0, "unadopts": 0, "deleteJudged": 0,
             "pre": num((an.get("spec") if isinstance(an.get("spec"), dict) else (arch or {}).get("spec") or {}).get("preRatio"))}   # その解析の preRatio(山の位置を戻すのに使う)
        autos = V["auto"]

        def find(a0, rid=""):
            """区間(auto0)で突き合わせる。行に markId があるときは、別の ID を持つマークとは突き合わせない"""
            return next((it for it in autos if same(it["a0"], a0) and (not rid or not it["markId"] or it["markId"] == rid)), None)

        def by_id(lst, rid):
            return next((it for it in lst if it["markId"] == rid), None) if rid else None

        # 1. data.json のマーク
        for m in dv.get("marks") or []:
            if not isinstance(m, dict):
                continue
            s, e = num(m.get("start")), num(m.get("end"))
            if s is None or e is None:
                continue
            a0 = pair(m.get("auto0")) or pair(m.get("auto0Orig"))
            item = {"a0": a0 or (s, e), "start": s, "end": e, "score": num(m.get("score")), "t": m.get("createdAt") if isinstance(m.get("createdAt"), int) else None,
                    "src": "data", "status": m.get("status") or "", "path": m.get("path") or "", "markId": str(m.get("id") or ""), "events": [], "a0known": a0 is not None,
                    "adoptedBy": m.get("adoptedBy") if m.get("adoptedBy") in ("auto", "request") else None,
                    "parts": m.get("parts") if isinstance(m.get("parts"), dict) else None, "reasons": m.get("reasons") if isinstance(m.get("reasons"), list) else None, "peak": num(m.get("peak"))}
            if m.get("src") == "auto" or (m.get("src") == "manual" and a0):
                autos.append(item)
            elif m.get("src") == "manual":
                V["manual"].append(item)
        # 2. archive の最後の解析の候補(data.json から消えたものを補う。判定は無い)
        for c in (arch or {}).get("candidates") or []:
            s, e = num(c.get("start")), num(c.get("end"))
            if s is None or e is None or find((s, e)):
                continue
            autos.append({"a0": (s, e), "start": s, "end": e, "score": num(c.get("score")), "t": arch.get("at") if isinstance(arch.get("at"), int) else None, "src": "archive",
                          "status": "", "path": "", "markId": "", "events": [], "a0known": True, "adoptedBy": None,
                          "parts": c.get("parts") if isinstance(c.get("parts"), dict) else None, "reasons": None, "peak": num(c.get("peak"))})
        # 3. feedback の行
        for r in rv:
            ev = r.get("event") or ""
            s, e = num(r.get("start")), num(r.get("end"))
            t = ts_ms(r.get("ts"))
            rid = r.get("markId") if isinstance(r.get("markId"), str) else ""   # 新しい行は markId で突き合わせる(無い以前の行は区間)
            if ev == "manual_add":
                if in_range(t):
                    near = r.get("nearAuto") if isinstance(r.get("nearAuto"), dict) else None
                    V["adds"].append({"t": t, "start": s, "end": e, "markId": rid, "autoCount": r.get("autoCount"), "cancelled": False,
                                      "nearScore": num((near or {}).get("score")), "nearDistance": num((near or {}).get("distance"))})
                continue
            if ev == "manual_remove":
                for ad in reversed(V["adds"]):   # 手で足したあと同じ区間を消した = 足したのは取り消し
                    if ad["cancelled"]:
                        continue
                    if (rid and ad["markId"] == rid) or (not (rid and ad["markId"]) and s is not None and ad["start"] is not None and abs(ad["start"] - s) <= TOL and abs(ad["end"] - e) <= TOL):
                        ad["cancelled"] = True
                        break
                continue
            if rid and ev in HUMAN_EVENTS + RETRACT_EVENTS:
                hit = by_id(autos, rid) or by_id(V["manual"], rid)
                if hit is not None:
                    hit["events"].append((ev, r))
                    continue
            a0 = pair(r.get("auto0")) if r.get("auto0") else None
            if a0 is None and (r.get("src") != "auto" or s is None or e is None):
                # 手動マークの判定は、手動マークの数え方(manual)にだけ使う(下)
                if ev in HUMAN_EVENTS + RETRACT_EVENTS and s is not None and e is not None:
                    mi = next((x for x in V["manual"] if same((x["start"], x["end"]), (s, e)) and (not rid or not x["markId"] or x["markId"] == rid)), None)
                    if mi is None and in_range(t):
                        mi = {"a0": (s, e), "start": s, "end": e, "score": None, "t": t, "src": "feedback", "status": "", "path": "", "markId": rid, "events": [], "a0known": False, "adoptedBy": None}
                        V["manual"].append(mi)
                    if mi is not None:
                        mi["events"].append((ev, r))
                continue
            a0 = a0 or (s, e)
            it = find(a0, rid)
            if it is None:
                it = {"a0": a0, "start": s, "end": e, "score": num(r.get("score")), "t": t, "src": "feedback", "status": "", "path": "", "markId": rid, "events": [], "a0known": bool(r.get("auto0")), "adoptedBy": None}
                autos.append(it)
            elif rid and not it["markId"]:
                it["markId"] = rid   # archive の候補に、消えたマークの ID を結びつける
            it["events"].append((ev, r))
        # 4. 取り消しの数(日時で絞る)
        for r in rv:
            t = ts_ms(r.get("ts"))
            ev = r.get("event")
            if ev in RETRACT_EVENTS and in_range(t) and (ev == "unadopt" or r.get("prevStatus") in ("adopted", "exported")):
                V["retracts"] += 1
                V["unadopts" if ev == "unadopt" else "deleteJudged"] += 1
        # 5. 判定・書き出し・パック・届けを決める。日時で絞る
        V["auto"] = [it for it in autos if in_range(it["t"] if it["t"] is not None else (ts_ms(it["events"][0][1].get("ts")) if it["events"] else None))]
        V["manual"] = [it for it in V["manual"] if in_range(it["t"])]
        for it in V["auto"] + V["manual"]:
            judge(it, vid in machine, status_fallback)
            if it["verdict"] == "good" and it["exported"]:
                info = txindex.pack_info(it["path"], packs) if it["path"] else None
                it["packed"] = bool(info)
                it["delivered"] = bool(it["markId"]) and it["markId"] in delivered.get(vid, ())
            else:
                it["packed"] = it["delivered"] = False
        if V["auto"] or V["manual"] or V["adds"] or V["retracts"]:
            videos[vid] = V
    return videos, notes


def judge(it, machine_video, status_fallback):
    """item の events(時刻の順)と data.json の status から、人の判定を決める。
    it["verdict"] = good / bad / none(判定なし)/ machine(自動採用)/ unrecorded(status はあるが行も実行記録も無い)
    it["exported"] = 書き出した(良いもののうち)"""
    state, exported, human_adopt = None, False, False
    for ev, r in it["events"]:
        if ev in ("adopt", "export") and r.get("adoptedBy"):
            state, exported = "machine", False   # 機械が採用にしたマークの行(書き出しの行を含む)は人の判定ではない
        elif ev == "adopt":
            state, human_adopt = "good", True
        elif ev == "export":
            state, exported = "good", True
        elif ev in ("reject", "delete"):
            state, exported = "bad", False
        elif ev == "unadopt":
            state, exported = None, False
        elif ev == "delete_judged" and r.get("prevStatus") in ("adopted", "exported"):
            state, exported = None, False
    if any(r.get("markId") for _, r in it["events"]):
        machine_video = False   # markId のある新しい行は adoptedBy で機械の採用を見分けられる。実行記録からの近似は、印の無い以前の記録だけ
    st = it["status"] if it["src"] == "data" else None
    if st is None:   # data.json に無い(削除した・archive だけ): 行だけで決める
        verdict = state or "none"
    elif st in ("adopted", "exported"):
        if it.get("adoptedBy") or state == "machine":   # 機械が採用にした印(人が状態を変えると外れる)。印の無い以前の記録は、下の近似(実行記録)
            verdict = "machine"
        elif state == "good" and not (machine_video and not human_adopt):
            verdict = "good"
        elif machine_video and not human_adopt:
            verdict = "machine"
        elif status_fallback:
            verdict = "good"
        else:
            verdict = "unrecorded"
        exported = st == "exported" and verdict in ("good",)
    elif st == "rejected":
        verdict, exported = "bad", False
    else:
        verdict, exported = "none", False
    it["verdict"], it["exported"] = verdict, bool(exported and verdict == "good")
    # 端のずれ(人が直した量。秒): data のマークの今の区間 − 最初の自動区間。data が無ければ最後の行の dStart・dEnd
    it["dStart"] = it["dEnd"] = None
    if it["a0known"] and it["src"] == "data":
        it["dStart"], it["dEnd"] = round(it["start"] - it["a0"][0], 2), round(it["end"] - it["a0"][1], 2)
    else:
        for ev, r in reversed(it["events"]):
            if num(r.get("dStart")) is not None and num(r.get("dEnd")) is not None:
                it["dStart"], it["dEnd"] = num(r["dStart"]), num(r["dEnd"])
                break


# ---------------------------------------------------------------- 指標

def funnel(items):
    """item の並び -> 採用・書き出し・パック・届けの数と率"""
    n = len(items)
    c = {k: sum(1 for i in items if i["verdict"] == k) for k in ("good", "bad", "none", "machine", "unrecorded")}
    exported = sum(1 for i in items if i["exported"])
    packed = sum(1 for i in items if i["packed"])
    delivered = sum(1 for i in items if i["delivered"])
    judged = c["good"] + c["bad"]
    return {"items": n, "judged": judged, "good": c["good"], "bad": c["bad"], "unjudged": c["none"], "machine": c["machine"], "unrecorded": c["unrecorded"],
            "adoptRate": rate(c["good"], judged), "adoptRateAll": rate(c["good"], n),
            "exported": exported, "exportRate": rate(exported, c["good"]),
            "packed": packed, "packRate": rate(packed, exported),
            "delivered": delivered, "deliveredRate": rate(delivered, exported)}


def ranked(auto):
    """点数の高い順(点数が無いものは後ろ)"""
    return sorted(auto, key=lambda i: (-(i["score"] if i["score"] is not None else -1e9), i["start"] if i["start"] is not None else 0))


def group_metrics(vlist):
    """動画(build_videos の V)の集まり -> 指標。N 件は配信ごとに上位 N を取ってから合わせる(配信を重く見すぎない)"""
    out = {"videos": len(vlist), "judgedVideos": 0}
    tops = {n: [] for n in TOPS}
    tops["all"] = []
    good_items, adds, manual, edits = [], [], [], []
    for V in vlist:
        r = ranked(V["auto"])
        if any(i["verdict"] in ("good", "bad") for i in r) or V["adds"]:
            out["judgedVideos"] += 1
        tops["all"] += r
        for n in TOPS:
            tops[n] += r[:n]
        good_items += [i for i in r if i["verdict"] == "good"]
        adds += [a for a in V["adds"] if not a["cancelled"]]
        manual += V["manual"]
    out["top"] = {("all" if k == "all" else "top%d" % k): funnel(v) for k, v in tops.items()}
    ng = len(good_items)
    na = len(adds)
    near = [a["nearDistance"] for a in adds if a["nearDistance"] is not None]
    out["misses"] = {"added": na, "goodAuto": ng, "missRate": rate(na, na + ng),
                     "nearDistance": dist(near), "nearScore": dist([a["nearScore"] for a in adds]),
                     "withNearAuto": len(near), "noAuto": na - len(near), "near15s": sum(1 for d in near if d <= NEAR_SEC),
                     "farOrNone": na - sum(1 for d in near if d <= NEAR_SEC)}
    abs_all = [abs(x) for i in good_items for x in (i["dStart"], i["dEnd"]) if x is not None]
    both = [i for i in good_items if i["dStart"] is not None]
    out["edits"] = {"items": len(both), "dStart": dist([abs(i["dStart"]) for i in both]), "dEnd": dist([abs(i["dEnd"]) for i in both]),
                    "dStartSigned": dist([i["dStart"] for i in both]), "dEndSigned": dist([i["dEnd"] for i in both]),
                    "editedRate": rate(sum(1 for i in both if abs(i["dStart"]) >= EDIT_SEC or abs(i["dEnd"]) >= EDIT_SEC), len(both)), "absMean": round(sum(abs_all) / len(abs_all), 2) if abs_all else None}
    out["retracts"] = {"unadopt": sum(V["unadopts"] for V in vlist), "deleteJudged": sum(V["deleteJudged"] for V in vlist), "total": sum(V["retracts"] for V in vlist)}
    mg = [m for m in manual if m["verdict"] == "good"]
    out["manualMarks"] = {"marks": len(manual), "good": len(mg), "exported": sum(1 for m in mg if m["exported"]), "packed": sum(1 for m in mg if m["packed"]), "delivered": sum(1 for m in mg if m["delivered"])}
    return out


# ---------------------------------------------------------------- 友人が時刻で指定した区間(friendRanges)

def load_friend_runs(app, records=None):
    """入口の実行記録の、友人が指定した区間 -> [{"videoId", "start", "end", "t"(実行の作られた時刻 ms か None), "source": "runs"}](記録の順)。
    ranges は指定したままの区間 [[開始秒, 終了秒], …](余白を足す前)。形の違うものは飛ばす。records は load_runs と同じ"""
    out = []
    for r in run_records(app) if records is None else records:
        vid = r.get("videoId")
        if not isinstance(vid, str) or not isinstance(r.get("ranges"), list):
            continue
        t = r.get("created") if isinstance(r.get("created"), int) and not isinstance(r.get("created"), bool) else None
        if t is None and isinstance(r.get("finished"), int) and not isinstance(r.get("finished"), bool):
            t = r["finished"]
        for rg in r["ranges"]:
            p = pair(rg)
            if p and p[1] > p[0] >= 0:
                out.append({"videoId": vid, "start": p[0], "end": p[1], "t": t, "source": "runs"})
    return out


def unpad_mark(m, duration):
    """出どころ 2: 依頼が足した前後の余白(FRIEND_PAD)を引いて、友人が指定した区間へ戻す。
    0 と配信の長さで切られていた端は、戻しすぎない(開始 0 のまま・終了は長さのまま)。-> (開始, 終了, 開始が切られていた, 終了が切られていた)"""
    s, e = m["start"], m["end"]
    cs = s <= 0.05
    ce = bool(duration and duration > 0 and e >= duration - 0.05)
    a = 0.0 if cs else s + FRIEND_PAD
    b = e if ce else e - FRIEND_PAD
    if b - a < 0.1:   # 余白を引くと残らない短い区間は、そのまま
        a, b, cs, ce = s, e, False, False
    return a, b, cs, ce


def same_friend_range(a, b):
    """同じ区間か(±TOL)。b が余白の切られた端(b["cs"]・b["ce"])を持つときは、その端は余白の分まで動いてよい"""
    if b.get("cs"):
        ok_s = -TOL <= a["start"] <= FRIEND_PAD + TOL
    else:
        ok_s = abs(a["start"] - b["start"]) <= TOL
    if b.get("ce"):
        ok_e = abs(a["end"] - b["end"]) <= FRIEND_PAD + TOL
    else:
        ok_e = abs(a["end"] - b["end"]) <= TOL
    return ok_s and ok_e


def collect_friend_ranges(run_ranges, dvideos, since=None, until=None):
    """出どころ 1(実行の記録)+ 出どころ 2(スタジオの adoptedBy が request の手動マーク。1 に無いものだけ)-> {配信 ID: [区間]}。
    同じ配信・同じ区間(±TOL)は 1 つにまとめる(いちばん早い時刻を残す)。--since / --until は、まとめたあとの区間の時刻で絞る(時刻が無いものは落とさない)"""
    per = {}

    def add(rg):
        lst = per.setdefault(rg["videoId"], [])
        if not any(same_friend_range(x, rg) or same_friend_range(rg, x) for x in lst):
            lst.append(rg)

    for rg in run_ranges:
        add(dict(rg))
    for vid in sorted(dvideos):
        dv = dvideos[vid]
        if not isinstance(dv, dict):
            continue
        dur = num(dv.get("duration"))
        for m in dv.get("marks") or []:
            if not isinstance(m, dict) or m.get("src") != "manual" or m.get("adoptedBy") != "request" or not str(m.get("id") or "").startswith("r"):
                continue
            s, e = num(m.get("start")), num(m.get("end"))
            if s is None or e is None or e <= s:
                continue
            a, b, cs, ce = unpad_mark({"start": s, "end": e}, dur)
            t = m.get("createdAt") if isinstance(m.get("createdAt"), int) and not isinstance(m.get("createdAt"), bool) else None
            add({"videoId": vid, "start": round(a, 2), "end": round(b, 2), "t": t, "source": "marks", "cs": cs, "ce": ce})

    def in_range(t):
        return C.in_period(t, since, until)

    return {vid: [r for r in lst if in_range(r["t"])] for vid, lst in sorted(per.items()) if any(in_range(r["t"]) for r in lst)}


def friend_hit(cand, rng):
    """区間 rng=(開始, 終了) に自動の候補 cand=(開始, 終了) が当たるか: 候補の真ん中が区間の中、または重なりが候補の長さの HIT_OVERLAP 以上"""
    cs, ce = cand
    mid = (cs + ce) / 2
    if rng[0] <= mid <= rng[1]:
        return True
    ov = min(ce, rng[1]) - max(cs, rng[0])
    return ce > cs and ov > 0 and ov >= HIT_OVERLAP * (ce - cs)


def friend_gap(cand, rng):
    """区間と候補のあいだの秒(重なっていれば 0)"""
    return max(0.0, max(cand[0], rng[0]) - min(cand[1], rng[1]))


def judge_friend_range(rg, cands, analyzed):
    """1 つの区間を、その配信の自動の候補(ranked の順)と比べる -> 結果の辞書。解析していない配信は analyzed=False(rank などは None)"""
    res = {"videoId": rg["videoId"], "source": rg["source"], "start": rg["start"], "end": rg["end"], "length": round(rg["end"] - rg["start"], 2), "t": rg["t"],
           "analyzed": analyzed, "hit": False, "rank": None, "score": None, "hits": 0, "dStart": None, "dEnd": None,
           "nearDistance": None, "nearScore": None, "nearRank": None, "parts": None, "reasons": None}
    if not analyzed:
        return res
    rng = (rg["start"], rg["end"])
    hits = [(i + 1, c) for i, c in enumerate(cands) if friend_hit(c["a0"], rng)]
    res["hits"] = len(hits)
    if hits:
        rank, best = hits[0]
        res.update(hit=True, rank=rank, score=best["score"], parts=best.get("parts"), reasons=best.get("reasons"),
                   dStart=round(best["a0"][0] - rng[0], 2), dEnd=round(best["a0"][1] - rng[1], 2))
    elif cands:
        d, rank, c = min(((friend_gap(c["a0"], rng), i + 1, c) for i, c in enumerate(cands)), key=lambda x: (x[0], x[1]))
        res.update(nearDistance=round(d, 2), nearScore=c["score"], nearRank=rank)
    return res


def friend_group(results):
    """区間の結果(judge_friend_range)の集まり -> 指標"""
    vids = {r["videoId"] for r in results}
    an = [r for r in results if r["analyzed"]]
    an_vids = {r["videoId"] for r in an}
    hit = [r for r in an if r["hit"]]
    miss = [r for r in an if not r["hit"]]
    out = {"videos": len(vids), "analyzedVideos": len(an_vids), "unanalyzedVideos": len(vids - an_vids),
           "ranges": len(results), "analyzedRanges": len(an), "unanalyzedRanges": len(results) - len(an),
           "sources": {"runs": sum(1 for r in results if r["source"] == "runs"), "marks": sum(1 for r in results if r["source"] == "marks")},
           "hit": len(hit), "hitRate": rate(len(hit), len(an)), "miss": len(miss), "missRate": rate(len(miss), len(an))}
    top = {}
    for n in TOPS:
        k = sum(1 for r in hit if r["rank"] <= n)
        top["top%d" % n] = {"hit": k, "rate": rate(k, len(an))}
    top["all"] = {"hit": len(hit), "rate": rate(len(hit), len(an))}
    out["top"] = top
    out["bestRank"] = dist([r["rank"] for r in hit])
    out["bestScore"] = dist([r["score"] for r in hit])
    nd = [r["nearDistance"] for r in miss if r["nearDistance"] is not None]
    out["misses"] = {"missed": len(miss), "nearDistance": dist(nd), "nearScore": dist([r["nearScore"] for r in miss]), "withNearAuto": len(nd),
                     "noAuto": len(miss) - len(nd), "near15s": sum(1 for d in nd if d <= NEAR_SEC), "farOrNone": len(miss) - sum(1 for d in nd if d <= NEAR_SEC)}
    # 点数の内訳(当たったいちばん上の候補に parts があるものだけ。無ければ None)
    withp = [r for r in hit if r["parts"]]
    if withp:
        on = {k: sum(1 for r in withp if (num(r["parts"].get(k)) or 0) >= th) for k, th in PART_ON.items()}
        dom = {k: 0 for k in PART_ON}
        for r in withp:
            vals = {k: num(r["parts"].get(k)) or 0 for k in PART_ON}
            k = max(vals, key=lambda x: vals[x])
            if vals[k] > 0:
                dom[k] += 1
        reasons = {}
        for r in withp:
            for t in r["reasons"] or []:
                if isinstance(t, str):
                    reasons[t] = reasons.get(t, 0) + 1
        out["contribution"] = {"hits": len(withp), "on": on, "dominant": dom, "reasons": reasons, "thresholds": dict(PART_ON)}
    else:
        out["contribution"] = None
    out["lengths"] = dist([r["length"] for r in results])
    buckets = (("short", "%d秒未満" % FRIEND_SHORT, lambda x: x < FRIEND_SHORT), ("mid", "%d〜%d秒" % (FRIEND_SHORT, FRIEND_LONG), lambda x: FRIEND_SHORT <= x < FRIEND_LONG),
               ("long", "%d秒以上" % FRIEND_LONG, lambda x: x >= FRIEND_LONG))
    by_len = {}
    for key, label, f in buckets:
        a = [r for r in an if f(r["length"])]
        h = sum(1 for r in a if r["hit"])
        by_len[key] = {"label": label, "ranges": sum(1 for r in results if f(r["length"])), "analyzedRanges": len(a), "hit": h, "hitRate": rate(h, len(a))}
    out["byLength"] = by_len
    short = [r for r in hit if r["length"] < FRIEND_LONG]
    out["edges"] = {"ranges": len(short), "dStart": dist([abs(r["dStart"]) for r in short]), "dEnd": dist([abs(r["dEnd"]) for r in short]),
                    "dStartSigned": dist([r["dStart"] for r in short]), "dEndSigned": dist([r["dEnd"] for r in short])}
    return out


def friend_ranges(studio, app, vmap, since_ms=None, until_ms=None, dvideos=None, records=None, archive=None):
    """-> friendRanges(結果の新しいまとまり)。vmap = build_videos(日付で絞らない)の結果(自動の候補を引く)。
    dvideos・records・archive は build_videos・load_runs と同じ(読んであれば渡す)"""
    dvideos = studio_videos(studio) if dvideos is None else dvideos
    archive = archive or archive_reader(studio)
    per = collect_friend_ranges(load_friend_runs(app, records), dvideos, since_ms, until_ms)
    results, by_video = [], []
    for vid, rgs in per.items():
        dv = dvideos.get(vid) if isinstance(dvideos.get(vid), dict) else {}
        V = vmap.get(vid)
        cands = ranked(V["auto"]) if V else []
        arch = archive(vid)
        an = dv.get("analysis") if isinstance(dv.get("analysis"), dict) else {}
        analyzed = bool(an) or arch is not None or bool(cands)
        typ = an.get("type") or (arch or {}).get("type") or (V or {}).get("type") or "不明"
        rs = [judge_friend_range(r, cands, analyzed) for r in sorted(rgs, key=lambda x: (x["start"], x["end"]))]
        results += rs
        g = friend_group(rs)
        ts = [r["t"] for r in rgs if r.get("t") is not None]
        g.update(videoId=vid, title=str(dv.get("title") or "")[:80], type=typ, analyzed=analyzed, candidates=len(cands),
                 latest=max(ts) if ts else None,   # 区間のいちばん新しい時刻(ms。--analyze-missing が新しい順に並べる)
                 items=[{k: r[k] for k in ("source", "start", "end", "length", "hit", "rank", "score", "hits", "dStart", "dEnd", "nearDistance", "nearScore", "nearRank")} for r in rs])
        by_video.append(g)
    overall = friend_group(results)
    few = overall["analyzedRanges"] < FRIEND_FEW_RANGES or overall["analyzedVideos"] < FRIEND_FEW_VIDEOS
    notes = []
    if overall["unanalyzedRanges"]:
        notes.append("解析していない配信の区間 %d 個(配信 %d 本)は「未解析」として別に数えました(自動の候補が無いので、見逃しには入れていません)。"
                     "依頼のあとの解析が済むと比べられます" % (overall["unanalyzedRanges"], overall["unanalyzedVideos"]))
    if overall["sources"]["marks"]:
        notes.append("区間のうち %d 個は実行の記録に区間が無い以前の依頼で、スタジオのマーク(adoptedBy が request の手動マーク)から前後 %g 秒の余白を引いて戻しました。"
                     "人がそのマークの状態を変えると印が外れるので、取りこぼしがあります" % (overall["sources"]["marks"], FRIEND_PAD))
    return {"schema": "youtube-tools-friend-ranges/v1", "hitRule": {"midInside": True, "overlapOfCandidate": HIT_OVERLAP}, "few": few,
            "fewNote": "まだ少ない(参考): 解析済みの区間が %d 個・配信が %d 本(解析済みの区間 %d 個・配信 %d 本のどちらかがこれ未満)。これで既定値を決めない"
                       % (overall["analyzedRanges"], overall["analyzedVideos"], FRIEND_FEW_RANGES, FRIEND_FEW_VIDEOS) if few else "",
            "notes": notes, "overall": overall, "byVideo": by_video}


# ---------------------------------------------------------------- 人が選んだ区間の長さ(clipLength)と自動の長さの目安

def len_dist(values):
    """長さのそろい -> dist + p50(= median)"""
    d = dist(values)
    if d["n"]:
        d["p50"] = d["median"]
    return d


def clip_samples(videos, allv, friend):
    """人が選んだ区間の見本 -> [{"src": friend / manual / adjusted / kept, "videoId", "type", "start", "end", "length", "ratio"(山の位置の割合か None)}]
    videos = 日付で絞った build_videos / allv = 絞らない build_videos(自動の候補の山を引く)/ friend = friend_ranges の結果"""
    out = []

    def cands_of(vid):
        V = allv.get(vid)
        return (ranked(V["auto"]) if V else []), ((V or {}).get("pre") or DEFAULT_PRE)

    def add(src, vid, typ, s, e, own=None):
        cands, pre = cands_of(vid)
        out.append({"src": src, "videoId": vid, "type": typ, "start": s, "end": e, "length": round(e - s, 2), "ratio": peak_ratio(s, e, cands, pre, own)})

    for v in friend["byVideo"]:
        for it in v["items"]:
            add("friend", v["videoId"], v["type"], it["start"], it["end"])
    friend_by_vid = {v["videoId"]: v["items"] for v in friend["byVideo"]}
    for vid in sorted(videos):
        V = videos[vid]
        # 手で足したマーク(manual_add)。依頼のマーク(adoptedBy が request)・友人の区間と同じ区間は friend で数えているので、ここでは数えない
        req_ids = {m["markId"] for m in V["manual"] if m.get("adoptedBy") == "request" and m["markId"]}
        finals = {m["markId"]: m for m in V["manual"] if m["markId"]}
        frs = friend_by_vid.get(vid, [])
        for ad in V["adds"]:
            if ad["cancelled"] or ad["start"] is None or ad["end"] is None or (ad["markId"] and ad["markId"] in req_ids):
                continue
            s, e = ad["start"], ad["end"]
            fin = finals.get(ad["markId"]) if ad["markId"] else None
            if fin is not None:
                s, e = fin["start"], fin["end"]   # 残っているマークは、人が直したあとの区間
            if any(same((s, e), (f["start"], f["end"])) or same((s, e), (max(0.0, f["start"] - FRIEND_PAD), f["end"] + FRIEND_PAD)) for f in frs):
                continue
            if e > s:
                add("manual", vid, V["type"], s, e)
        # 自動マークを人が「良い」にしたもの: 端を 0.5 秒以上直した = adjusted(直したあとの長さ)/ 直さなかった = kept
        for it in V["auto"]:
            if it["verdict"] != "good" or it["dStart"] is None or it["dEnd"] is None or it["start"] is None or it["end"] is None or it["end"] <= it["start"]:
                continue
            edited = abs(it["dStart"]) >= EDIT_SEC or abs(it["dEnd"]) >= EDIT_SEC
            add("adjusted" if edited else "kept", vid, V["type"], it["start"], it["end"], it)
    return out


def peak_of(it, pre):
    """候補の山の時刻(秒)。項目 peak があればそれ。無ければ最初の自動区間 auto0 に preRatio を当てて戻す(開始 = 山 − 長さ × preRatio)"""
    p = num(it.get("peak"))
    if p is not None:
        return p
    a = it["a0"]
    return a[0] + (a[1] - a[0]) * pre


def peak_ratio(s, e, cands, pre, own=None):
    """区間 (s, e) の中にある自動の候補の山(点数の高いものを優先。own があればそれを先に)の位置 = (山 − 開始) ÷ 長さ。無ければ None"""
    if e <= s:
        return None
    for it in ([own] if own is not None else []) + cands:
        p = peak_of(it, pre)
        if s <= p <= e:
            return round((p - s) / (e - s), 4)
    return None


def read_analyze_settings(studio):
    """スタジオの保存した解析の設定(settings-ui.json の analyze)-> {"length", "preRatio"} か None(読めない・数でない)。読むだけ"""
    d = read_json(os.path.join(studio, "settings-ui.json"), {})
    a = d.get("analyze") if isinstance(d, dict) else None
    if not isinstance(a, dict):
        return None
    length, pre = num(a.get("length")), num(a.get("preRatio"))
    if length is None or pre is None:
        return None
    return {"length": length, "preRatio": pre}


def clip_suggest(samples, kept_n, current):
    """見本(friend・manual・adjusted。外れ値を除いたもの)-> 目安 suggest。kept は「今の設定のまま」の票なので中央値に入れず、数だけ添える"""
    lens = [s["length"] for s in samples]
    ratios = [s["ratio"] for s in samples if s["ratio"] is not None]
    vids = {s["videoId"] for s in samples}
    ld = dist(lens)
    length = int(round(min(CL_LENGTH_MAX, max(CL_LENGTH_MIN, ld["median"])))) if lens else None
    pre = round(min(CL_PRE_MAX, max(CL_PRE_MIN, dist(ratios)["median"])), 2) if len(ratios) >= CL_PRE_MIN_SAMPLES else None
    enough = len(samples) >= CL_ENOUGH_SAMPLES and len(vids) >= CL_ENOUGH_VIDEOS
    out = {"length": length, "preRatio": pre, "samples": len(samples), "videos": len(vids), "enough": enough,
           "p25": ld.get("p25"), "p75": ld.get("p75"), "kept": kept_n, "preSamples": len(ratios), "current": current, "note": ""}
    if not lens:
        out["note"] = "人が選んだ長さの見本がまだありません(友人の区間・手で足したマーク・端を直した自動マーク)"
        return out
    out["note"] = "%s見本 %d 個(配信 %d 本): 長さの中央値 %d 秒(四分位 %s〜%s)・山の位置: %s%s%s" % (
        "" if enough else "まだ少ない(参考): ", len(samples), len(vids), length, ld["p25"], ld["p75"],
        "山の前 %.2f" % pre if pre is not None else "見本が %d 個未満で出せない" % CL_PRE_MIN_SAMPLES,
        "。いまの設定: %g 秒・%g" % (current["length"], current["preRatio"]) if current else "。いまの設定は読めない",
        "。直さずに良いにした自動マーク %d 個は含めていない" % kept_n if kept_n else "")
    return out


def clip_length(studio, videos, allv, friend):
    """-> clipLength(結果の新しいまとまり)。作業データ・設定は読むだけ"""
    samples = clip_samples(videos, allv, friend)
    current = read_analyze_settings(studio)

    def ok(s):
        return CL_OUTLIER_MIN <= s["length"] <= CL_OUTLIER_MAX

    def block(lst):
        good = [s for s in lst if ok(s)]
        return {"n": len(good), "videos": len({s["videoId"] for s in good}), "outliers": len(lst) - len(good), "length": len_dist([s["length"] for s in good])}

    srcs = ("friend", "manual", "adjusted", "kept")
    used = [s for s in samples if s["src"] != "kept"]
    out = {"schema": "youtube-tools-clip-length/v1", "outlier": {"min": CL_OUTLIER_MIN, "max": CL_OUTLIER_MAX}, "editSec": EDIT_SEC,
           "samples": dict({k: block([s for s in samples if s["src"] == k]) for k in srcs}, all=block(samples), used=block(used)),
           "peakRatio": dict({k: dist([s["ratio"] for s in samples if s["src"] == k and ok(s)]) for k in srcs}, used=dist([s["ratio"] for s in used if ok(s)]))}
    kept_n = sum(1 for s in samples if s["src"] == "kept" and ok(s))
    out["suggest"] = clip_suggest([s for s in used if ok(s)], kept_n, current)
    by_type = {}
    for s in samples:
        by_type.setdefault(s["type"], []).append(s)
    out["byType"] = {}
    for typ, lst in sorted(by_type.items()):
        u = [s for s in lst if s["src"] != "kept" and ok(s)]
        out["byType"][typ] = {"samples": {k: block([s for s in lst if s["src"] == k])["n"] for k in srcs},
                              "suggest": clip_suggest(u, sum(1 for s in lst if s["src"] == "kept" and ok(s)), current)}
    return out


def evaluate(data_dir=None, since=None, until=None, status_fallback=False):
    """-> 結果の辞書(JSON にする形)。作業データは読むだけ"""
    env, studio, app = locate(data_dir)
    since_ms, until_ms = C.period(since, until)
    dvideos, feedback, records, archive = studio_videos(studio), load_feedback(studio), run_records(app), archive_reader(studio)   # 1 回だけ読む
    runs = load_runs(app, records)

    def build(s, u):
        return build_videos(studio, feedback, runs, env, s, u, status_fallback, dvideos=dvideos, archive=archive)
    videos, notes = build(since_ms, until_ms)
    vlist = [videos[k] for k in sorted(videos)]
    types = {}
    for V in vlist:
        types.setdefault(V["type"], []).append(V)
    overall = group_metrics(vlist)
    if runs[2]:
        notes.append("友人へ届けた実行のうち %d 件は、マークの ID が実行記録に無く「届けた」に数えていません" % runs[2])
    unrec, mach = overall["top"]["all"]["unrecorded"], overall["top"]["all"]["machine"]
    if unrec:
        notes.append("採用・書き出しの状態があるのに、判定の行も入口の実行記録も無いマークが %d 個あります(記録の前のものか、行が消えた)。--status-fallback で人の判定として数えます" % unrec)
    if mach:
        notes.append("まとめて実行の自動採用とみなして正に数えなかったマークが %d 個あります(自動採用はマークに印が残らないため、実行記録で近似)" % mach)
    few = overall["judgedVideos"] < FEW_VIDEOS
    studio_judged = {V["id"] for V in vlist if group_metrics([V])["judgedVideos"]}
    overall["judgedElsewhere"] = judged_elsewhere(app, studio_judged, since_ms, until_ms, records, folder_videos(dvideos))
    overall["judgedAll"] = overall["judgedElsewhere"]["all"]
    meta = {"schema": SCHEMA, "at": int(time.time() * 1000), "since": since, "until": until, "statusFallback": bool(status_fallback), "git": C.git_rev(),
            "studioDir": studio, "videos": len(vlist), "judgedVideos": overall["judgedVideos"], "judgedAll": overall["judgedAll"], "few": few,
            "fewNote": "まだ少ない(参考): 判定のある配信が %d 本(%d 本未満)。これで既定値を決めない" % (overall["judgedVideos"], FEW_VIDEOS) if few else "", "notes": notes}
    by_video = []
    for V in vlist:
        g = group_metrics([V])
        by_video.append(dict(g, videoId=V["id"], title=V["title"], type=V["type"]))
    # 友人が時刻で指定した区間: 自動の候補は日付で絞らない(絞るのは区間の時刻。時期の指定が無ければ上と同じなので作り直さない)
    allv = videos if since_ms is None and until_ms is None else build(None, None)[0]
    friend = friend_ranges(studio, app, allv, since_ms, until_ms, dvideos=dvideos, records=records, archive=archive)
    clip = clip_length(studio, videos, allv, friend)
    return {"meta": meta, "overall": overall, "byType": {k: group_metrics(v) for k, v in sorted(types.items())}, "byVideo": by_video, "friendRanges": friend, "clipLength": clip}


# ---------------------------------------------------------------- 配信ごと(線 D の D-12。--live)

LIVE_SCHEMA = "youtube-tools-marks-eval-live/v1"
LIVE_FEW = 5             # 録画がこれより少ないときは「まだ少ない(参考)」
LIVE_DIR = "live"
REPORTS_DIR = "reports"
LIVE_FEEDBACK = "live_feedback.jsonl"
FRIEND_FEEDBACK = "friend_feedback.jsonl"   # 入口の logs/ の友人の「要らない」(src/human/friend/friend_feedback.py の FEEDBACK_LOG)


def folder_videos(dvideos):
    """スタジオのマークの書き出し先のフォルダ(path の親。配信ごとのフォルダ)-> 配信の ID(大文字小文字・区切りをそろえた鍵)"""
    out = {}
    for vid, v in (dvideos or {}).items():
        for m in (v.get("marks") if isinstance(v, dict) else None) or []:
            p = m.get("path") if isinstance(m, dict) else None
            if isinstance(p, str) and p:
                out.setdefault(os.path.normcase(os.path.dirname(os.path.abspath(p))), vid)
    return out


def _friend_folder(r, run_src):
    """友人の返事の行の切り抜きのフォルダ(パックのフォルダの親か、実行記録の sourcePath の親)。分からなければ空"""
    for p in r.get("packs") or []:
        d = p.get("dir") if isinstance(p, dict) else None
        if isinstance(d, str) and d:
            return os.path.normcase(os.path.dirname(os.path.abspath(d)))
    src = run_src.get(r.get("runId"))
    return os.path.normcase(os.path.dirname(os.path.abspath(src))) if isinstance(src, str) and src else ""


def judged_elsewhere(app, studio_judged, since_ms=None, until_ms=None, records=None, folders=None):
    """C1 の入口(「採用の記録 配信 10 本」)に数える、スタジオの判定の外の人の判定(K2。10-08 決定 = 線 D の [採用][要らない]・友人の返事も数える)。
    線 D の録画 = live/live_feedback.jsonl の人の行(event deliver = 届けた = 良い・reject = 要らない = 悪い。自動の採用は数えない)を録画ごとに。
    友人の返事 = logs/friend_feedback.jsonl の行(友人の「要らない」)のある配信。行の videoId が空(自動で届けた切り抜き)なら、行の runId から
    入口の実行記録(autorun-runs.jsonl)の videoId をたどり、それも無ければ(ファイル 1 本ずつの全自動)切り抜きのフォルダ = 配信ごとのフォルダを
    スタジオのマークの書き出し先(folders = folder_videos)と突き合わせる。突き合わなければフォルダを 1 つの配信として数える。
    **採用率には混ぜない**(友人が採る基準は送る基準と別 = 10-08 ユーザー決定)。records = run_records(app) を読んであれば渡す。
    -> {"live": {"recordings", "good", "bad"}, "friend": {"videos", "rows", "unknown", "notInStudio"}, "all": スタジオの判定のある配信 + 線 D の録画 + ほかで数えていない友人の配信}"""
    live = {}
    for _, r in read_jsonl(os.path.join(app, LIVE_DIR, LIVE_FEEDBACK)):
        if r.get("human") is True and r.get("event") in ("deliver", "reject") and _live_period_ok(r.get("at"), since_ms, until_ms):
            g = live.setdefault((str(r.get("recorder") or ""), str(r.get("recording") or "")), {"good": 0, "bad": 0})
            g["good" if r.get("event") == "deliver" else "bad"] += 1
    recs = run_records(app) if records is None else records
    run_vid = {r.get("id"): r.get("videoId") for r in recs if isinstance(r.get("videoId"), str) and r.get("videoId")}
    run_src = {r.get("id"): r.get("sourcePath") for r in recs if isinstance(r.get("sourcePath"), str)}
    friend, unknown = {}, 0
    for _, r in read_jsonl(os.path.join(app, "logs", FRIEND_FEEDBACK)):
        at = r.get("at") if isinstance(r.get("at"), int) and not isinstance(r.get("at"), bool) else None
        if not C.in_period(at, since_ms, until_ms):
            continue
        vid = r.get("videoId") if isinstance(r.get("videoId"), str) and r.get("videoId") else run_vid.get(r.get("runId"))
        if not vid:
            folder = _friend_folder(r, run_src)
            vid = (folders or {}).get(folder) or (("folder:" + folder) if folder else "")
        if vid:
            friend[vid] = friend.get(vid, 0) + 1
        else:
            unknown += 1
    recordings = {rec for _rc, rec in live}
    extra = [v for v in friend if v not in studio_judged and v not in recordings]
    return {"live": {"recordings": len(live), "good": sum(g["good"] for g in live.values()), "bad": sum(g["bad"] for g in live.values())},
            "friend": {"videos": len(friend), "rows": sum(friend.values()) + unknown, "unknown": unknown, "notInStudio": len(extra)},
            "all": len(studio_judged) + len(live) + len(extra)}


def _live_period_ok(iso_at, since_ms, until_ms):
    """入口の記録の時刻(UTC の ISO。末尾 Z。src/flow/live_export.py の now_iso)が時期の中か(分からなければ入れる)"""
    t = None
    s = str(iso_at or "")
    if s.endswith("Z"):
        try:
            t = calendar.timegm(time.strptime(s[:19], "%Y-%m-%dT%H:%M:%S")) * 1000
        except (ValueError, OverflowError):
            t = None
    elif s:
        t = ts_ms(s)
    return C.in_period(t, since_ms, until_ms)


def _live_row(d):
    """配信ごとの記録 1 件(src/flow/live_report.py の形)-> 表の 1 行の土台"""
    s, dt, tx, ex, info = d.get("samples") or {}, d.get("detect") or {}, d.get("tx") or {}, d.get("exports") or {}, d.get("info") or {}
    return {"recorder": d.get("recorder"), "recording": d.get("recording"), "title": info.get("title") or "", "hours": info.get("hours"),
            "state": d.get("state"), "startedAt": d.get("startedAt"), "request": bool(d.get("request")),
            "peaks": {"frame": dt.get("frame", 0), "bench": dt.get("bench", 0), "dismissed": dt.get("dismissed", 0), "adopted": dt.get("adopted", 0),
                      "givenUp": dt.get("givenUp", 0), "gaps": dt.get("gaps"), "ended": dt.get("ended")},
            "adopt": {"auto": dt.get("adoptedAuto", 0), "manual": dt.get("adoptedManual", 0), "archive": 0, "good": 0, "bad": 0, "unjudged": None},
            "worker": {"behindMax": s.get("behindMax"), "lagMax": s.get("lagMax"), "memMaxMB": s.get("memMaxMB"), "restarts": s.get("restarts"),
                       "chatRestarts": s.get("chatRestarts"), "chat": s.get("chat")},
            "tx": {"ok": tx.get("ok", 0), "empty": tx.get("empty", 0), "error": tx.get("error", 0), "secMedian": tx.get("secMedian")},
            "exports": {"total": ex.get("total", 0), "failures": ex.get("failures", 0), "waitSecMedian": ex.get("waitSecMedian"), "waitSecMax": ex.get("waitSecMax"),
                        "byState": ex.get("byState") or {}},
            "disk": d.get("disk"), "compare": None}


def _live_empty(rc, rec):
    return _live_row({"recorder": rc, "recording": rec, "state": "feedback", "startedAt": None})


def evaluate_live(data_dir=None, since=None, until=None):
    """--live -> {"meta", "recordings": [...], "totals"}。作業データは読むだけ"""
    _env, studio, app = locate(data_dir)
    live_dir = os.path.join(app, LIVE_DIR)
    since_ms, until_ms = C.period(since, until)
    by, order = {}, []
    rdir = os.path.join(live_dir, REPORTS_DIR)
    names = sorted(n for n in os.listdir(rdir) if n.endswith(".json")) if os.path.isdir(rdir) else []
    for n in names:
        d = read_json(os.path.join(rdir, n))
        if not isinstance(d, dict) or d.get("v") != 1 or not d.get("recorder") or not d.get("recording"):
            continue
        if not _live_period_ok(d.get("startedAt"), since_ms, until_ms):
            continue
        key = "%s/%s" % (d["recorder"], d["recording"])
        by[key] = _live_row(d)
        order.append(key)
    auto_marks = {}   # key -> {スタジオのマーク or markId: origin}(自動の採用の行)
    for _raw, r in read_jsonl(os.path.join(live_dir, LIVE_FEEDBACK)):
        rc, rec = r.get("recorder"), r.get("recording")
        if not isinstance(rc, str) or not isinstance(rec, str):
            continue
        key = "%s/%s" % (rc, rec)
        if key not in by:
            if not _live_period_ok(r.get("at"), since_ms, until_ms):
                continue
            by[key] = _live_empty(rc, rec)
            order.append(key)
        row = by[key]
        ev, origin = r.get("event"), r.get("origin")
        mid = (r.get("studio") or {}).get("mark") if isinstance(r.get("studio"), dict) else None
        mid = mid or r.get("markId")
        marks = auto_marks.setdefault(key, {})
        if ev == "adopt":
            if origin == "archive":
                row["adopt"]["archive"] += 1
            if origin in ("auto", "archive") and mid:
                marks[mid] = origin
            if row["state"] == "feedback" and origin in ("auto", "manual"):   # 記録の無い録画は行から数える
                row["adopt"][origin] += 1
        elif ev in ("deliver", "reject") and r.get("human") is True and mid in marks:
            row["adopt"]["good" if ev == "deliver" else "bad"] += 1
        elif ev == "detect_compare":
            row["compare"] = {k: r.get(k) for k in ("archive", "hit", "ratio", "medianAbsDiff", "liveFrame", "liveBench", "liveUnmatched")}
    for row in by.values():
        a = row["adopt"]
        a["unjudged"] = max(0, a["auto"] + a["archive"] - a["good"] - a["bad"])
    recs = [by[k] for k in order]
    recs.sort(key=lambda x: x.get("startedAt") or "", reverse=True)
    totals = _live_totals(recs)
    few = len(recs) < LIVE_FEW
    meta = {"schema": LIVE_SCHEMA, "at": int(time.time() * 1000), "since": since, "until": until, "git": C.git_rev(), "appDir": app, "liveDir": live_dir,
            "recordings": len(recs), "few": few, "fewNote": "まだ少ない(参考): 録画が %d 本(%d 本未満)。これで数を決めない" % (len(recs), LIVE_FEW) if few else ""}
    return {"meta": meta, "recordings": recs, "totals": totals}


def _live_totals(recs):
    def s(path):
        out = 0
        for r in recs:
            v = r
            for k in path:
                v = v.get(k) if isinstance(v, dict) else None
            if num(v):
                out += v
        return out

    def mx(path):
        vals = []
        for r in recs:
            v = r
            for k in path:
                v = v.get(k) if isinstance(v, dict) else None
            if num(v):
                vals.append(v)
        return max(vals) if vals else None
    good, bad = s(("adopt", "good")), s(("adopt", "bad"))
    comp = [r["compare"] for r in recs if isinstance(r.get("compare"), dict)]
    arch, hit = sum(c.get("archive") or 0 for c in comp), sum(c.get("hit") or 0 for c in comp)
    waits = [r["exports"]["waitSecMedian"] for r in recs if num(r["exports"].get("waitSecMedian"))]
    return {"recordings": len(recs), "hours": round(s(("hours",)), 1), "peaks": s(("peaks", "frame")) + s(("peaks", "adopted")), "bench": s(("peaks", "bench")),
            "dismissed": s(("peaks", "dismissed")), "adoptAuto": s(("adopt", "auto")), "adoptManual": s(("adopt", "manual")), "adoptArchive": s(("adopt", "archive")),
            "good": good, "bad": bad, "unjudged": s(("adopt", "unjudged")), "adoptRate": rate(good, good + bad), "givenUp": s(("peaks", "givenUp")),
            "compare": {"recordings": len(comp), "archive": arch, "hit": hit, "ratio": rate(hit, arch),
                        "medianAbsDiff": dist([c["medianAbsDiff"] for c in comp if num(c.get("medianAbsDiff"))])["median"] if comp else None},
            "behindMax": mx(("worker", "behindMax")), "lagMax": mx(("worker", "lagMax")), "memMaxMB": mx(("worker", "memMaxMB")),
            "restarts": s(("worker", "restarts")), "chatRestarts": s(("worker", "chatRestarts")),
            "tx": {"ok": s(("tx", "ok")), "empty": s(("tx", "empty")), "error": s(("tx", "error"))},
            "exports": {"total": s(("exports", "total")), "failures": s(("exports", "failures")), "waitSecMedian": _mid(waits), "waitSecMax": mx(("exports", "waitSecMax"))}}


def _mid(xs):
    xs = sorted(x for x in xs if num(x))
    return xs[len(xs) // 2] if xs else None


def _v(x, fmt="%s"):
    return (fmt % x) if num(x) else "-"


def print_live(res):
    m, t = res["meta"], res["totals"]
    print("配信ごとの記録(%s)  録画 %d 本・%s 時間  入口: %s" % (C.period_label(m["since"], m["until"]), m["recordings"], _v(t["hours"]), m["liveDir"]))
    if m["fewNote"]:
        print("★ " + m["fewNote"])
    if not m["recordings"]:
        print("(記録がありません。リアルタイム切り抜きで配信を録画すると live/reports/ に貯まります)")
        return
    print("  候補 %d(控え %d・見送り %d)  採用 自動 %d・人 %d・アーカイブ %d  自動の判定 良い %d / 悪い %d(採用率 %s。未判定 %d)  諦め %d" % (
        t["peaks"], t["bench"], t["dismissed"], t["adoptAuto"], t["adoptManual"], t["adoptArchive"], t["good"], t["bad"], pct(t["adoptRate"]), t["unjudged"], t["givenUp"]))
    c = t["compare"]
    print("  配信中 vs アーカイブ(detect_compare %d 本): アーカイブの候補 %d のうち配信中にも出た %d(%s)。時刻の差の中央値 %s 秒" % (
        c["recordings"], c["archive"], c["hit"], pct(c["ratio"]), _v(c["medianAbsDiff"])))
    print("  ワーカー: 遅れ最大 %s 秒・lag 最大 %s・メモリ最大 %s MB・起動し直し %d・チャットの起動し直し %d" % (
        _v(t["behindMax"]), _v(t["lagMax"]), _v(t["memMaxMB"]), t["restarts"], t["chatRestarts"]))
    print("  配信中の文字起こし: 付いた %d・空 %d・失敗 %d    書き出し: %d 本(失敗 %d)。作ってから済むまで 中央値 %s 秒・最大 %s 秒" % (
        t["tx"]["ok"], t["tx"]["empty"], t["tx"]["error"], t["exports"]["total"], t["exports"]["failures"], _v(t["exports"]["waitSecMedian"]), _v(t["exports"]["waitSecMax"])))
    print("  [録画ごと]")
    for r in res["recordings"]:
        a, p, w, cp = r["adopt"], r["peaks"], r["worker"], r.get("compare")
        print("    %s %s時間 候補 %d(控 %d 送 %d)採用 自 %d 人 %d ア %d 判定 %d/%d 遅れ %s メモリ %s 文字 %d/%d 書出 %d(失 %d)%s%s %s" % (
            r["recording"], _v(r["hours"], "%.1f "), p["frame"] + p["adopted"], p["bench"], p["dismissed"], a["auto"], a["manual"], a["archive"], a["good"], a["bad"],
            _v(w["behindMax"]), _v(w["memMaxMB"]), r["tx"]["ok"], r["tx"]["ok"] + r["tx"]["empty"] + r["tx"]["error"], r["exports"]["total"], r["exports"]["failures"],
            " 重なり %s" % pct(cp.get("ratio")) if cp else "", "(依頼)" if r.get("request") else "", r["title"][:24]))


# ---------------------------------------------------------------- 表示・保存

def print_group(title, g):
    print("  [%s]  配信 %d 本(判定あり %d 本)" % (title, g["videos"], g["judgedVideos"]))
    print("    %-7s %5s %5s %5s %6s %6s %5s %5s %6s %5s %6s %5s" % ("上位", "件", "判定", "良い", "採用率", "(全体)", "自動", "書出", "書出率", "パック", "パック率", "届け"))
    for k, f in g["top"].items():
        print("    %-7s %5d %5d %5d %6s %6s %5d %5d %6s %5d %6s %5d" % (k, f["items"], f["judged"], f["good"], pct(f["adoptRate"]), pct(f["adoptRateAll"]), f["machine"],
                                                                f["exported"], pct(f["exportRate"]), f["packed"], pct(f["packRate"]), f["delivered"]))
    f = g["top"]["all"]
    if f["unjudged"] or f["unrecorded"]:
        print("    判定なし %d 個(分母に入れていない)・記録なし %d 個" % (f["unjudged"], f["unrecorded"]))
    m, e, r = g["misses"], g["edits"], g["retracts"]
    nd = m["nearDistance"]
    print("    手で足した(見逃し) %d 個 / 良い自動 %d 個 → 見逃しの割合 %s。近くの自動マーク: 距離の中央値 %s 秒・%d 秒以内 %d 個・遠いか無し %d 個"
          % (m["added"], m["goodAuto"], pct(m["missRate"]).strip(), nd.get("median", "-"), NEAR_SEC, m["near15s"], m["farOrNone"]))
    if e["items"]:
        print("    端のずれ(良い自動 %d 個): 開始 中央値 %s 秒・90%% %s 秒 / 終了 中央値 %s 秒・90%% %s 秒 / %.1f 秒以上直した %s"
              % (e["items"], e["dStart"].get("median"), e["dStart"].get("p90"), e["dEnd"].get("median"), e["dEnd"].get("p90"), EDIT_SEC, pct(e["editedRate"]).strip()))
    print("    採用の取り消し %d(候補に戻した %d・採用したものを削除 %d)" % (r["total"], r["unadopt"], r["deleteJudged"]))


def print_friend(fr):
    """友人が時刻で指定した区間の節"""
    o = fr["overall"]
    print("")
    print("友人が時刻で指定した区間(自動の候補を見ずに人が選んだ見どころ。当たり = 区間に重なる自動の候補がある)")
    if not o["ranges"]:
        print("  (まだありません。依頼に区間を付けた配信が貯まると測れます)")
        return
    if fr["fewNote"]:
        print("★ " + fr["fewNote"])
    print("  区間 %d 個(配信 %d 本)= 解析済み %d 個(配信 %d 本)・未解析 %d 個(配信 %d 本)。出どころ: 実行の記録 %d・マーク %d"
          % (o["ranges"], o["videos"], o["analyzedRanges"], o["analyzedVideos"], o["unanalyzedRanges"], o["unanalyzedVideos"], o["sources"]["runs"], o["sources"]["marks"]))
    if o["analyzedRanges"]:
        t = o["top"]
        print("  拾えた率(解析済みの区間に対して): 上位5 %s・上位10 %s・上位20 %s・全部 %s(%d / %d)"
              % (pct(t["top5"]["rate"]).strip(), pct(t["top10"]["rate"]).strip(), pct(t["top20"]["rate"]).strip(), pct(t["all"]["rate"]).strip(), o["hit"], o["analyzedRanges"]))
        br, bs = o["bestRank"], o["bestScore"]
        if br.get("n"):
            print("  当たった候補のいちばん上の順位: 中央値 %s・90%% %s・最悪 %s / 点数: 中央値 %s" % (br["median"], br["p90"], br["max"], bs.get("median", "-")))
        m = o["misses"]
        print("  見逃し %d 個(%s)。近くの候補: 区間の端からの距離の中央値 %s 秒・点数の中央値 %s・%d 秒以内 %d 個・遠いか候補なし %d 個"
              % (m["missed"], pct(o["missRate"]).strip(), m["nearDistance"].get("median", "-"), m["nearScore"].get("median", "-"), NEAR_SEC, m["near15s"], m["farOrNone"]))
        c = o["contribution"]
        if c:
            print("  点数の内訳(当たった候補 %d 個。効いた = 音声・チャット %.1f 以上 / コメント %.1f 以上): 音声 %d・チャット %d・コメント %d / いちばん大きい成分: 音声 %d・チャット %d・コメント %d"
                  % (c["hits"], PART_ON["audio"], PART_ON["comments"], c["on"]["audio"], c["on"]["chat"], c["on"]["comments"], c["dominant"]["audio"], c["dominant"]["chat"], c["dominant"]["comments"]))
        ln = o["lengths"]
        print("  区間の長さ: 中央値 %s 秒・90%% %s 秒 / 長さごとの拾えた率: %s" % (ln.get("median", "-"), ln.get("p90", "-"),
              "・".join("%s %s(%d / %d)" % (b["label"], pct(b["hitRate"]).strip(), b["hit"], b["analyzedRanges"]) for b in o["byLength"].values())))
        e = o["edges"]
        if e["ranges"]:
            print("  端のずれ(%d 秒未満で当たった %d 個。候補 − 区間): 開始 中央値 %s 秒・90%% %s 秒 / 終了 中央値 %s 秒・90%% %s 秒(絶対値)"
                  % (FRIEND_LONG, e["ranges"], e["dStart"].get("median"), e["dStart"].get("p90"), e["dEnd"].get("median"), e["dEnd"].get("p90")))
    print("  [配信ごと]")
    for v in fr["byVideo"]:
        if v["analyzed"]:
            print("    %s %-6s 区間 %d 個: 拾えた %d・見逃し %d(候補 %d 個)  %s" % (v["videoId"], v["type"], v["ranges"], v["hit"], v["miss"], v["candidates"], v["title"][:30]))
        else:
            print("    %s %-6s 区間 %d 個: 未解析  %s" % (v["videoId"], v["type"], v["ranges"], v["title"][:30]))
    for n in fr["notes"]:
        print("注意: " + n)


def print_clip_length(cl):
    """人が選んだ区間の長さと、自動の長さの目安の節"""
    print("")
    print("人が選んだ区間の長さ(自動の長さの目安。%g 秒未満・%g 秒超は外れ値で数に入れない)" % (CL_OUTLIER_MIN, CL_OUTLIER_MAX))
    names = (("friend", "友人の区間"), ("manual", "手で足した"), ("adjusted", "端を直した自動"), ("kept", "直さなかった自動(今の設定のまま)"), ("used", "目安に使う分(上の3つ)"))
    if not cl["samples"]["all"]["n"] and not cl["samples"]["all"]["outliers"]:
        print("  (見本がまだありません)")
    else:
        print("    %-26s %5s %5s %5s %7s %7s %7s %6s" % ("出どころ", "個", "配信", "外れ", "25%", "中央値", "75%", "山の位置"))
        for k, label in names:
            b = cl["samples"][k]
            d = b["length"]
            pr = cl["peakRatio"][k]
            print("    %-24s %5d %5d %5d %7s %7s %7s %6s" % (label, b["n"], b["videos"], b["outliers"], d.get("p25", "-"), d.get("p50", "-"), d.get("p75", "-"), pr.get("median", "-")))
    s = cl["suggest"]
    if s["enough"] is False and s["samples"]:
        print("★ まだ少ない(参考): 見本 %d 個・配信 %d 本(%d 個・%d 本以上で目安にする)" % (s["samples"], s["videos"], CL_ENOUGH_SAMPLES, CL_ENOUGH_VIDEOS))
    print("  目安: " + s["note"])
    for typ, t in cl["byType"].items():
        ts = t["suggest"]
        if ts["samples"]:
            print("    [%s] 長さ %s 秒・山の前 %s(見本 %d 個・配信 %d 本%s)" % (typ, ts["length"], ts["preRatio"] if ts["preRatio"] is not None else "-", ts["samples"], ts["videos"], "" if ts["enough"] else "・まだ少ない"))


def print_report(res):
    m = res["meta"]
    rng = C.period_label(m["since"], m["until"])
    print("盛り上がり検出の測定(%s)  配信 %d 本・判定のある配信 %d 本  スタジオ: %s" % (rng, m["videos"], m["judgedVideos"], m["studioDir"]))
    je = res["overall"].get("judgedElsewhere") or {}
    if je:
        print("C1 の入口に数える判定のある配信 %d 本 = スタジオ %d・線 D の録画 %d(届けた %d・要らない %d)・友人の返事だけの配信 %d(採用率には混ぜない)" % (
            je["all"], m["judgedVideos"], je["live"]["recordings"], je["live"]["good"], je["live"]["bad"], je["friend"]["notInStudio"]))
    if m["fewNote"]:
        print("★ " + m["fewNote"])
    if not m["videos"]:
        print("(データがありません。スタジオでマークを判定すると貯まります)")
        print_friend(res["friendRanges"])
        print_clip_length(res["clipLength"])
        return
    print_group("全体", res["overall"])
    for k, g in res["byType"].items():
        print_group("配信の種類: " + k, g)
    print("  [配信ごと(上位10件の採用率)]")
    for v in res["byVideo"]:
        f = v["top"]["top10"]
        print("    %s %-6s 採用率 %s(判定 %d / 件 %d)見逃し %d  %s" % (v["videoId"], v["type"], pct(f["adoptRate"]), f["judged"], f["items"], v["misses"]["added"], v["title"][:30]))
    for n in m["notes"]:
        print("注意: " + n)
    print_friend(res["friendRanges"])
    print_clip_length(res["clipLength"])


# ---------------------------------------------------------------- 未解析の友人の配信の解析をスタジオに頼む(--analyze-missing。RS4)

ANALYZE_LIMIT = 10       # 一度に頼む本数の既定(スタジオの解析のキューの上限 src/flow/batch.py の MAX_ACTIVE と同じ)
WAIT_POLL = 5.0          # --wait でキューを見る間隔(秒)
QUEUE_END = ("done", "error", "cancelled", "skipped")   # スタジオの解析のキューの終わった状態(src/flow/batch.py の FINISHED)
EXIT_NO_STUDIO = 2
SKIP_LABELS = {"analyzed": "解析済み", "missing": "スタジオに無い", "queued": "すでに順番待ち", "full": "キューが満杯", "limit": "--limit を超えた分",
               "kind": "解析しない種類(ライブの録画など)"}


def missing_videos(data_dir=None):
    """友人が区間を指定したのに解析していない配信(friendRanges の analyzed が False)-> [{"videoId", "title", "latest", "kind", "path"}]。
    区間の新しい順(時刻の無いものは最後)。kind・path はスタジオの data.json の値(動画ファイルの解析は元の場所を渡すため。読むだけ)"""
    res = evaluate(data_dir)
    dvideos = studio_videos(locate(data_dir)[1])
    out = []
    for v in sorted((v for v in res["friendRanges"]["byVideo"] if not v["analyzed"]), key=lambda v: -(v.get("latest") or 0)):
        dv = dvideos.get(v["videoId"]) if isinstance(dvideos.get(v["videoId"]), dict) else {}
        out.append({"videoId": v["videoId"], "title": v["title"], "latest": v.get("latest"), "kind": dv.get("kind"), "path": dv.get("path")})
    return out


def _queue_item(v, video):
    """スタジオの /api/queue/add に渡す 1 件(src/flow/run.py の _step_analyze と同じ形)。解析しない種類は None"""
    kind = video.get("kind") or v.get("kind") or "youtube"
    if kind == "youtube":
        return {"kind": "youtube", "videoId": v["videoId"]}
    if kind == "file" and isinstance(v.get("path"), str) and v["path"]:
        return {"kind": "file", "path": v["path"]}
    return None


def analyze_missing(data_dir=None, limit=ANALYZE_LIMIT, wait=False, ep=None, poll=WAIT_POLL, sleep=time.sleep, out=print):
    """未解析の友人の配信の解析を、動いているスタジオに頼む(書くのはスタジオ。この道具は作業データを読むだけ)。
    解析の設定はスタジオの画面で保存したもの(/api/settings の settings.analyze)だけ(友人の重み・友人の区間の長さは使わない =
    消した「あとから解析」と同じ条件)。-> (終了コード, {"added", "skipped", "failed", "results"})。スタジオが動いていなければ終了コード 2"""
    ep = ep or API.find_studio()
    if not ep:
        out("スタジオが動いていません。ホームを起動してから(start.bat)、もう一度実行してください")
        return EXIT_NO_STUDIO, None
    res = {"added": [], "skipped": [], "failed": [], "results": []}
    todo = missing_videos(data_dir)
    if not todo:
        out("未解析の友人の配信はありません")
        return 0, res
    try:
        st, obj = API.call(ep, "GET", "api/settings")
    except API.StudioError as e:
        out(str(e))
        return EXIT_NO_STUDIO, None
    saved = (obj.get("settings") or {}).get("analyze") if st == 200 and isinstance(obj.get("settings"), dict) else None
    saved = saved if isinstance(saved, dict) else {}
    for i, v in enumerate(todo):
        def skip(why, v=v):
            res["skipped"].append(dict(v, reason=why))
        if len(res["added"]) >= limit:
            skip("limit")
            continue
        try:
            st, obj = API.call(ep, "GET", "api/video?id=" + urllib.parse.quote(v["videoId"], safe=""))
            if st == 404:
                skip("missing")
                continue
            if st != 200:
                res["failed"].append(dict(v, reason=obj.get("message") or "HTTP %s" % st))
                continue
            video = obj.get("video") if isinstance(obj.get("video"), dict) else {}
            if video.get("analysis"):
                skip("analyzed")
                continue
            item = _queue_item(v, video)
            if item is None:
                skip("kind")
                continue
            st, obj = API.call(ep, "POST", "api/queue/add", {"items": [item], "settings": saved})
        except API.StudioError as e:
            res["failed"].append(dict(v, reason=str(e)))
            break
        added = obj.get("added") if st == 200 and isinstance(obj.get("added"), list) else []
        if added and isinstance(added[0], dict) and added[0].get("qid"):
            res["added"].append(dict(v, qid=added[0]["qid"]))
            continue
        rej = obj.get("rejected") if isinstance(obj.get("rejected"), list) and obj.get("rejected") else [{}]
        why = str((rej[0] if isinstance(rej[0], dict) else {}).get("reason") or obj.get("message") or ("HTTP %s" % st if st != 200 else "理由不明"))
        if "一度に入れられる" in why:   # キューが満杯(FULL_MSG): 残りも入らないので、ここで止める
            for w in todo[i:]:
                res["skipped"].append(dict(w, reason="full"))
            break
        if "すでに解析の順番待ち" in why:   # DUP_MSG
            skip("queued")
            continue
        res["failed"].append(dict(v, reason=why))
    print_analyze_missing(res, out)
    if wait and res["added"]:
        res["results"] = wait_queue(ep, res["added"], poll, sleep, out)
    return (1 if res["failed"] else 0), res


def wait_queue(ep, added, poll=WAIT_POLL, sleep=time.sleep, out=print):
    """入れた解析が終わるまでキュー(/api/queue)を見る -> [{"videoId", "qid", "status", "marks", "error"}]"""
    left = {a["qid"]: a for a in added}
    results = []
    out("解析が終わるのを待ちます(%g 秒ごとに見ます。Ctrl+C で待つのをやめても解析は続きます)" % poll)
    while left:
        try:
            st, obj = API.call(ep, "GET", "api/queue")
        except API.StudioError as e:
            out(str(e))
            break
        items = obj.get("items") if st == 200 and isinstance(obj.get("items"), list) else []
        by_q = {it.get("qid"): it for it in items if isinstance(it, dict)}
        for qid in list(left):
            it = by_q.get(qid)
            if it is None or it.get("status") in QUEUE_END:
                a = left.pop(qid)
                r = {"videoId": a["videoId"], "qid": qid, "status": it.get("status") if it else "gone",
                     "marks": it.get("marks") if it else None, "error": (it.get("error") if it else "") or ""}
                results.append(r)
                out("  %s %s%s" % (a["videoId"], {"done": "解析しました(候補 %s 件)" % r["marks"], "gone": "キューから消えました(スタジオで取り消したかもしれません)"}.get(
                    r["status"], r["status"]), ": " + r["error"] if r["error"] else ""))
        if left:
            sleep(poll)
    done = sum(1 for r in results if r["status"] == "done")
    out("待ち終わり: 解析した %d 本・終わらなかった %d 本" % (done, len(results) - done))
    return results


def print_analyze_missing(res, out=print):
    out("未解析の友人の配信: 解析を頼んだ %d 本・飛ばした %d 本・失敗 %d 本" % (len(res["added"]), len(res["skipped"]), len(res["failed"])))
    for a in res["added"]:
        out("  入れた   %s %s" % (a["videoId"], a["title"][:40]))
    counts = {}
    for s in res["skipped"]:
        counts[s["reason"]] = counts.get(s["reason"], 0) + 1
    for k, n in counts.items():
        out("  飛ばした %s %d 本" % (SKIP_LABELS.get(k, k), n))
    for f in res["failed"]:
        out("  失敗     %s %s" % (f["videoId"], f["reason"][:200]))
    if res["added"]:
        out("解析が済んだら、もう一度この道具(--analyze-missing なし)で友人の区間と自動の候補を比べられます")


def main(argv=None):
    p = argparse.ArgumentParser(description="盛り上がり検出の当たり具合を人の判定の記録で測る(作業データは読むだけ)")
    C.add_period_args(p, "この日(YYYY-MM-DD)以後のものだけ", "この日(YYYY-MM-DD。この日を含む)までのものだけ",
                      "同じ形の JSON を スタジオの作業データの evals/marks/<日時>.json に残す")
    p.add_argument("--status-fallback", action="store_true", help="行も実行記録も無い採用・書き出しの状態を、人の判定として数える")
    p.add_argument("--live", action="store_true", help="配信ごとの記録(入口の live/reports/ と live_feedback.jsonl。線 D の D-12)を並べる")
    p.add_argument("--analyze-missing", action="store_true",
                   help="友人が区間を指定したのに解析していない配信の解析を、動いているスタジオに頼む(書くのはスタジオ。ホームを起動しておく)")
    p.add_argument("--wait", action="store_true", help="--analyze-missing で頼んだ解析が終わるまで待って結果を出す")
    p.add_argument("--limit", type=int, default=ANALYZE_LIMIT, help="--analyze-missing で一度に頼む本数(既定 %d = スタジオの解析のキューの上限)" % ANALYZE_LIMIT)
    args = p.parse_args(argv)
    if args.analyze_missing:
        code, res = analyze_missing(args.data_dir, max(1, args.limit), args.wait)
        if code:
            sys.exit(code)
        return res
    if args.live:
        res = evaluate_live(args.data_dir, args.since, args.until)
        print_live(res)
        C.report_saved(res, args.json, locate(args.data_dir)[1], "marks", "-live")
        return res
    res = evaluate(args.data_dir, args.since, args.until, args.status_fallback)
    print_report(res)
    C.report_saved(res, args.json, res["meta"]["studioDir"], "marks")
    return res


if __name__ == "__main__":
    C.utf8_stdout()
    main()
