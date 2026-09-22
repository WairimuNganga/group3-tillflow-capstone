"""PII redaction, applied centrally before anything leaves the process.

ADR-008 requires that a service cannot leak an attendant's phone number through a log
line or a span attribute. That guarantee is implemented here and enforced by the log
formatter and the span helpers, not by asking service authors to remember.
"""

from __future__ import annotations

import hashlib
import os
import re
from typing import Any

REDACTED = "[redacted]"

# Kenyan mobile MSISDNs as +254712345678, 254712345678 or 0712345678, on both the 07x
# and 01x prefixes. Bounded by non-digits so it cannot bite into a longer identifier.
_MSISDN_RE = re.compile(r"(?<!\d)(?:\+?254|0)(?:1|7)\d{8}(?!\d)")

_SENSITIVE_KEY_RE = re.compile(
    r"pass(word)?|secret|token|api[_-]?key|authorization|credential|consumer[_-]?(key|secret)",
    re.IGNORECASE,
)

# The Daraja STK callback path carries its own shared secret as the final path
# segment -- authenticity rests entirely on that segment being unguessable
# (ADR-007 / threat model TB5). uvicorn's access logger writes the *resolved*
# request line, so without this every callback published the secret to
# CloudWatch in plaintext, where anyone with log read access could lift it and
# forge a settlement. Observed 2026-09-21.
#
# Matches the segment only, so the route itself stays greppable.
_CALLBACK_SECRET_RE = re.compile(r"(/callbacks/mpesa/)[^/\s\"'?]+")

_SALT_ENV_VAR = "TILLFLOW_PII_HASH_SALT"


def _salt() -> bytes | None:
    salt = os.getenv(_SALT_ENV_VAR)
    return salt.encode("utf-8") if salt else None


def _normalise_msisdn(raw: str) -> str:
    """Reduce every accepted MSISDN form to one canonical form before hashing."""
    digits = re.sub(r"\D", "", raw)
    if digits.startswith("0"):
        digits = "254" + digits[1:]
    return digits


def hash_msisdn(value: str) -> str:
    """A stable, non-reversible reference to a phone number.

    Falls back to a plain redaction when no salt is configured: an unsalted hash of a
    12-digit number is trivially brute-forced, so an unset salt must fail closed.
    """
    salt = _salt()
    if salt is None:
        return REDACTED
    digest = hashlib.sha256(salt + _normalise_msisdn(value).encode("utf-8")).hexdigest()
    return f"msisdn:{digest[:12]}"


def redact_text(value: str) -> str:
    """Replace every MSISDN and callback-secret occurrence inside a string."""
    value = _MSISDN_RE.sub(lambda match: hash_msisdn(match.group(0)), value)
    return _CALLBACK_SECRET_RE.sub(rf"\g<1>{REDACTED}", value)


#: Kept as the name the M-Pesa adapter's docs already advertise.
redact_msisdn = hash_msisdn


def redact(value: Any) -> Any:
    """Recursively redact a log payload or span attribute set.

    Mappings are filtered by key as well as by value, because a field named
    ``consumer_secret`` is unsafe whatever it contains.
    """
    if isinstance(value, str):
        return redact_text(value)
    if isinstance(value, dict):
        return {
            key: REDACTED if _SENSITIVE_KEY_RE.search(str(key)) else redact(item)
            for key, item in value.items()
        }
    if isinstance(value, (list, tuple)):
        return [redact(item) for item in value]
    return value
