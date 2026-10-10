# -*- coding: utf-8 -*-
"""ライブの採用 = サーバー側の「マーク + 書き出し」(線 D の M1。役割で組み直す RS7-2 G1b。docs/design/rs7-survey-2026-10-10/plan_order_v3.md)。

POST /live/api/adopt・配信中の自動の採用(live_detect の M11)・配信後の追加(live_archive の M7)が通る。もとは src/home/live.py の Live.adopt と
その周り(区間の秒・余白・スタジオのマーク・友人の依頼の結びつき)。Live.adopt は Adopter.adopt を呼ぶだけ(名前は残す = Detector・HTTP の受け口が呼ぶ)。

マークの置き場は差し込み口(親の marks。flow/livehost.py の MarkBook):
  StudioMarks  今の動き(ユーザーの PC)。取り込んだスタジオの API で kind live の配信(id = 録画の id)を(無ければ)登録し、採用のマークを足す
               (同じ区間 ±SAME 秒のマークがあれば使い回し、候補・不採用なら採用に)。番号 n = スタジオの配信のマークを開始の順に並べた位置。
               書き出したら「書き出し済み」(POST /api/live/exported)
  LocalMarks   スタジオなし(友人の PC・headless。ライブ係 flow/livesession.py の既定・入口の Live.use_headless)。マークの正本 live_export.MarkStore
               (live/marks/<録画元>__<録画>.json)に採用の印を置く(MarkStore.adopt。配信の登録はしない)。
               採用の印の形: マークに key(スタジオのマークの id の代わり = "a" + 16 進 12 桁)・status(adopted → 書き出したら exported)・src "local"。
               マークの id は studio_mark_id(key)(スタジオのマークと同じ規則)= 書き出しのジョブ・.clip.json の studio {video: 録画の id, mark: key} も同じ形。
               使い回し・番号 n の決まりは StudioMarks と同じ(同じ録画の正本のマークを開始の順に並べた位置)
どちらでも Exporter.add_studio へ同じ呼び方で渡る(studio {video, mark, n, label, start, end})。

本数の上限(D-13)はここでは数えない = 自動の採用を数えるのは live_detect.Detector(親の auto_max。無ければ AUTO_MAX_PER_REC。
友人の PC は束の adopt.top = top_of)。人のマーク・配信後の追加は数えない(今と同じ)。
友人へ届ける(自分の配信の自動の切り抜き live.autoDeliver)は app の hook(deliver_for)。友人の依頼の結びつきは親の requests(livehost.RequestBook)。
"""
import secrets
import threading
import urllib.parse

from ytt import schemas
from . import live_export as LX
from . import live_tx
from . import livehost   # 親の口の型(RS7-2 G0・G1b)
from . import spec as _spec

SAME = 0.5         # マークを使い回す区間の差(秒。スタジオの DUP_TOL と同じ。もとは live.ADOPT_SAME)
TRIES = 3          # スタジオの配信の保存が画面の保存とぶつかったときに読み直す回数
WHO = {"manual": "人", "auto": "自動", "archive": "アーカイブ"}


