# Monitoring Stack — Reference

## Overview

The monitoring layer consists of four components wired together automatically by Docker Compose:

```
Flask App (/metrics)
    │  scrape every 10 s
    ▼
Prometheus  ──── evaluates alert_rules.yml every 30 s ────► AlertManager
    │                                                              │
    ▼                                                              ▼
Grafana (Golden Signals dashboard)                     remediation-service
                                                       /webhook  /remediate
```

---

## Prometheus

| Setting | Value |
|---|---|
| Scrape interval (default) | 15 s |
| Scrape interval (app) | 10 s |
| Evaluation interval | 15 s |
| Retention | 7 days |
| UI | http://localhost:9090 |

### Scrape targets

| Job | Target | What it collects |
|---|---|---|
| `techstream_api` | `techstream-app:5000/metrics` | HTTP counters, latency histograms, CPU/memory gauges |
| `node_exporter` | `node-exporter:9100` | Host CPU, memory, disk, network |
| `cadvisor` | `cadvisor:8080` | Per-container CPU, memory, network |
| `prometheus` | `localhost:9090` | Prometheus internal metrics |

### Useful PromQL queries

```promql
# Current error rate (%)
sum(rate(http_errors_total[2m])) by (job)
/ sum(rate(http_requests_total[2m])) by (job) * 100

# P99 latency on /api/data
histogram_quantile(0.99,
  sum(rate(http_request_duration_seconds_bucket{endpoint="/api/data"}[5m])) by (le))

# Requests per second
sum(rate(http_requests_total[1m]))

# CPU usage gauge from app
process_cpu_percent

# Memory RSS
process_memory_bytes / 1024 / 1024   # MB
```

---

## Alert Rules

File: `monitoring/prometheus/alert_rules.yml`  
Evaluation interval: 30 s

### Group: `golden_signals`

#### HighErrorRate
| Field | Value |
|---|---|
| Signal | Errors |
| Expression | `rate(http_errors_total[2m]) / rate(http_requests_total[2m]) > 0.05` |
| Threshold | 5 % error rate |
| Duration | Must hold for 1 minute |
| Severity | **critical** |
| Auto-remediation | Yes — AlertManager routes to `/remediate` |

#### HighLatencyP99
| Field | Value |
|---|---|
| Signal | Latency |
| Expression | `histogram_quantile(0.99, rate(http_request_duration_seconds_bucket[5m])) > 1.0` |
| Threshold | P99 > 1 second |
| Duration | Must hold for 2 minutes |
| Severity | warning |
| Auto-remediation | No (logged to `/webhook`) |

#### HighCpuSaturation
| Field | Value |
|---|---|
| Signal | Saturation |
| Expression | `process_cpu_percent > 80` |
| Threshold | 80 % |
| Duration | Must hold for 2 minutes |
| Severity | warning |
| Auto-remediation | No |

#### HighMemorySaturation
| Field | Value |
|---|---|
| Signal | Saturation |
| Expression | `process_memory_bytes / node_memory_MemTotal_bytes > 0.85` |
| Threshold | 85 % of total host memory |
| Duration | Must hold for 2 minutes |
| Severity | warning |
| Auto-remediation | No |

#### TrafficDrop
| Field | Value |
|---|---|
| Signal | Traffic |
| Expression | Current RPS < 20 % of RPS from 5 minutes ago |
| Threshold | 80 % drop vs baseline |
| Duration | Must hold for 1 minute (only when baseline RPS > 1) |
| Severity | **critical** |
| Auto-remediation | No |

### Group: `infrastructure`

#### AppContainerDown
| Field | Value |
|---|---|
| Expression | `up{job="techstream_api"} == 0` |
| Meaning | Prometheus cannot scrape `/metrics` |
| Duration | 30 seconds |
| Severity | **critical** |
| Auto-remediation | Yes — triggers container restart |

---

## AlertManager

UI: http://localhost:9093  
Config: `monitoring/alertmanager/alertmanager.yml`

### Routing tree

```
All alerts
├── severity=critical              → critical-webhook (/webhook, with auth token)
│   └── severity=critical          → auto-remediation (/remediate, 10 s group_wait)
│       signal=errors
└── severity=warning               → warning-email (platform team)
```

**Inhibition rule**: A critical alert suppresses warning alerts for the same `alertname` and `job`, preventing noise during an active incident.

### Receivers

| Receiver | Endpoint | Purpose |
|---|---|---|
| `default` | `/webhook` | Logs all alerts to remediation history |
| `critical-webhook` | `/webhook` | Logs critical alerts with auth token |
| `auto-remediation` | `/remediate` | Triggers automated healing for error alerts |
| `warning-email` | SMTP | Email notification for warnings |

---

## Grafana

UI: http://localhost:3000  
Credentials: `admin` / `techstream123` (or `$GRAFANA_PASSWORD`)

The **Golden Signals** dashboard is auto-provisioned on startup from:
```
monitoring/grafana/provisioning/
├── datasources/datasource.yml     # Wires Prometheus (uid: prometheus)
└── dashboards/
    ├── dashboard.yml              # Provisioning config
    └── golden_signals.json        # Dashboard definition
```

### Dashboard panels

| Panel | Metric | Visualisation |
|---|---|---|
| Request Rate | `rate(http_requests_total[1m])` | Time series |
| Error Rate % | `rate(http_errors_total) / rate(http_requests_total)` | Time series + threshold line |
| P99 Latency | `histogram_quantile(0.99, ...)` | Time series |
| CPU Usage | `process_cpu_percent` | Gauge |
| Memory Usage | `process_memory_bytes` | Gauge |
| Active Requests | `active_requests` | Stat |
| Alert State | Prometheus alert rules | Table |

---

## Adding a new alert

1. Add a rule block to `monitoring/prometheus/alert_rules.yml`
2. Add a matching receiver/route in `monitoring/alertmanager/alertmanager.yml` if routing changes are needed
3. Reload Prometheus without restart: `curl -X POST http://localhost:9090/-/reload`
4. Reload AlertManager: `curl -X POST http://localhost:9093/-/reload`
