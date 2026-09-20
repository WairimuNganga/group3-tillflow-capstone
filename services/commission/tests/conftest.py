import os

# Unit tests use in-memory stores — do not pick up a local DATABASE_URL.
os.environ["DATABASE_URL"] = ""
os.environ["DB_CREDENTIALS"] = ""
os.environ.setdefault("COMMISSION_WORKER_ENABLED", "false")
os.environ.setdefault("TILLFLOW_TELEMETRY_EXPORT", "none")

import pytest

from commission.deps import reset_runtime_state


@pytest.fixture(autouse=True)
def _reset_state():
    reset_runtime_state()
    yield
    reset_runtime_state()
