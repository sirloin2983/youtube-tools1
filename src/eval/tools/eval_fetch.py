#!/usr/bin/env python3
"""編集前の定点(評価用)を、配信のアーカイブから取得する道具(文字起こしの精度改善の計画 第2版 D0-b。plan/line-b-transcription.md の 3-3)。

    python dev/eval_fetch.py plan  [--root 評価用のフォルダ] [--minutes 40] [--clip-sec 40] [--since YYYY-MM-DD] [--seed 文字] [--redo]
    python dev/eval_fetch.py show  [--root 評価用のフォルダ]
    python dev/eval_fetch.py fetch [--root 評価用のフォルダ] [--limit N]

- plan  … メンバーのチャンネル(src/editor/hololive-roster.json の channel)の配信の一覧を yt-dlp で読み、どの配信のどこを取るかの一覧
           <評価用のフォルダ>\\fetch-plan.json を作る(動画は取らない)。乱数は使わない(seed と ID の SHA-1 で決める = 何度作っても同じ)
- fetch … 一覧のうちまだ取っていない区間を取って、<評価用のフォルダ>\\評価用_仮置き に置く。途中で止めても、もう一度流せば続きから
- show  … 一覧の要約

決まり:
- 取るのは **--since 以降の配信**だけ(既定 = 分け方の一覧 split-plan.json のショートのいちばん新しい日付の翌日。学習用のショートと同じ場面が評価用に入らないように)
- 配信中・配信前・短い配信(20 分未満)・歌枠などは選ばない。1 つの配信からは 1 区間。メンバーが偏らないよう、全員に 1 区間ずつ → 目標の分まで 2 区間目
  (2 区間目は、題名にほかのメンバーの名前がある配信 = コラボ(重なり声)を先に選ぶ)
- 区間は配信の 10%〜90% の中(始まりの待機画面と終わりを避ける)。盛り上がりの所に寄せない(普通の話し方も測る)
- 取り方はスタジオの書き出しと同じ 2 段: yt-dlp で区間をそのまま取る(前後に余裕)→ ffmpeg で正確な区間に切って 30fps(H.264・AAC)に
- ほとんど無音の区間(音のある所が 2 割未満)は、同じ配信の別の所を 1 回だけ取り直す。取れない配信(メンバー限定・非公開)は次の候補へ
- 動画の名前は「配信_<メンバー>_<動画ID>_<開始>.mp4」。隣の 作業用\\ に youtube-tools-clip/v1 の .clip.json を書く
  (文字起こしの文書に元の配信(clip.source.videoId)が残る = ショートの定点と見分けられる・評価ドリルの「配信」の数え方に入る)
- 作業データには触らない。書くのは評価用のフォルダの中だけ(一覧・動画・.clip.json)。取ったあとは、編集の ⚙ の「仮置きをまとめて文字起こし」→ 評価ドリル
"""
import argparse
import datetime
import glob
import json
import os
import re
import subprocess
import sys
import time

HERE = os.path.dirname(os.path.abspath(__file__))
REPO = os.path.join(os.path.dirname(HERE), "src")   # ツールと ytt_core の置き場所
if REPO not in sys.path:
    sys.path.insert(0, REPO)
from ytt import fsio, normalize, schemas, tools  # noqa: E402
import eval_split  # noqa: E402  (同じ dev/ の道具。評価用のフォルダの決め方・名簿の読み方を使う)

SCHEMA = "youtube-tools-eval-fetch/v1"
PLAN_NAME = "fetch-plan.json"
TOOL = {"name": "eval-fetch", "version": "1"}
VID_RE = re.compile(r"^[A-Za-z0-9_-]{11}$")
CH_RE = re.compile(r"^UC[A-Za-z0-9_-]{22}$")
LIST_MAX = 40                # チャンネルごとに読む配信の数(新しい順)
MIN_STREAM_SEC = 20 * 60     # これより短い配信は選ばない
EDGE = 0.10                  # 配信の前後のこの割合は取らない
SECTION_PAD = 2.0            # 区間取得で前後に足す秒(src/pipeline/export/exporter.py と同じ)
MAX_HEIGHT = 720             # 校正の画面で見るだけなので 720p まで
CANDIDATES = 6               # 1 区間あたりの配信の候補(取れなければ次へ)
SILENT_RATIO = 0.8           # 無音がこの割合を超えたら取り直す
SKIP_TITLE = re.compile(r"歌枠|カラオケ|karaoke|singing|歌ってみた|3D ?LIVE|お知らせ|ASMR", re.I)
COLLAB_WORD = re.compile(r"コラボ|collab|オフコラボ", re.I)


