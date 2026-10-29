"""更新の署名(安全面の直し 1・10-29 決めた事 1〜3。案 A = Ed25519・公開鍵を src に焼き込む)。
署名する物 = latest.json の sig 以外の全部(version・file・size・sha256・light・cancel・fixes …)を canonical な JSON にしたバイト。
zip の中身は latest.json の sha256 で守られる(sync._fetch_install が照らす)。
latest.json の sig = {"alg": "ed25519", "key": <鍵の名前>, "value": <署名の base64>}。公開鍵は同じフォルダの pubkeys.json {"keys": {名前: base64}}。
段(決めた事 3。1 段ずつ別の zip で、友人の版の見張りを見てから次へ):
  1 段目(今)= sig があれば確かめ、合わなければ取らない・無ければ今まで通り取る(REQUIRED = False)
  2 段目 = 配る道具が sig を書く / 3 段目以降 = sig が無ければ取らない(REQUIRED = True)・印のファイルにも署名
秘密鍵はユーザーの PC の friend-apps/launcher/signing.key(git に入れない)。作るのは dev/signing_key.py"""
import base64
import json
import os

from . import ed25519

ALG = "ed25519"
REQUIRED = False   # スイッチ: True = 署名の無い latest.json も取らない(3 段目以降。今は 1 段目 = 有れば確かめるだけ)
PUBKEYS = os.path.join(os.path.dirname(os.path.abspath(__file__)), "pubkeys.json")


def canonical(doc):
    """署名するバイト: sig を除いた doc を、鍵の順をそろえ・空白なしの JSON(UTF-8)にした物"""
    body = {k: v for k, v in doc.items() if k != "sig"}
    return json.dumps(body, ensure_ascii=False, sort_keys=True, separators=(",", ":")).encode("utf-8")


def load_keys(path=None):
    """公開鍵 {名前: 32 バイト}(読めない・形の違う物は外す)"""
    try:
        with open(path or PUBKEYS, encoding="utf-8") as f:
            d = json.load(f)
    except (OSError, ValueError):
        return {}
    out = {}
    for name, v in ((d or {}).get("keys") or {}).items() if isinstance(d, dict) and isinstance(d.get("keys"), dict) else ():
        try:
            b = base64.b64decode(v, validate=True) if isinstance(v, str) else b""
        except ValueError:
            continue
        if len(b) == 32:
            out[str(name)] = b
    return out


def check(doc, keys=None):
    """latest.json の署名 -> "ok"(合う)・"none"(sig が無い)・"bad"(形が違う・知らない鍵・合わない)"""
    sig = doc.get("sig") if isinstance(doc, dict) else None
    if sig is None:
        return "none"
    if not isinstance(sig, dict) or sig.get("alg") != ALG or not isinstance(sig.get("value"), str):
        return "bad"
    pub = (load_keys() if keys is None else keys).get(str(sig.get("key")))
    if pub is None:
        return "bad"
    try:
        value = base64.b64decode(sig["value"], validate=True)
    except ValueError:
        return "bad"
    return "ok" if ed25519.verify(pub, canonical(doc), value) else "bad"


def accept(doc, keys=None):
    """更新を取ってよいか -> (よいか, check の答え)。1 段目は sig が無くても取る(REQUIRED = False)"""
    got = check(doc, keys)
    return (got == "ok" or (got == "none" and not REQUIRED)), got


def sign(doc, seed, name):
    """doc に sig を付けた写しを返す(ユーザーの PC の道具だけが呼ぶ。seed = 32 バイトの秘密鍵)"""
    out = {k: v for k, v in doc.items() if k != "sig"}
    out["sig"] = {"alg": ALG, "key": name, "value": base64.b64encode(ed25519.sign(seed, canonical(out))).decode("ascii")}
    return out
