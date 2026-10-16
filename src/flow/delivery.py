"""② 友人へ届ける: まとめて実行の「Dropbox へ届ける」段と、ライブの切り抜きの組の溜め(まとめて実行 AutoRunner が継ぐ mixin)。
ds1(要件 1-5「届ける段と溜めは ② へ」・仮決め 3-70 ds1・3-71 m3i)で ③ human/friend から移した(動きは変えていない)。
① まとめ動画は pipeline/pack/preview・1 本の届け方は同じフォルダの deliver。③(受付・送り返し)は読まない(友人の PC には ③ が無い)。

形: AutoRunner(入口の src/app/autorun.py)が `class AutoRunner(Delivery, Queue)` で継ぐ(Queue = src/flow/runqueue.py)。ここは入口の部品
(autorun・launch・live・prefs)も案件の部品(manage/cases)も ③ も読まない = 要るものは継いだクラスが埋める:
  - _deliver_batch_limits() -> (既定, 下限, 上限)  n 本ごとに組にする数の既定と範囲(ホームの設定 intake.deliverBatch。AutoRunner が prefs から)
  - _save_active()・_active_runs()                 待ち・実行中の記録を残す(M5)・待ちと実行中の一覧(Queue)
  - 属性 prefs(ホームの設定。get だけ)・log_path(終わった実行の記録のパス。隣に deliveries.jsonl)・cv・log・clock・find_pack と
    Runner の _check・_clips
溜めの置き場所とロックは _delivery_init(log_dir) で作る(AutoRunner の __init__ が呼ぶ)。

届け方(notes:docs/spec/friend.md の 2-16): パックを n 本(依頼ごとの deliver_batch。無ければホームの設定 intake.deliverBatch)たまるごとに、
組 = まとめ動画 1 本 + 1 本ずつの zip + 組の一覧(.group.json)で Dropbox の 出力 へ置く(実行の終わりには n 本に満たない残りも)。
n=1 か 1 本だけのときは 1 本の zip + その隣のまとめ動画。1 本の作り方(まとめ動画 → zip → 届けた記録)は同じフォルダの deliver.deliver_one(手で届けるのも同じ)。
ライブの切り抜き(友人のライブ配信の依頼・live.autoDeliver)は 1 本ごとに別の実行なので、実行をまたいで「組の溜め」(run.pool)に預け、
n 本たまったら組で届ける(flush_pools は入口の src/app/live.py が見回りで呼ぶ)。溜めは logs/deliver-pool.json(10-09 ユーザー決定 = decisions 3-20)。

友人へ自動で送る(D-SEND。要件 notes:plan/d-send-requirements.md・判定と理由の文は ② flow/sendpolicy):
  - 出どころ(_origin): run.deliver_origin(request・auto・manual)。無ければ依頼の id があれば request・無ければ auto。友人に見せる形は deliver.face_origin
  - まとめて実行(mode full)の届ける段は、先に sendpolicy.decide(チェック = 届け先があるか・友人の依頼済み = _requested・配信が終わった時刻 =
    スタジオの配信の analysis)。送らないなら段は飛ばして理由の文・切り抜きごとに _remember_not_sent(② の送らなかった記録 logs/not-sent.jsonl。
    flow/deliveries.record_not_sent。前は案件の auto[マーク].notSent・origin "full" = 3-71 m3e)
  - 置けない(Dropbox のフォルダが無い・書けない)とき、出どころ auto は実行を失敗にせず溜めに預ける(鍵 full|<deliver_tag>|<配信>。meta.parked)・段は warn。
    flush_pools がすぐ送り直す(受付のフォルダがあるとき)。配信が終わってから 48 時間(sendpolicy.FRESH_SEC)を過ぎたら送らず溜めを消し notSent expired
  - 友人に失敗の知らせ(.失敗.txt)を置くのは依頼(request)だけ(2-6)。環境変数 YTT_AUTO_SEND=off(sendpolicy.switched_off)なら auto は届けない
  - 組の本数(_batch_size): 依頼ごと → 友人のアプリの「届け方」(継ぐ側の _friend_batch = 受付の <受付のフォルダ>/設定/届け方.json。2-4)→ ホームの設定
継ぐ側が埋める物(上に加えて。既定は何もしない): _friend_batch() -> 友人のアプリの届け方の本数か None・_returned_request(配信 id) -> 友人の PC で
処理した依頼か(③ 送り返し)・属性 requested_hook(配信 id) -> 受け付けた時刻か None(入口が受付の Intake.requested_at を渡す)。
届けたは案件に写さない(届けた記録 logs/deliveries.jsonl は deliver.deliver_one が書き、案件は ② flow/deliveries.delivered_marks で引く。MARKS-3)。
"""
import contextlib
import json
import os
import shutil
import threading
import uuid

