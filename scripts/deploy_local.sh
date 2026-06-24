#!/usr/bin/env bash
# deploy_local.sh – Start the full TechStream Self-Healing stack locally
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
ROOT="$(dirname "$SCRIPT_DIR")"

cd "$ROOT"

echo "╔══════════════════════════════════════════════════════════╗"
echo "║     TechStream Self-Healing — Local Deployment           ║"
echo "╚══════════════════════════════════════════════════════════╝"

# Prerequisites
for cmd in docker curl; do
  if ! command -v "$cmd" &>/dev/null; then
    echo "ERROR: $cmd is required but not installed."
    exit 1
  fi
done

# Copy env file if missing
if [[ ! -f .env ]]; then
  cp .env.example .env
  echo "[INFO] Created .env from .env.example — review and update as needed."
fi

# Build and start
echo ""
echo "[1/3] Building Docker images…"
docker compose build --no-cache

echo ""
echo "[2/3] Starting services…"
docker compose up -d

echo ""
echo "[3/3] Waiting for services to be healthy…"
MAX_WAIT=120
WAITED=0
until curl -sf http://localhost:5000/health >/dev/null 2>&1; do
  if [[ $WAITED -ge $MAX_WAIT ]]; then
    echo "ERROR: App did not become healthy within ${MAX_WAIT}s"
    docker compose logs --tail=30 techstream-app
    exit 1
  fi
  printf "."
  sleep 3
  WAITED=$((WAITED + 3))
done
echo ""

echo ""
echo "═══════════════════════════════════════════════════════════"
echo "  Stack is UP!"
echo ""
echo "  Application  : http://localhost:5000"
echo "  Prometheus   : http://localhost:9090"
echo "  Grafana      : http://localhost:3000   admin / techstream123"
echo "  AlertManager : http://localhost:9093"
echo "  Remediation  : http://localhost:8080/history"
echo "═══════════════════════════════════════════════════════════"
echo ""
echo "Next: run ./scripts/run_demo.sh to simulate an incident"
