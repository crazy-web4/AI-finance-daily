"""限流检测与重试测试（建议 #12 T-D12）"""
import unittest

import _path  # noqa: F401
from app.utils.ratelimit import (
    is_rate_limit, retry_after_seconds, call_with_retry, acall_with_retry,
    RateLimitExhausted, RetryPolicy,
)


class RateLimitErr(Exception):
    def __init__(self, code=429, msg="rate limit"):
        super().__init__(msg)
        self.status_code = code


class TestRateLimit(unittest.TestCase):
    def test_detect_status_429(self):
        self.assertTrue(is_rate_limit(RateLimitErr()))

    def test_detect_message_quota(self):
        self.assertTrue(is_rate_limit(Exception("You exceeded your current quota")))
        self.assertTrue(is_rate_limit(Exception("请求过于频繁")))

    def test_non_rate_error(self):
        self.assertFalse(is_rate_limit(ValueError("bad json")))
        self.assertFalse(is_rate_limit(None))

    def test_retry_then_success(self):
        calls = {"n": 0}
        def fn():
            calls["n"] += 1
            if calls["n"] < 3:
                raise RateLimitErr()
            return "ok"
        sleeps = []
        out = call_with_retry(fn, policy=RetryPolicy(max_retries=3, base_delay=0.01),
                              sleep=lambda s: sleeps.append(s))
        self.assertEqual(out, "ok")
        self.assertEqual(calls["n"], 3)
        self.assertEqual(len(sleeps), 2)

    def test_exhausted_raises(self):
        def fn():
            raise RateLimitErr()
        with self.assertRaises(RateLimitExhausted):
            call_with_retry(fn, policy=RetryPolicy(max_retries=2, base_delay=0.01),
                            sleep=lambda s: None)

    def test_non_rate_error_propagates(self):
        def fn():
            raise KeyError("boom")
        with self.assertRaises(KeyError):
            call_with_retry(fn, policy=RetryPolicy(max_retries=3), sleep=lambda s: None)

    def test_retry_after_header(self):
        class Resp:
            headers = {"retry-after": "30"}
        e = Exception("429")
        e.response = Resp()
        self.assertEqual(retry_after_seconds(e), 30.0)

    def test_backoff_capped(self):
        p = RetryPolicy(base_delay=5, max_delay=60)
        self.assertLessEqual(p.backoff(10), 60)

    def test_async_retry(self):
        import asyncio
        calls = {"n": 0}
        async def fn():
            calls["n"] += 1
            if calls["n"] < 2:
                raise RateLimitErr()
            return "async-ok"
        out = asyncio.run(acall_with_retry(fn, policy=RetryPolicy(max_retries=3, base_delay=0.01),
                                          sleep=lambda s: asyncio.sleep(0)))
        self.assertEqual(out, "async-ok")


if __name__ == "__main__":
    unittest.main()
