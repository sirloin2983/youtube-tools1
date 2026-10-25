"""誰の声の材料の配信の音を YouTube から少しだけ取る(10-25。ユーザー「全メンバー揃えてほしい」「ショートだけでは足りない。配信からの材料も要る」。
ショート = 手元の学習用データ は voicefill)。

対象 = 名簿の日本の今のメンバー(EN・ID・ホロアナ・ユニット・卒業の組は除く = flow/voicematerial.jp_members)の全員。1 人あたり配信の材料 TARGET 本まで:
  配信の材料の本数 = 手元のソロの配信の文書(ショート・評価用・ここで取った物を除く。app/check/voice_solo.stream_counts)+ ここで取った本数。
  本数の少ない人から 1 人ずつ(0 本 = ショートだけ・何も無い人 → 1 本 → …)。同じ本数なら試した数の少ない人・名簿の順。
  1 本目: チャンネルの RSS(最近の 15 本)から雑談らしい配信(歌・コラボ・ショートは外す・雑談の印が先)。
  2 本目から: 配信の一覧(yt-dlp --flat-playlist の /streams・LIST_ITEMS 本)の古い方(RSS の外)から、取った配信と別の月の物
  (配信の材料が 1〜2 本の配信に偏らない = 配信ごとのマイク・部屋の違いを平均に入れる)。
  その SECTION 秒の所の音だけを yt-dlp の --download-sections で取り(音だけ・cookie なし)、「編集」の文字起こしに頼む。
  できた文書は誰の声のカードだけに使う(sources.View.docs が外す = voicefill.in_learn_dir。見立て = 名前を付けたファイルの名前の人)。
YouTube の枠は研究と分け合う(印のファイル <app>/check/yt-slot.json):
  last から GAP 秒たっていない・stopDay が今日・last が自分(相手の番を待つ。OWN_WAIT 秒たてば自分でもよい)なら問い合わせない。
  問い合わせたら last・by を書く。bot 判定・ログインを求められたら stopDay = 今日(その日は両方止める)。
途中で残ったファイル(PC の再起動など)は次の回に消して取り直す。
動かす時刻 HOURS。手が空いていない(入口の _accuracy_busy)・ライブの録画中は飛ばす。1 回に 1 人・取った音は <app>/check/voice-fetch/<名前>/ に残す。
"""
import datetime
import json
import os
import re
import subprocess
import time
import urllib.request
import xml.etree.ElementTree as ET

from flow import voicematerial as _vm
from ytt import fsio, tools as _tools

ENABLED = True
EVERY = 60                    # 見回りの間隔(秒)
SLOT_NAME = "yt-slot.json"
STATE_NAME = "voice-fetch.json"
DIR_NAME = "voice-fetch"
BY = "voice"
GAP = 1800                    # どちらかが問い合わせてから、次に問い合わせるまでの最短(秒)
OWN_WAIT = 5400               # 自分が続けて問い合わせてよいまでの秒(研究が動いていないとき)
HOURS = (0, 24)               # 1 日中(10-25: 研究にそろえた。枠の分け合いと判定で止める決まりはそのまま)
SECTION = (600, 840)          # 取る所(配信の 10〜14 分。頭の待機画面と BGM を避ける)
FETCH_TIMEOUT = 900
MAX_TRIES = 8                 # 1 人につき試す配信の数(取れなければ次の回に次の配信)
TARGET = 2                    # 1 人あたりの配信の材料の本数(この本数に届くまで取る)
LIST_ITEMS = 80               # 2 本目からの配信の一覧の本数(古い方から選ぶ)
LIST_SKIP = 15                # 一覧の頭のこの本数は RSS と同じ頃なので 2 本目には使わない
RSS_URL = "https://www.youtube.com/feeds/videos.xml?channel_id=%s"
CHANNEL_RE = re.compile(r"^UC[A-Za-z0-9_-]{22}\Z")
VIDEO_RE = re.compile(r"^[A-Za-z0-9_-]{11}\Z")
BOT = ("sign in to confirm", "not a bot", "login required", "http error 429", "use --cookies")
TALK_RE = re.compile(r"雑談|ざつだん|freetalk|free talk|chatting|zatsudan|talk|おしゃべり|朝活|morning", re.I)
SHORT_RE = re.compile(r"#shorts?\b|\bshorts?\b", re.I)
NS = {"a": "http://www.w3.org/2005/Atom", "yt": "http://www.youtube.com/xml/schemas/2015"}


