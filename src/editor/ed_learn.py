# -*- coding: utf-8 -*-
"""旧い名前 ed_learn.名前 の転送だけの殻(役割で組み直す RS3-E5c。2026-10-10。**RS5 で消す**)。

中身は pipeline/transcribe/replace(置換辞書の読み方と当て方)・human/proof/learn(人が直した内容からの学習・提案・採用と却下の記録・名簿)と
eval/drill/metrics(認識精度の測定・noSub と重なりの数え方・評価用の基準の記録。serve が _add_moved で足す = 殻は eval を読まない)。
設定の読み書きと鍵の検査は RS3-1 に ytt/settings へ、修正データの書き出しとデータの保管は 0.68.0 で消した。
ed_learn.名前 の読み・書き・削除(テストの差し替え・unittest.mock の patch.object)を、下の _MOVED の持ち主へ回す(ytt/modfwd.py)。
新しい名前はここに書かない(持ち主の部品に書き、読む側は持ち主を `モジュール.名前` で呼ぶたびに読む)。
この殻が持つ名前は _MOVED・_moved_owner・_add_moved だけ(ed_jobs・ed_speakers の殻と同じ = serve の名前の受付 _ED_MODULES には並べない)。
"""
from ytt import modfwd as _modfwd  # noqa: E402
from pipeline.transcribe import replace as _replace  # noqa: E402
from human.proof import learn as _learn  # noqa: E402

# 移した先のモジュール(serve.py の _ED_MODULES にも並べてある)。名前が重ならないことは test_names が確かめる
_MOVED = (_replace, _learn)
_moved_owner = _modfwd.install(globals(), _MOVED, "ed_learn")


def _add_moved(mod):
    """ed_learn が読まない層の持ち主(④ の eval/drill/metrics の norm_cer・doc_metrics・all_metrics・record_baseline ほか)を転送に足す。
    呼ぶのは app(serve)だけ(殻から eval を import しない = 層の向きを守る)"""
    global _MOVED, _moved_owner
    if mod not in _MOVED:
        _MOVED += (mod,)
        _moved_owner = _modfwd.install(globals(), _MOVED, "ed_learn")
