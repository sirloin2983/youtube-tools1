"""精度の自動測定(マスタープラン Q3)。

人が直した最終の記録に対して、機械の出力がどれだけ当たっているかを、手が空いたときに自動で測って「調子」に出す。
測る道具(src/eval/tools/eval_asr.py・eval_marks.py・eval_speakers.py・eval_cut.py。無い道具は飛ばす)はそのまま使い、**子プロセス**で呼ぶ
(eval_asr は入口の中では import しない。ほかの道具も形をそろえる)。

- 測るもの: 軽い測定だけ = 保存してある機械の出力と人の最終を比べる(認識し直さない。文字起こしは `eval_asr.py stored`)。作業データは読むだけ。
  結果は各道具が今どおり `<ツールの作業データ>\\evals\\<領域>\\` に保存する。入口は最新 2 回分の要約だけを記録 `app\\accuracy-state.json` に写す(直近と前回)
- いつ測るか: 夜の窓(設定 accuracy の nightFrom〜nightTo 時。既定 1〜6 時)に、1 日 1 回。画面の「今すぐ測る」はいつでも(窓・1 日 1 回・編集の静けさを待たない)
- 手が空いた判定: 入口の重い処理の順番(jobs.SLOTS)に動いている・待っているものが無い・「編集」のジョブが動いていない・まとめて実行が動いていない
  (この 3 つは busy() が返す理由。「今すぐ」でも待つ)、さらに自動のときは文字起こしの文書の最後の更新が 30 分以上前(last_edit())
- 子プロセス: sys.executable・優先度は通常より下・黒い画面なし・時間切れあり。環境変数(YTT_DATA_DIR など作業データの場所)はそのまま引き継ぐ。
  道具が失敗・時間切れ・結果を読めなくても入口は止まらない(その領域に理由を記録して、次の領域へ)
- 結果ファイルの整理: 自動の測定が作った分だけ、領域ごとに新しい 30 件を残して古いものを消す(人が手で流した結果は消さない)。
  自分が作った分の見分け方 = 入口が覚えた「自分が作ったファイルの一覧」(state の areas.<領域>.files)。marks・speakers・cut の道具には --label が無く、
  名前が手で流した分と同じ形(<日時>.json)なので、名前の印では見分けられない。asr だけは `_auto` の印でも見分けられる(一覧が失われても拾える)。
  消すのは各道具の evals/<領域>/ の中の、名前の形が厳しく合う普通のファイルだけ(シンボリックリンクはたどらない)
- 重い測定(認識し直しての比較)は入れない(箱も無い)。
  ただし「保存してある出力を今の既定で当て直す・判別し直す」測定は軽い(CPU・数十秒)ので夜に入れる: 行の時刻 = eval_timing --apply(今の既定の後処理を保存してある生出力に当て直す)・
  話者 = eval_speakers run --or-stored(確かめ済みの評価用を今の既定の設定で判別し直す。モデルや音声が無ければ保存してある記録に切り替える)。文書には書かない
- 前と中身が同じ結果は書かない: 道具の保存(src/eval/tools/_evalcommon.py の save)が、前の結果と時刻・git を除いて同じなら書かずに最後の行「変わらず: <前のファイル>」を出す。
  入口はその行も「保存: 」と同じに読む(前のファイルを読み直して latest の at だけ進める。失敗にしない。marks は対象外 = 毎回書く)
- 設定(src/app/prefs.py の節 accuracy): enabled(既定オン。読むだけで軽い)・nightFrom・nightTo
- 入口の条件(「あと何本・何分」。plan/README.md の 7): 各工程を始めてよい量(G1・G2・学習用・話者の行・採用の記録・パック・「別」の候補)の
  今の値 / 目標 / あと を snapshot の goals に出す。しきい値は GOALS の 1 か所(道具の「まだ少ない」の値と同じ。test_accuracy が食い違いを検査)。
  値は各道具の直近の結果から(道具は変えない)。普段・学習用の校正済みの秒だけは道具の結果に無いので、測るときに入口が文字起こしの文書を読んで数える
  (評価用でない文書の、校正済みで「聞き取れない」の印が無い行の長さの合計。普段と学習用を分ける印が無いので同じ数)。
  まだ測っていない・道具が無い・古い記録で鍵が無いものは now = None(画面は「未測定」)
"""
import datetime
import json
import math
import os
import re
import threading
import time

from manage.cases import txindex
from ytt import datadir, fsio, schemas, tools

