#!/usr/bin/env python3
"""友人のアプリから届いた診断の記録を読む(ユーザーの PC。notes:docs/spec/friend.md の 13-11)。AI が原因を調べるときに流す。

    py -3.12 dev/friend_diag.py                  # 最新の 10 件を、段ごとの秒・エラー・道具の終了コードで一覧
    py -3.12 dev/friend_diag.py -n 30            # 30 件
    py -3.12 dev/friend_diag.py --errors         # 失敗(kind run の error・kind live のパック 0 本と、run・live・preview 以外)だけ
    py -3.12 dev/friend_diag.py --live           # ライブの行の診断(kind live。閉じた結果・録画の長さ・検出・チャット・採用・書き出し・配信後の追加)だけ
    py -3.12 dev/friend_diag.py --id <依頼 id>   # 1 つの依頼の物だけ(全部の欄)
    py -3.12 dev/friend_diag.py --json           # 読んだ物をそのまま JSON で(AI が細かく読む)
    py -3.12 dev/friend_diag.py --dir D          # 読む場所を変える(既定 <ホームの設定 intake.folder>/診断 = Dropbox の /診断/)

置き場所は Dropbox のアプリのフォルダの 診断\\(友人のアプリの同期 src/friendapp/sync.py が上げる)。名前 <依頼 id か app か launcher>__diag-<ミリ秒 13 桁>.diag.json。
片付け: 流すたびに 3 日より古い診断を消す(友人の側の同期も Dropbox の /診断/ の 3 日より古い物を消す = 同じ基準)。--keep で消さない。
中身は伏せてある(ユーザー名を含むパス・合言葉・鍵・API キー・動画の中身は入っていない)。読むだけで、友人の PC には何も送らない。
"""
import argparse
import datetime
import json
import os
import re
import sys

REPO = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
SRC = os.path.join(REPO, "src")
if SRC not in sys.path:
    sys.path.insert(0, SRC)
from flow import retention  # noqa: E402
from ytt import datadir  # noqa: E402

NAME_RE = re.compile(r"^([0-9A-Za-z_-]{1,64})__diag-(\d{13})\.diag\.json$")   # src/friendapp/diag.py の NAME_RE と同じ
KEEP_DAYS = retention.KEEP_DAYS      # 物の終わりの日数
CAP = 1024 * 1024                   # 1 つの読む上限
FOLDER = "診断"


def default_dir():
    """<ホームの設定 intake.folder>/診断(無ければ None)"""
    prefs = os.path.join(datadir.locate("app", SRC), "prefs.json")
    try:
        with open(prefs, encoding="utf-8") as f:
            folder = (json.load(f).get("intake") or {}).get("folder") or ""
    except (OSError, ValueError):
        folder = ""
    return os.path.join(folder, FOLDER) if folder else None


def prune(folder, now_ms):
    """3 日より古い診断を消す -> 消した数(名前の時刻で決める。診断の名前でない物は触らない)"""
    n = 0
    for name in os.listdir(folder):
        m = NAME_RE.match(name)
        if m and now_ms - int(m.group(2)) >= KEEP_DAYS * 86400 * 1000:
            try:
                os.remove(os.path.join(folder, name))
                n += 1
            except OSError:
                pass
    return n


def load(folder):
    """診断を新しい順に [(名前, 中身 dict)](読めない物は {"broken": 理由})"""
    out = []
    for name in os.listdir(folder):
        m = NAME_RE.match(name)
        if not m:
            continue
        p = os.path.join(folder, name)
        try:
            if os.path.getsize(p) > CAP:
                raise ValueError("大きすぎます")
            with open(p, encoding="utf-8-sig") as f:
                d = json.load(f)
            if not isinstance(d, dict):
                raise ValueError("形が違います")
        except (OSError, ValueError) as e:
            d = {"broken": str(e)[:200], "at": int(m.group(2))}
        d.setdefault("at", int(m.group(2)))
        out.append((name, d))
    out.sort(key=lambda x: (x[1].get("at") or 0, x[0]), reverse=True)
    return out


def is_error(d):
    if d.get("broken"):
        return True
    kind = d.get("kind")
    if kind == "run":
        return (d.get("request") or {}).get("state") == "error"
    if kind == "live":
        return (d.get("outcome") or {}).get("state") not in ("arrived", "done")
    return kind not in ("preview", "update")


