#!/usr/bin/env python3
"""画面テスト(e2e)の一式を 1 本ずつ流して、1 本 1 行(所要秒・OK/FAIL の数)で出す。一式の正はこのファイルの SUITE。

    py -3.10 dev/run_e2e.py                      # 一式(大きな区切りに 1 回。AGENTS.md の「e2e は少なめに」)
    py -3.10 dev/run_e2e.py --only editor        # 組(editor / home / studio / dev / ui-kit)か、名前の一部で絞る
    py -3.10 dev/run_e2e.py --only live_studio --only edit_cut
    py -3.10 dev/run_e2e.py --skip live_          # ライブを触っていないときは重い 2 本(約 7 分)を飛ばす
    py -3.10 dev/run_e2e.py --list               # 一覧だけ
    py -3.10 dev/run_e2e.py --out 結果.json

リポジトリ直下から流す。各テストは別のプロセス・PYTHONIOENCODING=utf-8・同時に流さない(待ちのあるテストが揺れる)。
一式に入れないもの: src/studio/tests/e2e_review.py(手で見る見本サーバー)・chrome-ext の e2e_fake_studio(Edge で別に)・
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

# (組, スクリプト, 追加の引数, 何を確かめるか)。所要秒は 2026-10-10 の実測(i9-12900KF。31 本で約 18 分、うちライブの 2 本で約 7 分)。
SUITE = [
    # 編集(src/editor/tests/。合わせて約 6 分)
    ("editor", "src/editor/tests/e2e_ui_mounted.py", [], "入口に取り込んだ形: CSP・合言葉・ワーカーの立ち直り・履歴の一覧・パック(23 秒)"),
    ("editor", "src/editor/tests/e2e_edit_tabs.py", [], "2 つのタブ・メニュー・URL の #・題名の行・文字起こしせずに開く(40 秒)"),
    ("editor", "src/editor/tests/e2e_edit_cut.py", [], "2 カット: ドラッグ・吸着・分割・I/O・元に戻す・409・たたき台(55 秒)"),
    ("editor", "src/editor/tests/e2e_edit_pack.py", [], "パック: 設定・見積もり・サムネ案・配信者・中止・30fps(36 秒)"),
    ("editor", "src/editor/tests/e2e_row_editing.py", [], "行の追加・結合・分割・重なり・下書き・Z・画面幅(42 秒)"),
    ("editor", "src/editor/tests/e2e_proofread_keys.py", [], "設定のチェックの即保存・キー・表示・保存の競合・4000 行(26 秒)"),
    ("editor", "src/editor/tests/e2e_proofread_accuracy.py", [], "校正済み・絞り込み・精度のカード(6 秒)"),
    ("editor", "src/editor/tests/e2e_folder_marker_range.py", [], "フォルダ一括・スタジオのマーク・範囲の再認識(7 秒)"),
    ("editor", "src/editor/tests/e2e_eval_set.py", [], "評価用を守る(学習・辞書・再認識・測定・⚙ の評価用フォルダ)(12 秒)"),
    ("editor", "src/editor/tests/e2e_ui_handoff.py", [], "受け渡し ?media= / ?clip=・動画の隣に保存・409・390px の引き出し(17 秒)"),
    ("editor", "src/editor/tests/e2e_edit_voices.py", [], "声を覚える・判別し直す・忘れる(14 秒)"),
    ("editor", "src/editor/tests/e2e_drill.py", [], "評価ドリル・全行をこの人に・話者の自動判別(38 秒)"),
    ("editor", "src/editor/tests/e2e_alt.py", [], "2 つ目のエンジンと YouTube の字幕の候補(15 秒)"),
    ("editor", "src/editor/tests/e2e_fill.py", [], "認識のあとの後処理(別の読み)の札と戻す(7 秒)"),
    ("editor", "src/editor/tests/e2e_follow_scroll.py", [], "再生の追いかけで窓が動かない(8 秒)"),
    # 3 ツールの通し・作業データの置き場所(dev/tests/)
    ("dev", "dev/tests/e2e_pipeline.py", [], "スタジオ → 編集 → cut2resolve の API の通し(Playwright なし)(14 秒)"),
    ("dev", "dev/tests/e2e_datadir.py", [], "作業データを外へ写す(入口を本物で起動)(7 秒)"),
    # 入口(src/home/tests/)
    ("home", "src/home/tests/e2e_portal.py", [], "ホーム(本番と同じ取り込み)・案件・次にやること・子プロセスの文字起こし(59 秒)"),
    ("home", "src/home/tests/e2e_autorun.py", [], "まとめて実行(画面と API・起動し直し後の記録)(28 秒)"),
    ("home", "src/home/tests/e2e_window.py", [], "画面のエラーの記録・離れた/戻った・窓で開く(12 秒)"),
    ("home", "src/home/tests/e2e_keymap.py", [], "共通の再生キーの移行・? の一覧・キーの変更(19 秒)"),
    ("home", "src/home/tests/e2e_settings.py", [], "設定の画面 /settings(5 秒)"),
    ("home", "src/home/tests/e2e_intake_ui.py", [], "依頼の受付の画面(3 秒)"),
    ("home", "src/home/tests/e2e_backup_ui.py", [], "バックアップの画面(本物のバックアップ)(6 秒)"),
    ("home", "src/home/tests/e2e_live.py", [], "ライブ(線 D)の入口の API(録画の部品は本物)(9 秒)"),
    ("home", "src/home/tests/e2e_live_studio.py", [], "ライブ: スタジオの画面(録画 → 再生 → マーク → 書き出し・候補)(約 3 分)"),
    ("home", "src/home/tests/e2e_live_archive.py", [], "ライブ: アーカイブで本番版に入れ替え・自動の消去・配信後の全自動(約 4 分)"),
    # スタジオ(src/studio/tests/)・ui-kit
    ("studio", "src/studio/tests/e2e_analyze.py", [], "解析の通し(合成の音声とチャット。Playwright なし)(15 秒)"),
    ("studio", "src/studio/tests/e2e_ui.py", [], "スタジオの画面 25 場面(単体)(46 秒)"),
    ("studio", "src/studio/tests/e2e_ui.py", ["--mounted"], "同じ 25 場面を入口に取り込んだ形で(CSP・合言葉)(53 秒)"),
    ("ui-kit", "src/ui-kit/tests/e2e_styleguide.py", [], "ui-kit の見本(部品の動き・版の帯・録画中の札・http)(17 秒)"),
]
# リポジトリにあるが一式に入れない e2e(理由は先頭の説明)
NOT_IN_SUITE = {
    "src/studio/tests/e2e_review.py",
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
    ap.add_argument("--only", action="append", default=[], help="組(editor/home/studio/dev/ui-kit)か名前の一部。複数可")
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
