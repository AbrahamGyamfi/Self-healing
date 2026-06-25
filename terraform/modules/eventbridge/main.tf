resource "aws_cloudwatch_event_rule" "remediation_trigger" {
  name        = "${var.prefix}-remediation-trigger"
  description = "Routes ALARM-state CloudWatch alarms to the auto-remediation Lambda"
  event_pattern = jsonencode({
    source        = ["aws.cloudwatch"]
    "detail-type" = ["CloudWatch Alarm State Change"]
    detail = {
      alarmName = [{ prefix = var.prefix }]
      state     = { value = ["ALARM"] }
    }
  })
}

resource "aws_cloudwatch_event_target" "lambda" {
  rule      = aws_cloudwatch_event_rule.remediation_trigger.name
  target_id = "RemediationLambda"
  arn       = var.lambda_arn
}

resource "aws_lambda_permission" "eventbridge" {
  statement_id  = "AllowEventBridgeInvoke"
  action        = "lambda:InvokeFunction"
  function_name = var.lambda_name
  principal     = "events.amazonaws.com"
  source_arn    = aws_cloudwatch_event_rule.remediation_trigger.arn
}

resource "aws_cloudwatch_event_rule" "ai_analysis_schedule" {
  name                = "${var.prefix}-ai-analysis-schedule"
  description         = "Periodic AI root-cause analysis trigger"
  schedule_expression = "rate(5 minutes)"
}
