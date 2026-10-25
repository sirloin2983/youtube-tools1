"""YouTube の取得の列(10-25。ユーザー「取り方 1 と 2 を統一しよう」「取得する配信を選ぶ段階で効率化できるはず」)。

研究(overlap-research の m2)と誰の声の材料(voicefetch)が別々に YouTube へ問い合わせていたのを、入口のこの列 1 本にまとめる。
置き場 <app>/check/yt-queue/:
  req/<id>.json        研究の頼み {"id", "purpose": "research", "kind": "info"|"audio"|"list", "priority", "hint": {"channel", "title"}, ...}
                       info: "urls"(10 本まで。説明欄など)/ audio: "url", "section": [始め, 終わり] か null / list: "url", "items" /
                       chat: "url"(チャットのリプレイ。長い配信は問い合わせが多いので研究が頼む物だけ)/
                       subs: "url"(自動字幕だけ。研究が手元のショートの文字と突き合わせて ?t= の無い候補の位置を出す = 全体の音を取らずに済む)
  done/<id>.json       結果 {"id", "state": "done"|"error", "error", "at", "infos" | "file" + "info" | "entries"}。音は done/<id>.<拡張子>。
                       読む側が消す(DONE_DAYS 日残っていれば列が消す)
  candidates.json      研究が置く候補 = 友人のショートの元の配信 [{"video", "t"(?t= の秒か null), "channel", "title", "uploadDate", "research"(研究に効く度合い 0〜1)}]
  state.json           列の状態(最後に取った時刻・側・間隔・API の使用量)。ready.json = 列が動いている印(研究はこれを見て自分の問い合わせをやめる)
選び方(1 回に 1 本・INTERVAL 時間に 1 本。10-25 ユーザー: 研究と声を交互に回すのはやめた): 全部の頼みを 1 つの一覧(plan)で点を付け、いちばん高い 1 本。
  候補 = 研究(research)+ 声(日本の対象のメンバーのソロと見える題名で、配信の材料が TARGET 本に届かない・取った月と違う)− 区間の長さ。
  研究の頼み = 種類の点(REQ_BASE。字幕・動画の情報 = あとの音の取得を短くできる軽い物は高く)+ 声 + priority − 区間の長さ。
  声だけ = 友人のショートの元(候補)に無いメンバーの材料の足りなさ(voicefetch.tick で RSS・一覧から)。
  取る区間 = 候補の ?t= の前 AROUND[0] 秒〜後 AROUND[1] 秒(研究の 2 段の探し方に足りる幅)。声の材料もその区間から(voice-inbox → voicefetch.intake が 4 分に)。
  info の頼みは、YouTube Data API のキーがあれば公式の窓口(ytt/ytapi。1 日 API_DAILY まで・50 本ずつ)で読み、枠を使わない。無ければ yt-dlp(枠を使う)。
  キーの値は読まない・出さない(ytapi が見出しで送る。ここは有無と成否だけ)。
決まり(研究の今の決まりを 1 か所に): cookie なし・bot 判定やログインを求められたらその日は止め、翌日から間隔を LADDER で伸ばす・
  友人のライブ中と処理中は休む(呼び手の busy)・再起動で途中の物は次に取り直す(done の .part を消す・頼みは done が書けるまで残る)。
使い道の束(10-25 ユーザー「当たりでも外れでも使える物は全部使う」): 音を取る問い合わせの中で、動画の情報(説明欄・チャプター・よく見られている場面の山)と
  日本語の自動字幕も keep/<動画>/ に小さく残す(bundle)。結果の info.bundle に場所。分析(区間・編集カット・同時発話・置換辞書の候補・BGM)は研究。
  keep は DONE_DAYS 日で消す(研究が keep/<動画>/hold を置いた物は残す)。
切り替えの前後で二重に取らないよう、研究の古い道の印 yt-slot.json(voicefetch.slot_free)も見て、取ったら書く。
"""
import datetime
import json
import os
import re
import shutil
import time

from flow import voicematerial as _vm
from ytt import fsio, ytapi as _ytapi
from ytt.errors import ApiError
from . import voicefetch as _vf

