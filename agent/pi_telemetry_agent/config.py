"""Agent configuration from YAML file with environment variable overrides.

Precedence: environment variables > YAML file > defaults.
Environment variables use the PI_TELEMETRY_ prefix, for example
PI_TELEMETRY_MQTT_ENDPOINT overrides mqtt.endpoint.
"""

from __future__ import annotations

import os
import socket
from dataclasses import dataclass, field
from pathlib import Path

import yaml

ENV_PREFIX = "PI_TELEMETRY_"
VALID_PUBLISHERS = ("stdout", "mqtt")


class ConfigError(ValueError):
    """Raised when configuration is missing or invalid."""


@dataclass
class MqttConfig:
    endpoint: str = ""
    port: int = 8883
    topic: str = ""
    ca_cert: str = ""
    device_cert: str = ""
    private_key: str = ""
    client_id: str = ""


@dataclass
class AgentConfig:
    device_id: str = field(default_factory=socket.gethostname)
    interval_seconds: float = 60.0
    publisher: str = "stdout"
    mqtt: MqttConfig = field(default_factory=MqttConfig)

    def __post_init__(self) -> None:
        if not self.mqtt.topic:
            self.mqtt.topic = f"telemetry/{self.device_id}"
        if not self.mqtt.client_id:
            self.mqtt.client_id = self.device_id

    def validate(self) -> None:
        if self.interval_seconds <= 0:
            raise ConfigError("interval_seconds must be positive")
        if not self.device_id:
            raise ConfigError("device_id must not be empty")
        if self.publisher not in VALID_PUBLISHERS:
            raise ConfigError(f"publisher must be one of {VALID_PUBLISHERS}, got {self.publisher!r}")
        if self.publisher == "mqtt":
            missing = [
                name
                for name, value in (
                    ("mqtt.endpoint", self.mqtt.endpoint),
                    ("mqtt.ca_cert", self.mqtt.ca_cert),
                    ("mqtt.device_cert", self.mqtt.device_cert),
                    ("mqtt.private_key", self.mqtt.private_key),
                )
                if not value
            ]
            if missing:
                raise ConfigError(f"mqtt publisher requires: {', '.join(missing)}")
            for name, path in (
                ("mqtt.ca_cert", self.mqtt.ca_cert),
                ("mqtt.device_cert", self.mqtt.device_cert),
                ("mqtt.private_key", self.mqtt.private_key),
            ):
                if not Path(path).is_file():
                    raise ConfigError(f"{name} file not found: {path}")


def _env(name: str) -> str | None:
    return os.environ.get(ENV_PREFIX + name)


def load_config(path: str | Path | None = None) -> AgentConfig:
    """Build an AgentConfig from an optional YAML file plus env overrides."""
    data: dict = {}
    if path:
        raw = yaml.safe_load(Path(path).read_text())
        if raw is not None:
            if not isinstance(raw, dict):
                raise ConfigError(f"config file must contain a mapping: {path}")
            data = raw

    mqtt_data = data.get("mqtt") or {}
    if not isinstance(mqtt_data, dict):
        raise ConfigError("mqtt section must be a mapping")

    def pick(env_name: str, file_value, default):
        env_value = _env(env_name)
        if env_value is not None:
            return env_value
        if file_value is not None:
            return file_value
        return default

    mqtt = MqttConfig(
        endpoint=str(pick("MQTT_ENDPOINT", mqtt_data.get("endpoint"), "")),
        port=int(pick("MQTT_PORT", mqtt_data.get("port"), 8883)),
        topic=str(pick("MQTT_TOPIC", mqtt_data.get("topic"), "")),
        ca_cert=str(pick("MQTT_CA_CERT", mqtt_data.get("ca_cert"), "")),
        device_cert=str(pick("MQTT_DEVICE_CERT", mqtt_data.get("device_cert"), "")),
        private_key=str(pick("MQTT_PRIVATE_KEY", mqtt_data.get("private_key"), "")),
        client_id=str(pick("MQTT_CLIENT_ID", mqtt_data.get("client_id"), "")),
    )
    config = AgentConfig(
        device_id=str(pick("DEVICE_ID", data.get("device_id"), socket.gethostname())),
        interval_seconds=float(pick("INTERVAL_SECONDS", data.get("interval_seconds"), 60.0)),
        publisher=str(pick("PUBLISHER", data.get("publisher"), "stdout")),
        mqtt=mqtt,
    )
    return config
