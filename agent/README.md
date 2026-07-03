# pi-telemetry-agent

Collects Raspberry Pi system metrics (CPU, memory, disk, load, CPU
temperature) and publishes structured JSON to AWS IoT Core over MQTT with
mutual TLS. See the repository root README for the full pipeline.

Quick local check without any AWS setup:

```bash
python -m pi_telemetry_agent --once
```
