"""src/friendapp/dropbox.py のテスト(本物の Dropbox につながない = 偽の通信 transport)。リポジトリ直下で: py -3.12 -m unittest src/friendapp/tests/test_dropbox.py"""
import hashlib
import io
import json
import os
import sys
import unittest

SRC = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
if SRC not in sys.path:
    sys.path.insert(0, SRC)
from ytt import testkit  # noqa: E402
from friendapp import dropbox as D  # noqa: E402

TOKEN = "sl.SECRET-ACCESS-TOKEN"
REFRESH = "REFRESH-SECRET"


class Stream(io.BytesIO):
    """返事の本文。fail_after バイト読んだら通信が切れる"""

    def __init__(self, data, fail_after=None):
        super().__init__(data)
        self.fail_after = fail_after

    def read(self, n=-1):
        if self.fail_after is not None and self.tell() >= self.fail_after:
            raise ConnectionResetError("切れた")
        if self.fail_after is not None and n is not None and n > 0:
            n = min(n, self.fail_after - self.tell())
        return super().read(n)


class FakeNet:
    """呼ばれた順に返事を返す偽の通信。handler(url, headers, body) -> (status, headers, 本文 bytes か Stream)"""

    def __init__(self, *handlers):
        self.handlers = list(handlers)
        self.calls = []

    def __call__(self, url, headers, body, timeout):
        self.calls.append((url, dict(headers), body))
        if url == D.TOKEN_URL:
            return 200, {}, Stream(json.dumps({"access_token": TOKEN}).encode())
        h = self.handlers.pop(0)
        status, hd, data = h(url, headers, body) if callable(h) else h
        return status, hd, data if isinstance(data, Stream) else Stream(data)


def ok(obj):
    return (200, {}, json.dumps(obj).encode())


def err(status, obj):
    return (status, {}, json.dumps(obj).encode())


NOT_FOUND = err(409, {"error_summary": "path/not_found/..", "error": {".tag": "path", "path": {".tag": "not_found"}}})


