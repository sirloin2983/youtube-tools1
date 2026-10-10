# -*- coding: utf-8 -*-
"""旧い名前 ed_misc.名前 の転送だけの殻(役割で組み直す RS3-E7。2026-10-10。**RS5 で消す**)。

中身は manage/cases/handoff_io(clip-marker との連携・受け渡しの API)・human/proof/batch(フォルダの一括読み込み・文字起こし済みの範囲)・
human/proof/progress(進行度。次の段 D2 で消す予定)。.runtime の置き場所 runtime_path_dir は app の editor/ed_state(serve の名前で読む。殻からは読まない)。
ed_misc.名前 の読み・書き・削除(テストの差し替え・unittest.mock の patch.object)を、下の _MOVED の持ち主へ回す(ytt/modfwd.py)。
新しい名前はここに書かない(持ち主の部品に書き、読む側は持ち主を `モジュール.名前` で呼ぶたびに読む)。
この殻が持つ名前は _MOVED・_moved_owner・_add_moved だけ(ed_jobs の殻と同じ = serve の名前の受付 _ED_MODULES には並べない)。
"""
from ytt import modfwd as _modfwd  # noqa: E402
from manage.cases import handoff_io as _handoff_io  # noqa: E402
from human.proof import batch as _batch, progress as _progress  # noqa: E402

# 移した先のモジュール(serve.py の _ED_MODULES にも並べてある)。名前が重ならないことは test_names が確かめる
_MOVED = (_handoff_io, _batch, _progress)
_moved_owner = _modfwd.install(globals(), _MOVED, "ed_misc")


def _add_moved(mod):
    """上の層の持ち主を転送に足す(呼ぶのは app(serve)だけ。今は足す物は無い。ほかの殻と同じ形)"""
    global _MOVED, _moved_owner
    if mod not in _MOVED:
        _MOVED += (mod,)
        _moved_owner = _modfwd.install(globals(), _MOVED, "ed_misc")
