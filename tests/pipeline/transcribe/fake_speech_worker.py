"""偽の `speech worker`(tests/pipeline/transcribe/test_haas_speechcpp.py が tx_engines.HaasSpeechCpp.COMMAND に入れる)。
JSON Lines の protocol 4 の ready・chunk・transcribe・end だけ。答えの字 = 区切りの音の長さ(秒)の数と keywords。
環境変数: FAKE_SPEECH_DEVICE(起動の記録の機器の名前・既定は --device の値)・FAKE_SPEECH_DIE(この回目の transcribe の前に終わる。1 回だけ = 印のファイル)・
FAKE_SPEECH_EMPTY(1 = 字なし)・FAKE_SPEECH_VAD(vad の声の区間「始め-終わり,…」)・FAKE_SPEECH_LOG(受けた頼みを 1 行ずつ書くファイル)
    python fake_speech_worker.py worker <model> --device <dev> --threads <n>
"""
import base64
import json
import os
import sys


def main():
    sys.stdout.reconfigure(encoding="utf-8")   # 本物の speech worker と同じく UTF-8 で読んで答える
    sys.stdin.reconfigure(encoding="utf-8")
    args = sys.argv[1:]
    if args and args[0] == "vad":   # 声の区間: 環境変数 FAKE_SPEECH_VAD(「始め-終わり,…」)をそのまま
        regs = [dict(zip(("start", "end"), map(float, x.split("-")))) for x in (os.environ.get("FAKE_SPEECH_VAD") or "").split(",") if x]
        print(json.dumps({"regions": regs}))
        return
    dev = args[args.index("--device") + 1] if "--device" in args else "auto"
    dev = os.environ.get("FAKE_SPEECH_DEVICE") or ("CPU" if dev == "cpu" else dev)
    sys.stderr.write("speech worker: Haas-ja-v1.0 on %s, ready\n" % dev)
    sys.stderr.flush()
    print(json.dumps({"type": "ready", "protocol": 4, "version": "0.10.0", "model": {"name": "Haas-ja-v1.0"}}), flush=True)
    pcm, n = {}, 0
    die = os.environ.get("FAKE_SPEECH_DIE")
    for line in sys.stdin:
        m = json.loads(line)
        if m["type"] == "chunk":
            pcm.setdefault(m["id"], b"")
            pcm[m["id"]] += base64.b64decode(m["pcm"])
            continue
        if m["type"] != "transcribe":
            continue
        n += 1
        if os.environ.get("FAKE_SPEECH_LOG"):
            with open(os.environ["FAKE_SPEECH_LOG"], "a", encoding="utf-8") as f:
                f.write(json.dumps({"id": m["id"], "keywords": m.get("keywords"), "timestamps": m.get("timestamps"), "bytes": len(pcm.get(m["id"], b""))}) + "\n")
        mark = (die or "") + ".done"
        if die and n == int(die.split(":")[0]) and not os.path.exists(mark.split(":", 1)[-1]):
            open(mark.split(":", 1)[-1], "w").close()
            sys.exit(3)
        sec = len(pcm.pop(m["id"], b"")) / 32000.0
        if os.environ.get("FAKE_SPEECH_EMPTY") == "1":
            print(json.dumps({"type": "end", "id": m["id"], "text": "", "tokens": []}), flush=True)
            continue
        kw = (m.get("keywords") or "").replace("\n", "")
        toks = [{"start": 0.0, "end": 0.5, "text": "あ", "p": 0.9}, {"start": 0.5, "end": 1.0, "text": "%d秒" % round(sec), "p": 0.5}]
        if kw:
            toks.append({"start": 1.0, "end": 1.5, "text": kw, "p": 0.8})
        print(json.dumps({"type": "end", "id": m["id"], "text": "".join(t["text"] for t in toks) + "。", "tokens": toks}, ensure_ascii=False), flush=True)


if __name__ == "__main__":
    main()
