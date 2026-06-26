# TechStream Self-Healing System

Reduce MTTR to near-zero by monitoring the four Golden Signals, automatically detecting anomalies, and triggering remediation before an engineer is paged.

---

## Architecture

```
┌─────────────────────────────────────────────────────────────────────┐
│                          TECHSTREAM STACK                           │
│                                                                     │
│  ┌──────────────┐   /metrics   ┌─────────────┐   alerts   ┌──────┐ │
│  │ Flask App    │◄────────────►│ Prometheus  │──────────►│Alert │ │
│  │ :5000        │              │ :9090       │            │Mgr   │ │
│  │              │              └──────┬──────┘            │:9093 │ │
│  │ • /api/data  │                     │                    └──┬───┘ │
│  │ • /chaos     │              ┌──────▼──────┐               │     │
│  │ • /metrics   │              │  Grafana    │       ┌────────▼───┐ │
│  └──────────────┘              │  :3000      │       │Remediation │ │
│         ▲                      │  Golden     │       │Service     │ │
│         │ inject               │  Signals    │       │:8080       │ │
│  ┌──────┴──────┐               └─────────────┘       └────────────┘ │
│  │ Chaos Script│                                                     │
│  │             │         ┌────────────────────────────────────────┐ │
│  │ • errors    │         │  AI Root Cause Analyzer                │ │
│  │ • latency   │         │  analyze.py  (Claude API)              │ │
│  │ • cpu spike │         │  root_cause_analyzer.py  (stdlib)      │ │
│  └─────────────┘         └────────────────────────────────────────┘ │
└─────────────────────────────────────────────────────────────────────┘

AWS Deployment (Terraform)
  EC2 / ASG  →  CloudWatch Alarms  →  EventBridge  →  Lambda
                                                        ↓
                                              SSM Run Command / ASG scale-out
                                                        ↓
                                              SNS Notification  +  DevOps Guru
```

---

## Golden Signals Monitored

| Signal | Metric | Alert Threshold |
|---|---|---|
| **Latency** | P99 request duration | > 1 s |
| **Traffic** | Requests per second | Drop > 80 % |
| **Errors** | HTTP 5xx rate | > 5 % |
| **Saturation** | CPU utilisation | > 80 % |
| **Saturation** | Memory (RSS) | > 85 % of total |

---

## Quick Start (Local / Docker)

### Prerequisites
- Docker ≥ 24 with Compose plugin
- Python 3.10+ (for chaos script and AI analyzer)
- `ANTHROPIC_API_KEY` set in your environment (optional — enables Claude AI analysis)

### 1. Deploy the stack

```bash
./scripts/deploy_local.sh
```

| Service | URL | Credentials |
|---|---|---|
| TechStream API | http://localhost:5000 | — |
| Prometheus | http://localhost:9090 | — |
| Grafana | http://localhost:3000 | admin / techstream123 |
| AlertManager | http://localhost:9093 | — |
| Remediation | http://localhost:8080/history | — |

### 2. Run the end-to-end demo

```bash
./scripts/run_demo.sh
```

The script runs through four phases and prints an AI-generated RCA report.

### 3. Tear down

```bash
./scripts/cleanup.sh
```

---

## Manual Chaos Injection

```bash
# Full incident scenario (latency → errors → CPU → recovery)
python3 chaos/chaos_script.py --scenario full --duration 120 --workers 30

# Error storm only
python3 chaos/chaos_script.py --scenario errors --duration 60

# CPU spike
python3 chaos/chaos_script.py --scenario cpu --duration 30

# High latency
python3 chaos/chaos_script.py --scenario latency --duration 60

# High traffic (no errors)
python3 chaos/chaos_script.py --scenario load --workers 50 --duration 90
```

---

## AI Root Cause Analysis

### Claude-powered (recommended)

```bash
export ANTHROPIC_API_KEY=sk-ant-...
python3 ai_analysis/analyze.py --prometheus http://localhost:9090
# Save full JSON report:
python3 ai_analysis/analyze.py --output report.json
```

Produces a structured RCA report with sections:
- Anomaly Summary
- Root Cause Analysis
- Impact Assessment
- Automated Remediation Actions
- Recommended Follow-up (On-Call Engineer)
- MTTR Estimate

### Statistical analyzer (no API key required)

```bash
python3 ai_analysis/root_cause_analyzer.py --watch --interval 60
```

Uses Z-score + IQR anomaly detection and causal-chain correlation.

---

## Self-Healing Flow

