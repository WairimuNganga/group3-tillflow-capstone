from tillflow_shared.mpesa.daraja_sandbox import DarajaSandboxAdapter
from tillflow_shared.mpesa.factory import create_mpesa_adapter
from tillflow_shared.mpesa.fake import FakeMpesaAdapter
from tillflow_shared.mpesa.settings import MpesaSettings


def test_factory_returns_fake_adapter() -> None:
    adapter = create_mpesa_adapter(MpesaSettings(MPESA_ADAPTER="fake"))
    assert isinstance(adapter, FakeMpesaAdapter)


def test_factory_returns_sandbox_adapter() -> None:
    adapter = create_mpesa_adapter(MpesaSettings(MPESA_ADAPTER="sandbox"))
    assert isinstance(adapter, DarajaSandboxAdapter)
