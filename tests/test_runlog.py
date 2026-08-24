"""运行报告测试（第二轮 R18）"""
import json
import os
import tempfile
import unittest

import _path  # noqa: F401
from app.utils.runlog import RunReport


class TestRunReport(unittest.TestCase):
    def test_basic_lifecycle(self):
        rr = RunReport(mode="test")
        self.assertEqual(rr.data["mode"], "test")
        self.assertIn("started_at", rr.data)

        rr.stage("collect")
        rr.set("articles", 100)
        rr.flag("warning: something low")

        with tempfile.TemporaryDirectory() as tmp:
            path = rr.finish(tmp, ok=True)
            self.assertTrue(path.exists())
            data = json.loads(path.read_text(encoding="utf-8"))
            self.assertEqual(data["mode"], "test")
            self.assertTrue(data["success"])
            self.assertIn("elapsed_sec", data)
            self.assertIn("finished_at", data)
            self.assertEqual(data["articles"], 100)
            self.assertEqual(len(data["flags"]), 1)
            self.assertIn("collect", data["stages"])

    def test_failure_flag_preserved(self):
        rr = RunReport(mode="test")
        rr.flag("error: oops")
        with tempfile.TemporaryDirectory() as tmp:
            path = rr.finish(tmp, ok=False)
            data = json.loads(path.read_text(encoding="utf-8"))
            self.assertFalse(data["success"])
            self.assertIn("oops", data["flags"][0])

    def test_stage_timing_numeric(self):
        rr = RunReport(mode="test")
        rr.stage("step1")
        rr.stage("step2")
        self.assertIsInstance(rr.data["stages"]["step1"], float)
        self.assertIsInstance(rr.data["stages"]["step2"], float)


if __name__ == "__main__":
    unittest.main()
