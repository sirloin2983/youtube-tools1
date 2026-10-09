#!/usr/bin/env python3
"""評価用_仮置き の動画を、評価用(定点)と学習用に分ける道具(文字起こしの精度改善の計画 第2版 D0。plan/line-b-transcription.md の 3-1)。

    python dev/eval_split.py plan  [--root 評価用のフォルダ] [--train 学習用のフォルダ] [--eval-min 30] [--seed 文字] [--data 文字起こしの作業データ]
    python dev/eval_split.py show  [--root 評価用のフォルダ]
    python dev/eval_split.py apply [--root 評価用のフォルダ] [--data 文字起こしの作業データ] [--force]

- plan  … 分け方の一覧 <評価用のフォルダ>\\split-plan.json を作る(動画は動かさない)。すでに一覧があれば作り直さない(--redo で作り直す。移したあとは作り直せない)
- show  … 一覧の要約(メンバーごとの本数と分)を出す
- apply … 一覧で「学習用」の動画を、学習用のフォルダの <メンバー>\\ へ移す(同じドライブなら名前の付け替えだけ。別のドライブはコピー → 大きさを確かめる → 元を消す)

決まり:
- 単位は **メンバー × 日付**(同じ単位は必ず同じ側 = 同じ配信の切り抜きが評価用と学習用の両方に入らない)
- 必ず評価用にするもの: 文書がすでにある動画(文字起こし済み。評価用の印が付いていて、動かすと文書が動画を見失う)と同じ単位・名簿に無い人(学習に入れない人 = 知らない声での確認)・名前から人が分からない動画
- 残りは、まず評価用が 1 本も無い人(2 単位以上ある人)に 1 単位ずつ、そのあと評価用の分が --eval-min に届くまで、**まだ評価用の少ないメンバーから順に** 1 単位ずつ足す(人が偏らないように。全員に行き渡るまでは --eval-min を超えても足す)。同じ条件の中の順番は seed と名前から決まる(乱数は使わない = 何度作っても同じ)
- 作業データは**読むだけ**(文書の動画のパス・まとめての文字起こしが動いているか)。書くのは評価用のフォルダの一覧と、動画の移動だけ
- apply は、文書が指している動画・移す先に同じ名前がある動画・無くなった動画を飛ばす。まとめての文字起こし(eval-batch)が動いている間は止める(--force で進める)
"""
import argparse
import datetime
import hashlib
import os
import re
import shutil
import sys
import unicodedata

HERE = os.path.dirname(os.path.abspath(__file__))
REPO = os.path.join(os.path.dirname(HERE), "src")   # ツールと ytt_core の置き場所
if REPO not in sys.path:
    sys.path.insert(0, REPO)
from ytt_core import datadir, fsio, normalize  # noqa: E402

SCHEMA = "youtube-tools-eval-split/v1"
PLAN_NAME = "split-plan.json"
STAGING = "評価用_仮置き"                    # src/editor/ed_relink.py の EVAL_STAGING と同じ(editor は読み込まない)
VIDEO_EXT = (".mp4", ".mov", ".mkv", ".webm", ".m4v", ".avi", ".ts", ".flv")
ROSTER = os.path.join(REPO, "editor", "hololive-roster.json")
ALIAS_MIN = 3                                # 名前が無いときに呼び名で決める最短の長さ(短い呼び名は別の語に紛れる)
UNKNOWN = "(不明)"
MAX_DOC_BYTES = 64 * 1024 * 1024        # 文字起こしの文書を読む大きさの上限
_SEP = re.compile(r"[\s・･\-‐_＿.,、。'\"/|｜!！?？#＃【】\[\]()（）「」『』<>〈〉★☆♪~〜]+")
_DATE = re.compile(r"\d{2}-\d{2,4}(?:-\d{2})?(?:,\d{2})*")
_NOISE = re.compile(r"教師データ|ショート|\d+")


def fold(s):
    """照らし合わせ用(src/editor/roster.py の fold と同じ): NFKC・小文字・カタカナ → ひらがな・空白と区切りを除く"""
    t = unicodedata.normalize("NFKC", str(s or "")).lower()
    t = "".join(chr(ord(c) - 0x60) if "ァ" <= c <= "ヶ" else c for c in t)
    return _SEP.sub("", t)


def roster_members(path=ROSTER):
    """名簿の人 -> [(正式な名前, 名簿の項目, [(照らし合わせ用の形, 種類)])](名前の無い項目は飛ばす。読めなければ [])。
    種類 0 = 正式な名前・1 = 呼び名・2 = 普通の言葉と重なる呼び名(common)か短い呼び名(ALIAS_MIN 未満)。eval_fetch.py も使う"""
    members = (fsio.read_json_or(path, None, kind=dict) or {}).get("members") or []
    out = []
    for m in members:
        name = str(m.get("name") or "").strip()
        if not name:
            continue
        common = {fold(c) for c in m.get("common") or []}
        aliases = [(k, 2 if len(k) < ALIAS_MIN or k in common else 1) for k in (fold(a) for a in m.get("aliases") or []) if k]
        out.append((name, m, [(fold(name), 0)] + aliases))
    return out


