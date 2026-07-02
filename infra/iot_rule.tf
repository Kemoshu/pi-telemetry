# Routing: one topic rule fans each telemetry message out to DynamoDB
# (raw storage) and the processing Lambda. The SQL computes the TTL
# attribute at ingest so raw items expire automatically.

resource "aws_iot_topic_rule" "telemetry" {
  name        = replace("${var.project_name}_telemetry", "-", "_")
  description = "Store telemetry in DynamoDB and invoke the processor Lambda"
  enabled     = true
  sql_version = "2016-03-23"

  sql = <<-SQL
    SELECT *, (timestamp() / 1000) + ${var.ttl_days * 86400} AS expires_at
    FROM '${var.telemetry_topic_prefix}/+'
  SQL

  dynamodbv2 {
    role_arn = aws_iam_role.iot_rule.arn

    put_item {
      table_name = aws_dynamodb_table.telemetry.name
    }
  }

  lambda {
    function_arn = aws_lambda_function.processor.arn
  }

  error_action {
    cloudwatch_logs {
      role_arn       = aws_iam_role.iot_rule.arn
      log_group_name = aws_cloudwatch_log_group.iot_rule_errors.name
    }
  }
}

resource "aws_lambda_permission" "iot_invoke" {
  statement_id  = "AllowIotRuleInvoke"
  action        = "lambda:InvokeFunction"
  function_name = aws_lambda_function.processor.function_name
  principal     = "iot.amazonaws.com"
  source_arn    = aws_iot_topic_rule.telemetry.arn
}
