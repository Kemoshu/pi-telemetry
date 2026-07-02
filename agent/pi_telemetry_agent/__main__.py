"""Command line entry point: python -m pi_telemetry_agent."""

from __future__ import annotations

import argparse
import logging
import signal
import sys

from .agent import Agent
from .config import ConfigError, load_config
from .publisher import build_publisher


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        prog="pi-telemetry-agent",
        description="Collect Raspberry Pi system metrics and publish them as JSON.",
    )
    parser.add_argument("--config", help="path to YAML config file")
    parser.add_argument(
        "--publisher", choices=["stdout", "mqtt"], help="override the configured publisher"
    )
    parser.add_argument(
        "--once", action="store_true", help="collect and publish a single payload, then exit"
    )
    parser.add_argument("--verbose", action="store_true", help="enable debug logging")
    args = parser.parse_args(argv)

    logging.basicConfig(
        level=logging.DEBUG if args.verbose else logging.INFO,
        format="%(asctime)s %(levelname)s %(name)s: %(message)s",
        stream=sys.stderr,
    )

    try:
        config = load_config(args.config)
        if args.publisher:
            config.publisher = args.publisher
        config.validate()
        publisher = build_publisher(config.publisher, config.mqtt)
    except (ConfigError, OSError) as exc:
        logging.getLogger(__name__).error("startup failed: %s", exc)
        return 1

    agent = Agent(config, publisher)
    if args.once:
        agent.run_once()
        publisher.close()
        return 0

    for sig in (signal.SIGINT, signal.SIGTERM):
        signal.signal(sig, lambda signum, frame: agent.stop())
    agent.run()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
