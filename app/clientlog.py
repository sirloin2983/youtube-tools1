# -*- coding: utf-8 -*-
"""画面(ブラウザ・窓)で起きたエラーの記録(統合計画の段階7-0)。

画面の ui-kit.js(UIKit.report)が、捕まえられなかったエラー(window の error・unhandledrejection)を
入口の POST api/ytt/client-log に送り、ここで作業データの置き場所の app\\logs\\client-errors.jsonl に1行ずつ書く。
入口の画面・取り込んだ3ツールの画面が、同じ1つのファイルに書く(tool に画面の名前)。AI は /api/log?tool=client で末尾を読める。

- 1行 = 1件の JSON(json.dumps が改行・制御文字をエスケープするので、エラーの文が偽の行を作れない)
- 決まった項目だけを、決まった長さで切って書く。画面から来た値は文字列・整数として扱うだけ(解釈しない)
- 1分に PER_MINUTE 件まで(画面の不具合でログが埋まらないように)。超えた分は数えて、次の1分の最初に1行で書く
- MAX_BYTES を超えたら .1 に回して新しく始める(ディスクを使い切らない)
- エラーの文・スタックにはファイルのパスが入ることがある → ログはリポジトリの外(作業データの置き場所)だけに置く
"""
import json
import os
import threading
import time

FILE_NAME = "client-errors.jsonl"
PER_MINUTE = 30
MAX_BYTES = 512 * 1024
KINDS = ("error", "rejection", "report")
TEXT = {"message": 500, "source": 300, "stack": 2000, "page": 300}


def clean(body):
    """画面から来た1件を、決まった項目・長さの辞書にする。message が無ければ ValueError"""
    if not isinstance(body, dict):
        raise ValueError("JSON のオブジェクトを送ってください")
    kind = body.get("kind")
    out = {"kind": kind if kind in KINDS else "report"}
    for k, n in TEXT.items():
        v = body.get(k)
        if isinstance(v, str) and v:
            out[k] = v[:n]
    for k in ("line", "col"):
        v = body.get(k)
        if isinstance(v, int) and not isinstance(v, bool) and 0 < v < 10 ** 7:
            out[k] = v
    if not out.get("message"):
        raise ValueError("message がありません")
    return out


class ClientLog:
    def __init__(self, logs_dir, per_minute=PER_MINUTE, max_bytes=MAX_BYTES, clock=time.time):
        self.path = os.path.join(logs_dir, FILE_NAME)
        self.per_minute, self.max_bytes, self._clock = per_minute, max_bytes, clock
        self._lock = threading.Lock()
        self._start = None
        self._count = 0
        self._dropped = 0

    def record(self, tool, body, version=""):
        """1件を書く。-> 書いたか(上限を超えて書かなかったら False)。body が正しくなければ ValueError"""
        entry = clean(body)
        with self._lock:
            now = self._clock()
            if self._start is None or now - self._start >= 60:
                if self._dropped:
                    self._write({"time": self._stamp(now), "tool": "-", "kind": "dropped", "count": self._dropped,
                                 "message": "上限(1分に %d 件)を超えたので書かなかった件数" % self.per_minute})
                self._start, self._count, self._dropped = now, 0, 0
            if self._count >= self.per_minute:
                self._dropped += 1
                return False
            self._count += 1
            line = {"time": self._stamp(now), "tool": str(tool)[:20]}
            if version:
                line["version"] = str(version)[:20]
            line.update(entry)
            self._write(line)
            return True

    @staticmethod
    def _stamp(t):
        return time.strftime("%Y-%m-%d %H:%M:%S", time.localtime(t))

    def _write(self, obj):
        try:
            os.makedirs(os.path.dirname(self.path), exist_ok=True)
            try:
                if os.path.getsize(self.path) > self.max_bytes:
                    os.replace(self.path, self.path + ".1")
            except OSError:
                pass
            with open(self.path, "a", encoding="utf-8") as f:
                f.write(json.dumps(obj, ensure_ascii=False) + "\n")
        except OSError:
            pass   # 記録できなくても画面の操作は止めない