STATE_FILE = "accuracy-state.json"
FIRST_WAIT = 120           # 起動してから最初に見るまで(秒。ツールの起動とぶつけない)
CHECK_EVERY = 300          # 夜の窓・手が空いたかを見る間隔(秒)
FORCE_CHECK_EVERY = 30     # 「今すぐ」で手が空くのを待っているときの間隔(秒)
QUIET_EDIT_SEC = 30 * 60   # 文字起こしの文書の最後の更新からこれだけ空いていれば「手が空いた」(自動のとき)
TOOL_TIMEOUT = 20 * 60     # 道具1つあたりの時間切れ(秒)
FEW_DOCS = 2               # これより少ない文書(配信)数のときは「まだ少ない」
MAX_RESULT_BYTES = 64 * 1024 * 1024
SAVED_MARK = "保存: "       # 道具が結果のファイルを書いたとき、最後に標準出力へ出す行の頭(src/eval/tools/eval_*.py)
SAME_MARK = "変わらず: "     # 前の結果と中身が同じで書かなかったとき、最後に出す行の頭(src/eval/tools/_evalcommon.py の SAME_MARK)
ERR_TAIL = 200
TIMING_FEW_ROWS = 100      # 行の時刻の「文字が合う行」がこれより少ないときは「まだ少ない」(src/eval/tools/eval_timing.py の FEW_ROWS と同じ。GOALS の timing の目標も同じ値)
KEEP_FILES = 30            # 自動の測定が作った結果ファイルは、領域ごとに新しい分をこれだけ残して古いものを消す
# 消してよい名前の形(道具の save の形: <日時>.json。asr は --label auto の <日時>_auto.json・話者の run は <日時>-run.json)。これに合わないファイルは数えもしない・消さない
RESULT_NAME_RE = re.compile(r"^\d{8}-\d{6}(?:_auto|-run)?\.json\Z")
STATE_LABELS = {"off": "オフ", "idle": "動いています", "waiting": "手が空くのを待っています", "running": "測っています…"}
STATE_MAX = 1024 * 1024    # 記録(accuracy-state.json)を読む上限(これより大きければ読めない扱い = 記録なし)
MAX_DOC_BYTES = 64 * 1024 * 1024   # 普段の校正済みの秒を数えるとき、これより大きい文書は読まない
DOC_NAME_RE = re.compile(r"^[0-9a-f]{12}\.json\Z")   # 文字起こしの文書(src/editor の TID_RE と同じ形)。edit.json・diar.json などは数えない

# 入口の条件(plan/README.md の 7「入口の条件と今」)。今の値 / 目標 / あと を「調子」に 1 行ずつ出す。**しきい値はここだけ**
# (道具の「まだ少ない」と同じ値: src/eval/tools/eval_asr.py の GATES の G1・G2・eval_speakers.py の FEW_ROWS・eval_marks.py の FEW_VIDEOS・eval_cut.py の FEW_PACKS・
#  eval_alt.py の FEW_CANDS。test_accuracy が食い違いを検査する)。src = (領域の id, 直近の要約の鍵)。"daily" = 入口が数えた評価用以外の校正済みの秒。
# unit: "sec" = 秒(画面は分・時間で出す)・それ以外 = 数の単位。
# check = 「確かめる」のカードがこの目標へ足す形(src/eval/check/goals.py がここから引く): kind = カードの種類・sources = 出どころ・
#   count = (数える単位, 足す範囲)・default = 出どころが表に無いときのその種類の既定か(既定 True。1 つの種類に 1 つだけ)
GOALS = (
    {"id": "g1", "label": "G1 定点 15 分", "opens": "B1 行の時刻・B2 エンジンの決定", "src": ("asr", "reviewedSec"), "target": 15 * 60, "unit": "sec"},
    {"id": "g2fixed", "label": "G2 定点 30 分", "opens": "B4 抜け・呼び名(普段 30 分も要る)", "src": ("asr", "reviewedSec"), "target": 30 * 60, "unit": "sec"},
    {"id": "g2daily", "label": "G2 普段の校正 30 分", "opens": "B4 抜け・呼び名(定点 30 分も要る)", "src": ("daily", "sec"), "target": 30 * 60, "unit": "sec"},
    {"id": "train", "label": "学習用の校正 3 時間", "opens": "B5 追加学習", "src": ("daily", "sec"), "target": 3 * 3600, "unit": "sec"},
    {"id": "speakers", "label": "確かめ済みの話者の行 200", "opens": "A1 話者の既定(I-2a)", "src": ("speakers", "rows"), "target": 200, "unit": "行",
     "check": {"kind": "voice", "sources": ("diar",), "count": ("card", "all")}},
    {"id": "marks", "label": "採用の記録 配信 10 本", "opens": "C1 盛り上がりの重み(I-4a)", "src": ("marks", "docs"), "target": 10, "unit": "本",
     "check": {"kind": "value", "sources": ("auto", "cand"), "count": ("case", "since")}},
    {"id": "packs", "label": "たたき台つきのパック 20 本", "opens": "C3 カット(I-3a)", "src": ("cut", "fromPack"), "target": 20, "unit": "本"},
    {"id": "alt", "label": "「別」の候補の判定 100 件", "opens": "D1-b 候補の既定オン", "src": ("alt", "judged"), "target": 100, "unit": "件",
     "check": {"kind": "read", "sources": ("alt",), "count": ("card", "since"), "default": False}},
    # V1 確かめる(V0): 後処理の札(src/eval/tools/eval_fill.py の FEW_ROWS)・行の時刻(eval_timing.py の FEW_ROWS)。開く物の文言は仮
    {"id": "fill", "label": "後処理の札の判定 30 行", "opens": "K1 後処理の既定", "src": ("fill", "judged"), "target": 30, "unit": "行",
     "check": {"kind": "read", "sources": ("fill",), "count": ("card", "since")}},
    {"id": "timing", "label": "行の時刻の判定 100 行", "opens": "B1 行の時刻", "src": ("timing", "rows"), "target": 100, "unit": "行",
     "check": {"kind": "time", "sources": ("row",), "count": ("card", "all")}},
)


