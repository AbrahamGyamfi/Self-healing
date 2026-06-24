# ---------------------------------------------------------------------------
# EventBridge rule  – routes CloudWatch Alarm state-change to Lambda
# ---------------------------------------------------------------------------
resource "aws_cloudwatch_event_rule" "remediation_trigger" {
  name        = "${var.prefix}-remediation-trigger"
  description = "Routes ALARM-state CloudWatch alarms to the auto-remediation Lambda"

  event_pattern = jsonencode({
    source      = ["aws.cloudwatch"]
    "detail-type" = ["CloudWatch Alarm State Change"]
    detail = {
      alarmName = [
        { prefix = var.prefix },
      ]
      state = {
        value = ["ALARM"]
      }
    }
  })

  tags = { Function = "remediation-trigger" }
}

resource "aws_cloudwatch_event_target" "lambda" {
  rule      = aws_cloudwatch_event_rule.remediation_trigger.name
  target_id = "RemediationLambda"
  arn       = aws_lambda_function.remediation.arn
}

# ---------------------------------------------------------------------------
# EventBridge rule  – scheduled DevOps Guru–style AI analysis (every 5 min)
# ---------------------------------------------------------------------------
resource "aws_cloudwatch_event_rule" "ai_analysis_schedule" {
  name                = "${var.prefix}-ai-analysis-schedule"
  description         = "Periodic AI root-cause analysis"
  schedule_expression = "rate(5 minutes)"
  tags                = { Function = "ai-analysis" }
}

# (target would point to a Lambda wrapping root_cause_analyzer.py)
