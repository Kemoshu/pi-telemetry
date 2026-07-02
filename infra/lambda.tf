# Processing Lambda: source-only package, no third-party dependencies
# beyond boto3 which the runtime provides.

data "archive_file" "lambda" {
  type        = "zip"
  source_dir  = "${path.module}/../lambda/src"
  output_path = "${path.module}/lambda_build/processor.zip"
}

resource "aws_lambda_function" "processor" {
  function_name    = "${var.project_name}-processor"
  role             = aws_iam_role.lambda.arn
  runtime          = "python3.13"
  architectures    = ["arm64"]
  handler          = "handler.handler"
  filename         = data.archive_file.lambda.output_path
  source_code_hash = data.archive_file.lambda.output_base64sha256
  memory_size      = var.lambda_memory_mb
  timeout          = var.lambda_timeout_seconds

  environment {
    variables = {
      TELEMETRY_TABLE          = aws_dynamodb_table.telemetry.name
      ANOMALIES_TABLE          = aws_dynamodb_table.anomalies.name
      AGGREGATE_WINDOW_MINUTES = var.aggregate_window_minutes
      CPU_TEMP_THRESHOLD_C     = var.cpu_temp_threshold_c
      CPU_PERCENT_THRESHOLD    = var.cpu_percent_threshold
      MEMORY_PERCENT_THRESHOLD = var.memory_percent_threshold
      METRIC_NAMESPACE         = "PiTelemetry"
    }
  }

  depends_on = [aws_cloudwatch_log_group.lambda]
}
