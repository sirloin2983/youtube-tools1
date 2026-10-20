"""解析の材料を取ってくる仕事(音声のダウンロード・チャットのリプレイの取得と先読み・コメント欄・動画の付加情報)と、そのキャッシュの置き場と掃除。
点数の計算は excite.py・音量は levels.py・ジョブの流れは analyze.py。動きは analyze.py にあった頃と同じ(OPT2 で分けた)。
ここの関数は ytt/jobs.Ctl(進み具合・取り消し・合図 skipChat)と、実行ごとの辞書 run({"chat", "meta"}。analyze.run が作る)を受ける(OPT2 の J1)。
子プロセスは Ctl の見張り(run_progress)が止める。チャット・付加情報の取得は、自分だけ止められる小さな Ctl(_Stop)を使う。
"""
import glob
import json
import os
import re
import shutil
import threading
import time

from ytt import yturl as _yturl
from ytt import apikey as _key, fsio as _fsio, procs as _procs, studio_env as _env, tools as _tools, ytapi as _ytapi
from ytt.jobs import Ctl
from ytt.errors import ApiError, Cancelled
from ytt.textutil import redact, tail_reason

CHAT_CACHE_KEEP = 30
# チャットのキャッシュの合計の上限(件数だけでは容量が膨らむため)。既定 1GB。環境変数 STUDIO_CHAT_CACHE_MB(MB)で変えられる
CHAT_CACHE_MAX_BYTES = 1024 ** 3
AUDIO_DL_IDLE = 600      # 音声のダウンロードで、この秒数まったく出力がなければ中止
MAX_CHAT_BYTES = 400 * 1024 * 1024
META_TTL = 24 * 3600     # 動画の付加情報の再取得までの秒数(再解析のたびに取り直さない)
META_KEEP = 300
META_TIMEOUT = 90


def work_dir():
    return _env.p("work")


def chat_cache_dir():
    return _env.p("cache", "chat")


# ---------- 素材の取得(YouTube) ----------
class _Stop:
    """取り消し(親の Ctl)か、自分の stop が立つと止まる Ctl の代わり(run_capture に渡す)。skip=True なら親の合図 skipChat でも止まる"""

    def __init__(self, ctl, stop, skip=False):
        self.ctl, self.stop, self.skip = ctl, stop, skip

    def is_cancelled(self):
        return self.ctl.is_cancelled() or self.stop.is_set() or (self.skip and self.ctl.flag("skipChat"))


def download_audio(ctl, vid, wdir):
    if _env.fake():
        return _env.fake_media()
    yt = _env.find_tool("yt-dlp")
    if not yt:
        raise ApiError("no_ytdlp", "yt-dlp が見つかりません(README の準備手順を確認してください)")
    cmd = [yt, "--encoding", "utf-8"] + _tools.ytdlp_auth_args() + ["--no-playlist", "--no-warnings", "--newline", "--ffmpeg-location", _env.find_tool("ffmpeg") or "", "-f", "ba/b", "-o", _yturl.ytdlp_out(wdir, "audio.%(ext)s"),
           "--", _yturl.watch_url(vid)]

    def on(line):
        m = re.search(r"\[download\]\s+([\d.]+)%", line)
        if m:
            ctl.report(0.02 + 0.10 * float(m.group(1)) / 100)
    rc, err = _procs.run_capture(ctl, cmd, on, idle_timeout=AUDIO_DL_IDLE, what="音声の取得")
    files = [f for f in glob.glob(glob.escape(os.path.join(wdir, "audio")) + ".*") if not f.endswith((".part", ".ytdl", ".temp"))]
    if rc != 0 or not files:
        raise ApiError("download", "音声を取得できませんでした: " + (tail_reason(err) or "不明なエラー"), 502)
    return files[0]


def chat_cache_path(vid):
    return os.path.join(chat_cache_dir(), vid + ".live_chat.json")


