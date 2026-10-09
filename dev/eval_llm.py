#!/usr/bin/env python3
"""LLM の後処理(提案 P18。plan/llm-postfix.md)が効くかを、確かめ済みの評価用の文書で先に測る道具。編集にはまだ入れない(効いたら入れる)。

    python dev/eval_llm.py [--docs id,id] [--limit 30] [--dry] [--label 名前] [--no-save]

- 作業データは**読むだけ**(文字起こしの transcripts/<id>.json・<id>.asr.json)。結果は 文字起こしの作業データの evals/asr/<日時>_llm-base.json と _llm-on.json
  (dev/eval_asr.py compare でそのまま比べられる形)と、提案の中身 evals/llm/<日時>.json に残す(--no-save で残さない)
- 対象: dev/eval_asr.py と同じ選び方(既定は評価用の確かめ済みだけ)。機械の出力 original(評価用には辞書・後処理が当たっていない)に LLM の直しを当てる前と後を、
  eval_asr の採点(score_doc・summarize = 画面の精度の測定と同じ規則)で比べ、最後に compare の対の差(95% の範囲)を出す
- 流れ(plan/llm-postfix.md の 1):
  1. 選ぶ(pick_doc): 疑わしい所だけ。(c) 名簿の呼び名(3 字以上・普通の言葉と重なるものは除く)に、かなに寄せて 1 字違いの所 /
     (d) 名簿の誤りやすい形(misrecognitions の wrong)/ (b) whisper の語の確信度(生の結果 asr.json の words)が低い 2 字以上の語。
     名簿は、その文書に出る人(話者・題名・動画のパスに名前か呼び名があるメンバー)だけを使う。1 文書あたり --limit 箇所まで
  2. 問い合わせ: 行ごとに 前後 2 行・疑わしい所・候補(名簿の呼び名)・出る人を渡し、差分だけを JSON で答えさせる(行を書き直させない。思考はオフ・温度 0)
  3. 検査(guard): 置き換え前の文字が行にある・候補の呼び名そのものか、かなに寄せた音が近い(編集距離が字数の 3 分の 1 以下)・字数の差が 2 字か 2 割以内・
     自信が 0.5 以上。1 文書で直す行は 15% まで(自信の高い順)
  4. 当てる: original の行の文字を置き換える(写しの上で。作業データは書き換えない)
- モデル: Qwen3-8B Q4_K_M(plan/llm-postfix.md の 6-1。Apache-2.0)を作業データの models/llm-gguf/ に置く(大きさ・SHA-256 を確かめる。無ければ止まる = この道具は取りに行かない)。
  llama-server は編集の Qwen3-ASR と同じ版(作業データの bin/llama.cpp-*-vulkan/)を 127.0.0.1 の空いたポート・毎回作る合言葉・GPU(Vulkan)で起動する
- --dry は選ぶだけ(LLM を起動しない)。選んだ所の数と例を出す
- 当たり: 当てた直しのうち、人の最終(同じ時間の校正済みの行)に置き換え後の文字があり、置き換え前の文字が無いもの
"""
import argparse
import hashlib
import json
import os
import re
import secrets
import socket
import subprocess
import sys
import tempfile
import time
import unicodedata
import urllib.error
import urllib.request

HERE = os.path.dirname(os.path.abspath(__file__))
if HERE not in sys.path:
    sys.path.insert(0, HERE)
import _evalcommon as C  # noqa: E402  共通の部品(作業データの場所・保存。src を sys.path に足す)
import eval_asr as E  # noqa: E402  選び方と採点(score_doc・summarize・compare)

MODEL = {"file": "Qwen3-8B-Q4_K_M.gguf", "size": 5027783488, "sha256": "d98cdcbd03e17ce47681435b5150e34c1417f50b5c0019dd560e4882c5745785",
         "url": "https://huggingface.co/Qwen/Qwen3-8B-GGUF/resolve/7c41481f57cb95916b40956ab2f0b139b296d974/Qwen3-8B-Q4_K_M.gguf"}
MODEL_DIR = ("models", "llm-gguf")
LOW_PROB = 0.35          # whisper の語の確信度がこれ未満なら疑わしい
MIN_CONF = 0.5           # LLM の自信がこれ未満の案は当てない
MAX_EDIT_SHARE = 0.15    # 1 文書で直す行の割合の上限
CTX_ROWS = 2             # 前後に見せる行の数
START_SEC = 180
SYSTEM = ("あなたは日本語の配信(VTuber のゲーム実況・雑談)の文字起こしの校正者です。音声認識の誤りのうち、疑わしい所だけを直します。"
          "確信が持てないときは直しません。行を書き直さず、直す所の差分だけを JSON で答えます。/no_think")
