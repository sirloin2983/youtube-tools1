#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""作業データの置き場所(統合計画の段階4)の通し確認。本物の入口(app/launch.py)を、以前の場所にデータがある状態で起動する。

1. リポジトリを一時フォルダに写し、以前の場所(各ツールのフォルダの中)に作業データを置く
2. YTT_DATA_DIR=<一時フォルダ>/data で入口を起動 → 3つのツールのデータが <data>/<ツール> へコピーされ、画面(API)から読める
3. 以前の場所のデータは残っている(消さない)。新しい場所で直した内容は、以前の場所に書かれない
4. 入口を止めて起動し直すと、もう写さない(新しい場所で直した内容が残る)
5. ログ・入口の記録も新しい場所に書かれ、リポジトリのフォルダには作業データが増えない

実行(リポジトリ直下): python tools/e2e_datadir.py   (本物の AppData は使わない)
"""
import json
import os
import shutil
import socket
import subprocess
import sys
import tempfile
import time
import urllib.request

REPO = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
IGNORE = shutil.ignore_patterns("__pycache__", ".git", "transcripts", "dataset", "models", "cache", "archive", "work", "exports",
                                "data.json*", "feedback.jsonl*", "registry.json", "config.json", "settings*.json", "*.log",
                                ".running.json", "node_modules", ".runtime", "0old", ".whisper_models", "resolve-ui-test", "logs")
TID = "0123456789ab"


def free_port():
    s = socket.socket()
    s.bind(("127.0.0.1", 0))
    p = s.getsockname()[1]
    s.close()
    return p


def main():
    ok = True

    def check(cond, msg):
        nonlocal ok
        print(("OK   " if cond else "FAIL ") + msg)
        ok = ok and bool(cond)

    tmp = tempfile.mkdtemp(prefix="ytt-datadir-e2e-")
    repo = os.path.join(tmp, "repo")
    data = os.path.join(tmp, "data")
    proc = None
    try:
        for d in ("app", "clip-studio", "transcribe-tool", "cut2resolve", "ytt_core", "ui-kit"):
            shutil.copytree(os.path.join(REPO, d), os.path.join(repo, d), ignore=IGNORE)
        # ---- 以前の場所のデータ
        st, tx = os.path.join(repo, "clip-studio"), os.path.join(repo, "transcribe-tool")
        os.makedirs(os.path.join(st, "cache", "meta"))
        with open(os.path.join(st, "data.json"), "w", encoding="utf-8") as f:
            json.dump({"videos": {}, "version": 1}, f)
        with open(os.path.join(st, "cache", "meta", "abcdefghijk.json"), "w", encoding="utf-8") as f:
            f.write("{}")
        with open(os.path.join(st, "config.json"), "w", encoding="utf-8") as f:
            json.dump({"apiKey": "A" * 39}, f)
        os.makedirs(os.path.join(tx, "transcripts", ".hist", TID))
        doc = {"id": TID, "title": "移す前の文字起こし", "sourcePath": "", "whole": True, "duration": 10, "updatedAt": 1,
               "segments": [{"id": "s1", "start": 0, "end": 1, "text": "以前の場所"}]}
        with open(os.path.join(tx, "transcripts", TID + ".json"), "w", encoding="utf-8") as f:
            json.dump(doc, f, ensure_ascii=False)
        with open(os.path.join(tx, "transcripts", ".hist", TID, "1.json"), "w", encoding="utf-8") as f:
            f.write("{}")
        with open(os.path.join(tx, "settings.json"), "w", encoding="utf-8") as f:
            json.dump({"glossary": "移した用語"}, f, ensure_ascii=False)

        port = free_port()
        env = dict(os.environ, YTT_DATA_DIR=data, YTT_RUNTIME_DIR=os.path.join(tmp, "rt"), STUDIO_FAKE="1", TRANSCRIBE_BACKEND="fake")
        for k in ("STUDIO_HOME", "TRANSCRIBE_DATA_DIR", "TRANSCRIBE_STUDIO_DATA"):
            env.pop(k, None)

        def start():
            p = subprocess.Popen([sys.executable, os.path.join(repo, "app", "launch.py"), "--port", str(port), "--no-open"],
                                 env=env, stdout=subprocess.PIPE, stderr=subprocess.STDOUT, text=True, encoding="utf-8", errors="replace")
            for _ in range(300):
                try:
                    urllib.request.urlopen("http://127.0.0.1:%d/transcribe/api/ping" % port, timeout=1).read()
                    urllib.request.urlopen("http://127.0.0.1:%d/studio/api/ping" % port, timeout=1).read()
                    urllib.request.urlopen("http://127.0.0.1:%d/cut2resolve/api/ping" % port, timeout=1).read()
                    return p
                except Exception:
                    time.sleep(0.1)
            p.kill()
            raise RuntimeError("入口が起動しませんでした")

        def get(path):
            with urllib.request.urlopen("http://127.0.0.1:%d%s" % (port, path), timeout=10) as r:
                return json.loads(r.read())

        def stop(p):
            p.terminate()
            try:
                out, _ = p.communicate(timeout=30)
            except subprocess.TimeoutExpired:
                p.kill()
                out, _ = p.communicate()
            return out

        # ==================== 1回目の起動: コピーする ====================
        proc = start()
        status = get("/api/status")
        check(status.get("dataDir") == data, "入口の /api/status が作業データの置き場所を返す: %s" % status.get("dataDir"))
        check(os.path.isfile(os.path.join(data, "studio", "data.json")) and os.path.isfile(os.path.join(data, "studio", "cache", "meta", "abcdefghijk.json")),
              "スタジオの data.json・cache が新しい場所にコピーされた")
        check(os.path.isfile(os.path.join(data, "studio", "config.json")), "API キー(config.json)もコピーされた")
        check(os.path.isfile(os.path.join(data, "transcribe", "transcripts", ".hist", TID, "1.json")),
              "文字起こしの transcripts(控えの .hist を含む)が新しい場所にコピーされた")
        state = get("/studio/api/state")
        check(state.get("dataDir") == os.path.join(data, "studio"), "スタジオは新しい場所を使っている: %s" % state.get("dataDir"))
        lst = get("/transcribe/api/transcripts")
        items = lst.get("items") if isinstance(lst, dict) else lst
        check(any((i.get("id") == TID) for i in (items or [])), "文字起こしの一覧に、移した文字起こしが出る")
        d = get("/transcribe/api/transcript?id=" + TID)
        check(d.get("segments", [{}])[0].get("text") == "以前の場所", "移した文字起こしを開ける")
        check(os.path.isdir(os.path.join(data, "cut2resolve", "work")) or os.path.isdir(os.path.join(data, "cut2resolve")),
              "cut2resolve の作業用フォルダも新しい場所")
        check(os.path.isfile(os.path.join(data, "app", "logs", "launcher.log")), "入口の記録も新しい場所(app/logs)")
        # 新しい場所で内容を変える(以前の場所には書かれない)
        with open(os.path.join(data, "transcribe", "transcripts", TID + ".json"), "r+", encoding="utf-8") as f:
            nd = json.load(f)
            nd["segments"][0]["text"] = "新しい場所で直した"
            f.seek(0)
            f.truncate()
            json.dump(nd, f, ensure_ascii=False)
        out = stop(proc)
        proc = None
        check("コピーしています" in out and "消しません" in out, "起動の画面に、コピーしたこと・元を消さないことを出す")

        # ==================== 以前の場所は残っている ====================
        with open(os.path.join(tx, "transcripts", TID + ".json"), encoding="utf-8") as f:
            check(json.load(f)["segments"][0]["text"] == "以前の場所", "以前の場所のデータは消さず、変えていない")
        check(os.path.isfile(os.path.join(st, "config.json")), "以前の場所の config.json も残っている")
        stray = [n for n in ("serve.log", "worker.log", ".running.json") if os.path.exists(os.path.join(tx, n))] + \
                [n for n in ("studio.log",) if os.path.exists(os.path.join(st, n))] + \
                [n for n in ("logs",) if os.path.exists(os.path.join(repo, "app", n))] + \
                [n for n in ("work",) if os.path.exists(os.path.join(repo, "cut2resolve", n))]
        check(not stray, "リポジトリのフォルダにログ・作業用のファイルが増えていない: %s" % stray)

        # ==================== 2回目の起動: もう写さない ====================
        proc = start()
        d = get("/transcribe/api/transcript?id=" + TID)
        check(d.get("segments", [{}])[0].get("text") == "新しい場所で直した", "2回目の起動では写し直さない(新しい場所で直した内容が残る)")
        out = stop(proc)
        proc = None
        check("コピーしています" not in out, "2回目の起動ではコピーの表示が出ない")
    finally:
        if proc and proc.poll() is None:
            proc.kill()
        shutil.rmtree(tmp, ignore_errors=True)
    print("ALL PASSED" if ok else "SOME FAILED")
    return 0 if ok else 1


if __name__ == "__main__":
    sys.exit(main())