_h = eval_split._order   # seed と文字から決まる順番の鍵(SHA-1。分け方の一覧と同じ決め方)


def _frac(seed, text):
    """0 以上 1 未満(seed と text から決まる)"""
    return int(_h(seed, text)[:8], 16) / float(0x100000000)


def fmt_pos(sec):
    sec = int(sec)
    return "%dh%02dm%02ds" % (sec // 3600, sec % 3600 // 60, sec % 60)


def fmt_ts(sec):
    return "%d:%02d:%06.3f" % (int(sec) // 3600, int(sec) % 3600 // 60, sec % 60)


def load_members(path=eval_split.ROSTER):
    """[{"name", "channel"(形の合わないものは ""), "keys": 題名から見つけるための形(正式な名前と、紛れない呼び名)}](名簿の読み方は eval_split.roster_members)"""
    out = []
    for name, m, keys in eval_split.roster_members(path):
        ch = str(m.get("channel") or "")
        out.append({"name": name, "channel": ch if CH_RE.match(ch) else "", "keys": [k for k, kind in keys if kind < 2]})
    return out


def is_collab(title, member, members):
    """題名にほかのメンバーの名前(か「コラボ」)がある"""
    if COLLAB_WORD.search(title or ""):
        return True
    t = eval_split.fold(title)
    return any(k in t for m in members if m["name"] != member for k in m["keys"])


def usable(entry, since_ts):
    """配信の一覧の 1 件を使えるか(終わった配信・長さが足りる・--since 以降・歌枠などでない)"""
    if not VID_RE.match(str(entry.get("id") or "")):
        return False
    if entry.get("live_status") not in (None, "was_live", "not_live"):
        return False
    dur, ts = entry.get("duration"), entry.get("timestamp")
    if not isinstance(dur, (int, float)) or dur < MIN_STREAM_SEC:
        return False
    if not isinstance(ts, (int, float)) or ts < since_ts:
        return False
    return not SKIP_TITLE.search(str(entry.get("title") or ""))


def pick_start(seed, vid, duration, clip_sec, attempt=0):
    """区間の開始(秒。整数)。配信の EDGE〜1-EDGE の中"""
    lo, hi = duration * EDGE, duration * (1 - EDGE) - clip_sec
    return int(lo + _frac(seed, "%s|start|%d" % (vid, attempt)) * max(0.0, hi - lo))


def make_plan(members, listings, minutes, clip_sec, since_ts, seed="1"):
    """listings = {メンバー: 配信の一覧(yt-dlp の entries)} → 取る区間の一覧 [{member, slot, candidates: [{id, title, duration, date, collab}]}]。

    1 巡目 = 全員に 1 区間(題名にほかの人がいない配信を先に)。2 巡目以降 = 目標の分に届くまで、順番に 1 区間ずつ(コラボの配信を先に)
    """
    pools = {}
    for m in members:
        seen, pool = set(), []
        for e in listings.get(m["name"]) or []:
            if usable(e, since_ts) and e["id"] not in seen:
                seen.add(e["id"])
                pool.append({"id": e["id"], "title": str(e.get("title") or "")[:200], "duration": int(e["duration"]),
                             "date": datetime.datetime.fromtimestamp(e["timestamp"], datetime.timezone.utc).strftime("%Y-%m-%d"),
                             "collab": is_collab(e.get("title"), m["name"], members)})
        pool.sort(key=lambda c: _h(seed, c["id"]))
        if pool:
            pools[m["name"]] = pool
    order = sorted(pools, key=lambda n: _h(seed, n))
    need = int(round(minutes * 60 / float(clip_sec)))
    items, taken, slot = [], set(), 0
    while len(items) < need:
        added = False
        for name in order:
            if len(items) >= need:
                break
            free = [c for c in pools[name] if c["id"] not in taken]
            if not free:
                continue
            free.sort(key=lambda c: (c["collab"] != (slot >= 1), _h(seed, c["id"])))   # 1 巡目はひとりの配信・2 巡目からはコラボを先に
            cands = free[:CANDIDATES]
            taken.add(cands[0]["id"])       # 1 つ目の候補はほかの区間に使わない(取れずに次の候補へ進んだときは fetch が重なりを見る)
            items.append({"member": name, "slot": slot, "candidates": cands})
            added = True
        if not added:
            break
        slot += 1
    return items


# ---------- 外のコマンド(テストで差し替える) ----------
def run_cmd(cmd, timeout):
    """(終了コード, 標準出力, 標準エラーの最後の数行)"""
    try:
        p = subprocess.run(cmd, capture_output=True, text=True, encoding="utf-8", errors="replace", timeout=timeout, creationflags=tools.no_window_flags())
    except (OSError, subprocess.SubprocessError) as e:
        return 1, "", str(e)
    return p.returncode, p.stdout or "", "\n".join((p.stderr or "").strip().splitlines()[-3:])


def list_streams(channel, run=run_cmd):
    """チャンネルの配信の一覧(新しい順。yt-dlp の entries)。読めなければ []"""
    exe = tools.find_tool("yt-dlp")
    if not exe or not CH_RE.match(channel):
        return []
    code, out, _err = run([exe, "--flat-playlist", "--no-warnings", "--playlist-end", str(LIST_MAX), "--extractor-args", "youtubetab:approximate_date",
                           "-J", "--", "https://www.youtube.com/channel/%s/streams" % channel], 180)
    if code != 0:
        return []
    try:
        return [e for e in json.loads(out).get("entries") or [] if isinstance(e, dict)]
    except ValueError:
        return []


def silent_ratio(path):
    """無音の割合(0〜1。ffmpeg の silencedetect)。分からなければ 0"""
    ff, info = tools.find_tool("ffmpeg"), normalize.probe(path)
    dur = (info or {}).get("duration") or 0
    if not ff or not dur:
        return 0.0
    try:
        p = subprocess.run([ff, "-hide_banner", "-nostdin", "-i", path, "-vn", "-af", "silencedetect=noise=-40dB:d=0.5", "-f", "null", "-"],
                           capture_output=True, text=True, encoding="utf-8", errors="replace", timeout=120, creationflags=tools.no_window_flags())
    except (OSError, subprocess.SubprocessError):
        return 0.0
    total = sum(float(x) for x in re.findall(r"silence_duration: ([0-9.]+)", p.stderr or ""))
    return min(1.0, total / dur)


def download(vid, start, clip_sec, out, work, run=run_cmd):
    """配信 vid の start から clip_sec 秒を out(mp4・30fps)に作る。失敗したら理由の文字、成功したら None"""
    exe, ff = tools.find_tool("yt-dlp"), tools.find_tool("ffmpeg")
    if not exe or not ff:
        return "yt-dlp か ffmpeg が見つかりません"
    os.makedirs(work, exist_ok=True)
    raw_base = os.path.join(work, "fetch_%s_%d.partial" % (vid, start))
    for f in glob.glob(glob.escape(raw_base) + ".*"):     # 前回の残り(yt-dlp は同じ名前があると取得済みとして使ってしまう)
        os.unlink(f)
    dl_start = max(0.0, start - SECTION_PAD)
    dl_end = start + clip_sec + SECTION_PAD
    tmp = out + ".part.mp4"
    try:
        code, _o, err = run([exe, "--no-playlist", "--no-warnings", "--ffmpeg-location", ff,
                             "--download-sections", "*%s-%s" % (fmt_ts(dl_start), fmt_ts(dl_end)),
                             "-f", "bv*[height<=%d]+ba/b[height<=%d]/b" % (MAX_HEIGHT, MAX_HEIGHT), "--merge-output-format", "mp4",
                             "-o", os.path.join(work.replace("%", "%%"), os.path.basename(raw_base) + ".%(ext)s"),
                             "--", "https://www.youtube.com/watch?v=" + vid], 900)
        files = [f for f in glob.glob(glob.escape(raw_base) + ".*") if not f.endswith((".part", ".ytdl", ".temp"))]
        if code != 0 or not files:
            return "取得できませんでした: %s" % (err or "出力がありません")[:200]
        raw = sorted(files)[0]
        raw_len = (normalize.probe(raw) or {}).get("duration")
        if not raw_len or raw_len > (dl_end - dl_start) + 1.0:   # 頼んだより長い = 開始の位置が分からない(studio と同じ扱い)
            return "取った区間の開始の位置が分かりません"
        off = start - dl_start
        dur = min(clip_sec, raw_len - off)
        if dur < clip_sec * 0.5:
            return "取った区間が短すぎます(%.1f 秒)" % raw_len
        code, _o, err = run([ff, "-hide_banner", "-nostdin", "-y", "-protocol_whitelist", "file,pipe", "-ss", "%.3f" % off, "-i", raw, "-t", "%.3f" % dur]
                            + normalize.encode_args(normalize.FAST_PRESET) + [tmp], 900)
        if code != 0 or not os.path.isfile(tmp):
            return "切り出しに失敗しました: %s" % (err or "")[:200]
        fsio.replace_retry(tmp, out)
        return None
    finally:
        for f in glob.glob(glob.escape(raw_base) + ".*") + [tmp]:
            fsio.unlink_quiet(f)


# ---------- 一覧 ----------
def plan_path(root):
    return os.path.join(root, PLAN_NAME)


def read_plan(root):
    plan = fsio.read_json_or(plan_path(root), None, kind=dict)
    return plan if plan is not None and plan.get("schema") == SCHEMA else None


def write_plan(root, plan):
    fsio.write_json(plan_path(root), plan, indent=1)


def default_since(root):
    """分け方の一覧(split-plan.json)のショートのいちばん新しい日付の翌日。分からなければ None"""
    plan = eval_split.read_plan(root)
    best = None
    for f in (plan or {}).get("files") or []:
        m = re.match(r"^(\d{2})-(\d{2})-(\d{2})$", str(f.get("date") or "")[:8])
        if m:
            try:
                d = datetime.date(2000 + int(m.group(1)), int(m.group(2)), int(m.group(3)))
            except ValueError:
                continue
            best = d if best is None or d > best else best
    return (best + datetime.timedelta(days=1)).isoformat() if best else None


def print_plan(plan):
    items = plan["items"]
    done = [i for i in items if i.get("done")]
    print("取得の一覧: %d 区間 × %d 秒 = %.1f 分(%s 以降の配信)・取得済み %d・あきらめた %d" % (
        len(items), plan["clipSec"], len(items) * plan["clipSec"] / 60.0, plan["since"], len(done), sum(1 for i in items if i.get("failed"))))
    per = {}
    for i in items:
        row = per.setdefault(i["member"], [0, 0, 0])
        row[0] += 1
        row[1] += 1 if i.get("done") else 0
        row[2] += 1 if i["candidates"][0]["collab"] else 0
    for name in sorted(per, key=lambda n: (-per[n][0], n)):
        print("  %d 区間(取得済み %d・コラボ %d)  %s" % (per[name][0], per[name][1], per[name][2], name))
    if plan.get("noStreams"):
        print("  使える配信が無かった人: " + "・".join(plan["noStreams"]))


def cmd_plan(args, lister=list_streams):
    old = read_plan(args.root)
    if old and not args.redo:
        print("すでに一覧があります(作り直すなら --redo)。")
        print_plan(old)
        return 0
    if old and any(i.get("done") for i in old["items"]):
        print("もう取得を始めた一覧なので、作り直せません(取った動画と一覧が食い違うため)。")
        return 2
    since = args.since or default_since(args.root)
    if not since:
        print("--since YYYY-MM-DD を指定してください(分け方の一覧からショートの日付が分かりませんでした)。")
        return 2
    try:
        since_ts = datetime.datetime.strptime(since, "%Y-%m-%d").replace(tzinfo=datetime.timezone.utc).timestamp()
    except ValueError:
        print("--since の書き方は YYYY-MM-DD です。")
        return 2
    all_members = load_members()
    members = [m for m in all_members if m["channel"]]
    listings = {}
    for n, m in enumerate(members):
        print("  配信の一覧を読んでいます… (%d/%d) %s" % (n + 1, len(members), m["name"]), flush=True)
        listings[m["name"]] = lister(m["channel"])
    items = make_plan(all_members, listings, args.minutes, args.clip_sec, since_ts, args.seed)
    plan = {"schema": SCHEMA, "createdAt": datetime.datetime.now().isoformat(timespec="seconds"), "root": args.root, "since": since,
            "minutes": args.minutes, "clipSec": args.clip_sec, "seed": args.seed, "items": items,
            "noStreams": sorted(m["name"] for m in members if not any(i["member"] == m["name"] for i in items))}
    write_plan(args.root, plan)
    print_plan(plan)
    return 0


def clip_name(member, vid, start):
    return "配信_%s_%s_%s.mp4" % (re.sub(r'[\\/:*?"<>|%]', "_", member), vid, fmt_pos(start))


def cmd_fetch(args, fetcher=download, silence=silent_ratio):
    plan = read_plan(args.root)
    if not plan:
        print("一覧がありません。先に plan を実行してください。")
        return 2
    staging = os.path.join(args.root, eval_split.STAGING)
    work = os.path.join(staging, schemas.WORK_DIR)
    os.makedirs(staging, exist_ok=True)
    used = {i["done"]["id"] for i in plan["items"] if i.get("done")}
    got = 0
    todo = [i for i in plan["items"] if not i.get("done") and not i.get("failed")]
    for n, item in enumerate(todo):
        if args.limit and got >= args.limit:
            break
        errors = []
        for cand in item["candidates"]:
            vid = cand["id"]
            if vid in used:
                continue
            ok = None
            for attempt in (0, 1):                       # 無音ばかりなら、同じ配信の別の所を 1 回だけ
                start = pick_start(plan["seed"], vid, cand["duration"], plan["clipSec"], attempt)
                out = os.path.join(staging, clip_name(item["member"], vid, start))
                print("(%d/%d) %s %s %s …" % (n + 1, len(todo), item["member"], vid, fmt_pos(start)), flush=True)
                err = fetcher(vid, start, plan["clipSec"], out, work)
                if err:
                    errors.append("%s: %s" % (vid, err))
                    break
                ratio = silence(out)
                if ratio > SILENT_RATIO and attempt == 0:
                    os.unlink(out)
                    continue
                ok = (out, start, ratio)
                break
            if not ok:
                continue
            out, start, ratio = ok
            dur = (normalize.probe(out) or {}).get("duration") or plan["clipSec"]
            clip = schemas.build_clip(out, dur, {"kind": "youtube", "videoId": vid, "title": cand["title"]}, (start, start + dur),
                                      {"id": "", "label": "評価用(配信から取得)", "status": "", "src": "auto"}, {"mode": "precise"}, TOOL)
            fsio.write_json(schemas.clip_path_for(out), clip, indent=1)   # フォルダも作る
            item["done"] = {"id": vid, "start": start, "sec": round(dur, 2), "file": os.path.basename(out), "silent": round(ratio, 2),
                            "date": cand["date"], "collab": cand["collab"], "at": datetime.datetime.now().isoformat(timespec="seconds")}
            used.add(vid)
            got += 1
            break
        if not item.get("done"):
            item["failed"] = errors[-3:] or ["候補の配信がすべてほかの区間で使われています"]
            print("  取れませんでした: %s" % " / ".join(item["failed"])[:300])
        item.pop("errors", None)
        write_plan(args.root, plan)                       # 1 区間ごとに書く(途中で止めても続きから)
        time.sleep(1.0)
    done = [i["done"] for i in plan["items"] if i.get("done")]
    print("取得済み %d 区間・%.1f 分(今回 %d)・あきらめた %d → %s" % (len(done), sum(d["sec"] for d in done) / 60.0, got,
                                                       sum(1 for i in plan["items"] if i.get("failed")), staging))
    return 0


def main(argv=None):
    p = argparse.ArgumentParser(description="編集前の定点(評価用)を、配信のアーカイブから取得する")
    p.add_argument("mode", choices=("plan", "show", "fetch"))
    p.add_argument("--root", help="評価用のフォルダ(既定 = 編集の設定の評価用のフォルダの 1 つ目)")
    p.add_argument("--data", help="文字起こしの作業データのフォルダ(評価用のフォルダを設定から読むときだけ使う)")
    p.add_argument("--minutes", type=float, default=40.0, help="取る量(分。既定 40)")
    p.add_argument("--clip-sec", dest="clip_sec", type=int, default=40, help="1 区間の長さ(秒。既定 40)")
    p.add_argument("--since", help="この日以降の配信だけ(YYYY-MM-DD。既定 = ショートのいちばん新しい日付の翌日)")
    p.add_argument("--seed", default="1", help="順番を決める文字(同じなら同じ一覧)")
    p.add_argument("--redo", action="store_true", help="plan: 一覧を作り直す(取得を始めたあとは作り直せない)")
    p.add_argument("--limit", type=int, default=0, help="fetch: 今回取る数の上限(0 = 全部)")
    args = p.parse_args(argv)
    if not args.root:
        from ytt import datadir
        args.root = eval_split.default_root(args.data or datadir.tool_dir("transcribe", os.path.join(REPO, "editor")))
    if not args.root or not os.path.isdir(args.root) or fsio.is_network_path(args.root):
        print("評価用のフォルダが分かりません(--root で指定してください。ネットワーク上のフォルダは使えません)。")
        return 2
    if args.clip_sec < 10 or args.clip_sec > 300 or args.minutes <= 0:
        print("--clip-sec は 10〜300、--minutes は 0 より大きく。")
        return 2
    if args.mode == "plan":
        return cmd_plan(args)
    if args.mode == "show":
        plan = read_plan(args.root)
        if not plan:
            print("一覧がありません。先に plan を実行してください。")
            return 2
        print_plan(plan)
        return 0
    return cmd_fetch(args)


if __name__ == "__main__":
    sys.exit(main())
