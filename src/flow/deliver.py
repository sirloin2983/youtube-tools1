"""② パックを友人へ届ける(Dropbox の見張るフォルダの 出力\\ に zip で置く。友人のアプリの「受け取る」が読む)。
notes:docs/spec/friend.md の 2-7。ds1(要件 1-5「届ける段と溜めは ② へ」)。
確認用の動画(ffmpeg)は ① pipeline/pack/preview。ここは ytt と ① と ② だけを読む(友人の PC には ③ が無い)。

届く物の形(notes:plan/done/f1-friend-requirements.md の C-3・C-6。パックは 1 本ずつ):
  出力\\<頭>__<パックの題>.zip + 隣に同じ名前の .preview.mp4(480p・字幕なし)と .meta.json(依頼の分にも必ず)。置く順 = 確認用の動画 → meta → zip
- deliver_one: 1 本を届ける(確認用の動画 → meta → zip → 届けた記録 deliveries.jsonl)。まとめて実行の届ける段(同じフォルダの delivery.py の _deliver_one)と
  手で届ける(Deliveries = 「編集」の「友人へ届ける」・案件の「採用(友人へ届ける)」)が同じこれを使う(ユーザー決定 Q16)
- zip_packs: パックを zip に(中は <題>_pack/ が並ぶ)
- place_preview: ① の確認用の動画を zip の隣に <zip の名前>.preview.mp4 で置く
- 名前: zip は <依頼 id>__<題>(delivery_name)。同じ名前があれば末尾に 4 文字足す(unique_zip)
- 出どころ(D-SEND 2-7。notes:plan/done/d-send-requirements.md): 届けた記録の origin は request(友人の依頼)・auto(自分の配信から自動で)・manual(手で届ける)。
  友人に見せる出どころ(face_origin)は request か auto(手で届けるも auto = 札「自動で届いた」)。.meta.json の origin(meta_doc の欄の説明)
- Deliveries: 手で「友人へ届ける」(画面の api/ytt/deliver)の裏の仕事。数 GB の zip は時間がかかるので、画面は状態を聞き直す
送れるのは cut2resolve が作ったパックのフォルダだけ(manage.cases.txindex.is_pack_dir。画面から任意のフォルダを Dropbox へ出させない)。
zip は動画を圧縮しない(ZIP_STORED)ので CPU はほとんど使わない → 重い処理の枠(jobs.SLOTS)は通さない(文字起こしの後ろで何時間も待たせないため)。
同時に作るのは1本だけ(ディスクの取り合いを避ける)。
"""
import datetime
import os
import re
import shutil
import threading
import time
import types
import uuid
import zipfile

from pipeline.pack import preview as _preview   # ① 確認用の動画・パックの中の切り抜きの動画と題・長さ
from ytt import datadir as _datadir, fsio, tools, version as _version
from . import deliveries   # 届けた記録 deliveries.jsonl の書く口(友人の「要らない」が来たときに引く)

OUT_DIR = "出力"   # 見張るフォルダの 出力\ = 友人のアプリの「受け取る」が読む(③ 受付 human/friend/intake もここを読む = 名前の 1 か所)
BAD_NAME_CHARS = re.compile(r'[\\/:*?"<>|\x00-\x1f]')   # ファイル名に使えない文字(_ に置き換える。受付 intake もここを読む)
VIDEO_EXT = (".mp4", ".mov", ".mkv", ".webm", ".m4v", ".wav", ".m4a")   # 圧縮しても小さくならない物は ZIP_STORED
PREVIEW_SUFFIX = ".preview.mp4"        # zip の隣の名前(<zip の名前>.preview.mp4。友人のアプリが先にこれだけ取ってきて見る。zip の中には入れない)
META_SUFFIX = ".meta.json"             # 1 本のパックのメタ(<zip の名前>.meta.json。友人のアプリの OutputFolder.MetaSuffix と同じ)
BAD_CHARS = BAD_NAME_CHARS   # 同じ物の別名(受付と同じ決まり)
KEEP_JOBS = 20
RID_RE = re.compile(r"^\d{8}-\d{6}-[0-9a-f]{6}\Z")   # 友人のアプリの依頼の id の形(request_id と同じ)
SAME_SHARE = 0.8                       # 元の依頼 id で手で届けるとき、同じ依頼・同じ配信でこの割合以上重なる物があれば置かない(問題 2・10-25)


