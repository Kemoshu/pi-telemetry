from pi_telemetry_agent.agent import Agent
from pi_telemetry_agent.config import AgentConfig


class RecordingPublisher:
    def __init__(self, fail_times: int = 0):
        self.fail_times = fail_times
        self.payloads = []
        self.closed = False

    def publish(self, payload):
        if self.fail_times > 0:
            self.fail_times -= 1
            raise ConnectionError("broker unavailable")
        self.payloads.append(payload)

    def close(self):
        self.closed = True


def test_run_once_collects_and_publishes():
    publisher = RecordingPublisher()
    agent = Agent(AgentConfig(device_id="pi-test"), publisher)
    payload = agent.run_once()
    assert publisher.payloads == [payload]
    assert payload["device_id"] == "pi-test"


def test_run_survives_publish_errors_and_stops_cleanly():
    publisher = RecordingPublisher(fail_times=1)
    config = AgentConfig(device_id="pi-test", interval_seconds=0.01)
    agent = Agent(config, publisher)

    original_publish = publisher.publish

    def publish_then_stop(payload):
        original_publish(payload)
        agent.stop()

    publisher.publish = publish_then_stop
    agent.run()
    # First cycle raised, second succeeded and requested the stop.
    assert len(publisher.payloads) == 1
    assert publisher.closed
