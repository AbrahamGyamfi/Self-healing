#!/usr/bin/env bash
# cleanup.sh – Tear down the local stack
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
ROOT="$(dirname "$SCRIPT_DIR")"
cd "$ROOT"

echo "Stopping TechStream Self-Healing stack…"
docker compose down -v --remove-orphans
echo "Done."
