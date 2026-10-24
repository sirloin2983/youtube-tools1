"""誰の声の材料が無いメンバーの音を YouTube から少しだけ取る(10-25。ユーザー「全メンバー揃えてほしい」の 2。1 = 手元の学習用データ は voicefill)。

名簿の日本の今のメンバー(EN・ID・ユニット・卒業の組は除く。10-25 ユーザー「EN・ID は外す」)のうち、材料が無い人(手元のソロの文書・覚えた声の登録簿・学習用データ・ここで取った物のどれにも無い)を
1 人ずつ: チャンネルの RSS(最近の 15 本)から雑談らしい配信を 1 本選び(歌・コラボ・ショートは外す)、その SECTION 秒の所の音だけを
yt-dlp の --download-sections で取って(音だけ・cookie なし)、「編集」の文字起こしに頼む。できた文書は誰の声のカードだけに使う
(sources.View.docs が外す = voicefill.in_learn_dir と同じ決まり。見立て = 名前を付けたファイルの名前の人)。
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
MAX_TRIES = 4                 # 1 人につき試す配信の数(取れなければ次の回に次の配信)
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
    """RSS -> [{"id", "title"}](新しい順)"""
    try:
        root = ET.fromstring(body)
    except (ET.ParseError, ValueError):
        return []
    out = []
    for e in root.findall("a:entry", NS):
        vid = (e.findtext("yt:videoId", "", NS) or "").strip()
        if VIDEO_RE.match(vid):
            out.append({"id": vid, "title": (e.findtext("a:title", "", NS) or "").strip()})
    return out


def choose(items, tried):
    """雑談らしい配信を 1 本(歌・コラボ・ショート・試した物を外す。雑談の印がある物が先)か None"""
    ok = [it for it in items if it["id"] not in tried and not SHORT_RE.search(it["title"]) and not _vm.song_title(it["title"])
          and not _vm.COLLAB_RE.search(it["title"])]
    ok.sort(key=lambda it: not TALK_RE.search(it["title"]))
    return ok[0] if ok else None


def _rss(channel, timeout=20):
    req = urllib.request.Request(RSS_URL % channel, headers={"User-Agent": "Mozilla/5.0"})
    with urllib.request.urlopen(req, timeout=timeout) as r:   # noqa: S310  (決まった youtube.com の RSS だけ)
        return r.read(2 * 1024 * 1024)


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
    try:
        r = subprocess.run(cmd, capture_output=True, text=True, encoding="utf-8", errors="replace", timeout=timeout, stdin=subprocess.DEVNULL,
                           creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0))
    except (OSError, subprocess.TimeoutExpired) as e:
        return None, "%s" % e.__class__.__name__
    d, base = os.path.dirname(out_base), os.path.basename(out_base)
    got = [os.path.join(d, x) for x in os.listdir(d) if x.startswith(base + ".") and not x.endswith((".part", ".ytdl"))]
    if r.returncode == 0 and got:
        return max(got, key=os.path.getsize), ""
    return None, ((r.stderr or "") + (r.stdout or ""))[-400:].strip() or "終了コード %s" % r.returncode


def _todo(roster_r, have, state, extra=None):
    return [(n, c) for n, c in members(roster_r, extra) if n not in have and not (state.get(n) or {}).get("got")
            and len((state.get(n) or {}).get("tried") or []) < MAX_TRIES]


def wants(app_dir, roster_r, have, now=None, extra=None):
    """今 YouTube から取りたいか(動かす時刻・材料の無い人が残っている・枠が空いている)。学習用データの文字起こし(voicefill)はこの間は休む
    = 入口の手の空いた合間をこちらに譲る(10-25: 文字起こしが続いて、こちらがいつ見ても処理中だった)"""
    now = time.time() if now is None else now
    if not ENABLED or not (HOURS[0] <= datetime.datetime.fromtimestamp(now).hour < HOURS[1]):
        return False
    return bool(_todo(roster_r, have, _read(os.path.join(app_dir, "check", STATE_NAME)), extra)) and slot_free(app_dir, now)[0]


def tick(app_dir, roster_r, have, busy, start_job, log, now=None, rss=None, fetch=None, extra=None):
    """1 回分: 材料の無い人を 1 人取って文字起こしに頼む。-> 頼んだ人の名前か None。have = 材料のある人の名前の集合"""
    now = time.time() if now is None else now
    if not ENABLED or not (HOURS[0] <= datetime.datetime.fromtimestamp(now).hour < HOURS[1]) or busy():
        return None
    st_path = os.path.join(app_dir, "check", STATE_NAME)
    state = _read(st_path)
    todo = _todo(roster_r, have, state, extra)
    if not todo:
        return None
    free, why = slot_free(app_dir, now)
    if not free:
        return None
    who, chan = min(todo, key=lambda x: (len((state.get(x[0]) or {}).get("tried") or []), todo.index(x)))   # 試した数の少ない人・日本が先
    rec = state.setdefault(who, {"tried": []})
    _mark_slot(app_dir, now)
    try:
        items = parse_rss((rss or _rss)(chan))
    except Exception as e:   # noqa: BLE001  (RSS が読めなければ次の回)
        log("誰の声の材料(YouTube): %s のチャンネルの一覧を読めませんでした(%s)" % (who, e.__class__.__name__))
        return None
    it = choose(items, set(rec["tried"]))
    if it is None:
        rec["tried"].append("none")
        fsio.write_json(st_path, state, indent=None)
        log("誰の声の材料(YouTube): %s の最近の配信に雑談らしい物がありませんでした" % who)
        return None
    rec["tried"].append(it["id"])
    folder = os.path.join(app_dir, "check", DIR_NAME, who)
    os.makedirs(folder, exist_ok=True)
    for x in os.listdir(folder):   # 途中で残った物(PC の再起動・止まった取得)= 消して取り直す。取れた音は state の got にあり、ここへは来ない
        fsio.unlink_quiet(os.path.join(folder, x))
    safe = re.sub(r'[\\/:*?"<>|\x00-\x1f]', "_", it["title"])[:60]
    path, err = (fetch or _fetch)(it["id"], os.path.join(folder, "%s_%s_%s" % (who, it["id"], safe)))
    if path is None:
        if any(b in err.lower() for b in BOT):
            _mark_slot(app_dir, now, stop_why=err[:200])
            log("誰の声の材料(YouTube): bot 判定・ログインを求められたので今日は止めます(研究も止まる)")
        else:
            log("誰の声の材料(YouTube): %s の %s の音を取れませんでした(%s)" % (who, it["id"], err.splitlines()[-1][:160] if err else ""))
        fsio.write_json(st_path, state, indent=None)
        return None
    rec.update(got=path, video=it["id"], title=it["title"][:200], at=int(now))
    try:
        rec["job"] = start_job({"sourcePath": path, "autoLlm": False, "title": "%s %s" % (who, it["title"][:150])})
    except Exception as e:   # noqa: BLE001  (取った音は残る = 次に頼み直せるよう got を消す)
        rec.pop("got", None)
        log("誰の声の材料(YouTube): %s の音を文字起こしに頼めませんでした(%s)" % (who, str(e)[:120]))
    fsio.write_json(st_path, state, indent=None)
    log("誰の声の材料(YouTube): %s の「%s」の %d〜%d 秒の音を取りました(残り %d 人)" % (who, it["title"][:40], SECTION[0], SECTION[1], len(todo) - 1))
    return who
