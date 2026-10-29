"""src/friendapp/ed25519.py・signing.py と dev/signing_key.py のテスト(更新の署名・安全面の直し 1)。
本物の秘密鍵は読まない(一時フォルダに作る)。リポジトリ直下で: py -3.12 -m unittest tests/friendapp/test_signing.py"""
import json
import os
import sys
import unittest
from unittest import mock

os.environ.setdefault("YTT_DATA_DIR", "inplace")
ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
for p in (os.path.join(ROOT, "src"), os.path.join(ROOT, "dev"), os.path.join(ROOT, "tests")):
    if p not in sys.path:
        sys.path.insert(0, p)
import testkit  # noqa: E402
from friendapp import ed25519 as E, signing as S  # noqa: E402
import signing_key as K  # noqa: E402

# RFC 8032 の 7.1 の TEST 1・TEST 2
VECTORS = (("9d61b19deffd5a60ba844af492ec2cc44449c5697b326919703bac031cae7f60", "d75a980182b10ab7d54bfed3c964073a0ee172f3daa62325af021a68f707511a", "",
            "e5564300c360ac729086e2cc806e828a84877f1eb8e5d974d873e065224901555fb8821590a33bacc61e39701cf9b46bd25bf5f0595bbe24655141438e7a100b"),
           ("4ccd089b28ff96da9db6c346ec114e0f5b8a319f35aba624da8cf6ed4fb8a6fb", "3d4017c3e843895a92b70aa74d1b7ebc9c982ccf2ec4968cc0cd55f12af4660c", "72",
            "92a009a9f0d4cab8720e820b5f642540a2b27b5416503f8fb3762223ebdb69da085ac1e43e15996e458f3613d0f11d8c387b2eaeb4302aeeb00d291612bb0c00"))


class Ed25519Test(unittest.TestCase):
    def test_rfc8032_vectors(self):
        for sk, pk, msg, sig in VECTORS:
            sk, pk, msg, sig = (bytes.fromhex(x) for x in (sk, pk, msg, sig))
            self.assertEqual(E.public_key(sk), pk)
            self.assertEqual(E.sign(sk, msg), sig)
            self.assertTrue(E.verify(pk, msg, sig))
            self.assertFalse(E.verify(pk, msg + b"x", sig))
            self.assertFalse(E.verify(pk, msg, sig[:-1] + bytes([sig[-1] ^ 1])))
        self.assertFalse(E.verify(b"x" * 31, b"", b"y" * 64))


class SigningTest(unittest.TestCase):
    def setUp(self):
        self.seed = bytes(range(32))
        self.keys = {"t": E.public_key(self.seed)}
        self.doc = {"version": "0.99.400", "file": "FriendApp-0.99.400.zip", "size": 1, "sha256": "a" * 64, "cancel": [], "notes": "直した"}

    def test_round_trip_and_tamper(self):
        signed = S.sign(self.doc, self.seed, "t")
        self.assertEqual(S.check(signed, self.keys), "ok")
        self.assertEqual(S.check(json.loads(json.dumps(signed, indent=3)), self.keys), "ok")   # 鍵の順・空白に関わらない
        for k, v in (("cancel", ["0.99.400"]), ("sha256", "b" * 64), ("important", True)):
            self.assertEqual(S.check(dict(signed, **{k: v}), self.keys), "bad", k)
        self.assertEqual(S.check(dict(signed, sig=dict(signed["sig"], key="other")), self.keys), "bad")
        self.assertEqual(S.check(dict(signed, sig={"alg": "rsa", "key": "t", "value": "x"}), self.keys), "bad")
        self.assertEqual(S.check(dict(signed, sig="x"), self.keys), "bad")
        self.assertEqual(S.check(self.doc, self.keys), "none")

    def test_accept_by_stage(self):
        """1 段目(REQUIRED = False)は署名が無くても取る・合わなければ取らない。3 段目(True)は無い物も取らない"""
        signed = S.sign(self.doc, self.seed, "t")
        self.assertEqual(S.accept(signed, self.keys), (True, "ok"))
        self.assertEqual(S.accept(self.doc, self.keys), (True, "none"))
        self.assertEqual(S.accept(dict(signed, size=2), self.keys), (False, "bad"))
        with mock.patch.object(S, "REQUIRED", True):
            self.assertEqual(S.accept(self.doc, self.keys), (False, "none"))
            self.assertEqual(S.accept(signed, self.keys), (True, "ok"))

    def test_shipped_pubkeys_load(self):
        """配る公開鍵 src/friendapp/pubkeys.json は 1 つ以上読める(32 バイト)"""
        keys = S.load_keys()
        self.assertTrue(keys)
        self.assertTrue(all(len(v) == 32 for v in keys.values()))


class SigningKeyToolTest(unittest.TestCase):
    def setUp(self):
        tmp = testkit.tempdir(self, "signkey-")
        self.key, self.pub = os.path.join(tmp, "launcher", "signing.key"), os.path.join(tmp, "pubkeys.json")

    def test_new_check_and_replace(self):
        name = K.new(self.key, self.pub)
        self.assertEqual(K.check(self.key, self.pub), name)
        with self.assertRaises(ValueError):
            K.new(self.key, self.pub)   # もうある = 断る(上書きで失くさない)
        name2 = K.new(self.key, self.pub, replace=True)
        self.assertNotEqual(name, name2)
        self.assertEqual(K.check(self.key, self.pub), name2)
        self.assertEqual(set(S.load_keys(self.pub)), {name, name2})   # 前の公開鍵も残す(前の鍵で署名した版も通る)
        self.assertEqual(len([n for n in os.listdir(os.path.dirname(self.key)) if n.startswith("signing.key.old-")]), 1)

    def test_lost_key_is_made_again(self):
        """鍵を失くした: new でそのまま作り直せる(公開鍵が増える)"""
        K.new(self.key, self.pub)
        os.remove(self.key)
        K.new(self.key, self.pub)
        self.assertEqual(len(S.load_keys(self.pub)), 2)
        with open(self.pub, encoding="utf-8") as f:
            self.assertNotIn("seed", f.read())   # 公開鍵の表に秘密鍵は入らない


if __name__ == "__main__":
    unittest.main()