KATA = re.compile(r"[ァ-ヶ]")


def fold(text):
    """かなに寄せた比べ方(NFKC・カタカナ → ひらがな・小文字・空白と記号を捨てる)"""
    out = []
    for ch in unicodedata.normalize("NFKC", str(text or "")).lower():
        if "ァ" <= ch <= "ヶ":
            ch = chr(ord(ch) - 0x60)
        if unicodedata.category(ch)[0] in "LN" or ch == "ー":
            out.append(ch)
    return "".join(out)


def edit_distance(a, b):
    """編集距離(短い文字どうし)"""
    prev = list(range(len(b) + 1))
    for i, ca in enumerate(a, 1):
        cur = [i]
        for j, cb in enumerate(b, 1):
            cur.append(min(prev[j] + 1, cur[j - 1] + 1, prev[j - 1] + (ca != cb)))
        prev = cur
    return prev[-1]


# ---------------------------------------------------------------- 1. 選ぶ

def doc_members(doc, members):
    """その文書に出る人(話者の名前・題名・動画のパスに名前か 3 字以上の呼び名があるメンバー)-> [メンバー]"""
    hay = " ".join([str(doc.get("title") or ""), str(doc.get("sourcePath") or "")] + [str(s.get("name") or "") for s in doc.get("speakers") or []])
    out = []
    for m in members:
        keys = [m["name"]] + [a for a in m.get("aliases") or [] if len(a) >= 3 and a not in (m.get("common") or [])]
        if any(k and k in hay for k in keys):
            out.append(m)
    return out


def alias_targets(mems):
    """名簿の呼び名のうち、近い所を探すもの(3 字以上・普通の言葉と重なるものは除く)-> [(かなに寄せた形, 呼び名)]"""
    out = []
    for m in mems:
        for a in [m["name"]] + list(m.get("aliases") or []):
            if a in (m.get("common") or []):
                continue
            f = fold(a)
            if len(f) >= 3 and (f, a) not in out:
                out.append((f, a))
    return out


def near_spans(text, targets):
    """行の文字の中で、呼び名に 1 字違い(同じ形は除く)の所 -> [(元の文字の一部, 呼び名)]"""
    found = []
    for f, alias in targets:
        if fold(alias) in fold(text):
            continue
        for n in (len(alias) - 1, len(alias), len(alias) + 1):
            for i in range(0, max(0, len(text) - n) + 1):
                sub = text[i:i + n]
                fs = fold(sub)
                if KATA.search(alias) and not KATA.search(sub):
                    continue   # カタカナの呼び名の聞き違いはカタカナで出る(トーイ・メコちゃん)。ひらがなの普通の言葉(みるか → ポルカ)は選ばない
                if len(fs) >= 2 and fs != f and edit_distance(fs, f) == 1 and (sub, alias) not in found:
                    found.append((sub, alias))
    return found


def low_prob_words(row, raw):
    """生の結果のうち、行の時間に入る語で確信度が LOW_PROB 未満・2 字以上・行の文字にあるもの -> [語]"""
    out = []
    a, b = float(row["start"]), float(row["end"])
    for seg in raw:
        for w in seg.get("words") or []:
            if not isinstance(w, list) or len(w) < 4 or not isinstance(w[3], (int, float)):
                continue
            t = str(w[2] or "").strip()
            if (w[3] < LOW_PROB and len(set(fold(t))) >= 2 and a - 0.2 <= float(w[0]) and float(w[1]) <= b + 0.2
                    and t in row["text"] and t not in out):   # 同じ字の繰り返し(ーー・ああ)は選ばない
                out.append(t)
    return out