from pipeline.pack import preview as _preview   # ① 組のまとめ動画・切り抜きの長さ・パックの題
from ytt import fsio, tools
from . import deliver as deliver_mod   # 1 本を届ける(まとめ動画 → zip → 届けた記録)・組の一覧・名前の整え方
from . import deliveries as deliveries_mod   # 届けた記録の読み口(依頼済みの配信・届け済みのパック)・送らなかった記録の書く口
from . import envelope   # 届け方の数の範囲(batch_ok)
from . import run as run_mod   # 段の表 MODE_STEPS・段の失敗 StepError(② の経路)
from . import sendpolicy   # 友人へ自動で送るかの判定と理由の文(D-SEND)

POOL_FILE = "deliver-pool.json"   # ライブの切り抜きの組の溜め(実行をまたいで n 本ためて組で届ける。log_dir の中)
POOL_SCHEMA = "ytt-deliver-pool/v1"
POOL_IDLE_SEC = 600.0              # 録画が終わって書き出しも実行も無くなってから、最後に預けてこれだけたったら残りを届ける
POOL_MAX_AGE = 12 * 3600.0         # 溜めを作ってからこれだけたったら、終わりを待たずに残りを届ける(録画が長すぎる・見張りが止まった)


class _PoolRun:
    """組の溜めを届けるときに Delivery の届ける部品(_deliver_pending・_deliver_group・_deliver_one)へ渡す、実行の代わり"""

    def __init__(self, key, p):
        self.id = "pool" + uuid.uuid5(uuid.NAMESPACE_URL, key).hex[:6]
        self.request_id, self.title, self.deliver_dir = p.get("rid") or "", p.get("title") or "pack", p.get("deliverDir") or ""
        b = p.get("batch")
        self.deliver_batch = b if envelope.batch_ok(b) else None
        meta = p.get("meta") if isinstance(p.get("meta"), dict) else {}
        self.video_id = meta.get("videoId") or meta.get("recording") or ""
        self.packs, self.delivered = list(p.get("packs") or []), list(p.get("delivered") or [])
        self.pack_marks = dict(p.get("marks") or {})
        self.cancel, self.pool = False, None
        # D-SEND: 名前の頭・出どころ・実行の形・配信が終わった時刻(古い溜めには無い = 名前は依頼の id・出どころは鍵の 2 つ目が auto なら auto)
        tag = p.get("tag")
        self.deliver_tag = tag if isinstance(tag, str) and tag else None
        origin = p.get("origin") if p.get("origin") in sendpolicy.ORIGINS else meta.get("origin")
        parts = key.split("|")
        self.deliver_origin = origin if origin in sendpolicy.ORIGINS else ("auto" if len(parts) > 1 and parts[1] == "auto" else "request")
        self.mode = p.get("mode") if isinstance(p.get("mode"), str) else None
        ended = meta.get("endedAt")
        self.send_ended_at = ended if isinstance(ended, (int, float)) and not isinstance(ended, bool) and ended > 0 else None


