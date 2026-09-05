"""健康检查 doctor 测试（建议 #3 T-A3）"""
import tempfile
import unittest
from pathlib import Path

import _path  # noqa: F401
import sys, os
sys.path.insert(0, os.path.dirname(__file__))
from _factory import make_store
from app.utils import doctor
from app.utils.doctor import run_checks, format_report, CheckResult, OK, WARN, ERROR


def fake_pw(level=OK):
    return lambda: CheckResult("Playwright", level, "mocked")


class TestDoctor(unittest.TestCase):
    def setUp(self):
        self.tmp = Path(tempfile.mkdtemp())
        self.store = make_store(self.tmp, ("2026-08-31", "2026-09-01"))
        self.good_env = {"ANYSEARCH_API_KEY": "as_sk_realkey1234567", "ARK_API_KEY": "ark", "OPENAI_API_KEY": "oai"}

    def _run(self, env):
        return run_checks(base_dir=self.tmp, env=env, playwright_probe=fake_pw())

    def test_healthy_env_all_ok(self):
        results = self._run(self.good_env)
        names = {r.name: r for r in results}
        self.assertEqual(names["Python 版本"].level, OK)
        self.assertEqual(names["搜索 API Key"].level, OK)
        self.assertEqual(names["LLM 配置"].level, OK)
        self.assertEqual(names["Playwright"].level, OK)

    def test_missing_search_key_error(self):
        env = dict(self.good_env)
        del env["ANYSEARCH_API_KEY"]
        results = run_checks(base_dir=self.tmp, env=env, playwright_probe=fake_pw())
        key = [r for r in results if r.name == "搜索 API Key"][0]
        self.assertEqual(key.level, ERROR)
        self.assertTrue(key.fix)

    def test_placeholder_key_error(self):
        env = dict(self.good_env)
        env["ANYSEARCH_API_KEY"] = "as_sk_your_key_here"
        results = run_checks(base_dir=self.tmp, env=env, playwright_probe=fake_pw())
        self.assertEqual([r for r in results if r.name == "搜索 API Key"][0].level, ERROR)

    def test_single_llm_warns(self):
        env = {"ANYSEARCH_API_KEY": "as_sk_realkey1234567", "ARK_API_KEY": "ark"}
        results = run_checks(base_dir=self.tmp, env=env, playwright_probe=fake_pw())
        self.assertEqual([r for r in results if r.name == "LLM 配置"][0].level, WARN)

    def test_no_llm_error(self):
        env = {"ANYSEARCH_API_KEY": "as_sk_realkey1234567"}
        results = run_checks(base_dir=self.tmp, env=env, playwright_probe=fake_pw())
        self.assertEqual([r for r in results if r.name == "LLM 配置"][0].level, ERROR)

    def test_runlog_success_rate(self):
        results = self._run(self.good_env)
        rl = [r for r in results if r.name == "运行成功率"][0]
        self.assertEqual(rl.level, OK)  # 全部成功

    def test_writable_check(self):
        results = self._run(self.good_env)
        names = [r.name for r in results]
        self.assertIn("缓存目录 写权限", names)
        self.assertIn("日志目录 写权限", names)

    def test_format_and_exit(self):
        results = self._run(self.good_env)
        text = format_report(results)
        self.assertIn("健康检查", text)
        self.assertFalse(any(r.level == ERROR for r in results))

    def test_python_version_check(self):
        self.assertEqual(doctor._check_python((3, 10)).level, OK)


if __name__ == "__main__":
    unittest.main()
