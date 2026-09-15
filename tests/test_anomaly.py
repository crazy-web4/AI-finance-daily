"""异常告警测试（建议 #10 T-D10）"""
import tempfile
import unittest
from pathlib import Path

import _path  # noqa: F401
import sys, os
sys.path.insert(0, os.path.dirname(__file__))
from _factory import make_store
from app.storage.indexer import build_index
from app.storage.db import connect
from app.utils import anomaly
from app.utils.anomaly import (
    load_watch_config, check_collection_drop, check_topic_drop,
    check_company_spike, run_checks, notify_local, Anomaly,
)


class TestAnomaly(unittest.TestCase):
    def setUp(self):
        self.tmp = Path(tempfile.mkdtemp())
        self.reports = self.tmp / "data" / "reports"
        self.db = self.tmp / "intel.db"
        make_store(self.tmp, ("2026-08-31", "2026-09-01"))
        build_index(self.db, self.reports, rebuild=True)

    def test_default_config_loaded(self):
        cfg = load_watch_config(self.tmp / "no_watch.yaml")
        self.assertIn("company_spike", cfg)
        self.assertEqual(cfg["company_spike"]["factor"], 4.0)

    def test_collection_drop_detected(self):
        runlogs = [("2026-08-31", {"articles": 500}), ("2026-09-01", {"articles": 10})]
        out = check_collection_drop(runlogs, {"ratio": 0.5, "min_baseline": 20})
        self.assertEqual(len(out), 1)
        self.assertEqual(out[0].rule, "collection_drop")

    def test_collection_no_drop(self):
        runlogs = [("2026-08-31", {"articles": 500}), ("2026-09-01", {"articles": 480})]
        self.assertEqual(check_collection_drop(runlogs, {"ratio": 0.5, "min_baseline": 20}), [])

    def test_collection_drop_small_baseline_ignored(self):
        runlogs = [("2026-08-31", {"articles": 10}), ("2026-09-01", {"articles": 1})]
        self.assertEqual(check_collection_drop(runlogs, {"ratio": 0.5, "min_baseline": 20}), [])

    def test_topic_drop_returns_list(self):
        conn = connect(self.db)
        out = check_topic_drop(conn, {"consecutive_days": 1})
        conn.close()
        self.assertIsInstance(out, list)

    def test_company_spike_returns_list(self):
        conn = connect(self.db)
        # 放宽阈值确保逻辑可跑
        out = check_company_spike(conn, {"factor": 0.1, "window_days": 7, "min_count": 1})
        conn.close()
        self.assertIsInstance(out, list)
        if out:
            self.assertEqual(out[0].rule, "company_spike")

    def test_run_checks_integration(self):
        runlogs = [("2026-08-31", {"articles": 500}), ("2026-09-01", {"articles": 5})]
        out = run_checks(self.db, runlogs=runlogs, config_path=self.tmp / "none.yaml")
        rules = {a.rule for a in out}
        self.assertIn("collection_drop", rules)
        for a in out:
            self.assertIsInstance(a.format(), str)

    def test_notify_local_returns_bool(self):
        self.assertIsInstance(notify_local("测试通知"), bool)

    def test_anomaly_dataclass(self):
        a = Anomaly(rule="x", severity="warning", message="m", context={"k": 1})
        self.assertIn("x", a.format())


if __name__ == "__main__":
    unittest.main()