```
Chaos script injects errors
        ↓
Prometheus scrapes /metrics every 10 s
        ↓
alert_rules.yml: error_rate > 5% for 1 min → HighErrorRate FIRING
        ↓
AlertManager routes to remediation-service:8080/remediate
        ↓
webhook_handler.py:
  1. POST /chaos/reset  — clears any injected chaos
  2. docker restart techstream-app  — recovers the container
        ↓
Prometheus sees healthy metrics → alert RESOLVES
        ↓
Grafana dashboard returns to green
```

---

## AWS Deployment (Terraform)

### Deploy

```bash
cd terraform/
cp terraform.tfvars.example terraform.tfvars   # fill in your values
terraform init
terraform plan
terraform apply
```

### What gets created

| Resource | Purpose |
|---|---|
| VPC + subnets + IGW | Network foundation |
| EC2 Launch Template + ASG | Application hosting |
| Application Load Balancer | Traffic distribution |
| CloudWatch Dashboard | Golden Signals visualisation |
| CloudWatch Alarms (3) | Error rate · Latency · CPU |
| SNS Topic | Alert notifications |
| EventBridge Rule | Routes alarms to Lambda |
| Lambda Function | Auto-remediation (SSM restart / ASG scale-out) |
| IAM Roles | Least-privilege permissions |
| DevOps Guru (optional) | ML-based anomaly detection |

### Enable DevOps Guru

```hcl
# terraform.tfvars
enable_devops_guru = true
alert_email        = "you@techstream.io"
```

After running the chaos script, export insights:

```bash
aws devops-guru list-insights --status-filter type=ONGOING \
  --query 'ProactiveInsights[*].{Name:Name,Severity:Severity,Status:Status}'
```

---

## Project Layout

```
Self-healing/
├── app/                          # Flask application
│   ├── app.py                    # API + Prometheus metrics + chaos toggle
│   ├── Dockerfile
│   ├── requirements.txt
│   ├── wsgi.py
│   └── templates/index.html      # Dark-theme dashboard UI
├── monitoring/
│   ├── prometheus/
│   │   ├── prometheus.yml        # Scrape config (app, node-exporter, cAdvisor)
│   │   └── alert_rules.yml       # Golden Signal alert rules (5 rules, 2 groups)
│   ├── grafana/
│   │   └── provisioning/
│   │       ├── datasources/      # Auto-wired Prometheus datasource (uid: prometheus)
│   │       └── dashboards/       # Golden Signals dashboard (auto-provisioned)
│   └── alertmanager/
│       └── alertmanager.yml      # Routes critical alerts → remediation webhook
├── chaos/
│   └── chaos_script.py           # 6 scenarios: errors/latency/cpu/memory/load/full
├── remediation/
│   ├── webhook_handler.py        # HTTP server: alerts → chaos reset → container restart
│   ├── lambda_remediation.py     # AWS Lambda variant: EventBridge → SSM / ASG scale-out
│   └── Dockerfile
├── ai_analysis/
│   ├── analyze.py                # Claude API (claude-sonnet-4-6) — DevOps Guru-style RCA
│   └── root_cause_analyzer.py   # stdlib fallback — Z-score + IQR + causal chain
├── terraform/
│   ├── main.tf                   # Root module — wires all child modules
│   ├── variables.tf
│   ├── outputs.tf
│   ├── terraform.tfvars          # Active deployment values
│   ├── terraform.tfvars.example  # Template for new deployments
│   └── modules/
│       ├── networking/           # VPC, subnets, IGW, SG, SNS
│       ├── iam/                  # EC2 role + Lambda role (least-privilege)
│       ├── compute/              # Launch Template, ALB, ASG
│       ├── lambda/               # Remediation function + log group
│       ├── eventbridge/          # Alarm routing rule + AI analysis schedule
│       ├── monitoring/           # CloudWatch dashboard + 3 alarms
│       └── devops_guru/          # ML anomaly detection (tag-scoped)
├── tests/
│   ├── conftest.py               # Shared fixtures (Flask test client, chaos reset)
│   ├── test_app.py               # 24 Flask endpoint unit tests
│   ├── test_remediation.py       # 11 webhook service tests (mocked Docker)
│   ├── test_chaos.py             # 13 chaos script tests (Stats, Scenarios)
│   └── requirements.txt
├── docs/
│   └── cost-analysis.md          # Itemised AWS cost breakdown + optimisation notes
├── scripts/
│   ├── deploy_local.sh           # docker compose up + health check
│   ├── run_demo.sh               # Full incident demo (chaos + AI analysis)
│   └── cleanup.sh                # docker compose down -v
├── .github/workflows/ci.yml      # CI: lint → test → terraform validate → docker build
├── pytest.ini
└── docker-compose.yml            # 7-service local stack
```

