"""
TechStream AI Root Cause Analysis — Amazon DevOps Guru
=======================================================
Queries DevOps Guru for ML-detected insights, anomalies, and recommendations
then prints a structured RCA report.

Usage
-----
    # Uses AWS_DEFAULT_REGION / credentials from env / ~/.aws/credentials
    python analyze.py

    # Override region
    python analyze.py --region eu-west-1

    # Save full JSON report
    python analyze.py --output report.json

    # Include closed insights from the last N hours (default: 24)
    python analyze.py --hours 48

Note: DevOps Guru requires 3–7 days of CloudWatch metric history to
establish baselines before it generates the first insights.
"""

import argparse
import json
import logging
import os
import sys
from datetime import datetime, timedelta, timezone

import boto3
from botocore.exceptions import BotoCoreError, ClientError, NoCredentialsError

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s %(levelname)-8s %(message)s",
    datefmt="%Y-%m-%d %H:%M:%S",
)
log = logging.getLogger("devops-guru-rca")

SEVERITY_EMOJI = {"HIGH": "🔴", "MEDIUM": "🟡", "LOW": "🟢"}
SEP = "=" * 68


# ---------------------------------------------------------------------------
# DevOps Guru helpers
# ---------------------------------------------------------------------------

def _client(region: str):
    return boto3.client("devops-guru", region_name=region)


def list_insights(client, hours: int) -> dict:
    """Return all ongoing + recently closed insights."""
    now = datetime.now(timezone.utc)
    start = now - timedelta(hours=hours)

    ongoing_reactive = _paginate_insights(client, {"Ongoing": {"Type": "REACTIVE"}})
    ongoing_proactive = _paginate_insights(client, {"Ongoing": {"Type": "PROACTIVE"}})
    closed_reactive = _paginate_insights(client, {
        "Closed": {
            "Type": "REACTIVE",
            "EndTimeRange": {"FromTime": start, "ToTime": now},
        }
    })

    return {
        "ongoing_reactive": ongoing_reactive,
        "ongoing_proactive": ongoing_proactive,
        "closed_reactive": closed_reactive,
    }


def _paginate_insights(client, status_filter: dict) -> list:
    results = []
    kwargs = {"StatusFilter": status_filter}
    while True:
        resp = client.list_insights(**kwargs)
        results.extend(resp.get("ReactiveInsights", []))
        results.extend(resp.get("ProactiveInsights", []))
        token = resp.get("NextToken")
        if not token:
            break
        kwargs["NextToken"] = token
    return results


def get_anomalies(client, insight_id: str) -> list:
    results = []
    kwargs = {"InsightId": insight_id}
    while True:
        resp = client.list_anomalies_for_insight(**kwargs)
        results.extend(resp.get("ReactiveAnomalies", []))
        results.extend(resp.get("ProactiveAnomalies", []))
        token = resp.get("NextToken")
        if not token:
            break
        kwargs["NextToken"] = token
    return results


def get_recommendations(client, insight_id: str) -> list:
    results = []
    kwargs = {"InsightId": insight_id, "Locale": "EN_US"}
    while True:
        resp = client.list_recommendations(**kwargs)
        results.extend(resp.get("Recommendations", []))
        token = resp.get("NextToken")
        if not token:
            break
        kwargs["NextToken"] = token
    return results


# ---------------------------------------------------------------------------
# Report formatting
# ---------------------------------------------------------------------------

def _format_time(dt) -> str:
    if isinstance(dt, datetime):
        return dt.strftime("%Y-%m-%d %H:%M:%S UTC")
    return str(dt)


def _format_insight(client, insight: dict, idx: int) -> dict:
    iid = insight["Id"]
    name = insight.get("Name", "Unnamed insight")
    severity = insight.get("Severity", "UNKNOWN")
    status = insight.get("Status", "?")
    time_range = insight.get("InsightTimeRange", insight.get("PredictionTimeRange", {}))
    start = _format_time(time_range.get("StartTime", ""))
    end = _format_time(time_range.get("EndTime", "still ongoing"))

    anomalies = get_anomalies(client, iid)
    recommendations = get_recommendations(client, iid)

    # Extract CloudWatch metric names from anomalies
    affected_metrics = set()
    for a in anomalies:
        for cw in a.get("SourceDetails", {}).get("CloudWatchMetrics", []):
            metric = f"{cw.get('Namespace', '')}/{cw.get('MetricName', '')}"
            affected_metrics.add(metric)

    return {
        "index": idx,
        "id": iid,
        "name": name,
        "severity": severity,
        "status": status,
        "start": start,
        "end": end,
        "anomaly_count": len(anomalies),
        "affected_metrics": sorted(affected_metrics),
        "recommendations": [
            {
                "name": r.get("Name", ""),
                "description": r.get("Description", ""),
                "reason": r.get("Reason", ""),
                "link": r.get("Link", ""),
            }
            for r in recommendations
        ],
    }


