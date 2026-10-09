#!/usr/bin/env python3
"""話者の判別(と覚えた声の照合)の当たり具合を、人が直した最終で測る道具(線 B の話者の評価。plan/line-bc-master-plan.md の Q3・I-2a)。

    python dev/eval_speakers.py [stored] [--since YYYY-MM-DD] [--until YYYY-MM-DD] [--json] [--data-dir 作業データの親フォルダ] [--no-eval] [--include-draft]
                                [--reviewed only|prefer|ignore] [--docs id,…]
        保存してある判別の記録(<id>.diar.json)を人の最終と比べる(既定。引数なしはこれ)
    py -3.10 dev/eval_speakers.py run --threshold 0.5,0.6,0.7 [--num auto,2] [--emb voxceleb] [--min-on 0.1] [--min-off 0.3] [--docs id,…] [--reviewed …] [--json]
        文書の音声をもう一度判別して(設定の組ごと)人の最終と比べる。本番と同じ道(音声の取り出し extract_audio → diarize_real → assign_speakers)。
        判別はこの道具のプロセスの中で動かす(eval_asr.py の run と同じ。サーバーではないので sherpa-onnx を読んでよい。認識ワーカーは起動しない)。
        モデルは作業データの models/diar のもの(無ければ取得せずに止める)。文書・diar.json は書かない(--json のときだけ evals/speakers/<日時>-run.json)。
        元の動画が無ければ保管データの full.flac(eval_asr.py と同じ)。TRANSCRIBE_BACKEND=fake なら疑似の判別(テスト用)
    --smooth off,on(stored・run のどちらでも): 話者の細切れをならす(S2。src/editor/ed_speakers.py の smooth_labels・smooth_speakers。本番と同じ関数を読む)を、
        ならさない/ならすで比べる。stored は保存してある判別の記録(rows の label・ratio・overlaps)と文書の今の行の時刻で「ならしたら」を計算するだけ(判別し直さない)。
        run は 1 回の判別の結果を両方で採点する。行の正しさ・ならした行の数・ならした行のうち人が確かめた行で合った/外れた数・直った/壊れた数(ならさないと比べて)

- 作業データは**読むだけ**(transcribe の transcripts/<id>.json と <id>.diar.json)。何も書き換えない。--json のときだけ、結果を
  文字起こしの作業データの evals/speakers/<日時>.json に残す(evals の置き場所は eval_asr.py(evals/asr)・eval_marks.py と同じ「ツールの作業データの下の evals/<領域>」)。
- 人の最終 = 文書の行の speaker(id)→ speakers[].name。機械 = <id>.diar.json の latest(rows[行 id].speaker = その回の S1/S2…・voices = 声の照合)。
  行 id で突き合わせる(人が分けた・つないだ行は新しい id で、機械の記録が無い = 「記録なし」として別に数える)。
- --reviewed(評価用の「確かめ済み」= evalSet が True かつ evalReviewed が dict。src/editor/ed_drill.py の drill_is_reviewed と同じ条件。editor は読み込まない):
    only = 評価用は確かめ済みの文書だけ(既定。--docs のときは prefer。確かめ済みが 0 本なら今までの選び方に戻して注意)/
    prefer = 確かめ済みでない評価用も混ぜる / ignore = 印を見ない。評価用でない文書は、どれでも今までどおり入る
- **人が確かめた行だけを測る**(行ごとに決める。記録から確実に言える範囲。--include-draft で今までどおり全部を入れる = 甘く出る):
    人が確かめた = 確かめ済みの文書の行 / 校正済み(proofed)の行 / 人が話者を付け替えた行(行の speaker が判別の記録の rows[行 id].speaker と違う)
    機械の下書きのまま(数えない)= それ以外の行で、その話者の名前が機械のもの(仮の名前 話者n か、声の照合 voices の decided と同じで by が threshold・elimination・context)、
      かつその話者に人が確かめた行が 1 つも無い
    確かめられない(数えない・別に数える)= それ以外(人が名前を付けた・ほかの行を確かめた話者の、確かめていない行。話者を見たかは記録から言えない)
  仮の名前(話者1・話者2…)のままの行は今までどおり既定で測らない(人が確かめた行でも)。「校正済みの行だけ」の数も並べて見る
- **字幕に出さない行は測らない**(行の印 noSub: true、または組み込みの話者「ゲーム音声など」の行。ゲームのキャラ・NPC の声など = その場かぎりの声で、
  話者判別の当たり外れではなく人の判断。組み込みの話者の id・名前(ed_state.OTHER_SPK_ID・OTHER_SPK_NAME と同じ値)と行の noSub で判定する)。行の話者の正しさ・声の照合・重なりの見つけ方のどれにも入れず、
  行の数だけ meta.noSubRows に別に出す(人が時刻を直した行・話者の数の数え方にも入らない = 測る行の集まりから外す)
- 重なりの見つけ方: 機械の「声が混ざっている」(diar.json の rows[].mixed)と、話者の区間が重なる所(overlaps と行が OVL_MIN_SEC 以上重なる)を、
  人の音のメモ overlap(行の tags)と比べる(適合率・再現率)。行 = 確かめ済みの文書の行か校正済みの行(文字のある・機械の記録がある行)
- 指標(行の集まり = 話者つきの行 / 校正済みの行だけ / 人が時刻を直した行だけ。どれも同じ書き方で数える):
    行ごとの正しさ: 文書ごとに、機械のラベル(S1/S2…)と人の名前を1対1で最もよく対応させる(ハンガリア法。行数で重み。分けすぎた話者は対応できず間違いになる)→
      合っている行 ÷ 行(人が話者を付けていない行は入れない。機械が付けなかった行は間違いに数え、数も別に出す)。声が混ざっている(mixed)行・不確か(weak)行・それ以外で別に出す
    声の照合: decided(しきい値か消去法で付いた名前)が、その機械の話者の行に人が付けた名前(多い方)と同じ割合 / 付けなかった話者の理由の内訳 /
      正しかった名前・間違った名前の点数と2位との差の分布 / 付けなかったが、1位が人の名前だった(しきい値で取りこぼした)数 /
      しきい値(点数・差)を変えたら決まる数・正しい数がどう変わるかの表(記録された点数と差からの計算。VOICE_MATCH 0.60・VOICE_MARGIN 0.08 の見直しの材料)
    話者の数: 機械の数 − 人の数(文書ごと)の分布と、ちょうど当たった割合
    判別の回(履歴を含む)ごとの行の正しさ: エンジン・埋め込み・クラスタのしきい値ごとにまとめる(設定を変えた前後の比較)
- 人が時刻を直した行 = original(機械の出力。行の id が無いので時刻で突き合わせる)のどの行とも、始まりと終わりが 0.05 秒以内で一致しない行。
  行を分けた・つないだ行も入る。original が無い文書の行は分からないので入れない
- --since / --until(原則 4: 時期で分ける)は行の時刻で絞る(until はその日を含む)。行の時刻 = 校正した時刻 proofedAt(あれば)、無ければ文書の更新時刻 updatedAt
  (proofedAt を作る前に校正済みになった行は時刻が無いので更新時刻になる)。
- 話者つきの行が 200 未満のときは「まだ少ない(参考)」と出す(少ないデータで決めすぎない)。評価用(evalSet)の文書は既定で含める(--no-eval で外す)
"""
import argparse
import bisect
import os
import re
import shutil
import sys
import tempfile
import time
import unicodedata

HERE = os.path.dirname(os.path.abspath(__file__))
if HERE not in sys.path:
    sys.path.insert(0, HERE)
import _evalcommon as C  # noqa: E402  共通の部品(作業データの場所・時期・率・分布・git の rev・保存・editor の読み込み。src を sys.path に足す)
from _evalcommon import dist, is_reviewed, pct, rate, read_json  # noqa: E402
from ytt import fsio  # noqa: E402

SCHEMA = "youtube-tools-speakers-eval/v1"
DIAR_SCHEMA = "youtube-tools-diar/v1"     # src/editor/ed_speakers.py の DIAR_SCHEMA と同じ(editor は読み込まない)
FEW_ROWS = 200                            # 話者つきの行がこれより少ないときは「まだ少ない(参考)」
TIME_TOL = 0.05                           # original と行の端が一致したとみなす秒
MAX_DIAR_BYTES = 32 * 1024 * 1024
OTHER_VOICE_NAME = "ゲーム音声など"        # 組み込みの話者の名前(src/editor/ed_state.py の OTHER_SPK_NAME と同じ)
OTHER_VOICE_ID = "other"                   # 組み込みの話者の id(ed_state.OTHER_SPK_ID と同じ。名前より id で見分けるのが確実)
DRAFT_NAME = re.compile(r"^話者\d+$")     # src/editor/ed_speakers.py の DEFAULT_SPK_NAME(話者判別が付けた仮の名前)と同じ
DOC_RE = re.compile(r"^[0-9a-f]{12}\.json\Z")
SUBSETS = (("all", "話者つきの行"), ("proofed", "校正済みの行だけ"), ("timeEdited", "人が時刻を直した行だけ"))
SWEEP_MATCH = (0.40, 0.50, 0.55, 0.60, 0.65, 0.70, 0.75, 0.80)
SWEEP_MARGIN = (0.0, 0.04, 0.08, 0.12)
REASONS = {"no_feature": "特徴が取れない", "no_voices": "比べる声が無い", "below_match": "しきい値に届かない", "margin": "2位との差が足りない",
           "name_taken": "同じ名前を別の人が先に取った", "already_named": "人が先に名前を付けていた", "name_in_use": "その名前を別の人が使っている", "no_rows": "行が無い"}
