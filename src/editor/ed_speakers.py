# -*- coding: utf-8 -*-
"""旧い名前 ed_speakers.名前 の転送だけの殻(役割で組み直す RS2-9。2026-10-10。**RS5 で消す**)。

中身は pipeline/transcribe/diarize(話者判別の計算・判別の記録・声の特徴と照らし合わせ)と human/proof/speakers(判別の結果を文書へ・
判別のジョブ・空の行の下書き・自動の判別・声を覚える・字幕の見た目)。疑似の diarize_fake・embed_fake は eval/fake/fake_asr(serve が _add_moved で足す)。
ed_speakers.名前 の読み・書き・削除(テストの差し替え・unittest.mock の patch.object・dev/eval_speakers の DIAR_DIR)を、下の _MOVED の持ち主へ回す(ytt/modfwd.py)。
新しい名前はここに書かない(持ち主の部品に書き、読む側は持ち主を `モジュール.名前` で呼ぶたびに読む)。
この殻が持つ名前は _MOVED・_moved_owner・_add_moved だけ(ed_jobs の殻と同じ = serve の名前の受付 _ED_MODULES には並べない)。
"""
from ytt import modfwd as _modfwd  # noqa: E402
from pipeline.transcribe import diarize as _diarize  # noqa: E402
from human.proof import speakers as _speakers  # noqa: E402

# 移した先のモジュール(serve.py の _ED_MODULES にも並べてある)。名前が重ならないことは test_names が確かめる
_MOVED = (_diarize, _speakers)
_moved_owner = _modfwd.install(globals(), _MOVED, "ed_speakers")


def _add_moved(mod):
    """ed_speakers が読まない層の持ち主(④ の疑似 eval/fake/fake_asr の diarize_fake・embed_fake)を転送に足す。呼ぶのは app(serve)だけ
    (殻から eval を import しない = 層の向きを守る)"""
    global _MOVED, _moved_owner
    if mod not in _MOVED:
        _MOVED += (mod,)
        _moved_owner = _modfwd.install(globals(), _MOVED, "ed_speakers")
