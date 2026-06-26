"""
AI/ML Root Cause Analyzer
==========================
Simulates Amazon DevOps Guru–style anomaly detection and root-cause correlation.

Algorithm
---------
1. Fetch current metric snapshots from Prometheus
2. Detect anomalies using Z-score and IQR (similar to DevOps Guru's ML-based approach)
3. Correlate anomalous signals (e.g., "CPU spike → latency → errors cascade")
4. Generate a structured insight report (JSON + human-readable)

Usage
-----
  python root_cause_analyzer.py                         # one-shot analysis
  python root_cause_analyzer.py --watch --interval 60  # continuous polling
  python root_cause_analyzer.py --output report.json   # save report to file
"""

import argparse
import json
import math
import os
import statistics
import time
import urllib.parse
import urllib.request
from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Optional

PROMETHEUS_URL = os.getenv("PROMETHEUS_URL", "http://localhost:9090")

# ---------------------------------------------------------------------------
# Metric definitions  (PromQL + human label + thresholds)
# ---------------------------------------------------------------------------

@dataclass
class MetricSpec:
    name: str
    query: str
    unit: str
    critical_threshold: Optional[float] = None
    warning_threshold: Optional[float] = None
    direction: str = "high"   # "high" = alert when value rises; "low" = alert when drops

METRICS = [
    MetricSpec(
        name="error_rate",
        query='sum(rate(http_errors_total{job="techstream_api"}[2m])) '
              '/ sum(rate(http_requests_total{job="techstream_api"}[2m]))',
        unit="ratio",
        critical_threshold=0.05,
        warning_threshold=0.01,
    ),
    MetricSpec(
        name="latency_p99",
        query='histogram_quantile(0.99, sum(rate('
              'http_request_duration_seconds_bucket{job="techstream_api"}[5m])) by (le))',
        unit="seconds",
        critical_threshold=1.0,
        warning_threshold=0.5,
    ),
    MetricSpec(
        name="cpu_percent",
        query='process_cpu_percent{job="techstream_api"}',
        unit="percent",
        critical_threshold=80.0,
        warning_threshold=60.0,
    ),
    MetricSpec(
        name="memory_bytes",
        query="process_memory_bytes",
        unit="bytes",
        critical_threshold=None,  # dynamic — based on Z-score
    ),
    MetricSpec(
        name="request_rate",
        query='sum(rate(http_requests_total{job="techstream_api"}[1m]))',
        unit="rps",
        direction="low",
        warning_threshold=0.1,
    ),
    MetricSpec(
        name="active_requests",
        query='active_requests{job="techstream_api"}',
        unit="count",
        warning_threshold=50.0,
        critical_threshold=100.0,
    ),
]

# ---------------------------------------------------------------------------
# Prometheus client
# ---------------------------------------------------------------------------

def _query_prometheus(promql: str) -> Optional[float]:
    encoded = urllib.parse.quote(promql)
    url = f"{PROMETHEUS_URL}/api/v1/query?query={encoded}"
    try:
        url = f"{PROMETHEUS_URL}/api/v1/query?query={urllib.parse.quote(promql)}"
        with urllib.request.urlopen(url, timeout=10) as resp:
            data = json.loads(resp.read())
        results = data.get("data", {}).get("result", [])
        if results:
            return float(results[0]["value"][1])
    except Exception:
        pass
    return None


def _query_range(promql: str, minutes: int = 30) -> list[float]:
    """Fetch a time-series window for baseline calculation."""
    import urllib.parse
    end = int(time.time())
    start = end - minutes * 60
    step = max(15, minutes * 3)
    url = (
        f"{PROMETHEUS_URL}/api/v1/query_range"
        f"?query={urllib.parse.quote(promql)}"
        f"&start={start}&end={end}&step={step}"
    )
    try:
        with urllib.request.urlopen(url, timeout=15) as resp:
            data = json.loads(resp.read())
        results = data.get("data", {}).get("result", [])
        if results:
            return [float(v[1]) for v in results[0]["values"] if v[1] != "NaN"]
    except Exception:
        pass
    return []

# ---------------------------------------------------------------------------
# Anomaly detection
# ---------------------------------------------------------------------------

@dataclass
class AnomalyResult:
    metric: str
    current_value: float
    baseline_mean: float
    baseline_stddev: float
    z_score: float
    severity: str        # "normal" | "warning" | "critical"
    description: str