REVIEWED_MODES = ("only", "prefer", "ignore")
MACHINE_BY = ("threshold", "elimination", "context")   # 声の照合 voices の by のうち、機械が付けた名前(request = 依頼の名前は人の入力)
CONFIRM_RULE = ("人が確かめた行 = 確かめ済みの文書の行・校正済みの行・人が話者を付け替えた行。機械の下書きのまま = それ以外で、名前が機械のもの(話者n・声の照合・動画の手がかり)"
                "かつその話者に確かめた行が無い。確かめられない = それ以外")
OVL_MIN_SEC = 0.1                         # 行と話者の区間の重なり(overlaps)がこれ以上なら「重なりあり」とみなす
OVL_PREDICTORS = (("mixed", "声が混ざる(mixed)"), ("region", "区間の重なり(overlaps)"), ("either", "どちらか"))
SMOOTH_MODES = {"off": False, "on": True}  # --smooth の値(話者の細切れをならす。S2)
SHORT_SEC = 60.0                          # run の動画の長さ別(これ未満 = 短い)
LENGTHS = (("short", "60秒未満"), ("long", "60秒以上"))


# ---------------------------------------------------------------- 読み込み(読むだけ)

def read_diar(tdir, tid):
    d = read_json(os.path.join(tdir, tid + ".diar.json"), None, MAX_DIAR_BYTES)
    if not isinstance(d, dict) or d.get("schema") != DIAR_SCHEMA or not isinstance(d.get("latest"), dict):
        return None
    return d


# ---------------------------------------------------------------- 日時・数の小道具

def num(x):
    return x if isinstance(x, (int, float)) and not isinstance(x, bool) else None


def norm_name(s):
    return unicodedata.normalize("NFKC", str(s or "")).strip().casefold()


def hungarian_max(w):
    """重みの表 w(行 × 列)を、1行に1列まで・1列に1行までで、合計がいちばん大きくなるように対応させる -> {行: 列}(重み 0 の対応は除く)"""
    n_r = len(w)
    n_c = len(w[0]) if w else 0
    n = max(n_r, n_c)
    if not n:
        return {}
    cost = [[0] * (n + 1) for _ in range(n + 1)]
    for i in range(n_r):
        for j in range(n_c):
            cost[i + 1][j + 1] = -w[i][j]
    INF = float("inf")
    u, v, p, way = [0] * (n + 1), [0] * (n + 1), [0] * (n + 1), [0] * (n + 1)
    for i in range(1, n + 1):
        p[0] = i
        j0 = 0
        minv = [INF] * (n + 1)
        used = [False] * (n + 1)
        while True:
            used[j0] = True
            i0, delta, j1 = p[j0], INF, 0
            for j in range(1, n + 1):
                if not used[j]:
                    cur = cost[i0][j] - u[i0] - v[j]
                    if cur < minv[j]:
                        minv[j], way[j] = cur, j0
                    if minv[j] < delta:
                        delta, j1 = minv[j], j
            for j in range(n + 1):
                if used[j]:
                    u[p[j]] += delta
                    v[j] -= delta
                else:
                    minv[j] -= delta
            j0 = j1
            if p[j0] == 0:
                break
        while True:
            j1 = way[j0]
            p[j0] = p[j1]
            j0 = j1
            if not j0:
                break
    out = {}
    for j in range(1, n + 1):
        i = p[j] - 1
        if 0 <= i < n_r and j - 1 < n_c and w[i][j - 1] > 0:
            out[i] = j - 1
    return out


def best_mapping(rows):
    """rows の (機械のラベル, 人の名前) の組を数えて、ラベル → 名前の1対1の対応(合う行が最大になるもの)を返す。機械のラベルが空の行は数えない"""
    cnt = {}
    for r in rows:
        if r["label"]:
            cnt[(r["label"], r["human"])] = cnt.get((r["label"], r["human"]), 0) + 1
    labels = sorted({k[0] for k in cnt})
    names = sorted({k[1] for k in cnt})
    pairs = hungarian_max([[cnt.get((lb, nm), 0) for nm in names] for lb in labels])
    return {labels[i]: names[j] for i, j in pairs.items()}


# ---------------------------------------------------------------- 1つの文書

def time_edited_flags(doc, rows):
    """行ごとに「人が時刻を直した」か。original が無ければ None(分からない)"""
    orig = sorted((num(o.get("start")), num(o.get("end"))) for o in (doc.get("original") or []) if isinstance(o, dict)
                  and num(o.get("start")) is not None and num(o.get("end")) is not None)
    if not orig:
        return [None] * len(rows)
    starts = [o[0] for o in orig]
    out = []
    for r in rows:
        a, b = r["start"], r["end"]
        k = bisect.bisect_left(starts, a - TIME_TOL)
        same = False
        while k < len(orig) and orig[k][0] <= a + TIME_TOL:
            if abs(orig[k][1] - b) <= TIME_TOL:
                same = True
                break
            k += 1
        out.append(not same)
    return out


def is_other_row(sg, names):
    """字幕に出さない行か(noSub: true、または話者の名前が組み込みの「ゲーム音声など」)。names = 話者 id → 名前"""
    return sg.get("noSub") is True or sg.get("speaker") == OTHER_VOICE_ID or (bool(sg.get("speaker")) and str(names.get(sg.get("speaker")) or "") == OTHER_VOICE_NAME)


def in_period(sg, doc_t, since_ms, until_ms):
    return C.in_period(num(sg.get("proofedAt")) or doc_t, since_ms, until_ms)


def confirm_map(doc, run, whole):
    """行 id(文字列)-> "human"(人が確かめた)/ "draft"(機械の下書きのまま)/ "unknown"(確かめられない)。決め方は CONFIRM_RULE(docstring の先頭)。
    run = 保存してある判別の記録の最新(無ければ None = 機械が付けた名前も行も分からない → 名前は人のもの扱い)。whole = 確かめ済みの文書として扱うか"""
    segs = [sg for sg in doc.get("segments") or [] if isinstance(sg, dict)]
    if whole:
        return {str(sg.get("id")): "human" for sg in segs}
    names = {s.get("id"): str(s.get("name") or "") for s in doc.get("speakers") or [] if isinstance(s, dict)}
    run = run if isinstance(run, dict) else {}
    mrows = run.get("rows") if isinstance(run.get("rows"), dict) else {}
    vs = (run.get("voices") or {}).get("speakers") if isinstance(run.get("voices"), dict) else None
    vs = vs if isinstance(vs, dict) else {}

    def machine_named(sid):
        n = names.get(sid, "")
        if DRAFT_NAME.match(n):
            return True
        v = vs.get(sid)
        return bool(n) and isinstance(v, dict) and v.get("by") in MACHINE_BY and norm_name(v.get("decided")) == norm_name(n)
    out, touched = {}, set()
    for sg in segs:
        rec = mrows.get(str(sg.get("id")))
        changed = isinstance(rec, dict) and str(rec.get("speaker") or "") != str(sg.get("speaker") or "")
        if sg.get("proofed") is True or changed:
            out[str(sg.get("id"))] = "human"
            touched.add(sg.get("speaker"))
    touched |= {sid for sid in names if not machine_named(sid)}
    for sg in segs:
        out.setdefault(str(sg.get("id")), "unknown" if sg.get("speaker") in touched else "draft")
    return out


