import json

import pytest

from pi_telemetry_agent.config import MqttConfig
from pi_telemetry_agent.publisher import MqttPublisher, StdoutPublisher, build_publisher


class FakePublishInfo:
    def __init__(self, published: bool = True):
        self._published = published
        self.wait_timeout = None

    def wait_for_publish(self, timeout=None):
        self.wait_timeout = timeout

    def is_published(self):
        return self._published


class FakeClient:
    def __init__(self, connect_failures: int = 0, publish_ok: bool = True):
        self.connect_failures = connect_failures
        self.publish_ok = publish_ok
        self.connect_calls = 0
        self.published = []
        self.loop_started = False
        self.loop_stopped = False
        self.disconnected = False

    def connect(self, host, port, keepalive=60):
        self.connect_calls += 1
        if self.connect_calls <= self.connect_failures:
            raise OSError("connection refused")

    def loop_start(self):
        self.loop_started = True

    def loop_stop(self):
        self.loop_stopped = True

    def disconnect(self):
        self.disconnected = True

    def publish(self, topic, payload, qos=0):
        self.published.append((topic, payload, qos))
        return FakePublishInfo(self.publish_ok)


MQTT_CONFIG = MqttConfig(
    endpoint="example-ats.iot.us-east-1.amazonaws.com",
    topic="telemetry/pi-test",
    client_id="pi-test",
)


class TestStdoutPublisher:
    def test_prints_json_line(self, capsys):
        StdoutPublisher().publish({"device_id": "x", "metrics": {"cpu_percent": 1.0}})
        out = capsys.readouterr().out
        assert json.loads(out) == {"device_id": "x", "metrics": {"cpu_percent": 1.0}}


class TestMqttPublisher:
    def test_connect_retries_with_exponential_backoff(self):
        client = FakeClient(connect_failures=3)
        sleeps = []
        publisher = MqttPublisher(
            MQTT_CONFIG,
            initial_backoff_seconds=1.0,
            max_backoff_seconds=60.0,
            client=client,
            sleep=sleeps.append,
        )
        publisher.connect()
        assert client.connect_calls == 4
        assert client.loop_started
        assert len(sleeps) == 3
        # Backoff doubles each retry: base 1, 2, 4 plus up to 25% jitter.
        for base, actual in zip([1.0, 2.0, 4.0], sleeps):
            assert base <= actual <= base * 1.25

    def test_backoff_is_capped(self):
        client = FakeClient(connect_failures=6)
        sleeps = []
        publisher = MqttPublisher(
            MQTT_CONFIG,
            initial_backoff_seconds=1.0,
            max_backoff_seconds=4.0,
            client=client,
            sleep=sleeps.append,
        )
        publisher.connect()
        assert max(sleeps) <= 4.0 * 1.25

    def test_publish_sends_json_at_qos_1(self):
        client = FakeClient()
        publisher = MqttPublisher(MQTT_CONFIG, client=client)
        publisher.publish({"device_id": "pi-test", "epoch_ms": 123})
        topic, payload, qos = client.published[0]
        assert topic == "telemetry/pi-test"
        assert qos == 1
        assert json.loads(payload) == {"device_id": "pi-test", "epoch_ms": 123}

    def test_publish_timeout_raises(self):
        client = FakeClient(publish_ok=False)
        publisher = MqttPublisher(MQTT_CONFIG, client=client)
        with pytest.raises(TimeoutError):
            publisher.publish({"device_id": "pi-test"})

    def test_close_stops_loop_and_disconnects(self):
        client = FakeClient()
        publisher = MqttPublisher(MQTT_CONFIG, client=client)
        publisher.close()
        assert client.loop_stopped
        assert client.disconnected


class TestBuildPublisher:
    def test_stdout(self):
        assert isinstance(build_publisher("stdout", MQTT_CONFIG), StdoutPublisher)

    def test_unknown_kind_raises(self):
        with pytest.raises(ValueError, match="carrier-pigeon"):
            build_publisher("carrier-pigeon", MQTT_CONFIG)
