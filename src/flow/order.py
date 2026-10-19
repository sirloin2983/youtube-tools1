# -*- coding: utf-8 -*-
"""② 管理の層 flow: 欄 → (封筒, 束の差分) の変換の 1 か所(RV A1)。

受付は ② の口 Queue.submit(封筒, 束)の 1 本だけ(HTTP は POST /api/flow/submit)。画面・CLI・友人の受付・ライブの受け渡しは、
それぞれの欄をここで封筒(flow/envelope.py の版 2)+ 束の差分(flow/spec.py の形。変えたい所だけ)にして submit する。
束の土台は submit の側(Queue の hook build_spec = 既定 + この PC・入口は画面の設定)。画面の JS の同じ変換は UIKit.flow.order(src/ui-kit/ui-kit.js)。

order(kind, ...) の欄(どれも無ければ既定):
  入力: url = video_id(か url)・title・duration・fresh {title, channel}・marks / file = path・title・normalize / docs = doc_id・title / live = url(か video_id)・title・recorder
  段の並び: from_(run.from。None = 土台のまま)・upto(run.upto。transcribe か pack。既定 pack)・on_fail(run.onFail。None = 土台のまま)
  中身(依頼が決めた物。検査に合う値だけ写す = 合わない欄は黙って土台のまま): top → adopt.top / ranges → hints.ranges /
    weights → analyze.w* + run.requested "weights" / cut → pack.cut + "cut" / video_tracks → pack.videoTracks + "videoTracks" /
    speakers {count, names, styles} → transcribe.diarize(人数)+ hints.people(名前と色)/ engine・model → transcribe.engine・model + "engine"・"model" /
    force → run.force / repack → run.repack / streamer → hints.streamer(None = 自動・"" = 色なし)
  友人の依頼の欄の検査(受付の口): speakers_arg・cut_arg・video_tracks_arg(束の検査と同じ範囲。形が違う欄は既定・None)
  届け先: request_id・deliver_dir・pool・origin・tag / ほか: eid(封筒の id。None = 新しく 10 桁の 16 進 = 実行の id にもなる)・created(秒)
形が違えば理由つきの ValueError(封筒の検査は envelope.check)。

純粋(ファイル・ネットワークを読まない)。import してよいのは標準ライブラリ・ytt・同じ flow の envelope・spec だけ。
"""
import copy
import uuid

from ytt import colors
from . import envelope as _envelope, spec as _spec

PEOPLE_NAME_MAX = 40  # 束の hints.people の名前の長さ(flow/spec.py の検査と同じ。友人の受付は 60 字まで受けるので、長い名前はここで切る)


def new_id():
    """封筒の id(10 桁の 16 進 = 実行の id にもなる)"""
    return uuid.uuid4().hex[:10]


SPEAKER_NAME_MAX = 60   # 依頼に書かれた人の名前の長さ(束へは people_of が PEOPLE_NAME_MAX で切る)
# 字幕の見た目(people[].style)の許可の一覧: 鍵 -> 値を検査して整える関数(通らなければ None = その項目だけ捨てる)。
# 鍵を増やすとき(font・size など)はここに足す。知らない鍵は黙って捨てる。
# 色は外から来る文字で画面・Lua に入るので、必ず 16 進 6 桁だけにそろえる(ytt/colors.norm_hex。# は付けても付けなくてもよい)
_STYLE_KEYS = {"color": lambda v: colors.norm_hex(v) if isinstance(v, str) else None}


def _speaker_name(x):
    """依頼に書かれた人の名前 -> 整えた名前(空・制御文字を含む・文字列でない = "")。names と people で同じ整え方にする"""
    s = x.strip()[:SPEAKER_NAME_MAX] if isinstance(x, str) else ""
    return s if s and not any(ord(c) < 32 for c in s) else ""


