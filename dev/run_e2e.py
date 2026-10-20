#!/usr/bin/env python3
"""画面テスト(e2e)の一式を 1 本ずつ流して、1 本 1 行(所要秒・OK/FAIL の数)で出す。一式の正はこのファイルの SUITE。

e2e は「主な道 1 つに 1 本」(plan/test-review.md): ホーム → 案件・候補 → 採用 → 書き出し・校正・カット → パック・
確かめる・まとめて実行・ライブ・友人の送る / 受け取る・API の通し。キー 1 つ・欄 1 つ・空の状態・文言・はみ出しのような細かい場面は
e2e に足さず、単体(/api・JS の小さな関数)と写真の関所(dev/ui_audit.py)へ。新しい e2e を足す前に、どの道の 1 本に入るかを決める。

    py -3.12 dev/run_e2e.py                      # 一式(大きな区切りに 1 回。AGENTS.md の「e2e は少なめに」)
    py -3.12 dev/run_e2e.py --only cases         # 組(cases / home / studio / dev)か、名前の一部で絞る
    py -3.12 dev/run_e2e.py --only live_studio --only cases_cut
    py -3.12 dev/run_e2e.py --skip live_          # ライブを触っていないときは重い 2 本(約 7 分)を飛ばす
    py -3.12 dev/run_e2e.py --list               # 一覧だけ
    py -3.12 dev/run_e2e.py --out 結果.json

リポジトリ直下から流す。各テストは別のプロセス・PYTHONIOENCODING=utf-8・同時に流さない(待ちのあるテストが揺れる)。
一式に入れないもの: chrome-ext の e2e_fake_studio(Edge で別に)・
friend-apps/holo-colors の e2e_holo_colors(本物のキー入力を送るので 1 本だけで)。dev/tests/test_run_e2e.py が、リポジトリの e2e_*.py が
この一覧か NOT_IN_SUITE のどちらかに必ずあることを確かめる(足した e2e の入れ忘れを止める)。
"""
import argparse
import json
import os
import re
import subprocess
import sys
import time

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
PY = sys.executable

# (組, スクリプト, 追加の引数, 何を確かめるか)。所要秒はほかのテストと同時に流した 1 本ずつの目安(i9-12900KF)。
# e2e は画面の操作(押す → API → 画面が変わる)を道ごとに 1 本で見る。API の拒否・計算の値・保存の細部は単体の持ち物
# (層の分け方 = 保管庫の plan/test-review.md の 8-1)。
SUITE = [
    # 案件の画面 /cases(src/app/tests/。RS8)
    ("cases", "src/app/tests/e2e_cases_cand.py", [], "道 2 候補 → 採用 → 書き出し: 再生・グラフ・採用・キー・時刻の欄・外から来る文字列・まとめて実行・書き出し・書き出したマークのセリフ・一瞬とつなげる・片付けと前回の場所・1720 / 390 の引き出し・再生できない配信(29 秒)"),
    ("cases", "src/app/tests/e2e_cases_proof.py", [], "道 3 校正 → 保存・競合: 編集の行・キー・保存・切り替え・カット・パックのタブの間のキー・タブの素早い切り替え・競合・文字起こし前・配信のプレーヤー・3 択(層が正)・行の道具・つなぐ分ける・全行を校正済み・評価用・2 つ目のエンジン・別の読み・声(約 1 分)"),
    ("cases", "src/app/tests/e2e_cases_cut.py", [], "道 4 カット → パック → zip: 区間・保存・キー・字幕の一覧の残す / カット・パックの設定・パックを作る・作り直しの理由と 3 択・zip・切り替え・行を分けてすぐ校正・区間があるときの校正の行のカット・端を 1 コマ・2 つの窓の 409・文書の競合(32 秒)"),
    # 確かめる /check(src/app/tests/。RS8 V1)
    ("cases", "src/app/tests/e2e_check.py", [], "道 5 確かめる: 帯・カード 6 種類(価値・読み・声・時刻・声ですか・自動カット)・評価のレーン・キー・Z で戻す・飛ばす・自動で再生と区間で止まる・波形・10 件のまとめ・空・失敗・本物の口で空(21 秒)"),
    # 入口(src/app/tests/)
    ("home", "src/app/tests/e2e_portal.py", [], "道 1 ホーム → 新しい案件 → 案件の画面: 本番と同じ取り込み・appnav・調子と片付け・確かめるの枠・動画のパスで開く /cases?v=・引数なしで前の案件・案件の一覧・次にやること・単体の文字起こし・新しい案件(探す設定・探す・URL から入れて候補へ)・依頼の受付の外の文字・自動の切り抜き・すべて終了と切断・子プロセスの文字起こし(約 70 秒)"),
    ("home", "src/app/tests/e2e_autorun.py", [], "道 6 まとめて実行(画面と API・起動し直し後の記録)(27 秒)"),
    ("home", "src/app/tests/e2e_live_studio.py", [], "道 7 ライブ: オフなら今までの解析・ホームの /#new から録画 → 案件の画面の候補で再生 → マーク → 書き出し(絶対時刻)・シーク・離れると止まる・欠け・帯の音量と音を下げる・調子・札から停止・終わった録画の書き出し・配信者・開き直し・サーバーの adopt・配信中の候補と文字(約 1 分 45 秒)"),
    ("home", "src/app/tests/e2e_live_archive.py", [], "道 7 ライブ: 録画に無い区間だけをアーカイブから書き出す(409 の待ち)・録画を消す設定(オフの間は残す・オンでごみ箱)・マークの無い録画の自動の消去・配信後の全自動・帯の案内の文(約 2 分 40 秒)"),
    # 友人の受信箱(src/friendapp/tests/。玄関を一時フォルダに起こす・② と外の口は偽物)
    ("friend", "src/friendapp/tests/e2e_friend_send.py", [], "道 8 友人の送る: 一覧のカード → 区間 2 つ → 送る → 順番待ち・進み具合 → 取り消す(確認)・URL を貼る・失敗の [もう一度送る]・録画中の [録画を取り消す]・Esc・動画を落として 1 つだけ入る(約 13 秒)"),
    ("friend", "src/friendapp/tests/e2e_friend_receive.py", [], "道 9 友人の受け取る: 段・通し番号 → 再生(速度・音量を覚える)→ 受け取る・見送る・戻す・まとめて見送る・判断の記録 v2(約 5 秒)"),
]
# リポジトリにあるが一式に入れない e2e(理由は先頭の説明)
NOT_IN_SUITE = {
    "chrome-ext/yt-studio-time/tests/e2e_fake_studio.py",
    "friend-apps/holo-colors/tests/e2e_holo_colors.py",
}


