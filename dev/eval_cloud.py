#!/usr/bin/env python3
"""クラウドの文字起こし(OpenAI・ElevenLabs)に評価用の音声を送り、手元のエンジンと同じ物差し(dev/eval_asr.py の採点)で測る道具
(計画 B2 = E1 の「クラウドとの比較を 1 回」。plan/line-b-transcription.md の E1。2026-10-07)。

    python dev/eval_cloud.py run --service openai --model gpt-4o-transcribe-diarize [--label 名前]
        送らない(既定): 対象の文書・秒数・見積もり(USD)・先方の保持の扱いを出して終わる(送る前にユーザーへ見せる)
    python dev/eval_cloud.py run --service openai --model gpt-4o-transcribe-diarize --send [--max-usd 1.0]
        送って測る(ユーザーの確認のあとに --send を付ける。見積もりが --max-usd を超えたら送らない)
    python dev/eval_cloud.py run --service elevenlabs --model scribe_v2 --send
    python dev/eval_cloud.py list        保存してある応答(送り先・モデルごとの本数)
    python dev/eval_cloud.py prices      この道具に書いてある単価の表(申し込みの前に公式の料金ページで確かめる)

  決まり(計画 E1「音声を外へ送る」: 送る前に毎回確認・秒数と見積もり・キーは環境変数・結果は保存して再送しない・終わったら先方の音声を消す):
  - キーは環境変数(OPENAI_API_KEY / ELEVENLABS_API_KEY)か、リポジトリの外の鍵のファイル(--key-file。既定 %USERPROFILE%/youtube-tools-keys.txt に NAME=value の行。
    AI は中身を見ない)。画面・結果・ログに出さない(先方のエラー文にキーの断片が戻ってきても伏せる = scrub)。文字起こしの全文も画面には出さない(数だけ)
  - 応答は <作業データ>/evals/cloud/<送り先>/<モデル>/<文書 id>.json に残し、あれば再送しない(採点のやり直し・別の数え方は送らずにできる)。
    文書の範囲(start・end)か boost が変わっていたら古い応答は使わない(送り直しになるので --send が要る)
  - 送る音声は手元のエンジンと同じ 16kHz モノラルの wav(editor の extract_audio。boost も設定どおり)。ヒント(用語集・prompt・keyterms)は渡さない(評価用はヒントなしの条件)
  - 先方の保持: OpenAI の /v1/audio/transcriptions は「保持なし・学習に使わない」(2026-10-07 の developers.openai.com の your-data)。
    ElevenLabs は既定で履歴に残る(Zero Retention は Enterprise だけ)ので、応答の transcription_id を DELETE で消す(--keep-remote で残す)。
    消せなかったときは応答を控えに残したうえで知らせる(結果の meta.cloud.remoteKept に数える)
  - 結果は eval_asr.py と同じ形(schema youtube-tools-asr-eval/v1)で <作業データ>/evals/asr/<日時>_<名前>.json に保存する
    → `python dev/eval_asr.py compare 手元の結果.json クラウドの結果.json` がそのまま使える。行の後処理の印(meta.post)は手元と違うので compare が注意を出す(想定どおり)
  - 行の時刻: diarized_json(OpenAI の *-diarize)・verbose_json(whisper-1)は区間の時刻、ElevenLabs は単語の時刻から行を組む(話者が変わる・0.6 秒以上の間・12 秒で区切る)。
    時刻の無いモデル(gpt-4o-transcribe・gpt-4o-mini-transcribe・gpt-transcribe)は文書全体を 1 行にする = まとまりごとの内訳・重なりの数字は意味が無い。
    **時刻によらない CER(summary.docText)で比べる**(手元の表の「時刻によらない CER」の列)
  - 作業データは読むだけ(文書は書き換えない)。送るのは評価用(--source eval・確かめ済み)の文書だけが既定。普段の文書を送るときは --source を自分で付ける
"""
import argparse
import json
import math
import os
import re
import shutil
import sys
import tempfile
import time
import urllib.error
import urllib.parse
import urllib.request
import uuid