def human_rows(doc, runrows, since_ms, until_ms, include_draft, conf=None):
    """人の最終の話者がある行 -> ([{id, start, end, human, label, mixed, weak, proofed, edited}], 数)。
    数 = {"drafts": 仮の名前のままで除いた行, "noRecord": 機械の記録が無い行, "machineDraft": 機械の下書きのままで除いた行, "unverified": 確かめられないで除いた行,
          "noSub": 字幕に出さない行(あるときだけ入る。is_other_row)で除いた行}。
    runrows = 判別の記録の rows(行 id → {label, speaker, mixed, weak})。label は「機械がその回に付けた S1/S2…」(付けなかった行は空)。
    conf = confirm_map の結果(None なら確かめたかで分けない)。include_draft なら仮の名前・下書き・確かめられない行も入れる(今までの数え方)"""
    names = {s.get("id"): str(s.get("name") or "") for s in doc.get("speakers") or [] if isinstance(s, dict)}
    doc_t = num(doc.get("updatedAt")) or 0
    out, base = [], []
    cnt = {"drafts": 0, "noRecord": 0, "machineDraft": 0, "unverified": 0}
    for sg in doc.get("segments") or []:
        if not isinstance(sg, dict):
            continue
        name = names.get(sg.get("speaker")) if sg.get("speaker") else None
        a, b = num(sg.get("start")), num(sg.get("end"))
        if not name or a is None or b is None:
            continue
        if not in_period(sg, doc_t, since_ms, until_ms):
            continue
        if is_other_row(sg, names):   # 字幕に出さない行(ゲーム音声など)は、判別の当たり外れの数に入れない(include_draft でも)
            cnt["noSub"] = cnt.get("noSub", 0) + 1
            continue
        if DRAFT_NAME.match(name) and not include_draft:
            cnt["drafts"] += 1
            continue
        base.append((sg, name, a, b))
    edited = time_edited_flags(doc, [{"start": a, "end": b} for _, _, a, b in base])
    for (sg, name, a, b), ed in zip(base, edited):
        rec = runrows.get(str(sg.get("id")))
        if not isinstance(rec, dict):
            cnt["noRecord"] += 1
            continue
        c = conf.get(str(sg.get("id")), "unknown") if conf is not None else "human"
        if c != "human" and not include_draft:
            cnt["machineDraft" if c == "draft" else "unverified"] += 1
            continue
        out.append({"id": sg.get("id"), "start": a, "end": b, "human": name, "label": str(rec.get("speaker") or ""), "mixed": bool(rec.get("mixed")),
                    "weak": bool(rec.get("weak")), "proofed": sg.get("proofed") is True, "edited": ed})
    return out, cnt


def overlap_rows(doc, recs, overlaps, since_ms, until_ms, whole):
    """重なりの見つけ方を測る行(確かめ済みの文書の行か校正済みの行。文字があり、機械の記録がある行)->
    [{"human": 人の音のメモ overlap, "mixed": 機械の声が混ざる, "region": 話者の区間の重なりと OVL_MIN_SEC 以上重なる}]。recs = 行 id → {mixed}"""
    ov = sorted((num(x[0]), num(x[1])) for x in overlaps or [] if isinstance(x, (list, tuple)) and len(x) >= 2
                and num(x[0]) is not None and num(x[1]) is not None)
    doc_t = num(doc.get("updatedAt")) or 0
    names = {s.get("id"): str(s.get("name") or "") for s in doc.get("speakers") or [] if isinstance(s, dict)}
    out = []
    for sg in doc.get("segments") or []:
        if not isinstance(sg, dict) or not str(sg.get("text") or "").strip():
            continue
        if is_other_row(sg, names):
            continue   # 字幕に出さない行は、重なりの見つけ方の測定にも入れない
        if not (whole or sg.get("proofed") is True) or not in_period(sg, doc_t, since_ms, until_ms):
            continue
        rec = recs.get(str(sg.get("id")))
        a, b = num(sg.get("start")), num(sg.get("end"))
        if not isinstance(rec, dict) or a is None or b is None:
            continue
        hit = sum(max(0.0, min(b, y) - max(a, x)) for x, y in ov if x < b and y > a)
        tags = sg.get("tags") if isinstance(sg.get("tags"), list) else []
        out.append({"human": "overlap" in tags, "mixed": bool(rec.get("mixed")), "region": hit >= OVL_MIN_SEC})
    return out


class Overlap:
    """重なりの見つけ方の集計(機械の印ごとの適合率・再現率)"""

    def __init__(self):
        self.rows = self.human = 0
        self.c = {k: {"pred": 0, "tp": 0} for k, _ in OVL_PREDICTORS}

    def add(self, rows):
        for r in rows:
            self.rows += 1
            self.human += r["human"]
            for k, _ in OVL_PREDICTORS:
                p = (r["mixed"] or r["region"]) if k == "either" else r[k]
                if p:
                    self.c[k]["pred"] += 1
                    self.c[k]["tp"] += r["human"]

    def result(self):
        return {"rows": self.rows, "human": self.human,
                "byPredictor": {k: {"pred": v["pred"], "tp": v["tp"], "fp": v["pred"] - v["tp"], "fn": self.human - v["tp"],
                                    "precision": rate(v["tp"], v["pred"]), "recall": rate(v["tp"], self.human)} for k, v in self.c.items()}}


def new_counts():
    return {"rows": 0, "correct": 0, "unassigned": 0, "plain": [0, 0], "weak": [0, 0], "mixed": [0, 0]}


def add_counts(total, rows, mapping):
    """rows を mapping(機械のラベル → 人の名前)で採点して total に足す。mixed(声が混ざっている)・weak(不確か。mixed でないもの)・plain(それ以外)に分けて数える"""
    for r in rows:
        ok = bool(r["label"]) and mapping.get(r["label"]) == r["human"]
        total["rows"] += 1
        total["correct"] += ok
        if not r["label"]:
            total["unassigned"] += 1
        k = "mixed" if r["mixed"] else "weak" if r["weak"] else "plain"
        total[k][0] += 1
        total[k][1] += ok


def finish_counts(c):
    return {"rows": c["rows"], "correct": c["correct"], "rate": rate(c["correct"], c["rows"]), "unassigned": c["unassigned"],
            "plain": {"rows": c["plain"][0], "correct": c["plain"][1], "rate": rate(c["plain"][1], c["plain"][0])},
            "weak": {"rows": c["weak"][0], "correct": c["weak"][1], "rate": rate(c["weak"][1], c["weak"][0])},
            "mixed": {"rows": c["mixed"][0], "correct": c["mixed"][1], "rate": rate(c["mixed"][1], c["mixed"][0])}}


def majority_name(rows):
    """その機械の話者の行に人が付けた名前(多い方)。同数なら None(決められない)"""
    cnt = {}
    for r in rows:
        cnt[r["human"]] = cnt.get(r["human"], 0) + 1
    if not cnt:
        return None
    ranked = sorted(cnt.items(), key=lambda kv: -kv[1])
    if len(ranked) > 1 and ranked[0][1] == ranked[1][1]:
        return None
    return ranked[0][0]


def voice_records(run, rows):
    """最新の回の声の照合 -> [{"label", "info", "human"(人が付けた名前。行が無い・決められないなら None), "rows"}]。単独指定(by=request)は測らない"""
    vs = (run.get("voices") or {}).get("speakers") if (run.get("voices") or {}).get("checked") else None
    out = []
    for sid, info in sorted((vs or {}).items()):
        if not isinstance(info, dict) or info.get("by") == "request":
            continue
        mine = [r for r in rows if r["label"] == sid]
        out.append({"label": sid, "info": info, "human": majority_name(mine), "rows": len(mine)})
    return out


class Voices:
    """声の照合の集計(1つの行の集まりぶん)"""

    def __init__(self):
        self.decided = self.unverified = 0
        self.correct, self.wrong = [], []             # (点数 or None, 2位との差 or None)
        self.undecided = {}                            # 理由 -> 数
        self.missed = []                               # 付けなかったが1位が人の名前だった: (点数, 理由)
        self.checked = []                              # しきい値の表の元: (点数, 2位の点数 or None, 1位の名前, 人の名前)

    def add(self, recs):
        for v in recs:
            i, human = v["info"], v["human"]
            top, score, second = i.get("top"), num(i.get("score")), num(i.get("secondScore"))
            if human is not None and score is not None and top:
                self.checked.append((score, second, top, human))
            if i.get("decided"):
                if human is None:
                    self.unverified += 1
                    continue
                self.decided += 1
                ok = norm_name(i["decided"]) == norm_name(human)
                (self.correct if ok else self.wrong).append((score, None if score is None or second is None else round(score - second, 3), i.get("by")))
            else:
                self.undecided[i.get("reason") or "unknown"] = self.undecided.get(i.get("reason") or "unknown", 0) + 1
                if human is not None and top and norm_name(top) == norm_name(human):
                    self.missed.append((score, i.get("reason")))

    def result(self):
        scores = lambda xs: dist([x[0] for x in xs])      # noqa: E731
        margins = lambda xs: dist([x[1] for x in xs])     # noqa: E731
        sweep = []
        for m in SWEEP_MATCH:
            for g in SWEEP_MARGIN:
                dec = cor = 0
                for score, second, top, human in self.checked:
                    if score >= m and (second is None or score - second >= g):
                        dec += 1
                        cor += norm_name(top) == norm_name(human)
                sweep.append({"match": m, "margin": g, "decided": dec, "correct": cor, "wrong": dec - cor, "precision": rate(cor, dec)})
        return {"decided": self.decided, "correct": len(self.correct), "wrong": len(self.wrong), "rate": rate(len(self.correct), self.decided),
                "unverified": self.unverified, "undecided": dict(sorted(self.undecided.items())), "undecidedTotal": sum(self.undecided.values()),
                "missed": {"n": len(self.missed), "score": dist([x[0] for x in self.missed]), "byReason": _count([x[1] for x in self.missed])},
                "correctScore": scores(self.correct), "wrongScore": scores(self.wrong), "correctMargin": margins(self.correct), "wrongMargin": margins(self.wrong),
                "sweep": sweep}


def _count(xs):
    out = {}
    for x in xs:
        out[str(x)] = out.get(str(x), 0) + 1
    return dict(sorted(out.items()))


