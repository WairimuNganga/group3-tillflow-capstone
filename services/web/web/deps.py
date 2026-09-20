from __future__ import annotations

from web.clients.commission import (
    CommissionClient,
    FakeCommissionClient,
    HttpCommissionClient,
)
from web.clients.pos import FakePosClient, HttpPosClient, PosClient
from web.config import settings

_fake_pos = FakePosClient()
_fake_commission = FakeCommissionClient()
_pos: PosClient | None = None
_commission: CommissionClient | None = None


def reset_runtime_state() -> None:
    global _pos, _fake_pos, _commission, _fake_commission
    _fake_pos = FakePosClient()
    _fake_commission = FakeCommissionClient()
    _pos = None
    _commission = None


def get_pos_client() -> PosClient:
    global _pos
    if _pos is None:
        _pos = HttpPosClient(settings.pos_base_url) if settings.pos_base_url else _fake_pos
    return _pos


def get_commission_client() -> CommissionClient:
    global _commission
    if _commission is None:
        _commission = (
            HttpCommissionClient(settings.commission_base_url)
            if settings.commission_base_url
            else _fake_commission
        )
    return _commission


def get_fake_pos() -> FakePosClient:
    return _fake_pos


def get_fake_commission() -> FakeCommissionClient:
    return _fake_commission