HERE = os.path.dirname(os.path.abspath(__file__))
if HERE not in sys.path:
    sys.path.insert(0, HERE)
import _evalcommon as C  # noqa: E402  共通の部品(作業データの場所・保存・editor の読み込み)
import eval_asr as E  # noqa: E402  文書の選び方・採点・まとめ・表示(同じ物差しで測るため)
from ytt import fsio  # noqa: E402

# 単価(USD / 分。2026-10-07 に公式の料金ページで確認。申し込みの前にもう 1 度見る)
#   OpenAI: developers.openai.com/api/docs/pricing(gpt-4o-transcribe は音声トークン $2.50/M = 目安 $0.006/分。whisper-1 は $0.006/分)
#   ElevenLabs: elevenlabs.io/pricing/api(Scribe v2 = $0.22/時間 = $0.00367/分。全プラン同じ)
SERVICES = {
    "openai": {
        "url": "https://api.openai.com/v1/audio/transcriptions", "keyEnv": "OPENAI_API_KEY", "keyHeader": "Authorization", "keyPrefix": "Bearer ",
        "models": {"gpt-4o-transcribe": 0.006, "gpt-4o-mini-transcribe": 0.003, "gpt-4o-transcribe-diarize": 0.006, "gpt-transcribe": 0.0045, "whisper-1": 0.006},
        "retention": "音声・文字は保持なし(abuse monitoring の記録も無し)・学習に使わない(API の既定)。消す操作は要らない",
        "maxBytes": 25 * 1024 * 1024},
    "elevenlabs": {
        "url": "https://api.elevenlabs.io/v1/speech-to-text", "keyEnv": "ELEVENLABS_API_KEY", "keyHeader": "xi-api-key", "keyPrefix": "",
        "models": {"scribe_v2": 0.22 / 60, "scribe_v1": 0.22 / 60},
        "retention": "既定で先方の履歴に残る(Zero Retention は Enterprise だけ)。応答の transcription_id をこの道具が DELETE で消す(--keep-remote で残す)",
        "deleteUrl": "https://api.elevenlabs.io/v1/speech-to-text/transcripts/%s",
        "maxBytes": 2 * 1024 * 1024 * 1024},
}
LANGUAGE = "ja"      # 送り先に伝える言語(手元の測定と同じ日本語)
WORD_GAP = 0.6       # ElevenLabs の単語の時刻から行を組むとき、この秒以上の間で区切る
ROW_MAX_SEC = 12.0   # 同上。1 行がこの長さを超えたら区切る
RETRY_WAIT = 5       # 429・5xx のときに待つ秒(1 回だけやり直す)
TIMEOUT = 600        # 1 本の要求の上限(秒)
YEN_PER_USD = 150    # 見積もりの円換算(目安。申し込みの前に為替を見直す)
PRICES_SAMPLE_MIN = 16   # prices の「何分で いくら」の分(評価用の定点の量の目安 = 約 16 分)
POST_NONE = {"clip": False, "mergeRepeats": False, "pullEnds": False, "joinGap": None}   # クラウドの行には editor の後処理をかけない(compare が注意を出す = 想定どおり)
DEFAULT_KEY_FILE = os.path.join(os.path.expanduser("~"), "youtube-tools-keys.txt")      # 環境変数が無いときの鍵のファイル(リポジトリの外。.gitignore に頼らない)


# ---------------------------------------------------------------- 要求の形

def request_fields(service, model):
    """送り先ごとの multipart の項目(file 以外)。ヒント(prompt・keyterms)は渡さない"""
    if service == "openai":
        f = {"model": model, "language": LANGUAGE}
        if model.endswith("-diarize"):
            f.update({"response_format": "diarized_json", "chunking_strategy": "auto"})   # 30 秒より長い音声は chunking_strategy が要る
        elif model == "whisper-1":
            f.update({"response_format": "verbose_json", "timestamp_granularities[]": "segment"})
        else:
            f["response_format"] = "json"   # gpt-4o-transcribe・gpt-4o-mini-transcribe・gpt-transcribe は時刻を返さない
        return f
    return {"model_id": model, "language_code": LANGUAGE, "diarize": "true", "timestamps_granularity": "word", "tag_audio_events": "false"}


