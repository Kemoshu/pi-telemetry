# Telemetry storage.
#
# Key design: device_id (partition) + epoch_ms (sort) gives cheap Query
# access patterns like "latest N readings for a device" and "readings in a
# time range". TTL on expires_at keeps the table small; the IoT rule SQL
# computes expires_at at ingest time.

resource "aws_dynamodb_table" "telemetry" {
  name         = "${var.project_name}-telemetry"
  billing_mode = "PAY_PER_REQUEST"
  hash_key     = "device_id"
  range_key    = "epoch_ms"

  attribute {
    name = "device_id"
    type = "S"
  }

  attribute {
    name = "epoch_ms"
    type = "N"
  }

  ttl {
    attribute_name = "expires_at"
    enabled        = true
  }
}

# Anomalies flagged by the processing Lambda. Kept separate so the hot raw
# table can expire quickly while anomalies stick around longer for review.
resource "aws_dynamodb_table" "anomalies" {
  name         = "${var.project_name}-anomalies"
  billing_mode = "PAY_PER_REQUEST"
  hash_key     = "device_id"
  range_key    = "epoch_ms"

  attribute {
    name = "device_id"
    type = "S"
  }

  attribute {
    name = "epoch_ms"
    type = "N"
  }

  ttl {
    attribute_name = "expires_at"
    enabled        = true
  }
}
