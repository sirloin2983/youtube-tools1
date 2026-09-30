# -*- coding: utf-8 -*-
"""dev/dropbox_auth.py(切り抜き依頼の鍵を作る)のテスト。通信はしない(urlopen を差し替える)。
実行(リポジトリ直下): python -m unittest dev/tests/test_dropbox_auth.py"""
import os
os.environ.setdefault("YTT_DATA_DIR", "inplace")   # サーバーは動かさないが、全テストの決まりに合わせる
import io
import json
import shutil
import sys
import tempfile
import unittest
import urllib.error
import urllib.parse

TESTS = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.dirname(TESTS))
import dropbox_auth as A  # noqa: E402

FAKE = "FAKE-short"   # 本物の形ではない値(push_helper の検査に掛からない長さ)


class FakeResp(io.BytesIO):
    def __enter__(self):
        return self

    def __exit__(self, *a):
        return False


class TestPkce(unittest.TestCase):
    def test_challenge_is_base64url_sha256(self):
        # S256 = BASE64URL(SHA256(ASCII(verifier)))、= なし・+ / を使わない(RFC 7636 の 4.2)
        import base64
        import hashlib
        v = "abcDEF-._~" * 5
        ch = A.challenge_for(v)
        self.assertEqual(len(ch), 43)
        self.assertRegex(ch, r"^[A-Za-z0-9_-]{43}$")
        self.assertEqual(base64.urlsafe_b64decode(ch + "="), hashlib.sha256(v.encode("ascii")).digest())

    def test_verifier_shape_and_random(self):
        vs = {A.make_verifier() for _ in range(20)}
        self.assertEqual(len(vs), 20)
        for v in vs:
            self.assertRegex(v, r"^[A-Za-z0-9\-._~]{43,128}$")
            self.assertNotIn("=", A.challenge_for(v))

    def test_authorize_url(self):
        u = urllib.parse.urlparse(A.authorize_url("abc123key", "CH"))
        self.assertEqual((u.scheme, u.netloc, u.path), ("https", "www.dropbox.com", "/oauth2/authorize"))
        q = dict(urllib.parse.parse_qsl(u.query))
        self.assertEqual(q, {"client_id": "abc123key", "response_type": "code", "code_challenge": "CH",
                             "code_challenge_method": "S256", "token_access_type": "offline"})

    def test_token_body(self):
        q = dict(urllib.parse.parse_qsl(A.token_request_body("abc123key", "  CODE \n", "VER").decode()))
        self.assertEqual(q, {"code": "CODE", "grant_type": "authorization_code", "code_verifier": "VER", "client_id": "abc123key"})
        self.assertNotIn("client_secret", q)

    def test_extra_scopes(self):
        self.assertEqual(A.extra_scopes("account_info.read files.content.write"), [])
        self.assertEqual(A.extra_scopes("files.content.read files.content.write"), ["files.content.read"])
        self.assertEqual(A.extra_scopes(None), [])


class TestMain(unittest.TestCase):
    def setUp(self):
        self.dir = tempfile.mkdtemp()
        self.out = os.path.join(self.dir, "sub", "config.json")
        self.logs = []

    def tearDown(self):
        shutil.rmtree(self.dir, ignore_errors=True)

    def run_main(self, urlopen, code="THECODE", key="abc123key"):
        return A.main([key, "--out", self.out, "--no-browser"], input_fn=lambda _: code, urlopen=urlopen, out=self.logs.append)

    def test_writes_config_without_printing_token(self):
        seen = {}

        def urlopen(req, timeout=None):
            seen["url"] = req.full_url
            seen["body"] = dict(urllib.parse.parse_qsl(req.data.decode()))
            return FakeResp(json.dumps({"refresh_token": FAKE, "access_token": "x", "scope": "files.content.write"}).encode())

        self.assertEqual(self.run_main(urlopen), 0)
        self.assertEqual(seen["url"], A.TOKEN_URL)
        self.assertEqual(seen["body"]["code"], "THECODE")
        with open(self.out, encoding="utf-8") as f:
            self.assertEqual(json.load(f), {"appKey": "abc123key", "refreshToken": FAKE})
        self.assertFalse(any(FAKE in x for x in self.logs), "鍵の値を画面に出さない")
        # 承認の URL の challenge は、送った verifier から作ったもの
        url = next(x for x in self.logs if "oauth2/authorize" in x).strip()
        ch = dict(urllib.parse.parse_qsl(urllib.parse.urlparse(url).query))["code_challenge"]
        self.assertEqual(ch, A.challenge_for(seen["body"]["code_verifier"]))

    def test_warns_extra_scope(self):
        urlopen = lambda req, timeout=None: FakeResp(json.dumps({"refresh_token": FAKE, "scope": "files.content.write files.content.read"}).encode())
        self.assertEqual(self.run_main(urlopen), 0)
        self.assertTrue(any("files.content.read" in x for x in self.logs))

    def test_http_error_writes_nothing(self):
        def urlopen(req, timeout=None):
            raise urllib.error.HTTPError(req.full_url, 400, "Bad Request", {}, io.BytesIO(b'{"error": "invalid_grant", "error_description": "code doesn\'t exist"}'))

        self.assertEqual(self.run_main(urlopen), 1)
        self.assertFalse(os.path.exists(self.out))
        self.assertTrue(any("invalid_grant" in x for x in self.logs))

    def test_missing_refresh_token(self):
        urlopen = lambda req, timeout=None: FakeResp(b'{"access_token": "x"}')
        self.assertEqual(self.run_main(urlopen), 1)
        self.assertFalse(os.path.exists(self.out))

    def test_bad_key_and_empty_code(self):
        self.assertEqual(self.run_main(None, key="Not A Key!"), 2)
        self.assertEqual(self.run_main(None, code="  "), 2)
        self.assertFalse(os.path.exists(self.out))


if __name__ == "__main__":
    unittest.main()