class ToolError(Exception):
    pass


# ---------------------------------------------------------------- 結果の要約(道具ごとの形 → 画面が読む共通の形)

_num = schemas.num   # 有限の数なら float・それ以外は None(ytt の共通の判定)


def _int(x):
    return int(x) if isinstance(x, (int, float)) and not isinstance(x, bool) and math.isfinite(x) else 0


def _summary(label, value, docs, unit, better, low=False, rng=None, extra=None):
    """画面が読む共通の形。value は 0〜1 の割合(None = 測れなかった)・docs は数えた文書(配信)の数・extra は [{label, value, better}]"""
    return {"label": label, "value": _num(value), "range": rng, "docs": _int(docs), "unit": unit, "better": better,
            "lowData": bool(low), "few": _int(docs) < FEW_DOCS, "extra": extra or []}


def summarize_asr(res):
    s = res.get("summary") if isinstance(res.get("summary"), dict) else {}
    o = s.get("overall")
    if not isinstance(o, dict):
        raise ValueError("結果の形が想定と違います(summary.overall が無い)")
    ci = s.get("ci95")
    rng = [_num(ci[0]), _num(ci[1])] if isinstance(ci, list) and len(ci) == 2 and _num(ci[0]) is not None and _num(ci[1]) is not None else None
    out = _summary("CER", o.get("cer"), len(s.get("byDoc") or []), "文書", "lower", s.get("lowData"), rng)
    out["chars"] = _int(o.get("refChars"))
    out["proofedSec"] = _int(s.get("proofedSec"))
    rv = s.get("reviewed") if isinstance(s.get("reviewed"), dict) else {}
    out["reviewedSec"] = _num(rv.get("sec"))      # 定点の量(確かめ済みの評価用の文書の長さの合計。入口の条件 G1・G2)
    return out


def summarize_marks(res):
    o = res.get("overall")
    if not isinstance(o, dict):
        raise ValueError("結果の形が想定と違います(overall が無い)")
    top10 = (o.get("top") or {}).get("top10") or {}
    miss = (o.get("misses") or {}).get("missRate")
    # 配信の数 = C1 の入口「採用の記録 配信 10 本」: スタジオの判定に線 D の録画・友人の返事も足した judgedAll(K2)
    docs = o.get("judgedAll")
    extra = [{"label": "見逃し率", "value": _num(miss), "better": "lower"}]
    # 物差し 3 本(MARKS-3・C-4-1。結果の human3。無い結果は足さない): 友人の区間の拾えた率・届けた物を友人が良いと答えた率
    h3 = res.get("human3") if isinstance(res.get("human3"), dict) else {}
    fr, used = h3.get("friendRange") or {}, (h3.get("used") or {}).get("all") or {}
    if _num(fr.get("hitRate")) is not None:
        extra.append({"label": "友人の区間の拾えた率", "value": _num(fr.get("hitRate")), "better": "higher"})
    if _num(used.get("goodRate")) is not None:
        extra.append({"label": "届けた物を友人が良いと答えた率", "value": _num(used.get("goodRate")), "better": "higher"})
    return _summary("上位10の採用率", top10.get("adoptRate"), docs, "配信", "higher", (res.get("meta") or {}).get("few"), extra=extra)


def summarize_speakers(res):
    """src/eval/tools/eval_speakers.py: 夜は run(確かめ済みの評価用を今の既定の設定で判別し直した結果。bySetting の先頭 = 既定の 1 組)。
    モデルや音声が無くて stored に切り替わったとき(subsets.all)は保存してある記録の結果"""
    bs = res.get("bySetting")
    if isinstance(bs, list) and bs and isinstance(bs[0], dict):
        s0, m = bs[0], res.get("meta") or {}
        count = s0.get("speakerCount") or {}
        out = _summary("行ごとの話者の正しさ(判別し直し)", s0.get("rate"), s0.get("docs"), "文書", "higher", m.get("few"),
                       extra=[{"label": "話者の数が合う", "value": _num(count.get("exactRate")), "better": "higher"}])
        out["rows"] = _num(m.get("rows"))   # 人が確かめた話者つきの行(入口の条件)
        return out
    sub = ((res.get("subsets") or {}).get("all"))
    if not isinstance(sub, dict):
        raise ValueError("結果の形が想定と違います(bySetting も subsets.all も無い)")
    voices = sub.get("voices") or {}
    count = res.get("speakerCount") or {}
    m = res.get("meta") or {}
    out = _summary("行ごとの話者の正しさ", sub.get("rate"), m.get("docs"), "文書", "higher", m.get("fewNote"),
                   extra=[{"label": "声の照合", "value": _num(voices.get("rate")), "better": "higher"},
                          {"label": "話者の数が合う", "value": _num(count.get("exactRate")), "better": "higher"}])
    out["rows"] = _num(m.get("rows"))   # 人が確かめた話者つきの行(入口の条件)
    return out


