import json


from conftest import ANOMALIES_TABLE, put_telemetry


def make_event(device_id="pi-test", epoch_ms=1_700_000_600_000, **metrics) -> dict:
    base_metrics = {
        "cpu_percent": 20.0,
        "memory_percent": 30.0,
        "disk_percent": 40.0,
        "cpu_temp_c": 50.0,
    }
    base_metrics.update(metrics)
    return {
        "schema_version": 1,
        "device_id": device_id,
        "epoch_ms": epoch_ms,
        "timestamp": "2023-11-14T22:23:20Z",
        "metrics": base_metrics,
    }


class TestValidation:
    def test_missing_fields_rejected(self, tables):
        import handler

        result = handler.handler({"device_id": "pi-test"})
        assert result["status"] == "invalid"
        assert "missing fields" in result["reason"]

    def test_out_of_range_metric_rejected(self, tables):
        import handler

        result = handler.handler(make_event(cpu_percent=250.0))
        assert result["status"] == "invalid"
        assert "cpu_percent" in result["reason"]

    def test_empty_device_id_rejected(self, tables):
        import handler

        result = handler.handler(make_event(device_id=""))
        assert result["status"] == "invalid"

    def test_invalid_payload_writes_nothing(self, tables):
        import handler

        handler.handler({"device_id": "pi-test"})
        scan = tables.Table(ANOMALIES_TABLE).scan()
        assert scan["Count"] == 0


class TestAggregates:
    def test_rolling_window_averages(self, tables):
        import handler

        now = 1_700_000_600_000
        # Three readings inside the 15 minute window, one outside it.
        put_telemetry(tables, "pi-test", now - 60_000, cpu_temp_c=50.0, cpu_percent=10.0)
        put_telemetry(tables, "pi-test", now - 120_000, cpu_temp_c=60.0, cpu_percent=20.0)
        put_telemetry(tables, "pi-test", now - 180_000, cpu_temp_c=70.0, cpu_percent=30.0)
        put_telemetry(tables, "pi-test", now - 60 * 60_000, cpu_temp_c=99.0, cpu_percent=99.0)

        result = handler.handler(make_event(epoch_ms=now))
        aggregates = result["aggregates"]
        assert aggregates["sample_count"] == 3
        assert aggregates["avg_cpu_temp_c"] == 60.0
        assert aggregates["max_cpu_temp_c"] == 70.0
        assert aggregates["avg_cpu_percent"] == 20.0

    def test_other_devices_excluded(self, tables):
        import handler

        now = 1_700_000_600_000
        put_telemetry(tables, "other-pi", now - 60_000, cpu_temp_c=99.0)
        result = handler.handler(make_event(epoch_ms=now))
        assert result["aggregates"]["sample_count"] == 0

    def test_empty_window(self, tables):
        import handler

        result = handler.handler(make_event())
        assert result["aggregates"] == {"sample_count": 0}


class TestAnomalies:
    def test_normal_reading_flags_nothing(self, tables):
        import handler

        result = handler.handler(make_event())
        assert result["status"] == "ok"
        assert result["anomaly_count"] == 0
        assert tables.Table(ANOMALIES_TABLE).scan()["Count"] == 0

    def test_high_temperature_flagged_and_stored(self, tables):
        import handler

        result = handler.handler(make_event(cpu_temp_c=82.5))
        assert result["anomaly_count"] == 1

        items = tables.Table(ANOMALIES_TABLE).scan()["Items"]
        assert len(items) == 1
        item = items[0]
        assert item["device_id"] == "pi-test"
        anomaly = item["anomalies"][0]
        assert anomaly["metric"] == "cpu_temp_c"
        assert float(anomaly["value"]) == 82.5
        assert float(anomaly["threshold"]) == 75.0
        assert "expires_at" in item
        assert "aggregates" in item

    def test_multiple_anomalies_in_one_reading(self, tables):
        import handler

        result = handler.handler(make_event(cpu_temp_c=90.0, cpu_percent=95.0, memory_percent=99.0))
        assert result["anomaly_count"] == 3

    def test_anomaly_ttl_uses_configured_days(self, tables, monkeypatch):
        import handler

        monkeypatch.setenv("ANOMALY_TTL_DAYS", "1")
        epoch_ms = 1_700_000_600_000
        handler.handler(make_event(epoch_ms=epoch_ms, cpu_temp_c=90.0))
        item = tables.Table(ANOMALIES_TABLE).scan()["Items"][0]
        assert int(item["expires_at"]) == epoch_ms // 1000 + 86_400


class TestMetricEmission:
    def test_emf_line_written(self, tables, capsys):
        import handler

        handler.handler(make_event(cpu_temp_c=90.0))
        emf_lines = [
            json.loads(line)
            for line in capsys.readouterr().out.splitlines()
            if line.startswith("{") and "_aws" in line
        ]
        assert len(emf_lines) == 1
        emf = emf_lines[0]
        assert emf["AnomalyCount"] == 1
        assert emf["DeviceId"] == "pi-test"
        metric = emf["_aws"]["CloudWatchMetrics"][0]
        assert metric["Namespace"] == "PiTelemetry"
        assert metric["Metrics"][0]["Name"] == "AnomalyCount"

    def test_metric_emitted_even_without_anomaly(self, tables, capsys):
        import handler

        handler.handler(make_event())
        out = capsys.readouterr().out
        assert '"AnomalyCount": 0' in out
