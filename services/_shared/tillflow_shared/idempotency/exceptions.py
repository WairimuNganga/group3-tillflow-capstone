from tillflow_shared.idempotency.types import IdempotencyRecord


class IdempotencyError(Exception):
    """Base class for idempotency guard failures."""


class IdempotencyRequiredError(IdempotencyError):
    """A money-path request arrived without Idempotency-Key or X-Tenant-Id."""


class IdempotencyTenantMismatchError(IdempotencyError):
    """The same key was reused under a different tenant ([threat model M1])."""


class IdempotencyConflictError(IdempotencyError):
    """Another in-flight request holds this key; client should retry shortly."""


class IdempotencyReplay(Exception):
    """Raised to short-circuit a handler and return a stored response ([ADR-004])."""

    def __init__(self, record: IdempotencyRecord) -> None:
        self.record = record
        super().__init__("idempotent replay")
