"""② 友人へ届ける: まとめて実行の「Dropbox へ届ける」段と、置けなかった自動の分の溜め(まとめて実行 AutoRunner が継ぐ mixin)。
ds1(要件 1-5「届ける段と溜めは ② へ」・仮決め 3-70 ds1・3-71 m3i)。
① 確認用の動画は pipeline/pack/preview・1 本を届ける部品は同じフォルダの deliver。③(受付・送り返し)は読まない(友人の PC には ③ が無い)。

形: AutoRunner(入口の src/app/autorun.py)が `class AutoRunner(Delivery, Queue)` で継ぐ(Queue = src/flow/runqueue.py)。ここは入口の部品
(autorun・launch・live・prefs)も案件の部品(manage/cases)も ③ も読まない = 要るものは継いだクラスが埋める:
  - _save_active()・_active_runs()                 待ち・実行中の記録を残す(M5)・待ちと実行中の一覧(Queue)
  - 属性 log_path(終わった実行の記録のパス。隣に deliveries.jsonl)・cv・log・clock・find_pack と Runner の _check・_clips
溜めの置き場所とロックは _delivery_init(log_dir) で作る(AutoRunner の __init__ が呼ぶ)。

届ける形(notes:plan/f1-friend-requirements.md の C-3-1・C-6): **パックはできた順に 1 本ずつ**届ける(1 本の zip + 480p の確認用の動画 + .meta.json。
作り方は同じフォルダの deliver.deliver_one = 手で届けるのも同じ)。
溜め(logs/deliver-pool.json)は、置けなかった自動の分(下)とライブの切り抜きの残りに使う(flush_pools が 1 本ずつ届ける)。

友人へ自動で送る(D-SEND。要件 notes:plan/done/d-send-requirements.md):
  - 送るかは注文を作る所が届け先(封筒の deliver.dir)を入れるかで決める(10-19 ユーザー決定 = 案 B3。切り替えはホームのまとめて実行と配信を探すの
    チェックだけ・ほかは受付のフォルダが決まっていればいつも送る)。届け先があれば段 deliver が付き(flow/run.steps_of)、ここは「置く」だけ。
    友人が依頼済みか・終わってから 48 時間かは見ない(2-1 の鮮度・2-9 の依頼済みは 10-19 に取り下げ。二重は防がない)
  - チェックを外したまとめて実行(出どころ auto・届け先なし)も段 deliver を持ち、送らずに切り抜きごとに送らなかった記録 unchecked を残す
    (品質のカード 2-8 の「まとめて実行の切り抜き」に出すため)
  - 出どころ(_origin): run.deliver_origin(request・auto・manual)。無ければ依頼の id があれば request・無ければ auto。友人に見せる形は deliver.face_origin
  - 出どころ auto は、届けた記録にあるパックを除く(同じパックを 2 回送らない = _sent_dirs)
  - 置けない(Dropbox のフォルダが無い・書けない)とき、出どころ auto は実行を失敗にせず溜めに預ける(鍵 full|<deliver_tag>|<配信>。meta.parked)・段は warn。
    flush_pools がすぐ送り直す(受付のフォルダがあるとき)。預けてから PARK_KEEP_SEC(片付けの 3 日)を過ぎたら送らず溜めを消し、
    切り抜きごとに送らなかった記録 expired(logs/not-sent.jsonl。flow/deliveries.record_not_sent。案件の「送らなかった」の札)
  - 友人に失敗の知らせ(.失敗.txt)を置くのは依頼(request)だけ(2-6)。環境変数 YTT_AUTO_SEND=off(switched_off = 開発機の守り)なら auto は届けない
届けたは案件に写さない(届けた記録 logs/deliveries.jsonl は deliver.deliver_one が書き、案件は ② flow/deliveries.delivered_marks で引く。MARKS-3)。
"""
import contextlib
import json
import os
import threading
import uuid

from pipeline.pack import preview as _preview   # ① パックの題
from ytt import fsio, tools
from . import deliver as deliver_mod   # 1 本を届ける(確認用の動画 → meta → zip → 届けた記録)・名前の整え方
from . import deliveries as deliveries_mod   # 届けた記録の読み口(届け済みのパック)・送らなかった記録の書く口
from . import retention   # 物の終わりの日数
from . import envelope as envelope_mod   # 届けるときの出どころの一覧 DELIVER_ORIGINS
from . import run as run_mod   # 段の失敗 StepError(② の経路)

