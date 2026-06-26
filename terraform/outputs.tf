output "app_url" {
  value       = "http://<instance-public-ip>:5000  # get IP: aws ec2 describe-instances --filters Name=tag:Name,Values=techstream-app --query 'Reservations[0].Instances[0].PublicIpAddress' --output text"
  description = "TechStream application URL (direct instance, no ALB)"
}

output "cloudwatch_dashboard_url" {
  value       = "https://console.aws.amazon.com/cloudwatch/home?region=${var.aws_region}#dashboards:name=${var.prefix}-golden-signals"
  description = "CloudWatch Golden Signals dashboard"
}

output "sns_topic_arn" {
  value       = module.networking.sns_topic_arn
  description = "SNS alerts topic ARN"
}

output "lambda_function_name" {
  value       = module.lambda.lambda_name
  description = "Auto-remediation Lambda function name"
}

output "asg_name" {
  value       = module.compute.asg_name
  description = "Auto Scaling Group name"
}
