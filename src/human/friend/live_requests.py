"""友人のライブ配信の依頼と録画の結びつき(notes:docs/spec/friend.md の 2-15)。

依頼の受付(src/human/friend/intake.py)が配信中・配信前の URL の依頼を受け付けると、録画を始めて(入口の src/app/live.py の Live.submit_request →
src/flow/livesession.py の begin_request)ここに結びつけ、録画の候補の検出・自動の採用(src/flow/live_detect.py・src/pipeline/analyze/live_excite_worker.py)・
採用した切り抜きの書き出しのあと(src/flow/live_export.py の _handoff)・配信後のアーカイブからの追加(src/flow/live_archive.py)が、
この結びつきを見て友人の設定で動き、パックを友人へ届ける。

結びつきの記録(入口の作業データの live/requests.json)は ② flow/live_rules.RequestBook の 1 つ(入口 src/app/live.py が作る。友人の玄関と同じ)。
settings = 友人の設定(依頼の JSON の live)。範囲・既定・読み直し(clean_settings)も flow/live_rules.py。ここに残すのは受付の文の言葉と、入口の上限の数だけ。
"""
from flow.live_rules import KEEP_DAYS, MAX_ITEMS, RANGES, SENS, SETTINGS_DEFAULT, TEXT_MAX, clean_settings, settings_text  # noqa: F401

SENS_LABELS = {"high": "高", "normal": "普通", "low": "低"}
TOP_DEFAULT = 10        # 1 録画の自動の採用の上限の既定(依頼の欄 = アーカイブの top と同じ。notes:plan/done/f1-friend-pc.md 決めたこと 7。束の adopt.top の既定 3 とは別なので依頼の束に明示する。RS7-2 G2b)
MAX_ACTIVE = 2         # 友人のライブ配信の依頼を同時に録画する本数(ユーザー「今は同時に 2 本。あとで増やすかもしれない」)
MAX_SEC = 6 * 3600.0    # D-13(仮の数): 1 依頼の録画の上限(依頼から。超えたら入口が録画を止める = src/app/live.py の stop_long_requests)


def settings_label(s):
    """受付の一覧に出す 1 行"""
    return "ライブの設定: " + settings_text(s, SENS_LABELS)