def outbox_ok(out_dir):
    """出力 の親(受付の Dropbox のフォルダ)があるか(無いのに 出力 を作ると、Dropbox でない所に置いてしまう。ネットワーク上には置かない)。
    まとめて実行の届ける段(flow/delivery)も手の「採用」(Deliveries.start)もここを通す"""
    parent = os.path.dirname(os.path.normpath(out_dir or ""))
    return bool(parent) and not fsio.is_network_path(parent) and os.path.isdir(parent)


def safe_name(s, limit=180):
    return BAD_CHARS.sub("_", str(s or ""))[:limit]


def request_id(now=None):
    """友人のアプリの依頼の id と同じ形(YYYYMMDD-HHMMSS-xxxxxx)。アプリはこの形の先頭を除いた部分を題名に出す"""
    return time.strftime("%Y%m%d-%H%M%S", time.localtime(now)) + "-" + uuid.uuid4().hex[:6]


def delivery_name(rid, title):
    """出力 フォルダに置くものの名前(拡張子なし): <依頼 id>__<題>(友人のアプリはこの形から依頼 id と題を読む)"""
    return safe_name("%s__%s" % (rid, title))


def face_origin(origin):
    """届けた記録の出どころ(request・auto・manual)-> 友人に見せる出どころ(request か auto。手で届けるも auto = 札「依頼なし」。D-SEND 2-7・2-8)"""
    return "request" if origin in (None, "", "request") else "auto"


def _local_iso(when=None):
    """その時刻の地方時 + UTC とのずれ(2026-10-09T12:00:00+09:00 の形)"""
    return datetime.datetime.fromtimestamp(time.time() if when is None else when).astimezone().isoformat(timespec="seconds")


def meta_path_for(zip_path):
    """zip の隣に置く出どころの印の名前(<zip の名前(.zip 抜き)>.meta.json)"""
    return os.path.splitext(zip_path)[0] + META_SUFFIX


TEXT_MAX = 300   # meta の文字の欄(題・配信のタイトル・配信者)の長さの上限(.meta.json は 16KB 未満)


def _text(v):
    return str(v or "")[:TEXT_MAX] if isinstance(v, str) else ""


def meta_doc(zip_path, origin, preview=None, title="", video_id="", mark_id="", stream_title="", streamer="", seconds=None, now=None, overlap=""):
    """届く物の .meta.json の中身:
    {"v":1, "kind":"clip", "origin": request|auto, "sentAt", "requestId"(zip の名前の頭), "zip", "preview"(名前か None), "title"(パックの題),
     "videoId", "markId", "streamTitle", "streamer"(分からなければ ""), "seconds"(切り抜きの長さ。分からなければ None),
     "madeOn"(user = 作る人の PC・friend = 友人の PC。made_on), "appVersion"(作った版)}(madeOn・appVersion は問題点 10・10-25。
     こちらで後追い・引き継ぎで作った物は友人の PC の物と中身が違いうる = 見分けるため)。
    overlap = 前に届けた区間とのかぶりの 1 行(flow/deliveries.overlap_note。あれば "overlapNote")
    #番号(配信ごとの通し番号)は友人のアプリが付ける(友人の PC で処理した物も同じ受信箱に入るため)"""
    name = os.path.basename(zip_path)
    ok = isinstance(seconds, (int, float)) and not isinstance(seconds, bool) and seconds > 0
    return {"v": 1, "kind": "clip", "origin": origin, "sentAt": _local_iso(now), "requestId": name.split("__", 1)[0] if "__" in name else "",
            "zip": name, "preview": os.path.basename(preview) if preview else None, "title": _text(title), "videoId": _text(video_id),
            "markId": _text(mark_id), "streamTitle": _text(stream_title), "streamer": _text(streamer), "seconds": round(float(seconds), 2) if ok else None,
            "madeOn": made_on(), "appVersion": _version.VERSION,
            **({"overlapNote": _text(overlap)} if isinstance(overlap, str) and overlap else {})}


