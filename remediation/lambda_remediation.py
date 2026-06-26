"""
AWS Lambda – Automated Remediation Function
============================================
Triggered by EventBridge when a CloudWatch Alarm transitions to ALARM state.

Supported actions:
  1. Restart EC2 instance (stop + start)
  2. Scale out ASG by +1 (buys headroom under load)
  3. Execute SSM Run Command to restart the systemd service

Environment variables
---------------------
  EC2_INSTANCE_ID   – target EC2 instance
  ASG_NAME          – Auto Scaling Group name
  SSM_DOCUMENT      – SSM document name (default: AWS-RunShellScript)
  SNS_TOPIC_ARN     – SNS topic for remediation notifications
  SCALE_OUT_ENABLED – "true" to allow ASG scale-out (default: "false")
"""

import json
import logging
import os
import time

import boto3

log = logging.getLogger()
log.setLevel(logging.INFO)

EC2_INSTANCE_ID = os.environ.get("EC2_INSTANCE_ID", "")
ASG_NAME = os.environ.get("ASG_NAME", "")
SSM_DOCUMENT = os.environ.get("SSM_DOCUMENT", "AWS-RunShellScript")
SNS_TOPIC_ARN = os.environ.get("SNS_TOPIC_ARN", "")
SCALE_OUT_ENABLED = os.environ.get("SCALE_OUT_ENABLED", "false").lower() == "true"
REGION = os.environ.get("AWS_REGION", "eu-west-1")

# Lazy-initialized clients — avoids credential errors at import time and
# allows connection reuse across warm Lambda invocations.
_clients: dict = {}


def _client(service: str):
    if service not in _clients:
        _clients[service] = boto3.client(service, region_name=REGION)
    return _clients[service]


# ---------------------------------------------------------------------------
# Remediation actions
# ---------------------------------------------------------------------------

def restart_service_via_ssm(instance_id: str) -> dict:
    """Run `systemctl restart techstream` on the instance via SSM."""
    log.info("SSM: restarting techstream service on %s", instance_id)
    resp = _client("ssm").send_command(
        InstanceIds=[instance_id],
        DocumentName=SSM_DOCUMENT,
        Parameters={
            "commands": [
                "systemctl restart techstream || (docker restart techstream-app && echo 'docker restarted')"
            ]
        },
        Comment="Auto-remediation: restart TechStream service",
        TimeoutSeconds=60,
    )
    cmd_id = resp["Command"]["CommandId"]
    log.info("SSM command sent, CommandId=%s", cmd_id)
    return {"action": "ssm_restart", "command_id": cmd_id, "instance_id": instance_id}


def scale_out_asg(asg_name: str, increment: int = 1) -> dict:
    """Increase the desired capacity of the ASG by `increment`."""
    asg_client = _client("autoscaling")
    resp = asg_client.describe_auto_scaling_groups(AutoScalingGroupNames=[asg_name])
    groups = resp.get("AutoScalingGroups", [])
    if not groups:
        return {"action": "scale_out_asg", "error": f"ASG {asg_name!r} not found"}
    group = groups[0]
    current = group["DesiredCapacity"]
    maximum = group["MaxSize"]
    new_desired = min(current + increment, maximum)
    if new_desired == current:
        return {"action": "scale_out_asg", "skipped": "already at max capacity", "current": current}
    asg_client.set_desired_capacity(AutoScalingGroupName=asg_name, DesiredCapacity=new_desired)
    log.info("ASG %s: scaled from %d → %d", asg_name, current, new_desired)
    return {"action": "scale_out_asg", "previous_desired": current, "new_desired": new_desired}


def notify_sns(subject: str, body: dict) -> None:
    if not SNS_TOPIC_ARN:
        return
    try:
        _client("sns").publish(
            TopicArn=SNS_TOPIC_ARN,
            Subject=subject,
            Message=json.dumps(body, indent=2, default=str),
        )
    except Exception as exc:
        log.warning("SNS notification failed: %s", exc)


# ---------------------------------------------------------------------------
# Decision logic
# ---------------------------------------------------------------------------

def choose_remediation(alarm_name: str, alarm_description: str) -> list[dict]:
    """
    Pick the correct remediation strategy based on the alarm that fired.
    Returns a list of action results.
    """
    results: list[dict] = []
    name_lower = alarm_name.lower()

    if "errorrate" in name_lower or "error_rate" in name_lower:
        # High error rate → restart the service to clear bad state
        if EC2_INSTANCE_ID:
            results.append(restart_service_via_ssm(EC2_INSTANCE_ID))
    elif "latency" in name_lower:
        # High latency → scale out for more capacity
        if SCALE_OUT_ENABLED and ASG_NAME:
            results.append(scale_out_asg(ASG_NAME))
        elif EC2_INSTANCE_ID:
            results.append(restart_service_via_ssm(EC2_INSTANCE_ID))
    elif "saturation" in name_lower or "cpu" in name_lower:
        # Saturation → scale out
        if SCALE_OUT_ENABLED and ASG_NAME:
            results.append(scale_out_asg(ASG_NAME))
    elif "containerdown" in name_lower or "appdown" in name_lower:
        # App down → restart immediately
        if EC2_INSTANCE_ID:
            results.append(restart_service_via_ssm(EC2_INSTANCE_ID))
    else:
        # Catch-all: restart
        if EC2_INSTANCE_ID:
            results.append(restart_service_via_ssm(EC2_INSTANCE_ID))

    return results


# ---------------------------------------------------------------------------
# Lambda handler
# ---------------------------------------------------------------------------

def handler(event: dict, context) -> dict:
    """
    EventBridge rule routes CloudWatch Alarm state-change events here.

    Expected event structure (EventBridge):
    {
      "source": "aws.cloudwatch",
      "detail-type": "CloudWatch Alarm State Change",
      "detail": {
        "alarmName": "TechStream-HighErrorRate",
        "state": { "value": "ALARM" },
        "previousState": { "value": "OK" },
        "configuration": { "description": "..." }
      }
    }
    """
    log.info("Event received: %s", json.dumps(event, default=str))

    detail = event.get("detail", {})
    alarm_name = detail.get("alarmName", "unknown")
    new_state = detail.get("state", {}).get("value", "")
    description = detail.get("configuration", {}).get("description", "")

    if new_state != "ALARM":
        log.info("Alarm %s transitioned to %s — no action needed", alarm_name, new_state)
        return {"statusCode": 200, "message": f"state={new_state}, no action"}

    log.info("Alarm FIRING: %s", alarm_name)

    remediation_results = choose_remediation(alarm_name, description)

    outcome = {
        "alarm": alarm_name,
        "state": new_state,
        "remediation_steps": remediation_results,
        "timestamp": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
    }

    notify_sns(
        subject=f"Auto-remediation executed: {alarm_name}",
        body=outcome,
    )

    log.info("Remediation complete: %s", json.dumps(outcome, default=str))
    return {"statusCode": 200, "body": outcome}
