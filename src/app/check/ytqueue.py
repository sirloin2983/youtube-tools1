"""YouTube の取得の列(10-25。ユーザー「取り方 1 と 2 を統一しよう」「取得する配信を選ぶ段階で効率化できるはず」)。

研究(overlap-research の m2)と誰の声の材料(voicefetch)が別々に YouTube へ問い合わせていたのを、入口のこの列 1 本にまとめる。
置き場 <app>/check/yt-queue/:
  req/<id>.json        研究の頼み {"id", "purpose": "research", "kind": "info"|"audio"|"list", "priority", "hint": {"channel", "title"}, ...}
                       info: "urls"(10 本まで。説明欄など)/ audio: "url", "section": [始め, 終わり] か null / list: "url", "items" /
                       chat: "url"(チャットのリプレイ。長い配信は問い合わせが多いので研究が頼む物だけ)/
                       subs: "urls"(5 本まで)か "url"(人の手の字幕があれば手・無ければ自動。軽い物のまとめ = 返事は "files": {動画: 字幕のパス}・"subsKind": {動画: "手" | "自動"}。。研究が手元のショートの文字と突き合わせて ?t= の無い候補の位置を出す = 全体の音を取らずに済む)
  done/<id>.json       結果 {"id", "state": "done"|"error", "error", "at", "infos" | "file" + "info" | "entries"}。音は done/<id>.<拡張子>。
                       読む側が消す(DONE_DAYS 日残っていれば列が消す)
  candidates.json      研究が置く候補 = 友人のショートの元の配信 [{"video", "t"(?t= の秒か null), "channel", "title", "uploadDate", "research"(研究に効く度合い 0〜1)}]
  short-sources.json   友人のショートの説明欄の【元配信】と ?t=(API で 50 本ずつ・6 時間ごとに新しいショートだけ = read_short_sources)。研究が rev_desc に足す
  state.json           列の状態(最後に取った時刻・側・間隔・API の使用量)。ready.json = 列が動いている印(研究はこれを見て自分の問い合わせをやめる)
音の選び方(1 回に 1 本・音の段の間隔。10-25 ユーザー: 研究と声を交互に回すのはやめた): 軽い物を除く全部の頼みを 1 つの一覧(plan)で点を付け、いちばん高い 1 本。
  候補 = 研究(research)+ 声(日本の対象のメンバーのソロと見える題名で、配信の材料が TARGET 本に届かない・取った月と違う)− 区間の長さ。
  研究の頼み = 種類の点(REQ_BASE。字幕・動画の情報 = あとの音の取得を短くできる軽い物は高く)+ 声 + priority − 区間の長さ。
  声だけ = 友人のショートの元(候補)に無いメンバーの材料の足りなさ(voicefetch.tick で RSS・一覧から)。
  取る区間 = 候補の ?t= の前 AROUND[0] 秒〜後 AROUND[1] 秒(研究の 2 段の探し方に足りる幅)。声の材料もその区間から(voice-inbox → voicefetch.intake が 4 分に)。
  info の頼みは、YouTube Data API のキーがあれば公式の窓口(ytt/ytapi。1 日 API_DAILY まで・50 本ずつ)で読み、枠を使わない。無ければ yt-dlp(枠を使う)。
  キーの値は読まない・出さない(ytapi が見出しで送る。ここは有無と成否だけ)。
決まり: ツールの YouTube のログインで取る(10-25 ユーザー「ログインして」。voicefetch._ytdlp。切れていれば cookie なし)・
  再起動で途中の物は次に取り直す(done/.dl を消す・頼みは done が書けるまで残る)。
軽い物と音(10-25 ユーザー「軽い問い合わせはまとめて同時に取得すればいい」「当たったらその日は全部止めるは極端すぎる」):
  軽い物(字幕 subs・API が使えない日の動画の情報 info)= 1 時間に 1 回、yt-dlp 1 回で最大 N 本まとめて(--skip-download・--sleep-requests)。
    処理中・ライブ中でも取る(軽いので)。N = LIGHT_N の段(当たらずに UP_AFTER 回続けば 1 段増やす。10-25 まとめ役)。
  音 = AUDIO_MIN の段の分おきに 1 本(同じく 1 段縮める = 上限の段階の実験)。処理中は BUSY_SLOWER 段遅く続ける。
  ライブ中は、音・チャット・字幕・説明欄・候補など列の頼みを全部ふだんどおり取る(10-25 ユーザー「ライブ中でもそんなに重くない」「ほかの研究に必要なものも」)。
  当たったら 1 段落とす(いちばん下なら本数を半分・間隔を 1.5 倍)。
  当たりの種類(classify): rate(429・速すぎ)・bot(ボット確認・ログインを求められた)= 当たった側(軽い物か音)だけ RESTS 分休み(続けば伸ばす)、
    本数を半分・間隔を 1.5 倍で続ける。当たらずに 3 回続けば 1 段ずつ戻す。gone(404・動画が無い・メンバー限定)= 数えない・その動画だけ飛ばす・枠も使わない。
    4 時間休んでもまた当たったら記録に「要知らせ」。1 日の終わりに、段の動きを記録に 1 行。
  結果に待ち時間 waitSec(頼み → 返事)を入れ、記録にも出す(研究の progress.md が読む)。
使い道の束(10-25 ユーザー「当たりでも外れでも使える物は全部使う」): 音を取る問い合わせの中で、動画の情報(説明欄・チャプター・よく見られている場面の山)と
  日本語の自動字幕も keep/<動画>/ に小さく残す(bundle)。結果の info.bundle に場所。分析(区間・編集カット・同時発話・置換辞書の候補・BGM)は研究。
  keep は DONE_DAYS 日で消す(研究が keep/<動画>/hold を置いた物は残す)。
切り替えの前後で二重に取らないよう、研究の古い道の印 yt-slot.json(voicefetch.slot_free)も見て、取ったら書く。
"""
import contextlib
import datetime
import json
import os
import re
import shutil
import time