def engine_key(run):
    e = run.get("engine") if isinstance(run.get("engine"), dict) else {}
    return "%s / %s / クラスタ %s / 人数 %s" % (e.get("name", "?"), e.get("embedding") or "-", e.get("clusterThreshold", "-"), e.get("requested", "-"))


def is_single(run):
    return (run.get("engine") or {}).get("name") == "single" if isinstance(run.get("engine"), dict) else False


# ---------------------------------------------------------------- 全体

def load_docs(tdir, include_eval, only=None):
    """文書を読む(読むだけ)-> ([(id, 文書)], {"broken", "evalSet"})。only = 文書の id の集まり(--docs)"""
    out, skipped = [], {"broken": 0, "evalSet": 0}
    for name in sorted(os.listdir(tdir)) if os.path.isdir(tdir) else []:
        if not DOC_RE.match(name):
            continue
        tid = name[:-5]
        if only and tid not in only:
            continue
        doc = read_json(os.path.join(tdir, name), None, C.DOC_BYTES)
        if not isinstance(doc, dict):
            skipped["broken"] += 1
            continue
        if doc.get("evalSet") is True and not include_eval:
            skipped["evalSet"] += 1
            continue
        out.append((tid, doc))
    return out, skipped


def resolve_reviewed(mode, only=None):
    """--reviewed の既定: only(--docs のときは prefer)。eval_asr.py と同じ決め方"""
    if mode is not None and mode not in REVIEWED_MODES:
        raise SystemExit("--reviewed は only・prefer・ignore のどれかです: %r" % mode)
    return mode or ("prefer" if only else "only")


def pick_reviewed(docs, mode):
    """確かめ済みの扱いで文書を絞る -> ([(id, 文書, 確かめ済みとして扱うか)], 記録)。評価用でない文書はどれでも残す。
    only で確かめ済みの評価用が 0 本なら(評価用があるときだけ)今までの選び方(ignore)に戻して fallback = True"""
    n_eval = sum(1 for _, d in docs if d.get("evalSet") is True)
    n_rev = sum(1 for _, d in docs if is_reviewed(d))
    info = {"mode": mode, "effective": mode, "evalDocs": n_eval, "reviewedDocs": n_rev, "fallback": False, "notReviewed": 0}
    if mode == "only" and n_eval and not n_rev:
        info["effective"], info["fallback"] = "ignore", True
    out = []
    for tid, d in docs:
        whole = info["effective"] != "ignore" and is_reviewed(d)
        if info["effective"] == "only" and d.get("evalSet") is True and not whole:
            info["notReviewed"] += 1
            continue
        out.append((tid, d, whole))
    return out, info


def reviewed_notes(info, include_draft):
    notes = []
    if info["fallback"]:
        notes.append("確かめ済みの評価用の動画が 0 本なので、評価用は今までどおりの選び方で測りました(--reviewed only の戻り。ドリルで動画を確かめると定点になります)")
    elif info["effective"] == "only" and info["notReviewed"]:
        notes.append("確かめ済みでない評価用の文書 %d 件は測っていません(--reviewed only。混ぜるなら --reviewed prefer)" % info["notReviewed"])
    if include_draft:
        notes.append("--include-draft: 仮の名前・機械の下書きのまま・確かめられない行も数えています(人が確かめていない = 甘く出る)")
    return notes


def speaker_count(diffs):
    """話者の数(機械 − 人。文書ごと)の分布"""
    dc = {}
    for d in diffs:
        dc[str(d)] = dc.get(str(d), 0) + 1
    return {"docs": len(diffs), "exact": dc.get("0", 0), "exactRate": rate(dc.get("0", 0), len(diffs)), "diff": dict(sorted(dc.items(), key=lambda kv: int(kv[0]))),
            "meanDiff": round(sum(diffs) / len(diffs), 2) if diffs else None, "over": sum(1 for d in diffs if d > 0), "under": sum(1 for d in diffs if d < 0)}


def parse_smooth(text):
    """--smooth の値 -> [False, True] など(off・on の「,」区切り)"""
    if text is None:
        return None
    return parse_list(text, _conv_smooth, "--smooth")


def _conv_smooth(x):
    if x.lower() not in SMOOTH_MODES:
        raise ValueError(x)
    return SMOOTH_MODES[x.lower()]


def smooth_key(on):
    return "ならす" if on else "ならさない"


class Smooth:
    """ならす/ならさないの比べ(1 つの設定ぶん)。行の正しさと、ならした行(人が確かめた行のうち)の合った/外れた・直った/壊れた"""

    def __init__(self, on):
        self.on = on
        self.counts = new_counts()
        self.smoothed = self.checked = self.correct = self.fixed = self.broke = 0

    def add(self, rows, mapping, smoothed_ids, before=None):
        """rows = 採点する行(human_rows)・smoothed_ids = ならした行の id(人が確かめたかによらず全部)・before = ならさないときの {行 id: 合ったか}"""
        add_counts(self.counts, rows, mapping)
        self.smoothed += len(smoothed_ids)
        for r in rows:
            if str(r["id"]) not in smoothed_ids:
                continue
            ok = bool(r["label"]) and mapping.get(r["label"]) == r["human"]
            self.checked += 1
            self.correct += ok
            if before is not None:
                b = before.get(str(r["id"]))
                self.fixed += ok and b is False
                self.broke += (not ok) and b is True

    def result(self):
        return dict(finish_counts(self.counts), key=smooth_key(self.on), on=self.on, smoothedRows=self.smoothed, smoothedChecked=self.checked,
                    smoothedCorrect=self.correct, smoothedWrong=self.checked - self.correct, fixed=self.fixed, broke=self.broke)


def row_ok(rows, mapping):
    return {str(r["id"]): bool(r["label"]) and mapping.get(r["label"]) == r["human"] for r in rows}


def stored_smooth_recs(S, doc, run):
    """保存してある判別の記録で「ならしたら」を計算する(判別し直さない)-> (ならさない recs, ならした recs, ならした行 id の集まり)。
    行の時刻は文書の今の行(人が直したあと)・ラベルと割合は記録の rows(記録の無い行はラベル無し = 前後に数えるが、ならせない)。
    記録が「ならした回」なら、ならさない側は label(元のラベル)から labelMap で話者に戻す"""
    E = S.ed_speakers
    recs = run.get("rows") if isinstance(run.get("rows"), dict) else {}
    lmap = {str(k): v for k, v in (run.get("labelMap") or {}).items()} if isinstance(run.get("labelMap"), dict) else {}
    ids = {str(s.get("id")) for s in doc.get("speakers") or [] if isinstance(s, dict) and s.get("id")}
    off, rows, rids = {}, [], []
    for sg in doc.get("segments") or []:
        if not isinstance(sg, dict) or num(sg.get("start")) is None or num(sg.get("end")) is None:
            continue
        rid = str(sg.get("id"))
        rec = recs.get(rid)
        if isinstance(rec, dict):
            off[rid] = dict(rec, speaker=lmap.get(str(rec.get("label")), "") if rec.get("smoothed") else rec.get("speaker"))
        lb = rec.get("label") if isinstance(rec, dict) else None
        rows.append({"start": num(sg["start"]), "end": num(sg["end"]), "label": lb, "ratio": num((rec or {}).get("ratio")) or 0.0,
                     "skip": E.diar_keep_row(sg, ids) or not str(sg.get("text") or "").strip()})
        rids.append(rid)
    ovl = [(num(x[0]), num(x[1])) for x in run.get("overlaps") or [] if isinstance(x, (list, tuple)) and len(x) >= 2 and num(x[0]) is not None and num(x[1]) is not None]
    sm = E.smooth_labels(rows, ovl)
    on = dict(off)
    for i, lb in sm.items():
        if rids[i] in on:
            on[rids[i]] = dict(on[rids[i]], speaker=lmap.get(str(lb), ""))
    return off, on, {rids[i] for i in sm}


