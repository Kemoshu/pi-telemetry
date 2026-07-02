output "iot_endpoint" {
  description = "MQTT endpoint for the agent config (mqtt.endpoint)."
  value       = data.aws_iot_endpoint.data.endpoint_address
}

output "telemetry_topic" {
  description = "Topic the device publishes to."
  value       = "${var.telemetry_topic_prefix}/${var.device_id}"
}

output "device_certificate_pem" {
  description = "Signed device certificate. Save as device.pem.crt on the Pi."
  value       = aws_iot_certificate.device.certificate_pem
  sensitive   = true
}

output "telemetry_table_name" {
  value = aws_dynamodb_table.telemetry.name
}

output "anomalies_table_name" {
  value = aws_dynamodb_table.anomalies.name
}