def summarize_cut(res):
    """src/eval/tools/eval_cut.py: たたき台のカットを人が直さなかった文書の割合(甘く出る = 人はたたき台につられる)と、端がそのままだった割合。
    人が見ずにパックした文書(edit.json の draftUntouched)は道具が数えない(fromPack にも入らない)"""
    t = res.get("total")
    if not isinstance(t, dict):
        raise ValueError("結果の形が想定と違います")
    m = res.get("meta") or {}
    out = _summary("たたき台を直さなかった文書", t.get("untouchedRate"), m.get("docs"), "文書", "higher", m.get("few"),
                   extra=[{"label": "端がそのまま", "value": _num((t.get("edges30") or {}).get("sameRate")), "better": "higher"}])
    out["fromPack"] = _num(m.get("fromPack"))     # 最終がパックのたたき台つきの文書(入口の条件)
    return out


def summarize_alt(res):
    """src/eval/tools/eval_alt.py: 2つ目のエンジンとの食い違いの候補(札「別」)の当たり率。judged = 判定できた候補の数(入口の条件)"""
    m, t = res.get("meta"), res.get("total")
    if not isinstance(m, dict) or not isinstance(t, dict):
        raise ValueError("結果の形が想定と違います(meta・total が無い)")
    fb = res.get("feedback") if isinstance(res.get("feedback"), dict) else {}
    pk = t.get("pickup") if isinstance(t.get("pickup"), dict) else {}
    out = _summary("候補の当たり率", t.get("hitRate"), m.get("docs"), "文書", "higher", m.get("few"),
                   extra=[{"label": "採否の記録の採用率", "value": _num(fb.get("acceptRate")), "better": "higher"},
                          {"label": "人の直しを拾えた率", "value": _num(pk.get("coveredRate")), "better": "higher"}])
    out["judged"] = _num(m.get("judged"))
    out["candidates"] = _num(m.get("candidates"))
    return out


def summarize_fill(res):
    """src/eval/tools/eval_fill.py: 認識のあとの後処理(札)を人が残した割合。judged = 残した・直した・戻した・消した行の数(入口の条件)。
    judged は A(別の読みで埋めた行)と E(LLM の名前直し)の両方を足す = 確かめるの read:fill の答えはどちらの行にも付くので、
    片方だけだと E の答えが次の夜の測定のあと入口の数から消える(goals の fill は since)"""
    a = res.get("a")
    if not isinstance(a, dict):
        raise ValueError("結果の形が想定と違います")
    out = _summary("後処理を残した行", a.get("keptRate"), a.get("docs"), "文書", "higher", a.get("few"),
                   extra=[{"label": "戻した行", "value": _num(a.get("revertRate")), "better": "lower"},
                          {"label": "直した行", "value": _num(a.get("editRate")), "better": "lower"}])
    e = res.get("e") if isinstance(res.get("e"), dict) else {}
    out["judged"] = _int(a.get("judged")) + _int(e.get("judged"))
    return out


def summarize_timing(res):
    """src/eval/tools/eval_timing.py: 行の頭が遅れた割合(①頭)。rows = 文字が合う行の数(入口の条件)。
    --apply の結果(apply.variants の先頭 = 今の既定の後処理を保存してある生出力に当て直した数字)があればそれを主にする(夜の測定。今の ① を測る)。
    無い・当て直せた文書が 0 本のときは、保存してある機械の出力(古い後処理の物)の数字"""
    o, m = res.get("overall"), res.get("meta")
    if not isinstance(o, dict):
        raise ValueError("結果の形が想定と違います(overall が無い)")
    m = m if isinstance(m, dict) else {}
    docs, few, label = m.get("docs"), m.get("few"), "頭が遅れた行"
    ap = res.get("apply") if isinstance(res.get("apply"), dict) else {}
    vs = ap.get("variants") if isinstance(ap.get("variants"), list) else []
    now = vs[0] if vs and isinstance(vs[0], dict) and isinstance(vs[0].get("overall"), dict) else None
    if now is not None and _int(ap.get("docs")) > 0 and _int(now["overall"].get("n")) > 0:
        o, docs, few, label = now["overall"], ap.get("docs"), _int(now["overall"].get("n")) < TIMING_FEW_ROWS, "頭が遅れた行(今の既定の後処理)"
    out = _summary(label, o.get("head"), docs, "文書", "lower", few,
                   extra=[{"label": "末が早く切れた行", "value": _num(o.get("tail")), "better": "lower"},
                          {"label": "前の行に食い込んだ", "value": _num(o.get("prev")), "better": "lower"},
                          {"label": "次の行に食い込んだ", "value": _num(o.get("next")), "better": "lower"}])
    out["rows"] = _num(o.get("n"))
    return out