ENABLED = True
DIR_NAME = "yt-queue"
INTERVAL = 1.0                       # 時間に 1 本(既定。判定に当たった翌日から LADDER で伸ばす)
LADDER = [1.0, 1.5, 2.0, 3.0, 4.0, 6.0]
AROUND = (300, 600)                  # 候補の ?t= の前 5 分〜後 10 分を取る(研究の今の幅)
API_DAILY = 2000                     # 列が 1 日に使う YouTube Data API の量の上限(1 日 10,000 をスタジオと分け合う)
DONE_DAYS = 3
SERVED_KEEP = 5000   # 済んだ頼みの id を覚える数
STAGE = ".dl"        # 取っている途中の音の置き場(done/.dl/。済んだら done へ移す = 止まっても途中の音が done に残らない)
ID_RE = re.compile(r"^[A-Za-z0-9_-]{1,64}\Z")
URL_RE = re.compile(r"^https://(www\.|m\.)?(youtube\.com|youtu\.be)/[\w\-./?=&%:@+]{1,300}\Z")
KINDS = ("info", "audio", "list", "subs", "chat")


def qdir(app_dir, *sub):
    return os.path.join(app_dir, "check", DIR_NAME, *sub)


def _state(app_dir):
    return fsio.read_json_or(qdir(app_dir, "state.json"), {}, kind=dict)


def _save(app_dir, st):
    """状態を書く。済んだ頼みの印(served)は、書いてある物と合わせる(_write_done が先に書いた印を、手元の古い状態で消さない)"""
    os.makedirs(qdir(app_dir), exist_ok=True)
    on_disk = _state(app_dir).get("served") or []
    st["served"] = list(dict.fromkeys(list(on_disk) + list(st.get("served") or [])))[-SERVED_KEEP:]
    fsio.write_json(qdir(app_dir, "state.json"), st, indent=None)


def requests(app_dir):
    """研究の頼み(形の正しい物だけ。done がある物は済み)-> [頼み](priority の高い順 → 頼んだ順)"""
    out = []
    served = set(_state(app_dir).get("served") or [])
    try:
        names = sorted(os.listdir(qdir(app_dir, "req")))
    except OSError:
        return out
    for n in names:
        if not n.endswith(".json"):
            continue
        rid = n[:-5]
        p = qdir(app_dir, "req", n)
        if not ID_RE.match(rid) or os.path.exists(qdir(app_dir, "done", rid + ".json")) or rid in served:
            continue
        r = fsio.read_json_or(p, {}, kind=dict)
        if r.get("kind") not in KINDS:
            continue
        urls = [r.get("url")] if r.get("kind") in ("audio", "list", "subs", "chat") else (r.get("urls") or [])[:10]
        if not urls or not all(isinstance(u, str) and URL_RE.match(u) for u in urls):
            continue
        try:
            at = os.path.getmtime(p)
        except OSError:
            continue
        out.append(dict(r, id=rid, urls=urls, _at=at))
    return sorted(out, key=lambda r: (-_vm.num(r.get("priority")), r["_at"]))


def _video_of(url):
    m = re.search(r"(?:v=|youtu\.be/|/live/|/shorts/)([A-Za-z0-9_-]{11})", url or "")
    return m.group(1) if m else None


def candidates(app_dir):
    """研究が置いた候補(友人のショートの元の配信)"""
    d = fsio.read_json_or(qdir(app_dir, "candidates.json"), [], kind=list)
    return [c for c in d if isinstance(c, dict) and _vf.VIDEO_RE.match(str(c.get("video") or ""))]


def score(c, chan_of, counts, vstate, done_videos):
    """候補の点 -> (研究, 声, 安さの引き)。声 = 日本の対象のメンバーのソロと見える題名で、配信の材料が足りない・取った月と違う"""
    if c["video"] in done_videos:
        return 0.0, 0.0, 0.0
    res = max(0.0, min(1.0, _vm.num(c.get("research"))))
    who = chan_of.get(str(c.get("channel") or "")) or (_vm.member(c.get("streamer")) if _vm.member(c.get("streamer")) in chan_of.values() else None)
    voice = 0.0
    title = str(c.get("title") or "")
    if who and not _vm.song_title(title) and not _vm.COLLAB_RE.search(title) and not _vf.SHORT_RE.search(title):
        have = _vf._have(who, counts, vstate)
        months = {x.get("month") for x in _vf._got(vstate.get(who))}
        month = (lambda d: d[:4] + "-" + d[4:6] if len(d) >= 6 else "")(str(c.get("uploadDate") or ""))
        if have < _vf.TARGET and not (month and month in months):
            voice = (_vf.TARGET - have) / float(_vf.TARGET)
    span = (AROUND[0] + AROUND[1]) if c.get("t") is not None else 3 * 3600
    return res, voice, span / 3600.0 * 0.2


