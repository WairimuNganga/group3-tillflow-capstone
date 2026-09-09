import io
import json
import logging

import pytest

from tillflow_shared.logging import JsonFormatter
from tillflow_shared.telemetry import setup_telemetry


@pytest.fixture(scope="session", autouse=True)
def telemetry():
    """Configure the SDK once per test session, with export switched off.

    ``TILLFLOW_TELEMETRY_EXPORT=none`` still creates real, recording spans — so trace
    correlation is genuinely exercised — without needing a collector. CI depends on
    this: the unit suite must not require Docker.
    """
    import os

    os.environ["TILLFLOW_TELEMETRY_EXPORT"] = "none"
    os.environ.setdefault("TILLFLOW_PII_HASH_SALT", "test-salt-not-a-real-secret")
    setup_telemetry("payments")


@pytest.fixture
def captured_logs():
    """A logger writing JSON into a buffer, plus a reader that parses the lines."""
    stream = io.StringIO()
    handler = logging.StreamHandler(stream)
    handler.setFormatter(JsonFormatter("payments"))

    logger = logging.getLogger("tests.captured")
    logger.handlers = [handler]
    logger.propagate = False
    logger.setLevel(logging.DEBUG)

    def lines() -> list[dict]:
        handler.flush()
        return [json.loads(line) for line in stream.getvalue().splitlines() if line]

    yield logger, lines

    logger.handlers = []