from flow import voicematerial as _vm
from ytt import fsio, settings as _settings, ytapi as _ytapi, ytledger as _ytledger
from ytt.errors import ApiError
from . import voicefetch as _vf

ENABLED = True
DIR_NAME = "yt-queue"
AUDIO_MIN = [60, 40, 30, 20, 15, 10, 7, 5]   # 音の間隔の段(分)。当たらずに UP_AFTER 回続けば 1 段縮め、当たったら 1 段戻す(上限の段階の実験。10-25 夜 5 分まで)
BUSY_SLOWER = 2                       # 処理中は音を止めず、この段だけ遅い間隔で続ける。ライブ中はふだんと同じ間隔(10-25 ユーザー「ライブ中でもそんなに重くない」)
LIVE_BUSY = "ライブ"                  # 入口の busy() がライブ中に返す文(ライブだけなら列の頼みは全部ふだんどおり)
LEDGER_MAX = 6.0                      # 製品のほかの YouTube への問い合わせ(帳簿 ytt/ytledger)の直近 30 分の重みがこれを超えたら、音の回を次へ延ばす(製品が先)
DAILY_NAME = "daily.jsonl"            # 1 日 1 行(研究の progress.md が読む): 音の本数・軽い物・ほかの問い合わせ・当たり・段
LIGHT_N = [5, 10, 20, 30]             # 軽い物を 1 回でまとめる本数の段(同じく)
UP_AFTER = 3                          # 当たらずにこの回数続けば 1 段上げる(10-25 まとめ役: 日が明けるごとでは遅い)
LIGHT_EVERY = 3600                    # 軽い物の回の間隔(秒)
RESTS = [30, 60, 120, 240]            # 当たったときに休む分(1 日の中で続けて当たるほど伸ばす)
SLEEP_REQ = 3                         # 軽い物のまとめの 1 本ごとの間(秒。--sleep-requests)
LIGHT_KINDS = ("subs",)               # まとめて取る軽い頼み(info は API。API が使えない日だけここに入れる)
CHAT_START = 10                       # チャットの回で取る本数の始まり(10-25 ユーザー「最初 1 回 10 本」)。当たるたびに半分(その日のうち。1 本まで)
LOCK_NAME = "run.lock"                # 列の錠(入口の見回りと手で流す 1 回がぶつからない)
LOCK_STALE = 3 * 3600                 # これより古い錠は残りかす(落ちたプロセスの物)として取り直す
AROUND = (300, 600)                  # 候補の ?t= の前 5 分〜後 10 分を取る(研究の今の幅)
API_DAILY = 2000                     # 列が 1 日に使う YouTube Data API の量の上限(1 日 10,000 をスタジオと分け合う)
DONE_DAYS = 3
SERVED_KEEP = 5000   # 済んだ頼みの id を覚える数
STAGE = ".dl"        # 取っている途中の音の置き場(done/.dl/。済んだら done へ移す = 止まっても途中の音が done に残らない)
ID_RE = re.compile(r"^[A-Za-z0-9_-]{1,64}\Z")
URL_RE = re.compile(r"^https://(www\.|m\.)?(youtube\.com|youtu\.be)/[\w\-./?=&%:@+]{1,300}\Z")
KINDS = ("info", "audio", "list", "subs", "chat")
_blocked_now = set()   # 評価用のショートの元の配信(tick が eval-sources.json から入れる。score が外す)


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
        urls = [r.get("url")] if r.get("kind") in ("audio", "list", "chat") else (r.get("urls") or ([r.get("url")] if r.get("url") else []))[:10]
        if r.get("kind") == "subs":
            urls = urls[:5]   # 字幕は 1 つの頼みで 5 本まで(研究)
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
    if c["video"] in done_videos or c["video"] in _blocked_now:
        return 0.0, 0.0, 0.0   # 取った物・評価用のショートの元の配信(10-25)
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


def _cls(st, name):
    c = st.get(name) if isinstance(st.get(name), dict) else {}
    st[name] = c
    for k, v in (("step", 0), ("pen", 0), ("level", 0), ("pause", 0), ("ok", 0)):
        c.setdefault(k, v)
    return c


def audio_gap(st, slower=0):
    """音の間隔(秒)= AUDIO_MIN の段(slower 段だけ遅く)× 1.5 の当たった回数乗"""
    a = _cls(st, "audio")
    return AUDIO_MIN[max(0, min(a["step"], len(AUDIO_MIN) - 1) - slower)] * 60 * (1.5 ** a["pen"])


