"""Collect system metrics into a structured telemetry payload."""

from __future__ import annotations

import logging
import os
import time
from datetime import datetime, timezone
from pathlib import Path

import psutil

log = logging.getLogger(__name__)

SCHEMA_VERSION = 1
DEFAULT_THERMAL_ROOT = "/sys/class/thermal"

# Plausible bounds for a CPU temperature reading in Celsius. Readings outside
# this range indicate a broken sensor and are discarded.
TEMP_MIN_C = -20.0
TEMP_MAX_C = 130.0


def read_cpu_temp_c(thermal_root: str | Path = DEFAULT_THERMAL_ROOT) -> float | None:
    """Read the CPU temperature from the kernel thermal zone interface.

    Prefers a zone whose type mentions "cpu" (the Pi exposes "cpu-thermal"),
    falling back to the first zone, then to psutil's sensor API. Returns None
    when no usable sensor exists so callers can omit the field.
    """
    zones = sorted(Path(thermal_root).glob("thermal_zone*"))
    candidates = [z for z in zones if "cpu" in _zone_type(z)] or zones
    for zone in candidates:
        try:
            millidegrees = int((zone / "temp").read_text().strip())
        except (OSError, ValueError):
            continue
        temp = millidegrees / 1000.0
        if TEMP_MIN_C <= temp <= TEMP_MAX_C:
            return round(temp, 1)
    return _psutil_temp_fallback()


def _zone_type(zone: Path) -> str:
    try:
        return (zone / "type").read_text().strip().lower()
    except OSError:
        return ""


def _psutil_temp_fallback() -> float | None:
    try:
        sensors = psutil.sensors_temperatures()
    except (AttributeError, OSError):
        return None
    for name in ("cpu_thermal", "cpu-thermal", "coretemp"):
        readings = sensors.get(name)
        if readings:
            return round(readings[0].current, 1)
    return None


def collect(device_id: str, thermal_root: str | Path = DEFAULT_THERMAL_ROOT) -> dict:
    """Return one telemetry payload for the given device."""
    now = datetime.now(timezone.utc)
    memory = psutil.virtual_memory()
    disk = psutil.disk_usage("/")
    load_1m, load_5m, load_15m = os.getloadavg()

    metrics = {
        "cpu_percent": psutil.cpu_percent(interval=None),
        "load_1m": round(load_1m, 2),
        "load_5m": round(load_5m, 2),
        "load_15m": round(load_15m, 2),
        "memory_percent": memory.percent,
        "memory_used_mb": round(memory.used / 2**20, 1),
        "memory_total_mb": round(memory.total / 2**20, 1),
        "disk_percent": disk.percent,
        "disk_free_gb": round(disk.free / 2**30, 2),
        "uptime_seconds": int(time.time() - psutil.boot_time()),
    }
    temp = read_cpu_temp_c(thermal_root)
    if temp is not None:
        metrics["cpu_temp_c"] = temp
    else:
        log.warning("no usable CPU temperature sensor found")

    return {
        "schema_version": SCHEMA_VERSION,
        "device_id": device_id,
        "timestamp": now.strftime("%Y-%m-%dT%H:%M:%SZ"),
        "epoch_ms": int(now.timestamp() * 1000),
        "metrics": metrics,
    }
