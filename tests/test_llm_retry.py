"""LLMClient 重试测试（第三轮 P0-2: chat_text 指数退避）"""
import time
import unittest

import _path  # noqa: F401
from app.agents.base import LLMClient


class _FlakyCompletions:
    """前 n-1 次抛异常，第 n 次成功。"""
    def __init__(self, fail_times: int):
        self.fail_times = fail_times
        self.calls = 0

    def create(self, **kwargs):
        self.calls += 1
        if self.calls <= self.fail_times:
            raise RuntimeError("transient api error")
        class _Msg:
            content = "ok"
        class _Choice:
            message = _Msg()
        class _Resp:
            choices = [_Choice()]
        return _Resp()


def _mk_client():
    # 显式传 key/base_url，避免依赖环境变量
    return LLMClient(api_key="test-key", base_url="http://test.local", model="test-model")


class TestChatTextRetry(unittest.TestCase):
    def setUp(self):
        self._orig_sleep = time.sleep
        time.sleep = lambda s: None  # 退避不真睡

    def tearDown(self):
        time.sleep = self._orig_sleep

    def test_retry_then_success(self):
        c = _mk_client()
        flaky = _FlakyCompletions(fail_times=2)
        c._client = type("C", (), {"chat": type("Ch", (), {"completions": flaky})()})()
        out = c.chat_text("s", "u")
        self.assertEqual(out, "ok")
        self.assertEqual(flaky.calls, 3)

    def test_raises_after_exhausted(self):
        c = _mk_client()
        flaky = _FlakyCompletions(fail_times=99)
        c._client = type("C", (), {"chat": type("Ch", (), {"completions": flaky})()})()
        with self.assertRaises(RuntimeError):
            c.chat_text("s", "u")
        self.assertEqual(flaky.calls, 3)  # 默认 max_retries=2 → 共 3 次


if __name__ == "__main__":
    unittest.main()