def live_lines(d, full=False):
    """kind live(ライブの行を閉じた・受付の失敗)の行: 結果・録画の長さ・検出・チャット・採用・書き出し・配信後の追加"""
    o, f = d.get("outcome") or {}, d.get("live") or {}
    out = ["    結果: %s パック %s 本・理由 %s・切り抜きの実行 %s 回(失敗 %s)%s" % (
        o.get("state") or "?", o.get("packs", "?"), o.get("cause") or "-", o.get("clipRuns", "?"), o.get("errors", "?"),
        "・最後の失敗 %s" % o["lastError"][:120] if o.get("lastError") else "")]
    rec, det, pd, wk = f.get("recording") or {}, f.get("detect") or {}, f.get("peaksDoc"), f.get("worker") or {}
    if f:
        out.append("    録画: %s(%s 〜 %s)" % (_sec(rec.get("sec")), rec.get("firstPdt") or "?", rec.get("endedAt") or rec.get("lastPdt") or "?"))
        if pd is None:
            out.append("    検出: 記録なし(peaks.json が無い)")
        else:
            out.append("    検出: 測った %s・候補 %s(枠 %s・控え %s・採用 %s うち自動 %s・上限 %s)・最高点 %s・しきい値 %s%s・チャット %s%s" % (
                _sec(pd.get("measuredSec")), pd.get("peaks"), det.get("frame"), det.get("bench"), det.get("adopted"), det.get("adoptedAuto"), f.get("autoMax"),
                pd.get("maxScore"), pd.get("thr"), "(音だけ)" if pd.get("audioOnly") else "", pd.get("chat"),
                "・%s" % pd["message"][:120] if pd.get("message") else ""))
        out.append("    ワーカー: %s・起動し直し %s・チャットの起動し直し %s%s" % (
            "動いている" if wk.get("running") else "止まっている", wk.get("restarts"), wk.get("chatRestarts"),
            "・%s" % (wk.get("error") or wk.get("message"))[:160] if (wk.get("error") or wk.get("message")) else ""))
        for g in (f.get("givenUp") or [])[-(3 if not full else 10):]:
            out.append("    採用を諦めた: %s〜%s %s" % (g.get("start"), g.get("end"), (g.get("message") or "")[:160]))
        ex = f.get("exports") or {}
        out.append("    書き出し: %s 本 %s" % (ex.get("total", "?"), json.dumps(ex.get("byState") or {}, ensure_ascii=False)))
        for t in (f.get("exportFailures") or [])[:(3 if not full else 10)]:
            out.append("      失敗: %s" % str(t)[:200])
        a = f.get("afterStream")
        out.append("    配信後の追加: %s" % ("%s %s" % (a.get("state"), (a.get("message") or "")[:160]) if a else "なし"))
        if f.get("settings"):
            out.append("    依頼の設定: %s" % json.dumps(f["settings"], ensure_ascii=False))
    return out


def _when(ms):
    try:
        return datetime.datetime.fromtimestamp(int(ms) / 1000).strftime("%m-%d %H:%M:%S")
    except (TypeError, ValueError, OSError):
        return "?"


def _sec(v):
    return "%.0f秒" % v if isinstance(v, (int, float)) and not isinstance(v, bool) else "-"