def _zscore(value: float, mean: float, std: float) -> float:
    return (value - mean) / std if std > 0 else 0.0

def _iqr_bounds(values: list[float]) -> tuple[float, float]:
    if len(values) < 4:
        return -math.inf, math.inf
    sorted_v = sorted(values)
    n = len(sorted_v)
    q1 = sorted_v[n // 4]
    q3 = sorted_v[(3 * n) // 4]
    iqr = q3 - q1
    return q1 - 1.5 * iqr, q3 + 1.5 * iqr

def _detect_anomaly(spec: MetricSpec, current: float, history: list[float]) -> AnomalyResult:
    mean = statistics.mean(history) if history else current
    std = statistics.stdev(history) if len(history) > 1 else 0.0
    z = _zscore(current, mean, std)
    _, iqr_upper = _iqr_bounds(history)

    severity = "normal"

    # Threshold-based
    if spec.critical_threshold and spec.direction == "high" and current >= spec.critical_threshold:
        severity = "critical"
    elif spec.warning_threshold and spec.direction == "high" and current >= spec.warning_threshold:
        severity = "warning"
    elif spec.warning_threshold and spec.direction == "low" and current <= spec.warning_threshold:
        severity = "warning"

    # Statistical override (Z-score ≥ 3 = anomaly even without hard threshold)
    if severity == "normal" and abs(z) >= 3.0:
        severity = "warning"
    if severity == "normal" and current > iqr_upper and iqr_upper != math.inf:
        severity = "warning"

    unit_str = spec.unit
    if unit_str == "ratio":
        desc_val = f"{current * 100:.1f}%"
    elif unit_str == "bytes":
        desc_val = f"{current / 1e6:.1f} MB"
    elif unit_str == "seconds":
        desc_val = f"{current * 1000:.0f} ms"
    else:
        desc_val = f"{current:.2f} {unit_str}"

    description = (
        f"{spec.name} = {desc_val}  (baseline mean={mean:.3f}, z={z:+.1f})"
    )

    return AnomalyResult(
        metric=spec.name,
        current_value=current,
        baseline_mean=mean,
        baseline_stddev=std,
        z_score=z,
        severity=severity,
        description=description,
    )

# ---------------------------------------------------------------------------
# Causal correlation
# ---------------------------------------------------------------------------

CAUSAL_CHAINS = [
    {
        "name": "Error Cascade",
        "pattern": ["cpu_percent", "latency_p99", "error_rate"],
        "description": (
            "CPU saturation is causing request processing delays (high latency), "
            "which leads to timeouts and elevated error rates. "
            "Root cause: application under-provisioned for current traffic."
        ),
        "recommended_action": "Scale out ASG by +1 or restart the service to clear stuck goroutines/threads.",
    },
    {
        "name": "Memory Pressure",
        "pattern": ["memory_bytes", "latency_p99"],
        "description": (
            "Memory growth is triggering frequent GC pauses, causing latency spikes. "
            "Root cause: potential memory leak or traffic surge without corresponding scaling."
        ),
        "recommended_action": "Restart the application process to reclaim memory. Investigate heap allocation.",
    },
    {
        "name": "Traffic Overload",
        "pattern": ["request_rate", "cpu_percent", "error_rate"],
        "description": (
            "Sudden traffic increase is saturating CPU capacity, leading to degraded responses. "
            "Root cause: external traffic spike (marketing event, crawler, DDoS)."
        ),
        "recommended_action": "Scale out ASG. Consider rate limiting at the load balancer.",
    },
    {
        "name": "Application Fault",
        "pattern": ["error_rate"],
        "description": (
            "Elevated error rate without CPU or latency anomalies suggests a code-level fault "
            "(bad deploy, null-pointer, misconfiguration). "
            "Root cause: recent deployment or configuration change."
        ),
        "recommended_action": "Roll back the latest deployment. Check application logs.",
    },
]

def _correlate(anomalies: list[AnomalyResult]) -> Optional[dict]:
    anomalous_metrics = {
        a.metric for a in anomalies if a.severity in ("warning", "critical")
    }
    if not anomalous_metrics:
        return None
    # Score each causal chain by how many of its pattern metrics are anomalous
    best_score = 0
    best_chain = None
    for chain in CAUSAL_CHAINS:
        matches = sum(1 for m in chain["pattern"] if m in anomalous_metrics)
        if matches > best_score:
            best_score = matches
            best_chain = chain
    return best_chain if best_chain else None

# ---------------------------------------------------------------------------
# Report
# ---------------------------------------------------------------------------

def run_analysis() -> dict:
    ts = datetime.now(timezone.utc).isoformat()
    anomalies: list[AnomalyResult] = []
    raw_values: dict[str, float] = {}

    for spec in METRICS:
        current = _query_prometheus(spec.query)
        if current is None:
            continue
        history = _query_range(spec.query, minutes=30)
        anomaly = _detect_anomaly(spec, current, history)
        anomalies.append(anomaly)
        raw_values[spec.name] = current

    anomalous = [a for a in anomalies if a.severity != "normal"]
    overall_severity = "normal"
    if any(a.severity == "critical" for a in anomalous):
        overall_severity = "critical"
    elif anomalous:
        overall_severity = "warning"

    root_cause = _correlate(anomalies)

    report = {
        "analysis_timestamp": ts,
        "overall_health": overall_severity,
        "anomaly_count": len(anomalous),
        "metrics": {
            a.metric: {
                "value": a.current_value,
                "severity": a.severity,
                "z_score": round(a.z_score, 2),
                "description": a.description,
            }
            for a in anomalies
        },
        "anomalies_detected": [
            {"metric": a.metric, "severity": a.severity, "description": a.description}
            for a in anomalous
        ],
        "root_cause_insight": root_cause,
        "devops_guru_simulation": {
            "insight_type": "anomaly_correlation" if root_cause else "no_anomaly",
            "confidence": "high" if len(anomalous) >= 2 else "medium" if anomalous else "low",
            "affected_resources": ["techstream-app"],
            "insight_name": root_cause["name"] if root_cause else "No anomaly detected",
            "recommendation": root_cause["recommended_action"] if root_cause else "System is healthy.",
        },
    }
    return report


def _print_report(report: dict):
    health_emoji = {"normal": "✅", "warning": "⚠️", "critical": "🚨"}.get(
        report["overall_health"], "❓"
    )
    print(f"\n{'='*70}")
    print("  TechStream Root Cause Analysis Report")
    print(f"  {report['analysis_timestamp']}")
    print(f"{'='*70}")
    print(f"  Overall Health : {health_emoji}  {report['overall_health'].upper()}")
    print(f"  Anomalies      : {report['anomaly_count']}")
    print()

    if report["anomalies_detected"]:
        print("  ANOMALOUS METRICS")
        print("  " + "-" * 50)
        for a in report["anomalies_detected"]:
            sym = "🔴" if a["severity"] == "critical" else "🟡"
            print(f"  {sym}  {a['description']}")
        print()

    insight = report.get("root_cause_insight")
    if insight:
        print("  ROOT CAUSE INSIGHT")
        print("  " + "-" * 50)
        print(f"  Pattern  : {insight['name']}")
        print(f"  Analysis : {insight['description']}")
        print()

    dg = report["devops_guru_simulation"]
    print("  DEVOPS GURU SIMULATION")
    print("  " + "-" * 50)
    print(f"  Insight  : {dg['insight_name']}")
    print(f"  Confidence : {dg['confidence']}")
    print(f"  Recommendation : {dg['recommendation']}")
    print(f"{'='*70}\n")


def main():
    global PROMETHEUS_URL
    parser = argparse.ArgumentParser(description="TechStream AI Root Cause Analyzer")
    parser.add_argument("--watch", action="store_true", help="Continuous analysis mode")
    parser.add_argument("--interval", type=int, default=60, help="Poll interval (seconds)")
    parser.add_argument("--output", help="Write report to JSON file")
    parser.add_argument("--prometheus", default=PROMETHEUS_URL,
                        help=f"Prometheus base URL (default: {PROMETHEUS_URL})")
    args = parser.parse_args()

    PROMETHEUS_URL = args.prometheus.rstrip("/")

    def once():
        report = run_analysis()
        _print_report(report)
        if args.output:
            with open(args.output, "w") as fh:
                json.dump(report, fh, indent=2)
            print(f"Report saved to {args.output}")
        return report

    if args.watch:
        print(f"[DevOps Guru Sim] Watching Prometheus at {PROMETHEUS_URL} every {args.interval}s…")
        while True:
            try:
                once()
            except Exception as exc:
                print(f"Analysis error: {exc}")
            time.sleep(args.interval)
    else:
        once()


if __name__ == "__main__":
    main()