def evaluate(data_dir=None, since=None, until=None, include_eval=True, include_draft=False, reviewed=None, only=None, smooth=None):
    tdir_root = C.locate("transcribe", data_dir)
    S_ = load_serve() if smooth else None   # ならしの計算は本番の関数(editor の ed_speakers)を使う。--smooth のときだけ読む
    tdir = os.path.join(tdir_root, "transcripts")
    since_ms, until_ms = C.period(since, until)
    subs = {k: {"counts": new_counts(), "voices": Voices()} for k, _ in SUBSETS}
    engines, by_doc = {}, []
    diffs = []
    ovl = Overlap()
    mode = resolve_reviewed(reviewed, only)
    loaded, sk = load_docs(tdir, include_eval, set(only) if only else None)
    picked, rinfo = pick_reviewed(loaded, mode)
    skipped = {"noDiar": 0, "single": 0, "noRows": 0, "evalSet": sk["evalSet"], "broken": sk["broken"], "notReviewed": rinfo["notReviewed"]}
    totals = {"docs": 0, "drafts": 0, "noRecord": 0, "evalDocs": 0, "machineDraft": 0, "unverified": 0, "reviewedDocs": 0, "noSub": 0}
    sm_agg = [Smooth(on) for on in smooth] if smooth else []
    for tid, doc, whole in picked:
        diar = read_diar(tdir, tid)
        if not diar:
            skipped["noDiar"] += 1
            continue
        run = diar["latest"]
        if is_single(run):
            skipped["single"] += 1
            continue
        runrows = run.get("rows") if isinstance(run.get("rows"), dict) else {}
        conf = confirm_map(doc, run, whole)
        if sm_agg:   # ならす/ならさないの比べ(記録からの計算。下の本体の数には入れない)
            recs_off, recs_on, sm_ids = stored_smooth_recs(S_, doc, run)
            r_off, _ = human_rows(doc, recs_off, since_ms, until_ms, include_draft, conf)
            before = row_ok(r_off, best_mapping(r_off))
            for a in sm_agg:
                rr, _ = human_rows(doc, recs_on if a.on else recs_off, since_ms, until_ms, include_draft, conf)
                a.add(rr, best_mapping(rr), sm_ids if a.on else set(), before)
        ovl.add(overlap_rows(doc, runrows, run.get("overlaps"), since_ms, until_ms, whole))
        rows, cnt = human_rows(doc, runrows, since_ms, until_ms, include_draft, conf)
        for k in ("drafts", "noRecord", "machineDraft", "unverified"):
            totals[k] += cnt[k]
        totals["noSub"] += cnt.get("noSub", 0)
        if not rows:
            skipped["noRows"] += 1
            continue
        totals["docs"] += 1
        totals["evalDocs"] += doc.get("evalSet") is True
        totals["reviewedDocs"] += bool(whole)
        mapping = best_mapping(rows)
        picks = {"all": rows, "proofed": [r for r in rows if r["proofed"]], "timeEdited": [r for r in rows if r["edited"] is True]}
        for k, sel in picks.items():
            add_counts(subs[k]["counts"], sel, mapping)
            subs[k]["voices"].add(voice_records(run, sel))
        one = new_counts()
        add_counts(one, rows, mapping)
        m_cnt = num(run.get("speakers"))
        machine = int(m_cnt) if m_cnt is not None else len({r["label"] for r in rows if r["label"]})
        human = len({r["human"] for r in rows})
        diffs.append(machine - human)
        by_doc.append({"id": tid, "title": str(doc.get("title") or "")[:40], "evalSet": doc.get("evalSet") is True, "reviewed": bool(whole), "engine": engine_key(run),
                       "machineSpeakers": machine, "humanSpeakers": human, "rows": one["rows"], "correct": one["correct"], "rate": rate(one["correct"], one["rows"])})
        # 判別の回ごと(最新 + 履歴): その回の rows を、その回自身の対応で採点する(行の id が消えた回は、残っている行だけ)。
        # 人が確かめた行かは最新の回で決めたもの(conf)を使う(文書の今の話者は最新の回から作られたため)
        for r_ in [run] + [h for h in diar.get("history") or [] if isinstance(h, dict)]:
            if is_single(r_) or not isinstance(r_.get("rows"), dict):
                continue
            if r_ is run:   # 最新の回は上で同じ引数で採点した結果(rows・one)をそのまま使う
                c = one
            else:
                hr, _ = human_rows(doc, r_["rows"], since_ms, until_ms, include_draft, conf)
                if not hr:
                    continue
                c = new_counts()
                add_counts(c, hr, best_mapping(hr))
            e = engines.setdefault(engine_key(r_), {"runs": 0, "docs": set(), "counts": new_counts()})
            e["runs"] += 1
            e["docs"].add(tid)
            for k in ("rows", "correct", "unassigned"):
                e["counts"][k] += c[k]
    nrows = subs["all"]["counts"]["rows"]
    few = nrows < FEW_ROWS
    notes = reviewed_notes(rinfo, include_draft)
    if totals["drafts"]:
        notes.append("仮の名前(話者1…)のままの行 %d 行は測っていません(人が確かめていない下書き。--include-draft で入れる)" % totals["drafts"])
    if totals["machineDraft"]:
        notes.append("機械の下書きのままの行(名前も行も機械が付けて、その話者を人が 1 行も確かめていない)%d 行は測っていません" % totals["machineDraft"])
    if totals["unverified"]:
        notes.append("確かめられない行(人が名前を付けた・ほかの行を確かめた話者の、校正していない行)%d 行は測っていません" % totals["unverified"])
    if totals["noRecord"]:
        notes.append("機械の記録が無い行(判別のあとに分けた・つないだ行)%d 行は測っていません" % totals["noRecord"])
    if totals["noSub"]:
        notes.append("字幕に出さない行(noSub・ゲーム音声など)%d 行は測っていません(その場かぎりの声で、判別の当たり外れではない)" % totals["noSub"])
    if skipped["noDiar"]:
        notes.append("判別の記録(.diar.json)が無い文書が %d 件あります(記録を入れる前に判別したもの)" % skipped["noDiar"])
    if skipped["single"]:
        notes.append("「話す人が1人」の指定の文書が %d 件あります(機械の判別ではないので測っていません)" % skipped["single"])
    meta = {"schema": SCHEMA, "at": int(time.time() * 1000), "since": since, "until": until, "includeEval": bool(include_eval), "includeDraft": bool(include_draft),
            "git": C.git_rev(), "dataDir": tdir_root, "docs": totals["docs"], "evalDocs": totals["evalDocs"], "reviewedDocs": totals["reviewedDocs"], "rows": nrows, "few": few,
            "fewNote": "まだ少ない(参考): 話者つきの行が %d 行(%d 行未満)。これで既定値(しきい値 0.60・差 0.08 など)を決めない" % (nrows, FEW_ROWS) if few else "",
            "skipped": skipped, "draftRows": totals["drafts"], "noRecordRows": totals["noRecord"],
            "machineDraftRows": totals["machineDraft"], "unverifiedRows": totals["unverified"], "noSubRows": totals["noSub"], "confirmRule": CONFIRM_RULE, "reviewed": rinfo,
            "only": sorted(only) if only else None, "notes": notes}
    return {"meta": meta,
            "subsets": {k: dict(finish_counts(v["counts"]), voices=v["voices"].result()) for k, v in subs.items()},
            "speakerCount": speaker_count(diffs),
            "overlap": ovl.result(),
            "byEngine": {k: {"runs": v["runs"], "docs": len(v["docs"]), "rows": v["counts"]["rows"], "correct": v["counts"]["correct"],
                             "rate": rate(v["counts"]["correct"], v["counts"]["rows"]), "unassigned": v["counts"]["unassigned"]} for k, v in sorted(engines.items())},
            "byDoc": by_doc, **({"smooth": [a.result() for a in sm_agg]} if sm_agg else {})}


# ---------------------------------------------------------------- 判別し直して測る(run)

_SERVE = []


def load_serve():
    """src/editor/serve.py(_evalcommon.load_serve。1 プロセスで 1 回だけ)。serve 自身の作業データは一時フォルダ eval_speakers_…で、
    読み込んだあと環境変数を戻す(戻さないと、このあとの locate(本物の作業データ)が一時フォルダを指す)。判別はこのプロセスの中で動かす(ed_jobs.IN_WORKER)"""
    if not _SERVE:
        _SERVE.append(C.load_serve(prefix="eval_speakers_", keep_env=False))
    return _SERVE[0]


def parse_list(text, conv, what):
    out = []
    for x in str(text).split(","):
        x = x.strip()
        if not x:
            continue
        try:
            v = conv(x)
        except ValueError:
            raise SystemExit("%s の値が正しくありません: %r" % (what, x))
        if v not in out:
            out.append(v)
    if not out:
        raise SystemExit("%s に値がありません" % what)
    return out


def _conv_num(x):
    if x.lower() in ("auto", "0", "自動"):
        return 0
    n = int(x)
    if not 1 <= n <= 10:
        raise ValueError(x)
    return n


def _conv_sec(x):
    v = float(x)
    if not 0.0 <= v < 10.0:   # src/editor/ed_speakers.py の diar_tune と同じ範囲
        raise ValueError(x)
    return v


def run_grid(S, threshold=None, num=None, emb=None, min_on=None, min_off=None, smooth=None):
    """設定の組(どれも「,」区切り。指定しない項目は本番の既定の値)-> [{"threshold", "num", "emb", "minOn", "minOff", "smooth"}]。
    smooth = [False, True] など(ならす/ならさない。判別は 1 回で、採点だけ両方。指定しなければ ならさない だけ)"""
    ths = parse_list(threshold, _conv_sec, "--threshold") if threshold else [S.DIAR_CLUSTER_THRESHOLD]
    nums = parse_list(num, _conv_num, "--num") if num else [0]
    embs = parse_list(emb, str, "--emb") if emb else [S.DIAR_EMB_DEFAULT]
    bad = [e for e in embs if e not in S.DIAR_EMBS]
    if bad:
        raise SystemExit("--emb は %s のどれかです: %s" % ("・".join(S.DIAR_EMBS), ", ".join(bad)))
    ons = parse_list(min_on, _conv_sec, "--min-on") if min_on else [S.DIAR_MIN_ON]
    offs = parse_list(min_off, _conv_sec, "--min-off") if min_off else [S.DIAR_MIN_OFF]
    sms = smooth or [False]
    return [{"threshold": t, "num": n, "emb": e, "minOn": a, "minOff": b, "smooth": sm} for e in embs for n in nums for t in ths for a in ons for b in offs for sm in sms]


