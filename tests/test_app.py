"""
Unit tests for the TechStream Flask application.
Covers all four Golden Signal endpoints and chaos control.
"""


class TestHealth:
    def test_returns_200(self, app_client):
        resp = app_client.get("/health")
        assert resp.status_code == 200

    def test_status_field(self, app_client):
        data = app_client.get("/health").get_json()
        assert data["status"] == "healthy"

    def test_chaos_mode_field_present(self, app_client):
        data = app_client.get("/health").get_json()
        assert "chaos_mode" in data

    def test_chaos_mode_default_false(self, app_client):
        data = app_client.get("/health").get_json()
        assert data["chaos_mode"] is False

    def test_version_field(self, app_client):
        data = app_client.get("/health").get_json()
        assert "version" in data

    def test_uptime_field(self, app_client):
        data = app_client.get("/health").get_json()
        assert "uptime_seconds" in data
        assert data["uptime_seconds"] >= 0

    def test_system_metrics_present(self, app_client):
        data = app_client.get("/health").get_json()
        assert "system" in data
        assert "cpu_pct" in data["system"]
        assert "memory_mb" in data["system"]


class TestApiData:
    def test_returns_200_in_normal_mode(self, app_client):
        assert app_client.get("/api/data").status_code == 200

    def test_returns_records_list(self, app_client):
        data = app_client.get("/api/data").get_json()
        assert "records" in data
        assert len(data["records"]) == 20

    def test_record_schema(self, app_client):
        record = app_client.get("/api/data").get_json()["records"][0]
        assert "id" in record and "value" in record

    def test_returns_500_when_100pct_error_rate(self, app_client):
        app_client.post("/chaos", json={"enabled": True, "error_rate": 1.0, "latency_ms": 0})
        assert app_client.get("/api/data").status_code == 500

    def test_returns_200_when_0pct_error_rate(self, app_client):
        app_client.post("/chaos", json={"enabled": True, "error_rate": 0.0, "latency_ms": 0})
        assert app_client.get("/api/data").status_code == 200


class TestApiUsers:
    def test_returns_200(self, app_client):
        assert app_client.get("/api/users").status_code == 200

    def test_returns_users_list(self, app_client):
        data = app_client.get("/api/users").get_json()
        assert "users" in data
        assert len(data["users"]) == 5

    def test_user_schema(self, app_client):
        user = app_client.get("/api/users").get_json()["users"][0]
        assert "id" in user
        assert "name" in user
        assert "active" in user

    def test_active_field_is_bool(self, app_client):
        users = app_client.get("/api/users").get_json()["users"]
        for u in users:
            assert isinstance(u["active"], bool)


class TestChaosControl:
    def test_get_returns_current_state(self, app_client):
        resp = app_client.get("/chaos")
        assert resp.status_code == 200
        data = resp.get_json()
        assert "enabled" in data
        assert "error_rate" in data
        assert "latency_ms" in data

    def test_chaos_off_by_default(self, app_client):
        data = app_client.get("/chaos").get_json()
        assert data["enabled"] is False

    def test_enable_chaos(self, app_client):
        resp = app_client.post("/chaos", json={
            "enabled": True, "error_rate": 0.5, "latency_ms": 200
        })
        assert resp.status_code == 200
        data = resp.get_json()
        assert data["enabled"] is True
        assert data["error_rate"] == 0.5
        assert data["latency_ms"] == 200

    def test_reset_disables_chaos(self, app_client):
        app_client.post("/chaos", json={"enabled": True, "error_rate": 0.9})
        resp = app_client.post("/chaos/reset", json={})
        assert resp.status_code == 200
        assert resp.get_json()["state"]["enabled"] is False

    def test_reset_restores_defaults(self, app_client):
        app_client.post("/chaos", json={"enabled": True, "error_rate": 0.9, "latency_ms": 2000})
        app_client.post("/chaos/reset", json={})
        state = app_client.get("/chaos").get_json()
        assert state["enabled"] is False

    def test_cpu_spike_flag(self, app_client):
        app_client.post("/chaos", json={"enabled": True, "cpu_spike": True})
        state = app_client.get("/chaos").get_json()
        assert state["cpu_spike"] is True

    def test_memory_hog_flag(self, app_client):
        app_client.post("/chaos", json={"enabled": True, "memory_hog": True})
        state = app_client.get("/chaos").get_json()
        assert state["memory_hog"] is True

    def test_rejects_error_rate_above_1(self, app_client):
        resp = app_client.post("/chaos", json={"error_rate": 1.5})
        assert resp.status_code == 400

    def test_rejects_negative_error_rate(self, app_client):
        resp = app_client.post("/chaos", json={"error_rate": -0.1})
        assert resp.status_code == 400

    def test_rejects_negative_latency(self, app_client):
        resp = app_client.post("/chaos", json={"latency_ms": -100})
        assert resp.status_code == 400

    def test_accepts_boundary_error_rate_zero(self, app_client):
        resp = app_client.post("/chaos", json={"error_rate": 0.0})
        assert resp.status_code == 200

    def test_accepts_boundary_error_rate_one(self, app_client):
        resp = app_client.post("/chaos", json={"error_rate": 1.0})
        assert resp.status_code == 200


class TestMetrics:
    def test_metrics_endpoint_200(self, app_client):
        assert app_client.get("/metrics").status_code == 200

    def test_metrics_content_type(self, app_client):
        resp = app_client.get("/metrics")
        assert "text/plain" in resp.content_type

    def test_metrics_contains_request_counter(self, app_client):
        app_client.get("/api/data")
        resp = app_client.get("/metrics")
        assert b"http_requests_total" in resp.data

    def test_metrics_contains_error_counter(self, app_client):
        resp = app_client.get("/metrics")
        assert b"http_errors_total" in resp.data

    def test_metrics_contains_latency_histogram(self, app_client):
        resp = app_client.get("/metrics")
        assert b"http_request_duration_seconds" in resp.data

    def test_metrics_contains_active_requests(self, app_client):
        resp = app_client.get("/metrics")
        assert b"active_requests" in resp.data


class TestGoldenSignalsEndpoint:
    def test_signals_returns_200(self, app_client):
        assert app_client.get("/api/signals").status_code == 200

    def test_signals_has_four_sections(self, app_client):
        data = app_client.get("/api/signals").get_json()
        assert "errors" in data
        assert "latency" in data
        assert "traffic" in data
        assert "saturation" in data

    def test_signals_errors_has_rate_pct(self, app_client):
        data = app_client.get("/api/signals").get_json()
        assert "rate_pct" in data["errors"]

    def test_signals_saturation_has_cpu(self, app_client):
        data = app_client.get("/api/signals").get_json()
        assert "cpu_pct" in data["saturation"]
        assert "memory_mb" in data["saturation"]
