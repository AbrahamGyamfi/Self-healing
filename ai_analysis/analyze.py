"""
TechStream AI Root Cause Analysis
==================================
Queries Prometheus for Golden Signal metrics, then uses the Claude API
to produce a DevOps Guru-style root cause analysis report.

Usage
-----
    export ANTHROPIC_API_KEY=sk-ant-...
    python analyze.py                        # live Prometheus at localhost:9090
    python analyze.py --prometheus http://...  # custom Prometheus URL
    python analyze.py --output report.json   # save structured report
"""

import argparse
import json
import logging
import os
import sys
import time
import urllib.error
import urllib.parse
import urllib.request
from datetime import datetime, timezone

import anthropic

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s %(levelname)-8s %(message)s",
    datefmt="%Y-%m-%d %H:%M:%S",
)
log = logging.getLogger("ai-rca")

# ---------------------------------------------------------------------------
# Prometheus query helpers
# ---------------------------------------------------------------------------

def _prom_query(base_url: str, query: str) -> list[dict]:
    """Execute an instant PromQL query and return the result list."""
    url = f"{base_url}/api/v1/query?query={urllib.parse.quote(query)}"
    try:
        with urllib.request.urlopen(url, timeout=10) as resp:
            data = json.loads(resp.read())
    except urllib.error.URLError as exc:
        raise ConnectionError(f"Cannot reach Prometheus at {base_url}: {exc}") from exc
    if data.get("status") != "success":
        raise ValueError(f"PromQL error: {data.get('error', 'unknown')}")
    return data["data"]["result"]


def _scalar(results: list[dict], default: float = 0.0) -> float:
    if not results:
        return default
    try:
        return float(results[0]["value"][1])
    except (KeyError, IndexError, ValueError):
        return default


def _by_label(results: list[dict], label: str) -> dict[str, float]:
    out: dict[str, float] = {}
    for r in results:
        key = r.get("metric", {}).get(label, "?")
        try:
            out[key] = float(r["value"][1])
        except (KeyError, ValueError):
            pass
    return out


# ---------------------------------------------------------------------------
# Metric collection
# ---------------------------------------------------------------------------