def setting_key(st):
    return "しきい値 %.2f / 人数 %s / %s / on %.2f / off %.2f%s" % (st["threshold"], st["num"] or "自動", st["emb"], st["minOn"], st["minOff"],
                                                              " / ならす" if st.get("smooth") else "")


def check_models(S, root, grid):
    """本物の判別のモデルが作業データの models/diar にあるか(無ければ取得せずに止める)。S の DIAR_DIR を本物の場所にする"""
    d = os.path.join(root, "models", "diar")
    need = [S.DIAR_SEG["file"]] + sorted({S.DIAR_EMBS[st["emb"]]["file"] for st in grid})
    missing = [f for f in need if not (os.path.isfile(os.path.join(d, f)) and os.path.getsize(os.path.join(d, f)) > 1000)]
    if missing:
        raise SystemExit("話者判別のモデルがありません(この道具は取得しません。編集の画面で一度判別すると取得されます): %s の %s" % (d, "・".join(missing)))
    try:
        import sherpa_onnx  # noqa: F401  (道具のプロセスで読む。サーバーではない)
    except ImportError:
        raise SystemExit("話者判別の部品(sherpa-onnx)が入っていません(setup の install-diarize.bat)。py -3.10 で動かしているか確かめてください")
    S.ed_speakers.DIAR_DIR = d


def doc_audio(S, tid, doc, root, wav, job):
    """文書の範囲の音声を wav に取り出す(本番の run_diarize と同じ extract_audio)-> (offset = 音声の先頭が元の動画の何秒か, 音声の秒, 出どころ)。
    元の動画が無ければ保管データの full.flac(eval_asr.py と同じ)。ネットワーク上の動画は読まない(資格情報を送らない)"""
    spec, start, where = C.audio_span(S, doc, root, doc_id=tid)
    end = S.num(doc.get("end"))
    S.extract_audio(job, spec, wav)
    return start, S.media_duration(wav) or max(0.0, (end or 0.0) - start), where


def diarize_once(S, job, wav, total, st):
    """設定 st で 1 回判別する -> [(開始, 終了, 話者番号)](音声の先頭からの秒)。疑似(TRANSCRIBE_BACKEND=fake)は diarize_fake"""
    if S.backend_name() == "fake":
        return S.diarize_fake(job, total, st["num"], st["threshold"])
    return S.diarize_real(job, wav, st["num"], st["emb"], threshold=st["threshold"], min_on=st["minOn"], min_off=st["minOff"])


def score_turns(S, doc, turns, offset, since_ms, until_ms, include_draft, conf, whole, smooth=False):
    """判別の結果を本番と同じ assign_speakers で行に割り当てて採点する -> (行, 数, 機械の話者の数, 重なりの行, ならした行 id, ならさないときの {行 id: 合ったか} or None)。
    smooth なら本番と同じ smooth_speakers で細切れをならしてから採点する(守る行は diar_keep_row・文字の無い行は前後に数えない)"""
    segs = [sg for sg in doc.get("segments") or [] if isinstance(sg, dict) and num(sg.get("start")) is not None and num(sg.get("end")) is not None]
    plain = [{"start": num(sg.get("start")), "end": num(sg.get("end")), "text": sg.get("text")} for sg in segs]
    res = S.assign_speakers(plain, turns, offset)
    recs = {str(sg.get("id")): {"speaker": "L%d" % sp if sp is not None else "", "mixed": bool(mixed), "weak": bool(weak)}
            for sg, (sp, mixed, weak) in zip(segs, res)}
    sm_ids, before = set(), None
    if smooth:
        r_off, _ = human_rows(doc, recs, since_ms, until_ms, include_draft, conf)
        before = row_ok(r_off, best_mapping(r_off))
        ids = {str(s.get("id")) for s in doc.get("speakers") or [] if isinstance(s, dict) and s.get("id")}
        ts = sorted((a + offset, b + offset, s) for a, b, s in turns)
        sm = S.ed_speakers.smooth_speakers(plain, res, ts, [S.ed_speakers.diar_keep_row(sg, ids) for sg in segs])
        recs = dict(recs)
        for i, lb in sm.items():
            rid = str(segs[i].get("id"))
            recs[rid] = dict(recs[rid], speaker="L%d" % lb, weak=True)
            sm_ids.add(rid)
    rows, cnt = human_rows(doc, recs, since_ms, until_ms, include_draft, conf)
    overlaps = S._turn_overlaps(sorted((a + offset, b + offset, s) for a, b, s in turns))
    return rows, cnt, len({sp for sp, _, _ in res if sp is not None}), overlap_rows(doc, recs, overlaps, since_ms, until_ms, whole), sm_ids, before


