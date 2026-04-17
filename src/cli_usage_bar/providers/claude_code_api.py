"""Claude Code usage provider — OAuth API source.

Uses the same endpoint the Claude.ai dashboard calls internally, so the
returned percentages are dashboard-accurate and never need calibration.

Flow:
- Reuse the Claude Code OAuth access token from either
  ``CLAUDE_CODE_OAUTH_TOKEN`` or Claude Code's own macOS keychain entry.
  We do not create, rotate, or persist credentials ourselves.
- GET https://api.anthropic.com/api/oauth/usage with
  ``anthropic-beta: oauth-2025-04-20``.
- Expected response shape (both fields optional):
  {
    "five_hour":  {"utilization": <float 0..100>, "resets_at": <iso-8601>},
    "seven_day":  {"utilization": <float 0..100>, "resets_at": <iso-8601>}
  }

The endpoint is undocumented/beta; if it ever moves or changes shape we
return an ``UsageSnapshot`` with ``error`` set so the menu degrades
gracefully. Consider switching back to ``source = "local"`` if that
happens.
"""

from __future__ import annotations

import json
import logging
import os
import shutil
import subprocess
import time
import urllib.error
import urllib.request
from collections.abc import Callable
from dataclasses import dataclass
from datetime import UTC, datetime
from hashlib import sha256
from pathlib import Path
from typing import Any
from unicodedata import normalize

from cli_usage_bar.models import RateLimit, UsageSnapshot
from cli_usage_bar.providers.base import Provider

logger = logging.getLogger(__name__)

USAGE_ENDPOINT = "https://api.anthropic.com/api/oauth/usage"
KEYCHAIN_SERVICE = "Claude Code-credentials"
BETA_HEADER = "oauth-2025-04-20"
OAUTH_TOKEN_ENV = "CLAUDE_CODE_OAUTH_TOKEN"
KNOWN_OAUTH_SUFFIXES = ("", "-custom-oauth", "-local-oauth", "-staging-oauth")

FIVE_HOUR_MINUTES = 5 * 60
SEVEN_DAY_MINUTES = 7 * 24 * 60


@dataclass(frozen=True)
class ClaudeAuthStatus:
    logged_in: bool
    auth_method: str | None = None
    api_provider: str | None = None


class ClaudeCodeApiProvider(Provider):
    name = "claude_code"

    def __init__(
        self,
        plan_display: str | None = None,
        cache_seconds: int = 60,
        now_fn: Callable[[], datetime] = lambda: datetime.now(tz=UTC),
        fetch_fn: Callable[[], dict[str, Any] | None] | None = None,
        token_fn: Callable[[], str | None] | None = None,
        auth_status_fn: Callable[[], ClaudeAuthStatus | None] | None = None,
    ) -> None:
        self.plan_display = plan_display
        self.cache_seconds = max(0, cache_seconds)
        self._now = now_fn
        self._fetch_fn = fetch_fn
        self._token_fn = token_fn
        self._auth_status_fn = auth_status_fn
        self._cached: dict[str, Any] | None = None
        self._cached_at: float = 0.0
        # Last HTTP status from _fetch_live (None = no request made, 0 = transport error)
        self._last_status: int | None = None
        self._last_attempt: float = 0.0
        self._last_auth_status: ClaudeAuthStatus | None = None

    def watch_paths(self) -> list[str]:
        # Nothing to watch on disk — the app's refresh timer polls the API.
        return []

    def snapshot(self) -> UsageSnapshot:
        data = self._fetch()
        if data is None:
            return UsageSnapshot(
                provider=self.name,
                plan_type=self.plan_display,
                error=self._error_message(),
            )
        try:
            primary = _parse_block(data.get("five_hour"), FIVE_HOUR_MINUTES)
            secondary = _parse_block(data.get("seven_day"), SEVEN_DAY_MINUTES)
        except Exception as exc:
            logger.exception("failed to parse oauth usage response")
            return UsageSnapshot(
                provider=self.name,
                plan_type=self.plan_display,
                error=f"api: parse error: {exc}",
            )
        return UsageSnapshot(
            provider=self.name,
            primary=primary,
            secondary=secondary,
            plan_type=self.plan_display,
            last_activity=self._now(),
        )

    # Negative-cache window after a 429: hammering the endpoint keeps
    # resetting Anthropic's cooldown, so we stop retrying for RATE_LIMIT_BACKOFF
    # seconds after seeing a 429 and surface the cached error in the meantime.
    RATE_LIMIT_BACKOFF = 300

    def _fetch(self) -> dict[str, Any] | None:
        now = time.time()
        if self._cached is not None and now - self._cached_at < self.cache_seconds:
            return self._cached
        if self._last_status == 429 and now - self._last_attempt < self.RATE_LIMIT_BACKOFF:
            return None
        data = (self._fetch_fn or self._fetch_live)()
        self._last_attempt = now
        if data is not None:
            self._cached = data
            self._cached_at = now
        return data

    def _fetch_live(self) -> dict[str, Any] | None:
        self._last_auth_status = (self._auth_status_fn or _read_auth_status)()
        token = (self._token_fn or _read_oauth_token)()
        if not token:
            self._last_status = None
            return None
        req = urllib.request.Request(  # noqa: S310 — fixed https URL, not user input
            USAGE_ENDPOINT,
            headers={
                "Authorization": f"Bearer {token}",
                "anthropic-beta": BETA_HEADER,
                "Content-Type": "application/json",
            },
        )
        try:
            with urllib.request.urlopen(req, timeout=5) as resp:  # noqa: S310
                body = resp.read()
                self._last_status = resp.status
        except urllib.error.HTTPError as exc:
            self._last_status = exc.code
            logger.warning("oauth usage HTTP %s", exc.code)
            return None
        except (urllib.error.URLError, TimeoutError) as exc:
            self._last_status = 0
            logger.warning("oauth usage request failed: %s", exc)
            return None
        try:
            parsed = json.loads(body)
        except json.JSONDecodeError:
            logger.warning("oauth usage response not JSON")
            return None
        if not isinstance(parsed, dict):
            return None
        return parsed

    def _error_message(self) -> str:
        if self._last_status in (401, 403):
            return "api: auth failed (run `claude auth login --claudeai`)"
        if self._last_status == 429:
            return "api: rate limited (try again shortly)"
        if self._last_status and self._last_status >= 500:
            return f"api: server error ({self._last_status})"
        if self._last_auth_status and not self._last_auth_status.logged_in:
            return "api: Claude login required (run `claude auth login --claudeai`)"
        if self._last_auth_status and self._last_auth_status.logged_in:
            return "api: OAuth token unreadable (re-login to Claude Code)"
        return "api: no usage data (missing token or network)"