def made_on(env=None):
    """この PC は作る人の PC(user)か友人の PC(friend)か = ホームの設定 <作業データ>/app/prefs.json の intake.folder が空でなければ user
    (flow/learning.maker_pc と同じ条件。読めなければ friend)"""
    d = fsio.read_json_or(os.path.join(_datadir.locate("app", env=env), "prefs.json"), None, kind=dict)
    intake = d.get("intake") if d else None
    folder = intake.get("folder") if isinstance(intake, dict) else None
    return "user" if isinstance(folder, str) and folder.strip() else "friend"


def write_meta_json(path, doc):
    """届く物の .meta.json を書く(meta_doc の形)。UTF-8・BOM なし・1 行・原子的に(一時ファイルは友人のアプリの一覧に出ない)。-> 書いた中身"""
    fsio.write_json(path, doc, indent=None)
    return doc


def unique_zip(out_dir, name):
    """out_dir/<name>.zip の、まだ無いパス(同じ名前があれば末尾に 4 文字足す)"""
    dest = os.path.join(out_dir, name + ".zip")
    if os.path.exists(dest):
        dest = os.path.join(out_dir, "%s-%s.zip" % (name, uuid.uuid4().hex[:4]))
    return dest


def zip_packs(dirs, out_dir, name, check=None, progress=None, dest=None):
    """n 本のパックのフォルダを 1 つの zip に(それぞれ <題>_pack/ の下に並ぶ)。同じ名前があれば末尾に 4 文字足す。
    dest を渡せばその名前に置く(先に unique_zip で決めて、隣に置く確認用の動画の名前をそろえるため)。-> 置いたパス。
    check(): 止めるなら例外を投げる(まとめて実行の中止)。progress(済んだバイト, 全体のバイト)。
    zip は Dropbox の外(最初のパックの隣)で作ってから移す。1980 年より前の更新時刻のファイルも入れる(strict_timestamps=False = 1980 年にそろう)"""
    dirs = [os.path.normpath(d) for d in dirs]
    os.makedirs(out_dir, exist_ok=True)
    files = []   # (ファイル, zip の中の名前, 大きさ)
    for d in dirs:
        top = os.path.basename(d)
        for base, _dirs, fs in os.walk(d):
            for f in sorted(fs):
                p = os.path.join(base, f)
                try:
                    files.append((p, os.path.join(top, os.path.relpath(p, d)), os.path.getsize(p)))
                except OSError:
                    pass
    total, done = sum(n for _p, _a, n in files) or 1, 0
    tmp = _preview.scratch_path(dirs[0], "", ".zip")
    try:
        with zipfile.ZipFile(tmp, "w", allowZip64=True, strict_timestamps=False) as z:
            for p, arc, n in files:
                if check:
                    check()
                video = os.path.splitext(p)[1].lower() in VIDEO_EXT
                z.write(p, arc, compress_type=zipfile.ZIP_STORED if video else zipfile.ZIP_DEFLATED)
                done += n
                if progress:
                    progress(done, total)
        dest = dest or unique_zip(out_dir, name)
        shutil.move(tmp, dest)
        return dest
    finally:
        _preview.remove_quiet(tmp)


def preview_path_for(zip_path):
    """zip の隣に置く確認用の動画の名前(<zip の名前>.preview.mp4。友人のアプリは名前で zip と組にする)"""
    return os.path.splitext(zip_path)[0] + PREVIEW_SUFFIX


def place_preview(preview, zip_path):
    """確認用の動画を zip の隣に <zip の名前>.preview.mp4 で写す(元の一時ファイルは呼ぶ側が消す)。-> 置いたパス。
    zip より先に置く(友人のアプリは zip が見えたら、確認用の動画もそろっているとみなす)"""
    dest = preview_path_for(zip_path)
    shutil.copyfile(preview, dest)
    return dest