def run_evaluate(data_dir=None, since=None, until=None, include_eval=True, include_draft=False, reviewed=None, only=None,
                 threshold=None, num_=None, emb=None, min_on=None, min_off=None, log=print, smooth=None):
    """文書の音声をもう一度判別して(設定の組ごと)人の最終と比べる。文書・diar.json は書かない。smooth = [False, True] など(--smooth)"""
    root = C.locate("transcribe", data_dir)
    S = load_serve()
    tdir = os.path.join(root, "transcripts")
    since_ms, until_ms = C.period(since, until)
    grid = run_grid(S, threshold, num_, emb, min_on, min_off, smooth)
    real = S.backend_name() != "fake"
    if real:
        check_models(S, root, grid)
    mode = resolve_reviewed(reviewed, only)
    loaded, sk = load_docs(tdir, include_eval, set(only) if only else None)
    picked, rinfo = pick_reviewed(loaded, mode)
    if only:
        missing = sorted(set(only) - {t for t, _ in loaded})
        if missing:
            log("注意: 見つからない(か --no-eval で外した)文書: " + ", ".join(missing))
    agg = [{"key": setting_key(st), "settings": st, "counts": new_counts(), "len": {k: new_counts() for k, _ in LENGTHS},
            "diffs": [], "diffLen": {k: [] for k, _ in LENGTHS}, "docsLen": {k: 0 for k, _ in LENGTHS}, "sec": 0.0, "docs": 0, "overlap": Overlap(), "errors": [],
            "smooth": Smooth(st["smooth"])}
           for st in grid]
    skipped = {"noRows": 0, "noAudio": 0, "evalSet": sk["evalSet"], "broken": sk["broken"], "notReviewed": rinfo["notReviewed"]}
    totals = {"docs": 0, "evalDocs": 0, "reviewedDocs": 0, "audioSec": 0.0, "rows": 0, "drafts": 0, "machineDraft": 0, "unverified": 0, "noSub": 0}
    by_doc = []
    tmp = tempfile.mkdtemp(prefix="eval_speakers_wav_")
    try:
        for n, (tid, doc, whole) in enumerate(picked, 1):
            diar = read_diar(tdir, tid)
            stored = diar["latest"] if diar else None
            conf = confirm_map(doc, stored, whole)
            all_recs = {str(sg.get("id")): {"speaker": ""} for sg in doc.get("segments") or [] if isinstance(sg, dict)}
            pre, cnt = human_rows(doc, all_recs, since_ms, until_ms, include_draft, conf)
            if not pre and not overlap_rows(doc, all_recs, [], since_ms, until_ms, whole):
                skipped["noRows"] += 1
                continue
            log("(%d/%d) %s %s …" % (n, len(picked), tid, str(doc.get("title") or "")[:30]), flush=True)
            job = C.fake_job()
            wav = os.path.join(tmp, "%s.wav" % tid)
            try:
                offset, total, where = doc_audio(S, tid, doc, root, wav, job)
            except Exception as e:   # 音声が無い・取り出せない文書は数えない(理由を出す)
                log("   とばしました: %s" % str(getattr(e, "message", "") or e)[:200])
                skipped["noAudio"] += 1
                by_doc.append({"id": tid, "title": str(doc.get("title") or "")[:40], "error": str(getattr(e, "message", "") or e)[:200]})
                continue
            totals["docs"] += 1
            totals["evalDocs"] += doc.get("evalSet") is True
            totals["reviewedDocs"] += bool(whole)
            totals["audioSec"] += total
            totals["rows"] += len(pre)
            for k in ("drafts", "machineDraft", "unverified"):
                totals[k] += cnt[k]
            totals["noSub"] += cnt.get("noSub", 0)
            lk = "short" if total < SHORT_SEC else "long"
            one = {"id": tid, "title": str(doc.get("title") or "")[:40], "sec": round(total, 1), "audio": where, "reviewed": bool(whole),
                   "humanSpeakers": len({r["human"] for r in pre}), "rows": len(pre), "bySetting": []}
            cache = {}   # ならす/ならさないだけ違う設定は、同じ判別の結果を使う(判別は 1 回)
            for a in agg:
                st = a["settings"]
                base = setting_key(dict(st, smooth=False))
                t0 = time.monotonic()
                try:
                    if base not in cache:
                        cache[base] = diarize_once(S, job, wav, total, st)
                    turns = cache[base]
                except Exception as e:   # 1 つの設定で落ちても、ほかの設定・文書は続ける
                    msg = str(getattr(e, "message", "") or e)[:200]
                    log("   %s: 判別できませんでした: %s" % (a["key"], msg))
                    a["errors"].append({"id": tid, "error": msg})
                    one["bySetting"].append({"key": a["key"], "error": msg})
                    continue
                sec = time.monotonic() - t0
                rows, _c, found, orows, sm_ids, before = score_turns(S, doc, turns, offset, since_ms, until_ms, include_draft, conf, whole, st["smooth"])
                mapping = best_mapping(rows)
                a["smooth"].add(rows, mapping, sm_ids, before)
                c = new_counts()
                add_counts(c, rows, mapping)
                add_counts(a["counts"], rows, mapping)
                add_counts(a["len"][lk], rows, mapping)
                a["overlap"].add(orows)
                a["sec"] += sec
                a["docs"] += 1
                a["docsLen"][lk] += 1
                if rows:
                    d = found - len({r["human"] for r in rows})
                    a["diffs"].append(d)
                    a["diffLen"][lk].append(d)
                one["bySetting"].append({"key": a["key"], "machineSpeakers": found, "rows": c["rows"], "correct": c["correct"], "rate": rate(c["correct"], c["rows"]),
                                         "sec": round(sec, 2)})
            by_doc.append(one)
            fsio.unlink_quiet(wav)
    finally:
        shutil.rmtree(tmp, ignore_errors=True)
    nrows = totals["rows"]
    few = nrows < FEW_ROWS
    notes = reviewed_notes(rinfo, include_draft)
    if totals["drafts"]:
        notes.append("仮の名前(話者1…)のままの行 %d 行は測っていません(--include-draft で入れる)" % totals["drafts"])
    if totals["machineDraft"] or totals["unverified"]:
        notes.append("人が確かめていない行(機械の下書きのまま %d 行・確かめられない %d 行)は測っていません" % (totals["machineDraft"], totals["unverified"]))
    if totals["noSub"]:
        notes.append("字幕に出さない行(noSub・ゲーム音声など)%d 行は測っていません" % totals["noSub"])
    if skipped["noAudio"]:
        notes.append("音声が無い・取り出せない文書 %d 件は測っていません" % skipped["noAudio"])
    meta = {"schema": SCHEMA, "mode": "run", "at": int(time.time() * 1000), "git": C.git_rev(), "dataDir": root, "backend": "sherpa-onnx" if real else "fake",
            "threads": S.diar_threads() if real else None, "since": since, "until": until, "includeEval": bool(include_eval), "includeDraft": bool(include_draft),
            "only": sorted(only) if only else None, "reviewed": rinfo, "docs": totals["docs"], "evalDocs": totals["evalDocs"], "reviewedDocs": totals["reviewedDocs"],
            "audioSec": round(totals["audioSec"], 1), "rows": nrows, "few": few,
            "fewNote": "まだ少ない(参考): 人が確かめた話者つきの行が %d 行(%d 行未満)。これで判別の既定の値(しきい値 %.2f など)を決めない"
                       % (nrows, FEW_ROWS, S.DIAR_CLUSTER_THRESHOLD) if few else "",
            "draftRows": totals["drafts"], "machineDraftRows": totals["machineDraft"], "unverifiedRows": totals["unverified"], "noSubRows": totals["noSub"], "confirmRule": CONFIRM_RULE,
            "skipped": skipped, "settings": grid, "notes": notes}
    out = []
    for a in agg:
        r = dict(finish_counts(a["counts"]), key=a["key"], settings=a["settings"], docs=a["docs"], sec=round(a["sec"], 2), speakerCount=speaker_count(a["diffs"]),
                 overlap=a["overlap"].result(), errors=a["errors"], smooth=a["smooth"].result())
        r["byLength"] = {k: dict(finish_counts(a["len"][k]), docs=a["docsLen"][k], speakerCount=speaker_count(a["diffLen"][k])) for k, _ in LENGTHS}
        out.append(r)
    return {"meta": meta, "bySetting": out, "byDoc": by_doc}


def print_run(res):
    m = res["meta"]
    rv = m.get("reviewed") or {}
    print("話者の判別をやり直して測る(run・%s)  文書 %d 件(うち評価用 %d・確かめ済み %d)・音声 %.0f 秒・人が確かめた話者つきの行 %d  作業データ: %s"
          % ("本物の sherpa-onnx・スレッド %s" % m["threads"] if m["backend"] != "fake" else "疑似の判別", m["docs"], m["evalDocs"], m["reviewedDocs"],
             m["audioSec"], m["rows"], m["dataDir"]))
    print("  --reviewed %s%s  数える行: %s" % (rv.get("effective", "?"), "(only から戻した)" if rv.get("fallback") else "",
                                          "全部(--include-draft)" if m["includeDraft"] else "人が確かめた行だけ"))
    if m["fewNote"]:
        print("★ " + m["fewNote"])
    for i, s in enumerate(res["bySetting"], 1):
        c = s["speakerCount"]
        lens = "  ".join("%s %s(%d/%d・%d 本)" % (label, pct(s["byLength"][k]["rate"]).strip(), s["byLength"][k]["correct"], s["byLength"][k]["rows"],
                                                s["byLength"][k]["docs"]) for k, label in LENGTHS)
        print("  #%d %s" % (i, s["key"]))
        print("      行の正しさ %s(%d/%d)  %s" % (pct(s["rate"]).strip(), s["correct"], s["rows"], lens))
        print("      話者の数(機械 − 人): ちょうど %d/%d(%s)・多すぎ %d・少なすぎ %d・分布 %s  %s  判別 %.1f 秒%s"
              % (c["exact"], c["docs"], pct(c["exactRate"]).strip(), c["over"], c["under"], c["diff"],
                 "  ".join("%s ちょうど %d/%d" % (label, s["byLength"][k]["speakerCount"]["exact"], s["byLength"][k]["speakerCount"]["docs"]) for k, label in LENGTHS),
                 s["sec"], "  失敗 %d" % len(s["errors"]) if s["errors"] else ""))
        o = s["overlap"]
        if o["rows"]:
            p = o["byPredictor"]["mixed"]
            print("      重なり(mixed): 機械 %d 行・人 %d 行・当たり %d  適合率 %s  再現率 %s(行 %d)"
                  % (p["pred"], o["human"], p["tp"], pct(p["precision"]).strip(), pct(p["recall"]).strip(), o["rows"]))
        sm = s.get("smooth") or {}
        if sm.get("on"):
            print("      ならした行 %d(うち人が確かめた行 %d: 合った %d・外れた %d・ならさないより 直った %d・壊れた %d)"
                  % (sm["smoothedRows"], sm["smoothedChecked"], sm["smoothedCorrect"], sm["smoothedWrong"], sm["fixed"], sm["broke"]))
    docs = [d for d in res["byDoc"]]
    if docs and len(docs) <= 20:
        print("  [文書ごと]")
        for d in docs:
            if d.get("error"):
                print("    %s  とばした: %s" % (d["id"], d["error"]))
                continue
            cells = "  ".join("#%d %s" % (i, "失敗" if x.get("error") else "機械 %d 人・%s" % (x["machineSpeakers"], pct(x["rate"]).strip()))
                              for i, x in enumerate(d["bySetting"], 1))
            print("    %s %4.0f 秒 人 %d 人・行 %d%s  %s  %s" % (d["id"], d["sec"], d["humanSpeakers"], d["rows"], "  [確かめ済み]" if d["reviewed"] else "", cells, d["title"]))
    for n in m["notes"]:
        print("注意: " + n)


# ---------------------------------------------------------------- 表示・保存

def _d(x, key="median"):
    return "-" if not x.get("n") else "%s" % x.get(key)


