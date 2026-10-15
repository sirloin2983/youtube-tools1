"""「確かめる」の自動カットのカードの答えの記録(CUT-CARD。決定: plan/opt-eval.md の Q4 自動カットのカード)。

カードは 3 種類の出どころ(src/app/check/cut_sources.py の edge・gap・whole)。答えは記録するだけ:
  edge  切れ目 = good / early(早すぎ・言葉が切れる)/ late(遅すぎ・間が残る)/ keep(ここは切らない)
  gap   消した所 = ok(消してよい)/ keep(残すべき・笑い・反応など)
  whole 仕上がり = good / tempo(テンポが悪い)/ unnatural(不自然な所がある)
人の答えが自動カットの物差しの正解になる。文書(.json)と編集の内容(.edit.json)には触らない(反映の部品は何もしない)。
スイッチ enabled(): 環境変数 YTT_CHECK_CUT か、編集の設定 checkCutCards が真のときだけ出どころが出す(既定オフ)。
入口が import すると register される(server が import する)。
"""
import os

from ytt import schemas as _yschemas, settings as _settings
from . import apply   # 同じ human/check の兄弟(register・Refused)

SWITCH_ENV = "YTT_CHECK_CUT"
CHOICES = {
    "edge": ("good", "early", "late", "keep"),
    "gap": ("ok", "keep"),
    "whole": ("good", "tempo", "unnatural"),
}


def enabled():
    """カットのカードのスイッチ(既定オフ)。環境変数 YTT_CHECK_CUT が on 系、または編集の設定 checkCutCards が真なら有効"""
    if str(os.environ.get(SWITCH_ENV) or "").strip().lower() in ("1", "on", "true", "yes"):
        return True
    try:
        return _settings.load_settings().get("checkCutCards") is True
    except Exception:
        return False


def _checker(source):
    """出どころごとの答えの検査 -> 検査して整えた答え {choice}。違えば ValueError(400)"""
    choices = CHOICES[source]

    def check(answer):
        if not isinstance(answer, dict) or set(answer) != {"choice"} or answer.get("choice") not in choices:
            raise ValueError("答え(choice)は %s のどれかです" % "・".join(choices))
        return {"choice": answer["choice"]}
    return check


def _apply(ctx, card, answer):
    """答えを記録するだけ(文書・編集の内容は触らない)。-> applied {docId, recorded}"""
    tid = (card.get("target") or {}).get("docId")
    if not isinstance(tid, str) or not _yschemas.TID_RE.match(tid):
        raise apply.Refused("カードの文書を特定できません", 400, "bad_request")
    return {"docId": tid, "recorded": True}


def _revert(ctx, row):
    """Z。取り消す実物は無い(記録の取り消しだけ・apply.undo が書く)。-> {docId, reverted}"""
    ap = row.get("applied") or {}
    return {"docId": ap.get("docId"), "reverted": True}


for _src in CHOICES:
    apply.register("cut", _src, _apply, revert=_revert, check=_checker(_src))