def light_n(st):
    """軽い物を 1 回でまとめる本数 = LIGHT_N の段 ÷ 2 の当たった回数乗(1 本まで)"""
    c = _cls(st, "light")
    return max(1, LIGHT_N[min(c["step"], len(LIGHT_N) - 1)] // (2 ** c["pen"]))


def rollover(st, now, log=None, app_dir=None):
    """日が変わった最初の回: 休みの段と当たった回数を始めから・前の日の当たりの数と今の段を記録に 1 行(段の上げ下げは回ごと = fine・hit)"""
    today = datetime.date.fromtimestamp(now).isoformat()
    if st.get("day") == today:
        return
    notes = []
    for name in ("audio", "light"):
        c = _cls(st, name)
        c.update(level=0, pen=0, chatPen=0)   # 休みの段と当たった回数は日ごとに始めから(段 step は回ごとの fine・hit が上げ下げする)
        if c.get("cap") is not None:   # 前の日に当たった = 当たった段の 1 段手前から始める(毎日同じ所で当たらない。10-25 夜)
            c["step"] = min(c["step"], int(c["cap"]))
            notes.append("%sは前の日に %sで当たったので %sから" % ("音" if name == "audio" else "軽い物", c.get("capAt") or "?",
                                                                   ("%d 分おき" % (audio_gap(st) // 60)) if name == "audio" else ("%d 本まとめ" % light_n(st))))
            c.pop("cap", None)
            c.pop("capDay", None)
        notes.append("%s 当たり %d 回" % ("音" if name == "audio" else "軽い物", int(c.get("hits") or 0)))
        c["hits"] = 0
    if st.get("day") and log:
        d0 = time.mktime(datetime.date.fromisoformat(st["day"]).timetuple())
        dc = _ytledger.day_counts(d0, d0 + 86400)
        others = {k: v for k, v in dc["by"].items() if not k.startswith("queue:")}
        audio_n = dc["by"].get("queue:fetch", 0)
        log("YouTube の取得の列: %s の段の動き(%s)。音 %d 本・ほかの問い合わせ %d 回(%s)・当たり %s。今日は 音 %d 分おき・軽い物 %d 本まとめ"
            % (st["day"], "・".join(notes), audio_n, sum(others.values()), "・".join("%s %d" % kv for kv in sorted(others.items())) or "なし",
               "・".join("%s %d" % kv for kv in sorted(dc["hits"].items())) or "なし", audio_gap(st) // 60, light_n(st)))
        if app_dir:
            try:
                fsio.append_jsonl(qdir(app_dir, DAILY_NAME), [{"day": st["day"], "audio": audio_n, "light": dc["by"].get("queue:light", 0),
                                                              "others": others, "hits": dc["hits"], "notes": notes,
                                                              "nowAudioMin": audio_gap(st) // 60, "nowLightN": light_n(st)}])
            except OSError:
                pass
        _ytledger.prune(now)
    st["day"] = today


def classify(err):
    """失敗の文 -> "rate"(速すぎ)| "bot"(ボット確認・ログインを求められた)| "gone"(動画が無い・メンバー限定・404 = 判定ではない)| None"""
    e = str(err or "").lower()
    if "429" in e or "too many requests" in e:
        return "rate"
    if any(w in e for w in ("not a bot", "sign in to confirm", "login required", "confirm you")):
        return "bot"
    if any(w in e for w in ("404", "video unavailable", "private video", "members-only", "members only", "has been removed", "not available", "does not exist")):
        return "gone"
    return None


def hit(st, name, kind, now, log):
    """当たった: その側だけ休む(続けて当たるほど RESTS を伸ばす)・段を 1 つ落とす(いちばん下なら本数を半分 / 間隔を 1.5 倍)"""
    c = _cls(st, name)
    c["capAt"] = ("%d 分おき" % (audio_gap(st) // 60)) if name == "audio" else ("%d 本まとめ" % light_n(st))   # 当たった間隔(その日の上限・記録)
    c["cap"], c["capDay"] = max(0, c["step"] - 1), datetime.date.fromtimestamp(now).isoformat()   # その日はこの段より速くしない
    c["level"] = min(c["level"] + 1, len(RESTS))
    c["pause"] = now + RESTS[c["level"] - 1] * 60
    if c["step"] > 0:
        c["step"] -= 1
    else:
        c["pen"] += 1
    c["ok"] = 0
    c["hits"] = int(c.get("hits") or 0) + 1
    c["hitDay"] = datetime.date.fromtimestamp(now).isoformat()
    tag = "音" if name == "audio" else "軽い物"
    log("YouTube の取得の列: %sで当たりました(%s)。%d 分休み、そのあと %s で続けます%s"
        % (tag, "速すぎの断り" if kind == "rate" else "ボット確認・ログインを求められた", RESTS[c["level"] - 1],
           ("%d 分おき" % (audio_gap(st) // 60)) if name == "audio" else ("%d 本まとめ" % light_n(st)),
           "(要知らせ: 4 時間休んでもまた当たりました)" if c["level"] == len(RESTS) and c["hits"] > len(RESTS) else ""))


def fine(st, name, log=None):
    """当たらずに済んだ: UP_AFTER 回続けば 1 段 = 半分にした本数・伸ばした間隔を戻す → 休みの段を戻す → 段を上げる(本数を増やす・間隔を縮める)。
    段を上げたら記録に 1 行(本数・間隔・今日の当たりの数)"""
    c = _cls(st, name)
    c["ok"] += 1
    if c["ok"] < UP_AFTER:
        return
    c["ok"] = 0
    top = (len(AUDIO_MIN) if name == "audio" else len(LIGHT_N)) - 1
    if c["pen"]:
        c["pen"] -= 1
    elif c["level"]:
        c["level"] -= 1
    elif c["step"] < (top if c.get("cap") is None else min(top, int(c["cap"]))):   # 当たった日は当たった段の 1 段手前まで
        c["step"] += 1
        if log:
            log("YouTube の取得の列: 当たらずに %d 回続いたので段を上げました(%s。今日の当たり %d 回)"
                % (UP_AFTER, ("音 %d 分おき" % (audio_gap(st) // 60)) if name == "audio" else ("軽い物 %d 本まとめ" % light_n(st)), int(c.get("hits") or 0)))


def due(app_dir, now, slower=0, ledger_weight=0.0):
    """音を今取ってよいか -> (よいか, 理由)。休み・音の段の間隔(slower 段だけ遅く = 処理中)・
    ほかの問い合わせの直近 30 分の重み ledger_weight が LEDGER_MAX を超えていれば延ばす(製品が先)"""
    st = _state(app_dir)
    a = _cls(st, "audio")
    if now < a["pause"]:
        return False, "当たったので休んでいます(あと %d 分)" % ((a["pause"] - now) // 60)
    if ledger_weight > LEDGER_MAX:
        return False, "ほかの YouTube への問い合わせが多い(直近 30 分の重み %.1f)" % ledger_weight
    last = _vm.num(st.get("last"))
    gap = audio_gap(st, slower)
    if now - last < gap:
        return False, "前の取得から %d 分(間隔 %d 分)" % ((now - last) // 60, gap // 60)
    return True, ""


def _api_left(st, today):
    used = st.get("api") if isinstance(st.get("api"), dict) else {}
    return API_DAILY - int(used.get(today) or 0)


def _api_count(st, today, n):
    used = st.get("api") if isinstance(st.get("api"), dict) else {}
    st["api"] = {today: int(used.get(today) or 0) + n}


def _write_done(app_dir, rid, body):
    """結果を done/<rid>.json に。頼み(req/<rid>.json)は消し、済んだ印を state の served に覚える = 研究が done を消しても二度取らない(10-25)。
    頼みのファイルがあれば待ち時間 waitSec(頼み → 返事)を入れる"""
    os.makedirs(qdir(app_dir, "done"), exist_ok=True)
    p = qdir(app_dir, "done", rid + ".json")
    try:
        body = dict(body, waitSec=int(time.time() - os.path.getmtime(qdir(app_dir, "req", rid + ".json"))))
    except OSError:
        pass
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
    r, tail = _vf._ytdlp([yd, "--encoding", "utf-8", "--no-warnings", "--skip-download", "--no-playlist", "-j", "--"] + list(urls), 300)
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
    r, tail = _vf._ytdlp(cmd + ["--", url], _vf.FETCH_TIMEOUT * 2)
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
    r, tail = _vf._ytdlp([yd, "--encoding", "utf-8", "--no-warnings", "--no-playlist", "--skip-download", "--sleep-requests", str(SLEEP_REQ),
                          "--write-subs", "--sub-langs", "live_chat",
                        "-o", os.path.join(d, "chat.%(ext)s"), "-o", "subtitle:" + os.path.join(d, "chat"), "--", url], 1800)   # 既定の -o = 途中の .part も d へ(無いと作業フォルダに書く。10-26)
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
    r, tail = _vf._ytdlp([yd, "--encoding", "utf-8", "--no-warnings", "--no-playlist", "--skip-download", "--write-auto-subs", "--sub-langs", "ja",
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
    return classify(err) in ("rate", "bot")


def _hit(st, now, err, log, name="audio"):
    """当たった(rate・bot)を段の守りに渡す(st は呼び手が書く)"""
    hit(st, name, classify(err) or "bot", now, log)


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
    """1 回分 -> 取った物の説明か None。busy() = 休む理由か None。YouTube に問い合わせた回は、ログインつきだったかを記録に 1 行"""
    _vf.LOGIN.update(used=None)
    t0 = time.time()
    got = _tick(app_dir, roster_r, counts, busy, start_job, log, extra=extra, now=now)
    if _vf.LOGIN.get("used") is not None:
        if _vf.LOGIN.get("at", 0) >= t0:
            log("YouTube の取得の列: ツールの YouTube のログインで断られたので、cookie なしで取り直しました(ログインし直しが要るかもしれません)")
        else:
            log("YouTube の取得の列: %s で取りました" % ("ツールの YouTube のログインつき" if _vf.LOGIN["used"] else "ログインなし(ツールにログインが入っていない)"))
    return got


def _tick(app_dir, roster_r, counts, busy, start_job, log, extra=None, now=None):
    """tick の本体"""
    now = time.time() if now is None else now
    if not ENABLED:
        return None
    tidy(app_dir, now)
    _api_infos(app_dir, log, now)        # API の読み込みは軽いので処理中でも読む(枠も使わない)
    fill_candidates(app_dir, now, log)
    read_short_sources(app_dir, os.path.join(os.path.dirname(app_dir), "analytics", "raw"), now, log)   # 友人のショートの元の配信(API)
    try:   # 評価用のショートの元の配信 = 外す(10-25)
        eval_sources(app_dir, _settings.eval_dirs(), os.path.join(os.path.dirname(app_dir), "analytics", "raw"), now, log)
    except (OSError, TypeError, ValueError):   # 評価用のフォルダが決まっていない(作業データの置き場所が無い)・読めない = 前の一覧のまま
        pass
    _blocked_now.clear()
    _blocked_now.update(blocked_videos(app_dir))
    st = _state(app_dir)
    rollover(st, now, log, app_dir)
    led = _ytledger.load(now, exclude_src=("queue",))   # 製品のほかの問い合わせ(帳簿)= 列は自分の分を数えない
    fresh = [h for h in led["hits"] if h[0] > float(st.get("ledgerHit") or 0)]
    if fresh:   # 誰かが当たった(429・ボット確認)= 列も同じ休みに入る(音と軽い物の両方)
        at, kind, src = max(fresh)
        st["ledgerHit"] = at
        for name in ("audio", "light"):
            hit(st, name, kind, now, lambda m, s=src: log(m + "(当たったのは %s)" % s))
    _save(app_dir, st)
    light = light_batch(app_dir, now, log)   # 軽い物は処理中・ライブ中でも(10-25)
    why = busy()
    if why and str(why).startswith("新しい版"):   # 入口の起動し直しの待ち = 新しく取らない(起き直しを延ばさない)
        return light
    if not why or why == LIVE_BUSY:   # ライブ中もふだんどおり(処理中だけ休む)
        with run_lock(app_dir) as mine:   # 手で流すチャットの 1 回とぶつからない
            light = (chat_batch(app_dir, now, log) if mine else None) or light   # チャットは処理中でないときだけ(1 本で長くかかる)
    ok, _why = due(app_dir, now, BUSY_SLOWER if why and why != LIVE_BUSY else 0, led["weight"])   # 処理中は止めず 2 段遅く・ライブ中はふだんどおり・製品の問い合わせが多ければ延ばす(10-25 夜)
    if not ok:
        return light
    st = _state(app_dir)
    chan_of = {c: n for n, c in _vf.members(roster_r, extra)}
    ranked = [o for o in plan(app_dir, roster_r, counts, extra, st=st, now=now) if not (o["kind"] == "request" and o["req"]["kind"] in LIGHT_KINDS + ("info", "chat"))]
    if not ranked:
        return light
    best = ranked[0]
    prev_last = st.get("last")
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
                _hit(st, now, info, log)
            elif classify(info) == "gone":
                st["last"] = prev_last   # 動画が無い・メンバー限定 = 枠に数えない(次の見回りで次の 1 本)
            _write_done(app_dir, rid, {"state": "error", "error": str(info)[:300], "video": c["video"]})
            _save(app_dir, st)
            log("YouTube の取得の列: 候補 %s を取れませんでした(%s)" % (c["video"], str(info).splitlines()[-1][:120] if info else ""))
            return None
        fine(st, "audio", log)
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
            _hit(st, now, body["error"], log)
        elif body["state"] == "error" and classify(body.get("error")) == "gone":
            st["last"] = prev_last   # 枠に数えない
        else:
            fine(st, "audio", log)
        _write_done(app_dir, r["id"], body)
        _save(app_dir, st)
        log("YouTube の取得の列: 研究の頼み %s(%s)を%s" % (r["id"], r["kind"], "済ませました" if body["state"] == "done" else "済ませられませんでした"))
        return "research"
    _save(app_dir, st)   # 声だけ = 候補に無いメンバーを RSS・一覧で(voicefetch)
    _vf.LAST_ERR["err"] = ""
    got = _vf.tick(app_dir, roster_r, counts, lambda: None, start_job, log, now=now, extra=extra, use_slot=False, only={best["who"]})
    st = _state(app_dir)
    if _bot(_vf.LAST_ERR["err"]):
        _hit(st, now, _vf.LAST_ERR["err"], log)
    elif got:
        fine(st, "audio", log)
    _save(app_dir, st)
    return "voice" if got else None


REQ_BASE = {"subs": 1.6, "info": 1.4, "list": 0.9, "audio": 1.0, "chat": 0.6}   # 研究の頼みの点の元(字幕・動画の情報 = あとの音の取得を短くできる軽い物は高く)
AGE_PER_H, AGE_MAX = 0.05, 1.0        # 研究の頼みの待った時間の点(1 時間に 0.05・上限 1.0)。10-26: 配信全体の音(r-full-*)が区間の長さの引きで一度も順番を取れなかった
STARVE_SEC, STARVE_BONUS = 24 * 3600, 10.0   # これより長く待った頼みは一番上へ(どの頼みも 24 時間より長く飢えない。古い順)


def light_batch(app_dir, now, log):
    """軽い物の回(LIGHT_EVERY に 1 回・休みでなければ): 字幕(と API が使えない日の info)の頼みを、URL で最大 light_n 本まで yt-dlp 1 回でまとめて取る
    (--skip-download・自動字幕と動画の情報だけ・1 本ごとに SLEEP_REQ 秒)。-> "light" か None"""
    st = _state(app_dir)
    c = _cls(st, "light")
    if now < c["pause"] or now - _vm.num(c.get("last")) < LIGHT_EVERY:
        return None
    today = datetime.date.fromtimestamp(now).isoformat()
    kinds = LIGHT_KINDS + (("info",) if st.get("apiOff") == today else ())
    n = light_n(st)
    picked, urls = [], []
    for q in requests(app_dir):
        if q["kind"] in kinds and len(urls) + len(q["urls"]) <= n:
            picked.append(q)
            urls += q["urls"]
    if not picked:
        return None
    c["last"] = now
    got, err = _light_fetch(app_dir, urls)
    kind = classify(err) if not got else None
    if kind in ("rate", "bot"):
        hit(st, "light", kind, now, log)
        _save(app_dir, st)
        return None   # 頼みは残す(休みのあとに取り直す)
    fine(st, "light", log)
    _save(app_dir, st)
    for q in picked:
        vids = [v for v in (_video_of(u) for u in q["urls"]) if v]
        if q["kind"] == "subs":
            files = {v: got[v]["subs"] for v in vids if v in got and got[v].get("subs")}
            infos = {v: got[v]["info"] for v in vids if v in got and got[v].get("info")}   # 動画の情報(heatmap・チャプター入り。同じ呼び出しで取った物)
            kinds_ = {v: k for v in files for k in [sub_kind(infos.get(v))] if k}   # 手 / 自動の印(研究の頼み。問い合わせは増やさない)
            body = ({"state": "done", "files": files, "file": next(iter(files.values()), None), "infos": infos, "subsKind": kinds_} if files
                    else {"state": "error", "error": (err or "自動字幕がありません")[:300], "infos": infos})
        else:
            infos = [fsio.read_json_or(got[v]["info"], {}, kind=dict) for v in vids if v in got and got[v].get("info")]
            body = {"state": "done", "infos": infos, "via": "yt-dlp"} if infos else {"state": "error", "error": (err or "読めませんでした")[:300]}
        _write_done(app_dir, q["id"], body)
    log("YouTube の取得の列: 軽い物を %d 本まとめて取りました(頼み %d 件・字幕のあった動画 %d 本・まとめの上限 %d)"
        % (len(urls), len(picked), sum(1 for v in got.values() if v.get("subs")), n))
    return "light"


def chat_n(st):
    """チャットの回で取る本数 = CHAT_START ÷ 2 の(軽い物の当たった回数 + チャットで当たった回数)乗(1 本まで。日が変わると始めから)"""
    c = _cls(st, "light")
    return max(1, CHAT_START // (2 ** (c["pen"] + int(c.get("chatPen") or 0))))


@contextlib.contextmanager
def run_lock(app_dir, now=None):
    """列の錠(qdir/run.lock を作れたら True)。取れなければ False(ほかが回している)。LOCK_STALE より古い錠は取り直す"""
    p = qdir(app_dir, LOCK_NAME)
    os.makedirs(os.path.dirname(p), exist_ok=True)
    now = time.time() if now is None else now
    try:
        if now - os.path.getmtime(p) > LOCK_STALE:
            fsio.unlink_quiet(p)
    except OSError:
        pass
    try:
        fd = os.open(p, os.O_CREAT | os.O_EXCL | os.O_WRONLY)
    except OSError:
        yield False
        return
    try:
        os.write(fd, str(os.getpid()).encode())
        os.close(fd)
        yield True
    finally:
        fsio.unlink_quiet(p)


def chat_batch(app_dir, now, log, n=None, force=False):
    """チャットの回(LIGHT_EVERY に 1 回・軽い物の休みでなければ): 研究の chat の頼みを chat_n 本まで(点の高い順)1 本ずつ取る。
    10-25 まで chat は音の枠で点を競い(REQ_BASE 0.6)、候補・声にいつも負けて 1 件も取られていなかった = 軽い物の側の守り(休み・段)で別に回す。
    当たったら軽い物と同じく休み、次の回の本数を半分に(頼みは残す)。取ってあれば取らずに済ませる。
    n・force = 手で流す 1 回(本数・間隔を無視。休みは守る)。-> "chat" か None"""
    st = _state(app_dir)
    c = _cls(st, "light")
    if now < c["pause"] or (not force and now - _vm.num(c.get("chatLast")) < LIGHT_EVERY):
        return None
    picked = [q for q in requests(app_dir) if q["kind"] == "chat" and q["urls"]][:n or chat_n(st)]
    if not picked:
        return None
    c["chatLast"] = now
    _save(app_dir, st)
    done = 0
    for q in picked:
        vid = _video_of(q["urls"][0])
        have = bundle(app_dir, vid).get("chat") if vid else None
        path, err = (have, "") if have else _chat(app_dir, q["urls"][0])
        kind = classify(err) if not path else None
        if kind in ("rate", "bot"):
            st = _state(app_dir)
            hit(st, "light", kind, now, log)
            lc = _cls(st, "light")
            lc["chatPen"] = int(lc.get("chatPen") or 0) + 1
            _save(app_dir, st)
            break   # 頼みは残す(休みのあとに取り直す)
        _write_done(app_dir, q["id"], {"state": "done", "file": path, "bundle": bundle(app_dir, vid)} if path else {"state": "error", "error": (err or "")[:300]})
        done += 1
        if not have:
            st = _state(app_dir)
            fine(st, "light", log)
            _save(app_dir, st)
    if done:
        log("YouTube の取得の列: チャットの頼みを %d 件済ませました(残り %d 件・1 回 %d 本まで)"
            % (done, sum(1 for q in requests(app_dir) if q["kind"] == "chat"), chat_n(_state(app_dir))))
    return "chat" if done else None


def sub_kind(info_path, lang="ja"):
    """取った字幕が人の手か自動か(同じ呼び出しで取った動画の情報の subtitles に lang があれば 手。yt-dlp は両方あれば手を書く)-> "手" | "自動" | None"""
    d = fsio.read_json_or(info_path, None, kind=dict) if info_path else None
    if not d:
        return None
    return "手" if lang in (d.get("subtitles") or {}) else ("自動" if lang in (d.get("automatic_captions") or {}) else None)


def _light_fetch(app_dir, urls):
    """yt-dlp 1 回で、URL を並べて字幕(人の手があれば手・無ければ自動。10-25 研究の頼み)と動画の情報だけ -> ({動画: bundle}, 失敗の文)"""
    yd = _vf._tools.find_tool("yt-dlp")
    if not yd:
        return {}, "yt-dlp が見つかりません"
    keep = qdir(app_dir, KEEP_DIR, "%(id)s")
    r, tail = _vf._ytdlp([yd, "--encoding", "utf-8", "--no-warnings", "--ignore-errors", "--no-playlist", "--skip-download",
                          "--sleep-requests", str(SLEEP_REQ), "--write-subs", "--write-auto-subs", "--sub-langs", "ja", "--sub-format", "json3", "--write-info-json",
                          "-o", keep + os.sep + "v.%(ext)s",   # 既定の -o = 途中のファイルも keep/<動画>/ へ(無いと作業フォルダに書く。10-26)
                          "-o", "subtitle:" + keep + os.sep + "subs", "-o", "infojson:" + keep + os.sep + "info", "--"] + list(urls), 300 + 30 * len(urls))
    got = {}
    for u in urls:
        v = _video_of(u)
        b = bundle(app_dir, v) if v else {}
        if b.get("subs") or b.get("info"):
            got[v] = b
    return got, (tail if (r is None or r.returncode != 0) else "")


def req_age_bonus(q, now):
    """研究の頼みの待った時間の点: 少しずつ上がり(上限 AGE_MAX)、STARVE_SEC を超えたら STARVE_BONUS を足す(古いほど上)"""
    age = max(0.0, now - _vm.num(q.get("_at"))) if now else 0.0
    return min(AGE_MAX, age / 3600.0 * AGE_PER_H) + (STARVE_BONUS + age / 86400.0 if age >= STARVE_SEC else 0.0)


def plan(app_dir, roster_r, counts, extra=None, st=None, now=None):
    """全部の頼みを 1 つの一覧で点を付ける(10-25 ユーザー: 研究と声を交互に回すのをやめ、毎回いちばん点の高い 1 本)。
    -> [{"score", "kind": "candidate"|"request"|"voice", "label", ...}](点の高い順)。
    候補 = 研究 + 声 − 区間の長さ / 研究の頼み = REQ_BASE(種類)+ 声(音の頼みで配信者が材料の少ない人)+ priority × 0.1 − 区間の長さ /
    声だけ = その人の材料の足りなさ(候補に無いメンバーだけ)。研究の頼みには待った時間の点(req_age_bonus。now が無ければ 0)"""
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
        sc = REQ_BASE.get(q["kind"], 0.5) + voice + _vm.num(q.get("priority")) * 0.1 - span / 3600.0 * 0.2 + req_age_bonus(q, now)
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
    r, tail = _vf._ytdlp([yd, "--encoding", "utf-8", "--no-warnings", "--flat-playlist", "-J", "--playlist-items", "1:%d" % max(1, min(items, 500)), "--", url], 300)
    if r is None or r.returncode != 0:
        return [], tail or "一覧を読めませんでした"
    try:
        d = json.loads(r.stdout)
    except ValueError:
        return [], "一覧の形が違います"
    return [{k: e.get(k) for k in ("id", "title", "upload_date", "timestamp", "duration")} for e in d.get("entries") or () if isinstance(e, dict)], ""


# ---------------------------------------------------------------- 友人のショートの元の配信(説明欄の【元配信】URL と ?t=。10-25 研究の非効率の洗い出し 1)
SRC_NAME = "short-sources.json"   # {ショート: {"src": 元の配信の id か null, "t": 秒か null, "at"}}。研究が rev_desc へ足す
SRC_EVERY = 6 * 3600              # 見直しの間隔(新しいショートだけ読む)
URL_T_RE = re.compile(r"(?:youtu\.be/|[?&]v=|/live/)([A-Za-z0-9_-]{11})[^\s]*?(?:[?&]t=((?:\d+h)?(?:\d+m)?\d+s?|\d+))?(?=[\s&#)]|$)")


def _t_sec(s):
    if not s:
        return None
    if s.isdigit():
        return int(s)
    m = re.match(r"^(?:(\d+)h)?(?:(\d+)m)?(?:(\d+)s?)?$", s)
    return (int(m.group(1) or 0) * 3600 + int(m.group(2) or 0) * 60 + int(m.group(3) or 0)) if m else None


def source_of(desc):
    """説明欄 -> (元の配信の id, ?t= の秒)。【元配信】の行の URL を先に、無ければ最初の配信らしい URL。無ければ (None, None)"""
    lines = str(desc or "").splitlines()
    for line in sorted(lines, key=lambda l: "元配信" not in l):
        m = URL_T_RE.search(line)
        if m:
            return m.group(1), _t_sec(m.group(2))
    return None, None


def friend_shorts(raw_dir):
    """友人のチャンネルのショートの id(分析の取得の最新の記録 analytics/raw の videos の short)"""
    try:
        names = sorted(n for n in os.listdir(raw_dir) if n.endswith(".json"))
    except OSError:
        return []
    d = fsio.read_json_or(os.path.join(raw_dir, names[-1]), {}, kind=dict) if names else {}
    return [str(v["id"]) for v in d.get("videos") or () if isinstance(v, dict) and str(v.get("short")).lower() == "true" and _vf.VIDEO_RE.match(str(v.get("id") or ""))]


def read_short_sources(app_dir, raw_dir, now, log):
    """まだ読んでいない友人のショートの説明欄を API で 50 本ずつ読み、元の配信と ?t= を short-sources.json に(枠は使わない・1 日 API_DAILY まで)。-> 読んだ本数"""
    st = _state(app_dir)
    if now - _vm.num(st.get("srcAt")) < SRC_EVERY:
        return 0
    today = datetime.date.fromtimestamp(now).isoformat()
    path = qdir(app_dir, SRC_NAME)
    have = fsio.read_json_or(path, {}, kind=dict)
    todo = [v for v in friend_shorts(raw_dir) if v not in have]
    n = 0
    while todo and _api_left(st, today) > 0 and st.get("apiOff") != today:
        batch, todo = todo[:50], todo[50:]
        try:
            infos = _info_api(batch)
        except ApiError as e:
            if e.code in _ytapi.FATAL:
                st["apiOff"] = today
            break
        _api_count(st, today, 1)
        for it in infos:
            src, t = source_of(it.get("description"))
            have[it["id"]] = {"src": src, "t": t, "at": int(now)}
            n += 1
        for v in batch:
            have.setdefault(v, {"src": None, "t": None, "at": int(now), "gone": True})
    if not todo:
        st["srcAt"] = now
    _save(app_dir, st)
    if n:
        os.makedirs(qdir(app_dir), exist_ok=True)
        fsio.write_json(path + ".tmp", have, indent=None)
        os.replace(path + ".tmp", path)
        log("YouTube の取得の列: 友人のショートの説明欄を %d 本読みました(元の配信あり %d 本・?t= あり %d 本。API・枠は使わない)"
            % (n, sum(1 for x in have.values() if x.get("src")), sum(1 for x in have.values() if x.get("t") is not None)))
    return n


# ---------------------------------------------------------------- 評価用のショートの元の配信(10-25 ユーザーの方針「間違った正解で学習しないように」)
EVAL_SRC_NAME = "eval-sources.json"   # {"videos": [元の配信の id], "movs": {評価用の .mov: {"dur", "short", "src"}}, "at"}
EVAL_SRC_EVERY = 6 * 3600
MOV_EXTS = (".mov", ".mp4", ".mkv")


def blocked_videos(app_dir):
    """評価用のショートの元の配信(声の材料の取得・研究の音の受け取り・列の候補から外す)"""
    d = fsio.read_json_or(qdir(app_dir, EVAL_SRC_NAME), {}, kind=dict)
    return {v for v in d.get("videos") or () if isinstance(v, str)}


def _shorts_meta(raw_dir):
    """分析の記録の最新の videos のショート [{"id", "title", "day", "length"}]"""
    try:
        names = sorted(n for n in os.listdir(raw_dir) if n.endswith(".json"))
    except OSError:
        return []
    d = fsio.read_json_or(os.path.join(raw_dir, names[-1]), {}, kind=dict) if names else {}
    out = []
    for v in d.get("videos") or ():
        if not isinstance(v, dict) or str(v.get("short")).lower() != "true":
            continue
        try:
            day = (datetime.datetime.fromisoformat(str(v.get("published")).replace("Z", "+00:00")) + datetime.timedelta(hours=9)).date()
            out.append({"id": str(v["id"]), "title": str(v.get("title") or ""), "day": day, "length": float(v.get("length"))})
        except (KeyError, TypeError, ValueError):
            continue
    return out


def eval_sources(app_dir, eval_dirs, raw_dir, now, log, dur=None):
    """評価用のフォルダのショート(YY-MM-DD_<名前>)を、分析の記録のショートと突き合わせ(名前が題名に・日付が 0〜2 日・長さが ±1.5 秒 = 研究の rev_map と同じ)、
    説明欄の元の配信(short-sources.json)を eval-sources.json に。EVAL_SRC_EVERY に 1 回。-> 元の配信の数"""
    path = qdir(app_dir, EVAL_SRC_NAME)
    cur = fsio.read_json_or(path, {}, kind=dict)
    if now - _vm.num(cur.get("at")) < EVAL_SRC_EVERY:
        return len(cur.get("videos") or ())
    dur = dur or _vf._tools.media_duration
    src_of = fsio.read_json_or(qdir(app_dir, SRC_NAME), {}, kind=dict)
    shorts = _shorts_meta(raw_dir)
    old = cur.get("movs") if isinstance(cur.get("movs"), dict) else {}
    movs, videos = {}, set()
    for root in eval_dirs:
        for d, _sub, files in os.walk(root):
            for f in files:
                m = re.match(r"^(\d\d)-(\d\d)-(\d\d)_(.+?)\d*(?:\(ショート\))?\.(?:mov|mp4|mkv)$", f, re.I)
                if not m:
                    continue
                p = os.path.join(d, f)
                rec = dict(old.get(p) or {})
                if rec.get("dur") is None:
                    rec["dur"] = dur(p)
                day = datetime.date(2000 + int(m.group(1)), int(m.group(2)), int(m.group(3)))
                who = m.group(4)
                c = [s for s in shorts if who in s["title"] and 0 <= (s["day"] - day).days <= 2 and rec["dur"] and abs(s["length"] - rec["dur"]) <= 1.5]
                rec["short"] = c[0]["id"] if len(c) == 1 else None
                rec["src"] = (src_of.get(rec["short"]) or {}).get("src") if rec["short"] else None
                if rec["src"]:
                    videos.add(rec["src"])
                movs[p] = rec
    out = {"videos": sorted(videos), "movs": movs, "at": int(now)}
    os.makedirs(qdir(app_dir), exist_ok=True)
    fsio.write_json(path + ".tmp", out, indent=None)
    os.replace(path + ".tmp", path)
    log("YouTube の取得の列: 評価用のショート %d 本のうち %d 本の元の配信が分かりました(元の配信 %d 本を、声の材料・研究の音の受け取り・候補から外します)"
        % (len(movs), sum(1 for r in movs.values() if r.get("src")), len(videos)))
    return len(videos)
