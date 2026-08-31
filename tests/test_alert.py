"""告警模块测试（第三轮 P0-4: 接线前先保证无 webhook 时静默不影响主流程）"""
import unittest

import _path  # noqa: F401
from app.utils.alert import send_alert


class TestAlert(unittest.TestCase):
    def test_no_webhook_silent_false(self):
        """未配置 ALERT_WEBHOOK_URL 时应返回 False 且不抛异常"""
        import os
        old = os.environ.pop("ALERT_WEBHOOK_URL", None)
        try:
            self.assertFalse(send_alert("test", level="error"))
        finally:
            if old is not None:
                os.environ["ALERT_WEBHOOK_URL"] = old

    def test_bad_url_returns_false_not_raise(self):
        """webhook 不可达时不抛异常"""
        self.assertFalse(
            send_alert("test", webhook_url="https://localhost.invalid/hook", timeout=1)
        )


if __name__ == "__main__":
    unittest.main()
