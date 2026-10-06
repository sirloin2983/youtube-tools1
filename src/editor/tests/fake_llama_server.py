#!/usr/bin/env python3
"""テスト用の偽の llama-server(tx_engines.LlamaQwen3.COMMAND に [python, このファイル] を入れて使う)。

本物と同じ引数(--host・--port・--api-key・-ngl・-m・--mmproj …)を受け取り、/health と /v1/chat/completions に答える。
合言葉(Authorization: Bearer <--api-key>)が違えば 401。標準エラーには、-ngl が 0 でなければ GPU に載せた行を出す。
答えの文章は「language <言語><asr_text>音声 <秒> 秒」(assistant の先書きがあれば、その言語)。環境変数:
  FAKE_LLAMA_GPU=none     GPU に載せた行を出さない
  FAKE_LLAMA_LOG=パス     受け取った要求(messages)を1行1件の JSON で書き足す
  FAKE_LLAMA_DIE_AFTER=n  n 回答えたら(n+1 回目の要求で)プロセスごと落ちる
"""
import base64
import io
import json
import os
import sys
import wave
from http.server import BaseHTTPRequestHandler, HTTPServer


def main():
    a = sys.argv[1:]
    opt = {}
    i = 0
    while i < len(a):
        if a[i].startswith("-") and i + 1 < len(a) and not a[i + 1].startswith("--"):
            opt[a[i]] = a[i + 1]
            i += 2
        else:
            opt[a[i]] = True
            i += 1
    key, port = str(opt.get("--api-key") or ""), int(opt.get("--port") or 0)
    if opt.get("-ngl", "0") != "0" and os.environ.get("FAKE_LLAMA_GPU") != "none":
        sys.stderr.write("llama_prepare_model_devices: using device Vulkan0 (Fake GPU) (unknown id)\n")
        sys.stderr.write("load_tensors: offloaded 29/29 layers to GPU\n")
    sys.stderr.flush()
    count = [0]
    die_after = int(os.environ.get("FAKE_LLAMA_DIE_AFTER") or -1)

    class H(BaseHTTPRequestHandler):
        def log_message(self, *x):
            pass

        def _auth(self):
            if self.headers.get("Authorization") != "Bearer " + key:
                self.send_response(401)
                self.end_headers()
                return False
            return True

        def _json(self, obj):
            b = json.dumps(obj, ensure_ascii=False).encode("utf-8")
            self.send_response(200)
            self.send_header("Content-Type", "application/json")
            self.send_header("Content-Length", str(len(b)))
            self.end_headers()
            self.wfile.write(b)

        def do_GET(self):
            if self._auth():
                self._json({"status": "ok"})

        def do_POST(self):
            if not self._auth():
                return
            if die_after >= 0 and count[0] >= die_after:
                os._exit(3)
            count[0] += 1
            body = json.loads(self.rfile.read(int(self.headers.get("Content-Length") or 0)).decode("utf-8"))
            if os.environ.get("FAKE_LLAMA_LOG"):
                with open(os.environ["FAKE_LLAMA_LOG"], "a", encoding="utf-8") as f:
                    f.write(json.dumps({"messages": [{"role": m["role"], "text": m["content"] if isinstance(m["content"], str) else "<audio>"}
                                                     for m in body["messages"]], "max_tokens": body.get("max_tokens")}, ensure_ascii=False) + "\n")
            sec = 0.0
            for m in body["messages"]:
                if isinstance(m["content"], list):
                    raw = base64.b64decode(m["content"][0]["input_audio"]["data"])
                    with wave.open(io.BytesIO(raw), "rb") as w:
                        sec = w.getnframes() / float(w.getframerate())
            lang = "Chinese"
            pre = [m for m in body["messages"] if m["role"] == "assistant"]
            if pre:
                lang = pre[-1]["content"].split("language ", 1)[1].split("<", 1)[0]
            self._json({"choices": [{"message": {"content": "language %s<asr_text>音声 %d 秒。" % (lang, round(sec))}}]})

    HTTPServer(("127.0.0.1", port), H).serve_forever()


if __name__ == "__main__":
    main()
