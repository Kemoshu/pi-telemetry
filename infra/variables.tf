variable "project_name" {
  description = "Name prefix for all resources."
  type        = string
  default     = "pi-telemetry"
}

variable "aws_region" {
  description = "AWS region to deploy into."
  type        = string
  default     = "us-east-1"
}

variable "device_id" {
  description = "Device id of the Pi. Used as IoT thing name, MQTT client id, and DynamoDB partition key."
  type        = string
}

variable "device_csr_path" {
  description = "Path to the certificate signing request generated on the Pi. The private key never leaves the device."
  type        = string
}

variable "telemetry_topic_prefix" {
  description = "MQTT topic prefix. The device publishes to <prefix>/<device_id>."
  type        = string
  default     = "telemetry"
}

variable "ttl_days" {
  description = "Days to keep raw telemetry items before DynamoDB TTL expires them."
  type        = number
  default     = 14

  validation {
    condition     = var.ttl_days >= 1
    error_message = "ttl_days must be at least 1."
  }
}

variable "lambda_memory_mb" {
  description = "Memory for the processing Lambda."
  type        = number
  default     = 128
}

variable "lambda_timeout_seconds" {
  description = "Timeout for the processing Lambda."
  type        = number
  default     = 15
}

variable "log_retention_days" {
  description = "CloudWatch log retention for Lambda and IoT rule error logs."
  type        = number
  default     = 14
}

variable "aggregate_window_minutes" {
  description = "Rolling window the Lambda queries when computing aggregates."
  type        = number
  default     = 15
}

variable "cpu_temp_threshold_c" {
  description = "CPU temperature in Celsius above which a record is flagged as an anomaly."
  type        = number
  default     = 75
}

variable "cpu_percent_threshold" {
  description = "CPU utilization percent above which a record is flagged as an anomaly."
  type        = number
  default     = 90
}

variable "memory_percent_threshold" {
  description = "Memory utilization percent above which a record is flagged as an anomaly."
  type        = number
  default     = 90
}

variable "enable_temp_alarm" {
  description = "Create a CloudWatch alarm on the anomaly metric. Free tier covers 10 alarms, then USD 0.10 per alarm per month."
  type        = bool
  default     = false
}

variable "alarm_email" {
  description = "Email for the SNS subscription behind the temperature alarm. Only used when enable_temp_alarm is true."
  type        = string
  default     = ""
}
