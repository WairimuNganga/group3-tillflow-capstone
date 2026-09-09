"""The ADR-008 log-line contract. Every dashboard query depends on these names."""

from opentelemetry import trace

from tillflow_shared.context import request_context
from tillflow_shared.redaction import REDACTED

REQUIRED_FIELDS = ("ts", "level", "service", "msg")


def test_required_fields_are_present(captured_logs):
    logger, lines = captured_logs
    logger.info("sale created")

    (line,) = lines()
    for field in REQUIRED_FIELDS:
        assert field in line
    assert line["service"] == "payments"
    assert line["level"] == "info"
    assert line["msg"] == "sale created"


def test_timestamp_is_utc_rfc3339_with_milliseconds(captured_logs):
    logger, lines = captured_logs
    logger.info("tick")

    ts = lines()[0]["ts"]
    assert ts.endswith("Z")
    assert len(ts) == len("2026-09-09T18:25:03.123Z")


def test_trace_and_span_ids_correlate_with_the_active_span(captured_logs):
    """This is the field that turns five services' logs into one story."""
    logger, lines = captured_logs
    tracer = trace.get_tracer("tests")

    with tracer.start_as_current_span("payments.stk_push") as span:
        logger.info("stk push sent")
        expected = span.get_span_context()

    line = lines()[0]
    assert line["trace_id"] == f"{expected.trace_id:032x}"
    assert line["span_id"] == f"{expected.span_id:016x}"


def test_tenant_id_comes_from_request_context(captured_logs):
    logger, lines = captured_logs

    with request_context(tenant_id="dukawala-42"):
        logger.info("sale created")

    assert lines()[0]["tenant_id"] == "dukawala-42"


def test_tenant_id_is_null_outside_a_request(captured_logs):
    logger, lines = captured_logs
    logger.info("worker started")

    assert lines()[0]["tenant_id"] is None


def test_extra_fields_are_merged_onto_the_line(captured_logs):
    logger, lines = captured_logs
    logger.info("sale created", extra={"sale_id": "S-1007", "amount_minor": 150000})

    line = lines()[0]
    assert line["sale_id"] == "S-1007"
    assert line["amount_minor"] == 150000


def test_redaction_covers_the_message_and_the_extras(captured_logs):
    """Central enforcement means a careless call site still cannot leak PII."""
    logger, lines = captured_logs
    logger.info("stk push to 254712345678", extra={"consumer_secret": "abc123"})

    line = lines()[0]
    assert "254712345678" not in line["msg"]
    assert line["consumer_secret"] == REDACTED


def test_exceptions_are_structured(captured_logs):
    logger, lines = captured_logs

    try:
        raise ValueError("callback amount mismatch")
    except ValueError:
        logger.exception("callback rejected")

    error = lines()[0]["error"]
    assert error["type"] == "ValueError"
    assert error["message"] == "callback amount mismatch"
    assert "ValueError" in error["stack"]


def test_each_record_is_exactly_one_line(captured_logs):
    """CloudWatch treats a newline as a record boundary."""
    logger, lines = captured_logs
    logger.info("first\nsecond")

    assert len(lines()) == 1
