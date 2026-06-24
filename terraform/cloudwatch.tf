# ---------------------------------------------------------------------------
# CloudWatch Dashboard  – Golden Signals
# ---------------------------------------------------------------------------
resource "aws_cloudwatch_dashboard" "golden_signals" {
  dashboard_name = "${var.prefix}-golden-signals"
  dashboard_body = jsonencode({
    widgets = [
      {
        type = "metric"
        properties = {
          title  = "HTTP Error Rate (errors/total)"
          period = 60
          stat   = "Average"
          metrics = [
            ["TechStream/Application", "ErrorRate", { label = "Error Rate" }]
          ]
          annotations = {
            horizontal = [{ value = 0.05, label = "5% threshold", color = "#ff0000" }]
          }
        }
      },
      {
        type = "metric"
        properties = {
          title  = "P99 Request Latency"
          period = 60
          stat   = "p99"
          metrics = [
            ["TechStream/Application", "RequestLatency", { label = "P99 Latency (ms)" }]
          ]
          annotations = {
            horizontal = [{ value = 1000, label = "1 s threshold", color = "#ff9900" }]
          }
        }
      },
      {
        type = "metric"
        properties = {
          title   = "Traffic (Requests/s)"
          period  = 60
          stat    = "Sum"
          metrics = [["TechStream/Application", "RequestCount", { label = "RPS" }]]
        }
      },
      {
        type = "metric"
        properties = {
          title  = "CPU Saturation"
          period = 60
          stat   = "Average"
          metrics = [
            ["CWAgent", "cpu_usage_active", "AutoScalingGroupName", "${var.prefix}-asg",
              { label = "CPU %" }]
          ]
          annotations = {
            horizontal = [{ value = 80, label = "80% threshold", color = "#ff0000" }]
          }
        }
      }
    ]
  })
}

# ---------------------------------------------------------------------------
# CloudWatch Alarms
# ---------------------------------------------------------------------------
resource "aws_cloudwatch_metric_alarm" "high_error_rate" {
  alarm_name          = "${var.prefix}-HighErrorRate"
  alarm_description   = "HTTP error rate exceeded 5% — triggering auto-remediation"
  comparison_operator = "GreaterThanOrEqualToThreshold"
  evaluation_periods  = 2
  threshold           = 5
  metric_name         = "ErrorRate"
  namespace           = "TechStream/Application"
  period              = 60
  statistic           = "Average"
  treat_missing_data  = "notBreaching"
  alarm_actions       = [aws_sns_topic.alerts.arn, aws_cloudwatch_event_rule.remediation_trigger.arn]
  ok_actions          = [aws_sns_topic.alerts.arn]
  tags                = { Signal = "errors" }
}

resource "aws_cloudwatch_metric_alarm" "high_latency" {
  alarm_name          = "${var.prefix}-HighLatencyP99"
  alarm_description   = "P99 latency exceeded 1 second"
  comparison_operator = "GreaterThanOrEqualToThreshold"
  evaluation_periods  = 3
  threshold           = 1000
  metric_name         = "RequestLatency"
  namespace           = "TechStream/Application"
  extended_statistic  = "p99"
  period              = 60
  treat_missing_data  = "notBreaching"
  alarm_actions       = [aws_sns_topic.alerts.arn]
  ok_actions          = [aws_sns_topic.alerts.arn]
  tags                = { Signal = "latency" }
}

resource "aws_cloudwatch_metric_alarm" "high_cpu" {
  alarm_name          = "${var.prefix}-HighCpuSaturation"
  alarm_description   = "CPU utilisation exceeded 80%"
  comparison_operator = "GreaterThanOrEqualToThreshold"
  evaluation_periods  = 3
  threshold           = 80
  metric_name         = "cpu_usage_active"
  namespace           = "CWAgent"
  dimensions          = { AutoScalingGroupName = "${var.prefix}-asg" }
  period              = 60
  statistic           = "Average"
  treat_missing_data  = "notBreaching"
  alarm_actions       = [aws_sns_topic.alerts.arn]
  ok_actions          = [aws_sns_topic.alerts.arn]
  tags                = { Signal = "saturation" }
}
