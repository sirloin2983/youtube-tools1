# -*- coding: utf-8 -*-
"""旧い名前 ed_ytcap.名前 の転送だけの殻(役割で組み直す RS3-E6。2026-10-10。**RS5 で消す**)。

中身は human/proof/ytcap(元の配信の YouTube の字幕の候補)。
ed_ytcap.名前 の読み・書き・削除(テストの差し替え・unittest.mock の patch.object)を、下の _MOVED の持ち主へ回す(ytt/modfwd.py)。
新しい名前はここに書かない(持ち主の部品に書き、読む側は持ち主を `モジュール.名前` で呼ぶたびに読む)。
この殻が持つ名前は _MOVED・_moved_owner だけ(serve の名前の受付 _ED_MODULES には並べない)。
"""
from ytt import modfwd as _modfwd  # noqa: E402
from human.proof import ytcap as _ytcap  # noqa: E402

# 移した先のモジュール(serve.py の _ED_MODULES にも並べてある)。名前が重ならないことは test_names が確かめる
_MOVED = (_ytcap,)
_moved_owner = _modfwd.install(globals(), _MOVED, "ed_ytcap")