def adopt_secs(body, first):
    """POST /live/api/adopt の start・end -> 録画の頭からの秒 (a, b)。数 = 秒・文字列 = 絶対時刻(UTC)。first = 最初のセグメントの受信時刻(epoch)"""
    out = []
    for k in ("start", "end"):
        v = body.get(k)
        if isinstance(v, str):
            e = LX.iso_epoch(v)
            if e is None:
                raise LX.LiveError("%s の時刻が正しくありません(UTC の …Z か、録画の頭からの秒)" % k)
            v = e - first
        if not schemas.is_num(v):
            raise LX.LiveError("%s は録画の頭からの秒(数)か、絶対時刻(UTC の文字列)で指定してください" % k)
        out.append(round(float(v), 3))
    a, b = out
    if not 0 <= a or b - a < 0.5:
        raise LX.LiveError("区間は 0 ≤ 開始 で、終了は開始より 0.5 秒以上あとにしてください")
    if b - a > LX.MAX_MARK_SEC:
        raise LX.LiveError("1つのマークは %d 分までです" % (LX.MAX_MARK_SEC // 60))
    return a, b


def pad_secs(a, b, pad, st, first):
    """自動・アーカイブの採用の区間 (a, b) を前後 pad 秒だけ広げる(M8。plan/improvements.md の M8)。
    0 より前と、録れている範囲(録画元の状態の lastPdt)の外へは広げない(終わりが録れていなければ後ろは足さない)。1 つのマークの上限も守る"""
    pad = float(pad)
    a2, b2 = max(0.0, a - pad), b + pad
    last = LX.iso_epoch(st.get("lastPdt")) if isinstance(st, dict) else None
    if last is not None and first is not None:
        b2 = min(b2, max(b, last - first))
    b2 = min(b2, a2 + LX.MAX_MARK_SEC)
    return round(a2, 3), round(b2, 3)


def top_of(bundle):
    """束の adopt.top(友人の PC の 1 録画の自動の採用の上限 = 親の auto_max が返す値。plan/f1-friend-pc.md 決めたこと 7)。
    無い・形が違えば束の既定(spec.DEFAULTS)"""
    a = bundle.get("adopt") if isinstance(bundle, dict) else None
    try:
        return _spec.top_arg((a or {}).get("top") if isinstance(a, dict) else None)
    except ValueError:
        return _spec.DEFAULTS["adopt"]["top"]


class StudioMarks:
    """マークの置き場 = 取り込んだスタジオ(ユーザーの PC。今の動き)。call(method, path, body=None) -> (HTTP の番号か None, JSON)"""

    def __init__(self, call):
        self.call = call

    def _ok(self, method, path, body=None):
        """取り込んだスタジオの API -> JSON。だめなら LiveError(スタジオが動いていない = 502)"""
        code, d = self.call(method, path, body)
        if code is None:
            raise LX.LiveError("切り抜きスタジオにつながりません: %s" % ((d or {}).get("message") or ""), 502)
        if code != 200 or not isinstance(d, dict):
            raise LX.LiveError("切り抜きスタジオが断りました: %s" % ((d or {}).get("message") or "HTTP %s" % code), code if code in (400, 404, 409) else 502)
        return d

    def adopt_mark(self, rc_id, rec, st, first, a, b, label):
        """スタジオの配信(kind live。id = 録画の id)を(無ければ)登録し、採用のマーク [a, b] を足す(同じ区間 ±SAME 秒があれば使い回し、候補・不採用なら採用に)。
        画面と同じ PUT /api/video(baseRev つき。画面の保存とぶつかったら読み直して TRIES 回まで)。first は使わない(秒のまま渡す)。-> (配信の id, マーク, 番号 n)"""
        v = self._ok("POST", "/api/videos/open", {"kind": "live", "recorder": rc_id, "recording": rec, "url": st.get("url") or "",
                                                  "title": (st.get("title") or "")[:LX.TITLE_MAX], "channel": ""}).get("video") or {}
        vid = v.get("id")
        if not isinstance(vid, str) or not vid:
            raise LX.LiveError("切り抜きスタジオに録画を登録できませんでした", 502)
        for _try in range(TRIES):
            v = self._ok("GET", "/api/video?id=" + urllib.parse.quote(vid)).get("video") or {}
            marks = [m for m in v.get("marks") or [] if isinstance(m, dict)]
            hit = next((m for m in marks if abs((m.get("start") or 0) - a) <= SAME and abs((m.get("end") or 0) - b) <= SAME), None)
            if hit is not None and hit.get("status") in ("adopted", "exported"):
                mark = hit
                break
            if hit is not None:
                new = [dict(m, status="adopted") if m.get("id") == hit.get("id") else m for m in marks]
            else:
                new = marks + [{"start": a, "end": b, "label": label, "status": "adopted"}]
            code, d = self.call("PUT", "/api/video", {"id": vid, "marks": new, "baseRev": v.get("rev")})
            if code == 409:   # 画面の保存・解析とぶつかった: 読み直してもう一度
                continue
            if code != 200 or not isinstance(d, dict):
                raise LX.LiveError("切り抜きスタジオにマークを足せませんでした: %s" % ((d or {}).get("message") or "HTTP %s" % code), 502)
            v = d.get("video") or {}
            old_ids = {m.get("id") for m in marks}
            got = [m for m in v.get("marks") or [] if isinstance(m, dict)]
            mark = next((m for m in got if m.get("id") == (hit or {}).get("id")), None) if hit is not None else \
                next((m for m in got if m.get("id") not in old_ids and abs((m.get("start") or 0) - a) <= SAME), None)
            if mark is None:
                raise LX.LiveError("切り抜きスタジオに足したマークが見つかりません", 502)
            marks = got
            break
        else:
            raise LX.LiveError("切り抜きスタジオの配信が続けて書き換えられているので、マークを足せませんでした(少し待ってもう一度)", 409)
        order = sorted(marks, key=lambda m: (m.get("start") or 0, m.get("end") or 0))
        n = next((i + 1 for i, m in enumerate(order) if m.get("id") == mark.get("id")), 0)
        return vid, mark, n

    def exported(self, job, media, archived=False):
        """書き出したら、スタジオのマークを「書き出し済み」に(Exporter の exported hook)。-> 警告の文か "\""""
        return LX.studio_exported(self.call, job, media, archived)


class LocalMarks:
    """マークの置き場 = マークの正本 live_export.MarkStore(スタジオなし。友人の PC)。exporter() -> live_export.Exporter(初めて使うときに作る親の物)"""

    def __init__(self, exporter):
        self.exporter = exporter

    def adopt_mark(self, rc_id, rec, st, first, a, b, label):
        """採用の印を正本に置く(同じ区間 ±SAME 秒の採用の印があれば使い回す)。配信の id = 録画の id(スタジオの kind live と同じ)。
        -> (配信の id, マーク {id: key, start, end, label, status}(秒は録画の頭から), 番号 n)"""
        m, n = self.exporter().marks.adopt(rc_id, rec, "a" + secrets.token_hex(6), first, a, b, label, tol=SAME,
                                           url=st.get("url") if isinstance(st.get("url"), str) else None,
                                           title=st.get("title") if isinstance(st.get("title"), str) else None)
        return rec, {"id": m["key"], "start": m["sec"][0], "end": m["sec"][1], "label": m.get("label") or "", "status": m.get("status")}, n

    def exported(self, job, media, archived=False):
        """書き出したら、正本の採用の印を「書き出し済み」に(Exporter の exported hook)。-> 警告の文か "\""""
        if not isinstance(job.get("studio"), dict) or not job.get("markId"):
            return ""
        try:
            self.exporter().marks.mark_exported(job.get("recorder"), job.get("recording"), job["markId"], media)
        except LX.LiveError as e:
            return "マークを「書き出し済み」にできませんでした: %s" % e
        return ""


class Adopter:
    """採用(M1)の本体。host: 親(flow/livehost.py の LiveHost。flow/livesession.py の LiveSession)= 録画元の検査 _ids・録画の状態 _rec_status・
    書き出し exporter・マークの置き場 marks・友人の依頼 requests・書き出したあとの設定 auto_cfg・記録 log。
    deliver_for(origin, after, streamer) -> (届ける依頼の形か None, after, streamer): 友人の依頼の無い録画を確認なしで届けるか(app。無ければ届けない)"""

    def __init__(self, host: "livehost.LiveHost", deliver_for=None):
        self.host = host
        self.deliver_for = deliver_for
        self.lock = threading.Lock()   # 同じ区間を続けて頼まれても、マーク・ジョブを二重に作らない

    def request_for(self, rc_id, rec, origin, after, streamer):
        """録画が友人のライブ配信の依頼に結びついていれば (依頼, after=auto, 配信者) を返す(2-15: 採用した切り抜きは全部 文字起こし → パック → 届ける)。
        配信後のアーカイブからの追加(origin archive)は依頼の afterStream が真のときだけ。結びついていなければ deliver_for(無ければ (None, after, streamer))"""
        req = self.host.requests.get(rc_id, rec)
        if req is None:
            return self.deliver_for(origin, after, streamer) if self.deliver_for is not None else (None, after, streamer)
        if origin == "archive" and req["settings"].get("afterStream") is not True:
            return None, after, streamer
        return req, "auto", streamer or req.get("streamer") or ""

    def adopt(self, body, hold=None):
        """POST /live/api/adopt(M1)。-> {job, video, mark, origin, existing}。
        hold: "archive" = 書き出したあと、本番版に入れ替えてから まとめて実行へ渡す(配信後の全自動 M7 が入口の中から渡す。API の本文からは渡せない)"""
        host = self.host
        origin = LX.check_origin(body.get("origin"))
        rc_id, rec = body.get("recorder"), body.get("recording")
        auto = host.auto_cfg(rc_id, rec)   # その録画の束があれば束から(RS7-2 G2b)
        after, streamer = LX.check_after(body, auto["after"]), LX.check_streamer(body.get("streamer"))
        label = LX._text(body.get("label"), LX.LABEL_MAX)
        text = LX._text(body.get("text"), live_tx.TEXT_MAX)   # 配信中の文字起こし(D-11 案 b)の文字(採用の記録に残す = C2 の材料。任意)
        score = body.get("score") if schemas.is_num(body.get("score")) else None   # 候補の点数(配信中の検出・アーカイブの解析。任意)
        rc = host._ids(rc_id, rec)
        req, after, streamer = self.request_for(rc_id, rec, origin, after, streamer)   # 友人の依頼の録画(2-15): after は auto・余白は依頼の設定
        pad = req["settings"]["pad"] if req and isinstance(req.get("settings"), dict) else auto["pad"]
        st, first = host._rec_status(rc, rc_id, rec)
        a, b = adopt_secs(body, first)
        if origin != "manual" and pad > 0:   # M8: 自動・アーカイブの採用は前後に余白を足す(人が決めた区間はそのまま)
            a, b = pad_secs(a, b, pad, st, first)
        ex = host.exporter
        with self.lock:
            vid, mark, n = host.marks.adopt_mark(rc_id, rec, st, first, a, b, label)
            mid = LX.studio_mark_id(mark["id"])
            prev = [j for j in ex.snapshot(rc_id, rec) if j.get("markId") == mid and (j.get("state") in LX.ACTIVE or j.get("state") == "done")]
            if mark.get("status") == "exported" or (prev and prev[0].get("state") in LX.ACTIVE):   # 書き出しの途中か済み: 新しく作らない(同じ切り抜きを二重に作らない)
                return {"job": prev[0] if prev else None, "video": vid, "mark": mark["id"], "origin": (prev[0].get("origin") if prev else None) or "manual",
                        "existing": True}
            studio = {"video": vid, "mark": mark["id"], "n": n, "label": mark.get("label") or label,
                      "start": float(mark.get("start", a)), "end": float(mark.get("end", b))}   # 置き場が丸めた区間(画面の書き出しと同じ値で突き合わせる)
            job = ex.add_studio(rc_id, rec, studio, first, after != "none", url=st.get("url") if isinstance(st.get("url"), str) else None,
                                title=st.get("title") if isinstance(st.get("title"), str) else None, after=after, streamer=streamer, origin=origin, auto=auto,
                                hold=hold if hold in LX.HOLDS else None, score=score, request=req)
        ex.feedback({"event": "adopt", "origin": origin, "human": origin == "manual", "verdict": "good" if origin == "manual" else None,
                     "recorder": rc_id, "recording": rec, "markId": mid, "jobId": job.get("id"), "studio": {"video": vid, "mark": mark["id"]},
                     "start": round(studio["start"], 3), "end": round(studio["end"], 3), "label": studio["label"], **({"text": text} if text else {})})
        host.log("リアルタイム切り抜き: %s のマークを採用して書き出しを頼みました(%s %.1f〜%.1f 秒)" % (WHO[origin], rec, studio["start"], studio["end"]))
        return {"job": job, "video": vid, "mark": mark["id"], "origin": origin, "existing": False}