def load_roster(path=ROSTER):
    """[(照らし合わせ用の形, 正式な名前, 種類)] を、正式な名前が先・長い順に(種類は roster_members と同じ)"""
    keys = [(k, name, kind) for name, _m, ks in roster_members(path) for k, kind in ks]
    keys.sort(key=lambda t: (t[2], -len(t[0]), t[1]))
    return keys


def parse_name(filename, roster):
    """動画の名前 → (メンバー, 日付, 名簿にあるか)。日付が無ければ日付は名前そのもの(1 本で 1 単位)"""
    stem = os.path.splitext(filename)[0]
    stem = re.sub(r"\.(mp4|mov|mkv|webm)$", "", stem, flags=re.I)   # 「名前.mkv.mov」のような二重の拡張子
    key = fold(stem)
    member, known = None, False
    rest = _SEP.sub("", _NOISE.sub("", unicodedata.normalize("NFKC", _DATE.sub("", stem))))   # 日付・番号・「ショート」を除いた残り
    for k, name, kind in roster:
        # 紛れやすい呼び名(種類 2)は、残りがその呼び名ちょうどのときだけ(「26-05-01_スバル」)
        if k and (k in key if kind < 2 else k == fold(rest)):
            member, known = name, True
            break
    if member is None:
        member = rest or UNKNOWN
    m = _DATE.search(unicodedata.normalize("NFKC", stem))
    return member, (m.group(0) if m else stem), known


def probe_sec(path):
    """動画の長さ(秒)。分からなければ 0"""
    return round((normalize.probe(path) or {}).get("duration") or 0.0, 2)


def list_videos(staging):
    try:
        names = os.listdir(staging)
    except OSError:
        return []
    return sorted(n for n in names if n.lower().endswith(VIDEO_EXT) and os.path.isfile(os.path.join(staging, n)))


def norm_path(p):
    return os.path.normcase(os.path.normpath(str(p or "")))


def doc_sources(data):
    """文字起こしの作業データの文書が指している動画のパス(照らし合わせ用の形)の集まり。読むだけ"""
    out = set()
    folder = os.path.join(data, "transcripts")
    try:
        names = os.listdir(folder)
    except OSError:
        return out
    for n in names:
        if not n.endswith(".json") or n.count(".") != 1:
            continue
        src = (fsio.read_json_or(os.path.join(folder, n), None, MAX_DOC_BYTES, dict) or {}).get("sourcePath")
        if src:
            out.add(norm_path(src))
    return out


def batch_running(data):
    """まとめての文字起こし(eval-batch)が動いているか"""
    return (fsio.read_json_or(os.path.join(data, "eval-batch.json"), None, kind=dict) or {}).get("enabled") is True


def _order(seed, text):
    return hashlib.sha1(("%s|%s" % (seed, text)).encode("utf-8")).hexdigest()


def make_plan(files, eval_sec, seed="1", used=()):
    """files = [{"name", "sec", "member", "date", "known"}] → 各ファイルに side("eval" | "train")と why を付けて返す。

    used = 文書がすでにある動画の名前。その単位は評価用に固定する
    """
    units = {}
    for f in files:
        u = units.setdefault((f["member"], f["date"]), {"files": [], "sec": 0.0, "why": None})
        u["files"].append(f)
        u["sec"] += f["sec"]
    used = set(used)
    for (member, _date), u in units.items():
        if any(f["name"] in used for f in u["files"]):
            u["why"] = "doc"            # 文字起こし済み(文書がある)
        elif member == UNKNOWN:
            u["why"] = "unknown"        # 名前から人が分からない(動かさない)
        elif not all(f["known"] for f in u["files"]):
            u["why"] = "outside"        # 名簿に無い人(学習に入れない人)
    per = {}                            # メンバーごとの評価用の秒
    total = 0.0
    for (member, _date), u in units.items():
        if u["why"]:
            per[member] = per.get(member, 0.0) + u["sec"]
            total += u["sec"]
    rest = {}
    for key, u in units.items():
        if not u["why"]:
            rest.setdefault(key[0], []).append(key)
    for member in rest:
        rest[member].sort(key=lambda k: _order(seed, "%s|%s" % k))
    def missing():                      # 評価用がまだ 1 本も無く、2 単位以上ある人(1 単位しか無い人は学習用に残す)
        return [m for m in rest if rest[m] and m not in per and len(rest[m]) >= 2]

    while any(rest.values()):
        need = missing() if eval_sec > 0 else []   # 目標 0 分 = 決まったもの以外は全部学習用
        if not need and total >= eval_sec:
            break
        pool = need or [m for m in rest if rest[m]]
        member = min(pool, key=lambda m: (per.get(m, 0.0), _order(seed, m)))
        key = rest[member].pop(0)
        units[key]["why"] = "balance"   # 人が偏らないように足した分
        per[member] = per.get(member, 0.0) + units[key]["sec"]
        total += units[key]["sec"]
    out = []
    for key, u in units.items():
        for f in u["files"]:
            out.append({**f, "side": "eval" if u["why"] else "train", "why": u["why"] or "train"})
    out.sort(key=lambda f: f["name"])
    return out