---

## Architecture Decision Records

### ADR-001: Flask over FastAPI
**Decision**: Use Flask with `prometheus_client` for the application server.  
**Reason**: `prometheus_client` provides a WSGI middleware that integrates directly with Flask via `make_wsgi_app()`, giving zero-overhead metric exposition. FastAPI requires an async bridge. Flask is also simpler to instrument for chaos injection (global state dict).

### ADR-002: Webhook-based remediation over direct Prometheus integration
**Decision**: AlertManager calls the remediation service via HTTP webhook, rather than having the remediator poll Prometheus.  
**Reason**: AlertManager already handles deduplication, grouping, silence, and inhibition. Re-implementing those in a poller would duplicate work and introduce race conditions. The webhook pattern also allows manual testing with a single `curl`.

### ADR-003: Modular Terraform over a single flat configuration
**Decision**: Split AWS resources across 7 child modules (`networking`, `iam`, `compute`, `lambda`, `eventbridge`, `monitoring`, `devops_guru`).  
**Reason**: Flat files make `terraform plan` output unreadable at scale, and blast radius of a change is unbounded. Modules enforce explicit input/output contracts, allow independent `terraform destroy -target`, and make the IAM/networking separation obvious for security reviews.

### ADR-004: Claude API for RCA over a rules-based engine
**Decision**: Use `claude-sonnet-4-6` for root cause analysis when an API key is available, with a Z-score/IQR statistical fallback.  
**Reason**: Rules-based RCA requires enumerating every failure mode upfront. LLMs can correlate across all four Golden Signals simultaneously and generate actionable remediation steps in natural language — matching what DevOps Guru's ML service does, but available locally without AWS.

### ADR-005: Tag-scoped DevOps Guru over full-account monitoring
**Decision**: Scope DevOps Guru's resource collection to `Project=TechStream-SelfHealing` tag.  
**Reason**: Full-account DevOps Guru monitoring scales cost with the number of resources. Tag-scoping constrains cost to exactly the resources under test (~$7/month) and avoids noisy cross-project insights.

---

## Runbook

### Alert: HighErrorRate (HTTP 5xx > 5%)

1. **Check current chaos state**: `curl http://localhost:5000/chaos`
2. **If chaos is active**: `curl -X POST http://localhost:5000/chaos/reset`
3. **Check remediation history**: `curl http://localhost:8080/history`
4. **Check container health**: `docker ps | grep techstream-app`
5. **If container is unhealthy**: `docker restart techstream-app`
6. **Run AI analysis**: `python3 ai_analysis/analyze.py` (requires `ANTHROPIC_API_KEY`)

### Alert: HighLatencyP99 (P99 > 1 s)

1. Check chaos latency: `curl http://localhost:5000/chaos | python3 -m json.tool`
2. If `latency_ms > 0`: `curl -X POST http://localhost:5000/chaos/reset`
3. Check node exporter: `curl http://localhost:9100/metrics | grep node_cpu`
4. If host CPU is saturated: identify and kill the offending process or scale out

### Alert: HighCpuSaturation (CPU > 80%)

1. Check if CPU spike is chaos-injected: `curl http://localhost:5000/chaos`
2. If `cpu_spike: true`: reset chaos as above
3. If genuine: check `top` / `docker stats`; scale ASG if on AWS

### Alert: AppContainerDown

1. `docker ps -a | grep techstream-app` — get exit code
2. `docker logs techstream-app --tail 50`
3. `docker start techstream-app` or `docker compose up -d techstream-app`
4. If recurring: check host memory (`free -m`) and disk (`df -h`)

### Silence an alert during maintenance

```bash
# Via AlertManager UI at http://localhost:9093
# Or via API:
curl -X POST http://localhost:9093/api/v2/silences \
  -H 'Content-Type: application/json' \
  -d '{
    "matchers": [{"name": "alertname", "value": "HighErrorRate", "isRegex": false}],
    "startsAt": "2026-01-01T00:00:00Z",
    "endsAt": "2026-01-01T02:00:00Z",
    "createdBy": "oncall",
    "comment": "planned maintenance"
  }'
```

---

## MTTR Comparison

| Scenario | Without Self-Healing | With Self-Healing |
|---|---|---|
| High error rate | 15–30 min (pager → triage → fix) | ~90 s (alert → remediate) |
| Container crash | 5–15 min | ~30 s |
| CPU saturation | 10–20 min | ~2 min (scale-out) |
| Latency spike | 15–30 min | ~2 min |