COLORS_PATH = os.path.join("friend-apps", "holo-colors", "members.json")   # 配信者の色の名簿(リポジトリ。名簿にチャンネルの無い人の控え)


def extra_channels(root):
    """配信者の色の名簿のチャンネル {名前: チャンネル id}(名簿 = 文字起こしの名簿にチャンネルが無い人のため。読めなければ {})"""
    d = fsio.read_json_or(os.path.join(root, COLORS_PATH), {}, kind=dict) if root else {}
    return {m["name"]: m["channel"] for g in d.get("groups") or () if isinstance(g, dict) for m in g.get("members") or ()
            if isinstance(m, dict) and isinstance(m.get("name"), str) and CHANNEL_RE.match(str(m.get("channel") or ""))}


def members(r, extra=None):
    """日本の今のメンバー [(名前, チャンネル id)](flow/voicematerial.jp_members・チャンネルのある人だけ)。r = 名簿のファイルの中身(roster_data)・
    extra = 名簿にチャンネルが無い人の控え(extra_channels)。EN・ID は外す(10-25 ユーザー)"""
    chan = dict(extra or {})
    chan.update({m.get("name"): m.get("channel") for m in r.get("members") or () if isinstance(m, dict) and CHANNEL_RE.match(str(m.get("channel") or ""))})
    return [(n, chan[n]) for n in _vm.jp_members(r) if CHANNEL_RE.match(str(chan.get(n) or ""))]


def _read(path):
    return fsio.read_json_or(path, {}, kind=dict)


def slot_free(app_dir, now):
    """研究と分け合う枠が空いているか -> (空いているか, 理由)"""
    s = _read(os.path.join(app_dir, "check", SLOT_NAME))
    if s.get("stopDay") == datetime.date.fromtimestamp(now).isoformat():
        return False, "今日は止めています(%s)" % (s.get("why") or "bot 判定")
    last = _vm.num(s.get("last"))
    if now - last < GAP:
        return False, "前の問い合わせから %d 分" % ((now - last) // 60)
    if s.get("by") == BY and now - last < OWN_WAIT:
        return False, "研究の番"
    return True, ""


def _mark_slot(app_dir, now, stop_why=None):
    p = os.path.join(app_dir, "check", SLOT_NAME)
    s = _read(p)
    s.update(last=int(now), by=BY)
    if stop_why:
        s.update(stopDay=datetime.date.fromtimestamp(now).isoformat(), why=stop_why[:200])
    os.makedirs(os.path.dirname(p), exist_ok=True)
    fsio.write_json(p, s, indent=None)


def parse_rss(body):
    """RSS -> [{"id", "title", "month"}](新しい順。month = 公開の年月 "YYYY-MM")"""
    try:
        root = ET.fromstring(body)
    except (ET.ParseError, ValueError):
        return []
    out = []
    for e in root.findall("a:entry", NS):
        vid = (e.findtext("yt:videoId", "", NS) or "").strip()
        if VIDEO_RE.match(vid):
            out.append({"id": vid, "title": (e.findtext("a:title", "", NS) or "").strip(), "month": (e.findtext("a:published", "", NS) or "")[:7]})
    return out


def choose(items, tried, months=()):
    """雑談らしい配信を 1 本(歌・コラボ・ショート・試した物・取った配信と同じ月の物を外す。雑談の印がある物が先)か None"""
    ok = [it for it in items if it["id"] not in tried and not SHORT_RE.search(it["title"]) and not _vm.song_title(it["title"])
          and not _vm.COLLAB_RE.search(it["title"]) and not (it.get("month") and it["month"] in months)]
    ok.sort(key=lambda it: not TALK_RE.search(it["title"]))
    return ok[0] if ok else None


def _rss(channel, timeout=20):
    req = urllib.request.Request(RSS_URL % channel, headers={"User-Agent": "Mozilla/5.0"})
    with urllib.request.urlopen(req, timeout=timeout) as r:   # noqa: S310  (決まった youtube.com の RSS だけ)
        return r.read(2 * 1024 * 1024)


def _run(cmd, timeout):
    try:
        r = subprocess.run(cmd, capture_output=True, text=True, encoding="utf-8", errors="replace", timeout=timeout, stdin=subprocess.DEVNULL,
                           creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0))
    except (OSError, subprocess.TimeoutExpired) as e:
        return None, "%s" % e.__class__.__name__
    return r, ((r.stderr or "") + (r.stdout or ""))[-400:].strip()


