"""Verifies the ADR-008 promise that a service cannot leak an MSISDN."""

import pytest

from tillflow_shared.redaction import REDACTED, hash_msisdn, redact, redact_text


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