def print_report(insights: dict, formatted: list, hours: int):
    now = datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M:%S UTC")
    ongoing_count = len(insights["ongoing_reactive"]) + len(insights["ongoing_proactive"])
    closed_count = len(insights["closed_reactive"])

    print(f"\n{SEP}")
    print("  TechStream Self-Healing — DevOps Guru RCA Report")
    print(f"  Generated : {now}")
    print(f"  Window    : last {hours} hours")
    print(SEP)
    print(f"\n  Ongoing insights  : {ongoing_count}")
    print(f"  Closed insights   : {closed_count}  (last {hours} h)")
    print(f"  Total analysed    : {len(formatted)}\n")

    if not formatted:
        print("  No insights found.")
        print()
        print("  This is expected for a new deployment — DevOps Guru needs")
        print("  3–7 days of CloudWatch metric history to build baselines.")
        print("  Run the chaos script to generate anomalous metric patterns:")
        print("    python3 chaos/chaos_script.py --scenario full --duration 120")
        print(f"\n{SEP}\n")
        return

    for f in formatted:
        emoji = SEVERITY_EMOJI.get(f["severity"], "⚪")
        print(f"  {SEP[:64]}")
        print(f"  Insight #{f['index'] + 1} — {emoji} {f['severity']}  [{f['status']}]")
        print(f"  {SEP[:64]}")
        print(f"  Name     : {f['name']}")
        print(f"  ID       : {f['id']}")
        print(f"  Started  : {f['start']}")
        print(f"  Ended    : {f['end']}")
        print(f"  Anomalies: {f['anomaly_count']}")

        if f["affected_metrics"]:
            print("\n  Affected metrics:")
            for m in f["affected_metrics"]:
                print(f"    • {m}")

        if f["recommendations"]:
            print(f"\n  Recommendations ({len(f['recommendations'])}):")
            for i, r in enumerate(f["recommendations"], 1):
                print(f"\n    [{i}] {r['name']}")
                if r["description"]:
                    print(f"        {r['description']}")
                if r["reason"]:
                    print(f"        Why: {r['reason']}")
                if r["link"]:
                    print(f"        Ref: {r['link']}")
        else:
            print("\n  No recommendations available for this insight.")
        print()

    print(SEP)
    print("  Summary")
    print(SEP)
    high = sum(1 for f in formatted if f["severity"] == "HIGH")
    med = sum(1 for f in formatted if f["severity"] == "MEDIUM")
    low = sum(1 for f in formatted if f["severity"] == "LOW")
    total_recs = sum(len(f["recommendations"]) for f in formatted)
    print(f"  🔴 HIGH severity   : {high}")
    print(f"  🟡 MEDIUM severity : {med}")
    print(f"  🟢 LOW severity    : {low}")
    print(f"  Total recommendations : {total_recs}")
    if ongoing_count:
        print(f"\n  ⚠️  {ongoing_count} insight(s) still ONGOING — remediation may be needed.")
    else:
        print("\n  ✅ No ongoing incidents detected.")
    print(f"\n{SEP}\n")


# ---------------------------------------------------------------------------
# Entry point
# ---------------------------------------------------------------------------

def main():
    parser = argparse.ArgumentParser(
        description="TechStream RCA — powered by Amazon DevOps Guru"
    )
    parser.add_argument(
        "--region",
        default=os.getenv("AWS_DEFAULT_REGION", "eu-west-1"),
        help="AWS region (default: eu-west-1 or $AWS_DEFAULT_REGION)",
    )
    parser.add_argument(
        "--hours",
        type=int,
        default=24,
        help="Look back window in hours for closed insights (default: 24)",
    )
    parser.add_argument(
        "--output",
        default=None,
        metavar="FILE",
        help="Save full JSON report to this file",
    )
    args = parser.parse_args()

    try:
        dg = _client(args.region)
        # Quick credential check
        boto3.client("sts", region_name=args.region).get_caller_identity()
    except NoCredentialsError:
        print("ERROR: AWS credentials not found.", file=sys.stderr)
        print("       Configure via environment variables, ~/.aws/credentials,", file=sys.stderr)
        print("       or an EC2/Lambda instance role.", file=sys.stderr)
        sys.exit(1)
    except (BotoCoreError, ClientError) as exc:
        print(f"ERROR: AWS connection failed: {exc}", file=sys.stderr)
        sys.exit(1)

    log.info("Connected to DevOps Guru in %s", args.region)

    try:
        insights = list_insights(dg, args.hours)
    except ClientError as exc:
        code = exc.response["Error"]["Code"]
        if code == "AccessDeniedException":
            print("ERROR: IAM permissions missing for devops-guru:ListInsights.", file=sys.stderr)
            print("       Ensure the executing role has DevOpsGuruReadOnlyAccess.", file=sys.stderr)
        else:
            print(f"ERROR: DevOps Guru API error: {exc}", file=sys.stderr)
        sys.exit(1)

    all_insights = (
        insights["ongoing_reactive"]
        + insights["ongoing_proactive"]
        + insights["closed_reactive"]
    )

    log.info(
        "Found %d ongoing + %d closed insights",
        len(insights["ongoing_reactive"]) + len(insights["ongoing_proactive"]),
        len(insights["closed_reactive"]),
    )

    formatted = [_format_insight(dg, ins, i) for i, ins in enumerate(all_insights)]
    print_report(insights, formatted, args.hours)

    if args.output:
        report = {
            "generated_at": datetime.now(timezone.utc).isoformat(),
            "region": args.region,
            "hours": args.hours,
            "summary": {
                "ongoing": len(insights["ongoing_reactive"]) + len(insights["ongoing_proactive"]),
                "closed": len(insights["closed_reactive"]),
            },
            "insights": formatted,
        }
        with open(args.output, "w", encoding="utf-8") as fh:
            json.dump(report, fh, indent=2, default=str)
        print(f"Full report saved → {args.output}")


if __name__ == "__main__":
    main()