LOGIN_WORDS = ("cookies are no longer valid", "sign in", "login", "account", "cookie")   # ログインの問題(切れた・止められた)の印(小文字で照らす)
LOGIN = {"trouble": None, "at": 0, "used": None}
LAST_ERR = {"err": ""}   # 最後に当たった失敗の文(列 ytqueue が段の守りに使う)   # 最後にログインで断られた時刻と文(列が記録に出す。cookie の中身は持たない)


def _blocked(app_dir):
    """評価用のショートの元の配信(列 ytqueue の eval-sources.json。声の材料にしない = 評価を汚さない。10-25)"""
    d = fsio.read_json_or(os.path.join(app_dir, "check", "yt-queue", "eval-sources.json"), {}, kind=dict)
    return {v for v in d.get("videos") or () if isinstance(v, str)}


def _ytdlp(cmd, timeout):
    """yt-dlp を、ツールに入っている YouTube のログイン(ytt/tools.ytdlp_auth_args = 普段の取得と同じ口。写しのパスだけ渡す・中身は読まない)で呼ぶ。
    ログインが無ければ cookie なし。ログインで断られたら(切れた・止められた)cookie なしで 1 回取り直し、LOGIN に印を残す(10-25 ユーザー「ログインして」)"""
    auth = _tools.ytdlp_auth_args()
    LOGIN["used"] = bool(auth)
    if not auth:
        return _run(cmd, timeout)
    r, tail = _run(cmd[:1] + auth + cmd[1:], timeout)
    if (r is None or r.returncode != 0) and any(w in (tail or "").lower() for w in LOGIN_WORDS):
        LOGIN.update(trouble=(tail or "")[-200:], at=time.time())
        return _run(cmd, timeout)
    return r, tail


def _list(channel, timeout=180):
    """配信の一覧(/streams の LIST_ITEMS 本・中身は読まない)-> ([{"id", "title", "month"}](新しい順), 失敗の文)。cookie は使わない"""
    yd = _tools.find_tool("yt-dlp")
    if not yd:
        return [], "yt-dlp が見つかりません"
    r, tail = _ytdlp([yd, "--encoding", "utf-8", "--no-warnings", "--flat-playlist", "-J", "--playlist-items", "1:%d" % LIST_ITEMS,
                    "--", "https://www.youtube.com/channel/%s/streams" % channel], timeout)
    if r is None or r.returncode != 0:
        return [], tail or "一覧を読めませんでした"
    try:
        d = json.loads(r.stdout)
    except ValueError:
        return [], "一覧の形が違います"
    out = []
    for e in d.get("entries") or ():
        if not isinstance(e, dict) or not VIDEO_RE.match(str(e.get("id") or "")):
            continue
        ts = e.get("release_timestamp") or e.get("timestamp")
        month = datetime.datetime.fromtimestamp(ts).strftime("%Y-%m") if isinstance(ts, (int, float)) else str(e.get("upload_date") or "")[:6]
        if len(month) == 6:
            month = month[:4] + "-" + month[4:]
        out.append({"id": e["id"], "title": str(e.get("title") or ""), "month": month})
    return out, ""


def _fetch(video_id, out_base, timeout=FETCH_TIMEOUT):
    """音だけ SECTION の所を取る -> (パスか None, 失敗の文)。cookie は使わない"""
    yd = _tools.find_tool("yt-dlp")
    if not yd:
        return None, "yt-dlp が見つかりません"
    cmd = [yd, "--encoding", "utf-8", "--no-warnings", "--no-playlist", "--no-part", "--force-overwrites", "--no-progress", "-f", "ba",
           "--download-sections", "*%d-%d" % SECTION, "-o", out_base + ".%(ext)s"]
    ff = _tools.find_tool("ffmpeg")
    if ff:
        cmd += ["--ffmpeg-location", ff]
    cmd += ["--", "https://www.youtube.com/watch?v=" + video_id]
    r, tail = _ytdlp(cmd, timeout)
    if r is None:
        return None, tail
    d, base = os.path.dirname(out_base), os.path.basename(out_base)
    got = [os.path.join(d, x) for x in os.listdir(d) if x.startswith(base + ".") and not x.endswith((".part", ".ytdl"))]
    if r.returncode == 0 and got:
        return max(got, key=os.path.getsize), ""
    return None, tail or "終了コード %s" % r.returncode


