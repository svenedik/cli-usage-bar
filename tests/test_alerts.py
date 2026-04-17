from __future__ import annotations

from datetime import UTC, datetime, timedelta

from cli_usage_bar.alerts import ProviderAlertState, next_provider_alert
from cli_usage_bar.models import RateLimit, UsageSnapshot


def _rate_limit(percent: float, *, hours: int) -> RateLimit:
    now = datetime(2026, 4, 17, 12, 0, tzinfo=UTC)
    return RateLimit(
        used_percent=percent,
        window_minutes=hours * 60,
        resets_at=now + timedelta(hours=hours),
    )


def test_provider_alerts_fire_at_90_then_95_and_stop() -> None:
    state = ProviderAlertState()

    state, decision = next_provider_alert(
        UsageSnapshot(provider="claude_code", primary=_rate_limit(91, hours=5)),
        state,
        enabled=True,
    )
    assert decision is not None
    assert decision.level == 90

    state, decision = next_provider_alert(
        UsageSnapshot(provider="claude_code", primary=_rate_limit(94, hours=5)),
        state,
        enabled=True,
    )
    assert decision is None

    state, decision = next_provider_alert(
        UsageSnapshot(provider="claude_code", primary=_rate_limit(96, hours=5)),
        state,
        enabled=True,
    )
    assert decision is not None
    assert decision.level == 95

    state, decision = next_provider_alert(
        UsageSnapshot(provider="claude_code", primary=_rate_limit(99, hours=5)),
        state,
        enabled=True,
    )
    assert decision is None


def test_provider_alerts_rearm_after_usage_drops_below_90() -> None:
    state = ProviderAlertState(last_level=95)

    state, decision = next_provider_alert(
        UsageSnapshot(provider="codex_cli", primary=_rate_limit(72, hours=5)),
        state,
        enabled=True,
    )
    assert decision is None
    assert state.last_level == 0

    state, decision = next_provider_alert(
        UsageSnapshot(provider="codex_cli", secondary=_rate_limit(92, hours=24 * 7)),
        state,
        enabled=True,
    )
    assert decision is not None
    assert decision.kind == "weekly"
    assert decision.level == 90
