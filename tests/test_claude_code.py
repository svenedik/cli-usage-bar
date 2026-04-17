from __future__ import annotations

import shutil
from datetime import UTC, datetime, timedelta
from pathlib import Path

from cli_usage_bar.providers.claude_code import ClaudeCodeProvider

FIXTURE = Path(__file__).parent / "fixtures" / "claude_session.jsonl"


def _layout(tmp_path: Path) -> Path:
    projects = tmp_path / "projects"
    slug = projects / "-Users-test-demo"
    slug.mkdir(parents=True)
    dest = slug / "session-abc.jsonl"
    shutil.copy(FIXTURE, dest)
    return projects


def test_aggregates_tokens_in_current_block(tmp_path):
    projects = _layout(tmp_path)
    now = datetime(2026, 4, 17, 8, 30, tzinfo=UTC)
    p = ClaudeCodeProvider(
        projects_dir=projects,
        budget_tokens=10_000,
        now_fn=lambda: now,
    )
    snap = p.snapshot()

    assert snap.error is None
    # Totals: (100+1000+50) + (200+2000+150) + (50+500+300) = 4350 (cache_read excluded)
    assert snap.tokens_used == 4350
    assert snap.primary is not None
    assert snap.primary.used_percent == round(100.0 * 4350 / 10_000, 2)
    # Block starts at 07:00 → resets 12:00
    assert snap.primary.resets_at == datetime(2026, 4, 17, 12, 0, tzinfo=UTC)
    assert snap.cost_usd is not None
    assert snap.cost_usd > 0


def test_missing_directory(tmp_path):
    p = ClaudeCodeProvider(projects_dir=tmp_path / "nope")
    snap = p.snapshot()
    assert snap.error is not None


def test_no_recent_messages_returns_error(tmp_path):
    (tmp_path / "projects").mkdir()
    p = ClaudeCodeProvider(projects_dir=tmp_path / "projects")
    snap = p.snapshot()
    assert snap.error == "no recent usage messages"


def test_stale_block_is_excluded(tmp_path):
    projects = _layout(tmp_path)
    # Fast-forward 6 hours beyond the last message → block is closed, no current block
    now = datetime(2026, 4, 17, 15, 0, tzinfo=UTC)
    p = ClaudeCodeProvider(
        projects_dir=projects,
        budget_tokens=10_000,
        now_fn=lambda: now,
        lookback_hours=48,
    )
    snap = p.snapshot()
    # Weekly aggregate still has tokens, primary block is None because no active block
    assert snap.primary is None
    assert snap.secondary is not None
    assert snap.tokens_used == 0


def test_weekly_reset_anchors_to_now(tmp_path):
    """Local mode has no true window start — the 7d reset is monotonic w.r.t. now."""
    projects = _layout(tmp_path)
    now = datetime(2026, 4, 17, 8, 30, tzinfo=UTC)
    later = now + timedelta(minutes=1)

    first = ClaudeCodeProvider(projects_dir=projects, now_fn=lambda: now).snapshot()
    second = ClaudeCodeProvider(projects_dir=projects, now_fn=lambda: later).snapshot()

    assert first.secondary is not None
    assert second.secondary is not None
    assert first.secondary.resets_at == now + timedelta(days=7)
    assert second.secondary.resets_at == later + timedelta(days=7)
