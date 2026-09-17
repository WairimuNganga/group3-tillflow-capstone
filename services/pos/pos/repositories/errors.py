from __future__ import annotations


class RepositoryError(Exception):
    """Base class for storage-agnostic repository errors."""


class AlreadyExistsError(RepositoryError):
    """A uniqueness constraint would be violated (e.g. duplicate idempotency key)."""


class InvalidReferenceError(RepositoryError):
    """A referenced row does not exist for this tenant (composite FK violation)."""
