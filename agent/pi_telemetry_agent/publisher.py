"""Payload publishers: stdout for local runs, MQTT over TLS for AWS IoT Core."""

from __future__ import annotations

import json
import logging
import random
import ssl
import time
from typing import Protocol

from .config import MqttConfig

log = logging.getLogger(__name__)


class Publisher(Protocol):
    def publish(self, payload: dict) -> None: ...

    def close(self) -> None: ...


class StdoutPublisher:
    """Print payloads as JSON lines, useful for local verification."""

    def publish(self, payload: dict) -> None:
        print(json.dumps(payload), flush=True)

    def close(self) -> None:
        pass


class MqttPublisher:
    """Publish payloads to AWS IoT Core over MQTT with mutual TLS.

    Initial connection retries forever with capped exponential backoff and
    jitter. After the first connect, paho's network loop handles reconnects.
    """

    def __init__(
        self,
        config: MqttConfig,
        initial_backoff_seconds: float = 1.0,
        max_backoff_seconds: float = 60.0,
        publish_timeout_seconds: float = 10.0,
        client=None,
        sleep=time.sleep,
    ) -> None:
        self._config = config
        self._initial_backoff = initial_backoff_seconds
        self._max_backoff = max_backoff_seconds
        self._publish_timeout = publish_timeout_seconds
        self._sleep = sleep
        self._client = client if client is not None else self._build_client()

    def _build_client(self):
        import paho.mqtt.client as mqtt

        client = mqtt.Client(
            callback_api_version=mqtt.CallbackAPIVersion.VERSION2,
            client_id=self._config.client_id,
            protocol=mqtt.MQTTv5,
        )
        client.tls_set(
            ca_certs=self._config.ca_cert,
            certfile=self._config.device_cert,
            keyfile=self._config.private_key,
            tls_version=ssl.PROTOCOL_TLS_CLIENT,
        )
        client.reconnect_delay_set(min_delay=1, max_delay=int(self._max_backoff))
        client.on_connect = self._on_connect
        client.on_disconnect = self._on_disconnect
        return client

    def _on_connect(self, client, userdata, flags, reason_code, properties=None) -> None:
        log.info("connected to %s:%s (%s)", self._config.endpoint, self._config.port, reason_code)

    def _on_disconnect(self, client, userdata, flags, reason_code, properties=None) -> None:
        log.warning("disconnected (%s), paho will reconnect", reason_code)

    def connect(self) -> None:
        backoff = self._initial_backoff
        while True:
            try:
                self._client.connect(self._config.endpoint, self._config.port, keepalive=60)
                self._client.loop_start()
                return
            except (OSError, ssl.SSLError) as exc:
                delay = backoff + random.uniform(0, backoff * 0.25)
                log.warning("connect failed (%s), retrying in %.1fs", exc, delay)
                self._sleep(delay)
                backoff = min(backoff * 2, self._max_backoff)

    def publish(self, payload: dict) -> None:
        info = self._client.publish(self._config.topic, json.dumps(payload), qos=1)
        info.wait_for_publish(timeout=self._publish_timeout)
        if not info.is_published():
            raise TimeoutError(
                f"publish to {self._config.topic} not acknowledged "
                f"within {self._publish_timeout}s"
            )

    def close(self) -> None:
        self._client.loop_stop()
        self._client.disconnect()


def build_publisher(kind: str, mqtt_config: MqttConfig) -> Publisher:
    if kind == "stdout":
        return StdoutPublisher()
    if kind == "mqtt":
        publisher = MqttPublisher(mqtt_config)
        publisher.connect()
        return publisher
    raise ValueError(f"unknown publisher: {kind!r}")
