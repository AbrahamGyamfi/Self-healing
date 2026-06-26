"""
Unit tests for the AWS Lambda remediation handler.
All boto3 calls are mocked — no AWS credentials required.
"""

import json
import sys
import os
from unittest.mock import MagicMock, patch, call

import pytest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "remediation"))

import lambda_remediation as lr


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _alarm_event(alarm_name="HighErrorRate", state="ALARM"):
    return {
        "source": "aws.cloudwatch",
        "detail-type": "CloudWatch Alarm State Change",
        "detail": {
            "alarmName": alarm_name,
            "state": {"value": state},
            "previousState": {"value": "OK"},
            "configuration": {"description": f"Test alarm: {alarm_name}"},
        },
    }


def _mock_ssm(cmd_id="cmd-001"):
    m = MagicMock()
    m.send_command.return_value = {"Command": {"CommandId": cmd_id}}
    return m


def _mock_asg(desired=1, maximum=4):
    m = MagicMock()
    m.describe_auto_scaling_groups.return_value = {
        "AutoScalingGroups": [{
            "AutoScalingGroupName": "techstream-asg",
            "DesiredCapacity": desired,
            "MaxSize": maximum,
        }]
    }
    return m


@pytest.fixture(autouse=True)
def clean_client_cache():
    """Clear the lazy-client cache before each test."""
    lr._clients.clear()
    yield
    lr._clients.clear()


@pytest.fixture(autouse=True)
def set_env(monkeypatch):
    monkeypatch.setenv("EC2_INSTANCE_ID", "i-0abc123def456")
    monkeypatch.setenv("ASG_NAME", "techstream-asg")
    monkeypatch.setenv("SNS_TOPIC_ARN", "arn:aws:sns:eu-west-1:123456789012:alerts")
    monkeypatch.setenv("SCALE_OUT_ENABLED", "true")


# ---------------------------------------------------------------------------
# handler()
# ---------------------------------------------------------------------------

class TestHandler:
    def test_alarm_state_triggers_remediation(self):
        mock_ssm = _mock_ssm()
        with patch.object(lr, "_client", return_value=mock_ssm):
            result = lr.handler(_alarm_event("HighErrorRate", "ALARM"), {})
        assert result["statusCode"] == 200

    def test_ok_state_is_skipped(self):
        result = lr.handler(_alarm_event("HighErrorRate", "OK"), {})
        assert result["statusCode"] == 200
        assert "no action" in result.get("message", "")

    def test_insufficient_ok_no_boto_calls(self):
        with patch.object(lr, "_client") as mock_c:
            lr.handler(_alarm_event(state="OK"), {})
            mock_c.assert_not_called()

    def test_alarm_body_contains_alarm_name(self):
        mock_ssm = _mock_ssm()
        with patch.object(lr, "_client", return_value=mock_ssm):
            result = lr.handler(_alarm_event("HighErrorRate", "ALARM"), {})
        body = result["body"]
        assert body["alarm"] == "HighErrorRate"

    def test_missing_detail_still_returns_200(self):
        result = lr.handler({}, {})
        assert result["statusCode"] == 200


# ---------------------------------------------------------------------------
# choose_remediation()
# ---------------------------------------------------------------------------

class TestChooseRemediation:
    def test_high_error_rate_runs_ssm_restart(self):
        mock_ssm = _mock_ssm()
        with patch.object(lr, "EC2_INSTANCE_ID", "i-0abc123def456"), \
             patch.object(lr, "_client", return_value=mock_ssm):
            results = lr.choose_remediation("HighErrorRate", "")
        assert any(r.get("action") == "ssm_restart" for r in results)

    def test_high_latency_scales_out(self):
        mock_asg = _mock_asg()
        with patch.object(lr, "ASG_NAME", "techstream-asg"), \
             patch.object(lr, "SCALE_OUT_ENABLED", True), \
             patch.object(lr, "_client", return_value=mock_asg):
            results = lr.choose_remediation("HighLatencyP99", "")
        assert any(r.get("action") == "scale_out_asg" for r in results)

    def test_cpu_saturation_scales_out(self):
        mock_asg = _mock_asg()
        with patch.object(lr, "ASG_NAME", "techstream-asg"), \
             patch.object(lr, "SCALE_OUT_ENABLED", True), \
             patch.object(lr, "_client", return_value=mock_asg):
            results = lr.choose_remediation("HighCpuSaturation", "")
        assert any(r.get("action") == "scale_out_asg" for r in results)

    def test_container_down_restarts(self):
        mock_ssm = _mock_ssm()
        with patch.object(lr, "EC2_INSTANCE_ID", "i-0abc123def456"), \
             patch.object(lr, "_client", return_value=mock_ssm):
            results = lr.choose_remediation("AppContainerDown", "")
        assert any(r.get("action") == "ssm_restart" for r in results)

    def test_returns_list(self):
        mock_ssm = _mock_ssm()
        with patch.object(lr, "EC2_INSTANCE_ID", "i-0abc123def456"), \
             patch.object(lr, "_client", return_value=mock_ssm):
            results = lr.choose_remediation("HighErrorRate", "")
        assert isinstance(results, list)