ENV_SWITCH = "YTT_AUTO_SEND"   # 開発機の守り: off で出どころ auto の届けを止める(switched_off)
PARK_KEEP_SEC = retention.KEEP_SEC   # 置けなかった自動の分を送り直す期限(預けてから。物の終わりの日数)
EXPIRED = "expired"            # 送らなかった記録の理由の鍵(期限切れ。案件の画面の札 cases.js の NOT_SENT と同じ鍵)
EXPIRED_TEXT = "送らなかった(古くなった)"
UNCHECKED = "unchecked"        # 同(まとめて実行で「友人へ自動で送る」のチェックを外した)
UNCHECKED_TEXT = "チェックを外したので送りません"
POOL_FILE = "deliver-pool.json"   # 溜め(置けなかった自動の分・前の版で溜めたライブの切り抜きの残り。log_dir の中)
POOL_SCHEMA = "ytt-deliver-pool/v1"
POOL_IDLE_SEC = 600.0              # (前の版のライブの溜め)録画が終わって書き出しも実行も無くなってから、最後に預けてこれだけたったら残りを届ける
POOL_MAX_AGE = 12 * 3600.0         # (同)溜めを作ってからこれだけたったら、終わりを待たずに残りを届ける


def switched_off(environ=None):
    """環境変数 YTT_AUTO_SEND=off(開発機の守り)か。True のとき出どころ auto の届けをしない"""
    env = os.environ if environ is None else environ
    return str(env.get(ENV_SWITCH) or "").strip().lower() == "off"


class _PoolRun:
    """溜めを届けるときに Delivery の届ける部品(_deliver_pending・_deliver_one)へ渡す、実行の代わり"""

    def __init__(self, key, p):
        self.id = "pool" + uuid.uuid5(uuid.NAMESPACE_URL, key).hex[:6]
        self.request_id, self.title, self.deliver_dir = p.get("rid") or "", p.get("title") or "pack", p.get("deliverDir") or ""
        meta = p.get("meta") if isinstance(p.get("meta"), dict) else {}
        self.video_id = meta.get("videoId") or meta.get("recording") or ""
        self.packs, self.delivered = list(p.get("packs") or []), list(p.get("delivered") or [])
        self.pack_marks = dict(p.get("marks") or {})
        self.cancel, self.pool = False, None
        # D-SEND: 名前の頭・出どころ・実行の形(古い溜めには無い = 名前は依頼の id・出どころは鍵の 2 つ目が auto なら auto)
        tag = p.get("tag")
        self.deliver_tag = tag if isinstance(tag, str) and tag else None
        origins = envelope_mod.DELIVER_ORIGINS
        origin = p.get("origin") if p.get("origin") in origins else meta.get("origin")
        parts = key.split("|")
        self.deliver_origin = origin if origin in origins else ("auto" if len(parts) > 1 and parts[1] == "auto" else "request")
        self.mode = p.get("mode") if isinstance(p.get("mode"), str) else None


