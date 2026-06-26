output "vpc_id" { value = aws_vpc.main.id }
output "subnet_ids" { value = [aws_subnet.public_a.id, aws_subnet.public_b.id] }
output "sg_id" { value = aws_security_group.app.id }
output "sns_topic_arn" { value = aws_sns_topic.alerts.arn }
