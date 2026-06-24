# ---------------------------------------------------------------------------
# Amazon DevOps Guru
# ---------------------------------------------------------------------------
# DevOps Guru uses ML to detect operational anomalies across your AWS stack.
# Here we enable it scoped to a CloudFormation stack tag (or all resources).
#
# Note: DevOps Guru is not available in all regions. Check availability first.
#       Set var.enable_devops_guru = true to activate.
# ---------------------------------------------------------------------------

resource "aws_devopsguru_resource_collection" "techstream" {
  count = var.enable_devops_guru ? 1 : 0

  type = "AWS_SERVICE"

  # Monitor all resources with the Project tag matching our stack
  tags {
    app_boundary_key    = "Project"
    tag_values          = ["TechStream-SelfHealing"]
  }
}

resource "aws_devopsguru_notification_channel" "alerts" {
  count = var.enable_devops_guru ? 1 : 0

  sns {
    topic_arn = aws_sns_topic.alerts.arn
  }
}

# ---------------------------------------------------------------------------
# DevOps Guru Insight — exported for presentation
# ---------------------------------------------------------------------------
# After running the chaos script, export insights using:
#   aws devops-guru list-insights --status-filter type=ONGOING \
#     --query 'ProactiveInsights[*].{Name:Name,Severity:Severity,Status:Status}'
#
# Or view in the AWS Console under:
#   Developer Tools → DevOps Guru → Insights
# ---------------------------------------------------------------------------