def pick_doc(doc, raw, members, limit=30):
    """疑わしい所 -> [{"row": 行の番号, "span": 元の文字の一部, "why": "name" | "mis" | "lowprob", "cands": [候補]}](limit 箇所まで)"""
    rows = doc.get("original") or []
    mems = doc_members(doc, members)
    targets = alias_targets(mems)
    mis = [(x["wrong"], x["right"]) for m in mems for x in m.get("misrecognitions") or []]
    picks = []
    for i, r in enumerate(rows):
        text = str(r.get("text") or "")
        if not text:
            continue
        for wrong, right in mis:
            if wrong in text:
                picks.append({"row": i, "span": wrong, "why": "mis", "cands": [right]})
        for sub, alias in near_spans(text, targets):
            picks.append({"row": i, "span": sub, "why": "name", "cands": [alias]})
        for w in low_prob_words(r, raw):
            picks.append({"row": i, "span": w, "why": "lowprob", "cands": []})
    # 同じ行で、ほかの選んだ所に含まれる短い所は外す(「ラミ」「ラミー」「ラミーちゃん」なら「ラミーちゃん」だけ)
    picks = [p for p in picks if not any(q is not p and q["row"] == p["row"] and p["span"] in q["span"] and len(q["span"]) > len(p["span"]) for q in picks)]
    order = {"mis": 0, "name": 1, "lowprob": 2}
    picks.sort(key=lambda p: (order[p["why"]], p["row"]))
    return picks[:limit]


# ---------------------------------------------------------------- 2. 問い合わせ

def build_messages(rows, i, picks, people):
    """行 i の問い合わせ(前後 CTX_ROWS 行・疑わしい所・候補・出る人)-> chat の messages"""
    lo, hi = max(0, i - CTX_ROWS), min(len(rows), i + CTX_ROWS + 1)
    ctx = "\n".join(("→ " if k == i else "  ") + str(rows[k].get("text") or "") for k in range(lo, hi))
    lines = []
    for p in picks:
        hint = ("候補: " + "・".join(p["cands"])) if p["cands"] else "認識の自信が低い語"
        lines.append("- 「%s」(%s)" % (p["span"], hint))
    user = ("出る人: %s\n\n前後の行(→ が直す行):\n%s\n\n疑わしい所:\n%s\n\n"
            "直す必要がある所だけ、次の形で答えてください。直さない所は書かない。何も直さないなら {\"edits\": []}。\n"
            "{\"edits\": [{\"from\": \"直す行の中の元の文字\", \"to\": \"直した文字\", \"confidence\": 0〜1}]}"
            % ("、".join(people) or "(不明)", ctx, "\n".join(lines)))
    return [{"role": "system", "content": SYSTEM}, {"role": "user", "content": user}]


def parse_reply(content):
    """LLM の答え -> [{"from", "to", "confidence"}](読めなければ [])。<think> の部分と、JSON の前後の文は捨てる"""
    text = re.sub(r"<think>.*?</think>", "", str(content or ""), flags=re.S)
    a, b = text.find("{"), text.rfind("}")
    if a < 0 or b <= a:
        return []
    try:
        data = json.loads(text[a:b + 1])
    except ValueError:
        return []
    out = []
    for e in data.get("edits") or [] if isinstance(data, dict) else []:
        if isinstance(e, dict) and isinstance(e.get("from"), str) and isinstance(e.get("to"), str):
            c = e.get("confidence")
            out.append({"from": e["from"], "to": e["to"], "confidence": float(c) if isinstance(c, (int, float)) and not isinstance(c, bool) else None})
    return out


# ---------------------------------------------------------------- 3. 検査・4. 当てる