def _req_voice(q, chan_of, counts, vstate):
    """研究の audio の頼みが声にも効くか(hint の streamer か channel が、配信の材料が TARGET 本に届かない日本の対象のメンバー)"""
    if q.get("kind") != "audio":
        return False
    hint = q.get("hint") if isinstance(q.get("hint"), dict) else {}
    who = chan_of.get(str(hint.get("channel") or "")) or _vm.member(hint.get("streamer"))
    if not who or who not in chan_of.values() or _vm.song_title(str(hint.get("title") or "")):
        return False
    return _vf._have(who, counts, vstate) < _vf.TARGET


def fill_candidates(app_dir, now, log):
    """候補の空の欄(channel・title・uploadDate。研究は持っていない)を API で埋めて state の meta に覚える(枠は使わない・1 日 API_DAILY まで)。
    -> 埋めた数。キーが無い・断られた日は埋めない(点は streamer だけで付ける)"""
    st = _state(app_dir)
    today = datetime.date.fromtimestamp(now).isoformat()
    meta = st.get("meta") if isinstance(st.get("meta"), dict) else {}
    ids = [c["video"] for c in candidates(app_dir) if not c.get("title") and c["video"] not in meta]
    n = 0
    while ids and _api_left(st, today) > 0 and st.get("apiOff") != today:
        batch, ids = ids[:50], ids[50:]
        try:
            infos = _info_api(batch)
        except ApiError as e:
            if e.code in _ytapi.FATAL:
                st["apiOff"] = today
                log("YouTube の取得の列: API を使えないので、候補の題名は埋めません(%s)" % e.code)
            break
        _api_count(st, today, 1)
        for it in infos:
            meta[it["id"]] = {"channel": it.get("channel_id"), "title": it.get("title"), "uploadDate": it.get("upload_date")}
            n += 1
        for v in batch:
            meta.setdefault(v, {})   # 消された・非公開 = 空で覚える(もう読まない)
    st["meta"] = dict(list(meta.items())[-3000:])
    _save(app_dir, st)
    return n


def _merged(c, meta):
    """候補に API で埋めた欄を重ねる(候補にある値が先)"""
    m = meta.get(c["video"]) or {}
    return dict(c, **{k: m.get(k) for k in ("channel", "title", "uploadDate") if not c.get(k) and m.get(k)})