def _got(rec):
    """取った配信の一覧(古い形 = got がパスの文字は 1 本に読む)"""
    g = (rec or {}).get("got")
    if isinstance(g, str):
        return [{"path": g, "video": rec.get("video"), "month": rec.get("month") or ""}]
    return [x for x in g or () if isinstance(x, dict)]


def _have(n, counts, state):
    return int(counts.get(n) or 0) + len(_got(state.get(n)))


def _todo(roster_r, counts, state, extra=None):
    """取る人 [(名前, チャンネル)](配信の材料の本数の少ない人・試した数の少ない人・名簿の順)"""
    out = [(n, c) for n, c in members(roster_r, extra) if _have(n, counts, state) < TARGET
           and len((state.get(n) or {}).get("tried") or []) < MAX_TRIES]
    return sorted(out, key=lambda x: (_have(x[0], counts, state), len((state.get(x[0]) or {}).get("tried") or [])))


def wants(app_dir, roster_r, counts, now=None, extra=None):
    """今 YouTube から取りたいか(動かす時刻・配信の材料が TARGET 本に届かない人が残っている・枠が空いている)。学習用データの文字起こし(voicefill)はこの間は休む
    = 入口の手の空いた合間をこちらに譲る(10-25: 文字起こしが続いて、こちらがいつ見ても処理中だった)"""
    now = time.time() if now is None else now
    if not ENABLED or not (HOURS[0] <= datetime.datetime.fromtimestamp(now).hour < HOURS[1]):
        return False
    return bool(_todo(roster_r, counts, _read(os.path.join(app_dir, "check", STATE_NAME)), extra)) and slot_free(app_dir, now)[0]


