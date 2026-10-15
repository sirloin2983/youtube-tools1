# -*- coding: utf-8 -*-
"""ytt/ytapi(YouTube Data API を 1 回呼ぶ口)のテスト。外へは繋がない。  py -3.10 -m unittest src/ytt/tests/test_ytapi.py -v

- 失敗の対応表(quota・key_invalid・api_permission・not_found・upstream・network・no_key)と 5xx の 1 回のやり直し
- 数え = 実際に外へ出るとき(と疑似のとき)だけ・キーは URL でなく見出し
- 覚え(cached)・soft
"""
import io
import json
import os
import sys
import unittest
import urllib.error
from unittest import mock

SRC = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))   # tests -> ytt -> src
sys.path.insert(0, SRC)
from ytt import ytapi  # noqa: E402
from ytt.errors import ApiError  # noqa: E402


def http_error(code, reason="", message=""):
    body = json.dumps({"error": {"message": message, "errors": [{"reason": reason}]}}).encode()
    return urllib.error.HTTPError("https://x", code, "err", {}, io.BytesIO(body))


class Resp:
    def __enter__(self):
        return self

    def __exit__(self, *a):
        return False


class TestGet(unittest.TestCase):
    def setUp(self):
        for p in (mock.patch.object(ytapi._env, "fake", return_value=False),
                  mock.patch.object(ytapi._key, "get_api_key", return_value=("KEY123", "env")),
                  mock.patch.object(ytapi.time, "sleep")):
            p.start()
            self.addCleanup(p.stop)

    def call(self, *effects):
        """urlopen が順に effects(例外なら投げる・それ以外は JSON の答え)を返したときの get -> (答え, 呼ばれた Request の列)"""
        seen, it = [], iter(effects)
        answer = []

        def fake_open(req, timeout=0):
            seen.append(req)
            e = next(it)
            if isinstance(e, Exception):
                raise e
            answer.append(e)
            return Resp()
        with mock.patch.object(ytapi.urllib.request, "urlopen", fake_open), mock.patch.object(ytapi.json, "load", side_effect=lambda r: answer[-1]):
            return ytapi.get("channels", {"id": "x"}), seen

    def failure(self, *effects):
        with self.assertRaises(ApiError) as cm:
            self.call(*effects)
        return cm.exception

    def test_table(self):
        for err, code in ((http_error(403, "quotaExceeded"), "quota"), (http_error(429, "rateLimitExceeded"), "quota"),
                          (http_error(400, "keyInvalid", "API key not valid"), "key_invalid"),
                          (http_error(403, "accessNotConfigured"), "api_permission"), (http_error(403, "ipRefererBlocked"), "api_permission"),
                          (http_error(404), "not_found"), (http_error(400, "playlistNotFound"), "not_found"),
                          (http_error(400, "other"), "upstream")):
            self.assertEqual(self.failure(err).code, code, err)
        self.assertEqual(self.failure(http_error(403, "commentsDisabled")).extra, {"detail": "HTTP 403", "reason": "commentsDisabled"})

    def test_retry_once_on_5xx_and_network(self):
        q0 = ytapi.used()
        ex = self.failure(http_error(503), http_error(503))
        self.assertEqual((ex.code, ex.extra["detail"]), ("upstream", "HTTP 503"))
        self.assertEqual(ytapi.used(), q0 + 1)   # やり直しても 1 回の呼びとして数える
        self.assertEqual(self.failure(urllib.error.URLError("down"), urllib.error.URLError("down")).code, "network")
        ok, seen = self.call(http_error(500), {"items": [1]})   # 1 回目の 5xx のあと 2 回目で通る
        self.assertEqual((ok, len(seen)), ({"items": [1]}, 2))

    def test_count_only_when_going_out_and_key_in_header(self):
        q0 = ytapi.used()
        with mock.patch.object(ytapi._key, "get_api_key", return_value=("", "")):
            with self.assertRaises(ApiError) as cm:
                ytapi.get("channels", {"id": "x"})
        self.assertEqual((cm.exception.code, ytapi.used()), ("no_key", q0))   # キーが無くて呼ばなかったときは数えない
        got, seen = self.call({"items": []})
        self.assertEqual((got, ytapi.used()), ({"items": []}, q0 + 1))
        self.assertNotIn("KEY123", seen[0].full_url)   # キーは URL に載せない(失敗の文・ログに出ても漏れない)
        self.assertEqual(seen[0].get_header("X-goog-api-key"), "KEY123")
        with mock.patch.object(ytapi.urllib.request, "urlopen", return_value=Resp()), mock.patch.object(ytapi.json, "load", return_value={}):
            ytapi.get("channels", {}, count=False)
        self.assertEqual(ytapi.used(), q0 + 1)


class TestFakeAndCache(unittest.TestCase):
    def test_fake_counts_and_is_used_only_in_fake_mode(self):
        calls = []
        self.addCleanup(ytapi.set_fake, ytapi._fake)   # 元の差し込み(rank が入れた物)に戻す
        ytapi.set_fake(lambda path, params: calls.append(path) or {"fake": path})
        q0 = ytapi.used()
        with mock.patch.object(ytapi._env, "fake", return_value=True):
            self.assertEqual(ytapi.get("videos", {}), {"fake": "videos"})
        self.assertEqual((calls, ytapi.used()), (["videos"], q0 + 1))
        with mock.patch.object(ytapi._env, "fake", return_value=False), mock.patch.object(ytapi._key, "get_api_key", return_value=("", "")):
            with self.assertRaises(ApiError):
                ytapi.get("videos", {})   # 疑似でなければ差し込みは使わない
        self.assertEqual(calls, ["videos"])

    def test_cached_and_soft(self):
        ytapi.CACHE.clear()
        self.addCleanup(ytapi.CACHE.clear)
        n = []
        self.assertEqual([ytapi.cached("k", lambda: n.append(1) or len(n), 100) for _ in range(3)], [1, 1, 1])

        def boom(code):
            raise ApiError(code, "m", 400)
        got = []
        self.assertEqual(ytapi.soft(lambda: boom("not_found"), "d", got.append), "d")
        self.assertEqual(len(got), 1)
        with self.assertRaises(ApiError):
            ytapi.soft(lambda: boom("quota"), "d")


if __name__ == "__main__":
    unittest.main()
