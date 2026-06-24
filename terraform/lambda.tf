# ---------------------------------------------------------------------------
# Package the Lambda function
# ---------------------------------------------------------------------------
data "archive_file" "lambda_zip" {
  type        = "zip"
  source_file = "${path.module}/../remediation/lambda_remediation.py"
  output_path = "${path.module}/.build/lambda_remediation.zip"
}

# ---------------------------------------------------------------------------
# Lambda function
# ---------------------------------------------------------------------------
resource "aws_lambda_function" "remediation" {
  function_name    = "${var.prefix}-auto-remediation"
  description      = "TechStream automated remediation triggered by CloudWatch Alarms"
  filename         = data.archive_file.lambda_zip.output_path
  source_code_hash = data.archive_file.lambda_zip.output_base64sha256
  role             = aws_iam_role.lambda_remediation.arn
  handler          = "lambda_remediation.handler"
  runtime          = "python3.12"
  timeout          = 60
  memory_size      = 128

  environment {
    variables = {
      EC2_INSTANCE_ID    = ""                          # populated post-deploy
      ASG_NAME           = "${var.prefix}-asg"
      SNS_TOPIC_ARN      = aws_sns_topic.alerts.arn
      SCALE_OUT_ENABLED  = "true"
      AWS_REGION_OVERRIDE = var.aws_region
    }
  }

  tags = { Function = "auto-remediation" }
}

# ---------------------------------------------------------------------------
# CloudWatch Log Group for Lambda
# ---------------------------------------------------------------------------
resource "aws_cloudwatch_log_group" "lambda" {
  name              = "/aws/lambda/${aws_lambda_function.remediation.function_name}"
  retention_in_days = 7
}

# ---------------------------------------------------------------------------
# Permission for EventBridge to invoke Lambda
# ---------------------------------------------------------------------------
resource "aws_lambda_permission" "eventbridge" {
  statement_id  = "AllowEventBridgeInvoke"
  action        = "lambda:InvokeFunction"
  function_name = aws_lambda_function.remediation.function_name
  principal     = "events.amazonaws.com"
  source_arn    = aws_cloudwatch_event_rule.remediation_trigger.arn
}