def deliver_one(d, out_dir, name, log_dir=None, run=None, marks=None, check=None, progress=None, log=None, origin="request"):
    """1 本のパックを友人へ届ける(notes:docs/spec/friend.md の 2-7。まとめて実行の 1 本ずつ・手で届ける の 1 か所):
    ① その切り抜きの確認用の動画 <zip の名前>.preview.mp4 を zip より先に隣へ(480p・字幕なし。作れなければ無し = meta の preview が None)
    ② メタ <zip の名前>.meta.json を zip より先に隣へ(依頼の分にも必ず。meta_doc の形)
    ③ zip <name>.zip(同じ名前があれば末尾に 4 文字)④ 届けた記録 deliveries.jsonl に 1 行(log_dir と run があるとき。友人の判断が引く。書けなくても止めない)。
    run = request_id・id・video_id・title(・streamer・stream_title)を持つ物(まとめて実行の実行か、手で届けるときの代わり)。
    配信のタイトルは run.stream_title があればそれ・無ければ run.title。marks = {パックのフォルダ: {"path", "markId"}}。
    origin = 届けた記録の出どころ(request・auto・manual)。
    -> 置いた zip のパス。途中で失敗したら置いた確認用の動画・meta を消して例外をそのまま上げる(一時の確認用の動画はいつも消す)"""
    preview = _preview.clip_preview(d, check=check, log=log)
    placed, meta = None, None
    mark = (marks or {}).get(d) if isinstance((marks or {}).get(d), dict) else {}
    stream_title = getattr(run, "stream_title", None)
    try:
        os.makedirs(out_dir, exist_ok=True)
        dest = unique_zip(out_dir, name)
        if preview:
            placed = preview_path_for(dest)   # place_preview の途中で止まっても書きかけを残さないように先に控える
            place_preview(preview, dest)
        meta = meta_path_for(dest)
        write_meta_json(meta, meta_doc(dest, face_origin(origin), placed, _preview.pack_title(d), getattr(run, "video_id", None) or "",
                                       str(mark.get("markId") or ""), getattr(run, "title", "") if stream_title is None else stream_title,
                                       getattr(run, "streamer", None) or "", _preview.pack_seconds(d),
                                       overlap=mark.get("overlap") or ""))
        zip_packs([d], out_dir, name, check=check, progress=progress, dest=dest)
    except BaseException:
        _preview.remove_quiet(placed)
        _preview.remove_quiet(meta)
        raise
    finally:
        _preview.remove_quiet(preview)
    if log_dir and run is not None:
        deliveries.record(log_dir, dest, run, [d], marks, origin or "request")
    return dest