def timing_kind(service, model):
    """応答の時刻の種類: segments(区間)/ words(単語)/ none(文書全体を 1 行)"""
    if service == "elevenlabs":
        return "words"
    return "segments" if (model.endswith("-diarize") or model == "whisper-1") else "none"


def multipart(fields, filename, blob, content_type="audio/wav"):
    """multipart/form-data の本体 -> (Content-Type, bytes)。標準ライブラリだけで組む(requests に頼らない)"""
    boundary = "----ytt-eval-cloud-" + uuid.uuid4().hex
    parts = []
    for k, v in fields.items():
        parts.append(('--%s\r\nContent-Disposition: form-data; name="%s"\r\n\r\n%s\r\n' % (boundary, k, v)).encode("utf-8"))
    parts.append(('--%s\r\nContent-Disposition: form-data; name="file"; filename="%s"\r\nContent-Type: %s\r\n\r\n' % (boundary, filename, content_type)).encode("utf-8"))
    parts.append(blob)
    parts.append(("\r\n--%s--\r\n" % boundary).encode("utf-8"))
    return "multipart/form-data; boundary=" + boundary, b"".join(parts)


def http_json(method, url, headers, body=None, content_type=None, timeout=TIMEOUT):
    """-> (status, JSON か {"error": 本文の先頭})。キーはヘッダーにだけ入れ、どこにも出さない。テストはこの関数を差し替える"""
    req = urllib.request.Request(url, data=body, method=method)
    for k, v in headers.items():
        req.add_header(k, v)
    if content_type:
        req.add_header("Content-Type", content_type)
    try:
        with urllib.request.urlopen(req, timeout=timeout) as r:
            raw = r.read()
            return r.status, (json.loads(raw.decode("utf-8")) if raw.strip() else {})
    except urllib.error.HTTPError as e:
        raw = e.read()
        try:
            return e.code, json.loads(raw.decode("utf-8"))
        except ValueError:
            return e.code, {"error": raw.decode("utf-8", "replace")[:500]}


def auth_headers(svc, key):
    return {svc["keyHeader"]: svc["keyPrefix"] + key, "Accept": "application/json"}


def scrub(text, key):
    """エラーの文からキーを伏せる。先方が 401 の本文に、受け取ったキーを一部だけ伏せて(sk-proj-****abcd のように)返すことがあるので、
    そのままの値に加えて sk- / sk_ で始まる形も消す。画面・結果・ログにキーの断片も出さない約束のため"""
    if key:
        text = text.replace(key, "***")
    return re.sub(r"\bsk[-_][\w*-]{4,}", "sk-***", text)


def send_audio(svc, model, key, blob):
    """音声を 1 本送る -> (応答の JSON, かかった秒)。429・5xx は RETRY_WAIT 秒待って 1 回だけやり直す。失敗は RuntimeError(本文の先頭だけ。キーは伏せる)"""
    ctype, body = multipart(request_fields(svc["id"], model), "a.wav", blob)
    t0 = time.monotonic()
    status, resp = http_json("POST", svc["url"], auth_headers(svc, key), body, ctype)
    if status == 429 or status >= 500:
        time.sleep(RETRY_WAIT)
        status, resp = http_json("POST", svc["url"], auth_headers(svc, key), body, ctype)
    if status != 200:
        raise RuntimeError("HTTP %s: %s" % (status, scrub(json.dumps(resp, ensure_ascii=False), key)[:300]))
    return resp, time.monotonic() - t0


