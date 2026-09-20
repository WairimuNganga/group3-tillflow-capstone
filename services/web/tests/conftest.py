import os

os.environ.setdefault("TILLFLOW_TELEMETRY_EXPORT", "none")

import pytest

from web.deps import reset_runtime_state


@pytest.fixture(autouse=True)
def _reset():
    reset_runtime_state()
    yield
    reset_runtime_state()
