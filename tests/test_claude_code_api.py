from __future__ import annotations

import hashlib
import subprocess
from datetime import UTC, datetime
from pathlib import Path
from unicodedata import normalize

from cli_usage_bar.providers.claude_code_api import (
    ClaudeAuthStatus,
    ClaudeCodeApiProvider,
    _keychain_service_candidates,
    _read_auth_status,
    _read_oauth_token,
)


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


def test_rate_limit_backoff_skips_calls_after_429() -> None:
    calls = {"n": 0}

    def fetch():
        calls["n"] += 1
        return None

    provider = ClaudeCodeApiProvider(fetch_fn=fetch, cache_seconds=0)
    provider._last_status = 429
    provider.snapshot()
    first_calls = calls["n"]
    # Subsequent snapshots within the backoff window must not hit the endpoint.
    provider.snapshot()
    provider.snapshot()
    assert calls["n"] == first_calls


def test_snapshot_prompts_for_claude_login_when_logged_out() -> None:
    provider = ClaudeCodeApiProvider(
        token_fn=lambda: None,
        auth_status_fn=lambda: ClaudeAuthStatus(logged_in=False, auth_method="none"),
    )
    snap = provider.snapshot()
    assert snap.error == "api: Claude login required (run `claude auth login --claudeai`)"


def test_snapshot_reports_token_lookup_issue_when_login_exists() -> None:
    provider = ClaudeCodeApiProvider(
        token_fn=lambda: None,
        auth_status_fn=lambda: ClaudeAuthStatus(logged_in=True, auth_method="claudeai"),
    )
    snap = provider.snapshot()
    assert snap.error == "api: OAuth token unreadable (re-login to Claude Code)"


def test_read_auth_status_parses_logged_out_json_even_on_exit_1(monkeypatch) -> None:
    def fake_run(*args, **kwargs):
        return subprocess.CompletedProcess(
            args[0],
            1,
            '{"loggedIn": false, "authMethod": "none", "apiProvider": "firstParty"}\n',
            "",
        )

    monkeypatch.setattr("cli_usage_bar.providers.claude_code_api._claude_command", lambda: "claude")
    monkeypatch.setattr("cli_usage_bar.providers.claude_code_api.subprocess.run", fake_run)
    status = _read_auth_status()
    assert status == ClaudeAuthStatus(
        logged_in=False,
        auth_method="none",
        api_provider="firstParty",
    )


def test_read_oauth_token_prefers_env(monkeypatch) -> None:
    monkeypatch.setenv("CLAUDE_CODE_OAUTH_TOKEN", "token-from-env")

    def unexpected_run(*args, **kwargs):
        raise AssertionError("security lookup should not run when env token is present")

    monkeypatch.setattr("cli_usage_bar.providers.claude_code_api.subprocess.run", unexpected_run)
    assert _read_oauth_token() == "token-from-env"


def test_keychain_service_candidates_include_config_hash(monkeypatch) -> None:
    config_dir = "~/Library/Application Support/Claude Test"
    normalized = normalize("NFC", str(Path(config_dir).expanduser()))
    expected_hash = hashlib.sha256(normalized.encode("utf-8")).hexdigest()[:8]

    monkeypatch.setenv("CLAUDE_CONFIG_DIR", config_dir)
    candidates = _keychain_service_candidates()

    assert f"Claude Code-credentials-{expected_hash}" in candidates
    assert "Claude Code-credentials" in candidates
