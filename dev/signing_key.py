"""友人のアプリの更新の署名の鍵(安全面の直し 1・10-29。手順は保管庫 docs/spec/更新の署名の鍵.md)。

    py -3.12 dev/signing_key.py new              # 秘密鍵 friend-apps/launcher/signing.key を作り、公開鍵を src/friendapp/pubkeys.json に足す(もうあれば断る)
    py -3.12 dev/signing_key.py new --replace    # 鍵が漏れた・作り直す: 前の鍵を signing.key.old-<時刻> に退けて新しく作る(前の公開鍵は pubkeys.json に残す)
    py -3.12 dev/signing_key.py check            # 秘密鍵と pubkeys.json が組か(署名して確かめる往復。秘密鍵の中身は出さない)

秘密鍵は git に入れない(.gitignore・push_helper の SECRET_FILES)。写しは資格情報マネージャーとユーザーのバックアップ(ユーザーが手で。この道具は外へ写さない)。
鍵を失くしたら new で作り直し、新しい公開鍵の入った友人のアプリの zip(--first)を手で入れ直す(2 段目より後 = 署名が要る版の後だけ要る)"""
import argparse
import base64
import datetime
import json
import os
import secrets
import sys

REPO = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(REPO, "src"))
from friendapp import ed25519, signing  # noqa: E402
from ytt import fsio  # noqa: E402

KEY_PATH = os.path.join(REPO, "friend-apps", "launcher", "signing.key")


def load(path=None):
    """秘密鍵 -> (名前, 32 バイト)。無い・形が違えば ValueError"""
    try:
        with open(path or KEY_PATH, encoding="utf-8") as f:
            d = json.load(f)
        seed = base64.b64decode(d["seed"], validate=True)
        name = d["name"]
    except (OSError, ValueError, KeyError, TypeError) as e:
        raise ValueError("署名の鍵を読めません(%s)" % e.__class__.__name__)
    if d.get("alg") != signing.ALG or len(seed) != 32 or not isinstance(name, str) or not name:
        raise ValueError("署名の鍵の形が違います")
    return name, seed


def _pubkeys(path):
    try:
        with open(path, encoding="utf-8") as f:
            d = json.load(f)
    except (OSError, ValueError):
        d = {}
    return d if isinstance(d, dict) and isinstance(d.get("keys"), dict) else {"keys": {}}


def new(key_path=None, pub_path=None, replace=False, now=None):
    """鍵を作る -> 鍵の名前"""
    key_path, pub_path = key_path or KEY_PATH, pub_path or signing.PUBKEYS
    now = now or datetime.datetime.now()
    if os.path.exists(key_path):
        if not replace:
            raise ValueError("署名の鍵はもうあります(作り直すなら --replace)")
        os.replace(key_path, "%s.old-%s" % (key_path, now.strftime("%Y%m%d-%H%M%S")))
    doc = _pubkeys(pub_path)
    name = "k" + now.strftime("%Y%m%d")
    while name in doc["keys"]:
        name = "k" + now.strftime("%Y%m%d-%H%M%S") + secrets.token_hex(2)
    seed = secrets.token_bytes(32)
    os.makedirs(os.path.dirname(key_path), exist_ok=True)
    fsio.atomic_write(key_path, json.dumps({"alg": signing.ALG, "name": name, "seed": base64.b64encode(seed).decode("ascii"),
                                            "createdAt": now.strftime("%Y-%m-%dT%H:%M:%S")}, indent=1).encode("utf-8"))
    doc["keys"][name] = base64.b64encode(ed25519.public_key(seed)).decode("ascii")
    fsio.atomic_write(pub_path, (json.dumps(doc, ensure_ascii=False, indent=1) + "\n").encode("utf-8"))
    return name


def check(key_path=None, pub_path=None):
    """秘密鍵と公開鍵の往復 -> 鍵の名前。合わなければ ValueError"""
    name, seed = load(key_path)
    probe = signing.sign({"probe": True}, seed, name)
    if signing.check(probe, signing.load_keys(pub_path)) != "ok":
        raise ValueError("秘密鍵 %s の公開鍵が pubkeys.json に無いか、合いません" % name)
    return name


def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("cmd", choices=("new", "check"))
    ap.add_argument("--replace", action="store_true")
    a = ap.parse_args(argv)
    try:
        if a.cmd == "new":
            name = new(replace=a.replace)
            print("署名の鍵 %s を作りました: %s(公開鍵は %s)。写しを資格情報マネージャーとバックアップへ(手順の資料)" % (name, KEY_PATH, signing.PUBKEYS))
        else:
            print("署名の鍵 %s は pubkeys.json と組です" % check())
    except ValueError as e:
        print(str(e))
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