def drop_chat_cache(vid):
    """取っておいたチャットを捨てる(件数が少なすぎて使えなかった = 配信の直後でリプレイがまだ揃っていないかもしれない。次の解析で取り直す)。
    消せなくても上げない(次の機会に)"""
    if not isinstance(vid, str) or not _yturl.VID_RE.match(vid):
        return False
    try:
        os.remove(chat_cache_path(vid))
        return True
    except OSError:
        return False


def _usable_chat(path):
    """取得済みのチャット(空でなく、大きすぎない)があるか"""
    return os.path.isfile(path) and 0 < os.path.getsize(path) <= MAX_CHAT_BYTES


def chat_cache_limit():
    """チャットのキャッシュの合計の上限(バイト)。環境変数 STUDIO_CHAT_CACHE_MB(1 以上の整数)があればそれ。"""
    try:
        mb = int(str(os.environ.get("STUDIO_CHAT_CACHE_MB") or "0").strip())
    except ValueError:
        mb = 0
    return mb * 1024 * 1024 if mb > 0 else CHAT_CACHE_MAX_BYTES


# 解析が使っているチャットのキャッシュ(動画ID → 数)。キャッシュを消すときはこれと先読み中(PREFETCH)の動画のものを飛ばす。
# 消す処理(prune_chat_cache)と使い始め(use_chat_cache)は同じロックを取る(「使っていないと確かめた直後に使い始めた」を消さない)
_chat_use_lock = threading.Lock()
_chat_in_use = {}


def use_chat_cache(vid, delta):
    """解析がその動画のチャットのキャッシュを使い始める(+1)・使い終える(-1)。"""
    with _chat_use_lock:
        n = _chat_in_use.get(vid, 0) + delta
        if n > 0:
            _chat_in_use[vid] = n
        else:
            _chat_in_use.pop(vid, None)


def prune_chat_cache(limit=None, keep=CHAT_CACHE_KEEP):
    """件数(keep)と合計の大きさ(limit。既定は chat_cache_limit())の両方に収まるまで、最後に使った時刻が古いものから消す。
    解析・先読みが使っている動画のものと、いちばん新しいもの(今入れたもの)は消さない。途中で止まった写し(*.tmp)も消す。消したバイト数を返す"""
    limit = chat_cache_limit() if limit is None else limit
    d = chat_cache_dir()
    freed = 0
    with _chat_use_lock:
        with _pf_lock:
            busy = set(_chat_in_use) | set(PREFETCH)
        files, tmps = [], []
        total, count = 0, 0   # 合計と件数は、使っている最中で飛ばしたものも含めて数える(消せないものの分も上限に入る)
        for p in glob.glob(os.path.join(glob.escape(d), "*.live_chat.json*")):   # フォルダは 1 回だけ読む
            name = os.path.basename(p)
            vid = name.split(".live_chat.json", 1)[0]
            try:
                st = os.stat(p)
            except OSError:
                continue
            if name.endswith(".live_chat.json"):
                total += st.st_size
                count += 1
                if vid not in busy:
                    files.append((st.st_mtime, st.st_size, p))
            elif name.endswith(".live_chat.json.tmp") and vid not in busy:
                tmps.append((st.st_size, p))
        for size, p in tmps:
            try:
                os.remove(p)
                freed += size
            except OSError:
                pass
        files.sort()
        newest = files[-1][2] if files else None
        for _mtime, size, p in files:
            if count <= keep and total <= limit:
                break
            if p == newest:
                break   # いちばん新しいものは残す(今入れたもの。1つで上限を超えていても)
            try:
                os.remove(p)
            except OSError:   # Windows で読み込み中などは消せない → 次の機会に
                continue
            total -= size
            count -= 1
            freed += size
    return freed


