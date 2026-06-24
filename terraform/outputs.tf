output "vpc_id" {
  value       = aws_vpc.main.id
  description = "VPC ID"
}

output "app_url" {
  value       = "http://${aws_lb.app.dns_name}:5000"
  description = "TechStream application URL"
}

output "grafana_url" {
  value       = "http://${aws_lb.app.dns_name}:3000"
  description = "Grafana dashboard URL"
}

output "prometheus_url" {
  value       = "http://${aws_lb.app.dns_name}:9090"
  description = "Prometheus URL"
}

output "sns_topic_arn" {
  value       = aws_sns_topic.alerts.arn
  description = "SNS alerts topic ARN"
}

output "lambda_function_name" {
  value       = aws_lambda_function.remediation.function_name
  description = "Auto-remediation Lambda function name"
}

output "cloudwatch_dashboard_url" {
  value       = "https://console.aws.amazon.com/cloudwatch/home?region=${var.aws_region}#dashboards:name=${var.prefix}-golden-signals"
  description = "CloudWatch dashboard URL"
}