def delete_remote(svc, key, remote_id):
    """先方に残った文字起こしを消す(ElevenLabs の transcription_id)-> {"id", "status", "ok"}。消す口の無い送り先・id の無い応答なら None。
    通信が切れた・応答が読めないときも例外にせず status 0・ok False(+ error)で返す(送って課金したあとなので、応答の控えを失わない)"""
    if not svc.get("deleteUrl") or not remote_id:
        return None
    url = svc["deleteUrl"] % urllib.parse.quote(str(remote_id), safe="")
    try:
        status, _resp = http_json("DELETE", url, auth_headers(svc, key))
    except (OSError, ValueError) as e:   # URLError・タイムアウトは OSError / JSON でない本文は ValueError
        return {"id": str(remote_id), "status": 0, "ok": False, "error": scrub(str(e), key)[:200]}
    return {"id": str(remote_id), "status": status, "ok": status in (200, 204, 404)}


# ---------------------------------------------------------------- 応答 -> 行(editor の original と同じ形: start・end・text。時刻は元の動画の秒)

def _row(start, end, text, speaker=None, lp=None):
    r = {"start": round(float(start), 2), "end": round(float(end), 2), "text": str(text or "").strip()}
    if speaker not in (None, ""):
        r["speaker"] = str(speaker)
    if isinstance(lp, (int, float)):
        r["avg_logprob"] = round(float(lp), 4)
    return r


def rows_from_words(words, offset):
    """ElevenLabs の words(text・start・end・type・speaker_id)から行を組む。type が word のものだけ(spacing・audio_event は捨てる)。
    話者が変わる・WORD_GAP 以上の間・ROW_MAX_SEC を超えたら区切る。日本語なので語はそのままつなぐ(空白を入れない)"""
    rows, cur = [], None
    for w in words:
        if not isinstance(w, dict) or w.get("type", "word") != "word" or not str(w.get("text") or "").strip():
            continue
        a, b = w.get("start"), w.get("end")
        a = a if isinstance(a, (int, float)) else None
        b = b if isinstance(b, (int, float)) else a
        spk = w.get("speaker_id")
        new = cur is None or (cur["spk"] != spk) or (a is not None and cur["end"] is not None and (a - cur["end"] >= WORD_GAP or a - cur["start"] >= ROW_MAX_SEC))
        if new:
            if cur:
                rows.append(cur)
            cur = {"start": a, "end": b, "text": "", "spk": spk}
        cur["text"] += str(w["text"]).strip()
        if b is not None:
            cur["end"] = b if cur["end"] is None else max(cur["end"], b)
        if cur["start"] is None:
            cur["start"] = a
    if cur:
        rows.append(cur)
    out, last = [], 0.0
    for r in rows:
        a = r["start"] if r["start"] is not None else last
        b = r["end"] if r["end"] is not None else a
        last = max(last, b)
        out.append(_row(offset + a, offset + b, r["text"], r["spk"]))
    return out


def rows_from(service, model, resp, offset, audio_sec):
    """応答 -> 行。segments(start・end・text・speaker・avg_logprob)があればそれ、ElevenLabs は words、どちらも無ければ text を文書全体の 1 行に"""
    if service == "elevenlabs":
        return rows_from_words(resp.get("words") or [], offset)
    segs = resp.get("segments")
    if isinstance(segs, list) and segs and timing_kind(service, model) == "segments":
        rows = [_row(offset + float(s.get("start") or 0), offset + float(s.get("end") or s.get("start") or 0), s.get("text"), s.get("speaker"), s.get("avg_logprob"))
                for s in segs if isinstance(s, dict)]
        return [r for r in rows if r["text"]]
    text = str(resp.get("text") or "").strip()
    return [_row(offset, offset + audio_sec, text)] if text else []


# ---------------------------------------------------------------- 応答の控え(<作業データ>/evals/cloud/<送り先>/<モデル>/<文書 id>.json)

def cache_dir(data, service, model):
    return os.path.join(data, "evals", "cloud", service, C.label_name(model, None))


def audio_span(S, doc, data, boost):
    """文書の音声の出どころ(eval_asr.recognize_doc と同じ順: 元の動画 → 保管の full.flac。今ある保管データだけ。保管の書き手は 10-10 に消した)-> (extract_audio の spec, 行の時刻の基準の秒, 出どころの名前)"""
    return C.audio_span(S, doc, data, boost=boost)


def span_key(spec):
    return {"start": round(float(spec["start"] or 0), 3), "end": (round(float(spec["end"]), 3) if spec["end"] else None), "boost": bool(spec.get("boost"))}


