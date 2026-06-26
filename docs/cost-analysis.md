# Cost Analysis — TechStream Self-Healing System

## Monthly Estimate (eu-west-1, minimum production configuration)

| Resource | Config | Monthly Cost (USD) |
|---|---|---|
| EC2 t3.small (ASG min=1) | 1 × t3.small on-demand | ~$15.18 |
| Application Load Balancer | 1 ALB + 1 listener | ~$16.20 |
| Lambda | ~8,640 invocations/mo (5-min schedule) | < $0.01 |
| CloudWatch | 4 alarms + custom metrics + logs (7 days) | ~$3.50 |
| SNS | ~500 notifications/mo | < $0.50 |
| EventBridge | ~8,640 rule evaluations/mo | < $0.10 |
| Amazon DevOps Guru | 1 resource hour * 730 hrs | ~$7.30 |
| Data Transfer | ~10 GB/mo | ~$0.90 |
| **Total** | | **~$43.69 / month** |

## Cost Optimisation Measures Applied

### Compute
- **t3.small** chosen over t3.medium — sufficient for demo; ASG handles burst.
- **ASG max=4** caps runaway scaling. Scale-out remediation adds ~$15/instance/month but only triggers under sustained saturation.
- Swap to **Spot Instances** (using mixed-instance policy) for up to 70% saving in non-prod environments.

### Storage / Logs
- CloudWatch log group retention set to **7 days** (`aws_cloudwatch_log_group` in Lambda module). Default unlimited retention would accumulate cost over time.
- Prometheus and Grafana data stored on **EC2 instance store** (no extra EBS cost) for local demo.

### Lambda
- Memory set to **256 MB** — remediation logic is I/O-bound (SSM/ASG API calls), not CPU-bound.
- Provisioned concurrency: **none** — cold-start latency (~200ms) is acceptable for remediation actions measured in minutes.

### DevOps Guru
- Scoped to a **tag-based resource collection** (`Project=TechStream-SelfHealing`) rather than the full account, so only monitored resources incur cost.
- Set `enable_devops_guru = false` in `terraform.tfvars` to disable entirely in dev/test environments.

### ALB
- ALB is the largest single cost item for this architecture. Alternatives:
  - Replace with **NLB** (~30% cheaper for TCP passthrough).
  - Remove entirely and expose EC2 directly (acceptable for demo, not production).

## Scaling Cost Projection

| Scenario | Config | Monthly Delta |
|---|---|---|
| Baseline (min) | 1 × t3.small | +$0 |
| Moderate load | 2 × t3.small (ASG scale-out) | +$15 |
| High load | 4 × t3.small (ASG max) | +$45 |
| Chaos demo running 24/7 | Extra Lambda invocations | < $0.10 |

## Tags for Cost Tracking

All resources are tagged `Project = TechStream-SelfHealing`. Use AWS Cost Explorer with this tag filter to isolate project spend from other workloads in the account.
