"""
Remediation Service
===================
Receives webhook calls from Alertmanager and automatically heals
the TechStream application.

Endpoints
---------
  POST /webhook      – general alert notification (logs + notifies Slack)
  POST /remediate    – automated remediation for critical alerts
  GET  /health       – liveness check
  GET  /history      – returns last 50 remediation events
"""

import json
import logging
import os
import subprocess
import time
import threading
import urllib.request
from datetime import datetime
from http.server import BaseHTTPRequestHandler, HTTPServer

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s %(levelname)-8s %(message)s",
    datefmt="%Y-%m-%d %H:%M:%S",
)
log = logging.getLogger("remediation")

WEBHOOK_TOKEN = os.getenv("WEBHOOK_TOKEN", "changeme")
APP_CONTAINER = os.getenv("APP_CONTAINER", "techstream-app")
SLACK_WEBHOOK_URL = os.getenv("SLACK_WEBHOOK_URL", "")

# In-memory history (last 100 events)
_history: list[dict] = []
_history_lock = threading.Lock()

# Rate-limiting: don't restart more than once per 60 s
_last_remediation_time: float = 0
_REMEDIATION_COOLDOWN = 60


def _add_history(event: dict):
    with _history_lock:
        _history.append({"timestamp": datetime.utcnow().isoformat() + "Z", **event})
        if len(_history) > 100:
            _history.pop(0)


def _notify_slack(text: str):
    if not SLACK_WEBHOOK_URL:
        return
    try:
        payload = json.dumps({"text": text}).encode()
        req = urllib.request.Request(
            SLACK_WEBHOOK_URL,
            data=payload,
            headers={"Content-Type": "application/json"},
        )
        urllib.request.urlopen(req, timeout=5)
    except Exception as exc:
        log.warning("Slack notification failed: %s", exc)


def _docker_restart(container: str) -> tuple[bool, str]:
    """Restart a Docker container by name."""
    try:
        result = subprocess.run(
            ["docker", "restart", container],
            capture_output=True, text=True, timeout=30,
        )
        if result.returncode == 0:
            return True, f"Container '{container}' restarted successfully."
        return False, f"docker restart failed: {result.stderr.strip()}"
    except FileNotFoundError:
        # Docker not available (e.g., running in CI without Docker)
        return False, "docker binary not found"
    except subprocess.TimeoutExpired:
        return False, "docker restart timed out after 30 s"


def _reset_chaos(base_url: str = "http://techstream-app:5000") -> tuple[bool, str]:
    """POST /chaos/reset to clear chaos mode."""
    try:
        req = urllib.request.Request(
            f"{base_url}/chaos/reset",
            data=b"{}",
            headers={"Content-Type": "application/json"},
            method="POST",
        )
        with urllib.request.urlopen(req, timeout=10) as resp:
            return resp.status == 200, "chaos reset successfully"
    except Exception as exc:
        return False, str(exc)


def _perform_remediation(alerts: list[dict]) -> dict:
    """
    Decide and execute the correct remediation action based on alert labels.
    Returns a result dict describing what was done.
    """
    global _last_remediation_time

    now = time.time()
    if now - _last_remediation_time < _REMEDIATION_COOLDOWN:
        return {
            "action": "skipped",
            "reason": f"cooldown active ({_REMEDIATION_COOLDOWN}s between remediations)",
        }

    _last_remediation_time = now

    # Classify alerts
    signals = {a.get("labels", {}).get("signal", "unknown") for a in alerts}
    severities = {a.get("labels", {}).get("severity", "unknown") for a in alerts}
    names = [a.get("labels", {}).get("alertname", "") for a in alerts]

    log.info("Remediating alerts: %s  signals=%s  severities=%s", names, signals, severities)

    results: list[str] = []

    # 1. Always try chaos reset first (covers chaos-injected failures)
    ok, msg = _reset_chaos()
    results.append(f"chaos_reset={'ok' if ok else 'failed'}: {msg}")
    log.info("Chaos reset → %s", msg)

    # 2. If the app looks down, restart the container
    if "AppContainerDown" in names or "errors" in signals:
        ok, msg = _docker_restart(APP_CONTAINER)
        results.append(f"container_restart={'ok' if ok else 'failed'}: {msg}")
        log.info("Container restart → %s", msg)

    action_summary = {
        "action": "remediation_executed",
        "signals": list(signals),
        "alerts": names,
        "steps": results,
    }

    # Notify Slack
    alert_list = ", ".join(names) or "unknown"
    _notify_slack(
        f":rotating_light: *Auto-remediation triggered*\n"
        f"Alerts: `{alert_list}`\n"
        f"Steps taken:\n" + "\n".join(f"  • {r}" for r in results)
    )

    return action_summary

# ---------------------------------------------------------------------------
# HTTP handler
# ---------------------------------------------------------------------------

class Handler(BaseHTTPRequestHandler):
    def log_message(self, fmt, *args):  # suppress default access log
        log.debug(fmt, *args)

    def _send(self, status: int, body: dict):
        payload = json.dumps(body, indent=2).encode()
        self.send_response(status)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(payload)))
        self.end_headers()
        self.wfile.write(payload)

    def _read_body(self) -> dict:
        length = int(self.headers.get("Content-Length", 0))
        raw = self.rfile.read(length)
        return json.loads(raw) if raw else {}

    def _check_auth(self) -> bool:
        token = self.headers.get("Authorization", "")
        return token == f"Bearer {WEBHOOK_TOKEN}" or WEBHOOK_TOKEN == "changeme"

    # GET ---------------------------------------------------------------
    def do_GET(self):
        if self.path == "/health":
            self._send(200, {"status": "ok", "service": "remediation"})
        elif self.path == "/history":
            with _history_lock:
                self._send(200, {"events": list(reversed(_history))})
        else:
            self._send(404, {"error": "not found"})

    # POST --------------------------------------------------------------
    def do_POST(self):
        body = self._read_body()

        if self.path == "/webhook":
            alerts = body.get("alerts", [])
            for a in alerts:
                alertname = a.get("labels", {}).get("alertname", "?")
                status = a.get("status", "?")
                log.info("Alert received: %s [%s]", alertname, status)
                _add_history({"type": "alert", "alertname": alertname, "status": status})
            _notify_slack(
                f":bell: Alertmanager webhook received\n"
                f"Alerts: {', '.join(a.get('labels',{}).get('alertname','?') for a in alerts)}"
            )
            self._send(200, {"received": len(alerts)})

        elif self.path == "/remediate":
            if not self._check_auth():
                self._send(401, {"error": "unauthorized"})
                return
            alerts = body.get("alerts", [])
            firing = [a for a in alerts if a.get("status") == "firing"]
            if not firing:
                self._send(200, {"message": "no firing alerts"})
                return
            result = _perform_remediation(firing)
            _add_history({"type": "remediation", **result})
            log.info("Remediation result: %s", result)
            self._send(200, result)

        else:
            self._send(404, {"error": "not found"})


def main():
    port = int(os.getenv("PORT", 8080))
    server = HTTPServer(("0.0.0.0", port), Handler)
    log.info("Remediation service listening on port %d", port)
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        log.info("Shutting down")


if __name__ == "__main__":
    main()
