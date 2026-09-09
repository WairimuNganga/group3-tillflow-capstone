from tillflow_shared.mpesa.adapter import MpesaAdapter
from tillflow_shared.mpesa.daraja_sandbox import DarajaSandboxAdapter
from tillflow_shared.mpesa.fake import FakeMpesaAdapter
from tillflow_shared.mpesa.settings import MpesaSettings


def create_mpesa_adapter(settings: MpesaSettings | None = None) -> MpesaAdapter:
    """Build the configured M-Pesa adapter ([ADR-007]).

    CI and k6 must set ``MPESA_ADAPTER=fake``. Deployed environments use ``sandbox``.
    """
    resolved = settings or MpesaSettings()
    if resolved.adapter == "fake":
        return FakeMpesaAdapter(resolved)
    if resolved.adapter == "sandbox":
        return DarajaSandboxAdapter(resolved)
    raise ValueError(f"unknown MPESA_ADAPTER: {resolved.adapter}")
