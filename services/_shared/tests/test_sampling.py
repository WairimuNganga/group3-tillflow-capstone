"""The sampling split from ADR-008, and the reasoning for the money-path exception."""

from opentelemetry.sdk.trace.sampling import ALWAYS_ON, ParentBased

from tillflow_shared.sampling import ratio_for_service, sampler_for_service


def test_money_path_services_are_fully_sampled():
    assert ratio_for_service("payments") == 1.0
    assert ratio_for_service("commission") == 1.0


def test_read_path_services_are_sampled_at_ten_percent():
    assert ratio_for_service("pos") == 0.1
    assert ratio_for_service("web") == 0.1


def test_money_path_ignores_the_parent_decision():
    """A sale starts in pos at 10%; deferring would leave 90% of payments untraced."""
    assert sampler_for_service("payments") is ALWAYS_ON


def test_read_path_respects_an_upstream_decision():
    assert isinstance(sampler_for_service("pos"), ParentBased)


def test_ratio_can_be_overridden_for_a_load_test(monkeypatch):
    monkeypatch.setenv("TILLFLOW_TRACE_SAMPLE_RATIO", "1.0")
    assert ratio_for_service("pos") == 1.0


def test_override_is_clamped_to_a_valid_probability(monkeypatch):
    monkeypatch.setenv("TILLFLOW_TRACE_SAMPLE_RATIO", "5")
    assert ratio_for_service("pos") == 1.0
