# Least-privilege roles for the IoT rule and the Lambda. Each statement is
# scoped to the specific tables, log groups, and actions it needs.

# --- IoT rule role: PutItem on the telemetry table, write error logs ---

data "aws_iam_policy_document" "iot_rule_assume" {
  statement {
    effect  = "Allow"
    actions = ["sts:AssumeRole"]

    principals {
      type        = "Service"
      identifiers = ["iot.amazonaws.com"]
    }
  }
}

resource "aws_iam_role" "iot_rule" {
  name               = "${var.project_name}-iot-rule"
  assume_role_policy = data.aws_iam_policy_document.iot_rule_assume.json
}

data "aws_iam_policy_document" "iot_rule" {
  statement {
    sid       = "PutTelemetry"
    effect    = "Allow"
    actions   = ["dynamodb:PutItem"]
    resources = [aws_dynamodb_table.telemetry.arn]
  }

  statement {
    sid    = "WriteErrorLogs"
    effect = "Allow"
    actions = [
      "logs:CreateLogStream",
      "logs:PutLogEvents",
      "logs:DescribeLogStreams",
    ]
    resources = ["${aws_cloudwatch_log_group.iot_rule_errors.arn}:*"]
  }
}

resource "aws_iam_role_policy" "iot_rule" {
  name   = "telemetry-write"
  role   = aws_iam_role.iot_rule.id
  policy = data.aws_iam_policy_document.iot_rule.json
}

# --- Lambda role: query telemetry, write anomalies, write its own logs ---

data "aws_iam_policy_document" "lambda_assume" {
  statement {
    effect  = "Allow"
    actions = ["sts:AssumeRole"]

    principals {
      type        = "Service"
      identifiers = ["lambda.amazonaws.com"]
    }
  }
}

resource "aws_iam_role" "lambda" {
  name               = "${var.project_name}-processor"
  assume_role_policy = data.aws_iam_policy_document.lambda_assume.json
}

data "aws_iam_policy_document" "lambda" {
  statement {
    sid       = "QueryTelemetry"
    effect    = "Allow"
    actions   = ["dynamodb:Query"]
    resources = [aws_dynamodb_table.telemetry.arn]
  }

  statement {
    sid       = "PutAnomalies"
    effect    = "Allow"
    actions   = ["dynamodb:PutItem"]
    resources = [aws_dynamodb_table.anomalies.arn]
  }

  statement {
    sid    = "WriteLogs"
    effect = "Allow"
    actions = [
      "logs:CreateLogStream",
      "logs:PutLogEvents",
    ]
    resources = ["${aws_cloudwatch_log_group.lambda.arn}:*"]
  }
}

resource "aws_iam_role_policy" "lambda" {
  name   = "processor"
  role   = aws_iam_role.lambda.id
  policy = data.aws_iam_policy_document.lambda.json
}