class Delivery:
    """まとめて実行(AutoRunner)が継ぐ、友人へ届ける段と溜め。継ぐ側が埋めるものはこのファイルの先頭の説明"""

    def _delivery_init(self, log_dir):
        """溜めの置き場所(log_dir の中。None = メモリだけ)とロック"""
        self.pool_path = os.path.join(log_dir, POOL_FILE) if log_dir else None   # 届ける溜め(None = メモリだけ)
        self._pool_lock = threading.RLock()   # 溜めの読み書きと溜めから届ける間(これを持ったまま self.cv を取ってよい。逆に self.cv を持ったまま取らない)
        self._pools = None                    # {溜めの鍵: {rid, title, deliverDir, meta, packs, delivered, marks, created, updated, (tag, origin, mode)}}(初めて使うときに読む)

    def _after_pack(self, run, st, prefix):
        """① 全自動: パックができるたびに 1 本ずつ届ける(全部を待たない)。まとめて実行(依頼の番号の無い配信)は段 deliver で
        (届け済みのパックを除いてから)まとめて置く"""
        if run.deliver_dir and run.delivers() and (run.request_id or run.kind() != "url"):
            self._deliver_pending(run)

    # 依頼の動画(mode file) -------------------------------------
    def _file_deliver(self, run, st):
        found = self.find_pack(run.source_path)
        return self._deliver(run, st, list(run.packs) + ([found["dir"]] if found else []))

    def _step_deliver(self, run, st, v):
        clips = self._clips(v, run)
        if not run.deliver_dir:   # チェックを外したまとめて実行: 送らず、切り抜きごとに送らなかった記録(品質のカード 2-8 の「まとめて実行の切り抜き」)
            st["state"], st["detail"] = "skip", UNCHECKED_TEXT
            for m in clips:
                self._not_sent(run.video_id, m.get("id"), UNCHECKED, UNCHECKED_TEXT)
            return None
        dirs = list(run.packs)
        for m in clips:
            found = self.find_pack(m["path"])
            if found:
                d = os.path.normpath(found["dir"])
                dirs.append(d)
                if not run.request_id and d not in run.pack_marks and m.get("id"):   # 前からあったパックも、どの切り抜きか分かるように(案件の印・友人の「要らない」)
                    run.pack_marks[d] = {"path": m["path"], "markId": str(m["id"])}
        if self._origin(run) == "auto":   # 自動で送る分は、届けた記録にあるパックを除く(同じパックを 2 回送らない)
            sent = self._sent_dirs()
            left = [d for d in dirs if os.path.normcase(os.path.normpath(d)) not in sent or d in run.delivered]
            if dirs and not left:
                st["state"], st["detail"] = "skip", "パックはもう友人へ届けてあります"
                return None
            dirs = left
        return self._deliver(run, st, dirs)

    def _not_sent(self, video_id, mark_id, code, text):
        """送らなかった切り抜きを ② の送らなかった記録へ(logs/not-sent.jsonl。④ 案件の札が引く)。残せなくてもログだけ"""
        try:
            if video_id and mark_id and self.log_path:
                deliveries_mod.record_not_sent(os.path.dirname(self.log_path), video_id, str(mark_id), code, text)
        except Exception as e:   # noqa: BLE001  (残せなくても進める)
            self.log("まとめて実行: 送らなかった記録を残せませんでした(%s)" % (str(e)[:120] or e.__class__.__name__))

    def _sent_dirs(self):
        """届けた記録にあるパックのフォルダ(大文字・小文字と区切りをそろえた形の集合)。読めなければ空"""
        rows = deliveries_mod.rows(os.path.dirname(self.log_path)) if self.log_path else None
        return {os.path.normcase(os.path.normpath(str(p.get("dir")))) for r in rows or () for p in r.get("packs") or () if isinstance(p, dict) and p.get("dir")}

    @staticmethod
    def _origin(run):
        """届けるときの出どころ: run.deliver_origin(request・auto・manual)。無ければ依頼の id があれば request・無ければ auto"""
        o = getattr(run, "deliver_origin", None)
        if o in envelope_mod.DELIVER_ORIGINS:
            return o
        return "request" if getattr(run, "request_id", None) else "auto"

    @staticmethod
    def _deliver_name(run, title):
        """出力 に置くものの名前(拡張子なし): <名前の頭>__<題>。頭 = run.deliver_tag(自動で送る分。友人のアプリの名前の形 YYYYMMDD-HHMMSS-xxxxxx)→
        依頼 id → 実行の id"""
        return deliver_mod.delivery_name(getattr(run, "deliver_tag", None) or run.request_id or run.id, title)

    def _deliver(self, run, st, dirs):
        """① 全自動の届ける段: この実行のパック(前からあったものも)のうち、まだ届けていない分を全部 1 本ずつ Dropbox の 出力 へ置く
        (友人のアプリの「受け取る」に出る)。
        出どころ auto: YTT_AUTO_SEND=off なら届けない・置けなければ溜めに預けて送り直す(_park。段は warn = 実行は失敗にしない)"""
        dirs = [d for d in dict.fromkeys(os.path.normpath(x) for x in dirs if x) if os.path.isdir(d)]
        if not run.deliver_dir:
            st["state"], st["detail"] = "skip", "届け先がありません"
            return None
        if not dirs:
            st["state"], st["detail"] = "skip", "届けるパックがありません"
            return None
        auto = self._origin(run) == "auto"
        if auto and switched_off():
            st["state"], st["detail"] = "skip", "開発機の守り(環境変数 %s=off)なので友人へ送りません" % ENV_SWITCH
            return None
        for d in dirs:
            if d not in run.packs:
                run.packs.append(d)   # 前からあったパックも、この実行の並び(1 本目・2 本目…)に入れて同じ数え方で届ける
        if auto:
            try:
                if not deliver_mod.outbox_ok(run.deliver_dir):
                    raise self._place_error(FileNotFoundError(2, "Dropbox のフォルダが見つかりません", os.path.dirname(os.path.normpath(run.deliver_dir))))
                self._deliver_pending(run)
            except run_mod.StepError as e:
                return self._park(run, st, e)
        else:
            self._deliver_pending(run)
        st["detail"] = "%d 本のパックを Dropbox の 出力 に置きました(字幕は校正前)" % len(run.delivered)
        return None

    def _park(self, run, st, err):
        """置けなかった自動の分を溜めに預ける(D-SEND 2-6): 鍵 full|<名前の頭>|<配信>(ライブの自動は auto|…)・meta {origin, videoId, parked}。
        預けたパックはこの実行では届け済みの扱い(二重に置かない)。送り直すのは預けてから PARK_KEEP_SEC(3 日)まで"""
        now = self.clock()
        pending = [d for d in run.packs if d not in run.delivered and os.path.isdir(d)]
        if not pending:
            raise err
        tag = getattr(run, "deliver_tag", None) or run.request_id or run.id
        key = "%s|%s|%s" % ("full" if run.kind() == "url" else "auto", tag, run.video_id or run.id)   # 鍵の頭は前のまま(配信 = まとめて実行 full・ライブの書き出し = auto)
        with self._pool_lock:
            pools = self._pools_load()
            p = pools.get(key) or {"rid": run.request_id or tag, "tag": getattr(run, "deliver_tag", None), "origin": "auto", "mode": run.mode,
                                   "title": run.title or "pack", "deliverDir": run.deliver_dir,
                                   "meta": {"origin": "auto", "videoId": run.video_id or "", "parked": True},
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
        st["detail"] = "Dropbox へ置けなかったので %d 本を預けました。次にホームが動いたときに送り直します(%d 日まで): %s" % (
            len(pending), PARK_KEEP_SEC // 86400, str(err)[:160])
        self.log("まとめて実行: %s を友人へ届けられませんでした(%s)。%d 本を預けて、あとで送り直します" % (run.title or run.id, str(err)[:160], len(pending)))
        return None

    def _deliver_pending(self, run):
        """まだ届けていないパックを 1 本ずつ届ける"""
        for p in [p for p in run.packs if p not in run.delivered and os.path.isdir(p)]:
            self._deliver_one(run, p)

    def _mark_delivered(self, run, dirs):
        """届けたパックを run.delivered に足して、すぐ残す(段の途中で起動し直しても、同じパックを二度置かない。M5)"""
        run.delivered.extend(dirs)
        self._save_active()

    @staticmethod
    def _place_error(e):
        return run_mod.StepError("パックを Dropbox へ置けませんでした: %s" % tools.why(e))

    @contextlib.contextmanager
    def _placing(self):
        """届けるときの OSError を StepError(_place_error)に変える"""
        try:
            yield
        except OSError as e:
            raise self._place_error(e)

    def _deliver_rest_quietly(self, run):
        """止まった実行に、まだ届けていないパックがあれば届ける。届けられなくても失敗の知らせは置く"""
        if not run.deliver_dir or not run.delivers():
            return
        try:
            self._deliver_pending(run)
        except Exception as e:   # noqa: BLE001  (届け残しが置けなくても止まった知らせは出す)
            self.log("まとめて実行: 止まった実行のパックを届けられませんでした(%s)" % (str(e)[:120] or e.__class__.__name__))

    def _deliver_one(self, run, d):
        """1本のパックのフォルダを zip(<依頼 id>__<パックの題>.zip)にして 出力 へ置く(deliver.deliver_one = 確認用の動画 → meta → zip → 届けた記録。
        「編集」の「友人へ届ける」と同じ)。d は run.packs の書き方のまま(届けた印 run.delivered と同じ文字列で比べる。run.packs に入れるときにそろえてある)。
        -> 置いた zip のパス(届け済みなら None)"""
        if d in run.delivered or not os.path.isdir(d):
            return None
        name = self._deliver_name(run, _preview.pack_title(d) or run.title or "pack")
        with self._placing():   # 置けなかったら StepError(置いた確認用の動画・meta は deliver_one が消す)
            dest = deliver_mod.deliver_one(d, run.deliver_dir, name, log_dir=os.path.dirname(self.log_path) if self.log_path else None, run=run,
                                           marks=run.pack_marks, check=lambda: self._check(run), log=self.log,
                                           origin=self._origin(run))
            self._mark_delivered(run, [d])
            return dest

    # ------------------------------------------------------------ 溜め(置けなかった自動の分・ライブの切り抜きの残り)
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
            self.log("まとめて実行: 届ける溜めを書けませんでした(%s)" % tools.why(e))

    def pools(self):
        """溜めの今(画面・テスト用)-> {鍵: {rid, title, waiting(まだ届けていない本数), meta}}"""
        with self._pool_lock:
            return {k: {"rid": p.get("rid"), "title": p.get("title"), "meta": p.get("meta"),
                        "waiting": sum(1 for d in p["packs"] if d not in (p.get("delivered") or []))} for k, p in self._pools_load().items()}

    def _pool_deliver(self, key, final):
        """溜め 1 つの、まだ届けていないパックを 1 本ずつ届ける。-> 届けた本数。final で届け終えた溜めは消す"""
        with self._pool_lock:
            pools = self._pools_load()
            p = pools.get(key)
            if not p:
                return 0
            prun = _PoolRun(key, p)
            before = len(prun.delivered)
            try:
                self._deliver_pending(prun)
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
        置けなかった自動の分(meta.parked。D-SEND 2-6)は待たずにすぐ送り直す(受付の Dropbox のフォルダがあるとき)。預けてから PARK_KEEP_SEC を過ぎていれば
        送らずに溜めを消し、切り抜きごとに送らなかった記録 expired。出どころ auto は YTT_AUTO_SEND=off なら届けない(溜めは残す)。
        入口の src/app/live.py の見回りと、受付の Intake.scan の終わり(server.py が flush に渡す)が呼ぶ。-> 届けた本数の合計"""
        now = self.clock() if now is None else now
        with self._pool_lock:
            keys = list(self._pools_load())
        total = 0
        off = switched_off()
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
                    self.log("まとめて実行: 溜めの残りを届けられませんでした(%s)" % (str(e)[:120] or e.__class__.__name__))
        return total

    def _flush_parked(self, key, p, now):
        """置けなかった自動の分の溜め 1 つ(呼ぶのは self._pool_lock を持っている間)。預けてから PARK_KEEP_SEC(3 日)を過ぎていれば消して
        送らなかった記録 expired、受付の Dropbox のフォルダが無ければ待つ、あれば全部届ける。-> 届けた本数"""
        meta = p.get("meta") or {}
        created = p.get("created")
        created = created if isinstance(created, (int, float)) and not isinstance(created, bool) else 0
        if now - created > PARK_KEEP_SEC:
            left = [d for d in p["packs"] if d not in p["delivered"]]
            self._pools_load().pop(key, None)
            self._pools_save()
            for d in left:
                self._not_sent(meta.get("videoId"), (p.get("marks", {}).get(d) or {}).get("markId"), EXPIRED, EXPIRED_TEXT)
            self.log("まとめて実行: %s の %d 本は届けられないまま預けてから %d 日を過ぎたので、送りませんでした" % (
                p.get("title") or key, len(left), PARK_KEEP_SEC // 86400))
            return 0
        if not deliver_mod.outbox_ok(p.get("deliverDir")):
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