def guard(text, edit, cands, names=()):
    """直しの案を検査する -> None(通す)か 断る理由。names = 名簿の名前と呼び名(かなに寄せた形)。候補に無い名前を新しく持ち込む案は断る
    (10-09 の測定: 確信度の低い語「みるか」を「ポルカ」に変えた = 音が近いだけで別の人の名前になった)"""
    f, t = edit["from"], edit["to"]
    if not f or f not in text:
        return "notInRow"
    if f == t or not t.strip():
        return "noChange"
    if edit.get("confidence") is not None and edit["confidence"] < MIN_CONF:
        return "lowConfidence"
    if abs(len(t) - len(f)) > max(2, round(0.2 * len(f))):
        return "length"
    ff, ft = fold(f), fold(t)
    if any(fold(c) == ft for c in cands):
        return None
    if any(n in ft and n not in ff and not any(n in fold(c) for c in cands) for n in names):
        return "newName"
    if edit_distance(ff, ft) > max(1, len(ff) // 3):
        return "farSound"
    return None


def apply_edits(rows, accepted):
    """original の写しに直しを当てる。accepted = [(行の番号, 案)] -> 新しい行の一覧(行の数・時刻は同じ)"""
    out = [dict(r) for r in rows]
    for i, e in accepted:
        out[i]["text"] = out[i]["text"].replace(e["from"], e["to"], 1)
    return out


def cap_edits(accepted, n_rows):
    """1 文書で直す行を MAX_EDIT_SHARE までに(自信の高い順。自信の無い案は 0.5 とみる)-> (残す案, 落とした案)"""
    cap = max(1, int(n_rows * MAX_EDIT_SHARE))
    rows_kept, keep, drop = set(), [], []
    for i, e in sorted(accepted, key=lambda x: -(x[1]["confidence"] if x[1]["confidence"] is not None else 0.5)):
        if i in rows_kept or len(rows_kept) < cap:
            rows_kept.add(i)
            keep.append((i, e))
        else:
            drop.append((i, e))
    return keep, drop


def judge_hit(doc, row, e):
    """当てた直しが人の最終と合うか: "hit"(置き換え後の文字が人の行にあり、前の文字が無い)・"miss"(前の文字が人の行に残る)・"other" """
    a, b = float(row["start"]), float(row["end"])
    final = "".join(str(s.get("text") or "") for s in doc.get("segments") or []
                    if s.get("proofed") and min(b, float(s["end"])) - max(a, float(s["start"])) > 0)
    ff, ft, fin = fold(e["from"]), fold(e["to"]), fold(final)
    if ft and ft in fin and ff not in fin:
        return "hit"
    if ff and ff in fin:
        return "miss"
    return "other"


# ---------------------------------------------------------------- LLM(llama-server)

class Llm:
    """llama-server を 127.0.0.1 の空いたポート・毎回作る合言葉・GPU(Vulkan)で起動し、chat で問い合わせる"""

    def __init__(self, data):
        self.data, self.proc, self.port, self.key = data, None, 0, secrets.token_hex(16)

    def model_path(self):
        """モデルの場所(無い・大きさが違う・SHA-256 が違うときは止める)"""
        p = os.path.join(self.data, *MODEL_DIR, MODEL["file"])
        if not os.path.isfile(p) or os.path.getsize(p) != MODEL["size"]:
            raise SystemExit("モデルがありません(または取得の途中です): %s\n取得先: %s(%d バイト・SHA-256 %s)" % (p, MODEL["url"], MODEL["size"], MODEL["sha256"]))
        h = hashlib.sha256()
        with open(p, "rb") as f:
            for chunk in iter(lambda: f.read(1 << 22), b""):
                h.update(chunk)
        if h.hexdigest() != MODEL["sha256"]:
            raise SystemExit("モデルの SHA-256 が違います(壊れているか別のファイル): %s" % p)
        return p

    def exe(self):
        """llama-server の場所(編集の Qwen3-ASR が使う作業データの bin/llama.cpp-*-vulkan/)"""
        bdir = os.path.join(self.data, "bin")
        for name in sorted(os.listdir(bdir)) if os.path.isdir(bdir) else []:
            p = os.path.join(bdir, name, "llama-server.exe" if os.name == "nt" else "llama-server")
            if name.startswith("llama.cpp-") and os.path.isfile(p):
                return p
        raise SystemExit("llama-server がありません(編集で Qwen3-ASR 1.7B を 1 回使うと取得されます): %s" % bdir)

    def start(self):
        """起動して /health が 200 になるまで待つ"""
        model, exe = self.model_path(), self.exe()
        s = socket.socket()
        s.bind(("127.0.0.1", 0))
        self.port = s.getsockname()[1]
        s.close()
        env = dict(os.environ, GGML_VK_DISABLE_COOPMAT="1")   # 編集の llama-server と同じ(RX 7800 XT で行列コアの経路が落ちる)
        self.log = tempfile.NamedTemporaryFile(prefix="eval-llm-server-", suffix=".log", delete=False)
        flags = 0x08000000 if os.name == "nt" else 0   # CREATE_NO_WINDOW
        self.proc = subprocess.Popen([exe, "-m", model, "--host", "127.0.0.1", "--port", str(self.port), "--api-key", self.key, "--no-webui",
                                      "-c", "4096", "-np", "1", "-t", "8", "-ngl", "99"],
                                     stdin=subprocess.DEVNULL, stdout=subprocess.DEVNULL, stderr=self.log, creationflags=flags, env=env)
        t0 = time.monotonic()
        while time.monotonic() - t0 < START_SEC:
            if self.proc.poll() is not None:
                raise SystemExit("llama-server が起動の途中で止まりました(ログ %s)" % self.log.name)
            try:
                with urllib.request.urlopen(urllib.request.Request("http://127.0.0.1:%d/health" % self.port, headers={"Authorization": "Bearer " + self.key}), timeout=2) as r:
                    if r.status == 200:
                        return
            except OSError:
                pass
            time.sleep(0.5)
        self.stop()
        raise SystemExit("llama-server の起動が %d 秒で終わりませんでした" % START_SEC)

    def ask(self, messages):
        """chat の答えの文字(温度 0・思考オフ)"""
        body = json.dumps({"messages": messages, "temperature": 0, "max_tokens": 400, "cache_prompt": False,
                           "chat_template_kwargs": {"enable_thinking": False}}).encode("utf-8")
        req = urllib.request.Request("http://127.0.0.1:%d/v1/chat/completions" % self.port, body,
                                     {"Content-Type": "application/json", "Authorization": "Bearer " + self.key})
        with urllib.request.urlopen(req, timeout=300) as r:
            data = json.loads(r.read().decode("utf-8"))
        return ((data.get("choices") or [{}])[0].get("message") or {}).get("content") or ""

    def stop(self):
        """止める(終わらなければ強制終了)"""
        if self.proc and self.proc.poll() is None:
            self.proc.terminate()
            try:
                self.proc.wait(10)
            except subprocess.TimeoutExpired:
                self.proc.kill()


# ---------------------------------------------------------------- 通し

def roster_names(members):
    """名簿の名前と呼び名(かなに寄せた 2 字以上の形。普通の言葉と重なる呼び名は除く)"""
    out = set()
    for m in members:
        for a in [m["name"]] + list(m.get("aliases") or []):
            if a not in (m.get("common") or []) and len(fold(a)) >= 2:
                out.add(fold(a))
    return sorted(out)


def run_doc(doc, raw, members, ask, limit, only=None):
    """1 本: 選ぶ → 問い合わせ → 検査 → 当てる -> (新しい行, 記録)。only = 選ぶ手がかりを絞る(例 {"name", "mis"})"""
    rows = doc.get("original") or []
    picks = [p for p in pick_doc(doc, raw, members, 10 ** 6) if not only or p["why"] in only][:limit]
    people = [m["name"] for m in doc_members(doc, members)]
    names = roster_names(members)
    rec = {"id": doc["id"], "picks": len(picks), "byWhy": {}, "proposed": [], "rejected": {}, "applied": []}
    for p in picks:
        rec["byWhy"][p["why"]] = rec["byWhy"].get(p["why"], 0) + 1
    accepted = []
    if ask is not None:
        for i in sorted({p["row"] for p in picks}):
            mine = [p for p in picks if p["row"] == i]
            cands = [c for p in mine for c in p["cands"]]
            for e in parse_reply(ask(build_messages(rows, i, mine, people))):
                why = guard(rows[i]["text"], e, cands, names)
                rec["proposed"].append({"row": i, **e, "rejected": why})
                if why:
                    rec["rejected"][why] = rec["rejected"].get(why, 0) + 1
                else:
                    accepted.append((i, e))
    keep, drop = cap_edits(accepted, len(rows))
    if drop:
        rec["rejected"]["cap"] = len(drop)
    for i, e in keep:
        rec["applied"].append({"row": i, "text": rows[i]["text"], **e, "judge": judge_hit(doc, rows[i], e)})
    return apply_edits(rows, keep), rec


def score(S, docs, rows_of, terms, args, data, sel, label):
    """eval_asr と同じ採点 -> 結果(eval_asr compare の形)"""
    groups, nosub = [], {}
    for d in docs:
        groups += E.score_doc(S, d, rows_of[d["id"]], terms, flag_from="ref")
        nosub[d["id"]] = E.doc_nosub(S, d, rows_of[d["id"]])
    meta = E.base_meta("stored", args, docs, data, sel)
    meta["label"] = label
    return {"meta": meta, "summary": E.summarize(groups, docs, S, E.STORED, None, nosub), "groups": groups, "terms": terms}


def print_report(recs, dry):
    picks = sum(r["picks"] for r in recs)
    by = {}
    for r in recs:
        for k, v in r["byWhy"].items():
            by[k] = by.get(k, 0) + v
    print("選んだ所 %d(名簿の誤りやすい形 %d・呼び名に 1 字違い %d・確信度が低い語 %d)" % (picks, by.get("mis", 0), by.get("name", 0), by.get("lowprob", 0)))
    if dry:
        return
    prop = sum(len(r["proposed"]) for r in recs)
    app = [a for r in recs for a in r["applied"]]
    rej = {}
    for r in recs:
        for k, v in r["rejected"].items():
            rej[k] = rej.get(k, 0) + v
    j = {k: sum(1 for a in app if a["judge"] == k) for k in ("hit", "miss", "other")}
    print("LLM の案 %d・当てた %d(当たり %d・外れ %d・どちらとも %d)・断った %s" % (prop, len(app), j["hit"], j["miss"], j["other"], json.dumps(rej, ensure_ascii=False)))
    for a in app[:20]:
        print("  [%s] 「%s」→「%s」(%s)  %s" % (a["judge"], a["from"], a["to"], a["confidence"], a["text"][:40]))


def main(argv=None):
    p = argparse.ArgumentParser(description="LLM の後処理(P18)を確かめ済みの評価用の文書で測る(作業データは読むだけ)")
    p.add_argument("--docs", help="文書の id をカンマ区切りで(既定は確かめ済みの評価用すべて)")
    p.add_argument("--limit", type=int, default=30, help="1 文書あたり選ぶ所の上限(既定 30)")
    p.add_argument("--only", help="選ぶ手がかりを絞る(カンマ区切り: mis・name・lowprob。既定は全部)")
    p.add_argument("--dry", action="store_true", help="選ぶだけ(LLM を起動しない)")
    p.add_argument("--label", default="", help="結果の名前に付ける")
    p.add_argument("--no-save", action="store_true", help="結果を保存しない")
    p.add_argument("--data", help="文字起こしの作業データのフォルダ(既定 %%LOCALAPPDATA%%/youtube-tools/transcribe)")
    args = p.parse_args(argv)
    C.utf8_stdout()
    ns = argparse.Namespace(docs=[x.strip() for x in args.docs.split(",") if x.strip()] if args.docs else None, scope="eval", source=None,
                            reviewed=None, since=None, until=None, intake=None, label=args.label, group_by=None)
    data = E.real_data_dir(args.data)
    S = E.load_serve()
    settings = C.read_json(os.path.join(data, "settings.json"), {}) or {}
    docs, sel = E.select_docs(data, ns)
    if not docs:
        raise SystemExit("測れる文書がありません")
    members = list(S._roster.load(S.ROSTER)["members"].values())
    terms = E.name_terms(S, settings)
    llm = None if args.dry else Llm(data)
    recs, rows_of = [], {}
    try:
        if llm:
            llm.start()
        for n, d in enumerate(docs, 1):
            asr = C.read_json(os.path.join(data, "transcripts", d["id"] + ".asr.json"), None, 64 * 1024 * 1024)
            raw = asr.get("segments") if isinstance(asr, dict) and isinstance(asr.get("segments"), list) else []
            only = {x.strip() for x in args.only.split(",") if x.strip()} if args.only else None
            rows_of[d["id"]], rec = run_doc(d, raw, members, llm.ask if llm else None, args.limit, only)
            recs.append(rec)
            print("(%d/%d) %s 選んだ %d・当てた %d" % (n, len(docs), d["id"], rec["picks"], len(rec["applied"])), flush=True)
    finally:
        if llm:
            llm.stop()
    print_report(recs, args.dry)
    if args.dry:
        return 0
    base = score(S, docs, {d["id"]: d.get("original") or [] for d in docs}, terms, ns, data, sel, "llm-base" + args.label)
    on = score(S, docs, rows_of, terms, ns, data, sel, "llm-on" + args.label)
    for name, r in (("基準(直す前)", base), ("LLM の直しのあと", on)):
        o = r["summary"]["overall"]
        print("%s: CER %s(置換 %d・抜け %d・余分 %d)・名前 %d/%d・正解に無い名前 %d" % (name, C.pct(o["cer"], 0), o["sub"], o["del"], o["ins"], o["termHit"], o["termRef"], o["termExtra"]))
    if not args.no_save:
        pa = C.save(base, data, "asr", "_llm-base" + args.label)
        pb = C.save(on, data, "asr", "_llm-on" + args.label)
        print("保存: " + C.save({"schema": "youtube-tools-llm-eval/v1", "model": MODEL["file"], "docs": recs}, data, "llm"))
        E.cmd_compare(pa, pb)
    return 0


if __name__ == "__main__":
    sys.exit(main())
