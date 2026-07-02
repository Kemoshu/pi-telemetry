# Log groups are created explicitly so retention is bounded and destroy
# removes them. The anomaly metric comes from the Lambda's embedded metric
# format log lines, so no PutMetricData calls are made.

resource "aws_cloudwatch_log_group" "lambda" {
  name              = "/aws/lambda/${var.project_name}-processor"
  retention_in_days = var.log_retention_days
}

resource "aws_cloudwatch_log_group" "iot_rule_errors" {
  name              = "/iot/${var.project_name}/rule-errors"
  retention_in_days = var.log_retention_days
}

# Optional alarm on the anomaly count. Off by default: the metric itself is
# free via EMF, but alarms beyond the free tier bill USD 0.10 per month.

resource "aws_sns_topic" "alerts" {
  count = var.enable_temp_alarm ? 1 : 0
  name  = "${var.project_name}-alerts"
}

resource "aws_sns_topic_subscription" "email" {
  count     = var.enable_temp_alarm && var.alarm_email != "" ? 1 : 0
  topic_arn = aws_sns_topic.alerts[0].arn
  protocol  = "email"
  endpoint  = var.alarm_email
}

resource "aws_cloudwatch_metric_alarm" "anomalies" {
  count               = var.enable_temp_alarm ? 1 : 0
  alarm_name          = "${var.project_name}-anomalies"
  alarm_description   = "Device reported anomalous readings (high temp, CPU, or memory)"
  namespace           = "PiTelemetry"
  metric_name         = "AnomalyCount"
  statistic           = "Sum"
  period              = 300
  evaluation_periods  = 1
  threshold           = 1
  comparison_operator = "GreaterThanOrEqualToThreshold"
  treat_missing_data  = "notBreaching"

  dimensions = {
    DeviceId = var.device_id
  }

  alarm_actions = [aws_sns_topic.alerts[0].arn]
}