def load_cache(path, spec):
    """控えがあり、文書の範囲と boost が同じならその応答。違えば None(送り直し)"""
    c = C.read_json(path, None, C.DOC_BYTES)
    if not isinstance(c, dict) or not isinstance(c.get("response"), dict) or c.get("span") != span_key(spec):
        return None
    return c


def save_cache(path, rec):
    """応答の控えを書く(フォルダは必要になったときに作る。書きかけを残さない)"""
    fsio.write_json(path, rec, indent=1)


def doc_seconds(S, spec):
    """送る音声の長さの目安(秒)。文書に end があれば end − start、無ければ ffprobe で測った長さ − start(見積もりに使う。取り出さない)"""
    if spec["end"]:
        return max(0.0, float(spec["end"]) - float(spec["start"] or 0))
    total = S.media_duration(spec["sourcePath"]) or 0.0
    return max(0.0, total - float(spec["start"] or 0))


def extract_wav(S, spec):
    """音声を 16kHz モノラルの wav に取り出して bytes で返す(一時フォルダは消す)-> (bytes, 秒)"""
    job = C.fake_job()
    tmp = tempfile.mkdtemp(prefix="eval_cloud_wav_")
    wav = os.path.join(tmp, "a.wav")
    try:
        S.extract_audio(job, spec, wav)
        sec = S.media_duration(wav) or 0.0
        with open(wav, "rb") as f:
            return f.read(), sec
    finally:
        shutil.rmtree(tmp, ignore_errors=True)


# ---------------------------------------------------------------- run

def resolve_model(service, model):
    """--model(省略なら送り先の表の最初のモデル)-> モデル名。ほかの送り先の表にあるモデルを選んでいたら止める(組み合わせの間違い)。
    どの表にも無いモデルは新しいモデルを試す場合があるので通す(単価が分からないことは cmd_run が知らせる)"""
    if not model:
        return next(iter(SERVICES[service]["models"]))
    if model not in SERVICES[service]["models"]:
        for other, svc in SERVICES.items():
            if other != service and model in svc["models"]:
                raise SystemExit("モデル %s は %s のモデルです(%s の表には無い)。--service %s を付けてください" % (model, other, service, other))
    return model


def estimate_usd(items, price):
    """items の音声の長さ(秒)の合計の見積もり(USD)"""
    return sum(i["sec"] for i in items) / 60 * price


def plan_lines(svc, model, items, todo, price):
    """送る前に見せる一覧(文書・秒・控えの有無)と合計・見積もり。-> 表示する行の一覧"""
    lines = ["== 送り先 %s / モデル %s / 単価 $%.4f/分 ==" % (svc["id"], model, price), "先方の保持: " + svc["retention"]]
    for it in items:
        lines.append("  %s %5.1f 秒  %s  %s" % (it["doc"]["id"], it["sec"], "控えあり(送らない)" if it["cached"] else "送る", str(it["doc"].get("title") or "")[:30]))
    est = estimate_usd(todo, price)
    lines.append("文書 %d 本・%.1f 分(うち送るのは %d 本・%.1f 分)・見積もり $%.3f(約 %.0f 円 @%d)"
                 % (len(items), sum(i["sec"] for i in items) / 60, len(todo), sum(i["sec"] for i in todo) / 60, est, est * YEN_PER_USD, YEN_PER_USD))
    if todo:
        lines.append("注意: 評価用の音声(配信者など他人の声を含む)を外へ送ります。送るには --send(ユーザーの確認のあと)")
    return lines