def label(script, args):
    """一覧に出す名前(スクリプトの名前 + 引数)"""
    return os.path.basename(script)[:-3] + ("" if not args else " " + " ".join(args))


def summary(out):
    """出力から OK/FAIL の数を拾う"""
    oks = len(re.findall(r"^\s*OK\s", out, re.M))
    fails = len(re.findall(r"^\s*(FAIL|NG)\s", out, re.M))
    return "OK %d / FAIL %d" % (oks, fails)


def selected(only, skip=()):
    """--only(組か名前の一部。複数は OR)で絞り、--skip(同じ形)に当たる物を外した一式"""
    rows = []
    for group, script, args, what in SUITE:
        name = label(script, args)
        if only and not any(o == group or o in name for o in only):
            continue
        if any(s == group or s in name for s in skip):
            continue
        rows.append((group, script, args, what, name))
    return rows


def run_one(script, args, timeout=1800):
    """1 本流して (終了コード, 出力, 秒) を返す"""
    env = dict(os.environ)
    env["PYTHONIOENCODING"] = "utf-8"
    t0 = time.time()
    try:
        p = subprocess.run([PY, script] + list(args), cwd=ROOT, env=env, capture_output=True, timeout=timeout)
        out = (p.stdout + p.stderr).decode("utf-8", "replace")
        code = p.returncode
    except subprocess.TimeoutExpired:
        out, code = "timeout", -1
    return code, out, round(time.time() - t0)


def main():
    try:
        sys.stdout.reconfigure(encoding="utf-8")
    except (AttributeError, ValueError):
        pass
    ap = argparse.ArgumentParser(description="e2e の一式を 1 本ずつ流す")
    ap.add_argument("--only", action="append", default=[], help="組(cases/home/studio/dev)か名前の一部。複数可")
    ap.add_argument("--skip", action="append", default=[], help="外す物(同じ形。例: --skip live_ でライブの 2 本を飛ばす)")
    ap.add_argument("--list", action="store_true", help="一覧だけ出す")
    ap.add_argument("--out", default="", help="結果を JSON で書く")
    a = ap.parse_args()
    rows = selected(a.only, a.skip)
    if a.list:
        for group, _s, _a, what, name in rows:
            print("%-7s %-26s %s" % (group, name, what))
        return
    results = []
    for group, script, args, what, name in rows:
        code, out, sec = run_one(script, args)
        row = {"group": group, "name": name, "exit": code, "sec": sec, "summary": summary(out)}
        results.append(row)
        print("%-7s %-26s exit %-3s %5ds  %s" % (group, name, code, sec, row["summary"]), flush=True)
        if code != 0:
            lines = [l for l in out.splitlines() if re.search(r"FAIL|NG |Error|Traceback", l)][:6]
            print("    ↳ " + "\n    ↳ ".join(lines), flush=True)
    total = sum(r["sec"] for r in results)
    bad = [r["name"] for r in results if r["exit"] != 0]
    print("合計 %d 本 %d 分 %d 秒 / 落ちた: %s" % (len(results), total // 60, total % 60, "、".join(bad) if bad else "なし"))
    if a.out:
        with open(a.out, "w", encoding="utf-8") as f:
            json.dump(results, f, ensure_ascii=False, indent=1)
    sys.exit(0 if not bad else 1)


if __name__ == "__main__":
    main()