def tick(app_dir, roster_r, counts, busy, start_job, log, now=None, rss=None, fetch=None, extra=None, lister=None, use_slot=True, only=None):
    """1 回分: 配信の材料の少ない人を 1 人取って文字起こしに頼む。-> 頼んだ人の名前か None。counts = {名前: 手元の配信の材料の本数}。
    use_slot=False = 枠の見張りは呼び手(YouTube の取得の列 app/check/ytqueue)がする。only = この名前の人だけから選ぶ(列が、友人のショートの元に無い人だけを渡す)"""
    now = time.time() if now is None else now
    if not ENABLED or not (HOURS[0] <= datetime.datetime.fromtimestamp(now).hour < HOURS[1]) or busy():
        return None
    st_path = os.path.join(app_dir, "check", STATE_NAME)
    state = _read(st_path)
    todo = [x for x in _todo(roster_r, counts, state, extra) if only is None or x[0] in only]
    if not todo:
        return None
    if use_slot and not slot_free(app_dir, now)[0]:
        return None
    who, chan = todo[0]
    rec = state.setdefault(who, {"tried": []})
    rec["got"] = _got(rec)
    first = _have(who, counts, state) == 0
    if use_slot:
        _mark_slot(app_dir, now)
    if first:   # 1 本目 = 最近の配信(RSS。軽い)
        try:
            items = parse_rss((rss or _rss)(chan))
        except Exception as e:   # noqa: BLE001  (RSS が読めなければ次の回)
            log("誰の声の材料(YouTube): %s のチャンネルの一覧を読めませんでした(%s)" % (who, e.__class__.__name__))
            return None
    else:       # 2 本目から = 配信の一覧の古い方・取った配信と別の月
        items, err = (lister or _list)(chan)
        if not items and any(b in err.lower() for b in BOT):
            LAST_ERR["err"] = err   # 当たりの守りは呼び手の列(ytqueue)が段で決める
            if use_slot:
                _mark_slot(app_dir, now, stop_why=err[:200])
            log("誰の声の材料(YouTube): bot 判定・ログインを求められました(%s)" % ("今日は止めます" if use_slot else "列が休みを決めます"))
            return None
        items = items[LIST_SKIP:]
    it = choose(items, set(rec["tried"]) | _blocked(app_dir), {x.get("month") for x in rec["got"] if x.get("month")})   # 評価用のショートの元の配信は取らない
    if it is None:
        rec["tried"].append("none")
        fsio.write_json(st_path, state, indent=None)
        log("誰の声の材料(YouTube): %s の%s配信に雑談らしい物がありませんでした" % (who, "最近の" if first else "古い方の"))
        return None
    rec["tried"].append(it["id"])
    folder = os.path.join(app_dir, "check", DIR_NAME, who)
    os.makedirs(folder, exist_ok=True)
    keep = {os.path.normcase(x["path"]) for x in rec["got"] if x.get("path")}
    for x in os.listdir(folder):   # 途中で残った物(PC の再起動・止まった取得)= 消して取り直す。取れた音(got)は残す
        if os.path.normcase(os.path.join(folder, x)) not in keep:
            fsio.unlink_quiet(os.path.join(folder, x))
    safe = re.sub(r'[\\/:*?"<>|\x00-\x1f]', "_", it["title"])[:60]
    path, err = (fetch or _fetch)(it["id"], os.path.join(folder, "%s_%s_%s" % (who, it["id"], safe)))
    if path is None:
        if any(b in err.lower() for b in BOT):
            LAST_ERR["err"] = err
            if use_slot:
                _mark_slot(app_dir, now, stop_why=err[:200])
            log("誰の声の材料(YouTube): bot 判定・ログインを求められました(%s)" % ("今日は止めます" if use_slot else "列が休みを決めます"))
        else:
            log("誰の声の材料(YouTube): %s の %s の音を取れませんでした(%s)" % (who, it["id"], err.splitlines()[-1][:160] if err else ""))
        fsio.write_json(st_path, state, indent=None)
        return None
    one = {"path": path, "video": it["id"], "month": it.get("month") or "", "title": it["title"][:200], "at": int(now)}
    try:
        one["job"] = start_job({"sourcePath": path, "autoLlm": False, "title": "%s %s" % (who, it["title"][:150])})
        rec["got"].append(one)
    except Exception as e:   # noqa: BLE001  (頼めなければ got に入れない = 次の回に取り直す)
        log("誰の声の材料(YouTube): %s の音を文字起こしに頼めませんでした(%s)" % (who, str(e)[:120]))
    fsio.write_json(st_path, state, indent=None)
    log("誰の声の材料(YouTube): %s の「%s」(%s)の %d〜%d 秒の音を取りました(配信の材料 %d 本目・まだ %d 本に届かない人 %d 人)"
        % (who, it["title"][:40], it.get("month") or "月不明", SECTION[0], SECTION[1], _have(who, counts, state), TARGET, len(todo) - (1 if _have(who, counts, state) >= TARGET else 0)))
    return who


# ---------------------------------------------------------------- 研究が取った元の配信の音(10-25 ユーザー「1 回の取得で 2 つの目的」)
INBOX_NAME = "voice-inbox"     # <app>/check/voice-inbox/: 研究(overlap-research の m2)が当て終えた元の配信の音 <動画 id>.<拡張子> と meta <動画 id>.json を置く
AUDIO_EXTS = (".m4a", ".opus", ".webm", ".wav", ".mp3", ".mp4", ".mkv", ".ogg", ".aac")
MAX_META = 64 * 1024


LONG_SEC = 20 * 60   # これより長い研究の音は SECTION の所だけを切り出して残す(配信の全部 = 大きい・文字起こしが重い)
MID_START = 300      # 研究の音の ?t= の頭(前 5 分〜後 10 分の音 = 300 秒の所が切り抜きの所)


def _shorten(src, dst):
    """研究の音が長ければ一部だけ dst に写して元を消す -> 写したか(短ければ False = 呼び手がそのまま移す)。
    LONG_SEC より長い = 配信の全部 → SECTION(10〜14 分)。それ以下(?t= の前 5 分〜後 10 分)は MID_START から 4 分。ffmpeg が無ければ写さない"""
    dur = _tools.media_duration(src)
    ff = _tools.find_tool("ffmpeg")
    if not dur or not ff or dur <= (SECTION[1] - SECTION[0]) + 60:
        return False
    a = SECTION[0] if dur > LONG_SEC else MID_START
    a = min(a, max(0.0, dur - (SECTION[1] - SECTION[0])))
    r, _tail = _run([ff, "-hide_banner", "-nostdin", "-y", "-v", "error", "-ss", "%.3f" % a, "-i", src, "-t", "%d" % (SECTION[1] - SECTION[0]),
                     "-vn", "-c:a", "copy", dst], 300)
    if r is None or r.returncode != 0 or not os.path.isfile(dst):
        fsio.unlink_quiet(dst)
        return False
    fsio.unlink_quiet(src)
    return True