def lines_of(name, d, full=False):
    """1 件 -> 画面の行(full = 全部の欄)"""
    if d.get("broken"):
        return ["%s  読めません: %s(%s)" % (_when(d.get("at")), d["broken"], name)]
    app, pc = d.get("app") or {}, d.get("pc") or {}
    gpu = (pc.get("gpu") or {}).get("name") if isinstance(pc.get("gpu"), dict) else None
    head = "%s  %-9s %s  版 %s(%s)  %s" % (_when(d.get("at")), d.get("kind"), d.get("requestId") or d.get("source") or "",
                                          app.get("version") or "?", app.get("host") or "", d.get("code") or "")
    out = [head.rstrip(), "    要約: %s" % (d.get("summary") or "")]
    if full or d.get("kind") == "run":
        out.append("    PC: %s / GPU %s / 文字起こし %s" % (pc.get("windows") or "?", gpu or "?", pc.get("device") or "?"))
    st = d.get("stages") or []
    if st:
        out.append("    段: " + "・".join("%s %s%s" % (s.get("key"), _sec(s.get("sec")), "" if s.get("state") in ("done", "skip", "") else "(%s)" % s.get("state"))
                                       for s in st) + "  計 %s" % _sec(d.get("totalSec")))
    for t in d.get("transcribe") or []:
        out.append("    文字起こし: %s %s GPU=%s モデル=%s 音声 %s かかった %s 実時間比 %s" % (
            t.get("device"), t.get("backend") or "", t.get("gpu") or "?", t.get("model") or "?", _sec(t.get("audioSec")), _sec(t.get("wallSec")),
            t.get("ratio") if t.get("ratio") is not None else "?"))
    if d.get("kind") == "live":
        out += live_lines(d, full)
    if d.get("kind") == "preview" or d.get("stage") == "preview":
        out.append("    確認用の動画: %s 本・作れなかった %s 本 %s" % (d.get("count"), d.get("missed"), _sec(d.get("sec"))))
    tools = d.get("tools") or []
    bad = [t for t in tools if t.get("code") or t.get("why")]
    if tools:
        out.append("    道具: %d 回(失敗 %d)" % (len(tools), len(bad)) + ("" if not full else "  " + "・".join("%s=%s" % (t.get("name"), t.get("code")) for t in tools)))
    for t in bad[-3 if not full else None:]:
        out.append("      %s 終了コード %s%s %s" % (t.get("name"), t.get("code"), "(%s)" % t["why"] if t.get("why") else "", _sec(t.get("sec"))))
        for x in (t.get("tail") or [])[-(4 if not full else 20):]:
            out.append("        | %s" % x)
    if "exitCode" in d:
        out.append("    終了コード: %s" % d.get("exitCode"))
    for x in (d.get("tail") or [])[-(6 if not full else 20):]:
        out.append("      | %s" % x)
    if d.get("detail") and (full or is_error(d)):
        det = d["detail"] if full else d["detail"][:400]
        out += ["    詳しく: " + det.replace("\n", "\n            ")]
    if full:
        rest = {k: v for k, v in d.items() if k not in ("v", "kind", "source", "at", "requestId", "app", "pc", "summary", "code", "stages", "transcribe",
                                                       "tools", "tail", "detail", "exitCode", "totalSec", "outcome")}
        if rest:
            out.append("    ほか: %s" % json.dumps(rest, ensure_ascii=False))
    return out


def main(argv=None):
    ap = argparse.ArgumentParser(prog="dev/friend_diag.py", description="友人のアプリから届いた診断の記録を一覧にする")
    ap.add_argument("-n", type=int, default=10, help="件数(新しい順。既定 10)")
    ap.add_argument("--errors", action="store_true", help="失敗だけ")
    ap.add_argument("--live", action="store_true", help="ライブの行の診断(kind live)だけ")
    ap.add_argument("--id", help="1 つの依頼の id の物だけ(全部の欄)")
    ap.add_argument("--json", action="store_true", help="そのまま JSON で")
    ap.add_argument("--dir", help="読む場所(既定 <intake.folder>/診断)")
    ap.add_argument("--keep", action="store_true", help="3 日より古い物を消さない")
    a = ap.parse_args(argv)
    folder = a.dir or default_dir()
    if not folder:
        print("依頼の受付のフォルダ(ホームの設定 intake.folder)が決まっていません。--dir で渡してください", file=sys.stderr)
        return 2
    if not os.path.isdir(folder):
        print("まだ診断が届いていません(%s がありません)" % folder)
        return 0
    if not a.keep:
        n = prune(folder, int(datetime.datetime.now().timestamp() * 1000))
        if n:
            print("3 日より前の診断を %d 件消しました" % n, file=sys.stderr)   # --json の出力に混ぜない
    got = load(folder)
    if a.id:
        got = [g for g in got if g[1].get("requestId") == a.id]
    if a.errors:
        got = [g for g in got if is_error(g[1])]
    if a.live:
        got = [g for g in got if g[1].get("kind") == "live"]
    got = got[:max(1, a.n)] if not a.id else got
    if a.json:
        print(json.dumps([dict(d, file=n) for n, d in got], ensure_ascii=False, indent=1))
        return 0
    if not got:
        print("当てはまる診断はありません(%s)" % folder)
        return 0
    print("診断 %d 件(新しい順。%s)" % (len(got), folder))
    for n, d in got:
        print("\n".join(lines_of(n, d, full=bool(a.id))))
    return 0


if __name__ == "__main__":
    sys.exit(main())
