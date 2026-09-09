import pytest

from tillflow_shared.mpesa.fake import FakeMpesaAdapter
from tillflow_shared.mpesa.settings import MpesaSettings
from tillflow_shared.mpesa.types import StkPushRequest


@pytest.fixture
def fake_settings() -> MpesaSettings:
    return MpesaSettings(
        MPESA_ADAPTER="fake",
        MPESA_HTTP_READ_TIMEOUT=0.05,
    )


@pytest.fixture
def fake_adapter(fake_settings: MpesaSettings) -> FakeMpesaAdapter:
    return FakeMpesaAdapter(fake_settings)


@pytest.fixture
def sample_stk_request() -> StkPushRequest:
    return StkPushRequest(
        tenant_id="tenant-1",
        idempotency_key="sale-key-1",
        phone_number="254712345678",
        amount_whole_kes=10,
        account_reference="sale-key-1",
    )