def _style_arg(v):
    """人ごとの字幕の見た目 {"color": "FF00AA"} -> 許可した鍵だけを整えた dict({"color": "#FF00AA"})。形が違う・何も残らない = {}"""
    out = {}
    if isinstance(v, dict):
        for k, check in _STYLE_KEYS.items():
            if k in v:
                x = check(v[k])
                if x is not None:
                    out[k] = x
    return out


def speakers_arg(v):
    """依頼の「配信者」{"count": 人数(束の transcribe.diarize と同じ 1〜10), "names": [...], "people": [{"name", "style"}]?} ->
    {"count", "names", "styles": {名前: {"color": "#RRGGBB"}}}(styles は見た目を指定した人だけ。無ければ {})か None(無い・形が違う = 話者分離しない)。
    people は任意。styles の名前は count で切ったあとの names に入っている人だけ。同じ名前が2回あれば先のもの(友人の受付の口)"""
    if not isinstance(v, dict):
        return None
    n = v.get("count")
    if n is None or not _spec.key_ok("transcribe", "diarize", n):
        return None
    names = []
    for x in v.get("names") if isinstance(v.get("names"), list) else []:
        s = _speaker_name(x)
        if s and s not in names:
            names.append(s)
    names = names[:n]
    styles = {}
    for p in v.get("people") if isinstance(v.get("people"), list) else []:
        if not isinstance(p, dict):
            continue
        s = _speaker_name(p.get("name"))
        st = _style_arg(p.get("style"))
        if s in names and st and s not in styles:
            styles[s] = st
    return {"count": n, "names": names, "styles": styles}


def cut_arg(v):
    """依頼のカット(① のパック)-> spec.CUTS のどれか(none・silence)か None(無い・知らない値 = ホームの設定)"""
    return v if not isinstance(v, bool) and v in _spec.CUTS else None


def video_tracks_arg(v):
    """依頼の「映像トラックの数」-> 束の pack.videoTracks に合う整数(1〜5)。無い・形が違う = 既定(spec.DEFAULTS の 1)"""
    return v if v is not None and _spec.key_ok("pack", "videoTracks", v) else _spec.DEFAULTS["pack"]["videoTracks"]


def people_of(speakers):
    """友人の「話す人」{"count", "names", "styles"} -> 束の hints.people [{name, color?}](名前の順。色は 16 進 6 桁にそろえる)"""
    styles = speakers.get("styles") if isinstance(speakers.get("styles"), dict) else {}
    out, seen = [], set()
    for n in speakers.get("names") or []:
        name = n.strip()[:PEOPLE_NAME_MAX].strip() if isinstance(n, str) else ""
        if not name or name in seen:
            continue
        seen.add(name)
        p = {"name": name}
        sty = styles.get(n)
        hx = colors.norm_hex(sty.get("color")) if isinstance(sty, dict) and isinstance(sty.get("color"), str) else None
        if hx:
            p["color"] = hx
        out.append(p)
    return out


def spec_diff(top=None, ranges=None, weights=None, cut=None, video_tracks=None, speakers=None, engine=None, model=None, force=False, repack=False,
              streamer=None, from_=None, upto="pack", on_fail=None):
    """中身の欄 -> 束の差分 {節: {項目: 値}}(検査に合う値だけ。合わない欄は写さない)。表は先頭の説明"""
    a, pins = {}, []

    def put(sec, key, val, pin=None):
        if not _spec.key_ok(sec, key, val):
            return False
        a.setdefault(sec, {})[key] = copy.deepcopy(_spec.read_legacy_tx(key, val) if sec == "transcribe" else val)   # 旧い名前は今の値に
        if pin:
            pins.append(pin)
        return True
    if top is not None:
        put("adopt", "top", top)
    if ranges:
        put("hints", "ranges", [list(r) for r in ranges])
    w = weights
    if isinstance(w, dict) and w and all(_spec.key_ok("analyze", k, w.get(k)) for k in _spec.WEIGHT_KEYS):
        for k in _spec.WEIGHT_KEYS:
            put("analyze", k, w[k])
        pins.append("weights")
    if cut in _spec.CUTS:
        put("pack", "cut", cut, "cut")
    if video_tracks:
        put("pack", "videoTracks", video_tracks, "videoTracks")
    sp = speakers if isinstance(speakers, dict) else None
    if sp and put("transcribe", "diarize", sp.get("count")):
        people = people_of(sp)
        if people:
            put("hints", "people", people)
    if engine in _spec.TX_ENGINES:
        put("transcribe", "engine", engine, "engine")
    if model in _spec.TX_MODELS:
        put("transcribe", "model", model, "model")
    if force is True:
        put("run", "force", True)
    if repack is True:
        put("run", "repack", True)
    if pins:
        a.setdefault("run", {})["requested"] = pins
    run = a.setdefault("run", {})
    if from_ is not None:   # None = 土台のまま(土台の既定は頭から。CLI の --from pack など土台が決めた物を消さない)
        run["from"] = from_
    run["upto"] = upto
    if on_fail is not None:
        run["onFail"] = on_fail
    if streamer is not None:
        a.setdefault("hints", {})["streamer"] = streamer
    return a


