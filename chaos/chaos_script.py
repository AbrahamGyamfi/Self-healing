"""
TechStream Chaos Script
=======================
Injects faults into the TechStream API to simulate real-world incidents.

Usage examples
--------------
  # Run the full incident scenario
  python chaos_script.py --scenario full

  # Inject only errors for 60 s
  python chaos_script.py --scenario errors --duration 60

  # Hammer the API with 50 concurrent workers
  python chaos_script.py --scenario load --workers 50 --duration 120

  # CPU spike
  python chaos_script.py --scenario cpu --duration 30
"""

import argparse
import json
import os
import sys
import time
import threading
import random
import signal
import urllib.request
import urllib.error
from dataclasses import dataclass, field
from datetime import datetime

BASE_URL = os.getenv("TARGET_URL", "http://localhost:5000")
STOP_EVENT = threading.Event()

# ---------------------------------------------------------------------------
# Stats collector
# ---------------------------------------------------------------------------

@dataclass
class Stats:
    total: int = 0
    errors: int = 0
    success: int = 0
    latencies: list = field(default_factory=list)
    lock: threading.Lock = field(default_factory=threading.Lock)

    def record(self, status: int, latency: float):
        with self.lock:
            self.total += 1
            self.latencies.append(latency)
            if status >= 500:
                self.errors += 1
            else:
                self.success += 1

    def report(self) -> dict:
        with self.lock:
            lat = sorted(self.latencies)
            n = len(lat)
            return {
                "total_requests": self.total,
                "success": self.success,
                "errors": self.errors,
                "error_rate_pct": round(self.errors / self.total * 100, 2) if self.total else 0,
                "latency_p50_ms": round(lat[int(n * 0.50)] * 1000, 1) if n else 0,
                "latency_p95_ms": round(lat[int(n * 0.95)] * 1000, 1) if n else 0,
                "latency_p99_ms": round(lat[int(n * 0.99)] * 1000, 1) if n else 0,
            }


STATS = Stats()

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _post_json(path: str, payload: dict) -> int:
    data = json.dumps(payload).encode()
    req = urllib.request.Request(
        f"{BASE_URL}{path}",
        data=data,
        headers={"Content-Type": "application/json"},
        method="POST",
    )
    try:
        with urllib.request.urlopen(req, timeout=10) as resp:
            return resp.status
    except urllib.error.HTTPError as exc:
        return exc.code
    except Exception:
        return 0


def _get(path: str) -> tuple[int, float]:
    t0 = time.perf_counter()
    try:
        req = urllib.request.Request(f"{BASE_URL}{path}", method="GET")
        with urllib.request.urlopen(req, timeout=10) as resp:
            resp.read()
            return resp.status, time.perf_counter() - t0
    except urllib.error.HTTPError as exc:
        return exc.code, time.perf_counter() - t0
    except Exception:
        return 0, time.perf_counter() - t0


def _enable_chaos(config: dict):
    status = _post_json("/chaos", config)
    ts = datetime.now().strftime("%H:%M:%S")
    print(f"[{ts}] CHAOS ON  → {config}  (HTTP {status})")


def _disable_chaos():
    status = _post_json("/chaos/reset", {})
    ts = datetime.now().strftime("%H:%M:%S")
    print(f"[{ts}] CHAOS OFF → reset (HTTP {status})")


def _worker(endpoints: list[str]):
    while not STOP_EVENT.is_set():
        endpoint = random.choice(endpoints)
        status, latency = _get(endpoint)
        STATS.record(status, latency)
        time.sleep(random.uniform(0.02, 0.1))


def _launch_workers(n: int, endpoints: list[str]) -> list[threading.Thread]:
    threads = [
        threading.Thread(target=_worker, args=(endpoints,), daemon=True)
        for _ in range(n)
    ]
    for t in threads:
        t.start()
    return threads

# ---------------------------------------------------------------------------
# Scenarios
# ---------------------------------------------------------------------------

ENDPOINTS = ["/api/data", "/api/users", "/health"]


def scenario_errors(duration: int, workers: int):
    """Spike error rate to ~30 % (triggers HighErrorRate alert)."""
    _enable_chaos({"enabled": True, "error_rate": 0.30, "latency_ms": 0})
    _launch_workers(workers, ENDPOINTS)
    time.sleep(duration)
    _disable_chaos()


def scenario_latency(duration: int, workers: int):
    """Inject 700 ms latency per request (triggers HighLatencyP99 alert)."""
    _enable_chaos({"enabled": True, "error_rate": 0.0, "latency_ms": 700})
    _launch_workers(workers, ENDPOINTS)
    time.sleep(duration)
    _disable_chaos()