def send_all(S, svc, model, key, todo, keep_remote):
    """送る本(todo)を順に送って控えに残す。失敗は本ごとに記録して続ける -> 失敗の一覧"""
    failed = []
    for n, it in enumerate(todo, 1):
        d = it["doc"]
        print("(%d/%d) %s 送信 …" % (n, len(todo), d["id"]), flush=True)
        try:
            blob, sec = extract_wav(S, it["spec"])
            if len(blob) > svc["maxBytes"]:
                raise RuntimeError("音声が大きすぎます(%d MB。上限 %d MB)" % (len(blob) // 1048576, svc["maxBytes"] // 1048576))
            resp, wall = send_audio(svc, model, key, blob)
        except Exception as e:   # 1 本の失敗で全部を止めない(残りの本は送る。失敗は数に入れない)
            msg = scrub(str(e), key)[:200]
            print("   とばしました: %s" % msg)
            failed.append({"id": d["id"], "error": msg})
            continue
        rec = {"schema": "youtube-tools-cloud-asr/v1", "service": svc["id"], "model": model, "doc": d["id"], "at": int(time.time() * 1000),
               "span": span_key(it["spec"]), "audioSec": round(sec, 2), "wallSec": round(wall, 2), "bytes": len(blob),
               "fields": request_fields(svc["id"], model), "response": resp, "remote": None}
        if not keep_remote:
            rec["remote"] = delete_remote(svc, key, resp.get("transcription_id"))
            if rec["remote"] and not rec["remote"]["ok"]:
                print("   注意: 先方の文字起こしを消せませんでした(%s)。先方の画面で消してください"
                      % (("HTTP %s" % rec["remote"]["status"]) if rec["remote"]["status"] else rec["remote"].get("error") or "通信エラー"))
        save_cache(it["cache"], rec)
        it["cached"] = rec
        print("   %.1f 秒の音声 / %.1f 秒(行 %d)" % (sec, wall, len(rows_from(svc["id"], model, resp, 0.0, sec))))
    return failed


def score_all(S, svc, model, items, docs, terms, args, data, sel, failed):
    """控えのある本を採点して、eval_asr の run と同じ形の結果にまとめる"""
    groups, nosub, per_doc, audio_sec, wall_sec = [], {}, [], 0.0, 0.0
    kind = timing_kind(svc["id"], model)
    for it in items:
        c = it["cached"]
        if not c:
            continue
        d = it["doc"]
        rows = rows_from(svc["id"], model, c["response"], it["offset"], c.get("audioSec") or it["sec"])
        groups += E.score_doc(S, d, rows, terms, flag_from="hyp")
        nosub[d["id"]] = E.doc_nosub(S, d, rows)
        audio_sec += c.get("audioSec") or 0.0
        wall_sec += c.get("wallSec") or 0.0
        per_doc.append({"id": d["id"], "audioSec": c.get("audioSec"), "wallSec": c.get("wallSec"), "audio": it["where"], "rows": len(rows),
                        "sentAt": c.get("at"), "remote": c.get("remote")})
    per_doc += failed
    done = {p["id"] for p in per_doc if not p.get("error")}
    price = svc["models"].get(model)
    engine = {"engine": "cloud:" + svc["id"], "engineVersion": "", "model": model, "device": "cloud",
              "settings": {"language": LANGUAGE, "boost": bool(items[0]["spec"].get("boost")) if items else False, "timing": kind, "fields": request_fields(svc["id"], model)},
              "glossary": [], "context": "none", "hintFree": True}
    cloud = {"service": svc["id"], "model": model, "pricePerMin": price, "estimateUsd": round(audio_sec / 60 * (price or 0), 4), "timing": kind,
             "remoteDeleted": sum(1 for p in per_doc if (p.get("remote") or {}).get("ok")),
             "remoteKept": sum(1 for p in per_doc if p.get("remote") and not p["remote"].get("ok"))}
    meta = E.base_meta("run", args, docs, data, sel)
    meta.update({"engine": engine, "audioSec": round(audio_sec, 2), "wallSec": round(wall_sec, 2), "loadSec": 0.0, "peakMemMB": None, "post": dict(POST_NONE),
                 "perDoc": per_doc, "failed": len(failed), "cloud": cloud})
    summary = E.summarize(groups, [d for d in docs if d["id"] in done], S, {"engine": engine["engine"], "model": model}, None, nosub)
    return {"meta": meta, "summary": summary, "groups": groups, "terms": terms}


def load_key(svc, key_file):
    """キー -> (値, 出どころの名前)。環境変数 keyEnv が先。無ければ --key-file(NAME=value の行。リポジトリの外に置く。AI は中身を見ない)の同じ名前の行。値はどこにも出さない"""
    key = os.environ.get(svc["keyEnv"]) or ""
    if key.strip():
        return key.strip(), "環境変数 " + svc["keyEnv"]
    if key_file and os.path.isfile(key_file):
        try:
            with open(key_file, encoding="utf-8-sig", errors="replace") as f:   # 日本語のコメントが別の文字コードでも、キーの行(ASCII)は読む
                for line in f:
                    k, _sep, v = line.strip().partition("=")
                    if k.strip() == svc["keyEnv"] and v.strip():
                        return v.strip().strip('"').strip("'"), "鍵のファイル"
        except OSError:   # 読めないファイルは「キーが無い」と同じに扱う(呼び出し側が置き方を案内する)
            pass
    return "", ""


def collect_items(S, docs, cdir, data, boost):
    """文書ごとの送る単位(音声の範囲・控え・秒数)を組む -> (items, 音声が見つからず測れない文書の失敗の一覧)"""
    items, failed = [], []
    for d in docs:
        try:
            spec, offset, where = audio_span(S, d, data, boost)
        except RuntimeError as e:
            failed.append({"id": d["id"], "error": str(e)})
            continue
        path = os.path.join(cdir, d["id"] + ".json")
        items.append({"doc": d, "spec": spec, "offset": offset, "where": where, "cache": path, "cached": load_cache(path, spec), "sec": doc_seconds(S, spec)})
    return items, failed


def cmd_run(S, args, data):
    svc = dict(SERVICES[args.service], id=args.service)
    model = resolve_model(args.service, args.model)
    price = svc["models"].get(model)
    if price is None:
        if args.send:   # 単価が無いと --max-usd の上限が効かない = 送らない(見積もりの表だけ出す)
            raise SystemExit("モデル %s の単価はこの道具に無いので --send できません(SERVICES の models に単価を足してから。公式の料金ページで確かめること)" % model)
        print("注意: モデル %s の単価はこの道具に無い(見積もりは $0 = --max-usd の上限も効かない。--send は断る)。公式の料金ページで確かめること" % model)
        price = 0.0
    settings = C.read_json(os.path.join(data, "settings.json"), {}, kind=dict)
    boost = (settings.get("boost") is True) if args.boost is None else args.boost == "on"
    docs, sel = E.select_docs(data, args)
    if not docs:
        raise SystemExit("測れる文書がありません(校正済みの行がある評価用の文書)")
    items, failed = collect_items(S, docs, cache_dir(data, svc["id"], model), data, boost)
    todo = [i for i in items if not i["cached"]]
    for line in plan_lines(svc, model, items, todo, price):
        print(line)
    if todo:
        if not args.send:
            return None
        key, key_from = load_key(svc, args.key_file)
        if not key:
            raise SystemExit("キーがありません。環境変数 %s か、鍵のファイル %s に「%s=…」の行を置いてください(画面・結果には出しません)"
                             % (svc["keyEnv"], args.key_file, svc["keyEnv"]))
        print("キー: " + key_from)
        est = estimate_usd(todo, price)
        if est > args.max_usd:
            raise SystemExit("見積もり $%.3f が上限 --max-usd %.2f を超えています。送りません" % (est, args.max_usd))
        failed += send_all(S, svc, model, key, todo, args.keep_remote)
    if not any(i["cached"] for i in items):
        raise SystemExit("採点できる応答がありません")
    terms = E.name_terms(S, settings)
    res = score_all(S, svc, model, items, docs, terms, args, data, sel, failed)
    if timing_kind(svc["id"], model) == "none":
        print("※ このモデルは時刻を返さないので文書全体を 1 行にしました。まとまりごとの内訳・重なりの数字は意味が無い。「時刻によらない CER」で比べること")
    if failed:
        print("注意: %d 本は送れず、数に入っていません(比べるときは同じ文書で比べること)" % len(failed))
    return res


def cmd_list(data):
    """保存してある応答の送り先・モデルごとの本数 -> [(送り先, モデル, 本数)]"""
    root = os.path.join(data, "evals", "cloud")
    rows = []
    for svc in sorted(os.listdir(root)) if os.path.isdir(root) else []:
        svc_dir = os.path.join(root, svc)
        for model in sorted(os.listdir(svc_dir)) if os.path.isdir(svc_dir) else []:
            d = os.path.join(svc_dir, model)
            if os.path.isdir(d):
                n = len([f for f in os.listdir(d) if f.endswith(".json")])
                rows.append((svc, model, n))
                print("%-12s %-28s %3d 本" % (svc, model, n))
    if not rows:
        print("保存してある応答はありません(%s)" % root)
    return rows


def cmd_prices():
    for sid, svc in SERVICES.items():
        for m, p in svc["models"].items():
            print("%-12s %-28s $%.4f/分  %d 分で $%.2f" % (sid, m, p, PRICES_SAMPLE_MIN, p * PRICES_SAMPLE_MIN))
        print("    保持: " + svc["retention"])
    return SERVICES


def usd_limit(text):
    """--max-usd の値(argparse の type)。0 以上の有限の数だけ。負の数・nan・inf だと「超えたら送らない」の比較が壊れる(nan との比較はいつも偽)"""
    try:
        v = float(text)
    except ValueError:
        raise argparse.ArgumentTypeError("数で指定してください: %r" % text)
    if not math.isfinite(v) or v < 0:
        raise argparse.ArgumentTypeError("0 以上の数で指定してください: %r" % text)
    return v


def main(argv=None):
    p = argparse.ArgumentParser(description="クラウドの文字起こしに評価用の音声を送って、手元と同じ物差しで測る(送る前に見積もり。作業データは読むだけ)")
    p.add_argument("mode", choices=("run", "list", "prices"))
    p.add_argument("--service", choices=tuple(SERVICES), default="openai")
    p.add_argument("--model", help="送り先のモデル(openai: gpt-4o-transcribe / gpt-4o-transcribe-diarize / gpt-4o-mini-transcribe / gpt-transcribe / whisper-1。elevenlabs: scribe_v2)")
    p.add_argument("--send", action="store_true", help="実際に送る(付けなければ見積もりだけ。控えのある本は付けても送らない)")
    p.add_argument("--max-usd", dest="max_usd", type=usd_limit, default=1.0, help="見積もりがこれ(USD。0 以上)を超えたら送らない(既定 1.0)")
    p.add_argument("--keep-remote", dest="keep_remote", action="store_true", help="先方に残った文字起こしを消さない(ElevenLabs)")
    p.add_argument("--key-file", dest="key_file", default=DEFAULT_KEY_FILE,
                   help="環境変数が無いときに読む鍵のファイル(NAME=value の行。既定 %%USERPROFILE%%\\youtube-tools-keys.txt。リポジトリの外に置く)")
    E.add_select_args(p, "結果に付ける名前(既定 cloud-<送り先>-<モデル>)", "結果を保存しない(応答の控えは送ったときに残る)")
    p.add_argument("--boost", choices=("on", "off"), help="小さい声の持ち上げ(既定は設定どおり。手元の測定と同じにする)")
    args = p.parse_args(argv)
    if args.mode == "prices":   # 作業データは要らない
        return cmd_prices()
    args.docs = C.split_ids(args.docs)
    data = E.real_data_dir(args.data)
    if args.mode == "list":
        return cmd_list(data)
    args.model = resolve_model(args.service, args.model)   # 送り先と合わないモデルは、作業データを読む前に止める
    args.label = args.label or "cloud-%s-%s" % (args.service, args.model)
    S = C.load_serve()
    res = cmd_run(S, args, data)
    if res is None:
        print("送っていません(見積もりだけ)。")
        return None
    E.print_summary(res)
    C.report_saved(res, not args.no_save, data, "asr", "_" + C.label_name(res["meta"].get("label") or "cloud"))
    return res


if __name__ == "__main__":
    C.utf8_stdout()
    main()
