import time
import random
import threading
import os

from flask import Flask, jsonify, request, render_template
import psutil
from prometheus_client import (
    Counter, Histogram, Gauge,
    generate_latest, CONTENT_TYPE_LATEST,
)

app = Flask(__name__)
_START_TIME = time.time()

# ---------------------------------------------------------------------------
# Prometheus metrics  (Golden Signals)
# ---------------------------------------------------------------------------
REQUEST_COUNT = Counter(
    "http_requests_total",
    "Total HTTP requests",
    ["method", "endpoint", "status"],
)
REQUEST_LATENCY = Histogram(
    "http_request_duration_seconds",
    "HTTP request latency in seconds",
    ["endpoint"],
    buckets=[0.005, 0.01, 0.025, 0.05, 0.1, 0.25, 0.5, 1.0, 2.5, 5.0, 10.0],
)
ERROR_COUNTER = Counter(
    "http_errors_total",
    "Total HTTP 5xx errors",
    ["endpoint"],
)
CPU_USAGE = Gauge("process_cpu_percent", "Process CPU utilisation (%)")
MEMORY_BYTES = Gauge("process_memory_bytes", "Process resident set size (bytes)")
ACTIVE_REQUESTS = Gauge("active_requests", "In-flight HTTP requests")

# ---------------------------------------------------------------------------
# Chaos state  (toggled by /chaos POST)
# ---------------------------------------------------------------------------
chaos = {
    "enabled": False,
    "error_rate": 0.30,   # fraction of requests that return 500
    "latency_ms": 500,    # extra latency injected per request
    "cpu_spike": False,   # burn CPU on each request
    "memory_hog": False,  # allocate a large buffer once
}
_memory_hog_buffer: list = []


def _collect_system_metrics() -> None:
    proc = psutil.Process()
    while True:
        try:
            CPU_USAGE.set(proc.cpu_percent(interval=None))
            MEMORY_BYTES.set(proc.memory_info().rss)
        except Exception:
            pass
        time.sleep(5)


threading.Thread(target=_collect_system_metrics, daemon=True).start()

# ---------------------------------------------------------------------------
# Request lifecycle hooks
# ---------------------------------------------------------------------------

@app.before_request
def _start_timer():
    request.start_time = time.perf_counter()
    ACTIVE_REQUESTS.inc()


@app.after_request
def _record_metrics(response):
    elapsed = time.perf_counter() - request.start_time
    REQUEST_COUNT.labels(
        method=request.method,
        endpoint=request.path,
        status=str(response.status_code),
    ).inc()
    REQUEST_LATENCY.labels(endpoint=request.path).observe(elapsed)
    if response.status_code >= 500:
        ERROR_COUNTER.labels(endpoint=request.path).inc()
    ACTIVE_REQUESTS.dec()
    return response

# ---------------------------------------------------------------------------
# Application endpoints
# ---------------------------------------------------------------------------

@app.route("/")
def index():
    return render_template("index.html")


@app.route("/api/info")
def api_info():
    return jsonify(
        service="TechStream API",
        version="1.0.0",
        chaos_active=chaos["enabled"],
        endpoints=["/health", "/api/data", "/api/users", "/chaos", "/metrics"],
    )


@app.route("/api/signals")
def api_signals():
    """Aggregated Golden Signal snapshot for the dashboard."""
    proc = psutil.Process()
    cpu = proc.cpu_percent(interval=None)
    mem = proc.memory_info().rss

    # Calculate error rate and RPS from Prometheus registry counters
    # (approximate from in-process counters since last scrape)
    total = sum(
        REQUEST_COUNT.labels(method=m, endpoint=e, status=s)._value.get()
        for m in ["GET", "POST"]
        for e in ["/api/data", "/api/users", "/health", "/chaos", "/chaos/reset", "/metrics", "/", "/api/signals", "/api/alerts"]
        for s in ["200", "500", "404"]
        if REQUEST_COUNT.labels(method=m, endpoint=e, status=s)._value.get() > 0
    ) or 1

    errors = sum(
        ERROR_COUNTER.labels(endpoint=e)._value.get()
        for e in ["/api/data", "/api/users", "/chaos"]
    )

    return jsonify(
        errors=dict(
            rate_pct=round(errors / total * 100, 2),
        ),
        latency=dict(
            p50_ms=0,
            p99_ms=0,
        ),
        traffic=dict(
            rps=round(total / max((time.time() - _START_TIME), 1), 2),
        ),
        saturation=dict(
            cpu_pct=round(cpu, 1),
            memory_mb=round(mem / 1e6, 1),
            active_requests=int(ACTIVE_REQUESTS._value.get()),
        ),
    )


