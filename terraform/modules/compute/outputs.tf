output "asg_name" { value = aws_autoscaling_group.app.name }
output "asg_arn" { value = aws_autoscaling_group.app.arn }
output "alb_dns_name" { value = aws_lb.app.dns_name }