def summarize(files):
    """メンバーごとの {eval: [本, 秒], train: [本, 秒]} と合計"""
    per, tot = {}, {"eval": [0, 0.0], "train": [0, 0.0]}
    for f in files:
        row = per.setdefault(f["member"], {"eval": [0, 0.0], "train": [0, 0.0]})
        for box in (row[f["side"]], tot[f["side"]]):
            box[0] += 1
            box[1] += f["sec"]
    return per, tot


def print_plan(plan):
    per, tot = summarize(plan["files"])
    print("分け方の一覧: %s" % plan.get("path", ""))
    print("  評価用(定点) %3d 本 %5.1f 分 / 学習用 %3d 本 %5.1f 分" % (tot["eval"][0], tot["eval"][1] / 60, tot["train"][0], tot["train"][1] / 60))
    print("  学習用の移す先: %s" % plan["train"])
    print("  %-4s %-8s  %s" % ("評価", "学習", "メンバー"))
    for member in sorted(per, key=lambda m: (-(per[m]["eval"][0] + per[m]["train"][0]), m)):
        r = per[member]
        print("  %2d 本 %4.1f 分 / %3d 本 %5.1f 分  %s" % (r["eval"][0], r["eval"][1] / 60, r["train"][0], r["train"][1] / 60, member))
    why = {}
    for f in plan["files"]:
        if f["side"] == "eval":
            why[f["why"]] = why.get(f["why"], 0) + 1
    names = {"doc": "文字起こし済み(文書がある)", "outside": "名簿に無い人", "unknown": "名前から人が分からない", "balance": "人が偏らないように足した"}
    print("  評価用にした理由: " + " / ".join("%s %d 本" % (names.get(k, k), n) for k, n in sorted(why.items())))
    if plan.get("applied"):
        a = plan["applied"]
        print("  移した記録: %s  移した %d 本・飛ばした %d 本" % (a.get("at", ""), len(a.get("moved") or []), len(a.get("skipped") or [])))


def plan_path(root):
    return os.path.join(root, PLAN_NAME)


def read_plan(root):
    plan = fsio.read_json_or(plan_path(root), None, kind=dict)
    if plan is None or plan.get("schema") != SCHEMA:
        return None
    plan["path"] = plan_path(root)
    return plan


def write_plan(root, plan):
    body = {k: v for k, v in plan.items() if k != "path"}
    fsio.write_json(plan_path(root), body, indent=1)


def cmd_plan(args, probe=probe_sec):
    root, staging = args.root, os.path.join(args.root, STAGING)
    old = read_plan(root)
    if old and not args.redo:
        print("すでに一覧があります(作り直すなら --redo)。")
        print_plan(old)
        return 0
    if old and old.get("applied"):
        print("この一覧はもう移したあとなので、作り直せません(学習用に使い始めた動画が評価用に戻らないように)。")
        return 2
    names = list_videos(staging)
    if not names:
        print("動画が見つかりません: %s" % staging)
        return 2
    roster = load_roster()
    used_paths = doc_sources(args.data)
    files = []
    for i, n in enumerate(names):
        member, date, known = parse_name(n, roster)
        files.append({"name": n, "sec": probe(os.path.join(staging, n)), "member": member, "date": date, "known": known})
        if (i + 1) % 50 == 0:
            print("  長さを調べています… %d / %d" % (i + 1, len(names)), flush=True)
    used = [f["name"] for f in files if norm_path(os.path.join(staging, f["name"])) in used_paths]
    plan = {"schema": SCHEMA, "createdAt": datetime.datetime.now().isoformat(timespec="seconds"), "root": root, "train": args.train,
            "evalMin": args.eval_min, "seed": args.seed, "files": make_plan(files, args.eval_min * 60, args.seed, used)}
    write_plan(root, plan)
    plan["path"] = plan_path(root)
    print_plan(plan)
    print("一覧を直すときは、ファイルの side を eval / train に書き換えてください(同じメンバー・同じ日付は同じ側に)。よければ apply で移します。")
    return 0