def download_chat(ctl, run, vid, wdir, timeout):
    """チャットのリプレイ(live_chat)。取れなければ (None, 理由)。
    完走したものは cache/chat/<動画ID> に残す(途中で打ち切ったものは残さない)。"""
    c = run["chat"]
    sub = _Stop(ctl, c.setdefault("stop", threading.Event()), skip=True)
    if _env.fake():
        p = _env.fake_file("CHAT")
        return (p, "") if p else (None, "疑似モード: チャットなし")
    cp = chat_cache_path(vid)
    if _usable_chat(cp):
        c["cached"] = True
        c["prefetched"] = vid in _pf_done
        _pf_done.discard(vid)
        os.utime(cp, None)
        return cp, ""
    if not run.get("prefetch"):
        with _pf_lock:
            pf = PREFETCH.get(vid)
        if pf:   # 先読みが同じ動画を取得中なら、もう1つ起動せず、その完了を待つ
            while not pf["done"].wait(0.5):
                if sub.is_cancelled():
                    cancel_prefetch(vid)
                    if ctl.is_cancelled():
                        raise Cancelled()
                    return None, "チャットは待たずに進めました"
                c["bytes"] = pf["run"]["chat"]["bytes"] if pf["run"].get("chat") else c["bytes"]
            if _usable_chat(cp):
                c["cached"] = c["prefetched"] = True
                return cp, ""
            return None, pf["why"] or "チャットのリプレイを取得できませんでした"
    yt = _env.find_tool("yt-dlp")
    if not yt:
        return None, "yt-dlp が見つからないため、チャットは使えません"
    cmd = [yt, "--encoding", "utf-8"] + _tools.ytdlp_auth_args() + ["--no-playlist", "--no-warnings", "--newline", "--skip-download", "--write-subs", "--sub-langs", "live_chat", "-o", _yturl.ytdlp_out(wdir, "chat.%(ext)s"), "--", _yturl.watch_url(vid)]
    stop = threading.Event()

    def watch():   # 出力ファイルの大きさを見せる(yt-dlp は進捗を出さないため、動いている目安になる)
        while not stop.wait(2):
            try:
                c["bytes"] = sum(os.path.getsize(f) for f in glob.glob(glob.escape(os.path.join(wdir, "chat")) + "*"))
            except OSError:
                pass
    threading.Thread(target=watch, daemon=True).start()
    t0 = time.time()
    try:
        rc, err = _procs.run_capture(sub, cmd, None, timeout=timeout)
    except Cancelled:
        if ctl.is_cancelled():
            raise
        return None, "チャットは待たずに進めました"   # skipChat か後始末の stop
    finally:
        stop.set()
    if ctl.flag("skipChat"):
        return None, "チャットは待たずに進めました"
    if timeout and time.time() - t0 >= timeout:
        return None, "チャットの取得が %d 分を超えたため、チャットは使っていません(設定で待ち時間を延ばせます)" % (timeout // 60)
    files = [f for f in glob.glob(glob.escape(os.path.join(wdir, "chat")) + "*.live_chat.json")]
    if not files:
        return None, "チャットのリプレイを取得できませんでした(チャットが無効・削除されている、または取得に失敗)" + ((": " + tail_reason(err)) if rc != 0 and tail_reason(err) else "")
    if os.path.getsize(files[0]) > MAX_CHAT_BYTES:
        return None, "チャットのファイルが大きすぎます"
    if rc == 0:
        try:
            os.makedirs(chat_cache_dir(), exist_ok=True)
            tmp = cp + ".tmp"
            shutil.copyfile(files[0], tmp)
            _fsio.replace_retry(tmp, cp)
            prune_chat_cache()
        except OSError:
            pass
    return files[0], ""


# ---------- チャットの先読み ----------
# チャットの取得は yt-dlp が順番に取るため速くできない。代わりに、バッチの「次の配信」のチャットを、今の配信の解析と並行して取っておく
# (取れたものは cache/chat に入り、その配信の番が来たときは待たずに使える)。同時に取るのは先読み1本まで(YouTube への負荷を増やしすぎない)。
PREFETCH_MAX = 1
_pf_lock = threading.Lock()
_pf_done = set()   # 先読みで取得できた動画ID(画面の文言用)
PREFETCH = {}   # 動画ID -> {"ctl", "run", "done": Event, "why", "path"}


def prefetch_chat(vid, timeout, on_done=None):
    """"started" / "full"(先読みの枠がいっぱい)/ "skip"(すでに取得済み・取得中、または使えない)。"""
    if _env.fake() or not isinstance(vid, str) or not _yturl.VID_RE.match(vid):   # ASCII の 11 文字だけ(全角の英字などは通さない)
        return "skip"
    with _pf_lock:
        if vid in PREFETCH:
            return "skip"
        if len(PREFETCH) >= PREFETCH_MAX:
            return "full"
        if _usable_chat(chat_cache_path(vid)):
            return "skip"
        if not _env.find_tool("yt-dlp"):
            return "skip"
        pctl = Ctl()
        prun = {"prefetch": True, "chat": {"state": "running", "t0": time.time(), "t1": None, "bytes": 0, "cached": False}}
        pf = {"ctl": pctl, "run": prun, "done": threading.Event(), "why": "", "path": None}
        PREFETCH[vid] = pf

    def work():
        wdir = os.path.join(work_dir(), "pf_" + vid)
        try:
            os.makedirs(wdir, exist_ok=True)
            pf["path"], pf["why"] = download_chat(pctl, prun, vid, wdir, timeout)
            if pf["path"] and os.path.isfile(chat_cache_path(vid)):
                _pf_done.add(vid)
        except Cancelled:
            pf["why"] = "中止"
        except Exception as e:
            pf["why"] = "チャットの先読みで予期しないエラー: " + redact(str(e))[:160]
        finally:
            shutil.rmtree(wdir, ignore_errors=True)
            with _pf_lock:
                PREFETCH.pop(vid, None)
            pf["done"].set()
            if on_done:
                try:
                    on_done()
                except Exception:
                    pass
    threading.Thread(target=work, daemon=True, name="chat-prefetch").start()
    return "started"


def cancel_prefetch(vid, kill=True):
    with _pf_lock:
        pf = PREFETCH.get(vid)
    if pf:
        pf["ctl"].cancel()   # 子プロセスは run_progress の見張りが 0.3 秒で止める


def cancel_all_prefetch():
    """終了の流れ用: 先読みをすべて中止する(止める依頼だけ。子プロセスは procs.stop_children がまとめて止める)。中止した数"""
    with _pf_lock:
        vids = list(PREFETCH)
    for vid in vids:
        cancel_prefetch(vid, kill=False)
    return len(vids)


def start_chat(ctl, run, vid, wdir, timeout):
    """チャット取得を別スレッドで始める(音声のダウンロード・解析と並行して進める)。"""
    c = {"state": "running", "t0": time.time(), "t1": None, "bytes": 0, "stop": threading.Event(), "cached": False, "path": None, "why": "", "err": None}
    run["chat"] = c
    ctl.note("chat", c)   # 器が画面に見せる(進み具合のチャットの欄)

    def work():
        try:
            c["path"], c["why"] = download_chat(ctl, run, vid, wdir, timeout)
        except Cancelled:
            c["why"] = "中止"
        except Exception as e:   # 想定外でも本体の解析は続ける
            c["why"] = "チャットの取得で予期しないエラー: " + redact(str(e))[:160]
        finally:
            c["t1"] = time.time()
            c["state"] = "cached" if c["cached"] and c["path"] else ("done" if c["path"] else "failed")
    th = threading.Thread(target=work, daemon=True)
    c["thread"] = th
    th.start()


TS_RE = re.compile(r"(?<![\d:])(?:(\d{1,2}):)?([0-5]?\d):([0-5]\d)(?![\d:])")


def fetch_comments(vid, dur, texts=None):
    """動画コメント欄から [(秒, いいね数)]。APIキーが無い・失敗のときは (None, 理由)。"""
    if _env.fake():
        p = _env.fake_file("COMMENTS")
        if not p:
            return None, "疑似モード: コメントなし"
        with open(p, encoding="utf-8") as f:
            threads = json.load(f)
        return stamps_from(threads, dur, texts), ""
    key = _key.get_api_key()[0]
    if not key:
        return None, "APIキーが未設定のため、コメント欄は使っていません(任意)"
    items, token = [], None
    for _ in range(5):
        params = {"part": "snippet", "videoId": vid, "maxResults": 100, "order": "relevance", "textFormat": "plainText"}
        if token:
            params["pageToken"] = token
        try:
            d = _ytapi.get("commentThreads", params)   # キーは URL でなく見出しで送る(取得の口は ytt/ytapi の 1 つ)
        except ApiError as ex:
            if ex.code == "quota":
                return None, "コメント欄を取得できませんでした(YouTube API の1日の利用上限に達しました)"
            if ex.code == "network":
                return None, "コメント欄を取得できませんでした(接続エラー)"
            reason = ex.extra.get("reason", "")
            if reason == "commentsDisabled":
                return None, "この動画はコメントが無効です"
            if ex.code == "upstream" or ex.status == 403:
                return None, "コメント欄を取得できませんでした(%s / %s)" % (reason or "エラー", ex.extra.get("detail") or "HTTP %d" % ex.status)
            return None, "コメント欄を取得できませんでした(%s)" % ex.message
        for it in d.get("items", []):
            sn = it.get("snippet", {}).get("topLevelComment", {}).get("snippet", {})
            items.append({"text": sn.get("textOriginal") or sn.get("textDisplay") or "", "likes": int(sn.get("likeCount") or 0)})
        token = d.get("nextPageToken")
        if not token:
            break
    return stamps_from(items, dur, texts), ""


LIST_MIN = 3   # 1つのコメントに時刻がこの数以上あれば「チャプター一覧」とみなす


def stamps_from(items, dur, texts=None):
    """[(秒, いいね数, 重み)]。チャプター一覧のコメント(時刻が LIST_MIN 個以上)は、1つあたりの重みを 1/個数 に下げる
    (「ここが見どころ」という個別の指定ではなく、一覧に載っているだけなので)。"""
    out = []
    for it in items:
        ts = []
        for m in TS_RE.finditer(str(it.get("text", ""))):
            t = int(m.group(1) or 0) * 3600 + int(m.group(2)) * 60 + int(m.group(3))
            if 0 < t < dur:
                ts.append(t)
        w = 1.0 if len(ts) < LIST_MIN else 1.0 / len(ts)
        likes = int(it.get("likes", 0))
        out.extend((t, likes, w) for t in ts)
        if texts is not None:   # 記録用: 時刻ごとに、そのコメントの先頭60文字
            texts.extend(str(it.get("text", "")).replace("\n", " ")[:60] for _ in ts)
    return out


# ---------- 動画の付加情報(みんなが繰り返し見た場面・チャプター・カテゴリなど。記録用) ----------
def meta_dir():
    return _env.p("cache", "meta")


def slim_meta(d):
    """yt-dlp の動画情報(-J)から、記録に使う項目だけを小さく取り出す。形が違えば None。"""
    if not isinstance(d, dict):
        return None

    def s_(k, n=200):
        v = d.get(k)
        return str(v)[:n] if isinstance(v, (str, int, float)) and not isinstance(v, bool) else ""

    def i_(k):
        v = d.get(k)
        return int(v) if isinstance(v, (int, float)) and not isinstance(v, bool) else None

    def lst(k, n, m):
        v = d.get(k)
        return [str(x)[:n] for x in v[:m]] if isinstance(v, list) else []
    hm, ch = [], []
    for h in d.get("heatmap") or []:   # 「最も再生された場面」: 区間ごとの相対値 0〜1(粗い。再生数が少ない動画・配信直後は無い)
        try:
            hm.append([round(float(h["start_time"]), 1), round(float(h["end_time"]), 1), round(float(h["value"]), 3)])
        except (KeyError, TypeError, ValueError):
            continue
    for c in d.get("chapters") or []:
        try:
            ch.append([round(float(c["start_time"]), 1), round(float(c["end_time"]), 1), str(c.get("title") or "")[:60]])
        except (KeyError, TypeError, ValueError):
            continue
    return {"title": s_("title", 120), "channel": s_("channel", 100) or s_("uploader", 100), "categories": lst("categories", 30, 5), "tags": lst("tags", 30, 30),
            "views": i_("view_count"), "likes": i_("like_count"), "commentCount": i_("comment_count"), "followers": i_("channel_follower_count"),
            "uploadDate": s_("upload_date", 8), "releaseTs": i_("release_timestamp"), "timestamp": i_("timestamp"), "duration": i_("duration"), "liveStatus": s_("live_status", 20),
            "heatmap": hm[:300], "chapters": ch[:100], "fetchedAt": int(time.time())}


def _meta_ok(d):
    """キャッシュの形の確認(記録用の情報の型の違いで解析全体が失敗するのを防ぐ)。"""
    return (isinstance(d, dict) and isinstance(d.get("title", ""), str)
            and all(isinstance(d.get(k) or [], list) and all(isinstance(x, str) for x in (d.get(k) or [])) for k in ("tags", "categories"))
            and all(isinstance(d.get(k) or [], list) for k in ("heatmap", "chapters")))


def load_meta(vid):
    d = _fsio.read_json_or(os.path.join(meta_dir(), vid + ".json"))
    try:
        if _meta_ok(d) and time.time() - float(d.get("fetchedAt") or 0) < META_TTL:
            return d
    except (OSError, ValueError, TypeError):
        pass
    return None


def fetch_meta(ctl, vid):
    """(付加情報 or None, 理由)。失敗しても解析には影響しない。24時間以内に取得済みならそれを使う。"""
    if _env.fake():
        p = _env.fake_file("META")
        if not p:
            return None, "疑似モード: 付加情報なし"
        with open(p, encoding="utf-8") as f:
            return slim_meta(json.load(f)), ""
    cached = load_meta(vid)
    if cached:
        return cached, ""
    yt = _env.find_tool("yt-dlp")
    if not yt:
        return None, "yt-dlp が見つかりません"
    buf = []
    try:
        rc, err = _procs.run_capture(ctl, [yt, "--encoding", "utf-8"] + _tools.ytdlp_auth_args() + ["--no-playlist", "--no-warnings", "--skip-download", "-J", "--", _yturl.watch_url(vid)],
                              lambda l: buf.append(l) if len(buf) < 20000 else None, timeout=META_TIMEOUT, what="動画情報の取得")
    except ApiError as e:
        return None, e.message
    if rc != 0:
        return None, tail_reason(err) or "取得できませんでした"
    try:
        m = slim_meta(json.loads("".join(buf)))
    except ValueError:
        return None, "動画情報を読み取れませんでした"
    if m:
        try:
            _fsio.write_json(os.path.join(meta_dir(), vid + ".json"), m, indent=None)
            _fsio.prune_cache(meta_dir(), "*.json", META_KEEP)
        except OSError:
            pass
    return m, ""


def start_meta(ctl, run, vid):
    """付加情報の取得を別スレッドで始める(音声などの解析と並行)。結果は run["meta"] = {"data", "why", "thread", "stop"}。stop を立てると取得だけ止まる。"""
    r = {"data": None, "why": "", "thread": None, "stop": threading.Event()}
    run["meta"] = r
    sub = _Stop(ctl, r["stop"])

    def work():
        try:
            r["data"], r["why"] = fetch_meta(sub, vid)
        except Cancelled:
            r["why"] = "中止"
        except Exception as e:   # 記録用なので、何があっても本体の解析は続ける
            r["why"] = "予期しないエラー: " + redact(str(e))[:120]
    th = threading.Thread(target=work, daemon=True)
    r["thread"] = th
    th.start()
