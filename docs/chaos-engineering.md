# Chaos Engineering — Reference

## What chaos injection does

The chaos script (`chaos/chaos_script.py`) controls a state dict inside the Flask app via the `/chaos` endpoint. When chaos is active, the app deliberately misbehaves to simulate real-world failure modes. The remediation service watches for the resulting alerts and heals the system automatically.

Chaos state is stored in memory — a `docker restart techstream-app` or `POST /chaos/reset` returns the app to normal.

---

## Running chaos scenarios

```bash
# Full staged incident (recommended for demos)
python3 chaos/chaos_script.py --scenario full --duration 120 --workers 30

# Error storm only
python3 chaos/chaos_script.py --scenario errors --duration 60

# Latency injection only
python3 chaos/chaos_script.py --scenario latency --duration 60

# CPU spike
python3 chaos/chaos_script.py --scenario cpu --duration 30

# Memory pressure
python3 chaos/chaos_script.py --scenario memory --duration 30

# Traffic flood (no errors — tests saturation)
python3 chaos/chaos_script.py --scenario load --workers 50 --duration 90
```

Override the target URL (e.g. for AWS ALB):
```bash
python3 chaos/chaos_script.py --scenario errors --url http://your-alb-dns/
```

---

## Scenarios

### `errors` — HTTP Error Storm

Injects a 30 % HTTP 500 error rate across all endpoints.

| What happens | Value |
|---|---|
| Error rate injected | 30 % |
| Alert triggered | `HighErrorRate` (fires after 1 min at > 5 %) |
| Severity | critical |
| Auto-remediation | Yes — chaos reset + container restart |
| Expected MTTR | ~90 seconds |

**Observe**: Prometheus error rate graph spikes. AlertManager fires `HighErrorRate`. Remediation service logs a `remediation_executed` event at http://localhost:8080/history.

---

### `latency` — Slow Response Injection

Adds a 700 ms sleep to every request.

| What happens | Value |
|---|---|
| Latency injected | 700 ms per request |
| Alert triggered | `HighLatencyP99` (fires after 2 min at P99 > 1 s) |
| Severity | warning |
| Auto-remediation | No (logged only) |
| Expected MTTR | Manual reset required |

**Observe**: P99 latency histogram climbs past 1 s in Grafana. Run `curl -X POST http://localhost:5000/chaos/reset` to heal.

---

### `cpu` — CPU Spike

Runs a busy-loop on every request to max out CPU.

| What happens | Value |
|---|---|
| CPU injected | Busy-loop per request |
| Alert triggered | `HighCpuSaturation` (fires after 2 min at > 80 %) |
| Severity | warning |
| Auto-remediation | No |
| Expected MTTR | Manual reset |

**Observe**: `process_cpu_percent` gauge climbs above 80 % in Grafana. Latency also rises due to the extra computation.

---

### `memory` — Memory Pressure

Allocates a 50 MB buffer inside the app process.

| What happens | Value |
|---|---|
| Memory added | 50 MB RSS increase |
| Alert triggered | `HighMemorySaturation` (only if buffer + existing usage > 85 % of host RAM) |
| Severity | warning |
| Auto-remediation | No |
| Expected MTTR | Manual reset |

**Note**: On machines with > 4 GB RAM, the 50 MB buffer alone won't cross the 85 % threshold. Combine with `--scenario load` to stress memory further.

---

### `load` — Traffic Flood

Spawns N concurrent goroutine-like workers hammering all endpoints with no error injection.

| What happens | Value |
|---|---|
| Errors injected | None |
| Alert triggered | `HighCpuSaturation` (indirect, under heavy load) |
| Severity | warning |
| Auto-remediation | No |
| Expected MTTR | Stops automatically when `--duration` expires |

**Observe**: RPS counter in Grafana climbs. CPU saturation may trigger if workers are high (> 50).

---

### `full` — Staged Incident (4 phases)

The most realistic scenario — simulates a progressive incident that self-heals.

| Phase | Duration | What's injected | Alert |
|---|---|---|---|
| 1 — Latency Spike | 25 % of total | 600 ms latency | HighLatencyP99 (warning) |
| 2 — Error Storm | 50 % of total | 35 % errors + 400 ms latency | HighErrorRate (critical) |
| 3 — CPU + Errors | 25 % of total | 20 % errors + CPU spike | HighErrorRate + HighCpuSaturation |
| 4 — Recovery | 25 % of total | Nothing (chaos off) | All alerts resolve |

At 120 s total: phases are ~30 s / 60 s / 30 s with auto-heal starting at ~90 s.

**Observe**: Watch the Grafana dashboard change colour as phases progress. AlertManager fires `HighErrorRate` critical in phase 2, triggering auto-remediation. The remediation service resets chaos and restarted the container; by phase 4 all signals return to green.

---

## Manual chaos via curl

```bash
# Enable 30 % errors + 500 ms latency
curl -X POST http://localhost:5000/chaos \
  -H 'Content-Type: application/json' \
  -d '{"enabled": true, "error_rate": 0.30, "latency_ms": 500}'

# Enable CPU spike
curl -X POST http://localhost:5000/chaos \
  -H 'Content-Type: application/json' \
  -d '{"enabled": true, "cpu_spike": true}'

# Enable memory hog
curl -X POST http://localhost:5000/chaos \
  -H 'Content-Type: application/json' \
  -d '{"enabled": true, "memory_hog": true}'

# Check current chaos state
curl http://localhost:5000/chaos

# Reset — all chaos off
curl -X POST http://localhost:5000/chaos/reset
```

---

## Stats output

The chaos script prints a live stats summary every 10 seconds:

```
[14:32:10] Stats → total=847 errors=254 (30.0%) p50=512ms p99=1243ms
```

At the end of a run it prints a full report:

```
════════════════════════════════════════════════════
  Chaos run complete  (120.3s)
  Total requests : 2541
  Errors         : 763  (30.0%)
  Latency P50    : 508 ms
  Latency P95    : 987 ms
  Latency P99    : 1204 ms
════════════════════════════════════════════════════
```

---

## Self-healing verification

After a chaos run, confirm healing succeeded:

```bash
# 1. Check chaos is off
curl http://localhost:5000/chaos

# 2. Check app is healthy
curl http://localhost:5000/health

# 3. Check remediation log
curl http://localhost:8080/history | python3 -m json.tool

# 4. Check Prometheus — alerts should be resolved
curl http://localhost:9090/api/v1/alerts | python3 -m json.tool
```
