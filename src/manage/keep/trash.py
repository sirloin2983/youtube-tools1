# -*- coding: utf-8 -*-
"""④ データの keep: 動画と一緒にごみ箱フォルダへ動かす途中のファイル(何を一緒に動かすか)。

移す・戻す・記録の動作は ytt/trashbin の 1 か所(to_trash・put_back・record。① の録画の部品と友人のアプリも同じ物を使う)。
片付けの move(manage/keep/cleanup.Cleanup)と案件の「要らない」(manage/cases/cases.discard_clip。友人の「要らない」も)がそれを呼ぶ。
置き場所は ごみ箱\\<日付>\\<種類>\\<名前>\\(作業用 の物は その中の 作業用\\)。どのごみ箱フォルダかは Cleanup.trash_for(動画と同じドライブ)。
"""
import os

from ytt import schemas

SIDECARS = (".clip.json", ".edit.json", ".transcript.json", ".cut-plan.json", ".srt", "_edit.mp4", "_edit.clip.json")
# ↑ 動画と同じ名前で持つ途中のファイル(片付け・評価用のフォルダの整理・「要らない」が動画と一緒に動かす。使うのは ④ だけ)


def existing_sidecars(media_path):
    """動画の途中のファイル(SIDECARS)のうち、あるもの(作業用/ と動画の隣)"""
    return [p for suf in SIDECARS for p in schemas.sidecar_candidates(media_path, suf) if os.path.isfile(p)]
