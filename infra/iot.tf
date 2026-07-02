# IoT thing, certificate, and a least-privilege device policy.
#
# The certificate is issued from a CSR generated on the Pi, so the private
# key exists only on the device and never enters Terraform state.

resource "aws_iot_thing" "device" {
  name = var.device_id

  attributes = {
    project = var.project_name
  }
}

resource "aws_iot_certificate" "device" {
  csr    = file(var.device_csr_path)
  active = true
}

resource "aws_iot_thing_principal_attachment" "device" {
  thing     = aws_iot_thing.device.name
  principal = aws_iot_certificate.device.arn
}

# The device may only connect as its own client id and publish to its own
# telemetry topic. No subscribe, no wildcards.
data "aws_iam_policy_document" "device" {
  statement {
    effect    = "Allow"
    actions   = ["iot:Connect"]
    resources = ["arn:aws:iot:${var.aws_region}:${data.aws_caller_identity.current.account_id}:client/${var.device_id}"]
  }

  statement {
    effect    = "Allow"
    actions   = ["iot:Publish"]
    resources = ["arn:aws:iot:${var.aws_region}:${data.aws_caller_identity.current.account_id}:topic/${var.telemetry_topic_prefix}/${var.device_id}"]
  }
}

resource "aws_iot_policy" "device" {
  name   = "${var.project_name}-device"
  policy = data.aws_iam_policy_document.device.json
}

resource "aws_iot_policy_attachment" "device" {
  policy = aws_iot_policy.device.name
  target = aws_iot_certificate.device.arn
}

data "aws_caller_identity" "current" {}

data "aws_iot_endpoint" "data" {
  endpoint_type = "iot:Data-ATS"
}
