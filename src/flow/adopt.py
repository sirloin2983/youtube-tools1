"""② 採用の口(RS8 B3-2 の G1a。2026-10-11)。③ のスタジオの台帳(human/review/store の Store.adopt_marks)が、採用の規則 F-5
(① pipeline/analyze/adopt.py)を直に読まずに済む動詞。保存・ロック・学習の記録は呼ぶ側(③)。

- `check(ranges, top)` : 区間と上限の検査 -> 丸めた区間。② が足すこと = 理由を ApiError 400 bad_request にそろえる
  (スタジオの「上位 n 本を採用」・まとめて実行・友人の依頼へ、そのまま返せる形)
- `pick(video, want, top)` : 配信 1 本に F-5 を当てる -> ① の結果(採る印をつけたマークの一覧と選んだ id)。② が足すこと =
  配信の種類で通すかを決める(kind live の録画は F-5 を通さない = 解析していないので自動マークが無い・依頼の時刻は YouTube の配信の秒)・
  区間の終わりを配信の長さで切る(video の duration)・① の理由を ApiError 400 bad_request に
② の採用の段(flow/run.py の _step_adopt)は今のまま HTTP の /api/video/request-marks を通す(直に呼ぶ形は B3-4 のあと)。
"""
from pipeline.analyze import adopt as _adopt
from ytt import yturl
from ytt.errors import ApiError


def check(ranges, top):
    """区間と上限の検査 -> [(開始, 終了), …](小数 1 桁)。だめなら ApiError 400 bad_request"""
    try:
        return _adopt.check_args(ranges, top)
    except ValueError as e:
        raise ApiError("bad_request", str(e), 400)


def pick(video, want, top):
    """配信 1 本(ytt/marks の形のマークを持つ辞書。変えない)に F-5 を当てる。want = check の区間。
    -> {"marks", "rangeIds", "humanIds", "autoIds", "added"}(pipeline/analyze/adopt.adopt)。kind live・区間が配信の外などは ApiError 400"""
    if video.get("kind") == "live":
        raise ApiError("bad_request", yturl.LIVE_NO_ANALYZE, 400)
    try:
        return _adopt.adopt(video["marks"], want, top, video.get("duration"))
    except ValueError as e:
        raise ApiError("bad_request", str(e), 400)