def scenario_cpu(duration: int, workers: int):
    """Spike CPU on every request (triggers HighCpuSaturation alert)."""
    _enable_chaos({"enabled": True, "error_rate": 0.0, "latency_ms": 0, "cpu_spike": True})
    _launch_workers(workers, ENDPOINTS)
    time.sleep(duration)
    _disable_chaos()


def scenario_memory(duration: int, workers: int):
    """Allocate a large buffer in-process (triggers HighMemorySaturation alert)."""
    _enable_chaos({"enabled": True, "error_rate": 0.0, "latency_ms": 0, "memory_hog": True})
    _launch_workers(workers, ENDPOINTS)
    time.sleep(duration)
    _disable_chaos()


def scenario_load(duration: int, workers: int):
    """Flood the API with traffic without injecting errors."""
    _launch_workers(workers, ENDPOINTS)
    time.sleep(duration)


def scenario_full(duration: int, workers: int):
    """
    Staged incident scenario:
      Phase 1 (30 s)  – latency spike
      Phase 2 (60 s)  – errors + latency (critical)
      Phase 3 (30 s)  – CPU spike
      Phase 4         – remediation window (chaos off, observe recovery)
    """
    phase_duration = max(duration // 4, 10)
    _launch_workers(workers, ENDPOINTS)

    print("\n=== PHASE 1: Latency Spike ===")
    _enable_chaos({"enabled": True, "error_rate": 0.0, "latency_ms": 600})
    time.sleep(phase_duration)

    print("\n=== PHASE 2: Error Storm (CRITICAL) ===")
    _enable_chaos({"enabled": True, "error_rate": 0.35, "latency_ms": 400})
    time.sleep(phase_duration * 2)

    print("\n=== PHASE 3: CPU + Errors ===")
    _enable_chaos({"enabled": True, "error_rate": 0.20, "latency_ms": 200, "cpu_spike": True})
    time.sleep(phase_duration)

    print("\n=== PHASE 4: Recovery (chaos off — watch auto-remediation) ===")
    _disable_chaos()
    time.sleep(phase_duration)


# ---------------------------------------------------------------------------
# Stats printer
# ---------------------------------------------------------------------------

def _stats_printer():
    while not STOP_EVENT.is_set():
        time.sleep(10)
        r = STATS.report()
        ts = datetime.now().strftime("%H:%M:%S")
        print(
            f"[{ts}] Stats → total={r['total_requests']} "
            f"errors={r['errors']} ({r['error_rate_pct']}%) "
            f"p50={r['latency_p50_ms']}ms p99={r['latency_p99_ms']}ms"
        )


# ---------------------------------------------------------------------------
# Entry point
# ---------------------------------------------------------------------------

SCENARIOS = {
    "errors": scenario_errors,
    "latency": scenario_latency,
    "cpu": scenario_cpu,
    "memory": scenario_memory,
    "load": scenario_load,
    "full": scenario_full,
}


def main():
    global BASE_URL
    parser = argparse.ArgumentParser(description="TechStream Chaos Engineering Script")
    parser.add_argument("--scenario", choices=list(SCENARIOS), default="full",
                        help="Chaos scenario to run (default: full)")
    parser.add_argument("--duration", type=int, default=120,
                        help="Total duration in seconds (default: 120)")
    parser.add_argument("--workers", type=int, default=20,
                        help="Concurrent traffic workers (default: 20)")
    parser.add_argument("--url", default=BASE_URL,
                        help=f"Target base URL (default: {BASE_URL})")
    args = parser.parse_args()

    BASE_URL = args.url.rstrip("/")

    def _sigint(_s, _f):
        print("\nInterrupted — cleaning up…")
        STOP_EVENT.set()
        _disable_chaos()
        sys.exit(0)

    signal.signal(signal.SIGINT, _sigint)
    signal.signal(signal.SIGTERM, _sigint)

    print(f"[TechStream Chaos] target={BASE_URL}  scenario={args.scenario}  "
          f"duration={args.duration}s  workers={args.workers}")

    threading.Thread(target=_stats_printer, daemon=True).start()

    t0 = time.time()
    SCENARIOS[args.scenario](args.duration, args.workers)
    STOP_EVENT.set()

    elapsed = round(time.time() - t0, 1)
    report = STATS.report()
    print(f"\n{'='*60}")
    print(f"  Chaos run complete  ({elapsed}s)")
    print(f"  Total requests : {report['total_requests']}")
    print(f"  Errors         : {report['errors']}  ({report['error_rate_pct']}%)")
    print(f"  Latency P50    : {report['latency_p50_ms']} ms")
    print(f"  Latency P95    : {report['latency_p95_ms']} ms")
    print(f"  Latency P99    : {report['latency_p99_ms']} ms")
    print(f"{'='*60}\n")


if __name__ == "__main__":
    main()
