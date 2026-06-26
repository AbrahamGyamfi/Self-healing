"""
Unit tests for the chaos script — stats collector and helper functions.
No live network calls; external HTTP is mocked throughout.
"""

import sys
import os
from unittest.mock import patch, MagicMock

import pytest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "chaos"))

from chaos_script import Stats, SCENARIOS


class TestStats:
    def test_initial_state(self):
        s = Stats()
        assert s.total == 0
        assert s.errors == 0
        assert s.success == 0

    def test_record_success(self):
        s = Stats()
        s.record(200, 0.05)
        assert s.total == 1
        assert s.success == 1
        assert s.errors == 0

    def test_record_error(self):
        s = Stats()
        s.record(500, 0.1)
        assert s.errors == 1
        assert s.success == 0

    def test_record_mixed(self):
        s = Stats()
        for _ in range(7):
            s.record(200, 0.01)
        for _ in range(3):
            s.record(500, 0.05)
        assert s.total == 10
        assert s.errors == 3
        assert s.success == 7

    def test_report_error_rate(self):
        s = Stats()
        for _ in range(9):
            s.record(200, 0.01)
        s.record(500, 0.01)
        r = s.report()
        assert r["error_rate_pct"] == 10.0

    def test_report_latency_percentiles(self):
        s = Stats()
        for i in range(1, 101):
            s.record(200, i / 1000.0)  # 1ms to 100ms
        r = s.report()
        assert r["latency_p50_ms"] > 0
        assert r["latency_p99_ms"] >= r["latency_p95_ms"] >= r["latency_p50_ms"]

    def test_report_empty(self):
        s = Stats()
        r = s.report()
        assert r["total_requests"] == 0
        assert r["error_rate_pct"] == 0

    def test_thread_safety(self):
        import threading
        s = Stats()
        threads = [threading.Thread(target=lambda: s.record(200, 0.01)) for _ in range(100)]
        for t in threads:
            t.start()
        for t in threads:
            t.join()
        assert s.total == 100


class TestScenarios:
    def test_all_scenarios_defined(self):
        expected = {"errors", "latency", "cpu", "memory", "load", "full"}
        assert expected.issubset(set(SCENARIOS.keys()))

    def test_scenarios_are_callable(self):
        for name, fn in SCENARIOS.items():
            assert callable(fn), f"Scenario '{name}' is not callable"

    @patch("chaos_script._enable_chaos")
    @patch("chaos_script._disable_chaos")
    @patch("chaos_script._launch_workers", return_value=[])
    @patch("chaos_script.time.sleep")
    def test_errors_scenario_enables_and_disables(self, mock_sleep, mock_workers, mock_disable, mock_enable):
        SCENARIOS["errors"](duration=1, workers=1)
        mock_enable.assert_called_once()
        mock_disable.assert_called_once()

    @patch("chaos_script._enable_chaos")
    @patch("chaos_script._disable_chaos")
    @patch("chaos_script._launch_workers", return_value=[])
    @patch("chaos_script.time.sleep")
    def test_latency_scenario_sets_latency(self, mock_sleep, mock_workers, mock_disable, mock_enable):
        SCENARIOS["latency"](duration=1, workers=1)
        call_args = mock_enable.call_args[0][0]
        assert call_args.get("latency_ms", 0) > 0

    @patch("chaos_script._enable_chaos")
    @patch("chaos_script._disable_chaos")
    @patch("chaos_script._launch_workers", return_value=[])
    @patch("chaos_script.time.sleep")
    def test_cpu_scenario_sets_cpu_spike(self, mock_sleep, mock_workers, mock_disable, mock_enable):
        SCENARIOS["cpu"](duration=1, workers=1)
        call_args = mock_enable.call_args[0][0]
        assert call_args.get("cpu_spike") is True

    @patch("chaos_script._enable_chaos")
    @patch("chaos_script._disable_chaos")
    @patch("chaos_script._launch_workers", return_value=[])
    @patch("chaos_script.time.sleep")
    def test_full_scenario_calls_disable_at_end(self, mock_sleep, mock_workers, mock_disable, mock_enable):
        SCENARIOS["full"](duration=40, workers=1)
        mock_disable.assert_called_once()
