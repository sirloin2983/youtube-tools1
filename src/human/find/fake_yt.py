"""① 配信の検索 rank.py の疑似 YouTube Data API(STUDIO_FAKE=1 のときだけ使う。ネットワークなし。e2e と画面の確かめが使う)。

チャンネル・チャンネルの欄・アップロード一覧(150 本)・動画の詳しい情報・配信中の枠を、ハッシュから決まった形で作る。
本来は ⑤ eval/fake/ の仕事だが、③ は ⑤ を読めないので同じフォルダに分けた(疑似の口を差し込む仕組みは OPT2)。
rank.yt_get だけが呼ぶ(fake_get に「配信中」の見回りの本数を渡す)。
"""
import hashlib
from datetime import datetime, timedelta, timezone

from ytt.errors import ApiError

_FAKE_WORDS = ["雑談", "ゲーム", "歌枠", "マイクラ", "コラボ", "ホラー"]
_FAKE_INDEX = {}   # 疑似の動画ID → 動画(疑似動画IDからは元のチャンネルが分からないので、ここから引く)


def _h(s, mod=1000003):
    return int(hashlib.sha1(s.encode()).hexdigest()[:8], 16) % mod


def fake_channel_id(ref):
    return "UC" + hashlib.sha1(ref.lower().encode()).hexdigest()[:22].replace("0", "a")[:22].ljust(22, "x")


def fake_video(cid, n):
    """チャンネル cid の n 本目(新しい順)の動画。日付は現在から遡る(2日に1本ぐらい)。"""
    vid = "f" + hashlib.sha1(("%s/%d" % (cid, n)).encode()).hexdigest()[:10]
    when = datetime.now(timezone.utc).replace(hour=12, minute=0, second=0, microsecond=0) - timedelta(days=n * 2 + _h(vid, 2), hours=_h(vid + "h", 5))
    title = "【%s】%s配信 #%d" % (_FAKE_WORDS[_h(vid, 6)], _FAKE_WORDS[_h(vid + "x", 6)], n)
    live = _h(vid + "l", 10) < 8
    return {"id": vid, "publishedAt": when.strftime("%Y-%m-%dT%H:%M:%SZ"), "title": title, "views": _h(vid + "v", 900000) + 100, "live": live, "channelId": cid,
            "dur": ("PT%dH%dM%dS" % (1 + _h(vid, 3), _h(vid, 50), _h(vid, 50))) if live else "PT%dM%dS" % (_h(vid, 9), _h(vid, 50))}


def fake_get(path, params, live_page):
    """YouTube Data API の疑似の答え(channels・channelSections・playlistItems・videos)。live_page = 「配信中」のタブの見回りの本数(rank.LIVE_PAGE)"""
    if path == "channels":
        items = []
        if "forHandle" in params:
            ref = params["forHandle"]
            if "nothere" in ref:
                return {"items": []}
            ids = [fake_channel_id(ref)]
            names = {ids[0]: ref.lstrip("@")}
        else:
            ids = params["id"].split(",")
            names = {i: "ch-" + i[2:8] for i in ids}
        for i in ids:
            items.append({"id": i, "snippet": {"title": names.get(i, i)}, "contentDetails": {"relatedPlaylists": {"uploads": "UU" + i[2:]}}, "statistics": {"subscriberCount": "100000"}})
        return {"items": items}
    if path == "channelSections":
        cid = params["channelId"]
        ids = [fake_channel_id("%s-m%d" % (cid, k)) for k in range(4)]
        return {"items": [{"snippet": {"type": "multipleChannels"}, "contentDetails": {"channels": ids}}, {"snippet": {"type": "allPlaylists"}}]}
    if path == "playlistItems":
        cid = "UC" + params["playlistId"][2:]
        _fake_register(cid)
        start = int(params.get("pageToken") or 0)
        items = []
        if params.get("maxResults") == live_page and not start:   # 「配信中」のタブの見回り(先頭の数本だけ): 疑似の配信中・予定を先頭に足す
            items = [{"contentDetails": {"videoId": v["id"]}} for v in fake_live(cid)]
            items += [{"contentDetails": {"videoId": fake_video(cid, n)["id"]}} for n in range(live_page - len(items))]
            return {"items": items}
        for n in range(start, min(start + 50, 150)):
            v = fake_video(cid, n)
            items.append({"contentDetails": {"videoId": v["id"], "videoPublishedAt": v["publishedAt"]}})
        out = {"items": items}
        if start + 50 < 150:
            out["nextPageToken"] = str(start + 50)
        return out
    if path == "videos":
        items = []
        for vid in params["id"].split(","):
            v = _FAKE_INDEX.get(vid)
            if not v:
                continue
            det = {"duration": v["dur"]}
            item = {"id": vid, "snippet": {"title": v["title"], "description": "説明文 " + v["title"], "channelId": v["channelId"], "channelTitle": "ch-" + v["channelId"][2:8],
                                           "publishedAt": v["publishedAt"], "thumbnails": {"medium": {"url": "https://i.ytimg.com/vi/%s/mqdefault.jpg" % vid}}},
                    "statistics": {"viewCount": str(v["views"]), "likeCount": str(v["views"] // 30), "commentCount": str(v["views"] // 200)}, "contentDetails": det}
            item["snippet"]["liveBroadcastContent"] = v.get("lbc", "none")
            if v.get("lsd"):   # 疑似の配信中・予定(fake_live)
                item["liveStreamingDetails"] = v["lsd"]
            elif v["live"]:
                st = datetime.strptime(v["publishedAt"], "%Y-%m-%dT%H:%M:%SZ")
                item["liveStreamingDetails"] = {"actualStartTime": v["publishedAt"], "actualEndTime": (st + timedelta(hours=2)).strftime("%Y-%m-%dT%H:%M:%SZ")}
            items.append(item)
        return {"items": items}
    raise ApiError("upstream", "fake: unknown " + path, 502)


def _fake_register(cid):
    for n in range(150):
        v = fake_video(cid, n)
        _FAKE_INDEX[v["id"]] = v


def fake_live(cid):
    """チャンネル cid の疑似の配信中・予定(チャンネルごとに決まった形: 配信中 / 数時間後の予定 / 30時間後の予定(出さない) / メン限の配信中 / なし)。
    時刻は今の「時」の頭から決める(同じ時間の中なら何度呼んでも同じ)"""
    k = _h(cid + "/live", 6)
    if k > 3:
        return []
    base = datetime.now(timezone.utc).replace(minute=0, second=0, microsecond=0)
    vid = "L" + hashlib.sha1((cid + "/live").encode()).hexdigest()[:10]
    fmt = "%Y-%m-%dT%H:%M:%SZ"
    title = "【%s】%s配信" % (_FAKE_WORDS[_h(vid, 6)], _FAKE_WORDS[_h(vid + "x", 6)])
    if k in (0, 3):
        st = base - timedelta(minutes=20 + _h(vid, 90))
        lsd = {"actualStartTime": st.strftime(fmt), "concurrentViewers": str(500 + _h(vid + "c", 40000))}
        lbc = "live"
        if k == 3:
            title = "【メン限】" + title
    else:
        st = base + timedelta(hours=1 + _h(vid, 5) if k == 1 else 30)
        lsd, lbc = {"scheduledStartTime": st.strftime(fmt)}, "upcoming"
    v = {"id": vid, "publishedAt": st.strftime(fmt), "title": title, "views": 0, "live": False, "channelId": cid, "dur": "P0D", "lbc": lbc, "lsd": lsd}
    _FAKE_INDEX[vid] = v
    return [v]
