import sys
from decimal import Decimal
from pathlib import Path

import boto3
import pytest
from moto import mock_aws

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "src"))

TELEMETRY_TABLE = "test-telemetry"
ANOMALIES_TABLE = "test-anomalies"


@pytest.fixture(autouse=True)
def lambda_env(monkeypatch):
    monkeypatch.setenv("AWS_DEFAULT_REGION", "us-east-1")
    monkeypatch.setenv("AWS_ACCESS_KEY_ID", "testing")
    monkeypatch.setenv("AWS_SECRET_ACCESS_KEY", "testing")
    monkeypatch.setenv("TELEMETRY_TABLE", TELEMETRY_TABLE)
    monkeypatch.setenv("ANOMALIES_TABLE", ANOMALIES_TABLE)
    monkeypatch.setenv("AGGREGATE_WINDOW_MINUTES", "15")
    monkeypatch.setenv("CPU_TEMP_THRESHOLD_C", "75")
    monkeypatch.setenv("CPU_PERCENT_THRESHOLD", "90")
    monkeypatch.setenv("MEMORY_PERCENT_THRESHOLD", "90")


@pytest.fixture
def tables():
    with mock_aws():
        import handler

        handler._dynamodb = None
        dynamodb = boto3.resource("dynamodb", region_name="us-east-1")
        for name in (TELEMETRY_TABLE, ANOMALIES_TABLE):
            dynamodb.create_table(
                TableName=name,
                KeySchema=[
                    {"AttributeName": "device_id", "KeyType": "HASH"},
                    {"AttributeName": "epoch_ms", "KeyType": "RANGE"},
                ],
                AttributeDefinitions=[
                    {"AttributeName": "device_id", "AttributeType": "S"},
                    {"AttributeName": "epoch_ms", "AttributeType": "N"},
                ],
                BillingMode="PAY_PER_REQUEST",
            )
        yield dynamodb
        handler._dynamodb = None


def put_telemetry(dynamodb, device_id: str, epoch_ms: int, **metrics) -> None:
    dynamodb.Table(TELEMETRY_TABLE).put_item(
        Item={
            "device_id": device_id,
            "epoch_ms": epoch_ms,
            "metrics": {k: Decimal(str(v)) for k, v in metrics.items()},
        }
    )
