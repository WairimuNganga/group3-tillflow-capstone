class MpesaError(Exception):
    """Base class for M-Pesa adapter errors."""


class MpesaTimeoutError(MpesaError):
    """Daraja did not respond within the configured HTTP timeout.

    Optional provider IDs are set when the push was accepted by Daraja (or the
    fake) before the transport timed out — enough for STK Query reconciliation.
    """

    def __init__(
        self,
        message: str = "Daraja request timed out",
        *,
        merchant_request_id: str | None = None,
        checkout_request_id: str | None = None,
    ) -> None:
        super().__init__(message)
        self.merchant_request_id = merchant_request_id
        self.checkout_request_id = checkout_request_id


class MpesaProviderError(MpesaError):
    """Daraja returned an error response."""


class MpesaAuthError(MpesaError):
    """OAuth token acquisition failed."""
