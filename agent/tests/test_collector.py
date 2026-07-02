"""Collector tests: fake thermal zones plus real-hardware checks on a Pi."""

from datetime import datetime, timezone
from pathlib import Path

import pytest

from pi_telemetry_agent import collector
from pi_telemetry_agent.collector import SCHEMA_VERSION, collect, read_cpu_temp_c

ON_PI = Path("/sys/class/thermal/thermal_zone0/temp").exists()


def make_zone(root: Path, index: int, zone_type: str, millidegrees: str) -> None:
    zone = root / f"thermal_zone{index}"
    zone.mkdir(parents=True)
    (zone / "type").write_text(zone_type + "\n")
    (zone / "temp").write_text(millidegrees + "\n")


class TestReadCpuTemp:
    def test_prefers_cpu_zone(self, tmp_path):
        make_zone(tmp_path, 0, "gpu-thermal", "70000")
        make_zone(tmp_path, 1, "cpu-thermal", "48200")
        assert read_cpu_temp_c(tmp_path) == 48.2

    def test_falls_back_to_first_zone_without_cpu_type(self, tmp_path):
        make_zone(tmp_path, 0, "soc-thermal", "51000")
        assert read_cpu_temp_c(tmp_path) == 51.0

    def test_rejects_implausible_reading(self, tmp_path, monkeypatch):
        make_zone(tmp_path, 0, "cpu-thermal", "250000")
        monkeypatch.setattr(collector, "_psutil_temp_fallback", lambda: None)
        assert read_cpu_temp_c(tmp_path) is None

    def test_skips_corrupt_zone(self, tmp_path):
        make_zone(tmp_path, 0, "cpu-thermal", "not-a-number")
        make_zone(tmp_path, 1, "cpu-thermal", "44000")
        assert read_cpu_temp_c(tmp_path) == 44.0

    def test_no_zones_uses_psutil_fallback(self, tmp_path, monkeypatch):
        monkeypatch.setattr(collector, "_psutil_temp_fallback", lambda: 42.5)
        assert read_cpu_temp_c(tmp_path) == 42.5


class TestCollect:
    def test_payload_shape(self):
        payload = collect("test-device")
        assert payload["schema_version"] == SCHEMA_VERSION
        assert payload["device_id"] == "test-device"
        metrics = payload["metrics"]
        for key in (
            "cpu_percent",
            "load_1m",
            "load_5m",
            "load_15m",
            "memory_percent",
            "memory_used_mb",
            "memory_total_mb",
            "disk_percent",
            "disk_free_gb",
            "uptime_seconds",
        ):
            assert key in metrics, f"missing metric {key}"
        assert 0 <= metrics["cpu_percent"] <= 100
        assert 0 <= metrics["memory_percent"] <= 100
        assert 0 <= metrics["disk_percent"] <= 100
        assert metrics["memory_used_mb"] < metrics["memory_total_mb"]
        assert metrics["uptime_seconds"] > 0

    def test_timestamp_is_utc_and_consistent_with_epoch(self):
        payload = collect("test-device")
        parsed = datetime.strptime(payload["timestamp"], "%Y-%m-%dT%H:%M:%SZ").replace(
            tzinfo=timezone.utc
        )
        assert abs(parsed.timestamp() - payload["epoch_ms"] / 1000) < 1.5
        assert abs(parsed.timestamp() - datetime.now(timezone.utc).timestamp()) < 5

    def test_missing_thermal_omits_temp(self, tmp_path, monkeypatch):
        monkeypatch.setattr(collector, "_psutil_temp_fallback", lambda: None)
        payload = collect("test-device", thermal_root=tmp_path)
        assert "cpu_temp_c" not in payload["metrics"]


@pytest.mark.skipif(not ON_PI, reason="requires real thermal zone hardware")
class TestOnRealPi:
    def test_reads_real_cpu_temperature(self):
        temp = read_cpu_temp_c()
        assert temp is not None
        assert 10.0 <= temp <= 110.0

    def test_real_payload_includes_temp(self):
        payload = collect("real-pi")
        assert "cpu_temp_c" in payload["metrics"]
