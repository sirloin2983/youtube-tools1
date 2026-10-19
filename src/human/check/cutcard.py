"""「確かめる」の自動カットのカードの答えの記録(CUT-CARD。決定: plan/opt-eval.md の Q4 自動カットのカード)。

カードは 3 種類の出どころ(src/app/check/cut_sources.py の edge・gap・whole)。答えは記録するだけ:
  edge  切れ目 = good / early(早すぎ・言葉が切れる)/ late(遅すぎ・間が残る)/ keep(ここは切らない)
  gap   消した所 = ok(消してよい)/ keep(残すべき・笑い・反応など)
  whole 仕上がり = good / tempo(テンポが悪い)/ unnatural(不自然な所がある)
人の答えが自動カットの物差しの正解になる。文書(.json)と編集の内容(.edit.json)には触らない(反映の部品は何もしない)。
スイッチ enabled(): 既定オン(ユーザー決定 3-64 (cc1) B)。編集の設定 checkCutCardsOn を明示でオフにしたか、環境変数 YTT_CHECK_CUT が off 系のときだけ出さない。
入口が import すると register される(server が import する)。
"""
import os

from ytt import settings as _settings
from . import _doc, apply   # 同じ human/check の兄弟(register・Refused・カードの文書・答えの検査)

SWITCH_ENV = "YTT_CHECK_CUT"
CHOICES = {
    "edge": ("good", "early", "late", "keep"),
    "gap": ("ok", "keep"),
    "whole": ("good", "tempo", "unnatural"),
}


SETTING = "checkCutCardsOn"   # 編集の設定の鍵(既定オン)。既定オフのころの鍵 checkCutCards は読まない = 前に保存されたオフは既定オンに読み替える


def enabled():
    """カットのカードのスイッチ(既定オン)。環境変数 YTT_CHECK_CUT が on 系なら出す・off 系(0・off・false・no)なら出さない。
    それ以外は編集の設定 checkCutCardsOn を明示でオフにしたときだけ出さない"""
    v = str(os.environ.get(SWITCH_ENV) or "").strip().lower()
    if v in ("1", "on", "true", "yes"):
        return True
    if v in ("0", "off", "false", "no"):
        return False
    try:
        return _settings.load_settings().get(SETTING) is not False
    except Exception:
        return True


def _apply(ctx, card, answer):
    """答えを記録するだけ(文書・編集の内容は触らない)。-> applied {docId, recorded}"""
    return {"docId": _doc.doc_id(card, "カードの文書を特定できません"), "recorded": True}


def _revert(ctx, row):
    """Z。取り消す実物は無い(記録の取り消しだけ・apply.undo が書く)。-> {docId, reverted}"""
    ap = row.get("applied") or {}
    return {"docId": ap.get("docId"), "reverted": True}


for _src in CHOICES:
    apply.register("cut", _src, _apply, revert=_revert, check=_doc.choice(CHOICES[_src], only=True))