# ---------------------------------------------------------------------------
# restart_service_via_ssm()
# ---------------------------------------------------------------------------

class TestSsmRestart:
    def test_sends_aws_run_shell_script(self):
        mock_ssm = _mock_ssm()
        with patch.object(lr, "_client", return_value=mock_ssm):
            lr.restart_service_via_ssm("i-0abc123def456")
        call_kwargs = mock_ssm.send_command.call_args[1]
        assert call_kwargs["DocumentName"] == "AWS-RunShellScript"

    def test_returns_ssm_restart_action(self):
        mock_ssm = _mock_ssm("cmd-xyz")
        with patch.object(lr, "_client", return_value=mock_ssm):
            result = lr.restart_service_via_ssm("i-0abc123def456")
        assert result["action"] == "ssm_restart"
        assert result["command_id"] == "cmd-xyz"

    def test_targets_correct_instance(self):
        mock_ssm = _mock_ssm()
        with patch.object(lr, "_client", return_value=mock_ssm):
            lr.restart_service_via_ssm("i-target-instance")
        call_kwargs = mock_ssm.send_command.call_args[1]
        assert "i-target-instance" in call_kwargs["InstanceIds"]


# ---------------------------------------------------------------------------
# scale_out_asg()
# ---------------------------------------------------------------------------

class TestScaleOutAsg:
    def test_increments_desired_capacity(self):
        mock_asg = _mock_asg(desired=1, maximum=4)
        with patch.object(lr, "_client", return_value=mock_asg):
            result = lr.scale_out_asg("techstream-asg")
        mock_asg.set_desired_capacity.assert_called_once_with(
            AutoScalingGroupName="techstream-asg",
            DesiredCapacity=2,
        )
        assert result["new_desired"] == 2

    def test_does_not_exceed_max_size(self):
        mock_asg = _mock_asg(desired=4, maximum=4)
        with patch.object(lr, "_client", return_value=mock_asg):
            result = lr.scale_out_asg("techstream-asg")
        mock_asg.set_desired_capacity.assert_not_called()
        assert "skipped" in result

    def test_asg_not_found_returns_error(self):
        mock_asg = MagicMock()
        mock_asg.describe_auto_scaling_groups.return_value = {"AutoScalingGroups": []}
        with patch.object(lr, "_client", return_value=mock_asg):
            result = lr.scale_out_asg("missing-asg")
        assert "error" in result


# ---------------------------------------------------------------------------
# notify_sns()
# ---------------------------------------------------------------------------

class TestNotifySns:
    def test_publishes_to_topic(self):
        mock_sns = MagicMock()
        topic = "arn:aws:sns:eu-west-1:123456789012:alerts"
        with patch.object(lr, "SNS_TOPIC_ARN", topic), \
             patch.object(lr, "_client", return_value=mock_sns):
            lr.notify_sns("Test subject", {"alarm": "HighErrorRate"})
        mock_sns.publish.assert_called_once()
        kwargs = mock_sns.publish.call_args[1]
        assert kwargs["TopicArn"] == topic
        assert "HighErrorRate" in kwargs["Message"]

    def test_empty_topic_arn_skips_publish(self):
        with patch.object(lr, "SNS_TOPIC_ARN", ""), \
             patch.object(lr, "_client") as mock_c:
            lr.notify_sns("subject", {})
            mock_c.assert_not_called()
