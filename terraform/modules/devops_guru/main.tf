resource "aws_devopsguru_resource_collection" "techstream" {
  count = var.enable ? 1 : 0
  type  = "AWS_SERVICE"
  tags {
    app_boundary_key = "Project"
    tag_values       = ["TechStream-SelfHealing"]
  }
}

resource "aws_devopsguru_notification_channel" "alerts" {
  count = var.enable ? 1 : 0
  sns   { topic_arn = var.sns_topic_arn }
}
