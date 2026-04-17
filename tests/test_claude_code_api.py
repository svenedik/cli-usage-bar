from __future__ import annotations

from datetime import UTC, datetime

from cli_usage_bar.providers.claude_code_api import ClaudeCodeApiProvider


def _fake_payload() -> dict:
    return {
        "five_hour": {
            "utilization": 70.0,
            "resets_at": "2026-04-17T10:00:00Z",
        },
        "seven_day": {
            "utilization": 6.5,
            "resets_at": "2026-04-22T10:00:00Z",
        },
    }


def test_snapshot_parses_oauth_payload() -> None:
    fixed_now = datetime(2026, 4, 17, 8, 0, tzinfo=UTC)
    provider = ClaudeCodeApiProvider(
        plan_display="Max (5x)",
        fetch_fn=lambda: _fake_payload(),
        now_fn=lambda: fixed_now,
    )
    snap = provider.snapshot()
    assert snap.error is None
    assert snap.plan_type == "Max (5x)"
    assert snap.primary is not None
    assert snap.primary.used_percent == 70.0
    assert snap.primary.window_minutes == 300
    assert snap.secondary is not None
    assert snap.secondary.used_percent == 6.5
    assert snap.secondary.window_minutes == 7 * 24 * 60


def test_snapshot_reports_error_when_fetch_returns_none() -> None:
    provider = ClaudeCodeApiProvider(fetch_fn=lambda: None)
    snap = provider.snapshot()
    assert snap.error is not None
    assert "api" in snap.error
    assert snap.primary is None
    assert snap.secondary is None


def test_snapshot_uses_cache_within_window() -> None:
    calls = {"n": 0}

    def fetch():
        calls["n"] += 1
        return _fake_payload()

    provider = ClaudeCodeApiProvider(fetch_fn=fetch, cache_seconds=300)
    provider.snapshot()
    provider.snapshot()
    assert calls["n"] == 1


def test_partial_payload_yields_partial_snapshot() -> None:
    provider = ClaudeCodeApiProvider(
        fetch_fn=lambda: {"five_hour": {"utilization": 10.0, "resets_at": "2026-04-17T10:00:00Z"}},
    )
    snap = provider.snapshot()
    assert snap.error is None
    assert snap.primary is not None
    assert snap.secondary is None
