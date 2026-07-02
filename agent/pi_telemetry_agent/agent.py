"""Main collect-and-publish loop with graceful shutdown."""

from __future__ import annotations

import logging
import threading

from .collector import collect
from .config import AgentConfig
from .publisher import Publisher

log = logging.getLogger(__name__)


class Agent:
    def __init__(self, config: AgentConfig, publisher: Publisher) -> None:
        self._config = config
        self._publisher = publisher
        self._stop = threading.Event()

    def run_once(self) -> dict:
        payload = collect(self._config.device_id)
        self._publisher.publish(payload)
        return payload

    def run(self) -> None:
        log.info(
            "agent started: device_id=%s interval=%.0fs publisher=%s",
            self._config.device_id,
            self._config.interval_seconds,
            self._config.publisher,
        )
        while not self._stop.is_set():
            try:
                self.run_once()
            except Exception:
                log.exception("collect/publish cycle failed, will retry next interval")
            self._stop.wait(self._config.interval_seconds)
        self._publisher.close()
        log.info("agent stopped")

    def stop(self) -> None:
        self._stop.set()