def _pseudo(who, title):
    """ソロの見分け(flow/voicematerial.solo_person)に通す仮の文書(話者 = 配信者 1 人・題名)"""
    return {"title": title, "sourceName": "", "speakers": [{"id": "S1", "name": who}], "segments": []}


def intake(app_dir, roster_r, start_job, log, extra=None, now=None):
    """研究の置き場の音を拾う: 日本の対象のメンバーのソロ(題名・名簿・solo_person)だけ自分の置き場へ移して文字起こしに頼み、取った配信に数える。
    ほかは消す(研究の置き場を大きくしない)。meta(<id>.json)のある物だけ(音 → meta の順に書かれる)。-> 拾った数"""
    box = os.path.join(app_dir, "check", INBOX_NAME)
    try:
        names = sorted(os.listdir(box))
    except OSError:
        return 0
    chan_of = {c: n for n, c in members(roster_r, extra)}   # 日本の対象のチャンネル -> 名前
    blocked = _blocked(app_dir)
    st_path = os.path.join(app_dir, "check", STATE_NAME)
    state = _read(st_path)
    took = 0
    for meta_name in [n for n in names if n.endswith(".json")]:
        vid = meta_name[:-5]
        mp = os.path.join(box, meta_name)
        audio = next((os.path.join(box, n) for n in names if n.startswith(vid + ".") and n.lower().endswith(AUDIO_EXTS)), None)
        try:
            meta = fsio.read_json_or(mp, {}, kind=dict) if os.path.getsize(mp) <= MAX_META else {}
        except OSError:
            continue
        title = str(meta.get("title") or "")[:200]
        who = chan_of.get(str(meta.get("channel") or "")) or (_vm.member(meta.get("streamer")) if _vm.member(meta.get("streamer")) in chan_of.values() else None)
        why = ("動画の id の形" if not VIDEO_RE.match(vid) else "音が無い" if not audio else "評価用のショートの元の配信" if vid in blocked
               else "日本の対象のメンバーでない" if not who
               else "評価用" if "評価用" in title else "歌" if _vm.song_title(title) else "ショート" if SHORT_RE.search(title)
               else "ソロでない" if _vm.solo_person(_pseudo(who, title)) != who else "")
        rec = state.setdefault(who, {"tried": []}) if who else None
        if not why and vid in {x.get("video") for x in _got(rec)}:
            why = "もう取った配信"
        if why:
            log("誰の声の材料(研究の音): %s を使いませんでした(%s)" % (vid, why))
        else:
            folder = os.path.join(app_dir, "check", DIR_NAME, who)
            os.makedirs(folder, exist_ok=True)
            safe = re.sub(r'[\/:*?"<>|\x00-\x1f]', "_", title)[:60]
            dst = os.path.join(folder, "%s_%s_%s%s" % (who, vid, safe, os.path.splitext(audio)[1].lower()))
            try:
                if not _shorten(audio, dst):   # 長い音(?t= の無い配信の全部)は SECTION の 4 分だけにする
                    os.replace(audio, dst)
                audio = None if not os.path.exists(audio) else audio
                rec["got"] = _got(rec)
                one = {"path": dst, "video": vid, "month": (lambda d: d[:4] + "-" + d[4:6] if len(d) >= 6 else "")(str(meta.get("uploadDate") or "")),
                       "title": title, "at": int(time.time() if now is None else now), "by": "research"}
                one["job"] = start_job({"sourcePath": dst, "autoLlm": False, "title": "%s %s" % (who, title[:150])})
                rec["got"].append(one)
                took += 1
                log("誰の声の材料(研究の音): %s の「%s」を文字起こしに頼みました" % (who, title[:40]))
            except Exception as e:   # noqa: BLE001  (頼めなければ消す = 研究の置き場を残さない。取り直しはこちらの取得が埋める)
                log("誰の声の材料(研究の音): %s を頼めませんでした(%s)" % (vid, str(e)[:120]))
        for p in (audio, mp):
            if p:
                fsio.unlink_quiet(p)
    if took:
        fsio.write_json(st_path, state, indent=None)
    return took