def collect_signals(prometheus_url: str) -> dict:
    """Pull all four Golden Signals plus alert state from Prometheus."""
    log.info("Querying Prometheus at %s …", prometheus_url)

    job = 'job="techstream_api"'

    # ---- ERRORS -----------------------------------------------------------
    error_rate = _scalar(_prom_query(
        prometheus_url,
        f'sum(rate(http_errors_total{{{job}}}[2m])) '
        f'/ sum(rate(http_requests_total{{{job}}}[2m]))'
    ))

    errors_by_endpoint = _by_label(_prom_query(
        prometheus_url,
        f'sum by (endpoint) (rate(http_errors_total{{{job}}}[2m]))'
    ), "endpoint")

    # ---- TRAFFIC ----------------------------------------------------------
    rps_total = _scalar(_prom_query(
        prometheus_url,
        f'sum(rate(http_requests_total{{{job}}}[1m]))'
    ))

    rps_by_endpoint = _by_label(_prom_query(
        prometheus_url,
        f'sum by (endpoint) (rate(http_requests_total{{{job}}}[1m]))'
    ), "endpoint")

    # ---- LATENCY ----------------------------------------------------------
    def latency_pct(q: str) -> float:
        return _scalar(_prom_query(prometheus_url, q))

    p50 = latency_pct(
        f'histogram_quantile(0.50, sum(rate(http_request_duration_seconds_bucket{{{job}}}[5m])) by (le))'
    )
    p95 = latency_pct(
        f'histogram_quantile(0.95, sum(rate(http_request_duration_seconds_bucket{{{job}}}[5m])) by (le))'
    )
    p99 = latency_pct(
        f'histogram_quantile(0.99, sum(rate(http_request_duration_seconds_bucket{{{job}}}[5m])) by (le))'
    )

    # ---- SATURATION -------------------------------------------------------
    cpu_pct = _scalar(_prom_query(
        prometheus_url,
        f'process_cpu_percent{{{job}}}'
    ))
    memory_bytes = _scalar(_prom_query(
        prometheus_url,
        f'process_memory_bytes{{{job}}}'
    ))
    active_reqs = _scalar(_prom_query(
        prometheus_url,
        f'active_requests{{{job}}}'
    ))

    # ---- ALERTS -----------------------------------------------------------
    try:
        with urllib.request.urlopen(f"{prometheus_url}/api/v1/alerts", timeout=10) as resp:
            alert_data = json.loads(resp.read())
        firing_alerts = [
            {
                "name": a["labels"].get("alertname", "?"),
                "severity": a["labels"].get("severity", "?"),
                "signal": a["labels"].get("signal", "?"),
                "description": a.get("annotations", {}).get("description", ""),
                "active_since": a.get("activeAt", ""),
            }
            for a in alert_data.get("data", {}).get("alerts", [])
            if a.get("state") == "firing"
        ]
    except Exception as exc:
        log.warning("Could not fetch alerts: %s", exc)
        firing_alerts = []

    return {
        "collected_at": datetime.now(timezone.utc).isoformat(),
        "errors": {
            "rate": error_rate,
            "rate_pct": round(error_rate * 100, 2),
            "threshold_pct": 5.0,
            "by_endpoint": errors_by_endpoint,
            "breaching": error_rate > 0.05,
        },
        "traffic": {
            "rps_total": round(rps_total, 3),
            "by_endpoint": rps_by_endpoint,
        },
        "latency": {
            "p50_ms": round(p50 * 1000, 1),
            "p95_ms": round(p95 * 1000, 1),
            "p99_ms": round(p99 * 1000, 1),
            "p99_threshold_ms": 1000,
            "p99_breaching": p99 > 1.0,
        },
        "saturation": {
            "cpu_pct": round(cpu_pct, 1),
            "cpu_threshold_pct": 80,
            "cpu_breaching": cpu_pct > 80,
            "memory_mb": round(memory_bytes / 1_048_576, 1),
            "active_requests": int(active_reqs),
        },
        "alerts": {
            "firing_count": len(firing_alerts),
            "firing": firing_alerts,
        },
    }


# ---------------------------------------------------------------------------
# AI analysis
# ---------------------------------------------------------------------------

_SYSTEM_PROMPT = """\
You are a Senior Site Reliability Engineer AI assistant for TechStream.
Your task is to analyse real-time monitoring data and produce a concise,
actionable root-cause analysis (RCA) report in the style of Amazon DevOps Guru.

Always structure your response with these exact section headers:
  ## Anomaly Summary
  ## Root Cause Analysis
  ## Impact Assessment
  ## Automated Remediation Actions
  ## Recommended Follow-up (On-Call Engineer)
  ## MTTR Estimate

Be specific — reference the actual metric values provided.
Use technical language appropriate for a senior engineer audience.
"""


def analyse(signals: dict, api_key: str) -> str:
    """Call Claude to produce the RCA report."""
    client = anthropic.Anthropic(api_key=api_key)

    # Summarise signals as concise text to keep the prompt tight
    s = signals
    err = s["errors"]
    lat = s["latency"]
    sat = s["saturation"]
    trf = s["traffic"]
    alerts_text = (
        "\n".join(
            f"  • [{a['severity'].upper()}] {a['name']}: {a['description']}"
            for a in s["alerts"]["firing"]
        )
        or "  None currently firing"
    )

    user_message = f"""
**Collection timestamp:** {s["collected_at"]}

### Golden Signal Snapshot

| Signal        | Value                         | Threshold | Breaching? |
|---------------|-------------------------------|-----------|------------|
| Error Rate    | {err["rate_pct"]:.2f}%        | 5 %       | {"YES" if err["breaching"] else "no"} |
| P50 Latency   | {lat["p50_ms"]:.0f} ms        | –         | –          |
| P95 Latency   | {lat["p95_ms"]:.0f} ms        | –         | –          |
| P99 Latency   | {lat["p99_ms"]:.0f} ms        | 1000 ms   | {"YES" if lat["p99_breaching"] else "no"} |
| Traffic (RPS) | {trf["rps_total"]:.2f} req/s  | –         | –          |
| CPU           | {sat["cpu_pct"]:.1f}%         | 80 %      | {"YES" if sat["cpu_breaching"] else "no"} |
| Memory        | {sat["memory_mb"]:.0f} MB     | –         | –          |
| In-Flight Req | {sat["active_requests"]}       | –         | –          |

### Error Breakdown by Endpoint
{json.dumps(err["by_endpoint"], indent=2)}

### Traffic Breakdown by Endpoint
{json.dumps(trf["by_endpoint"], indent=2)}

### Firing Alerts ({s["alerts"]["firing_count"]})
{alerts_text}

Please produce the RCA report now.
"""

    log.info("Sending metrics to Claude API for analysis …")
    message = client.messages.create(
        model="claude-sonnet-4-6",
        max_tokens=2048,
        system=_SYSTEM_PROMPT,
        messages=[{"role": "user", "content": user_message}],
    )
    return message.content[0].text