@app.route("/api/alerts")
def api_alerts():
    """Proxy Prometheus alert rules for the dashboard."""
    import urllib.request as ur
    prometheus_url = os.getenv("PROMETHEUS_URL", "http://prometheus:9090")
    try:
        with ur.urlopen(f"{prometheus_url}/api/v1/rules", timeout=3) as resp:
            data = __import__("json").loads(resp.read())
        rules = []
        for g in data.get("data", {}).get("groups", []):
            for r in g.get("rules", []):
                if r.get("type") == "alerting":
                    rules.append(dict(
                        name=r["name"],
                        state=r.get("state", "inactive"),
                        description=r.get("annotations", {}).get("summary", ""),
                    ))
        return jsonify(alerts=rules)
    except Exception:
        return jsonify(alerts=[])


@app.route("/health")
def health():
    proc = psutil.Process()
    return jsonify(
        status="healthy",
        version="1.0.0",
        uptime_seconds=round(time.time() - _START_TIME, 1),
        chaos_mode=chaos["enabled"],
        system=dict(
            cpu_pct=round(proc.cpu_percent(interval=None), 1),
            memory_mb=round(proc.memory_info().rss / 1e6, 1),
            threads=proc.num_threads(),
        ),
    )


@app.route("/api/data")
def api_data():
    _apply_chaos()
    return jsonify(
        records=[{"id": i, "value": round(random.random(), 4)} for i in range(20)],
        generated_at=time.time(),
    )


@app.route("/api/users")
def api_users():
    _apply_chaos()
    return jsonify(
        users=[
            {"id": i, "name": f"user_{i}", "active": random.choice([True, False])}
            for i in range(5)
        ]
    )


def _apply_chaos():
    if not chaos["enabled"]:
        return
    if chaos["latency_ms"] > 0:
        time.sleep(chaos["latency_ms"] / 1000.0)
    if chaos["cpu_spike"]:
        deadline = time.time() + 0.15
        while time.time() < deadline:
            _ = sum(x ** 2 for x in range(50_000))
    if chaos["memory_hog"] and not _memory_hog_buffer:
        _memory_hog_buffer.extend([b"\x00" * 1024] * 50_000)  # ~50 MB
    if random.random() < chaos["error_rate"]:
        raise InternalError("Simulated fault injected by chaos engine")


class InternalError(Exception):
    pass


@app.errorhandler(InternalError)
def handle_internal(exc):
    return jsonify(error="Internal Server Error", detail=str(exc)), 500


# ---------------------------------------------------------------------------
# Chaos control endpoints
# ---------------------------------------------------------------------------

@app.route("/chaos", methods=["GET"])
def get_chaos():
    return jsonify(chaos)


@app.route("/chaos", methods=["POST"])
def set_chaos():
    data = request.get_json(silent=True) or {}

    error_rate = data.get("error_rate", chaos["error_rate"])
    latency_ms = data.get("latency_ms", chaos["latency_ms"])

    if not (0.0 <= float(error_rate) <= 1.0):
        return jsonify(error="error_rate must be between 0.0 and 1.0"), 400
    if int(latency_ms) < 0:
        return jsonify(error="latency_ms must be >= 0"), 400

    chaos["enabled"] = bool(data.get("enabled", chaos["enabled"]))
    chaos["error_rate"] = float(error_rate)
    chaos["latency_ms"] = int(latency_ms)
    chaos["cpu_spike"] = bool(data.get("cpu_spike", chaos["cpu_spike"]))
    chaos["memory_hog"] = bool(data.get("memory_hog", chaos["memory_hog"]))
    if not chaos["memory_hog"]:
        _memory_hog_buffer.clear()
    return jsonify(chaos), 200


@app.route("/chaos/reset", methods=["POST"])
def reset_chaos():
    chaos.update(
        enabled=False, error_rate=0.30,
        latency_ms=500, cpu_spike=False, memory_hog=False,
    )
    _memory_hog_buffer.clear()
    return jsonify({"message": "chaos reset", "state": chaos})

# ---------------------------------------------------------------------------
# Prometheus scrape endpoint
# ---------------------------------------------------------------------------

@app.route("/metrics")
def metrics():
    return generate_latest(), 200, {"Content-Type": CONTENT_TYPE_LATEST}


if __name__ == "__main__":
    app.run(host="0.0.0.0", port=int(os.getenv("PORT", 5000)), debug=False)