class DropboxTest(unittest.TestCase):
    def setUp(self):
        self.tmp = testkit.tempdir(self, "dbx-")
        self.logs = []
        self.slept = []

    def client(self, net):
        return D.Client(D.Config("APPKEY", REFRESH), transport=net, log=self.logs.append, sleep=self.slept.append)

    def test_config_load_and_repr_hides_keys(self):
        self.assertIsNone(D.load_config(self.tmp))
        testkit.write_json(os.path.join(self.tmp, "config.json"), {"appKey": "k"})
        self.assertIsNone(D.load_config(self.tmp))   # refreshToken が無い
        with open(os.path.join(self.tmp, "config.json"), "w", encoding="utf-8-sig") as f:
            json.dump({"appKey": " k ", "refreshToken": REFRESH}, f)
        c = D.load_config(self.tmp)
        self.assertEqual((c.app_key, c.refresh_token), ("k", REFRESH))
        self.assertNotIn(REFRESH, repr(c))

    def test_refresh_then_rpc_with_bearer(self):
        net = FakeNet(ok({"metadata": {"name": "x"}}))
        c = self.client(net)
        c.get_metadata("/a")
        url, h, body = net.calls[0]
        self.assertEqual(url, D.TOKEN_URL)
        self.assertIn(b"grant_type=refresh_token", body)
        self.assertIn(b"client_id=APPKEY", body)
        self.assertEqual(net.calls[1][1]["Authorization"], "Bearer " + TOKEN)
        self.assertTrue(net.calls[1][0].startswith(D.RPC_BASE))

    def test_401_refreshes_once_then_missing_scope_is_not_retried(self):
        net = FakeNet(err(401, {"error_summary": "expired_access_token/"}), ok({"name": "a"}))
        self.client(net).get_metadata("/a")
        self.assertEqual([u for u, _h, _b in net.calls].count(D.TOKEN_URL), 2)
        net = FakeNet(err(401, {"error_summary": "missing_scope/"}))
        with self.assertRaises(D.DropboxError) as cm:
            self.client(net).get_metadata("/a")
        self.assertIn("権限", str(cm.exception))

    def test_5xx_and_429_retry_with_wait(self):
        net = FakeNet(err(500, {}), err(429, {"error_summary": "too_many_requests"}), ok({"entries": [{"name": "a"}], "has_more": False}))
        got = self.client(net).list_folder("/出力")
        self.assertEqual([e["name"] for e in got], ["a"])
        self.assertTrue(self.slept)
        net = FakeNet(*[err(503, {})] * D.RETRIES)
        with self.assertRaises(D.DropboxError) as cm:
            self.client(net).list_folder("/x")
        self.assertEqual(cm.exception.status, 503)

    def test_list_folder_continues_and_missing_folder_is_none(self):
        net = FakeNet(ok({"entries": [{"name": "a"}], "has_more": True, "cursor": "c1"}), ok({"entries": [{"name": "b"}], "has_more": False}))
        c = self.client(net)
        self.assertEqual([e["name"] for e in c.list_folder("/出力")], ["a", "b"])
        self.assertTrue(net.calls[-1][0].endswith("files/list_folder/continue"))
        self.assertIsNone(self.client(FakeNet(NOT_FOUND)).list_folder("/出力"))

    def test_delete_reports_missing_as_false(self):
        self.assertTrue(self.client(FakeNet(ok({}))).delete("/a"))
        self.assertFalse(self.client(FakeNet(NOT_FOUND)).delete("/a"))

    def test_upload_small_header_is_ascii(self):
        net = FakeNet(ok({"name": "依頼.json"}))
        name = self.client(net).upload_bytes(b"{}", "/送り返し/判断.verdict.json", overwrite=True)
        self.assertEqual(name, "依頼.json")
        arg = net.calls[1][1]["Dropbox-API-Arg"]
        arg.encode("ascii")   # ASCII だけ
        self.assertEqual(json.loads(arg), {"path": "/送り返し/判断.verdict.json", "mode": "overwrite", "autorename": False, "mute": True})

    def test_upload_large_uses_session_and_skips_received_chunk(self):
        p = os.path.join(self.tmp, "big.zip")
        with open(p, "wb") as f:
            f.write(b"x" * 25)
        old = (D.SINGLE_LIMIT, D.CHUNK)
        D.SINGLE_LIMIT, D.CHUNK = 10, 10
        self.addCleanup(lambda: setattr(D, "SINGLE_LIMIT", old[0]) or setattr(D, "CHUNK", old[1]))
        net = FakeNet(ok({"session_id": "S"}),
                      err(400, {"error": {".tag": "incorrect_offset", "correct_offset": 20}}),   # 前の回が実は届いていた
                      ok({}), ok({"name": "big.zip"}))
        self.assertEqual(self.client(net).upload(p, "/送り返し/big.zip"), "big.zip")
        eps = [u.rsplit("/2/", 1)[-1] for u, _h, _b in net.calls[1:]]
        self.assertEqual(eps, ["files/upload_session/start", "files/upload_session/append_v2", "files/upload_session/append_v2",
                               "files/upload_session/finish"])
        fin = json.loads(net.calls[-1][1]["Dropbox-API-Arg"])
        self.assertEqual(fin["cursor"], {"session_id": "S", "offset": 25})

    def test_download_resumes_with_range(self):
        data = b"0123456789" * 100

        def first(url, h, body):
            return 200, {"dropbox-api-result": json.dumps({"rev": "r1"})}, Stream(data, fail_after=300)

        def second(url, h, body):
            self.assertEqual(h.get("Range"), "bytes=300-")
            return 206, {"dropbox-api-result": json.dumps({"rev": "r1"})}, data[300:]
        part = os.path.join(self.tmp, "a.part")
        self.assertTrue(self.client(FakeNet(first, second)).download("/出力/a.zip", part, rev="r1"))
        with open(part, "rb") as f:
            self.assertEqual(f.read(), data)
        part = os.path.join(self.tmp, "a.part")
        net = FakeNet((200, {"dropbox-api-result": json.dumps({"rev": "r2"})}, b"abc"))
        with self.assertRaises(D.DropboxError) as cm:
            self.client(net).download("/出力/a.zip", part, rev="r1")
        self.assertEqual(cm.exception.status, -1)
        self.assertFalse(os.path.exists(part))
        self.assertFalse(self.client(FakeNet(NOT_FOUND)).download("/出力/a.zip", part))

    def test_read_small_truncates(self):
        got = self.client(FakeNet((200, {}, b"abcdef"))).read_small("/a", 4)
        self.assertEqual(got, (b"abcd", True))
        self.assertIsNone(self.client(FakeNet(NOT_FOUND)).read_small("/a"))

    def test_content_hash(self):
        p = os.path.join(self.tmp, "h.bin")
        data = b"hello" * 10
        with open(p, "wb") as f:
            f.write(data)
        self.assertEqual(D.content_hash(p), hashlib.sha256(hashlib.sha256(data).digest()).hexdigest())

    def test_cancelled(self):
        c = D.Client(D.Config("k", "r"), transport=FakeNet(ok({})), cancelled=lambda: True)
        with self.assertRaises(D.Cancelled):
            c.get_metadata("/a")

    def test_errors_and_logs_do_not_contain_keys(self):
        net = FakeNet(*[err(500, {"error_summary": "internal"})] * D.RETRIES)
        with self.assertRaises(D.DropboxError) as cm:
            self.client(net).list_folder("/x")
        text = str(cm.exception) + " ".join(self.logs)
        self.assertNotIn(TOKEN, text)
        self.assertNotIn(REFRESH, text)

    def test_real_transport_refuses_other_hosts(self):
        with self.assertRaises(D.DropboxError):
            D.urlopen_transport("https://example.com/2/files/upload", {}, b"", 5)


if __name__ == "__main__":
    unittest.main()
