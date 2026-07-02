"""Telemetry processor invoked by the AWS IoT rule for each message.

Validates the payload, computes rolling aggregates over the recent window
from the telemetry table, and flags anomalies. Anomalies are written to a
separate DynamoDB table and emitted as a CloudWatch metric using embedded
metric format, which needs no PutMetricData permission or API cost.
"""

from __future__ import annotations

import json
import logging
import os
import time
from decimal import Decimal

import boto3
from boto3.dynamodb.conditions import Key

logger = logging.getLogger()
logger.setLevel(logging.INFO)

REQUIRED_FIELDS = ("device_id", "epoch_ms", "timestamp", "metrics")
METRIC_RANGES = {
    "cpu_percent": (0, 100),
    "memory_percent": (0, 100),
    "disk_percent": (0, 100),
    "cpu_temp_c": (-20, 130),
}
AGGREGATE_KEYS = ("cpu_percent", "memory_percent", "cpu_temp_c")

_dynamodb = None


def _table(name: str):
    global _dynamodb
    if _dynamodb is None:
        _dynamodb = boto3.resource("dynamodb")
    return _dynamodb.Table(name)


class ValidationError(ValueError):
    pass


def validate(event: dict) -> None:
    missing = [f for f in REQUIRED_FIELDS if f not in event]
    if missing:
        raise ValidationError(f"missing fields: {missing}")
    if not isinstance(event["device_id"], str) or not event["device_id"]:
        raise ValidationError("device_id must be a non-empty string")
    if not isinstance(event["epoch_ms"], (int, Decimal)) or event["epoch_ms"] <= 0:
        raise ValidationError("epoch_ms must be a positive number")
    metrics = event["metrics"]
    if not isinstance(metrics, dict):
        raise ValidationError("metrics must be an object")
    for key, (low, high) in METRIC_RANGES.items():
        value = metrics.get(key)
        if value is not None and not low <= float(value) <= high:
            raise ValidationError(f"{key}={value} outside [{low}, {high}]")


def rolling_aggregates(device_id: str, epoch_ms: int, window_minutes: int) -> dict:
    """Average the recent window of readings from the telemetry table."""
    table = _table(os.environ["TELEMETRY_TABLE"])
    window_start = epoch_ms - window_minutes * 60_000
    response = table.query(
        KeyConditionExpression=(
            Key("device_id").eq(device_id) & Key("epoch_ms").between(window_start, epoch_ms)
        ),
        ScanIndexForward=False,
        Limit=500,
    )
    items = response.get("Items", [])
    aggregates: dict = {"sample_count": len(items)}
    for key in AGGREGATE_KEYS:
        values = [float(item["metrics"][key]) for item in items if key in item.get("metrics", {})]
        if values:
            aggregates[f"avg_{key}"] = round(sum(values) / len(values), 2)
            aggregates[f"max_{key}"] = round(max(values), 2)
    return aggregates


def detect_anomalies(metrics: dict) -> list[dict]:
    thresholds = {
        "cpu_temp_c": float(os.environ.get("CPU_TEMP_THRESHOLD_C", 75)),
        "cpu_percent": float(os.environ.get("CPU_PERCENT_THRESHOLD", 90)),
        "memory_percent": float(os.environ.get("MEMORY_PERCENT_THRESHOLD", 90)),
    }
    anomalies = []
    for key, threshold in thresholds.items():
        value = metrics.get(key)
        if value is not None and float(value) > threshold:
            anomalies.append({"metric": key, "value": float(value), "threshold": threshold})
    return anomalies


def emit_anomaly_metric(device_id: str, count: int) -> None:
    """CloudWatch embedded metric format: a metric via a structured log line."""
    print(
        json.dumps(
            {
                "_aws": {
                    "Timestamp": int(time.time() * 1000),
                    "CloudWatchMetrics": [
                        {
                            "Namespace": os.environ.get("METRIC_NAMESPACE", "PiTelemetry"),
                            "Dimensions": [["DeviceId"]],
                            "Metrics": [{"Name": "AnomalyCount", "Unit": "Count"}],
                        }
                    ],
                },
                "DeviceId": device_id,
                "AnomalyCount": count,
            }
        )
    )


def _to_dynamo(value):
    if isinstance(value, float):
        return Decimal(str(value))
    if isinstance(value, dict):
        return {k: _to_dynamo(v) for k, v in value.items()}
    if isinstance(value, list):
        return [_to_dynamo(v) for v in value]
    return value


def handler(event: dict, context=None) -> dict:
    try:
        validate(event)
    except ValidationError as exc:
        logger.warning("dropping invalid payload: %s", exc)
        return {"status": "invalid", "reason": str(exc)}

    device_id = event["device_id"]
    epoch_ms = int(event["epoch_ms"])
    metrics = event["metrics"]

    window_minutes = int(os.environ.get("AGGREGATE_WINDOW_MINUTES", 15))
    aggregates = rolling_aggregates(device_id, epoch_ms, window_minutes)
    anomalies = detect_anomalies(metrics)
    emit_anomaly_metric(device_id, len(anomalies))

    if anomalies:
        ttl_days = int(os.environ.get("ANOMALY_TTL_DAYS", 90))
        record = {
            "device_id": device_id,
            "epoch_ms": epoch_ms,
            "timestamp": event["timestamp"],
            "anomalies": anomalies,
            "metrics": metrics,
            "aggregates": aggregates,
            "expires_at": epoch_ms // 1000 + ttl_days * 86_400,
        }
        _table(os.environ["ANOMALIES_TABLE"]).put_item(Item=_to_dynamo(record))
        logger.info("anomaly for %s at %s: %s", device_id, event["timestamp"], anomalies)

    return {
        "status": "ok",
        "device_id": device_id,
        "anomaly_count": len(anomalies),
        "aggregates": aggregates,
    }
