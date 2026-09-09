import io
import json
import logging
import os

import pytest

from tillflow_shared.mpesa.fake import FakeMpesaAdapter
from tillflow_shared.mpesa.settings import MpesaSettings
from tillflow_shared.mpesa.types import StkPushRequest
from tillflow_shared.otel.bootstrap import setup_telemetry
from tillflow_shared.otel.logging import JsonFormatter


@pytest.fixture(scope="session", autouse=True)
def telemetry():
    """Configure the SDK once per session, with export switched off.

    ``TILLFLOW_TELEMETRY_EXPORT=none`` still creates real, recording spans, so trace
    correlation is genuinely exercised without a collector. CI depends on this.
    """
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


@pytest.fixture
def fake_settings() -> MpesaSettings:
    return MpesaSettings(
        MPESA_ADAPTER="fake",
        MPESA_HTTP_READ_TIMEOUT=0.05,
    )


@pytest.fixture
def fake_adapter(fake_settings: MpesaSettings) -> FakeMpesaAdapter:
    return FakeMpesaAdapter(fake_settings)


@pytest.fixture
def sample_stk_request() -> StkPushRequest:
    return StkPushRequest(
        tenant_id="tenant-1",
        idempotency_key="sale-key-1",
        phone_number="254712345678",
        amount_whole_kes=10,
        account_reference="sale-key-1",
    )
