"""② 友人へ届ける: まとめて実行の「Dropbox へ届ける」段と、ライブの切り抜きの組の溜め(役割で組み直す RS3-3。入口の src/home/autorun.py の
AutoRunner から mixin に切り出した。中身と動きは変えていない)。

形: AutoRunner(app)が `class AutoRunner(Delivery, run_mod.Runner)` で継ぐ。ここは入口の部品(autorun・launch・live・prefs)も
案件の部品(manage/cases)も読まない = 要るものは継いだクラスが埋める:
  - _deliver_batch_limits() -> (既定, 下限, 上限)  n 本ごとに組にする数の既定と範囲(ホームの設定 intake.deliverBatch。AutoRunner が prefs から)
  - _remember_delivered(切り抜きのパス, zip の名前)  案件の一覧に「届けた」を残す(AutoRunner が cases.remember_delivered を呼ぶ)
  - _save_active()・_active_runs()                 待ち・実行中の記録を残す(M5)・待ちと実行中の一覧(AutoRunner)
  - 属性 prefs(ホームの設定。get だけ)・log_path(終わった実行の記録のパス。隣に deliveries.jsonl)・cv・log・clock・find_pack と
    Runner の _check・_clips・_analyze_item
溜めの置き場所とロックは _delivery_init(log_dir) で作る(AutoRunner の __init__ が呼ぶ)。

届け方(docs/spec/friend-intake.md の 2-16): パックを n 本(依頼ごとの deliver_batch。無ければホームの設定 intake.deliverBatch)たまるごとに、
組 = まとめ動画 1 本 + 1 本ずつの zip + 組の一覧(.group.json)で Dropbox の 出力 へ置く(実行の終わりには n 本に満たない残りも)。
n=1 か 1 本だけのときは 1 本の zip + その隣のまとめ動画。作り方・名前は同じフォルダの deliver.py。
ライブの切り抜き(友人のライブ配信の依頼・live.autoDeliver)は 1 本ごとに別の実行なので、実行をまたいで「組の溜め」(run.pool)に預け、
n 本たまったら組で届ける(flush_pools は入口の src/home/live.py が見回りで呼ぶ)。溜めは logs/deliver-pool.json(10-09 ユーザー決定 = decisions 3-20)。
「確認してから届ける」(友人の依頼の ②③・ライブの after・手で届ける)の動きもそのまま(消すのは RS5・RS6 = 決定 3-25 の h)。
"""
import contextlib
import json
import os
import shutil
import threading
import uuid

from flow import run as run_mod   # 段の表 MODE_STEPS・段の失敗 StepError(① の経路)
from ytt import fsio, tools
from . import deliver as deliver_mod   # パックを zip にして届ける・まとめ動画・名前の整え方
from . import friend_feedback          # 届けた zip の中身の記録 deliveries.jsonl(友人の「要らない」が来たときに引く。2026-10-08)

POOL_FILE = "deliver-pool.json"   # ライブの切り抜きの組の溜め(実行をまたいで n 本ためて組で届ける。log_dir の中)
POOL_SCHEMA = "ytt-deliver-pool/v1"
POOL_IDLE_SEC = 600.0              # 録画が終わって書き出しも実行も無くなってから、最後に預けてこれだけたったら残りを届ける
POOL_MAX_AGE = 12 * 3600.0         # 溜めを作ってからこれだけたったら、終わりを待たずに残りを届ける(録画が長すぎる・見張りが止まった)


