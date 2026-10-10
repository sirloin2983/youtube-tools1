# -*- coding: utf-8 -*-
"""旧い名前 ed_alt.名前 の転送だけの殻(役割で組み直す RS3-E6。2026-10-10。**RS5 で消す**)。

中身は human/proof/alt(2つ目のエンジンとの食い違いの候補)。疑似の認識の行 `_alt_fake` は eval/fake/fake_asr(serve が _add_moved で足す = 殻は ④ を読まない)。
ed_alt.名前 の読み・書き・削除(テストの差し替え・unittest.mock の patch.object)を、下の _MOVED の持ち主へ回す(ytt/modfwd.py)。
新しい名前はここに書かない(持ち主の部品に書き、読む側は持ち主を `モジュール.名前` で呼ぶたびに読む)。
この殻が持つ名前は _MOVED・_moved_owner・_add_moved だけ(ed_jobs・ed_store の殻と同じ = serve の名前の受付 _ED_MODULES には並べない)。
"""
from ytt import modfwd as _modfwd  # noqa: E402
from human.proof import alt as _alt  # noqa: E402

# 移した先のモジュール(serve.py の _ED_MODULES にも並べてある)。名前が重ならないことは test_names が確かめる
_MOVED = (_alt,)
_moved_owner = _modfwd.install(globals(), _MOVED, "ed_alt")


def _add_moved(mod):
    """ed_alt が読まない上の層の持ち主(④ の eval/fake/fake_asr の _alt_fake)を転送に足す。呼ぶのは app(serve)だけ(殻は層 human なので eval を import しない = 層の向きを守る)"""
    global _MOVED, _moved_owner
    if mod not in _MOVED:
        _MOVED += (mod,)
        _moved_owner = _modfwd.install(globals(), _MOVED, "ed_alt")
