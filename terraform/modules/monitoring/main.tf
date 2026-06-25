resource "aws_cloudwatch_dashboard" "golden_signals" {
  dashboard_name = "${var.prefix}-golden-signals"
  dashboard_body = jsonencode({
    widgets = [
      {
        type = "metric"
        properties = {
          title   = "Error Rate"
          period  = 60
          stat    = "Average"
          metrics = [["TechStream/Application", "ErrorRate"]]
          annotations = { horizontal = [{ value = 0.05, label = "5% threshold", color = "#ff0000" }] }
        }
      },
      {
        type = "metric"
        properties = {
          title          = "P99 Request Latency (ms)"
          period         = 60
          extended_statistic = "p99"
          metrics        = [["TechStream/Application", "RequestLatency"]]
          annotations    = { horizontal = [{ value = 1000, label = "1s threshold", color = "#ff9900" }] }
        }
      },
      {
        type = "metric"
        properties = {
          title   = "Traffic (Requests/min)"
          period  = 60
          stat    = "Sum"
          metrics = [["TechStream/Application", "RequestCount"]]
        }
      },
      {
        type = "metric"
        properties = {
          title   = "CPU Saturation (%)"
          period  = 60
          stat    = "Average"
          metrics = [["CWAgent", "cpu_usage_active", "AutoScalingGroupName", "${var.asg_name}"]]
          annotations = { horizontal = [{ value = 80, label = "80% threshold", color = "#ff0000" }] }
        }
      }
    ]
  })
}

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
  alarm_actions       = [var.sns_topic_arn, var.remediation_rule_arn]
  ok_actions          = [var.sns_topic_arn]
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
  alarm_actions       = [var.sns_topic_arn]
  ok_actions          = [var.sns_topic_arn]
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
  dimensions          = { AutoScalingGroupName = var.asg_name }
  period              = 60
  statistic           = "Average"
  treat_missing_data  = "notBreaching"
  alarm_actions       = [var.sns_topic_arn]
  ok_actions          = [var.sns_topic_arn]
  tags                = { Signal = "saturation" }
}