def _read_oauth_token() -> str | None:
    """Fetch the Claude Code OAuth access token from env or the login keychain."""
    env_token = os.environ.get(OAUTH_TOKEN_ENV, "").strip()
    if env_token:
        return env_token

    for service_name in _keychain_service_candidates():
        token = _read_keychain_token(service_name)
        if token:
            return token
    return None


def _read_auth_status() -> ClaudeAuthStatus | None:
    claude_cmd = _claude_command()
    if not claude_cmd:
        return None
    try:
        out = subprocess.run(
            [claude_cmd, "auth", "status", "--json"],
            capture_output=True,
            text=True,
            check=False,
            timeout=3,
        )
    except Exception:
        return None

    raw = out.stdout.strip()
    if not raw:
        return None
    try:
        payload = json.loads(raw)
    except json.JSONDecodeError:
        return None
    if not isinstance(payload, dict):
        return None

    return ClaudeAuthStatus(
        logged_in=bool(payload.get("loggedIn")),
        auth_method=_coerce_str(payload.get("authMethod")),
        api_provider=_coerce_str(payload.get("apiProvider")),
    )


def _keychain_service_candidates() -> list[str]:
    config_hash = _config_dir_hash()
    ordered_suffixes = [_current_oauth_suffix(), *KNOWN_OAUTH_SUFFIXES]
    seen: set[str] = set()
    candidates: list[str] = []

    for suffix in ordered_suffixes:
        base = f"Claude Code{suffix}-credentials"
        for service_name in (
            f"{base}-{config_hash}" if config_hash else None,
            base,
        ):
            if service_name and service_name not in seen:
                seen.add(service_name)
                candidates.append(service_name)

    if KEYCHAIN_SERVICE not in seen:
        candidates.append(KEYCHAIN_SERVICE)
    return candidates


def _current_oauth_suffix() -> str:
    if os.environ.get("CLAUDE_CODE_CUSTOM_OAUTH_URL"):
        return "-custom-oauth"
    return ""


def _config_dir_hash() -> str | None:
    config_dir = os.environ.get("CLAUDE_CONFIG_DIR")
    if not config_dir:
        return None
    normalized = normalize("NFC", str(Path(config_dir).expanduser()))
    return sha256(normalized.encode("utf-8")).hexdigest()[:8]


def _read_keychain_token(service_name: str) -> str | None:
    try:
        out = subprocess.run(
            ["security", "find-generic-password", "-s", service_name, "-w"],
            capture_output=True,
            text=True,
            check=False,
            timeout=3,
        )
    except Exception:
        return None
    if out.returncode != 0 or not out.stdout.strip():
        return None
    try:
        blob = json.loads(out.stdout.strip())
    except json.JSONDecodeError:
        logger.warning("keychain entry %s did not contain JSON OAuth data", service_name)
        return None
    if not isinstance(blob, dict):
        return None
    inner = blob.get("claudeAiOauth")
    if isinstance(inner, dict) and inner.get("accessToken"):
        return str(inner["accessToken"])
    if blob.get("accessToken"):
        return str(blob["accessToken"])
    return None


def _claude_command() -> str | None:
    cli_path = shutil.which("claude")
    if cli_path:
        return cli_path

    fallback = Path.home() / ".local" / "bin" / "claude"
    if fallback.exists():
        return str(fallback)
    return None


def _coerce_str(value: object) -> str | None:
    if isinstance(value, str) and value:
        return value
    return None


def _parse_block(block: Any, window_minutes: int) -> RateLimit | None:
    if not isinstance(block, dict):
        return None
    if "utilization" not in block or "resets_at" not in block:
        return None
    pct = float(block["utilization"])
    resets_at = _parse_iso(str(block["resets_at"]))
    if resets_at is None:
        return None
    return RateLimit(
        used_percent=max(0.0, min(100.0, pct)),
        window_minutes=window_minutes,
        resets_at=resets_at,
    )


def _parse_iso(ts: str) -> datetime | None:
    try:
        dt = datetime.fromisoformat(ts.replace("Z", "+00:00"))
    except ValueError:
        return None
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=UTC)
    return dt