def print_subset(title, s):
    print("  [%s]  %d 行" % (title, s["rows"]))
    if not s["rows"]:
        return
    print("    行ごとの正しさ %s(%d / %d)  機械が付けなかった行 %d" % (pct(s["rate"]).strip(), s["correct"], s["rows"], s["unassigned"]))
    for k, label in (("plain", "ふつうの行"), ("weak", "不確か(weak)の行"), ("mixed", "声が混ざる(mixed)の行")):
        g = s[k]
        print("      %-18s %5d 行  正しさ %s" % (label, g["rows"], pct(g["rate"]).strip()))
    v = s["voices"]
    if not (v["decided"] or v["undecidedTotal"] or v["unverified"]):
        return
    print("    声の照合: 付いた名前 %d(人の最終と同じ %d・違う %d → %s)・確かめられない %d・付けなかった %d"
          % (v["decided"], v["correct"], v["wrong"], pct(v["rate"]).strip(), v["unverified"], v["undecidedTotal"]))
    if v["undecided"]:
        print("      付けなかった理由: " + "・".join("%s %d" % (REASONS.get(k, k), n) for k, n in v["undecided"].items()))
    print("      点数 正しい: 中央値 %s(最小 %s・%d 個) / 間違い: 中央値 %s(最大 %s・%d 個)"
          % (_d(v["correctScore"]), _d(v["correctScore"], "min"), v["correctScore"]["n"], _d(v["wrongScore"]), _d(v["wrongScore"], "max"), v["wrongScore"]["n"]))
    print("      2位との差 正しい: 中央値 %s(最小 %s) / 間違い: 中央値 %s(最大 %s)" % (_d(v["correctMargin"]), _d(v["correctMargin"], "min"), _d(v["wrongMargin"]), _d(v["wrongMargin"], "max")))
    print("      取りこぼし(付けなかったが1位が人の名前だった): %d 個%s" % (v["missed"]["n"], "  点数 中央値 %s" % _d(v["missed"]["score"]) if v["missed"]["n"] else ""))
    if v["sweep"] and any(x["decided"] for x in v["sweep"]):
        print("      しきい値を変えたら(決まる数 / 正しい数。記録の点数と差からの計算):")
        print("        点数\\差 " + "".join("%12s" % ("差 %.2f" % g) for g in SWEEP_MARGIN))
        for m in SWEEP_MATCH:
            cells = [x for x in v["sweep"] if x["match"] == m]
            print("        %.2f    " % m + "".join("%12s" % ("%d / %d" % (c["decided"], c["correct"])) for c in cells))


def print_overlap(o, indent="  "):
    if not o:
        return
    print("%s[重なりの見つけ方(人の音のメモ overlap と比べる。確かめ済みの文書の行・校正済みの行)]  行 %d・人が重なりと付けた行 %d" % (indent, o["rows"], o["human"]))
    if not o["rows"]:
        return
    for k, label in OVL_PREDICTORS:
        p = o["byPredictor"][k]
        print("%s  %-22s 機械が付けた %4d 行  当たり %3d・外れ %3d・見逃し %3d  適合率 %s  再現率 %s"
              % (indent, label, p["pred"], p["tp"], p["fp"], p["fn"], pct(p["precision"]).strip(), pct(p["recall"]).strip()))


def print_smooth(items, indent="  ", title="[話者の細切れをならす(--smooth)。人が確かめた行で比べる]"):
    if not items:
        return
    print(indent + title)
    for s in items:
        print("%s  %-6s 行の正しさ %s(%d/%d)  ならした行 %d(うち人が確かめた行 %d: 合った %d・外れた %d%s)"
              % (indent, s["key"], pct(s["rate"]).strip(), s["correct"], s["rows"], s["smoothedRows"], s["smoothedChecked"], s["smoothedCorrect"], s["smoothedWrong"],
                 "・ならさないより 直った %d・壊れた %d" % (s["fixed"], s["broke"]) if s["on"] else ""))


def print_report(res):
    m = res["meta"]
    rng = C.period_label(m["since"], m["until"])
    print("話者の判別の測定(%s)  文書 %d 件(うち評価用 %d・確かめ済み %d)・人が確かめた話者つきの行 %d  作業データ: %s"
          % (rng, m["docs"], m["evalDocs"], m.get("reviewedDocs", 0), m["rows"], m["dataDir"]))
    rv = m.get("reviewed") or {}
    print("  --reviewed %s%s  数える行: %s" % (rv.get("effective", "?"), "(only から戻した)" if rv.get("fallback") else "",
                                          "全部(--include-draft)" if m["includeDraft"] else "人が確かめた行だけ(機械の下書きのまま %d 行・確かめられない %d 行は外した)"
                                          % (m.get("machineDraftRows", 0), m.get("unverifiedRows", 0))))
    if m["fewNote"]:
        print("★ " + m["fewNote"])
    if not m["docs"]:
        print("(測れる文書がありません。話者を判別して名前を付けた文書(.diar.json つき)が貯まると測れます)")
    else:
        for k, label in SUBSETS:
            print_subset(label, res["subsets"][k])
        c = res["speakerCount"]
        print("  [話者の数(機械 − 人)]  文書 %d 件  ちょうど当たり %d(%s)  多すぎ %d・少なすぎ %d  平均 %s  分布 %s"
              % (c["docs"], c["exact"], pct(c["exactRate"]).strip(), c["over"], c["under"], c["meanDiff"], c["diff"]))
        print_overlap(res.get("overlap"))
        print_smooth(res.get("smooth"), title="[話者の細切れをならす(--smooth。保存してある判別の記録から計算・判別し直さない)。人が確かめた行で比べる]")
        if res["byEngine"]:
            print("  [判別の回ごとの行の正しさ(最新と履歴の全部。設定の比較)]")
            for k, e in res["byEngine"].items():
                print("    %-60s 回 %3d・文書 %3d・行 %6d  正しさ %s" % (k, e["runs"], e["docs"], e["rows"], pct(e["rate"]).strip()))
        print("  [文書ごと(悪い順に10件)]")
        for d in sorted(res["byDoc"], key=lambda d: (d["rate"] if d["rate"] is not None else 2, d["id"]))[:10]:
            print("    %s 機械 %d 人・人 %d 人  行 %4d  正しさ %s%s  %s" % (d["id"], d["machineSpeakers"], d["humanSpeakers"], d["rows"], pct(d["rate"]).strip(),
                                                                    ("  [確かめ済み]" if d.get("reviewed") else "  [評価用]") if d["evalSet"] else "", d["title"]))
    for n in m["notes"]:
        print("注意: " + n)


def main(argv=None):
    p = argparse.ArgumentParser(description="話者の判別と声の照合の当たり具合を、人が直した最終で測る(作業データは読むだけ)")
    p.add_argument("mode", nargs="?", choices=("stored", "run"), default="stored",
                   help="stored = 保存してある判別の記録を比べる(既定)/ run = 音声をもう一度判別して設定の組ごとに比べる")
    C.add_period_args(p, "この日(YYYY-MM-DD)以後の行だけ(行の校正した時刻 proofedAt、無ければ文書の更新時刻)", "この日(YYYY-MM-DD。この日を含む)までの行だけ",
                      "同じ形の JSON を 文字起こしの作業データの evals/speakers/<日時>.json(run は <日時>-run.json)に残す")
    p.add_argument("--no-eval", action="store_true", help="評価用(evalSet)の文書を外す")
    p.add_argument("--include-draft", action="store_true",
                   help="仮の名前(話者1…)・機械の下書きのまま・確かめられない行も測る(今までの数え方 = 人が確かめていないので甘く出る)")
    p.add_argument("--reviewed", choices=REVIEWED_MODES,
                   help="評価用の確かめ済み(動画を全部聞いて直した印)の扱い。only = 評価用は確かめ済みだけ(既定。--docs のときは prefer。0 本なら今までの選び方に戻す)/"
                        " prefer = 確かめ済みでない評価用も混ぜる / ignore = 印を見ない。評価用でない文書はどれでも入る")
    p.add_argument("--docs", help="文書の id をカンマ区切りで")
    g = p.add_argument_group("run(判別し直す)の設定。どれも「,」区切りで複数 → 全部の組み合わせ。指定しない項目は本番の既定の値")
    g.add_argument("--threshold", help="クラスタのしきい値(DIAR_CLUSTER_THRESHOLD。大きいほど人をまとめる)")
    g.add_argument("--num", help="人数(auto = 自動 か 1〜10)")
    g.add_argument("--emb", help="声の特徴のモデル(voxceleb・campplus・standard。作業データに無いモデルは使えない)")
    g.add_argument("--min-on", dest="min_on", help="声の区間の最短(秒。DIAR_MIN_ON)")
    g.add_argument("--min-off", dest="min_off", help="すき間の最短(秒。DIAR_MIN_OFF)")
    p.add_argument("--smooth", help="話者の細切れをならす(S2)を比べる: off・on の「,」区切り(例 off,on)。stored は記録から計算・run は同じ判別の結果を両方で採点")
    args = p.parse_args(argv)
    only = C.split_ids(args.docs)
    tune = {"threshold": args.threshold, "num_": args.num, "emb": args.emb, "min_on": args.min_on, "min_off": args.min_off}
    smooth = parse_smooth(args.smooth)
    if args.mode == "stored":
        if any(v is not None for v in tune.values()):
            p.error("--threshold・--num・--emb・--min-on・--min-off は run のときだけ使えます")
        res = evaluate(args.data_dir, args.since, args.until, not args.no_eval, args.include_draft, args.reviewed, only, smooth)
        print_report(res)
    else:
        res = run_evaluate(args.data_dir, args.since, args.until, not args.no_eval, args.include_draft, args.reviewed, only, smooth=smooth, **tune)
        print_run(res)
    C.report_saved(res, args.json, res["meta"]["dataDir"], "speakers", "-run" if args.mode == "run" else "")
    return res


if __name__ == "__main__":
    C.utf8_stdout()
    main()