class _PoolRun:
    """組の溜めを届けるときに Delivery の届ける部品(_deliver_pending・_deliver_group・_deliver_one・_record_delivery)へ渡す、実行の代わり"""

    def __init__(self, key, p):
        self.id = "pool" + uuid.uuid5(uuid.NAMESPACE_URL, key).hex[:6]
        self.request_id, self.title, self.deliver_dir = p.get("rid") or "", p.get("title") or "pack", p.get("deliverDir") or ""
        b = p.get("batch")
        self.deliver_batch = b if isinstance(b, int) and not isinstance(b, bool) and 1 <= b <= 10 else None
        self.video_id = (p.get("meta") or {}).get("recording") or ""
        self.packs, self.delivered = list(p.get("packs") or []), list(p.get("delivered") or [])
        self.pack_marks = dict(p.get("marks") or {})
        self.cancel, self.pool = False, None


class Delivery:
    """まとめて実行(AutoRunner)が継ぐ、友人へ届ける段と組の溜め。継ぐ側が埋めるものはこのファイルの先頭の説明"""

    def _delivery_init(self, log_dir):
        """溜めの置き場所(log_dir の中。None = メモリだけ)とロック"""
        self.pool_path = os.path.join(log_dir, POOL_FILE) if log_dir else None   # ライブの切り抜きの組の溜め(None = メモリだけ)
        self._pool_lock = threading.RLock()   # 溜めの読み書きと組で届ける間(これを持ったまま self.cv を取ってよい。逆に self.cv を持ったまま取らない)
        self._pools = None                    # {溜めの鍵: {rid, title, deliverDir, batch, meta, packs, delivered, marks, created, updated}}(初めて使うときに読む)

    def _deliver_batch_limits(self):
        """n 本ごとに組にする数の (既定, 下限, 上限)。継ぐ側(AutoRunner)がホームの設定の既定と範囲で埋める"""
        raise NotImplementedError("継ぐ側が _deliver_batch_limits を埋める")

    def _remember_delivered(self, clip_path, zip_name):
        """届けた切り抜きを案件の一覧に残す。継ぐ側(AutoRunner)が埋める"""
        raise NotImplementedError("継ぐ側が _remember_delivered を埋める")

    def _after_pack(self, run, st, prefix):
        """① 全自動: パックが n 本たまるごとに届ける(全部を待たない)"""
        if run.deliver_dir and "deliver" in run_mod.MODE_STEPS[run.mode]:
            self._deliver_pending(run, st, prefix, final=False)

    # 依頼の動画(mode file) -------------------------------------
    def _file_analyze(self, run, st):
        """依頼 ③: 友人の動画をスタジオに入れて盛り上がりの解析まで(切り抜く所は人が決める)"""
        if not os.path.isfile(run.source_path):
            raise run_mod.StepError("依頼の動画が見つかりません(移動・削除した可能性があります)")
        self._analyze_item(run, st, {"kind": "file", "path": run.source_path, "title": run.title}, None)
        st["detail"] += "。切り抜く所はスタジオで決めてください"
        return None

    def _file_deliver(self, run, st):
        found = self.find_pack(run.source_path)
        return self._deliver(run, st, list(run.packs) + ([found["dir"]] if found else []))

    def _step_deliver(self, run, st, v):
        dirs = list(run.packs)
        for m in self._clips(v, run):
            found = self.find_pack(m["path"])
            if found:
                dirs.append(found["dir"])
        return self._deliver(run, st, dirs)

    @staticmethod
    def _deliver_name(run, title):
        """出力 に置くものの名前(拡張子なし): <依頼 id>__<題>(依頼でない実行は実行の id)"""
        return deliver_mod.delivery_name(run.request_id or run.id, title)

    def _deliver(self, run, st, dirs):
        """① 全自動の届ける段: この実行のパック(前からあったものも)のうち、まだ届けていない分を全部 Dropbox の 出力 へ置く
        (友人のアプリの「受け取る」に出る。n 本ごとのまとめ方は _deliver_pending)"""
        dirs = [d for d in dict.fromkeys(os.path.normpath(x) for x in dirs if x) if os.path.isdir(d)]
        if not run.deliver_dir:
            st["state"], st["detail"] = "skip", "届け先がありません"
            return None
        if not dirs:
            st["state"], st["detail"] = "skip", "届けるパックがありません"
            return None
        if run.pool and self._batch_size(run) > 1:   # ライブの切り抜き: 実行をまたいで溜めに預け、n 本たまったら組で届ける(1 本ずつのときは今までどおり)
            return self._pool_add(run, st, dirs)
        for d in dirs:
            if d not in run.packs:
                run.packs.append(d)   # 前からあったパックも、この実行の並び(1 本目・2 本目…)に入れて同じ数え方で届ける
        self._deliver_pending(run, st, "", final=True)
        st["detail"] = "%d 本のパックを Dropbox の 出力 に置きました(字幕は校正前)" % len(run.delivered)
        return None

    def _batch_size(self, run):
        """n 本ごとに組にして届ける。友人の依頼が指定していればそれ(run.deliver_batch。2-16)、無ければホームの設定 intake.deliverBatch(既定と範囲は継ぐ側の _deliver_batch_limits = 入口の prefs.py。1 = 1 本ずつ)"""
        if run.deliver_batch:
            return run.deliver_batch
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
        """n 本のパックを組にして 出力 へ(docs/spec/friend-intake.md の 2-16): ① 組のまとめ動画 <依頼 id>__<題> 1-5.preview.mp4(2-13 の中身のまま)→
        ② 1 本ずつの zip(_deliver_one と同じ <依頼 id>__<パックの題>.zip。まとめ動画は組のものを使うので付けない)→ ③ 最後に <同じ名前>.group.json(zip の名前・何本目・
        まとめ動画の中の開始秒)。友人のアプリ(2.8.0)はまとめ動画を見てから 1 本ずつ受け取る・要らないを選べる。古いアプリは 1 本ずつの zip として受け取れる。
        まとめ動画を作れなくても(ffmpeg が無い・動画が壊れている)zip と一覧は届ける。届けた記録(deliveries.jsonl)は zip ごと"""
        first, last = run.packs.index(batch[0]) + 1, run.packs.index(batch[-1]) + 1
        rng = "%d-%d" % (first, last)
        name = self._deliver_name(run, "%s %s" % (run.title or "pack", rng))
        st["detail"] = prefix + "まとめ動画を作っています(%d 本)" % len(batch)

        def check():
            self._check(run)
        preview = deliver_mod.batch_preview(batch, check=check, log=self.log)   # 作れなければ None
        seconds = deliver_mod.clip_seconds(batch)
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
                    titles.append(deliver_mod.pack_title(d))
                    secs.append(seconds[i])
            deliver_mod.write_group_json(json_path, run.title or "pack", rng, placed[0], deliver_mod.group_members(zips, titles, secs))

    def _mark_delivered(self, run, dirs):
        """届けたパックを run.delivered に足して、すぐ残す(段の途中で起動し直しても、同じパックを二度置かない。M5)"""
        run.delivered.extend(dirs)
        self._save_active()

    def _record_delivery(self, run, zip_path, dirs):
        """届けた zip の中身(パックのフォルダ・切り抜きの動画・スタジオのマーク)を logs/deliveries.jsonl に残す(友人の「要らない」が来たときに引く)"""
        if self.log_path:
            friend_feedback.record_delivery(os.path.dirname(self.log_path), zip_path, run, dirs, run.pack_marks)
        for d in dirs:   # ライブの自動の切り抜きなら、案件の一覧に「届けた」を残す(二重に届けない。live.autoDeliver・友人の依頼)
            path = (run.pack_marks.get(d) or {}).get("path") or ""
            try:
                if path:
                    self._remember_delivered(path, os.path.basename(zip_path))
            except Exception as e:   # noqa: BLE001  (記録が残せなくても届けたことは変わらない)
                self.log("まとめて実行: 届けた印を案件に残せませんでした(%s)" % (str(e)[:120] or e.__class__.__name__))

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
            deliver_mod.remove_quiet(placed[0])
            if isinstance(e, OSError):
                raise self._place_error(e)
            raise
        finally:
            deliver_mod.remove_quiet(preview)

    def _deliver_rest_quietly(self, run):
        """止まった実行に、まとめて届ける前のパック(n 本に満たず手元に残っていた分)があれば届ける。届けられなくても失敗の知らせは置く"""
        if "deliver" not in run_mod.MODE_STEPS.get(run.mode, ()):
            return
        try:
            self._deliver_pending(run, {}, "", final=True)
        except Exception as e:   # noqa: BLE001  (届け残しが置けなくても止まった知らせは出す)
            self.log("まとめて実行: 止まった実行のパックを届けられませんでした(%s)" % (str(e)[:120] or e.__class__.__name__))

    def _deliver_one(self, run, d, with_preview=True):
        """1本のパックのフォルダを zip(<依頼 id>__<パックの題>.zip)にして 出力 へ置く(作り方は deliver.py。「編集」の「友人へ届ける」と同じ)。
        with_preview: その切り抜きだけのまとめ動画 <同じ名前>.preview.mp4 を zip より先に隣へ置く(2-16。友人は 1 本でも見てから選べる。組の中では組のものを使うので付けない)。
        d は run.packs の書き方のまま(届けた印 run.delivered と同じ文字列で比べる。run.packs に入れるときにそろえてある)。-> 置いた zip のパス(届け済みなら None)"""
        if d in run.delivered or not os.path.isdir(d):
            return None
        name = self._deliver_name(run, deliver_mod.pack_title(d) or run.title or "pack")
        preview = deliver_mod.batch_preview([d], check=lambda: self._check(run), log=self.log) if with_preview else None
        with self._placing(preview) as placed:   # zip が置けなかったら、先に置いたまとめ動画も残さない
            os.makedirs(run.deliver_dir, exist_ok=True)
            dest = deliver_mod.unique_zip(run.deliver_dir, name)
            if preview:
                placed[0] = deliver_mod.preview_path_for(dest)   # place_preview の途中で止まっても書きかけを残さないように先に控える
                deliver_mod.place_preview(preview, dest)
            deliver_mod.zip_packs([d], run.deliver_dir, name, check=lambda: self._check(run), dest=dest)
            self._mark_delivered(run, [d])
            self._record_delivery(run, dest, [d])
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
                                   "packs": [], "delivered": [], "marks": {}, "created": now}
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
        """溜めの残りを届ける見回り(入口の src/home/live.py が呼ぶ)。is_done(meta) = その録画・その段がもう切り抜きを作らないか
        (録画が終わった・書き出しの途中が無い)。届けるのは: is_done が真で、その溜めに預ける実行が待ち・実行中に無く、最後に預けてから POOL_IDLE_SEC たったとき、
        または溜めを作ってから POOL_MAX_AGE たったとき。-> 届けた本数の合計"""
        now = self.clock() if now is None else now
        with self._pool_lock:
            keys = list(self._pools_load())
        total = 0
        for key in keys:
            with self._pool_lock:
                p = self._pools_load().get(key)
                if not p:
                    continue
                if not any(d not in p["delivered"] and os.path.isdir(d) for d in p["packs"]):
                    self._pools_load().pop(key, None)
                    self._pools_save()
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

    def _deliver_failure(self, run):
        """① 全自動が止まったとき、友人のアプリの「受け取る」に理由を出す(<依頼 id>__<題名>.失敗.txt)"""
        try:
            os.makedirs(run.deliver_dir, exist_ok=True)
            name = self._deliver_name(run, run.title or "依頼") + ".失敗.txt"
            text = "自動の処理が止まりました。\r\n理由: %s\r\n送り先の人が確かめます。" % (run.error or run.message)
            with open(os.path.join(run.deliver_dir, name), "w", encoding="utf-8-sig", newline="") as f:
                f.write(text + "\r\n")
        except OSError:
            pass