# 領域: script = src/eval/tools/ の道具・args = 呼び方・tool/sub = 結果の置き場所(<ツールの作業データ>\evals\<sub>)・summarize = 結果 → 要約
AREAS = (
    {"id": "asr", "label": "文字起こし", "script": "eval_asr.py", "args": ("stored", "--label", "auto"), "tool": "transcribe", "sub": "asr", "summarize": summarize_asr},
    {"id": "marks", "label": "盛り上がり", "script": "eval_marks.py", "args": ("--json",), "tool": "studio", "sub": "marks", "summarize": summarize_marks},
    {"id": "speakers", "label": "話者", "script": "eval_speakers.py", "args": ("run", "--or-stored", "--json"), "tool": "transcribe", "sub": "speakers", "summarize": summarize_speakers},
    {"id": "cut", "label": "カット", "script": "eval_cut.py", "args": ("--json",), "tool": "transcribe", "sub": "cut", "summarize": summarize_cut},   # src/eval/tools/eval_cut.py(無ければ飛ばす)
    {"id": "alt", "label": "「別」の候補", "script": "eval_alt.py", "args": ("--json",), "tool": "transcribe", "sub": "alt", "summarize": summarize_alt},
    {"id": "fill", "label": "後処理の札", "script": "eval_fill.py", "args": ("--json",), "tool": "transcribe", "sub": "fill", "summarize": summarize_fill},   # V1 確かめる(V0)
    {"id": "timing", "label": "行の時刻", "script": "eval_timing.py", "args": ("--json", "--apply"), "tool": "transcribe", "sub": "timing", "summarize": summarize_timing},
)


def count_daily(folder):
    """評価用でない文字起こしの文書の、校正済みの量(入口の条件の「普段」「学習用」)。読むだけ。
    数え方は「編集」の定点の行(src/human/proof/store.py の good_row)と同じ: 校正済み(proofed が True)で「聞き取れない」(tags の unclear)の
    印が無い行の長さの合計。-> {"sec", "docs"(校正済みの行がある文書の数), "lines"}。フォルダが無ければ 0"""
    sec, docs, lines = 0.0, 0, 0
    try:
        found = txindex.doc_paths(folder) if folder and os.path.isdir(folder) else {}   # 案件の 作業用 に置いた文書も数える
    except OSError:
        found = {}
    for name in sorted(found):
        p = found[name]
        if not DOC_NAME_RE.match(name) or not os.path.isfile(p):
            continue
        try:
            if os.path.getsize(p) > MAX_DOC_BYTES:
                continue
            with open(p, "rb") as f:
                d = json.loads(f.read().decode("utf-8-sig"))
        except (OSError, ValueError):
            continue
        if not isinstance(d, dict) or d.get("evalSet") is True:
            continue
        n = 0
        for g in d.get("segments") or []:
            if not isinstance(g, dict) or g.get("proofed") is not True or "unclear" in (g.get("tags") or []):
                continue
            a, b = _num(g.get("start")), _num(g.get("end"))
            sec += max(0.0, (b or 0.0) - (a or 0.0))
            n += 1
        lines += n
        docs += 1 if n else 0
    return {"sec": round(sec, 1), "docs": docs, "lines": lines}


def goals_of(last, extra=None):
    """記録(Accuracy.last)-> 入口の条件の一覧 [{id, label, opens, target, unit, now(None = 未測定), left, reached, at, check}]。GOALS の順。
    extra(目標の id, 直近の測定の時刻 ms か None) -> 「確かめる」の答えから足す数(src/eval/check/goals.py の extra_counter。V1 V0)。
    足した数は check に出す(0 なら now はそのまま。未測定でも答えがあれば now = 答えの数)"""
    out = []
    areas = last.get("areas") if isinstance(last.get("areas"), dict) else {}
    for g in GOALS:
        area, key = g["src"]
        if area == "daily":
            src = last.get("daily") if isinstance(last.get("daily"), dict) else {}
            now, at = _num(src.get(key)), src.get("at")
        else:
            latest = (areas.get(area) or {}).get("latest")
            latest = latest if isinstance(latest, dict) else {}
            summ = latest.get("summary") if isinstance(latest.get("summary"), dict) else {}
            now, at = _num(summ.get(key)), latest.get("at")
        at = at if isinstance(at, (int, float)) and not isinstance(at, bool) else None
        add = 0
        if extra is not None:
            try:
                add = int(extra(g["id"], at) or 0)
            except Exception:
                add = 0
        if add > 0:
            now = (now or 0.0) + add
        left = max(0.0, g["target"] - now) if now is not None else None
        out.append({"id": g["id"], "label": g["label"], "opens": g["opens"], "target": g["target"], "unit": g["unit"], "now": now,
                    "left": left if left is None or g["unit"] == "sec" else int(math.ceil(left)),
                    "reached": now is not None and now >= g["target"], "at": at, "check": add})
    return out


def in_window(now, cfg):
    """now(エポック秒。PC の時刻)が夜の窓か。nightFrom > nightTo なら日をまたぐ(22 → 6 など)"""
    h = datetime.datetime.fromtimestamp(now).hour
    a, b = int(cfg.get("nightFrom", 1)), int(cfg.get("nightTo", 6))
    return a <= h < b if a < b else (h >= a or h < b)


