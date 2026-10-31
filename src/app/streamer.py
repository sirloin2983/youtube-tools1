# -*- coding: utf-8 -*-
"""配信者の名前の当て(入口の POST api/ytt/streamer-guess の中身。PortalServer が Guesser を 1 つ作って呼ぶ)。

手順: 文書 → その文書の元の配信(.clip.json の source.videoId)→ 配信のチャンネル名(スタジオの一覧)→ prefs の当て
(app/prefs.guess_streamer = 覚えた名前・チャンネル名から ytt/colors で)。名前が分かれば字幕の既定の色も添える。
flow/colors_api に置かないのは、manage/cases と app/prefs を読むため(層の決まり)。
"""
import threading
import time

from manage.cases import cases as cases_mod
from ytt import colors as colors_mod
from app import prefs as prefs_mod

STUDIO_CH_SEC = 30.0   # スタジオのチャンネル名の一覧を覚える秒(Guesser.channel)


class Guesser:
    """root = リポジトリの作業の根(manage/cases.locations に渡す)・prefs = app/prefs の Prefs"""

    def __init__(self, root, prefs):
        self.root = root
        self.prefs = prefs
        self._ch, self._ch_lock = None, threading.Lock()   # (覚えた時刻, {動画 id: チャンネル名})

    def channel(self, video_id):
        """配信のチャンネル名(スタジオの一覧)か None。一覧は STUDIO_CH_SEC 秒覚える(10-30: ホームは描くたびに案件 8 本ぶん問い合わせ、
        1 本ごとに一覧を全部読むと 0.17 秒 × 8 本が重なって 1 本 1 秒になっていた。チャンネル名はめったに変わらない)"""
        now = time.monotonic()
        with self._ch_lock:
            if self._ch is None or now - self._ch[0] > STUDIO_CH_SEC:
                vids = cases_mod.read_studio(cases_mod.locations(self.root)["studio"])
                self._ch = (now, {k: str((v or {}).get("channel") or "").strip()[:120] for k, v in vids.items()})
            return self._ch[1].get(video_id) or None

    def guess(self, doc_id=None, video_id=None, channel=None):
        """-> {"ok", "name", "source", "hex", "channel"}。文書だけ分かれば、その文書の元の配信(.clip.json)・チャンネル(スタジオ)を調べる"""
        doc_id = doc_id if isinstance(doc_id, str) and len(doc_id) <= 64 else None
        video_id = video_id if isinstance(video_id, str) and len(video_id) <= 64 else None
        channel = channel.strip()[:120] if isinstance(channel, str) and channel.strip() else None
        if doc_id and not video_id:
            d = next((x for x in cases_mod.txindex.load(cases_mod.locations(self.root)["transcripts"]) if x["id"] == doc_id), None)
            src = ((d or {}).get("clip") or {}).get("source") or {}
            video_id = src.get("videoId") if isinstance(src.get("videoId"), str) else None
        if video_id and not channel:
            channel = self.channel(video_id)
        r = prefs_mod.guess_streamer(self.prefs, doc_id, video_id, channel,
                                     from_channel=lambda ch: (colors_mod.from_channel(ch) or {}).get("name"))
        hit = colors_mod.lookup(r["name"])["match"] if r["name"] else None
        return dict(r, ok=True, hex=hit["hex"] if hit else None, channel=channel)
