"""
Unit tests for the remediation webhook service.
Docker and external HTTP calls are mocked to allow offline testing.
"""

import json
import threading
from http.server import HTTPServer
from unittest.mock import patch, MagicMock
import urllib.request

import pytest

import sys, os
sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "remediation"))

import webhook_handler as wh


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _start_server(port=18080):
    server = HTTPServer(("127.0.0.1", port), wh.Handler)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    return server


def _get(path, port=18080):
    url = f"http://127.0.0.1:{port}{path}"
    with urllib.request.urlopen(url, timeout=5) as r:
        return r.status, json.loads(r.read())


def _post(path, body, port=18080):
    data = json.dumps(body).encode()
    req = urllib.request.Request(
        f"http://127.0.0.1:{port}{path}",
        data=data,
        headers={"Content-Type": "application/json"},
        method="POST",
    )
    try:
        with urllib.request.urlopen(req, timeout=5) as r:
            return r.status, json.loads(r.read())
    except urllib.error.HTTPError as exc:
        return exc.code, {}


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------

@pytest.fixture(scope="module")
def server():
    srv = _start_server(18080)
    yield srv
    srv.shutdown()


@pytest.fixture(autouse=True)
def reset_history():
    wh._history.clear()
    wh._last_remediation_time = 0


# ---------------------------------------------------------------------------
# Health
# ---------------------------------------------------------------------------

class TestHealth:
    def test_health_returns_200(self, server):
        status, data = _get("/health")
        assert status == 200

    def test_health_body(self, server):
        _, data = _get("/health")
        assert data["status"] == "ok"
        assert data["service"] == "remediation"


# ---------------------------------------------------------------------------
# Webhook (notification only)
# ---------------------------------------------------------------------------

class TestWebhook:
    def test_webhook_accepts_alerts(self, server):
        payload = {"alerts": [{"labels": {"alertname": "HighErrorRate"}, "status": "firing"}]}
        status, data = _post("/webhook", payload)
        assert status == 200
        assert data["received"] == 1

    def test_webhook_empty_alerts(self, server):
        status, data = _post("/webhook", {"alerts": []})
        assert status == 200
        assert data["received"] == 0

    def test_webhook_adds_to_history(self, server):
        payload = {"alerts": [{"labels": {"alertname": "TestAlert"}, "status": "firing"}]}
        _post("/webhook", payload)
        _, history = _get("/history")
        assert any(e.get("alertname") == "TestAlert" for e in history["events"])


# ---------------------------------------------------------------------------
# Remediation
# ---------------------------------------------------------------------------

class TestRemediation:
    @patch("webhook_handler._docker_restart", return_value=(True, "restarted"))
    @patch("webhook_handler._reset_chaos",   return_value=(True, "reset"))
    def test_remediation_executes_steps(self, mock_chaos, mock_docker, server):
        payload = {"alerts": [{
            "status": "firing",
            "labels": {"alertname": "HighErrorRate", "severity": "critical", "signal": "errors"}
        }]}
        status, data = _post("/remediate", payload)
        assert status == 200
        assert data["action"] == "remediation_executed"

    @patch("webhook_handler._docker_restart", return_value=(True, "restarted"))
    @patch("webhook_handler._reset_chaos",   return_value=(True, "reset"))
    def test_remediation_cooldown(self, mock_chaos, mock_docker, server):
        import time
        wh._last_remediation_time = time.time()  # simulate recent remediation
        payload = {"alerts": [{"status": "firing", "labels": {"alertname": "X", "signal": "errors"}}]}
        _, data = _post("/remediate", payload)
        assert data["action"] == "skipped"

    def test_no_firing_alerts_skipped(self, server):
        payload = {"alerts": [{"status": "resolved", "labels": {"alertname": "X"}}]}
        status, data = _post("/remediate", payload)
        assert status == 200
        assert "no firing" in data.get("message", "").lower()

    def test_history_records_remediation(self, server):
        wh._last_remediation_time = 0
        with patch("webhook_handler._docker_restart", return_value=(True, "ok")), \
             patch("webhook_handler._reset_chaos", return_value=(True, "ok")):
            payload = {"alerts": [{"status": "firing", "labels": {"alertname": "HighErrorRate", "signal": "errors"}}]}
            _post("/remediate", payload)
        _, history = _get("/history")
        assert any(e.get("type") == "remediation" for e in history["events"])


# ---------------------------------------------------------------------------
# History
# ---------------------------------------------------------------------------

class TestHistory:
    def test_history_returns_200(self, server):
        status, _ = _get("/history")
        assert status == 200

    def test_history_has_events_key(self, server):
        _, data = _get("/history")
        assert "events" in data

    def test_history_is_list(self, server):
        _, data = _get("/history")
        assert isinstance(data["events"], list)
