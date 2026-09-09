def redact_msisdn(msisdn: str) -> str:
    """Mask a phone number before it reaches logs or span attributes ([ADR-008])."""
    digits = "".join(ch for ch in msisdn if ch.isdigit())
    if len(digits) < 4:
        return "***"
    return f"{digits[:4]}*****{digits[-3:]}"