def request_top(top, ranges):
    """友人の依頼の切り抜く数: 区間を選んだら区間の数(自動では埋めない)・選ばなければ頼んだ本数(10-19 ユーザー決定。友人のアプリと受付の 1 か所)"""
    return len(ranges) if ranges else top


def order(kind, video_id=None, url=None, path=None, doc_id=None, title="", duration=None, fresh=None, marks=None, normalize=False, recorder=None,
          from_=None, upto="pack", on_fail=None, top=None, ranges=None, weights=None, cut=None, video_tracks=None, speakers=None,
          engine=None, model=None, force=False, repack=False, streamer=None,
          request_id=None, deliver_dir=None, pool=None, origin=None, tag=None, eid=None, created=None):
    """欄 -> (封筒(版 2。検査済み), 束の差分)。表は先頭の説明。題は封筒の上限で切る。形が違えば理由つきの ValueError"""
    title = str(title or "")[:_envelope.TITLE_MAX]
    if kind in ("url", "live"):
        inp = {"title": title}
        if video_id is not None:
            inp["videoId"] = video_id
        if url is not None:
            inp["url"] = url
        if kind == "url":
            inp.update(duration=duration if _spec.num_ok(duration) and duration > 0 else None,
                       fresh={"title": str(fresh.get("title") or "")[:_envelope.TITLE_MAX], "channel": str(fresh.get("channel") or "")[:_envelope.CHANNEL_MAX]}
                       if isinstance(fresh, dict) else None,
                       marks=list(marks) if isinstance(marks, tuple) else (marks or None))   # 形の検査は封筒(envelope.check)
        else:
            inp["recorder"] = recorder
    elif kind == "file":
        inp = {"path": path, "title": title, "normalize": normalize is True}
    elif kind == "docs":
        inp = {"docId": doc_id, "title": title}
    else:
        raise ValueError("封筒.kind は %s のどれかにしてください" % "・".join(_envelope.KINDS))
    env = {"id": eid or new_id(), "kind": kind, "input": inp, "requestId": request_id or None,
           "deliver": {"dir": deliver_dir or None, "pool": _envelope.clean_pool(pool), "origin": origin, "tag": tag or None},
           "specVersion": _envelope.SPEC_VERSION}
    if created is not None:
        env["createdAt"] = int(created * 1000)
    env = _envelope.check(env)
    diff = spec_diff(top=top if kind == "url" else None, ranges=ranges, weights=weights, cut=cut, video_tracks=video_tracks, speakers=speakers,
                     engine=engine, model=model, force=force, repack=repack, streamer=streamer, from_=from_, upto=upto, on_fail=on_fail)
    if kind == "live":   # ライブは段の並びを持たない(録画の束)
        for k in ("from", "upto", "onFail"):
            diff["run"].pop(k, None)
        if not diff["run"]:
            diff.pop("run")
    return env, diff
