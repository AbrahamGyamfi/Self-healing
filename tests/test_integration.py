"""
Integration tests — require the full Docker Compose stack to be running.

Run only when the stack is up:
    pytest tests/test_integration.py -v

Skipped automatically in CI unless INTEGRATION_TESTS=1 is set.
"""

import json
import os
import urllib.error
import urllib.request

import pytest

STACK_UP = os.getenv("INTEGRATION_TESTS") == "1"
APP_URL = os.getenv("TARGET_URL", "http://localhost:5000")
PROM_URL = os.getenv("PROMETHEUS_URL", "http://localhost:9090")
REMED_URL = os.getenv("REMEDIATION_URL", "http://localhost:8080")

skip_if_no_stack = pytest.mark.skipif(
    not STACK_UP,
    reason="Set INTEGRATION_TESTS=1 and start the stack with docker compose up -d",
)


def _get(url: str, timeout: int = 5) -> tuple[int, dict]:
    try:
        with urllib.request.urlopen(url, timeout=timeout) as r:
            return r.status, json.loads(r.read())
    except urllib.error.HTTPError as e:
        return e.code, {}
    except Exception as e:
        pytest.skip(f"Stack unreachable ({url}): {e}")


def _post(url: str, body: dict, timeout: int = 5) -> tuple[int, dict]:
    data = json.dumps(body).encode()
    req = urllib.request.Request(
        url, data=data, headers={"Content-Type": "application/json"}, method="POST"
    )
    try:
        with urllib.request.urlopen(req, timeout=timeout) as r:
            return r.status, json.loads(r.read())
    except urllib.error.HTTPError as e:
        return e.code, {}
    except Exception as e:
        pytest.skip(f"Stack unreachable ({url}): {e}")


# ---------------------------------------------------------------------------
# App integration
# ---------------------------------------------------------------------------

@skip_if_no_stack
class TestAppIntegration:
    def test_health_endpoint_live(self):
        status, data = _get(f"{APP_URL}/health")
        assert status == 200
        assert data["status"] == "healthy"

    def test_api_data_live(self):
        status, data = _get(f"{APP_URL}/api/data")
        assert status == 200
        assert len(data["records"]) == 20

    def test_api_users_live(self):
        status, data = _get(f"{APP_URL}/api/users")
        assert status == 200
        assert len(data["users"]) == 5

    def test_golden_signals_live(self):
        status, data = _get(f"{APP_URL}/api/signals")
        assert status == 200
        for key in ("errors", "latency", "traffic", "saturation"):
            assert key in data

    def test_metrics_endpoint_live(self):
        try:
            with urllib.request.urlopen(f"{APP_URL}/metrics", timeout=5) as r:
                body = r.read()
        except Exception as e:
            pytest.skip(str(e))
        assert b"http_requests_total" in body

    def test_chaos_state_default_off(self):
        _, chaos = _get(f"{APP_URL}/chaos")
        assert chaos["enabled"] is False

    def test_chaos_round_trip(self):
        _post(f"{APP_URL}/chaos", {"enabled": True, "error_rate": 0.5})
        _, state = _get(f"{APP_URL}/chaos")
        assert state["enabled"] is True
        assert state["error_rate"] == 0.5
        # Always reset after
        _post(f"{APP_URL}/chaos/reset", {})

    def test_chaos_reset_live(self):
        _post(f"{APP_URL}/chaos", {"enabled": True, "error_rate": 0.9})
        status, data = _post(f"{APP_URL}/chaos/reset", {})
        assert status == 200
        assert data["state"]["enabled"] is False

    def test_error_injection_live(self):
        _post(f"{APP_URL}/chaos", {"enabled": True, "error_rate": 1.0})
        status, _ = _get(f"{APP_URL}/api/data")
        assert status == 500
        _post(f"{APP_URL}/chaos/reset", {})

    def test_chaos_input_validation_rejects_invalid_error_rate(self):
        status, data = _post(f"{APP_URL}/chaos", {"error_rate": 1.5})
        assert status == 400

    def test_chaos_input_validation_rejects_negative_latency(self):
        status, data = _post(f"{APP_URL}/chaos", {"latency_ms": -100})
        assert status == 400


# ---------------------------------------------------------------------------
# Prometheus integration
# ---------------------------------------------------------------------------

@skip_if_no_stack
class TestPrometheusIntegration:
    def test_prometheus_reachable(self):
        status, data = _get(f"{PROM_URL}/api/v1/query?query=up")
        assert status == 200
        assert data["status"] == "success"

    def test_app_target_up(self):
        status, data = _get(
            f"{PROM_URL}/api/v1/query?query=up%7Bjob%3D%22techstream_api%22%7D"
        )
        assert status == 200
        results = data["data"]["result"]
        assert any(float(r["value"][1]) == 1.0 for r in results), \
            "techstream_api target is not UP in Prometheus"

    def test_error_counter_exists(self):
        status, data = _get(
            f"{PROM_URL}/api/v1/query?query=http_errors_total"
        )
        assert status == 200
        assert data["data"]["result"] is not None

    def test_alert_rules_loaded(self):
        status, data = _get(f"{PROM_URL}/api/v1/rules")
        assert status == 200
        rule_names = [
            r["name"]
            for g in data["data"]["groups"]
            for r in g["rules"]
        ]
        for expected in ("HighErrorRate", "HighLatencyP99", "HighCpuSaturation"):
            assert expected in rule_names, f"Alert rule '{expected}' not loaded"


# ---------------------------------------------------------------------------
# Remediation service integration
# ---------------------------------------------------------------------------

@skip_if_no_stack
class TestRemediationIntegration:
    def test_remediation_health(self):
        status, data = _get(f"{REMED_URL}/health")
        assert status == 200
        assert data["status"] == "ok"

    def test_history_endpoint(self):
        status, data = _get(f"{REMED_URL}/history")
        assert status == 200
        assert "events" in data

    def test_webhook_receives_alerts(self):
        payload = {"alerts": [{"labels": {"alertname": "IntegrationTest"}, "status": "firing"}]}
        status, data = _post(f"{REMED_URL}/webhook", payload)
        assert status == 200
        assert data["received"] == 1
