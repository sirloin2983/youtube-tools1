"""ショート(学習用データ)の文書の下ごしらえ(10-25 ユーザー「読みのカードと この行は声ですか のカードを ショートから作る」)。
10-31: 読みのカード(read:alt)と「この行は声ですか」(speech:diar)は消した(Haas に替えるため)。read:alt のためだけだった 2 つ目のエンジンの聞き直しの段も消した
(裏で重い読みを頼むので CPU と GPU を無駄に使う)。判別の段は残す(誰の声のカードが使う)。前の記録の alt の欄は読み飛ばす。

文字起こしが済んだショートの文書に、手が空いているとき 1 本ずつ(1 回の見回りで 1 つ)「編集」のジョブを頼む:
  1. 話者の判別(人数は決めない・配信者の名前を渡す・覚えた声との照らし合わせはしない)= 声の区間。
     分かれた話者は誰の声のカードでは行の多い話者(配信者)の行だけ使う(flow/voicematerial.main_speaker)
頼んだ物は <app>/check/short-jobs.json に覚え、2 度は頼まない(頼めなかった物も理由を覚えて飛ばす)。
手が空いているか・YouTube の取り込みに合間を譲るのは、学習用データの文字起こし(voicefill)と同じ(入口が busy で渡す)。評価用の写しは頼まない。スイッチ ENABLED。
"""
import os
import time

from ytt import fsio
from . import voice_solo as _solo, voicefill as _fill

ENABLED = True
STATE_NAME = "short-jobs.json"
STEPS = ("diar",)   # 10-31 に alt(2 つ目のエンジンの聞き直し)を外した


def _path(app_dir):
    return os.path.join(app_dir, "check", STATE_NAME)


def tick(view, app_dir, call, busy, log, now=None):
    """1 回分: 下ごしらえのまだ無いショートの文書に 1 つ頼む -> 頼んだ (文書, 段) か None。call(path, body) -> ジョブの id(失敗は例外)"""
    if not ENABLED or busy():
        return None
    st = fsio.read_json_or(_path(app_dir), {}, kind=dict)
    for tid, path, doc in view.docs(need_media=False):
        src = doc.get("sourcePath")
        if not _fill.in_learn_dir(src) or _fill.eval_like(src) or not os.path.isfile(str(src or "")) or not doc.get("segments"):
            continue
        rec = st.setdefault(tid, {})
        step = next((s for s in STEPS if s not in rec), None)
        if step is None:
            continue
        who, _song = _solo._solo_of(path, doc)
        try:
            body = {"tid": tid, "numSpeakers": 0, "names": [who] if who else [], "recognize": False}   # 人数は決めない(1 人の指定は判別しない = 声の区間ができない)
            rec[step] = {"job": call("/api/diarize", body)}
        except Exception as e:   # noqa: BLE001  (頼めなかった = 理由を覚えて飛ばす)
            rec[step] = {"error": "%s: %s" % (e.__class__.__name__, str(e)[:160])}
        rec[step]["at"] = int(time.time() if now is None else now)
        os.makedirs(os.path.dirname(_path(app_dir)), exist_ok=True)
        fsio.write_json(_path(app_dir), st, indent=None)
        left = sum(1 for t, _p, d in view.docs(need_media=False) if _fill.in_learn_dir(d.get("sourcePath")) and any(s not in (st.get(t) or {}) for s in STEPS))
        log("ショートのカードの下ごしらえ: %s の%sを頼みました(残り %d 本)%s"
            % (os.path.basename(str(src)), "話者の判別", left,
               "" if "job" in rec[step] else " — 頼めませんでした " + rec[step]["error"]))
        return tid, step
    return None