def day_of(now):
    return datetime.date.fromtimestamp(now).isoformat()


class Accuracy:
    def __init__(self, prefs, data_dir, repo_root, busy=None, last_edit=None, log=None, clock=None, commands=None, evals_dir=None,
                 timeout=TOOL_TIMEOUT, first_wait=FIRST_WAIT, check_every=CHECK_EVERY, keep=KEEP_FILES, transcripts_dir=None,
                 defaults=None):
        """prefs: src/app/prefs.py の Prefs(節 accuracy)。defaults: 設定が読めないときに使う節の既定(入口が prefs.DEFAULTS["accuracy"] を渡す。
        prefs を読み込まない = app の部品に依存しない。None = 空 = オフ扱い)。data_dir: ホームの作業データ(app。記録を置く)。repo_root: ツールの親のフォルダ(src。作業データの場所の既定。測る道具は repo_root/eval/tools/)。
        busy() -> 手が空いていない理由の文(空・None = 空いている)。last_edit() -> 文字起こしの文書の最後の更新(エポック秒・None = 不明)。
        commands(area) -> 子プロセスの引数の一覧(None = その道具が無い)・evals_dir(area) -> 結果の置き場所: テストで偽の道具に差し替える。
        transcripts_dir() -> 文字起こしの文書のフォルダ(入口の条件の「普段」を数える。None = 数えない)"""
        self.transcripts_dir = transcripts_dir or self._default_transcripts_dir
        self.prefs, self.data_dir, self.repo_root = prefs, data_dir, repo_root
        self.defaults = defaults
        self.busy = busy or (lambda: None)
        self.last_edit = last_edit or (lambda: None)
        self.log = log or (lambda msg: None)
        self.clock = clock or time.time
        self.commands = commands or self._default_commands
        self.evals_dir = evals_dir or self._default_evals_dir
        self.timeout = timeout
        self.keep = keep
        self.first_wait, self.check_every = first_wait, check_every
        self.state_path = os.path.join(data_dir, STATE_FILE)
        self.lock = threading.Lock()           # 測る処理を1つずつ
        self.wake = threading.Event()
        self.force = False                     # 「今すぐ」(手が空くまで残る)
        self.closed = False
        self.thread = None
        self.state = "idle"
        self.message = ""
        self.last = self._load_state()

    # ---- 記録
    def _load_state(self):
        d = fsio.read_json_or(self.state_path, {}, max_bytes=STATE_MAX, kind=dict)
        if not isinstance(d.get("areas"), dict):
            d["areas"] = {}
        return d

    def _save_state(self):
        try:
            fsio.write_json(self.state_path, self.last, indent=None)
        except OSError as e:
            self.log("精度の測定: 記録を書けませんでした(%s)" % tools.why(e))

    def _cfg(self):
        try:
            return dict(self.prefs.get(["accuracy"])["accuracy"])
        except (OSError, ValueError, KeyError):
            return dict(self.defaults or {})

    # ---- 道具の呼び方
    def _default_commands(self, area):
        script = os.path.join(self.repo_root, "eval", "tools", area["script"])   # 道具は src/eval/tools/(repo_root = src = 子の作業フォルダ)
        return [tools.python_exe(), "-m", "eval.tools." + area["script"][:-3]] + list(area["args"]) if os.path.isfile(script) else None

    def _default_evals_dir(self, area):
        try:
            return os.path.join(datadir.resolve(area["tool"], self.repo_root), "evals", area["sub"])
        except Exception:
            return None

    def _default_transcripts_dir(self):
        try:
            return txindex.folder(self.repo_root)
        except Exception:
            return None

    def _count_daily(self):
        """入口の条件の「普段」「学習用」= 評価用でない文書の校正済みの秒を数えて記録に入れる。失敗しても測定は止めない(前の値を残す)"""
        try:
            folder = self.transcripts_dir()
            if folder is None:
                return
            self.last["daily"] = dict(count_daily(folder), at=int(self.clock() * 1000))
        except Exception as e:
            self.log("精度の測定: 普段の校正済みの量を数えられませんでした(%s)" % e.__class__.__name__)

    def _run(self, argv):
        """子プロセスで道具を動かす -> 標準出力。失敗・時間切れは ToolError(理由の文)"""
        env = dict(os.environ, PYTHONIOENCODING="utf-8", PYTHONUTF8="1")   # 作業データの場所(YTT_DATA_DIR など)はそのまま引き継ぐ
        kw = {} if os.name == "nt" else {"preexec_fn": lambda: os.nice(10)}   # 優先度: Windows は creationflags、ほかは nice
        try:
            r = tools.run(argv, timeout=self.timeout, cancelled=lambda: self.closed, flags=tools.no_window_flags(priority="low"), poll=1.0,
                          cwd=self.repo_root, env=env, **kw)
        except OSError as e:
            raise ToolError("道具を起動できませんでした(%s)" % tools.why(e))
        if r.why:
            raise ToolError("ホームを終了します" if r.why == "cancel" else "時間切れ(%d 分)で止めました" % max(1, int(self.timeout // 60)))
        if r.code != 0:
            lines = r.err_lines(1)
            raise ToolError("道具が失敗しました(終了コード %d)%s" % (r.code, ": " + lines[-1][:ERR_TAIL] if lines else ""))
        return r.out.decode("utf-8", "replace")

    def _result_path(self, out, edir, t0):
        """道具が結果を書いたファイル。標準出力の「保存: <パス>」か「変わらず: <前のパス>」(前と中身が同じで書かなかった)を優先し、無ければ置き場所の中で今回の測定のあとに書かれた最新のファイル。
        置き場所の外のファイルは読まない"""
        cand = None
        for line in reversed(out.splitlines()):
            mark = SAVED_MARK if line.startswith(SAVED_MARK) else SAME_MARK if line.startswith(SAME_MARK) else None
            if mark:
                cand = line[len(mark):].strip()
                break
        if cand is None and edir and os.path.isdir(edir):
            best = None
            for name in os.listdir(edir):
                p = os.path.join(edir, name)
                if name.endswith(".json") and os.path.isfile(p) and os.path.getmtime(p) >= t0 - 2 and (best is None or os.path.getmtime(p) > os.path.getmtime(best)):
                    best = p
            cand = best
        if not cand or not os.path.isfile(cand):
            raise ToolError("結果のファイルが見つかりません")
        if edir:
            e, c = os.path.normcase(os.path.realpath(edir)), os.path.normcase(os.path.realpath(cand))
            if not c.startswith(e.rstrip("\\/") + os.sep):
                raise ToolError("結果のファイルが想定の場所の外にあります")
        return cand

    def _prune(self, area, entry):
        """自動の測定が作った結果ファイルを、新しい self.keep 件だけ残して消す。entry["files"](自分が作った分の一覧)を更新する。
        対象 = 一覧にある名前 + (asr だけ)置き場所の中の `_auto` 付きの名前。名前は RESULT_NAME_RE に厳しく合うものだけ・
        置き場所の中の普通のファイルだけ(シンボリックリンク・フォルダは消さない)。名前は先頭が日時なので、並べ替えれば古い順"""
        edir = self.evals_dir(area)
        names = {n for n in entry.get("files") or [] if isinstance(n, str) and RESULT_NAME_RE.match(n)}
        if not edir or not os.path.isdir(edir):
            entry["files"] = sorted(names)
            return
        if area["id"] == "asr":
            try:
                names |= {n for n in os.listdir(edir) if RESULT_NAME_RE.match(n) and n.endswith("_auto.json")}
            except OSError:
                pass
        ordered = sorted(names)
        keep = ordered[-self.keep:] if self.keep > 0 else []
        real = os.path.normcase(os.path.realpath(edir))
        for n in ordered[:len(ordered) - len(keep)]:
            p = os.path.join(edir, n)
            try:
                if os.path.islink(p) or not os.path.isfile(p) or os.path.normcase(os.path.realpath(os.path.dirname(p))) != real:
                    continue
                os.remove(p)
            except OSError:
                continue
        entry["files"] = keep

    def _measure_area(self, area, t0):
        """1 つの領域を測る。-> 記録に入れる {"at", "file", "summary"}。None = 道具が無い。失敗は ToolError"""
        argv = self.commands(area)
        if not argv:
            return None
        out = self._run(argv)
        path = self._result_path(out, self.evals_dir(area), t0)
        try:
            if os.path.getsize(path) > MAX_RESULT_BYTES:
                raise ToolError("結果のファイルが大きすぎます")
            with open(path, "rb") as f:
                res = json.loads(f.read().decode("utf-8-sig"))
            if not isinstance(res, dict):
                raise ValueError("JSON の形が違います")
            summary = area["summarize"](res)
        except (OSError, ValueError) as e:
            raise ToolError("結果を読めませんでした(%s)" % str(e)[:ERR_TAIL])
        return {"at": int(self.clock() * 1000), "file": os.path.basename(path), "summary": summary}

    # ---- 見張り
    def start(self):
        if self.thread is None:
            self.thread = threading.Thread(target=self._loop, name="accuracy", daemon=True)
            self.thread.start()

    def close(self):
        self.closed = True
        self.wake.set()

    def run_now(self):
        """「今すぐ測る」。手が空くまで待って(窓・1 日 1 回は待たない)裏で測る。オフのときは False"""
        if not self._cfg().get("enabled"):
            return False
        self.force = True
        self.wake.set()
        return True

    def _loop(self):
        self.wake.wait(self.first_wait)
        while not self.closed:
            self.wake.clear()
            try:
                self.tick()
            except Exception as e:   # 想定外でも止めない(次の回でやり直す)
                self.state, self.message = "idle", "内部エラー: %s %s" % (e.__class__.__name__, str(e)[:200])
                self.log("精度の測定: " + self.message)
            self.wake.wait(FORCE_CHECK_EVERY if self.force else self.check_every)

    def waiting_reason(self, force):
        """手が空いていない理由(空 = 空いている)。busy() = 重い処理・編集のジョブ・まとめて実行(「今すぐ」でも待つ)。
        自動のときは、文字起こしの文書の最後の更新から QUIET_EDIT_SEC 空くのも待つ(今まさに校正している最中に測らない)"""
        try:
            why = self.busy()
        except Exception:
            why = None
        if why:
            return "動いている処理が終わるのを待っています(%s)" % why
        if not force:
            try:
                le = self.last_edit()
            except Exception:
                le = None
            if isinstance(le, (int, float)) and self.clock() - le < QUIET_EDIT_SEC:
                return "文書の編集が止まるのを待っています(あと %d 分)" % max(1, int((QUIET_EDIT_SEC - (self.clock() - le)) // 60) + 1)
        return ""

    def tick(self):
        """夜の窓で今日まだなら(または「今すぐ」なら)、手が空いているときに測る。-> 測ったときは {領域の id: "ok" / 理由 / None}"""
        cfg = self._cfg()
        now = self.clock()
        if not cfg.get("enabled"):
            self.force = False
            self.state, self.message = "off", ""
            return None
        force = self.force
        today = day_of(now)
        if not force and not (self.last.get("day") != today and in_window(now, cfg)):
            self.state, self.message = "idle", ""
            return None
        why = self.waiting_reason(force)
        if why:
            self.state, self.message = "waiting", why
            return None
        with self.lock:
            self.force = False
            return self._measure(today)

    def _measure(self, today):
        self.state, self.message = "running", ""
        t0 = self.clock()
        result, done = {}, True
        for area in AREAS:
            if self.closed:
                done = False
                break
            entry = dict(self.last["areas"].get(area["id"]) or {})
            try:
                got = self._measure_area(area, t0)
            except ToolError as e:   # 1 つの道具の失敗で止めない(その領域に理由を残して次へ)
                entry.update(error=str(e), errorAt=int(self.clock() * 1000))
                result[area["id"]] = str(e)
                self.log("精度の測定: %s: %s" % (area["label"], e))
            except Exception as e:
                entry.update(error="内部エラー: %s %s" % (e.__class__.__name__, str(e)[:ERR_TAIL]), errorAt=int(self.clock() * 1000))
                result[area["id"]] = entry["error"]
                self.log("精度の測定: %s: %s" % (area["label"], entry["error"]))
            else:
                if got is None:
                    result[area["id"]] = None
                else:
                    cur = entry.get("latest")
                    if isinstance(cur, dict) and cur.get("file") != got["file"]:
                        entry["prev"] = cur          # 直近 → 前回
                    entry["latest"] = got
                    if RESULT_NAME_RE.match(got["file"]) and got["file"] not in (entry.get("files") or []):
                        entry["files"] = list(entry.get("files") or []) + [got["file"]]   # 自分が作った分の一覧(整理の対象。「変わらず」で同じ名前が続くときは足さない)
                    try:
                        self._prune(area, entry)
                    except Exception as e:   # 整理に失敗しても測定は成功(次の回でやり直す)
                        self.log("精度の測定: %s: 古い結果ファイルを整理できませんでした(%s)" % (area["label"], e.__class__.__name__))
                    entry.pop("error", None)
                    entry.pop("errorAt", None)
                    result[area["id"]] = "ok"
            if result[area["id"]] is not None or entry:
                self.last["areas"][area["id"]] = entry
        if not self.closed:
            self._count_daily()                 # 入口の条件の「普段」「学習用」(道具の結果に無いので入口が数える)
        now = self.clock()
        self.last.update(ran=now, seconds=round(now - t0, 1))
        if done:
            self.last["day"] = day_of(t0)       # 1 日 1 回(途中で終了したときは記録しない = 次の起動でやり直す)
        self._save_state()
        self.state, self.message = "idle", ""
        self.log("精度の測定: 終わりました(%s)" % "・".join("%s %s" % (a["label"], "ok" if result.get(a["id"]) == "ok" else "なし" if result.get(a["id"]) is None else "失敗") for a in AREAS))
        return result

    def snapshot(self):
        cfg = self._cfg()
        areas = []
        for a in AREAS:
            e = self.last["areas"].get(a["id"]) or {}
            try:
                available = bool(self.commands(a))
            except Exception:
                available = False
            areas.append({"id": a["id"], "label": a["label"], "available": available, "latest": e.get("latest"), "prev": e.get("prev"),
                          "error": e.get("error") or "", "errorAt": e.get("errorAt")})
        ran = self.last.get("ran")
        state = "off" if not cfg.get("enabled") else self.state
        return dict(cfg, state=state, stateLabel=STATE_LABELS[state], message=self.message if state != "off" else "",
                    forced=bool(self.force), lastRun=int(ran * 1000) if isinstance(ran, (int, float)) else None, areas=areas,
                    goals=goals_of(self.last, extra=self._check_extra()))

    def _check_extra(self):
        """「確かめる」の答え(app/check/answers.jsonl)から入口の条件に足す数の関数(src/eval/check/goals.py。読めなければ None)"""
        try:
            from eval.check import goals as check_goals   # 同じ ⑤ の層。goals は GOALS を読むので、輪にならないようここで読む
            return check_goals.extra_from(self.data_dir)
        except Exception:
            return None
