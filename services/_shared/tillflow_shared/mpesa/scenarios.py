from enum import Enum


class FakeScenario(str, Enum):
    """Deterministic fake-adapter behaviours for CI, k6, and G4 drills."""

    IMMEDIATE_SUCCESS = "immediate_success"
    IMMEDIATE_FAILURE = "immediate_failure"
    DELAYED_TIMEOUT = "delayed_timeout"
    DUPLICATE_CALLBACK = "duplicate_callback"
    OUT_OF_ORDER_CALLBACK = "out_of_order_callback"
