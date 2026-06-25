data "archive_file" "lambda_zip" {
  type        = "zip"
  source_file = "${path.root}/../remediation/lambda_remediation.py"
  output_path = "${path.root}/.build/lambda_remediation.zip"
}

resource "aws_lambda_function" "remediation" {
  function_name    = "${var.prefix}-auto-remediation"
  description      = "TechStream automated remediation triggered by CloudWatch Alarms"
  filename         = data.archive_file.lambda_zip.output_path
  source_code_hash = data.archive_file.lambda_zip.output_base64sha256
  role             = var.lambda_role_arn
  handler          = "lambda_remediation.handler"
  runtime          = "python3.12"
  timeout          = 60
  memory_size      = 128

  environment {
    variables = {
      ASG_NAME          = var.asg_name
      SNS_TOPIC_ARN     = var.sns_topic_arn
      SCALE_OUT_ENABLED = "true"
      AWS_REGION        = var.aws_region
    }
  }
  tags = { Function = "auto-remediation" }
}

resource "aws_cloudwatch_log_group" "lambda" {
  name              = "/aws/lambda/${aws_lambda_function.remediation.function_name}"
  retention_in_days = 7
}