class Delivery:
    """まとめて実行(AutoRunner)が継ぐ、友人へ届ける段と組の溜め。継ぐ側が埋めるものはこのファイルの先頭の説明"""

    def _delivery_init(self, log_dir):
        """溜めの置き場所(log_dir の中。None = メモリだけ)とロック"""
        self.pool_path = os.path.join(log_dir, POOL_FILE) if log_dir else None   # ライブの切り抜きの組の溜め(None = メモリだけ)
        self._pool_lock = threading.RLock()   # 溜めの読み書きと組で届ける間(これを持ったまま self.cv を取ってよい。逆に self.cv を持ったまま取らない)
        self._pools = None                    # {溜めの鍵: {rid, title, deliverDir, batch, meta, packs, delivered, marks, created, updated, (tag, origin, mode)}}(初めて使うときに読む)
        self.requested_hook = None            # 配信 id -> 友人の依頼で受け付けた時刻か None(入口が受付の Intake.requested_at を渡す。D-SEND 2-9)

    def _remember_not_sent(self, video_id, mark_id, code, text):
        """送らなかった切り抜きを ② の送らなかった記録へ(logs/not-sent.jsonl。④ 案件の札・品質のカードが引く。D-SEND・3-71 m3e)。
        書けなければ OSError(_not_sent がログへ)。記録のフォルダが無い(log_path None)なら何もしない"""
        if self.log_path:
            deliveries_mod.record_not_sent(os.path.dirname(self.log_path), video_id, mark_id, code, text)

    def _friend_batch(self):
        """友人のアプリの「届け方」の本数(D-SEND 2-4)か None。継ぐ側(AutoRunner)が受付の届け方.json で埋める。既定は None"""
        return None

    def _returned_request(self, video_id):
        """その配信が友人の PC で処理した依頼か(送り返し。D-SEND 2-9 の 3 つ目の引き方)。継ぐ側(AutoRunner)が ③ の送り返しで埋める。既定は False"""
        return False

    def _deliver_batch_limits(self):
        """n 本ごとに組にする数の (既定, 下限, 上限)。継ぐ側(AutoRunner)がホームの設定の既定と範囲で埋める"""
        raise NotImplementedError("継ぐ側が _deliver_batch_limits を埋める")

    def _after_pack(self, run, st, prefix):
        """① 全自動: パックが n 本たまるごとに届ける(全部を待たない)"""
        if run.deliver_dir and "deliver" in run_mod.MODE_STEPS[run.mode]:
            self._deliver_pending(run, st, prefix, final=False)

    # 依頼の動画(mode file) -------------------------------------
    def _file_deliver(self, run, st):
        found = self.find_pack(run.source_path)
        return self._deliver(run, st, list(run.packs) + ([found["dir"]] if found else []))

    def _step_deliver(self, run, st, v):
        dirs = list(run.packs)
        clips = self._clips(v, run)
        for m in clips:
            found = self.find_pack(m["path"])
            if found:
                d = os.path.normpath(found["dir"])
                dirs.append(d)
                if run.mode == "full" and d not in run.pack_marks and m.get("id"):   # 前からあったパックも、どの切り抜きか分かるように(案件の印・友人の「要らない」)
                    run.pack_marks[d] = {"path": m["path"], "markId": str(m["id"])}
        if run.mode == "full" and self._origin(run) == "auto":   # まとめて実行で友人へ自動で送る(D-SEND): 先に送るかを決める
            dirs = self._full_gate(run, st, v, clips, dirs)
            if dirs is None:
                return None
        return self._deliver(run, st, dirs)

    def _full_gate(self, run, st, v, clips, dirs):
        """まとめて実行の自動で送るか(flow/sendpolicy.decide)。送らないなら段を飛ばして理由の文・切り抜きごとに notSent を残し None。
        送るなら、もう届けたパック(届けた記録にある物)を除いた dirs(二重に送らない)"""
        ended = sendpolicy.ended_at_of(v.get("analysis") if isinstance(v, dict) else None)
        now = self.clock()
        checked = bool(run.deliver_dir)
        run.send_ended_at = ended   # 届けた記録の endedAt・溜めの 48 時間(実行の欄ではない = 残さない。段をやり直せばまた決める)
        send, code = sendpolicy.decide("auto", ended, now, checked and self._requested(run.video_id), checked)
        if not send:
            text = sendpolicy.reason_text(code, sendpolicy.hours_since(ended, now) if ended else None)
            st["state"], st["detail"] = "skip", text
            for m in clips:
                self._not_sent(run.video_id, m.get("id"), code, text)
            self.log("まとめて実行: %s を友人へ送りません(%s)" % (run.title or run.video_id, text))
            return None
        sent = self._sent_dirs()
        left = [d for d in dirs if os.path.normcase(os.path.normpath(d)) not in sent or d in run.delivered]
        if dirs and not left:
            st["state"], st["detail"] = "skip", "パックはもう友人へ届けてあります"
            return None
        return left

    def _not_sent(self, video_id, mark_id, code, text):
        try:
            if video_id and mark_id:
                self._remember_not_sent(video_id, str(mark_id), code, text)
        except Exception as e:   # noqa: BLE001  (残せなくても段は進める)
            self.log("まとめて実行: 送らなかった記録を残せませんでした(%s)" % (str(e)[:120] or e.__class__.__name__))

    def _sent_dirs(self):
        """届けた記録にあるパックのフォルダ(大文字・小文字と区切りをそろえた形の集合)。読めなければ空"""
        rows = deliveries_mod.rows(os.path.dirname(self.log_path)) if self.log_path else None
        return {os.path.normcase(os.path.normpath(str(p.get("dir")))) for r in rows or () for p in r.get("packs") or () if isinstance(p, dict) and p.get("dir")}

    def _requested(self, video_id):
        """その配信を友人が依頼済みか(D-SEND 2-9): 受付の覚え(requested_hook)・届けた記録の origin request の配信・送り返し(友人の PC で処理した依頼)"""
        if not video_id:
            return False
        try:
            if self.requested_hook is not None and self.requested_hook(video_id):
                return True
        except Exception:   # noqa: BLE001  (引けなければ次の引き方へ)
            pass
        if not self.log_path:
            return False
        log_dir = os.path.dirname(self.log_path)
        if video_id in (deliveries_mod.delivered_videos(log_dir, origin="request") or {}):
            return True
        try:
            return bool(self._returned_request(video_id))
        except OSError:
            return False

    @staticmethod
    def _origin(run):
        """届けるときの出どころ: run.deliver_origin(request・auto・manual)。無ければ依頼の id があれば request・無ければ auto"""
        o = getattr(run, "deliver_origin", None)
        if o in sendpolicy.ORIGINS:
            return o
        return "request" if getattr(run, "request_id", None) else "auto"

    @staticmethod
    def _deliver_name(run, title):
        """出力 に置くものの名前(拡張子なし): <名前の頭>__<題>。頭 = run.deliver_tag(自動で送る分。友人のアプリの名前の形 YYYYMMDD-HHMMSS-xxxxxx)→
        依頼 id → 実行の id"""
        return deliver_mod.delivery_name(getattr(run, "deliver_tag", None) or run.request_id or run.id, title)

    def _deliver(self, run, st, dirs):
        """① 全自動の届ける段: この実行のパック(前からあったものも)のうち、まだ届けていない分を全部 Dropbox の 出力 へ置く
        (友人のアプリの「受け取る」に出る。n 本ごとのまとめ方は _deliver_pending)。
        出どころ auto: YTT_AUTO_SEND=off なら届けない・置けなければ溜めに預けて送り直す(_park。段は warn = 実行は失敗にしない)"""
        dirs = [d for d in dict.fromkeys(os.path.normpath(x) for x in dirs if x) if os.path.isdir(d)]
        if not run.deliver_dir:
            st["state"], st["detail"] = "skip", "届け先がありません"
            return None
        if not dirs:
            st["state"], st["detail"] = "skip", "届けるパックがありません"
            return None
        auto = self._origin(run) == "auto"
        if auto and sendpolicy.switched_off():
            st["state"], st["detail"] = "skip", "開発機の守り(環境変数 %s=off)なので友人へ送りません" % sendpolicy.ENV_SWITCH
            return None
        if run.pool and self._batch_size(run) > 1:   # ライブの切り抜き: 実行をまたいで溜めに預け、n 本たまったら組で届ける(1 本ずつのときは今までどおり)
            return self._pool_add(run, st, dirs)
        for d in dirs:
            if d not in run.packs:
                run.packs.append(d)   # 前からあったパックも、この実行の並び(1 本目・2 本目…)に入れて同じ数え方で届ける
        if auto:
            try:
                if not self._outbox_ok(run.deliver_dir):
                    raise self._place_error(FileNotFoundError(2, "Dropbox のフォルダが見つかりません", os.path.dirname(os.path.normpath(run.deliver_dir))))
                self._deliver_pending(run, st, "", final=True)
            except run_mod.StepError as e:
                return self._park(run, st, e)
        else:
            self._deliver_pending(run, st, "", final=True)
        st["detail"] = "%d 本のパックを Dropbox の 出力 に置きました(字幕は校正前)" % len(run.delivered)
        return None

    @staticmethod
    def _outbox_ok(out_dir):
        """出力 の親(受付の Dropbox のフォルダ)があるか(無いのに 出力 を作ると、Dropbox でない所に置いてしまう)"""
        parent = os.path.dirname(os.path.normpath(out_dir or ""))
        return bool(parent) and not fsio.is_network_path(parent) and os.path.isdir(parent)

    def _park(self, run, st, err):
        """置けなかった自動の分を溜めに預ける(D-SEND 2-6): 鍵 full|<名前の頭>|<配信>(ライブの自動は auto|…)・meta {origin, videoId, endedAt, parked}。
        預けたパックはこの実行では届け済みの扱い(二重に置かない)。終わった時刻が分からない(ライブ)は預けた時刻から 48 時間"""
        now = self.clock()
        pending = [d for d in run.packs if d not in run.delivered and os.path.isdir(d)]
        if not pending:
            raise err
        tag = getattr(run, "deliver_tag", None) or run.request_id or run.id
        key = "%s|%s|%s" % ("full" if run.mode == "full" else "auto", tag, run.video_id or run.id)
        ended = getattr(run, "send_ended_at", None)
        with self._pool_lock:
            pools = self._pools_load()
            p = pools.get(key) or {"rid": run.request_id or tag, "tag": getattr(run, "deliver_tag", None), "origin": "auto", "mode": run.mode,
                                   "title": run.title or "pack", "deliverDir": run.deliver_dir, "batch": run.deliver_batch,
                                   "meta": {"origin": "auto", "videoId": run.video_id or "", "endedAt": ended if ended else now, "parked": True},
                                   "packs": [], "delivered": [], "marks": {}, "created": now}
            for d in pending:
                if d not in p["packs"]:
                    p["packs"].append(d)
                if isinstance(run.pack_marks.get(d), dict):
                    p["marks"][d] = run.pack_marks[d]
            p["updated"] = now
            pools[key] = p
            self._pools_save()
            self._mark_delivered(run, pending)
        st["state"] = "warn"
        st["detail"] = "Dropbox へ置けなかったので %d 本を預けました。次にホームが動いたときに送り直します(配信が終わってから %d 時間まで): %s" % (
            len(pending), sendpolicy.FRESH_SEC // 3600, str(err)[:160])
        self.log("まとめて実行: %s を友人へ届けられませんでした(%s)。%d 本を預けて、あとで送り直します" % (run.title or run.id, str(err)[:160], len(pending)))
        return None

    def _batch_size(self, run):
        """n 本ごとに組にして届ける。友人の依頼が指定していればそれ(run.deliver_batch。2-16)、次に友人のアプリの「届け方」(<受付のフォルダ>/設定/届け方.json。
        D-SEND 2-4)、無ければホームの設定 intake.deliverBatch(既定と範囲は継ぐ側の _deliver_batch_limits = 入口の prefs.py。1 = 1 本ずつ)"""
        if run.deliver_batch:
            return run.deliver_batch
        friend = self._friend_batch()
        if friend:
            return friend
        default, lo, hi = self._deliver_batch_limits()
        try:
            v = (self.prefs.get(["intake"])["intake"] or {}).get("deliverBatch") if self.prefs else None
            return max(lo, min(hi, int(v))) if v is not None else default
        except (OSError, ValueError, KeyError, TypeError):
            return default

    def _deliver_pending(self, run, st, prefix, final):
        """まだ届けていないパックを n 本ごとに届ける(final = 実行の終わり: n 本に満たない分もその本数で届ける)。
        2 本以上なら組(_deliver_group = まとめ動画 1 本 + 1 本ずつの zip + .group.json)、1 本なら 1 本の zip + そのまとめ動画(_deliver_one)。2-16"""
        n = self._batch_size(run)
        while True:
            pending = [p for p in run.packs if p not in run.delivered and os.path.isdir(p)]
            if not pending or (len(pending) < n and not final):
                return
            batch = pending[:n]
            if n <= 1 or len(batch) <= 1:
                self._deliver_one(run, batch[0])
            else:
                self._deliver_group(run, st, batch, prefix)

    def _deliver_group(self, run, st, batch, prefix):
        """n 本のパックを組にして 出力 へ(notes:docs/spec/friend.md の 2-16): ① 組のまとめ動画 <依頼 id>__<題> 1-5.preview.mp4(2-13 の中身のまま)→
        ② 1 本ずつの zip(_deliver_one と同じ <依頼 id>__<パックの題>.zip。まとめ動画は組のものを使うので付けない)→ ③ 最後に <同じ名前>.group.json(zip の名前・何本目・
        まとめ動画の中の開始秒)。友人のアプリ(2.8.0)はまとめ動画を見てから 1 本ずつ受け取る・要らないを選べる。古いアプリは 1 本ずつの zip として受け取れる。
        まとめ動画を作れなくても(ffmpeg が無い・動画が壊れている)zip と一覧は届ける。届けた記録(deliveries.jsonl)は zip ごと"""
        first, last = run.packs.index(batch[0]) + 1, run.packs.index(batch[-1]) + 1
        rng = "%d-%d" % (first, last)
        name = self._deliver_name(run, "%s %s" % (run.title or "pack", rng))
        st["detail"] = prefix + "まとめ動画を作っています(%d 本)" % len(batch)

        def check():
            self._check(run)
        preview = _preview.batch_preview(batch, check=check, log=self.log)   # 作れなければ None
        seconds = _preview.clip_seconds(batch)
        zips, titles, secs = [], [], []
        # 一覧(.group.json)を書けなかったら、先に置いた組のまとめ動画は消す(相手のいない動画は誰にも見えないごみになる。置けた zip は 1 本ずつの形で残る)
        with self._placing(preview) as placed:
            os.makedirs(run.deliver_dir, exist_ok=True)
            pv_path, json_path, name = deliver_mod.group_paths(run.deliver_dir, name)
            if preview:
                placed[0] = pv_path   # 写している途中で止まっても(ディスクがいっぱい)、書きかけを残さないように先に控える
                shutil.copyfile(preview, pv_path)
            for i, d in enumerate(batch):
                st["detail"] = prefix + "%d 本を 1 本ずつ zip にして Dropbox へ届けています(%d / %d)" % (len(batch), i + 1, len(batch))
                zp = self._deliver_one(run, d, with_preview=False)
                if zp:
                    zips.append((run.packs.index(d) + 1, zp))
                    titles.append(_preview.pack_title(d))
                    secs.append(seconds[i])
            deliver_mod.write_group_json(json_path, run.title or "pack", rng, placed[0], deliver_mod.group_members(zips, titles, secs),
                                         origin=deliver_mod.face_origin(self._origin(run)))   # 出どころ(D-SEND 2-7。友人のアプリの札「依頼なし」)

    def _mark_delivered(self, run, dirs):
        """届けたパックを run.delivered に足して、すぐ残す(段の途中で起動し直しても、同じパックを二度置かない。M5)"""
        run.delivered.extend(dirs)
        self._save_active()

    @staticmethod
    def _place_error(e):
        return run_mod.StepError("パックを Dropbox へ置けませんでした: %s" % tools.why(e))

    @contextlib.contextmanager
    def _placing(self, preview):
        """届けるときの後片付け(組と 1 本で共通): 中で失敗したら、先に置いたまとめ動画(箱 placed[0])を消し、OSError は StepError(_place_error)に変える。
        最後に一時のまとめ動画 preview を消す。-> 箱 [置いたまとめ動画のパス or None]"""
        placed = [None]
        try:
            yield placed
        except Exception as e:
            _preview.remove_quiet(placed[0])
            if isinstance(e, OSError):
                raise self._place_error(e)
            raise
        finally:
            _preview.remove_quiet(preview)

    def _deliver_rest_quietly(self, run):
        """止まった実行に、まとめて届ける前のパック(n 本に満たず手元に残っていた分)があれば届ける。届けられなくても失敗の知らせは置く"""
        if "deliver" not in run_mod.MODE_STEPS.get(run.mode, ()):
            return
        try:
            self._deliver_pending(run, {}, "", final=True)
        except Exception as e:   # noqa: BLE001  (届け残しが置けなくても止まった知らせは出す)
            self.log("まとめて実行: 止まった実行のパックを届けられませんでした(%s)" % (str(e)[:120] or e.__class__.__name__))

    def _deliver_one(self, run, d, with_preview=True):
        """1本のパックのフォルダを zip(<依頼 id>__<パックの題>.zip)にして 出力 へ置く(deliver.deliver_one = まとめ動画 → zip → 届けた記録。
        「編集」の「友人へ届ける」と同じ)。with_preview: その切り抜きだけのまとめ動画を隣へ(2-16。友人は 1 本でも見てから選べる。組の中では組のものを使うので付けない)。
        d は run.packs の書き方のまま(届けた印 run.delivered と同じ文字列で比べる。run.packs に入れるときにそろえてある)。-> 置いた zip のパス(届け済みなら None)"""
        if d in run.delivered or not os.path.isdir(d):
            return None
        name = self._deliver_name(run, _preview.pack_title(d) or run.title or "pack")
        with self._placing(None):   # 置けなかったら StepError(置いたまとめ動画は deliver_one が消す)
            dest = deliver_mod.deliver_one(d, run.deliver_dir, name, log_dir=os.path.dirname(self.log_path) if self.log_path else None, run=run,
                                           marks=run.pack_marks, with_preview=with_preview, check=lambda: self._check(run), log=self.log,
                                           origin=self._origin(run), ended_at=getattr(run, "send_ended_at", None))
            self._mark_delivered(run, [d])
            return dest

    # ------------------------------------------------------------ ライブの切り抜きの組の溜め(10-09 ユーザー決定 = decisions 3-20)
    def _pools_load(self):
        """溜めの一覧(呼ぶのは self._pool_lock を持っている間)"""
        if self._pools is None:
            d = fsio.read_json_or(self.pool_path, {}) if self.pool_path else {}
            pools = d.get("pools") if isinstance(d, dict) and d.get("schema") == POOL_SCHEMA else None
            self._pools = {k: v for k, v in (pools or {}).items() if isinstance(k, str) and isinstance(v, dict) and isinstance(v.get("packs"), list)}
        return self._pools

    def _pools_save(self):
        if not self.pool_path:
            return
        try:
            fsio.atomic_write(self.pool_path, json.dumps({"schema": POOL_SCHEMA, "pools": self._pools or {}}, ensure_ascii=False, indent=1).encode("utf-8"))
        except OSError as e:
            self.log("まとめて実行: 組の溜めを書けませんでした(%s)" % tools.why(e))

    def pools(self):
        """溜めの今(画面・テスト用)-> {鍵: {rid, title, waiting(まだ届けていない本数), meta}}"""
        with self._pool_lock:
            return {k: {"rid": p.get("rid"), "title": p.get("title"), "meta": p.get("meta"),
                        "waiting": sum(1 for d in p["packs"] if d not in (p.get("delivered") or []))} for k, p in self._pools_load().items()}

    def _pool_add(self, run, st, dirs):
        """この実行のパックを溜めに預け、n 本たまっていれば組で届ける。預けたパックはこの実行では届け済みの扱い(二重に置かない)"""
        key, now = run.pool["key"], self.clock()
        with self._pool_lock:
            pools = self._pools_load()
            p = pools.get(key) or {"rid": run.pool.get("rid") or run.request_id or run.id, "title": run.pool.get("title") or run.title or "pack",
                                   "deliverDir": run.deliver_dir, "batch": run.deliver_batch, "meta": run.pool.get("meta") or {},
                                   "packs": [], "delivered": [], "marks": {}, "created": now,
                                   "origin": self._origin(run), "tag": getattr(run, "deliver_tag", None)}   # 出どころ・名前の頭(D-SEND。古い溜めには無い)
            for d in dirs:
                if d not in p["packs"]:
                    p["packs"].append(d)
                if isinstance(run.pack_marks.get(d), dict):
                    p["marks"][d] = run.pack_marks[d]
            p["updated"] = now
            pools[key] = p
            self._pools_save()
            self._mark_delivered(run, [d for d in dirs if d not in run.delivered])
            self._pool_deliver(key, final=False, st=st)
            p = self._pools_load().get(key)
            waiting = sum(1 for d in (p or {}).get("packs", []) if d not in (p or {}).get("delivered", []))
        n = self._batch_size(run)
        st["detail"] = ("%d 本たまったので組で Dropbox の 出力 に置きました(字幕は校正前)" % n) if not waiting else \
            "%d 本の組にためています(今 %d 本。録画が終わったら残りも届けます)" % (n, waiting)
        return None

    def _pool_deliver(self, key, final, st=None):
        """溜め 1 つの、まだ届けていないパックを n 本ごとに届ける(final = 残りも)。-> 届けた本数。届け終えた溜めは消す"""
        with self._pool_lock:
            pools = self._pools_load()
            p = pools.get(key)
            if not p:
                return 0
            prun = _PoolRun(key, p)
            before = len(prun.delivered)
            try:
                self._deliver_pending(prun, st if st is not None else {}, "", final)
            finally:
                p["delivered"] = list(prun.delivered)
                if final and all(d in p["delivered"] or not os.path.isdir(d) for d in p["packs"]):
                    pools.pop(key, None)
                self._pools_save()
            return len(prun.delivered) - before

    def flush_pools(self, is_done, now=None):
        """溜めの残りを届ける見回り(入口の src/app/live.py が呼ぶ)。is_done(meta) = その録画・その段がもう切り抜きを作らないか
        (録画が終わった・書き出しの途中が無い)。届けるのは: is_done が真で、その溜めに預ける実行が待ち・実行中に無く、最後に預けてから POOL_IDLE_SEC たったとき、
        または溜めを作ってから POOL_MAX_AGE たったとき。
        置けなかった自動の分(meta.parked。D-SEND 2-6)は待たずにすぐ送り直す(受付の Dropbox のフォルダがあるとき)。配信が終わってから 48 時間を過ぎていれば
        送らずに溜めを消し、切り抜きごとに notSent expired。出どころ auto は YTT_AUTO_SEND=off なら届けない(溜めは残す)。
        入口の src/app/live.py の見回りと、受付の Intake.scan の終わり(server.py が flush に渡す)が呼ぶ。-> 届けた本数の合計"""
        now = self.clock() if now is None else now
        with self._pool_lock:
            keys = list(self._pools_load())
        total = 0
        off = sendpolicy.switched_off()
        for key in keys:
            with self._pool_lock:
                p = self._pools_load().get(key)
                if not p:
                    continue
                if not any(d not in p["delivered"] and os.path.isdir(d) for d in p["packs"]):
                    self._pools_load().pop(key, None)
                    self._pools_save()
                    continue
                if off and _PoolRun(key, p).deliver_origin == "auto":
                    continue
                if (p.get("meta") or {}).get("parked"):
                    total += self._flush_parked(key, p, now)
                    continue
                with self.cv:
                    busy = any(r.pool and r.pool.get("key") == key for r in self._active_runs())
                idle = now - float(p.get("updated") or 0) >= POOL_IDLE_SEC
                old = now - float(p.get("created") or now) >= POOL_MAX_AGE
                try:
                    done = bool(is_done(p.get("meta") or {}))
                except Exception:   # noqa: BLE001  (確かめられなければ、届けるのは待つ)
                    done = False
                if not (old or (idle and not busy and done)):
                    continue
                try:
                    total += self._pool_deliver(key, final=True)
                except Exception as e:   # noqa: BLE001  (置けなければ次の見回りでまた試す)
                    self.log("まとめて実行: 組の残りを届けられませんでした(%s)" % (str(e)[:120] or e.__class__.__name__))
        return total

    def _flush_parked(self, key, p, now):
        """置けなかった自動の分の溜め 1 つ(呼ぶのは self._pool_lock を持っている間)。48 時間を過ぎていれば消して notSent expired、
        受付の Dropbox のフォルダが無ければ待つ、あれば全部届ける。-> 届けた本数"""
        meta = p.get("meta") or {}
        ended = meta.get("endedAt")
        fresh = isinstance(ended, (int, float)) and not isinstance(ended, bool) and ended > 0 and now - ended <= sendpolicy.FRESH_SEC
        if not fresh:
            left = [d for d in p["packs"] if d not in p["delivered"]]
            self._pools_load().pop(key, None)
            self._pools_save()
            text = sendpolicy.reason_text("expired")
            for d in left:
                self._not_sent(meta.get("videoId"), (p.get("marks", {}).get(d) or {}).get("markId"), "expired", text)
            self.log("まとめて実行: %s の %d 本は届けられないまま配信が終わってから %d 時間を過ぎたので、送りませんでした(%s)" % (
                p.get("title") or key, len(left), sendpolicy.FRESH_SEC // 3600, text))
            return 0
        if not self._outbox_ok(p.get("deliverDir")):
            return 0
        try:
            n = self._pool_deliver(key, final=True)
        except Exception as e:   # noqa: BLE001  (置けなければ次の見回りでまた試す)
            self.log("まとめて実行: 預けていた %s を送り直せませんでした(%s)" % (p.get("title") or key, str(e)[:120] or e.__class__.__name__))
            return 0
        if n:
            self.log("まとめて実行: 預けていた %s の %d 本を友人へ送り直しました" % (p.get("title") or key, n))
        return n

    def _deliver_failure(self, run):
        """① 全自動が止まったとき、友人のアプリの「受け取る」に理由を出す(<依頼 id>__<題名>.失敗.txt)。友人の依頼(出どころ request)だけ
        (自動で送る分は友人に知らせない = ホームのログと案件の画面だけ。D-SEND 2-6)"""
        if self._origin(run) != "request":
            return
        try:
            os.makedirs(run.deliver_dir, exist_ok=True)
            name = self._deliver_name(run, run.title or "依頼") + ".失敗.txt"
            text = "自動の処理が止まりました。\r\n理由: %s\r\n送り先の人が確かめます。" % (run.error or run.message)
            with open(os.path.join(run.deliver_dir, name), "w", encoding="utf-8-sig", newline="") as f:
                f.write(text + "\r\n")
        except OSError:
            pass