# ---------------------------------------------------------------------------
# Entry point
# ---------------------------------------------------------------------------

def main():
    parser = argparse.ArgumentParser(
        description="TechStream AI Root Cause Analysis — powered by Claude"
    )
    parser.add_argument(
        "--prometheus",
        default=os.getenv("PROMETHEUS_URL", "http://localhost:9090"),
        metavar="URL",
        help="Prometheus base URL (default: http://localhost:9090)",
    )
    parser.add_argument(
        "--output",
        default=None,
        metavar="FILE",
        help="Save the full JSON report to this file (optional)",
    )
    args = parser.parse_args()

    api_key = os.getenv("ANTHROPIC_API_KEY", "")
    if not api_key:
        print("ERROR: ANTHROPIC_API_KEY environment variable is not set.", file=sys.stderr)
        print("       export ANTHROPIC_API_KEY=sk-ant-...", file=sys.stderr)
        sys.exit(1)

    banner = "=" * 68
    print(f"\n{banner}")
    print("  TechStream Self-Healing — AI Root Cause Analysis")
    print(f"  Powered by Claude | {datetime.now().strftime('%Y-%m-%d %H:%M:%S UTC')}")
    print(f"{banner}\n")

    # 1. Collect metrics
    print("[1/2] Collecting Golden Signal metrics …")
    t0 = time.monotonic()
    try:
        signals = collect_signals(args.prometheus)
    except ConnectionError as exc:
        print(f"\nERROR: {exc}", file=sys.stderr)
        print("       Make sure 'docker compose up -d' has been run.", file=sys.stderr)
        sys.exit(1)

    err = signals["errors"]
    lat = signals["latency"]
    sat = signals["saturation"]
    trf = signals["traffic"]

    print(f"  Error Rate    : {err['rate_pct']:.2f}%  {'<-- BREACHING THRESHOLD' if err['breaching'] else ''}")
    print(f"  Traffic       : {trf['rps_total']:.2f} req/s")
    print(f"  P99 Latency   : {lat['p99_ms']:.0f} ms  {'<-- BREACHING THRESHOLD' if lat['p99_breaching'] else ''}")
    print(f"  CPU           : {sat['cpu_pct']:.1f}%  {'<-- BREACHING THRESHOLD' if sat['cpu_breaching'] else ''}")
    print(f"  Firing Alerts : {signals['alerts']['firing_count']}")
    elapsed = time.monotonic() - t0
    print(f"  Collected in  : {elapsed:.2f}s\n")

    # 2. AI analysis
    print("[2/2] Requesting Claude AI root cause analysis …")
    t1 = time.monotonic()
    report_text = analyse(signals, api_key)
    elapsed2 = time.monotonic() - t1
    print(f"  Analysis in   : {elapsed2:.2f}s\n")

    print(banner)
    print("  AI ROOT CAUSE ANALYSIS REPORT")
    print(banner)
    print(report_text)
    print(f"\n{banner}\n")

    # 3. Optionally save report
    if args.output:
        report = {
            "generated_at": datetime.now(timezone.utc).isoformat(),
            "signals": signals,
            "analysis": report_text,
        }
        with open(args.output, "w", encoding="utf-8") as fh:
            json.dump(report, fh, indent=2)
        print(f"Full report saved → {args.output}")

    return 0


if __name__ == "__main__":
    sys.exit(main())