def _move(src, dst):
    """同じドライブなら名前の付け替え。別のドライブはコピー → 大きさを確かめる → 元を消す(消せなければコピーを消して失敗)"""
    try:
        os.rename(src, dst)
        return
    except OSError:
        pass
    part = dst + ".part"
    shutil.copy2(src, part)
    if os.path.getsize(part) != os.path.getsize(src):
        os.remove(part)
        raise OSError("コピーの大きさが合いません")
    os.rename(part, dst)
    try:
        os.remove(src)
    except OSError:
        os.remove(dst)
        raise


def cmd_apply(args):
    root, staging = args.root, os.path.join(args.root, STAGING)
    plan = read_plan(root)
    if not plan:
        print("一覧がありません。先に plan を実行してください。")
        return 2
    if batch_running(args.data) and not args.force:
        print("まとめての文字起こしが動いています。⚙ の「止める」で止めてから、もう一度実行してください(--force で進めることもできます)。")
        return 2
    units = {}
    for f in plan["files"]:
        units.setdefault((f["member"], f["date"]), set()).add(f["side"])
    mixed = sorted("%s %s" % k for k, sides in units.items() if len(sides) > 1)
    if mixed:
        print("同じメンバー・同じ日付が評価用と学習用に分かれています(直してから実行してください): " + " / ".join(mixed[:10]))
        return 2
    used = doc_sources(args.data)
    moved, skipped = [], []
    for f in plan["files"]:
        if f["side"] != "train":
            continue
        src = os.path.join(staging, f["name"])
        folder = os.path.join(plan["train"], re.sub(r'[\\/:*?"<>|]', "_", f["member"]))
        dst = os.path.join(folder, f["name"])
        if not os.path.isfile(src):
            if not os.path.isfile(dst):
                skipped.append([f["name"], "動画が見つかりません"])
            continue                    # もう移してある
        if norm_path(src) in used:
            skipped.append([f["name"], "文書がこの動画を指しています(評価用のままにします)"])
            continue
        if os.path.exists(dst):
            skipped.append([f["name"], "移す先に同じ名前があります"])
            continue
        try:
            os.makedirs(folder, exist_ok=True)
            _move(src, dst)
            moved.append(f["name"])
        except OSError as e:
            skipped.append([f["name"], "移せませんでした: %s" % e])
    plan["applied"] = {"at": datetime.datetime.now().isoformat(timespec="seconds"),
                       "moved": (plan.get("applied") or {}).get("moved", []) + moved, "skipped": skipped}
    write_plan(root, plan)
    print("学習用へ移した %d 本・飛ばした %d 本 → %s" % (len(moved), len(skipped), plan["train"]))
    for name, why in skipped[:20]:
        print("  飛ばした: %s(%s)" % (name, why))
    return 0


def default_root(data):
    """編集の設定の評価用のフォルダ(1つ目)"""
    dirs = (fsio.read_json_or(os.path.join(data, "settings.json"), None, kind=dict) or {}).get("evalDirs") or []
    return dirs[0] if dirs and isinstance(dirs[0], str) else None


def main(argv=None):
    p = argparse.ArgumentParser(description="評価用_仮置き の動画を、評価用(定点)と学習用に分ける")
    p.add_argument("mode", choices=("plan", "show", "apply"))
    p.add_argument("--root", help="評価用のフォルダ(既定 = 編集の設定の評価用のフォルダの 1 つ目)")
    p.add_argument("--train", help="学習用のフォルダ(既定 = 評価用のフォルダの隣の「学習用データ」)")
    p.add_argument("--eval-min", dest="eval_min", type=float, default=30.0, help="評価用(定点)にする分(既定 30)")
    p.add_argument("--seed", default="1", help="順番を決める文字(同じなら同じ一覧)")
    p.add_argument("--data", help="文字起こしの作業データのフォルダ(既定 %%LOCALAPPDATA%%\\youtube-tools\\transcribe)")
    p.add_argument("--redo", action="store_true", help="plan: 一覧を作り直す(移したあとは作り直せない)")
    p.add_argument("--force", action="store_true", help="apply: まとめての文字起こしが動いていても進める")
    args = p.parse_args(argv)
    args.data = args.data or datadir.tool_dir("transcribe", os.path.join(REPO, "editor"))
    args.root = args.root or default_root(args.data)
    if not args.root or not os.path.isdir(args.root):
        print("評価用のフォルダが分かりません(--root で指定してください)。")
        return 2
    if fsio.is_network_path(args.root):
        print("ネットワーク上のフォルダは使えません。")
        return 2
    args.train = args.train or os.path.join(os.path.dirname(os.path.normpath(args.root)), "学習用データ")
    if os.path.commonpath([norm_path(args.root), norm_path(args.train)]) == norm_path(args.root):
        print("学習用のフォルダは、評価用のフォルダの外にしてください(中にあると評価用の印が付きます)。")
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
    return cmd_apply(args)


if __name__ == "__main__":
    sys.exit(main())
