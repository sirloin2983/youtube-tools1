"""「確かめる」のカードの元の文書を、今の版の文字起こしで作り直す(夜の見回り)。

確かめるのカードは文書の機械の行から作るので、古い版(① records.output_old = OUTPUT_SINCE より前)で文字起こしした文書のカードは、
今の精度を確かめていることにならない。古い版の文書を、夜に 1 本ずつ今の設定で全体を認識し直す。
  道          編集の POST /api/rerun {target: whole, refresh: true}(画面の「全体を再認識」と同じ受付 rerun.validate_whole → rebuild_whole)。
              人の層(編集で直した行・確かめるで答えた話者・音のメモ・校正済み)は残る。前の状態は履歴(以前の版に戻す)・前の機械の出力は
              recognition.runs の kind "whole" に残る(元に戻せる)。印 = 文書の retranscribed.refresh。refresh のジョブは空いているときだけ動く級
              (flow/prio の later)で、入れたあとに文書が直されたら書かない
  いつ        精度の自動測定(eval/drill/accuracy)の見回りが、夜の窓(prefs の accuracy.nightFrom〜nightTo)・手が空いている
              (重い処理・まとめて実行・編集のジョブが無い)・文書の編集が 30 分止まっている・その日の測定が済んだ、ときに tick を呼ぶ。
              1 回の tick で 1 本入れる(入れたジョブが動いている間は手が空いていないので次は入らない)。1 晩に PER_NIGHT 本まで
  スイッチ    prefs の accuracy.retranscribe(既定オフ。本物の文書の機械の行を書き換えるため)
  対象        今のカードの元の文書のうち、古い版・元の動画がある・評価用でない(View.docs が外す + evalSet を見直す)物。
              誰の声(ソロ配信 voice:solo)の元を先に、あとはカードの多い文書から。同じ文書は MAX_TRIES 回まで(失敗し続ける文書を入れ続けない)
  記録        入口の作業データの retranscribe-state.json {night, count, tried{文書: {n, at}}, done[{tid, at, from}]}
"""
import os
import time

from pipeline.transcribe import records
from ytt import fsio
from . import sources

STATE_FILE = "retranscribe-state.json"
STATE_MAX = 1024 * 1024
PER_NIGHT = 5            # 1 晩に作り直す本数(切り抜き 1 本は GPU で 1 分ほど)
MAX_TRIES = 2            # 同じ文書を入れる回数の上限
FIRST = ("voice:solo",)  # 先に作り直すカードの出どころ
DONE_KEEP = 200


def night_of(now):
    """夜の窓をまたいでも同じになる「その晩」の名前(正午で切り替える)"""
    return time.strftime("%Y-%m-%d", time.localtime(now - 12 * 3600))


def has_media(doc):
    p = str(doc.get("sourcePath") or "")
    return bool(p) and not fsio.is_network_path(p) and os.path.isfile(p)


def targets(cards, view):
    """作り直す文書の id の並び(先の物から)。cards = sources.collect のカード"""
    docs = {t: d for t, _p, d in view.docs()}
    score = {}
    for c in cards:
        tid = (c.get("target") or {}).get("docId")
        d = docs.get(tid)
        if d is None:
            continue
        first, n = score.get(tid, (1, 0))
        score[tid] = (0 if "%s:%s" % (c.get("kind"), c.get("source")) in FIRST else first, n + 1)
    out = [t for t in score if docs[t].get("evalSet") is not True and records.output_old(docs[t]) and has_media(docs[t])]
    return sorted(out, key=lambda t: (score[t][0], -score[t][1], t))


def read_state(app_dir):
    d = fsio.read_json_or(os.path.join(app_dir, STATE_FILE), {}, max_bytes=STATE_MAX, kind=dict)
    return {"night": str(d.get("night") or ""), "count": d.get("count") if isinstance(d.get("count"), int) else 0,
            "tried": d.get("tried") if isinstance(d.get("tried"), dict) else {},
            "done": [x for x in d.get("done") or () if isinstance(x, dict)][-DONE_KEEP:]}


def tick(ctx, call, app_dir, now=None, log=None, collect=None):
    """1 本だけ作り直しを入れる。call(body) -> (HTTP の状態, JSON)(編集の POST /api/rerun)。-> 入れた文書の id か None。
    スイッチ・夜の窓・手が空いているかは呼び手(入口の精度の見回り)が見る"""
    now = time.time() if now is None else now
    log = log or (lambda msg: None)
    st = read_state(app_dir)
    night = night_of(now)
    if st["night"] != night:
        st.update(night=night, count=0)
    if st["count"] >= PER_NIGHT:
        return None
    cards, view = (collect or sources.collect)(ctx, None)
    docs = {t: d for t, _p, d in view.docs()}
    for tid in targets(cards, view):
        tr = st["tried"].get(tid) if isinstance(st["tried"].get(tid), dict) else {}
        if (tr.get("n") or 0) >= MAX_TRIES or tr.get("night") == night:
            continue
        st["tried"][tid] = {"n": (tr.get("n") or 0) + 1, "night": night, "at": int(now * 1000)}
        try:
            code, obj = call({"tid": tid, "target": "whole", "refresh": True})
        except Exception as e:   # 編集が動いていない: 数えずに次の見回りへ
            st["tried"][tid] = tr
            log("古い版の作り直し: 編集に頼めませんでした(%s)" % e.__class__.__name__)
            return None
        if code == 200:
            st["count"] += 1
            st["done"] = (st["done"] + [{"tid": tid, "at": int(now * 1000), "from": records.output_version(docs[tid])["version"]}])[-DONE_KEEP:]
            _write(app_dir, st, log)
            log("古い版の作り直し: %s を入れました(%s の文字起こし)" % (tid, records.output_version(docs[tid])["version"] or "版不明"))
            return tid
        log("古い版の作り直し: %s を断られました(%s)" % (tid, (obj or {}).get("error") if isinstance(obj, dict) else code))
    _write(app_dir, st, log)
    return None


def _write(app_dir, st, log):
    try:
        fsio.write_json(os.path.join(app_dir, STATE_FILE), st, indent=None)
    except OSError as e:
        log("古い版の作り直し: 記録を書けませんでした(%s)" % e.__class__.__name__)
