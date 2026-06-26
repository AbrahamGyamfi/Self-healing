#!/usr/bin/env bash
# run_demo.sh – End-to-end self-healing demonstration
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
ROOT="$(dirname "$SCRIPT_DIR")"
CHAOS="$ROOT/chaos/chaos_script.py"
# Use DevOps Guru if AWS credentials are available; fall back to stdlib analyser for local demo
if aws sts get-caller-identity &>/dev/null 2>&1; then
  ANALYZER="$ROOT/ai_analysis/analyze.py"
  echo "[INFO] AWS credentials found — using Amazon DevOps Guru for RCA"
else
  ANALYZER="$ROOT/ai_analysis/root_cause_analyzer.py"
  echo "[WARN] No AWS credentials — using statistical analyser (stdlib fallback)"
  echo "       To use DevOps Guru: configure AWS credentials and deploy Terraform first."
fi

APP_URL="${TARGET_URL:-http://localhost:5000}"
PROMETHEUS_URL="${PROMETHEUS_URL:-http://localhost:9090}"

echo ""
echo "╔══════════════════════════════════════════════════════════╗"
echo "║     TechStream Self-Healing — DEMO                       ║"
echo "╚══════════════════════════════════════════════════════════╝"
echo ""
echo "  Target   : $APP_URL"
echo "  Scenario : Full incident (latency → errors → CPU → recovery)"
echo "  Analyser : $(basename "$ANALYZER")"
echo ""
echo "  Watch the Grafana dashboard as chaos is injected:"
echo "  → http://localhost:3000  (admin / techstream123)"
echo ""
read -rp "  Press ENTER to begin…"

echo ""
echo "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━"
echo "  STEP 1: Baseline analysis (before chaos)"
echo "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━"
python3 "$ANALYZER" --prometheus "$PROMETHEUS_URL" --output /tmp/baseline_report.json || true

echo ""
echo "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━"
echo "  STEP 2: Injecting chaos (full scenario, 120 s)"
echo "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━"
python3 "$CHAOS" \
  --scenario full \
  --duration 120 \
  --workers 30 \
  --url "$APP_URL" &
CHAOS_PID=$!

# Run AI analysis mid-chaos
sleep 60
echo ""
echo "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━"
echo "  STEP 3: AI Root Cause Analysis (during incident)"
echo "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━"
python3 "$ANALYZER" --prometheus "$PROMETHEUS_URL" --output /tmp/incident_report.json || true

wait $CHAOS_PID || true

echo ""
echo "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━"
echo "  STEP 4: Post-remediation analysis (recovery)"
echo "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━"
echo "  Waiting 30 s for remediation to take effect…"
sleep 30
python3 "$ANALYZER" --prometheus "$PROMETHEUS_URL" --output /tmp/recovery_report.json || true

echo ""
echo "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━"
echo "  STEP 5: Remediation history"
echo "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━"
curl -s http://localhost:8080/history | python3 -m json.tool || true

echo ""
echo "  Reports saved to:"
echo "  /tmp/baseline_report.json"
echo "  /tmp/incident_report.json"
echo "  /tmp/recovery_report.json"
echo ""
echo "  Demo complete!"
