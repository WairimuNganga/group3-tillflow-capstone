"""Verifies the ADR-008 promise that a service cannot leak an MSISDN."""

import pytest

from tillflow_shared.otel.pii import REDACTED, hash_msisdn, redact, redact_text


@pytest.mark.parametrize(
    "raw",
    [
        "+254712345678",
        "254712345678",
        "0712345678",
        "+254112345678",
        "0112345678",
    ],
)
def test_every_accepted_msisdn_form_is_removed(raw):
    result = redact_text(f"stk push to {raw} accepted")
    assert raw not in result
    assert "msisdn:" in result


def test_same_subscriber_hashes_identically_across_formats():
    """An operator following one subscriber needs a stable reference across forms."""
    assert hash_msisdn("0712345678") == hash_msisdn("+254712345678") == hash_msisdn("254712345678")


def test_different_subscribers_hash_differently():
    assert hash_msisdn("0712345678") != hash_msisdn("0712345679")


def test_missing_salt_fails_closed(monkeypatch):
    """An unsalted hash of a 12-digit number is brute-forceable, so drop the value."""
    monkeypatch.delenv("TILLFLOW_PII_HASH_SALT", raising=False)
    assert hash_msisdn("0712345678") == REDACTED


def test_sensitive_keys_are_dropped_whatever_the_value():
    payload = {
        "consumer_secret": "abc123",
        "Authorization": "Bearer token",
        "password": "hunter2",
        "sale_id": "S-1007",
    }
    result = redact(payload)
    assert result["consumer_secret"] == REDACTED
    assert result["Authorization"] == REDACTED
    assert result["password"] == REDACTED
    assert result["sale_id"] == "S-1007"


def test_identifiers_and_amounts_survive_untouched():
    """Over-redaction is its own failure: a mangled trace id makes a log line useless."""
    payload = {
        "trace_id": "4bf92f3577b34da6a3ce929d0e0e4736",
        "amount_minor": 150000,
        "checkout_request_id": "ws_CO_09092026210000123456",
    }
    assert redact(payload) == payload


def test_nested_structures_are_walked():
    payload = {"callback": {"items": [{"msisdn": "254712345678"}]}}
    result = redact(payload)
    assert "254712345678" not in str(result)


# --- Daraja callback secret --------------------------------------------------
#
# Callback authenticity is the unguessable path segment (ADR-007 / TB5), so the
# resolved path is a credential. uvicorn's access logger writes the request line
# verbatim; before this redaction every callback published the secret to
# CloudWatch, where it could be lifted and replayed to forge a settlement.


def test_callback_secret_is_stripped_from_access_log_line():
    line = '10.20.76.91:0 - "POST /callbacks/mpesa/tillflow-sandbox HTTP/1.1" 200'
    result = redact_text(line)

    assert "tillflow-sandbox" not in result
    # The route stays greppable -- redaction must not destroy the log's value.
    assert "/callbacks/mpesa/" in result
    assert REDACTED in result
    assert result.endswith('HTTP/1.1" 200')


def test_callback_secret_redacted_in_full_url():
    url = "https://k8ve9ik8zl.execute-api.us-west-1.amazonaws.com/v1/callbacks/mpesa/s3cr3t-value"
    result = redact_text(url)

    assert "s3cr3t-value" not in result
    assert result.endswith(f"/callbacks/mpesa/{REDACTED}")


def test_callback_secret_redacted_through_nested_payload():
    payload = {"http": {"request": {"url": "http://p:8080/callbacks/mpesa/abc123"}}}
    result = redact(payload)

    assert "abc123" not in str(result)


def test_callback_redaction_stops_at_the_segment_boundary():
    """A trailing path or query must survive, or the log stops being diagnostic."""
    assert redact_text("/callbacks/mpesa/sekret?retry=1").endswith("?retry=1")
    assert "/extra" in redact_text("/callbacks/mpesa/sekret/extra")


def test_unrelated_callback_paths_are_untouched():
    """Only the M-Pesa callback carries a secret segment; do not over-redact."""
    assert redact_text("/callbacks/other/plain") == "/callbacks/other/plain"
    assert redact_text("/internal/sales/2c1cbb8b/payment-result") == (
        "/internal/sales/2c1cbb8b/payment-result"
    )
