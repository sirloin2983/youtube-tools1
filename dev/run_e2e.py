#!/usr/bin/env python3
"""画面テスト(e2e)の一式を 1 本ずつ流して、1 本 1 行(所要秒・OK/FAIL の数)で出す。一式の正はこのファイルの SUITE。

    py -3.10 dev/run_e2e.py                      # 一式(大きな区切りに 1 回。AGENTS.md の「e2e は少なめに」)
    py -3.10 dev/run_e2e.py --only cases         # 組(cases / home / studio / dev / ui-kit)か、名前の一部で絞る
    py -3.10 dev/run_e2e.py --only live_studio --only cases_cut
    py -3.10 dev/run_e2e.py --skip live_          # ライブを触っていないときは重い 2 本(約 7 分)を飛ばす
    py -3.10 dev/run_e2e.py --list               # 一覧だけ
    py -3.10 dev/run_e2e.py --out 結果.json

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

# (組, スクリプト, 追加の引数, 何を確かめるか)。所要秒は 2026-10-11 夜(V1 確かめる V4。一式 19 本 約 13 分)の実測(i9-12900KF)。RS8 C4(0.59.0)で古いスタジオ・編集の画面と、その e2e 18 本
# (編集 15 本・スタジオの e2e_ui 2 回・見本の e2e_review)を消し、確かめの要点を案件の画面の 4 本(組 cases)・e2e_portal・unittest へ移した。
SUITE = [
    # 案件の画面 /cases(src/app/tests/。RS8)
    ("cases", "src/app/tests/e2e_cases.py", [], "案件の画面の殻: 一覧・タブ・URL・キー・② の問い合わせ・引数なしで前の案件・appnav(6 秒)"),
    ("cases", "src/app/tests/e2e_cases_cand.py", [], "候補のパネル: 再生・グラフ・採用・キー・書き出し・時刻の欄・引き出し・まとめて実行・一瞬とつなげる・再生できない配信・片付け(22 秒)"),
    ("cases", "src/app/tests/e2e_cases_proof.py", [], "校正のパネル: 編集の行・キー・保存・切り替え・競合・行の道具・評価用・2 つ目のエンジン・別の読み・声・配信のプレーヤー・3 択(層が正)(約 1 分)"),
    ("cases", "src/app/tests/e2e_cases_cut.py", [], "カット・パックのパネル: 区間・保存・キー・パックの設定・パックを作る・作り直し・zip・2 つの窓の 409・切り替え・区間があるときの校正の行のカット(32 秒)"),
    # 確かめる /check(src/app/tests/。RS8 V1)
    ("cases", "src/app/tests/e2e_check.py", [], "確かめるの殻: 帯・カード 4 種類・キー・Z で戻す・飛ばす・自動で再生と区間で止まる・波形・10 件のまとめ・空・失敗・本物の口で空(13 秒)"),
    # 3 ツールの通し・作業データの置き場所(dev/tests/)
    ("dev", "dev/tests/e2e_pipeline.py", [], "スタジオ → 編集 → cut2resolve の API の通し(Playwright なし)(14 秒)"),
    ("dev", "dev/tests/e2e_datadir.py", [], "作業データを外へ写す(入口を本物で起動)(7 秒)"),
    # 入口(src/home/tests/)
    ("home", "src/home/tests/e2e_portal.py", [], "ホーム(本番と同じ取り込み)・appnav・古い URL の転送・案件の画面の候補/校正/カット・新しい案件と探す設定・案件・次にやること・子プロセスの文字起こし(72 秒)"),
    ("home", "src/home/tests/e2e_autorun.py", [], "まとめて実行(画面と API・起動し直し後の記録)(27 秒)"),
    ("home", "src/home/tests/e2e_window.py", [], "画面のエラーの記録・離れた/戻った・窓で開く(案件の画面)(11 秒)"),
    ("home", "src/home/tests/e2e_keymap.py", [], "共通の再生キーの移行・? の一覧・キーの変更(校正・候補のパネル)(22 秒)"),
    ("home", "src/home/tests/e2e_settings.py", [], "設定の画面 /settings(5 秒)"),
    ("home", "src/home/tests/e2e_intake_ui.py", [], "依頼の受付の画面(4 秒)"),
    ("home", "src/home/tests/e2e_backup_ui.py", [], "バックアップの画面(本物のバックアップ)(6 秒)"),
    ("home", "src/home/tests/e2e_live.py", [], "ライブ(線 D)の入口の API(録画の部品は本物)(8 秒)"),
    ("home", "src/home/tests/e2e_live_studio.py", [], "ライブ: ホームの /#new から録画 → 案件の画面の候補で再生 → マーク → 書き出し・候補(約 3 分)"),
    ("home", "src/home/tests/e2e_live_archive.py", [], "ライブ: 案件の画面の候補でアーカイブの本番版に入れ替え・自動の消去・配信後の全自動(約 4 分)"),
    # スタジオ(src/studio/tests/)・ui-kit
    ("studio", "src/studio/tests/e2e_analyze.py", [], "解析の通し(合成の音声とチャット。Playwright なし)(14 秒)"),
    ("ui-kit", "src/ui-kit/tests/e2e_styleguide.py", [], "ui-kit の見本(部品の動き・版の帯・録画中の札・http)(16 秒)"),
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
    ap.add_argument("--only", action="append", default=[], help="組(cases/home/studio/dev/ui-kit)か名前の一部。複数可")
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
