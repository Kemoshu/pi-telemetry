import socket

import pytest

from pi_telemetry_agent.config import AgentConfig, ConfigError, MqttConfig, load_config


class TestDefaults:
    def test_defaults(self):
        config = load_config(None)
        assert config.device_id == socket.gethostname()
        assert config.interval_seconds == 60.0
        assert config.publisher == "stdout"
        assert config.mqtt.port == 8883
        config.validate()

    def test_topic_and_client_id_derive_from_device_id(self):
        config = AgentConfig(device_id="pi-x")
        assert config.mqtt.topic == "telemetry/pi-x"
        assert config.mqtt.client_id == "pi-x"


class TestYamlLoading:
    def test_loads_values(self, tmp_path):
        path = tmp_path / "config.yaml"
        path.write_text(
            """
device_id: pi-test
interval_seconds: 15
publisher: mqtt
mqtt:
  endpoint: example-ats.iot.us-east-1.amazonaws.com
  port: 443
  topic: custom/topic
  ca_cert: /tmp/ca.pem
  device_cert: /tmp/cert.pem
  private_key: /tmp/key.pem
"""
        )
        config = load_config(path)
        assert config.device_id == "pi-test"
        assert config.interval_seconds == 15.0
        assert config.publisher == "mqtt"
        assert config.mqtt.endpoint == "example-ats.iot.us-east-1.amazonaws.com"
        assert config.mqtt.port == 443
        assert config.mqtt.topic == "custom/topic"

    def test_empty_file_gives_defaults(self, tmp_path):
        path = tmp_path / "config.yaml"
        path.write_text("")
        config = load_config(path)
        assert config.publisher == "stdout"

    def test_non_mapping_file_rejected(self, tmp_path):
        path = tmp_path / "config.yaml"
        path.write_text("- just\n- a list\n")
        with pytest.raises(ConfigError):
            load_config(path)


class TestEnvOverrides:
    def test_env_wins_over_file(self, tmp_path, monkeypatch):
        path = tmp_path / "config.yaml"
        path.write_text("device_id: from-file\ninterval_seconds: 30\n")
        monkeypatch.setenv("PI_TELEMETRY_DEVICE_ID", "from-env")
        monkeypatch.setenv("PI_TELEMETRY_INTERVAL_SECONDS", "5")
        monkeypatch.setenv("PI_TELEMETRY_MQTT_ENDPOINT", "env-ats.iot.us-east-1.amazonaws.com")
        config = load_config(path)
        assert config.device_id == "from-env"
        assert config.interval_seconds == 5.0
        assert config.mqtt.endpoint == "env-ats.iot.us-east-1.amazonaws.com"


class TestValidation:
    def test_rejects_non_positive_interval(self):
        config = AgentConfig(interval_seconds=0)
        with pytest.raises(ConfigError, match="interval_seconds"):
            config.validate()

    def test_rejects_unknown_publisher(self):
        config = AgentConfig(publisher="carrier-pigeon")
        with pytest.raises(ConfigError, match="publisher"):
            config.validate()

    def test_mqtt_requires_endpoint_and_certs(self):
        config = AgentConfig(publisher="mqtt")
        with pytest.raises(ConfigError, match="mqtt.endpoint"):
            config.validate()

    def test_mqtt_requires_cert_files_to_exist(self, tmp_path):
        ca = tmp_path / "ca.pem"
        ca.write_text("x")
        config = AgentConfig(
            publisher="mqtt",
            mqtt=MqttConfig(
                endpoint="example-ats.iot.us-east-1.amazonaws.com",
                ca_cert=str(ca),
                device_cert=str(tmp_path / "missing.crt"),
                private_key=str(ca),
            ),
        )
        with pytest.raises(ConfigError, match="device_cert"):
            config.validate()