class Deliveries:
    """手で「友人へ届ける」の仕事。folder(): 見張るフォルダ(入口の Intake.folder)。is_pack(dir): cut2resolve が作ったパックか。
    log_dir: 届けた記録 deliveries.jsonl を書くフォルダ(入口の logs。None = 書かない)。作り方はまとめて実行と同じ deliver_one(確認用の動画 + meta + zip + 記録)"""

    def __init__(self, folder, is_pack, log=None, clock=time.time, log_dir=None):
        self.folder, self.is_pack, self.log, self.clock = folder, is_pack, log or (lambda m: None), clock
        self.log_dir = log_dir
        self.lock = threading.Lock()
        self.jobs = {}
        self.busy = threading.Lock()   # 同時に作るのは1本
        self._finished = {}            # 仕事の id -> 終わった時刻(ms)。掲示板が読む(status には出さない)

    def start(self, d, title="", on_done=None, clip=None, rid=None):
        """-> 仕事の状態。断るときは ValueError(画面にそのまま出す文)。
        rid: 元の依頼 id(後追い・引き継ぎ・急ぎの届けなど、元の依頼がある届けは必ず渡す = 友人の行に結びつく・出どころ request)。
        無ければ今どおり新しい id(依頼なしで届ける = manual)。渡したときは、同じ id・同じ配信で区間が SAME_SHARE 以上重なる物が
        届けた記録か 出力\\ にもうあれば断る(二重に届けない。10-24 の二重の再発防止)
        on_done(仕事の状態): 置き終えたときに 1 回だけ呼ぶ(今の呼び手は使わない。案件の「届けた」は届けた記録から引く = MARKS-3)。
        clip: 届けた記録に残す切り抜き {"path", "markId", "videoId"}(分かるとき。友人の「要らない」で切り抜きの動画も片付けるため。無ければパックだけ)"""
        if not isinstance(d, str) or not d.strip() or len(d) > 1024:
            raise ValueError("パックのフォルダがありません")
        d = os.path.normpath(d.strip())
        if not self.is_pack(d):
            raise ValueError("cut2resolve が作ったパックのフォルダではありません(作り直してから届けてください)")
        folder = self.folder() or ""
        if not folder:
            raise ValueError("友人からの依頼の受付で、Dropbox のフォルダが決まっていません(ホームの設定で指定してください)")
        out_dir = os.path.join(folder, OUT_DIR)
        if not outbox_ok(out_dir):
            raise ValueError("Dropbox のフォルダが見つかりません: %s" % folder)
        title = (title.strip() if isinstance(title, str) else "") or _preview.pack_title(d) or "pack"
        clip = clip if isinstance(clip, dict) else {}
        if rid is not None and not (isinstance(rid, str) and RID_RE.match(rid)):
            raise ValueError("元の依頼 id の形が違います(YYYYMMDD-HHMMSS-6 文字)")
        given = bool(rid)
        if given:
            self._refuse_same(rid, out_dir, clip)
        rid = rid or request_id(self.clock())
        name = delivery_name(rid, title)
        job = {"id": uuid.uuid4().hex[:10], "state": "running", "message": "zip にしています", "progress": 0.0,
               "dir": d, "name": name + ".zip", "error": "", "startedAt": int(self.clock() * 1000)}
        # 届けた記録の行の「実行」の代わり(依頼 id = zip の名前の頭・実行 id = 仕事の id)。出どころは元の依頼があれば request・無ければ manual
        # (友人には「依頼なし」= D-SEND 2-8)
        run = types.SimpleNamespace(request_id=rid, id="dl" + job["id"], video_id=str(clip.get("videoId") or ""), title=title,
                                    deliver_origin="request" if given else "manual",
                                    stream_title="", streamer="")   # 配信のタイトル・配信者は手で届けるときは分からない(友人のアプリが videoId から引く)
        marks = {d: {"path": str(clip.get("path") or ""), "markId": str(clip.get("markId") or "")}}
        with self.lock:
            if self._running_locked(d):
                raise ValueError("このパックは今、届けているところです")
            self.jobs[job["id"]] = job
            for k in [k for k, j in self.jobs.items() if j["state"] != "running"][:-KEEP_JOBS]:
                del self.jobs[k]
                self._finished.pop(k, None)
        threading.Thread(target=self._run, args=(job, out_dir, on_done, run, marks), daemon=True, name="deliver").start()
        return dict(job)

    def _refuse_same(self, rid, out_dir, clip):
        """元の依頼 id で届ける前の二重の守り: 届けた記録に同じ id・同じ配信で区間が SAME_SHARE 以上重なる物、出力\\ に同じ id・同じ配信・
        同じマークの .meta.json があれば ValueError"""
        vid, path, mark = str(clip.get("videoId") or ""), str(clip.get("path") or ""), str(clip.get("markId") or "")
        rng = deliveries.clip_range(path) if path else None
        hit = deliveries.overlaps(self.log_dir, vid, rng, request_id=rid, share=SAME_SHARE) if self.log_dir else []
        if hit:
            raise ValueError("同じ依頼に、区間が重なる切り抜き(%d 割)をもう届けてあります(%s)" % (round(hit[-1]["share"] * 10), hit[-1]["zip"]))
        try:
            names = [n for n in os.listdir(out_dir) if n.startswith(rid + "__") and n.endswith(META_SUFFIX)]
        except OSError:
            names = []
        for n in names:
            m = fsio.read_json_or(os.path.join(out_dir, n), None) or {}
            if vid and m.get("videoId") == vid and (not mark or m.get("markId") == mark):
                raise ValueError("同じ依頼・同じ切り抜きが 出力 にもう置いてあります(%s)" % n[:-len(META_SUFFIX)])

    def running(self, d):
        """そのパックのフォルダを今 zip にしているか(届けている途中のパックを「要らない」で動かさない。src/manage/cases/cases.py)"""
        with self.lock:
            return self._running_locked(d)

    def _running_locked(self, d):
        """running の中身(self.lock を持っている間に呼ぶ)。パスは大文字・小文字と区切りをそろえて比べる"""
        d = os.path.normcase(os.path.normpath(str(d or "")))
        return any(j["state"] == "running" and os.path.normcase(j["dir"]) == d for j in self.jobs.values())

    def _run(self, job, out_dir, on_done=None, run=None, marks=None):
        def prog(done, total):
            job["message"] = "zip にしています"
            job["progress"] = round(done / total, 3)
        if not self.busy.acquire(blocking=False):
            job["message"] = "前のパックを届け終わるのを待っています"
            self.busy.acquire()
        try:
            job["message"] = "確認用の動画を作っています"
            dest = deliver_one(job["dir"], out_dir, job["name"][:-4], log_dir=self.log_dir, run=run, marks=marks, progress=prog, log=self.log,
                               origin=getattr(run, "deliver_origin", None) or "manual")
            done = dict(state="done", progress=1.0, name=os.path.basename(dest),
                        message="Dropbox の 出力 に置きました。同期が終わると友人のアプリの「受け取る」に出ます")
            self.log("友人へ届ける: %s を 出力 に置きました" % os.path.basename(dest))
            if on_done:   # 記録してから done にする(画面は done を見てすぐ一覧を読み直すので、先に done にすると「届けた」がまだ無い一覧を読む)
                try:
                    on_done(dict(job, **done))
                except Exception as e:   # 記録できなくても、届けたことは変わらない(ログにだけ残す)
                    self.log("友人へ届ける: 届けたことを記録できませんでした: %r" % (e,))
            job.update(done)
        except Exception as e:   # noqa: BLE001  (zip にできないファイルなど何でも error にする。running のまま残すと同じパックを二度と届けられない)
            why = tools.why(e) if isinstance(e, OSError) else "%s: %s" % (e.__class__.__name__, str(e)[:200])
            job.update(state="error", error=why, message="届けられませんでした: %s" % why)
            self.log("友人へ届ける: 失敗 %s (%s)" % (job["dir"], job["message"]))
        finally:
            self.busy.release()
            with self.lock:
                self._finished[job["id"]] = int(self.clock() * 1000)

    # ---- 掲示板(RS8 の ② の口 S2。flow/board.py。頭 dl・id = dl:<仕事の id>。入口が board を渡して 1 回呼ぶ。取り消し・やり直しは無い) ----
    def attach_board(self, board):
        board.register("dl", source=self.board_jobs)

    def board_jobs(self):
        """掲示板の引く形: 仕事(入れた順)-> [Job の辞書]。target.path = パックのフォルダ(案件の根は掲示板の case_hook が引く)"""
        with self.lock:
            rows = [(dict(j), self._finished.get(j["id"])) for j in self.jobs.values()]
        out = []
        for j, fin in rows:
            state = j["state"] if j["state"] in ("running", "done", "error") else "error"
            out.append({"id": "dl:" + j["id"], "kind": "deliver", "target": {"path": j["dir"]}, "title": j["name"], "state": state,
                        "phase": j["message"], "progress": j["progress"], "createdAt": j["startedAt"], "startedAt": j["startedAt"], "finishedAt": fin,
                        "error": {"code": None, "text": j["message"], "detail": j["error"] or None} if state == "error" else None})
        return out

    def status(self, job_id):
        with self.lock:
            j = self.jobs.get(job_id) if isinstance(job_id, str) else None
            return dict(j) if j else None