def due(app_dir, now):
    """今取ってよいか -> (よいか, 理由)。間隔(判定に当たった翌日から伸ばす)・その日の止め・研究の古い道の印"""
    st = _state(app_dir)
    today = datetime.date.fromtimestamp(now).isoformat()
    slot = fsio.read_json_or(os.path.join(app_dir, "check", _vf.SLOT_NAME), {}, kind=dict)
    stop = slot.get("stopDay")
    if stop == today:
        return False, "今日は止めています(%s)" % (slot.get("why") or "bot 判定")
    if stop and stop != st.get("hitSeen"):   # 判定に当たった日の翌日 = 間隔を 1 段伸ばす
        i = LADDER.index(st["hours"]) if st.get("hours") in LADDER else 0
        st.update(hours=LADDER[min(i + 1, len(LADDER) - 1)], hitSeen=stop)
        _save(app_dir, st)
    hours = st.get("hours") or INTERVAL
    last = max(_vm.num(st.get("last")), _vm.num(slot.get("last")) if slot.get("by") == "research" else 0.0)
    if now - last < hours * 3600:
        return False, "前の取得から %d 分(間隔 %.1f 時間)" % ((now - last) // 60, hours)
    return True, ""


def _api_left(st, today):
    used = st.get("api") if isinstance(st.get("api"), dict) else {}
    return API_DAILY - int(used.get(today) or 0)


def _api_count(st, today, n):
    used = st.get("api") if isinstance(st.get("api"), dict) else {}
    st["api"] = {today: int(used.get(today) or 0) + n}


def _write_done(app_dir, rid, body):
    """結果を done/<rid>.json に。頼み(req/<rid>.json)は消し、済んだ印を state の served に覚える = 研究が done を消しても二度取らない(10-25)"""
    os.makedirs(qdir(app_dir, "done"), exist_ok=True)
    p = qdir(app_dir, "done", rid + ".json")
    fsio.write_json(p + ".tmp", dict(body, id=rid, at=int(time.time())), indent=None)
    os.replace(p + ".tmp", p)
    fsio.unlink_quiet(qdir(app_dir, "req", rid + ".json"))
    st = _state(app_dir)
    st["served"] = (list(st.get("served") or []) + [rid])[-SERVED_KEEP:]
    _save(app_dir, st)


def _info_api(ids):
    """API で動画の情報(説明欄・チャンネル・日付・長さ)。50 本ずつ -> [{"id", "title", "description", "channel_id", "upload_date", "duration"}]"""
    out = []
    for i in range(0, len(ids), 50):
        got = _ytapi.get("videos", {"part": "snippet,contentDetails,liveStreamingDetails", "id": ",".join(ids[i:i + 50]), "maxResults": 50})
        for it in got.get("items") or ():
            sn = it.get("snippet") or {}
            ls = it.get("liveStreamingDetails") or {}
            when = str(ls.get("actualStartTime") or sn.get("publishedAt") or "")
            out.append({"id": it.get("id"), "title": sn.get("title"), "description": sn.get("description"), "channel_id": sn.get("channelId"),
                        "upload_date": when[:10].replace("-", ""), "duration": (it.get("contentDetails") or {}).get("duration")})
    return out


def _info_ytdlp(urls):
    yd = _vf._tools.find_tool("yt-dlp")
    if not yd:
        raise RuntimeError("yt-dlp が見つかりません")
    r, tail = _vf._run([yd, "--encoding", "utf-8", "--no-warnings", "--skip-download", "--no-playlist", "-j", "--"] + list(urls), 300)
    if r is None or r.returncode != 0:
        raise RuntimeError(tail or "読めませんでした")
    out = []
    for line in (r.stdout or "").splitlines():
        try:
            d = json.loads(line)
        except ValueError:
            continue
        out.append({k: d.get(k) for k in ("id", "title", "description", "channel_id", "upload_date", "duration")})
    return out


def _audio(app_dir, rid, url, section):
    """音だけ取って done/<rid>.<拡張子> に -> (パス, 情報) か (None, 失敗の文)"""
    yd = _vf._tools.find_tool("yt-dlp")
    if not yd:
        return None, "yt-dlp が見つかりません"
    os.makedirs(qdir(app_dir, "done"), exist_ok=True)
    stage = qdir(app_dir, "done", STAGE)
    os.makedirs(stage, exist_ok=True)
    base = os.path.join(stage, rid)
    keep = qdir(app_dir, KEEP_DIR, "%(id)s")
    cmd = [yd, "--encoding", "utf-8", "--no-warnings", "--no-playlist", "--no-part", "--force-overwrites", "--no-progress", "-f", "ba",
           "-o", base + ".%(ext)s", "--no-simulate", "--print", "%(id)s\t%(channel_id)s\t%(upload_date)s\t%(duration)s\t%(title)s",
           # 使い道の束(同じ問い合わせの中で): 動画の情報(説明欄・チャプター・よく見られている場面の山 heatmap)と日本語の自動字幕
           "--write-info-json", "-o", "infojson:" + keep + os.sep + "info", "--write-auto-subs", "--sub-langs", "ja", "--sub-format", "json3",
           "-o", "subtitle:" + keep + os.sep + "subs"]
    if section:
        cmd += ["--download-sections", "*%d-%d" % (max(0, int(section[0])), int(section[1]))]
    ff = _vf._tools.find_tool("ffmpeg")
    if ff:
        cmd += ["--ffmpeg-location", ff]
    r, tail = _vf._run(cmd + ["--", url], _vf.FETCH_TIMEOUT * 2)
    files = [os.path.join(stage, x) for x in os.listdir(stage) if x.startswith(rid + ".")]
    if r is None or r.returncode != 0 or not [f for f in files if not f.endswith((".part", ".ytdl", ".tmp"))]:
        for f in files:
            fsio.unlink_quiet(f)
        return None, tail or "取れませんでした"
    got = max((f for f in files if not f.endswith((".part", ".ytdl", ".tmp"))), key=os.path.getsize)
    dst = qdir(app_dir, "done", os.path.basename(got))
    os.replace(got, dst)
    for f in files:
        if f != got:
            fsio.unlink_quiet(f)
    parts = ((r.stdout or "").strip().splitlines() or [""])[0].split("\t")
    info = dict(zip(("id", "channel_id", "upload_date", "duration", "title"), parts + [""] * 5))
    info["bundle"] = bundle(app_dir, info.get("id"))
    return dst, info


KEEP_DIR = "keep"
INFO_KEYS = ("id", "title", "channel_id", "channel", "upload_date", "release_timestamp", "duration", "description", "chapters", "heatmap",
             "view_count", "like_count", "comment_count", "was_live", "live_status", "tags", "categories")


def bundle(app_dir, vid):
    """使い道の束を小さくする: keep/<動画>/info.info.json(大きい = 形式の一覧など)を要る欄だけの info.json に・字幕はそのまま。
    -> {"dir", "info", "subs", "chat"}(ある物だけ)。研究が分析に使う(区間・編集カット・同時発話・置換辞書の候補・BGM・場面の山・チャプター)"""
    if not _vf.VIDEO_RE.match(str(vid or "")):
        return {}
    d = qdir(app_dir, KEEP_DIR, vid)
    if not os.path.isdir(d):
        return {}
    out = {"dir": d}
    for x in os.listdir(d):
        p = os.path.join(d, x)
        if x.endswith(".info.json"):
            raw = fsio.read_json_or(p, {}, kind=dict)
            fsio.write_json(os.path.join(d, "info.json"), {k: raw.get(k) for k in INFO_KEYS if raw.get(k) is not None}, indent=None)
            fsio.unlink_quiet(p)
    for x in os.listdir(d):
        p = os.path.join(d, x)
        if x == "info.json":
            out["info"] = p
        elif x.startswith("subs.") and x.endswith((".json3", ".vtt")):
            out["subs"] = p
        elif x.startswith("chat."):
            out["chat"] = p
    return out


def _chat(app_dir, url):
    """チャットのリプレイ(文字だけ・live_chat)を keep/<動画>/chat.* に -> (パス, "") か (None, 失敗の文)。
    長い配信は問い合わせの数が多いので、自動では取らない(研究が kind chat で頼む物だけ)"""
    yd = _vf._tools.find_tool("yt-dlp")
    vid = _video_of(url)
    if not yd or not vid:
        return None, "yt-dlp が見つからないか、動画の id が分かりません"
    d = qdir(app_dir, KEEP_DIR, vid)
    os.makedirs(d, exist_ok=True)
    r, tail = _vf._run([yd, "--encoding", "utf-8", "--no-warnings", "--no-playlist", "--skip-download", "--write-subs", "--sub-langs", "live_chat",
                        "-o", "subtitle:" + os.path.join(d, "chat"), "--", url], 1800)
    got = [os.path.join(d, x) for x in os.listdir(d) if x.startswith("chat.") and not x.endswith(".part")]
    if r is not None and r.returncode == 0 and got:
        return got[0], ""
    return None, tail or "チャットのリプレイがありません"


def _subs(app_dir, rid, url):
    """自動字幕だけ(日本語・json3)を done/<rid>.ja.json3 に -> (パス, "") か (None, 失敗の文)。字幕が無ければ失敗の文"""
    yd = _vf._tools.find_tool("yt-dlp")
    if not yd:
        return None, "yt-dlp が見つかりません"
    os.makedirs(qdir(app_dir, "done"), exist_ok=True)
    r, tail = _vf._run([yd, "--encoding", "utf-8", "--no-warnings", "--no-playlist", "--skip-download", "--write-auto-subs", "--sub-langs", "ja",
                        "--sub-format", "json3", "-o", qdir(app_dir, "done", rid) + ".%(ext)s", "--", url], 300)
    got = [qdir(app_dir, "done", x) for x in os.listdir(qdir(app_dir, "done")) if x.startswith(rid + ".") and x.endswith((".json3", ".vtt"))]
    if r is not None and r.returncode == 0 and got:
        return got[0], ""
    return None, tail or "自動字幕がありません"


def _to_voice(app_dir, path, info, chan_of):
    """取った音が日本の対象のメンバーの配信なら、声の置き場(voice-inbox)へ写す。ソロかどうか・要るかは voicefetch.intake が決める"""
    if str(info.get("channel_id") or "") not in chan_of or not _vf.VIDEO_RE.match(str(info.get("id") or "")):
        return False
    box = os.path.join(app_dir, "check", _vf.INBOX_NAME)
    os.makedirs(box, exist_ok=True)
    vid = info["id"]
    shutil.copyfile(path, os.path.join(box, vid + ".tmp"))
    os.replace(os.path.join(box, vid + ".tmp"), os.path.join(box, vid + os.path.splitext(path)[1].lower()))
    fsio.write_json(os.path.join(box, vid + ".json"), {"videoId": vid, "channel": info.get("channel_id"), "title": info.get("title"),
                                                       "uploadDate": info.get("upload_date"), "by": "ytqueue"}, indent=None)
    return True


def _bot(err):
    return any(b in str(err or "").lower() for b in _vf.BOT)


def _hit(app_dir, now, err, log):
    _vf._mark_slot(app_dir, now, stop_why=str(err)[:200])
    log("YouTube の取得の列: bot 判定・ログインを求められたので今日は止めます(翌日から間隔を伸ばします)")


_first_tidy = {}


def tidy(app_dir, now=None):
    """起動の後と見回りごと: 途中の物(.part・.tmp・.ytdl)を消す・DONE_DAYS 日より古い結果を消す・ready.json を置く"""
    now = time.time() if now is None else now
    d = qdir(app_dir, "done")
    os.makedirs(d, exist_ok=True)
    os.makedirs(qdir(app_dir, "req"), exist_ok=True)
    if _first_tidy.get(app_dir, True):   # 起動の後の 1 回 = 途中で止まった取得の音を消す
        shutil.rmtree(os.path.join(d, STAGE), ignore_errors=True)
        _first_tidy[app_dir] = False
    names = set(os.listdir(d))
    for x in names:
        p = os.path.join(d, x)
        if os.path.isdir(p):
            continue
        try:
            age = now - os.path.getmtime(p)
        except OSError:
            continue
        orphan = not x.endswith(".json") and (x.split(".", 1)[0] + ".json") not in names and age > 3600   # 結果の json の無い古い音 = 途中で止まった物
        if x.endswith((".part", ".tmp", ".ytdl")) or age > DONE_DAYS * 86400 or orphan:
            fsio.unlink_quiet(p)
    k = qdir(app_dir, KEEP_DIR)
    for v in (os.listdir(k) if os.path.isdir(k) else ()):
        p = os.path.join(k, v)
        try:
            old = now - os.path.getmtime(p) > DONE_DAYS * 86400
        except OSError:
            continue
        if old and not os.path.exists(os.path.join(p, "hold")):   # 研究が hold を置いた物は残す(研究が要る間)
            shutil.rmtree(p, ignore_errors=True)
    if not os.path.exists(qdir(app_dir, "ready.json")):
        fsio.write_json(qdir(app_dir, "ready.json"), {"since": int(now)}, indent=None)


def _api_infos(app_dir, log, now):
    """info の頼みを API で読む(枠を使わない・1 日 API_DAILY まで)。キーが無い・断られたら残す(枠で yt-dlp が読む)-> 読んだ数"""
    st = _state(app_dir)
    today = datetime.date.fromtimestamp(now).isoformat()
    n = 0
    for r in [r for r in requests(app_dir) if r["kind"] == "info"]:
        ids = [v for v in (_video_of(u) for u in r["urls"]) if v]
        if not ids or _api_left(st, today) < 1 or st.get("apiOff") == today:
            break
        try:
            infos = _info_api(ids)
        except ApiError as e:
            if e.code in _ytapi.FATAL:
                st["apiOff"] = today   # キーが無い・上限・断られた = 今日は yt-dlp の道
                log("YouTube の取得の列: API を使えないので、今日は説明欄も枠で読みます(%s)" % e.code)
            break
        _api_count(st, today, 1)
        _write_done(app_dir, r["id"], {"state": "done", "infos": infos, "via": "api"})
        n += 1
    _save(app_dir, st)
    return n


def wants(app_dir, roster_r, counts, extra=None, now=None):
    """列が今取りたいか(学習用データの文字起こしを休ませる合図)= 取ってよい時刻で、頼み・候補・声の不足のどれかがある"""
    now = time.time() if now is None else now
    if not ENABLED or not due(app_dir, now)[0]:
        return False
    vstate = _vf._read(os.path.join(app_dir, "check", _vf.STATE_NAME))
    return bool(requests(app_dir) or candidates(app_dir) or _vf._todo(roster_r, counts, vstate, extra))


def tick(app_dir, roster_r, counts, busy, start_job, log, extra=None, now=None):
    """1 回分 -> 取った物の説明か None。busy() = 休む理由か None"""
    now = time.time() if now is None else now
    if not ENABLED:
        return None
    tidy(app_dir, now)
    _api_infos(app_dir, log, now)        # API の読み込みは軽いので処理中でも読む(枠も使わない)
    fill_candidates(app_dir, now, log)
    if busy():
        return None
    ok, _why = due(app_dir, now)
    if not ok:
        return None
    st = _state(app_dir)
    chan_of = {c: n for n, c in _vf.members(roster_r, extra)}
    ranked = plan(app_dir, roster_r, counts, extra, st=st)
    if not ranked:
        return None
    best = ranked[0]
    st.update(last=now, lastPurpose=best["kind"])
    _vf._mark_slot(app_dir, now)   # 研究の古い道(yt-slot.json)にも取ったと書く = 切り替えの前後で二重に取らない
    if best["kind"] == "candidate":
        c, res, voice = best["cand"], best["research"], best["voice"]
        t = c.get("t")
        section = [max(0, int(t) - AROUND[0]), int(t) + AROUND[1]] if isinstance(t, (int, float)) else None
        rid = "cand-" + c["video"]
        path, info = _audio(app_dir, rid, "https://www.youtube.com/watch?v=" + c["video"], section)
        st["cands"] = (list(st.get("cands") or []) + [c["video"]])[-2000:]
        if path is None:
            if _bot(info):
                _hit(app_dir, now, info, log)
            _write_done(app_dir, rid, {"state": "error", "error": str(info)[:300], "video": c["video"]})
            _save(app_dir, st)
            log("YouTube の取得の列: 候補 %s を取れませんでした(%s)" % (c["video"], str(info).splitlines()[-1][:120] if info else ""))
            return None
        _write_done(app_dir, rid, {"state": "done", "file": path, "info": info, "video": c["video"], "section": section, "candidate": True})
        sent = voice > 0 and _to_voice(app_dir, path, info, chan_of)
        _save(app_dir, st)
        log("YouTube の取得の列: 候補 %s(研究 %.2f・声 %.2f)を取りました%s" % (c["video"], res, voice, "(声の材料にも回します)" if sent else ""))
        return "candidate"
    if best["kind"] == "request":
        r = best["req"]
        if r["kind"] == "info":
            try:
                body = {"state": "done", "infos": _info_ytdlp(r["urls"]), "via": "yt-dlp"}
            except Exception as e:   # noqa: BLE001
                body = {"state": "error", "error": str(e)[:300]}
        elif r["kind"] == "chat":
            path, err = _chat(app_dir, r["urls"][0])
            body = {"state": "done", "file": path, "bundle": bundle(app_dir, _video_of(r["urls"][0]))} if path else {"state": "error", "error": err[:300]}
        elif r["kind"] == "subs":
            path, err = _subs(app_dir, r["id"], r["urls"][0])
            body = {"state": "done", "file": path} if path else {"state": "error", "error": err[:300]}
        elif r["kind"] == "list":
            items, err = _list_url(r["urls"][0], int(_vm.num(r.get("items"), 50)))
            body = {"state": "done", "entries": items} if items else {"state": "error", "error": err[:300]}
        else:
            path, info = _audio(app_dir, r["id"], r["urls"][0], r.get("section"))
            body = {"state": "done", "file": path, "info": info} if path else {"state": "error", "error": str(info)[:300]}
            if path:
                _to_voice(app_dir, path, info, chan_of)
        if body["state"] == "error" and _bot(body.get("error")):
            _hit(app_dir, now, body["error"], log)
        _write_done(app_dir, r["id"], body)
        _save(app_dir, st)
        log("YouTube の取得の列: 研究の頼み %s(%s)を%s" % (r["id"], r["kind"], "済ませました" if body["state"] == "done" else "済ませられませんでした"))
        return "research"
    _save(app_dir, st)   # 声だけ = 候補に無いメンバーを RSS・一覧で(voicefetch)
    got = _vf.tick(app_dir, roster_r, counts, lambda: None, start_job, log, now=now, extra=extra, use_slot=False, only={best["who"]})
    return "voice" if got else None


REQ_BASE = {"subs": 1.6, "info": 1.4, "list": 0.9, "audio": 1.0, "chat": 0.6}   # 研究の頼みの点の元(字幕・動画の情報 = あとの音の取得を短くできる軽い物は高く)


def plan(app_dir, roster_r, counts, extra=None, st=None):
    """全部の頼みを 1 つの一覧で点を付ける(10-25 ユーザー: 研究と声を交互に回すのをやめ、毎回いちばん点の高い 1 本)。
    -> [{"score", "kind": "candidate"|"request"|"voice", "label", ...}](点の高い順)。
    候補 = 研究 + 声 − 区間の長さ / 研究の頼み = REQ_BASE(種類)+ 声(音の頼みで配信者が材料の少ない人)+ priority × 0.1 − 区間の長さ /
    声だけ = その人の材料の足りなさ(候補に無いメンバーだけ)"""
    st = _state(app_dir) if st is None else st
    chan_of = {c: n for n, c in _vf.members(roster_r, extra)}
    vstate = _vf._read(os.path.join(app_dir, "check", _vf.STATE_NAME))
    done_videos = {x.get("video") for rec in vstate.values() if isinstance(rec, dict) for x in _vf._got(rec)} | set(st.get("cands") or [])
    meta = st.get("meta") if isinstance(st.get("meta"), dict) else {}
    out = []
    for c in (_merged(c, meta) for c in candidates(app_dir)):
        res, voice, cost = score(c, chan_of, counts, vstate, done_videos)
        if res or voice:
            out.append({"score": round(res + voice - cost, 3), "kind": "candidate", "label": "候補 %s" % c["video"], "cand": c, "research": res, "voice": voice})
    for q in requests(app_dir):
        voice = 0.0
        if _req_voice(q, chan_of, counts, vstate):
            hint = q.get("hint") if isinstance(q.get("hint"), dict) else {}
            who = chan_of.get(str(hint.get("channel") or "")) or _vm.member(hint.get("streamer"))
            voice = (_vf.TARGET - _vf._have(who, counts, vstate)) / float(_vf.TARGET)
        sec = q.get("section")
        span = (sec[1] - sec[0]) if q.get("kind") == "audio" and isinstance(sec, list) and len(sec) == 2 else (3 * 3600 if q.get("kind") == "audio" else 0)
        sc = REQ_BASE.get(q["kind"], 0.5) + voice + _vm.num(q.get("priority")) * 0.1 - span / 3600.0 * 0.2
        out.append({"score": round(sc, 3), "kind": "request", "label": "研究の頼み %s(%s)" % (q["id"], q["kind"]), "req": q, "research": 1.0, "voice": voice})
    covered = {chan_of.get(str(o["cand"].get("channel") or "")) for o in out if o["kind"] == "candidate" and o["voice"] > 0}
    for n, _c in _vf._todo(roster_r, counts, vstate, extra):
        if n not in covered:
            need = (_vf.TARGET - _vf._have(n, counts, vstate)) / float(_vf.TARGET)
            out.append({"score": round(need - 0.02, 3), "kind": "voice", "label": "声だけ %s" % n, "who": n, "research": 0.0, "voice": need})
    return sorted(out, key=lambda o: -o["score"])


def _list_url(url, items):
    yd = _vf._tools.find_tool("yt-dlp")
    if not yd:
        return [], "yt-dlp が見つかりません"
    r, tail = _vf._run([yd, "--encoding", "utf-8", "--no-warnings", "--flat-playlist", "-J", "--playlist-items", "1:%d" % max(1, min(items, 500)), "--", url], 300)
    if r is None or r.returncode != 0:
        return [], tail or "一覧を読めませんでした"
    try:
        d = json.loads(r.stdout)
    except ValueError:
        return [], "一覧の形が違います"
    return [{k: e.get(k) for k in ("id", "title", "upload_date", "timestamp", "duration")} for e in d.get("entries") or () if isinstance(e, dict)], ""
