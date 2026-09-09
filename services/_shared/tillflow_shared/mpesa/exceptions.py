class MpesaError(Exception):
    """Base class for M-Pesa adapter errors."""


class MpesaTimeoutError(MpesaError):
    """Daraja did not respond within the configured HTTP timeout."""


class MpesaProviderError(MpesaError):
    """Daraja returned an error response."""


class MpesaAuthError(MpesaError):
    """OAuth token acquisition failed."""
