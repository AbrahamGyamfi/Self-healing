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
├── app/                      # Flask application
│   ├── app.py                # API server with Prometheus metrics + chaos toggle
│   ├── Dockerfile
│   ├── requirements.txt
│   └── wsgi.py
├── monitoring/
│   ├── prometheus/
│   │   ├── prometheus.yml    # Scrape config (app, node-exporter, cAdvisor)
│   │   └── alert_rules.yml   # Golden Signal alert rules
│   ├── grafana/
│   │   └── provisioning/
│   │       ├── datasources/  # Auto-wired Prometheus datasource
│   │       └── dashboards/   # Golden Signals dashboard (auto-provisioned)
│   └── alertmanager/
│       └── alertmanager.yml  # Routes critical alerts to remediation webhook
├── chaos/
│   └── chaos_script.py       # Injects errors / latency / CPU / memory
├── remediation/
│   ├── webhook_handler.py    # HTTP server — receives alerts, executes healing
│   ├── lambda_remediation.py # AWS Lambda variant (EventBridge → SSM / ASG)
│   └── Dockerfile
├── ai_analysis/
│   ├── analyze.py            # Claude API — DevOps Guru-style RCA report
│   └── root_cause_analyzer.py # stdlib fallback — Z-score + causal chain
├── terraform/
│   ├── main.tf               # VPC, networking, SNS
│   ├── ec2.tf                # Launch template, ALB, ASG
│   ├── cloudwatch.tf         # Dashboard + alarms
│   ├── lambda.tf             # Remediation Lambda
│   ├── eventbridge.tf        # Alarm → Lambda routing
│   ├── iam.tf                # Roles + policies
│   └── devops_guru.tf        # Amazon DevOps Guru
├── scripts/
│   ├── deploy_local.sh       # docker compose up + health check
│   ├── run_demo.sh           # Full incident demo (chaos + AI analysis)
│   └── cleanup.sh            # docker compose down -v
└── docker-compose.yml        # Full local stack
```

---

## MTTR Comparison

| Scenario | Without Self-Healing | With Self-Healing |
|---|---|---|
| High error rate | 15–30 min (pager → triage → fix) | ~90 s (alert → remediate) |
| Container crash | 5–15 min | ~30 s |
| CPU saturation | 10–20 min | ~2 min (scale-out) |
| Latency spike | 15–30 min | ~2 min |
